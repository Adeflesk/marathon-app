"""Garmin Personal API client. Reads GARMIN_API_KEY from the environment (.env).

The key (made at connect.garmin.com/app/settings/personalApiToken, valid up to a year) is exchanged for an
access token that lasts about 24 h; there is no refresh token, so we just ask again. The token is cached in
`meta` (garmin_token / garmin_token_exp, epoch seconds) and re-fetched when under an hour is left.

    python -m app.garmin_api probe [days]   # saves raw responses to samples/garmin-api/ (untracked)
"""
import base64
import json
import os
import sys
import time
from datetime import date, timedelta
from pathlib import Path

import httpx

from . import config, db  # config loads .env

BASE = "https://personal.connectapi.garmin.com"
TOKEN_PATH = "/personalapitoken-service/personal-api/personal-api-key/token"
KEY_WARN_DAYS = 7  # the dashboard warns this many days before the key runs out
REFRESH_BEFORE = 3600  # seconds; re-fetch the token when less than this is left
TIMEOUT = 20


class SyncError(Exception):
    pass


def key_expiry() -> date | None:
    """When the API key runs out, from GARMIN_API_KEY_EXPIRES (YYYY-MM-DD), or None if unset or unreadable."""
    try:
        return date.fromisoformat(os.environ.get("GARMIN_API_KEY_EXPIRES", "").strip())
    except ValueError:
        return None


def _jwt_exp(tok: str) -> float | None:
    try:
        seg = tok.split(".")[1]
        seg += "=" * (-len(seg) % 4)
        return float(json.loads(base64.urlsafe_b64decode(seg))["exp"])
    except (IndexError, ValueError, KeyError, TypeError):
        return None


def _exchange(client: httpx.Client, key: str) -> str:
    r = client.post(BASE + TOKEN_PATH, headers={"Authorization": f"ApiKey {key}"})
    if r.status_code in (401, 403):
        raise SyncError(f"Garmin rejected GARMIN_API_KEY ({r.status_code}). It may have expired or been revoked: "
                        "create a new key at connect.garmin.com/app/settings/personalApiToken and update "
                        ".env (GARMIN_API_KEY and GARMIN_API_KEY_EXPIRES).")
    if r.status_code >= 400:
        raise SyncError(f"Garmin token exchange returned {r.status_code}: {r.text[:200]}")
    try:
        body = r.json()
    except ValueError:
        body = None
    if isinstance(body, dict):
        tok = body.get("access_token") or body.get("accessToken") or body.get("token")
        expires_in = body.get("expires_in")
    else:  # the live service answers with the bare JWT as text/plain
        tok, expires_in = r.text.strip().strip('"'), None
    if not tok:
        raise SyncError("Garmin token exchange returned no access token.")
    exp = time.time() + float(expires_in) if expires_in else _jwt_exp(tok) or time.time() + 23 * 3600
    db.set_meta("garmin_token", tok)
    db.set_meta("garmin_token_exp", str(exp))
    return tok


def token(client: httpx.Client) -> str:
    key = os.environ.get("GARMIN_API_KEY", "").strip()
    if not key:
        raise SyncError("GARMIN_API_KEY is not set. Copy .env.example to .env and add your key.")
    cached, exp = db.get_meta("garmin_token"), db.get_meta("garmin_token_exp")
    try:
        if cached and exp and float(exp) - time.time() > REFRESH_BEFORE:
            return cached
    except ValueError:
        pass
    return _exchange(client, key)


def _drop_token() -> None:
    with db.conn() as c:
        c.execute("DELETE FROM meta WHERE key IN ('garmin_token', 'garmin_token_exp')")


def get(client: httpx.Client, path: str, params: dict | None = None) -> httpx.Response:
    """GET with a Bearer token. On a 401 the token is dropped and re-fetched once; a second 401 raises."""
    for attempt in (1, 2):
        r = client.get(BASE + path, params=params, headers={"Authorization": f"Bearer {token(client)}"})
        if r.status_code != 401:
            return r
        _drop_token()
    raise SyncError("Garmin rejected a fresh access token (401). Check GARMIN_API_KEY.")


# --- probe -----------------------------------------------------------------------------------------------

def _probe(days: int = 14) -> None:
    db.init()
    out = Path(__file__).resolve().parent.parent / "samples" / "garmin-api"
    out.mkdir(parents=True, exist_ok=True)
    end = date.today()
    start = end - timedelta(days=days)
    yday = end - timedelta(days=1)
    act = "/activitylist-service/activities/search/activities"
    endpoints = {
        "activities": (act, {"start": 0, "limit": 20, "startDate": start.isoformat(), "endDate": end.isoformat()}),
        "hrv_daily": (f"/hrv-service/hrv/daily/{start}/{end}", None),
        "hrv_day": (f"/hrv-service/hrv/{yday}", None),
        "sleep_summaries": ("/sleep-service/sleep/dailySleepSummariesByDate",
                            {"startDate": start.isoformat(), "endDate": end.isoformat()}),
        "sleep_day": ("/sleep-service/sleep/dailySleep", {"date": end.isoformat()}),
        "heart_rate_day": ("/wellness-service/wellness/dailyHeartRate", {"date": yday.isoformat()}),
        "wellness_summary": (f"/wellnessactivity-service/activity/summary/range/{start}/{end}", None),
        "weight": (f"/weight-service/weight/range/{start}/{end}", {"includeAll": "true"}),
        "hr_zones": ("/biometric-service/heartRateZones/v2", None),
    }
    results = {}
    with httpx.Client(timeout=TIMEOUT) as client:
        for name, (path, params) in endpoints.items():
            try:
                r = get(client, path, params)
            except (SyncError, httpx.HTTPError) as e:
                print(f"{name}: FAILED {e}")
                continue
            results[name] = r
            print(f"{name}: {r.status_code}")
            try:
                (out / f"{name}.json").write_text(json.dumps(r.json(), indent=2))
            except ValueError:
                (out / f"{name}.txt").write_text(r.text)
        # detail, workouts and one FIT zip for the newest activity
        acts = results.get("activities")
        rows = []
        if acts is not None and acts.status_code == 200:
            j = acts.json()
            rows = j if isinstance(j, list) else (j.get("activityList") or j.get("activities") or [])
        if rows:
            aid = rows[0].get("activityId")
            for name, path in (("activity_detail", f"/activity-service/activity/{aid}"),
                               ("activity_workouts", f"/activity-service/activity/{aid}/workouts")):
                r = get(client, path)
                print(f"{name}: {r.status_code}")
                try:
                    (out / f"{name}.json").write_text(json.dumps(r.json(), indent=2))
                except ValueError:
                    (out / f"{name}.txt").write_text(r.text)
            r = get(client, f"/download-service/files/activity/{aid}")
            print(f"activity_zip: {r.status_code} ({len(r.content)} bytes)")
            if r.status_code == 200:
                (out / "activity.zip").write_bytes(r.content)
        else:
            print("no activities found; skipped detail, workouts and zip")


if __name__ == "__main__":
    if len(sys.argv) >= 2 and sys.argv[1] == "probe":
        _probe(int(sys.argv[2]) if len(sys.argv) > 2 else 14)
    else:
        print("usage: python -m app.garmin_api probe [days]")
