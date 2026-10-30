"""The progress page: am I on course for the goal, and why.

Pure: callers pass what build_view() computed (weeks with reviews, guard, strength and ankle state, the
settings with the goal and the latest result). Nothing here is stored; like the plan, it's recomputed.
"""
from datetime import date, timedelta
from statistics import median

PACE_BAND = 15  # s/km either side of the reference pace for a split to count
MIN_SPLITS = 3  # fewer than this in a week is a gap, not a guess
DRIFT_WARN, DRIFT_BAD = 5, 10


def _to_date(weeks: list[dict]) -> list[dict]:
    return [w for w in weeks if w["is_past"] or w["is_current"]]


def fitness_trend(weeks: list[dict], ref_pace: float) -> list[dict]:
    """Per week to now: median heart rate on easy and long runs' km splits near `ref_pace`. Lower is fitter.

    Each run's first km is left out (warming up), as are part-km splits and quality days."""
    out = []
    for w in _to_date(weeks):
        hrs = []
        for wo in w["workouts"]:
            if wo["type"] not in ("easy", "long") or "steps" in wo or not wo.get("review"):
                continue
            for sp in wo["review"]["splits"][1:]:
                if sp["km"] >= 0.9 and sp["hr"] and abs(sp["pace"] - ref_pace) <= PACE_BAND:
                    hrs.append(sp["hr"])
        out.append({"week": w["week"], "hr": median(hrs) if len(hrs) >= MIN_SPLITS else None, "n": len(hrs)})
    return out


def _colour(drift: float | None) -> str:
    if drift is None:
        return "none"
    return "good" if drift < DRIFT_WARN else "warn" if drift <= DRIFT_BAD else "bad"


def long_runs(weeks: list[dict]) -> list[dict]:
    """Each long run done: its km, its drift and whether it had a marathon-pace finish."""
    out = []
    for w in weeks:
        for wo in w["workouts"]:
            if wo["type"] == "long" and wo.get("actual_km") is not None and not wo.get("skipped"):
                drift = (wo.get("review") or {}).get("drift")
                out.append({"week": w["week"], "date": wo["date"], "km": wo["actual_km"], "drift": drift,
                            "mp": bool(wo.get("mp_km")), "colour": _colour(drift)})
    return out


def plan_bars(weeks: list[dict]) -> list[dict]:
    """Km planned (after trims) against km done, for past weeks and this one."""
    return [{"week": w["week"], "planned": w["target_km"], "done": w["actual_km"], "held": bool(w.get("guard"))}
            for w in _to_date(weeks)]


# --- the verdict and the goals that fit ---

STATES = {"on track": "on course", "within reach": "within reach", "ambitious": "stretch"}
WEEKLY_GAIN = 0.01 / 4  # about 1% faster per 4 weeks of training left
MAX_GAIN = 0.04
NEAR = 60  # goal options within a minute of each other (or the goal) are the same option


def verdict(s: dict) -> dict:
    r = s.get("result")
    return {"state": STATES[r["verdict"]] if r else "none", "predicted": r["predicted"] if r else None,
            "goal": s["goal_time"]}


def _hms(seconds: float) -> str:
    s = int(round(seconds))
    return f"{s // 3600}:{(s % 3600) // 60:02d}:{s % 60:02d}"


def goal_options(predicted: float, goal_s: float, settings_goal_s: float, weeks_left: int) -> list[dict]:
    """Goals that fit where you are: a realistic stretch, today's prediction, and the way back to the
    settings' goal once it has been changed."""
    stretch = round(predicted * (1 - min(MAX_GAIN, WEEKLY_GAIN * weeks_left)) / 60) * 60
    today = -(-int(predicted) // 60) * 60  # rounded up to the minute
    picks = [(stretch, "stretch", f"A realistic stretch: needs the next {weeks_left} weeks done well."),
             (today, "prediction", "What today's fitness predicts.")]
    if goal_s != settings_goal_s:
        picks.append((settings_goal_s, "back", "Your original goal."))
    out, taken = [], [goal_s]
    for seconds, kind, why in picks:
        if kind != "back" and any(abs(seconds - x) < NEAR for x in taken):
            continue
        taken.append(seconds)
        out.append({"seconds": seconds, "time": _hms(seconds), "mp": round(seconds / 42.195), "kind": kind,
                    "why": why})
    return out


# --- why: plan, fitness, long runs, ankle ---

WINDOW = 4  # completed weeks the plan row looks back on
PLAN_OK = 0.8
PAIN_WARN = 3


def why_rows(weeks: list[dict], t: date, ref_pace: float) -> list[dict]:
    done = [w for w in weeks if w["is_past"]][-WINDOW:]
    if done:
        share = sum(w["actual_km"] for w in done) / (sum(w["target_km"] for w in done) or 1)
        sessions = [x for w in done for x in w.get("strength", []) if not x.get("skipped")]
        held = [w["week"] for w in done if w.get("guard")]
        text = (f"{round(100 * share)}% of planned km over the last {len(done)} weeks, "
                f"{sum(1 for x in sessions if x['done'])} of {len(sessions)} strength sessions")
        if held:
            text += ", week " + ", ".join(map(str, held)) + " held"
        plan = {"key": "plan", "ok": share >= PLAN_OK, "text": text}
    else:
        plan = {"key": "plan", "ok": True, "text": "Nothing to judge yet: week 1 is still under way."}

    hrs = [x for x in fitness_trend(weeks, ref_pace) if x["hr"] is not None]
    if len(hrs) >= 2:
        first, last = hrs[0], hrs[-1]
        fitness = {"key": "fitness", "ok": last["hr"] <= first["hr"],
                   "text": f"heart rate at easy pace {first['hr']:g} in week {first['week']}, {last['hr']:g} now"}
    else:
        fitness = {"key": "fitness", "ok": True, "text": "not enough easy-pace splits yet for a trend"}

    recent = [r for r in long_runs(weeks) if r["drift"] is not None][-3:]
    drifted = sum(1 for r in recent if r["drift"] >= DRIFT_WARN)
    long = {"key": "long", "ok": drifted < 2,
            "text": (f"{drifted} of the last {len(recent)} drifted" if drifted else
                     f"the last {len(recent)} held steady" if recent else "none with heart-rate data yet")}

    st = weeks[0]["ankle_state"]
    since = (t - timedelta(days=28)).isoformat()
    pains = [lg["ankle_pain"] for lg in st["logs"] if lg.get("ankle_pain") is not None and lg["date"] >= since]
    flag = st["flag_until"]
    hop = "hops not started" if st["hop_stage"] is None else f"hops at stage {st['hop_stage']}"
    text = (f"flag up until {flag.strftime('%-d %b')}" if flag else "no flag") + f", {hop}"
    if pains:
        text += f", pain {min(pains)}–{max(pains)} over 4 weeks"
    ankle = {"key": "ankle", "ok": not flag and not any(p >= PAIN_WARN for p in pains), "text": text}
    return [plan, fitness, long, ankle]



# --- ankle tests against their targets ---

ANKLE_ROWS = [("Calf raises", ("calf_raises",), "25", lambda v: v >= 25),
              ("Eyes-closed balance", ("eyes_closed_balance",), "30 s", lambda v: v >= 30),
              ("Y-balance (worst reach)", ("y_balance_ant", "y_balance_pm", "y_balance_pl"), "90%", lambda v: v >= 90)]


def ankle_table(weeks: list[dict], tests: list[dict]) -> dict:
    """Injured-side results per test week: calf raises and balance as logged, Y-balance as the worst reach in
    % of the other side."""
    def week_of(day: str) -> int | None:
        d = date.fromisoformat(day)
        return next((w["week"] for w in weeks if w["start"] <= d < w["start"] + timedelta(days=7)), None)

    by_week: dict[int, dict] = {}
    for x in sorted(tests, key=lambda r: r["date"]):
        n = week_of(x["date"])
        if n is not None:
            by_week.setdefault(n, {})[x["test"]] = x
    columns = sorted(n for n, got in by_week.items() if any(k in got for _, keys, _, _ in ANKLE_ROWS for k in keys))
    rows = []
    for name, keys, target, met in ANKLE_ROWS:
        cells = []
        for n in columns:
            got = [by_week[n].get(k) for k in keys]
            if not all(got):
                cells.append(None)
                continue
            if len(keys) == 1:
                value = got[0]["injured"]
            elif all(g.get("other") for g in got):
                value = min(round(100 * g["injured"] / g["other"], 1) for g in got)
            else:
                cells.append(None)
                continue
            cells.append({"value": value, "met": met(value)})
        rows.append({"name": name, "target": target, "cells": cells})
    return {"columns": columns, "rows": rows}
