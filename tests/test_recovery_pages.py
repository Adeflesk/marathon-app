"""The recovery panel and advice card on This week, and the HRV / resting HR / sleep charts on Progress."""
from datetime import date, timedelta

import pytest
from fastapi.testclient import TestClient

from app import db, main, progress, recovery, view

TUE = date(2026, 12, 8)  # week 8, a Build week
RACE_MON = date(2027, 3, 8)  # Race week


def _clear():
    db.init()
    with db.conn() as c:
        for table in ("activities", "run_details", "wellness", "recovery_trims", "checkins"):
            c.execute(f"DELETE FROM {table}")


@pytest.fixture
def client(monkeypatch):
    _clear()
    monkeypatch.setattr(main, "today", lambda: TUE)
    with TestClient(main.app) as c:
        yield c
    _clear()


def night(day: date, hrv=52.0, low=45.0, high=60.0, avg=51.0, rhr=48, sleep_s=7 * 3600 + 5 * 60, **more):
    row = {"date": day.isoformat(), "hrv_night": hrv, "hrv_week_avg": avg, "hrv_low": low, "hrv_high": high,
           "rhr": rhr, "sleep_s": sleep_s, "sleep_score": 80, "stress_avg": 21, "weight_kg": 72.4, **more}
    with db.conn() as c:
        c.execute("INSERT OR REPLACE INTO wellness (date, hrv_night, hrv_week_avg, hrv_low, hrv_high, rhr, sleep_s, "
                  "sleep_score, stress_avg, weight_kg) VALUES (:date, :hrv_night, :hrv_week_avg, :hrv_low, "
                  ":hrv_high, :rhr, :sleep_s, :sleep_score, :stress_avg, :weight_kg)", row)
    return row


def force(monkeypatch, **over):
    """Make the recovery state what a test needs, keeping the real wellness row as `last`."""
    real = recovery.state

    def fake(wellness, runs, trims, t, easy_pace):
        out = real(wellness, runs, trims, t, easy_pace)
        out.update(over)
        return out
    monkeypatch.setattr(view.recovery, "state", fake)


def test_panel_shows_last_night(client):
    night(TUE)
    page = client.get("/").text
    assert 'id="recovery"' in page
    assert "52 ms" in page and "45" in page and "60" in page  # HRV and its band
    assert "48 bpm" in page  # resting HR
    assert "7:05" in page  # sleep, h:mm
    assert "sleep stress" in page and "72.4 kg" in page


def test_panel_hidden_without_wellness(client):
    page = client.get("/").text
    assert 'id="recovery"' not in page


def test_suspect_is_quiet(client, monkeypatch):
    night(TUE)
    force(monkeypatch, phase="suspect", since=TUE, reasons=["HRV below your normal range 3 nights running"])
    page = client.get("/").text
    assert 'role="alert"' not in page.split('id="recovery"')[1].split("</section>")[0]
    assert "HRV below your normal range 3 nights running" in page
    assert "Take the trim" not in page


def test_note_text(client, monkeypatch):
    night(TUE)
    force(monkeypatch, phase="note", since=TUE, run={"date": TUE}, reasons=["HRV below your normal range 3 nights running"])
    page = client.get("/").text
    assert "looked normal" in page and "Take the trim" not in page


def test_advice_card_with_button(client, monkeypatch):
    night(TUE)
    force(monkeypatch, phase="advice", since=TUE, reasons=["HRV below your normal range 3 nights running"],
          offer="trim")
    page = client.get("/").text
    assert 'action="/recovery"' in page and 'value="trim"' in page and "Take the trim" in page
    assert "Rest of this week at 90% and one rep off the next session." in page
    assert "Make the next run easy" not in page


def test_firm_card_wording(client, monkeypatch):
    night(TUE)
    force(monkeypatch, phase="firm", since=TUE, reasons=["no better 3 nights later"], offer="easy",
          trim_taken=True, support=["Resting heart rate is up 6 bpm"], rest=True)
    page = client.get("/").text
    assert "hasn't improved" in page
    assert "an easy day or a rest day" in page
    assert "Resting heart rate is up 6 bpm" in page


def test_firm_without_support_does_not_recommend_rest(client, monkeypatch):
    night(TUE)
    force(monkeypatch, phase="firm", since=TUE, reasons=["no better 3 nights later"], offer="easy",
          trim_taken=True, support=[], rest=False)
    page = client.get("/").text
    assert "hasn't improved" in page and "an easy day or a rest day" not in page


def test_easy_button_only_when_offered(client, monkeypatch):
    night(TUE)
    force(monkeypatch, phase="firm", since=TUE, reasons=["x"], offer="easy", trim_taken=True)
    page = client.get("/").text
    assert "Make the next run easy" in page and 'value="easy"' in page and "Take the trim" not in page
    force(monkeypatch, phase="firm", since=TUE, reasons=["x"], offer=None, trim_taken=True, easy_taken=True)
    page = client.get("/").text
    assert "Make the next run easy" not in page and "Take the trim" not in page


def test_no_trim_button_in_race_week(client, monkeypatch):
    monkeypatch.setattr(main, "today", lambda: RACE_MON + timedelta(days=1))
    night(RACE_MON + timedelta(days=1))
    force(monkeypatch, phase="advice", since=RACE_MON, reasons=["x"], offer="trim")
    page = client.get("/").text
    assert "Take the trim" not in page and 'action="/recovery"' not in page


def test_progress_shows_hrv_rhr_sleep_charts(client):
    for i in range(10):
        night(TUE - timedelta(days=i), hrv=50.0 + i % 3, rhr=47 + i % 2, sleep_s=7 * 3600 + i * 60)
    page = client.get("/progress").text
    assert page.count('class="chart"') >= 3
    for label in ("Overnight HRV", "Resting heart rate", "Sleep"):
        assert f'aria-label="{label}' in page


def test_progress_without_wellness_has_no_recovery_charts(client):
    page = client.get("/progress").text
    assert 'aria-label="Overnight HRV' not in page


def test_recovery_trend_is_last_eight_weeks_per_day():
    rows = [{"date": (TUE - timedelta(days=i)).isoformat(), "hrv_night": 50.0, "hrv_week_avg": 50.0, "hrv_low": 45.0,
             "hrv_high": 60.0, "rhr": 48, "sleep_s": 25000, "sleep_score": 80, "stress_avg": 20, "weight_kg": 72.0}
            for i in range(80, -1, -1)]
    out = progress.recovery_trend(rows, TUE)
    assert len(out) == 56 and out[-1]["date"] == TUE.isoformat() and out[0]["date"] == (TUE - timedelta(days=55)).isoformat()
    assert set(out[0]) == {"date", "hrv_night", "hrv_week_avg", "hrv_low", "hrv_high", "rhr", "sleep_s"}
    assert progress.recovery_trend([], TUE) == []
