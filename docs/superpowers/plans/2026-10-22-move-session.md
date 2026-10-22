# Move or Skip a Session Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A **Move to tomorrow** button on every run and strength session from today on, with a clash warning
that advises skipping the missed session, plus Skip and Undo, all following the session to its new day.

**Architecture:** Moves are stored user facts (`moves` table), keyed by the session's original planned date and
identity. A new pure module, `app/moves.py`, applies them to the freshly generated plan inside
`main.build_view`, relocates sessions that cross into the next week, and checks clashes. The plan itself is
still never stored.

**Tech Stack:** Python 3.11, FastAPI, Jinja2, SQLite, pytest.

**Spec:** `docs/superpowers/specs/2026-10-22-move-session-design.md`, including "Settled after the builder
check". Executors read both.

## Global Constraints

- The plan is never stored. Only the move/skip fact is stored. A stored move whose session no longer exists is
  ignored.
- Next day only. No moves onto race day or past the plan's last day; no moves of sessions dated before today.
- Clash rules: the target day has a long run or a speed session (a workout with `steps`), or a run is being
  moved and the target day has any run, or a strength session lands on the other strength session's day.
- The warning advises skipping the **missed** session; tomorrow's own session is never changed.
- A moved session keeps its own week's prescription and check-in factor.
- Forms work without JavaScript: POST, then a 303 redirect.
- Phone-first at 390 px, light and dark, existing tokens from `base.html` and `_ui.html`. No new fonts or
  colours.
- Strength days come from `settings["strength_days"]`; never hardcode Tuesday or Thursday.

## Review Focus

1. **A session already done is moved** (a strength session with logs, or a run with synced km on its day): the
   button is hidden, so logs and runs don't get orphaned. Task 4 test: `test_no_move_button_once_done`.
2. **Moving twice** (Thu → Fri → Sat) updates the one stored row, still keyed by Thursday, so Undo returns to
   Thursday. Task 1 test: `test_move_twice_keeps_original`; Task 4 test: `test_move_twice_then_undo`.
3. **A stored move whose session no longer exists** (settings changed `run_days` or `strength_days`) is
   ignored, not a crash. Task 2 test: `test_stale_move_ignored`.
4. **A stale or forged form** (a date with no session, a bad session name, a past date) redirects with a
   message and stores nothing. Task 4 test: `test_move_rejects_bad_requests`.
5. **The user runs anyway on a skipped day:** the synced km still count in the week's actual total. Task 3 test:
   `test_run_on_skipped_day_still_counts`.

---

### Task 1: Storage for moves and skips

**Files:**
- Modify: `app/db.py`
- Test: `tests/test_db_moves.py`

**Interfaces:**
- **Produces:**
  - Table `moves`: `date` TEXT (original planned date), `session` TEXT (`"run"`, `"A"` or `"B"`),
    `new_date` TEXT NULL (NULL means skipped), `created` TEXT. PRIMARY KEY (`date`, `session`).
  - `save_move(day: str, session: str, new_date: str | None) -> None` (INSERT OR REPLACE).
  - `delete_move(day: str, session: str) -> None`.
  - `moves() -> list[dict]`.

- [ ] **Step 1: Write failing tests:**
  - `test_move_roundtrip`: `save_move("2026-10-22", "A", "2026-10-23")` → `moves()` has one row with that
    `new_date`.
  - `test_skip_is_null`: `save_move(..., None)` → `new_date is None`.
  - `test_move_twice_keeps_original`: saving `("2026-10-22", "A")` with `"2026-10-23"` then `"2026-10-24"`
    leaves one row, `new_date == "2026-10-24"`.
  - `test_delete_move`.
- [ ] **Step 2:** Run `pytest tests/test_db_moves.py -q`. Expected: FAIL (`no such table` / attribute error).
- [ ] **Step 3:** Implement in `app/db.py` (table in `init()`'s script; same style as `save_check`).
- [ ] **Step 4:** Run `pytest -q`. Expected: all pass. Add `"moves"` to `TABLES` in
  `tests/test_strength_view.py` so its `_clear()` empties it.
- [ ] **Step 5:** Commit: "Moves table".

### Task 2: Pure move logic (`app/moves.py`)

**Files:**
- Create: `app/moves.py`
- Test: `tests/test_moves.py`

**Interfaces:**
- **Consumes:** `db.moves()` rows (Task 1); week dicts from `plan.generate`, each with `start`, `workouts`
  (dicts with `date`, `type`, `km`, maybe `steps`) and, after `main.attach_strength`, `strength` (dicts with
  `key`, `date`).
- **Produces:**
  - `index(rows) -> dict[tuple[date, str], date | None]`: `(original date, session) → new date or None`.
  - `shift(item: dict, session: str, moved: dict) -> None`: if `(item["date"], session)` is in `moved`, sets
    `item["moved_from"] = original date` and `item["date"] = new date`, or `item["skipped"] = True` (date
    unchanged). Every item also gets `item["orig_date"]` (its planned date) so Undo can name it.
  - `relocate(weeks) -> None`: any workout or strength session whose `date` is past its week's last day is moved
    into the list of the week that contains its new date (appended, then that list re-sorted by date). Items
    with no containing week stay put (the routes prevent that case).
  - `day_items(weeks, day: date) -> list[tuple[str, dict]]`: non-skipped `("run", workout)` and
    `(key, strength session)` pairs dated `day`.
  - `clash(weeks, session: str, day: date) -> dict | None`: the first item on `day + 1` that blocks moving
    `session` there, per the Global Constraints' clash rules (ignoring the item being moved itself), else None.
  - `can_move(day: date, weeks, race: date) -> bool`: `day + 1 < race` and `day + 1` ≤ the last week's last
    day.
  - `session_name(session: str, item: dict) -> str`: e.g. "easy run", "long run", "speed session",
    "Strength A", for the warning copy.

- [ ] **Step 1: Write failing tests** (build weeks with `generate(load_settings(), D0)` and
  `D0 = date(2026, 10, 19)`; attach a minimal `strength` list `[{"key": "B", "date": tue}, {"key": "A", "date": thu}]`
  where a test needs it):
  - `test_shift_moves_and_marks`: a `("2026-10-24", "run")` move to the 25th sets `date == 25 Oct`,
    `moved_from == 24 Oct`.
  - `test_shift_skip`: `skipped is True`, date unchanged.
  - `test_stale_move_ignored`: a move for a date with no run leaves every workout unchanged.
  - `test_relocate_sunday_into_monday`: week 1's Sunday long run moved to Monday 26 Oct ends up in week 2's
    `workouts`, not week 1's.
  - `test_clash_rules`: run onto Sunday (long) → clash; run onto a speed-session day → clash; strength A onto an
    easy-run day → None; strength B onto the quality day → clash; strength B onto A's day → clash; run onto a
    strength-only day → None.
  - `test_can_move_stops_before_race`: false for the day before race day and for the plan's last day.
- [ ] **Step 2:** Run `pytest tests/test_moves.py -q`. Expected: FAIL (`ModuleNotFoundError`).
- [ ] **Step 3:** Implement `app/moves.py`.
- [ ] **Step 4:** Run `pytest -q`. Expected: all pass.
- [ ] **Step 5:** Commit: "Pure move, skip and clash logic".

### Task 3: Apply moves in the view

**Files:**
- Modify: `app/main.py` (`build_view`, `attach_strength`, `dashboard`, `workout_fit`), `app/garmin.py`
  (`week_zip` file names)
- Test: `tests/test_moves_view.py`

**Interfaces:**
- **Consumes:** Tasks 1 and 2.
- **Produces:** after `build_view()`:
  - Each workout and strength session may carry `moved_from`, `skipped`, `orig_date`.
  - Runs are scaled by their **own** week's factor before moving. Order in `build_view`: scale every week's
    workouts → `shift` runs → `relocate` runs → join actuals and reviews → totals → `attach_strength` (which
    `shift`s its sessions before looking up logs, so logs match the new date) → `relocate` strength.
  - **Actual join is per day:** when a day has two planned runs, each shows the day's actual km, compliance
    is the day's actual against the day's combined planned km, and `review` attaches only to the longer planned
    run. Skipped workouts get no `actual_km`, `compliance`, `review` or `.fit` link; the day's actual still adds
    to `w["actual_km"]`.
  - `w["target_km"]` excludes skipped workouts, so the profile's planned bar does too.
  - `next_run` skips skipped workouts; `strength_today` is found across all weeks (so a session relocated into
    this week is found) and skips skipped sessions.
  - `GET /workout/{day}.fit?n=0`: `n` picks among the non-skipped runs on that day (default 0). `week_zip`
    gives duplicate file names a `-2` suffix.

- [ ] **Step 1: Write failing tests** (`client` fixture and `on(monkeypatch, day)` as in
  `tests/test_strength_view.py`; insert facts with `db.save_move`):
  - `test_moved_strength_is_tomorrows_card`: today Fri 23 Oct, a move `("2026-10-22", "A") → 23rd`: the
    dashboard's `strength_session["key"] == "A"` and its `date` is the 23rd. A log POSTed for the 23rd shows as
    `ex["log"]` on that session.
  - `test_morning_check_follows_move`: with that log, on Sat 24 Oct `morning_check` is True.
  - `test_skipped_run_out_of_target`: skipping Sat 24 Oct (4.5 km) drops week 1 `target_km` from 25 to 20.5 and
    `next_run` on the 24th is Sunday's run.
  - `test_run_on_skipped_day_still_counts`: insert a 4.5 km activity on the skipped 24th → week `actual_km`
    includes it; the skipped workout has `compliance is None`.
  - `test_two_runs_one_day_share_actuals`: move Saturday's run onto Sunday (Move anyway), insert a 14 km
    activity on Sunday → both workouts show `actual_km == 14`; compliance is `round(100 * 14 / 14.5)`; only
    the 10 km run has `review` set (when details exist) — assert at least that the 4.5 km one has
    `review is None`.
  - `test_fit_route_picks_nth_run`: with two runs on Sunday, `/workout/2026-10-25.fit?n=1` returns 200 and a
    different body from `n=0`; `week_zip` names are unique.
  - `test_moved_run_keeps_own_factor`: with a week-1 check-in of pain 5 (factor 0.8 for week 2), week 1's
    Sunday run moved to Monday keeps its unscaled km.
- [ ] **Step 2:** Run them. Expected: FAIL.
- [ ] **Step 3:** Implement.
- [ ] **Step 4:** Run `pytest -q`. Expected: all pass.
- [ ] **Step 5:** Commit: "Moves and skips applied to the plan view".

### Task 4: Buttons, the clash warning, and the routes

**Files:**
- Modify: `app/main.py` (routes, dashboard context), `app/templates/index.html`, `app/templates/_strength.html`
- Test: `tests/test_moves_view.py`

**Interfaces:**
- **Consumes:** Tasks 2 and 3.
- **Produces:**
  - `POST /move`: form `date` (the session's current date), `session` (`run`, `A` or `B`), `confirm` (``,
    `move` or `skip`). Rebuilds the view, finds the session by current date and identity, and:
    - refuses (303 to `/` with a `msg`) when the date is before today, no such session exists, it's already
      done (a run with `actual_km` or a strength session with any log), or `can_move` is false;
    - with no `confirm` and a `clash`: 303 to `/?confirm=<session>&on=<date>#move`, storing nothing;
    - `confirm=skip`: `save_move(orig, session, None)`;
    - otherwise: `save_move(orig, session, (date + 1 day))`, where `orig` is the session's `orig_date`.
    - Redirect anchor `#week` (or `#strength` for strength).
  - `POST /move/undo`: form `date` (the original date), `session` → `delete_move`.
  - The dashboard reads `confirm`/`on` query params and passes `move_warning = {"session", "date", "name",
    "blocker", "blocker_day"}` when that clash still holds.
  - **Template:**
    - **Warning panel** (`id="move"`), top of the page under any `msg`. Copy:
      "<Blocker day> already has your <blocker name>. Better to skip <day>'s <session name> than stack them."
      Two buttons as forms: **Skip it** (`confirm=skip`) and **Move anyway** (`confirm=move`), plus a quiet
      "Keep it on <day>" link back to `/`.
    - **Move to tomorrow** as a quiet button form on the run hero and the strength card header, and as a small
      link-styled button in each week-table row dated today or later, whenever the move is allowed.
    - A moved item shows "Moved from <Thursday>" and a skipped one "Skipped", each with an **Undo** button
      form.
    - The week table's strength line ("Strength on …") uses the moved dates.

- [ ] **Step 1: Write failing tests:**
  - `test_move_strength_no_clash`: on Thu 22 Oct, POST `/move` `date=2026-10-22, session=A` → 303; the stored
    row is `("2026-10-22", "A", "2026-10-23")`.
  - `test_move_run_onto_long_run_warns`: on Sat 24 Oct, POST `session=run, date=2026-10-24` → 303 to a location
    containing `confirm=run`; no row stored. Then GET that location: the page contains "Sunday already has your"
    and "Better to skip Saturday".
  - `test_skip_and_move_anyway`: POST with `confirm=skip` stores `new_date None`; with `confirm=move` stores the
    25th.
  - `test_move_twice_then_undo`: on Thu, move A (→ Fri), then on Fri move it again (→ Sat), then POST
    `/move/undo` with `date=2026-10-22, session=A` → no rows; A is back on Thursday.
  - `test_move_rejects_bad_requests`: a past date, `session=X`, a date with no run, and the day before race day
    each give 303 with a `msg` and store nothing.
  - `test_no_move_button_once_done`: with a log for A on Thursday, the Thursday page has no
    `action="/move"` form for A; POSTing it anyway stores nothing.
  - `test_buttons_render`: on Thu 22 Oct the page contains `Move to tomorrow`; after the move, Friday's page
    contains "Moved from Thursday" and an `action="/move/undo"` form.
  - `test_pages_200` still passes.
- [ ] **Step 2:** Run them. Expected: FAIL.
- [ ] **Step 3:** Implement the routes and templates, with minimal CSS in `index.html`'s `head` block.
- [ ] **Step 4:** Run `pytest -q`. Expected: all pass.
- [ ] **Step 5:** Preview at 390 px, light and dark (the scratchpad preview approach from the strength plan):
  the Thursday strength card with its button, the warning panel, and a week table with a moved and a skipped
  row. Fix whatever reads badly.
- [ ] **Step 6:** Commit: "Move to tomorrow, clash warning, skip and undo".

### Task 5: Docs and ship

**Files:**
- Modify: `README.md` (a short "Moving a session" paragraph for the runner), `CLAUDE.md` (`app/moves.py`, the
  `moves` table, the `build_view` order, the routes)

- [ ] **Step 1:** Update the docs.
- [ ] **Step 2:** Run `pytest -q` and the generator one-liner; walk the spec's "How to check it" list.
- [ ] **Step 3:** Commit, push the branch, and open a PR.
- [ ] **Step 4:** After the user merges, `fly deploy --ha=false` and confirm the machine runs the new version.
