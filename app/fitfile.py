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

PAUSE_S = 10  # a gap between two records longer than this is a pause, not running
MIN_TAIL_M = 10  # a final partial km shorter than this isn't worth a split
ACTIVE = (0, 5)  # FIT intensity: active, interval
REPEAT = 6  # FIT workout step duration type: repeat until steps complete
MIN_REPS = 2  # laps are typed only for a workout with this many active steps; one is a plain run
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


def _messages(data: bytes) -> list:
    """Every data message in a FIT file."""
    decoder = FitDecoder(check_crc=False)
    document = decoder.decode_document(data)
    registry = decoder.developer_fields_by_data_index
    out = []
    for segment in document.segments:
        for raw in segment.records:
            record = _project(decoder, raw, registry)
            register_developer_field(record, registry)
            if isinstance(record.message, DataMessage):
                out.append(record.message)
    return out


def _active_steps(messages: list) -> int:
    """Active (run) steps in the FIT's workout, a repeat block counting its steps once per repeat."""
    steps = [m for m in messages if m.name == "workout_step"]
    active = [int(m.intensity) in ACTIVE if m.intensity is not None else False for m in steps]
    total = 0
    for i, m in enumerate(steps):
        if m.duration_type == REPEAT:
            first, times = m.duration_value or 0, m.target_value or 0
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
    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as z:
        name = next((n for n in z.namelist() if n.lower().endswith(".fit")), None)
        if name is None:
            raise ValueError("no .fit file in the activity ZIP")
        messages = _messages(z.read(name))

    records = [(m.timestamp, m.distance, m.heart_rate) for m in messages
               if m.name == "record" and m.timestamp is not None and m.distance is not None]
    laps_raw = [m for m in messages if m.name == "lap"]
    # Garmin attaches a one-step workout to plain runs, so only a real session types its laps
    typed = _active_steps(messages) >= MIN_REPS

    laps, dist, dur = [], 0.0, 0.0
    for m in laps_raw:
        dist += m.total_distance or 0.0
        dur += m.total_timer_time or 0.0
        kind = LAP_TYPES.get(int(m.intensity if m.intensity is not None else 0), "general") if typed else "general"
        laps.append({"endDistance": dist / 1000, "endDuration": dur, "lapType": kind})
    return {"splits": _splits(records), "laps": laps}
