"""Post-run review: what a synced run says about the planned session.

Inputs are the planned workout, the run summary ({"km", "seconds"}) and Smashrun's detail
({"splits": km splits, "laps": laps}), where splits and laps carry cumulative distance and time.
Paces are seconds per km. Nothing here is stored; reviews are recomputed like the plan.
"""
import math

from .pace_engine import fmt_pace
from .sessions import flatten, pace_s

ON_PACE_S = 10  # a rep within 10 s/km of target counts as on pace (the watch's hard band)


def splits(raw: list[dict]) -> list[dict]:
    """Smashrun km splits (cumulative) as [{km, pace, hr}] per split."""
    out, dist, secs = [], 0.0, 0.0
    for s in raw:
        d, t = s["distance"] - dist, s["seconds"] - secs
        if d > 0:
            out.append({"km": d, "pace": t / d, "hr": s.get("heartRate")})
        dist, secs = s["distance"], s["seconds"]
    return out


def drift(sp: list[dict]) -> float | None:
    """Heart-rate cost of pace, second half against first, in %. 0 means steady; 5+ is drift.

    The first km is left out as warm-up, and a short last split (under 0.5 km) is ignored."""
    full = [s for s in sp if s["km"] >= 0.5 and s["hr"]]
    if len(full) >= 5:
        full = full[1:]
    if len(full) < 4:
        return None
    half = len(full) // 2

    def cost(part):  # heartbeats per metre, roughly: HR × pace
        km = sum(s["km"] for s in part)
        return sum(s["hr"] * s["km"] for s in part) / km * sum(s["pace"] * s["km"] for s in part) / km

    return round((cost(full[half:]) / cost(full[:half]) - 1) * 100, 1)


def _drift_words(d: float | None) -> str:
    if d is None:
        return ""
    if d < 5:
        return "heart rate steady"
    return "some heart-rate drift" if d < 10 else "heart rate drifted a lot"


def _laps(laps: list[dict]) -> list[dict]:
    """Smashrun laps (cumulative) as [{type, km, seconds}] per lap."""
    out, dist, dur = [], 0.0, 0.0
    for lap in laps:
        d, t = lap["endDistance"] - dist, lap["endDuration"] - dur
        if d > 0:
            out.append({"type": lap.get("lapType"), "km": d, "seconds": t})
        dist, dur = lap["endDistance"], lap["endDuration"]
    return out


def _reps(workout: dict, laps: list[dict], paces: dict, label: str = "Rep") -> list[dict]:
    targets = [pace_s(st["pace"], paces) for st in flatten(workout["steps"]) if st["intensity"] == "active"]
    work = [lap["seconds"] / lap["km"] for lap in _laps(laps) if lap["type"] == "work"]
    out = []
    for n, (actual, target) in enumerate(zip(work, targets), 1):
        diff = actual - target
        verdict = "on" if abs(diff) <= ON_PACE_S else ("fast" if diff < 0 else "slow")
        out.append({"n": n, "label": label, "target": target, "actual": actual, "verdict": verdict})
    return out


def _strides(workout: dict, run: dict, detail: dict, paces: dict, out: dict) -> dict:
    """Strides go by feel, so they're listed, not judged; the verdict is whether the running around
    them stayed easy. Never "bad", and no drift: the strides lift the heart rate on purpose."""
    out["drift"] = None
    laps = _laps(detail.get("laps") or [])
    reps = _reps(workout, detail.get("laps") or [], paces, "Stride")
    out["reps"] = reps
    if not reps:
        avg = run["seconds"] / run["km"] if run["km"] else None
        out["headline"] = f"Strides done: {run['km']:.1f} km at {fmt_pace(avg)}/km." if avg else "Strides done."
        out["note"] = "No stride laps came through. Start the session from the watch workout to see each stride."
        return out
    # The easy running: every lap but the strides and the jog straight after each one
    easy = [lap for i, lap in enumerate(laps) if lap["type"] != "work" and (i == 0 or laps[i - 1]["type"] != "work")]
    each = [r["actual"] for r in reps]
    out["headline"] = f"{len(reps)} strides, {fmt_pace(min(each))}–{fmt_pace(max(each))}/km."
    out["verdict"] = "good"
    km = sum(lap["km"] for lap in easy)
    if km:
        pace = sum(lap["seconds"] for lap in easy) / km
        if pace < paces["marathon"] + 20:
            out["headline"] += f" Easy running at {fmt_pace(pace)}/km is quicker than easy. Keep it easy."
            out["verdict"] = "warn"
        else:
            out["headline"] += f" Easy running at {fmt_pace(pace)}/km."
    return out


def review(workout: dict, run: dict, detail: dict, paces: dict) -> dict:
    sp = splits(detail.get("splits") or [])
    d = drift(sp)
    words = _drift_words(d)
    avg = run["seconds"] / run["km"] if run["km"] else None
    out = {"splits": sp, "drift": d, "reps": [], "note": "", "verdict": "neutral", "headline": ""}

    if workout["type"] == "strides":
        return _strides(workout, run, detail, paces, out)
    if "steps" in workout:
        reps = _reps(workout, detail.get("laps") or [], paces)
        out["reps"] = reps
        if not reps:
            out["headline"] = f"Session done: {run['km']:.1f} km at {fmt_pace(avg)}/km." if avg else "Session done."
            out["note"] = "No rep laps came through. Start the session from the watch workout to get a rep-by-rep check."
            return out
        on = sum(r["verdict"] == "on" for r in reps)
        off = [r for r in reps if r["verdict"] != "on"]
        out["headline"] = f"{on} of {len(reps)} reps on pace."
        if off:
            r = off[0]
            out["headline"] += f" Rep {r['n']} was {abs(round(r['actual'] - r['target']))} s/km {'quick' if r['verdict'] == 'fast' else 'slow'}."
        out["verdict"] = "good" if on == len(reps) else ("warn" if on * 2 >= len(reps) else "bad")
        return out

    mp_km = workout.get("mp_km") or 0
    if workout["type"] == "long" and mp_km and sp:
        tail = sp[-math.ceil(mp_km):]
        km = sum(s["km"] for s in tail)
        pace = sum(s["pace"] * s["km"] for s in tail) / km
        diff = pace - paces["marathon"]
        out["headline"] = f"Last {mp_km:g} km averaged {fmt_pace(pace)}/km"
        if abs(diff) <= ON_PACE_S:
            out["headline"] += ", on marathon pace."
            out["verdict"] = "good"
        else:
            out["headline"] += f", {abs(round(diff))} s/km {'quicker' if diff < 0 else 'slower'} than marathon pace."
            out["verdict"] = "warn"
        if words:
            out["headline"] += f" {words.capitalize()}."
        return out

    if avg is None:
        return out
    if avg < paces["marathon"] + 20:
        out["headline"] = f"{fmt_pace(avg)}/km is quicker than easy. Keep easy days easy."
        out["verdict"] = "warn"
    else:
        out["headline"] = f"Easy at {fmt_pace(avg)}/km" + (f", {words}." if words else ".")
        out["verdict"] = "good" if (d is None or d < 10) else "warn"
    return out
