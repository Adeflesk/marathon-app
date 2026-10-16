import math
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
    assert reps(trimmed["steps"]) == [max(2, math.floor(r * 0.8)) for r in reps(original["steps"])]
    assert trimmed["km"] == _half(session_km(trimmed["steps"], s["paces"]))
    assert trimmed["note"] == describe(trimmed["steps"], s["paces"])


def test_trimmed_fit_matches(client):
    from fit_tool.profile.profile_type import WorkoutStepDuration
    s, weeks = main.build_view()
    trimmed = quality(weeks[11])
    msgs = garmin.steps_for(trimmed, s["paces"])
    counts = [m.target_repeat_steps for m in msgs if m.duration_type == WorkoutStepDuration.REPEAT_UNTIL_STEPS_CMPLT.value]
    assert counts == reps(trimmed["steps"])


def test_strength_a_reduced_only_next_to_hard(client):
    _, weeks = main.build_view()

    def strength_a(w):
        return next(x for x in weeks[w - 1]["strength"] if x["name"].startswith("Strength A"))

    assert strength_a(5)["reduced"] is False
    assert strength_a(9)["reduced"] is True


def test_pages_200(client):
    assert [client.get(p).status_code for p in ("/", "/plan", "/strength", "/equipment")] == [200] * 4
