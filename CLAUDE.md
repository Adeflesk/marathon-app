# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

A single-user marathon training app (FastAPI + Jinja2 server-rendered pages + SQLite). It generates a
week-by-week plan to a target race (default: Barcelona Marathon, 14 Mar 2027), syncs runs and recovery data from Garmin,
compares them with the plan, builds strength sessions from the user's equipment, and exports Garmin `.fit`
workouts. `README.md` is written for the end user and explains the training logic in plain terms.

## Commands

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env                       # set GARMIN_API_KEY (+ GARMIN_API_KEY_EXPIRES) for sync
uvicorn app.main:app --reload              # http://localhost:8000 (F5 in VS Code does the same)
python -m app.pace_engine 10 52:30         # training paces from a 10 km in 52:30
python -m app.garmin_api probe [days]      # saves raw Garmin API responses to samples/garmin-api/ (untracked)
```

Deployed to Fly.io (`fly.toml`, `Dockerfile`): `fly deploy`. SQLite and `equipment.json` live on the
`marathon_data` volume at `/data` (via `DB_PATH`). Setting the `APP_PASSWORD` secret turns on HTTP Basic auth
(middleware in `main.py`); leave it unset locally. A second middleware refuses POSTs whose `Origin` is another site. `TZ=Europe/Dublin` so `date.today()` matches the user.

Tests: `pip install -r requirements-dev.txt && pytest` (tests use defaults only and a temp DB, and never reach
Garmin: `tests/conftest.py` clears `GARMIN_API_KEY` and blocks its HTTP client). There's no linter or build step. To check plan output quickly without the server:

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
  - `volume_caps()` is the missed-week guard: a week ≤ 1.15 × the best of the last 4 *known* weeks' actual
    km, or ≤ 0.9 × it when the week before ran under 60% of its target; floor `base_weekly_km`, race week
    untouched, only once the week before is known. Never bites on the plan as written (tested).
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
  item (`orig_date`, then `moved_from` + new `date`, or `skipped`); `relocate()` puts items moved out of their week
  (past Sunday or before Monday) into the week holding their new date; `clash()` holds the warning rules and
  `can_move()` stops at race day and the plan's ends, both taking `by` (1 = tomorrow, -1 = a day earlier, never
  into the past). Items carry `movable` and `movable_back`; `/move` takes `by`.
- `app/view.py` — builds every page's view; a functional core with one read at the edge.
  - `load_facts()` is the only storage read: every table, `settings.json` and the equipment, as a frozen `Facts`.
  - `build_view(facts, today)` is pure (it deep-copies the settings; tested without a database in
    `tests/test_view_pure.py`). Its pipeline: `apply_goal()` (the latest `goals` row overrides `goal_time` and
    marathon pace, never within `MP_GAP` of threshold; the settings goal again restores exact settings paces) →
    `apply_result()` (the latest result sets `s["paces"]` and `s["result"]` via `pace_engine.from_result`) →
    generate → `ankle_state()` → `scale_and_shift_runs()` (each week by the smaller of the *previous* week's
    check-in factor and the missed-week guard, `volume_guard()`: known weeks are over and covered by
    `last_sync`, marked `w["synced"]`; fuel notes; moves, then relocate) → `join_actuals()` (actual runs by date;
    a day with two runs shares its actual, the longer run gets the review; then `attach_strength()`, shifted
    before logs are looked up, with suggestions and snacks; then relocate strength) → `mark_done_and_movable()`.
  - Recovery: `Facts` also holds `wellness` and `trims`. `scale_and_shift_runs()` applies trims (the rest of the week at
    0.9 and a rep off the next session, or the next run easy at 0.8; never race week) from the trim's stored `start`
    (today, or tomorrow when today's run had synced when it was pressed), so the trimmed runs and the easy run stay
    fixed once they sync; a session with no rep to drop is scaled at min(factor, 0.9) instead,
    `recovery_state()` puts `recovery.state()` on each week, and strength follows a trim (loads held).
  - Also the questions pages ask of a built view: `missing_runs()`, `session_at()`, `move_warning()`.
  - Page data from a built view, pure too: `dashboard()` is everything This week shows (`next_run()`, `last_run()`,
    `ankle_tests()`, `last_summary()`, `profile()`, the token warning); its route only adds the message and sync line.
- `app/main.py` — the shell: routes, the auth and same-origin middlewares, Jinja filters, and `build_view()`,
  which is `view.build_view(view.load_facts(), today())` (tests patch `main.today`). This week and Progress go
  through `view_with_sync()`, which syncs first when a run from yesterday or today is missing, or before 12:00
  (`main.now()`) when today's wellness row or its `hrv_night` is missing, and neither
  `last_sync` nor `last_sync_try` in `meta` is under 15 minutes old (only with `GARMIN_API_KEY`; a quick sync,
  `garmin_sync.QUICK`: details for the newest 4 runs, wellness range endpoints from 27 days back (one call each),
  4 resting-HR days, 8 s timeout, while Sync fetches the rest).
  Routes: `/`, `/plan`, `/progress`, `/race`, `/goal` (POST), `/fuel` (POST, toggles the tick on a done long run with a note), `/strength`, `/equipment` (GET/POST), `/workout/{date}.fit?n=`,
  `/workouts/week/{n}.zip`, `/sync`, `/recovery` (POST: takes the offered `trim` or `easy`, never in race week), `/checkin`, `/strength/log` (POST), `/snack` (POST), `/ankle/check` (POST),
  `/ankle/tests` (POST), `/result` and `/result/delete` (POST), `/manifest.webmanifest` and the icons (from
  `app/static/`, outside the password so Android can install the app), `/move` (POST; warns via `/?confirm=…` on a clash), `/move/undo` (POST).
  POSTs redirect with a 303 to their anchor.
- `app/pace_engine.py` — pace maths. `from_result()` turns a result into paces and a goal verdict: easy,
  long, threshold and interval from fitness; marathon stays the settings' goal pace unless within 10 s/km of
  threshold or the goal is >5% off; sub-threshold MP − 9, never quicker than threshold.
- `app/progress.py` — pure, the Progress page: `fitness_trend` (median HR of easy/long km splits within ±15 s/km
  of the *settings* easy pace, km 1 dropped, ≥3 splits a week), `long_runs` (drift colours), `plan_bars`,
  `verdict` (from `s["result"]`), `goal_options` (stretch = prediction × (1 − min(4%, 1% per 4 weeks left)),
  prediction, way back), `why_rows`, `ankle_table`, `summaries` (completed weeks; "Next week" = first rule
  that applies: ankle trigger, next week held, easy too quick, long-run drift, snacks < 4, strength missed,
  test week).
- `app/fuel.py` — pure: `gel_minutes` (45, then every 35, none in the last 10; runs ≥ 90 min only),
  `long_run_note(km, mp_km, long_pace)`, `race_plan(mp, stations, gel_stations)` (first 5 km MP + 5, the rest
  quicker so the finish is MP × 42.195; gels before the first gel station carried, later ones at the last gel
  station at or before their km). `build_view` sets `wo["fuel"]`, `wo["gels"]` and `wo["fuelled"]`.
- `app/garmin.py` — builds FIT workout files with `fit-tool`; pace targets are speed ranges (m/s) around
  `settings.paces`. Repeat blocks become a `REPEAT_UNTIL_STEPS_CMPLT` step after their steps, pointing back
  to the block's first step index, mirroring Garmin Connect's own files (samples in `samples/garmin/`,
  untracked). Single-step and tempo files are confirmed on the user's watch. Easy and long runs open with a `WARMUP_KM` (1 km) open-target warm-up
  step inside their planned km; race day doesn't.
- `app/garmin_api.py` — Garmin Personal API client. `GARMIN_API_KEY` is exchanged for an access token (~24 h, no
  refresh token) cached in `meta` and re-fetched when under an hour is left; one retry on a 401; failures are
  `SyncError` messages on the dashboard. `GARMIN_API_KEY_EXPIRES` (YYYY-MM-DD) gives `key_expiry()`; the
  dashboard warns from 7 days before. The `probe` CLI saves raw responses for field checking.
- `app/fitfile.py` — pure: an activity FIT ZIP to the cumulative km splits and laps `review.py` reads. Laps are
  typed `work` only when the file holds a workout with 2+ active steps; lenient on bad UTF-8. Uses fit-tool's
  private `_project_raw` (version pinned in requirements).
- `app/garmin_sync.py` — `sync_runs()` pages the activity search, upserts `activities`, then fetches the FIT ZIP
  once per new run into `run_files`/`run_details` (`run_source` marks Garmin rows); `sync_wellness()` fills
  `wellness` (HRV, resting HR, sleep, stress, weight); `sync()` does both. A Garmin run replaces the matching
  older row (same date, km within 3% or 0.2 km), taking over its `run_details` until its own FIT arrives (FIT is
  fetched for runs with no `run_files` row). A FIT that fails is retried next sync, logged and counted in `meta`
  `garmin_fit_failures`. An `activities` row with no `run_source` entry came from Smashrun, the previous source
  (removed).
- `app/recovery.py` — pure HRV episode state, recomputed per request. Starts on 3 nights below the HRV band or a
  low 7-day average; the next judged run (HR at easy pace, drift) confirms it (advice) or not (note); firm after
  3 more nights or 2 more runs; clears on 2 nights in band. `offer` says which button (`trim`, then `easy`) the
  page may show; only a stored choice changes the plan. Resting HR and sleep are support, never a start.
- `app/review.py` — pure post-run review, recomputed per request like the plan: per-km pace and HR from
  splits, heart-rate drift (second half against first, first km excluded), easy runs quicker than MP + 20 s
  flagged, the long run's MP finish checked from its last splits, and structured sessions checked rep by
  rep from Garmin `work` laps (within 10 s/km is on pace). Strides days list each stride without judging it, skip drift, and
  warn (never "bad") only when the easy running around them is too quick. `build_view` attaches `review` to each planned
  workout whose day has a synced run with details (the day's longest run).
- `app/db.py` — tables: `activities` (synced runs), `run_details` (JSON km splits and laps per run),
  `checkins` (keyed by week number), `strength_logs` (logged sets, weight, reps, rating, ankle pain),
  `snack_logs` (daily ankle snack ticks), `ankle_tests` (readiness test values), `ankle_checks` (morning ankle checks),
  `moves` (a session's original date + `run`/`A`/`B` → new date, or NULL when skipped), `wellness` (daily HRV, resting HR, sleep, stress, weight), `recovery_trims` (recovery choices: date pressed + `trim`/`easy` + `start`, the first day it applies), `run_files` (original FIT per Garmin run), `run_source` (which activities came from Garmin), `results` (races and
  time trials: date, km, seconds), `goals` (goal changes: date, goal_time or "settings"; the latest wins), `fuel_logs` (date of a long run fuelled as planned) and `meta` (key/value; `last_sync` is written by a successful sync,
  `last_sync_try` by each sync on open).
  Schema is `CREATE IF NOT EXISTS` on startup; there are no migrations. `DB_PATH` env var overrides `data/marathon.db`.

## Conventions

- Units: distances in km, paces in **seconds per km**, durations in seconds. Format only at display time
  (`fmt_pace` / `pace_mi` Jinja filters registered in `main.py`).
- Planned km are rounded to 0.5 km.
- Strength defaults to Tuesday (B) and Thursday (A), the non-running days, but stays configurable via
  `strength_days` in `settings.json`. Don't hardcode the days.
