# Race preparation in the long runs — design

Date: 2026-10-31. Roadmap item 3 (`docs/roadmap.md`).

## Why

Marathons are usually lost on fuelling and pacing, not fitness. The user takes no fuel today (long runs have
been 65 minutes), has a strong stomach, and will practise with **Finisher gels**, the Barcelona course's
official gel, so the course gels in the second half hold no surprises. The goal (user): **race day holds no
surprises**: the same gels, the same timing, practised at marathon pace when it counts.

Barcelona's course (recent editions; nothing official for 2027 yet): drinks stations at km 5, 10, then every
2.5 km to 40 (14 in all), each with water and a sports drink; Finisher gels from about km 15 (reported around
km 15, 20, 25, 30, 35, 37.5); fruit later; sponges when warm.

## Goals

### 1. Fuelling notes on long runs (user agreed)

- A long run gets a fuelling note when its **expected time at long-run pace is 90 minutes or more**: week 5's
  14 km (about 1 h 31) is the first on the plan as written, then every long run except the cutbacks under
  90 minutes. (Claude's call: from week 5, a week earlier than the roadmap's "about week 8", because the rule is
  time-based.)
- **The schedule:** a Finisher gel at 45 minutes, then every 35 minutes, none in the last 10 minutes; drink
  water with each. So 2 gels at 91–114 minutes, 5 on the 32 km peak run (about 3 h 28: 45, 80, 115, 150,
  185). (Claude's call, a common 30–60 g carbohydrate an hour pattern for a 4-hour marathoner.)
- The note reads, for example: "Fuel practice: a Finisher gel at 45 and 80 min (2 gels), with water."
- **Marathon-pace finishes** (weeks 12, 14, 16, 18) add: "Take the gel before the marathon-pace part as on
  race day, and keep taking them at goal pace."
- Shown wherever the long run's note shows (hero on This week, week list, Plan page). Moved long runs keep
  their note. The plan's km and the watch files don't change.

### 2. "Fuelled as planned" (user agreed: a single tap, no stomach log)

- On a done long run that had a fuelling note, a **Fuelled as planned** button (an undo once ticked). A new
  `fuel_logs` table keyed by the run's date.
- The weekly summary adds "Fuelled as planned." or, when the long run had a note but no tick, "No fuel logged
  on the long run." The Progress page's Long runs section adds "Fuel practice: 3 of 4 long runs."
- No warning or "Next week" rule from it (Claude's call: it's practice, not a risk).

### 3. Race-day plan (user agreed)

A **Race day** page (`/race`), linked from This week from the first taper week (about four weeks out, time
to buy gels) and from the race row on the Plan page.

- **Pacing:** the target is the current marathon pace (`s["paces"]["marathon"]`, which already follows the
  goal and the latest result). The first 5 km 5 s/km easier, the rest a touch quicker (about 1 s/km) so the
  finish is unchanged: target time = marathon pace × 42.195. A table of 5 km splits with the clock time at
  each, plus the half and 30 km, and the finish time. (Claude's call: the trained marathon
  pace, not the bare goal, so the plan matches the training; the page names the goal beside it.)
- **Fuelling:** the same 45-then-every-35-minutes schedule over the race's expected time, with each gel
  turned into the km where it falls at race pace. Gels due before the first course gel station are
  **carried**; later ones are **taken from the course** at the **last gel station at or before** the km where
  they fall (a little early, never late; the next unused station if that one's taken). At 5:41/km (6 gels over about 4 hours) that's 2 carried, at about
  km 8 and 14, then course gels at km 20, 25, 30 and 37.5. (Claude's calls.) Water at every station; the sports drink at alternate stations, or as
  wanted.
- The station kilometres and the gel stations are **settings** (`race_stations`, `race_gel_stations`) with
  the recent-years values as defaults, and the page says: "From recent editions: check the 2027 course
  guide." (Claude's call: they're race-specific facts, like `race_name`.)
- Practical lines: gels carried, start pen, "nothing new on race day".

## Non-goals

- A stomach log, ratings, or carbohydrate grams per product.
- Gel alerts on the watch (the `.fit` files stay as they are; a possible follow-up).
- Fuelling on runs under 90 minutes, Wednesday sessions or easy runs.
- Weather, heat or caffeine advice. Changing the plan's volume or paces.

## Anti-goals

- **Storing the plan:** notes and the race plan are recomputed; only the "fuelled as planned" tick is stored.
- **Stating 2027 course details as fact:** they're labelled as from recent editions until checked.

## Constraints

FastAPI + Jinja2 + SQLite, no JavaScript, POST then 303. Phone-first at 390 px, light and dark tokens. New
table `CREATE TABLE IF NOT EXISTS`. Pure maths in a new `app/fuel.py`, tested; each behaviour gets a test
that fails first.

## Left to the builder

Route names for the tick (e.g. `POST /fuel`, `POST /fuel/undo`), exact copy within the app's tone, where the
tick sits on the long-run row, and the race page's layout.

## How to check it

- Plan as written: weeks 1–4 have no fuelling note; week 5's 14 km says 2 gels (45, 80); week 18's 32 km says
  5 gels and the MP line; week 7's 12 km cutback has none.
- Race page at 5:41/km: first 5 km at 5:46/km, then 5:40; half about 2:00; finish 3:59:48 (341 × 42.195);
  carried gels at about km 8 and 14, course gels at km 20, 25, 30 and 37.5.
- Tick a long run: the summary says "Fuelled as planned."; Progress counts it; undo removes it.
