from datetime import date, timedelta

import pytest

from app import moves
from app.config import load_settings, race_date
from app.plan import generate

D0 = date(2026, 10, 19)  # plan week 1, a Monday


@pytest.fixture
def weeks():
    ws = generate(load_settings(), D0)
    for w in ws:  # strength B on Tuesday and A on Thursday, as main.attach_strength builds them
        w["strength"] = [{"key": "B", "date": w["start"] + timedelta(days=1)},
                         {"key": "A", "date": w["start"] + timedelta(days=3)}]
    return ws


def row(day, session, new):
    return {"date": day, "session": session, "new_date": new, "created": ""}


def run_on(weeks, day):
    return next(wo for w in weeks for wo in w["workouts"] if wo["date"] == day)


def apply_runs(weeks, rows):
    moved = moves.index(rows)
    for w in weeks:
        for wo in w["workouts"]:
            moves.shift(wo, "run", moved)
    moves.relocate(weeks)


def test_shift_moves_and_marks(weeks):
    sat = run_on(weeks, date(2026, 10, 24))
    moves.shift(sat, "run", moves.index([row("2026-10-24", "run", "2026-10-25")]))
    assert sat["date"] == date(2026, 10, 25)
    assert sat["moved_from"] == date(2026, 10, 24) and sat["orig_date"] == date(2026, 10, 24)
    assert not sat.get("skipped")


def test_shift_skip(weeks):
    sat = run_on(weeks, date(2026, 10, 24))
    moves.shift(sat, "run", moves.index([row("2026-10-24", "run", None)]))
    assert sat["skipped"] is True and sat["date"] == date(2026, 10, 24)
    assert "moved_from" not in sat


def test_shift_strength_by_key(weeks):
    a, b = weeks[0]["strength"][1], weeks[0]["strength"][0]
    moved = moves.index([row("2026-10-22", "A", "2026-10-23")])
    moves.shift(a, "A", moved)
    moves.shift(b, "B", moved)
    assert a["date"] == date(2026, 10, 23) and b["date"] == date(2026, 10, 20)


def test_stale_move_ignored(weeks):
    before = [[wo["date"] for wo in w["workouts"]] for w in weeks]
    apply_runs(weeks, [row("2026-10-22", "run", "2026-10-23")])  # no run on Thursday
    assert [[wo["date"] for wo in w["workouts"]] for w in weeks] == before


def test_relocate_sunday_into_monday(weeks):
    apply_runs(weeks, [row("2026-10-25", "run", "2026-10-26")])
    assert date(2026, 10, 26) not in [wo["date"] for wo in weeks[0]["workouts"]]
    mondays = [wo for wo in weeks[1]["workouts"] if wo["date"] == date(2026, 10, 26)]
    assert len(mondays) == 2 and any(wo.get("moved_from") == date(2026, 10, 25) for wo in mondays)
    assert [wo["date"] for wo in weeks[1]["workouts"]] == sorted(wo["date"] for wo in weeks[1]["workouts"])


def test_clash_rules(weeks):
    # a run onto Sunday's long run
    assert moves.clash(weeks, "run", date(2026, 10, 24))["type"] == "long"
    # a run onto Wednesday's speed session (strides, week 2)
    assert moves.clash(weeks, "run", date(2026, 10, 27)) is not None
    # strength A (Thu) onto Friday, a rest day; and onto an easy-run day (Sat)
    assert moves.clash(weeks, "A", date(2026, 10, 22)) is None
    assert moves.clash(weeks, "A", date(2026, 10, 23)) is None
    # strength B (Tue) onto week 2's speed session
    assert moves.clash(weeks, "B", date(2026, 10, 27)) is not None
    # strength B onto A's day, and strength onto the long run
    assert moves.clash(weeks, "B", date(2026, 10, 21))["key"] == "A"
    assert moves.clash(weeks, "A", date(2026, 10, 24))["type"] == "long"
    # a run onto a strength-only day (Mon run moved to Tue)
    assert moves.clash(weeks, "run", date(2026, 10, 19)) is None


def test_clash_ignores_skipped(weeks):
    apply_runs(weeks, [row("2026-10-25", "run", None)])
    assert moves.clash(weeks, "run", date(2026, 10, 24)) is None


def test_can_move_stops_before_race(weeks):
    race = race_date(load_settings())
    assert moves.can_move(date(2026, 10, 22), weeks, race)
    assert not moves.can_move(race - timedelta(days=1), weeks, race)
    assert not moves.can_move(race, weeks, race)


def test_session_names(weeks):
    assert moves.session_name("run", run_on(weeks, date(2026, 10, 24))) == "easy run"
    assert moves.session_name("run", run_on(weeks, date(2026, 10, 25))) == "long run"
    assert moves.session_name("run", run_on(weeks, date(2026, 10, 28))) == "speed session"
    assert moves.session_name("A", weeks[0]["strength"][1]) == "Strength A"
