from datetime import date

from fit_tool.profile.profile_type import Intensity, WorkoutStepDuration, WorkoutStepTarget

from app import garmin
from app.plan import generate

REPEAT = WorkoutStepDuration.REPEAT_UNTIL_STEPS_CMPLT.value  # fit-tool reads fields back as plain ints
TODAY = date(2026, 10, 16)


def quality(settings, week):
    return next(x for x in generate(settings, TODAY)[week - 1]["workouts"] if "steps" in x)


def test_repeat_structure(settings):
    w = quality(settings, 8)
    msgs = garmin.steps_for(w, settings["paces"])
    block = next(st for st in w["steps"] if "repeat" in st)
    assert [msgs[i].intensity for i in (0, 1, 2, 4)] == [Intensity.WARMUP.value, Intensity.ACTIVE.value, Intensity.RECOVERY.value, Intensity.COOLDOWN.value]
    assert msgs[3].duration_type == REPEAT
    assert msgs[3].duration_step == 1
    assert msgs[3].target_repeat_steps == block["repeat"]
    assert msgs[2].target_type == WorkoutStepTarget.OPEN.value and msgs[2].intensity == Intensity.RECOVERY.value
    assert msgs[1].target_type == WorkoutStepTarget.SPEED.value
    assert len(msgs) == 5


def test_two_blocks(settings):
    w = {"type": "fartlek", "km": 8, "date": TODAY, "steps": [
        {"label": "WU", "km": 2, "pace": "easy", "intensity": "warmup"},
        {"repeat": 6, "steps": [{"label": "Fast", "seconds": 60, "pace": "interval", "intensity": "active"},
                                {"label": "Easy", "seconds": 60, "pace": None, "intensity": "recovery"}]},
        {"repeat": 4, "steps": [{"label": "Stride", "seconds": 20, "pace": "interval", "intensity": "active"},
                                {"label": "Jog", "seconds": 60, "pace": None, "intensity": "recovery"}]},
        {"label": "CD", "km": 1, "pace": "easy", "intensity": "cooldown"}]}
    msgs = garmin.steps_for(w, settings["paces"])
    repeats = [(i, m.duration_step, m.target_repeat_steps) for i, m in enumerate(msgs) if m.duration_type == REPEAT]
    assert repeats == [(3, 1, 6), (6, 4, 4)]
    assert len(msgs) == 8


def test_build_fit_bytes(settings):
    for week in generate(settings, TODAY):
        for w in week["workouts"]:
            if w["km"] > 0:
                data = garmin.build_fit(w, settings["paces"])
                assert data[8:12] == b".FIT", (week["week"], w["type"])


def _km(msgs):
    return sum(m.duration_distance for m in msgs) / 1000


def test_easy_and_long_start_with_an_open_warmup_km(settings):
    p = settings["paces"]
    for w in ({"type": "easy", "km": 4.5}, {"type": "long", "km": 10},
              {"type": "long", "km": 24, "mp_km": 4}):
        msgs = garmin.steps_for(w, p)
        assert msgs[0].intensity == Intensity.WARMUP.value
        assert msgs[0].target_type == WorkoutStepTarget.OPEN.value
        assert msgs[0].duration_distance == 1000
        assert msgs[1].target_type == WorkoutStepTarget.SPEED.value
        assert _km(msgs) == w["km"]
    assert garmin.steps_for({"type": "long", "km": 24, "mp_km": 4}, p)[-1].workout_step_name.startswith("MP")


def test_race_has_no_warmup_step(settings):
    msgs = garmin.steps_for({"type": "race", "km": 42.2}, settings["paces"])
    assert len(msgs) == 1 and msgs[0].intensity == Intensity.ACTIVE.value
