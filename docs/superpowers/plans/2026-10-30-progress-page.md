# Progress Page Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A Progress tab that answers "am I on course for my goal?", backs it with four pieces of evidence and
weekly summaries, and lets the user change the goal.

**Architecture:** A new pure module `app/progress.py` turns what `build_view()` already computes (weeks with
reviews, guard, strength, ankle state, `s["result"]`) into the page's numbers and sentences. Goals are a new
stored fact (`goals` table) applied in `build_view()` before item 2's `apply_result()`. One new page
(`GET /progress`), one new form (`POST /goal`), and a summary card on This week on Monday and Tuesday.

**Tech Stack:** FastAPI, Jinja2, SQLite, inline SVG (no JS), pytest.

**Spec:** `docs/superpowers/specs/2026-10-30-progress-page-design.md`

## Global Constraints

- The plan is never stored; summaries and charts are recomputed per request. Goals are user facts.
- No JavaScript; POSTs redirect with 303 to an anchor. Phone-first at 390 px, light and dark, tokens from `base.html`.
- New tables with `CREATE TABLE IF NOT EXISTS`; no migrations.
- Verdict bands = item 2's: predicted ≤ goal "on course"; ≤ 5% slower "within reach"; else "stretch".
- Fitness reference pace = the settings' easy pace (`load_settings()["paces"]["easy"]`, 405), ±15 s/km, km 1 left
  out, splits ≥ 0.9 km, ≥ 3 splits per week, easy and long runs only.
- Drift colours: < 5 green, 5–10 amber, > 10 red, missing grey.
- Ankle targets: calf raises 25, eyes-closed balance 30 s, Y-balance 90% of the other side.
- Stretch goal = prediction × (1 − min(0.04, 0.01 × weeks_left / 4)), rounded to the minute; prediction card
  rounds up to the minute; drop cards within 60 s of another card or the current goal.
- The app never changes the goal on its own.

## Review Focus

1. **Weeks with runs but no details** (not synced, or sync before details): reviews are None. Expect gaps in the
   fitness line and grey long-run bars, never a crash or a zero. → Task 2 test `test_runs_without_details_are_gaps`.
2. **The current, unfinished week**: no summary for it, plan bar shows done-so-far, the "Plan" why row uses the
   last 4 *completed* weeks only. → Task 2 `test_plan_bars_current_week_partial`, Task 4 `test_no_summary_for_current_week`.
3. **A malformed or silly goal** posted ("soon", "1:00:00", "9:00:00"): refused with a message, nothing stored.
   → Task 1 `test_bad_goals_are_refused`.
4. **A goal change with a result already logged**: the result's verdict is recomputed against the new goal, and
   item 2's MP rule still applies on top. → Task 1 `test_goal_change_with_a_result`.
5. **Skipped and moved sessions**: a skipped strength session isn't counted as missed; a moved run counts in the
   week it landed in. → Task 3 `test_why_plan_ignores_skipped_strength`.

---

### Task 1: Goals as a stored fact

**Files:**
- Modify: `app/db.py` (table `goals`, `save_goal`, `goals`)
- Modify: `app/main.py` (`apply_goal`, call order in `build_view`, `POST /goal`)
- Test: `tests/test_goals.py`

**Interfaces:**
- Produces: `db.save_goal(goal_time: str) -> None` (row: `id INTEGER PRIMARY KEY`, `date TEXT` (today), `goal_time TEXT` "H:MM:SS", `created TEXT`);
  `db.goals() -> list[dict]` oldest first.
- Produces: `main.apply_goal(s: dict, t: date) -> None`: latest goal row (any date ≤ t) whose `goal_time != s["goal_time"]`
  sets `s["goal_time"]`, `s["paces"]["marathon"] = round(parse_time(goal)/42.195)`, `s["paces"]["subthreshold"] = marathon - 9`.
  If the latest row equals the settings goal, nothing changes (exact settings paces). Always sets
  `s["settings_goal"]` (the settings value) and `s["goal_changes"] = [{"date", "from", "to"}]` built from consecutive rows
  (first `from` = settings goal; rows equal to the previous goal skipped).
- Produces: `POST /goal` form field `goal` ("H:MM:SS"); accepts 2:30:00–6:00:00; saves and redirects 303 to `/progress#verdict`
  with msg "Goal changed to 4:09. The plan now follows it."; else msg "Not changed: …".
- `build_view` order: `load_settings()` → `apply_goal(s, t)` → `apply_result(s, t)` → `generate`.

- [ ] **Step 1: Write the failing tests** in `tests/test_goals.py` (client fixture clears `goals` and `results`, like `tests/test_results.py`):
  - `test_changing_the_goal_moves_marathon_pace`: POST `/goal` `goal=4:09:00` → 303; `build_view()[0]`: `goal_time == "4:09:00"`, `paces["marathon"] == 354`, `paces["subthreshold"] == 345`; `client.get("/").text` contains `"4:09:00"`.
  - `test_back_to_the_settings_goal_restores_exact_paces`: POST 4:09:00 then 3:59:00 → `paces == settings["paces"]` (341, not 340); `goal_changes` has two entries, the second `{"from": "4:09:00", "to": "3:59:00"}`.
  - `test_bad_goals_are_refused`: "soon", "1:00:00", "9:00:00" → `db.goals() == []`.
  - `test_goal_change_with_a_result`: save result 5 km 26:30 (`db.save_result`) and POST 4:09:00 → `s["result"]["verdict"] == "within reach"`, `s["result"]["mp_source"] == "threshold"`, `paces["marathon"] == paces["tempo"] + 10`.
- [ ] **Step 2: Run** `.venv/bin/pytest tests/test_goals.py -q` → FAIL (no route / no table).
- [ ] **Step 3: Implement** the table, the two db functions, `apply_goal`, the route.
- [ ] **Step 4: Run** `.venv/bin/pytest -q` → all pass.
- [ ] **Step 5: Commit** `git commit -m "Goals as a stored fact: POST /goal moves goal and marathon pace"`

### Task 2: Fitness, long-run and plan series

**Files:**
- Create: `app/progress.py`
- Test: `tests/test_progress.py`

**Interfaces:**
- Consumes: weeks from `main.build_view()` (each workout may carry `review` with `splits: [{km, pace, hr}]`, `drift`; `actual_km`; `skipped`; week `target_km`, `actual_km`, `guard`, `is_past`, `is_current`, `week`, `start`).
- Produces (all pure):
  - `fitness_trend(weeks: list[dict], ref_pace: float) -> list[dict]`: one `{"week": int, "hr": float | None, "n": int}` per week up to the current one; `hr` = median HR of qualifying splits, None when `n < 3`.
  - `long_runs(weeks: list[dict]) -> list[dict]`: per long run done, `{"week", "date", "km": actual_km, "drift": float | None, "mp": bool, "colour": "good"|"warn"|"bad"|"none"}`.
  - `plan_bars(weeks: list[dict]) -> list[dict]`: per past and current week `{"week", "planned": target_km, "done": actual_km, "held": bool}`.

- [ ] **Step 1: Write failing tests** with hand-built week dicts (a helper `wk(n, workouts, **kw)`):
  - `test_fitness_uses_splits_near_easy_pace`: easy run splits (km, pace, hr) `[(1, 400, 130), (1, 400, 150), (1, 410, 152), (1, 415, 148), (1, 380, 160), (1, 430, 170)]`, ref 405 → hr 150, n 3 (km 1 dropped; 380 and 430 outside 390–420).
  - `test_quality_days_and_short_splits_dont_count`: a workout with `steps` and a 0.5 km split → n = 0, hr None.
  - `test_runs_without_details_are_gaps`: `review: None` → hr None; long run with `review: None` → colour "none".
  - `test_long_run_colours`: drifts 3.0, 6.0, 12.0, None → good, warn, bad, none; `mp` True when `mp_km > 0`.
  - `test_plan_bars_current_week_partial`: past week and current week included, future week excluded; `held` True when `guard` set.
- [ ] **Step 2: Run** `.venv/bin/pytest tests/test_progress.py -q` → FAIL (no module).
- [ ] **Step 3: Implement** the three functions in `app/progress.py`.
- [ ] **Step 4: Run** → pass.
- [ ] **Step 5: Commit** `git commit -m "Progress: fitness, long-run and plan series"`

### Task 3: Verdict, why rows, goal options, ankle table

**Files:**
- Modify: `app/progress.py`
- Test: `tests/test_progress.py`

**Interfaces:**
- Consumes: Task 2's functions; `s["result"]` (`predicted`, `verdict`, `date`, `km`, `seconds`) from item 2; `s["goal_time"]`, `s["settings_goal"]`, `s["goal_changes"]` from Task 1; `ankle_state` dict (`tests`, `flag_until`, `hop_stage`, `balance_stage`, `logs`, `checks`) as `weeks[0]["ankle_state"]`.
- Produces:
  - `verdict(s: dict) -> dict`: `{"state": "none"|"on course"|"within reach"|"stretch", "predicted": float|None, "goal": str}`.
  - `goal_options(predicted: float, goal_s: float, settings_goal_s: float, weeks_left: int) -> list[dict]`: each `{"seconds": int, "time": "H:MM:SS", "mp": int, "kind": "stretch"|"prediction"|"back", "why": str}`; "back" only when `goal_s != settings_goal_s`; 60 s de-duplication against each other and `goal_s`.
  - `why_rows(weeks: list[dict], t: date) -> list[dict]`: four `{"key": "plan"|"fitness"|"long"|"ankle", "ok": bool, "text": str}`.
  - `ankle_table(weeks: list[dict], tests: list[dict]) -> dict`: `{"columns": [week numbers with any core test], "rows": [{"name", "target", "cells": [{"value", "met": bool} | None]}]}`; Y-balance row = worst of the three reaches as % of the other side.

- [ ] **Step 1: Write failing tests:**
  - `test_verdict_states`: no result → "none"; result verdicts "on track"/"within reach"/"ambitious" map to "on course"/"within reach"/"stretch".
  - `test_goal_options_for_a_stretch`: predicted 4:19:15 (15555 s), goal 3:59:00, settings 3:59:00, weeks_left 19 → times `["4:09:00", "4:20:00"]`, kinds stretch, prediction; no "back".
  - `test_goal_options_offer_the_way_back`: goal 4:09:00, settings 3:59:00 → a "back" option with time "3:59:00".
  - `test_goal_options_drop_near_duplicates`: predicted 4:00:30, goal 3:59:00, weeks_left 2 → stretch within 60 s of goal dropped.
  - `test_why_plan_ignores_skipped_strength`: 4 completed weeks at 100% with one skipped strength session → plan row ok, text says "8 of 8" (skipped excluded from both sides).
  - `test_why_rows_warn`: a week at 50% → plan not ok; flag up → ankle not ok; two of last three long runs drift ≥ 5 → long not ok; fitness hr rising first→latest → fitness not ok.
  - `test_ankle_table_from_week_one_tests`: tests from 23 Oct (calf 19/21, eyes 28/21, Y 70/80, 75/80, 75/80) → columns [1]; calf cell 19 not met; eyes 28 not met; Y-balance 87.5 not met (target 90).
- [ ] **Step 2: Run** → FAIL.
- [ ] **Step 3: Implement.** Stretch: `predicted * (1 - min(0.04, 0.01 * weeks_left / 4))`, round to 60 s. Prediction: ceil to 60 s. `mp = round(seconds / 42.195)`.
- [ ] **Step 4: Run** → pass.
- [ ] **Step 5: Commit** `git commit -m "Progress: verdict, why rows, goal options, ankle table"`

### Task 4: Weekly summaries

**Files:**
- Modify: `app/progress.py`
- Test: `tests/test_progress.py`

**Interfaces:**
- Consumes: weeks from `build_view()` (workouts with `review.headline`, `actual_km`, `type`, `steps`; `strength` sessions with `done`, `skipped`, exercises' `log.ankle_pain`; `guard`, `checkin`), ankle state (`snacks`, `checks`, `flag_until`), `s["goal_changes"]`, `db.results()` rows, the paces.
- Produces: `summaries(weeks: list[dict], s: dict, st: dict, results: list[dict], t: date) -> list[dict]`, newest first, completed weeks only: `{"week", "start", "end", "planned", "done", "sentences": list[str], "next": str}`.
  `next` = first rule that applies, in the spec's order (1 ankle flag or rising pain … 8 "Keep doing what you're doing.").

- [ ] **Step 1: Write failing tests** (real `build_view()` on a temp DB, like `tests/test_volume_guard.py`):
  - `test_week_one_summary`: activities for 19, 21, 24, 25 Oct with details from `tests/test_review.py` style splits, today 27 Oct → one summary; heading numbers 25 of 25; sentences mention the long run's headline; `next` is the easy-pace rule when the easy runs average 6:30 against 6:45.
  - `test_no_summary_for_current_week`: today Wednesday of week 2 → only week 1.
  - `test_low_week_focus`: week 9 at 10 of 40 km → its `next` starts "Ease back in".
  - `test_ankle_focus_wins`: a "worse" morning check in the week → `next` starts "Ankle first".
  - `test_snacks_focus`: everything fine but 2 snack days → `next` mentions 4 snack days.
- [ ] **Step 2: Run** → FAIL.
- [ ] **Step 3: Implement.** One small function per sentence part; the rules as an ordered list of (test, text) pairs.
- [ ] **Step 4: Run** → pass.
- [ ] **Step 5: Commit** `git commit -m "Progress: weekly summaries with one focus for next week"`

### Task 5: The page, the nav, This week's card, docs

**Files:**
- Create: `app/templates/progress.html`
- Modify: `app/main.py` (`GET /progress`; dashboard gets `last_summary` on Monday and Tuesday), `app/templates/base.html` (nav link), `app/templates/index.html` (summary card under the hero)
- Modify: `README.md`, `CLAUDE.md`, `docs/roadmap.md` (tick item 1)
- Test: `tests/test_progress_page.py`

**Interfaces:**
- Consumes: everything above. `GET /progress` context: `verdict`, `options`, `why`, `fitness`, `long_runs`, `plan`, `ankle`, `summaries`, `goal_changes`, `week` (current), `n_weeks`.

- [ ] **Step 1: Write failing tests:**
  - `test_progress_page_without_a_result`: 200; contains "Not enough to call yet"; nav has `href="/progress"`.
  - `test_progress_page_with_a_stretch`: result 5 km 26:30 → contains "3:59 is a stretch", a form posting `goal=4:09:00`, "Train for 4:09".
  - `test_this_week_shows_last_weeks_summary_monday_only`: Monday of week 2 → "Week 1" summary card on `/`; Wednesday → absent.
  - `test_progress_renders_every_day`: loop every day from plan start to race day, `/progress` 200.
- [ ] **Step 2: Run** → FAIL.
- [ ] **Step 3: Implement** the template (verdict card `id="verdict"`, goal cards as POST forms, inline SVG charts like the profile in `index.html`, ankle table, `<details>` summaries with the newest open), the route, the nav link, the dashboard card, the docs.
- [ ] **Step 4: Run** `.venv/bin/pytest -q` → all pass; render `/progress` against a copy of production data and read the text.
- [ ] **Step 5: Commit** `git commit -m "Progress page: verdict, evidence, goal choice and weekly summaries"`
