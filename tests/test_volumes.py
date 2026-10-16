from datetime import date

import pytest

from app.plan import week_count, weekly_volumes

ORDER = ["general", "threshold", "strength", "specific"]
VARIANTS = [{}, {"base_weeks": 2}, {"peak_weekly_km": 50}, {"race_date": "2027-03-13"}, {"plan_start": "2026-12-28"}]


def vols_for(settings, **over):
    settings.update(over)
    n = week_count(settings, date(2026, 10, 16))[1]
    return weekly_volumes(n, settings)


def week(vols, w):
    return vols[w - 1]


def test_default_phases(settings):
    vols = vols_for(settings)
    expected = (["Rebuild"] * 3 + ["Build"] * 3 + ["Cutback"] + ["Build"] * 3 + ["Cutback"]
                + ["Build"] * 3 + ["Cutback"] + ["Peak"] * 3 + ["Taper"] * 2 + ["Race week"])
    assert [v["phase"] for v in vols] == expected


def test_default_km(settings):
    vols = vols_for(settings)
    assert [v["km"] for v in vols[:20]] == [25, 25, 25, 28, 31, 34, 27, 37, 40, 43, 34, 46, 49, 52, 42, 55, 58, 60, 45, 33]


def test_blocks(settings):
    vols = vols_for(settings)
    for weeks, name in [((4, 5, 6), "general"), ((8, 9, 10), "threshold"), ((12, 13, 14), "strength"), ((16, 17, 18), "specific")]:
        assert [week(vols, w)["block"] for w in weeks] == [name] * 3
        assert [week(vols, w)["block_week"] for w in weeks] == [0, 1, 2]
    assert [week(vols, w)["block"] for w in (7, 11, 15)] == ["general", "threshold", "strength"]
    assert all(week(vols, w)["block_week"] is None for w in (1, 7, 19, 21))
    assert all(week(vols, w)["block"] is None for w in (1, 2, 3, 19, 20, 21))


def test_peak_long_runs(settings):
    vols = vols_for(settings)
    assert [week(vols, w)["long"] for w in (16, 17, 18)] == [28, 24, 32]


def test_mp_weeks(settings):
    vols = vols_for(settings)
    assert {i + 1: v["mp_km"] for i, v in enumerate(vols) if v["mp_km"] > 0} == {12: 6, 14: 8, 16: 10, 18: 12}


@pytest.mark.parametrize("over", VARIANTS)
def test_long_run_invariants(settings, over):
    vols = vols_for(settings, **over)
    longs = [v["long"] for v in vols]
    build_idx = [i for i, v in enumerate(vols) if v["phase"] in ("Build", "Peak")]
    last_build = build_idx[-1]
    for a, b in zip(longs, longs[1:]):
        assert not (a >= 30 and b >= 30)
    for i, lg in enumerate(longs):
        assert lg <= 32
        if lg >= 20 and i != last_build and i >= 1:
            assert lg <= 1.1 * max(longs[max(0, i - 4):i]) + 1e-9, (i + 1, lg)
    first_taper = next(i for i, v in enumerate(vols) if v["phase"] == "Taper")
    assert vols[first_taper - 1]["phase"] != "Cutback"
    assert [v["block"] for v in vols if v["block"]][-1] == "specific"
    tail = [v["km"] for v in vols[first_taper - 1:]]
    assert all(a > b for a, b in zip(tail, tail[1:])), tail


def test_short_plan_drops_early_blocks(settings):
    vols = vols_for(settings, plan_start="2027-01-04")
    assert len(vols) == 10
    present = list(dict.fromkeys(v["block"] for v in vols if v["block"]))
    assert present == ORDER[len(ORDER) - len(present):]
