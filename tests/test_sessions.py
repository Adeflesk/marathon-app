from datetime import date

from app import sessions
from app.plan import _half, week_count, weekly_volumes

CAPS = {"tempo": 0.12, "subthreshold": 0.18, "marathon": 0.18}

THRESHOLD = [
    {"label": "WU", "km": 2, "pace": "easy", "intensity": "warmup"},
    {"repeat": 4, "steps": [
        {"label": "Rep", "km": 1.6, "pace": "tempo", "intensity": "active"},
        {"label": "Jog", "seconds": 60, "pace": None, "intensity": "recovery"},
    ]},
    {"label": "CD", "km": 1, "pace": "easy", "intensity": "cooldown"},
]


def plan_sessions(settings, max_km=99):
    n = week_count(settings, date(2026, 10, 16))[1]
    vols = weekly_volumes(n, settings)
    return vols, [sessions.quality_session(v, i, settings, max_km) for i, v in enumerate(vols)]


def repeats(steps):
    return [st for st in steps if "repeat" in st]


def test_session_km_expands_repeats(settings):
    assert abs(sessions.session_km(THRESHOLD, settings["paces"]) - (3 + 6.4 + 4 * 60 / 405)) < 0.01


def test_work_km_excludes_recovery(settings):
    assert abs(sessions.work_km(THRESHOLD, settings["paces"]) - 6.4) < 1e-9


def test_menu_types(settings):
    _, ss = plan_sessions(settings)
    by_week = {w: (ss[w - 1] or {}).get("type") for w in (1, 2, 4, 7, 8, 12, 16, 19, 20, 21)}
    assert by_week == {1: None, 2: "strides", 4: "fartlek", 7: "fartlek", 8: "threshold", 12: "strength",
                       16: "specific", 19: "strength", 20: "mp", 21: "mp"}
    assert repeats(ss[6]["steps"])[0]["repeat"] == 5
    assert ss[18]["hard"] is False and ss[19]["hard"] is False and ss[20]["hard"] is False
    assert ss[7]["hard"] is True and ss[15]["hard"] is True


def test_caps_hold(settings):
    vols, ss = plan_sessions(settings)
    for v, sess in zip(vols, ss):
        if sess and sess["pace"] in CAPS and v["phase"] != "Race week":  # race week's sharpener is fixed
            assert sessions.work_km(sess["steps"], settings["paces"]) <= CAPS[sess["pace"]] * v["km"] + 0.01, sess["note"]


def test_max_km_respected(settings):
    vols, ss = plan_sessions(settings, max_km=9)
    for sess in ss:
        if sess and sess["type"] not in ("strides",):
            assert sessions.session_km(sess["steps"], settings["paces"]) <= 9 + 0.01 or min(
                r["repeat"] for r in repeats(sess["steps"]) or [{"repeat": 2}]) == 2


def test_reps_floor(settings):
    for max_km in (99, 7):
        _, ss = plan_sessions(settings, max_km)
        for sess in ss:
            for r in repeats(sess["steps"]) if sess else []:
                assert r["repeat"] >= 2


def test_scale_session(settings):
    w = {"type": "strength", "steps": [
        {"label": "WU", "km": 2, "pace": "easy", "intensity": "warmup"},
        {"repeat": 6, "steps": [{"label": "Rep", "km": 1.6, "pace": "subthreshold", "intensity": "active"},
                                {"label": "Jog", "km": 0.4, "pace": None, "intensity": "recovery"}]},
        {"label": "CD", "km": 1, "pace": "easy", "intensity": "cooldown"}]}
    w["km"] = _half(sessions.session_km(w["steps"], settings["paces"]))
    w["note"] = sessions.describe(w["steps"], settings["paces"])
    before = (w["km"], w["note"])
    sessions.scale_session(w, 0.8, settings["paces"])
    assert repeats(w["steps"])[0]["repeat"] == 5  # round(6 × 0.8)
    assert w["km"] == _half(sessions.session_km(w["steps"], settings["paces"])) and w["km"] < before[0]
    assert w["note"] != before[1] and "5 × 1.6 km" in w["note"]


def test_scale_session_shortens_when_reps_cannot_drop(settings):
    w = {"type": "threshold", "steps": [
        {"label": "WU", "km": 2, "pace": "easy", "intensity": "warmup"},
        {"repeat": 2, "steps": [{"label": "Rep", "km": 2.4, "pace": "tempo", "intensity": "active"},
                                {"label": "Jog", "seconds": 120, "pace": None, "intensity": "recovery"}]},
        {"label": "CD", "km": 1, "pace": "easy", "intensity": "cooldown"}]}
    sessions.scale_session(w, 0.8, settings["paces"])
    assert repeats(w["steps"])[0]["repeat"] == 2 and repeats(w["steps"])[0]["steps"][0]["km"] == 1.6


def test_describe(settings):
    note = sessions.describe(THRESHOLD, settings["paces"])
    assert "× 1.6 km at 5:25" in note and "60 s jog" in note and note.startswith("2 km WU")


def test_fit_keeps_most_work(settings):
    # wk 14 (52 km): 3 × 3.2 km is over the 18% cap; 3 × 2.4 km keeps more work than 2 × 3.2 km
    _, ss = plan_sessions(settings)
    assert "3 × 2.4 km" in ss[13]["note"]


def test_mp_reps_note_says_goal_pace(settings):
    _, ss = plan_sessions(settings)
    for s in (ss[19], ss[20]):  # taper week 2 and race week
        rep = next(st for st in s["steps"] if "repeat" in st)["steps"][0]
        assert rep["note"] == "At goal pace."
