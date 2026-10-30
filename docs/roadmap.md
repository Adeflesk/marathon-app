# Roadmap

Big-picture gains agreed on 30 Oct 2026, after the app review. The core (plan, logging, reviews, moves) is
solid; these turn the data into decisions. Order of work: **2 → 1 → 3** (3 needs to be in place by early
December, when long runs pass 90 minutes), then 4 when convenient.

Each item gets a design in `docs/superpowers/specs/` before any code. Tick items off here as they ship.

## 1. Progress page: "Am I getting fitter?"

Everything below uses data the app already stores (splits, laps, tests, logs, checks). Mostly a new page.

- [x] **Easy-run fitness trend:** heart rate at a fixed easy pace, and pace at a fixed heart rate, week by
      week. The clearest sign the aerobic base is improving.
- [x] **Long-run steadiness:** heart-rate drift on each long run as they get longer.
- [x] **Ankle trend:** test results against their gates, pain scores over time, hop and balance stages.
- [x] **Weekly summary** each Sunday: runs done against the plan, strength, ankle and one focus for next
      week (the week 1 review, written by the app).

## 2. A plan that responds to what was actually done

Today the plan adjusts only from the weekly check-in, and only downwards.

- [x] **Missed-week guard:** after a low week (illness, travel), the next week holds or repeats volume
      instead of stepping up as if the week had been done.
- [x] **Paces from a result:** enter a 5 km, parkrun or 10 km time in the app. It updates every pace, the
      watch files and the whole plan, with an honest read on whether the goal time looks realistic. Pairs
      with the week 7 time trial (30 Nov – 6 Dec, cutback week).

## 3. Race preparation built into the long runs

Needed from about week 8 (long runs of 90 minutes and more).

- [ ] **Fuelling notes** on long runs, e.g. "a gel every 30–40 min from 45 min".
- [ ] **Log how the stomach coped** with the fuel.
- [ ] **MP finishes checked while fuelling.**
- [ ] **Race-day plan:** pacing and fuelling for Barcelona in the last weeks.

## 4. Less admin

- [ ] **Sync on its own:** when the app opens and the last sync is more than a few hours old.
- [ ] **Smashrun full login:** research whether a registered app's tokens refresh themselves, removing the
      60-day token renewal. Depends on Smashrun approving an app.
- [ ] **Home-screen app:** install from the phone's home screen so it opens like a native app.

## Decided against

- **Garmin strength workouts.** Possible, but the watch can't capture the Easy/Right/Hard rating or ankle
  pain that drive progression, so it means logging twice, and exercise names don't reliably show. Instead,
  record a plain Strength activity on the watch for heart rate and training load. Revisit only if a rest
  timer on the wrist is missed (it would need a Garmin Connect strength export in `samples/garmin/` first).
- **Multiple users.**
- **An AI chat coach.** Deterministic rules are easier to trust and test.

## Also open (from the 29 Oct review)

- [ ] Set `SMASHRUN_TOKEN_ISSUED` (`fly secrets set SMASHRUN_TOKEN_ISSUED=YYYY-MM-DD`).
- [ ] Week 7 time trial, then update paces (item 2 makes this an in-app step).
- [ ] January: revisit the peak weeks (week 18: 32 km long run with a 12 km MP finish, 53% of the week;
      week 17's 10 and 10.5 km easy runs). Depends on how weeks 12–16 go.
