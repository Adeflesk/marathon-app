# Weekly Scorecard Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Each completed week gets a scorecard. It has a verdict on whether the week went in the right direction, one row per signal with an up, flat or down arrow, and the weakest areas named. It shows on Progress and on This week.

**Architecture:** A new pure module, `app/scorecard.py`, builds the rows, verdict and weakest areas for one week from the weeks `build_view()` already returns. `progress.summaries()` attaches one card to each summary, so Progress and This week (`view.last_summary`) get it with no new storage. `review.py` gains two fields the rows need.

**Tech Stack:** Python 3, FastAPI, Jinja2, SQLite, pytest.

**Spec:** `docs/superpowers/specs/2026-11-22-weekly-scorecard-design.md`

## Global Constraints

- The scorecard never changes the plan. No trims, buttons or POSTs.
- No new tables, no new Garmin calls, nothing stored. The card is recomputed per request.
- Pure functions only in `app/scorecard.py`, with no `db` import.
- Arrows are `"up"`, `"flat"`, `"down"` or `None` (shown as a dash). A `None` row is never counted.
- Each scored week is compared with the **4 completed weeks before it** (fewer near the start).
- Thresholds are named module constants.
- Units are bpm, %, steps/min and km, formatted at display time. Row texts use `progress._pace` for paces.
- The page shows a text arrow (↑ → ↓ –) as well as colour, with an accessible label on each row.
- Strength days are not hardcoded. Use the week's `strength` items.

## Review Focus

1. **Week 1 and 2:** most rows have nothing to compare with, so the verdict must be "Too early to say", never "Right direction" from target rows alone. Tested in Task 3 (`test_week_one_is_too_early`).
2. **A week not synced:** Plan done is a dash, not "down", and no running row reads "down" just because runs are missing. Tested in Task 1 (`test_plan_done_dash_when_not_synced`).
3. **No check-in for the week:** How it felt is a dash, and the verdict still forms from the other rows. Tested in Task 3 (`test_no_checkin_still_gives_verdict`).
4. **Skipped strength sessions:** they don't count as missed, and a week with no strength sessions shows a dash. Tested in Task 2 (`test_strength_done_ignores_skipped`).
5. **The ankle stage before the plan starts:** in weeks 1–4, "4 weeks before" falls before the plan. Compare with the stage the day before plan start, not crash or read as down. Tested in Task 2 (`test_stages_early_weeks_compare_with_plan_start`).

---

### Task 1: Review fields and the running rows

**Files:**
- Modify: `app/review.py` (`review()`: the MP-finish branch and the `form_note` line)
- Create: `app/scorecard.py`
- Test: `tests/test_review.py`, `tests/test_scorecard.py` (new; reuse `ran`, `lifted`, `week_one` and the `clean` fixture pattern from `tests/test_summaries.py` by importing them, `from tests.test_summaries import ...`)

**Interfaces:**
- Produces in `review()`: `out["mp_on"]: bool | None`. True or False on a long run with an MP finish (the existing `abs(diff) <= ON_PACE_S` test), None otherwise. Also `out["form"]: bool`, True when `form_note()` returned a non-empty note.
- Produces `Row = {"key": str, "group": "running" | "strength", "arrow": "up" | "flat" | "down" | None, "text": str, "past": bool}`. `past` is True for rows that compare with past weeks (counted by "too early").
- Produces `running_rows(weeks: list[dict], i: int, s: dict, ref_pace: float) -> list[Row]`, where `i` is the scored week's index in `weeks`. Keys in order: `fitness`, `long`, `plan`, `mp`, `form`, `feel`. `past` is True for `fitness`, `long`, `form` and `feel`.
- Constants: `WINDOW = 4`, `FIT_BPM = 2`, `PLAN_UP = 0.95` (and `progress.PLAN_OK` = 0.8 for the flat floor), `FEEL_STEP = 1`, `FEEL_LOW = 2`, `PRIOR_MIN = 2`.

Rules (from the spec's Running table):
- **fitness:** `progress.fitness_trend(weeks, ref_pace)`, this week's `hr` against the median of the prior `WINDOW` weeks' non-None `hr` (needs ≥ `PRIOR_MIN`). Lower by ≥ 2 is up, higher by ≥ 2 is down.
- **long:** the week's entry in `progress.long_runs(weeks)`. A None drift is a dash. Drift ≥ `progress.DRIFT_WARN` is down. Up when its km beats every earlier long run's km. Otherwise flat.
- **plan:** a dash unless `w["synced"]`. Share = actual/target: ≥ 0.95 is up, ≥ 0.8 is flat, else down.
- **mp:** the week's long run `review["mp_on"]`, plus any workout with `steps` of type `specific` or `mp` that has `review["reps"]`, which is on when all reps are `"on"`. Down if any check is off, up if all are on, a dash with none.
- **form:** down if any easy or long run that week has `review["form"]`. Otherwise `progress.cadence_reading(progress.cadence_trend(weeks[:i+1], ref_pace))`: rising is up, falling is down, steady is flat, None is a dash.
- **feel:** the week's `checkin["feel"]`. With no check-in, a dash. Feel ≤ 2 is down. Against the mean of the prior `WINDOW` weeks' feels (needs ≥ 2): ≥ 1 lower is down, ≥ 1 higher is up, else flat. With fewer than 2 prior feels and feel > 2, a dash.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_review.py
def test_long_run_mp_finish_sets_mp_on(): ...      # on pace → out["mp_on"] is True; 30 s/km slow → False
def test_easy_run_has_no_mp_on(): ...              # out["mp_on"] is None
def test_form_flag_follows_form_note(): ...        # cadence falls 6 steps/min late → out["form"] True; steady → False

# tests/test_scorecard.py
def test_fitness_up_when_heart_rate_drops(monkeypatch):
    # weeks 1–3 easy at 150 bpm, week 4 at 146 → running_rows(..., i=3)["fitness"].arrow == "up"
def test_fitness_dash_with_one_prior_week(monkeypatch): ...       # arrow is None
def test_long_run_down_on_drift(monkeypatch): ...                 # drift_hr so drift ≥ 5% → "down"
def test_long_run_up_when_longest_and_steady(monkeypatch): ...
def test_plan_done_dash_when_not_synced(monkeypatch): ...         # no last_sync covering the week → None
def test_plan_done_thresholds(monkeypatch): ...                   # 96% up, 85% flat, 70% down
def test_feel_down_at_two_or_below(monkeypatch): ...              # check-in feel 2 → "down" even with no prior weeks
def test_feel_against_prior_weeks(monkeypatch): ...               # 4,4,4 then 3 → "down"; then 5 → "up"
def test_mp_dash_without_mp_work(monkeypatch): ...
```

Each scorecard test builds runs with the `ran()` helper, sets `main.today`, takes `s, weeks = main.build_view()`, and asserts on `{r["key"]: r for r in running_rows(weeks, i, s, s["paces"]["easy"])}`.

- [ ] **Step 2: Run and see them fail**

Run: `pytest tests/test_review.py tests/test_scorecard.py -q`
Expected: FAIL. `KeyError: 'mp_on'` and `ModuleNotFoundError: app.scorecard`.

- [ ] **Step 3: Add the two review fields, then `running_rows()` in `app/scorecard.py`**

Row `text` is one short phrase with its number, such as "heart rate at easy pace 146, 150 before", "drift 6%", "92% of planned km" or "rated 2 of 5". The exact wording is the builder's call.

- [ ] **Step 4: Run and see them pass, then the full suite**

Run: `pytest -q`
Expected: all pass, with the new tests included.

- [ ] **Step 5: Commit**

```bash
git add app/review.py app/scorecard.py tests/test_review.py tests/test_scorecard.py
git commit -m "Scorecard running rows: fitness, long run, plan, MP, form and feel against the last 4 weeks"
```

### Task 2: Strength and ankle rows

**Files:**
- Modify: `app/scorecard.py`
- Test: `tests/test_scorecard.py`

**Interfaces:**
- Consumes: `Row` from Task 1; `st = weeks[0]["ankle_state"]` (keys `logs`, `checks`, `tests`, `snacks`, `checkins`, `by_ex`); `ankle.hop_stage`, `ankle.balance_stage`, `ankle._triggers`, `ankle.test_weeks`; `progress.ankle_table`, `progress.SNACK_DAYS`, `progress._in`.
- Produces: `strength_rows(weeks: list[dict], i: int, st: dict) -> list[Row]`. Keys in order: `sessions`, `loads`, `stages`, `ankle`, `snacks`. `past` is True for `loads` and `stages` only. Constant: `SNACK_LOW = 2`.

Rules (from the spec's Strength and ankle table):
- **sessions:** the week's `strength` items not `skipped`. None of them gives a dash. All done is up, fewer than half is down, else flat.
- **loads:** for each exercise in `st["by_ex"]` (newest first), take the latest log dated on or before the week's end and the latest on or before end − 28 days. Each needs a `weight_kg` or a `rung`. Compare `(weight_kg or 0, rung or 0)` and count ups and downs. With no pairs, a dash. In a week where `w["cutback"]` is set or the phase is `"Taper"` or `"Race week"`, an exercise that was held counts as up.
- **stages:** `hop_stage(end, …)` and `balance_stage(end, …)` against the same at the comparison day. The comparison day is end − 28, but never before the day before `weeks[0]["start"]`. Treat a `None` hop stage as −1. Down if either went lower, up if either went higher and neither went lower, else flat.
- **ankle:** down when any `ankle._triggers(...)` date falls in the week. Otherwise, in a test week (`ankle.test_weeks`), up when this week's `ankle_table` column meets more targets than the previous column. Else flat. Always `past=False`.
- **snacks:** distinct snack days in the week. At least `SNACK_DAYS` is up, fewer than 2 is down, else flat.

- [ ] **Step 1: Write the failing tests**

```python
def test_strength_done_all_up(monkeypatch): ...
def test_strength_done_ignores_skipped(monkeypatch): ...        # one done, one skipped → "up"; none at all → None
def test_loads_up_when_weight_rises(monkeypatch): ...           # box_squat 40 kg week 1, 45 kg week 5 → "up"
def test_loads_held_counts_up_in_cutback(monkeypatch): ...      # same weight, scored week is a cutback → "up"
def test_stages_down_when_hop_steps_back(monkeypatch): ...      # worse morning check drops the hop stage → "down"
def test_stages_early_weeks_compare_with_plan_start(monkeypatch): ...  # week 2, no crash, arrow "flat" or "up"
def test_ankle_down_on_trigger_in_week(monkeypatch): ...        # db.save_check(day, True) inside the week → "down"
def test_snacks_thresholds(monkeypatch): ...                    # 4 days up, 2 flat, 1 down
```

- [ ] **Step 2: Run and see them fail**

Run: `pytest tests/test_scorecard.py -q`
Expected: FAIL. `strength_rows` is not defined.

- [ ] **Step 3: Implement `strength_rows()`**

- [ ] **Step 4: Run the full suite**

Run: `pytest -q`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add app/scorecard.py tests/test_scorecard.py
git commit -m "Scorecard strength and ankle rows: sessions, loads, stages, ankle and snacks"
```

### Task 3: Verdict, weakest areas and the card on each summary

**Files:**
- Modify: `app/scorecard.py`, `app/progress.py` (`summaries()`, `_summary()`), `app/main.py` (progress route), `app/view.py` (`last_summary` and its caller in `dashboard()`)
- Test: `tests/test_scorecard.py`, `tests/test_summaries.py`

**Interfaces:**
- Consumes: `running_rows`, `strength_rows`.
- Produces:
  - `verdict(rows: list[Row], fitness_before: str | None) -> dict` with keys `state` (one of `"ankle"`, `"disagree"`, `"early"`, `"off"` or `"right"`) and `text`. `fitness_before` is the previous week's fitness arrow.
  - `weakest(rows: list[Row]) -> list[str]`: one to two sentences.
  - `card(weeks: list[dict], i: int, s: dict, st: dict, ref_pace: float) -> dict` with keys `verdict`, `rows` and `weakest`.
  - `progress.summaries(weeks, s, st, results, t, ref_pace: float | None = None)`: each summary gains `"card"`. A None `ref_pace` means `s["paces"]["easy"]`.
- Constants: `EARLY_MIN = 3` and `ORDER = ("ankle", "feel", "fitness", "long", "plan", "stages", "loads", "form", "mp", "sessions", "snacks")`. Labels come from `LABELS = {"ankle": "Ankle", "feel": "How it felt", "fitness": "Fitness", "long": "Long run", "plan": "Plan done", "stages": "Hops and balance", "loads": "Strength loads", "form": "Late-run form", "mp": "Marathon pace", "sessions": "Strength done", "snacks": "Snacks"}`.

The verdict, first match wins:
1. `ankle` is down: `"ankle"`, with text "Ankle first: not the right direction."
2. Work out `off`: two or more running rows other than `feel` are down, or fitness is down and `fitness_before` is down.
3. `feel` is down and not `off`: `"disagree"`, with text "The numbers and how you felt disagree: {k} of {n} improving or holding, but you rated the week {feel} of 5."
4. Fewer than `EARLY_MIN` rows with `past` have arrows: `"early"`, with text "Too early to say: not enough weeks to compare yet."
5. `off`: `"off"`, with text "Not the right direction: {labels of the down rows, joined with "and"} down."
6. Otherwise `"right"`, with text "Right direction: {k} of {n} improving or holding."

In these texts, k is the number of up or flat rows and n is the number of rows with arrows. Feel is read from the row (the builder carries the number in the row or reads the check-in).

`weakest()`:
- The down rows in `ORDER`, at most 2, each as "{label}: {text}."
- If none is down: the first flat row in `ORDER`, as "Holding, not yet improving: {label} ({text})."
- If nothing is down or flat: "Nothing weak this week."

Wiring:
- `main.py`'s progress route passes its `ref_pace` to `summaries`.
- `view.last_summary` passes the settings' easy pace from the loaded facts, the same value `main.py` reads with `load_settings()["paces"]["easy"]`. That way This week and Progress show the same card.

- [ ] **Step 1: Write the failing tests**

```python
def row(key, arrow, group="running", past=True, text="x"): ...  # local helper building a Row
def test_ankle_down_overrides_everything():
    rows = [row("ankle", "down", "strength", False), row("fitness", "up"), row("long", "up"), row("feel", "up")]
    assert verdict(rows, None)["state"] == "ankle"
def test_feel_down_with_good_numbers_disagrees():
    rows = [row("fitness", "up"), row("long", "flat"), row("form", "up"), row("feel", "down", text="rated 2 of 5")]
    v = verdict(rows, None); assert v["state"] == "disagree" and "2 of 5" in v["text"]
def test_feel_down_early_still_disagrees(): ...   # only feel has a past arrow → "disagree", not "early"
def test_two_running_rows_down_is_off(): ...
def test_fitness_down_two_weeks_is_off(): ...     # fitness down, fitness_before "down" → "off"; fitness_before None → not off
def test_target_rows_alone_are_too_early():
    rows = [row("plan", "up", past=False), row("sessions", "up", "strength", False),
            row("snacks", "up", "strength", False), row("ankle", "flat", "strength", False)]
    assert verdict(rows, None)["state"] == "early"
def test_right_direction_counts_only_arrows(): ...  # 3 up, 1 flat, 2 None → "4 of 4"
def test_weakest_orders_and_caps_at_two(): ...      # snacks, fitness and ankle down → ankle then fitness
def test_weakest_holding_when_nothing_down(): ...
def test_stage_down_is_weak_spot_not_ankle_verdict(): ...  # stages down, ankle flat, else good → state "right", weakest names Hops and balance
def test_week_one_is_too_early(monkeypatch): ...    # tests/test_summaries.py: week_one(), summaries(...)[0]["card"]["verdict"]["state"] == "early"
def test_no_checkin_still_gives_verdict(monkeypatch): ...  # 6 weeks of runs, no check-ins → state is "right" or "off", feel row None
```

- [ ] **Step 2: Run and see them fail**

Run: `pytest tests/test_scorecard.py tests/test_summaries.py -q`
Expected: FAIL. `verdict` is not defined and `KeyError: 'card'`.

- [ ] **Step 3: Implement `verdict`, `weakest` and `card`, then wire `summaries`, `main` and `view`**

- [ ] **Step 4: Run the full suite**

Run: `pytest -q`
Expected: all pass, including the existing `test_summaries.py` and `test_progress_page.py` tests.

- [ ] **Step 5: Commit**

```bash
git add app/scorecard.py app/progress.py app/main.py app/view.py tests/test_scorecard.py tests/test_summaries.py
git commit -m "Scorecard verdict and weakest areas on every weekly summary"
```

### Task 4: Pages and docs

**Files:**
- Modify: `app/templates/progress.html` (the `summaries` section), `app/templates/index.html` (the `last_summary` card), `README.md`, `CLAUDE.md`
- Test: `tests/test_progress_page.py`

**Interfaces:**
- Consumes: `summary["card"]` from Task 3.

Page:
- **Progress:** each week's `<details>` gets `id="week-{{ x.week }}"`. Its `<summary>` line ends with the verdict state's short name: "Right direction", "Mixed feelings" for disagree, "Too early", "Ankle first" or "Not the right direction".
- **Inside the card, in order:**
  - the verdict text,
  - a list of rows grouped "Running" then "Strength and ankle", each as `<li class="up|flat|down|none" aria-label="{label}: {improving|holding|falling|not enough data}, {text}">`. The glyph is ↑, →, ↓ or – in a `span aria-hidden="true"`.
  - the weakest sentences under "Weakest",
  - the existing fact sentences,
  - "Next week:".
- **Colours:** use the page's existing `--good`, `--warn` and `--mute`. Up and flat share good, and down uses warn.
- **This week's card:** keeps its heading. It shows the verdict text and the weakest sentences instead of the fact sentences, then "This week: {next}", then a link to `/progress#week-{n}`.

- [ ] **Step 1: Write the failing tests**

```python
def test_progress_shows_scorecard_rows(client, monkeypatch): ...
    # a completed week: page contains 'id="week-1"', 'aria-label="Fitness:', "Weakest", the verdict text
def test_this_week_shows_verdict_and_link(client, monkeypatch): ...
    # Monday after week 1: "/progress#week-1" and the verdict text present, the first fact sentence absent
```

- [ ] **Step 2: Run and see them fail**

Run: `pytest tests/test_progress_page.py -q`
Expected: FAIL on the missing markup.

- [ ] **Step 3: Update both templates**

- [ ] **Step 4: Update the docs**

- **README:** a "Weekly scorecard" section in plain words. Cover what the arrows compare with, the verdict rules in order, and that your feel can't be overruled by the numbers. Say that a hop or balance stage stepping back is a weak spot, not an ankle verdict. Say that early weeks read "Too early to say". Replace the README's description of the Sunday summary's contents where it conflicts.
- **CLAUDE.md:** add `app/scorecard.py` to Architecture, covering `running_rows`, `strength_rows`, `verdict`, `weakest` and `card`, the row keys and the verdict order. Note `summaries(..., ref_pace)` and the `card` key. Add the `mp_on` and `form` fields to the `review.py` entry.
- **`docs/roadmap.md`:** tick the weekly review under item 1 with the date.

- [ ] **Step 5: Run the full suite, then render the page once**

Run: `pytest -q`
Expected: all pass.
Then run `uvicorn app.main:app` against a local DB with a few weeks of data, open `/progress` and `/` on a Monday (`main.today` patched or a real Monday), and read one card end to end.

- [ ] **Step 6: Commit**

```bash
git add app/templates/progress.html app/templates/index.html README.md CLAUDE.md docs/roadmap.md tests/test_progress_page.py
git commit -m "Weekly scorecard on Progress and This week; docs"
```
