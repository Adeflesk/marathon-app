# Garmin sync and recovery signal — design

## Why

Garmin opened a Personal API on 21 Oct 2026: a key the user creates in Garmin Connect, read-only, for their own
data, lasting up to a year. Smashrun works fine, so this is not a rescue. The user wants the app to use **all the
data available to it** so its decisions are better informed, and a key that is renewed once a year instead of every
60 days. Garmin is the source the watch writes to; Smashrun only has a copy of the runs.

Two things come out of it:

1. **Garmin replaces Smashrun** as the only sync source, straight away (no side-by-side period). It brings richer
   run data (the original FIT file: per-second HR/pace/cadence, real laps with intensity) and data Smashrun never
   had (HRV, sleep, resting HR, stress, weight).
2. **A recovery signal**: overnight HRV, backed by resting HR and sleep, raises a suspicion; the next run confirms
   or clears it; a confirmed signal becomes advice the user can accept. The plan never changes on its own.

## Goals

- One sync source (Garmin), one key, set as a Fly secret like today's `SMASHRUN_TOKEN`.
- Every existing feature that reads runs (actuals, reviews, rep checks, drift, fitness trend, volume guard, fuel,
  summaries) keeps working on Garmin data, with lap data at least as good as Smashrun's.
- Daily wellness data stored and shown: a recovery panel on This week, trends on Progress.
- The HRV → run-confirmation → advice → monitoring → firmer advice flow below.
- Store enough raw data (FIT files, raw wellness JSON) that later features can use it without a re-sync.

## Non-goals

- Pushing workouts to the watch or Garmin calendar. The Personal API is GET-only; the `.fit` export stays.
- Using stress or weight in any decision (shown only — see Recovery signal).
- Replacing the weekly check-in. How the user feels still counts; the Garmin data sits alongside it.
- Multi-user anything. The Personal API is for personal apps, which this is.

## Anti-goals (a failure even if it works)

- **The plan changing by itself** because of HRV. Recovery only ever produces advice; the user decides.
- **Recovery adjusting up.** Like every other guard, it can only trim. Good HRV never adds volume.
- **Nagging.** HRV alone with a normal run is a quiet note, not a warning. False alarms erode trust in the real ones.
- **Losing history.** Runs already synced (and reviews, fitness trend, volume guard history built on them) must
  survive the switch.
- Breaking the "plan is never stored" rule. Wellness rows and the user's "take the trim" choice are facts; the
  signal, warnings and trims are recomputed per request.

## Constraints

- Architecture in `CLAUDE.md` holds: `load_facts()` is the only storage read, `build_view` stays pure, new logic
  goes in pure modules with tests that never reach the network (`tests/conftest.py` must block Garmin's HTTP client
  the way it blocks Smashrun's today).
- No migrations: schema is `CREATE TABLE IF NOT EXISTS`. New data goes in new tables.
- Units as everywhere: km, s/km, seconds. HRV in ms, HR in bpm.
- Fields must be checked against the user's real account before relying on them (as Smashrun's were). The user
  needs to create a key first; the builder should ask for it at the start and run the endpoints once to capture
  sample responses (kept untracked, like `samples/garmin/`).

### The Garmin Personal API (as of 13 Nov 2026)

- Key created at https://connect.garmin.com/app/settings/personalApiToken (30/90/180/365 days, shown once).
- Key → access token: `POST https://personal.connectapi.garmin.com/personalapitoken-service/personal-api/personal-api-key/token`
  with `Authorization: ApiKey <key>`. Token lasts 24 h (or until the key expires); no refresh token, just ask
  again. Calls use `Authorization: Bearer <token>`.
- Endpoints (from Garmin's own sample client, `github.com/garmin/connect-personal-api-python`), all GET:
  - runs: `/activitylist-service/activities/search/activities?start&limit&startDate&endDate&activityType`,
    `/activity-service/activity/{id}`, `/activity-service/activity/{id}/workouts`,
    `/download-service/files/activity/{id}` (ZIP containing the FIT file)
  - wellness: `/hrv-service/hrv/daily/{start}/{end}`, `/hrv-service/hrv/{date}`,
    `/sleep-service/sleep/dailySleepSummariesByDate?startDate&endDate`, `/sleep-service/sleep/dailySleep?date`,
    `/wellness-service/wellness/dailyHeartRate?date`, `/wellnessactivity-service/activity/summary/range/{s}/{e}`,
    `/weight-service/weight/range/{s}/{e}?includeAll=true`, `/biometric-service/heartRateZones/v2`
- Rate limits and history depth are undocumented. Be gentle: range endpoints over per-day ones, each FIT file
  fetched once, a cap per sync like Smashrun's `MAX_DETAILS_PER_SYNC`.

## Part 1 — Garmin sync replaces Smashrun

**Decided:**

- New module `app/garmin_sync.py` (name is the builder's; `app/garmin.py` is the FIT *workout* builder and stays).
  `sync(since, ...)` mirrors `smashrun.sync`: same `SyncError`, same `QUICK` mode for sync-on-open, writes
  `last_sync` on success. `main.run_sync` and `view_with_sync` call it instead of Smashrun; messages say Garmin.
- Env: `GARMIN_API_KEY`, and `GARMIN_API_KEY_EXPIRES` (YYYY-MM-DD, chosen when the key is made). The dashboard
  warns 7 days before, replacing the Smashrun token warning. The access token is cached in `meta` with its expiry
  and re-fetched when under an hour is left or a call returns 401.
- Runs go into the existing `activities` table, so everything downstream keeps working. Only running activity
  types (running, treadmill, trail, track) are synced.
- Laps and km splits go into `run_details` **in the shape `review.py` already reads** (cumulative
  `distance`/`seconds`/`heartRate` splits; cumulative `endDistance`/`endDuration`/`lapType` laps with `"work"` for
  the watch's active steps), derived from the FIT file: lap messages (FIT `intensity` active → `work`) and record
  messages (km splits computed from distance/time/HR). `fit-tool` (already a dependency) can decode. The builder
  may instead move `review.py` to a neutral shape if cleaner, as long as old Smashrun rows still review.
- The raw FIT bytes are stored once per run in a new table (e.g. `run_files(id, fit BLOB)`), so later features can
  use per-second data without a re-sync.
- **Switching over (my call):** Garmin and Smashrun ids are different numbers for the same run. On a Garmin sync,
  any Smashrun-sourced row on a date Garmin has a run for is replaced by Garmin's (match by date and start time /
  distance within a small tolerance). Smashrun rows with no Garmin match stay as history. To know which rows are
  which, record the source somewhere that needs no migration (e.g. a `run_source(id, source)` table, or the
  builder's better idea).
- Once Garmin sync is verified against the user's account: `app/smashrun.py`, its tests, env vars, `.env.example`
  lines and README/CLAUDE.md mentions are removed. One source.

**Left to the builder:** module layout, how splits are computed from records, exact dedupe tolerance, how the
per-sync cap and backfill window are tuned (start from `plan_start − 28 days` like today), ZIP handling.

## Part 2 — Wellness data

- New table `wellness(date PRIMARY KEY, hrv_night, hrv_week_avg, hrv_low, hrv_high, hrv_status, rhr, sleep_s,
  sleep_score, stress_avg, weight_kg, raw TEXT)` (columns indicative; `raw` keeps the JSON from each endpoint for
  that day). Synced alongside runs; backfill from `plan_start − 60 days` so the baselines exist from the start.
  Today's row is refreshed each sync (last night's sleep/HRV land in the morning).
- `hrv_low`/`hrv_high` is Garmin's own personal "balanced" baseline band. Use it rather than computing one.
- Heart-rate zones may be fetched and shown; not used in decisions in this project.

## Part 3 — Recovery signal

A new pure module (e.g. `app/recovery.py`) takes wellness rows, the built weeks (runs + reviews) and the user's
recovery choices, and returns the current state. It is recomputed every request.

**Method (best practice: HRV-guided training, e.g. Plews; Kiviniemi):** single nights are noisy, so trends against
a personal baseline matter more than one reading. HRV leads; resting HR and sleep only add weight.

1. **Suspicion** (nothing shown except a quiet line in the recovery panel) when either:
   - HRV below `hrv_low` **three nights in a row** (the user's rule), or
   - the 7-day HRV average below `hrv_low` (catches a slow slide).
   Supporting signs, which never start a suspicion on their own: morning resting HR ≥ 5 bpm above its 30-day
   average; sleep under 6 h or a poor Garmin sleep score two nights running.
2. **Check against the next run** after the suspicion starts (the user's rule: the run must confirm the HRV
   before anything is said). Confirmed when any of:
   - easy/long run: median HR at easy pace (the Progress fitness-trend measure, ±15 s/km of settings easy pace,
     km 1 dropped) ≥ 5 bpm above its median over the previous 4 weeks;
   - drift ≥ 10 % on a run that normally drifts less than 5 %;
   - quality session: review verdict `bad`.
   Thresholds are my calls; keep them as named constants.
3. **Not confirmed:** a quiet note ("HRV low 3 nights, but Tuesday's run looked normal"); monitoring continues
   and the next run is checked again while the suspicion lasts.
4. **Confirmed → advice** on This week: what was seen, in plain words ("HRV low 3 nights, and easy-pace heart rate
   up 6 bpm on Tuesday's run"), plus supporting signs if present. It offers the trim as a button: **the rest of
   that week at 0.9** (as a "tired" check-in) **and one rep off the next quality session** (`scale_session`).
   Taking it stores a fact (new table, e.g. `recovery_trims(date, created)`); the trim is then applied in
   `scale_and_shift_runs` from that date to the week's end, recomputed like everything else. Ignoring it does
   nothing. The trim never stacks below what the existing guards already do (take the smaller factor, as now).
5. **Monitoring:** after advice, the app keeps checking each night and each run.
   - **Improves** — HRV back in band two nights running and the next run normal: the advice clears.
   - **No improvement** after three more nights or two more runs: a **firmer** warning saying plainly it has
     persisted and recommending the trim; if resting HR or sleep are also off, it recommends an easy day or rest.
   - It stays the user's choice throughout.
6. Race week: advice is shown but the trim isn't offered (race week is untouched by every guard).

**Shown only, never used in decisions:** stress (derived from HR/HRV, so counting it would double-count) and
weight (changes too slowly to matter week to week).

## Part 4 — Pages

- **This week:** a small recovery panel — last night's HRV against the band, resting HR, sleep — with the advice
  card above it when there is one. The Garmin key warning replaces the Smashrun token warning.
- **Progress:** HRV (nightly + 7-day average with the band), resting HR and sleep trends next to the fitness trend.
  The weekly summaries' "Next week" rules may mention a recovery trigger (builder's call where it ranks).
- README updated for the user: how to create the key, what the recovery advice means.

## Recovery details (settled after review — all my calls, the user said "you would know best")

- **One trim per episode.** An episode runs from a suspicion starting to it clearing. The trim can be taken once;
  it never stacks with itself. If the warning turns firmer **after** the trim was taken, it offers one further
  button: **make the next run easy** — the next planned run becomes an easy run at 0.8 of its planned km (a quality
  session loses its reps; a long run loses its MP finish). It is stored as a second kind of fact in the same table
  (e.g. `recovery_trims(date, kind, created)` with kind `trim` or `easy`). "Rest" is text only: the user can
  already skip a session with Move. Nothing goes below what a 0.8 check-in would do.
- **Strength follows the trim** like a "tired" check-in: from the trim date to the week's end, strength is
  trimmed and `progression.suggest` holds loads (no increases). Same guards, same tests, one more trigger.
- **"One rep off":** the 0.9 is applied to the quality session through `scale_session`; if rounding didn't
  already remove a rep, one more is removed (never below 2, as `scale_session` already guarantees). If that
  week's quality session is already done, nothing carries into next week. The trim ends on Sunday, and next week
  has its own check-in and the recovery panel.
- **How a suspicion ends:** when HRV is back in band two nights running **and** the 7-day average is back in
  band, whether or not advice was given. A new episode can start straight after (it needs three low nights or a
  low 7-day average again, so no extra cooldown). Each episode shows **at most one** quiet note, updated in place
  with the latest run checked, so a long slide doesn't produce a note per run.
- **Which run confirms:** the first synced run on or after the day the suspicion started (any run on any date,
  including unplanned or moved ones, since actuals go by date) that can be judged:
  - easy or long: needs ≥ 3 km splits within the easy-pace band (km 1 dropped); compared with the median of
    the same measure over the previous 4 weeks. A run with fewer splits is **skipped**, and the next run is checked.
  - strides days are skipped (heart rate is raised on purpose, no drift).
  - quality: review verdict `bad` confirms; anything else is normal.
  - drift: confirms when ≥ 10 % and the median drift of easy/long runs over the previous 4 weeks is < 5 %.
- **Switch-over dedupe:** `activities` stores no start time, so match a stored Smashrun run to a Garmin run on the
  same date with distance within 3 % (or 0.2 km). If two runs on a date both match, pair them by distance order.

## Left to the builder

Module names, table names and exact columns, chart styling (follow the Progress page), wording of notes and
warnings (plain, like the rest of the app), test layout, and the order of work — though Part 1 should land and be
checked against the real account before Part 3 relies on its data.

## Changed during the build (14 Nov 2026)

What shipped differs from the text above in these places:

- **Stress:** the Personal API has no daily stress average; `stress_avg` is Garmin's average stress during sleep,
  shown as "sleep stress".
- **Resting HR** has no range endpoint: it is fetched per day, capped per sync (4 on a quick sync).
- **Laps count as reps** only when the FIT's workout has 2+ active steps — Garmin attaches a one-step workout
  to plain runs. Text that isn't valid UTF-8 (e.g. "£" in step names) is decoded leniently.
- **Switch-over:** a replaced Smashrun run's splits are carried over to the Garmin id until its FIT arrives,
  never deleted.
- **A NULL night** breaks "three in a row".
- **The trim** takes exactly one rep off the next quality session as the check-in left it; a session with no
  rep to spare is scaled to 0.9 instead. `recovery_trims` stores `date` (pressed, used for the episode) and
  `start` (today, or tomorrow if today's run is in), fixed at press time — syncing never moves or undoes it. A
  Sunday press after the run covers the next week.
- **Sync on open** also fires before 12:00 while last night's HRV is missing; a quick sync covers 27 days of
  wellness.
- **The HRV band** is labelled as the normal range for the 7-day average.
