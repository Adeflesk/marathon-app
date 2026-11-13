import io
import json
import zipfile
from datetime import date

import httpx
import pytest

from app import db, garmin_sync

REAL_CLIENT = httpx.Client
SEARCH = "/activitylist-service/activities/search/activities"


def run(i, day, metres, time="07:00:00", type_key="running"):
    return {"activityId": i, "startTimeLocal": f"{day} {time}", "distance": metres, "duration": 3000.4,
            "averageHR": 141.6, "activityType": {"typeId": 1, "typeKey": type_key}}


def zip_of(i):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr(f"{i}_ACTIVITY.fit", b"FIT" + str(i).encode())
    return buf.getvalue()


@pytest.fixture
def garmin(monkeypatch):
    """A fake Garmin: set .runs; .calls lists data paths; .bad is a set of ids whose FIT can't be read."""
    class G:
        runs, calls, bad = [], [], set()
    g = G()
    g.runs, g.calls, g.bad = [], [], set()

    def handler(req):
        if "token" in req.url.path:
            return httpx.Response(200, json={"access_token": "t", "expires_in": 86400})
        g.calls.append(req.url.path)
        if req.url.path == SEARCH:
            start, limit = int(req.url.params["start"]), int(req.url.params["limit"])
            return httpx.Response(200, json=g.runs[start:start + limit])
        i = int(req.url.path.rsplit("/", 1)[1])
        return httpx.Response(200, content=zip_of(i))

    def fake_details(data):
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            i = int(z.namelist()[0].split("_")[0])
        if i in g.bad:
            raise ValueError("corrupt")
        return {"splits": [{"km": 1, "seconds": 300 + i % 7}], "laps": []}

    monkeypatch.setenv("GARMIN_API_KEY", "k")
    monkeypatch.setattr(garmin_sync.fitfile, "details", fake_details)
    db.init()
    with db.conn() as c:
        for t in ("activities", "run_details", "run_files", "run_source", "meta"):
            c.execute(f"DELETE FROM {t}")
    g.client = REAL_CLIENT(transport=httpx.MockTransport(handler))
    return g


def sync(g, max_details=40):
    return garmin_sync.sync_runs(g.client, date(2026, 11, 1), max_details)


def rows():
    with db.conn() as c:
        return [dict(r) for r in c.execute("SELECT * FROM activities ORDER BY id")]


def test_runs_saved_with_km_and_local_date(garmin):
    garmin.runs = [run(1, "2026-11-12", 10050.0, "23:30:00"), run(2, "2026-11-12", 20000, type_key="cycling")]
    assert sync(garmin) == 1
    (r,) = rows()
    assert (r["id"], r["date"], r["seconds"], r["avg_hr"]) == (1, "2026-11-12", 3000, 142)
    assert r["km"] == pytest.approx(10.05)
    with db.conn() as c:
        assert c.execute("SELECT source FROM run_source WHERE id = 1").fetchone()[0] == "garmin"


def test_details_fetched_once_newest_first(garmin):
    garmin.runs = [run(1, "2026-11-10", 5000), run(2, "2026-11-12", 6000), run(3, "2026-11-11", 7000)]
    sync(garmin, max_details=1)
    assert set(db.run_details([1, 2, 3])) == {2}
    sync(garmin)
    assert set(db.run_details([1, 2, 3])) == {1, 2, 3}
    n = len(garmin.calls)
    sync(garmin)
    assert [p for p in garmin.calls[n:] if p != SEARCH] == []


def test_fit_stored(garmin):
    garmin.runs = [run(7, "2026-11-12", 5000)]
    sync(garmin)
    with db.conn() as c:
        assert c.execute("SELECT fit FROM run_files WHERE id = 7").fetchone()[0] == b"FIT7"


def test_bad_fit_retried_next_sync(garmin):
    garmin.runs = [run(1, "2026-11-10", 5000), run(2, "2026-11-12", 6000)]
    garmin.bad = {2}
    assert sync(garmin) == 2
    assert set(db.run_details([1, 2])) == {1}
    with db.conn() as c:
        assert c.execute("SELECT COUNT(*) FROM run_files WHERE id = 2").fetchone()[0] == 0
    garmin.bad = set()
    sync(garmin)
    assert set(db.run_details([1, 2])) == {1, 2}


def add_smashrun(i, day, km):
    with db.conn() as c:
        c.execute("INSERT INTO activities(id, date, km, seconds, avg_hr) VALUES (?,?,?,?,?)", (i, day, km, 3000, 140))
        c.execute("INSERT INTO run_details(id, splits, laps) VALUES (?, '[]', '[]')", (i,))


def test_replaces_matching_smashrun_row(garmin):
    add_smashrun(900, "2026-11-10", 10.0)
    garmin.runs = [run(1, "2026-11-10", 10100)]
    sync(garmin)
    assert [r["id"] for r in rows()] == [1]
    assert 900 not in db.run_details([900])


def test_keeps_unmatched_smashrun_rows(garmin):
    add_smashrun(900, "2026-11-10", 8.0)
    add_smashrun(901, "2026-11-09", 5.0)
    garmin.runs = [run(1, "2026-11-10", 12000)]
    sync(garmin)
    assert [r["id"] for r in rows()] == [1, 900, 901]


def test_two_runs_a_day_pair_by_distance(garmin):
    add_smashrun(900, "2026-11-10", 5.0)
    add_smashrun(901, "2026-11-10", 10.0)
    garmin.runs = [run(1, "2026-11-10", 10050), run(2, "2026-11-10", 5020, "17:00:00")]
    sync(garmin)
    assert [r["id"] for r in rows()] == [1, 2]
    assert sum(r["km"] for r in rows()) == pytest.approx(15.07)
