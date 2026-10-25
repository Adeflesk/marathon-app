"""Smashrun sync. Reads SMASHRUN_TOKEN from the environment (.env).

GET /v1/my/activities/search (fromDate in local unix seconds) for run summaries, then for each new
run GET /v1/my/activities/{id} (laps) and /splits/km, stored once in run_details. Field names were
checked against the user's account in October 2026. A personal token comes from the API Explorer
with client id "client" and lasts about 60 days; user tokens allow 250 requests an hour.
"""
import json
import os
import time
from datetime import date, datetime, timedelta

import httpx

from . import db

BASE = "https://api.smashrun.com/v1"


class SyncError(Exception):
    pass


def _to_date(value) -> str:
    return str(value)[:10]


TOKEN_DAYS = 60  # a personal API Explorer token lasts about this long
TOKEN_WARN_DAYS = 7  # the dashboard warns this many days before it runs out
TOKEN_REJECTED = ("Smashrun rejected the token (401). Generate a fresh one in the API Explorer, then set "
                  "SMASHRUN_TOKEN and SMASHRUN_TOKEN_ISSUED (the day you generated it).")


def token_expiry() -> date | None:
    """When the token runs out, from SMASHRUN_TOKEN_ISSUED (the day it was generated), or None if unknown."""
    try:
        return date.fromisoformat(os.environ.get("SMASHRUN_TOKEN_ISSUED", "").strip()) + timedelta(days=TOKEN_DAYS)
    except ValueError:
        return None


MAX_DETAILS_PER_SYNC = 40  # two calls each; keeps a first sync well inside 250 requests an hour


def _get(client, url, headers):
    r = client.get(url, headers=headers)
    if r.status_code == 401:
        raise SyncError(TOKEN_REJECTED)
    return r


def _fetch_details(client, headers, ids: list[int]) -> None:
    """Km splits and laps for runs that don't have them yet. A run that fails is retried next sync."""
    missing = [i for i in ids if i not in db.run_details(ids)][:MAX_DETAILS_PER_SYNC]
    for i in missing:
        detail = _get(client, f"{BASE}/my/activities/{i}", headers)
        splits = _get(client, f"{BASE}/my/activities/{i}/splits/km", headers)
        if detail.status_code >= 400 or splits.status_code >= 400:
            continue
        with db.conn() as c:
            c.execute("INSERT OR REPLACE INTO run_details(id, splits, laps) VALUES (?,?,?)",
                      (i, json.dumps(splits.json()), json.dumps(detail.json().get("laps") or [])))


def sync(since: date) -> int:
    token = os.environ.get("SMASHRUN_TOKEN", "").strip()
    if not token:
        raise SyncError("SMASHRUN_TOKEN is not set. Copy .env.example to .env and add your token.")
    from_ts = int(time.mktime(datetime(since.year, since.month, since.day).timetuple()))
    headers = {"Authorization": f"Bearer {token}"}
    saved, skipped, page, sample_keys, ids = 0, 0, 0, [], []
    with httpx.Client(timeout=20) as client:
        while True:
            r = client.get(
                f"{BASE}/my/activities/search",
                params={"fromDate": from_ts, "count": 100, "page": page},
                headers=headers,
            )
            if r.status_code == 401:
                raise SyncError(TOKEN_REJECTED)
            if r.status_code >= 400:
                raise SyncError(f"Smashrun returned {r.status_code}: {r.text[:200]}")
            rows = r.json()
            if not rows:
                break
            with db.conn() as c:
                for a in rows:
                    km = float(a.get("distance") or 0)
                    if km <= 0:
                        continue
                    if a.get("activityId") is None:
                        # a NULL id would get a fresh rowid, so every sync would add the run again
                        skipped += 1
                        sample_keys = sample_keys or sorted(a)
                        continue
                    c.execute(
                        "INSERT OR REPLACE INTO activities(id, date, km, seconds, avg_hr) VALUES (?,?,?,?,?)",
                        (
                            a.get("activityId"),
                            _to_date(a.get("startDateTimeLocal") or a.get("startDateTimeUtc")),
                            km,
                            int(a.get("duration") or 0),
                            a.get("heartRateAverage"),
                        ),
                    )
                    saved += 1
                    ids.append(a["activityId"])
            page += 1
            if page > 20:
                break
        _fetch_details(client, headers, ids)
    if skipped and not saved:
        raise SyncError(f"Skipped {skipped} runs with no activityId. Fields Smashrun sent: {', '.join(sample_keys[:20])}")
    return saved
