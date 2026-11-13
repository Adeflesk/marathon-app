"""Garmin activity FIT file -> the km splits and laps that review.py reads.

Pure: ZIP bytes in, dict out. Both lists are cumulative, like Smashrun's: splits carry
`distance` (km), `seconds` and `heartRate`; laps carry `endDistance` (km), `endDuration`
(s) and `lapType` ("work" for an active rep, "general" for every lap of a free run).
"""
import io
import zipfile

from fit_tool.data_message import DataMessage
from fit_tool.decoder import FitDecoder, register_developer_field

PAUSE_S = 10  # a gap between two records longer than this is a pause, not running
NO_STEP = 65535  # FIT's "invalid" for a lap's workout step index
# FIT intensity enum: 0 active, 1 rest, 2 warmup, 3 cooldown, 4 recovery, 5 interval, 6 other
LAP_TYPES = {0: "work", 1: "rest", 2: "warmup", 3: "cooldown", 4: "rest", 5: "work"}


def _messages(data: bytes) -> list:
    """Every data message in a FIT file. A record that won't decode (real files carry device
    strings that aren't valid UTF-8) is skipped rather than failing the whole run."""
    decoder = FitDecoder(check_crc=False)
    document = decoder.decode_document(data)
    registry = decoder.developer_fields_by_data_index
    out = []
    for segment in document.segments:
        for raw in segment.records:
            try:
                record = decoder._project_raw(raw, registry)
            except Exception:
                continue
            register_developer_field(record, registry)
            if isinstance(record.message, DataMessage):
                out.append(record.message)
    return out


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
    if prev is not None and prev[1] - (nxt - 1000.0) > 10:
        out.append({"distance": prev[1] / 1000, "seconds": prev[2],
                    "heartRate": round(sum(hrs) / len(hrs)) if hrs else None})
    return out


def details(zip_bytes: bytes) -> dict:
    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as z:
        name = next(n for n in z.namelist() if n.lower().endswith(".fit"))
        messages = _messages(z.read(name))

    records = [(m.timestamp, m.distance, m.heart_rate) for m in messages
               if m.name == "record" and m.timestamp is not None and m.distance is not None]
    laps_raw = [m for m in messages if m.name == "lap"]
    has_workout = any(m.name == "workout_step" for m in messages) or any(
        m.workout_step_index not in (None, NO_STEP) for m in laps_raw)

    laps, dist, dur = [], 0.0, 0.0
    for m in laps_raw:
        dist += m.total_distance or 0.0
        dur += m.total_timer_time or 0.0
        kind = LAP_TYPES.get(int(m.intensity if m.intensity is not None else 0), "general") if has_workout else "general"
        laps.append({"endDistance": dist / 1000, "endDuration": dur, "lapType": kind})
    return {"splits": _splits(records), "laps": laps}
