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

Smashrun's API Explorer gives you an access token for your own account. Put it in `.env` as
`SMASHRUN_TOKEN=...`. The sync code has not been tested against a live account. If the sync button
reports an error, the message says what Smashrun returned.

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

## Strength

- Open **Equipment** and tick or edit what you own. Your kit is pre-filled (barbell and plates,
  dumbbells 2.5-35 kg, 12 and 16 kg kettlebells, 5 kg medicine ball, box, rings). Check the bar weight
  (assumed 20 kg) and that you have one pair of each plate. Bench, rack and bands are on. The pull-up bar is off.
- **Strength** shows two sessions a week: Tuesday B (upper body, trunk, light kettlebell work) and
  Thursday A (single-leg legs, calves, glutes, ankle balance). Exercises are picked from the equipment
  you have, and a few rotate week to week.
- Volume follows the run plan: 2 x 10-12 while rebuilding, 3 x 6-8 in build weeks, lower on cutback weeks
  and when a hard run session (threshold or harder) is the day before or after, low-volume heavy in peak weeks,
  tapering to nothing in race week.
- A tough check-in (ankle pain 3+ or a hard week) also trims the next week's strength work.

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
  | Taper and race week | A short marathon-pace session |

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
