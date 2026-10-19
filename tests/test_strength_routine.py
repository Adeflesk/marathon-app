from datetime import date

import pytest

from app import strength
from app.plan import generate

START = date(2026, 10, 19)


@pytest.fixture
def weeks(settings):
    return generate(settings, START)


def ctx(**kw):
    base = {"factor": 1.0, "wed_bad": False, "ankle_flag": False, "hop_stage": None,
            "balance_stage": 0, "restart": False, "days": {"B": "tue", "A": "thu"}}
    return {**base, **kw}


def eq(**kw):
    return {**strength.DEFAULT_EQUIPMENT, **kw}


def session(weeks, n, key, equipment=None, **kw):
    out = strength.sessions_for_week(weeks[n - 1], equipment or eq(), ctx(**kw))
    return next((s for s in out if s["key"] == key), None)


def ex(sess, key):
    return next(e for e in sess["exercises"] if e["key"] == key)


def keys(sess):
    return [e["key"] for e in sess["exercises"]]


def test_thursday_build_full_dose(weeks):
    a = session(weeks, 9, "A")
    sq = ex(a, "box_squat")
    assert sq["sets"] == 3
    assert (sq["lo"], sq["hi"]) == (6, 8)
    assert sq["rpe"] == "7–8"
    assert sq["rx"] == "3 × 6–8, about 2–3 reps left (RPE 7–8)"
    assert a["reduced"] is False


@pytest.mark.parametrize("trigger", [{"wed_bad": True}, {"ankle_flag": True}, {"factor": 0.9}])
def test_thursday_trimmed_by_triggers(weeks, trigger):
    a = session(weeks, 9, "A", **trigger)
    sq = ex(a, "box_squat")
    assert sq["sets"] == 2
    assert sq["rpe"] == "≤7"
    assert a["reduced"] is True


def test_thursday_trimmed_factor_08(weeks):
    a = session(weeks, 9, "A", factor=0.8)
    sq = ex(a, "box_squat")
    assert sq["sets"] == 2
    assert sq["rpe"] == "≤6"
    assert a["reduced"] is True


def test_factor_trims_tuesday_too(weeks):
    b = session(weeks, 9, "B", factor=0.9)
    assert ex(b, "sl_rdl_db")["sets"] == 1
    assert b["reduced"] is True
    assert session(weeks, 9, "B", wed_bad=True)["reduced"] is False


@pytest.mark.parametrize("ns, lift", [((4, 5, 6), "step_up"), ((8, 9, 10), "reverse_lunge"),
                                      ((12, 13, 14, 16, 17, 18), "bulgarian_split_squat")])
def test_single_leg_fixed_per_block(weeks, ns, lift):
    for n in ns:
        a = session(weeks, n, "A")
        assert keys(a)[2] == lift, n
        assert ex(a, lift)["role"] == "single_leg"


def test_thursday_order(weeks):
    assert keys(session(weeks, 9, "A", hop_stage=1)) == [
        "hops", "box_squat", "rdl", "reverse_lunge", "calf_raise_straight", "seated_soleus_raise", "hip_thrust"]


def test_tuesday_composition(weeks):
    assert keys(session(weeks, 2, "B")) == [
        "balance_block", "sl_rdl_db", "ring_row", "push_up", "suitcase_carry", "pallof_press",
        "calf_raise_bent", "band_eversion"]
    assert "ring_push_up" in keys(session(weeks, 8, "B"))


def test_tuesday_core_rotates_by_block(weeks):
    assert keys(session(weeks, 8, "B"))[5] == "dead_bug"
    assert keys(session(weeks, 12, "B"))[5] == "side_plank"


def test_no_hops_until_stage(weeks):
    assert "hops" not in keys(session(weeks, 9, "A"))
    assert keys(session(weeks, 9, "A", hop_stage=0))[0] == "hops"


def test_fallbacks_without_rings_or_rack(weeks):
    equipment = eq(rings=False, rack=False)
    b = session(weeks, 9, "B", equipment)
    a = session(weeks, 9, "A", equipment)
    assert "db_row" in keys(b) and "ring_row" not in keys(b)
    assert "push_up" in keys(b)
    assert "goblet_squat" in keys(a) and "box_squat" not in keys(a)
    gs = ex(a, "goblet_squat")
    assert gs["load"] == "dumbbell_lower"
    assert gs["role"] == "main"


def test_taper2_and_race_week(weeks):
    taper2 = strength.sessions_for_week(weeks[19], eq(), ctx())
    assert [s["key"] for s in taper2] == ["B"]
    assert "calf_raise_bent" not in keys(taper2[0])
    assert strength.sessions_for_week(weeks[20], eq(), ctx()) == []
    taper1 = strength.sessions_for_week(weeks[18], eq(), ctx())
    assert [s["key"] for s in taper1] == ["B", "A"]
    sq = ex(taper1[1], "box_squat")
    assert (sq["sets"], sq["lo"], sq["hi"], sq["rpe"]) == (2, 4, 5, "≤7")


def test_floor_one_set(weeks):
    a = session(weeks, 7, "A", factor=0.8)
    assert weeks[6]["phase"] == "Cutback"
    assert ex(a, "box_squat")["sets"] == 1
    assert ex(a, "rdl")["sets"] == 1


def test_phase_table_pins(weeks):
    def main(n, **kw):
        sq = ex(session(weeks, n, "A", **kw), "box_squat")
        return sq["sets"], sq["lo"], sq["hi"], sq["rpe"]
    assert main(2) == (2, 8, 10, "6–7")
    assert main(7) == (2, 6, 8, "6–7")
    assert main(17) == (2, 4, 6, "7")
    assert main(9, restart=True) == (2, 8, 10, "6–7")
    calf = lambda n: ex(session(weeks, n, "A"), "calf_raise_straight")  # noqa: E731
    assert (calf(2)["sets"], calf(2)["lo"], calf(2)["hi"]) == (3, 12, 15)
    assert (calf(9)["sets"], calf(9)["lo"], calf(9)["hi"]) == (3, 8, 12)
    assert (calf(17)["sets"], calf(17)["lo"], calf(17)["hi"]) == (2, 8, 10)
    rdl = ex(session(weeks, 9, "B"), "sl_rdl_db")
    assert (rdl["sets"], rdl["lo"], rdl["hi"], rdl["rpe"]) == (2, 8, 10, "6–7")


def test_catalogue_shape():
    loads = {"barbell_lower", "barbell_upper", "dumbbell", "dumbbell_lower", "kettlebell", "bodyweight",
             "band", "rings", "timed", "hops", "carry"}
    for k, e in strength.EXERCISES.items():
        assert {"name", "cue", "load", "needs", "ankle", "per_side", "fallback", "harder"} <= e.keys(), k
        assert e["load"] in loads, k
        assert e["fallback"] is None or e["fallback"] in strength.EXERCISES, k
        assert e["harder"] is None or e["harder"] in strength.EXERCISES, k
    for k in ("calf_raise_straight", "seated_soleus_raise", "band_eversion", "balance_block", "hops",
              "step_up", "sl_rdl_db"):
        assert strength.EXERCISES[k]["ankle"] is True, k
    assert strength.EXERCISES["box_squat"]["ankle"] is False


def test_session_fields(weeks):
    for s in strength.sessions_for_week(weeks[8], eq(), ctx(hop_stage=0)):
        assert {"key", "name", "date", "day", "minutes", "reduced", "note", "warmup", "exercises"} <= s.keys()
        for e in s["exercises"]:
            assert {"key", "name", "cue", "role", "sets", "lo", "hi", "rpe", "load", "ankle", "per_side",
                    "rx"} <= e.keys()
            assert e["sets"] >= 1
