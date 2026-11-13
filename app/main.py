import base64
import os
import secrets
from contextlib import asynccontextmanager
from datetime import date, datetime, timedelta
from pathlib import Path
from urllib.parse import urlencode, urlsplit

from fastapi import FastAPI, Form, Request
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse, Response
from fastapi.templating import Jinja2Templates

from . import ankle, db, fuel, garmin, garmin_api, garmin_sync, moves, progress, strength, view
from .config import load_settings, race_date
from .pace_engine import fmt_pace, fmt_time, pace_per_mi, parse_time
from .plan import generate
from .sessions import flatten, pace_s, step_km

BASE = Path(__file__).resolve().parent
ICONS = {"icon-192.png": "image/png", "icon-512.png": "image/png", "icon.svg": "image/svg+xml"}
# Android fetches these without the login, so they skip the password (nothing in them is private)
PUBLIC = {"/manifest.webmanifest"} | {f"/{name}" for name in ICONS}


@asynccontextmanager
async def lifespan(app: FastAPI):
    db.init()
    yield


app = FastAPI(lifespan=lifespan)


@app.middleware("http")
async def same_origin_posts(request: Request, call_next):
    """Refuse a form post sent from another site. Browsers resend Basic auth on their own, so without this a page
    elsewhere could post to /goal or /move while you're logged in. Posts without an Origin (tests, curl) pass."""
    origin = request.headers.get("origin")
    if request.method == "POST" and origin is not None and urlsplit(origin).netloc != request.headers.get("host"):
        return Response("Form posts must come from this app.", status_code=403)
    return await call_next(request)


@app.middleware("http")
async def basic_auth(request: Request, call_next):
    """HTTP Basic auth when APP_PASSWORD is set (any username). Unset locally, so dev needs no login."""
    password = os.environ.get("APP_PASSWORD")
    if password and request.url.path not in PUBLIC:
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


@app.get("/manifest.webmanifest")
def manifest():
    """Lets Android add the app to the home screen, opening full screen with its own icon."""
    icons = [{"src": f"/icon-{n}.png", "sizes": f"{n}x{n}", "type": "image/png", "purpose": "any maskable"}
             for n in (192, 512)]
    return JSONResponse({
        "name": "Barcelona build", "short_name": "Barcelona", "start_url": "/", "scope": "/",
        "display": "standalone", "background_color": "#0E2A3B", "theme_color": "#0E2A3B",
        "icons": icons + [{"src": "/icon.svg", "sizes": "any", "type": "image/svg+xml"}],
    }, media_type="application/manifest+json")


def _icon_route(name: str, kind: str):
    def icon():
        return FileResponse(BASE / "static" / name, media_type=kind,
                            headers={"Cache-Control": "public, max-age=86400"})
    app.add_api_route(f"/{name}", icon, methods=["GET"], name=name)


for _name, _kind in ICONS.items():
    _icon_route(_name, _kind)


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
templates.env.filters["hms"] = fmt_time
templates.env.filters["clock"] = lambda s: fmt_time(s)[2:] if s < 3600 else fmt_time(s)  # 25:30, 1:55:10
templates.env.filters["dayx"] = lambda d, d0: (date.fromisoformat(d) - date.fromisoformat(d0)).days  # chart x
templates.env.filters["longdate"] = lambda d: date.fromisoformat(d).strftime("%-d %b")
templates.env.globals["band"] = band_segments


def today() -> date:
    return date.today()


def build_view():
    """Every page's settings and weeks: today's facts through the pure pipeline in view.py."""
    return view.build_view(view.load_facts(), today())


SYNC_PAGES = ("/", "/progress")  # the pages that sync when they open
SYNC_GAP = timedelta(minutes=15)


def _sync_due() -> bool:
    """Neither a sync nor a try at one in the last 15 minutes."""
    tries = [x for x in (db.get_meta("last_sync"), db.get_meta("last_sync_try")) if x]
    return not tries or datetime.fromisoformat(max(tries)) <= datetime.now() - SYNC_GAP


def view_with_sync():
    """build_view, after a sync when a run from yesterday or today isn't in yet (at most every 15 minutes).
    Returns the view and the top line: a failed sync's reason, and which run is still missing."""
    s, weeks = build_view()
    t = today()
    missing = view.missing_runs(weeks, t)
    error = None
    no_wellness = not any(w["date"] == t.isoformat() for w in db.wellness())
    if (missing or no_wellness) and os.environ.get("GARMIN_API_KEY") and _sync_due():
        db.set_meta("last_sync_try", datetime.now().isoformat(timespec="seconds"))
        msg = run_sync(quick=True)
        error = msg if msg.startswith("Sync failed") else None
        s, weeks = build_view()
        missing = view.missing_runs(weeks, t)
    names = ["Yesterday's" if d < t else "Today's" for d in missing]
    line = (f"{names[0]} run isn't in Garmin yet." if len(names) == 1
            else "Yesterday's and today's runs aren't in Garmin yet." if names else None)
    return s, weeks, {"error": error, "missing": line}


@app.get("/")
def dashboard(request: Request, msg: str = "", confirm: str = "", on: str = "", orig: str = "", prev: str = "",
              by: str = "1"):
    s, weeks, auto_sync = view_with_sync()
    expires = garmin_api.key_expiry() if os.environ.get("GARMIN_API_KEY") else None
    page = view.dashboard(s, weeks, today(), db.results(), expires, confirm, _day(on), _day(orig),
                          -1 if by == "-1" else 1)
    return templates.TemplateResponse(request, "index.html",
                                      {**page, "auto_sync": auto_sync, "msg": msg, "prev_open": prev == "1"})


@app.get("/progress")
def progress_page(request: Request, msg: str = ""):
    s, weeks, auto_sync = view_with_sync()
    t = today()
    st = weeks[0]["ankle_state"]
    ref_pace = load_settings()["paces"]["easy"]  # fixed, so a new result doesn't break the fitness line
    verdict = progress.verdict(s)
    options = progress.goal_options(verdict["predicted"], parse_time(s["goal_time"]), parse_time(s["settings_goal"]),
                                    max(0, (race_date(s) - t).days // 7))
    if verdict["state"] in ("none", "on course"):  # suggestions only when the goal isn't on course
        options = [o for o in options if o["kind"] == "back"]
    current = next((w for w in weeks if w["is_current"]), None)
    cutback = next((w for w in weeks if w["phase"] == "Cutback" and w["start"] + timedelta(days=6) >= t), None)
    time_trial = {"week": cutback["week"], "start": cutback["start"],
                  "end": cutback["start"] + timedelta(days=6)} if cutback else None
    return templates.TemplateResponse(request, "progress.html", {
        "time_trial": time_trial,
        "s": s, "msg": msg, "auto_sync": auto_sync, "today": t, "verdict": verdict, "options": options, "week": current,
        "n_weeks": len(weeks), "why": progress.why_rows(weeks, t, ref_pace),
        "fitness": progress.fitness_trend(weeks, ref_pace), "ref_pace": ref_pace,
        "recovery_trend": progress.recovery_trend(db.wellness(), t),
        "long_runs": progress.long_runs(weeks), "plan": progress.plan_bars(weeks),
        "ankle": progress.ankle_table(weeks, st["tests"]), "ankle_state": st,
        "summaries": progress.summaries(weeks, s, st, db.results(), t),
    })


@app.get("/race")
def race_page(request: Request):
    s, weeks = build_view()
    plan = fuel.race_plan(s["paces"]["marathon"], s["race_stations"], s["race_gel_stations"])
    return templates.TemplateResponse(request, "race.html", {"s": s, "plan": plan, "race_day": race_date(s),
                                                             "goal": s["goal_time"]})


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


def run_sync(quick: bool = False) -> str:
    """Sync from Garmin; the message for the page, success or failure. `quick` (sync on open) fetches the
    details of only the newest few runs and gives up sooner, so the page doesn't hang; Sync fetches the rest."""
    s = load_settings()
    since = date.fromisoformat(s["plan_start"]) - timedelta(days=28)
    try:
        n = garmin_sync.sync(since, **(garmin_sync.QUICK if quick else {}))
        return f"Synced {n} runs from Garmin."
    except garmin_api.SyncError as e:
        return f"Sync failed: {e}"
    except Exception as e:  # network errors etc.
        return f"Sync failed: {type(e).__name__}: {e}"


@app.post("/sync")
def sync_now(next_page: str = Form("/", alias="next")):
    page = next_page if next_page in SYNC_PAGES else "/"
    return RedirectResponse(f"{page}?{urlencode({'msg': run_sync()})}", status_code=303)


@app.post("/checkin")
def checkin(week: int = Form(...), feel: int = Form(...), pain: int = Form(...), note: str = Form("")):
    n_weeks = len(generate(load_settings(), today()))
    if not (1 <= week <= n_weeks and 1 <= feel <= 5 and 0 <= pain <= 10):
        return RedirectResponse("/?msg=Check-in not saved: those values are out of range.", status_code=303)
    with db.conn() as c:
        c.execute(
            "INSERT OR REPLACE INTO checkins(week, feel, pain, note, created) VALUES (?,?,?,?,?)",
            (week, feel, pain, note, datetime.now().isoformat(timespec="seconds")),
        )
    return RedirectResponse(f"/?{urlencode({'msg': f'Week {week} check-in saved.'})}", status_code=303)


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


@app.post("/goal")
def goal_change(goal: str = Form("")):
    try:
        seconds = parse_time(goal.strip())
    except ValueError:
        seconds = 0
    if not 2.5 * 3600 <= seconds <= 6 * 3600:
        return RedirectResponse(f"/progress?{urlencode({'msg': 'Not changed: that is not a marathon time.'})}#verdict",
                                status_code=303)
    back = seconds == parse_time(load_settings()["goal_time"])
    db.save_goal(today().isoformat(), view.GOAL_SETTINGS if back else fmt_time(seconds))
    msg = f"Goal changed to {fmt_time(seconds)[:-3]}. The plan now follows it."
    return RedirectResponse(f"/progress?{urlencode({'msg': msg})}#verdict", status_code=303)


@app.post("/fuel")
def fuel_tick(day: str = Form("", alias="date")):
    """Tick or untick "fuelled as planned" on a done long run that had a fuelling note."""
    d = _day(day)
    if d is None or d > today():
        return _back("week", "Not saved: that isn't a day with a long run done.")
    _, weeks = build_view()
    if not any(wo["date"] == d and wo["fuel"] and wo["actual_km"] is not None and not wo.get("skipped")
               for w in weeks for wo in w["workouts"]):
        return _back("week", "Not saved: that isn't a day with a long run done.")
    db.toggle_fuel(d.isoformat())
    return _back("week")


@app.post("/recovery")
def recovery_take(kind: str = Form("")):
    """Take the recovery advice on offer: "trim" (the rest of this week at 0.9, a rep off the next session) or
    "easy" (the next run easy). Stored only when the page offers exactly that button, and never in Race week."""
    t = today()
    _, weeks = build_view()
    current = next((w for w in weeks if w["start"] <= t < w["start"] + timedelta(days=7)), None)
    if current and current["phase"] == "Race week":
        return _back("recovery", "Not changed: race week is never trimmed.")
    if kind not in ("trim", "easy") or weeks[0]["recovery"]["offer"] != kind:
        return _back("recovery", "Not changed: that isn't on offer right now.")
    db.add_trim(t.isoformat(), kind)
    return _back("recovery")


RESULT_KM = {"5": 5.0, "10": 10.0, "21.1": 21.0975}


@app.post("/result")
def result_save(day: str = Form("", alias="date"), km: str = Form(""), time: str = Form("")):
    d = _day(day)
    if d is None or d > today():
        return _back("paces", "Not saved: pick the day of the race, today or earlier.")
    if km not in RESULT_KM:
        return _back("paces", "Not saved: pick 5 km, 10 km or a half marathon.")
    try:
        seconds = parse_time(time.strip())
    except ValueError:
        seconds = 0
    pace = seconds / RESULT_KM[km]
    if not 150 <= pace <= 720:  # 2:30 to 12:00 per km
        return _back("paces", "Not saved: write the time as mm:ss or h:mm:ss.")
    db.save_result(d.isoformat(), RESULT_KM[km], seconds)
    return _back("paces", "Result saved. Your paces and the plan now follow it.")


@app.post("/result/delete")
def result_delete(day: str = Form("", alias="date")):
    d = _day(day)
    if d is not None:
        db.delete_result(d.isoformat())
    return _back("paces", "Result deleted.")


@app.post("/move")
def move(day: str = Form("", alias="date"), session: str = Form(""), confirm: str = Form(""),
         orig: str = Form(""), by: str = Form("1")):
    """Move a session to tomorrow (`by` 1) or to the day before (`by` -1), or skip it after a clash warning."""
    d = _day(day)
    if d is None or session not in view.SESSIONS:
        return _back("week", "Not moved: that isn't a session.")
    if confirm not in ("", "skip", "move") or by not in ("1", "-1"):
        return _back("week", "Not moved: that isn't a choice.")
    step = int(by)
    if d < today():
        return _back("week", "Not moved: that day has passed.")
    s, weeks = build_view()
    item = view.session_at(weeks, d, session, _day(orig))
    if item is None:
        return _back("week", "Not moved: there's no such session that day.")
    if not item["movable" if step == 1 else "movable_back"]:
        return _back("week", "Not moved: it's done already, or tomorrow is race day or past the plan." if step == 1
                     else "Not moved: it's done already, or the day before has passed or is before the plan.")
    if not confirm and moves.clash(weeks, session, d, step) is not None:
        q = urlencode({"confirm": session, "on": d.isoformat(), "orig": item["orig_date"].isoformat(), "by": by})
        return RedirectResponse(f"/?{q}#move", status_code=303)
    new = None if confirm == "skip" else (d + timedelta(days=step)).isoformat()
    db.save_move(item["orig_date"].isoformat(), session, new)
    return _back("week")


@app.post("/move/undo")
def move_undo(day: str = Form("", alias="date"), session: str = Form("")):
    d = _day(day)
    if d is None or session not in view.SESSIONS:
        return _back("week", "Not undone: that isn't a session.")
    s, weeks = build_view()
    items = [wo for w in weeks for wo in w["workouts"]] if session == "run" else \
        [x for w in weeks for x in w.get("strength", []) if x["key"] == session]
    if any(x["orig_date"] == d and x["done"] for x in items):
        return _back("week", "Not undone: it's done on its new day, so it stays there.")
    db.delete_move(d.isoformat(), session)
    return _back("week")
