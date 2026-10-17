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


def _work(x, settings):
    from app.sessions import work_km
    return work_km(x["steps"], settings["paces"])


def test_strength_block_does_not_dip_mid_block(settings):
    weeks, _ = build(settings, {})
    q = [next(x for x in weeks[w - 1]["workouts"] if "steps" in x) for w in (12, 13, 14)]
    works = [_work(x, settings) for x in q]
    assert works[1] >= works[0] - 1e-9, works


def test_cutback_session_smaller_than_block_start(settings):
    weeks, vols = build(settings, {})
    for i, v in enumerate(vols):
        if v["phase"] == "Cutback":
            first = next(j for j, u in enumerate(vols) if u["block"] == v["block"] and u["block_week"] == 0)
            cut = next(x for x in weeks[i]["workouts"] if "steps" in x)
            start = next(x for x in weeks[first]["workouts"] if "steps" in x)
            assert _work(cut, settings) < _work(start, settings), (i + 1, cut["note"], start["note"])


def test_long_run_note_has_no_trailing_zero(settings):
    weeks, _ = build(settings, {"plan_start": "2026-12-28"})
    notes = [x["note"] for w in weeks for x in w["workouts"] if x["type"] == "long"]
    assert not any(".0 km" in n for n in notes), notes


@pytest.mark.parametrize("over", VARIANTS)
def test_mp_finish_at_most_40_percent(settings, over):
    weeks, _ = build(settings, over)
    for w in weeks:
        for x in w["workouts"]:
            if x["type"] == "long" and x.get("mp_km"):
                assert x["mp_km"] <= 0.4 * x["km"] + 1e-9, (w["week"], x["km"], x["mp_km"])


def test_default_mp_finishes_unchanged(settings):
    weeks, _ = build(settings, {})
    mp = {w["week"]: x["mp_km"] for w in weeks for x in w["workouts"] if x["type"] == "long" and x.get("mp_km")}
    assert mp == {12: 6, 14: 8, 16: 10, 18: 12}


def test_no_sharpener_the_day_before_the_race(settings):
    weeks, _ = build(settings, {"race_date": "2027-03-11", "run_days": {"mon": "easy", "wed": "quality", "sat": "easy", "sun": "long"}})
    race_week = weeks[-1]
    assert not any("steps" in x for x in race_week["workouts"]), [(x["day"], x["type"]) for x in race_week["workouts"]]
