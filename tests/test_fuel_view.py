from datetime import date

import pytest
from fastapi.testclient import TestClient

from app import db, main


def _clear():
    db.init()
    with db.conn() as c:
        for table in ("activities", "run_details", "checkins", "moves", "fuel_logs"):
            c.execute(f"DELETE FROM {table}")


@pytest.fixture
def client(monkeypatch):
    _clear()
    monkeypatch.setattr(main, "today", lambda: date(2026, 10, 31))
    with TestClient(main.app) as c:
        yield c
    _clear()


def on(monkeypatch, day):
    monkeypatch.setattr(main, "today", lambda: day)


def long_run(weeks, n):
    return next(wo for wo in weeks[n - 1]["workouts"] if wo["type"] == "long")


def test_long_run_notes_on_the_plan(client):
    _, weeks = main.build_view()
    assert all(long_run(weeks, n)["fuel"] is None for n in (1, 2, 3, 4, 7))
    assert "(2 gels)" in long_run(weeks, 5)["fuel"]
    peak = long_run(weeks, 18)["fuel"]
    assert "(5 gels)" in peak and "marathon-pace part" in peak
    assert all(wo["fuel"] is None for w in weeks for wo in w["workouts"] if wo["type"] != "long")


def test_trimmed_long_run_follows_its_km(client):
    with db.conn() as c:
        c.execute("INSERT INTO checkins (week, feel, pain, note, created) VALUES (4, 3, 5, '', 'x')")
    _, weeks = main.build_view()
    lr = long_run(weeks, 5)
    assert lr["km"] == 11 and lr["fuel"] is None


def test_race_has_no_long_run_note(client):
    _, weeks = main.build_view()
    assert all(wo["fuel"] is None for wo in weeks[-1]["workouts"])


def test_note_shows_on_this_week_and_plan(client, monkeypatch):
    on(monkeypatch, date(2026, 11, 16))
    assert "Fuel practice:" in client.get("/").text
    assert "Fuel: 2 gels" in client.get("/plan").text


# --- fuelled as planned ---

from app import progress  # noqa: E402


def synced(day, km, id_):
    with db.conn() as c:
        c.execute("INSERT INTO activities (id, date, km, seconds, avg_hr) VALUES (?,?,?,?,?)",
                  (id_, day, km, int(km * 390), 145))


def fuelled(day):
    _, weeks = main.build_view()
    return [wo["fuelled"] for w in weeks for wo in w["workouts"] if wo["type"] == "long" and wo["date"] == day]


def test_tick_and_untick(client, monkeypatch):
    synced("2026-11-22", 14, 1)
    on(monkeypatch, date(2026, 11, 23))
    assert client.post("/fuel", data={"date": "2026-11-22"}, follow_redirects=False).status_code == 303
    assert fuelled(date(2026, 11, 22)) == [True]
    client.post("/fuel", data={"date": "2026-11-22"})
    assert fuelled(date(2026, 11, 22)) == [False]


def test_tick_refused_without_a_long_run(client, monkeypatch):
    synced("2026-11-19", 5, 2)
    on(monkeypatch, date(2026, 11, 23))
    for day in ("2026-11-19", "2026-11-29", "soon"):
        client.post("/fuel", data={"date": day})
    assert db.fuel_days() == set()


def test_tick_follows_a_moved_long_run(client, monkeypatch):
    db.save_move("2026-11-22", "run", "2026-11-23")
    synced("2026-11-23", 14, 3)
    on(monkeypatch, date(2026, 11, 24))
    client.post("/fuel", data={"date": "2026-11-23"})
    assert fuelled(date(2026, 11, 23)) == [True]


def test_summary_and_progress_count(client, monkeypatch):
    synced("2026-11-22", 14, 1)
    on(monkeypatch, date(2026, 11, 23))

    def week5():
        s, weeks = main.build_view()
        return next(x for x in progress.summaries(weeks, s, weeks[0]["ankle_state"], [], date(2026, 11, 23))
                    if x["week"] == 5)
    assert "No fuel logged on the long run." in week5()["sentences"]
    client.post("/fuel", data={"date": "2026-11-22"})
    assert "Fuelled as planned." in week5()["sentences"]
    assert "Fuel practice: 1 of 1 long runs" in client.get("/progress").text
