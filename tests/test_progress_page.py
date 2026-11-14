from datetime import date, timedelta

import pytest
from fastapi.testclient import TestClient

from app import db, main


def _clear():
    db.init()
    with db.conn() as c:
        for table in ("activities", "run_details", "strength_logs", "results", "goals", "checkins"):
            c.execute(f"DELETE FROM {table}")


@pytest.fixture
def client():
    _clear()
    with TestClient(main.app) as c:
        yield c
    _clear()


def on(monkeypatch, day):
    monkeypatch.setattr(main, "today", lambda: day)


def test_progress_page_without_a_result(client, monkeypatch):
    on(monkeypatch, date(2026, 10, 30))
    page = client.get("/progress")
    assert page.status_code == 200
    assert "Not enough to call yet" in page.text and 'href="/progress"' in page.text


def test_progress_page_with_a_stretch(client, monkeypatch):
    on(monkeypatch, date(2026, 11, 2))
    db.save_result("2026-11-01", 5.0, 1590)  # 26:30
    page = client.get("/progress").text
    assert "3:59 is a stretch" in page
    assert "predicts <strong>4:20</strong>" in page  # rounded up, like the prediction card
    assert 'name="goal" value="4:09:00"' in page and "Train for 4:09" in page


def test_goal_change_shows_on_the_page(client, monkeypatch):
    on(monkeypatch, date(2026, 11, 2))
    db.save_result("2026-11-01", 5.0, 1590)
    r = client.post("/goal", data={"goal": "4:09:00"}, follow_redirects=True)
    assert "Goal changed to 4:09" in r.text and "Back to 3:59" in r.text
    assert "from 3:59 to 4:09" in r.text


def test_this_week_shows_last_weeks_summary_monday_and_tuesday(client, monkeypatch):
    with db.conn() as c:
        c.execute("INSERT INTO activities (id, date, km, seconds, avg_hr) VALUES (1, '2026-10-25', 10, 3950, 150)")
    for day, shown in ((date(2026, 10, 26), True), (date(2026, 10, 27), True), (date(2026, 10, 28), False)):
        on(monkeypatch, day)
        page = client.get("/").text
        assert ("Last week, week 1" in page) is shown, day


def test_progress_renders_every_day(client, monkeypatch):
    db.save_result("2026-12-05", 5.0, 1530)
    day = date(2026, 10, 12)
    while day <= date(2027, 3, 21):
        on(monkeypatch, day)
        assert client.get("/progress").status_code == 200, day
        day += timedelta(days=3)


def test_cadence_chart(client, monkeypatch):
    on(monkeypatch, date(2026, 11, 14))
    assert "Cadence at easy pace" not in client.get("/progress").text
    trend = [{"week": i, "cadence": 170 + i, "stride": 1.0, "n": 5} for i in range(1, 9)]
    monkeypatch.setattr(main.progress, "cadence_trend", lambda weeks, ref: trend)
    page = client.get("/progress").text
    assert 'aria-label="Cadence at easy pace' in page and "rising over the last 4 weeks" in page


def test_steps_pattern_note(client, monkeypatch):
    on(monkeypatch, date(2026, 11, 14))
    assert "heavy day on your feet" not in client.get("/progress").text
    days = [{"date": date(2026, 11, 14) - timedelta(days=i), "on_feet": 15000, "heavy": False, "trouble": i == 3}
            for i in range(56)][::-1]
    view = {"days": days, "pattern": [date(2026, 11, 2), date(2026, 11, 10)]}
    monkeypatch.setattr(main.progress, "steps_view", lambda *a: view)
    page = client.get("/progress").text
    assert "Twice in the last 4 weeks your ankle was worse the day after a heavy day on your feet" in page
    assert "Mon 2 Nov" in page and "Tue 10 Nov" in page
    assert 'aria-label="On-feet steps' in page
    view["pattern"].append(date(2026, 11, 13))
    assert "3 times in the last 4 weeks" in client.get("/progress").text
