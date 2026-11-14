# Long-run wording, cadence and steps Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Long runs summarised as long runs, a cadence/stride form note and weekly cadence trend from the FIT files, and daily on-feet steps set against ankle trouble with a note only on a repeat pattern.

**Architecture:** `fitfile.details()` gains per-split cadence, step length and contact; sync stores daily steps and per-run steps in two new tables and re-derives old runs' details from `run_files`. `review.py` and `progress.py` stay pure and do the judging; Progress shows two new charts.

**Tech Stack:** Python 3.11, FastAPI, Jinja2, SQLite, fit-tool 0.9.16 (pinned), pytest.

**Spec:** `docs/superpowers/specs/2026-11-14-long-run-wording-cadence-steps-design.md`

## Global Constraints

- Nothing here changes the plan: no trims, no buttons, verdicts unchanged by cadence or steps.
- No message after a single heavy day; the steps note never claims a cause.
- Units: steps/min, metres, milliseconds, seconds per km; format at display time.
- No migrations: new tables via `CREATE TABLE IF NOT EXISTS`, no new columns on existing tables.
- `build_view` and `progress.py` stay pure; tests never reach Garmin (`tests/conftest.py`); FIT tests build files with `tests/fitdata.py`.
- `samples/` is never committed or read by tests.
- Thresholds are named module constants.
- Split cadence = 2 × (`cadence` + `fractional_cadence`) steps/min; only FIT-derived split cadence is used, never activity averages.

## Review Focus

1. A run file with no cadence/step-length fields (older watch, treadmill) → splits carry `None`, no form note, no crash, and the run is not re-derived again next sync.
2. A long run with an MP finish → form note compares only the steady part before the finish.
3. A day whose run has no `run_steps` row yet → that day is left out of the heavy-day test, not counted as all on-feet.
4. Fewer than 14 days with on-feet steps in the previous 28 → no heavy days at all, no note.
5. One bad spell (trouble on consecutive days after consecutive heavy days) → counts once (trouble days ≥ 3 days apart).

---

### Task 1: Long-run wording and short splits

**Files:**
- Modify: `app/review.py` (`splits()`, the generic branch of `review()`)
- Test: `tests/test_review.py`

**Interfaces:**
- Produces: `review.MIN_SPLIT_KM = 0.05`; `splits()` omits splits with `km < MIN_SPLIT_KM`.

- [ ] **Step 1: Write the failing tests** in `tests/test_review.py`:
  - `test_long_run_without_mp_names_planned_long_pace`: workout `{"type": "long", "km": 12}` (no `mp_km`), run 12 km at 6:13/km (`seconds = 12*373`), steady splits; with `settings["paces"]` (long 390, marathon 341) → headline starts `"Long run at 6:13/km (planned 6:30)"`, verdict `"good"`.
  - `test_long_run_quicker_than_mp_plus_20_warns`: same at 5:55/km → verdict `"warn"`, headline contains `"quicker than long-run pace"`.
  - `test_tiny_last_split_dropped`: raw splits ending `{"distance": 12.01, ...}` after `12.0` → `splits()` has 12 entries.
- [ ] **Step 2:** `pytest tests/test_review.py -v` → the three FAIL.
- [ ] **Step 3: Implement.** In `review()`, before the easy branch, handle `workout["type"] == "long"` without `mp_km`: headline `f"Long run at {fmt_pace(avg)}/km (planned {fmt_pace(paces['long'])})"` + `f", {words}."` or `"."`; quicker than `paces["marathon"] + 20` → headline `f"Long run at {fmt_pace(avg)}/km is quicker than long-run pace. Keep it steady."`, verdict `warn`; else verdict as the easy branch (`good` unless drift ≥ 10). `splits()` skips `d < MIN_SPLIT_KM` (still advancing the cumulative counters).
- [ ] **Step 4:** `pytest -q` → all pass (existing easy/MP/strides tests unchanged).
- [ ] **Step 5: Commit** `git commit -am "Long runs without an MP finish say long run and the planned pace; splits under 50 m dropped"`

### Task 2: Cadence, step length and contact per km split

**Files:**
- Modify: `app/fitfile.py` (`details()`, `_splits()`), `tests/fitdata.py` (`make_fit` records)
- Test: `tests/test_fitfile.py`

**Interfaces:**
- Produces: each split dict from `fitfile.details()` always has keys `cadence` (float steps/min, 1 dp, or `None`), `stepLength` (m, 2 dp, or `None`), `contact` (ms, int, or `None`), alongside `distance`, `seconds`, `heartRate`.
- `tests/fitdata.make_fit(records, ...)`: a record may be `(secs, metres, hr)` or `(secs, metres, hr, cadence_spm, step_mm, stance_ms)`; the builder writes FIT `cadence = spm // 2`, `fractional_cadence = (spm / 2) % 1`, `step_length`, `stance_time`.

- [ ] **Step 1: Write the failing tests** in `tests/test_fitfile.py`:
  - `test_splits_carry_cadence_step_length_and_contact`: 2.5 km at 3 m/s, 1 record/s, cadence 176 spm, step 1100 mm, stance 250 ms throughout → every split `cadence == 176.0`, `stepLength == 1.1`, `contact == 250`.
  - `test_cadence_is_time_weighted_per_split`: first km 170 spm, second km 180 → splits 170.0 and 180.0.
  - `test_file_without_cadence_gives_none_keys`: existing 3-tuple records → each split has `cadence is None`, `stepLength is None`, `contact is None` (keys present).
- [ ] **Step 2:** `pytest tests/test_fitfile.py -v` → FAIL.
- [ ] **Step 3: Implement.** Records become `(ts, dist, hr, spm, step_m, stance_ms)`; `_splits` averages each of the three over the split's records like `hrs` (records with a value only; FIT invalid values arrive as `None`). Treat `stance_time` ≥ 6553 or `step_length` ≥ 65535 as invalid (fit-tool may surface sentinels). Memory: same per-record tuple approach; no other fields kept.
- [ ] **Step 4:** `pytest -q` → pass.
- [ ] **Step 5: Commit** `"FIT splits carry cadence, step length and ground contact"`

### Task 3: Sync — daily steps, run steps, backfill

**Files:**
- Modify: `app/db.py` (schema, `steps()`), `app/garmin_sync.py` (`sync_runs`, `sync_wellness` or `sync`, new `_steps`, new `_backfill`, `QUICK`)
- Test: `tests/test_garmin_sync.py`, `tests/test_garmin_wellness.py`

**Interfaces:**
- Tables: `steps(date TEXT PRIMARY KEY, total INTEGER)`, `run_steps(id INTEGER PRIMARY KEY, steps INTEGER)`.
- Produces: `db.steps() -> list[dict]`, oldest first: `{"date": ISO, "total": int, "run": int | None}` where `run` is the sum of `run_steps.steps` over that date's `activities`, `0` with no activities, and `None` when any of that day's activities has no `run_steps` row. Joined at read time.
- `garmin_sync.STEPS_PATH = "/usersummary-service/stats/steps/daily/{s}/{e}"`, `STEPS_CHUNK_DAYS = 14`, response `[{"calendarDate", "totalSteps", ...}]`; `totalSteps` None → no row written.
- `garmin_sync.BACKFILL_PER_SYNC = 10`; `sync(..., backfill: int = BACKFILL_PER_SYNC)`; `QUICK["backfill"] = 0`.

- [ ] **Step 1: Write the failing tests:**
  - `test_run_steps_saved_from_search` (sync tests): a search row with `"steps": 11800` → `run_steps` row 11800; a row without `steps` → no row.
  - `test_steps_range_saved_in_14_day_chunks` (wellness tests, extend the fake with `g.steps = {date: n}`): wellness sync over 27 days → 2 calls to the steps path, `steps` rows for each date given.
  - `test_db_steps_subtracts_runs_and_marks_unknown`: day A total 20000 with a run of 11800 steps → `run == 11800`; day B with a run lacking `run_steps` → `run is None`; day C no runs → `run == 0`.
  - `test_backfill_rederives_details_without_cadence`: a run with a `run_files` FIT (built with cadence) and `run_details` splits lacking `cadence` → after `sync(..., backfill=10)` its splits have `cadence`; a second sync doesn't call `fitfile.details` for it again (count calls via monkeypatch).
  - `test_quick_sync_does_not_backfill`: same setup with `**garmin_sync.QUICK` → splits unchanged.
- [ ] **Step 2:** run them → FAIL.
- [ ] **Step 3: Implement.** In `sync_runs` write `run_steps` beside `activities` when `a.get("steps")` is a number. `_steps(client, since, until)` chunks by `STEPS_CHUNK_DAYS` and upserts `steps`; called from `sync_wellness` with the same `since`/`until`. `_backfill(limit)`: newest first, Garmin runs whose `run_details.splits` JSON has a split without a `"cadence"` key (an empty splits list counts as done) and which have `run_files`; re-run `fitfile.details` on the stored FIT (wrap it in a ZIP or add a `fitfile.details_from_fit(fit_bytes)` sibling—prefer the sibling, `details()` calling it), replace `run_details`; one at a time; a failure goes through `_failed` and isn't retried that sync. Called from `sync()` after `sync_runs` when `backfill > 0`. Add `CREATE TABLE IF NOT EXISTS` for both tables in `db.init` (or wherever the schema lives).
- [ ] **Step 4:** `pytest -q` → pass.
- [ ] **Step 5: Commit** `"Sync stores daily steps and each run's steps, and re-derives older runs' splits with cadence"`

### Task 4: Form note and cadence trend

**Files:**
- Modify: `app/review.py`, `app/progress.py`, `app/main.py` (progress context), `app/templates/index.html` (splits table cadence column), `app/templates/progress.html` (cadence chart in or beside the Ankle section)
- Test: `tests/test_review.py`, `tests/test_progress.py`, `tests/test_progress_page.py`

**Interfaces:**
- Consumes: split keys from Task 2; `review.splits()` from Task 1.
- Produces: `review.splits()` items gain `cadence`, `stride` (= `stepLength`), `contact` (via `.get`, `None` for old rows). `review.form_note(workout: dict, sp: list[dict]) -> str` (empty when nothing to say). Constants `FORM_MIN_KM = 8`, `CADENCE_DROP = 4`, `STRIDE_UP = 0.05`.
- `progress.cadence_trend(weeks, ref_pace) -> list[{"week", "cadence", "stride", "n"}]` (same selection as `fitness_trend`: easy/long, not `steps` sessions, km 1 dropped, splits ≥ 0.9 km, within `PACE_BAND` of `ref_pace`, `MIN_SPLITS` per week, else `None`). `progress.cadence_reading(trend) -> str | None`: median of the last 4 weeks' values against the 4 before; `None` without ≥ 2 weeks with values in each; "steady" within ±`CADENCE_STEADY = 3`, else "rising"/"falling".

- [ ] **Step 1: Write the failing tests:**
  - `test_form_note_cadence_drop`: easy 12 km, km 1–8 at 176, km 9–12 at 170 → note `"Cadence fell from 176 to 170 steps/min in the last 4 km."` (early = km 2 to end of first third, last = final third; `n` = splits in the last third; values rounded to int).
  - `test_form_note_stride_up_without_quicker_pace`: cadence flat, stride 1.00 → 1.06 m late, pace not quicker → `"Your stride lengthened in the last 4 km (1.00 → 1.06 m)."`
  - `test_form_note_none_under_8_km_or_without_cadence`: 7 km run, or splits with `cadence None` → `""`.
  - `test_form_note_mp_long_run_uses_part_before_finish`: long 18 km, `mp_km` 4, cadence 176 for km 1–14 and 184 in the finish → `""` (finish excluded; a drop inside km 1–14 would be noted).
  - `test_form_note_skipped_for_sessions_and_strides`: workout with `"steps"` or `type == "strides"` → review `note` unaffected by cadence.
  - `test_form_note_does_not_change_verdict`: cadence-drop run otherwise steady → verdict `"good"`, note set.
  - `test_cadence_trend_at_easy_pace` and `test_cadence_reading_falling` (progress tests): 8 weeks, last 4 at 170 vs first 4 at 176 → `"falling"`; ±2 → `"steady"`.
  - Progress page test: cadence chart renders with an `aria-label` starting `"Cadence at easy pace"`; absent when the trend has no values.
- [ ] **Step 2:** run → FAIL.
- [ ] **Step 3: Implement.** `review()` sets `out["note"] = form_note(...)` for easy and long runs (both long branches), not overwriting a non-empty note. Index splits table: a "Cadence" column (`x.cadence|round|int` or blank). Progress: pass `cadence` and `cadence_reading` from `main.progress_page`; chart styled like the Fitness chart, one reading line, e.g. "Cadence at easy pace: steady over the last 4 weeks."
- [ ] **Step 4:** `pytest -q` → pass.
- [ ] **Step 5: Commit** `"Form note on easy and long runs, cadence trend at easy pace on Progress"`

### Task 5: Steps against the ankle, and docs

**Files:**
- Modify: `app/ankle.py` (public `trouble_dates`), `app/progress.py`, `app/main.py`, `app/templates/progress.html` (Ankle section), `README.md`, `CLAUDE.md`, `docs/roadmap.md`
- Test: `tests/test_progress.py`, `tests/test_progress_page.py`, `tests/test_ankle.py`

**Interfaces:**
- Consumes: `db.steps()` from Task 3; `db.checks()`, `db.logs()`.
- Produces: `ankle.trouble_dates(checks, logs) -> set[date]` = dates of "worse" morning checks plus `_pain_dates(logs)` (the flag's own rows, no check-ins). `progress.steps_view(steps: list[dict], checks, logs, t: date) -> {"days": [{"date", "on_feet": int | None, "heavy": bool, "trouble": bool}] (last 56 days to t), "pattern": [date, ...]}`; constants `HEAVY_PCTL = 0.8`, `BASELINE_DAYS = 28`, `BASELINE_MIN = 14`, `PATTERN_DAYS = 28`, `PATTERN_MIN = 2`, `PATTERN_GAP = 3`.
  - `on_feet = total - run`, `None` when `run is None`.
  - Heavy: `on_feet` ≥ the 80th percentile (nearest-rank) of the previous 28 days' non-None `on_feet`, needing ≥ 14 of them.
  - `pattern`: heavy days in the last 28 days to `t` whose next date is a trouble date, keeping a day only if its trouble date is ≥ 3 days after the last kept one; returned only when ≥ 2 remain, else `[]`.

- [ ] **Step 1: Write the failing tests:**
  - `test_trouble_dates_are_flag_rows`: a worse check and a log with ankle pain 3 → both dates; a check-in with pain 4 → not included.
  - `test_heavy_relative_to_own_baseline`: 28 days at 15000 then 22000 → heavy; 28 days at 22000 then 22000 → heavy (nearest-rank, ≥); with only 10 prior days → not heavy.
  - `test_run_steps_taken_out`: total 30000, run 18000 → `on_feet == 12000`, not heavy against a 15000 baseline.
  - `test_unknown_run_steps_day_not_judged`: `run None` → `on_feet None`, `heavy False`, and excluded from later baselines.
  - `test_single_heavy_day_with_trouble_no_pattern` → `pattern == []`.
  - `test_two_spaced_episodes_make_a_pattern` → `pattern` lists both heavy dates.
  - `test_one_bad_spell_counts_once`: heavy days 10 and 11 Nov, trouble 11 and 12 Nov → one kept → `pattern == []`.
  - Progress page: with a pattern, the Ankle section shows `"Twice in the last 4 weeks your ankle was worse the day after a heavy day on your feet"` and the dates (`%a %-d %b`); with 3+, "3 times"; without, no such text; the steps chart renders (aria-label starting `"On-feet steps"`) with trouble days marked.
- [ ] **Step 2:** run → FAIL.
- [ ] **Step 3: Implement.** `main.progress_page` passes `progress.steps_view(db.steps(), db.checks(), db.logs(), t)` (read in the route, as `recovery_trend` reads `db.wellness()`). Chart: daily bars over 56 days like the Recovery charts, heavy days a stronger tone, trouble days a marker; one line under it: "Steps with your runs taken out. Heavy days are your top fifth." Pattern note as above, never claiming a cause.
- [ ] **Step 4: Docs.** README: plain-language bits on the long-run summary, the form note, the cadence trend, and the steps chart and when it speaks. CLAUDE.md: `steps`/`run_steps` tables and `db.steps()`, split keys, `form_note`, `cadence_trend`, `steps_view`, `trouble_dates`, backfill (`BACKFILL_PER_SYNC`, full Sync only). Roadmap: tick "Form and steps" under item 4.
- [ ] **Step 5:** `pytest -q` → pass.
- [ ] **Step 6: Commit** `"Steps against ankle trouble on Progress, noted only on a repeat pattern; docs"`
