# Long-run wording, cadence and steps — design

14 Nov 2026. Three small additions that use more of the Garmin data synced since the switch (PR #18).

## Why

- **Long-run wording.** Today's 12 km long run was summarised as "Easy at 6:13/km, heart rate steady." A long run
  with no marathon-pace finish gets the easy-run sentence and is never compared with the long-run pace it was
  planned at. The km splits also end with a 0.01 km "split" at 9:42/km, which is noise.
- **Cadence.** The user is coming back from a right-ankle injury, and long runs pass 90 minutes from early December.
  As a runner tires, cadence usually drops and the stride gets longer, which loads the ankle more. The run FIT files
  already hold cadence, step length and ground-contact time second by second; the app throws them away.
- **Steps.** The latest ankle swelling (Fri 13 Nov) came after a full day on feet at work plus an hour's walk, not
  from a run. Long days on feet are the user's normal, so a heavy day on its own is not news. The user's rule:
  **ignore it unless it's a repeat pattern.**

## What the data holds (checked 14 Nov against the user's account)

- Run FIT `record` messages: `cadence` (strides/min; ×2 for steps/min, plus `fractional_cadence`), `step_length`
  (mm), `stance_time` (ground contact, ms), `vertical_oscillation` (mm). `stance_time_balance` is invalid (655.35):
  no left/right balance without a chest strap, so the injured side can't be compared with the other.
- Activity search rows carry `steps`, `averageRunningCadenceInStepsPerMinute`, `avgStrideLength`,
  `avgGroundContactTime`.
- Daily steps: `GET /usersummary-service/stats/steps/daily/{start}/{end}` → `[{calendarDate, totalSteps,
  totalDistance, stepGoal}]`, one call for a range (14 days tried). Totals include the runs.
- The user's last two weeks: 8.6k–27k a day; work and weekend days 21–27k. Fri 13 Nov was 21.1k, not unusual.
  The walk wasn't recorded as an activity, so a walk and a shift look the same: only the daily total is usable.

## Goals

1. Long runs without an MP finish read as long runs and are judged against the planned long pace.
2. Splits shorter than 50 m are not shown or used.
3. Each easy and long run's review notes when form faded: cadence down, or step length up, late in the run.
4. Progress shows a cadence trend at a fixed easy pace, week by week, next to the ankle data.
5. Daily steps are stored; Progress shows them against ankle-trouble days, and says so only when heavy on-feet
   days are followed by ankle trouble repeatedly.

## Non-goals and anti-goals

- **Nothing here changes the plan.** Cadence and steps are information only. No trims, no buttons.
- **No message after a single heavy day** (the user's rule).
- **No claims of cause.** The steps note says what happened after what, never "steps caused this".
- No cadence targets ("aim for 180"). The trend is against the user's own past.
- No left/right comparison (no data).
- Not judging cadence on quality sessions or strides: pace changes cadence there on purpose.

## Design

### 1. Long-run wording and short splits (`review.py`)

- A `long` workout with no `mp_km` gets: `"Long run at {avg}/km (planned {long pace})"`, then `", {drift words}."`
  as today. Verdict as easy runs today: `warn` when quicker than MP + 20 s, `warn` on drift ≥ 10%, else `good`.
  When quicker than MP + 20 s the headline says so, as the easy one does ("… is quicker than long-run pace. Keep
  it steady.", builder's wording).
- `review.splits()` drops a split shorter than 0.05 km (50 m); it only ever occurs as the last split. Everything
  that reads splits (km table, drift, `fitness_trend`, the MP finish check) reads them through `review.splits()`,
  so they stay consistent; stored details are unchanged.
- The long run *with* an MP finish keeps its current headline.

### 2. Cadence and step length per km (`fitfile.py`, `review.py`)

- `fitfile.details()` also keeps, per record, cadence (steps/min = 2 × (`cadence` + `fractional_cadence`)),
  `step_length` and `stance_time`; each km split gains `cadence` (steps/min), `stepLength` (m) and `contact`
  (ms), time-weighted means over the split's records, `None` when the file has none. Same streaming approach,
  memory cost about the same (three more numbers per record kept only until the split closes).
- **Backfill:** existing `run_details` rows lack these. Garmin runs have their original FIT in `run_files`, so
  re-derive details from it when a run's splits have no `cadence` key. Full Sync only (the quick sync stays
  fast), at most 10 runs per sync, one file at a time (streaming, ~7 MB each, fine on the 256 MB VM). Re-derived
  splits always carry the key (`None` when the file has no cadence), so a run is never re-derived twice.
  Smashrun-only rows stay as they are.
- `review.splits()` carries `cadence`, `stride` and `contact` through.
- **Form note** on easy and long runs (not `steps` sessions, not strides), when the run has ≥ 8 full km with cadence:
  compare the early part (km 2 to the end of the first third) with the last third.
  - Cadence down by ≥ 4 steps/min → note "Cadence fell from {a} to {b} steps/min in the last {n} km."
  - Otherwise step length up by ≥ 5% with pace not quicker → "Your stride lengthened in the last {n} km ({a} →
    {b} m)."
  - Long runs with an MP finish: compare only the steady part before the finish (the finish is quicker on purpose).
  - The note goes in the review's `note` (shown under the headline), it doesn't change the verdict.
  - Thresholds are named constants. 4 steps/min ≈ 2.5% at the user's ~170–180, above second-to-second noise.
- The km splits table gains a cadence column.

### 3. Cadence trend (`progress.py`, Progress page)

- `cadence_trend(weeks, ref_pace)`: per week, median cadence of easy/long km splits within ±15 s/km of the
  settings easy pace, km 1 dropped, ≥ 3 splits a week. The same selection as `fitness_trend`, so pace doesn't
  confound it. Median step length alongside.
- Shown on Progress next to the ankle section as a small weekly chart, with one line of reading: cadence at easy
  pace steady, rising, or falling over the last 4 weeks (builder's wording; the last 4 weeks' median against the 4 before: "steady" within ±3 steps/min, else rising or
  falling). Only FIT-derived split cadence is used, never the activity-level average.

### 4. Steps and the ankle (`garmin_sync.py`, `db.py`, `progress.py`)

- Two new tables (new tables, not columns, because there are no migrations):
  - `steps(date TEXT PRIMARY KEY, total INTEGER)`: Garmin's daily total, which includes runs.
  - `run_steps(id INTEGER PRIMARY KEY, steps INTEGER)`: each Garmin run's `steps` from the activity search,
    written by `sync_runs` on every page it reads. The search already re-reads runs from `since`, so older runs
    fill in on the first full Sync.
- **On-feet steps = total − the day's runs' steps**, worked out in the view (pure), so a run added, replaced or
  removed later is always reflected. A day with a run but no `run_steps` value yet is left out (not judged).
  A long-run day isn't a heavy day just because of the run.
- Synced with wellness: the steps range endpoint, chunked like the others; in the quick sync with the same window.
  Read in `load_facts()` like everything else.
- **Heavy day:** on-feet steps at or above the 80th percentile of the previous 28 days' on-feet steps, counting
  only days that have a value, and only when at least 14 of them do. Relative to the user, since 20k+ days are
  normal for them.
- **Ankle trouble the next day:** on the literal next date, a morning check "worse than usual" or ankle pain ≥ 3
  on a strength-log ankle item dated that day: the same rows `ankle.py` flags on. (The weekly check-in isn't
  day-specific, so it doesn't count; the 7-day flag window doesn't count either.)
- **Pattern:** at least 2 heavy days in the last 28 days each followed by ankle trouble the next day, the two
  trouble days at least 3 days apart (so one bad spell counts once). Only then
  does Progress show a note in the ankle section, e.g. "Twice in the last 4 weeks your ankle was worse the day
  after a heavy day on your feet (Fri 13 Nov, …)." The weekly summary may use it as its "Next week" line
  after the ankle trigger rule (builder's call on wording).
- Progress also shows a plain daily on-feet steps chart over 8 weeks with ankle-trouble days marked, always,
  so the user can see the pattern forming without a message.

## Constraints

- Plan never stored; `build_view` stays pure; the new data comes in through `Facts`.
- Units: steps/min, metres, milliseconds; format at display time.
- Tests never reach Garmin. FIT tests build files with `tests/fitdata.py`.
- `samples/` stays untracked (personal data).
- README (written for the user) explains the form note, the cadence trend and the steps pattern in plain terms;
  CLAUDE.md gets the new table, fields and functions.

## Left to the builder

- Exact copy beyond the sentences above, chart styling (match the HRV/RHR charts on Progress).
- How the backfill is batched, within the existing per-sync limits.
- The steps range chunk size (14 days known to work).
