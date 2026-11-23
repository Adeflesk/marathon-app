# Weekly scorecard — design

22 Nov 2026. Replaces the Sunday summary with a scorecard that says whether the week went in the right direction.

## Why

The Sunday summary on Progress says what happened: km run, sessions done, check-in, snacks. It doesn't say what the
user wants to know after reading it: **"was it in the right direction?"** For the user, the right direction means
two things: **on course for the Barcelona goal time, and the ankle not going backwards.** The review should also
say **where they need to strengthen**, in the running and in the gym and ankle work.

**Their own feel comes first.** The verdict the user would distrust is one that says "right direction" when they
feel their fitness isn't going the right way. The numbers must never overrule how the week felt.

This also replaces the earlier idea of a weekly review run by Claude from a production data export (from the
11/14 insights report). The app already holds every fact it needs, so it can work the scorecard out on each
request like everything else. That means no fly ssh, no export and no scheduled job.

## Goals

1. Each completed week gets a **scorecard** (shape "B", chosen from three mockups):
   - an overall verdict at the top,
   - one row per signal, each with an arrow (up, flat or down) against the last 4 weeks and the number behind it,
   - the weakest one or two areas named in plain words,
   - the existing one-line focus for next week.
2. The signals cover **running** and **strength and ankle**, all from data the app already stores.
3. **How the week felt** is a row of its own, from the check-in's existing 1–5 feel. **No new check-in question**
   (the user's choice).
4. The verdict can't say "right direction" when the ankle is going backwards, or when the user's feel says
   otherwise.
5. Past weeks keep their scorecards on Progress, as the summaries do now.

## Non-goals and anti-goals

- **It never changes the plan.** No trims, no buttons. It only informs.
- **No verdict without data.** A signal without enough history shows a dash, not an arrow, and isn't counted.
  Early weeks are mostly dashes, and that's correct.
- **No hiding the feel.** If the numbers are good and the feel is poor, the scorecard says the two disagree. It
  never picks the numbers.
- No new data, no new Garmin calls, no new tables. A week's scorecard is recomputed per request like the plan, so
  a late sync or an edited check-in reshapes it.
- No stored scorecards. Nothing is frozen at the end of the week.
- No AI-written text. Fixed rules and fixed sentences, tested like `summaries()`.

## Where it shows

- **Progress, "Weekly summaries" section:** each week's card becomes a scorecard, newest first, collapsible as
  now. The summary's existing fact sentences (km, runs, long run, fuel, strength, snacks, check-in, results, goal
  changes, held weeks) stay inside the card under the rows, so nothing is lost. *(My call.)*
- **This week:** `last_summary` (the latest completed week, on the dashboard) shows that week's verdict line and
  the weakest areas, with a link to the full card on Progress. *(My call.)*

## The signals

Each signal compares the week being scored with the **4 completed weeks before it** (fewer at the start; at least
the number given). Each gives `up`, `flat`, `down` or `None` (dash), plus a short text with the number. The
thresholds are named constants. All of these are my calls, settled with the user's agreement in principle
("all good"); the exact numbers are the builder's to tune within them.

### Running

| Row | Source | Arrow |
|---|---|---|
| **Fitness** | `fitness_trend`: heart rate at easy pace | This week against the median of the prior weeks with a value (needs ≥ 2). Up when ≥ 2 bpm lower, down when ≥ 2 bpm higher, else flat. |
| **Long run** | `long_runs`: the week's long run drift | Down when drift ≥ `DRIFT_WARN`. Up when under it and the run is the longest yet. Else flat. Dash when the week's long run has no drift. |
| **Plan done** | the week's `actual_km` / `target_km` | Up ≥ 95%, flat 80–95% (`PLAN_OK`), down < 80%. Dash when the week isn't `synced`. Not against prior weeks: the plan already ramps. |
| **Marathon pace** | the long run's MP finish check, or an MP session's reps | Only in weeks that have one. Up when on pace, down when off, dash otherwise. |
| **Late-run form** | the week's `form_note`s; `cadence_trend` | Down when any easy or long run that week has a form note. Otherwise the cadence reading: rising is up, falling is down, steady is flat. Dash without cadence data. |
| **How it felt** | check-in `feel` (1–5) | Against the average of prior check-ins (needs ≥ 2): down when ≥ 1 lower, up when ≥ 1 higher, else flat. Down whenever feel ≤ 2. Dash with no check-in. |

### Strength and ankle

| Row | Source | Arrow |
|---|---|---|
| **Strength done** | the week's strength sessions, not skipped | Up when all were done, down when fewer than half, else flat. |
| **Strength loads** | `strength_logs` working weight (or rung) per exercise | Compare each exercise's latest weight with its weight 4 weeks before. Up when more went up than down, down when more went down, else flat. In cutback and taper weeks, held loads count as up (held is the plan). |
| **Hops and balance** | `hop_stage`, `balance_stage` | Against 4 weeks before: up when either stage advanced and neither stepped back, down when either stepped back, else flat. |
| **Ankle** | flag, ankle pain on logs, morning checks, weekly check-in pain, tests | Down when an ankle trigger fell in the week (`ankle._triggers`, as the summary's first rule). Up in a test week when the tests met more targets than last time (`ankle_table`). Else flat. |
| **Snacks** | snack days | Up ≥ `SNACK_DAYS` (4), down < 2, else flat. |

## The verdict

Checked in this order; the first that applies wins:

1. **"Ankle first: not the right direction."** The Ankle row is down. This overrides everything (the user's
   second meaning of "right direction"). A hop or balance stage stepping back without an ankle trigger that week
   does **not** fire this rule. It shows as a down row and is named among the weakest areas (the user's answer).
2. **"The numbers and how you felt disagree."** How it felt is down, while rule 5 would otherwise say right
   direction. The line names both, for example "The numbers are heading the right way, but you rated the week 2 of
   5." This is the user's anti-goal: the numbers must not overrule the feel.
3. **"Too early to say."** Fewer than 3 of the rows that compare with past weeks have arrows. Those rows are
   Fitness, Long run, Late-run form, How it felt, Strength loads, and Hops and balance. Rows judged against fixed
   targets (Plan done, Strength done, Snacks, and Ankle when flat) don't count towards the 3, so week 1 can't read
   "right direction" from targets alone. This comes after rules 1 and 2, so an ankle problem or a poor feel is
   never hidden behind "too early". *(My call, from the builder check.)*
4. **"Not the right direction."** Two or more running rows are down (How it felt doesn't count here, because
   rule 2 handles it), or Fitness is down two weeks running. A week with a dash doesn't count as down.
   *(My call.)*
5. **"Right direction."** Every other case, with a count like "7 of 9 improving or holding". The count only
   includes rows with arrows.

## The weakest areas

- The down rows, at most two, in this order of importance: Ankle, How it felt, Fitness, Long run, Plan done,
  Hops and balance, Strength loads, Late-run form, Marathon pace, Strength done, Snacks.
- No down rows: the first flat row in the same order, worded "Holding, not yet improving: …".
- Nothing flat or down: "Nothing weak this week."
- Each is one plain sentence with its number, for example "Balance stage stuck at 3 for 4 weeks." or "Cadence
  fell from 178 to 172 steps/min late in Saturday's long run."

## Focus for next week

Unchanged: the summary's existing "Next week" rules (ankle trigger, held week, easy too quick, long-run drift,
snacks, strength missed, test week, then "Keep doing what you're doing").

## Constraints

- Pure: a function in `app/progress.py` (a `scorecard()` beside `summaries()`), from the built weeks, settings,
  ankle state and results. Tested without a database, like `summaries()`.
- Plan never stored; nothing new in `db.py`.
- Units as everywhere: bpm, %, steps/min, km; formatting at display time.
- The page styling follows Progress: the arrows use the existing good/warn/mute colours, with a text arrow (↑ → ↓)
  as well so it reads without colour. Each row has an accessible label.
- README (written for the user) explains the scorecard and the verdict rules in plain terms. CLAUDE.md gets the
  function and its rules.

## Left to the builder

- Exact copy beyond the sentences above.
- Exact threshold values within the rules above, as named constants.
- How "working weight 4 weeks before" is read from the logs: the nearest logged session at or before that day.
- Whether `_summary()` and `scorecard()` share one pass over the week or two.
