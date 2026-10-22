"""Moved and skipped sessions, applied to a freshly generated plan.

Pure: the stored facts are `db.moves()` rows, keyed by a session's original planned date and identity ("run",
or the strength key "A"/"B"). A row's `new_date` is where it moved to, or None when it was skipped. A row
whose session no longer exists in the plan (settings changed) matches nothing and is ignored.
"""
from datetime import date, timedelta

STRENGTH = ("A", "B")


def index(rows) -> dict[tuple[date, str], date | None]:
    """(original date, session) -> new date, or None for a skip."""
    return {(date.fromisoformat(r["date"]), r["session"]):
            (date.fromisoformat(r["new_date"]) if r["new_date"] else None) for r in rows}


def shift(item: dict, session: str, moved: dict) -> None:
    """Mark `item` with its planned date and, if the user moved or skipped it, apply that."""
    item["orig_date"] = item["date"]
    key = (item["date"], session)
    if key not in moved:
        return
    if moved[key] is None:
        item["skipped"] = True
    else:
        item["moved_from"], item["date"] = item["date"], moved[key]


def relocate(weeks) -> None:
    """Put sessions moved past their week's Sunday into the week holding their new date; keep every week in date order."""
    for field in ("workouts", "strength"):
        for w in weeks:
            end = w["start"] + timedelta(days=6)
            gone = [x for x in w.get(field, []) if x["date"] > end]
            for x in gone:
                home = next((h for h in weeks if h["start"] <= x["date"] <= h["start"] + timedelta(days=6)), None)
                if home is None:  # outside the plan; the routes never allow this
                    continue
                w[field].remove(x)
                home.setdefault(field, []).append(x)
    for w in weeks:  # a move within a week can pass another day's session too
        for field in ("workouts", "strength"):
            w.get(field, []).sort(key=lambda y: y["date"])


def day_items(weeks, day: date) -> list[tuple[str, dict]]:
    """The non-skipped runs ("run", workout) and strength sessions (key, session) on `day`."""
    out = []
    for w in weeks:
        out += [("run", wo) for wo in w["workouts"] if wo["date"] == day and not wo.get("skipped")]
        out += [(s["key"], s) for s in w.get("strength", []) if s["date"] == day and not s.get("skipped")]
    return out


def _hard(wo: dict) -> bool:
    return wo["type"] in ("long", "race") or "steps" in wo


def clash(weeks, session: str, day: date) -> dict | None:
    """What blocks moving `session` from `day` to the next day, or None.

    A long run or speed session blocks anything; a run blocks a run; a strength session blocks the other one.
    """
    for kind, item in day_items(weeks, day + timedelta(days=1)):
        if kind == "run" and (_hard(item) or session == "run"):
            return item
        if kind in STRENGTH and session in STRENGTH and kind != session:
            return item
    return None


def can_move(day: date, weeks, race: date) -> bool:
    """Tomorrow is before race day and inside the plan."""
    last = weeks[-1]["start"] + timedelta(days=6)
    return day + timedelta(days=1) < race and day + timedelta(days=1) <= last


def session_name(session: str, item: dict) -> str:
    if session in STRENGTH:
        return f"Strength {session}"
    if item["type"] == "long":
        return "long run"
    if "steps" in item:
        return "speed session"
    return "easy run" if item["type"] == "easy" else f"{item['type']} run"
