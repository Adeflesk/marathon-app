"""The view: every page's weeks, built from the stored facts.

`load_facts()` is the only place here that reads storage (SQLite, settings.json, equipment.json). Everything
else is pure: `build_view(facts, today)` turns one snapshot of the facts into the settings and weeks the pages
render, as a pipeline of steps. The plan itself is never stored, so changing the settings or the generator
reshapes everything.
"""
import copy
from dataclasses import dataclass
from datetime import date, timedelta
from math import gcd

from . import ankle, db, fuel, garmin_api, moves, progress, progression, review, strength
from .config import load_settings, race_date
from .pace_engine import MP_GAP, from_result, parse_time
from .plan import DAYS, _half, feedback_factor, generate, volume_caps
from .sessions import scale_session

GOAL_SETTINGS = "settings"  # a stored goal meaning "back to whatever settings.json says"
SESSIONS = {"run", "A", "B"}  # what a move can apply to: a run, or strength session A or B


@dataclass(frozen=True)
class Facts:
    """Everything the user has told the app or synced into it, read once per request."""
    settings: dict
    actual: dict[str, dict]  # by ISO date: {"km", "seconds", "hr", "main"} (see db.actual_by_date)
    details: dict[int, dict]  # splits and laps of each day's main run, by activity id
    checkins: dict[int, dict]  # by week number
    moves: list[dict]
    goals: list[dict]
    results: list[dict]
    logs: list[dict]  # strength logs, newest first
    checks: list[dict]  # morning ankle checks
    tests: list[dict]  # ankle readiness tests
    snacks: list[dict]
    fuel_days: set[str]
    last_sync: str | None
    wellness: list[dict]  # daily HRV, resting HR, sleep, stress, weight; oldest first, values may be None
    equipment: dict


def load_facts() -> Facts:
    actual = db.actual_by_date()
    return Facts(
        settings=load_settings(),
        actual=actual,
        details=db.run_details([a["main"]["id"] for a in actual.values()]),
        checkins=db.checkins(),
        moves=db.moves(),
        goals=db.goals(),
        results=db.results(),
        logs=db.logs(),
        checks=db.checks(),
        tests=db.tests(),
        snacks=db.snacks(),
        fuel_days=db.fuel_days(),
        last_sync=db.get_meta("last_sync"),
        wellness=db.wellness(),
        equipment=strength.load_equipment(),
    )


# --- the pipeline ---

def build_view(f: Facts, t: date) -> tuple[dict, list[dict]]:
    """The settings (with the goal and latest result applied) and every week of the plan, as of day `t`."""
    s = copy.deepcopy(f.settings)  # the steps below change the settings; the facts stay as read
    apply_goal(s, t, f.goals)
    apply_result(s, t, f.results)
    weeks = generate(s, t)
    st = ankle_state(t, weeks, f)
    moved = moves.index(f.moves)
    scale_and_shift_runs(weeks, s, f, t, moved)
    join_actuals(weeks, s, f, t, st, moved)
    mark_done_and_movable(weeks, s, f, t)
    return s, weeks


def apply_goal(s: dict, t: date, goals: list[dict]) -> None:
    """The goal the user last picked (on or before `t`) overrides the settings' goal and its pace.

    Picking the settings' goal again restores the settings' paces exactly. Also sets s["settings_goal"]
    and s["goal_changes"] ([{"date", "from", "to"}], oldest first) for the progress page.
    """
    s["settings_goal"] = current = s["goal_time"]
    s["goal_changes"] = []
    for g in goals:
        goal = s["settings_goal"] if g["goal_time"] == GOAL_SETTINGS else g["goal_time"]
        if g["date"] <= t.isoformat() and goal != current:
            s["goal_changes"].append({"date": g["date"], "from": current, "to": goal})
            current = goal
    if current != s["settings_goal"]:
        s["goal_time"] = current
        # as in pace_engine.from_result: MP stays MP_GAP slower than threshold, sub-threshold never quicker than it
        tempo = s["paces"]["tempo"]
        s["paces"]["marathon"] = max(round(parse_time(current) / 42.195), tempo + MP_GAP)
        s["paces"]["subthreshold"] = max(s["paces"]["marathon"] - 9, tempo)


def apply_result(s: dict, t: date, results: list[dict]) -> None:
    """The latest race or time trial on or before `t` sets the paces, with a read of the goal."""
    latest = next((r for r in reversed(results) if r["date"] <= t.isoformat()), None)
    if latest:
        read = from_result(s["paces"], parse_time(s["goal_time"]), latest["km"], latest["seconds"])
        s["paces"] = read["paces"]
        s["result"] = {**latest, **read}


def volume_guard(weeks: list[dict], actual: dict, checkins: dict, t: date, base: float,
                 last_sync: str | None) -> tuple[dict[int, dict], set[int]]:
    """plan.volume_caps from the stored facts, and the weeks a sync has covered (the only ones it counts)."""
    synced = date.fromisoformat(last_sync[:10]) if last_sync else None
    run = {w["week"]: 0.0 for w in weeks}
    starts = {w["start"]: w["week"] for w in weeks}
    for d, a in actual.items():
        day = date.fromisoformat(d)
        monday = day - timedelta(days=day.weekday())
        if monday in starts:
            run[starts[monday]] += a["km"]
    # A week counts once it's over and a sync ran on or after its Sunday (usually after the long run; a sync
    # before it makes the week look short until the next sync puts it right).
    known = {w["week"] for w in weeks
             if synced and w["start"] + timedelta(days=6) < t and w["start"] + timedelta(days=6) <= synced}
    planned = [{"week": w["week"], "phase": w["phase"],
                "km": w["target_km"] * feedback_factor(checkins.get(w["week"] - 1))} for w in weeks]
    return volume_caps(planned, run, known, base), known


def scale_and_shift_runs(weeks: list[dict], s: dict, f: Facts, t: date, moved: dict) -> None:
    """Scale each week's runs by the smaller of last week's check-in and the missed-week guard, add the fuel
    notes, then apply moves (relocate takes a run across Sunday). Strength follows the check-in only."""
    caps, synced = volume_guard(weeks, f.actual, f.checkins, t, s["base_weekly_km"], f.last_sync)
    for w in weeks:
        factor = feedback_factor(f.checkins.get(w["week"] - 1))
        w["factor"] = factor
        w["checkin"] = f.checkins.get(w["week"])
        w["synced"] = w["week"] in synced  # over, and a sync has covered it
        cap = caps.get(w["week"])
        run_factor = factor
        w["guard"] = None
        if cap and w["target_km"] and cap["km"] / w["target_km"] < factor:
            run_factor = cap["km"] / w["target_km"]
            w["guard"] = {**cap, "planned": w["target_km"]}
        for wo in w["workouts"]:
            if run_factor != 1.0 and wo["type"] != "race":
                if "steps" in wo:  # fewer reps, so the day, the note and the .fit all agree
                    scale_session(wo, run_factor, s["paces"])
                else:
                    wo["km"] = _half(wo["km"] * run_factor)
            # fuel practice on long runs of 90 minutes or more, from the km left after any trim
            wo["fuel"] = fuel.long_run_note(wo["km"], wo.get("mp_km", 0), s["paces"]["long"]) \
                if wo["type"] == "long" else None
            wo["gels"] = len(fuel.gel_minutes(wo["km"] * s["paces"]["long"] / 60)) if wo["fuel"] else 0
            moves.shift(wo, "run", moved)
    moves.relocate(weeks)


def join_actuals(weeks: list[dict], s: dict, f: Facts, t: date, st: dict, moved: dict) -> None:
    """Synced runs and their reviews on the planned days, week totals, and the strength sessions."""
    # A day with two runs (after a move) is one day: both show its actual, the longer one gets the review.
    planned: dict[date, float] = {}
    lead: dict[date, dict] = {}
    seen: dict[date, int] = {}
    for wo in (wo for w in weeks for wo in w["workouts"] if not wo.get("skipped")):
        wo["fit_n"] = seen.get(wo["date"], 0)  # its index for /workout/{day}.fit?n=
        seen[wo["date"]] = wo["fit_n"] + 1
        planned[wo["date"]] = planned.get(wo["date"], 0) + wo["km"]
        if wo["date"] not in lead or wo["km"] > lead[wo["date"]]["km"]:
            lead[wo["date"]] = wo
    for w in weeks:
        wk_actual = 0.0
        for wo in w["workouts"]:
            a = None if wo.get("skipped") else f.actual.get(wo["date"].isoformat())
            day_km = planned.get(wo["date"], 0)
            wo["actual_km"] = round(a["km"], 1) if a else None
            wo["actual_pace"] = (a["seconds"] / a["km"]) if a and a["km"] else None
            wo["compliance"] = round(100 * a["km"] / day_km) if a and day_km else None
            wo["past"] = wo["date"] < t
            detail = f.details.get(a["main"]["id"]) if a and lead.get(wo["date"]) is wo else None
            wo["review"] = review.review(wo, a["main"], detail, s["paces"]) if detail else None
        w["target_km"] = round(sum(wo["km"] for wo in w["workouts"] if not wo.get("skipped")), 1)
        for i in range(7):
            d = (w["start"] + timedelta(days=i)).isoformat()
            if d in f.actual:
                wk_actual += f.actual[d]["km"]
        w["actual_km"] = round(wk_actual, 1)
        attach_strength(w, s, f.equipment, st, t, moved, weeks)
        w["is_current"] = w["start"] <= t < w["start"] + timedelta(days=7)
        w["is_past"] = w["start"] + timedelta(days=7) <= t
    moves.relocate(weeks)  # strength sessions moved across Sunday, keeping their own week's prescription


def mark_done_and_movable(weeks: list[dict], s: dict, f: Facts, t: date) -> None:
    race = race_date(s)
    for w in weeks:
        for wo in w["workouts"]:
            wo["fuelled"] = bool(wo["fuel"]) and wo["date"].isoformat() in f.fuel_days
        for kind, item in [("run", wo) for wo in w["workouts"]] + [(x["key"], x) for x in w.get("strength", [])]:
            item["done"] = (item.get("actual_km") is not None if kind == "run"
                            else any(ex.get("log") for ex in item.get("exercises", [])))
            item["movable"] = _movable(item, weeks, t, race)
            item["movable_back"] = _movable(item, weeks, t, race, by=-1)


def _movable(item: dict, weeks: list[dict], t: date, race: date, by: int = 1) -> bool:
    """From today on, not skipped, not done yet (a synced run or any strength log), and the new day is allowed:
    tomorrow for `by` 1; for -1 the day before, which mustn't have passed."""
    if item["date"] < t or item.get("skipped") or item.get("type") == "race" or item["done"]:
        return False
    if item["date"] + timedelta(days=by) < t:
        return False
    return moves.can_move(item["date"], weeks, race, by)


# --- ankle and strength ---

def ankle_state(t: date, weeks: list[dict], f: Facts) -> dict:
    """Today's ankle and logging state, computed once per view from the facts."""
    logs, checks, tests, snacks = f.logs, f.checks, f.tests, f.snacks
    checkins = list(f.checkins.values())
    hop = ankle.hop_stage(t, tests, checks, logs, checkins, weeks)
    by_ex: dict[str, list[dict]] = {}
    for lg in logs:  # newest first, as db.logs() returns them
        by_ex.setdefault(lg["exercise"], []).append(lg)
    return {
        "logs": logs, "checks": checks, "tests": tests, "snacks": snacks, "checkins": checkins,
        "by_key": {(lg["date"], lg["exercise"]): lg for lg in logs},
        "by_ex": by_ex,
        "flag_until": ankle.flag_until(t, checks, logs, checkins, weeks),
        "hop_stage": hop,
        "balance_stage": ankle.balance_stage(t, snacks, tests, checks, hop, logs, checkins, weeks),
        "restart": ankle.restart(t, logs, checks),
        # before today, so logging the first lift doesn't cancel the time-off drop for the rest of the session
        "last_any_log": next((date.fromisoformat(lg["date"]) for lg in logs if lg["date"] < t.isoformat()), None),
    }


def weight_range(weights: list[float]) -> dict | None:
    """Min, max and an input step that lands on every available weight, or None for unloaded work."""
    if not weights:
        return None
    lo = weights[0]
    step = 0
    for w in weights[1:]:
        step = gcd(step, round((w - lo) * 100))
    return {"min": lo, "max": weights[-1], "step": step / 100 if step else "any"}


def attach_strength(w: dict, s: dict, eq: dict, st: dict, t: date, moved: dict | None = None,
                    weeks: list[dict] | None = None) -> None:
    """Strength sessions with suggestions and logs, and the ankle snacks, for one week."""
    end = w["start"] + timedelta(days=6)
    flag = st["flag_until"]

    def flagged(day: date) -> bool:
        """The flag is still up on `day`, in a week that isn't over."""
        return flag is not None and day <= flag and end >= t

    def on(key: str) -> date:
        """The day a strength session actually falls on, after any move."""
        planned = w["start"] + timedelta(days=DAYS.index(s["strength_days"][key]))
        return (moved or {}).get((planned, key)) or planned

    # A past session keeps the hop and balance stages it had on its day, so unlocking hops later doesn't
    # rewrite it; today's and future sessions use today's stages.
    a_day, b_day = on("A"), on("B")
    hop_a, hop_b = (st["hop_stage"] if d >= t else ankle.hop_stage(d, st["tests"], st["checks"], st["logs"],
                                                                     st["checkins"], weeks or [w])
                    for d in (a_day, b_day))
    balance = st["balance_stage"] if b_day >= t else ankle.balance_stage(
        b_day, st["snacks"], st["tests"], st["checks"], hop_b, st["logs"], st["checkins"], weeks or [w])
    q = next((wo for wo in w["workouts"] if "steps" in wo), None)
    wed_bad = bool(q and q.get("review") and q["review"]["verdict"] == "bad")
    ctx = {"factor": w["factor"], "wed_bad": wed_bad, "ankle_flag": flagged(a_day), "hop_stage": hop_a,
           "balance_stage": balance, "restart": st["restart"], "days": s["strength_days"]}
    w["strength"] = strength.sessions_for_week(w, eq, ctx)
    pctx = {"phase": w["phase"], "cutback": w["phase"] == "Cutback", "factor": w["factor"],
            "last_any_log": st["last_any_log"]}
    for sess in w["strength"]:
        moves.shift(sess, sess["key"], moved or {})
        sess["day"] = sess["date"].strftime("%a")
        day = sess["date"].isoformat()
        pctx["ankle_flag"] = flagged(sess["date"])
        for ex in sess["exercises"]:
            history = st["by_ex"].get(ex["key"], [])
            ex["suggestion"] = progression.suggest(ex, history, pctx, eq, today=t)
            ex["log"] = st["by_key"].get((day, ex["key"]))
            ex["last"] = next((lg for lg in history if lg["date"] < day), None)
            ex["weights"] = weight_range(progression.available_weights(ex, eq))
        # A past session you logged shows what you did; the rest (skipped, or added to the routine since) is
        # listed apart. They can't be logged after the day, so they don't count against it.
        logged = [ex for ex in sess["exercises"] if ex["log"]]
        sess["not_logged"] = [ex for ex in sess["exercises"] if not ex["log"]] if logged and sess["date"] < t else []
        if sess["not_logged"]:
            sess["exercises"] = logged

    items = ankle.BALANCE_STAGES[max(0, min(st["balance_stage"], len(ankle.BALANCE_STAGES) - 1))]
    if w["phase"] == "Race week":
        items = items[:2]
    w["snack"] = {}
    for name in s["ankle_days"]:
        d = w["start"] + timedelta(days=DAYS.index(name))
        if d > race_date(s):
            continue
        done = {x["item"] for x in st["snacks"] if x["date"] == d.isoformat()}
        w["snack"][d] = {"date": d, "day": d.strftime("%a"), "stage": st["balance_stage"], "items": items,
                         "done": done}
    w["snack"] = dict(sorted(w["snack"].items()))
    w["ankle_state"] = st


# --- questions the pages ask of a built view ---

def missing_runs(weeks: list[dict], t: date) -> list[date]:
    """Days among yesterday and today with a planned run and nothing synced."""
    days = {t - timedelta(days=1), t}
    return sorted({wo["date"] for w in weeks for wo in w["workouts"]
                   if wo["date"] in days and wo["km"] > 0 and not wo.get("skipped") and wo["actual_km"] is None})


def session_at(weeks: list[dict], day: date, session: str, orig: date | None = None) -> dict | None:
    """The non-skipped session of this kind on `day`; `orig` picks one when two runs share the day."""
    return next((item for kind, item in moves.day_items(weeks, day)
                 if kind == session and (orig is None or item["orig_date"] == orig)), None)


def move_warning(weeks: list[dict], session: str, day: date | None, orig: date | None, by: int = 1) -> dict | None:
    """The clash warning to show after a move (`by` 1 = tomorrow, -1 = a day earlier), if that clash still holds."""
    if session not in SESSIONS or day is None:
        return None
    item = session_at(weeks, day, session, orig)
    blocker = moves.clash(weeks, session, day, by) if item else None
    if blocker is None:
        return None
    kind = "run" if "type" in blocker else blocker["key"]
    return {"session": session, "date": day, "orig": item["orig_date"], "name": moves.session_name(session, item),
            "blocker": moves.session_name(kind, blocker), "blocker_day": blocker["date"], "by": by}


# --- page data ---

def dashboard(s: dict, weeks: list[dict], t: date, results: list[dict], token_expires: date | None,
              confirm: str = "", on: date | None = None, orig: date | None = None, by: int = 1) -> dict:
    """What This week shows, from a built view. `token_expires` is None when there's no key or no expiry date;
    `confirm`, `on` and `orig` name a move waiting on a clash warning."""
    current = next((w for w in weeks if w["is_current"]), None)
    upcoming = weeks[0] if t < weeks[0]["start"] else current
    st = weeks[0]["ankle_state"]
    # last week, so a wrong check-in can still be changed once the week has rolled over
    prev_week = weeks[upcoming["week"] - 2] if upcoming and upcoming["week"] > 1 else None
    strength_sessions = [x for w in weeks for x in w.get("strength", []) if x["date"] == t and not x.get("skipped")]
    left = (token_expires - t).days if token_expires else None
    return {
        "s": s, "today": t, "race_day": race_date(s), "days_left": (race_date(s) - t).days,
        "paces": s["paces"], "goal": s["goal_time"], "injured_side": s["injured_side"],
        "week": upcoming, "prev_week": prev_week,
        "next_run": next_run(weeks, t), "last_run": last_run(weeks, t),
        "strength_session": strength_sessions[0] if strength_sessions else None,  # two only after a Move anyway
        "strength_sessions": strength_sessions,
        "snack_today": (upcoming or {}).get("snack", {}).get(t),
        "morning_check": ankle.morning_check_due(t, st["logs"], st["checks"]),
        "tests_due": bool(upcoming) and ankle.tests_due(upcoming, weeks, st["tests"]),
        "tests": ankle_tests(upcoming, st, t),
        "ankle_flag": st["flag_until"],
        "hop_stage": st["hop_stage"],
        "move_warning": move_warning(weeks, confirm, on, orig, by),
        "last_summary": last_summary(weeks, s, st, results, t),
        "token_warning": {"expires": token_expires, "days": left} if left is not None and left <= garmin_api.KEY_WARN_DAYS
        else None,
        "profile": profile(weeks),
    }


def next_run(weeks: list[dict], t: date) -> dict | None:
    """The next run from today on (today's only until it's synced); on a day with two, the longer."""
    first = next((wo for w in weeks for wo in w["workouts"]
                  if wo["km"] > 0 and not wo.get("skipped")
                  and (wo["date"] > t or (wo["date"] == t and wo["actual_km"] is None))), None)
    if first is None:
        return None
    return max((wo for w in weeks for wo in w["workouts"]
                if wo["date"] == first["date"] and wo["km"] > 0 and not wo.get("skipped")), key=lambda wo: wo["km"])


def last_run(weeks: list[dict], t: date) -> dict | None:
    """The latest run up to today that has a review."""
    done = [wo for w in weeks for wo in w["workouts"] if wo.get("review") and wo["date"] <= t]
    return done[-1] if done else None


def ankle_tests(week: dict | None, st: dict, t: date) -> dict:
    """The readiness tests to offer this week, each with what's logged for it this week."""
    keys = [k for k in ankle.TESTS if k in ankle.CORE_TESTS
            or (k == "pogo_trial" and week and week["week"] == 1)
            or (k in ("single_hop", "triple_hop") and (st["hop_stage"] or 0) >= 2)]
    start = week["start"].isoformat() if week else None
    end = (week["start"] + timedelta(days=6)).isoformat() if week else None
    logged = {x["test"]: x for x in st["tests"] if week and start <= x["date"] <= end}
    return {k: {**ankle.TESTS[k], "logged": logged.get(k)} for k in keys}


def last_summary(weeks: list[dict], s: dict, st: dict, results: list[dict], t: date) -> dict | None:
    """Last week's summary, on Monday and Tuesday only."""
    if t.weekday() >= 2:
        return None
    done = progress.summaries(weeks, s, st, results, t)
    return done[0] if done and done[0]["end"] == t - timedelta(days=t.weekday() + 1) else None


def profile(weeks: list[dict]) -> dict:
    """The road-to-the-race chart: km planned each week, km done to now, and where now is."""
    return {
        "planned": [w["target_km"] for w in weeks],
        "actual": [w["actual_km"] if (w["is_past"] or w["is_current"]) else None for w in weeks],
        "current": next((i for i, w in enumerate(weeks) if w["is_current"]), None),
        "max": max(w["target_km"] for w in weeks),
    }
