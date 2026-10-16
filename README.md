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

Runs are Monday (easy), Wednesday (easy, tempo from week 8), Saturday (easy) and Sunday (long); nothing on
Tuesday or Thursday. Strength is Tuesday and Thursday. Change them in `settings.json`, for example:

```json
{
  "run_days": {"mon": "easy", "wed": "quality", "sat": "easy", "sun": "long"},
  "strength_days": {"B": "tue", "A": "thu"}
}
```

Roles are `easy`, `quality` (tempo from week 8) and `long`. Use as many easy or quality days as you like, but `long` needs exactly one day.

## Tuning

Everything is in `settings.json` (create it next to `README.md`; any key you leave out uses the default
in `app/config.py`):

```json
{
  "paces": {"easy": 405, "long": 390, "marathon": 341, "tempo": 325},
  "peak_weekly_km": 55,
  "weekly_step_km": 3
}
```

Paces are seconds per km. After a 5K or 10K time trial, work out new ones with:

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
  and when a tempo run is the day before or after, low-volume heavy in peak weeks, tapering to nothing in race week.
- A tough check-in (ankle pain 3+ or a hard week) also trims the next week's strength work.

## Garmin Forerunner 255

Each run in the week table has a "Garmin .fit" link, and "Garmin files for the week" gives a zip of the
whole week. Workouts have warm-up, pace-target and cool-down steps (tempo and marathon-pace sessions) or a
single pace-range step (easy and long runs).

1. Connect the watch to the computer by USB and unzip the `.fit` files.
2. Copy them into the watch's `GARMIN/NewFiles` folder (if they don't show up, try `GARMIN/Workouts`).
3. Eject, then on the watch go to Training, Workouts and pick the session.

Pace ranges are set from `settings.json`, so update your paces there first. I couldn't test these files on a
real watch, so try one first and tell me if the watch rejects it.

## How the plan works

- Weeks 1-3: 25 km a week, longest run 10 km (rebuild).
- From week 4: long runs start at 12 km and grow by 2 km, weekly volume by 3 km, with a cutback every
  fourth week. Tempo work starts around week 8, marathon-pace finishes on long runs around week 11.
- Three-week taper, then race week.
- The weekly check-in (feel 1-5, ankle pain 0-10) trims the following week by 10% or 20% when it's
  a rough one. The plan only ever adjusts down.

This is a draft shape, not coaching. Stop if the ankle hurts, and see a physio if it keeps happening.
