"""Build Garmin .fit workout files from planned sessions.

Copy the files to the watch over USB. Pace targets are ranges (in seconds per km) so the
watch only nags when you drift well outside them.
"""
import io
import zipfile
from datetime import datetime, timezone

from fit_tool.fit_file_builder import FitFileBuilder
from fit_tool.profile.messages.file_id_message import FileIdMessage
from fit_tool.profile.messages.workout_message import WorkoutMessage
from fit_tool.profile.messages.workout_step_message import WorkoutStepMessage
from fit_tool.profile.profile_type import (
    FileType, Intensity, Manufacturer, Sport, WorkoutStepDuration, WorkoutStepTarget,
)

from .pace_engine import fmt_pace
from .plan import _half

# (slower seconds, faster seconds) around the target pace
EASY_BAND = (30, -30)
HARD_BAND = (10, -10)


def _step(name, intensity, pace, band, km=None, minutes=None):
    s = WorkoutStepMessage()
    s.workout_step_name = name[:15]
    s.intensity = intensity
    if km is not None:
        s.duration_type = WorkoutStepDuration.DISTANCE
        s.duration_distance = km * 1000.0
    else:
        s.duration_type = WorkoutStepDuration.TIME
        s.duration_time = minutes * 60.0
    s.target_type = WorkoutStepTarget.SPEED
    s.target_value = 0
    slow, fast = pace + band[0], pace + band[1]
    s.custom_target_speed_low = 1000.0 / slow   # m/s, slower end of the range
    s.custom_target_speed_high = 1000.0 / fast  # m/s, faster end of the range
    return s


def steps_for(w: dict, paces: dict) -> list:
    """Translate a planned workout dict into FIT steps."""
    easy, longp, mp, tempo = paces["easy"], paces["long"], paces["marathon"], paces["tempo"]
    kind = w["type"]
    label = lambda p: fmt_pace(p)
    if kind == "tempo":
        minutes = w.get("tempo_min", 20)
        tempo_km = minutes * 60 / tempo
        cool_km = max(1.0, _half(w["km"] - 2 - tempo_km))  # cool-down absorbs the rest of the planned distance
        return [
            _step(f"WU {label(easy)}", Intensity.WARMUP, easy, EASY_BAND, km=2),
            _step(f"Tempo {label(tempo)}", Intensity.ACTIVE, tempo, HARD_BAND, minutes=minutes),
            _step(f"CD {label(easy)}", Intensity.COOLDOWN, easy, EASY_BAND, km=cool_km),
        ]
    if kind == "long":
        mp_km = w.get("mp_km", 0)
        if mp_km:
            return [
                _step(f"Easy {label(longp)}", Intensity.ACTIVE, longp, EASY_BAND, km=w["km"] - mp_km),
                _step(f"MP {label(mp)}", Intensity.ACTIVE, mp, HARD_BAND, km=mp_km),
            ]
        return [_step(f"Long {label(longp)}", Intensity.ACTIVE, longp, EASY_BAND, km=w["km"])]
    if kind == "race":
        return [_step(f"Race {label(mp)}", Intensity.ACTIVE, mp, (15, -10), km=w["km"])]
    return [_step(f"Easy {label(easy)}", Intensity.ACTIVE, easy, EASY_BAND, km=w["km"])]


def workout_name(w: dict) -> str:
    return f"{w['date'].strftime('%d%b')} {w['type']} {w['km']:g}k"[:30]


def build_fit(w: dict, paces: dict) -> bytes:
    steps = steps_for(w, paces)
    now_ms = round(datetime.now(timezone.utc).timestamp() * 1000)

    fid = FileIdMessage()
    fid.type = FileType.WORKOUT
    fid.manufacturer = Manufacturer.DEVELOPMENT.value
    fid.product = 0
    fid.time_created = now_ms
    fid.serial_number = 0x12345678

    wm = WorkoutMessage()
    wm.sport = Sport.RUNNING
    wm.num_valid_steps = len(steps)
    wm.workout_name = workout_name(w)

    builder = FitFileBuilder(auto_define=True, min_string_size=50)
    builder.add(fid)
    builder.add(wm)
    for i, s in enumerate(steps):
        s.message_index = i
        builder.add(s)
    return builder.build().to_bytes()


def filename(w: dict) -> str:
    return f"{w['date'].isoformat()}-{w['type']}-{w['km']:g}km.fit"


def week_zip(workouts: list[dict], paces: dict) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for w in workouts:
            if w["km"] > 0:
                z.writestr(filename(w), build_fit(w, paces))
    return buf.getvalue()
