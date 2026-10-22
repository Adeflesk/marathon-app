# Move or skip a session — design

Date: 2026-10-22

## Why

Life gets in the way. On Thursday 22 Oct the user's car broke down and the morning went on getting a puncture
fixed, so Strength A had to wait until Friday. Today the app has no way to say so: Thursday's session just
shows as not done, and on Friday the strength card isn't there to log it, because the card only shows the
session planned for that day.

The user wants to see in advance that a session won't fit, tap **Move to tomorrow**, and have the plan follow:
the card, logging, the Garmin file and the run review all on the new day. When tomorrow already holds
something that shouldn't be stacked, the app warns and advises dropping the missed session rather than
cramming two into one day.

**Success:** on a day like 22 Oct, one tap moves Strength A to Friday. On Friday it is the strength card on
This week, it logs against Friday, and Saturday morning asks the ankle check as usual.

## Goals

1. **Move to tomorrow.** Each run and each strength session dated today or later in the current week gets a
   **Move to tomorrow** button. One tap moves it one day later. Moving it again moves it one more day.
2. **Clash warning** (user's rule). Before moving, the app checks the day it would land on. It warns when:
   - the target day has a **long run** or a **speed session** (the week's quality run, i.e. a workout with
     `steps`), or
   - the session being moved is a **run** and the target day has **any run**.

   A strength session landing on an easy-run day or a rest day moves without a warning.

   The warning names both sessions and advises dropping the **missed** one, never the planned one (user's
   decision). For example: "Sunday already has your 10 km long run. Better to skip Saturday's easy run than
   stack them." It offers **Skip it** and **Move anyway**. Tomorrow's own session is never changed.
3. **Skip.** A skipped session is shown as "Skipped" on its original day. It doesn't count as missed: no
   compliance figure, no Garmin file, no review, and it's not the "next run" hero. A skipped strength session
   shows no card.
4. **Undo.** A moved session shows "Moved from Thursday" and a skipped one "Skipped", each with **Undo**, which
   restores the plan's original day.
5. **Everything follows the session to its new day:**
   - **Runs:** This week's hero and table, the run's Garmin `.fit` (file name and date) and the week zip, and
     the Smashrun join and run review (they match actual runs by the new date).
   - **Strength:** the strength card shows on the new day and logs against it. The morning check follows from
     the logs, so it comes the morning after the new day without further work.

## Non-goals

- Picking any day from a calendar. Next day only, one tap (Claude's call, accepted by the user).
- Moving ankle snacks, the weekly check-in or ankle tests.
- Moving a session that's already in the past (Claude's call: the button shows only for today and later).
- Reshaping the rest of the week around a move, e.g. shortening Saturday because Friday got busier.
- Moving race day. The race has no button.

## Anti-goals

- **Storing the plan.** The plan is still regenerated on every request. What's stored is the user's fact:
  "this session moved from day X to day Y" or "this session was skipped". Changing settings or the generator
  still reshapes the whole plan, and a stored move whose session no longer exists is ignored.
- **Silently stacking.** A run onto a run day, or anything onto a long-run or speed day, never happens without
  the warning.
- **Needing JavaScript.** Like every other form here: POST, then a 303 redirect back to the page.

## Constraints

- FastAPI + Jinja2 + SQLite, no migrations: a new table created with `CREATE TABLE IF NOT EXISTS` in
  `db.init()`.
- Phone-first at 390 px, light and dark, using the existing design tokens in `base.html` and `_ui.html`.
- Strength days are configurable (`strength_days`). Don't hardcode Tuesday or Thursday.
- Tests use a temp DB (`tests/conftest.py`). Each behaviour above gets a test that fails first.

## Decided

- **What's stored** (Claude's call): one row per session that was moved or skipped, keyed by the session's
  **original planned date** and its **identity** (`run`, or the strength key `A`/`B`), holding either the new
  date or "skipped". A second move updates the same row. Undo deletes the row.
- **Where moves apply:** in `main.build_view`, after `generate()` and before anything reads workout dates
  (check-in scaling, actual-run join, review, strength attach). Pure functions stay pure.
- **A run moved across Sunday into Monday** moves into the next week: its km count towards that week's target
  and actual (Claude's call). Its Garmin file goes in that week's zip.
- **The clash check uses the plan as it will look after other moves,** so two moves can't both land on one day
  unseen.
- **A moved strength session keeps its own week's prescription** (phase, sets, suggestions), since it's the
  same session done a day later.
- **The warning** is a page state after the POST (e.g. the redirect carries what to confirm), with the two
  buttons as forms. Nothing is stored until the user picks one.

## Left to the builder

- Table and column names, and the route names (e.g. `POST /move`, `POST /move/undo`).
- Exactly where the buttons and the "Moved from …" line sit on the hero cards and the week table, within the
  design system.
- How the "next run" hero and the strength-card selection on This week read moved and skipped sessions.
- Whether a moved session's `.fit` file name changes (it should carry the new date if it's built from
  `wo["date"]`).

## How to check it

- **Thursday Strength A moved to Friday:** no warning. On Friday it's the strength card. A log posts with
  Friday's date, and Saturday morning's check is due.
- **Saturday easy run moved:** warning naming Sunday's long run. **Skip it** shows Saturday as skipped, with no
  compliance figure and no `.fit`. **Move anyway** puts both runs on Sunday.
- **Tuesday Strength B moved onto Wednesday's speed session:** warning.
- **Undo** puts each back.
- **A Sunday run moved into Monday** counts in the next week's totals and zip.
- **A synced run on the new day** is reviewed against the moved workout.
