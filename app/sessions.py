"""Quality-day (Wednesday) sessions as steps the watch can follow.

A step is {"label", "km" or "seconds", "pace", "intensity", optional "note"}; a repeat block is
{"repeat": n, "steps": [...]}. "pace" is a key in settings.paces, a number of seconds per km, or None
for an open target (recoveries). Sessions follow the plan's block, counted back from the taper:
general (fartlek), threshold (cruise intervals), strength (just under MP-10 s reps) and specific
(long reps at MP), with a smaller version in cutback weeks and a short MP touch in the taper.
"""
import math

from .pace_engine import fmt_pace
from .plan import _half

HARD_TYPES = {"threshold", "strength", "specific", "mp"}
CAP_PCT = {"tempo": 0.12, "subthreshold": 0.18, "marathon": 0.18}  # rep km as a share of the week
LADDER = {"threshold": [3.2, 2.4, 1.6, 1.0], "strength": [3.2, 2.4, 1.6, 1.0], "specific": [5, 4, 3, 2],
          "mp": [1.6, 1.0]}
WU_KM, CD_KM = 2, 1

# (reps, rep length, recovery) per block week; a longer block repeats the last entry
MENU = {
    "general": [(6, 60, 120), (7, 60, 120), (8, 60, 120)],  # seconds
    "threshold": [(4, 1.6, 60), (5, 1.6, 60), (3, 3.2, 120)],  # km, recovery seconds
    "strength": [(6, 1.6, 0.4), (4, 2.4, 0.8), (3, 3.2, 0.8)],  # km, recovery km
    "specific": [(2, 4, 1), (2, 5, 1), (2, 5, 1)],  # km, float km
}
TYPE_PACE = {"strides": "easy", "fartlek": "interval", "threshold": "tempo", "strength": "subthreshold",
             "specific": "marathon", "mp": "marathon"}


def pace_s(pace, paces: dict) -> float:
    if pace is None:
        return paces["easy"]
    return paces[pace] if isinstance(pace, str) else pace


def step_km(step: dict, paces: dict) -> float:
    return step["km"] if "km" in step else step["seconds"] / pace_s(step["pace"], paces)


def flatten(steps: list) -> list:
    """Steps with repeat blocks expanded."""
    out = []
    for st in steps:
        out.extend(st["steps"] * st["repeat"] if "repeat" in st else [st])
    return out


def session_km(steps: list, paces: dict) -> float:
    return sum(step_km(st, paces) for st in flatten(steps))


def work_km(steps: list, paces: dict) -> float:
    return sum(step_km(st, paces) for st in flatten(steps) if st["intensity"] == "active")


def _st(label, amount, pace, intensity, unit="km", note=None):
    st = {"label": label, unit: amount, "pace": pace, "intensity": intensity}
    if note:
        st["note"] = note
    return st


def _strides(n: int) -> dict:
    return {"repeat": n, "steps": [_st("Stride", 20, "interval", "active", "seconds", "Fast and relaxed."),
                                   _st("Jog", 60, None, "recovery", "seconds")]}


def _main(kind: str, reps: int, length, rec, paces: dict) -> list:
    """The work part of a session (no warm-up or cool-down)."""
    if kind == "fartlek":
        return [{"repeat": reps, "steps": [_st("Fast", length, "interval", "active", "seconds", "Hard but controlled."),
                                           _st("Easy", rec, None, "recovery", "seconds")]}]
    if kind == "threshold":
        return [{"repeat": reps, "steps": [_st("Rep", length, "tempo", "active", note="Comfortably hard, even."),
                                           _st("Jog", rec, None, "recovery", "seconds")]}]
    if kind == "specific":
        rep = _st("MP", length, paces["marathon"] - 3, "active", note="Goal pace, smooth.")
        return [rep, _st("Float", rec, paces["marathon"] / 0.95, "active", note="Steady, not a jog."), dict(rep)]
    pace = "subthreshold" if kind == "strength" else "marathon"
    rec_step = _st("Jog", rec, None, "recovery", "seconds" if kind == "mp" and rec >= 60 else "km")
    return [{"repeat": reps, "steps": [_st("Rep", length, pace, "active", note="Just quicker than goal pace."), rec_step]}]


def _wrap(main: list, wu: float = WU_KM, cd: float = CD_KM) -> list:
    return [_st("WU", wu, "easy", "warmup")] + main + [_st("CD", cd, "easy", "cooldown")]


def _fit(kind: str, reps: int, length, rec, week_km: float, max_km: float, paces: dict) -> list:
    """The biggest version (fewer reps, never below 2, or shorter reps down the ladder) within the
    work cap and max_km. If nothing fits, the smallest version; generate makes room for it."""
    cap = CAP_PCT.get(TYPE_PACE[kind], 1.0) * week_km
    ladder = LADDER.get(kind, [])
    lengths = ladder[ladder.index(length):] if length in ladder else [length]
    rep_counts = [reps] if kind == "specific" else range(reps, 1, -1)
    best, smallest = None, None
    for ln in lengths:
        for r in rep_counts:
            steps = _wrap(_main(kind, r, ln, rec, paces))
            work = work_km(steps, paces)
            if smallest is None or work < smallest[0]:
                smallest = (work, steps)
            if work <= cap + 1e-9 and session_km(steps, paces) <= max_km + 1e-9 and (best is None or work > best[0] + 1e-9):
                best = (work, steps)
    return (best or smallest)[1]


def describe(steps: list, paces: dict) -> str:
    def amount(st):
        if "km" in st:
            return f"{st['km']:g} km"
        s = st["seconds"]
        return f"{s // 60} min" if s >= 120 and s % 60 == 0 else f"{s} s"

    def one(st):
        if st["intensity"] == "recovery":
            return f"{amount(st)} jog"
        if st["label"] == "Float":
            return f"{amount(st)} float at {fmt_pace(pace_s(st['pace'], paces))}"
        return f"{amount(st)} at {fmt_pace(pace_s(st['pace'], paces))}"

    parts = []
    for st in steps:
        if "repeat" in st:
            work, *rest = st["steps"]
            text = f"{st['repeat']} × {one(work)}"
            if rest:
                text += " with " + ", ".join(one(r) for r in rest)
            parts.append(text)
        elif st["intensity"] == "warmup":
            parts.append(f"{amount(st)} WU")
        elif st["intensity"] == "cooldown":
            parts.append(f"{amount(st)} CD")
        else:
            parts.append(one(st))
    return ", ".join(parts) + ". Flat ground."


def _session(kind: str, steps: list, v: dict, paces: dict) -> dict:
    hard = kind in HARD_TYPES and v["phase"] in ("Build", "Peak", "Cutback")
    return {"type": kind, "pace": TYPE_PACE[kind], "hard": hard, "steps": steps, "note": describe(steps, paces)}


def strides_session(v: dict, s: dict, n: int = 6) -> dict:
    """An easy run with strides; also the fallback when a week has no room for its session."""
    steps = [_st("Easy", WU_KM, "easy", "warmup"), _strides(n), _st("CD", CD_KM, "easy", "cooldown")]
    return _session("strides", steps, v, s["paces"])


def quality_session(v: dict, week_index: int, s: dict, max_km: float) -> dict | None:
    """The quality day for one week of weekly_volumes(), or None (first Rebuild week)."""
    paces = s["paces"]
    phase = v["phase"]
    if phase == "Rebuild":
        if week_index == 0:
            return None
        return strides_session(v, s, 6 if week_index == 1 else 8)
    if phase == "Taper":
        if v["taper_week"] == 0:
            return _session("strength", _fit("strength", 2, 3.2, 0.8, v["km"], max_km, paces), v, paces)
        return _session("mp", _fit("mp", 3, 1.6, 0.4, v["km"], max_km, paces), v, paces)
    if phase == "Race week":
        main = _main("mp", 3, 1, 120, paces) + [_strides(4)]
        return _session("mp", _wrap(main, 1, 1), v, paces)
    block = v["block"]
    kind = "fartlek" if block == "general" else block
    if v["cutback"]:
        reps, length, rec = MENU[block][0]
        reps = 5 if block == "general" else max(2, round(reps * 0.65))
    else:
        reps, length, rec = MENU[block][min(v["block_week"], len(MENU[block]) - 1)]
    return _session(kind, _fit(kind, reps, length, rec, v["km"], max_km, paces), v, paces)


def scale_session(workout: dict, factor: float, paces: dict) -> None:
    """Check-in trim: fewer reps (rounded, never below 2). Where reps can't drop (already 2, or the
    specific session's two long reps), the reps get one rung shorter instead. km and note follow."""
    ladder = LADDER.get(workout["type"], [])

    def shorten(step: dict) -> bool:
        if step.get("km") in ladder and ladder.index(step["km"]) < len(ladder) - 1:
            step["km"] = ladder[ladder.index(step["km"]) + 1]
            return True
        return False

    for st in workout["steps"]:
        if "repeat" in st:
            reps = max(2, round(st["repeat"] * factor))
            if reps < st["repeat"]:
                st["repeat"] = reps
            else:
                shorten(st["steps"][0])
    if workout["type"] == "specific":
        for st in workout["steps"]:
            if st["label"] == "MP":
                shorten(st)
    workout["km"] = _half(session_km(workout["steps"], paces))
    workout["note"] = describe(workout["steps"], paces)
