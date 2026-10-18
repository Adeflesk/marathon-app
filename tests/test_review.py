from datetime import date

from app import review
from app.plan import generate

TODAY = date(2026, 10, 16)

# km splits as Smashrun returns them (cumulative distance and seconds), from the 16 Oct run
SPLITS = [{"distance": 1.0, "seconds": 426, "heartRate": 126}, {"distance": 2.0, "seconds": 819, "heartRate": 137},
          {"distance": 3.0, "seconds": 1184, "heartRate": 146}, {"distance": 4.0, "seconds": 1562, "heartRate": 150},
          {"distance": 5.0, "seconds": 1972, "heartRate": 152}, {"distance": 5.9259, "seconds": 2372, "heartRate": 153}]


def planned(settings, week, kind):
    return next(x for x in generate(settings, TODAY)[week - 1]["workouts"] if x["type"] == kind)


def test_splits_turn_cumulative_into_per_km_pace():
    s = review.splits(SPLITS)
    assert [round(x["pace"]) for x in s[:3]] == [426, 393, 365]
    assert abs(s[-1]["km"] - 0.9259) < 1e-6 and round(s[-1]["pace"]) == 432


def test_drift_compares_efficiency_of_the_two_halves():
    flat = [{"distance": i, "seconds": 400 * i, "heartRate": 140} for i in range(1, 9)]
    assert review.drift(review.splits(flat)) == 0
    rising = [{"distance": i, "seconds": 400 * i, "heartRate": 140 if i <= 4 else 154} for i in range(1, 9)]
    assert abs(review.drift(review.splits(rising)) - 10) < 0.5
    assert review.drift(review.splits(SPLITS[:2])) is None  # too short to say


def test_easy_run_too_fast_is_flagged(settings):
    easy = planned(settings, 1, "easy")
    fast = [{"distance": i, "seconds": 350 * i, "heartRate": 150} for i in range(1, 7)]
    r = review.review(easy, {"km": 6, "seconds": 2100}, {"splits": fast, "laps": []}, settings["paces"])
    assert r["verdict"] == "warn" and "easy" in r["headline"].lower()
    ok = [{"distance": i, "seconds": 400 * i, "heartRate": 140} for i in range(1, 7)]
    r = review.review(easy, {"km": 6, "seconds": 2400}, {"splits": ok, "laps": []}, settings["paces"])
    assert r["verdict"] == "good"


def test_rep_check_from_work_laps(settings):
    q = next(x for x in generate(settings, TODAY)[7]["workouts"] if "steps" in x)  # week 8: 4 x 1 km at 5:25
    laps, dur, dist = [], 0, 0
    laps.append({"lapType": "warmup", "endDuration": (dur := dur + 800), "endDistance": (dist := dist + 2)})
    for pace in (322, 326, 330, 345):
        laps.append({"lapType": "work", "endDuration": (dur := dur + pace), "endDistance": (dist := dist + 1)})
        laps.append({"lapType": "recovery", "endDuration": (dur := dur + 60), "endDistance": (dist := dist + 0.15)})
    laps.append({"lapType": "cooldown", "endDuration": dur + 400, "endDistance": dist + 1})
    r = review.review(q, {"km": 7.6, "seconds": dur + 400}, {"splits": [], "laps": laps}, settings["paces"])
    assert [x["verdict"] for x in r["reps"]] == ["on", "on", "on", "slow"]
    assert r["headline"].startswith("3 of 4 reps on pace")


def test_structured_run_without_work_laps_says_so(settings):
    q = next(x for x in generate(settings, TODAY)[7]["workouts"] if "steps" in x)
    r = review.review(q, {"km": 7.5, "seconds": 2700}, {"splits": SPLITS, "laps": [{"lapType": "general", "endDuration": 600, "endDistance": 1.5}]}, settings["paces"])
    assert r["reps"] == [] and "watch workout" in r["note"]


def test_mp_finish_checked_from_last_splits(settings):
    lr = next(x for w in generate(settings, TODAY) for x in w["workouts"] if x["type"] == "long" and x.get("mp_km") == 6)
    n = int(lr["km"])
    sp, t = [], 0
    for i in range(1, n + 1):
        t += 341 if i > n - 6 else 390
        sp.append({"distance": i, "seconds": t, "heartRate": 150})
    r = review.review(lr, {"km": n, "seconds": t}, {"splits": sp, "laps": []}, settings["paces"])
    assert "5:41" in r["headline"] and r["verdict"] == "good"
