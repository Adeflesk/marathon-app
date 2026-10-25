from datetime import date

import pytest
from fastapi.testclient import TestClient

from app import db, main

MON_W2 = date(2026, 10, 26)  # Monday of plan week 2
SUN_W1 = date(2026, 10, 25)


def _clear():
    db.init()
    with db.conn() as c:
        c.execute("DELETE FROM checkins")


@pytest.fixture
def client():
    _clear()
    with TestClient(main.app) as c:
        yield c
    _clear()


def on(monkeypatch, day):
    monkeypatch.setattr(main, "today", lambda: day)


def _checkin(client, week, pain, feel=3, note=""):
    return client.post("/checkin", data={"week": week, "feel": feel, "pain": pain, "note": note},
                       follow_redirects=False)


def _factor(week):
    _, weeks = main.build_view()
    return weeks[week - 1]["factor"]


def test_last_weeks_checkin_editable_after_rollover(client, monkeypatch):
    on(monkeypatch, SUN_W1)
    _checkin(client, 1, 10, note="typo")
    on(monkeypatch, MON_W2)
    assert _factor(2) == 0.8
    html = client.get("/").text
    assert 'id="prev-checkin"' in html
    assert "Change last week" in html
    # the earlier form is pre-filled with the wrong value and the note
    assert 'id="prev-pain10" value="10" checked' in html
    assert "typo" in html
    r = _checkin(client, 1, 2, note="typo")
    assert r.status_code == 303 and "#prev-checkin" not in r.headers["location"]
    assert _factor(2) == 1.0


def test_no_prev_checkin_in_week_1(client, monkeypatch):
    on(monkeypatch, SUN_W1)
    assert 'id="prev-checkin"' not in client.get("/").text


def test_trim_notice_links_to_change(client, monkeypatch):
    on(monkeypatch, SUN_W1)
    _checkin(client, 1, 6)
    on(monkeypatch, MON_W2)
    html = client.get("/").text
    assert "Trimmed to 80%" in html
    assert 'href="#prev-checkin"' in html


@pytest.mark.parametrize("data", [
    {"week": 1, "feel": 3, "pain": 11}, {"week": 1, "feel": 0, "pain": 2},
    {"week": 1, "feel": 6, "pain": 2}, {"week": 1, "feel": 3, "pain": -1}, {"week": 99, "feel": 3, "pain": 2},
])
def test_out_of_range_checkin_not_saved(client, monkeypatch, data):
    on(monkeypatch, SUN_W1)
    r = client.post("/checkin", data=data, follow_redirects=False)
    assert r.status_code == 303
    with db.conn() as c:
        assert c.execute("SELECT COUNT(*) FROM checkins").fetchone()[0] == 0
