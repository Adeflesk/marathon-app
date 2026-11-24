# Marathon plan app

FastAPI + server-rendered pages + SQLite. Plans a build to the Barcelona Marathon (Sun 14 Mar 2027),
syncs runs and recovery data from Garmin and compares them with the plan.

## Run it in VS Code

1. Unzip, then `File > Open Folder` on `marathon-app`.
2. Terminal:
   ```
   python -m venv .venv
   source .venv/bin/activate        # Windows: .venv\Scripts\activate
   pip install -r requirements.txt
   cp .env.example .env             # then paste your Garmin key into .env
   uvicorn app.main:app --reload
   ```
   Or press F5 (the launch config is in `.vscode/launch.json`).
3. Open http://localhost:8000. On your phone, use `--host 0.0.0.0` and your computer's IP.

## On your phone's home screen

In Chrome on Android, open the app, then the ⋮ menu → **Add to home screen** (or **Install app**). It opens
full screen with its own icon. If you had a plain shortcut before, remove it and add the app this way.

## Garmin key

Open https://connect.garmin.com/app/settings/personalApiToken, create a key and choose **1 year**. It is
shown once, so copy it straight away. Put it in `.env` as `GARMIN_API_KEY=...` and set
`GARMIN_API_KEY_EXPIRES` to the day it runs out (`YYYY-MM-DD`). On Fly:
`fly secrets set GARMIN_API_KEY=... GARMIN_API_KEY_EXPIRES=YYYY-MM-DD`. This week warns you in the last 7
days before it runs out. When sync says the key was rejected, make a new one the same way and update both.

Runs, their km splits and laps, and your nightly HRV, resting heart rate and sleep all come from Garmin
Connect. Runs you had synced from Smashrun before stay; a Garmin run replaces the matching old one.

## Recovery

The Recovery panel on This week and the charts on Progress read your HRV against your normal range (the band
Garmin shows, for your 7-day average). The app only suggests; it never changes the plan by itself, and race
week is never trimmed.

- **Suspicion:** three nights in a row with HRV below your range, or a 7-day average below it. Nothing
  changes yet. Resting heart rate and short or poor sleep are shown as extra weight, but never start it.
- **The next run decides.** If that run shows a higher heart rate at easy pace or more drift than your
  recent runs, or it's a hard session that fell short of its reps, the suspicion turns into advice; if it
  looks normal, the note stays a note.
- **Take the trim:** the rest of that week at 90%, one rep off the next session (or the whole session at 90%
  when it has no rep to spare), and strength held at its current loads. You choose; nothing happens until you
  press it. It starts today, or tomorrow if today's run is already in; pressed on a Sunday after the run, it
  covers the next week. Once pressed, it stays put: syncing runs never moves or undoes it.
- **Make the next run easy:** if HRV is still low three nights after the advice (or two more runs in), the
  warning turns firm and this second button appears: your next run becomes an easy run at 80% of its km.
- It clears when HRV is back in range two nights running and the 7-day average is no longer low.

## After a run

Open This week or Progress once the run is in Garmin Connect: when a run planned for yesterday or today hasn't
synced yet, the app syncs first (at most every 15 minutes). If the run still isn't there, a line at the top
says so with a **Sync now** button; the button at the bottom of the week works too. Each new run's km splits and laps come with it, and This week
shows a review of your last run: easy runs quicker than easy get flagged, long runs show whether the
marathon-pace finish was on pace, and sessions run from the watch workout are checked rep by rep.
Strides are listed one by one but not judged, since they go by feel; the review checks that the running
around them stayed easy. Heart-rate drift (second half against first) under 5% means the effort stayed
steady. Strides days show no drift figure, because the strides lift your heart rate on purpose.
A long run without a marathon-pace finish reads "Long run at 6:13/km (planned 6:30)".

**Form note.** On easy and long runs of 8 km or more, the review says when your form faded: "Cadence fell from
176 to 170 steps/min in the last 4 km", or "Your stride lengthened in the last 4 km" (at a pace no quicker). As
you tire the stride gets longer and loads the ankle more, so it's worth noticing on the long runs. It's
information only: it never changes the verdict or the plan. On a long run with a marathon-pace finish, only the
steady running before the finish is compared. The km splits show cadence too.

## Progress

The Progress tab answers one question: **are you on course for your goal?** Log a race or time trial (under
"Your paces" on This week) and it predicts your marathon: on course, within reach (up to 5% off) or a stretch.
Under the verdict, four reasons: the plan (km done over the last 4 weeks, strength sessions), fitness (heart
rate on easy runs at 6:45/km, week by week; lower is fitter), long runs (did heart rate hold steady) and the
ankle (flag, hops, pain).

When the goal isn't on course, it suggests goals that fit: a realistic stretch (today's prediction, improved
by about 1% per 4 weeks of training left, at most 4%) and today's prediction. **Train for 4:09** changes
your goal, and marathon pace, the sessions and the watch files follow; **Back to 3:59** puts the original
back exactly. The app never changes the goal by itself.

Below: charts of fitness, long runs and km planned against done, the ankle tests against their targets, and
a scorecard for every finished week (below). The Ankle section also shows:

- **Cadence** at easy pace (same pace every week, so a quicker or slower run doesn't move it), with a reading
  over the last 4 weeks: steady, rising or falling.
- **Time on your feet:** Garmin's daily steps with your runs taken out, over 8 weeks, a dot on each day your
  ankle was worse (a "worse than usual" morning check or ankle pain logged). A heavy day is one in your own top
  fifth of the previous 4 weeks, since long days on your feet are normal for you. One heavy day gets no
  message. Only when it repeats (twice in 4 weeks, a worse ankle the day after a heavy day, at least 3 days
  apart) does it say so. It shows what happened after what, never that the steps caused it.

### Weekly scorecard

Each finished week gets a scorecard that answers **was the week in the right direction, and where do I need to
strengthen?** Each line has an arrow: ↑ improving, → holding, ↓ falling, or – when there isn't enough to judge
yet.

**Running:**
- **Fitness:** heart rate at easy pace against the 4 weeks before. 2 beats lower is ↑.
- **Long run:** ↓ if heart rate drifted, ↑ if it was your longest yet and held steady.
- **Plan done:** km done against planned. 95% or more is ↑, under 80% is ↓.
- **Marathon pace:** only in weeks with marathon-pace work.
- **Late-run form:** ↓ if a run's cadence fell or its stride lengthened late. Otherwise, your cadence trend.
- **How it felt:** the check-in's 1–5 against your last 4 weeks. 2 or less is always ↓.

**Strength and ankle:**
- **Strength done.**
- **Strength loads:** weights against 4 weeks before. Held loads count as ↑ in cutback and taper weeks, because
  holding is the plan there.
- **Hops and balance:** stages against 4 weeks before.
- **Ankle:** ↓ on a worse morning, ankle pain of 3 or more, or check-in pain of 3 or more. ↑ in a test week that
  meets more targets.
- **Snacks:** 4 days or more is ↑.

The verdict at the top goes by the first of these that applies:

1. **Ankle first:** the ankle line is ↓. Nothing else matters that week.
2. **The numbers and how you felt disagree:** you rated the week poorly while the numbers look fine. The
   numbers never overrule how you felt.
3. **Too early to say:** fewer than 3 lines can be compared with past weeks yet. The first weeks read like this.
   A poor feel is never hidden behind it.
4. **Not the right direction:** two running lines are ↓, or fitness is ↓ two weeks running.
5. **Right direction:** with how many lines are improving or holding.

A hop or balance stage stepping back is named as a weak spot, but doesn't make the verdict "ankle first" on its
own.

Under the verdict come the weakest one or two lines, ankle and feel first, then what happened that week and one
focus for the next. The scorecard never changes the plan. It's worked out again each time you open the page, so
a late sync or an edited check-in updates it. Last week's verdict and weak spots also show on This week on
Monday and Tuesday, with a link to the full scorecard. A week no sync has covered says so, since runs may be
missing.

## Fuelling and race day

Long runs of 90 minutes or more (from week 5's 14 km) carry a fuel practice line: a Finisher gel at 45
minutes, then every 35, none in the last 10 minutes, with water. Finisher is the Barcelona course's own gel,
so race day holds no surprises. Marathon-pace finishes add: take the gel before the marathon-pace part and
keep taking them at goal pace. After the run, tap **Fuelled as planned** in the week list; the weekly summary
and Progress count your practice.

From the first taper week, This week links the **Race day** page: your finish time at the marathon pace you
train at (it follows your goal and latest result), the first 5 km 5 s/km easier and the rest a touch quicker,
5 km splits with the clock, and each gel with where it comes from: carry the ones due before the first course
gel station (about km 8 and 14 at 5:41/km), then take them from the course stations. The station kilometres
are `race_stations` and `race_gel_stations` in `settings.json`, from recent editions: check the 2027 course
guide and update them if they move.

## Days

Runs are Monday (easy), Wednesday (the quality session), Saturday (easy) and Sunday (long); nothing on
Tuesday or Thursday. Strength is Tuesday and Thursday. Change them in `settings.json`, for example:

```json
{
  "run_days": {"mon": "easy", "wed": "quality", "sat": "easy", "sun": "long"},
  "strength_days": {"B": "tue", "A": "thu"}
}
```

Roles are `easy`, `quality` (the week's session) and `long`. Only the first quality day gets the session; `long` needs exactly one day.

## Tuning

Everything is in `settings.json` (create it next to `README.md`; any key you leave out uses the default
in `app/config.py`):

```json
{
  "paces": {"easy": 405, "long": 390, "marathon": 341, "tempo": 325, "subthreshold": 332, "interval": 300},
  "peak_weekly_km": 60,
  "weekly_step_km": 3
}
```

Paces are seconds per km. `tempo` is threshold pace, `subthreshold` is just quicker than marathon pace
(about MP - 9 s) and `interval` is about 5 km race pace. `marathon` is your goal pace.

**After a race or time trial,** log it under "Your paces" on This week (5 km, 10 km or a half marathon). The
latest result sets easy, long, threshold and interval pace for the whole plan and the watch files, and says
how the goal looks: on track, within reach (up to 5% off) or ambitious. Marathon pace stays at goal pace
unless that's within 10 s/km of your threshold pace (then it sits 10 s slower than threshold for now, so
marathon-pace work doesn't turn into threshold work), or the goal is out of reach (then it's your predicted
pace). A parkrun or a solo 5 km in the week 7 cutback is ideal. Delete a mis-entered result to go back.
To try numbers without saving them: `python -m app.pace_engine 10 52:30`.

## Strength & Ankle

- Open **Equipment** and tick or edit what you own. Kit is pre-filled (barbell and plates,
  dumbbells 2.5–35 kg, 12 and 16 kg kettlebells, 5 kg medicine ball, box, rings). Check the bar weight
  (assumed 20 kg) and plate pairs. Bench, rack and bands are on; pull-up bar is off. Slots fallback to
  dumbbell or bodyweight variations if you don't have rings or a rack.
- **Two sessions a week** (Tuesday B and Thursday A by default):
  - **Thursday A** (heavy legs and hops, ~45 min): hops (once unlocked), barbell box squat, Romanian deadlift,
    the block's single-leg lift (step-ups in block 0, reverse lunges in block 1, Bulgarian split squats from block 2),
    straight calf raise, seated soleus raise, and barbell hip thrust.
  - **Tuesday B** (light full body and ankle, ~40 min): ankle balance block, dumbbell single-leg RDL, ring row +
    push-up, suitcase carry + core (Pallof press, dead bug, or side plank), Copenhagen plank, bent calf raise +
    band eversion. The Copenhagen plank works the inner thigh (groin), which the rest of the routine misses. It
    starts with the knee on the bench (short lever) and moves to the foot on the bench from week 7; holds grow
    from 15 s towards 30 s per side as you rate them easy. It's dropped in the last taper week.
- **Logging card on This week**: on strength days, a checklist card appears. Each exercise gives a suggested
  weight and reps. The very first session shows a warm-up ladder to establish your working weight. Enter your
  weights and reps, then tap **Easy**, **Right**, or **Hard** to save. The app steps the load up or down next
  time based on your rating. A break of 11–28 days drops one step; over 28 days resets conservatively (≤ 80%).
  Carries take the weight you carry too, and step up once the distance feels right. Timed holds and carries
  move in 5 s or 5 m steps.
- **Ankle snacks**: short 8–10 minute balance and tendon drills on non-strength days (`ankle_days`: default Mon,
  Wed, Fri, Sat). Ticking snack items advances your balance stage (Stage 1 to 6).
- **Ankle tests & hop stages**: readiness tests (20-pogo trial, calf raises to fatigue, eyes-closed balance,
  Y-balance, single and triple hops) are scheduled in week 1, the first build week, and cutback weeks. Passing
  tests unlocks plyometric hop stages (Stage 1 low pogos, Stage 2 line/lateral hops, Stage 3 continuous bounds).
- **Morning check & ankle flag**: the morning after hop or calf work, a quick check asks how the ankle feels.
  Rating it "Worse than usual", logging ankle pain ≥ 3 (or higher than last time on that exercise), or
  reporting ankle pain ≥ 3 in the weekly check-in raises the **ankle flag** for 7 days: no weight increases on
  ankle work, Thursday main lifts lose a set if the flag is still up that day, and hop work steps back. Notes on
  the morning check are kept for you but don't change anything.
- **Auto-trimming**: sessions lose 1 set during cutback weeks, taper weeks, if your Wednesday run review was "bad",
  or if the weekly check-in trimmed volume. Sessions never drop below 1 set. Race week has no strength sessions.

## Moving a session

Life gets in the way. Any run or strength session from today on has a **Move to tomorrow** button: on
today's card, and in the week list. The session moves one day, and its watch file, logging and run review move
with it. Tap it again to push it another day. Sessions from tomorrow on also have **Move a day earlier**, for
when you'll be away at the end of the week: move Saturday's run to Friday first, then Sunday's to Saturday.

If the new day already has a long run or a speed session, or you're moving a run onto another run day, or a
strength session onto the other strength day, the app warns you and suggests skipping the missed session
instead of stacking the two. **Skip it** marks it skipped: it comes off the week's planned km and doesn't count
as missed. **Move anyway** moves it regardless. Moved and skipped sessions show **Undo**. A session you've
already done, or one whose next day is race day, can't be moved.

## Garmin Forerunner 255

Each run in the week table has a "Garmin .fit" link, and "Garmin files for the week" gives a zip of the
whole week. Wednesday sessions have a warm-up, the reps as a repeat block (so the watch counts them down
and shows "rep 3 of 6"), and a cool-down. Recoveries have no pace target. Easy and long runs open with a
1 km warm-up with no pace target (start as slowly as you like; the watch won't nag), then the rest of the run
in its pace range. A long run with a marathon-pace finish adds the MP step at the end. Race day has no warm-up
step. Before any run, a couple of minutes of calf raises and ankle circles at the door is good for the ankle.

1. Connect the watch to the computer by USB and unzip the `.fit` files.
2. Copy them into the watch's `GARMIN/NewFiles` folder (if they don't show up, try `GARMIN/Workouts`).
3. Eject, then on the watch go to Training, Workouts and pick the session.

Pace ranges follow your paces (your latest logged result, else `settings.json`). The files have been tried on a
real Garmin watch and load as workouts.

## How the plan works

The shape follows what coaches and the research agree on. The full write-up is in
`reports/Marathon training practices for AI coach.md`.

- **Weeks 1-3, rebuild:** 25 km a week, longest run 10 km, strides on Wednesday from week 2.
- **Build:** weekly volume grows by 3 km to a 60 km peak. A cutback (about -20%) comes every fourth
  week. The extra km as you build go on Monday and Saturday, not Sunday.
- **Wednesday changes every few weeks**, from general speed to marathon-specific work:

  | Weeks (default) | Session |
  |---|---|
  | 4-6 | Fartlek: 1 min fast, 2 min easy |
  | 8-10 | Threshold cruise intervals at tempo pace |
  | 12-14 | Reps just quicker than marathon pace |
  | 16-18 | Long reps at marathon pace with a 1 km float |
  | Cutback weeks | A smaller version of the block's session |
  | Taper | Sub-threshold reps, then a short marathon-pace session |
  | Race week | 3 × 1 km at marathon pace, unless it's the day before the race |

  The work part of a session is capped at about 12% of the week (threshold pace) or 18% (marathon-ish
  pace). In lower-volume weeks it gets fewer or shorter reps, and it grows as the weeks do.
- **Long runs** grow by 2 km a week. From 20 km up, a long run is never more than 10% longer than the
  longest of the previous four weeks, apart from the final 32 km peak run. Long runs are capped at
  3.5 hours.
- **Marathon-pace finishes** come every other week from week 12, growing 6, 8, 10, then 12 km.
- **The peak block (weeks 16-18)** goes 28, 24 (all easy), then 32 km, so the two biggest runs aren't
  back to back.
- **Taper:** volume falls every week (45, then 33 km), then race week.
- **Check-in:** the weekly check-in (feel 1-5, ankle pain 0-10) trims the following week by 10% or
  20% when it's a rough one. Sessions lose reps (never below 2) or get shorter reps. The plan only ever
  adjusts down.
- **Missed running:** a week can't be more than 15% above the best of your last four weeks actually run. If a
  week fell under 60% of its target (ill, travelling), the next one is held at 90% of that best week, then
  climbs back to the plan over two or three weeks. Never below 25 km, never on race week. It only counts
  weeks a sync has covered (a sync on or after the Sunday), so a sync gap can't shrink the plan. The
  week says when it's been held; strength isn't trimmed by it. Following the plan, it never kicks in.

This is a draft shape, not coaching. Stop if the ankle hurts, and see a physio if it keeps happening.
