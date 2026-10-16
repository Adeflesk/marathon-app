# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

A single-user marathon training app (FastAPI + Jinja2 server-rendered pages + SQLite). It generates a
week-by-week plan to a target race (default: Barcelona Marathon, 14 Mar 2027), syncs runs from Smashrun,
compares them with the plan, builds strength sessions from the user's equipment, and exports Garmin `.fit`
workouts. `README.md` is written for the end user and explains the training logic in plain terms.

## Commands

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env                       # set SMASHRUN_TOKEN for sync
uvicorn app.main:app --reload              # http://localhost:8000 (F5 in VS Code does the same)
python -m app.pace_engine 10 52:30         # training paces from a 10 km in 52:30
```

Deployed to Fly.io (`fly.toml`, `Dockerfile`): `fly deploy`. SQLite and `equipment.json` live on the
`marathon_data` volume at `/data` (via `DB_PATH`). Setting the `APP_PASSWORD` secret turns on HTTP Basic auth
(middleware in `main.py`); leave it unset locally. `TZ=Europe/Dublin` so `date.today()` matches the user.

There are no tests, linter or build step configured. To check plan output quickly without the server:

```bash
python -c "from datetime import date; from app.config import load_settings; from app.plan import generate; [print(w['week'], w['phase'], w['target_km']) for w in generate(load_settings(), date.today())]"
```

## Architecture

The plan is **never stored**. Every request recomputes it from settings, and only user-generated facts
are persisted. Keep it that way: changing `settings.json` or the generator should reshape the whole plan.

- `app/config.py` — `DEFAULTS` merged with optional `settings.json` at the repo root. Dict values are
  shallow-merged, except keys in `REPLACE_KEYS` (`run_days`) which replace wholesale.
  Also loads `.env` itself (no python-dotenv). `plan_start` is pinned (must be a Monday) so week numbers
  don't drift.
- `app/plan.py` — pure functions. `weekly_volumes()` shapes km/long-run per week (Rebuild → Build/Peak
  with every 4th post-base week a Cutback → 2 Taper weeks → Race week). `generate()` distributes each
  week's km across `run_days` by role (`easy`, `quality`, exactly one `long`); the last mid-week run
  absorbs rounding. Tempo appears from week index 7, marathon-pace finishes on long runs from index 10.
  `feedback_factor()` turns a check-in into a 0.8/0.9/1.0 multiplier — the plan only ever adjusts down.
- `app/main.py` — `build_view()` is the hub every page uses: generate plan → apply the *previous* week's
  check-in factor → join actual runs from SQLite by date → attach strength sessions and current/past flags.
  Routes: `/`, `/plan`, `/strength`, `/equipment` (GET/POST), `/workout/{date}.fit`,
  `/workouts/week/{n}.zip`, `/sync`, `/checkin`. POSTs redirect with a `msg` query param.
- `app/strength.py` — equipment lives in `data/equipment.json` (defaults in `DEFAULT_EQUIPMENT`).
  Equipment is reduced to capability tokens; exercise slots pick the first option the tokens allow,
  rotating by week. Prescription depends on phase, check-in factor and whether a tempo run is adjacent.
- `app/garmin.py` — builds FIT workout files with `fit-tool`; pace targets are speed ranges (m/s) around
  `settings.paces`. Confirmed working on the user's Garmin watch.
- `app/smashrun.py` — paged `GET /v1/my/activities/search`, upserts into `activities`. Untested against a
  live account; errors surface as `SyncError` messages shown on the dashboard.
- `app/db.py` — two tables: `activities` (synced runs) and `checkins` (keyed by week number). Schema is
  `CREATE IF NOT EXISTS` on startup; there are no migrations. `DB_PATH` env var overrides `data/marathon.db`.

## Conventions

- Units: distances in km, paces in **seconds per km**, durations in seconds. Format only at display time
  (`fmt_pace` / `pace_mi` Jinja filters registered in `main.py`).
- Planned km are rounded to 0.5 km.
- Strength defaults to Tuesday (B) and Thursday (A), the non-running days, but stays configurable via
  `strength_days` in `settings.json`. Don't hardcode the days.
