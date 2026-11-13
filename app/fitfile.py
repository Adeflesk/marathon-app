"""Garmin activity FIT file -> the km splits and laps that review.py reads.

Pure: ZIP bytes in, dict out. Both lists are cumulative, like the stored rows: splits carry
`distance` (km), `seconds` and `heartRate`; laps carry `endDistance` (km), `endDuration`
(s) and `lapType` ("work" for an active rep when the FIT holds a workout with 2+ active steps,
otherwise "general" for every lap).
"""
import io
import threading
import zipfile

from fit_tool.data_message import DataMessage
from fit_tool.decoder import FitDecoder, register_developer_field
from fit_tool.exceptions import FitRecordError
from fit_tool.field import Field
from fit_tool.wire.decoder import WireDecoder

PAUSE_S = 10  # a gap between two records longer than this is a pause, not running
MIN_TAIL_M = 10  # a final partial km shorter than this isn't worth a split
ACTIVE = (0, 5)  # FIT intensity: active, interval
REPEAT = 6  # FIT workout step duration type: repeat until steps complete
MIN_REPS = 2  # laps are typed only for a workout with this many active steps; one is a plain run
FILE_CRC = 2  # bytes after each segment's records
# FIT intensity enum: 0 active, 1 rest, 2 warmup, 3 cooldown, 4 recovery, 5 interval, 6 other
LAP_TYPES = {0: "work", 1: "rest", 2: "warmup", 3: "cooldown", 4: "rest", 5: "work"}


_LENIENT = threading.Lock()


def _read_strings_leniently(self, bytes_buffer, offset=0, size=None):
    """fit-tool's Field.read_strings_from_bytes, but a byte that isn't UTF-8 becomes U+FFFD."""
    end = None if size is None else offset + size
    text = bytes(bytes_buffer[offset:end]).decode("utf-8", errors="replace")
    self.encoded_values = [x for x in text.split("\u0000")[:-1] if x]


def _project(decoder, raw, registry):
    """Project one raw record. Real files carry strings that aren't valid UTF-8 (workout step
    names, device strings), which makes fit-tool reject the whole message, numbers and all. On
    that error only, project it again with a lenient string decode, patched in for that one
    call under a lock and restored after. Any other decode error propagates."""
    try:
        return decoder._project_raw(raw, registry)  # private: see requirements.txt
    except FitRecordError as exc:
        if not isinstance(exc.__cause__, UnicodeError):
            raise
    with _LENIENT:
        original = Field.read_strings_from_bytes
        Field.read_strings_from_bytes = _read_strings_leniently
        try:
            return decoder._project_raw(raw, registry)
        finally:
            Field.read_strings_from_bytes = original


def _messages(data: bytes):
    """Every data message in a FIT file, one at a time: each raw record is read from the buffer and projected
    as it comes, so only the message in hand is held, never the whole decoded document (a 10 km run's FIT
    held at once took ~225 MB). Chained segments follow one another as in fit-tool's own decode."""
    decoder = FitDecoder(check_crc=False)  # projection state: developer fields, component accumulators
    registry = decoder.developer_fields_by_data_index
    wire = WireDecoder(check_crc=False)
    offset = 0
    while offset < len(data):
        for raw in wire.iter_raw_records(data, offset=offset):
            record = _project(decoder, raw, registry)
            register_developer_field(record, registry)
            if isinstance(record.message, DataMessage):
                yield record.message
        offset = wire.crc_offset + FILE_CRC
        if not WireDecoder._looks_like_header(data, offset):
            break


def _active_steps(steps: list[tuple]) -> int:
    """Active (run) steps in the FIT's workout, a repeat block counting its steps once per repeat.
    steps: (intensity, duration_type, duration_value, target_value) per workout_step message."""
    active = [intensity in ACTIVE if intensity is not None else False for intensity, *_ in steps]
    total = 0
    for i, (_, duration_type, duration_value, target_value) in enumerate(steps):
        if duration_type == REPEAT:
            first, times = duration_value or 0, target_value or 0
            total += sum(active[first:i]) * max(times - 1, 0)
        elif active[i]:
            total += 1
    return total


def _splits(records: list[tuple[float, float, int | None]]) -> list[dict]:
    """records: (ms timestamp, metres, hr). One split per whole km plus a final partial one,
    time counted only while moving and interpolated at each km boundary."""
    out, secs, nxt, hrs = [], 0.0, 1000.0, []
    prev = None
    for ts, dist, hr in records:
        if prev is not None:
            pts, pdist, psecs = prev
            gap = (ts - pts) / 1000
            step = gap if gap <= PAUSE_S else 0.0
            secs = psecs + step
            while dist >= nxt and dist > pdist:
                at = psecs + step * (nxt - pdist) / (dist - pdist)
                out.append({"distance": nxt / 1000, "seconds": at,
                            "heartRate": round(sum(hrs) / len(hrs)) if hrs else None})
                hrs, nxt = [], nxt + 1000.0
        if hr:
            hrs.append(hr)
        prev = (ts, dist, secs)
    if prev is not None and prev[1] - (nxt - 1000.0) > MIN_TAIL_M:
        out.append({"distance": prev[1] / 1000, "seconds": prev[2],
                    "heartRate": round(sum(hrs) / len(hrs)) if hrs else None})
    return out


def details(zip_bytes: bytes) -> dict:
    """Keeps only (timestamp, distance, hr) per record, lap totals and workout-step info as they're decoded."""
    records: list[tuple[float, float, int | None]] = []
    laps_raw: list[tuple[float, float, int]] = []
    steps: list[tuple] = []
    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as z:
        name = next((n for n in z.namelist() if n.lower().endswith(".fit")), None)
        if name is None:
            raise ValueError("no .fit file in the activity ZIP")
        data = z.read(name)
    for m in _messages(data):
        if m.name == "record":
            if m.timestamp is not None and m.distance is not None:
                records.append((m.timestamp, m.distance, m.heart_rate))
        elif m.name == "lap":
            laps_raw.append((m.total_distance or 0.0, m.total_timer_time or 0.0,
                             int(m.intensity if m.intensity is not None else 0)))
        elif m.name == "workout_step":
            steps.append((int(m.intensity) if m.intensity is not None else None, m.duration_type,
                          m.duration_value, m.target_value))
    # Garmin attaches a one-step workout to plain runs, so only a real session types its laps
    typed = _active_steps(steps) >= MIN_REPS

    laps, dist, dur = [], 0.0, 0.0
    for metres, timer, intensity in laps_raw:
        dist += metres
        dur += timer
        kind = LAP_TYPES.get(intensity, "general") if typed else "general"
        laps.append({"endDistance": dist / 1000, "endDuration": dur, "lapType": kind})
    return {"splits": _splits(records), "laps": laps}
