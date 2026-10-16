"""Plan generator: rebuild base, build with cutbacks, long runs from week 4, taper, race."""
from datetime import date, timedelta

from .config import next_monday, race_date

DAYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]


def _half(x: float) -> float:
    return round(x * 2) / 2


def week_count(s: dict, today: date) -> tuple[date, int]:
    race = race_date(s)
    race_monday = race - timedelta(days=race.weekday())
    start = date.fromisoformat(s["plan_start"]) if s.get("plan_start") else next_monday(today)
    return start, (race_monday - start).days // 7 + 1


def weekly_volumes(n: int, s: dict) -> list[dict]:
    """Return [{km, long, cutback, phase}] for each week."""
    base, base_weeks = s["base_weekly_km"], s["base_weeks"]
    peak, step, max_long = s["peak_weekly_km"], s["weekly_step_km"], s["max_long_run_km"]
    taper_weeks = 3  # two taper weeks plus race week
    build_end = n - taper_weeks
    out: list[dict] = []
    build_km, last_long = base, 10
    for i in range(n):
        if i < base_weeks:
            out.append({"km": base, "long": 10, "cutback": False, "phase": "Rebuild"})
        elif i < build_end:
            since = i - base_weeks
            if since % 4 == 3:  # every 4th week after the base is a cutback
                km = round(build_km * 0.8)
                lg = round(last_long * 0.75)
                out.append({"km": km, "long": lg, "cutback": True, "phase": "Cutback"})
            else:
                build_km = min(build_km + step, peak)
                last_long = min(last_long + 2 if since else 12, max_long)
                phase = "Peak" if build_km >= peak else "Build"
                out.append({"km": build_km, "long": last_long, "cutback": False, "phase": phase})
        else:
            k = i - build_end
            if k == 0:
                out.append({"km": round(peak * 0.75), "long": 20, "cutback": False, "phase": "Taper"})
            elif k == 1:
                out.append({"km": round(peak * 0.55), "long": 14, "cutback": False, "phase": "Taper"})
            else:
                out.append({"km": 16, "long": 0, "cutback": False, "phase": "Race week"})
    for w in out:
        if w["long"]:
            share = 0.58 if w["phase"] == "Peak" else 0.5
            w["long"] = min(w["long"], round(w["km"] * share))
    return out


def generate(s: dict, today: date) -> list[dict]:
    """Roles in s["run_days"]: easy, quality (tempo from week 8) or long (exactly one)."""
    start, n = week_count(s, today)
    vols = weekly_volumes(n, s)
    run_days = s["run_days"]
    long_day = next(d for d, role in run_days.items() if role == "long")
    mid_days = [d for d in DAYS if d in run_days and run_days[d] != "long"]
    weights = {d: (0.4 if run_days[d] == "quality" else 0.3) for d in mid_days}
    total_w = sum(weights.values())
    race = race_date(s)
    weeks = []
    for i, v in enumerate(vols):
        monday = start + timedelta(weeks=i)
        is_race_week = v["phase"] == "Race week"
        long_km = v["long"]
        rest = max(v["km"] - long_km, 0)
        workouts = []
        assigned, easy_seen = 0.0, 0
        for pos, d in enumerate(mid_days):
            role = run_days[d]
            day = monday + timedelta(days=DAYS.index(d))
            if is_race_week and day >= race:  # nothing on or after race day
                continue
            if is_race_week:
                if role == "quality":
                    km = 5
                else:
                    km = 6 if easy_seen == 0 else 3
                    easy_seen += 1
            elif not rest:
                km = 0
            elif pos == len(mid_days) - 1:  # last run absorbs rounding so the week hits its target
                km = max(_half(rest - assigned), 0)
            else:
                km = _half(rest * weights[d] / total_w)
            assigned += km
            kind, pace, note = "easy", "easy", "Easy. If the ankle complains, stop and walk home."
            if role == "quality" and not is_race_week and v["phase"] in ("Build", "Peak") and i >= 7:
                mins = min(40, 10 + (i - 6) * 2)
                kind, pace = "tempo", "tempo"
                note = f"2 km warm-up, {mins} min at tempo pace, 1 km cool-down."
            if role == "quality" and is_race_week:
                note = "Easy with 4 x 20 s strides."
            wk = _w(day, kind, km, pace, note)
            if kind == "tempo":
                wk["tempo_min"] = mins
            workouts.append(wk)
        lday = monday + timedelta(days=DAYS.index(long_day))
        if is_race_week:
            workouts.append(_w(race, "race", 42.195, "marathon", f"{s['race_name']}. Start at goal pace or a touch slower."))
        elif long_km:
            mp_km = 0
            if v["phase"] in ("Build", "Peak") and i >= 10:
                mp_km = min(12, 2 * (i - 9), long_km - 8)
            note = f"Easy, then last {mp_km} km at marathon pace." if mp_km > 0 else "Easy, conversational."
            wk = _w(lday, "long", long_km, "long", note)
            wk["mp_km"] = mp_km
            workouts.append(wk)
        workouts.sort(key=lambda w: w["date"])
        weeks.append({
            "week": i + 1,
            "start": monday,
            "phase": v["phase"],
            "target_km": round(sum(w["km"] for w in workouts), 1),
            "workouts": workouts,
        })
    return weeks


def _w(day: date, kind: str, km: float, pace: str, note: str) -> dict:
    return {"date": day, "day": DAYS[day.weekday()].title(), "type": kind, "km": km, "pace": pace, "note": note}


def feedback_factor(prev_checkin: dict | None) -> float:
    """Scale next week's targets from last week's check-in (pain 0-10, feel 1-5)."""
    if not prev_checkin:
        return 1.0
    pain, feel = prev_checkin["pain"], prev_checkin["feel"]
    if pain >= 5 or feel <= 1:
        return 0.8
    if pain >= 3 or feel <= 2:
        return 0.9
    return 1.0
