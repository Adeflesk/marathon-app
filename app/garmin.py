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
from .sessions import pace_s

# (slower seconds, faster seconds) around the target pace
EASY_BAND = (30, -30)
HARD_BAND = (10, -10)
WARMUP_KM = 1  # easy and long runs open with an untargeted km so the watch doesn't nag a cold start


INTENSITY = {"warmup": Intensity.WARMUP, "active": Intensity.ACTIVE, "recovery": Intensity.RECOVERY,
             "cooldown": Intensity.COOLDOWN}


def _step(name, intensity, pace, band, km=None, minutes=None, seconds=None, note=None):
    """One FIT step. pace None means an open target (recoveries), as in Garmin's own workouts."""
    s = WorkoutStepMessage()
    s.workout_step_name = name[:15]
    s.intensity = intensity
    if km is not None:
        s.duration_type = WorkoutStepDuration.DISTANCE
        s.duration_distance = km * 1000.0
    else:
        s.duration_type = WorkoutStepDuration.TIME
        s.duration_time = seconds if seconds is not None else minutes * 60.0
    s.target_value = 0
    if pace is None:
        s.target_type = WorkoutStepTarget.OPEN
    else:
        s.target_type = WorkoutStepTarget.SPEED
        slow, fast = pace + band[0], pace + band[1]
        s.custom_target_speed_low = 1000.0 / slow   # m/s, slower end of the range
        s.custom_target_speed_high = 1000.0 / fast  # m/s, faster end of the range
    if note:
        s.notes = note
    return s


def _repeat(first_step: int, reps: int) -> WorkoutStepMessage:
    """Go back to first_step and run the block reps times in all."""
    s = WorkoutStepMessage()
    s.duration_type = WorkoutStepDuration.REPEAT_UNTIL_STEPS_CMPLT
    s.duration_step = first_step
    s.target_repeat_steps = reps
    return s


def _structured(steps: list, paces: dict) -> list:
    out = []

    def add(st):
        pace = None if st["pace"] is None else pace_s(st["pace"], paces)
        band = EASY_BAND if pace is not None and pace >= paces["long"] else HARD_BAND
        name = st["label"] if pace is None else f"{st['label']} {fmt_pace(pace)}"
        out.append(_step(name, INTENSITY[st["intensity"]], pace, band,
                         km=st.get("km"), seconds=st.get("seconds"), note=st.get("note")))

    for st in steps:
        if "repeat" in st:
            first = len(out)
            for inner in st["steps"]:
                add(inner)
            out.append(_repeat(first, st["repeat"]))
        else:
            add(st)
    return out


def steps_for(w: dict, paces: dict) -> list:
    """Translate a planned workout dict into FIT steps."""
    easy, longp, mp = paces["easy"], paces["long"], paces["marathon"]
    if "steps" in w:
        return _structured(w["steps"], paces)
    kind = w["type"]
    label = lambda p: fmt_pace(p)
    if kind == "race":
        return [_step(f"Race {label(mp)}", Intensity.ACTIVE, mp, (15, -10), km=w["km"])]
    wu = WARMUP_KM if w["km"] > WARMUP_KM else 0
    first = [_step("Warm up", Intensity.WARMUP, None, None, km=wu)] if wu else []
    if kind == "long":
        mp_km = w.get("mp_km", 0)
        if mp_km:
            return first + [
                _step(f"Easy {label(longp)}", Intensity.ACTIVE, longp, EASY_BAND, km=w["km"] - mp_km - wu),
                _step(f"MP {label(mp)}", Intensity.ACTIVE, mp, HARD_BAND, km=mp_km),
            ]
        return first + [_step(f"Long {label(longp)}", Intensity.ACTIVE, longp, EASY_BAND, km=w["km"] - wu)]
    return first + [_step(f"Easy {label(easy)}", Intensity.ACTIVE, easy, EASY_BAND, km=w["km"] - wu)]


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
        seen: set[str] = set()
        for w in workouts:
            if w["km"] > 0 and not w.get("skipped"):
                name = filename(w)
                if name in seen:  # two runs alike on one day, after a move
                    name = name.replace(".fit", "-2.fit")
                seen.add(name)
                z.writestr(name, build_fit(w, paces))
    return buf.getvalue()
