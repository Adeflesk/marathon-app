"""The progress page: am I on course for the goal, and why.

Pure: callers pass what build_view() computed (weeks with reviews, guard, strength and ankle state, the
settings with the goal and the latest result). Nothing here is stored; like the plan, it's recomputed.
"""
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
