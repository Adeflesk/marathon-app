import json
from datetime import date, timedelta

import httpx
import pytest

from app import db, garmin_sync

REAL_CLIENT = httpx.Client

HRV, SLEEP, WEIGHT, HR = "/hrv-service/hrv/daily/", "/sleep-service/sleep/dailySleepSummariesByDate", \
    "/weight-service/weight/range/", "/wellness-service/wellness/dailyHeartRate"
DAYS = ["2026-11-11", "2026-11-12", "2026-11-13"]


@pytest.fixture
def garmin(monkeypatch):
    """A fake Garmin wellness API. Set .hrv/.sleep/.weight/.rhr as {date: value}; .calls lists (path, params)."""
    class G:
        pass
    g = G()
    g.hrv, g.sleep, g.weight, g.rhr, g.calls = {}, {}, {}, {}, []

    def handler(req):
        if "token" in req.url.path:
            return httpx.Response(200, json={"access_token": "t", "expires_in": 86400})
        p, q = req.url.path, dict(req.url.params)
        g.calls.append((p, q))
        if p.startswith(HRV):
            return httpx.Response(200, json={"hrvSummaries": [
                {"calendarDate": d, "lastNightAvg": v, "weeklyAvg": v + 1,
                 "baseline": {"balancedLow": 34, "balancedUpper": 47}} for d, v in sorted(g.hrv.items())]})
        if p == SLEEP:
            return httpx.Response(200, json=[
                {"calendarDate": d, "sleepTimeSeconds": s, "sleepScores": {"overall": {"value": 70}},
                 "avgSleepStress": 18} for d, s in sorted(g.sleep.items())])
        if p.startswith(WEIGHT):
            return httpx.Response(200, json={"dailyWeightSummaries": [
                {"summaryDate": d, "latestWeight": {"weight": w}} for d, w in sorted(g.weight.items())]})
        if p == HR:
            d = q["date"]
            return httpx.Response(200, json={"calendarDate": d, "restingHeartRate": g.rhr.get(d),
                                             "heartRateValues": [[1, 60]] * 720})
        return httpx.Response(404)

    monkeypatch.setenv("GARMIN_API_KEY", "k")
    db.init()
    with db.conn() as c:
        c.execute("DELETE FROM wellness")
        c.execute("DELETE FROM meta")
    g.client = REAL_CLIENT(transport=httpx.MockTransport(handler))
    return g


def sync(g, since=DAYS[0], until=DAYS[-1]):
    return garmin_sync.sync_wellness(g.client, date.fromisoformat(since), date.fromisoformat(until))


def fill(g):
    g.hrv = {d: 40 + i for i, d in enumerate(DAYS)}
    g.sleep = {d: 25000 + i for i, d in enumerate(DAYS)}
    g.weight = {d: 76000.0 + i * 100 for i, d in enumerate(DAYS)}
    g.rhr = {d: 50 + i for i, d in enumerate(DAYS)}


def test_wellness_row_per_day(garmin):
    fill(garmin)
    assert sync(garmin) == 3
    rows = db.wellness()
    assert [r["date"] for r in rows] == DAYS
    assert "raw" not in rows[0]
    assert rows[1] == {"date": "2026-11-12", "hrv_night": 41, "hrv_week_avg": 42, "hrv_low": 34, "hrv_high": 47,
                       "rhr": 51, "sleep_s": 25001, "sleep_score": 70, "stress_avg": 18, "weight_kg": 76.1}


def test_today_refreshed(garmin):
    fill(garmin)
    sync(garmin)
    garmin.hrv["2026-11-13"] = 55
    garmin.weight["2026-11-13"] = 75500.0
    sync(garmin)
    today = db.wellness()[-1]
    assert (today["hrv_night"], today["weight_kg"]) == (55, 75.5)
    assert len(db.wellness()) == 3


def test_missing_day_is_null_not_zero(garmin):
    fill(garmin)
    del garmin.hrv["2026-11-12"]
    del garmin.rhr["2026-11-12"]
    sync(garmin)
    r = db.wellness()[1]
    assert r["hrv_night"] is None and r["hrv_low"] is None and r["rhr"] is None
    assert r["sleep_s"] == 25001


def test_partial_refresh_keeps_other_columns(garmin):
    fill(garmin)
    sync(garmin)
    garmin.hrv, garmin.sleep, garmin.rhr = {}, {}, {}
    garmin.weight["2026-11-13"] = 75000.0
    sync(garmin)
    r = db.wellness()[-1]
    assert r["weight_kg"] == 75.0
    assert (r["hrv_night"], r["sleep_s"], r["rhr"]) == (42, 25002, 52)


def test_raw_kept(garmin):
    fill(garmin)
    sync(garmin)
    with db.conn() as c:
        raw = json.loads(c.execute("SELECT raw FROM wellness WHERE date = '2026-11-12'").fetchone()["raw"])
    assert raw["hrv"]["lastNightAvg"] == 41
    assert raw["sleep"]["sleepTimeSeconds"] == 25001
    assert raw["weight"]["latestWeight"]["weight"] == 76100.0
    assert raw["rhr"]["restingHeartRate"] == 51 and "heartRateValues" not in raw["rhr"]


def test_rhr_not_refetched_when_known(garmin):
    fill(garmin)
    sync(garmin)
    garmin.calls.clear()
    sync(garmin)
    asked = sorted(q["date"] for p, q in garmin.calls if p == HR)
    assert asked == ["2026-11-12", "2026-11-13"]  # yesterday and today only; 11-11 already has rhr


def test_rhr_fetch_capped_newest_first(garmin):
    garmin_sync.sync_wellness(garmin.client, date(2026, 10, 1), date(2026, 11, 13), rhr_days=5)
    asked = [q["date"] for p, q in garmin.calls if p == HR]
    assert asked == ["2026-11-13", "2026-11-12", "2026-11-11", "2026-11-10", "2026-11-09"]


def test_range_calls_chunked(garmin):
    sync(garmin, "2026-09-01", "2026-11-13")
    spans = [q for p, q in garmin.calls if p == SLEEP]
    assert len(spans) == 3 and spans[0]["startDate"] == "2026-09-01"
    assert spans[-1]["endDate"] == "2026-11-13"


# --- sync(): runs then wellness, the quick limits, last_sync ---

@pytest.fixture
def full_garmin(garmin, monkeypatch):
    """garmin's wellness fake plus an empty activity search, served to sync()'s own httpx.Client."""
    inner = garmin.client._transport

    def handler(req):
        if req.url.path == "/activitylist-service/activities/search/activities":
            garmin.calls.append((req.url.path, dict(req.url.params)))
            return httpx.Response(200, json=[])
        return inner.handle_request(req)

    monkeypatch.setattr(garmin_sync.httpx, "Client",
                        lambda timeout: REAL_CLIENT(transport=httpx.MockTransport(handler), timeout=timeout))
    return garmin


def starts(calls):
    hrv = [p for p, _ in calls if p.startswith(HRV)]
    return {"search": [q["startDate"] for p, q in calls if p.endswith("/search/activities")],
            "hrv": [p[len(HRV):].split("/")[0] for p in hrv],
            "sleep": [q["startDate"] for p, q in calls if p == SLEEP],
            "weight": [p[len(WEIGHT):].split("/")[0] for p, _ in calls if p.startswith(WEIGHT)],
            "rhr": [q["date"] for p, q in calls if p == HR]}


def test_full_sync_starts_and_last_sync(full_garmin):
    today = date.today()
    since = today - timedelta(days=10)
    assert garmin_sync.sync(since) == 0
    got = starts(full_garmin.calls)
    lead = (since - timedelta(days=garmin_sync.WELLNESS_LEAD)).isoformat()
    assert got["search"] == [since.isoformat()]
    assert got["hrv"][0] == got["sleep"][0] == got["weight"][0] == lead
    assert len(got["hrv"]) == 2  # 43 days in chunks of 28
    assert len(got["rhr"]) == garmin_sync.RHR_DAYS_PER_SYNC  # 43 days wanted, capped per sync
    assert db.get_meta("last_sync")[:10] == today.isoformat()


def test_quick_sync_one_call_per_range_endpoint_and_four_rhr_days(full_garmin):
    today = date.today()
    garmin_sync.sync(today - timedelta(days=60), **garmin_sync.QUICK)
    got = starts(full_garmin.calls)
    first = (today - timedelta(days=garmin_sync.QUICK_WELLNESS_DAYS)).isoformat()
    assert garmin_sync.QUICK_WELLNESS_DAYS == 27 and garmin_sync.QUICK_RHR_DAYS == 4
    assert got["hrv"] == got["sleep"] == got["weight"] == [first]  # one call each
    assert got["rhr"][:2] == [today.isoformat(), (today - timedelta(days=1)).isoformat()]
    assert len(got["rhr"]) == 4
    assert got["search"] == [(today - timedelta(days=60)).isoformat()]
    assert db.get_meta("last_sync") is not None
