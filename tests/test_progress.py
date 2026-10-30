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


def wk(n, workouts, target=25.0, actual=25.0, past=True, current=False, guard=None, synced=None):
    return {"week": n, "start": START + timedelta(weeks=n - 1), "workouts": workouts, "target_km": target,
            "actual_km": actual, "is_past": past, "is_current": current, "guard": guard,
            "synced": past if synced is None else synced}


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


# --- verdict, goal options, why rows, ankle table ---

def test_verdict_states():
    assert progress.verdict({"goal_time": "3:59:00"})["state"] == "none"
    for given, state in (("on track", "on course"), ("within reach", "within reach"), ("ambitious", "stretch")):
        v = progress.verdict({"goal_time": "3:59:00", "result": {"verdict": given, "predicted": 14000.0}})
        assert v["state"] == state and v["predicted"] == 14000.0 and v["goal"] == "3:59:00"


def test_goal_options_for_a_stretch():
    opts = progress.goal_options(15555, 14340, 14340, 19)
    assert [(o["time"], o["kind"]) for o in opts] == [("4:09:00", "stretch"), ("4:20:00", "prediction")]
    assert opts[0]["mp"] == 354


def test_goal_options_offer_the_way_back():
    opts = progress.goal_options(15555, 14940, 14340, 19)
    assert ("3:59:00", "back") in [(o["time"], o["kind"]) for o in opts]
    assert "4:09:00" not in [o["time"] for o in opts]  # that's the goal already


def test_goal_options_drop_near_duplicates():
    opts = progress.goal_options(14430, 14340, 14340, 2)  # stretch rounds to 3:59:00, the goal itself
    assert [o["kind"] for o in opts] == ["prediction"] and opts[0]["time"] == "4:01:00"


def sess(key, done=True, skipped=False, pain=None):
    return {"key": key, "done": done, "skipped": skipped,
            "exercises": [{"key": "calf_raise_bent", "log": {"ankle_pain": pain} if pain is not None else None}]}


def full_week(n, actual=25.0, drift=2.0, strength=None, **kw):
    w = wk(n, [run(n, splits=EASY), run(n, "long", km=10, drift=drift)], 25.0, actual, **kw)
    w["strength"] = strength if strength is not None else [sess("B"), sess("A")]
    return w


def state(flag=None, hop=0, logs=()):
    return {"flag_until": flag, "hop_stage": hop, "logs": list(logs)}


T = date(2026, 11, 23)  # Monday of week 6


def rows(weeks, st=None):
    weeks[0]["ankle_state"] = st or state()
    return {r["key"]: r for r in progress.why_rows(weeks, T, 405)}


def test_why_plan_ignores_skipped_strength():
    weeks = [full_week(i) for i in range(1, 6)] + [full_week(6, past=False, current=True)]
    weeks[2]["strength"] = [sess("B"), sess("A", done=False, skipped=True)]
    r = rows(weeks)["plan"]
    assert r["ok"] and "100%" in r["text"] and "7 of 7" in r["text"]  # weeks 2–5: 8 sessions, 1 skipped


def test_why_rows_warn():
    weeks = [full_week(i) for i in range(1, 6)] + [full_week(6, past=False, current=True)]
    weeks[4]["actual_km"] = 4.0  # 79% over weeks 2–5
    weeks[3]["workouts"][1]["review"]["drift"] = 7.0
    weeks[4]["workouts"][1]["review"]["drift"] = 6.0
    for w in weeks[4:]:  # heart rate at easy pace up from 150 to 160
        w["workouts"][0]["review"]["splits"] = [{"km": 1, "pace": 405, "hr": 160}] * 5
    r = rows(weeks, state(flag=date(2026, 11, 28)))
    assert [k for k, v in r.items() if not v["ok"]] == ["plan", "fitness", "long", "ankle"]


def test_why_rows_with_nothing_to_go_on():
    r = rows([full_week(1, past=False, current=True)])
    assert all(v["ok"] for v in r.values())
    assert r["long"]["text"] == "the last one held steady"


TESTS_W1 = [{"date": "2026-10-23", "test": t, "injured": i, "other": o} for t, i, o in
            (("calf_raises", 19, 21), ("eyes_closed_balance", 28, 21), ("y_balance_ant", 70, 80),
             ("y_balance_pm", 75, 80), ("y_balance_pl", 75, 80), ("pogo_trial", 0, None))]


def test_ankle_table_from_week_one_tests():
    t = progress.ankle_table([wk(1, []), wk(2, [])], TESTS_W1)
    assert t["columns"] == [1]
    cells = {r["name"]: r["cells"][0] for r in t["rows"]}
    assert cells["Calf raises"] == {"value": 19, "met": False}
    assert cells["Eyes-closed balance"] == {"value": 28, "met": False}
    assert cells["Y-balance (worst reach)"] == {"value": 87.5, "met": False}
    assert [r["target"] for r in t["rows"]] == ["25", "30 s", "90%"]


def test_goal_options_without_a_prediction_only_offer_the_way_back():
    assert progress.goal_options(None, 14340, 14340, 10) == []
    assert [o["kind"] for o in progress.goal_options(None, 14940, 14340, 10)] == ["back"]


def test_plan_row_after_one_week_reads_right():
    r = rows([full_week(1), full_week(2, past=False, current=True)])
    assert r["plan"]["text"].startswith("100% of planned km last week,")


def test_no_stretch_harder_than_the_goal():
    opts = progress.goal_options(4.05 * 3600, 14340, 14340, 14)  # predicts 4:03, goal 3:59: within reach
    assert all(o["seconds"] >= 14340 for o in opts if o["kind"] != "back")


def test_plan_row_ignores_weeks_no_sync_has_covered():
    weeks = [full_week(i) for i in range(1, 6)] + [full_week(6, past=False, current=True)]
    weeks[4]["actual_km"], weeks[4]["synced"] = 8.0, False  # Sunday's long run not synced yet
    r = rows(weeks)["plan"]
    assert r["ok"] and "100%" in r["text"] and "week 5 not synced yet" in r["text"]
