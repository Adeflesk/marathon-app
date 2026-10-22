import base64
import os
import secrets
from contextlib import asynccontextmanager
from datetime import date, datetime, timedelta
from math import gcd
from pathlib import Path
from urllib.parse import urlencode

from fastapi import FastAPI, Form, Request
from fastapi.responses import RedirectResponse, Response
from fastapi.templating import Jinja2Templates

from . import ankle, db, garmin, moves, progression, review, smashrun, strength
from .config import load_settings, race_date
from .pace_engine import fmt_pace, fmt_time, pace_per_mi
from .plan import DAYS, _half, feedback_factor, generate
from .sessions import flatten, pace_s, scale_session, step_km

BASE = Path(__file__).resolve().parent


@asynccontextmanager
async def lifespan(app: FastAPI):
    db.init()
    yield


app = FastAPI(lifespan=lifespan)


@app.middleware("http")
async def basic_auth(request: Request, call_next):
    """HTTP Basic auth when APP_PASSWORD is set (any username). Unset locally, so dev needs no login."""
    password = os.environ.get("APP_PASSWORD")
    if password:
        given = ""
        scheme, _, encoded = request.headers.get("authorization", "").partition(" ")
        if scheme.lower() == "basic":
            try:
                given = base64.b64decode(encoded).decode().partition(":")[2]
            except (ValueError, UnicodeDecodeError):
                pass
        if not secrets.compare_digest(given.encode(), password.encode()):
            return Response(status_code=401, headers={"WWW-Authenticate": 'Basic realm="marathon"'})
    return await call_next(request)


templates = Jinja2Templates(directory=str(BASE / "templates"))


def _effort(pace: float | None, intensity: str, paces: dict) -> str:
    if intensity == "recovery" or pace is None:
        return "rest" if intensity == "recovery" else "easy"
    if pace >= paces["long"]:
        return "easy"
    return "hard" if pace < paces["marathon"] - 5 else "steady"


def band_segments(w: dict, paces: dict) -> list[dict]:
    """A workout as pace-band segments: [{km, frac, effort}], effort one of easy/steady/hard/rest."""
    if "steps" in w:
        raw = [(step_km(st, paces), _effort(pace_s(st["pace"], paces) if st["pace"] is not None else None,
                                             st["intensity"], paces)) for st in flatten(w["steps"])]
    elif w["type"] == "long" and w.get("mp_km"):
        raw = [(w["km"] - w["mp_km"], "easy"), (w["mp_km"], "steady")]
    elif w["type"] == "race":
        raw = [(w["km"], "steady")]
    else:
        raw = [(w["km"], "easy")]
    total = sum(km for km, _ in raw) or 1
    return [{"km": km, "frac": km / total, "effort": e} for km, e in raw]


def fmt_km(km: float) -> str:
    return f"{km:.1f}".rstrip("0").rstrip(".")
templates.env.filters["pace"] = fmt_pace
templates.env.filters["pace_mi"] = lambda s: fmt_pace(pace_per_mi(s))
templates.env.filters["km"] = fmt_km
templates.env.globals["band"] = band_segments


def today() -> date:
    return date.today()


def actual_by_date() -> dict[str, dict]:
    out: dict[str, dict] = {}
    with db.conn() as c:
        for r in c.execute("SELECT id, date, km, seconds, avg_hr FROM activities"):
            d = out.setdefault(r["date"], {"km": 0.0, "seconds": 0, "hr": [], "main": None})
            d["km"] += r["km"]
            d["seconds"] += r["seconds"]
            if r["avg_hr"]:
                d["hr"].append(r["avg_hr"])
            if d["main"] is None or r["km"] > d["main"]["km"]:  # the day's longest run gets the review
                d["main"] = {"id": r["id"], "km": r["km"], "seconds": r["seconds"]}
    return out


def build_view():
    s = load_settings()
    weeks = generate(s, today())
    actual = actual_by_date()
    details = db.run_details([a["main"]["id"] for a in actual.values()])
    eq = strength.load_equipment()
    with db.conn() as c:
        checkins = {r["week"]: dict(r) for r in c.execute("SELECT * FROM checkins")}
    t = today()
    st = ankle_state(t, weeks, list(checkins.values()))
    moved = moves.index(db.moves())
    # Each run is scaled by its own week's check-in, then follows any move (relocate takes it across Sunday).
    for w in weeks:
        factor = feedback_factor(checkins.get(w["week"] - 1))
        w["factor"] = factor
        w["checkin"] = checkins.get(w["week"])
        for wo in w["workouts"]:
            if factor != 1.0 and wo["type"] != "race":
                if "steps" in wo:  # fewer reps, so the day, the note and the .fit all agree
                    scale_session(wo, factor, s["paces"])
                else:
                    wo["km"] = _half(wo["km"] * factor)
            moves.shift(wo, "run", moved)
    moves.relocate(weeks)
    # A day with two runs (after a move) is one day: both show its actual, the longer one gets the review.
    planned: dict[date, float] = {}
    lead: dict[date, dict] = {}
    for wo in (wo for w in weeks for wo in w["workouts"] if not wo.get("skipped")):
        planned[wo["date"]] = planned.get(wo["date"], 0) + wo["km"]
        if wo["date"] not in lead or wo["km"] > lead[wo["date"]]["km"]:
            lead[wo["date"]] = wo
    for w in weeks:
        wk_actual = 0.0
        for wo in w["workouts"]:
            a = None if wo.get("skipped") else actual.get(wo["date"].isoformat())
            day_km = planned.get(wo["date"], 0)
            wo["actual_km"] = round(a["km"], 1) if a else None
            wo["actual_pace"] = (a["seconds"] / a["km"]) if a and a["km"] else None
            wo["compliance"] = round(100 * a["km"] / day_km) if a and day_km else None
            wo["past"] = wo["date"] < t
            detail = details.get(a["main"]["id"]) if a and lead.get(wo["date"]) is wo else None
            wo["review"] = review.review(wo, a["main"], detail, s["paces"]) if detail else None
        w["target_km"] = round(sum(wo["km"] for wo in w["workouts"] if not wo.get("skipped")), 1)
        for i in range(7):
            d = (w["start"] + timedelta(days=i)).isoformat()
            if d in actual:
                wk_actual += actual[d]["km"]
        w["actual_km"] = round(wk_actual, 1)
        attach_strength(w, s, eq, st, t, moved)
        w["is_current"] = w["start"] <= t < w["start"] + timedelta(days=7)
        w["is_past"] = w["start"] + timedelta(days=7) <= t
    moves.relocate(weeks)  # strength sessions moved across Sunday, keeping their own week's prescription
    return s, weeks


def ankle_state(t: date, weeks: list[dict], checkins: list[dict]) -> dict:
    """Today's ankle and logging state, computed once per request from the stored facts."""
    logs, checks, tests, snacks = db.logs(), db.checks(), db.tests(), db.snacks()
    hop = ankle.hop_stage(t, tests, checks, logs, checkins, weeks)
    by_ex: dict[str, list[dict]] = {}
    for lg in logs:  # newest first, as db.logs() returns them
        by_ex.setdefault(lg["exercise"], []).append(lg)
    return {
        "logs": logs, "checks": checks, "tests": tests, "snacks": snacks,
        "by_key": {(lg["date"], lg["exercise"]): lg for lg in logs},
        "by_ex": by_ex,
        "flag_until": ankle.flag_until(t, checks, logs, checkins, weeks),
        "hop_stage": hop,
        "balance_stage": ankle.balance_stage(t, snacks, tests, checks, hop, logs, checkins, weeks),
        "restart": ankle.restart(t, logs, checks),
        # before today, so logging the first lift doesn't cancel the time-off drop for the rest of the session
        "last_any_log": next((date.fromisoformat(lg["date"]) for lg in logs if lg["date"] < t.isoformat()), None),
    }


def weight_range(weights: list[float]) -> dict | None:
    """Min, max and an input step that lands on every available weight, or None for unloaded work."""
    if not weights:
        return None
    lo = weights[0]
    step = 0
    for w in weights[1:]:
        step = gcd(step, round((w - lo) * 100))
    return {"min": lo, "max": weights[-1], "step": step / 100 if step else "any"}


def attach_strength(w: dict, s: dict, eq: dict, st: dict, t: date, moved: dict | None = None) -> None:
    """Strength sessions with suggestions and logs, and the ankle snacks, for one week."""
    end = w["start"] + timedelta(days=6)
    flag = st["flag_until"]

    def flagged(day: date) -> bool:
        """The flag is still up on `day`, in a week that isn't over."""
        return flag is not None and day <= flag and end >= t

    a_day = w["start"] + timedelta(days=DAYS.index(s["strength_days"]["A"]))
    q = next((wo for wo in w["workouts"] if "steps" in wo), None)
    wed_bad = bool(q and q.get("review") and q["review"]["verdict"] == "bad")
    ctx = {"factor": w["factor"], "wed_bad": wed_bad, "ankle_flag": flagged(a_day), "hop_stage": st["hop_stage"],
           "balance_stage": st["balance_stage"], "restart": st["restart"], "days": s["strength_days"]}
    w["strength"] = strength.sessions_for_week(w, eq, ctx)
    pctx = {"phase": w["phase"], "cutback": w["phase"] == "Cutback", "factor": w["factor"],
            "last_any_log": st["last_any_log"]}
    for sess in w["strength"]:
        moves.shift(sess, sess["key"], moved or {})
        sess["day"] = sess["date"].strftime("%a")
        day = sess["date"].isoformat()
        pctx["ankle_flag"] = flagged(sess["date"])
        for ex in sess["exercises"]:
            history = st["by_ex"].get(ex["key"], [])
            ex["suggestion"] = progression.suggest(ex, history, pctx, eq, today=t)
            ex["log"] = st["by_key"].get((day, ex["key"]))
            ex["last"] = next((lg for lg in history if lg["date"] < day), None)
            ex["weights"] = weight_range(progression.available_weights(ex, eq))

    items = ankle.BALANCE_STAGES[max(0, min(st["balance_stage"], len(ankle.BALANCE_STAGES) - 1))]
    if w["phase"] == "Race week":
        items = items[:2]
    w["snack"] = {}
    for name in s["ankle_days"]:
        d = w["start"] + timedelta(days=DAYS.index(name))
        if d > race_date(s):
            continue
        done = {x["item"] for x in st["snacks"] if x["date"] == d.isoformat()}
        w["snack"][d] = {"date": d, "day": d.strftime("%a"), "stage": st["balance_stage"], "items": items,
                         "done": done}
    w["snack"] = dict(sorted(w["snack"].items()))
    w["ankle_state"] = st


@app.get("/")
def dashboard(request: Request, msg: str = ""):
    s, weeks = build_view()
    t = today()
    current = next((w for w in weeks if w["is_current"]), None)
    upcoming = weeks[0] if t < weeks[0]["start"] else current
    days_left = (race_date(s) - t).days
    # the next run from today on, and any strength session today
    next_run = next((wo for w in weeks for wo in w["workouts"]
                     if wo["km"] > 0 and not wo.get("skipped")
                     and (wo["date"] > t or (wo["date"] == t and wo["actual_km"] is None))), None)
    done = [wo for w in weeks for wo in w["workouts"] if wo.get("review") and wo["date"] <= t]
    last_run = done[-1] if done else None
    strength_today = next((x for w in weeks for x in w.get("strength", [])
                           if x["date"] == t and not x.get("skipped")), None)
    st = weeks[0]["ankle_state"]
    snack_today = (upcoming or {}).get("snack", {}).get(t)
    tests_due = bool(upcoming) and ankle.tests_due(upcoming, weeks, st["tests"])
    test_keys = [k for k in ankle.TESTS if k in ankle.CORE_TESTS
                 or (k == "pogo_trial" and upcoming and upcoming["week"] == 1)
                 or (k in ("single_hop", "triple_hop") and (st["hop_stage"] or 0) >= 2)]
    week_end = upcoming["start"] + timedelta(days=6) if upcoming else t
    tests_this_week = {x["test"]: x for x in st["tests"]
                       if upcoming and upcoming["start"].isoformat() <= x["date"] <= week_end.isoformat()}
    profile = {
        "planned": [w["target_km"] for w in weeks],
        "actual": [w["actual_km"] if (w["is_past"] or w["is_current"]) else None for w in weeks],
        "current": next((i for i, w in enumerate(weeks) if w["is_current"]), None),
        "max": max(w["target_km"] for w in weeks),
    }
    return templates.TemplateResponse(
        request,
        "index.html",
        {
            "s": s,
            "week": upcoming,
            "days_left": days_left,
            "weeks_left": days_left // 7,
            "profile": profile,
            "today": t,
            "race_day": race_date(s),
            "next_run": next_run,
            "last_run": last_run,
            "strength_today": strength_today,
            "strength_session": strength_today,
            "snack_today": snack_today,
            "morning_check": ankle.morning_check_due(t, st["logs"], st["checks"]),
            "tests_due": tests_due,
            "tests": {k: {**ankle.TESTS[k], "logged": tests_this_week.get(k)} for k in test_keys},
            "ankle_flag": st["flag_until"],
            "hop_stage": st["hop_stage"],
            "injured_side": s["injured_side"],
            "msg": msg,
            "paces": s["paces"],
            "goal": s["goal_time"],
        },
    )


@app.get("/plan")
def full_plan(request: Request):
    s, weeks = build_view()
    return templates.TemplateResponse(request, "plan.html", {"s": s, "weeks": weeks})


@app.get("/strength")
def strength_page(request: Request, week: int = 0):
    s, weeks = build_view()
    t = today()
    default = next((w for w in weeks if w["is_current"]), weeks[0] if t < weeks[0]["start"] else weeks[-1])
    chosen = next((w for w in weeks if w["week"] == week), default)
    return templates.TemplateResponse(
        request, "strength.html",
        {"s": s, "w": chosen, "n": len(weeks), "eq_summary": strength.summary(strength.load_equipment()),
         "history": {ex["key"]: [{**lg, "day": date.fromisoformat(lg["date"])} for lg in db.logs(ex["key"])[:8]]
                     for sess in chosen["strength"] for ex in sess["exercises"]}},
    )


def _floats(text: str) -> list[float]:
    return [float(x) for x in text.replace(";", ",").split(",") if x.strip()]


@app.get("/equipment")
def equipment_page(request: Request, saved: int = 0):
    eq = strength.load_equipment()
    return templates.TemplateResponse(
        request, "equipment.html",
        {"eq": eq, "summary": strength.summary(eq), "saved": bool(saved)},
    )


@app.post("/equipment")
def equipment_save(
    barbell: bool = Form(False), bar_kg: float = Form(20.0), plates_kg: str = Form(""),
    dumbbells: bool = Form(False), db_min_kg: float = Form(2.5), db_max_kg: float = Form(35.0),
    db_step_kg: float = Form(1.25), kettlebells_kg: str = Form(""), medicine_balls_kg: str = Form(""),
    box: bool = Form(False), rings: bool = Form(False), bench: bool = Form(False),
    rack: bool = Form(False), pullup: bool = Form(False), bands: bool = Form(False),
):
    try:
        eq = {
            "barbell": barbell, "bar_kg": bar_kg, "plates_kg": _floats(plates_kg),
            "dumbbells": dumbbells, "db_min_kg": db_min_kg, "db_max_kg": db_max_kg, "db_step_kg": db_step_kg,
            "kettlebells_kg": _floats(kettlebells_kg), "medicine_balls_kg": _floats(medicine_balls_kg),
            "box": box, "rings": rings, "bench": bench, "rack": rack, "pullup": pullup, "bands": bands,
        }
    except ValueError:
        return RedirectResponse("/equipment", status_code=303)
    strength.save_equipment(eq)
    return RedirectResponse("/equipment?saved=1", status_code=303)


def _find_workout(day: str, n: int = 0):
    """The `n`th run planned on `day` (two can share a day after a move), skipped ones left out."""
    s, weeks = build_view()
    runs = [wo for w in weeks for wo in w["workouts"] if wo["date"].isoformat() == day and not wo.get("skipped")]
    return s, runs[n] if 0 <= n < len(runs) else None


@app.get("/workout/{day}.fit")
def workout_fit(day: str, n: int = 0):
    s, wo = _find_workout(day, n)
    if not wo or wo["km"] <= 0:
        return Response(status_code=404)
    return Response(
        garmin.build_fit(wo, s["paces"]),
        media_type="application/octet-stream",
        headers={"Content-Disposition": f'attachment; filename="{garmin.filename(wo)}"'},
    )


@app.get("/workouts/week/{n}.zip")
def workouts_zip(n: int):
    s, weeks = build_view()
    week = next((w for w in weeks if w["week"] == n), None)
    if not week:
        return Response(status_code=404)
    return Response(
        garmin.week_zip(week["workouts"], s["paces"]),
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="week-{n}-garmin-workouts.zip"'},
    )


@app.get("/backup.db")
def backup_db():
    return Response(
        db.backup_bytes(),
        media_type="application/octet-stream",
        headers={"Content-Disposition": f'attachment; filename="marathon-{date.today().isoformat()}.db"'},
    )


@app.post("/sync")
def sync_now():
    s = load_settings()
    since = date.fromisoformat(s["plan_start"]) - timedelta(days=28)
    try:
        n = smashrun.sync(since)
        msg = f"Synced {n} runs from Smashrun."
    except smashrun.SyncError as e:
        msg = f"Sync failed: {e}"
    except Exception as e:  # network errors etc.
        msg = f"Sync failed: {type(e).__name__}: {e}"
    return RedirectResponse(f"/?{urlencode({'msg': msg})}", status_code=303)


@app.post("/checkin")
def checkin(week: int = Form(...), feel: int = Form(...), pain: int = Form(...), note: str = Form("")):
    with db.conn() as c:
        c.execute(
            "INSERT OR REPLACE INTO checkins(week, feel, pain, note, created) VALUES (?,?,?,?,?)",
            (week, feel, pain, note, datetime.now().isoformat(timespec="seconds")),
        )
    return RedirectResponse("/?msg=Check-in saved.", status_code=303)


def _num(text: str, kind=float):
    """A form number, or None when the field is blank."""
    text = (text or "").strip()
    return kind(text) if text else None


def _back(anchor: str, msg: str = "") -> RedirectResponse:
    query = f"?{urlencode({'msg': msg})}" if msg else ""
    return RedirectResponse(f"/{query}#{anchor}", status_code=303)


def _day(text: str) -> date | None:
    """A form date as a `date`, or None when it isn't a valid ISO date."""
    try:
        return date.fromisoformat((text or "").strip())
    except ValueError:
        return None


RATINGS = {"easy", "right", "hard"}
SNACK_ITEMS = {x["item"] for stage in ankle.BALANCE_STAGES for x in stage}


@app.post("/strength/log")
def strength_log(
    day: str = Form("", alias="date"), exercise: str = Form(""), weight: str = Form(""), level: str = Form(""),
    rung: str = Form("0"), target_reps: str = Form(""), rep1: str = Form(""), rep2: str = Form(""),
    rep3: str = Form(""), rep4: str = Form(""), rep5: str = Form(""), rating: str = Form(""),
    ankle_pain: str = Form(""),
):
    anchor = f"ex-{exercise}" if exercise in strength.EXERCISES else "strength"
    d = _day(day)
    if d is None:
        return _back(anchor, "Not saved: that date isn't valid.")
    if d > today():
        return _back(anchor, "Not saved: that date is in the future.")
    if exercise not in strength.EXERCISES:
        return _back(anchor, "Not saved: unknown exercise.")
    if rating not in RATINGS:
        return _back(anchor, "Not saved: pick Easy, Right or Hard.")
    try:
        row = {
            "date": d.isoformat(), "exercise": exercise, "weight_kg": _num(weight),
            "level": level.strip() or None, "rung": _num(rung, int) or 0, "target_reps": _num(target_reps, int),
            "reps": [int(r) for r in (rep1, rep2, rep3, rep4, rep5) if r.strip()],
            "rating": rating, "ankle_pain": _num(ankle_pain, int),
            "created": datetime.now().isoformat(timespec="seconds"),
        }
    except ValueError:
        return _back(anchor, "Not saved: weight, reps and pain must be numbers.")
    db.save_log(row)
    return _back(anchor)


@app.post("/snack")
def snack_toggle(day: str = Form("", alias="date"), item: str = Form("")):
    d = _day(day)
    if d is None:
        return _back("snack", "Not saved: that date isn't valid.")
    if d > today():
        return _back("snack", "Not saved: that date is in the future.")
    if item not in SNACK_ITEMS:
        return _back("snack", "Not saved: unknown snack item.")
    db.toggle_snack(d.isoformat(), item)
    return _back("snack")


@app.post("/ankle/check")
def ankle_check(day: str = Form("", alias="date"), worse: str = Form("0"), note: str = Form("")):
    d = _day(day)
    if d is None:
        return _back("ankle-check", "Not saved: that date isn't valid.")
    if d > today():
        return _back("ankle-check", "Not saved: that date is in the future.")
    db.save_check(d.isoformat(), worse == "1", note)
    return _back("ankle-check")


@app.post("/ankle/tests")
async def ankle_tests(request: Request):
    form = await request.form()
    d = _day(form.get("date") or "")
    if d is None:
        return _back("tests", "Not saved: that date isn't valid.")
    rows = []
    try:
        for key in ankle.TESTS:  # only known tests are read; anything else in the form is ignored
            injured = _num(form.get(f"{key}_injured", ""))
            other = _num(form.get(f"{key}_other", ""))
            if injured is not None:
                rows.append((key, injured, other))
    except ValueError:
        return _back("tests", "Not saved: test results must be numbers.")
    for key, injured, other in rows:
        db.save_test(d.isoformat(), key, injured, other)
    return _back("tests")
