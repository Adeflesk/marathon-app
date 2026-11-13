"""Garmin run sync into `activities` and `run_details`, plus the original FIT in `run_files`.

GET /activitylist-service/activities/search/activities (paged), then per new run the activity ZIP from
/download-service/files/activity/{id}, read by `fitfile.details`. Garmin rows are listed in `run_source`;
an `activities` row with no `run_source` entry came from Smashrun. A Smashrun row is replaced by the Garmin run
it matches (same date, km within 3 % or 0.2 km), so history is not counted twice.
"""
import io
import json
import logging
import zipfile
from datetime import date, datetime, timedelta

import httpx

from . import db, fitfile, garmin_api

MAX_DETAILS_PER_SYNC = 40
RUN_TYPES = {"running", "treadmill_running", "trail_running", "track_running"}
SEARCH = "/activitylist-service/activities/search/activities"
PAGE = 100
MAX_PAGES = 20
KM_REL, KM_ABS = 0.03, 0.2
FIT_FAILURES = "garmin_fit_failures"  # meta: {"count", "last_error", "at"} of FIT downloads or reads that failed

log = logging.getLogger(__name__)


def _close(a: float, b: float) -> bool:
    return abs(a - b) <= max(KM_ABS, KM_REL * max(a, b))


def _fit_bytes(zip_bytes: bytes) -> bytes:
    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as z:
        name = next(n for n in z.namelist() if n.lower().endswith(".fit"))
        return z.read(name)


def _replace_smashrun(c, garmin: list[tuple[int, str, float]]) -> None:
    """Drop the Smashrun rows that the given Garmin runs (id, date, km) stand in for, pairing by distance per day.
    The Smashrun run's splits and laps move to the Garmin id, so the run keeps them until its FIT replaces them."""
    for day in {d for _, d, _ in garmin}:
        mine = sorted(((km, i) for i, d, km in garmin if d == day))
        theirs = sorted((r["km"], r["id"]) for r in c.execute(
            "SELECT id, km FROM activities WHERE date = ? AND id NOT IN (SELECT id FROM run_source)", (day,)))
        for km, garmin_id in mine:
            best = min((t for t in theirs if _close(km, t[0])), key=lambda t: abs(t[0] - km), default=None)
            if best:
                theirs.remove(best)
                c.execute("DELETE FROM activities WHERE id = ?", (best[1],))
                if c.execute("SELECT 1 FROM run_details WHERE id = ?", (best[1],)).fetchone():
                    c.execute("DELETE FROM run_details WHERE id = ?", (garmin_id,))
                    c.execute("UPDATE run_details SET id = ? WHERE id = ?", (garmin_id, best[1]))


def _failed(i: int, why: str) -> None:
    """Count a FIT that couldn't be fetched or read, keep the last reason, and log it."""
    log.warning("Garmin FIT for activity %s failed: %s", i, why)
    old = json.loads(db.get_meta(FIT_FAILURES) or "{}")
    db.set_meta(FIT_FAILURES, json.dumps({"count": old.get("count", 0) + 1, "last_error": f"{i}: {why}",
                                          "at": datetime.now().isoformat(timespec="seconds")}))


def _fetch_details(client, runs: list[tuple[str, int]], limit: int) -> None:
    """FIT, km splits and laps for runs without a stored FIT, newest first (details carried over from Smashrun
    are replaced). A run that fails is recorded and retried next sync."""
    with db.conn() as c:
        have = {r["id"] for r in c.execute("SELECT id FROM run_files")}
    missing = sorted((r for r in runs if r[1] not in have), reverse=True)[:limit]
    for _, i in missing:
        try:
            r = garmin_api.get(client, f"/download-service/files/activity/{i}")
            if r.status_code >= 400:
                _failed(i, f"Garmin returned {r.status_code}")
                continue
            d = fitfile.details(r.content)
            fit = _fit_bytes(r.content)
        except garmin_api.SyncError:
            raise
        except Exception as exc:
            _failed(i, f"{type(exc).__name__}: {exc}")
            continue
        with db.conn() as c:
            c.execute("INSERT OR REPLACE INTO run_files(id, fit) VALUES (?,?)", (i, fit))
            c.execute("INSERT OR REPLACE INTO run_details(id, splits, laps) VALUES (?,?,?)",
                      (i, json.dumps(d["splits"]), json.dumps(d["laps"])))


def sync_runs(client, since, max_details: int = MAX_DETAILS_PER_SYNC) -> int:
    """Save runs from `since` on; returns how many were saved."""
    saved: list[tuple[int, str, float]] = []
    runs: list[tuple[str, int]] = []
    for page in range(MAX_PAGES):
        r = garmin_api.get(client, SEARCH, {"start": page * PAGE, "limit": PAGE, "startDate": since.isoformat()})
        if r.status_code >= 400:
            raise garmin_api.SyncError(f"Garmin returned {r.status_code}: {r.text[:200]}")
        rows = r.json()
        if not rows:
            break
        with db.conn() as c:
            for a in rows:
                if (a.get("activityType") or {}).get("typeKey") not in RUN_TYPES:
                    continue
                km = float(a.get("distance") or 0) / 1000
                if km <= 0 or a.get("activityId") is None:
                    continue
                i, start = int(a["activityId"]), str(a.get("startTimeLocal") or a.get("startTimeGMT") or "")
                if len(start) < 10:
                    continue
                avg_hr = a.get("averageHR")
                c.execute("INSERT OR REPLACE INTO activities(id, date, km, seconds, avg_hr) VALUES (?,?,?,?,?)",
                          (i, start[:10], km, int(a.get("duration") or 0), round(avg_hr) if avg_hr else None))
                c.execute("INSERT OR REPLACE INTO run_source(id, source) VALUES (?, 'garmin')", (i,))
                saved.append((i, start[:10], km))
                runs.append((start, i))
    with db.conn() as c:
        _replace_smashrun(c, saved)
    _fetch_details(client, runs, max_details)
    return len(saved)


# --- daily wellness ----------------------------------------------------------------------------------------

RHR_DAYS_PER_SYNC = 40  # resting HR has no range endpoint: one call per day, so cap the calls per sync
CHUNK_DAYS = 28  # each range endpoint is asked for at most this many days at a time
HRV_PATH = "/hrv-service/hrv/daily/{s}/{e}"
SLEEP_PATH = "/sleep-service/sleep/dailySleepSummariesByDate"
WEIGHT_PATH = "/weight-service/weight/range/{s}/{e}"
RHR_PATH = "/wellness-service/wellness/dailyHeartRate"
COLUMNS = ("hrv_night", "hrv_week_avg", "hrv_low", "hrv_high", "rhr", "sleep_s", "sleep_score", "stress_avg",
           "weight_kg")


def _chunks(since: date, until: date):
    s = since
    while s <= until:
        e = min(s + timedelta(days=CHUNK_DAYS - 1), until)
        yield s, e
        s = e + timedelta(days=1)


def _json(r):
    if r.status_code >= 400:
        raise garmin_api.SyncError(f"Garmin returned {r.status_code}: {r.text[:200]}")
    return r.json()


def _num(v, cast=float):
    """A reading as a number; a missing one stays None (never 0)."""
    return cast(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else None


def _hrv(item: dict) -> dict:
    b = item.get("baseline") or {}
    return {"hrv_night": _num(item.get("lastNightAvg")), "hrv_week_avg": _num(item.get("weeklyAvg")),
            "hrv_low": _num(b.get("balancedLow")), "hrv_high": _num(b.get("balancedUpper"))}


def _sleep(item: dict) -> dict:
    return {"sleep_s": _num(item.get("sleepTimeSeconds"), int) or None,
            "sleep_score": _num(((item.get("sleepScores") or {}).get("overall") or {}).get("value"), int),
            "stress_avg": _num(item.get("avgSleepStress"), round)}


def _weight(item: dict) -> dict:
    g = _num((item.get("latestWeight") or {}).get("weight"))
    return {"weight_kg": g / 1000 if g else None}


def _save_day(c, day: str, cols: dict, raw: dict) -> None:
    """Merge one source's values into the day's row; a column the source has no value for keeps what it had."""
    old = c.execute("SELECT raw FROM wellness WHERE date = ?", (day,)).fetchone()
    merged = json.loads(old["raw"]) if old and old["raw"] else {}
    merged.update(raw)
    names = list(cols)
    c.execute(f"INSERT INTO wellness(date, {', '.join(names)}, raw) VALUES (?{',?' * len(names)}, ?) "
              f"ON CONFLICT(date) DO UPDATE SET raw = excluded.raw, "
              + ", ".join(f"{n} = COALESCE(excluded.{n}, {n})" for n in names),
              (day, *cols.values(), json.dumps(merged)))


def _range(client, since: date, until: date, path: str, params, pick, key, date_key, parse) -> set[str]:
    """Ask one range endpoint chunk by chunk and merge every day it returns; gives the days it saw."""
    seen: set[str] = set()
    for s, e in _chunks(since, until):
        body = _json(garmin_api.get(client, path.format(s=s, e=e), params(s, e)))
        with db.conn() as c:
            for item in pick(body):
                day = str(item.get(date_key) or "")[:10]
                if len(day) == 10:
                    _save_day(c, day, parse(item), {key: item})
                    seen.add(day)
    return seen


def _rhr_days(since: date, until: date, limit: int = RHR_DAYS_PER_SYNC) -> list[str]:
    """Days to ask resting HR for: the newest ones first, those in range with none stored, plus today and yesterday."""
    with db.conn() as c:
        have = {r["date"] for r in c.execute("SELECT date FROM wellness WHERE rhr IS NOT NULL")}
    want = [until - timedelta(days=i) for i in range((until - since).days + 1)]
    always = {until, until - timedelta(days=1)}
    return [d.isoformat() for d in want if d in always or d.isoformat() not in have][:limit]


def sync_wellness(client, since: date, until: date, rhr_days: int = RHR_DAYS_PER_SYNC) -> int:
    """Save HRV, sleep, weight (range endpoints) and resting HR (per day) from `since` to `until`; returns days touched."""
    days = _range(client, since, until, HRV_PATH, lambda s, e: None, lambda b: b.get("hrvSummaries") or [],
                  "hrv", "calendarDate", _hrv)
    days |= _range(client, since, until, SLEEP_PATH, lambda s, e: {"startDate": s.isoformat(), "endDate": e.isoformat()},
                   lambda b: b or [], "sleep", "calendarDate", _sleep)
    days |= _range(client, since, until, WEIGHT_PATH, lambda s, e: {"includeAll": "true"},
                   lambda b: b.get("dailyWeightSummaries") or [], "weight", "summaryDate", _weight)
    for day in _rhr_days(since, until, rhr_days):
        r = garmin_api.get(client, RHR_PATH, {"date": day})
        if r.status_code >= 400:
            continue  # that day is asked again next sync
        body = r.json() or {}
        rhr = _num(body.get("restingHeartRate"), int)
        if rhr is None:
            continue
        with db.conn() as c:
            _save_day(c, day, {"rhr": rhr}, {"rhr": {k: v for k, v in body.items() if k != "heartRateValues"}})
        days.add(day)
    return len(days)


QUICK_WELLNESS_DAYS = 27  # sync on open: range endpoints from this many days back, one chunk (one call) each
QUICK_RHR_DAYS = 4  # sync on open: resting-HR calls (one per day)
QUICK = {"max_details": 4, "timeout": 8, "wellness_days": QUICK_WELLNESS_DAYS,
         "rhr_days": QUICK_RHR_DAYS}  # sync on open: the page waits, so fetch less
WELLNESS_LEAD = 32  # days of wellness before `since`, so the 30-day resting-HR baseline exists


def sync(since: date, max_details: int = MAX_DETAILS_PER_SYNC, timeout: float = garmin_api.TIMEOUT,
         wellness_days: int | None = None, rhr_days: int = RHR_DAYS_PER_SYNC) -> int:
    """Runs from `since`, then wellness from `since` - 32 days (or only the last `wellness_days`), with at most
    `rhr_days` resting-HR calls. Returns the number of runs saved. Sets `last_sync` on success: weeks before it
    are known."""
    today = date.today()
    start = today - timedelta(days=wellness_days) if wellness_days is not None else since - timedelta(days=WELLNESS_LEAD)
    with httpx.Client(timeout=timeout) as client:
        n = sync_runs(client, since, max_details)
        sync_wellness(client, start, today, rhr_days)
    db.set_meta("last_sync", datetime.now().isoformat(timespec="seconds"))
    return n
