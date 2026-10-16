"""Smashrun sync. Reads SMASHRUN_TOKEN from the environment (.env).

Endpoint and field names follow Smashrun's public API as I understand it
(GET /v1/my/activities/search with fromDate as unix seconds). They have NOT been
tested against your account, so if a sync fails, the error text tells you what to fix.
"""
import os
import time
from datetime import date, datetime

import httpx

from . import db

BASE = "https://api.smashrun.com/v1"


class SyncError(Exception):
    pass


def _to_date(value) -> str:
    return str(value)[:10]


def sync(since: date) -> int:
    token = os.environ.get("SMASHRUN_TOKEN", "").strip()
    if not token:
        raise SyncError("SMASHRUN_TOKEN is not set. Copy .env.example to .env and add your token.")
    from_ts = int(time.mktime(datetime(since.year, since.month, since.day).timetuple()))
    headers = {"Authorization": f"Bearer {token}"}
    saved, skipped, page, sample_keys = 0, 0, 0, []
    with httpx.Client(timeout=20) as client:
        while True:
            r = client.get(
                f"{BASE}/my/activities/search",
                params={"fromDate": from_ts, "count": 100, "page": page},
                headers=headers,
            )
            if r.status_code == 401:
                raise SyncError("Smashrun rejected the token (401). Generate a fresh one in the API Explorer.")
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
            page += 1
            if page > 20:
                break
    if skipped and not saved:
        raise SyncError(f"Skipped {skipped} runs with no activityId. Fields Smashrun sent: {', '.join(sample_keys[:20])}")
    return saved
