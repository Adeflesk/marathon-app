import base64
import os
import secrets
from contextlib import asynccontextmanager
from datetime import date, datetime, timedelta
from pathlib import Path
from urllib.parse import urlencode

from fastapi import FastAPI, Form, Request
from fastapi.responses import RedirectResponse, Response
from fastapi.templating import Jinja2Templates

from . import db, garmin, smashrun, strength
from .config import load_settings, race_date
from .pace_engine import fmt_pace, fmt_time, pace_per_mi
from .plan import _half, feedback_factor, generate

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
templates.env.filters["pace"] = fmt_pace
templates.env.filters["pace_mi"] = lambda s: fmt_pace(pace_per_mi(s))


def today() -> date:
    return date.today()


def actual_by_date() -> dict[str, dict]:
    out: dict[str, dict] = {}
    with db.conn() as c:
        for r in c.execute("SELECT date, km, seconds, avg_hr FROM activities"):
            d = out.setdefault(r["date"], {"km": 0.0, "seconds": 0, "hr": []})
            d["km"] += r["km"]
            d["seconds"] += r["seconds"]
            if r["avg_hr"]:
                d["hr"].append(r["avg_hr"])
    return out


def build_view():
    s = load_settings()
    weeks = generate(s, today())
    actual = actual_by_date()
    eq = strength.load_equipment()
    with db.conn() as c:
        checkins = {r["week"]: dict(r) for r in c.execute("SELECT * FROM checkins")}
    t = today()
    for w in weeks:
        factor = feedback_factor(checkins.get(w["week"] - 1))
        w["factor"] = factor
        w["checkin"] = checkins.get(w["week"])
        wk_actual = 0.0
        for wo in w["workouts"]:
            if factor != 1.0 and wo["type"] != "race":
                wo["km"] = _half(wo["km"] * factor)
                if wo["type"] == "tempo":
                    # shorten the tempo too, so 2 km WU + tempo + 1 km CD fits the trimmed distance
                    fits = int((wo["km"] - 3) * s["paces"]["tempo"] / 60)
                    wo["tempo_min"] = max(0, min(round(wo["tempo_min"] * factor), fits))
                    wo["note"] = f"2 km warm-up, {wo['tempo_min']} min at tempo pace, 1 km cool-down."
            a = actual.get(wo["date"].isoformat())
            wo["actual_km"] = round(a["km"], 1) if a else None
            wo["actual_pace"] = (a["seconds"] / a["km"]) if a and a["km"] else None
            wo["compliance"] = round(100 * a["km"] / wo["km"]) if a and wo["km"] else None
            wo["past"] = wo["date"] < t
        w["target_km"] = round(sum(wo["km"] for wo in w["workouts"]), 1)
        for i in range(7):
            d = (w["start"] + timedelta(days=i)).isoformat()
            if d in actual:
                wk_actual += actual[d]["km"]
        w["actual_km"] = round(wk_actual, 1)
        w["strength"] = strength.sessions_for_week(w, eq, factor, s["strength_days"])
        w["is_current"] = w["start"] <= t < w["start"] + timedelta(days=7)
        w["is_past"] = w["start"] + timedelta(days=7) <= t
    return s, weeks


@app.get("/")
def dashboard(request: Request, msg: str = ""):
    s, weeks = build_view()
    t = today()
    current = next((w for w in weeks if w["is_current"]), None)
    upcoming = weeks[0] if t < weeks[0]["start"] else current
    days_left = (race_date(s) - t).days
    chart = {
        "labels": [f"W{w['week']}" for w in weeks],
        "planned": [w["target_km"] for w in weeks],
        "actual": [w["actual_km"] if (w["is_past"] or w["is_current"]) else None for w in weeks],
    }
    return templates.TemplateResponse(
        request,
        "index.html",
        {
            "s": s,
            "week": upcoming,
            "days_left": days_left,
            "weeks_left": days_left // 7,
            "chart": chart,
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
        {"s": s, "w": chosen, "n": len(weeks), "eq_summary": strength.summary(strength.load_equipment())},
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


def _find_workout(day: str):
    s, weeks = build_view()
    for w in weeks:
        for wo in w["workouts"]:
            if wo["date"].isoformat() == day:
                return s, wo
    return s, None


@app.get("/workout/{day}.fit")
def workout_fit(day: str):
    s, wo = _find_workout(day)
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
