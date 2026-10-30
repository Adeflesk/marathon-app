from datetime import date, timedelta

from app import progress

START = date(2026, 10, 19)


def run(n, kind="easy", splits=None, km=5.0, steps=False, mp_km=0, drift=None, review=True, skipped=False):
    """A workout as build_view leaves it; splits as (km, pace, hr)."""
    wo = {"date": START + timedelta(weeks=n - 1, days=6 if kind == "long" else 0), "type": kind, "km": km,
          "actual_km": km, "mp_km": mp_km, "skipped": skipped}
    if steps:
        wo["steps"] = []
    wo["review"] = {"splits": [{"km": a, "pace": b, "hr": c} for a, b, c in splits or []], "drift": drift} if review else None
    return wo


def wk(n, workouts, target=25.0, actual=25.0, past=True, current=False, guard=None):
    return {"week": n, "start": START + timedelta(weeks=n - 1), "workouts": workouts, "target_km": target,
            "actual_km": actual, "is_past": past, "is_current": current, "guard": guard}


EASY = [(1, 400, 130), (1, 400, 150), (1, 410, 152), (1, 415, 148), (1, 380, 160), (1, 430, 170)]


def test_fitness_uses_splits_near_easy_pace():
    trend = progress.fitness_trend([wk(1, [run(1, splits=EASY)])], 405)
    assert trend == [{"week": 1, "hr": 150, "n": 3}]


def test_quality_days_and_short_splits_dont_count():
    quality = run(1, "fartlek", splits=EASY, steps=True)
    short = run(1, splits=[(1, 400, 140), (0.5, 405, 150), (0.5, 405, 150), (0.5, 405, 150)])
    assert progress.fitness_trend([wk(1, [quality, short])], 405) == [{"week": 1, "hr": None, "n": 0}]


def test_runs_without_details_are_gaps():
    assert progress.fitness_trend([wk(1, [run(1, review=False)])], 405)[0]["hr"] is None
    assert progress.long_runs([wk(1, [run(1, "long", km=10, review=False)])])[0]["colour"] == "none"


def test_long_run_colours():
    weeks = [wk(i + 1, [run(i + 1, "long", km=10 + i, drift=d, mp_km=6 if i == 1 else 0)])
             for i, d in enumerate((3.0, 6.0, 12.0, None))]
    runs = progress.long_runs(weeks)
    assert [r["colour"] for r in runs] == ["good", "warn", "bad", "none"]
    assert [r["mp"] for r in runs] == [False, True, False, False] and runs[2]["km"] == 12


def test_plan_bars_current_week_partial():
    weeks = [wk(1, [], 25, 24.5), wk(2, [], 25, 10.4, past=False, current=True, guard={"why": "hold"}),
             wk(3, [], 25, 0, past=False)]
    assert progress.plan_bars(weeks) == [{"week": 1, "planned": 25, "done": 24.5, "held": False},
                                         {"week": 2, "planned": 25, "done": 10.4, "held": True}]
