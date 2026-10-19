from datetime import date, timedelta

from app import strength
from app.progression import available_weights, step, suggest

TODAY = date(2026, 10, 22)


def eq(**kw):
    return {**strength.DEFAULT_EQUIPMENT, **kw}


def ex(key, role, lo, hi, sets=3):
    e = strength.EXERCISES[key]
    return {"key": key, "name": e["name"], "cue": e["cue"], "role": role, "sets": sets, "lo": lo, "hi": hi,
            "rpe": "7–8", "load": e["load"], "ankle": e["ankle"], "per_side": e["per_side"], "rx": ""}


def log(weight, reps, rating, days_ago=7, rung=0, target=None, level=None, exercise="rdl"):
    return {"date": (TODAY - timedelta(days=days_ago)).isoformat(), "exercise": exercise, "weight_kg": weight,
            "level": level, "rung": rung, "reps": reps, "target_reps": target or max(reps),
            "rating": rating, "ankle_pain": None, "created": None}


def ctx(history=(), **kw):
    last = date.fromisoformat(history[0]["date"]) if history else None
    return {"phase": "Build", "cutback": False, "factor": 1.0, "ankle_flag": False, "last_any_log": last, **kw}


def run(e, history, equipment=None, **kw):
    history = list(history)
    return suggest(e, history, ctx(history, **kw), equipment or eq(), TODAY)


RDL = ex("rdl", "main", 6, 8)


# --- the rating-to-next-session table, one row each ---

def test_easy_all_top_steps_up():
    s = run(RDL, [log(50, [8, 8, 8], "easy")])
    assert (s["weight"], s["reps"], s["rung"]) == (55, 6, 0)
    assert s["warmup"] == []
    assert "50 kg" in s["reason"] and "55 kg" in s["reason"]


def test_easy_twice_two_steps():
    s = run(RDL, [log(50, [8, 8, 8], "easy"), log(45, [8, 8, 8], "easy", days_ago=14)])
    assert (s["weight"], s["reps"]) == (60, 6)


def test_easy_not_top_adds_reps():
    s = run(RDL, [log(50, [6, 6, 6], "easy")])
    assert (s["weight"], s["reps"]) == (50, 8)
    # within one rep of the top: +1 step and back to the bottom
    s = run(RDL, [log(50, [7, 7, 8], "easy")])
    assert (s["weight"], s["reps"]) == (55, 6)


def test_right_all_top():
    s = run(RDL, [log(50, [8, 8, 8], "right")])
    assert (s["weight"], s["reps"]) == (55, 6)


def test_right_not_top():
    s = run(RDL, [log(50, [7, 6, 6], "right")])
    assert (s["weight"], s["reps"]) == (50, 7)


def test_hard_completed_repeats():
    s = run(RDL, [log(50, [7, 7, 7], "hard", target=7), log(50, [7, 7, 7], "right", days_ago=14)])
    assert (s["weight"], s["reps"]) == (50, 7)


def test_hard_missed_steps_down():
    s = run(RDL, [log(50, [8, 6, 5], "hard", target=8)])
    assert (s["weight"], s["reps"]) == (45, 6)


def test_second_hard_steps_down():
    s = run(RDL, [log(50, [7, 7, 7], "hard", target=7), log(50, [7, 7, 6], "hard", days_ago=14, target=7)])
    assert (s["weight"], s["reps"]) == (45, 6)


# --- top weight ladder ---

def test_kettlebell_top_extends_reps():
    kb = ex("sl_rdl_kb", "tue_lift", 8, 12, sets=2)
    s = run(kb, [log(16, [12, 12], "easy", exercise="sl_rdl_kb")])
    assert (s["weight"], s["reps"], s["rung"]) == (16, 14, 1)


def test_db_35_at_top_goes_to_tempo():
    bss = ex("bulgarian_split_squat", "single_leg", 6, 8)
    s = run(bss, [log(35, [8, 8, 8], "right", exercise="bulgarian_split_squat")])
    assert (s["weight"], s["rung"], s["reps"]) == (35, 1, 9)
    s = run(bss, [log(35, [12, 12, 12], "right", rung=1, exercise="bulgarian_split_squat")])
    assert (s["weight"], s["rung"], s["reps"], s["level"]) == (35, 2, 6, "3–4 s lowering")
    s = run(bss, [log(35, [8, 8, 8], "right", rung=2, exercise="bulgarian_split_squat")])
    assert (s["rung"], s["reps"], s["level"]) == (3, 6, "2–3 s pause")


def test_ladder_harder_variation_for_bodyweight():
    pu = ex("push_up", "tue_upper", 8, 10, sets=2)
    s = run(pu, [log(None, [10, 10], "right", exercise="push_up")])
    assert (s["weight"], s["rung"], s["reps"]) == (None, 1, 11)
    s = run(pu, [log(None, [10, 10], "right", rung=3, exercise="push_up")])
    assert s["rung"] == 4 and s["reps"] == 8
    assert s["level"] == strength.EXERCISES["ring_push_up"]["name"]


def test_kettlebell_12_to_16_gate():
    kb = ex("sl_rdl_kb", "tue_lift", 8, 12, sets=2)
    k = {"exercise": "sl_rdl_kb"}
    s = run(kb, [log(12, [12, 12], "easy", **k)])
    assert (s["weight"], s["rung"], s["reps"]) == (12, 1, 14)
    s = run(kb, [log(12, [14, 14], "right", rung=1, **k)])
    assert (s["weight"], s["reps"]) == (12, 15)
    s = run(kb, [log(12, [15, 15], "easy", rung=1, **k)])
    assert (s["weight"], s["rung"], s["reps"]) == (16, 0, 8)
    s = run(kb, [log(12, [16, 16], "right", rung=1, **k)])
    assert s["weight"] == 12 and s["rung"] == 2


# --- overrides ---

def test_cutback_never_increases():
    s = run(RDL, [log(50, [8, 8, 8], "easy"), log(45, [8, 8, 8], "easy", days_ago=14)],
            phase="Cutback", cutback=True)
    assert s["weight"] == 50
    s = run(RDL, [log(50, [8, 6, 5], "hard", target=8)], phase="Cutback", cutback=True)
    assert s["weight"] == 45
    for phase in ("Taper", "Taper 1"):
        assert run(RDL, [log(50, [8, 8, 8], "easy")], phase=phase)["weight"] == 50


def test_factor_08_steps_down():
    s = run(RDL, [log(50, [8, 8, 8], "right")], factor=0.8)
    assert s["weight"] == 45
    s = run(RDL, [log(50, [8, 8, 8], "right")], factor=0.9)
    assert s["weight"] == 50


def test_peak_main_holds():
    s = run(ex("rdl", "main", 4, 6, sets=2), [log(70, [6, 6], "easy")], phase="Peak")
    assert s["weight"] == 70
    row = ex("db_row", "tue_upper", 8, 10, sets=2)
    s = run(row, [log(20, [10, 10], "easy", exercise="db_row")], phase="Peak")
    assert s["weight"] == 21.25


def test_ankle_flag_holds_ankle_items_only():
    calf = ex("calf_raise_straight", "calf", 8, 12)
    s = run(calf, [log(10, [12, 12, 12], "easy", exercise="calf_raise_straight")], ankle_flag=True)
    assert s["weight"] == 10
    bent = ex("calf_raise_bent", "tue_calf", 10, 15, sets=2)
    s = run(bent, [log(None, [15, 15], "easy", exercise="calf_raise_bent")], ankle_flag=True)
    assert s["rung"] == 0
    s = run(RDL, [log(50, [8, 8, 8], "easy")], ankle_flag=True)
    assert s["weight"] == 55


# --- first session, time off, equipment changes ---

def test_first_session_warmup_ladder():
    s = run(RDL, [])
    assert s["warmup"] == [20, 30, 40]
    assert (s["weight"], s["reps"], s["rung"]) == (None, 6, 0)
    assert run(ex("db_rdl", "main", 6, 8), [])["warmup"] == [5, 7.5, 10]
    assert run(ex("sl_rdl_kb", "tue_lift", 8, 10), [])["warmup"] == [12]
    assert run(ex("push_up", "tue_upper", 8, 10), [])["warmup"] == []
    calf = ex("calf_raise_straight", "calf", 8, 12)
    s = run(calf, [], equipment=eq(dumbbells=False))
    assert s["warmup"] == [] and s["weight"] is None and s["reps"] == 8


def test_calf_raise_without_dumbbells_uses_reps():
    calf = ex("calf_raise_straight", "calf", 8, 12)
    s = run(calf, [log(None, [10, 10, 10], "easy", exercise="calf_raise_straight")], equipment=eq(dumbbells=False))
    assert (s["weight"], s["reps"]) == (None, 12)
    # a stale weight from before the dumbbells went is ignored rather than suggested
    s = run(calf, [log(10, [12, 12, 12], "right", exercise="calf_raise_straight")], equipment=eq(dumbbells=False))
    assert s["weight"] is None and s["rung"] == 1


def test_time_off_11_to_28_days():
    s = run(RDL, [log(50, [8, 8, 8], "easy", days_ago=14)])
    assert (s["weight"], s["reps"]) == (45, 6)
    s = run(RDL, [log(50, [8, 8, 8], "easy", days_ago=10)])
    assert s["weight"] == 55


def test_time_off_over_28_days():
    assert run(RDL, [log(50, [8, 8, 8], "easy", days_ago=35)])["weight"] == 40
    assert run(RDL, [log(72.5, [8, 8, 8], "right", days_ago=29)])["weight"] == 57.5


def test_suggestion_snaps_to_available():
    d = ex("db_rdl", "main", 6, 8)
    s = run(d, [log(35, [7, 6, 6], "right", exercise="db_rdl")], equipment=eq(db_max_kg=30.0))
    assert s["weight"] == 30


# --- helpers ---

def test_available_weights():
    assert available_weights(RDL, eq())[:3] == [20, 22.5, 25]
    assert available_weights(RDL, eq(barbell=False)) == []
    dbs = available_weights(ex("db_rdl", "main", 6, 8), eq())
    assert dbs[0] == 2.5 and dbs[-1] == 35 and dbs[1] == 3.75
    assert available_weights(ex("sl_rdl_kb", "tue_lift", 8, 10), eq()) == [12, 16]
    assert available_weights(ex("push_up", "tue_upper", 8, 10), eq()) == []


def test_step_sizes():
    e = eq()
    assert step(50, RDL, e, 1, "Build") == 55
    assert step(60, RDL, e, 1, "Build") == 62.5
    assert step(50, RDL, e, 1, "Peak") == 52.5
    assert step(50, RDL, e, -1, "Build") == 45
    assert step(20, RDL, e, -1, "Build") == 20
    assert step(40, {**RDL, "load": "barbell_upper"}, e, 1, "Build") == 42.5
    lunge = ex("reverse_lunge", "single_leg", 6, 8)
    assert step(15, lunge, e, 1, "Build") == 16.25
    assert step(15, lunge, e, 2, "Build") == 20
    assert step(20, ex("db_row", "tue_upper", 8, 10), e, 2, "Build") == 22.5
    assert step(35, ex("db_row", "tue_upper", 8, 10), e, 1, "Build") == 35
    kb = ex("sl_rdl_kb", "tue_lift", 8, 10)
    assert step(12, kb, e, 1, "Build") == 16 and step(16, kb, e, 1, "Build") == 16


def test_timed_and_carry_stay_in_range():
    core = ex("pallof_press", "core", 30, 40, sets=2)
    s = run(core, [log(None, [40, 40], "easy", exercise="pallof_press")])
    assert (s["reps"], s["rung"], s["level"]) == (40, 0, None)
    assert "40 s" in s["reason"]
    s = run(core, [log(None, [30, 30], "easy", exercise="pallof_press")])
    assert s["reps"] == 32
    assert run(ex("hops", "hops", 10, 15), [log(None, [15, 15, 15], "easy", exercise="hops")])["reps"] == 10
