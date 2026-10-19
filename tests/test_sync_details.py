import json
from datetime import date

import httpx
import pytest

from app import db, smashrun

REAL_CLIENT = httpx.Client
RUNS = [{"activityId": 11, "startDateTimeLocal": "2026-10-20T07:00:00+01:00", "distance": 6.0, "duration": 2400, "heartRateAverage": 140},
        {"activityId": 12, "startDateTimeLocal": "2026-10-22T07:00:00+01:00", "distance": 7.5, "duration": 2700, "heartRateAverage": 150}]


@pytest.fixture
def fake_smashrun(monkeypatch):
    calls = []

    def handler(req):
        path = req.url.path
        calls.append(path)
        if path.endswith("/activities/search"):
            return httpx.Response(200, json=RUNS if req.url.params["page"] == "0" else [])
        if path.endswith("/splits/km"):
            return httpx.Response(200, json=[{"distance": 1.0, "seconds": 400, "heartRate": 140}])
        return httpx.Response(200, json={"activityId": int(path.rsplit("/", 1)[1]),
                                         "laps": [{"lapType": "warmup", "endDuration": 600, "endDistance": 1.5}]})

    monkeypatch.setattr(smashrun.httpx, "Client", lambda **kw: REAL_CLIENT(transport=httpx.MockTransport(handler), **kw))
    monkeypatch.setenv("SMASHRUN_TOKEN", "fake")
    db.init()
    with db.conn() as c:
        c.execute("DELETE FROM run_details")
    return calls


def test_sync_stores_splits_and_laps(fake_smashrun):
    smashrun.sync(date(2026, 10, 1))
    details = db.run_details([11, 12])
    assert set(details) == {11, 12}
    assert details[12]["splits"][0]["seconds"] == 400
    assert details[12]["laps"][0]["lapType"] == "warmup"


def test_details_fetched_once(fake_smashrun):
    smashrun.sync(date(2026, 10, 1))
    first = len(fake_smashrun)
    smashrun.sync(date(2026, 10, 1))
    detail_calls = [p for p in fake_smashrun[first:] if not p.endswith("/search")]
    assert detail_calls == []
