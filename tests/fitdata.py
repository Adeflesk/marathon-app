"""Builds Garmin activity ZIPs (one .fit inside) for tests, with fit-tool."""
import io
import zipfile

from fit_tool.fit_file_builder import FitFileBuilder
from fit_tool.profile.messages.file_id_message import FileIdMessage
from fit_tool.profile.messages.lap_message import LapMessage
from fit_tool.profile.messages.record_message import RecordMessage
from fit_tool.profile.messages.workout_step_message import WorkoutStepMessage
from fit_tool.profile.profile_type import FileType, Intensity, Manufacturer

T0 = 1_790_000_000_000  # ms, an arbitrary start

INTENSITY = {"warmup": Intensity.WARMUP, "active": Intensity.ACTIVE, "rest": Intensity.REST,
             "recovery": Intensity.RECOVERY, "cooldown": Intensity.COOLDOWN}


def make_fit(records, laps, workout):
    """records: (seconds, metres, hr); laps: (metres, timer_seconds, intensity); workout: bool."""
    builder = FitFileBuilder(auto_define=True, min_string_size=50)
    fid = FileIdMessage()
    fid.type = FileType.ACTIVITY
    fid.manufacturer = Manufacturer.GARMIN.value
    fid.product = 0
    fid.serial_number = 1
    fid.time_created = T0
    builder.add(fid)
    if workout:
        step = WorkoutStepMessage()
        step.message_index = 0
        builder.add(step)
    for secs, metres, hr in records:
        r = RecordMessage()
        r.timestamp = T0 + round(secs * 1000)
        r.distance = metres
        r.heart_rate = hr
        builder.add(r)
    for n, (metres, secs, intensity) in enumerate(laps):
        lap = LapMessage()
        lap.total_distance = metres
        lap.total_timer_time = secs
        lap.intensity = INTENSITY[intensity]
        if workout:
            lap.workout_step_index = n
        builder.add(lap)
    return builder.build().to_bytes()


def make_zip(records, laps, workout):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("1_ACTIVITY.fit", make_fit(records, laps, workout))
    return buf.getvalue()
