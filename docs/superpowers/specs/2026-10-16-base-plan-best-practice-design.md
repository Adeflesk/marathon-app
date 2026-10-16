# Base plan to best practice — design

Date: 2026-10-16
Evidence: `reports/Marathon training practices for AI coach.md` (sections 1–5, and the "Plan versus evidence" table).

## Why

The user is training for Barcelona (Sun 14 Mar 2027, goal 3:59) and wants the generated plan to follow best
practice before an AI weekly coach is added on top of it. The research found the plan's skeleton is sound,
but it differs from the evidence in four places:

- the Wednesday session is the same continuous tempo every week, and there is none in cutback or taper weeks;
- the peak block stacks three 30–32 km long runs, each with a 12 km marathon-pace (MP) finish;
- MP finishes appear every build week instead of every other week, and some long runs jump more than 10% in one go;
- the peak volume of 55 km is at the bottom of what sub-4 runners run.

The AI coach is a separate, later project. This change is only to the base plan and its watch export.

## Goals

1. **Peak volume of 60 km.** `DEFAULTS["peak_weekly_km"]` goes from 55 to 60 (user's decision). The extra
   km go to the Monday and Saturday runs, not to Sunday (user's decision).
2. **A Wednesday session that changes by phase** (the menu below), including a reduced session in
   cutback weeks and a short MP session in taper weeks and race week.
3. **Long runs to best practice:**
   - MP finishes every other week, growing 6 → 8 → 10 → 12 km;
   - no back-to-back 30 km+ long runs;
   - a spike guard of no more than 1.1 × the longest planned long run in the previous 4 weeks;
   - a time cap of 3.5 hours at long-run pace.
4. **Watch export with real repeat steps**, matching the files Garmin itself makes (see "FIT format").
5. **The README** still explains the training logic in plain terms, updated to match.

## Non-goals

- The AI weekly coach and any push or ease-off logic beyond today's check-in trim.
- Hill sessions in the base plan. They need an "ankle cleared" signal the app doesn't have. The AI coach
  can offer them later. *(my call)*
- Smashrun sync changes, new check-in questions, or strength-session redesign (beyond the adjacency
  rule below).

## Anti-goals (a failure even if it works)

- **Storing the plan.** It must still be recomputed from settings on every request (CLAUDE.md).
- **Hardcoding week numbers or weekdays.** Changing `race_date`, `plan_start`, `base_weeks`,
  `peak_weekly_km` or `run_days` must still reshape the whole plan sensibly. Sessions are placed by
  *position relative to the phases* (counted back from the taper), never by absolute week number.
- **Breaking watch compatibility.** The current single-step and tempo files load on the user's Garmin
  watch. Keep the same file_id/workout/step message shapes and speed-range targets that already work.
- **Making the taper flatter or bumping it.** Taper volume must fall every week.

## Constraints and conventions

- Units are km, seconds per km and seconds. Planned km are rounded to 0.5. Format only at display time.
- `plan.py` stays pure functions.
- The check-in factor (0.8/0.9/1.0 from the previous week) still only ever reduces load.
- Python 3.11, `fit-tool`. There's no test suite, so check plan output with the generator one-liner in
  CLAUDE.md.

## Paces

Add two keys to `DEFAULTS["paces"]`. Both can be overridden in `settings.json` like the others:

| Key | Default | Meaning |
|---|---|---|
| `interval` | 300 (5:00/km) | about 5 km race pace, for VO2 reps |
| `subthreshold` | 332 (5:32/km) | MP − 9 s, for Hansons-style "strength" reps |

The existing keys keep their meanings: `tempo` (325) is threshold, `marathon` (341) is MP, and `easy` and
`long` are unchanged. *(my call: the defaults come from the report's pace table. The interval value is an
estimate the report flags, which is fine because it is a setting.)*

## Phases and blocks

Weekly volumes keep today's shape: 3 Rebuild weeks, then build weeks with every 4th post-base week a
Cutback, then 2 Taper weeks and Race week. With the default settings and a 60 km peak:

- Rebuild: weeks 1–3, at 25 km.
- Build blocks: weeks 4–6, 8–10, 12–14 and 16–18. A cutback follows each of the first three.
- Taper: weeks 19–20, at 45 and 33 km.
- Race week: week 21.

**Blocks** are the runs of 3 build weeks between cutbacks. They are counted **backwards from the taper**:

| Block (from the taper) | Name | Default weeks |
|---|---|---|
| last | Specific (shown as phase "Peak") | 16–18 |
| 2nd last | Strength | 12–14 |
| 3rd last | Threshold | 8–10 |
| any earlier | General | 4–6 |

A **cutback** week takes the block before it. If the plan is shorter, the General and then the
Threshold blocks disappear first. If it's longer, there are more General blocks. *(my call)*

**Uneven builds** *(my call)*. Other settings can leave a last block of 1 or 2 weeks, or put a cutback
right before the taper:

- A cutback that would land in the week before Taper week 1 is dropped, and that week becomes a build
  week. The taper already gives the rest.
- The last block is Specific whatever its length. The rule of no back-to-back 30 km+ runs still holds,
  and in a 2-week block only the first week may reach 30 km. The final peak long run (exempt from the
  guard) is always the last build week's.
- The every-other-week MP count continues across short blocks.
- Change `weekly_volumes` as needed for these rules.

The phase label "Peak" applies to the whole last block. It no longer means "weekly km reached
`peak_weekly_km`", because the km now reach 60 only in its final week. Strength's "Peak" prescription
applies across the whole block too: lighter strength during the heaviest running. *(my call)* The taper's
link to `peak_weekly_km` stays as it is.

## Wednesday (quality day) session menu

Every structured session is wrapped in a warm-up and cool-down at easy pace. These are by distance, and
flex to fill the day's planned km: at least 2 km of warm-up and 1 km of cool-down. Strides are 20 s fast
with 60 s easy jogs, at interval pace.

| Where | Session (default) | Progression across the block's 3 weeks |
|---|---|---|
| Rebuild wk 1 | Easy run | none |
| Rebuild wk 2+ | Easy run + 6 × 20 s strides | 6 → 8 strides |
| General block | Fartlek: N × 1 min at interval pace / 2 min easy | 6 → 7 → 8 reps |
| Threshold block | Cruise intervals: N × 1.6 km at `tempo` / 60 s jog | 4 → 5 × 1.6 km, then 3 × 3.2 km / 2 min jog |
| Strength block | N × 1.6 km at `subthreshold` / 400 m jog | 6 × 1.6 km → 4 × 2.4 km (800 m jog) → 3 × 3.2 km (800 m jog) |
| Specific block | 2 × 5 km at MP − 3 s (about 5:38) with 1 km float at about 6:00 | wk 1: 2 × 4 km; wk 2: 2 × 5 km; wk 3: 2 × 5 km *(my call)* |
| Cutback | the preceding block's first-week session with about 35% fewer reps (at least 2), or for General, 5 × 1 min | none |
| Taper wk 1 | 2 × 3.2 km at `subthreshold` / 800 m jog | none |
| Taper wk 2 | 3 × 1.6 km at MP / 400 m jog | none |
| Race week | 3 × 1 km at MP / 2 min jog, then 4 strides | none |

"Float" is an active step with a pace target at 95% of MP speed (MP ÷ 0.95, about 6:00). Recovery jogs
have no pace target, as in Garmin's own files. All quality sessions are on flat ground; the note says so
while the ankle is recovering. *(my call: the menu's main options come from the report's section 4
table; its alternatives are left out of the base plan.)*

**Quality-day distance** *(my call)*. The session's own distance (warm-up + reps + recoveries + cool-down,
with time-based steps converted to km at their pace) decides Wednesday's km. The week's other mid-week
runs absorb the difference so the weekly target holds. The last mid-week run already absorbs rounding.
To keep the easy days real runs and stay within the evidence on quality volume:

- **Easy-run floor:** each easy mid-week run is at least 6 km in Build and Peak weeks, and 5 km
  elsewhere. Race week keeps its own fixed shakeouts.
- **Work cap:** the session's work volume (rep km, not warm-up, cool-down or recoveries) is at most about
  12% of the week's km for threshold (`tempo`) reps, and about 18% for `subthreshold` or MP reps. The
  float in the Specific session counts towards it.
- **Fitting it:** if the session doesn't fit the cap or the floor, drop reps (or shorten rep length one
  step, e.g. 3.2 → 2.4 km) until it does. Never go below 2 reps; below that, the session becomes the
  block's cutback version. The menu below is the *intended* progression, and the caps may trim it in
  lower-volume weeks.

## Long runs

- **Progression:** keep today's rules (12 km first build week, +2 km per build week, the cutback at 75%,
  `max_long_run_km` of 32), plus the following.
  - **Spike guard:** once a long run would be 20 km or more, it is never more than 1.1 × the longest
    planned long run in the previous 4 weeks, rounded down to 0.5 km. Below 20 km the +2 km steps
    stand, since 2 km is a small absolute jump. *(my call; otherwise the Rebuild weeks' 10 km runs cap
    the whole curve)*
  - **The final peak long run is exempt from the guard** and goes to `max_long_run_km` (32 km) when
    the time cap and share cap allow. This is the user's decision: they chose 32 km over the guard's
    roughly 30 km.
  - **Time cap:** a long run is never longer than 12600 s ÷ `paces.long` (32.3 km at 6:30/km).
- **Share-of-week cap:** 0.58 applies to the whole Peak block, and 0.5 elsewhere. *(my call; this follows
  the new meaning of the Peak label)*
- **Peak block (Specific):** no two long runs in a row may be 30 km or more. The middle week's long run is
  85% of the block's largest so far, rounded to the nearest 1 km, all easy, no MP. With the defaults
  that's about 28.5 → 24 → 32 km.
- **MP finishes:** from the first week of the Strength block, every other non-cutback build week gets an
  MP finish, starting at 6 km and growing +2 km each time, capped at 12 km. The other weeks are easy. MP
  km never exceed long_km − 8 and never go below 0. With the defaults, that's MP in weeks 12 (6), 14
  (8), 16 (10) and 18 (12), and weeks 13 and 17 are easy.
- **Taper:** long runs as today (20 and 14 km). Race week as today (the race on `race_date`).

## Data shape

Each workout dict keeps `date`, `day`, `type`, `km`, `pace` and `note`. Structured sessions add
`steps`: an ordered list where each item is either a step or a repeat block:

```python
{"label": "Rep", "km": 1.6, "pace": "tempo", "intensity": "active", "note": "Controlled, even."}
{"label": "Jog", "seconds": 60, "pace": None, "intensity": "recovery"}
{"repeat": 4, "steps": [<step>, <step>]}
```

A step has `km` or `seconds`, never both. `pace` is a key in `settings.paces` or a number in seconds per
km (for MP − 3 s or float), or `None` for an open target. `intensity` is one of warmup, active, recovery
or cooldown. The `type` field gains values `strides`, `fartlek`, `threshold`, `strength`, `specific` and
`mp`, alongside `easy`, `tempo`, `long` and `race`. Builder may rename these if the template, strength
adjacency and FIT export stay consistent. The `note` is generated from the steps (e.g. "2 km WU, 4 × 1.6
km at 5:25 with 60 s jog, 1.5 km CD. Flat ground."), and the existing `note` text is replaced.

`tempo_min` and `mp_km` either go, or are derived from `steps`. The check-in trim (`main.build_view`)
scales **reps** by the factor (round down, at least 2) and recomputes the day's km and note. It no longer
scales the minutes of a single tempo block.

## FIT format

Decoded from three workouts the user's watch accepts (`samples/garmin/`, made in Garmin Connect):

- A repeat block is the rep steps written once, followed by a step with `duration_type =
  REPEAT_UNTIL_STEPS_CMPLT`, `duration_step` (`duration_value`) = the index of the first step to repeat,
  and `target_repeat_steps` (`target_value`) = the count. Several blocks can appear in one workout.
- Pace targets are `target_type = SPEED` with a custom low/high speed. These are the same fields today's
  export uses, so the current pace bands (`EASY_BAND` / `HARD_BAND`) stay.
- Recoveries are `intensity = RECOVERY`, `target_type = OPEN`.
- Each step can carry a `notes` string.
- `workout.num_valid_steps` counts every step, including the repeat steps.

`garmin.steps_for` becomes a translation of the workout's `steps`, plus a single step for plain
easy/long/race runs and two steps for a long run with an MP finish, as today. `fit-tool`'s
`WorkoutStepMessage` already has `duration_step` and `target_repeat_steps`. A long-run MP finish stays
two plain steps.

## Other touch points

- **Strength.** "A tempo run is next to this session" becomes "a hard session is next to it". That
  covers `threshold`, `strength`, `specific` and `mp`, but not strides, fartlek, or the short taper and
  race-week sessions. *(my call: otherwise Strength A would sit on its reduced prescription for almost
  the whole plan. With the defaults it ends up reduced in about the same weeks as today, weeks 8–18.)*
  Strength A is still dropped in the final taper week.
- **Templates.** The plan, dashboard and strength pages show the new type names and generated notes.
  The `.fit` link appears for any workout with km > 0, as today.
- **README:** update the training-logic explanation for the session menu, MP finishes every other
  week, the peak block and the 60 km peak.
- **CLAUDE.md:** update the `plan.py` description (tempo from week index 7 and MP from index 10 no
  longer apply).

## How to check it

- The generator one-liner prints each week's phase, km and Wednesday type. With the defaults, check:
  - weeks 16–18 are labelled Peak, at 55 → 58 → 60 km;
  - the long runs are about 28.5 → 24 → 32 km;
  - no easy mid-week run is under the floor, and no session's work goes past its cap;
  - MP finishes fall in weeks 12, 14, 16 and 18 only;
  - every cutback, taper and race week has a Wednesday session;
  - no long run of 20 km or more breaks the 1.1× guard, except the final peak run;
  - the taper falls every week.
- Change the settings (e.g. `base_weeks: 2`, `peak_weekly_km: 50`, a Saturday `race_date`) and check
  that the plan still makes sense and nothing crashes. In particular, check that no cutback sits right
  before the taper.
- Decode an exported cruise-interval `.fit` (a raw decoder like the one used on `samples/garmin/`) and
  compare its structure with the Garmin samples.
- The user loads one structured workout onto their watch before relying on the rest.
- All pages return 200.

## Left to the builder

- Function boundaries inside `plan.py`, e.g. a `sessions.py` module for the menu.
- Exact rounding of step distances, the warm-up/cool-down flex algorithm within the rules above, and
  the wording of notes.
- Step labels, kept short for the watch screen.
- Whether to keep a decoder script in the repo for checking exports.
