"""Garmin run sync into `activities` and `run_details`, plus the original FIT in `run_files`.

GET /activitylist-service/activities/search/activities (paged), then per new run the activity ZIP from
/download-service/files/activity/{id}, read by `fitfile.details`. Garmin rows are listed in `run_source`;
an `activities` row with no `run_source` entry came from Smashrun. A Smashrun row is replaced by the Garmin run
it matches (same date, km within 3 % or 0.2 km), so history is not counted twice.
"""
import io
import json
import zipfile

from . import db, fitfile, garmin_api

MAX_DETAILS_PER_SYNC = 40
RUN_TYPES = {"running", "treadmill_running", "trail_running", "track_running"}
SEARCH = "/activitylist-service/activities/search/activities"
PAGE = 100
MAX_PAGES = 20
KM_REL, KM_ABS = 0.03, 0.2


def _close(a: float, b: float) -> bool:
    return abs(a - b) <= max(KM_ABS, KM_REL * max(a, b))


def _fit_bytes(zip_bytes: bytes) -> bytes:
    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as z:
        name = next(n for n in z.namelist() if n.lower().endswith(".fit"))
        return z.read(name)


def _replace_smashrun(c, garmin: list[tuple[int, str, float]]) -> None:
    """Drop the Smashrun rows that the given Garmin runs (id, date, km) stand in for, pairing by distance per day."""
    for day in {d for _, d, _ in garmin}:
        mine = sorted(((km, i) for i, d, km in garmin if d == day))
        theirs = sorted((r["km"], r["id"]) for r in c.execute(
            "SELECT id, km FROM activities WHERE date = ? AND id NOT IN (SELECT id FROM run_source)", (day,)))
        for km, _ in mine:
            best = min((t for t in theirs if _close(km, t[0])), key=lambda t: abs(t[0] - km), default=None)
            if best:
                theirs.remove(best)
                c.execute("DELETE FROM activities WHERE id = ?", (best[1],))
                c.execute("DELETE FROM run_details WHERE id = ?", (best[1],))


def _fetch_details(client, runs: list[tuple[str, int]], limit: int) -> None:
    """FIT, km splits and laps for runs without them, newest first. A run that fails is retried next sync."""
    have = db.run_details([i for _, i in runs])
    missing = sorted((r for r in runs if r[1] not in have), reverse=True)[:limit]
    for _, i in missing:
        try:
            r = garmin_api.get(client, f"/download-service/files/activity/{i}")
            if r.status_code >= 400:
                continue
            d = fitfile.details(r.content)
            fit = _fit_bytes(r.content)
        except garmin_api.SyncError:
            raise
        except Exception:
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
