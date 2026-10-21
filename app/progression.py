"""Next-session suggestions from strength logs.

Implements "Progression rules for the app's logging card" in `reports/Runner strength routine review.md`:
the rating-to-next-session table, load steps for the user's equipment, the top-weight ladder, the phase and
check-in overrides, return after time off, and the first-session warm-up ladder.

Pure: callers pass the exercise's history (newest first, as `db.logs(key)` returns it) and the context.
Overrides only ever cap a suggestion; nothing here raises load in a reduced week.
"""
from datetime import date

from .strength import EXERCISES, barbell_loads

# Light starting points for the first-session warm-up (Ruling R2), snapped to what's available.
WARMUP_START = {"barbell": [20, 30, 40], "dumbbell": [5, 7.5, 10], "kettlebell": [12]}

# Loads that progress through reps and the ladder only. Hops follow the hop stage instead (see strength.py);
# carries and timed holds stay inside their prescribed range.
NO_LADDER = {"hops", "timed", "carry"}
UNITS = {"carry": "m", "core": "s", "balance": "s"}  # by role, as strength._rx_text counts them
LADDER_TEXT = {2: "3–4 s lowering", 3: "2–3 s pause"}

KB_GATE_REPS = 15  # a kettlebell jump needs an easy rating at this many reps or more
KB_RESET_REPS = 8
HOLD_STEP = 5  # seconds or metres added per "aim for", where reps would add 1


def _kind(ex: dict) -> str | None:
    load = ex.get("load", "")
    if load.startswith("barbell"):
        return "barbell"
    if load.startswith("dumbbell"):
        return "dumbbell"
    if load == "kettlebell":
        return "kettlebell"
    if load == "carry":  # carried in one hand: the bell or dumbbell its equipment calls for
        return "kettlebell" if "kettlebell" in EXERCISES.get(ex.get("key"), {}).get("needs", ()) else "dumbbell"
    return None


def available_weights(ex: dict, eq: dict) -> list[float]:
    """Every weight this exercise can use with the user's equipment, ascending."""
    kind = _kind(ex)
    if kind == "barbell" and eq.get("barbell"):
        return [float(w) for w in barbell_loads(eq)]
    if kind == "dumbbell" and eq.get("dumbbells"):
        lo, hi, st = float(eq["db_min_kg"]), float(eq["db_max_kg"]), float(eq["db_step_kg"])
        if st <= 0 or hi < lo:
            return [lo] if st <= 0 else []
        return [round(lo + i * st, 2) for i in range(int(round((hi - lo) / st)) + 1)]
    if kind == "kettlebell":
        return sorted(float(w) for w in eq.get("kettlebells_kg") or [])
    return []


def _snap_down(w: float, weights: list[float]) -> float:
    """The heaviest available weight at or below `w`, else the lightest one."""
    below = [x for x in weights if x <= w + 1e-9]
    return below[-1] if below else weights[0]


def _increment(w: float, ex: dict, phase: str) -> float:
    load = ex.get("load")
    if load == "barbell_lower":
        return 2.5 if w >= 60 or phase == "Peak" else 5.0
    if load == "barbell_upper":
        return 2.5
    return 1.25


def step(weight: float, ex: dict, eq: dict, n: int, phase: str) -> float:
    """`n` load steps up (or down when negative) within the available weights, clamped at the ends."""
    weights = available_weights(ex, eq)
    if not weights:
        return weight
    w = _snap_down(weight, weights)
    for _ in range(abs(n)):
        if _kind(ex) == "kettlebell":
            i = weights.index(w) + (1 if n > 0 else -1)
            w = weights[max(0, min(i, len(weights) - 1))]
            continue
        inc = _increment(w, ex, phase)
        if n > 0:
            up = [x for x in weights if x >= w + inc - 1e-9]
            w = up[0] if up else weights[-1]
        else:
            down = [x for x in weights if x <= w - inc + 1e-9]
            w = down[-1] if down else weights[0]
    return w


def _hi(ex: dict, rung: int) -> int:
    """Top of the rep range; rung 1 extends it by up to 4 (12 at most for main lifts, 20 otherwise)."""
    if rung == 1:
        return max(ex["hi"], min(ex["hi"] + 4, 12 if ex.get("role") == "main" else 20))
    return ex["hi"]


def _kg(w) -> str:
    return f"{w:g} kg"


def _level(ex: dict, rung: int, last_level):
    if rung >= 4:
        harder = EXERCISES.get(ex["key"], {}).get("harder")
        return EXERCISES[harder]["name"] if harder else LADDER_TEXT[3]
    return LADDER_TEXT.get(rung, last_level)


def _first_session(ex: dict, eq: dict) -> dict:
    weights = available_weights(ex, eq)
    start = WARMUP_START.get(_kind(ex) or "", [])
    warmup = sorted({_snap_down(w, weights) for w in start}) if weights else []
    unit = UNITS.get(ex.get("role"), "reps")
    if warmup and unit == "reps":
        reason = (f"First time: warm up with {', '.join(f'{w:g}' for w in warmup)} kg and stop where "
                  f"{ex['lo']} reps leave about 3–4 in the tank. Log that as your working weight.")
    elif warmup:
        reason = (f"First time: try {', '.join(f'{w:g}' for w in warmup)} kg for {ex['lo']} {unit} and keep "
                  f"the heaviest that still feels steady. Log that as your working weight.")
    else:
        reason = f"First time: aim for {ex['lo']} {unit}, comfortably."
    return {"weight": None, "reps": ex["lo"], "rung": 0, "level": None, "warmup": warmup, "reason": reason}


def suggest(ex: dict, history: list[dict], ctx: dict, eq: dict, today: date) -> dict:
    """Next session's weight, reps, ladder rung and level for one exercise, with the reason why."""
    if not history:
        return _first_session(ex, eq)

    last, prev = history[0], (history[1] if len(history) > 1 else None)
    phase = ctx.get("phase", "")
    lo = ex["lo"]
    weights = available_weights(ex, eq)
    last_w = _snap_down(last["weight_kg"], weights) if weights and last.get("weight_kg") is not None else None
    last_rung = int(last.get("rung") or 0)
    done = min(last.get("reps") or [0])
    rating = last.get("rating")
    ladder = ex.get("load") not in NO_LADDER and ex.get("role") not in UNITS

    def out(weight, reps, rung, reason):
        return {"weight": weight, "reps": reps, "rung": rung, "warmup": [], "reason": reason,
                "level": _level(ex, rung, last.get("level"))}

    if ex.get("load") == "hops":
        return out(None, lo, last_rung, "Hop dose follows your hop stage.")

    # Rule 2: time off since the last log of any exercise.
    last_any = max(ctx.get("last_any_log") or date.min, date.fromisoformat(last["date"]))
    gap = (today - last_any).days
    if gap > 28:
        if last_w is not None:
            w = _snap_down(0.8 * last_w, weights)
            res = out(w, lo, 0, f"{gap} days off, so about 80% of {_kg(last_w)}: {_kg(w)}")
        else:
            res = out(None, lo, max(0, last_rung - 1), f"{gap} days off, so one stage easier")
    elif gap >= 11:
        if last_w is not None:
            w = step(last_w, ex, eq, -1, phase)
            res = out(w, lo, last_rung, f"{gap} days off, so one step lighter: {_kg(w)}")
        else:
            res = out(None, lo, last_rung, f"{gap} days off, so back to {lo} {UNITS.get(ex.get('role'), 'reps')}")
    else:
        res = _rate(ex, eq, last, prev, last_w, last_rung, done, rating, phase, ladder, out)

    return _override(ex, eq, ctx, last, last_w, last_rung, res)


def _rate(ex, eq, last, prev, last_w, last_rung, done, rating, phase, ladder, out):
    """Rule 3: the report's rating-to-next-session table, with the top-weight ladder (rule 5)."""
    lo, hi = ex["lo"], _hi(ex, last_rung)
    top = done >= hi
    target_done = done >= (last.get("target_reps") or 0)
    was = {"easy": "Easy", "right": "Right", "hard": "Hard"}.get(rating, "Logged")
    unit = UNITS.get(ex.get("role"), "reps")
    at = f"at {_kg(last_w)}" if last_w is not None else f"at {done} {unit}"
    inc = 1 if unit == "reps" else HOLD_STEP
    kb_reps = _kind(ex) == "kettlebell" and ex.get("load") != "carry"  # the 12 → 16 kg rep gate

    def can_up(n):
        """The heavier weight `n` steps up, or None when the ladder has to take over."""
        if last_w is None:
            return None
        if kb_reps and not (rating == "easy" and done >= KB_GATE_REPS):
            return None
        w = step(last_w, ex, eq, n, phase)
        return w if w > last_w else None

    def up(n):
        w = can_up(n)
        if w is not None:
            reps = KB_RESET_REPS if kb_reps else lo
            return out(w, reps, 0, f"{was} last time {at}, so {_kg(w)} for {reps}")
        return climb()

    def climb():
        """No heavier weight: move one rung down the ladder."""
        if not ladder:
            return out(last_w, hi, last_rung, f"{was} last time {at}, so hold {hi} {unit}")
        rung, reps = last_rung + 1, lo
        if rung == 1:
            reps = min(done + (2 if rating == "easy" else 1), _hi(ex, 1))
            if _hi(ex, 1) <= ex["hi"]:  # range can't extend any further
                rung, reps = 2, lo
        if rung == 4 and not EXERCISES.get(ex["key"], {}).get("harder"):
            rung, reps = 3, hi
        rung = min(rung, 4)
        if rung == 4 and last_rung == 4:
            reps = hi
        what = {1: f"a longer range (up to {_hi(ex, 1)})", 2: LADDER_TEXT[2], 3: LADDER_TEXT[3]}.get(rung)
        if rung == 4:
            what = _level(ex, 4, None)
        weight = f" {_kg(last_w)}" if last_w is not None else ""
        return out(last_w, reps, rung, f"{was} at the top{weight}, so {what}: {reps} reps")

    def same(reps, why):
        reps = max(lo, min(reps, hi))
        return out(last_w, reps, last_rung, f"{was} last time {at}, so {why} {reps} {unit}")

    if rating == "hard":
        if target_done and not (prev and prev.get("rating") == "hard"):
            return same(last.get("target_reps") or done, "repeat")
        if last_w is not None:
            w = step(last_w, ex, eq, -1, phase)
            if w < last_w:
                return out(w, lo, last_rung, f"{was} last time {at}, so {_kg(w)} for {lo}")
        rung = max(0, last_rung - 1) if ladder else last_rung
        return out(last_w, lo, rung, f"{was} last time {at}, so one stage back, {lo} {unit}")
    if rating == "easy":
        if top:
            return up(2 if prev and prev.get("rating") == "easy" else 1)
        if done >= hi - 1 and can_up(1) is not None:
            return up(1)
        return same(done + 2 * inc, "aim for")
    if top:
        return up(1)
    return same(done + inc, "aim for")


def _override(ex, eq, ctx, last, last_w, last_rung, res):
    """Rule 4: caps from the phase, the check-in and the ankle flag. They never raise a suggestion."""
    phase = ctx.get("phase", "")
    factor = ctx.get("factor", 1.0)
    why = []
    if ctx.get("cutback") or phase == "Cutback":
        why.append("cutback week")
    if phase.startswith("Taper"):
        why.append("taper")
    if factor < 1.0:
        why.append("last week's check-in")
    if phase == "Peak" and ex.get("role") == "main":
        why.append("Peak holds the main lifts")
    if ctx.get("ankle_flag") and ex.get("ankle"):
        why.append("ankle flag")
    if not why:
        return res

    cap_w = last_w
    if last_w is not None and factor <= 0.8:
        cap_w = step(last_w, ex, eq, -1, phase)
    changed = False
    if cap_w is not None and res["weight"] is not None and res["weight"] > cap_w:
        res["weight"], changed = cap_w, True
    if res["rung"] > last_rung:
        res["rung"], changed = last_rung, True
    if changed:
        hi = _hi(ex, res["rung"])
        if cap_w is not None and cap_w < last_w:
            res["reps"] = ex["lo"]
        else:
            res["reps"] = max(ex["lo"], min(last.get("target_reps") or ex["lo"], hi))
        res["level"] = _level(ex, res["rung"], last.get("level"))
        held = _kg(res["weight"]) if res["weight"] is not None else "the same level"
        res["reason"] = f"{res['reason']}; but {', '.join(why)}, so {held} for {res['reps']}"
    return res
