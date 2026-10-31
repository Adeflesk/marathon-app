from app import fuel
from app.config import DEFAULTS

STATIONS, GELS = DEFAULTS["race_stations"], DEFAULTS["race_gel_stations"]


def test_gel_minutes():
    assert fuel.gel_minutes(65) == []
    assert fuel.gel_minutes(91) == [45, 80]
    assert fuel.gel_minutes(208) == [45, 80, 115, 150, 185]
    assert fuel.gel_minutes(194) == [45, 80, 115, 150]  # 185 would fall in the last 10 minutes


def test_long_run_note():
    assert fuel.long_run_note(14, 0, 390) == "Fuel practice: a Finisher gel at 45 and 80 min (2 gels), with water."
    assert fuel.long_run_note(12, 0, 390) is None
    peak = fuel.long_run_note(32, 12, 390)
    assert "45, 80, 115, 150 and 185 min (5 gels)" in peak and "before the marathon-pace part" in peak


def test_race_plan_at_goal_pace():
    p = fuel.race_plan(341, STATIONS, GELS)
    assert p["first_pace"] == 346 and round(p["finish"]) == 14388  # 3:59:48
    half = next(x for x in p["splits"] if x["label"] == "Half")
    assert abs(half["clock"] - 7208) <= 2
    assert [(g["where"], g["station"]) for g in p["gels"]] == [
        ("carry", None), ("carry", None), ("course", 20), ("course", 25), ("course", 30), ("course", 37.5)]
    assert [round(g["km"], 1) for g in p["gels"][:2]] == [7.9, 14.0]
    assert [x["km"] for x in p["splits"]] == sorted(x["km"] for x in p["splits"])


def test_race_plan_at_a_slower_pace():
    p = fuel.race_plan(369, STATIONS, GELS)
    assert all(g["minute"] <= p["finish"] / 60 - 10 for g in p["gels"])
    course = [g["station"] for g in p["gels"] if g["where"] == "course"]
    assert len(course) == len(set(course)) and p["gels"][0]["where"] == "carry"
