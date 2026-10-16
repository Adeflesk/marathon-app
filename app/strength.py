"""Strength sessions built from the equipment you actually own.

Two sessions a week: Tuesday B (upper, trunk, light hinge) and Thursday A (single-leg legs,
calves, glutes, ankle). Volume follows the run plan's phase. Nothing here is rehab; it is
general strength work for a runner coming back from an ankle sprain.
"""
import json
from datetime import timedelta
from pathlib import Path

from . import db
from .config import DEFAULTS
from .plan import DAYS

EQUIP_PATH = Path(db.DB_PATH).parent / "equipment.json"

DEFAULT_EQUIPMENT = {
    "barbell": True,
    "bar_kg": 20.0,
    "plates_kg": [1.25, 2.5, 5, 10, 15, 20],  # assumed one pair of each; edit if you have more
    "dumbbells": True,
    "db_min_kg": 2.5,
    "db_max_kg": 35.0,
    "db_step_kg": 1.25,
    "kettlebells_kg": [12, 16],
    "medicine_balls_kg": [5],
    "box": True,
    "rings": True,
    "bench": True,
    "rack": True,
    "pullup": False,
    "bands": True,
}


def load_equipment() -> dict:
    eq = json.loads(json.dumps(DEFAULT_EQUIPMENT))
    if EQUIP_PATH.exists():
        eq.update(json.loads(EQUIP_PATH.read_text()))
    return eq


def save_equipment(eq: dict) -> None:
    EQUIP_PATH.parent.mkdir(parents=True, exist_ok=True)
    EQUIP_PATH.write_text(json.dumps(eq, indent=2))


def tokens(eq: dict) -> set[str]:
    t: set[str] = set()
    if eq.get("barbell") and eq.get("plates_kg"):
        t.add("barbell")
    if eq.get("dumbbells"):
        t.add("dumbbells")
    if eq.get("kettlebells_kg"):
        t.add("kettlebell")
    if eq.get("medicine_balls_kg"):
        t.add("medball")
    for k in ("box", "rings", "bench", "rack", "pullup", "bands"):
        if eq.get(k):
            t.add(k)
    return t


def barbell_loads(eq: dict) -> list[float]:
    """Totals you can build, using each plate once per side."""
    sums = {0.0}
    for p in eq.get("plates_kg", []):
        sums |= {s + p for s in sums}
    return sorted(eq.get("bar_kg", 20.0) + 2 * s for s in sums)


def summary(eq: dict) -> dict:
    out = {}
    if eq.get("barbell") and eq.get("plates_kg"):
        loads = barbell_loads(eq)
        gaps = sorted({round(b - a, 2) for a, b in zip(loads, loads[1:])})
        out["barbell"] = f"{loads[0]:g} to {loads[-1]:g} kg, smallest jump {gaps[0]:g} kg"
    if eq.get("dumbbells"):
        out["dumbbells"] = f"{eq['db_min_kg']:g} to {eq['db_max_kg']:g} kg in {eq['db_step_kg']:g} kg steps"
    return out


# Each slot: ordered candidates (name, needs, cue). The first available is used, or the
# slot rotates through the available ones week to week if rotate=True.
A_SLOTS = [
    dict(kind="main", rotate=True, label="Knee-dominant strength", cands=[
        ("Bulgarian split squat", {"box", "dumbbells"}, "Rear foot on the bench or box, a dumbbell in each hand. Per leg."),
        ("Step-up", {"box", "dumbbells"}, "Whole foot on the box, drive through the heel, lower slowly. Per leg."),
        ("Barbell squat to box", {"barbell", "rack", "box"}, "Set the rack safety bars. Sit back to light contact with the box, then stand. Don't rest on it."),
        ("Reverse lunge", {"dumbbells"}, "Dumbbell in each hand, short controlled steps back. Per leg."),
        ("Split squat", set(), "Bodyweight, slow tempo. Per leg."),
    ]),
    dict(kind="main", rotate=True, label="Hinge", cands=[
        ("Romanian deadlift", {"barbell"}, "Bar close to the legs, soft knees, flat back. Stop when hamstrings stretch."),
        ("Single-leg Romanian deadlift", {"kettlebell"}, "Kettlebell in the opposite hand. Per leg."),
        ("Single-leg Romanian deadlift", {"dumbbells"}, "Dumbbell in the opposite hand. Per leg."),
        ("Good morning", set(), "Bodyweight, hands behind head."),
    ]),
    dict(kind="main", rotate=False, label="Glutes", cands=[
        ("Barbell hip thrust", {"barbell", "bench"}, "Upper back on the bench, bar over the hips with padding. Pause at the top."),
        ("Barbell hip thrust", {"barbell", "box"}, "Upper back on the box, bar over the hips with padding. Pause at the top."),
        ("Single-leg glute bridge", {"dumbbells"}, "Dumbbell on the hip. Per leg."),
        ("Single-leg glute bridge", set(), "Bodyweight, pause at the top. Per leg."),
    ]),
    dict(kind="calf", rotate=False, label="Calf, straight knee", cands=[
        ("Single-leg calf raise, straight knee", {"box", "dumbbells"}, "Ball of foot on the box edge, full range, 2 s down. Dumbbell in the free hand once 15 is easy."),
        ("Single-leg calf raise, straight knee", set(), "Slow, full range, hold a wall for balance. Per leg."),
    ]),
    dict(kind="calf", rotate=False, label="Calf, bent knee", cands=[
        ("Single-leg calf raise, bent knee", {"box"}, "Knee bent about 30 degrees, ball of foot on the box edge. Works the soleus."),
        ("Single-leg calf raise, bent knee", set(), "Knee bent about 30 degrees, slow. Per leg."),
    ]),
    dict(kind="band", rotate=False, label="Ankle strength", cands=[
        ("Banded ankle eversion and inversion", {"bands"}, "Seated, band round the forefoot, slow out and back with no knee or hip movement. Per foot, each direction."),
    ]),
    dict(kind="ankle", rotate=False, label="Balance", cands=[
        ("Single-leg balance with medicine ball catches", {"medball"}, "Soft knee. Catch and return a light pass, then try eyes closed. Per leg."),
        ("Single-leg balance, eyes closed", set(), "Near a wall. Per leg."),
    ]),
    dict(kind="core", rotate=True, label="Core", cands=[
        ("Side plank", set(), "Straight line from head to ankles. Per side."),
        ("Dead bug", set(), "Lower back flat, slow."),
    ]),
]

B_SLOTS = [
    dict(kind="main", rotate=True, label="Pull", cands=[
        ("Ring row", {"rings"}, "Body straight, pull the rings to the ribs. Walk the feet forward to make it harder."),
        ("Single-arm dumbbell row", {"dumbbells", "bench"}, "One hand and knee on the bench, flat back. Per arm."),
        ("Single-arm dumbbell row", {"dumbbells"}, "Hand on the box or a chair. Per arm."),
    ]),
    dict(kind="main", rotate=True, label="Push", cands=[
        ("Barbell bench press", {"barbell", "bench", "rack"}, "Set the rack safety bars. Feet planted, controlled lower to the chest."),
        ("Dumbbell bench press", {"dumbbells", "bench"}, "Dumbbells over the chest, elbows about 45 degrees."),
        ("Ring push-up", {"rings"}, "Rings low, elbows about 45 degrees. Raise the rings if shoulders complain."),
        ("Push-up", set(), "Body in one line."),
    ]),
    dict(kind="main", rotate=False, label="Press", cands=[
        ("Single-arm dumbbell overhead press", {"dumbbells"}, "Standing, ribs down, no leaning back. Per arm."),
        ("Pike push-up", set(), "Hips high, head between the arms."),
    ]),
    dict(kind="swing", rotate=False, label="Hinge power", cands=[
        ("Kettlebell swing", {"kettlebell"}, "Hips drive the bell, arms just guide it. The 16 kg once the 12 kg feels easy."),
    ]),
    dict(kind="carry", rotate=True, label="Carry", cands=[
        ("Farmer's carry", {"dumbbells"}, "Heavy dumbbell in each hand, tall posture, quick small steps."),
        ("Suitcase carry", {"kettlebell"}, "One kettlebell, stay level, don't lean. Both sides."),
    ]),
    dict(kind="core", rotate=True, label="Core", cands=[
        ("Ring fallout", {"rings"}, "Short range at first, ribs down."),
        ("Pallof press", {"bands"}, "Band anchored at chest height, press out and resist the twist. Per side."),
        ("Medicine ball slam", {"medball"}, "Full body, stay braced."),
        ("Dead bug", set(), "Lower back flat, slow."),
    ]),
]


def _pick(slot: dict, toks: set[str], week_index: int) -> tuple[str, str] | None:
    avail = [c for c in slot["cands"] if c[1] <= toks]
    if not avail:
        return None
    if slot["rotate"]:
        # rotate between candidates that need real equipment, not the bodyweight fallback
        real = [c for c in avail if c[1]] or avail
        seen, uniq = set(), []
        for cand in real:  # kettlebell and dumbbell variants of one lift count once
            if cand[0] not in seen:
                seen.add(cand[0])
                uniq.append(cand)
        c = uniq[week_index % len(uniq)]
    else:
        c = avail[0]
    return c[0], c[2]


def _rx(kind: str, phase: str, reduced: bool) -> str:
    if phase == "Rebuild":
        table = {"main": "2 x 10-12, RPE 6", "calf": "2 x 12-15", "ankle": "2 x 30 s", "core": "2 x 30 s",
                 "swing": "2 x 12, light", "carry": "2 x 30 m", "band": "2 x 15"}
    elif phase == "Peak":
        table = {"main": "2 x 6, RPE 6" if reduced else "2 x 5-6, RPE 7-8", "calf": "2 x 10", "ankle": "2 x 30 s",
                 "core": "2 x 30 s", "swing": "2 x 10", "carry": "2 x 40 m", "band": "2 x 15"}
    elif phase in ("Taper", "Cutback") or reduced:
        table = {"main": "2 x 8, RPE 6", "calf": "2 x 10", "ankle": "2 x 30 s", "core": "2 x 30 s",
                 "swing": "2 x 10, light", "carry": "2 x 30 m", "band": "2 x 15"}
    else:  # Build
        table = {"main": "3 x 6-8, RPE 7-8", "calf": "3 x 10, slow", "ankle": "2 x 30 s", "core": "3 x 30-40 s",
                 "swing": "3 x 12", "carry": "3 x 40 m", "band": "3 x 15"}
    return table[kind]


def _session(name, day, slots, toks, week, reduced, minutes, note):
    ex = []
    for s in slots:
        pick = _pick(s, toks, week["week"])
        if not pick:
            continue
        ex.append({"slot": s["label"], "name": pick[0], "cue": pick[1], "rx": _rx(s["kind"], week["phase"], reduced)})
    return {
        "name": name, "date": day, "day": day.strftime("%a"), "minutes": minutes,
        "warmup": "5 min easy walk or bike, then leg swings, hip circles and 10 bodyweight squats.",
        "exercises": ex, "reduced": reduced, "note": note,
    }


def sessions_for_week(week: dict, eq: dict, factor: float = 1.0, days: dict | None = None) -> list[dict]:
    phase = week["phase"]
    monday = week["start"]
    toks = tokens(eq)
    if phase == "Race week":
        return []
    days = {**DEFAULTS["strength_days"], **(days or {})}
    a_day = monday + timedelta(days=DAYS.index(days["A"]))
    b_day = monday + timedelta(days=DAYS.index(days["B"]))
    # a tempo run the day before or after the leg session makes the legs a poor place to add volume
    has_tempo = any(w["type"] == "tempo" and abs((w["date"] - a_day).days) == 1 for w in week["workouts"])
    cut = factor < 1.0
    out = []
    taper2 = phase == "Taper" and week["target_km"] <= 31
    if not taper2:
        reduced_a = has_tempo or cut or phase in ("Cutback", "Taper")
        note = ""
        if cut:
            note = "Trimmed because of last week's check-in. Skip the loaded single-leg work if the ankle is sore."
        elif has_tempo:
            note = "A tempo run is next to this session, so the volume is kept lower."
        out.append(_session("Strength A: legs and ankle", a_day, A_SLOTS, toks, week,
                            reduced_a, 45, note))
    out.append(_session("Strength B: upper body and trunk", b_day, B_SLOTS, toks, week,
                           cut or phase in ("Cutback", "Taper"), 35, ""))
    out.sort(key=lambda x: x["date"])
    return out
