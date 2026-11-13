"""Taking the recovery trim (or "make the next run easy") and how the view applies it."""
import copy
from datetime import date, timedelta

import pytest
from fastapi.testclient import TestClient

from app import db, main, recovery, sessions, strength, view
from app.config import load_settings
from app.plan import _half

MON_W8 = date(2026, 12, 7)  # a Build week: Mon easy, Wed threshold (4 reps), Sat easy, Sun long
TUE_W8 = MON_W8 + timedelta(days=1)
RACE_MON = date(2027, 3, 8)  # Race week


def facts(**over) -> view.Facts:
    base = dict(settings=load_settings(), actual={}, details={}, checkins={}, moves=[], goals=[], results=[],
                logs=[], checks=[], tests=[], snacks=[], fuel_days=set(), last_sync=None, wellness=[], trims=[],
                equipment=strength.load_equipment())
    return view.Facts(**{**base, **over})


def weeks(t=TUE_W8, **over):
    return view.build_view(facts(**over), t)[1]


def trim(day: date, kind="trim", start: date | None = None):
    """A stored choice: pressed on `day`, applying from `start` (that day unless a run was already synced on it)."""
    return {"date": day.isoformat(), "kind": kind, "start": (start or day).isoformat()}


def reps(wo: dict) -> int:
    return sum(st["repeat"] for st in wo.get("steps", []) if "repeat" in st)


def by_day(w: dict) -> dict:
    return {wo["date"]: wo for wo in w["workouts"]}


def test_trim_scales_rest_of_week_only():
    plain = by_day(weeks()[7])
    w = weeks(trims=[trim(TUE_W8)])[7]
    trimmed = by_day(w)
    assert w["recovery_trim"] == TUE_W8
    mon, wed, sat, sun = sorted(plain)
    assert trimmed[mon]["km"] == plain[mon]["km"]  # before the trim date: as planned
    assert trimmed[sat]["km"] == _half(plain[sat]["km"] * 0.9)
    assert trimmed[sun]["km"] == _half(plain[sun]["km"] * 0.9)
    assert reps(trimmed[wed]) < reps(plain[wed])
    assert trimmed[wed]["km"] < plain[wed]["km"]


def test_trim_doesnt_stack_on_tired_checkin():
    tired = {7: {"week": 7, "feel": 2, "pain": 0, "note": ""}}  # 0.9 next week
    alone = by_day(weeks(checkins=tired)[7])
    both = by_day(weeks(checkins=tired, trims=[trim(TUE_W8)])[7])
    mon, wed, sat, sun = sorted(alone)
    for d in (mon, sat, sun):  # still 0.9, never 0.81
        assert both[d]["km"] == alone[d]["km"]
    assert reps(both[wed]) == reps(alone[wed]) - 1  # but the trim's rep comes off


def test_trim_drops_a_rep_never_below_two():
    wo = {"type": "threshold", "steps": copy.deepcopy(weeks()[7]["workouts"][1]["steps"])}
    paces = load_settings()["paces"]
    assert reps(wo) == 4
    assert sessions.drop_rep(wo, paces) and reps(wo) == 3
    assert wo["km"] == _half(sessions.session_km(wo["steps"], paces)) and wo["note"].startswith("2 km WU, 3 ×")
    assert sessions.drop_rep(wo, paces) and reps(wo) == 2
    assert not sessions.drop_rep(wo, paces) and reps(wo) == 2
    # a taper session already at two reps keeps them, and gets a shorter rep instead
    taper_wed = date(2027, 2, 24)
    plain = by_day(weeks(taper_wed)[18])[taper_wed]
    trimmed = by_day(weeks(taper_wed, trims=[trim(taper_wed)])[18])[taper_wed]
    assert reps(plain) == 2 and reps(trimmed) == 2
    assert trimmed["steps"] != plain["steps"] and trimmed["km"] < plain["km"]


def _minus_one(steps: list) -> list:
    """The steps with one rep off the first repeat block that has more than two."""
    out = copy.deepcopy(steps)
    block = next((st for st in out if "repeat" in st and st["repeat"] > 2), None)
    if block:
        block["repeat"] -= 1
    return out


@pytest.mark.parametrize("tired", [False, True])
def test_trimmed_session_is_the_untrimmed_one_minus_one_rep(tired):
    """Same rep length, same cool-down, one rep fewer. A session with no rep to drop (2 reps, or `specific`'s
    MP blocks) is scaled as a 0.9 check-in would instead, so the trim still does something."""
    paces = load_settings()["paces"]
    scaled, dropped = set(), 0
    for w in view.build_view(facts(), MON_W8)[1]:
        if w["phase"] in ("Rebuild", "Race week"):
            continue
        n = w["week"]
        checkins = {n - 1: {"week": n - 1, "feel": 2, "pain": 0, "note": ""}} if tired else {}
        raw = next(wo for wo in weeks(w["start"])[n - 1]["workouts"] if "steps" in wo)
        plain = next(wo for wo in weeks(w["start"], checkins=checkins)[n - 1]["workouts"] if "steps" in wo)
        got = next(wo for wo in weeks(w["start"], checkins=checkins, trims=[trim(w["start"])])[n - 1]["workouts"]
                   if "steps" in wo)
        assert got["km"] <= plain["km"]
        if _minus_one(plain["steps"]) != plain["steps"]:
            assert got["steps"] == _minus_one(plain["steps"]), n
            dropped += 1
        else:
            expect = copy.deepcopy(raw)
            sessions.scale_session(expect, 0.9, paces)  # min(check-in factor, 0.9): 0.9 either way here
            assert (got["steps"], got["km"], got["note"]) == (expect["steps"], expect["km"], expect["note"]), n
            if not tired:
                assert got["steps"] != plain["steps"], n
            scaled.add(plain["type"])
    assert {"specific", "strength"} <= scaled  # Peak's MP blocks and the 2-rep taper session
    assert dropped >= 8


def run(i: int, km: float) -> dict:
    return {"km": km, "seconds": int(km * 360), "hr": [], "main": {"id": i, "km": km, "seconds": int(km * 360)}}


def test_a_run_already_done_today_is_left_alone():
    """Pressed after today's run synced, the choice starts tomorrow (POST /recovery stores that start)."""
    wed, thu, sat = date(2026, 12, 9), date(2026, 12, 10), date(2026, 12, 12)
    done = {wed.isoformat(): run(9, 7.5)}
    plain = by_day(weeks(wed, actual=done)[7])
    easy = by_day(weeks(wed, actual=done, trims=[trim(wed, "easy", thu)])[7])
    assert easy[wed]["type"] == "threshold" and easy[wed]["steps"] == plain[wed]["steps"]
    assert (easy[sat]["type"], easy[sat]["km"]) == ("easy", _half(plain[sat]["km"] * 0.8))
    trimmed = by_day(weeks(wed, actual=done, trims=[trim(wed, start=thu)])[7])
    assert trimmed[wed]["steps"] == plain[wed]["steps"] and trimmed[wed]["km"] == plain[wed]["km"]
    assert trimmed[sat]["km"] == _half(plain[sat]["km"] * 0.9)  # the rest of the week is still trimmed


def plan_of(ws: list[dict], first: int = 0) -> list:
    return [[(wo["date"], wo["type"], wo["km"], wo.get("steps")) for wo in w["workouts"]] for w in ws[first:]]


def test_easy_target_stays_fixed_once_it_syncs():
    """The easy run is chosen when the button is pressed; syncing it never moves "easy" on to the next run."""
    wed, sat, sun = date(2026, 12, 9), date(2026, 12, 12), date(2026, 12, 13)
    stored = [trim(TUE_W8, "easy")]
    before = weeks(TUE_W8, trims=stored)
    for t, act in [(date(2026, 12, 10), {wed.isoformat(): run(1, 7.0)}),
                   (sun, {wed.isoformat(): run(1, 7.0), sat.isoformat(): run(2, 6.0)}),
                   (date(2026, 12, 14), {"2026-12-07": run(0, 6.0), wed.isoformat(): run(1, 7.0),
                                         sat.isoformat(): run(2, 6.0), sun.isoformat(): run(3, 15.0)})]:
        after = weeks(t, actual=act, trims=stored)
        got = by_day(after[7])
        assert (got[wed]["type"], got[wed]["km"]) == ("easy", before[7]["workouts"][1]["km"])
        assert got[wed]["actual_km"] == 7.0
        assert plan_of(after) == plan_of(before), t  # nothing else in that week or any later week changes


def test_trimmed_runs_stay_trimmed_once_they_sync():
    stored = [trim(TUE_W8)]
    before = weeks(TUE_W8, trims=stored)
    act = {"2026-12-09": run(1, 6.5), "2026-12-12": run(2, 5.0)}
    after = weeks(date(2026, 12, 13), actual=act, trims=stored)
    assert plan_of(after) == plan_of(before)
    assert plan_of(after, 8) == plan_of(weeks(date(2026, 12, 13), actual=act), 8)


def test_easy_on_the_trims_session_takes_its_rep_off_with_it():
    """When "easy" replaces the trim's quality session, the rep off goes with it: the rest of the week is just
    the 0.9 trim, and the next week is as planned."""
    stored = [trim(TUE_W8), trim(TUE_W8, "easy")]
    ws = weeks(trims=stored)
    only_trim = weeks(trims=[trim(TUE_W8)])
    w = by_day(ws[7])
    assert w[date(2026, 12, 9)]["type"] == "easy"
    assert [(wo["type"], wo["km"]) for wo in ws[7]["workouts"][2:]] == \
        [(wo["type"], wo["km"]) for wo in only_trim[7]["workouts"][2:]]
    assert plan_of(ws, 8) == plan_of(weeks(), 8)


def test_trim_ends_sunday():
    plain = weeks()
    trimmed = weeks(trims=[trim(TUE_W8)])
    for a, b in zip(plain[8:], trimmed[8:]):
        assert [wo["km"] for wo in a["workouts"]] == [wo["km"] for wo in b["workouts"]]
        assert b["recovery_trim"] is None and b["factor"] == 1.0


def test_race_week_untouched():
    t = RACE_MON + timedelta(days=1)
    plain = weeks(t)
    for stored in ([trim(t)], [trim(t, "easy")], [trim(RACE_MON - timedelta(days=1), "easy")]):
        w = weeks(t, trims=stored)
        assert [(wo["type"], wo["km"]) for wo in w[20]["workouts"]] == \
            [(wo["type"], wo["km"]) for wo in plain[20]["workouts"]]
        assert w[20]["recovery_trim"] is None


def test_easy_replaces_next_run():
    plain = by_day(weeks()[7])
    w = by_day(weeks(trims=[trim(TUE_W8, "easy")])[7])
    mon, wed, sat, sun = sorted(plain)
    assert plain[wed]["type"] == "threshold"
    assert (w[wed]["type"], w[wed]["km"], w[wed]["pace"]) == ("easy", _half(plain[wed]["km"] * 0.8), "easy")
    assert "steps" not in w[wed] and w[wed]["day"] == "Wed"
    assert w[wed]["note"] == "Easy. If the ankle complains, stop and walk home."
    assert (w[sat]["type"], w[sat]["km"]) == (plain[sat]["type"], plain[sat]["km"])  # only the next run changes
    # a long run loses its MP finish
    sat_d = date(2026, 12, 19)  # week 9's Saturday; the long run is next after it
    w9 = by_day(weeks(sat_d, trims=[trim(sat_d + timedelta(days=1), "easy")])[8])
    assert w9[sat_d + timedelta(days=1)]["type"] == "easy" and "mp_km" not in w9[sat_d + timedelta(days=1)]


def test_easy_skips_a_skipped_run():
    skip_wed = [{"date": "2026-12-09", "session": "run", "new_date": None}]
    w = by_day(weeks(moves=skip_wed, trims=[trim(TUE_W8, "easy")])[7])
    plain = by_day(weeks(moves=skip_wed)[7])
    assert w[date(2026, 12, 9)]["type"] == "threshold"
    assert w[date(2026, 12, 12)]["km"] == _half(plain[date(2026, 12, 12)]["km"] * 0.8)


RDL_EASY = {"date": "2026-12-03", "exercise": "rdl", "weight_kg": 40.0, "level": None, "rung": 0,
            "reps": [10, 10], "target_reps": 8, "rating": "easy", "ankle_pain": None}


def test_strength_after_trim_held():
    def rdl(ws):
        a = next(x for x in ws[7]["strength"] if x["key"] == "A")
        return a, next(e for e in a["exercises"] if e["key"] == "rdl")

    _, plain = rdl(weeks(logs=[RDL_EASY]))
    assert plain["suggestion"]["weight"] > 40.0
    a, held = rdl(weeks(logs=[RDL_EASY], trims=[trim(TUE_W8)]))
    assert held["suggestion"]["weight"] == 40.0
    assert a["reduced"] and a["note"] == "Trimmed for recovery: low HRV, confirmed by your last run."
    # with a tired check-in as well, the check-in note stays
    tired = {7: {"week": 7, "feel": 2, "pain": 0, "note": ""}}
    a, _ = rdl(weeks(logs=[RDL_EASY], trims=[trim(TUE_W8)], checkins=tired))
    assert a["note"] == "Trimmed because of last week's check-in."
    # a session before the trim date isn't trimmed
    wed = TUE_W8 + timedelta(days=1)
    b = next(x for x in weeks(wed, trims=[trim(wed)])[7]["strength"] if x["key"] == "B")
    assert not b["reduced"]


def test_recovery_on_every_week():
    ws = weeks()
    assert all(w["recovery"] is ws[0]["recovery"] for w in ws)
    assert ws[0]["recovery"]["phase"] == "none" and ws[0]["recovery"]["offer"] is None


def test_recovery_runs_kinds():
    def run(km, i):
        return {"km": km, "seconds": int(km * 360), "hr": [140], "main": {"id": i, "km": km, "seconds": int(km * 360)}}
    sp = [{"distance": float(k), "seconds": 360 * k, "heartRate": 140} for k in range(1, 7)]
    detail = {"splits": sp, "laps": []}
    actual = {"2026-12-07": run(6, 1), "2026-12-09": run(7, 2), "2026-12-10": run(5, 3), "2026-12-12": run(5, 4)}
    f = facts(actual=actual, details={1: detail, 2: detail, 3: detail})  # no details for 12-12
    s, ws = view.build_view(f, date(2026, 12, 13))
    runs = {r["date"]: r for r in view.recovery_runs(ws, f, s)}
    assert set(runs) == {date(2026, 12, 7), date(2026, 12, 9), date(2026, 12, 10)}
    assert runs[date(2026, 12, 7)]["kind"] == "easy"
    assert runs[date(2026, 12, 9)]["kind"] == "quality"
    assert runs[date(2026, 12, 10)]["kind"] == "easy"  # unplanned Thursday
    assert runs[date(2026, 12, 7)]["splits"] and runs[date(2026, 12, 9)]["verdict"] is None  # no rep laps


def test_race_week_offers_nothing(monkeypatch):
    offered = {"phase": "advice", "offer": "trim"}
    monkeypatch.setattr(recovery, "state", lambda *a: dict(offered))
    assert weeks(RACE_MON + timedelta(days=1))[0]["recovery"]["offer"] is None
    assert weeks()[0]["recovery"]["offer"] == "trim"


# --- POST /recovery ---

def _clear():
    db.init()
    with db.conn() as c:
        c.execute("DELETE FROM recovery_trims")


@pytest.fixture
def client(monkeypatch):
    _clear()
    monkeypatch.setattr(main, "today", lambda: TUE_W8)
    with TestClient(main.app) as c:
        yield c
    _clear()


def offering(monkeypatch, offer):
    monkeypatch.setattr(recovery, "state", lambda *a: {"phase": "advice", "offer": offer})


def test_post_recovery_stores_when_offered(client, monkeypatch):
    offering(monkeypatch, "trim")
    r = client.post("/recovery", data={"kind": "trim"}, follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/#recovery"
    assert db.trims() == [{"date": TUE_W8.isoformat(), "kind": "trim", "start": TUE_W8.isoformat()}]
    _, ws = main.build_view()
    assert ws[7]["recovery_trim"] == TUE_W8
    offering(monkeypatch, "easy")
    client.post("/recovery", data={"kind": "easy"}, follow_redirects=False)
    assert sorted(t["kind"] for t in db.trims()) == ["easy", "trim"]


def test_post_recovery_after_todays_run_starts_tomorrow(client, monkeypatch):
    offering(monkeypatch, "trim")
    with db.conn() as c:
        c.execute("DELETE FROM activities")
        c.execute("INSERT INTO activities(id, date, km, seconds) VALUES (77, ?, 6.0, 2160)", (TUE_W8.isoformat(),))
    try:
        client.post("/recovery", data={"kind": "trim"}, follow_redirects=False)
        wed = TUE_W8 + timedelta(days=1)
        assert db.trims() == [{"date": TUE_W8.isoformat(), "kind": "trim", "start": wed.isoformat()}]
        _, ws = main.build_view()
        assert ws[7]["recovery_trim"] == wed
    finally:
        with db.conn() as c:
            c.execute("DELETE FROM activities")


@pytest.mark.parametrize("offer,kind,day", [
    (None, "trim", TUE_W8),  # no episode
    ("easy", "trim", TUE_W8),  # trim already taken: only "easy" is on offer
    ("trim", "easy", TUE_W8),  # easy before a firm warning
    ("trim", "zzz", TUE_W8),
    ("trim", "trim", RACE_MON + timedelta(days=1)),  # race week
])
def test_post_recovery_refused_when_not_offered(client, monkeypatch, offer, kind, day):
    offering(monkeypatch, offer)
    monkeypatch.setattr(main, "today", lambda: day)
    r = client.post("/recovery", data={"kind": kind}, follow_redirects=False)
    assert r.status_code == 303
    assert r.headers["location"].startswith("/?msg=") and r.headers["location"].endswith("#recovery")
    assert db.trims() == []
