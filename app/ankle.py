"""Ankle flag, hop and balance stages, and the readiness-test schedule.

Pure functions: callers pass the stored rows (dates as ISO strings) and `today`. Nothing here is stored;
stages are replayed day by day from the user's own facts (tests, checks, logs, snack ticks) on every request.
General strength work for a runner back from a sprain, not rehab or medical advice.
"""
from datetime import date, timedelta

from app.strength import EXERCISES, HOP_STAGES  # noqa: F401  (HOP_STAGES re-exported for callers)

FLAG_DAYS = 7
GAP_DAYS = 28
STAGE_DAYS = 14
MORNING_ITEMS = {"hops", "calf_raise_straight", "seated_soleus_raise", "calf_raise_bent"}
Y_BALANCE = ("y_balance_ant", "y_balance_pm", "y_balance_pl")

TESTS = {
    "pogo_trial": {"name": "20-pogo trial", "unit": "pain 0–10", "sides": False,
                   "how": "20 two-leg pogo hops, low and stiff-ankled. Log the ankle pain (0–10)."},
    "calf_raises": {"name": "Single-leg calf raise to fatigue", "unit": "reps", "sides": True,
                    "how": "Straight knee, full height, steady pace (80 bpm). Stop when height drops."},
    "eyes_closed_balance": {"name": "Eyes-closed single-leg balance", "unit": "s", "sides": True,
                            "how": "Firm floor, near a wall. Time until you touch down (target 30 s)."},
    "y_balance_ant": {"name": "Y-balance reach, forward", "unit": "cm", "sides": True,
                      "how": "Stand on one leg, reach the other foot forward along the tape. Best of 3."},
    "y_balance_pm": {"name": "Y-balance reach, back-inward", "unit": "cm", "sides": True,
                     "how": "Reach back and inward along the tape. Best of 3."},
    "y_balance_pl": {"name": "Y-balance reach, back-outward", "unit": "cm", "sides": True,
                     "how": "Reach back and outward along the tape. Best of 3."},
    "single_hop": {"name": "Single hop for distance", "unit": "cm", "sides": True,
                   "how": "Hop forward on one leg, land and hold. Best of 3. Later, from hop stage 2."},
    "triple_hop": {"name": "Triple hop for distance", "unit": "cm", "sides": True,
                   "how": "Three hops on one leg, land and hold. Best of 3. Later, from hop stage 2."},
}
CORE_TESTS = ("calf_raises", "eyes_closed_balance") + Y_BALANCE


def _i(item, name, minutes, dose, cue):
    return {"item": item, "name": name, "minutes": minutes, "dose": dose, "cue": cue}


_EVERSION = _i("band_eversion", "Eccentric band eversion", 3, "2 × 15 per side",
               "Band round the forefoot; turn the sole out, then let it back in slowly over 3 s.")
_OPEN = _i("eyes_open_stance", "Single-leg stance, eyes open", 3, "3 × 30 s per leg",
           "Soft knee, tall hips, foot tripod pressed into the floor.")
_CLOSED = _i("eyes_closed_stance", "Single-leg stance, eyes closed", 3, "3 × 30 s per leg",
             "Near a wall. Touch down and restart if you wobble off.")
_CATCH = _i("ball_catch", "Single-leg ball catches", 3, "3 × 30 s per leg",
            "Catch and return a light ball (or a wall bounce), standing on one leg.")
_PERTURB = _i("band_perturbation", "Band perturbations", 3, "3 × 30 s per leg",
              "Band round the waist, anchored to one side; hold single-leg stance as it pulls you sideways.")
_YREACH = _i("y_balance_reach", "Y-balance reaches", 4, "3 × 5 each direction per leg",
             "Reach forward, back-inward and back-outward along tape lines; touch lightly, don't rest.")
_RDL = _i("sl_rdl_reach", "Single-leg RDL with a reach", 4, "3 × 8 per leg",
          "Hinge on one leg and reach the hand towards the floor in front; slow and level hips.")
_STICK = _i("hop_and_stick", "Hop-and-stick", 4, "3 × 5 each direction per leg",
            "Small single-leg hop forward, outward and inward; land quietly and hold 2 s.")
_WALKS = _i("heel_toe_walks", "Toe and heel walks", 2, "2 × 20 m each", "Tall on the toes, then on the heels.")


def _short(item, minutes, dose):
    return {**item, "minutes": minutes, "dose": dose}


# The report's progression: eyes open → eyes closed → ball catches → band perturbations → Y-balance reaches
# → SL RDL with a reach → hop-and-stick. Each stage keeps a lighter dose of the one before. 8–10 min each.
BALANCE_STAGES = [
    [_OPEN, _WALKS, _EVERSION],
    [_CLOSED, _short(_OPEN, 2, "2 × 30 s per leg, turning the head"), _EVERSION],
    [_CATCH, _short(_CLOSED, 2, "2 × 30 s per leg"), _EVERSION],
    [_PERTURB, _short(_CATCH, 2, "2 × 30 s per leg"), _EVERSION],
    [_YREACH, _short(_PERTURB, 2, "2 × 30 s per leg"), _EVERSION],
    [_RDL, _short(_YREACH, 3, "2 × 5 each direction per leg"), _EVERSION],
    [_STICK, _short(_RDL, 3, "2 × 8 per leg"), _EVERSION],
]


def _d(s) -> date:
    return s if isinstance(s, date) else date.fromisoformat(s)


# --- flag ---

def _triggers(checks=(), logs=(), checkins=(), weeks=()) -> list[date]:
    """Dates that raise the ankle flag."""
    out = [_d(c["date"]) for c in checks if c.get("worse")]
    prev: dict[str, int | None] = {}
    for lg in sorted(logs, key=lambda r: r["date"]):  # oldest first, to compare with the previous log
        ex = lg["exercise"]
        if not EXERCISES.get(ex, {}).get("ankle"):
            continue
        pain, before = lg.get("ankle_pain"), prev.get(ex)
        if pain is not None and (pain >= 3 or (before is not None and pain > before)):
            out.append(_d(lg["date"]))
        prev[ex] = pain
    starts = {w["week"]: w["start"] for w in weeks}
    for ci in checkins:
        if (ci.get("pain") or 0) >= 3 and ci.get("week") in starts:
            out.append(starts[ci["week"]] + timedelta(days=6))
    return out


def _flagged(day: date, triggers) -> bool:
    return any(t <= day <= t + timedelta(days=FLAG_DAYS) for t in triggers)


def flag_until(today: date, checks, logs, checkins, weeks) -> date | None:
    """The day the ankle flag expires, or None if it is down. Triggers after today are ignored."""
    ends = [t + timedelta(days=FLAG_DAYS) for t in _triggers(checks, logs, checkins, weeks) if t <= today]
    end = max(ends, default=None)
    return end if end is not None and end >= today else None


def morning_check_due(today: date, logs, checks) -> bool:
    """The morning after hop or calf work, until today's check is in."""
    yday = (today - timedelta(days=1)).isoformat()
    worked = any(lg["date"] == yday and lg["exercise"] in MORNING_ITEMS for lg in logs)
    return worked and not any(c["date"] == today.isoformat() for c in checks)


# --- test schedule ---

def test_weeks(weeks) -> set[int]:
    """Week 1, the first Build week and every Cutback week."""
    out = {1}
    build = [w["week"] for w in weeks if w["phase"] == "Build"]
    if build:
        out.add(build[0])
    return out | {w["week"] for w in weeks if w["phase"] == "Cutback"}


test_weeks.__test__ = False  # not a pytest test, despite the name


def tests_due(week: dict, weeks, tests) -> bool:
    """A test week whose core tests (plus the pogo trial in week 1) aren't all logged inside it yet."""
    if week["week"] not in test_weeks(weeks):
        return False
    start, end = week["start"], week["start"] + timedelta(days=6)
    done = {t["test"] for t in tests if start <= _d(t["date"]) <= end}
    need = set(CORE_TESTS) | ({"pogo_trial"} if week["week"] == 1 else set())
    return not need <= done


tests_due.__test__ = False


# --- stages ---

def _latest(tests, day: date) -> dict:
    """The most recent row of each test on or before `day`."""
    out = {}
    for t in sorted(tests, key=lambda r: r["date"]):
        if _d(t["date"]) <= day:
            out[t["test"]] = t
    return out


def _ratio_ok(row, ratio: float) -> bool:
    return bool(row) and bool(row.get("other")) and row["injured"] >= ratio * row["other"]


def _hop_gate(stage: int, latest: dict) -> bool:
    if stage == 0:
        return True
    if stage == 1:
        calf = latest.get("calf_raises")
        return (bool(calf) and calf["injured"] >= 25 and _ratio_ok(calf, 0.9)
                and all(_ratio_ok(latest.get(k), 0.8) for k in Y_BALANCE))
    if stage == 2:
        return (all(_ratio_ok(latest.get(k), 0.9) for k in Y_BALANCE)
                and all(_ratio_ok(latest.get(k), 0.85) for k in ("single_hop", "triple_hop")))
    return False


def hop_stage(today: date, tests, checks, logs=None) -> int | None:
    """0–3, or None ("not yet") before a passing pogo trial or after a long gap without a fresh one.

    A trial passes with pain ≤ 2 and no "worse" check the next morning (so it counts from the day after).
    The flag inside the replay comes from "worse" checks and, when `logs` are given, logged ankle pain.
    The 28-day gap rule needs `logs`: tests alone are 4 weeks apart and stop after the last cutback, so
    without logs there is no way to tell time off from a normal gap between tests.
    """
    worse = {_d(c["date"]) for c in checks if c.get("worse")}
    trials = {_d(t["date"]) for t in tests if t["test"] == "pogo_trial" and t["injured"] <= 2}
    trials = {t for t in trials if t + timedelta(days=1) <= today and t + timedelta(days=1) not in worse}
    if not trials:
        return None
    triggers = _triggers(checks, logs or ())
    active = {_d(r["date"]) for r in list(tests) + list(logs)} if logs is not None else None
    stage, entered, last_active = None, None, None
    day = min(trials)
    while day <= today:
        if stage is not None and last_active is not None and (day - last_active).days > GAP_DAYS:
            stage = None
        if active is not None and day in active:
            last_active = day
        if stage is None:
            if day in trials:
                stage, entered = 0, day
        elif day in worse:
            stage, entered = max(0, stage - 1), day
        elif (stage < len(HOP_STAGES) - 1 and (day - entered).days >= STAGE_DAYS
              and not _flagged(day, triggers) and _hop_gate(stage, _latest(tests, day))):
            stage, entered = stage + 1, day
        day += timedelta(days=1)
    return stage


def balance_stage(today: date, snacks, tests, checks, hop: int | None) -> int:
    """0–6: two weeks per stage, ≥4 snack days ticked in it and no flag; a worse morning holds it."""
    days = sorted({_d(s["date"]) for s in snacks if _d(s["date"]) <= today})
    if not days:
        return 0
    triggers = _triggers(checks)
    stage, entered, day = 0, days[0], days[0]
    while day <= today and stage < len(BALANCE_STAGES) - 1:
        ticked = sum(1 for s in days if entered <= s <= day)
        ok = (day - entered).days >= STAGE_DAYS and ticked >= 4 and not _flagged(day, triggers)
        if ok and stage == 1:
            eyes = _latest(tests, day).get("eyes_closed_balance")
            ok = bool(eyes) and eyes["injured"] >= 30
        if ok and stage == 5:
            ok = hop is not None and hop >= 2
        if ok:
            stage, entered = stage + 1, day
        day += timedelta(days=1)
    return stage


def restart(today: date, logs, checks) -> bool:
    """True for the first 2 sessions after >28 days off or a "worse" morning in the last 7 days.

    Sessions are counted by distinct log dates before today, so today's session keeps its prescription
    while it is being logged.
    """
    dates = sorted({_d(lg["date"]) for lg in logs if _d(lg["date"]) <= today})
    points = []
    if dates:
        if (today - dates[-1]).days > GAP_DAYS:
            return True
        gaps = [b for a, b in zip(dates, dates[1:]) if (b - a).days > GAP_DAYS]
        if gaps:
            points.append(gaps[-1])
    points += [_d(c["date"]) for c in checks
               if c.get("worse") and 0 <= (today - _d(c["date"])).days <= FLAG_DAYS]
    return any(sum(1 for x in dates if p <= x < today) < 2 for p in points)
