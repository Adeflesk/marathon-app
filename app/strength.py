"""Strength sessions built from the equipment you actually own.

Two sessions a week, as `reports/Runner strength routine review.md` lays out: Thursday A (hops, box
squat, RDL, a single-leg lift fixed per block, loaded calves, optional hip thrust) and Tuesday B (balance,
single-leg RDL, row and push-up, carry and core, bent-knee calf and eversion). Doses follow the plan's
phase; Thursday stays at full dose unless a check-in, a hard Wednesday or the ankle flag trims it.
Nothing here is rehab; it is general strength work for a runner coming back from an ankle sprain.
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




def _ex(name, cue, load, needs=(), ankle=False, per_side=False, fallback=None, harder=None):
    return {"name": name, "cue": cue, "load": load, "needs": set(needs), "ankle": ankle,
            "per_side": per_side, "fallback": fallback, "harder": harder}


# The catalogue, keyed by a stable key that logs refer to. `needs` are equipment tokens; when they
# aren't all there, `fallback` names the exercise to use instead. `harder` is the variation a top-weight
# ladder moves on to. `ankle` marks calf, soleus, eversion, balance, hop and single-leg items.
EXERCISES: dict[str, dict] = {
    # Thursday A
    "hops": _ex("Hops", "Current hop stage, on fresh calves. Low, stiff ankles, quiet landings.",
                "hops", ankle=True),
    "box_squat": _ex("Barbell box squat",
                     "Rack safeties 1–2 inches below the bottom position. Sit back to light contact with the box, "
                     "then stand; don't rest on it. Rest 2–3 min.",
                     "barbell_lower", {"barbell", "rack", "box"}, fallback="goblet_squat"),
    "goblet_squat": _ex("Dumbbell goblet squat", "One dumbbell held at the chest, sit down between the heels. Rest 2–3 min.",
                        "dumbbell_lower", {"dumbbells"}, fallback="split_squat"),
    "rdl": _ex("Barbell Romanian deadlift",
               "Bar close to the legs, soft knees, flat back. Stop when the hamstrings stretch. Rest 2–3 min.",
               "barbell_lower", {"barbell"}, fallback="db_rdl"),
    "db_rdl": _ex("Dumbbell Romanian deadlift", "A dumbbell in each hand, soft knees, flat back. Rest 2–3 min.",
                  "dumbbell_lower", {"dumbbells"}, fallback="good_morning"),
    "good_morning": _ex("Good morning", "Bodyweight, hands behind the head, hinge from the hips.", "bodyweight"),
    "step_up": _ex("Dumbbell step-up", "Whole foot on the box, drive through the heel, lower slowly. Per leg.",
                   "dumbbell_lower", {"box", "dumbbells"}, ankle=True, per_side=True,
                   fallback="reverse_lunge", harder="bulgarian_split_squat"),
    "reverse_lunge": _ex("Dumbbell reverse lunge", "A dumbbell in each hand, short controlled steps back. Per leg.",
                         "dumbbell_lower", {"dumbbells"}, ankle=True, per_side=True,
                         fallback="split_squat", harder="bulgarian_split_squat"),
    "bulgarian_split_squat": _ex("Dumbbell Bulgarian split squat",
                                 "Rear foot on the bench or box, a dumbbell in each hand. Per leg.",
                                 "dumbbell_lower", {"box", "dumbbells"}, ankle=True, per_side=True,
                                 fallback="reverse_lunge"),
    "split_squat": _ex("Split squat", "Bodyweight, slow tempo. Per leg.", "bodyweight", ankle=True, per_side=True,
                       harder="bulgarian_split_squat"),
    "calf_raise_straight": _ex("Single-leg calf raise, straight knee",
                               "Ball of the foot on the box edge, dumbbell in the same-side hand, 3 s lowering. "
                               "Pick the weight that leaves 3–4 reps in the tank; bodyweight is fine while that is enough.",
                               "dumbbell", ankle=True, per_side=True, harder="deficit_calf_raise"),
    "deficit_calf_raise": _ex("Single-leg deficit calf raise, straight knee",
                              "Ball of the foot on a plate on the box, heel drops well below it, dumbbell in the "
                              "same-side hand, 3 s lowering.",
                              "dumbbell", {"box"}, ankle=True, per_side=True, fallback="calf_raise_straight"),
    "seated_soleus_raise": _ex("Seated barbell soleus raise",
                               "Sit on the bench or box, bar padded across the knees, balls of the feet on a plate "
                               "or the box edge. Slow, 2 s pause at the top.",
                               "barbell_lower", {"barbell"}, ankle=True, fallback="calf_raise_bent"),
    "hip_thrust": _ex("Barbell hip thrust (optional)",
                      "Upper back on the bench, bar padded over the hips, pause at the top. Cut it first if time is short.",
                      "barbell_lower", {"barbell", "bench"}, fallback="glute_bridge"),
    "glute_bridge": _ex("Single-leg glute bridge (optional)", "Pause at the top. Per leg. Cut it first if time is short.",
                        "bodyweight", per_side=True),
    # Tuesday B
    "balance_block": _ex("Ankle balance block", "Current balance stage, both legs, injured side first.",
                         "timed", ankle=True, per_side=True),
    "sl_rdl_db": _ex("Dumbbell single-leg Romanian deadlift",
                     "Dumbbell in the opposite hand, hips square. Never above RPE 7. Per leg.",
                     "dumbbell", {"dumbbells"}, ankle=True, per_side=True, fallback="sl_rdl_kb"),
    "sl_rdl_kb": _ex("Kettlebell single-leg Romanian deadlift",
                     "Kettlebell in the opposite hand, hips square. Never above RPE 7. Per leg.",
                     "kettlebell", {"kettlebell"}, ankle=True, per_side=True, fallback="sl_rdl_bw"),
    "sl_rdl_bw": _ex("Single-leg Romanian deadlift", "Bodyweight, reach the hands to the floor, hips square. Per leg.",
                     "bodyweight", ankle=True, per_side=True, harder="sl_rdl_db"),
    "ring_row": _ex("Ring row",
                    "Body straight, pull the rings to the ribs. Walk the feet forward to make it harder. Superset "
                    "with the push-up. Hang the rings only from an anchor rated for body weight.",
                    "rings", {"rings"}, fallback="db_row"),
    "db_row": _ex("Single-arm dumbbell row", "Hand and knee on the bench or box, flat back. Per arm. Superset with the push-up.",
                  "dumbbell", {"dumbbells"}, per_side=True),
    "push_up": _ex("Push-up", "Body in one line, elbows about 45 degrees.", "bodyweight", harder="ring_push_up"),
    "ring_push_up": _ex("Ring push-up", "Rings low, elbows about 45 degrees. Raise the rings if the shoulders complain.",
                        "rings", {"rings"}, fallback="push_up"),
    "suitcase_carry": _ex("Suitcase carry", "One heavy dumbbell, stay level, don't lean. Both sides. Superset with the core move.",
                          "carry", {"dumbbells"}, per_side=True, fallback="suitcase_carry_kb"),
    "suitcase_carry_kb": _ex("Kettlebell suitcase carry", "One kettlebell, stay level, don't lean. Both sides.",
                             "carry", {"kettlebell"}, per_side=True),
    "pallof_press": _ex("Pallof press", "Band anchored at chest height, press out and resist the twist. Per side.",
                        "band", {"bands"}, per_side=True, fallback="dead_bug"),
    "dead_bug": _ex("Dead bug", "Lower back flat on the floor, slow.", "timed"),
    "side_plank": _ex("Side plank", "Straight line from head to ankles. Per side.", "timed", per_side=True),
    # Adductors: the one area the research routine left out. No ankle load (the top leg rests on the bench).
    "copenhagen_short": _ex("Copenhagen plank, short lever",
                            "Side plank with the top knee on a bench, chair or sofa and the bottom leg tucked or "
                            "hovering. Squeeze the top knee down to lift the hips. Per side.",
                            "timed", per_side=True, harder="copenhagen_long"),
    "copenhagen_long": _ex("Copenhagen plank, long lever",
                           "Side plank with the top foot or ankle on the bench and the bottom leg hovering. Hips "
                           "high, body in one line. Drop back to the knee if the groin complains. Per side.",
                           "timed", per_side=True),
    "calf_raise_bent": _ex("Single-leg calf raise, bent knee",
                           "Knee bent about 30 degrees, ball of the foot on the box edge or a step. Works the soleus. "
                           "Superset with the band eversion.",
                           "bodyweight", ankle=True, per_side=True),
    "band_eversion": _ex("Eccentric band eversion",
                         "Seated, band round the forefoot. Turn the foot out, then lower slowly over 3–4 s with no "
                         "knee or hip movement. A heavier band once 3 × 15 is easy. Per foot.",
                         "band", {"bands"}, ankle=True, per_side=True),
}


def _rx(sets, lo, hi, rpe):
    return {"sets": sets, "lo": lo, "hi": hi, "rpe": rpe}


# Tuesday's calves are a lighter second dose, so they get their own row (`tue_calf`).
_TUE_BUILD = {"tue_lift": _rx(2, 8, 10, "6–7"), "tue_upper": _rx(2, 8, 10, "6–7"), "tue_calf": _rx(2, 10, 15, "6–7"),
              "carry": _rx(2, 40, 40, ""), "core": _rx(2, 30, 40, ""), "band": _rx(2, 15, 15, ""),
              "balance": _rx(2, 30, 45, ""), "adductor": _rx(2, 20, 30, "")}
_TUE_EASY = {**_TUE_BUILD, "tue_lift": _rx(2, 8, 10, "≤6"), "tue_upper": _rx(2, 8, 10, "≤6"),
             "tue_calf": _rx(2, 10, 15, "≤6"), "adductor": _rx(2, 20, 20, "")}

# The report's phase table. Carries count lo/hi in metres, core and balance in seconds, the rest in reps.
# A role missing from a phase means that exercise is dropped that phase.
ROLE_RX: dict[str, dict[str, dict]] = {
    "Rebuild": {
        "main": _rx(2, 8, 10, "6–7"), "single_leg": _rx(2, 8, 10, "6"), "hip_thrust": _rx(2, 8, 10, "6"),
        "calf": _rx(3, 12, 15, "6–7"), "soleus": _rx(3, 12, 15, "6–7"),
        "tue_lift": _rx(2, 8, 10, "6–7"), "tue_upper": _rx(2, 8, 10, "6–7"), "tue_calf": _rx(2, 15, 15, "6–7"),
        "carry": _rx(2, 30, 30, ""), "core": _rx(2, 30, 30, ""), "band": _rx(2, 15, 15, ""),
        "balance": _rx(2, 30, 45, ""), "adductor": _rx(2, 15, 25, ""),
    },
    "Build": {
        "main": _rx(3, 6, 8, "7–8"), "single_leg": _rx(3, 6, 8, "7–8"), "hip_thrust": _rx(3, 6, 8, "7–8"),
        "calf": _rx(3, 8, 12, "7–8"), "soleus": _rx(3, 8, 12, "7–8"), **_TUE_BUILD,
    },
    "Cutback": {  # same load as the week before, one set fewer
        "main": _rx(2, 6, 8, "6–7"), "single_leg": _rx(2, 6, 8, "6"), "hip_thrust": _rx(2, 6, 8, "6–7"),
        "calf": _rx(2, 8, 12, "6–7"), "soleus": _rx(2, 8, 12, "6–7"), **_TUE_EASY,
    },
    "Peak": {
        "main": _rx(2, 4, 6, "7"), "single_leg": _rx(2, 6, 6, "7"), "hip_thrust": _rx(2, 6, 6, "7"),
        "calf": _rx(2, 8, 10, "7"), "soleus": _rx(2, 8, 10, "7"), **_TUE_BUILD,
    },
    "Taper 1": {
        "main": _rx(2, 4, 5, "≤7"), "single_leg": _rx(2, 5, 5, "6"), "hip_thrust": _rx(2, 5, 5, "6"),
        "calf": _rx(2, 8, 8, "6"), "soleus": _rx(2, 8, 8, "6"),
        **_TUE_EASY, "carry": _rx(2, 30, 30, ""), "core": _rx(2, 30, 30, ""),
    },
    # Tuesday only, and light: balance, eversion, core, ring row and push-ups. No heavy calves.
    "Taper 2": {
        "tue_upper": _rx(2, 8, 10, "≤6"), "core": _rx(2, 30, 30, ""), "band": _rx(2, 15, 15, ""),
        "balance": _rx(2, 30, 45, ""),
    },
}

# Hop stages from the report: exercises and contacts per session.
HOP_STAGES = [
    {"name": "Pogo hops and drop-and-stick", "sets": 3, "lo": 10, "hi": 15, "per_side": False,
     "cue": "Two-leg pogos, low and stiff-ankled; then drop off a low step and stick the landing. 30–40 contacts."},
    {"name": "Pogos, line hops and low box jump", "sets": 3, "lo": 20, "hi": 20, "per_side": False,
     "cue": "Pogos 3 × 20; two-leg line hops forward/back and side to side, 2 × 10 s each; low box jump, "
            "step down. About 60 contacts."},
    {"name": "Single-leg pogos and hop-and-stick", "sets": 3, "lo": 10, "hi": 10, "per_side": True,
     "cue": "Single-leg pogo 3 × 10 per side; single-leg hop-and-stick forward, outward and inward, 5 each; "
            "skater bounds with a hold. 60–80 contacts."},
    {"name": "Single-leg line hops and continuous hops", "sets": 3, "lo": 8, "hi": 10, "per_side": True,
     "cue": "Single-leg line hops 3 × 10 s; crossover hops; continuous single-leg hops 3 × 8–10; box jump to "
            "a single-leg landing. 80–100 contacts."},
]

BALANCE_STAGES = [
    "Eyes open, soft knee.",
    "Eyes closed, near a wall.",
    "Medicine ball catches: catch and return a light pass.",
    "Band perturbations: a band round the waist pulling you sideways.",
    "Y-balance reaches: forward, back-inward and back-outward.",
    "Single-leg RDL with a reach.",
    "Hop-and-stick in each direction.",
]

MAIN_ROLES = {"A": {"main"}, "B": {"tue_lift", "tue_upper"}}
WARMUP = {
    "A": "5 min easy bike or walk, leg swings, 10 bodyweight squats, then 1 × 30 s single-leg balance per leg.",
    "B": "5 min easy bike or walk, leg swings and hip circles.",
}


def _phase_key(week: dict) -> str:
    if week["phase"] == "Taper":
        return "Taper 2" if week["weeks_to_race"] <= 1 else "Taper 1"
    return week["phase"]


def _resolve(key: str, toks: set[str]) -> str | None:
    """The exercise itself if the equipment allows it, else the first fallback that does."""
    seen = set()
    while key and key not in seen:
        seen.add(key)
        if EXERCISES[key]["needs"] <= toks:
            return key
        key = EXERCISES[key]["fallback"]
    return None


def _cap(rpe: str, cap: int) -> str:
    """Effort no higher than `cap`; an existing lower ceiling is kept."""
    nums = [int(c) for c in rpe if c.isdigit()]
    return rpe if nums and max(nums) <= cap else f"≤{cap}"


def _effort(rpe: str) -> str:
    if not rpe:
        return ""
    if rpe.startswith("≤"):
        return f"at least {10 - int(rpe[1:])} reps left (RPE {rpe})"
    if "–" in rpe:
        a, b = (int(x) for x in rpe.split("–"))
        return f"about {10 - b}–{10 - a} reps left (RPE {rpe})"
    return f"about {10 - int(rpe)} reps left (RPE {rpe})"


def _rx_text(e: dict) -> str:
    unit = {"carry": " m", "core": " s", "balance": " s", "adductor": " s"}.get(e["role"], "")
    reps = f"{e['lo']}" if e["lo"] == e["hi"] else f"{e['lo']}–{e['hi']}"
    text = f"{e['sets']} × {reps}{unit}"
    if e["per_side"]:
        text += " each side"
    effort = _effort(e["rpe"])
    return f"{text}, {effort}" if effort else text


def _plan_a(week: dict, ctx: dict) -> list[tuple[str, str]]:
    block = week["strength_block"]
    single = "step_up" if block == 0 else "reverse_lunge" if block == 1 else "bulgarian_split_squat"
    slots = [("hops", "hops")] if ctx.get("hop_stage") is not None else []
    return slots + [("box_squat", "main"), ("rdl", "main"), (single, "single_leg"),
                    ("calf_raise_straight", "calf"), ("seated_soleus_raise", "soleus"), ("hip_thrust", "hip_thrust")]


def _plan_b(week: dict, ctx: dict) -> list[tuple[str, str]]:
    block = week["strength_block"]
    push = "push_up" if block == 0 else "ring_push_up"
    core = ("pallof_press", "dead_bug", "side_plank")[block % 3]
    cop = "copenhagen_short" if block == 0 else "copenhagen_long"
    return [("balance_block", "balance"), ("sl_rdl_db", "tue_lift"), ("ring_row", "tue_upper"), (push, "tue_upper"),
            ("suitcase_carry", "carry"), (core, "core"), (cop, "adductor"), ("calf_raise_bent", "tue_calf"),
            ("band_eversion", "band")]


def _hops(phase: str, stage: int) -> dict:
    if phase == "Taper 1":  # pogos only, about 30 contacts
        st = {**HOP_STAGES[0], "name": "Pogo hops", "sets": 2, "lo": 15, "hi": 15,
              "cue": "Two-leg pogos only, low and stiff-ankled. About 30 contacts."}
    else:
        st = dict(HOP_STAGES[max(0, min(stage, len(HOP_STAGES) - 1))])
        if phase == "Cutback":  # hold the stage, about two-thirds of the contacts
            st["sets"] = 2
    return st


def _session(key: str, week: dict, eq: dict, ctx: dict, day) -> dict:
    phase = _phase_key(week)
    table = ROLE_RX["Rebuild" if ctx.get("restart") and phase != "Taper 2" else phase]
    toks = tokens(eq)
    factor = ctx.get("factor", 1.0)
    trims = []
    if factor < 1.0:
        trims.append("Trimmed because of last week's check-in.")
    if key == "A" and ctx.get("wed_bad"):
        trims.append("Wednesday's session was hard, so the main lifts lose a set and effort is capped.")
    if key == "A" and ctx.get("ankle_flag"):
        trims.append("The ankle flag is up: the main lifts lose a set and effort is capped. "
                     "Stop any item that takes ankle pain above 3 out of 10.")
    cap = 6 if factor <= 0.8 else 7

    exercises = []
    for ex_key, role in (_plan_a if key == "A" else _plan_b)(week, ctx):
        if role == "hops":
            st = _hops(phase, ctx["hop_stage"])
            e = EXERCISES["hops"]
            exercises.append({"key": "hops", "name": st["name"], "cue": st["cue"], "role": "hops",
                              "sets": st["sets"], "lo": st["lo"], "hi": st["hi"], "rpe": "", "load": e["load"],
                              "ankle": True, "per_side": st["per_side"]})
            continue
        if role not in table:
            continue
        chosen = _resolve(ex_key, toks)
        if chosen is None:
            continue
        e = EXERCISES[chosen]
        rx = dict(table[role])
        if trims and role in MAIN_ROLES[key]:
            rx["sets"] = max(1, rx["sets"] - 1)
            rx["rpe"] = _cap(rx["rpe"], cap)
        cue = e["cue"]
        if role == "balance":
            stage = max(0, min(ctx.get("balance_stage", 0), len(BALANCE_STAGES) - 1))
            cue = f"{BALANCE_STAGES[stage]} {cue}"
        exercises.append({"key": chosen, "name": e["name"], "cue": cue, "role": role, **rx, "load": e["load"],
                          "ankle": e["ankle"], "per_side": e["per_side"]})
    for x in exercises:
        x["rx"] = _rx_text(x)

    note = " ".join(trims)
    if ctx.get("restart"):
        note = ("Back after time off: Rebuild doses at about 80% of your last loads. " + note).strip()
    return {
        "key": key,
        "name": "Strength A: heavy legs and hops" if key == "A" else "Strength B: light full body and ankle",
        "date": day, "day": day.strftime("%a"),
        "minutes": 45 if key == "A" else (25 if phase == "Taper 2" else 40),
        "reduced": bool(trims), "note": note, "warmup": WARMUP[key], "exercises": exercises,
    }


def sessions_for_week(week: dict, eq: dict, ctx: dict) -> list[dict]:
    """Thursday A and Tuesday B for one plan week, per the report's phase table and override rules.

    ctx: factor, wed_bad, ankle_flag, hop_stage (None = not yet), balance_stage, restart, days.
    """
    phase = _phase_key(week)
    if phase == "Race week":
        return []
    days = {**DEFAULTS["strength_days"], **(ctx.get("days") or {})}
    out = [_session("B", week, eq, ctx, week["start"] + timedelta(days=DAYS.index(days["B"])))]
    if phase != "Taper 2":
        out.append(_session("A", week, eq, ctx, week["start"] + timedelta(days=DAYS.index(days["A"]))))
    out.sort(key=lambda x: x["date"])
    return out
