# Marathon plan app

FastAPI + server-rendered pages + SQLite. Plans a build to the Barcelona Marathon (Sun 14 Mar 2027),
syncs runs from Smashrun and compares them with the plan.

## Run it in VS Code

1. Unzip, then `File > Open Folder` on `marathon-app`.
2. Terminal:
   ```
   python -m venv .venv
   source .venv/bin/activate        # Windows: .venv\Scripts\activate
   pip install -r requirements.txt
   cp .env.example .env             # then paste your Smashrun token into .env
   uvicorn app.main:app --reload
   ```
   Or press F5 (the launch config is in `.vscode/launch.json`).
3. Open http://localhost:8000. On your phone, use `--host 0.0.0.0` and your computer's IP.

## Smashrun token

Open https://api.smashrun.com/v1/explorer, type `client` in the box at the top, click Connect and copy
the token. Put it in `.env` as `SMASHRUN_TOKEN=...` (on Fly: `fly secrets set SMASHRUN_TOKEN=...`).
It lasts about 60 days; when sync says the token was rejected, get a new one the same way.

## After a run

Sync from Smashrun once the run is there. Each new run's km splits and laps come with it, and This week
shows a review of your last run: easy runs quicker than easy get flagged, long runs show whether the
marathon-pace finish was on pace, and sessions run from the watch workout are checked rep by rep.
Heart-rate drift (second half against first) under 5% means the effort stayed steady.

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
(about MP - 9 s) and `interval` is about 5 km race pace. After a 5K or 10K time trial, work out new ones with:

```
python -m app.pace_engine 10 52:30
```

## Strength & Ankle

- Open **Equipment** and tick or edit what you own. Kit is pre-filled (barbell and plates,
  dumbbells 2.5–35 kg, 12 and 16 kg kettlebells, 5 kg medicine ball, box, rings). Check the bar weight
  (assumed 20 kg) and plate pairs. Bench, rack and bands are on; pull-up bar is off. Slots fallback to
  dumbbell or bodyweight variations if you don't have rings or a rack.
- **Two sessions a week** (Tuesday B and Thursday A by default):
  - **Thursday A** (heavy legs and hops, ~45 min): hops (once unlocked), barbell box squat, Romanian deadlift,
    the block's single-leg lift (step-ups in block 0, reverse lunges in block 1, Bulgarian split squats from block 2),
    straight calf raise, seated soleus raise, and barbell hip thrust.
  - **Tuesday B** (light full body and ankle, ~35 min): ankle balance block, dumbbell single-leg RDL, ring row +
    push-up, suitcase carry + core (Pallof press, dead bug, or side plank), bent calf raise + band eversion.
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

## Garmin Forerunner 255

Each run in the week table has a "Garmin .fit" link, and "Garmin files for the week" gives a zip of the
whole week. Wednesday sessions have a warm-up, the reps as a repeat block (so the watch counts them down
and shows "rep 3 of 6"), and a cool-down. Recoveries have no pace target. Easy and long runs are a single
pace-range step; a long run with a marathon-pace finish is two.

1. Connect the watch to the computer by USB and unzip the `.fit` files.
2. Copy them into the watch's `GARMIN/NewFiles` folder (if they don't show up, try `GARMIN/Workouts`).
3. Eject, then on the watch go to Training, Workouts and pick the session.

Pace ranges are set from `settings.json`, so update your paces there first. The files have been tried on a
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

This is a draft shape, not coaching. Stop if the ankle hurts, and see a physio if it keeps happening.
