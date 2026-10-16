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

Tests: `pip install -r requirements-dev.txt && pytest` (tests use defaults only and a temp DB, see
`tests/conftest.py`). There's no linter or build step. To check plan output quickly without the server:

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
- `app/plan.py` — pure functions.
  - `weekly_volumes()` shapes each week's km and long run: Rebuild, then build blocks of three
    between cutbacks, then 2 Taper weeks and Race week.
    - Blocks are named counting back from the taper (`specific`/Peak, `strength`, `threshold`, then
      `general`), never by week number. A cutback right before the taper is dropped.
    - It owns the long-run rules: +2 km steps; a 1.1× spike guard from 20 km, which the final peak run is
      exempt from; a 3.5 h cap; no back-to-back 30 km+ runs; MP finishes every other week from the
      first strength week.
  - `generate()` spreads each week's km over `run_days` by role (`easy`, `quality`, exactly one `long`).
    The quality day's session sets its own km (its cool-down fills the day), easy runs keep a floor,
    and the last mid-week run absorbs rounding.
  - `feedback_factor()` turns a check-in into a 0.8/0.9/1.0 multiplier; the plan only ever adjusts
    down.
- `app/sessions.py` — the Wednesday menu.
  - Sessions are lists of steps and `{"repeat": n, "steps": [...]}` blocks, with `pace` as a
    `settings.paces` key, a number in s/km, or `None` (an open target).
  - `quality_session()` picks the session by block and position, and `_fit()` trims it to the work
    caps (12% of the week at `tempo`, 18% at `subthreshold`/MP) and to the day's room.
  - `scale_session()` applies the check-in trim by reps (never below 2). `hard` marks sessions that
    lighten an adjacent Strength A.
- `app/main.py` — `build_view()` is the hub every page uses: generate plan → apply the *previous* week's
  check-in factor → join actual runs from SQLite by date → attach strength sessions and current/past flags.
  Routes: `/`, `/plan`, `/strength`, `/equipment` (GET/POST), `/workout/{date}.fit`,
  `/workouts/week/{n}.zip`, `/sync`, `/checkin`. POSTs redirect with a `msg` query param.
- `app/strength.py` — equipment lives in `data/equipment.json` (defaults in `DEFAULT_EQUIPMENT`).
  Equipment is reduced to capability tokens; exercise slots pick the first option the tokens allow,
  rotating by week. Prescription depends on phase, check-in factor and whether a tempo run is adjacent.
- `app/garmin.py` — builds FIT workout files with `fit-tool`; pace targets are speed ranges (m/s) around
  `settings.paces`. Repeat blocks become a `REPEAT_UNTIL_STEPS_CMPLT` step after their steps, pointing back
  to the block's first step index, mirroring Garmin Connect's own files (samples in `samples/garmin/`,
  untracked). Single-step and tempo files are confirmed on the user's watch.
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
