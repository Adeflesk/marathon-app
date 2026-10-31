"""Fuelling: the gel schedule for long runs and the race-day pacing and fuelling plan.

Pure. A gel at 45 minutes, then every 35, none in the last 10 minutes; only runs of 90 minutes or more need
fuel. Finisher gels are the Barcelona course's own, so practice uses them too.
"""
MIN_RUN = 90  # minutes
FIRST, EVERY, NOT_LAST = 45, 35, 10
MARATHON = 42.195
GAP_MIN, GAP_MAX = 25, 45  # minutes between gels on race day, wherever they come from
EASY_START_KM, EASY_START_S = 5, 5  # the first 5 km 5 s/km easier, the rest a touch quicker


def gel_minutes(duration_min: float) -> list[int]:
    if duration_min < MIN_RUN:
        return []
    out, t = [], FIRST
    while t <= duration_min - NOT_LAST:
        out.append(t)
        t += EVERY
    return out


def _join(xs: list) -> str:
    xs = [str(x) for x in xs]
    return xs[0] if len(xs) == 1 else ", ".join(xs[:-1]) + " and " + xs[-1]


def long_run_note(km: float, mp_km: float, long_pace: float) -> str | None:
    """The fuel practice line for a long run, or None when it's under 90 minutes at long-run pace."""
    gels = gel_minutes(km * long_pace / 60)
    if not gels:
        return None
    note = f"Fuel practice: a Finisher gel at {_join(gels)} min ({len(gels)} gel{'s' if len(gels) > 1 else ''}), with water."
    if mp_km:
        note += " Take the gel before the marathon-pace part as on race day, and keep taking them at goal pace."
    return note


def race_plan(mp: int, stations: list[float], gel_stations: list[float]) -> dict:
    """Splits and gels for race day at marathon pace `mp` (s/km), finishing in mp × 42.195."""
    first = mp + EASY_START_S
    finish = mp * MARATHON
    rest = (finish - EASY_START_KM * first) / (MARATHON - EASY_START_KM)

    def clock(km: float) -> float:
        return km * first if km <= EASY_START_KM else EASY_START_KM * first + (km - EASY_START_KM) * rest

    def km_at(seconds: float) -> float:
        lead = EASY_START_KM * first
        return seconds / first if seconds <= lead else EASY_START_KM + (seconds - lead) / rest

    marks = [(float(k), f"{k} km") for k in range(5, 45, 5) if k < MARATHON] + [(21.0975, "Half"), (MARATHON, "Finish")]
    splits = [{"km": k, "label": label, "clock": clock(k)} for k, label in sorted(marks)]

    # Each gel is due on the long-run schedule. One due before the first course gel station is carried; later
    # ones come from the course gel station reached nearest the time it's due, 25–45 minutes after the gel
    # before. When no station fits, it's carried and taken on time. "time" is when it's actually taken.
    stations, gel_stations = sorted(stations), sorted(gel_stations)
    at = {st: clock(st) / 60 for st in gel_stations}
    gels, used, last = [], set(), None
    for minute in gel_minutes(finish / 60):
        fits = [st for st in gel_stations if st not in used and at[st] >= minute - 20
                and (last is None or last + GAP_MIN <= at[st] <= last + GAP_MAX)]
        station = min(fits, key=lambda st: abs(at[st] - minute)) if fits and gel_stations and \
            minute >= at[gel_stations[0]] - 5 else None
        if station is None:
            t = minute if last is None else max(minute, last + GAP_MIN)
            gels.append({"minute": minute, "time": t, "km": km_at(t * 60), "where": "carry", "station": None})
        else:
            used.add(station)
            t = at[station]
            gels.append({"minute": minute, "time": t, "km": station, "where": "course", "station": station})
        last = t
    return {"first_pace": first, "rest_pace": rest, "finish": finish, "splits": splits, "gels": gels,
            "stations": stations, "gel_stations": gel_stations}
