from datetime import date

import pytest
from fastapi.testclient import TestClient

from app import db, main


def _clear():
    db.init()
    with db.conn() as c:
        for table in ("goals", "results"):
            c.execute(f"DELETE FROM {table}")


@pytest.fixture
def client(monkeypatch):
    _clear()
    monkeypatch.setattr(main, "today", lambda: date(2026, 10, 31))
    with TestClient(main.app) as c:
        yield c
    _clear()


def test_race_page(client):
    page = client.get("/race")
    assert page.status_code == 200
    for text in ("5:46/km", "3:59:48", "Carry", "km 20", "From recent editions: check the 2027 course guide",
                 "Nothing new on race day", "Take carried gels just before a station"):
        assert text in page.text, text


def test_race_page_follows_the_goal(client):
    client.post("/goal", data={"goal": "4:09:00"})
    page = client.get("/race").text
    assert "5:54/km" in page and "4:09" in page


def test_race_link_from_taper_on(client, monkeypatch):
    assert 'href="/race"' not in client.get("/").text
    monkeypatch.setattr(main, "today", lambda: date(2027, 2, 22))
    assert 'href="/race"' in client.get("/").text
    assert 'href="/race"' in client.get("/plan").text


@pytest.mark.parametrize("day, heading", [
    (date(2026, 10, 10), "21 weeks to Barcelona"),  # before the plan starts: all of it
    (date(2026, 11, 27), "16 weeks to Barcelona"),  # week 6 of 21: this week and the 15 after it
    (date(2027, 3, 1), "2 weeks to Barcelona"),
    (date(2027, 3, 10), "Race week"),
])
def test_plan_counts_down_the_weeks(client, monkeypatch, day, heading):
    monkeypatch.setattr(main, "today", lambda: day)
    assert f'<h1 class="display">{heading}</h1>' in client.get("/plan").text
