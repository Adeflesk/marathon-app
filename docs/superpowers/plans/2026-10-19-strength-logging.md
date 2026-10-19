# Strength Routine Rework and Logging Card Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rework the Tuesday and Thursday strength sessions to the research, and log them on a checklist card:
weight, reps, Easy/Right/Hard, and next-time suggestions. Add daily ankle snacks, ankle tests, hop stages and a
morning ankle check.

**Architecture:** Three pure modules, recomputed per request like the plan.
- `app/strength.py`: routines and prescriptions.
- `app/progression.py`: weight and rep suggestions from logs.
- `app/ankle.py`: ankle flag, hop and balance stages, and when tests are due.

`app/db.py` stores only user facts: logs, ticks, tests and checks. `main.build_view` gathers the context, and
Jinja templates render the cards as no-JS forms that post and redirect.

**Tech Stack:** Python 3.11, FastAPI, Jinja2, SQLite, pytest.

**Spec:** `docs/superpowers/specs/2026-10-19-strength-logging-design.md`. The spec cites
`reports/Runner strength routine review.md` for its tables: "The redesigned week, phase by phase", "The
ankle progression and its readiness tests" and "Progression rules for the app's logging card". Executors read
all three. This plan pins the values those tables leave open.

## Global Constraints

- The plan, sessions, suggestions and stages are never stored. Only user facts are stored.
- Suggestions never increase load in a cutback, Peak (main leg lifts), taper, check-in-trimmed or ankle-flag
  context, or for an ankle item while the flag is up.
- Every exercise slot has an equipment-gated fallback (`strength.tokens(eq)`).
- Forms work without JavaScript (POST, then a 303 redirect).
- Use the existing design tokens and layout from `base.html` and `_ui.html`, phone-first at 390 px, in light
  and dark modes.
- Units are kg, seconds, metres for carries, and foot contacts for hops.
- Effort copy is plain words plus RPE, e.g. "about 3 reps left (RPE 7)".
- A session never goes below 1 set.
- `settings.json` gets new keys `ankle_days` (default `["mon", "wed", "fri", "sat"]`) and `injured_side`
  (default `"right"`). `ankle_days` replaces wholesale, so it goes in `REPLACE_KEYS`.

## Review Focus

1. **The very first session** (no history): the card shows the warm-up ladder and asks for a working weight,
   not a crash or a 0 kg suggestion. Task 4 test: `test_first_session_warmup_ladder`.
2. **Saving the same exercise twice in a day** replaces the earlier log, and the suggestion uses the latest
   one. Task 1 test: `test_log_replaces_same_day`.
3. **Equipment edited after logging** (e.g. 35 kg dumbbells removed): the suggestion snaps to the nearest
   available weight at or below it. Task 4 test: `test_suggestion_snaps_to_available`.
4. **A strength day that is also a run day** (custom `strength_days`): the run stays the hero and the strength
   card renders below it. Task 7 test: `test_strength_card_below_run_hero`.
5. **Ankle pain logged on a non-ankle item** is ignored for the flag. Ankle pain of 3 on an ankle item raises
   it for 7 days, and it clears on day 8. Task 5 test: `test_flag_expiry_and_scope`.

---

### Task 1: Storage for logs, ticks, tests and checks

**Files:**
- Modify: `app/db.py`
- Test: `tests/test_db_strength.py`

**Interfaces:**
- **Produces:**
  - Tables, created with `CREATE TABLE IF NOT EXISTS` in `init()`:
    - `strength_logs`: `date` TEXT, `exercise` TEXT, `weight_kg` REAL NULL, `level` TEXT NULL, `rung` INT
      DEFAULT 0, `reps` TEXT (JSON list), `target_reps` INT, `rating` TEXT, `ankle_pain` INT NULL,
      `created` TEXT. PRIMARY KEY (`date`, `exercise`).
    - `snack_logs`: `date`, `item`, PRIMARY KEY (`date`, `item`).
    - `ankle_tests`: `date`, `test`, `injured` REAL, `other` REAL NULL, PRIMARY KEY (`date`, `test`).
    - `ankle_checks`: `date` PRIMARY KEY, `worse` INT, `note` TEXT DEFAULT ''.
  - Functions:
    - `save_log(row: dict) -> None` (INSERT OR REPLACE) and `logs(exercise: str | None = None) -> list[dict]`,
      newest first, with `reps` decoded.
    - `toggle_snack(day: str, item: str) -> None` and `snacks() -> list[dict]`.
    - `save_test(day: str, test: str, injured: float, other: float | None) -> None` and
      `tests() -> list[dict]`, oldest first.
    - `save_check(day: str, worse: bool, note: str = "") -> None` and `checks() -> list[dict]`, oldest first.

- [x] **Step 1: Write failing tests:**
  - `test_log_roundtrip`: `reps == [8, 8, 7]` after decoding.
  - `test_log_replaces_same_day`: two saves for `("2026-10-22", "box_squat")` leave one row, holding the
    second weight.
  - `test_snack_toggle`: toggling twice removes the row.
  - `test_tests_and_checks_ordered`.
- [x] **Step 2:** Run `pytest tests/test_db_strength.py -q`. Expected: FAIL (`no such table`).
- [x] **Step 3:** Implement in `app/db.py`.
- [x] **Step 4:** Run `pytest -q`. Expected: all pass.
- [x] **Step 5:** Commit: `git commit -am "Strength log, snack, ankle test and check tables"` (add the new
  test file).

### Task 2: Plan and settings fields the routines need

**Files:**
- Modify: `app/plan.py` (week dict in `generate`), `app/config.py`
- Test: `tests/test_generate.py`

**Interfaces:**
- **Produces:**
  - Each week dict gains `strength_block: int`, the number of Cutback weeks before or at this week:
    - weeks 1–6 → 0;
    - weeks 7–10 → 1;
    - week 11 onwards → 2, and 3 from week 15.
  - `DEFAULTS["ankle_days"] = ["mon", "wed", "fri", "sat"]` and `DEFAULTS["injured_side"] = "right"`.
  - `"ankle_days"` is added to `REPLACE_KEYS`.

- [x] **Step 1: Write failing tests:**
  - `test_strength_block_counts_cutbacks`: weeks 1, 6, 7, 10, 11 and 15 map to 0, 0, 1, 1, 2 and 3.
  - `test_ankle_defaults`.
- [x] **Step 2:** Run them. Expected: FAIL (`KeyError`).
- [x] **Step 3:** Implement.
- [x] **Step 4:** Run `pytest -q`. Expected: all pass.
- [x] **Step 5:** Commit: "Plan exposes strength block; ankle settings".

### Task 3: Routines and prescriptions (`app/strength.py`)

**Files:**
- Modify: `app/strength.py`. Replace `A_SLOTS`, `B_SLOTS`, `_pick`, `_rx` and `_session`, and change
  `sessions_for_week`. Keep `load_equipment`, `save_equipment`, `tokens`, `barbell_loads` and `summary`.
- Test: `tests/test_strength_routine.py`. Rewrite `tests/test_view.py::test_strength_a_reduced_only_next_to_hard`
  as `test_thursday_full_dose_after_normal_wednesday`.

**Interfaces:**
- **Consumes:** `week["strength_block"]` (Task 2) and the run review verdict on that week's quality workout
  (`wo["review"]["verdict"]`, already in `build_view`).
- **Produces:**
  - `EXERCISES: dict[str, dict]`, keyed by a stable key. Each entry has `name`, `cue`, `load` (one of
    `barbell_lower`, `barbell_upper`, `dumbbell`, `dumbbell_lower`, `kettlebell`, `bodyweight`, `band`,
    `rings`, `timed`, `hops`, `carry`), `needs: set[str]`, `ankle: bool`, `per_side: bool` and
    `fallback: str | None`. `ankle` is True for calf, soleus, eversion, balance, hops and single-leg items.
  - `ROLE_RX[phase][role] -> {"sets": int, "lo": int, "hi": int, "rpe": str}`, holding the report's phase
    table values. Roles: `main`, `single_leg`, `hip_thrust`, `calf`, `soleus`, `tue_lift`, `tue_upper`,
    `carry`, `core`, `band`, `balance`.
    - Carries use `lo` and `hi` as metres, and core/balance use them as seconds.
    - Pinned values:
      - **Rebuild:** main 2×8–10 "6–7".
      - **Build:** main 3×6–8 "7–8".
      - **Cutback:** main 2 sets at the previous week's reps, "6–7".
      - **Peak:** main 2×4–6 "7".
      - **Taper 1:** main 2×4–5 "≤7".
      - **Calves:** Build 3×8–12, Rebuild 2–3×12–15 (use 3), Peak 2×8–10.
      - **Tuesday lifts:** 2×8–10 "6–7".
  - `sessions_for_week(week: dict, eq: dict, ctx: dict) -> list[dict]`.
    - `ctx` keys:
      - `factor: float`;
      - `wed_bad: bool`;
      - `ankle_flag: bool`;
      - `hop_stage: int | None` (None means "not yet");
      - `balance_stage: int`;
      - `restart: bool`;
      - `days: dict` (`strength_days`).
    - Each session dict: `key` ("A" or "B"), `name`, `date`, `day`, `minutes`, `reduced: bool`, `note`,
      `warmup`, and `exercises`.
    - Each exercise dict: `key`, `name`, `cue`, `role`, `sets`, `lo`, `hi`, `rpe`, `load`, `ankle`,
      `per_side`, and `rx` (the display string, e.g. "3 × 6–8, about 2–3 reps left (RPE 7–8)").
- **Session rules:**
  - **Thursday A** (report order):
    1. `hops` (only when `hop_stage` is not None);
    2. `box_squat`;
    3. `rdl`;
    4. the single-leg lift by `strength_block`: 0 → `step_up`, 1 → `reverse_lunge`, ≥2 → `bulgarian_split_squat`;
    5. `calf_raise_straight`;
    6. `seated_soleus_raise`;
    7. `hip_thrust`.
  - **Tuesday B:**
    1. `balance_block`;
    2. `sl_rdl_db`;
    3. `ring_row` + push-up (`push_up` when `strength_block` = 0, `ring_push_up` otherwise);
    4. `suitcase_carry` + core (`pallof_press`, `dead_bug` or `side_plank`, chosen by `strength_block % 3`);
    5. `calf_raise_bent` + `band_eversion`.
  - **Trims:** apply the report's overrides as plain rules. `factor` 0.9 or 0.8 → −1 set on the main lifts on
    both days (0.8 also sets `rpe` "≤6"). `wed_bad` or `ankle_flag` → Thursday main lifts −1 set, `rpe` "≤7".
    `reduced` is True when any trim applies. Floor of 1 set.
  - **Taper 2:** no Thursday. **Race week:** no sessions. **`restart`:** use `ROLE_RX["Rebuild"]`.

- [x] **Step 1: Write failing tests:**
  - `test_thursday_build_full_dose`: week 9 Thursday `box_squat` is `sets == 3`, `lo, hi == 6, 8`, and
    `reduced` is False with the default ctx.
  - `test_thursday_trimmed_by_triggers`, parametrized over `wed_bad`, `ankle_flag` and factor 0.9: `sets == 2`
    and `reduced`. A factor-0.8 case also has `rpe == "≤6"`.
  - `test_single_leg_fixed_per_block`: weeks 4–6 give `step_up`, weeks 8–10 `reverse_lunge`, weeks 12–18
    `bulgarian_split_squat`.
  - `test_tuesday_composition`: the week 2 keys are exactly the list above, with `push_up`. Week 8 has
    `ring_push_up`.
  - `test_no_hops_until_stage`: no `hops` key when `hop_stage` is None, and it's present when 0.
  - `test_fallbacks_without_rings_or_rack`: an equipment dict without rings or rack gives `db_row` instead
    of `ring_row`, and `goblet_squat` (dumbbell) instead of `box_squat`.
  - `test_taper2_and_race_week`.
  - `test_floor_one_set`: Cutback with factor 0.8 gives main `sets == 1`.
- [x] **Step 2:** Run `pytest tests/test_strength_routine.py -q`. Expected: FAIL.
- [x] **Step 3:** Implement. Cues come from the report's notes column (e.g. the safeties for the box squat).
- [x] **Step 4:** Update the `main.build_view` call to the new signature, passing a default ctx. Task 6
  replaces it with real values: `wed_bad` comes from that week's quality workout review verdict == "bad".
  Then run `pytest -q`. Expected: all pass.
- [x] **Step 5:** Commit: "Strength sessions reworked to the research".

### Task 4: Suggestions (`app/progression.py`)

**Files:**
- Create: `app/progression.py`
- Test: `tests/test_progression.py`

**Interfaces:**
- **Consumes:** an exercise dict from Task 3, `db.logs(exercise)` rows from Task 1, and `strength.barbell_loads(eq)`.
- **Produces:**
  - `available_weights(ex: dict, eq: dict) -> list[float]`, ascending:
    - barbell: `barbell_loads(eq)`;
    - dumbbell: `db_min_kg` to `db_max_kg` by `db_step_kg`;
    - kettlebell: `kettlebells_kg`;
    - otherwise `[]`.
  - `step(weight: float, ex: dict, eq: dict, n: int, phase: str) -> float` moves `n` steps up (or down when
    negative) within `available_weights`, clamped at the ends:
    - `barbell_lower`: +5 kg below 60 kg, +2.5 kg at or above 60 kg and in Peak;
    - `barbell_upper`: +2.5 kg;
    - `dumbbell`: +1.25 kg;
    - `dumbbell_lower`: +1.25 kg, or +2.5 kg when `n` ≥ 2;
    - `kettlebell`: the next bell.
  - `suggest(ex: dict, history: list[dict], ctx: dict, eq: dict, today: date) -> dict` returns:
    - `weight: float | None`;
    - `reps: int`, the target per set;
    - `rung: int`;
    - `level: str | None`, e.g. "3–4 s lowering";
    - `warmup: list[float]`, non-empty only with no history;
    - `reason: str`, e.g. "Easy last time at 50 kg, so 55 kg".

    `ctx` adds `phase`, `cutback: bool`, `factor`, `ankle_flag` and `last_any_log: date | None`.

    Rules, in order:
    1. **No history:** `warmup` is the first 3–4 available weights at or below a light start: empty bar 20 kg,
       dumbbells 5 kg, a kettlebell of 12. `weight` is None and `reps` is `lo`.
    2. **Time off since the last log of any exercise** (`ctx["last_any_log"]`): 11–28 days → −1 step once;
       over 28 days → the nearest weight ≤ 0.8 × last.
    3. **The report's rating-to-next-session table, row by row.** "All sets reached the top" means
       `min(reps) >= hi`, and "target completed" means `min(reps) >= target_reps`.
    4. **Overrides** (they cap rule 3's result, never raise it):
       - cutback, taper, factor < 1 and Peak main lifts → load ≤ last;
       - factor 0.8 → −1 step;
       - `ankle_flag` with `ex["ankle"]` → load ≤ last and rung ≤ last.
    5. **Top weight:** when a +step is impossible (already at the top of `available_weights`, or
       bodyweight/band/rings), advance `rung` instead, following the report's ladder:
       - extend `hi` by up to 4 (cap 12 for `main`, 20 otherwise);
       - "3–4 s lowering" with reps back to `lo`;
       - "2–3 s pause";
       - the harder variation via `EXERCISES[key].get("harder")`.

       Kettlebell 12 → 16 kg happens only after an easy rating at `hi` ≥ 15, then resets reps to 8.

- [x] **Step 1: Write failing tests**, one per row of the report's rating table, with pinned numbers:
  - `test_easy_all_top_steps_up`: RDL at 50 kg, reps [8, 8, 8], range 6–8, easy → 55.
  - `test_easy_twice_two_steps`: → 60.
  - `test_easy_not_top_adds_reps`: [6, 6, 6] → same weight, reps 8.
  - `test_right_all_top`: → +1 step, reps 6.
  - `test_right_not_top`: → reps +1.
  - `test_hard_completed_repeats`.
  - `test_hard_missed_steps_down`.
  - `test_second_hard_steps_down`.
  - `test_kettlebell_top_extends_reps`: 16 kg, easy at 12 → reps 14, rung 1.
  - `test_db_35_at_top_goes_to_tempo`.
  - `test_kettlebell_12_to_16_gate`.
  - `test_cutback_never_increases`.
  - `test_factor_08_steps_down`.
  - `test_peak_main_holds`.
  - `test_ankle_flag_holds_ankle_items_only`.
  - `test_first_session_warmup_ladder`: barbell gives [20, 30, 40]; with no dumbbells, nothing.
  - `test_time_off_11_to_28_days`.
  - `test_time_off_over_28_days`.
  - `test_suggestion_snaps_to_available`.
- [x] **Step 2:** Run `pytest tests/test_progression.py -q`. Expected: FAIL (`ModuleNotFoundError`).
- [x] **Step 3:** Implement `app/progression.py`.
- [x] **Step 4:** Run `pytest -q`. Expected: all pass.
- [x] **Step 5:** Commit: "Weight and rep suggestions from logs".

### Task 5: Ankle flag, stages and tests (`app/ankle.py`)

**Files:**
- Create: `app/ankle.py`
- Test: `tests/test_ankle.py`

**Interfaces:**
- **Consumes:** Task 1 rows, `db` check-ins (pain, week), and the week dicts.
- **Produces:**
  - `flag_until(today: date, checks, logs, checkins, weeks) -> date | None`. These raise the flag for 7 days
    from their date:
    - a check with `worse`;
    - a log of an `EXERCISES[ex]["ankle"]` item with `ankle_pain` ≥ 3, or higher than that item's previous log;
    - a check-in with pain ≥ 3, dated to the last day of its week.

    It returns the latest expiry if that is ≥ today, else None.
  - `morning_check_due(today, logs, checks) -> bool`: yesterday has a log of a `hops`, `calf_raise_straight`,
    `seated_soleus_raise` or `calf_raise_bent` item, and there is no check dated today.
  - `test_weeks(weeks) -> set[int]`: week 1, the first Build week and every Cutback week. With the defaults:
    {1, 4, 7, 11, 15}.
  - `tests_due(week: dict, weeks, tests) -> bool`.
  - `TESTS`: the keys `pogo_trial` (injured = pain 0–10), `calf_raises`, `eyes_closed_balance`,
    `y_balance_ant`, `y_balance_pm`, `y_balance_pl`, `single_hop` and `triple_hop` (injured/other values).
  - `hop_stage(today, tests, checks) -> int | None`. It replays day by day from the first passing
    `pogo_trial` (pain ≤ 2, and no `worse` check the next day):
    - starts at 0;
    - goes +1 when it has spent ≥14 days in the stage, no flag is up, and the latest tests meet the gate:
      - stage 1 → 2: `calf_raises` injured ≥ 25 and ≥ 0.9 × other; every Y-balance injured ≥ 0.8 × other;
      - stage 2 → 3: Y-balance ≥ 0.9 × other, and single and triple hop ≥ 0.85 × other;
    - goes −1 (min 0) on a `worse` check;
    - with no passing trial, or with no logs or tests for more than 28 days and no new trial since, returns None.
  - `HOP_STAGES[stage]`: exercise lines and contacts from the report's "Hop stages" table.
  - `balance_stage(today, snacks, tests, checks, hop) -> int`, from 0 to 6, replayed like the hop stage:
    - +1 after ≥14 days in the stage with ≥4 snack days ticked and no flag;
    - 1 → 2 also needs `eyes_closed_balance` injured ≥ 30;
    - 5 → 6 needs `hop` ≥ 2.
  - `BALANCE_STAGES[stage]`: the snack items for each stage, using the report's progression order. Each item
    has `item` (key), `name`, `dose` and `cue`, about 8–10 min in total.
  - `restart(today, logs, checks) -> bool`: True if the gap since the last log is over 28 days, or there was
    a `worse` check in the last 7 days, and fewer than 2 strength log dates have passed since that point.

- [x] **Step 1: Write failing tests:**
  - `test_flag_expiry_and_scope`.
  - `test_flag_from_checkin`.
  - `test_morning_check_due_after_thursday`.
  - `test_test_weeks_default`: {1, 4, 7, 11, 15}.
  - `test_hop_stage_not_yet_without_trial`.
  - `test_hop_stage_progression`: a trial on day 0 and good tests give stage 1 at day 14, and stage 2 at day 28
    with gates met.
  - `test_hop_stage_held_by_failed_gate`.
  - `test_worse_drops_stage`.
  - `test_balance_stage_needs_snacks_and_eyes_closed`.
  - `test_restart_after_gap`.
- [x] **Step 2:** Run `pytest tests/test_ankle.py -q`. Expected: FAIL.
- [x] **Step 3:** Implement `app/ankle.py`.
- [x] **Step 4:** Run `pytest -q`. Expected: all pass.
- [x] **Step 5:** Commit: "Ankle flag, hop and balance stages, test schedule".

### Task 6: Wire into the view and add the POST routes

**Files:**
- Modify: `app/main.py`
- Test: `tests/test_strength_view.py`

**Interfaces:**
- **Consumes:** Tasks 1, 3, 4 and 5.
- **Produces:**
  - `build_view` computes the ankle context once: `flag_until`, `hop_stage`, `balance_stage`, `restart` and
    `last_any_log`. For each week it computes `wed_bad`, then:
    - `w["strength"] = strength.sessions_for_week(w, eq, ctx)`;
    - for each exercise, `ex["suggestion"] = progression.suggest(...)`;
    - `ex["log"]` = the log for that date, if any;
    - `w["snack"]` = a dict per `ankle_days` date in the week, holding `items` from `BALANCE_STAGES` and the
      ticked set. In race week the snack has only the first two items.
  - The dashboard context adds `strength_session` (today's session, if any), `snack_today`, `morning_check`
    (bool), `tests_due` (bool), `ankle_flag` (date or None), `hop_stage` and `injured_side`.
  - Routes, each with a 303 redirect to `/#<anchor>`:
    - `POST /strength/log`: form fields `date`, `exercise`, `weight` (optional), `level`, `rung`, `target_reps`,
      `rep1`…`rep5`, `rating`, `ankle_pain` (optional). Blank reps fields are dropped. Redirects to
      `#ex-<key>`.
    - `POST /snack`: `date`, `item`. Toggles.
    - `POST /ankle/check`: `date`, `worse` ("0" or "1"), `note`.
    - `POST /ankle/tests`: `date`, plus `<test>_injured` and `<test>_other` for each key in `TESTS`. Blank
      fields are skipped.

- [x] **Step 1: Write failing tests:**
  - `test_log_post_saves_and_redirects`.
  - `test_logged_exercise_shows_done_and_next_suggestion`: after logging an easy RDL, next Thursday's
    suggestion is +1 step.
  - `test_snack_toggle_post`.
  - `test_morning_check_post_raises_flag`: the following Thursday is `reduced`.
  - `test_wed_bad_trims_thursday`: insert a run and a review that make Wednesday `bad`.
  - `test_tests_post_and_due_clears`.
- [x] **Step 2:** Run them. Expected: FAIL.
- [x] **Step 3:** Implement.
- [x] **Step 4:** Run `pytest -q`. Expected: all pass.
- [x] **Step 5:** Commit: "Strength logging, snacks, ankle checks and tests wired into the app".

### Task 7: Cards on This week, and history on Strength

**Files:**
- Create: `app/templates/_strength.html` (macros: `strength_card(session, today)`, `snack_card(snack)`,
  `morning_check(today)`, `test_card(date, tests, injured_side)`)
- Modify: `app/templates/index.html`, `app/templates/strength.html`, `app/main.py` (`strength_page` passes
  `history = {key: db.logs(key)[:8]}`)
- Test: `tests/test_strength_view.py`

**Interfaces:**
- **Consumes:** the Task 6 context.
- **Layout:** the mockup chosen in brainstorming (layout A, `.superpowers/brainstorm/*/content/strength-card.html`).
  - One `<details>` per exercise; the first undone one is open.
  - Inside it, a form for that exercise:
    - the weight as `<input type="number" name="weight">`, with `step` set to the exercise's load step and
      `min`/`max` from `available_weights`, pre-filled with the suggestion (the phone's own stepper gives −/+);
    - rep inputs pre-filled with `suggestion.reps`;
    - Easy, Right and Hard as three submit buttons (`name="rating"`);
    - `ankle_pain` select 0–10 on ankle items.
  - A done row collapses to "Box squat 60 kg, 3 × 8, right". The progress bar reads "N of M done".
- **Placement on This week:**
  - The morning check comes first, when due.
  - Then the strength card as hero if today has a session and no run. Otherwise the run hero comes first and
    the strength card goes under it.
  - The test card goes under the hero in a test week until it's done.
  - The snack card goes under the run hero on `ankle_days`.
  - While the flag is up, a notice: "Ankle flag until <date>: no increases on ankle work."
- **Strength page:** a per-exercise history table: date, weight, reps, rating.

- [x] **Step 1: Write failing tests:**
  - `test_strength_card_is_hero_on_tuesday`.
  - `test_strength_card_below_run_hero`.
  - `test_card_shows_last_and_suggestion`: shows "last time 50 kg" and "Try 55 kg".
  - `test_snack_card_on_ankle_day`.
  - `test_morning_check_shown_after_thursday`.
  - `test_test_card_in_week_1`.
  - `test_history_on_strength_page`.
  - `test_pages_200` still passes.
- [x] **Step 2:** Run them. Expected: FAIL.
- [x] **Step 3:** Implement the templates and minimal CSS in each template's `head` block. No new fonts or
  colours.
- [x] **Step 4:** Run `pytest -q`. Expected: all pass.
- [x] **Step 5:** Preview at 390 px, light and dark, with the scratchpad `preview.py` dated to a week-9
  Thursday and a seeded log. Screenshot the Thursday card part-way through, Tuesday, a snack, the morning check
  and the test card. Fix whatever reads badly.
- [x] **Step 6:** Commit: "Strength checklist, snack, ankle check and test cards".

### Task 8: Docs, review, deploy

**Files:**
- Modify: `README.md` (Strength section rewritten for the runner: the sessions, logging, suggestions, ankle
  snacks, tests and hop stages, and the ankle flag), `CLAUDE.md` (the new modules and tables; strength no
  longer lightened by adjacency)

- [x] **Step 1:** Update the docs.
- [x] **Step 2:** Run `pytest -q` and the generator one-liner. Check the spec's "How to check it" list.
- [ ] **Step 3:** Commit, push the branch, and open a PR.
- [ ] **Step 4:** After the user merges, run `fly deploy --ha=false`, wake the app, and run the `fly ssh
  console` page check. Expected: `[200, 200, 200, 200]`. The user logs a real Tuesday session.
