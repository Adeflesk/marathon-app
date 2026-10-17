from datetime import date

from app.main import band_segments
from app.plan import generate

TODAY = date(2026, 10, 16)


def week(settings, n):
    return generate(settings, TODAY)[n - 1]["workouts"]


def test_structured_session_expands_reps(settings):
    w = next(x for x in week(settings, 8) if "steps" in x)
    segs = band_segments(w, settings["paces"])
    efforts = [s["effort"] for s in segs]
    assert efforts[0] == "easy" and efforts[-1] == "easy"
    assert efforts.count("hard") == 4 and efforts.count("rest") == 4
    assert abs(sum(s["frac"] for s in segs) - 1) < 1e-9


def test_long_run_with_mp_finish(settings):
    w = next(x for x in week(settings, 12) if x["type"] == "long")
    segs = band_segments(w, settings["paces"])
    assert [s["effort"] for s in segs] == ["easy", "steady"]
    assert abs(segs[1]["frac"] - w["mp_km"] / w["km"]) < 1e-9


def test_easy_run_and_specific_float(settings):
    easy = next(x for x in week(settings, 8) if x["type"] == "easy")
    assert [s["effort"] for s in band_segments(easy, settings["paces"])] == ["easy"]
    spec = next(x for x in week(settings, 16) if "steps" in x)
    assert [s["effort"] for s in band_segments(spec, settings["paces"])] == ["easy", "steady", "steady", "steady", "easy"]
