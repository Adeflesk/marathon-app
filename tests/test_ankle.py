from datetime import date, timedelta

from app import ankle, strength
from app.plan import generate

D0 = date(2026, 10, 19)  # a Monday, plan week 1


def d(n):
    return (D0 + timedelta(days=n)).isoformat()


def log(day, exercise="calf_raise_straight", pain=None):
    return {"date": d(day), "exercise": exercise, "weight_kg": 10.0, "level": None, "rung": 0, "reps": [10, 10],
            "target_reps": 10, "rating": "right", "ankle_pain": pain, "created": None}


def check(day, worse=True):
    return {"date": d(day), "worse": int(worse), "note": ""}


def tst(day, name, injured, other=None):
    return {"date": d(day), "test": name, "injured": injured, "other": other}


def snack(day, item="eyes_open_stance"):
    return {"date": d(day), "item": item}


GOOD_1 = [tst(0, "calf_raises", 26, 27), tst(0, "y_balance_ant", 60, 70),
          tst(0, "y_balance_pm", 85, 100), tst(0, "y_balance_pl", 85, 100)]
GOOD_2 = [tst(0, "y_balance_ant", 64, 70), tst(0, "y_balance_pm", 92, 100), tst(0, "y_balance_pl", 92, 100),
          tst(0, "single_hop", 130, 150), tst(0, "triple_hop", 400, 450)]
TRIAL = tst(0, "pogo_trial", 1)


WEEKLY = [log(n, "rdl") for n in range(0, 400, 7)]  # regular non-ankle sessions: no gap, no pain


def hop(day, tests, checks=(), logs=WEEKLY, checkins=(), weeks=()):
    return ankle.hop_stage(D0 + timedelta(days=day), tests, checks, logs, checkins, weeks)


def bal(day, snacks, tests=(), checks=(), hop_st=None, logs=(), checkins=(), weeks=()):
    return ankle.balance_stage(D0 + timedelta(days=day), snacks, tests, checks, hop_st, logs, checkins, weeks)


def weeks(settings):
    return generate(settings, D0)


# --- flag ---

def test_flag_expiry_and_scope():
    today = D0 + timedelta(days=10)
    # a worse check lasts 7 days from its date
    assert ankle.flag_until(today, [check(5)], [], [], []) == D0 + timedelta(days=12)
    assert ankle.flag_until(today, [check(2)], [], [], []) is None
    assert ankle.flag_until(today, [check(8, worse=False)], [], [], []) is None
    # pain >= 3 on an ankle item raises it; on a non-ankle item it does not
    assert ankle.flag_until(today, [], [log(9, pain=3)], [], []) == D0 + timedelta(days=16)
    assert not strength.EXERCISES["rdl"]["ankle"]
    assert ankle.flag_until(today, [], [log(9, "rdl", pain=6)], [], []) is None
    # pain higher than the same item's previous log, even below 3 (logs come newest first)
    rising = [log(9, pain=2), log(6, pain=1)]
    assert ankle.flag_until(today, [], rising, [], []) == D0 + timedelta(days=16)
    steady = [log(9, pain=1), log(6, pain=1), log(6, "hops", pain=0)]
    assert ankle.flag_until(today, [], steady, [], []) is None
    # the latest expiry wins
    assert ankle.flag_until(today, [check(5)], [log(9, pain=4)], [], []) == D0 + timedelta(days=16)


def test_flag_from_checkin(settings):
    ws = weeks(settings)
    # week 1 ends Sunday 25 Oct; pain 3 flags until 1 Nov
    ci = [{"week": 1, "feel": 3, "pain": 3, "note": "", "created": "x"}]
    assert ankle.flag_until(date(2026, 10, 28), [], [], ci, ws) == date(2026, 11, 1)
    assert ankle.flag_until(date(2026, 11, 2), [], [], ci, ws) is None
    low = [{"week": 1, "feel": 3, "pain": 2, "note": "", "created": "x"}]
    assert ankle.flag_until(date(2026, 10, 28), [], [], low, ws) is None


def test_morning_check_due_after_thursday():
    thu, fri = D0 + timedelta(days=3), D0 + timedelta(days=4)
    logs = [log(3, "calf_raise_bent"), log(3, "rdl")]
    assert ankle.morning_check_due(fri, logs, [])
    assert not ankle.morning_check_due(fri, logs, [check(4, worse=False)])
    assert not ankle.morning_check_due(thu, logs, [])
    assert not ankle.morning_check_due(fri, [log(3, "rdl"), log(3, "band_eversion")], [])
    for ex in ("hops", "calf_raise_straight", "seated_soleus_raise"):
        assert ankle.morning_check_due(fri, [log(3, ex)], [])


# --- tests schedule ---

def test_test_weeks_default(settings):
    ws = weeks(settings)
    assert ankle.test_weeks(ws) == {1, 4, 7, 11, 15}
    w1, w2 = ws[0], ws[1]
    assert ankle.tests_due(w1, ws, [])
    assert not ankle.tests_due(w2, ws, [])
    core = [tst(1, k, 10, 10) for k in ("calf_raises", "eyes_closed_balance", "y_balance_ant",
                                          "y_balance_pm", "y_balance_pl")]
    assert ankle.tests_due(w1, ws, core)  # week 1 also needs the pogo trial
    assert not ankle.tests_due(w1, ws, core + [tst(1, "pogo_trial", 0)])
    assert set(ankle.TESTS) == {"pogo_trial", "calf_raises", "eyes_closed_balance", "y_balance_ant",
                                "y_balance_pm", "y_balance_pl", "single_hop", "triple_hop"}


# --- hop stage ---

def test_hop_stage_not_yet_without_trial():
    today = D0 + timedelta(days=20)
    assert hop(20, [], []) is None
    assert hop(20, GOOD_1, []) is None
    assert hop(20, [tst(0, "pogo_trial", 3)], []) is None  # painful trial
    assert hop(20, [TRIAL], [check(1)]) is None  # worse the next morning
    assert hop(0, [TRIAL]) is None  # next morning not here yet
    assert hop(1, [TRIAL], []) == 0


def test_hop_stage_progression():
    tests = [TRIAL] + GOOD_1 + GOOD_2
    assert hop(13, tests, []) == 0
    assert hop(14, tests, []) == 1
    assert hop(27, tests, []) == 1
    assert hop(28, tests, []) == 2
    assert hop(42, tests, []) == 3
    assert hop(90, tests, []) == 3
    assert len(strength.HOP_STAGES) == 4


def test_hop_stage_held_by_failed_gate():
    weak_calf = [TRIAL, tst(0, "calf_raises", 20, 27)] + GOOD_1[1:]
    assert hop(40, weak_calf, []) == 1
    # a passing re-test on day 30 opens the gate from then
    retest = weak_calf + [tst(30, "calf_raises", 26, 27)]
    assert hop(29, retest, []) == 1
    assert hop(30, retest, []) == 2
    # Y-balance below 80% of the other side holds stage 1 too
    weak_y = [TRIAL] + GOOD_1[:3] + [tst(0, "y_balance_pl", 70, 100)]
    assert hop(40, weak_y, []) == 1
    # no other-side value means the gate can't be checked
    assert hop(40, [TRIAL, tst(0, "calf_raises", 30)] + GOOD_1[1:], []) == 1
    # stage 2 -> 3 needs the hop tests
    assert hop(60, [TRIAL] + GOOD_1, []) == 2
    # a flag blocks a step that would otherwise happen
    assert hop(14, [TRIAL] + GOOD_1, [], logs=[log(10, pain=4)]) == 0


def test_worse_drops_stage():
    tests = [TRIAL] + GOOD_1 + GOOD_2
    assert hop(30, tests, [check(30)]) == 1
    assert hop(16, tests, [check(16)]) == 0
    assert hop(5, tests, [check(5)]) == 0  # never below 0
    # 14 more days in the dropped stage before it climbs again
    assert hop(43, tests, [check(30)]) == 1
    assert hop(44, tests, [check(30)]) == 2
    # more than 28 days with no logs or tests: "not yet" until a fresh trial
    assert hop(60, tests, [], logs=[log(20)]) is None
    fresh = tests + [tst(55, "pogo_trial", 0)]
    assert hop(60, fresh, [], logs=[log(20)]) == 0
    assert hop(60, tests, [], logs=[log(20), log(45)]) == 3


def test_logged_pain_drops_stage():
    tests = [TRIAL] + GOOD_1 + GOOD_2
    assert hop(30, tests) == 2
    assert hop(30, tests, logs=WEEKLY + [log(30, pain=3)]) == 1
    assert hop(30, tests, logs=WEEKLY + [log(30, "rdl", pain=8)]) == 2  # not an ankle item
    # a worse check and painful log on the same day drop only one stage
    assert hop(30, tests, [check(30)], logs=WEEKLY + [log(30, pain=5)]) == 1


def test_rising_pain_drops_stage():
    tests = [TRIAL] + GOOD_1 + GOOD_2
    assert hop(30, tests, logs=WEEKLY + [log(25, pain=1), log(30, pain=2)]) == 1
    assert hop(30, tests, logs=WEEKLY + [log(25, pain=1), log(30, pain=1)]) == 2
    # the previous log of that item, not of another ankle item
    assert hop(30, tests, logs=WEEKLY + [log(25, "hops", pain=0), log(30, pain=2)]) == 2


def test_falling_calf_raise_test_drops_stage():
    tests = [TRIAL] + GOOD_1 + GOOD_2
    assert hop(30, tests + [tst(30, "calf_raises", 26, 27)]) == 2  # same count: no drop
    assert hop(30, tests + [tst(30, "calf_raises", 25, 27)]) == 1


def test_hop_held_by_checkin_pain(settings):
    ws = weeks(settings)
    ci = [{"week": 2, "feel": 3, "pain": 3, "note": "", "created": "x"}]  # flag from Sun day 13 to day 20
    tests = [TRIAL] + GOOD_1
    assert hop(14, tests, weeks=ws) == 1
    assert hop(20, tests, checkins=ci, weeks=ws) == 0  # held, not dropped
    assert hop(21, tests, checkins=ci, weeks=ws) == 1


def test_balance_held_by_logged_pain_flag():
    four = [snack(n) for n in (1, 3, 5, 8)]
    assert bal(15, four) == 1
    assert bal(15, four, logs=[log(12, pain=4)]) == 0
    assert bal(19, four, logs=[log(12, pain=4)]) == 0
    assert bal(20, four, logs=[log(12, pain=4)]) == 1


# --- balance stage ---

def test_balance_stage_needs_snacks_and_eyes_closed():
    four = [snack(n) for n in (1, 3, 5, 8)]
    assert bal(20, [], [], [], None) == 0
    assert bal(20, four[:3], [], [], None) == 0
    assert bal(15, four, [], [], None) == 1
    # 1 -> 2 needs 4 more snack days and a 30 s eyes-closed test
    more = four + [snack(n) for n in (16, 18, 20, 22)]
    assert bal(40, more, [], [], None) == 1
    ok = [tst(10, "eyes_closed_balance", 30, 35)]
    assert bal(40, more, ok, [], None) == 2
    assert bal(40, more, [tst(10, "eyes_closed_balance", 25, 35)],
                               [], None) == 1
    # a flag holds the stage
    assert bal(15, four, [], [check(12)], None) == 0
    # all the way: 5 -> 6 waits for hop stage 2
    every = [snack(n) for n in range(1, 200, 2)]
    assert bal(199, every, ok, [], 1) == 5
    assert bal(199, every, ok, [], 2) == 6
    assert len(ankle.BALANCE_STAGES) == 7
    for items in ankle.BALANCE_STAGES:
        assert all({"item", "name", "dose", "cue"} <= set(i) for i in items)
        assert 8 <= sum(i["minutes"] for i in items) <= 10


# --- restart ---

def test_restart_after_gap():
    today = D0 + timedelta(days=60)
    assert not ankle.restart(today, [], [])
    assert not ankle.restart(today, [log(55)], [])
    assert ankle.restart(today, [log(20)], [])  # 40 days off
    # first two sessions back are restart sessions; the third is not
    assert ankle.restart(today, [log(58), log(20)], [])
    assert not ankle.restart(today, [log(59), log(58), log(20)], [])
    # a worse morning in the last 7 days restarts too, until 2 sessions have passed
    assert ankle.restart(today, [log(56), log(50)], [check(55)])
    assert not ankle.restart(today, [log(59), log(57), log(50)], [check(55)])
    assert not ankle.restart(today, [log(50)], [check(50)])  # 10 days ago
