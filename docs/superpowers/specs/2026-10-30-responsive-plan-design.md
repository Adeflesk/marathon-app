# A plan that responds to what was done — design

Date: 2026-10-30. Roadmap item 2 (`docs/roadmap.md`). The user skipped the questions, so every call below
is Claude's, marked for checking.

## Why

The plan adjusts only from the weekly check-in, and only downwards. Two gaps:

1. **A missed week.** Ill or travelling, the user runs 40% of a week; the next week still steps up as if it
   had all been done. That's the classic way to get hurt coming back, and the ankle makes it worse.
2. **Paces don't follow fitness.** They come from one easy run on 16 Oct. A time trial (week 7) or a parkrun
   should update every pace, the watch files and the plan, without editing `settings.json`, and say honestly
   whether 3:59 looks realistic.

## Goals

### Missed-week guard

Each week's volume is capped by what was actually run in the weeks before it:

- **Ramp cap:** a week's km may not exceed **1.15 × the best of the last 4 completed plan weeks' actual km**.
  On the plan as written (every week done) this never bites; it only matters after missed training.
- **Low-week hold:** if the week just finished reached **under 60% of its target**, the next week is capped at
  **0.9 × that same best week**. So after one sick week you restart a little under your last good week and
  rejoin the plan over two or three weeks; after two weeks off, lower still.
- **Floor:** never below `base_weekly_km` (25), the plan's own restart level. A long break lands at the
  rebuild volume.
- It only ever lowers a week, never raises one. **Race week is never touched.**
- **Only weeks the app knows about count:** a week counts once it's over *and* a successful Smashrun sync
  happened on or after its Sunday (usually after the long run; a sync before it makes the week look short
  until the next sync corrects it). Nothing is capped until the week just before is known. Without that, an expired token would look like a week of no running and wreck the
  plan. (Claude's call: a new `meta` table holds `last_sync`, written by a successful sync.)
- Only plan weeks count (pre-plan runs don't), so week 1 has no cap.
- **Applied like the check-in trim:** the week's runs are scaled by `cap / planned km` (quality session by
  `scale_session`, others rounded to 0.5 km, the long run included). When both apply, the **smaller factor
  wins**; they don't multiply.
- **Strength isn't trimmed** by the guard (a missed run week isn't strength fatigue). The check-in still
  trims strength as before. (Claude's call.)
- The week says why, on This week and the Plan page: "Held at 33 km after last week's 10 of 40 km" or
  "Capped at 39 km, 15% above your best recent week (34 km), while you build back up."
- Computed per request like the rest of the plan: pure function, nothing stored. Past weeks show the cap they
  had at the time, since it only uses weeks finished before them.

### Paces from a result

- **Log a race or time trial** on This week: date, distance (5 km, 10 km or half marathon) and time. A new
  `results` table. The **latest result on or before today** sets the paces for the whole plan (Claude's call:
  past weeks' sessions and reviews follow the new paces too, as with a `settings.json` edit today).
  Results can be deleted (a mis-entry).
- **Paces** come from `pace_engine.paces_from_race` (Riegel with a 2% allowance): easy, long and threshold
  from the result, **interval** = the result's predicted 5 km pace.
- **Marathon pace (Claude's call):** stays at the **goal pace** (the settings' marathon pace) unless:
  - the goal is more than 5% off the prediction: then it's the **predicted pace**, so MP sessions train
    what's realistic; or
  - goal pace is within **10 s/km of today's threshold pace**: then it sits 10 s slower than threshold for
    now, or marathon-pace work would really be threshold work (found building it: a 25:30 5 km gives
    threshold 5:37 against a 5:41 goal pace).
  The page says which. Sub-threshold is MP − 9 s, never quicker than threshold, so the paces always stay in
  order (tested).
- **An honest read**, under "Your paces":
  - predicted ≤ goal: "On track: your 5 km predicts 3:52."
  - up to 5% slower: "Within reach: your 5 km predicts 4:06. A gap this size can close over the build."
  - more than 5% slower: "Ambitious: your 5 km predicts 4:19. Marathon-pace work uses 6:09/km until a faster
    result comes in."
- Without a result, nothing changes: `settings.json` paces as now.

## Non-goals

- Scheduling the time trial in the plan (the user runs a parkrun or a solo 5 km in week 7).
- Changing the goal time automatically. Only the training pace follows.
- Raising volume after a big week. Pre-plan runs. Race week.
- Detecting races from Smashrun.

## Anti-goals

- **Storing the plan.** Caps and paces are recomputed from facts (actual runs, sync time, results).
- **Punishing a sync gap.** No sync after a week's end means that week is unknown, not zero.
- **Biting the plan as written.** Following the plan exactly must never trigger the cap (tested on the default
  plan).

## How to check it

- Default plan, every week done as planned: no week is capped.
- Week 9 at 10 of 40 km: week 10 is capped at 0.9 × 37 (about 33 km), and says so; weeks 12–13 climb back.
- Week 9 at 10 km but no sync since: no cap.
- Weeks 8 and 9 at 0 km: week 10 lower again; four weeks off: 25 km.
- A 5 km in 25:30: easy 7:02, long 6:44, threshold 5:37, interval 5:06, marathon 5:47 for now ("within
  reach", goal pace too close to threshold). A 5 km in 26:30: marathon 6:09 ("ambitious"). 23:00: on track,
  marathon stays 5:41.
