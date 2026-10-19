from datetime import date

import pytest
from fastapi.testclient import TestClient

from app import garmin, main
from app.plan import _half, generate
from app.sessions import describe, session_km


@pytest.fixture
def client():
    with TestClient(main.app) as c:
        c.post("/checkin", data={"week": 11, "feel": 3, "pain": 6, "note": ""})
        yield c


def reps(steps):
    return [st["repeat"] for st in steps if "repeat" in st]


def quality(week):
    return next(x for x in week["workouts"] if "steps" in x)


def test_trim_scales_reps(client, settings):
    original = quality(generate(settings, main.today())[11])
    s, weeks = main.build_view()
    trimmed = quality(weeks[11])
    assert weeks[11]["factor"] == 0.8
    expected = [max(2, round(r * 0.8)) for r in reps(original["steps"])]
    assert reps(trimmed["steps"]) == expected
    assert trimmed["km"] == _half(session_km(trimmed["steps"], s["paces"]))
    assert trimmed["note"] == describe(trimmed["steps"], s["paces"])


def test_trimmed_fit_matches(client):
    from fit_tool.profile.profile_type import WorkoutStepDuration
    s, weeks = main.build_view()
    trimmed = quality(weeks[11])
    msgs = garmin.steps_for(trimmed, s["paces"])
    counts = [m.target_repeat_steps for m in msgs if m.duration_type == WorkoutStepDuration.REPEAT_UNTIL_STEPS_CMPLT.value]
    assert counts == reps(trimmed["steps"])


def test_thursday_full_dose_after_normal_wednesday(client):
    _, weeks = main.build_view()

    def strength_a(w):
        return next(x for x in weeks[w - 1]["strength"] if x["key"] == "A")

    for n in (5, 9):
        a = strength_a(n)
        assert a["reduced"] is False
        squat = next(e for e in a["exercises"] if e["role"] == "main")
        assert squat["sets"] == 3
    assert strength_a(12)["reduced"] is True  # week 11's check-in trims week 12


def test_pages_200(client):
    assert [client.get(p).status_code for p in ("/", "/plan", "/strength", "/equipment")] == [200] * 4


def test_trim_shrinks_every_session(settings):
    from app.sessions import scale_session
    for week in generate(settings, main.today()):
        for x in week["workouts"]:
            if "steps" in x and x["type"] != "strides":
                before = session_km(x["steps"], settings["paces"])
                scale_session(x, 0.8, settings["paces"])
                assert session_km(x["steps"], settings["paces"]) < before - 0.4, (week["week"], x["type"], x["note"])


def test_review_attached_and_shown(client, settings, monkeypatch):
    import json
    from app import db
    wk8 = generate(settings, main.today())[7]
    q = next(x for x in wk8["workouts"] if "steps" in x)
    laps = [{"lapType": "warmup", "endDuration": 800, "endDistance": 2.0}]
    dur, dist = 800, 2.0
    for _ in range(4):
        dur, dist = dur + 325, dist + 1.0
        laps.append({"lapType": "work", "endDuration": dur, "endDistance": dist})
        dur, dist = dur + 60, dist + 0.15
        laps.append({"lapType": "recovery", "endDuration": dur, "endDistance": dist})
    with db.conn() as c:
        c.execute("INSERT OR REPLACE INTO activities VALUES (901, ?, 7.6, 2900, 150)", (q["date"].isoformat(),))
        c.execute("INSERT OR REPLACE INTO run_details VALUES (901, ?, ?)",
                  (json.dumps([{"distance": 1.0, "seconds": 400, "heartRate": 140}]), json.dumps(laps)))
    monkeypatch.setattr(main, "today", lambda: q["date"])
    _, weeks = main.build_view()
    reviewed = next(x for x in weeks[7]["workouts"] if "steps" in x)
    assert reviewed["review"]["headline"] == "4 of 4 reps on pace."
    page = client.get("/").text
    assert "4 of 4 reps on pace." in page
