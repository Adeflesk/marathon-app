from datetime import date, datetime, timedelta
from html import unescape

import pytest
from fastapi.testclient import TestClient

from app import db, garmin_api, garmin_sync, main

SUNDAY = date(2026, 11, 1)  # week 2's long run; Saturday has an easy run


def _clear():
    db.init()
    with db.conn() as c:
        for table in ("activities", "meta", "moves", "wellness"):
            c.execute(f"DELETE FROM {table}")


def synced(day, km=10):
    with db.conn() as c:
        c.execute("INSERT INTO activities (date, km, seconds, avg_hr) VALUES (?,?,?,?)",
                  (day.isoformat(), km, int(km * 400), 140))


def wellness(day):
    with db.conn() as c:
        c.execute("INSERT OR REPLACE INTO wellness (date, rhr) VALUES (?, ?)", (day.isoformat(), 50))


def on(monkeypatch, day):
    monkeypatch.setattr(main, "today", lambda: day)


class FakeSync:
    """Stands in for garmin_sync.sync: counts calls, adds the runs in `adds`, or raises `error`."""

    def __init__(self):
        self.calls, self.adds, self.error = 0, [], None

    def __call__(self, since, **limits):
        self.calls += 1
        self.limits = limits
        if self.error:
            raise self.error
        for day in self.adds:
            synced(day)
        db.set_meta("last_sync", datetime.now().isoformat(timespec="seconds"))
        return len(self.adds)


@pytest.fixture
def fake(monkeypatch):
    _clear()
    monkeypatch.setenv("GARMIN_API_KEY", "fake")
    on(monkeypatch, SUNDAY)
    wellness(SUNDAY)
    f = FakeSync()
    monkeypatch.setattr(garmin_sync, "sync", f)
    yield f
    _clear()


class Client(TestClient):
    def text(self, path):
        return unescape(self.get(path).text)


@pytest.fixture
def client(fake):
    with Client(main.app) as c:
        yield c


def test_opening_this_week_syncs_a_missing_run(client, fake):
    synced(SUNDAY - timedelta(days=1))
    fake.adds = [SUNDAY]
    page = client.text("/")
    assert fake.calls == 1
    assert "isn't in Garmin yet" not in page
    assert fake.limits == garmin_sync.QUICK  # the page waits, so it fetches less; Sync now fetches the rest


def test_sync_now_is_a_full_sync(client, fake):
    client.post("/sync", data={"next": "/"})
    assert fake.calls == 1 and fake.limits == {}


def test_still_missing_after_the_sync_says_so(client, fake):
    synced(SUNDAY - timedelta(days=1))
    page = client.text("/")
    assert fake.calls == 1
    assert "Today's run isn't in Garmin yet." in page and 'action="/sync"' in page


def test_yesterdays_run_named_when_that_is_the_missing_one(client, fake):
    synced(SUNDAY)
    assert "Yesterday's run isn't in Garmin yet." in client.text("/")


def test_no_sync_within_15_minutes(client, fake):
    db.set_meta("last_sync", (datetime.now() - timedelta(minutes=5)).isoformat(timespec="seconds"))
    page = client.text("/")
    assert fake.calls == 0
    assert "Yesterday's and today's runs aren't in Garmin yet." in page  # the line still offers a sync
    db.set_meta("last_sync", (datetime.now() - timedelta(minutes=16)).isoformat(timespec="seconds"))
    client.get("/")
    assert fake.calls == 1


def test_no_sync_when_the_runs_are_in(client, fake):
    synced(SUNDAY)
    synced(SUNDAY - timedelta(days=1))
    page = client.text("/")
    assert fake.calls == 0 and "isn't in Garmin yet" not in page


def test_no_sync_on_a_rest_day_after_a_rest_day(client, fake, monkeypatch):
    on(monkeypatch, date(2026, 11, 6))  # Friday, after Thursday: neither day has a run
    wellness(date(2026, 11, 6))
    client.get("/")
    assert fake.calls == 0


def test_skipped_run_is_not_missing(client, fake):
    synced(SUNDAY - timedelta(days=1))
    db.save_move(SUNDAY.isoformat(), "run", None)
    client.get("/")
    assert fake.calls == 0


def test_progress_syncs_too_other_pages_do_not(client, fake):
    for path in ("/plan", "/strength", "/race", "/equipment"):
        client.get(path)
    assert fake.calls == 0
    assert "aren't in Garmin yet" in client.text("/progress")
    assert fake.calls == 1


def test_failed_sync_shows_why_and_waits_before_trying_again(client, fake):
    fake.error = garmin_api.SyncError("Garmin rejected the key.")
    assert "Sync failed: Garmin rejected the key." in client.text("/")
    client.get("/")
    assert fake.calls == 1  # a failed try counts towards the 15 minutes too


def test_no_token_no_sync(client, fake, monkeypatch):
    monkeypatch.delenv("GARMIN_API_KEY")
    client.get("/")
    assert fake.calls == 0


def test_sync_now_returns_to_the_page_it_came_from(client, fake):
    r = client.post("/sync", data={"next": "/progress"}, follow_redirects=False)
    assert r.headers["location"].startswith("/progress?msg=")
    r = client.post("/sync", data={"next": "https://example.com"}, follow_redirects=False)
    assert r.headers["location"].startswith("/?msg=")


def test_missing_wellness_today_syncs(client, fake):
    synced(SUNDAY)
    synced(SUNDAY - timedelta(days=1))
    with db.conn() as c:
        c.execute("DELETE FROM wellness")
    client.get("/")
    assert fake.calls == 1
    wellness(SUNDAY)
    db.set_meta("last_sync", (datetime.now() - timedelta(minutes=16)).isoformat(timespec="seconds"))
    client.get("/")
    assert fake.calls == 1  # today's wellness is in and so are the runs
