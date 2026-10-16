from datetime import date

import pytest

from app.config import race_date
from app.plan import generate, week_count, weekly_volumes

VARIANTS = [{}, {"base_weeks": 2}, {"peak_weekly_km": 50}, {"race_date": "2027-03-13"}, {"plan_start": "2026-12-28"},
            {"plan_start": "2026-08-10"}, {"plan_start": "2027-01-04"}, {"plan_start": "2027-01-25"}]
TODAY = date(2026, 10, 16)


def build(settings, over):
    settings.update(over)
    n = week_count(settings, TODAY)[1]
    return generate(settings, TODAY), weekly_volumes(n, settings)


@pytest.mark.parametrize("over", VARIANTS)
def test_week_totals_match(settings, over):
    weeks, vols = build(settings, over)
    for w, v in zip(weeks, vols):
        assert abs(sum(x["km"] for x in w["workouts"]) - w["target_km"]) < 0.05
        if v["phase"] != "Race week":
            assert abs(w["target_km"] - v["km"]) <= 0.5, (w["week"], w["target_km"], v["km"])


@pytest.mark.parametrize("over", VARIANTS)
def test_easy_floor(settings, over):
    weeks, vols = build(settings, over)
    run_days = settings["run_days"]
    mids = [d for d, r in run_days.items() if r != "long"]
    weights = {d: 0.4 if run_days[d] == "quality" else 0.3 for d in mids}
    for w, v in zip(weeks, vols):
        if v["phase"] == "Race week":
            continue
        rest = v["km"] - v["long"]
        floor_base = 6 if v["phase"] in ("Build", "Peak") else 5
        for x in w["workouts"]:
            if x["type"] == "easy":
                share = rest * weights[x["day"].lower()] / sum(weights.values())
                # within one 0.5 km rounding step
                assert x["km"] >= min(floor_base, share) - 0.5, (w["week"], x["day"], x["km"])


def test_quality_every_week_but_first(settings):
    weeks, _ = build(settings, {})
    assert not any("steps" in x for x in weeks[0]["workouts"])
    for w in weeks[1:]:
        assert sum("steps" in x for x in w["workouts"]) == 1, w["week"]


@pytest.mark.parametrize("over", VARIANTS)
def test_at_most_one_session(settings, over):
    weeks, _ = build(settings, over)
    assert all(sum("steps" in x for x in w["workouts"]) <= 1 for w in weeks)


@pytest.mark.parametrize("over", VARIANTS)
def test_nothing_after_race(settings, over):
    weeks, _ = build(settings, over)
    race = race_date(settings)
    assert all(x["date"] <= race for w in weeks for x in w["workouts"])
    assert not any("tempo_min" in x for w in weeks for x in w["workouts"])


def test_no_quality_day(settings):
    settings["run_days"] = {"mon": "easy", "sat": "easy", "sun": "long"}
    weeks = generate(settings, TODAY)
    assert weeks and not any("steps" in x for w in weeks for x in w["workouts"])


def test_quality_km_matches_steps(settings):
    from app.sessions import session_km
    weeks, _ = build(settings, {})
    for w in weeks:
        for x in w["workouts"]:
            if "steps" in x:
                assert abs(session_km(x["steps"], settings["paces"]) - x["km"]) <= 0.25, (w["week"], x["km"])
