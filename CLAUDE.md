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
  shallow-merged, except keys in `REPLACE_KEYS` (`run_days`, `ankle_days`) which replace wholesale.
  Also loads `.env` itself (no python-dotenv). `plan_start` is pinned (must be a Monday) so week numbers
  don't drift. Settings include `ankle_days` (default `["mon", "wed", "fri", "sat"]`) and `injured_side`
  (default `"right"`).
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
    and the last mid-week run absorbs rounding. Each week gains `strength_block` (count of cutbacks
    prior/at that week: 0 for weeks 1–6, 1 for 7–10, 2 for 11–14, 3 from 15).
  - `feedback_factor()` turns a check-in into a 0.8/0.9/1.0 multiplier; the plan only ever adjusts
    down.
- `app/sessions.py` — the Wednesday menu.
  - Sessions are lists of steps and `{"repeat": n, "steps": [...]}` blocks, with `pace` as a
    `settings.paces` key, a number in s/km, or `None` (an open target).
  - `quality_session()` picks the session by block and position, and `_fit()` trims it to the work
    caps (12% of the week at `tempo`, 18% at `subthreshold`/MP) and to the day's room.
  - `scale_session()` applies the check-in trim by reps (rounded, never below 2), or by a shorter rep
    when reps can't drop.
- `app/strength.py` — routines and prescriptions based on sports science research.
  - Prescriptions come from `ROLE_RX` per phase (Rebuild, Build, Cutback, Peak, Taper).
  - Sessions are Thursday A (hops when ready, box squat, RDL, single-leg lift by block, calf raises, seated soleus, hip thrust)
    and Tuesday B (balance, single-leg RDL, ring row + push-up, suitcase carry + core, Copenhagen plank, bent calf
    + band eversion). The Copenhagen plank has its own `adductor` role (timed, seconds): `copenhagen_short` in
    `strength_block` 0, `copenhagen_long` after, none in Taper 2. Added after the research routine, not from it.
  - Equipment fallbacks dynamically map to dumbbells/bodyweight if rings or racks are missing (`strength.tokens(eq)`).
  - Trims apply when cutback, factor 0.9/0.8, Wednesday quality run verdict is "bad", or ankle flag is active (floor of 1 set).
- `app/progression.py` — pure progression and suggestion engine from logged history.
  - `suggest(ex, history, ctx, eq, today)`: suggests working weight, target reps, rungs, and warm-up ladders.
  - Adjusts load from Easy/Right/Hard ratings and RPE targets. Advances tempo/pause rungs at top weight.
  - Guards against load increases during cutbacks, tapers, fatigue trims, or when an ankle flag is active.
  - Conservative load drops after 11–28 days (-1 step) or >28 days off (≤ 80% weight).
- `app/ankle.py` — pure ankle state and readiness tracking.
  - Replays logs, tests, and checks to determine `hop_stage` (0–3), `balance_stage` (0–6), and `test_weeks` (weeks 1, 4, 7, 11, 15).
  - Manages `flag_until`: raises 7-day ankle flag on morning check "worse than usual", ankle pain ≥ 3 on ankle items, or weekly check-in pain ≥ 3.
  - Identifies when morning check is due and when readiness tests are due.
- `app/moves.py` — pure: applies the user's moved/skipped sessions to the generated plan. `shift()` marks an
  item (`orig_date`, then `moved_from` + new `date`, or `skipped`); `relocate()` puts items moved past Sunday
  into the next week; `clash()` holds the warning rules; `can_move()` stops at race day and the plan's end.
- `app/main.py` — `build_view()` is the hub every page uses: generate plan → apply the *previous* week's
  check-in factor → shift and relocate moved runs → join actual runs from SQLite by date (a day with two runs
  shares its actual; the longer run gets the review) → compute ankle context and attach strength sessions
  (shifted before logs are looked up), suggestions, and snacks → relocate strength → mark `movable`.
  Routes: `/`, `/plan`, `/strength`, `/equipment` (GET/POST), `/workout/{date}.fit?n=`,
  `/workouts/week/{n}.zip`, `/sync`, `/checkin`, `/strength/log` (POST), `/snack` (POST), `/ankle/check` (POST),
  `/ankle/tests` (POST), `/move` (POST; warns via `/?confirm=…` on a clash), `/move/undo` (POST).
  POSTs redirect with a 303 to their anchor.
- `app/garmin.py` — builds FIT workout files with `fit-tool`; pace targets are speed ranges (m/s) around
  `settings.paces`. Repeat blocks become a `REPEAT_UNTIL_STEPS_CMPLT` step after their steps, pointing back
  to the block's first step index, mirroring Garmin Connect's own files (samples in `samples/garmin/`,
  untracked). Single-step and tempo files are confirmed on the user's watch. Easy and long runs open with a `WARMUP_KM` (1 km) open-target warm-up
  step inside their planned km; race day doesn't.
- `app/smashrun.py` — paged `GET /v1/my/activities/search`, upserts into `activities`, then fetches laps
  (`/my/activities/{id}`) and km splits (`/splits/km`) once per new run into `run_details` (max 40 runs
  per sync). Checked against the user's account. The token is a personal API Explorer token (client id
  `client`, ~60 days, 250 requests/hour); errors surface as `SyncError` messages on the dashboard. `SMASHRUN_TOKEN_ISSUED` (YYYY-MM-DD) gives
  `token_expiry()` (+60 days); the dashboard warns from 7 days before.
- `app/review.py` — pure post-run review, recomputed per request like the plan: per-km pace and HR from
  splits, heart-rate drift (second half against first, first km excluded), easy runs quicker than MP + 20 s
  flagged, the long run's MP finish checked from its last splits, and structured sessions checked rep by
  rep from Garmin `work` laps (within 10 s/km is on pace). `build_view` attaches `review` to each planned
  workout whose day has a synced run with details (the day's longest run).
- `app/db.py` — tables: `activities` (synced runs), `run_details` (JSON km splits and laps per run),
  `checkins` (keyed by week number), `strength_logs` (logged sets, weight, reps, rating, ankle pain),
  `snack_logs` (daily ankle snack ticks), `ankle_tests` (readiness test values), `ankle_checks` (morning ankle checks),
  and `moves` (a session's original date + `run`/`A`/`B` → new date, or NULL when skipped).
  Schema is `CREATE IF NOT EXISTS` on startup; there are no migrations. `DB_PATH` env var overrides `data/marathon.db`.

## Conventions

- Units: distances in km, paces in **seconds per km**, durations in seconds. Format only at display time
  (`fmt_pace` / `pace_mi` Jinja filters registered in `main.py`).
- Planned km are rounded to 0.5 km.
- Strength defaults to Tuesday (B) and Thursday (A), the non-running days, but stays configurable via
  `strength_days` in `settings.json`. Don't hardcode the days.
