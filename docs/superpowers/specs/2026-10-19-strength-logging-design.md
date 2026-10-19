# Strength routine rework and logging card — design

Date: 2026-10-19
Evidence: `reports/Runner strength routine review.md`. Read it: this design adopts its redesign, ankle progression
and logging rules, and refers to its tables rather than copying them.

## Why

The user wants to be sure their twice-weekly strength work is right for a sub-4 marathon build after an ankle
sprain. They also want to log each session on their phone: tick each exercise off, record the weight, and have
the app suggest next time's weight from how it felt.

The research found five gaps:
- **Thursday is never heavy from week 7 on.** This is a bug. `strength.sessions_for_week` lightens Strength A
  whenever a "hard" session is on an adjacent day, and from week 8 every Wednesday is one.
- **The main leg exercise rotates weekly,** so load can't progress.
- **No plyometrics.**
- **Tuesday is an upper-body day,** with no support for marathon performance.
- **Ankle balance work is far too little:** about 2 min a week, against 60–90 in the trials.

## Goals

1. **Rework both sessions as the report's "The redesigned week, phase by phase" describes:**
   - **Thursday "Strength A: heavy legs and hops":**
     - Hops, barbell box squat and barbell RDL, all fixed for the whole build.
     - A single-leg lift fixed per block: step-up in weeks 1–6, reverse lunge in weeks 7–10, Bulgarian
       split squat from week 11.
     - Loaded straight-knee calf raise, seated barbell soleus raise, and an optional hip thrust.
   - **Tuesday "Strength B: light full body and ankle":**
     - A balance block, then a dumbbell single-leg RDL.
     - Ring row + push-up (ring push-up from week 7), suitcase carry + Pallof press, and bent-knee calf
       raise + eccentric band eversion.
   - **Sets, reps and effort by phase:** the report's phase table (Rebuild, Build, Cutback, Peak, Taper 1,
     Taper 2, race week).
   - **Block switches** happen at cutback weeks, counted by position in the plan like the run blocks, not by
     absolute week number. Nothing new is introduced after the second cutback.
2. **Replace "lighter next to a hard run"** with the report's narrower rule. Thursday runs at full dose unless
   one of these triggers fires:
   - **Hard Wednesday:** that week's Wednesday run review verdict is `bad`, meaning most reps were missed
     (user's decision). Thursday loses 1 set on the main lifts and is capped at RPE 7.
   - **Check-in trim:** applies to both days, per the report's override table.
     - Factor 0.9: −1 set on the main lifts, same load.
     - Factor 0.8: −1 set and −1 load step, RPE capped at 6, no increases that week.
   - **Ankle flag:** see goal 8.

   Trims stack with cutback, Peak and taper sets, but a session never goes below 1 set *(my call)*.
3. **Strength-day hero card, checklist style** (the user chose layout A from the mockups). On a strength day
   it leads This week:
   - session name, minutes, and progress ("2 of 7 done");
   - each exercise as a row; tapping a row opens it to show:
     - the target sets × reps and effort;
     - last time's weight and rating;
     - the suggested weight with − / + steppers;
     - reps per set, pre-filled with the target and editable;
     - **Easy / Right / Hard** buttons;
     - on calf, hop, balance and single-leg items, an ankle pain value (0–10);
     - a tick.
   - A ticked row collapses to one line, e.g. "Box squat 60 kg, 3 × 8, right".
   - The next-time suggestion appears as soon as a rating is chosen.
4. **Progression rules** exactly as the report's "Progression rules for the app's logging card":
   - the rating meanings and the rating-to-next-session table;
   - load steps per equipment (computed from `equipment.json`, e.g. `barbell_loads()`);
   - the top-weight ladder (extend reps, then slower lowering, then pause, then a harder variation, then
     moving to the barbell);
   - the phase and check-in overrides;
   - return after time off;
   - starting loads via warm-up sets on an exercise's first session.

   This is the user's own rule: easy means go up, hard means go down, and if the weight can't go up, add reps.
5. **Ankle snacks:** an 8–10 minute balance card on the other days (user's decision: "yes please"), with its
   own ticks. It follows the report's balance progression (eyes open → eyes closed → ball catches → band
   perturbations → Y-balance reaches → SL RDL with reach → hop-and-stick).
   - **Days** *(my call)*: Mon, Wed, Fri and Sat, configurable as `ankle_days` in settings.
   - **Placement:** on run days it sits under the run hero.
   - **Race week:** a low-dose version only.
6. **Ankle readiness tests and hop stages** *(timing and starting point are my calls)*:
   - **Baseline test week 1:** the first test card appears in plan week 1 and includes a 20-pogo trial.
     Before a pain-free pogo trial with a "fine" next morning, the hop stage is "not yet" and Thursday has no
     hops.
   - **Re-tests:** at 4, 7, 11 and 15 weeks into the plan (the start of the second build block and each
     cutback, counted by position like the run blocks), then no more new tests.
   - **Balance stage:** advances after at least 2 weeks in a stage with at least 4 snack sessions ticked and no
     ankle flag. Eyes-closed → ball catches also needs a ≥30 s eyes-closed test on the injured side. The
     hop-and-stick stage waits until hop stage 2.
   - **Out of scope:** Wednesday warm-up pogos *(my call)*.
   - **Tests:** every 3–4 weeks the app prompts a short test card: calf raises to fatigue (each side), eyes-closed
     balance (seconds, each side), Y-balance reach (cm, three directions, each side), and later the single and
     triple hop for distance.
   - **Hop stage (0–3):** derived from the test results, at least 2 weeks in each stage, and ankle flags, using
     the gates in the report's "Hop stages" table. The stage sets Thursday's hop exercises and contact count.
   - **Step-back signals** (report's list) drop one stage: a logged ankle pain ≥3 or higher than last time, a
     next-morning reaction note, or a falling calf-raise count.
8. **Ankle flag** *(one-tap check, user's decision)*:
   - **Morning check:** on the morning after a session with hops or calf work, This week shows "Ankle this
     morning: fine / worse than usual". "Worse" is stored in a new table (see Data).
   - **What raises the flag:** "worse", a logged `ankle_pain` of 3 or more (or higher than the previous log of
     the same item), or a weekly check-in pain of 3 or more.
   - **Duration:** 7 days from the latest trigger.
   - **While it's raised:**
     - no load increase on ankle, calf or hop items;
     - Thursday −1 set and RPE ≤7;
     - a "worse" morning drops the hop stage by one and holds the balance stage.
7. **History:** the Strength page shows each exercise's log history (date, weight, reps, rating), so the user
   can see progress.

## Non-goals

- The AI weekly coach.
- Changing the run plan.
- Video demos.
- Per-set rest timers *(my call; could come later)*.
- Exporting strength sessions to the watch.

## Anti-goals

- **Storing the plan.** Sessions, prescriptions, suggestions and hop stage are recomputed from settings,
  equipment and logs on every request. Only user facts are stored: logs, test results and ticks.
- **Suggestions that ever increase load** in a cutback, taper, check-in-trimmed or ankle-flagged context.
  The plan only adjusts down.
- **Exercises the user's equipment can't do.** Every slot keeps an equipment-gated fallback, as `strength.py`
  does today, e.g. no rings → single-arm DB row.
- **A card that needs typing mid-session.** The defaults are pre-filled, and one tap rates.

## Constraints and conventions

- **Code:** FastAPI + Jinja + SQLite, with the `CREATE IF NOT EXISTS` schema in `db.init()` and no migrations.
  Units are kg, seconds, km.
- **Look:** the existing design system (pace-band redesign): Archivo, sea-mist/navy/senyera tokens, light and
  dark modes, and a phone-first width of 390 px.
- **Phone use:** forms must work without JavaScript, posting and redirecting like the check-in. Progressive
  enhancement (instant expand and collapse, optimistic ticks) is fine.
- **Tests:** pytest, written test-first.
- **Wording:** effort is shown as plain words plus RPE: "about 3 reps left (RPE 7)".

**Time off** *(my call)*: measured from the last strength log of any exercise.
- **Up to 10 days:** resume at the last load.
- **2–4 weeks:** one session at about 90% (1–2 steps down).
- **More than 4 weeks, or the flag raised by a "worse" morning:** the next 2 sessions use the Rebuild
  prescription at about 80%, and the hop stage returns to "not yet" until a fresh pogo trial and test card.

## Data *(my call; builder may refine)*

- **`strength_logs`:** `id`, `date`, `exercise` (stable key, e.g. `box_squat`), `weight_kg` (nullable), `level`
  (text, for band/ring/stage items), `reps` (JSON list per set), `rating` (`easy`/`right`/`hard`), `ankle_pain`
  (nullable int), `created`. One row per exercise per day; saving again replaces it.
- **`ankle_tests`:** `id`, `date`, `test`, `injured_side` (float), `other_side` (float).
- **`snack_logs`:** `date`, `item`, `done`.
- **`ankle_checks`:** `date` (primary key), `worse` (0/1), plus an optional note.
- **Injured side:** `settings.json` gains `injured_side` ("left" or "right"; default "right" *(my call)*).

## Decided with the user

- **Hard Wednesday:** the Wednesday run review's `bad` verdict lightens Thursday. No per-run rating is added.
- **Taper week 2:** no leg session (current behaviour). Tuesday's light session and the ankle snacks continue.
- **Ankle flag:** a one-tap next-morning check (goal 8).
- **Layout:** the checklist card (layout A), with daily ankle snacks on their own card.

## How to check it

- **Plan output:** Thursday in weeks 8–14 prescribes 3 × 6–8 at RPE 7–8 with no check-in trim, and 2 sets with
  RPE 7 after a 0.9 check-in.
- **Exercises:** the main exercises don't change week to week within a block.
- **Logging rules:** pinned by tests that walk through the report's rating table, the top-weight ladder, and
  every override.
- **Hop stage:** follows the gates given a sequence of logged tests and flags.
- **Screenshots** at 390 px, light and dark: a Thursday card part-way through, a Tuesday card, an ankle snack
  card, and a test card.
- **Production:** after deploy, the user logs a real Tuesday session.

## Left to the builder

- Module boundaries, e.g. `strength.py` for routines and a new `progression.py` for the rules.
- Exercise keys and cue text.
- The exact HTML of the card within the design system.
- How the test prompt is surfaced, e.g. a card on the Saturday of a cutback week.
