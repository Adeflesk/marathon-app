# Progress page — design

Date: 2026-10-30. Roadmap item 1 (`docs/roadmap.md`). Mockups: `.superpowers/brainstorm/14845-1793394611/content/`
(`verdict.html`, `page-v1.html`, untracked).

## Why

On a Sunday evening, after the long run, the user wants one answer: **am I on course for my goal in
Barcelona?** Today that takes a manual review of the database (as for weeks 1 and 2). The app already holds
everything needed: synced runs with km splits, reviews, strength logs, ankle tests and checks, snack ticks,
check-ins, and since roadmap item 2 a logged race or time-trial result with a predicted marathon time.

**Success:** the user opens Progress and in a few seconds knows whether they're on course and why. When
they're not, they can pick a goal that fits, and the whole plan follows. Past weeks can be looked back
through.

## Goals

A new **Progress** tab (nav: This week · Plan · Progress · Strength · Equipment), phone-first, in this order
(user agreed):

### 1. Verdict card

- **No result yet:** "Not enough to call yet. Run a 5 km in week 7 (30 Nov – 6 Dec) and this page gives you
  a prediction." The evidence below still shows.
- **With a result** (the latest on or before today, as item 2 uses): the predicted marathon time against the
  goal, using item 2's verdict bands:
  - predicted ≤ goal → "On course for 3:59" (green);
  - up to 5% slower → "Within reach of 3:59" (amber-green);
  - more than 5% slower → "3:59 is a stretch right now" (amber).
- A line with the week ("Week 9 of 21") and the result it rests on ("Your 5 km on 5 Dec predicts 4:12").
- Four **why rows**, each a tick or a warning with one line of numbers:
  - **Plan:** share of planned km done over the last 4 completed weeks, strength sessions done of those not
    skipped (any log on the day counts), and whether a week was held. Warning under 80%.
  - **Fitness:** heart rate at easy pace now against the first weeks (see 2). Warning if it has risen.
  - **Long runs:** the last three long runs' drift. Warning if two of them drifted (5% or more).
  - **Ankle:** flag up or not, hop stage, ankle pain on logged items over the last 4 weeks. Warning if the
    flag is up or any pain ≥ 3.
  The verdict comes from the result alone; the rows are evidence, not part of the calculation (Claude's call:
  keeps the verdict explainable).

### Goal suggestions and changing the goal (user: "if selected it should change the goal")

- Shown when the verdict isn't "on course". Two or three cards, each with a time, its marathon pace and one
  line:
  - **Realistic stretch:** the prediction improved by the training still to come, about 1% per 4 weeks left,
    at most 4% (Claude's call), rounded to the minute. "Needs the next 12 weeks done well."
  - **Today's prediction**, rounded up to the minute. "What today's fitness predicts."
  - **Keep the current goal:** no button; says marathon-pace work stays where item 2 put it.
  Cards whose time is within a minute of another, or of the current goal, are dropped.
- **"Train for 4:05" changes the goal.** Stored as a fact (new `goals` table: date, goal_time), never in
  `settings.json`. The latest goal overrides `settings.goal_time`; the goal pace becomes that goal's pace
  (sub-threshold MP − 9 s); then item 2's result logic runs on top, as now, so marathon pace can still sit
  10 s/km off threshold for a while. So MP work, Wednesday sessions,
  watch files, the dashboard's goal line and everything else follow.
- **Switching back** to the settings goal (a "Back to 3:59" card when the goal has been changed) deletes the
  overrides, so the settings' marathon pace (5:41) is restored exactly.
- The app never changes the goal on its own.
- The page notes goal changes ("Goal changed from 3:59 to 4:05 on 12 Jan") in the verdict card and in that
  week's summary, so trends don't look odd.

### 2. Fitness chart

- **Heart rate at the same easy pace, week by week. Lower is fitter.**
- Per week: the median heart rate of km splits within ±15 s/km of a **fixed reference pace**, the settings'
  easy pace (6:45; not result-adjusted, so a new result doesn't break the line). Splits from easy and long
  runs only (not quality days), first km of each run left out, and only full splits (≥ 0.9 km). A week needs
  at least 3 such splits, otherwise it's a gap. (Claude's calls.)
- From plan week 1 to now. Labels: first value and latest value ("wk 1: 152 · now: 146").

### 3. Long-run chart

- One bar per long run done: height its km, colour from its drift (green under 5%, amber 5–10%, red above).
  MP-finish runs marked. Missing details → grey.

### 4. Plan chart

- Per past and current week: planned km (outline, after check-in and guard trims) and done km (filled).
  Held or capped weeks marked. Under it: strength sessions done of planned, check-ins done of weeks.

### 5. Ankle table

- One row per core test (calf raises, eyes-closed balance, the worst of the three Y-balance reaches as % of the
  other side), one column per test week with results, injured side, and a target column: calf raises 25,
  eyes-closed balance 30 s, Y-balance 90%. Met targets ticked. (Gates from `ankle._hop_gate` and
  `balance_stage`.)
- A line: hop stage and since when, balance stage, last flag date, ankle pain range on logged items over the
  last 4 weeks.

### 6. Weekly summaries (user: wants to look back)

- One per **completed** plan week, newest first. The newest is open; older ones are one tap away
  (`<details>`), back to week 1. Recomputed from facts like everything else, never stored.
- Each: heading "Week 9 · 14–20 Dec · 39.5 of 40 km", then a few plain sentences:
  - runs done of planned; the long run's review headline; the quality session's review headline;
  - strength sessions done, ankle pain range;
  - snack days ticked, morning checks marked worse, check-in feel and pain;
  - a result logged that week, a goal change, a held week;
  - **"Next week:"** one focus, the first rule that applies (Claude's order):
    1. ankle flag up, or ankle pain rose → ankle first (stop items over 3, note the morning check);
    2. week under 60% of target → ease back in, the plan has held next week;
    3. easy runs quicker than easy pace by more than 10 s/km on average → keep easy runs at the easy pace;
    4. the long run drifted 5% or more → start it slower;
    5. fewer than 4 snack days → tick 4 snack days;
    6. a strength session missed → fit both in;
    7. next week is a test week → do the tests on a non-strength day, calf raise first;
    8. otherwise → "Keep doing what you're doing."
- **This week shows the newest summary** at the start of the week (user: yes). Claude's call: on Monday and
  Tuesday, as a card under the hero, with a link to Progress.

## Non-goals

- Changing the plan from the page other than the goal (volume, days, paces stay where they are).
- Weather or heat adjustment of heart rate. Resting heart rate, sleep, HRV (not in the data).
- Storing summaries or charts. A JavaScript chart library (inline SVG, as the volume profile already does).
- Predicting from training runs without a result.

## Anti-goals

- **A verdict without evidence, or a false alarm from thin data.** Gaps are shown as gaps; a week with too few
  splits is left out, not guessed.
- **Changing the goal behind the user's back.** Only their tap changes it.
- **Storing the plan.** Goals are user facts like results; everything else is recomputed.

## Constraints

- FastAPI + Jinja2 + SQLite, no JavaScript needed (forms POST and redirect with a 303, like the rest).
- Phone-first at 390 px, light and dark, existing design tokens in `base.html`/`_ui.html`.
- New tables via `CREATE TABLE IF NOT EXISTS`; no migrations.
- Pure functions for the maths (a new `app/progress.py`), tested; `main.py` gathers facts.
- Tests use a temp DB; each behaviour above gets a test that fails first.

## Left to the builder

- Route names (e.g. `GET /progress`, `POST /goal`), the exact chart drawing, copy within the tone of the app.
- How `build_view` exposes what the page needs (it already computes reviews, guard, strength, ankle state).
- Whether the summary sentences are one function per part.

## How to check it

- Today's real data (weeks 1–2, no result): "Not enough to call yet"; fitness chart has weeks 1–2; long-run
  chart two green bars; ankle table week 1 column; week 1 summary with "Next week:" about easy pace or snacks.
- A 5 km in 26:30 logged: "3:59 is a stretch"; suggestions about 4:09 (stretch) and 4:20 (prediction);
  tapping "Train for 4:09" changes the goal pace to 5:54 and the dashboard goal to 4:09 (marathon pace shows
  6:00 for now: 5:54 is within 10 s of that result's 5:50 threshold); "Back to 3:59" restores 5:41.
- A week under 60%: its summary says so and next week's focus is "ease back in".
