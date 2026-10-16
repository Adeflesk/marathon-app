# Base Plan to Best Practice Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Reshape the generated marathon plan to the evidence: a phase-based Wednesday session menu,
best-practice long runs, a 60 km peak, and Garmin workouts with real repeat steps.

**Architecture:**
- **Volumes (`plan.weekly_volumes`):** labels each week with a block (General, Threshold, Strength or
  Specific, counted back from the taper) and owns every long-run rule.
- **Sessions (new `app/sessions.py`):** builds each Wednesday session as a list of steps and repeat
  blocks, sizes them against the work caps, and writes the notes.
- **Plan assembly (`plan.generate`):** fits the session into the week's km.
- **Watch export (`garmin`):** translates the steps one-to-one into FIT steps.
- **The plan is still never stored.**

**Tech Stack:** Python 3.11, FastAPI, Jinja2, fit-tool, and pytest (new; dev only).

**Spec:** `docs/superpowers/specs/2026-10-16-base-plan-best-practice-design.md`. Read it first; this
plan does not repeat its reasoning.

## Global Constraints

- Units: km, seconds per km, seconds. Planned km are rounded to 0.5 (`plan._half`). Format only at display time.
- `plan.py` and `sessions.py` are pure functions; the plan is recomputed per request, never stored.
- No hardcoded week numbers or weekdays. Blocks are found by position relative to the taper.
- `DEFAULTS["peak_weekly_km"] = 60`. New paces: `interval: 300`, `subthreshold: 332`.
- The check-in factor only ever reduces load.
- Keep the existing FIT message shapes (file_id, workout, steps with speed-range targets) that already load on the user's watch.
- Taper volume falls every week. Nothing is scheduled on or after `race_date`.

## Review Focus

1. **Other settings** (`base_weeks: 2`, `peak_weekly_km: 50`, a Saturday `race_date`, a late `plan_start`
   giving about 10 weeks): the plan builds, no cutback sits right before the taper, and all invariants
   hold. Tested in Task 2 and Task 4.
2. **A check-in trim of 0.8 or 0.9 on a structured session:** reps drop but stay at 2 or more, and the
   day's km, note and FIT all match the trimmed reps. Tested in Task 5.
3. **`run_days` with no `quality` day:** no session is placed, and nothing crashes. Tested in Task 4.
4. **A short plan where blocks disappear:** with only 1–2 build blocks, the last is still Specific, and
   General and then Threshold go first. Tested in Task 2.
5. **Repeat steps in the FIT:** each repeat step points back to its block's first step index, and
   `num_valid_steps` counts every step. Tested in Task 6.

---

### Task 1: Test harness and new defaults

**Files:**
- Create: `requirements-dev.txt`, `tests/__init__.py`, `tests/conftest.py`, `tests/test_config.py`
- Modify: `app/config.py` (`DEFAULTS`)

**Interfaces:**
- Produces: the pytest fixture `settings() -> dict`, which is `load_settings()` with defaults only, ignoring any `settings.json`. `conftest.py` sets `os.environ["DB_PATH"]` to a tmp file *before* any `app` import.

- [ ] **Step 1:** In `requirements-dev.txt`, add `-r requirements.txt` and `pytest==8.3.3`, then `pip install -r requirements-dev.txt`.
- [ ] **Step 2: Write failing tests** in `tests/test_config.py`:
  - `test_peak_default`: `settings["peak_weekly_km"] == 60`.
  - `test_new_paces`: `settings["paces"]["interval"] == 300 and settings["paces"]["subthreshold"] == 332`.
- [ ] **Step 3:** Run `pytest tests/test_config.py -v`. Expected: 2 FAIL.
- [ ] **Step 4:** Update `DEFAULTS` in `app/config.py`, with one comment line per new pace (`interval` is about 5 km pace; `subthreshold` is MP − 9 s).
- [ ] **Step 5:** Run `pytest -v`. Expected: PASS.
- [ ] **Step 6:** Commit: `git add requirements-dev.txt tests app/config.py && git commit -m "Add pytest harness; peak 60 km, interval and subthreshold paces"`.

### Task 2: Blocks and long-run rules in `weekly_volumes`

**Files:**
- Modify: `app/plan.py` (`weekly_volumes`)
- Test: `tests/test_volumes.py`

**Interfaces:**
- Produces: `weekly_volumes(n: int, s: dict) -> list[dict]`. Each dict has:
  - `km: float`, `long: float`, `cutback: bool`, `phase: str`;
  - `block: str | None`, one of `"general"`, `"threshold"`, `"strength"` or `"specific"`. A cutback
    carries the block before it. It is `None` for Rebuild, Taper and Race week;
  - `block_week: int | None`, the 0-based position inside the block (`None` for cutbacks, Rebuild,
    Taper and Race week);
  - `mp_km: float`, which is 0 when there's no MP finish.
- Phases: `"Rebuild"`, `"Build"`, `"Cutback"`, `"Peak"` (the whole last block), `"Taper"`, `"Race week"`.

The rules come from the spec's "Phases and blocks" and "Long runs" sections:
- **Cutbacks:** every 4th post-base week. A cutback in the week before Taper 1 becomes a build week.
- **Blocks:** maximal runs of build weeks, named from the taper backwards: specific, strength,
  threshold, then general for any earlier.
- **Long run in each build week:** `min(last + 2, max_long_run_km, 12600 / paces.long, share × km)`.
  - The first build week is 12 km.
  - The share is 0.58 in Peak weeks and 0.5 otherwise.
  - Spike guard: if the value is 20 km or more, cap it at 1.1 × the max long of the previous 4 weeks,
    rounded *down* to 0.5.
  - The last build week is exempt from the guard.
- **Specific block:** after the forward pass, find any week whose previous long run is 30 km or more.
  Also find the week before the final week, if it is 30 km or more. Each of these gets
  `round(0.85 × the longest earlier long in the block, not counting itself)`, easy, with no MP.
- **MP finishes:** counting weeks from the first strength-block week (offset 0), weeks at offsets 0,
  2, 4, 6 and so on get MP if they are non-cutback build weeks and weren't made easy by the
  Specific-block rule. The amounts are 6, 8, 10, then 12 km (12 is the cap), with
  `mp_km = max(0, min(that, long − 8))`. With the defaults that's weeks 12, 14, 16 and 18.
- **Cutback long run:** `round(last × 0.75)`, as today. Taper and Race week keep today's values.

- [ ] **Step 1: Write failing tests** in `tests/test_volumes.py`, using `n, vols` from `week_count` and `weekly_volumes` on `settings`:
  - `test_default_phases`: `[v["phase"] for v in vols]` equals 3×Rebuild, 3×Build, Cutback, 3×Build, Cutback, 3×Build, Cutback, 3×Peak, 2×Taper, Race week (21 weeks).
  - `test_default_km`: `[v["km"] for v in vols[:20]] == [25,25,25,28,31,34,27,37,40,43,34,46,49,52,42,55,58,60,45,33]`.
  - `test_blocks`: the blocks for weeks 4–6, 8–10, 12–14 and 16–18 are general, threshold, strength and specific, and cutback weeks 7, 11 and 15 carry general, threshold and strength.
  - `test_peak_long_runs`: the longs for weeks 16–18 are `[28, 24, 32]`.
  - `test_mp_weeks`: `{week: mp_km for mp_km > 0} == {12: 6, 14: 8, 16: 10, 18: 12}`.
  - `test_long_run_invariants(settings_variant)`, parametrised over the defaults, `{"base_weeks": 2}`, `{"peak_weekly_km": 50}`, `{"race_date": "2027-03-13"}` and `{"plan_start": "2026-12-28"}`. Assert:
    - no two consecutive longs are 30 km or more;
    - every long of 20 km or more, except the last build week's, is ≤ 1.1 × the max of the previous 4 longs;
    - every long is ≤ 32 km;
    - the week before the first Taper is not a Cutback;
    - the last block is `"specific"`;
    - Taper and Race km fall strictly.
  - `test_short_plan_drops_early_blocks`: with `plan_start` set so `n` is about 10, the blocks present are a suffix of `["general", "threshold", "strength", "specific"]`.
- [ ] **Step 2:** Run `pytest tests/test_volumes.py -v`. Expected: FAIL (no `block` key).
- [ ] **Step 3:** Implement the rules above in `weekly_volumes`. `generate` still runs, ignoring the new keys, but now reads `mp_km` from `v` instead of computing it.
- [ ] **Step 4:** Run `pytest -v`. Expected: PASS.
- [ ] **Step 5:** Commit: `git commit -am "Plan blocks, peak block and best-practice long runs"`.

### Task 3: Session builder (`app/sessions.py`)

**Files:**
- Create: `app/sessions.py`
- Test: `tests/test_sessions.py`

**Interfaces:**
- Step dicts are exactly as in the spec's "Data shape". `pace` is a `settings.paces` key, a number (s/km), or `None`.
- `pace_s(pace, paces) -> float`: `None` maps to `paces["easy"]`.
- `step_km(step, paces) -> float`: `km`, or `seconds / pace_s`.
- `session_km(steps, paces) -> float`: the total, with repeats expanded.
- `work_km(steps, paces) -> float`: km of `active` steps only. Warm-up, cool-down and recovery are excluded; floats count.
- `quality_session(v: dict, week_index: int, s: dict, max_km: float) -> dict | None`: returns `{"type", "pace", "hard", "steps", "note"}`, or `None` for Rebuild week 1. `pace` is the main rep's paces key (MP-based sessions use `"marathon"`). `hard` is `True` only for threshold, strength, specific and mp types in Build, Peak and Cutback weeks.
- `fit_session(steps, s, cap_pct, max_km) -> list` trims a session to fit, in this order:
  1. while over the cap or over `max_km`, drop a rep, down to 2;
  2. then shorten the rep length along the ladder `[3.2, 2.4, 1.6, 1.0]` for threshold and strength, or
     `[5, 4, 3]` for specific;
  3. if it still doesn't fit, use the block's cutback version.
- `describe(steps, paces) -> str`: e.g. `"2 km WU, 4 × 1.6 km at 5:25 with 60 s jog, 1.5 km CD. Flat ground."`.
- `scale_session(workout: dict, factor: float, paces: dict) -> None`: sets each repeat to `max(2, floor(reps × factor))`, then recomputes `km` (via `_half`) and `note`.
- Menu: the spec's "Wednesday (quality day) session menu" table, verbatim.
  - Warm-up and cool-down are easy-pace distance steps at their minimums of 2 km and 1 km. In race
    week they are 1 km each.
  - Strides are 20 s at `interval` with a 60 s recovery.
  - Float is a 1 km active step at `paces["marathon"] / 0.95`.
  - Specific reps are at `paces["marathon"] - 3`.
  - A block longer than 3 weeks repeats its last progression step.
- Caps (`cap_pct`): 0.12 for `tempo` reps, and 0.18 for `subthreshold`, MP and specific. Both are a
  share of `v["km"]`.

- [ ] **Step 1: Write failing tests** in `tests/test_sessions.py`:
  - `test_session_km_expands_repeats`: `4 × (1.6 km + 60 s jog)` plus 2 km WU and 1 km CD equals `3 + 6.4 + 4 × 60/405` within 0.01.
  - `test_work_km_excludes_recovery`: the same steps give 6.4.
  - `test_menu_types`: using `weekly_volumes` defaults, the weeks map as follows:
    - wk1 → `None`;
    - wk2 → `"strides"`;
    - wk4 → `"fartlek"`;
    - wk8 → `"threshold"`;
    - wk12 → `"strength"`;
    - wk16 → `"specific"`;
    - wk7 → `"fartlek"`, with 5 reps;
    - wk19 → `"strength"`, with `hard` False;
    - wk20 → `"mp"`;
    - wk21 → `"mp"`.
  - `test_caps_hold`: for every week, `work_km ≤ cap_pct × v["km"] + 0.01`.
  - `test_reps_floor`: no repeat block has fewer than 2 reps.
  - `test_scale_session`: on a 6 × 1.6 session at factor 0.8, the reps become 4, and `km` and `note` change.
  - `test_describe`: for the threshold example, the note contains `"× 1.6 km at 5:25"` and `"60 s jog"`.
- [ ] **Step 2:** Run `pytest tests/test_sessions.py -v`. Expected: FAIL (`ModuleNotFoundError`).
- [ ] **Step 3:** Implement `app/sessions.py` to the interfaces above. It imports `_half` and `DAYS` from `plan`, so it must not import `generate` (to avoid a circular import).
- [ ] **Step 4:** Run `pytest -v`. Expected: PASS.
- [ ] **Step 5:** Commit: `git add app/sessions.py tests/test_sessions.py && git commit -m "Wednesday session menu with repeat steps and work caps"`.

### Task 4: Put sessions into `generate`

**Files:**
- Modify: `app/plan.py` (`generate`)
- Test: `tests/test_generate.py`

**Interfaces:**
- Consumes: `sessions.quality_session`, `session_km` and `describe`.
- Produces: workout dicts as today, with `steps`, `hard` and the new `type` values on the quality day. `tempo_min` is removed. Long runs keep `mp_km`.

Quality-day sizing:
1. **Normal share:** each mid-week run's share is today's weighted split of `rest`.
2. **Easy floor:** `min(6 km in Build/Peak or 5 km elsewhere, that run's share)`.
3. **`max_km`** for the session is `rest − sum of the easy floors`.
4. **Wednesday's km** is `max(session_km, its share)`, capped at `max_km`. If the session is shorter
   than that, add the extra to the cool-down. The other runs split what's left by weight, and the last
   one absorbs rounding.
5. **Race week** keeps its fixed shakeouts (6 and 3 km) and uses the session's own km.

- [ ] **Step 1: Write failing tests** in `tests/test_generate.py`, parametrised over the same settings variants as Task 2:
  - `test_week_totals_match`: `sum(km) == target_km`, and `target_km` is within 0.5 of `v["km"]` for every non-race week.
  - `test_easy_floor`: every easy mid-week run's km is at least its floor, as defined above.
  - `test_quality_every_week_but_first`: every week except week 1 has exactly one workout with `steps`.
  - `test_nothing_after_race`: no workout is dated after `race_date`.
  - `test_no_quality_day`: with `run_days = {"mon": "easy", "sat": "easy", "sun": "long"}`, `generate` returns weeks with no `steps` and doesn't raise.
- [ ] **Step 2:** Run `pytest tests/test_generate.py -v`. Expected: FAIL.
- [ ] **Step 3:** Implement the sizing in `generate`. Delete the old tempo branch (the `i >= 7` rule and `tempo_min`).
- [ ] **Step 4:** Run `pytest -v`. Expected: PASS.
- [ ] **Step 5:** Commit: `git commit -am "Generate weeks with structured quality sessions"`.

### Task 5: Check-in trim, strength adjacency and templates

**Files:**
- Modify: `app/main.py` (`build_view` trim block), `app/strength.py` (`sessions_for_week`), `app/templates/index.html` and `plan.html` (only if they show something stale)
- Test: `tests/test_view.py`

**Interfaces:**
- Consumes: `sessions.scale_session`.
- In `build_view`, workouts with `steps` use `scale_session(wo, factor, s["paces"])`. The others scale km as today. Delete the old `tempo_min` branch.
- In `strength.py`, `has_tempo` becomes `has_hard = any(w.get("hard") and abs(...) == 1 ...)`, with the note text "A hard session is next to this one, so the volume is kept lower."

- [ ] **Step 1: Write failing tests** in `tests/test_view.py`. Use `TestClient(app)` with no `APP_PASSWORD`, and post a check-in with `pain=6` for week 11:
  - `test_trim_scales_reps`: in week 12, the session's reps are each `max(2, floor(original × 0.8))`, `km == _half(session_km)`, and the note matches `describe(steps)`.
  - `test_trimmed_fit_matches`: `garmin.steps_for` on that workout expands to the same rep count. Run this after Task 6, or mark it `xfail` until then.
  - `test_strength_a_reduced_only_next_to_hard`: Strength A's `reduced` flag is False in week 5 (fartlek on Wednesday) and True in week 9 (threshold).
  - `test_pages_200`: `/`, `/plan`, `/strength` and `/equipment` all return 200.
- [ ] **Step 2:** Run `pytest tests/test_view.py -v`. Expected: FAIL.
- [ ] **Step 3:** Implement the changes above.
- [ ] **Step 4:** Run `pytest -v`. Expected: PASS, apart from the xfail.
- [ ] **Step 5:** Commit: `git commit -am "Trim structured sessions by reps; strength adjacency on hard sessions"`.

### Task 6: FIT export with repeat steps

**Files:**
- Modify: `app/garmin.py` (`steps_for` and `_step`)
- Test: `tests/test_garmin.py`

**Interfaces:**
- Consumes: workout `steps`, and `sessions.pace_s`.
- `steps_for(w, paces) -> list[WorkoutStepMessage]`. For `steps`:
  - **Each step** becomes one message. The intensity maps to `Intensity.WARMUP`, `ACTIVE`, `RECOVERY`
    or `COOLDOWN`.
  - **Pace `None`:** `target_type = WorkoutStepTarget.OPEN`.
  - **Otherwise:** a speed range, using `EASY_BAND` when the pace is at least `paces["long"]` and
    `HARD_BAND` when it's faster.
  - **Distance or time:** `km` gives a distance duration, `seconds` a time duration.
  - **Notes:** a step's `note` goes to `notes`.
  - **After each repeat block's steps,** add one message with
    `duration_type = WorkoutStepDuration.REPEAT_UNTIL_STEPS_CMPLT`,
    `duration_step = <index of the block's first step>` and `target_repeat_steps = <reps>`.

  Without `steps`, the easy, long, long-with-MP and race runs export exactly as today. `build_fit` is unchanged; `num_valid_steps = len(steps)` already counts the repeat steps.

- [ ] **Step 1: Write failing tests** in `tests/test_garmin.py`:
  - `test_repeat_structure`: for week 8's threshold workout, the messages are WU, rep, jog, repeat, CD. The repeat has `duration_step == 1` and `target_repeat_steps` equal to the session's reps. The jog has an open target and recovery intensity.
  - `test_two_blocks`: on a hand-built workout with two repeat blocks, the second repeat's `duration_step` points to its own first step.
  - `test_build_fit_bytes`: `build_fit` returns bytes starting with a valid FIT header (`data[8:12] == b".FIT"`), for every workout in the default plan with `km > 0`.
- [ ] **Step 2:** Run `pytest tests/test_garmin.py -v`. Expected: FAIL.
- [ ] **Step 3:** Implement the export. Remove the `xfail` from `test_trimmed_fit_matches`.
- [ ] **Step 4:** Run `pytest -v`. Expected: all PASS.
- [ ] **Step 5:** Export week 8's session and decode it with `python -I <scratchpad>/rawfit.py <file>`. The structure should mirror `samples/garmin/Wednesday_speed_workout.fit`: a repeat step after the rep and recovery steps.
- [ ] **Step 6:** Commit: `git commit -am "FIT export with repeat steps"`.

### Task 7: Docs, full check, deploy

**Files:**
- Modify: `README.md` (training logic), `CLAUDE.md` (the `plan.py` description, a new `sessions.py` entry, the Commands section with `pytest`, and the removal of "There are no tests")

- [ ] **Step 1:** Update the README for the session menu, MP finishes every other week, the peak block, the 60 km peak and the 32 km final long run. Write it for the runner, in plain terms.
- [ ] **Step 2:** Update CLAUDE.md. Remove "tempo from week index 7, MP from index 10", and describe the blocks, `sessions.py` and `pytest`.
- [ ] **Step 3:** Run `pytest -v` and the generator one-liner. Check the spec's "How to check it" list against the output.
- [ ] **Step 4:** Commit and push: `git commit -am "Docs for best-practice plan" && git push`.
- [ ] **Step 5:** Run `fly deploy --ha=false`. Wake the app with `curl`, then run the `fly ssh console` page check. Expected: `[200, 200, 200, 200]`.
- [ ] **Step 6:** Ask the user to load one structured session (week 8 or later) onto their watch and confirm the reps count down.
