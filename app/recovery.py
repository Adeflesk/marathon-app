"""The recovery signal: low HRV raises a suspicion, the next run confirms it or not, and the advice clears when
HRV is back in band.

Pure, recomputed every request like the plan. HRV leads; resting heart rate and sleep only add weight (they never
start an episode). Nothing here trims the plan by itself: `offer` says which button the page may show, and only a
stored choice (`trims`) changes anything, elsewhere.

An episode starts on a night when HRV has been below the band three nights running, or the 7-day average is below
it. It clears when HRV is back in band two nights running and the 7-day average isn't low. In between, runs on or
after the start are judged in date order: the first that confirms turns the suspicion into advice, and three more
nights or two more judged runs without clearing make the warning firm.
"""
from datetime import date, timedelta
from statistics import mean, median
from typing import TypedDict

from .progress import PACE_BAND

RHR_UP = 5  # bpm over the 30-day mean
SLEEP_SHORT = 6 * 3600  # s
SLEEP_POOR = 60  # Garmin sleep score
HR_UP = 5  # bpm at easy pace over the 4-week median
DRIFT_CONFIRM = 10  # % on the run…
DRIFT_NORMAL = 5  # …when the 4-week median drift is under this
FIRM_NIGHTS = 3  # nights after the confirming run
FIRM_RUNS = 2  # judged runs after the confirming run

LOW_NIGHTS = 3  # nights below the band in a row to start an episode
CLEAR_NIGHTS = 2  # nights in band in a row (with the 7-day average not low) to end it
BASELINE_DAYS = 28  # the window for a run's heart-rate and drift baselines
MIN_BASELINE = 2  # earlier runs needed before heart rate or drift can confirm
MIN_SPLITS = 3  # km splits at easy pace for an easy run to be judged
RHR_DAYS = 30
MIN_RHR_DAYS = 7  # earlier resting-HR readings needed for a mean


class Run(TypedDict):
    """A run as recovery judges it. `kind` is "easy" (easy or long), "quality" or "strides".

    `splits` is `review.splits()` output, per km [{km, pace, hr}] (not the stored cumulative list); `drift` is
    `review.drift()` of them; `verdict` is the quality review's verdict ("bad" confirms)."""
    date: date
    kind: str
    splits: list | None
    drift: float | None
    verdict: str | None


def _low(row: dict | None) -> bool:
    return bool(row) and row["hrv_night"] is not None and row["hrv_low"] is not None \
        and row["hrv_night"] < row["hrv_low"]


def _in_band(row: dict | None) -> bool:
    return bool(row) and row["hrv_night"] is not None and row["hrv_low"] is not None \
        and row["hrv_night"] >= row["hrv_low"]


def _avg_low(row: dict | None) -> bool:
    return bool(row) and row["hrv_week_avg"] is not None and row["hrv_low"] is not None \
        and row["hrv_week_avg"] < row["hrv_low"]


def easy_hr(run: Run, easy_pace: float) -> float | None:
    """Median HR of the run's km splits near easy pace (first km dropped), as Progress's fitness trend does."""
    hrs = [sp["hr"] for sp in (run["splits"] or [])[1:]
           if sp["km"] >= 0.9 and sp["hr"] and abs(sp["pace"] - easy_pace) <= PACE_BAND]
    return median(hrs) if len(hrs) >= MIN_SPLITS else None


def _day(d: date) -> str:
    return d.strftime("%A")


def _judge(run: Run, runs: list[Run], easy_pace: float) -> tuple[str, str] | None:
    """None when the run can't be judged, else ("normal" | "confirm", the reason in words)."""
    when = _day(run["date"])
    normal = ("normal", f"{when}'s run looked normal")
    if run["kind"] == "strides":
        return None
    if run["kind"] == "quality":
        if run["verdict"] is None:
            return None
        return ("confirm", f"{when}'s session fell short") if run["verdict"] == "bad" else normal
    value = easy_hr(run, easy_pace)
    if value is None:
        return None
    lo = run["date"] - timedelta(days=BASELINE_DAYS)
    earlier = [r for r in runs if r["kind"] not in ("quality", "strides") and lo <= r["date"] < run["date"]]
    values = [v for v in (easy_hr(r, easy_pace) for r in earlier) if v is not None]
    if len(values) >= MIN_BASELINE and value >= median(values) + HR_UP:
        return "confirm", f"easy-pace heart rate up {round(value - median(values))} bpm on {when}'s run"
    drifts = [r["drift"] for r in earlier if r["drift"] is not None]
    if run["drift"] is not None and run["drift"] >= DRIFT_CONFIRM and len(drifts) >= MIN_BASELINE \
            and median(drifts) < DRIFT_NORMAL:
        return "confirm", f"heart rate drifted {round(run['drift'])}% on {when}'s run, which usually stays steady"
    return normal


def _support(rows: list[dict]) -> list[str]:
    out = []
    with_rhr = [r for r in rows if r["rhr"] is not None]
    if with_rhr:
        last = with_rhr[-1]
        d = date.fromisoformat(last["date"])
        lo = (d - timedelta(days=RHR_DAYS)).isoformat()
        before = [r["rhr"] for r in with_rhr if lo <= r["date"] < last["date"]]
        if len(before) >= MIN_RHR_DAYS and last["rhr"] >= mean(before) + RHR_UP:
            out.append(f"Resting heart rate is up {round(last['rhr'] - mean(before))} bpm")
    if rows:
        by_date = {r["date"]: r for r in rows}
        d = date.fromisoformat(rows[-1]["date"])

        def poor(r):
            return bool(r) and ((r["sleep_s"] is not None and r["sleep_s"] < SLEEP_SHORT)
                                or (r["sleep_score"] is not None and r["sleep_score"] < SLEEP_POOR))

        if all(poor(by_date.get((d - timedelta(days=i)).isoformat())) for i in range(2)):
            out.append("Short or poor sleep two nights running")
    return out


def state(wellness: list[dict], runs: list[Run], trims: list[dict], t: date, easy_pace: float) -> dict:
    """The recovery state on day `t` (today), from wellness rows, runs and the trims taken. Data after `t` is
    ignored. `offer` doesn't know about race week; the view leaves the button out there."""
    rows = sorted((r for r in wellness if r["date"] <= t.isoformat()), key=lambda r: r["date"])
    runs = sorted((r for r in runs if r["date"] <= t), key=lambda r: r["date"])
    by_date = {date.fromisoformat(r["date"]): r for r in rows}

    ep = None  # the open episode
    if rows:
        d = date.fromisoformat(rows[0]["date"])
        while d <= t:
            row = by_date.get(d)
            if ep is None:
                if all(_low(by_date.get(d - timedelta(days=i))) for i in range(LOW_NIGHTS)) or _avg_low(row):
                    why = []
                    if _low(row) and _low(by_date.get(d - timedelta(days=1))) \
                            and _low(by_date.get(d - timedelta(days=2))):
                        why.append(f"HRV below your normal range {LOW_NIGHTS} nights running")
                    if _avg_low(row):
                        why.append("7-day HRV average below your normal range")
                    ep = {"since": d, "why": why, "run": None, "said": None, "confirmed": None,
                          "nights": 0, "runs": 0}
            elif all(_in_band(by_date.get(d - timedelta(days=i))) for i in range(CLEAR_NIGHTS)) \
                    and not _avg_low(row):
                ep = None
            elif ep["confirmed"] and d > ep["confirmed"] and row and row["hrv_night"] is not None:
                ep["nights"] += 1
            if ep:
                for run in (r for r in runs if r["date"] == d):
                    judged = _judge(run, runs, easy_pace)
                    if judged is None:
                        continue
                    if ep["confirmed"]:
                        ep["runs"] += 1
                    else:
                        ep["run"], ep["said"] = run, judged[1]
                        if judged[0] == "confirm":
                            ep["confirmed"] = run["date"]
            d += timedelta(days=1)

    out = {"phase": "none", "since": None, "reasons": [], "support": _support(rows), "run": None,
           "trim_taken": False, "easy_taken": False, "offer": None, "rest": False, "last": rows[-1] if rows else None}
    if ep is None:
        return out
    taken = {tr["kind"] for tr in trims if ep["since"] <= date.fromisoformat(tr["date"]) <= t}
    if ep["confirmed"] is None:
        phase = "note" if ep["run"] else "suspect"
    elif ep["nights"] >= FIRM_NIGHTS or ep["runs"] >= FIRM_RUNS:
        phase = "firm"
    else:
        phase = "advice"
    reasons = ep["why"] + ([ep["said"]] if ep["said"] else [])
    if phase == "firm":
        reasons.append(f"no better {ep['nights']} nights later" if ep["nights"] >= FIRM_NIGHTS
                       else f"no better after {ep['runs']} more runs")
    out.update(phase=phase, since=ep["since"], reasons=reasons, run=ep["run"],
               trim_taken="trim" in taken, easy_taken="easy" in taken)
    if phase in ("advice", "firm") and not out["trim_taken"]:
        out["offer"] = "trim"
    elif phase == "firm" and not out["easy_taken"]:
        out["offer"] = "easy"
    out["rest"] = phase == "firm" and bool(out["support"])
    return out
