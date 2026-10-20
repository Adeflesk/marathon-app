import json
from datetime import date, timedelta

import pytest
from fastapi.testclient import TestClient

from app import ankle, db, main
from app.config import load_settings
from app.plan import generate

D0 = date(2026, 10, 19)  # plan week 1, a Monday
TABLES = ("strength_logs", "snack_logs", "ankle_tests", "ankle_checks", "checkins", "activities", "run_details")


def _clear():
    db.init()
    with db.conn() as c:
        for t in TABLES:
            c.execute(f"DELETE FROM {t}")


@pytest.fixture
def client():
    _clear()
    with TestClient(main.app) as c:
        yield c
    _clear()


def on(monkeypatch, day: date):
    monkeypatch.setattr(main, "today", lambda: day)


def session(weeks, n, key):
    return next(x for x in weeks[n - 1]["strength"] if x["key"] == key)


def exercise(sess, key):
    return next(e for e in sess["exercises"] if e["key"] == key)


def test_log_post_saves_and_redirects(client, monkeypatch):
    on(monkeypatch, D0 + timedelta(days=3))
    r = client.post("/strength/log", data={
        "date": "2026-10-22", "exercise": "rdl", "weight": "40", "level": "", "rung": "0", "target_reps": "8",
        "rep1": "10", "rep2": "9", "rep3": "", "rep4": "", "rep5": "", "rating": "right", "ankle_pain": "",
    }, follow_redirects=False)
    assert r.status_code == 303
    assert r.headers["location"] == "/#ex-rdl"
    [row] = db.logs("rdl")
    assert row["date"] == "2026-10-22" and row["weight_kg"] == 40.0
    assert row["reps"] == [10, 9] and row["target_reps"] == 8 and row["rating"] == "right"
    assert row["ankle_pain"] is None and row["level"] is None and row["created"]


def test_logged_exercise_shows_done_and_next_suggestion(client, monkeypatch):
    thu = D0 + timedelta(days=3)
    on(monkeypatch, thu)
    client.post("/strength/log", data={"date": thu.isoformat(), "exercise": "rdl", "weight": "40", "rung": "0",
                                       "target_reps": "8", "rep1": "10", "rep2": "10", "rating": "easy"})
    _, weeks = main.build_view()
    today_rdl = exercise(session(weeks, 1, "A"), "rdl")
    assert today_rdl["log"]["weight_kg"] == 40.0 and today_rdl["log"]["rating"] == "easy"
    nxt = exercise(session(weeks, 2, "A"), "rdl")
    assert nxt["log"] is None
    assert nxt["suggestion"]["weight"] == 45.0  # one 5 kg step up from an easy 40 kg at the top of the range
    page = client.get("/")
    assert page.context["strength_session"]["key"] == "A"


def test_snack_toggle_post(client, monkeypatch):
    mon = D0
    on(monkeypatch, mon)
    _, weeks = main.build_view()
    snack = weeks[0]["snack"][mon]
    assert snack["items"] == ankle.BALANCE_STAGES[0] and snack["done"] == set()
    assert sorted(weeks[0]["snack"]) == [D0 + timedelta(days=n) for n in (0, 2, 4, 5)]  # Mon, Wed, Fri, Sat
    r = client.post("/snack", data={"date": mon.isoformat(), "item": "eyes_open_stance"}, follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/#snack"
    _, weeks = main.build_view()
    assert weeks[0]["snack"][mon]["done"] == {"eyes_open_stance"}
    assert client.get("/").context["snack_today"]["done"] == {"eyes_open_stance"}
    client.post("/snack", data={"date": mon.isoformat(), "item": "eyes_open_stance"})
    assert db.snacks() == []
    # race week: only the first two items
    assert len(weeks[-1]["snack"][weeks[-1]["start"]]["items"]) == 2


def test_morning_check_post_raises_flag(client, monkeypatch):
    fri = D0 + timedelta(days=4)
    on(monkeypatch, fri)
    db.save_log({"date": (fri - timedelta(days=1)).isoformat(), "exercise": "calf_raise_straight",
                 "weight_kg": 10.0, "reps": [12, 12], "target_reps": 12, "rating": "right"})
    page = client.get("/")
    assert page.context["morning_check"] is True and page.context["ankle_flag"] is None
    r = client.post("/ankle/check", data={"date": fri.isoformat(), "worse": "1", "note": "stiff"},
                    follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/#ankle-check"
    assert db.checks() == [{"date": fri.isoformat(), "worse": 1, "note": "stiff"}]
    page = client.get("/")
    assert page.context["morning_check"] is False
    assert page.context["ankle_flag"] == fri + timedelta(days=7)
    _, weeks = main.build_view()
    assert session(weeks, 2, "A")["reduced"] is True  # the following Thursday
    assert session(weeks, 3, "A")["reduced"] is False  # the flag is down by then


def test_wed_bad_trims_thursday(client, monkeypatch):
    s = load_settings()
    wk8 = generate(s, D0)[7]
    q = next(x for x in wk8["workouts"] if "steps" in x)
    on(monkeypatch, q["date"])
    _, weeks = main.build_view()
    assert session(weeks, 8, "A")["reduced"] is False
    laps = [{"lapType": "warmup", "endDuration": 800, "endDistance": 2.0}]
    dur, dist = 800, 2.0
    for _ in range(4):  # every rep about 75 s/km slow
        dur, dist = dur + 400, dist + 1.0
        laps.append({"lapType": "work", "endDuration": dur, "endDistance": dist})
        dur, dist = dur + 60, dist + 0.15
        laps.append({"lapType": "recovery", "endDuration": dur, "endDistance": dist})
    with db.conn() as c:
        c.execute("INSERT INTO activities VALUES (902, ?, 7.6, 3200, 150)", (q["date"].isoformat(),))
        c.execute("INSERT INTO run_details VALUES (902, ?, ?)",
                  (json.dumps([{"distance": 1.0, "seconds": 400, "heartRate": 140}]), json.dumps(laps)))
    _, weeks = main.build_view()
    assert next(x for x in weeks[7]["workouts"] if "steps" in x)["review"]["verdict"] == "bad"
    thu = session(weeks, 8, "A")
    assert thu["reduced"] is True and "Wednesday" in thu["note"]
    assert session(weeks, 9, "A")["reduced"] is False


def test_tests_post_and_due_clears(client, monkeypatch):
    on(monkeypatch, D0 + timedelta(days=1))
    page = client.get("/")
    assert page.context["tests_due"] is True
    assert page.context["injured_side"] == "right" and page.context["hop_stage"] is None
    data = {"date": D0.isoformat(), "pogo_trial_injured": "1", "pogo_trial_other": "",
            "calf_raises_injured": "22", "calf_raises_other": "27",
            "eyes_closed_balance_injured": "18", "eyes_closed_balance_other": "30",
            "y_balance_ant_injured": "60", "y_balance_ant_other": "70",
            "y_balance_pm_injured": "85", "y_balance_pm_other": "100",
            "y_balance_pl_injured": "85", "y_balance_pl_other": "100",
            "single_hop_injured": "", "single_hop_other": ""}
    r = client.post("/ankle/tests", data=data, follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/#tests"
    rows = {t["test"]: t for t in db.tests()}
    assert set(rows) == {"pogo_trial", "calf_raises", "eyes_closed_balance", "y_balance_ant", "y_balance_pm",
                         "y_balance_pl"}
    assert rows["pogo_trial"]["other"] is None and rows["calf_raises"]["other"] == 27.0
    page = client.get("/")
    assert page.context["tests_due"] is False
    assert page.context["hop_stage"] == 0  # pain-free pogo trial yesterday, fine morning


GOOD_LOG = {"date": "2026-10-22", "exercise": "rdl", "weight": "40", "rung": "0", "target_reps": "8",
            "rep1": "10", "rep2": "10", "rating": "right"}


@pytest.mark.parametrize("change", [
    {"date": "notadate"},
    {"date": "2026-10-23"},  # tomorrow
    {"exercise": "zzz"},
    {"rating": "zzz"},
    {"rating": None},
    {"rep1": "ten"},
])
def test_bad_log_rejected(client, monkeypatch, change):
    on(monkeypatch, D0 + timedelta(days=3))
    data = {k: v for k, v in {**GOOD_LOG, **change}.items() if v is not None}
    r = client.post("/strength/log", data=data, follow_redirects=False)
    assert r.status_code == 303 and "msg=" in r.headers["location"]
    assert db.logs() == []
    assert client.get("/").status_code == 200


@pytest.mark.parametrize("path,data,read", [
    ("/snack", {"date": "notadate", "item": "eyes_open_stance"}, db.snacks),
    ("/snack", {"date": "2026-10-19", "item": "zzz"}, db.snacks),
    ("/ankle/check", {"date": "notadate", "worse": "1"}, db.checks),
    ("/ankle/tests", {"date": "notadate", "calf_raises_injured": "20"}, db.tests),
    ("/ankle/tests", {"date": "2026-10-19", "calf_raises_injured": "x"}, db.tests),
])
def test_bad_ankle_posts_rejected(client, monkeypatch, path, data, read):
    on(monkeypatch, D0 + timedelta(days=3))
    r = client.post(path, data=data, follow_redirects=False)
    assert r.status_code == 303 and "msg=" in r.headers["location"]
    assert read() == []
    assert client.get("/").status_code == 200


# --- Task 7: the cards on This week and the history on Strength ---

def page(client, monkeypatch, day: date) -> str:
    on(monkeypatch, day)
    r = client.get("/")
    assert r.status_code == 200
    return r.text


def test_strength_card_is_hero_on_tuesday(client, monkeypatch):
    html = page(client, monkeypatch, D0 + timedelta(days=1))  # Tuesday: Strength B, no run
    assert 'id="strength"' in html
    assert html.index('id="strength"') < html.index('id="today-h"')
    card = html[html.index('id="strength"'):html.index('id="today-h"')]
    assert "<h1" in card and "Today, Tuesday 20 October" in card
    assert "0 of " in card and " done" in card
    first = next(e for e in session(main.build_view()[1], 1, "B")["exercises"])
    assert f'<details class="ex" id="ex-{first["key"]}" open' in card  # the first undone one is open
    assert card.count(" open>") == 1
    assert 'name="rating" value="easy"' in card and ">Right<" in card and ">Hard<" in card


def test_strength_card_below_run_hero(client, monkeypatch, tmp_path):
    from app import config
    path = tmp_path / "settings.json"
    path.write_text(json.dumps({"strength_days": {"B": "mon"}}))
    monkeypatch.setattr(config, "SETTINGS_PATH", path)
    html = page(client, monkeypatch, D0)  # Monday: easy run and Strength B
    assert html.index('id="today-h"') < html.index('id="strength"')
    card = html[html.index('id="strength"'):]
    assert "<h1" not in card


def test_card_shows_last_and_suggestion(client, monkeypatch):
    on(monkeypatch, D0 + timedelta(days=3))
    client.post("/strength/log", data={"date": "2026-10-22", "exercise": "rdl", "weight": "50", "rung": "0",
                                       "target_reps": "8", "rep1": "10", "rep2": "10", "rating": "easy"})
    thu2 = D0 + timedelta(days=10)
    html = page(client, monkeypatch, thu2)
    ex = html[html.index('id="ex-rdl"'):]
    ex = ex[:ex.index("</details>")]
    assert "last time 50 kg" in ex and "Try 55 kg" in ex
    assert 'name="weight"' in ex and 'value="55"' in ex and 'step="2.5"' in ex and 'min="20"' in ex
    assert 'name="rep1"' in ex and 'value="8"' in ex
    # a done row collapses to a one-line summary
    client.post("/strength/log", data={"date": thu2.isoformat(), "exercise": "rdl", "weight": "55", "rung": "0",
                                       "target_reps": "8", "rep1": "8", "rep2": "8", "rating": "right"})
    html = client.get("/").text
    ex = html[html.index('id="ex-rdl"'):]
    ex = ex[:ex.index("</details>")]
    assert "Barbell Romanian deadlift 55 kg, 2 × 8, right" in ex
    assert "1 of " in html


def test_ankle_item_has_pain_select(client, monkeypatch):
    html = page(client, monkeypatch, D0 + timedelta(days=3))
    ex = html[html.index('id="ex-calf_raise_straight"'):]
    ex = ex[:ex.index("</details>")]
    assert '<select' in ex and 'name="ankle_pain"' in ex and '<option value="10"' in ex
    rdl = html[html.index('id="ex-rdl"'):]
    assert 'name="ankle_pain"' not in rdl[:rdl.index("</details>")]


def test_snack_card_on_ankle_day(client, monkeypatch):
    html = page(client, monkeypatch, D0)  # Monday is an ankle day
    assert 'id="snack"' in html and 'action="/snack"' in html
    assert html.index('id="today-h"') < html.index('id="snack"')
    for x in ankle.BALANCE_STAGES[0]:
        assert x["name"] in html and f'name="item" value="{x["item"]}"' in html
    assert "0 of 3 done" in html
    client.post("/snack", data={"date": D0.isoformat(), "item": "eyes_open_stance"})
    assert "1 of 3 done" in client.get("/").text
    assert 'id="snack"' not in page(client, monkeypatch, D0 + timedelta(days=1))  # Tuesday isn't


def test_morning_check_shown_after_thursday(client, monkeypatch):
    thu = D0 + timedelta(days=3)
    assert 'id="ankle-check"' not in page(client, monkeypatch, thu)
    db.save_log({"date": thu.isoformat(), "exercise": "calf_raise_straight", "weight_kg": None,
                 "reps": [12, 12], "target_reps": 12, "rating": "right"})
    html = page(client, monkeypatch, thu + timedelta(days=1))
    assert 'id="ankle-check"' in html and 'action="/ankle/check"' in html
    assert html.index('id="ankle-check"') < html.index('id="today-h"')
    assert ">Fine<" in html and ">Worse than usual<" in html
    client.post("/ankle/check", data={"date": (thu + timedelta(days=1)).isoformat(), "worse": "1"})
    html = client.get("/").text
    assert 'id="ankle-check"' not in html
    assert "Ankle flag until Friday 30 October: no increases on ankle work." in html


def test_test_card_in_week_1(client, monkeypatch):
    tue = D0 + timedelta(days=1)
    html = page(client, monkeypatch, tue)
    assert 'id="tests"' in html and 'action="/ankle/tests"' in html
    assert html.index('id="today-h"') < html.index('id="tests"') or html.index('id="strength"') < html.index('id="tests"')
    for key in ("pogo_trial_injured", "calf_raises_injured", "calf_raises_other", "y_balance_pl_other"):
        assert f'name="{key}"' in html
    assert 'name="single_hop_injured"' not in html  # hop tests only from hop stage 2
    assert "Right (injured)" in html and "Left" in html
    data = {"date": tue.isoformat(), "pogo_trial_injured": "0"}
    for key in ankle.CORE_TESTS:
        data[f"{key}_injured"], data[f"{key}_other"] = "20", "25"
    client.post("/ankle/tests", data=data)
    assert 'id="tests"' not in client.get("/").text
    assert 'id="tests"' not in page(client, monkeypatch, D0 + timedelta(days=8))  # week 2 isn't a test week


def test_history_on_strength_page(client, monkeypatch):
    on(monkeypatch, D0 + timedelta(days=10))
    for day, kg, rating in (("2026-10-22", "50", "easy"), ("2026-10-29", "55", "right")):
        client.post("/strength/log", data={"date": day, "exercise": "rdl", "weight": kg, "rung": "0",
                                           "target_reps": "8", "rep1": "8", "rep2": "8", "rating": rating})
    r = client.get("/strength?week=2")
    assert r.status_code == 200
    assert [x["date"] for x in r.context["history"]["rdl"]] == ["2026-10-29", "2026-10-22"]
    html = r.text
    h = html[html.index('id="history"'):]
    assert "Barbell Romanian deadlift" in h and "55 kg" in h and "8, 8" in h and "Right" in h and "Easy" in h
    assert "Thu 29 Oct" in h


def test_time_off_holds_through_the_session(client, monkeypatch):
    """Logging the first lift after a long gap doesn't undo the time-off drop for the rest of the session."""
    thu = D0 + timedelta(weeks=8, days=3)  # week 9 Thursday
    old = (thu - timedelta(days=42)).isoformat()
    for key in ("box_squat", "rdl"):
        db.save_log({"date": old, "exercise": key, "weight_kg": 60, "level": None, "rung": 0, "reps": [8, 8, 8],
                     "target_reps": 8, "rating": "easy", "ankle_pain": None, "created": ""})
    on(monkeypatch, thu)
    db.save_log({"date": thu.isoformat(), "exercise": "box_squat", "weight_kg": 47.5, "level": None, "rung": 0,
                 "reps": [8, 8], "target_reps": 8, "rating": "right", "ankle_pain": None, "created": ""})
    _, weeks = main.build_view()
    a = session(weeks, 9, "A")
    assert exercise(a, "rdl")["suggestion"]["weight"] == 47.5  # still about 80% of 60 kg
    assert exercise(a, "box_squat")["suggestion"]["weight"] == 47.5  # today's log isn't cut by 80% again
