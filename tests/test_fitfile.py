from datetime import date

from app import fitfile, review
from app.plan import generate
from app.sessions import flatten

from .fitdata import make_zip


def steady(km, pace=300, hr=lambda m: 140 if m < 1000 else 150):
    """1 Hz records at a steady pace (s/km)."""
    speed = 1000 / pace
    return [(t, t * speed, hr(t * speed)) for t in range(int(km * pace) + 1)]


def test_km_splits_from_records():
    d = fitfile.details(make_zip(steady(2.5), [], False))
    s = d["splits"]
    assert [round(x["distance"], 2) for x in s] == [1.0, 2.0, 2.5]
    assert [round(x["seconds"]) for x in s] == [300, 600, 750]
    assert [x["heartRate"] for x in s] == [140, 150, 150]
    # the shape review.py reads
    assert [round(x["pace"]) for x in review.splits(s)] == [300, 300, 300]


def test_pause_not_counted():
    recs = [(t, t * 3.0, 140) for t in range(100)]
    recs += [(99 + 120, 99 * 3.0 + 5, 140)]  # 120 s gap, 5 m on
    recs += [(99 + 120 + t, 99 * 3.0 + 5 + t * 3.0, 140) for t in range(1, 1001)]
    s = fitfile.details(make_zip(recs, [], False))["splits"]
    total = s[-1]["seconds"]
    assert abs(total - (99 + 1000)) < 1  # 1099 s moving, not 1219


def test_workout_laps_typed():
    laps = [(1000, 300, "warmup"), (800, 200, "active"), (200, 90, "rest"), (800, 195, "active"), (1000, 330, "cooldown")]
    out = fitfile.details(make_zip(steady(4), laps, True))["laps"]
    assert [x["lapType"] for x in out] == ["warmup", "work", "rest", "work", "cooldown"]
    assert [round(x["endDistance"], 1) for x in out] == [1.0, 1.8, 2.0, 2.8, 3.8]
    assert [round(x["endDuration"]) for x in out] == [300, 500, 590, 785, 1115]


def test_free_run_laps_are_not_reps():
    laps = [(1000, 300, "active"), (1000, 300, "active")]
    out = fitfile.details(make_zip(steady(2), laps, False))["laps"]
    assert [x["lapType"] for x in out] == ["general", "general"]


def test_review_reads_it(settings):
    wk = next(x for w in generate(settings, date(2026, 10, 16)) for x in w["workouts"] if "steps" in x and x["type"] != "strides")
    reps = [st for st in flatten(wk["steps"]) if st["intensity"] == "active"]
    laps = [(1000, 400, "warmup")]
    for _ in reps:
        laps += [(500, 150, "active"), (200, 90, "rest")]
    d = fitfile.details(make_zip(steady(12), laps, True))
    r = review.review(wk, {"km": 12, "seconds": 3600}, d, settings["paces"])
    assert len(r["reps"]) == len(reps) >= 2
