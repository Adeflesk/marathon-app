# Garmin Sync and Recovery Signal Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace Smashrun with the Garmin Personal API as the only sync source (runs from FIT files, plus daily HRV, sleep, resting HR, stress and weight), and add an HRV-led recovery signal that a run must confirm before it advises a trim the user can take.

**Architecture:** A small Garmin client (`garmin_api.py`) does the key → token exchange and GETs. `fitfile.py` turns an activity FIT into the splits and laps `review.py` already reads. `garmin_sync.py` writes runs to the existing `activities` and `run_details` tables, and wellness to a new table. `recovery.py` is pure: it replays wellness and runs into the episode state on every request. The only new stored facts are wellness rows and the user's taken trims, and `view.build_view` applies those trims the same way it applies check-ins.

**Tech Stack:** Python 3, FastAPI, Jinja2, SQLite, httpx (`MockTransport` in tests), fit-tool (FIT encode/decode).

**Spec:** `docs/superpowers/specs/2026-11-13-garmin-sync-design.md`

## Global Constraints

- `load_facts()` is the only storage read; `build_view` and every new logic module stay pure and are tested without the network.
- No migrations: new tables use `CREATE TABLE IF NOT EXISTS` in `db.init()`, and no existing table changes.
- Units: km, s/km, seconds; HRV in ms, HR in bpm. Planned km rounded to 0.5 (`plan._half`).
- Recovery only ever trims, and never by itself. A trim happens only after the user presses the button. Race week is never trimmed.
- The trim is taken once per episode: 0.9 from the trim date to Sunday, plus one rep off the next quality session (never below 2). Strength follows like a "tired" check-in (`factor` 0.9: trimmed, loads held).
- "Make the next run easy" is offered only on a firm warning after the trim was taken: the next run becomes easy at 0.8 of its km.
- Thresholds are named constants in `recovery.py`: `RHR_UP = 5` bpm over the 30-day mean; `SLEEP_SHORT = 6 * 3600` s or `SLEEP_POOR = 60` score, two nights running; `HR_UP = 5` bpm at easy pace vs the 4-week median; `DRIFT_CONFIRM = 10` % when the 4-week median drift < `DRIFT_NORMAL = 5` %; firm after `FIRM_NIGHTS = 3` nights or `FIRM_RUNS = 2` runs since advice.
- Env: `GARMIN_API_KEY`, `GARMIN_API_KEY_EXPIRES` (YYYY-MM-DD); the dashboard warns 7 days before.
- The user's key goes in `.env` (local) and as a Fly secret. Never paste it into chat or commit it. Sample API responses go in `samples/garmin-api/` (untracked, like `samples/garmin/`).
- Plain wording on pages, matching the rest of the app.

## Review Focus

1. **Missing wellness nights** (watch not worn, data not in yet). A gap is neither low nor in band: it doesn't count toward "three in a row" and doesn't clear an episode. → test in Task 6.
2. **A planned session run without starting the watch workout.** Its auto-laps must not be judged as reps: laps get `lapType "work"` only when the FIT has workout steps. → test in Task 2.
3. **Sync-on-open before last night's data is in.** Today's wellness row is refreshed on each sync, and a missing row for today also counts as "something missing" for sync on open. → test in Task 5.
4. **Two runs on a date during switch-over** (a Smashrun row and a Garmin row for each). They pair by distance order, so nothing is double-counted and nothing is lost. → test in Task 3.
5. **Pressing a recovery button that is no longer offered** (stale page, episode cleared, race week, already taken). The POST recomputes the view and refuses with a message instead of storing a fact. → test in Task 7.

---

### Task 1: Probe the real account and add the Garmin client

The user has a one-year key. Before anything relies on field names, capture real responses.

**Files:**
- Create: `app/garmin_api.py`
- Modify: `tests/conftest.py`, `.env.example`
- Test: `tests/test_garmin_api.py`

**Interfaces:**
- Produces:
  - `BASE = "https://personal.connectapi.garmin.com"`
  - `class SyncError(Exception)`
  - `KEY_WARN_DAYS = 7`
  - `key_expiry() -> date | None`, read from `GARMIN_API_KEY_EXPIRES`
  - `token(client: httpx.Client) -> str`: cached in `meta` as `garmin_token` / `garmin_token_exp`; re-fetched when under 1 h is left; `SyncError` naming the key when the exchange returns 401/403
  - `get(client, path: str, params: dict | None = None) -> httpx.Response`: Bearer header; on a 401, drops the cached token, re-fetches once and retries once
  - `python -m app.garmin_api probe [days]`: writes each endpoint's JSON (and one activity ZIP) to `samples/garmin-api/`

- [ ] **Step 1: Ask the user to add `GARMIN_API_KEY=` and `GARMIN_API_KEY_EXPIRES=` to `.env`** (and add both, empty, with a comment, to `.env.example`). Wait for confirmation.
- [ ] **Step 2: Write failing tests** with `httpx.MockTransport`:
  - `test_token_exchanged_with_api_key_header`: the POST to `/personalapitoken-service/personal-api/personal-api-key/token` carries `Authorization: ApiKey k`.
  - `test_token_cached_until_an_hour_left`: two `get` calls make one exchange; with the cached expiry 30 min away, a new exchange happens.
  - `test_401_refetches_token_once`: the first data call returns 401 and the retry 200, giving 2 exchanges and a 200. A second 401 raises `SyncError`.
  - `test_missing_key_raises`: `"GARMIN_API_KEY is not set"` in the message.
  - `test_key_expiry`: `"2027-11-01"` → `date(2027, 11, 1)`; empty or garbage → `None`.
- [ ] **Step 3: Run** `pytest tests/test_garmin_api.py -v`. Expected: FAIL (no module).
- [ ] **Step 4: Implement `app/garmin_api.py`.** Read the token's expiry from the response's `expires_in` if present, otherwise from the JWT `exp` claim (base64-decode the middle segment; no new dependency). Add the probe `__main__`, covering the run and wellness endpoints listed in the spec over the last `days` (default 14).
- [ ] **Step 5: Block the network in tests.** In `conftest.py`, add an autouse fixture like `no_smashrun`: `delenv("GARMIN_API_KEY")`, and patch `garmin_api.httpx.Client` to raise.
- [ ] **Step 6: Run** `pytest -q`. Expected: all pass.
- [ ] **Step 7: Run the probe against the real account** with `python -m app.garmin_api probe 14`, and list `samples/garmin-api/`. Record in a short `samples/garmin-api/FIELDS.md` (untracked) the field names actually seen for: activity id, local start time, distance (units), duration, average HR, activity type key; HRV last night / weekly average / baseline low / high; sleep seconds and score; resting HR; stress average; weight. Later tasks map from these. Expected names (verify, don't trust): `activityId`, `startTimeLocal`, `distance` (m), `duration`, `averageHR`, `activityType.typeKey`; `hrvSummaries[].lastNightAvg`, `weeklyAvg`, `baseline.balancedLow`/`balancedUpper`; `dailySleepDTO.sleepTimeSeconds`, `sleepScores.overall.value`; `restingHeartRate`; `averageStressLevel`.
- [ ] **Step 8: Commit** `app/garmin_api.py tests/test_garmin_api.py tests/conftest.py .env.example` with the message "Garmin Personal API client: key → token, cached, one retry on 401".

### Task 2: FIT activity → splits and laps

**Files:**
- Create: `app/fitfile.py`, `tests/fitdata.py` (builds test FIT ZIPs with fit-tool)
- Test: `tests/test_fitfile.py`

**Interfaces:**
- Produces `fitfile.details(zip_bytes: bytes) -> dict` returning `{"splits": [...], "laps": [...]}` in the Smashrun shape `review.py` reads:
  - splits: cumulative `{"distance": km, "seconds": s, "heartRate": bpm|None}`, one per whole km plus a final partial one
  - laps: cumulative `{"endDistance": km, "endDuration": s, "lapType": str}`
- `tests/fitdata.py`: `make_zip(records: list[tuple[float, float, int]], laps: list[tuple[float, float, str]], workout: bool) -> bytes`. Records are `(seconds, metres, hr)` and laps are `(metres, timer_seconds, intensity)`.

- [ ] **Step 1: Write failing tests:**
  - `test_km_splits_from_records`: 1 Hz records for 2.5 km at 300 s/km, HR 140 then 150. Splits are at 1, 2 and 2.5 km with seconds 300, 600 and 750, and `heartRate` is the mean HR within each km.
  - `test_pause_not_counted`: a 120 s gap between two records 5 m apart adds no time. Any gap over 10 s is a pause.
  - `test_workout_laps_typed`: with `workout=True`, laps with intensities `warmup, active, rest, active, cooldown` → `lapType` `warmup, work, rest, work, cooldown`, cumulative.
  - `test_free_run_laps_are_not_reps`: with `workout=False`, every `lapType` is `"general"`.
  - `test_review_reads_it`: `review.review` on a planned workout with steps, fed `details(...)`, gives one rep per active lap.
- [ ] **Step 2: Run** `pytest tests/test_fitfile.py -v`. Expected: FAIL.
- [ ] **Step 3: Implement `details`.** Open the single `.fit` in the ZIP and decode it with fit-tool. A file "has a workout" when it contains `workout_step` messages, or laps carrying `wkt_step_index`. Interpolate the time at each km boundary from the records either side.
- [ ] **Step 4: Run.** Expected: PASS. Then run `details` on the probe's real ZIP from `samples/garmin-api/` and check the splits by eye against Garmin Connect's splits for that run (pace within a few s/km).
- [ ] **Step 5: Commit** with the message "Read Garmin activity FIT files into km splits and typed laps".

### Task 3: Run sync into the existing tables

**Files:**
- Create: `app/garmin_sync.py`
- Modify: `app/db.py` (tables `run_files(id INTEGER PRIMARY KEY, fit BLOB NOT NULL)` and `run_source(id INTEGER PRIMARY KEY, source TEXT NOT NULL)`)
- Test: `tests/test_garmin_sync.py`

**Interfaces:**
- Consumes: `garmin_api.get`, `garmin_api.SyncError`, `fitfile.details`
- Produces:
  - `garmin_sync.sync_runs(client, since: date, max_details: int) -> int` (the number of runs saved)
  - `MAX_DETAILS_PER_SYNC = 40`
  - `RUN_TYPES = {"running", "treadmill_running", "trail_running", "track_running"}`, adjusted to the type keys seen in `FIELDS.md`

- [ ] **Step 1: Write failing tests** (MockTransport, using the shapes from `FIELDS.md`):
  - `test_runs_saved_with_km_and_local_date`: metres are converted to km, the date comes from local start time, and a cycling activity is ignored.
  - `test_details_fetched_once_newest_first`: the second sync downloads nothing; with `max_details=1`, only the newest run gets details.
  - `test_fit_stored`: the `run_files` row holds the ZIP's FIT bytes.
  - `test_replaces_matching_smashrun_row`: a stored Smashrun row on 2026-11-10 (10.0 km, with `run_details`), then a Garmin run that date at 10.1 km. The Smashrun row and its details are gone, and the Garmin row is in `run_source` as `garmin`.
  - `test_keeps_unmatched_smashrun_rows`: a Smashrun 8 km row with a Garmin 12 km run the same date both stay; a Smashrun row on a date with no Garmin run stays.
  - `test_two_runs_a_day_pair_by_distance` (Review Focus 4): Smashrun 5.0 and 10.0, Garmin 10.05 and 5.02 the same date. Both Smashrun rows are replaced, and the day's km is ≈ 15.07, not 30.
- [ ] **Step 2: Run** `pytest tests/test_garmin_sync.py -v`. Expected: FAIL.
- [ ] **Step 3: Implement `sync_runs`.**
  - Page through the search with `start`/`limit=100` and `startDate=since`, stopping on an empty page.
  - Upsert into `activities`, writing `run_source` too.
  - A row counts as Smashrun-sourced when it has no `run_source` entry. It matches when the date is the same and the km is within 3 % or 0.2 km, pairing by sorted distance.
  - For up to `max_details` runs without `run_details`, newest first: download the ZIP and store `run_files` and `run_details` (`json.dumps` of `details()`). A run that fails is retried next sync.
- [ ] **Step 4: Run.** Expected: PASS.
- [ ] **Step 5: Commit** with the message "Sync runs from Garmin: activities, FIT files, splits and laps; replaces matching Smashrun rows".

### Task 4: Wellness sync and storage

**Files:**
- Modify: `app/garmin_sync.py`, `app/db.py`
- Test: `tests/test_garmin_wellness.py`

**Interfaces:**
- Produces:
  - table `wellness(date TEXT PRIMARY KEY, hrv_night REAL, hrv_week_avg REAL, hrv_low REAL, hrv_high REAL, rhr INTEGER, sleep_s INTEGER, sleep_score INTEGER, stress_avg INTEGER, weight_kg REAL, raw TEXT)`
  - `db.wellness() -> list[dict]`, oldest first, without `raw`
  - `garmin_sync.sync_wellness(client, since: date, until: date) -> int`, which uses the range endpoints (HRV daily, sleep summaries, wellness activity summary, weight) and maps fields from `FIELDS.md`
  - A field missing for a day stays `NULL`

- [ ] **Step 1: Write failing tests:**
  - `test_wellness_row_per_day`: range responses for 3 days give 3 rows with every column mapped.
  - `test_today_refreshed`: a second sync with new values for today replaces today's row.
  - `test_missing_day_is_null_not_zero`: a night with no HRV gives `hrv_night IS NULL`.
  - `test_raw_kept`: `raw` holds each endpoint's JSON for that day.
- [ ] **Step 2: Run.** Expected: FAIL. **Step 3: Implement.** Split ranges into chunks if an endpoint caps its span (check the probe; start at 28 days). **Step 4: Run.** Expected: PASS.
- [ ] **Step 5: Commit** with the message "Sync daily HRV, sleep, resting HR, stress and weight from Garmin".

### Task 5: Switch the app's sync to Garmin

**Files:**
- Modify: `app/garmin_sync.py`, `app/main.py` (`run_sync`, `view_with_sync`, dashboard expiry), `app/view.py` (`Facts.wellness`, `load_facts`, `dashboard` key warning), `app/templates/index.html` (key warning, sync wording), `app/templates/_sync_line.html`
- Test: `tests/test_auto_sync.py`, `tests/test_token_warning.py` (rewrite for Garmin), `tests/test_view_pure.py`

**Interfaces:**
- Consumes: Tasks 1, 3 and 4
- Produces:
  - `garmin_sync.sync(since: date, max_details=MAX_DETAILS_PER_SYNC, timeout=TIMEOUT, wellness_days: int | None = None) -> int`, which syncs runs then wellness from `since − 32 days` (so the 30-day RHR baseline exists), or only the last `wellness_days`, then sets `last_sync`
  - `QUICK = {"max_details": 4, "timeout": 8, "wellness_days": 3}`
  - `Facts.wellness: list[dict]`

- [ ] **Step 1: Update the tests first.**
  - `test_auto_sync.py`: fake `garmin_sync.sync`, set `GARMIN_API_KEY` to `"fake"`, and assert `QUICK` is passed. The missing-run line reads "isn't in Garmin yet".
  - Add `test_missing_wellness_today_syncs` (Review Focus 3): no wellness row for today, runs all in → the sync runs.
  - `test_token_warning.py`: `GARMIN_API_KEY_EXPIRES` 5 days out → "Your Garmin key runs out" and `GARMIN_API_KEY_EXPIRES` on the page; 30 days out → nothing.
  - `test_view_pure.py`: `Facts` built with `wellness=[]`.
- [ ] **Step 2: Run.** Expected: FAIL.
- [ ] **Step 3: Implement.**
  - `run_sync` calls `garmin_sync.sync`, and the message says "Synced N runs from Garmin."
  - `view_with_sync` syncs when `GARMIN_API_KEY` is set, the sync is due, and a run is missing or today's wellness row is missing.
  - The key warning text tells the user to make a new key at connect.garmin.com/app/settings/personalApiToken, then run `fly secrets set GARMIN_API_KEY=… GARMIN_API_KEY_EXPIRES=…`.
- [ ] **Step 4: Run** `pytest -q`. Expected: all pass.
- [ ] **Step 5: Verify against the real account.** Run `uvicorn app.main:app --reload`, press Sync, and check on This week and Progress that:
  - last week's runs show
  - a quality session shows its rep-by-rep review
  - the fitness trend still has its earlier weeks (from Smashrun history)
  - the week totals aren't doubled

  Show the user and get their OK before Task 9.
- [ ] **Step 6: Commit** with the message "Sync from Garmin instead of Smashrun; key expiry warning".

### Task 6: Recovery signal (pure)

**Files:**
- Create: `app/recovery.py`
- Test: `tests/test_recovery.py`

**Interfaces:**
- Consumes: `review.splits`, `review.drift` (on run details), and the wellness rows from Task 4
- Produces:
  - `recovery.Run`: a dict `{"date": date, "kind": "easy"|"quality"|"strides", "splits": list|None, "drift": float|None, "verdict": str|None}`
  - `recovery.state(wellness: list[dict], runs: list[Run], trims: list[dict], t: date, easy_pace: float) -> dict` returning:
    `{"phase": "none"|"suspect"|"note"|"advice"|"firm", "since": date|None, "reasons": [str], "support": [str], "run": Run|None, "trim_taken": bool, "easy_taken": bool, "offer": "trim"|"easy"|None, "rest": bool, "last": dict|None}`
  - `"last"` is the latest wellness row. `"offer"` ignores race week, which the view handles.
  - `trims` are `{"date": str, "kind": "trim"|"easy"}` rows.

**Rules** (replay day by day from the first wellness date to `t`):
- low(d) = `hrv_night < hrv_low`; avg_low(d) = `hrv_week_avg < hrv_low`; NULL is neither low nor in band.
- An episode starts on d when low(d − 2..d) all hold, or avg_low(d).
- It clears on d when d and d − 1 both have HRV ≥ `hrv_low` and avg_low(d) is false. After that, a new episode can start.
- Judging a run on or after the episode start (in date order):
  - strides → skipped
  - quality → `verdict == "bad"` confirms; any other verdict is normal; no verdict → skipped
  - easy/long → value = median HR of `splits[1:]` with km ≥ 0.9, an HR, and pace within 15 s/km of `easy_pace`. Fewer than 3 such splits → skipped. Baseline = median of the values of the judged runs in the previous 28 days; with fewer than 2 runs, HR can't confirm. The run confirms if value ≥ baseline + `HR_UP`, or drift ≥ `DRIFT_CONFIRM` while the 28-day median drift < `DRIFT_NORMAL`.
- Phases:
  - suspect: no judged run yet
  - note: judged runs, all normal
  - advice: confirmed
  - firm: `FIRM_NIGHTS` nights or `FIRM_RUNS` judged runs after confirmation without clearing
- Support (wording in `support`):
  - "Resting heart rate is up N bpm" when the latest RHR ≥ 30-day mean + `RHR_UP`
  - "Short or poor sleep two nights running" when the last 2 nights each have `sleep_s < SLEEP_SHORT` or `sleep_score < SLEEP_POOR`
- `rest` = phase firm and any support.
- Offers:
  - "trim" when phase is advice or firm and no trim falls inside the episode
  - "easy" when phase is firm, a trim was taken, and no easy was taken
- `reasons` is plain text, e.g. "HRV below your normal range 3 nights running" / "7-day HRV average below your normal range", and "easy-pace heart rate up 6 bpm on Tuesday's run".

- [ ] **Step 1: Write failing tests**, with wellness built by a helper (band 50–70 ms):
  - `test_two_low_nights_nothing`
  - `test_three_low_nights_suspect`
  - `test_low_week_average_suspect`
  - `test_gap_breaks_the_run_and_doesnt_clear` (Review Focus 1): low, NULL, low, low → suspect starts only on the 4th night. An episode with NULL, NULL nights after it stays open.
  - `test_normal_run_note`
  - `test_raised_easy_hr_confirms_advice` (+6 bpm vs a 3-run baseline, `reasons` mentions "up 6 bpm")
  - `test_drift_confirms_only_when_usually_steady`
  - `test_bad_quality_confirms`
  - `test_strides_and_thin_runs_skipped`
  - `test_firm_after_three_nights`
  - `test_firm_after_two_runs`
  - `test_two_in_band_nights_and_avg_clear`
  - `test_offer_trim_once_per_episode`
  - `test_offer_easy_only_firm_after_trim`
  - `test_new_episode_after_clear_offers_trim_again`
  - `test_rest_when_firm_with_support`
  - `test_support_never_starts_an_episode` (RHR +10 and short sleep with HRV in band → phase none)
- [ ] **Step 2: Run** `pytest tests/test_recovery.py -v`. Expected: FAIL.
- [ ] **Step 3: Implement.** **Step 4: Run.** Expected: PASS.
- [ ] **Step 5: Commit** with the message "Recovery signal: HRV suspicion confirmed or cleared by the next run".

### Task 7: Taking the trim, and applying it

**Files:**
- Modify:
  - `app/db.py`: table `recovery_trims(date TEXT NOT NULL, kind TEXT NOT NULL, created TEXT, PRIMARY KEY(date, kind))`, plus `db.trims()` and `db.add_trim(day, kind)`
  - `app/view.py`: `Facts.trims`, plus a pipeline step `recovery_state()` after `join_actuals` that sets `w["recovery"]` on every week; trims applied in `scale_and_shift_runs`; strength factor in `attach_strength`
  - `app/sessions.py`: `drop_rep()`
  - `app/strength.py`: trim note
  - `app/main.py`: `POST /recovery`
- Test: `tests/test_recovery_view.py`

**Interfaces:**
- Consumes: `recovery.state`, `recovery.Run`
- Produces:
  - `view.recovery_runs(weeks, f, s) -> list[Run]`: every date in `f.actual` with details, judged from its main run's details. The kind comes from the planned workout on that date after moves (strides → `"strides"`, has `steps` → `"quality"` with that workout's review verdict, otherwise `"easy"`), and an unplanned date counts as `"easy"`.
  - `sessions.drop_rep(workout: dict, paces: dict) -> bool`: removes one rep from the first repeat block when it has more than 2, then recomputes km and note. It returns whether it dropped one.
  - `POST /recovery` (form `kind`) → 303 to `/#recovery`

**Applying the stored trims (in `scale_and_shift_runs`, before moves):**
- **kind `trim` on date D:** in D's week, unless it's Race week:
  - each run dated ≥ D is scaled to an overall factor of `min(run_factor, 0.9)`
  - the first quality run dated ≥ D: if scaling it didn't reduce its reps, call `drop_rep`
  - `w["recovery_trim"] = D`
- **kind `easy` on date D:** the first non-skipped, non-race run with km > 0 dated ≥ D becomes `{"type": "easy", "km": _half(km * 0.8), "pace": "easy", "note": <easy note as generate writes it>}`, keeping `date`/`day`, with `steps`/`mp_km` removed.
- **Strength:** in `attach_strength`, sessions dated ≥ `w["recovery_trim"]` get ctx and pctx `factor = min(w["factor"], 0.9)` and `ctx["recovery"] = True`. `strength.sessions_for_week` then adds the note "Trimmed for recovery: low HRV, confirmed by your last run." in place of the check-in note when the check-in factor is 1.0.

- [ ] **Step 1: Write failing tests:**
  - `test_trim_scales_rest_of_week_only` (runs before D unchanged; runs ≥ D at 0.9)
  - `test_trim_doesnt_stack_on_tired_checkin` (check-in 0.9 + trim → still 0.9, but a rep is dropped)
  - `test_trim_drops_a_rep_never_below_two`
  - `test_trim_ends_sunday`
  - `test_race_week_untouched`
  - `test_easy_replaces_next_run`
  - `test_strength_after_trim_held` (the suggestion doesn't increase load; note shown)
  - `test_post_recovery_stores_when_offered`
  - `test_post_recovery_refused_when_not_offered` (Review Focus 5: no episode / already taken / race week / `kind=easy` without firm → no row stored, a 303 with a message)
- [ ] **Step 2: Run.** Expected: FAIL. **Step 3: Implement.** The POST rebuilds the view and stores only when `weeks[0]["recovery"]["offer"] == kind` and the current week isn't Race week. **Step 4: Run** `pytest -q`. Expected: all pass.
- [ ] **Step 5: Commit** with the message "Take the recovery trim: rest of week at 0.9, a rep off, strength held; or make the next run easy".

### Task 8: Pages

**Files:**
- Modify: `app/view.py` (`dashboard()` adds `"recovery"`), `app/progress.py` (`recovery_trend(wellness, t) -> list[dict]`, per day for the last 8 weeks: `hrv_night`, `hrv_week_avg`, `hrv_low`, `hrv_high`, `rhr`, `sleep_s`), `app/main.py` (progress context), `app/templates/index.html`, `app/templates/progress.html`
- Test: `tests/test_recovery_pages.py`

- [ ] **Step 1: Write failing tests** (TestClient with seeded tables, as `tests/test_progress_page.py` does):
  - `test_panel_shows_last_night` (HRV value and band, resting HR, sleep in h:mm)
  - `test_suspect_is_quiet` (no `role="alert"` card; one quiet line)
  - `test_note_text` ("looked normal")
  - `test_advice_card_with_button`
  - `test_firm_card_wording` ("hasn't improved"; with support it recommends an easy day or rest)
  - `test_easy_button_only_when_offered`
  - `test_no_trim_button_in_race_week`
  - `test_progress_shows_hrv_rhr_sleep_charts` (three `svg.chart` with aria-labels)
  - `test_panel_hidden_without_wellness`
- [ ] **Step 2: Run.** Expected: FAIL.
- [ ] **Step 3: Implement.**
  - **This week:** `<section id="recovery">`, placed after the sync line and before the hero. The advice/firm card goes above the panel and uses the existing `.notice` styling.
  - **Progress:** the charts copy the fitness-trend SVG pattern. HRV has a shaded band, nightly dots and a 7-day line, with resting HR and sleep beside it.
  - Stress and weight appear in the panel/Progress as plain numbers only.
- [ ] **Step 4: Run** `pytest -q`. Expected: all pass. Then open both pages with real synced data and screenshot them for the user.
- [ ] **Step 5: Commit** with the message "Recovery panel on This week, HRV, resting HR and sleep trends on Progress".

### Task 9: Remove Smashrun and update the docs

Only after the user's OK in Task 5, Step 5.

**Files:**
- Delete: `app/smashrun.py`, `tests/test_sync_details.py`
- Modify: `tests/conftest.py` (drop `no_smashrun`), `app/view.py` and `app/main.py` (imports), `.env.example` (Smashrun lines), `README.md` (making the key, choosing 1 year, the Fly secrets, what the recovery panel and advice mean), `CLAUDE.md` (replace the `smashrun.py` entry with `garmin_api.py` / `fitfile.py` / `garmin_sync.py` / `recovery.py`; new tables; `/recovery` route)

- [ ] **Step 1:** Run `grep -rni smashrun app tests README.md CLAUDE.md .env.example`. Every hit is either removed or reworded, except the comment noting old rows came from Smashrun.
- [ ] **Step 2: Run** `pytest -q`. Expected: all pass.
- [ ] **Step 3: Commit** with the message "Remove Smashrun: Garmin is the only sync source".
- [ ] **Step 4: Deploy** after the user's OK: `fly secrets set GARMIN_API_KEY=… GARMIN_API_KEY_EXPIRES=…` (the user runs it, or confirms first), `fly secrets unset SMASHRUN_TOKEN SMASHRUN_TOKEN_ISSUED`, then `fly deploy`. Press Sync on the deployed app and check This week.
