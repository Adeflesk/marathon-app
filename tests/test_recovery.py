from datetime import date, timedelta

from app import recovery

START = date(2026, 10, 1)  # a Thursday
EASY = 360.0  # settings easy pace, s/km
IN, LOW = 60, 40  # nightly HRV against a 50–70 ms band


def nights(hrvs, start=START, avgs=None, rhr=None, sleep=None, score=None):
    """Wellness rows on consecutive days from `start`; a None HRV is a missing night (row kept, all NULL)."""
    rows = []
    for i, h in enumerate(hrvs):
        rows.append({"date": (start + timedelta(days=i)).isoformat(), "hrv_night": h,
                     "hrv_week_avg": (avgs[i] if avgs else (None if h is None else 60)),
                     "hrv_low": 50, "hrv_high": 70,
                     "rhr": rhr[i] if rhr else (None if h is None else 48),
                     "sleep_s": sleep[i] if sleep else (None if h is None else 8 * 3600),
                     "sleep_score": score[i] if score else (None if h is None else 80),
                     "stress_avg": None, "weight_kg": None})
    return rows


def day(n):
    return START + timedelta(days=n)


def easy(n, hr=140, drift=3.0, in_band=6):
    """An easy run on day n: km 1 (dropped) plus `in_band` km at easy pace, then 2 km well off it."""
    sp = [{"km": 1.0, "pace": EASY + 30, "hr": 120}]
    sp += [{"km": 1.0, "pace": EASY, "hr": hr} for _ in range(in_band)]
    sp += [{"km": 1.0, "pace": EASY - 60, "hr": 175} for _ in range(2)]
    return {"date": day(n), "kind": "easy", "splits": sp, "drift": drift, "verdict": None}


def quality(n, verdict):
    return {"date": day(n), "kind": "quality", "splits": None, "drift": None, "verdict": verdict}


BASE = [easy(2), easy(5), easy(8)]  # three steady easy runs at 140 bpm before the episode
LOW3 = [IN] * 10 + [LOW] * 3  # episode starts on day 12
EP = day(12)


def state(rows, runs=(), trims=(), t=None):
    return recovery.state(rows, list(runs), list(trims), t or date.fromisoformat(rows[-1]["date"]), EASY)


def test_two_low_nights_nothing():
    s = state(nights([IN] * 10 + [LOW] * 2))
    assert s["phase"] == "none" and s["since"] is None and s["offer"] is None


def test_three_low_nights_suspect():
    s = state(nights(LOW3), BASE)
    assert s["phase"] == "suspect" and s["since"] == EP and s["run"] is None
    assert s["reasons"] == ["HRV below your normal range 3 nights running"]
    assert s["offer"] is None


def test_low_week_average_suspect():
    rows = nights([IN] * 10 + [52], avgs=[60] * 10 + [48])
    s = state(rows)
    assert s["phase"] == "suspect" and s["since"] == day(10)
    assert s["reasons"] == ["7-day HRV average below your normal range"]


def test_gap_breaks_the_run_and_doesnt_clear():
    assert state(nights([IN] * 10 + [LOW, None, LOW, LOW]))["phase"] == "none"
    s = state(nights([IN] * 10 + [LOW, None, LOW, LOW, LOW]))
    assert s["phase"] == "suspect" and s["since"] == day(14)
    # missing nights after the start are neither low nor in band: the episode stays open
    s = state(nights(LOW3 + [None, None, IN]))
    assert s["phase"] == "suspect" and s["since"] == EP
    # a missing row (no row at all) is the same as a NULL night
    rows = nights(LOW3) + nights([IN], start=day(16))
    assert state(rows)["phase"] == "suspect"


def test_normal_run_note():
    s = state(nights(LOW3 + [LOW]), BASE + [easy(13, hr=141)])
    assert s["phase"] == "note" and s["run"]["date"] == day(13)
    assert "Wednesday's run looked normal" in s["reasons"]
    assert s["offer"] is None
    # a run before the episode started is not checked
    assert state(nights(LOW3), BASE + [easy(11, hr=150)])["phase"] == "suspect"


def test_raised_easy_hr_confirms_advice():
    s = state(nights(LOW3 + [LOW]), BASE + [easy(13, hr=146)])
    assert s["phase"] == "advice" and s["run"]["date"] == day(13)
    assert "easy-pace heart rate up 6 bpm on Wednesday's run" in s["reasons"]
    assert s["reasons"][0] == "HRV below your normal range 3 nights running"
    assert s["offer"] == "trim" and not s["trim_taken"]
    # under 5 bpm up is normal
    assert state(nights(LOW3 + [LOW]), BASE + [easy(13, hr=144)])["phase"] == "note"
    # with fewer than 2 earlier runs, heart rate can't confirm
    assert state(nights(LOW3 + [LOW]), [easy(8), easy(13, hr=150)])["phase"] == "note"


def test_drift_confirms_only_when_usually_steady():
    s = state(nights(LOW3 + [LOW]), BASE + [easy(13, drift=12.0)])
    assert s["phase"] == "advice"
    assert any("drift" in r and "Wednesday's run" in r for r in s["reasons"])
    drifty = [easy(2, drift=7.0), easy(5, drift=7.0), easy(8, drift=7.0)]
    assert state(nights(LOW3 + [LOW]), drifty + [easy(13, drift=12.0)])["phase"] == "note"
    assert state(nights(LOW3 + [LOW]), BASE + [easy(13, drift=9.0)])["phase"] == "note"


def test_bad_quality_confirms():
    s = state(nights(LOW3 + [LOW]), BASE + [quality(13, "bad")])
    assert s["phase"] == "advice" and s["run"]["kind"] == "quality"
    assert any("Wednesday's session" in r for r in s["reasons"])
    assert state(nights(LOW3 + [LOW]), BASE + [quality(13, "ok")])["phase"] == "note"
    assert state(nights(LOW3 + [LOW]), BASE + [quality(13, None)])["phase"] == "suspect"


def test_strides_and_thin_runs_skipped():
    strides = dict(easy(13, hr=160), kind="strides")
    assert state(nights(LOW3 + [LOW]), BASE + [strides])["phase"] == "suspect"
    thin = easy(13, hr=160, in_band=2)
    assert state(nights(LOW3 + [LOW]), BASE + [thin])["phase"] == "suspect"
    # the next run that can be judged is checked instead
    s = state(nights(LOW3 + [LOW, LOW]), BASE + [thin, easy(14, hr=146)])
    assert s["phase"] == "advice" and s["run"]["date"] == day(14)


def test_firm_after_three_nights():
    runs = BASE + [easy(13, hr=146)]
    assert state(nights(LOW3 + [LOW, LOW, LOW]), runs)["phase"] == "advice"  # 2 nights after the run
    s = state(nights(LOW3 + [LOW, LOW, LOW, LOW]), runs)  # 3 nights after
    assert s["phase"] == "firm" and s["run"]["date"] == day(13)
    # missing nights don't count
    assert state(nights(LOW3 + [LOW, LOW, None, LOW]), runs)["phase"] == "advice"


def test_firm_after_two_runs():
    rows = nights(LOW3 + [LOW])
    runs = BASE + [easy(13, hr=146)]
    assert state(rows, runs + [easy(14)], t=day(14))["phase"] == "advice"
    s = state(rows, runs + [easy(14), quality(15, "ok")], t=day(15))
    assert s["phase"] == "firm"
    # skipped runs don't count
    strides = dict(easy(15), kind="strides")
    assert state(rows, runs + [easy(14), strides], t=day(15))["phase"] == "advice"


def test_two_in_band_nights_and_avg_clear():
    runs = BASE + [easy(13, hr=146)]
    assert state(nights(LOW3 + [LOW, IN]), runs)["phase"] == "advice"
    s = state(nights(LOW3 + [LOW, IN, IN]), runs)
    assert s["phase"] == "none" and s["since"] is None and s["run"] is None and s["offer"] is None
    # nights in band but the 7-day average still low: not cleared
    rows = nights(LOW3 + [LOW, IN, IN], avgs=[60] * 10 + [55, 52, 50, 48, 49, 49])
    assert state(rows, runs)["phase"] == "advice"


def test_offer_trim_once_per_episode():
    rows, runs = nights(LOW3 + [LOW]), BASE + [easy(13, hr=146)]
    s = state(rows, runs, [{"date": day(13).isoformat(), "kind": "trim"}])
    assert s["trim_taken"] and s["offer"] is None
    # a trim from before this episode doesn't count
    s = state(rows, runs, [{"date": day(3).isoformat(), "kind": "trim"}])
    assert not s["trim_taken"] and s["offer"] == "trim"


def test_offer_easy_only_firm_after_trim():
    trim = {"date": day(13).isoformat(), "kind": "trim"}
    runs = BASE + [easy(13, hr=146)]
    advice, firm = nights(LOW3 + [LOW]), nights(LOW3 + [LOW] * 4)
    assert state(advice, runs, [trim])["offer"] is None
    assert state(firm, runs)["offer"] == "trim"
    s = state(firm, runs, [trim])
    assert s["phase"] == "firm" and s["offer"] == "easy" and not s["easy_taken"]
    s = state(firm, runs, [trim, {"date": day(15).isoformat(), "kind": "easy"}])
    assert s["easy_taken"] and s["offer"] is None


def test_new_episode_after_clear_offers_trim_again():
    trim = {"date": day(13).isoformat(), "kind": "trim"}
    rows = nights(LOW3 + [LOW, IN, IN, IN, LOW, LOW, LOW])  # clears day 15, new episode day 19
    runs = BASE + [easy(13, hr=146), easy(19, hr=147)]
    s = state(rows, runs, [trim])
    assert s["phase"] == "advice" and s["since"] == day(19)
    assert not s["trim_taken"] and s["offer"] == "trim"


def test_rest_when_firm_with_support():
    hrvs = LOW3 + [LOW] * 4
    runs = BASE + [easy(13, hr=146)]
    rhr = [48] * 16 + [55]
    s = state(nights(hrvs, rhr=rhr), runs)
    assert s["phase"] == "firm" and s["rest"]
    assert s["support"] == ["Resting heart rate is up 7 bpm"]
    assert not state(nights(hrvs), runs)["rest"]
    advice = state(nights(LOW3 + [LOW], rhr=[48] * 13 + [55]), runs)
    assert advice["phase"] == "advice" and advice["support"] and not advice["rest"]


def test_support_never_starts_an_episode():
    n = 32
    rows = nights([IN] * n, rhr=[46] * (n - 1) + [56], sleep=[8 * 3600] * (n - 2) + [5 * 3600] * 2)
    s = state(rows)
    assert s["phase"] == "none" and not s["rest"]
    assert s["support"] == ["Resting heart rate is up 10 bpm", "Short or poor sleep two nights running"]
    # a poor score counts as well as short sleep; one night isn't enough
    rows = nights([IN] * 5, score=[80, 80, 80, 55, 58])
    assert state(rows)["support"] == ["Short or poor sleep two nights running"]
    rows = nights([IN] * 5, score=[80, 80, 80, 80, 58])
    assert state(rows)["support"] == []


def test_ignores_data_after_today_and_returns_last_row():
    rows = nights(LOW3 + [LOW])
    s = state(rows, BASE + [easy(13, hr=146)], t=day(12))
    assert s["phase"] == "suspect" and s["last"]["date"] == day(12).isoformat()
    assert state([], [], t=day(0)) == {
        "phase": "none", "since": None, "reasons": [], "support": [], "run": None, "trim_taken": False,
        "easy_taken": False, "offer": None, "rest": False, "last": None}
