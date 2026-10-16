"""Plan generator: rebuild base, build with cutbacks, long runs from week 4, taper, race."""
import math
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


BLOCK_NAMES = ["specific", "strength", "threshold"]  # counted back from the taper; earlier ones are "general"


def _floor_half(x: float) -> float:
    return math.floor(x * 2) / 2


def weekly_volumes(n: int, s: dict) -> list[dict]:
    """Return [{km, long, cutback, phase, block, block_week, mp_km}] for each week.

    Build weeks run in blocks of three between cutbacks. Blocks are named from the taper backwards
    (specific, strength, threshold, then general), so the plan reshapes with the settings.
    """
    base, base_weeks = s["base_weekly_km"], s["base_weeks"]
    peak, step, max_long = s["peak_weekly_km"], s["weekly_step_km"], s["max_long_run_km"]
    time_cap = 12600 / s["paces"]["long"]  # 3.5 h at long-run pace
    build_end = n - 3  # two taper weeks plus race week

    # what each week is; a cutback right before the taper is dropped, the taper is the rest
    kinds = []
    for i in range(n):
        if i < base_weeks:
            kinds.append("rebuild")
        elif i < build_end:
            cut = (i - base_weeks) % 4 == 3 and i != build_end - 1
            kinds.append("cutback" if cut else "build")
        else:
            kinds.append("taper" if i < n - 1 else "race")

    runs: list[list[int]] = []
    for i, k in enumerate(kinds):
        if k == "build":
            if runs and runs[-1][-1] == i - 1:
                runs[-1].append(i)
            else:
                runs.append([i])
    block, block_week = [None] * n, [None] * n
    for r, idxs in enumerate(reversed(runs)):
        name = BLOCK_NAMES[r] if r < len(BLOCK_NAMES) else "general"
        for pos, i in enumerate(idxs):
            block[i], block_week[i] = name, pos
    for i, k in enumerate(kinds):
        if k == "cutback":
            block[i] = block[i - 1]
    peak_weeks = set(runs[-1]) if runs else set()
    last_build = runs[-1][-1] if runs else None

    out: list[dict] = []
    build_km, last_long = base, None
    for i, k in enumerate(kinds):
        phase = {"rebuild": "Rebuild", "cutback": "Cutback", "taper": "Taper", "race": "Race week"}.get(k)
        if k == "rebuild":
            km, lg = base, 10
        elif k == "build":
            build_km = min(build_km + step, peak)
            km = build_km
            phase = "Peak" if i in peak_weeks else "Build"
            share = 0.58 if phase == "Peak" else 0.5
            lg = _floor_half(min(12 if last_long is None else last_long + 2, max_long, time_cap, share * km))
            if lg >= 20 and i != last_build:  # spike guard; the final peak run is exempt
                lg = min(lg, _floor_half(1.1 * max(w["long"] for w in out[-4:])))
            last_long = lg
        elif k == "cutback":
            km, lg = round(build_km * 0.8), round(last_long * 0.75)
        elif k == "taper":
            first = i == build_end
            # from the volume actually reached, so a short plan's taper still falls
            km = round(build_km * (0.75 if first else 0.55))
            lg = min(20 if first else 14, round(km * 0.5), last_long or 10)
        else:
            km, lg = 16, 0
        out.append({"km": km, "long": lg, "cutback": k == "cutback", "phase": phase,
                    "block": block[i], "block_week": block_week[i], "mp_km": 0,
                    "taper_week": i - build_end if k == "taper" else None})

    # no two 30 km+ long runs in a row anywhere; the easier week is 85% and all easy. The final peak
    # run (exempt from the guard) is never the one eased, so the week before it gives way instead.
    easy_weeks = set()
    run_of = {i: r for r in runs for i in r}

    def ease(i: int) -> None:
        earlier = [out[j]["long"] for j in run_of[i] if j < i] or [w["long"] for w in out[max(0, i - 4):i]]
        out[i]["long"] = round(0.85 * max(earlier))
        easy_weeks.add(i)

    for i in sorted(run_of):
        if i != last_build and i > 0 and out[i - 1]["long"] >= 30:
            ease(i)
    if last_build is not None and kinds[last_build - 1] == "build" and out[last_build - 1]["long"] >= 30:
        ease(last_build - 1)

    # MP finishes every other week from the first strength week, counted back from the final peak
    # run so it always gets one: 6, 8, 10, 12 km
    if runs:
        start = (runs[-2] if len(runs) > 1 else runs[-1])[0]
        mp_weeks = [i for i in range(start, last_build + 1)
                    if (last_build - i) % 2 == 0 and kinds[i] == "build" and i not in easy_weeks]
        for k, i in enumerate(mp_weeks):
            out[i]["mp_km"] = max(0, min(6 + 2 * k, 12, out[i]["long"] - 8))
    return out


def generate(s: dict, today: date) -> list[dict]:
    """Roles in s["run_days"]: easy, quality (the session from sessions.py) or long (exactly one)."""
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
        days = [d for d in mid_days if not (is_race_week and monday + timedelta(days=DAYS.index(d)) >= race)]
        quality_day = next((d for d in days if run_days[d] == "quality"), None)
        km_by_day, sess = _size_mid_week(v, i, s, days, quality_day, weights, total_w, rest, is_race_week)
        for d in days:
            day = monday + timedelta(days=DAYS.index(d))
            if d == quality_day and sess:
                wk = _w(day, sess["type"], km_by_day[d], sess["pace"], sess["note"])
                wk["steps"], wk["hard"] = sess["steps"], sess["hard"]
            else:
                wk = _w(day, "easy", km_by_day[d], "easy", "Easy. If the ankle complains, stop and walk home.")
            workouts.append(wk)
        lday = monday + timedelta(days=DAYS.index(long_day))
        if is_race_week:
            workouts.append(_w(race, "race", 42.195, "marathon", f"{s['race_name']}. Start at goal pace or a touch slower."))
        elif long_km:
            mp_km = v["mp_km"]
            note = f"Easy, then last {mp_km} km at marathon pace." if mp_km > 0 else "Easy, conversational."
            wk = _w(lday, "long", long_km, "long", note)
            wk["mp_km"] = mp_km
            workouts.append(wk)
        workouts.sort(key=lambda w: w["date"])
        weeks.append({
            "week": i + 1,
            "start": monday,
            "phase": v["phase"],
            "weeks_to_race": n - 1 - i,
            "target_km": round(sum(w["km"] for w in workouts), 1),
            "workouts": workouts,
        })
    return weeks


def _size_mid_week(v, i, s, days, quality_day, weights, total_w, rest, is_race_week):
    """Km for each mid-week run plus the quality session (or None).

    The session decides the quality day's km, its cool-down growing to fill the day's normal share.
    Easy runs keep at least min(6 km in Build/Peak or 5 km, their normal share); the last run absorbs
    rounding so the week hits its target.
    """
    from .sessions import describe, quality_session, session_km, strides_session  # sessions imports plan

    paces = s["paces"]
    if is_race_week:
        sess = quality_session(v, i, s, 99) if quality_day else None
        out, easy_seen = {}, 0
        for d in days:
            if d == quality_day and sess:
                out[d] = _half(session_km(sess["steps"], paces))
            else:
                out[d] = 6 if easy_seen == 0 else 3
                easy_seen += 1
        return out, sess
    if not rest or not days:
        return {d: 0 for d in days}, None
    share = {d: rest * weights[d] / total_w for d in days}
    floor = 6 if v["phase"] in ("Build", "Peak") else 5
    easy_days = [d for d in days if d != quality_day]
    sess = None
    if quality_day:
        max_km = rest - sum(min(floor, share[d]) for d in easy_days)
        sess = quality_session(v, i, s, max_km)
        # no room even for the smallest session (very short plans): strides, else an easy run
        for fallback in (lambda: strides_session(v, s), lambda: None):
            if sess is None or session_km(sess["steps"], paces) <= max_km + 0.25:
                break
            sess = fallback()
    if not sess:
        easy_days = days  # no session: the quality day is just another run in the split
    out = {}
    if sess:
        target = min(max(session_km(sess["steps"], paces), share[quality_day]), max_km)
        extra = math.floor((target - session_km(sess["steps"], paces)) * 2) / 2
        if extra > 0:
            sess["steps"][-1]["km"] += extra  # the cool-down fills the day
            sess["note"] = describe(sess["steps"], paces)
        out[quality_day] = _half(session_km(sess["steps"], paces))
    assigned = sum(out.values())
    easy_w = sum(weights[d] for d in easy_days)
    for pos, d in enumerate(easy_days):
        if pos == len(easy_days) - 1:
            out[d] = max(_half(rest - assigned), 0)
        else:
            out[d] = _half((rest - out.get(quality_day, 0)) * weights[d] / easy_w)
        assigned += out[d]
    return out, sess


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
