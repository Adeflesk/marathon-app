"""Settings: race date, paces and plan shape. Edit settings.json, not this file."""
import json
import os
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SETTINGS_PATH = ROOT / "settings.json"


def load_env() -> None:
    """Tiny .env loader so there's no extra dependency."""
    env = ROOT / ".env"
    if not env.exists():
        return
    for line in env.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


load_env()

DEFAULTS = {
    "race_name": "Barcelona Marathon",
    "race_date": "2027-03-14",
    "goal_time": "3:59:00",
    # Fixed so the plan doesn't slide forward each day. Must be a Monday.
    "plan_start": "2026-10-19",
    # seconds per km. Easy is from the 16 Oct run (about 6:45/km). Update after a time trial.
    "paces": {
        "easy": 405,
        "long": 390,
        "marathon": 341,
        "tempo": 325,
        # about 5 km race pace, for VO2 reps and strides
        "interval": 300,
        # MP - 9 s, for Hansons-style "strength" reps
        "subthreshold": 332,
    },
    "base_weekly_km": 25,
    "base_weeks": 3,
    "peak_weekly_km": 60,
    "weekly_step_km": 3,
    "max_long_run_km": 32,
    # No running on Tuesday or Thursday. Roles: easy, quality (tempo work later), long.
    "run_days": {"mon": "easy", "wed": "quality", "sat": "easy", "sun": "long"},
    # Which weekday each strength session falls on.
    "strength_days": {"B": "tue", "A": "thu"},
}


REPLACE_KEYS = {"run_days"}  # a custom value replaces the default, not merges


def load_settings() -> dict:
    s = json.loads(json.dumps(DEFAULTS))
    if SETTINGS_PATH.exists():
        user = json.loads(SETTINGS_PATH.read_text())
        for k, v in user.items():
            if k in REPLACE_KEYS:
                s[k] = v
            elif isinstance(v, dict) and isinstance(s.get(k), dict):
                s[k].update(v)
            else:
                s[k] = v
    return s


def race_date(s: dict) -> date:
    return date.fromisoformat(s["race_date"])


def next_monday(today: date) -> date:
    return today + timedelta(days=(7 - today.weekday()) % 7 or 7)
