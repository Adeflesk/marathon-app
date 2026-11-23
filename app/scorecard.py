"""The weekly scorecard: was the week in the right direction, and where to strengthen.

Pure, like progress.py: built from the weeks build_view() returns, recomputed per request, never stored.
Each row compares the scored week with the WINDOW completed weeks before it, or with a fixed target, and gives
an arrow: "up", "flat", "down", or None when there's nothing to judge (shown as a dash, never counted).
"""
from datetime import timedelta
from statistics import mean, median

from . import ankle, progress

WINDOW = 4  # weeks before the scored one that a row compares with
PRIOR_MIN = 2  # earlier values a comparison needs
FIT_BPM = 2  # heart rate at easy pace this much lower (or higher) than before is a change
PLAN_UP = 0.95  # share of planned km for "up"; progress.PLAN_OK (0.8) is the floor for "flat"
FEEL_STEP = 1  # check-in feel this far from the earlier average is a change
FEEL_LOW = 2  # a feel at or below this is "down" whatever came before
SNACK_LOW = 2  # fewer snack days than this is "down"; progress.SNACK_DAYS (4) or more is "up"
HOLD_PHASES = ("Cutback", "Taper", "Race week")  # held loads are the plan here, so they count as "up"


def _row(key: str, group: str, arrow: str | None, text: str, past: bool) -> dict:
    return {"key": key, "group": group, "arrow": arrow, "text": text, "past": past}


def _done(w: dict, types: tuple[str, ...] | None = None) -> list[dict]:
    """The week's runs that synced with a review."""
    return [wo for wo in w["workouts"] if not wo.get("skipped") and wo.get("review")
            and (types is None or wo["type"] in types)]


def _fitness(weeks: list[dict], i: int, ref_pace: float) -> dict:
    w = weeks[i]
    hr = {x["week"]: x["hr"] for x in progress.fitness_trend(weeks[:i + 1], ref_pace)}
    now = hr.get(w["week"])
    before = [hr[x["week"]] for x in weeks[max(0, i - WINDOW):i] if hr.get(x["week"]) is not None]
    if now is None or len(before) < PRIOR_MIN:
        return _row("fitness", "running", None, "not enough easy-pace running to compare yet", True)
    ref = median(before)
    arrow = "up" if now <= ref - FIT_BPM else "down" if now >= ref + FIT_BPM else "flat"
    return _row("fitness", "running", arrow, f"heart rate at easy pace {now:g}, {ref:g} before", True)


def _long(weeks: list[dict], i: int) -> dict:
    n = weeks[i]["week"]
    runs = progress.long_runs(weeks)
    this = [r for r in runs if r["week"] == n]
    if not this or this[-1]["drift"] is None:
        return _row("long", "running", None, "no long run with heart rate this week", True)
    r = this[-1]
    if r["drift"] >= progress.DRIFT_WARN:
        return _row("long", "running", "down", f"{r['km']:g} km, heart rate drifted {r['drift']:g}%", True)
    earlier = [x["km"] for x in runs if x["week"] < n]
    arrow = "up" if all(r["km"] > km for km in earlier) and earlier else "flat"
    return _row("long", "running", arrow, f"{r['km']:g} km, drift {r['drift']:g}%", True)


def _plan(w: dict) -> dict:
    if not w.get("synced") or not w["target_km"]:
        return _row("plan", "running", None, "not synced since the week ended", False)
    share = w["actual_km"] / w["target_km"]
    arrow = "up" if share >= PLAN_UP else "flat" if share >= progress.PLAN_OK else "down"
    return _row("plan", "running", arrow, f"{round(100 * share)}% of planned km", False)


def _mp(w: dict) -> dict:
    checks = []
    for wo in _done(w):
        r = wo["review"]
        if wo["type"] == "long" and r.get("mp_on") is not None:
            checks.append(r["mp_on"])
        elif "steps" in wo and wo["type"] in ("specific", "mp") and r.get("reps"):
            checks.append(all(x["verdict"] == "on" for x in r["reps"]))
    if not checks:
        return _row("mp", "running", None, "no marathon-pace work this week", False)
    on = sum(checks)
    return _row("mp", "running", "up" if on == len(checks) else "down",
                f"{on} of {len(checks)} marathon-pace checks on pace", False)


def _form(weeks: list[dict], i: int, ref_pace: float) -> dict:
    faded = [wo for wo in _done(weeks[i], ("easy", "long")) if "steps" not in wo and wo["review"].get("form")]
    if faded:
        return _row("form", "running", "down", faded[-1]["review"]["note"].rstrip("."), True)
    reading = progress.cadence_reading(progress.cadence_trend(weeks[:i + 1], ref_pace))
    if reading is None:
        return _row("form", "running", None, "not enough cadence data yet", True)
    arrow = {"rising": "up", "falling": "down", "steady": "flat"}[reading]
    return _row("form", "running", arrow, f"cadence at easy pace {reading}", True)


def _feel(weeks: list[dict], i: int) -> dict:
    ci = weeks[i].get("checkin")
    if not ci:
        return _row("feel", "running", None, "no check-in", True)
    feel = ci["feel"]
    before = [x["checkin"]["feel"] for x in weeks[max(0, i - WINDOW):i] if x.get("checkin")]
    text = f"rated {feel} of 5"
    if feel <= FEEL_LOW:
        return _row("feel", "running", "down", text, True)
    if len(before) < PRIOR_MIN:
        return _row("feel", "running", None, text, True)
    ref = mean(before)
    arrow = "down" if feel <= ref - FEEL_STEP else "up" if feel >= ref + FEEL_STEP else "flat"
    return _row("feel", "running", arrow, f"{text}, {ref:.1f} before", True)


def running_rows(weeks: list[dict], i: int, s: dict, ref_pace: float) -> list[dict]:
    """Fitness, long run, plan done, marathon pace, late-run form and how it felt, for weeks[i]."""
    w = weeks[i]
    return [_fitness(weeks, i, ref_pace), _long(weeks, i), _plan(w), _mp(w), _form(weeks, i, ref_pace),
            _feel(weeks, i)]


def _end(w: dict):
    return w["start"] + timedelta(days=6)


def _sessions(w: dict) -> dict:
    items = [x for x in w.get("strength", []) if not x.get("skipped")]
    if not items:
        return _row("sessions", "strength", None, "no strength sessions planned", False)
    done = sum(1 for x in items if x["done"])
    arrow = "up" if done == len(items) else "down" if done * 2 < len(items) else "flat"
    return _row("sessions", "strength", arrow, f"{done} of {len(items)} sessions", False)


def _load(logs: list[dict], day: str) -> tuple | None:
    """(weight, rung) of the latest loaded log on or before `day`; logs are newest first."""
    lg = next((x for x in logs if x["date"] <= day and (x.get("weight_kg") or x.get("rung"))), None)
    return (lg.get("weight_kg") or 0, lg.get("rung") or 0) if lg else None


def _loads(w: dict, st: dict) -> dict:
    end = _end(w)
    now_day, then_day = end.isoformat(), (end - timedelta(days=28)).isoformat()
    held_ok = w["phase"] in HOLD_PHASES
    up = down = pairs = 0
    for logs in st["by_ex"].values():
        now, then = _load(logs, now_day), _load(logs, then_day)
        if now is None or then is None:
            continue
        pairs += 1
        if now > then or (now == then and held_ok):
            up += 1
        elif now < then:
            down += 1
    if not pairs:
        return _row("loads", "strength", None, "not enough logged loads to compare yet", True)
    arrow = "up" if up > down else "down" if down > up else "flat"
    held = pairs - up - down
    return _row("loads", "strength", arrow, f"{up} up, {held} held, {down} down over 4 weeks", True)


def _stages(weeks: list[dict], w: dict, st: dict) -> dict:
    end = _end(w)
    then = max(end - timedelta(days=28), weeks[0]["start"] - timedelta(days=1))

    def at(day):
        hop = ankle.hop_stage(day, st["tests"], st["checks"], st["logs"], st["checkins"], weeks)
        bal = ankle.balance_stage(day, st["snacks"], st["tests"], st["checks"], hop, st["logs"], st["checkins"],
                                  weeks)
        return (-1 if hop is None else hop), bal

    (hop1, bal1), (hop0, bal0) = at(end), at(then)
    if hop1 < hop0 or bal1 < bal0:
        arrow = "down"
    elif hop1 > hop0 or bal1 > bal0:
        arrow = "up"
    else:
        arrow = "flat"
    hop_text = "hops not started" if hop1 < 0 else f"hop stage {hop1}"
    return _row("stages", "strength", arrow, f"{hop_text}, balance stage {bal1}", True)


def _ankle(weeks: list[dict], w: dict, st: dict) -> dict:
    triggers = ankle._triggers(st["checks"], st["logs"], st["checkins"], weeks)
    if any(progress._in(d.isoformat(), w) for d in triggers):
        return _row("ankle", "strength", "down", "ankle worse or painful this week", False)
    if w["week"] in ankle.test_weeks(weeks):
        table = progress.ankle_table(weeks, st["tests"])
        cols = table["columns"]
        if w["week"] in cols and cols.index(w["week"]) > 0:
            k = cols.index(w["week"])
            met = [sum(1 for r in table["rows"] if r["cells"][j] and r["cells"][j]["met"]) for j in (k - 1, k)]
            if met[1] > met[0]:
                return _row("ankle", "strength", "up", f"tests met {met[1]} targets, {met[0]} last time", False)
    return _row("ankle", "strength", "flat", "no ankle trouble this week", False)


def _snacks(w: dict, st: dict) -> dict:
    days = len({x["date"] for x in st["snacks"] if progress._in(x["date"], w)})
    arrow = "up" if days >= progress.SNACK_DAYS else "down" if days < SNACK_LOW else "flat"
    return _row("snacks", "strength", arrow, f"snacks on {days} day{'' if days == 1 else 's'}", False)


def strength_rows(weeks: list[dict], i: int, st: dict) -> list[dict]:
    """Strength done, strength loads, hops and balance, ankle and snacks, for weeks[i]."""
    w = weeks[i]
    return [_sessions(w), _loads(w, st), _stages(weeks, w, st), _ankle(weeks, w, st), _snacks(w, st)]
