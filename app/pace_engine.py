"""Pace maths. Everything is stored in seconds and km; format only for display."""
import sys


def fmt_pace(sec_per_km: float) -> str:
    s = int(round(sec_per_km))
    return f"{s // 60}:{s % 60:02d}"


def fmt_time(seconds: float) -> str:
    s = int(round(seconds))
    return f"{s // 3600}:{(s % 3600) // 60:02d}:{s % 60:02d}"


def parse_time(text: str) -> int:
    """'28:30' -> 1710 s, '1:55:10' -> 6910 s."""
    parts = [int(p) for p in text.split(":")]
    secs = 0
    for p in parts:
        secs = secs * 60 + p
    return secs


def km_to_mi(km: float) -> float:
    return km / 1.609344


def pace_per_mi(sec_per_km: float) -> float:
    return sec_per_km * 1.609344


def riegel(time_s: float, dist_km: float, target_km: float = 42.195, exponent: float = 1.06) -> float:
    return time_s * (target_km / dist_km) ** exponent


def paces_from_race(time_s: float, dist_km: float) -> dict:
    """Rough training paces (sec/km) from a recent race or hard effort.

    The multipliers are rules of thumb, not gospel. Marathon pace comes from a
    Riegel projection, then a small fatigue allowance is added because Riegel
    flatters runners with a modest weekly mileage.
    """
    mp = riegel(time_s, dist_km) / 42.195 * 1.02
    return {
        "marathon": round(mp),
        "tempo": round(mp * 0.95),
        "long": round(mp * 1.14),
        "easy": round(mp * 1.19),
    }


if __name__ == "__main__":
    # python -m app.pace_engine 10 52:30   (10 km in 52:30)
    if len(sys.argv) != 3:
        print("usage: python -m app.pace_engine <distance_km> <time h:mm:ss or mm:ss>")
        sys.exit(1)
    d, t = float(sys.argv[1]), parse_time(sys.argv[2])
    print(f"Projected marathon: {fmt_time(riegel(t, d))}")
    for k, v in paces_from_race(t, d).items():
        print(f"{k:9s} {fmt_pace(v)}/km  ({fmt_pace(pace_per_mi(v))}/mi)")
    print("Paste these (in seconds) into settings.json under 'paces'.")
