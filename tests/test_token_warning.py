from datetime import date

import pytest
from fastapi.testclient import TestClient

from app import main, smashrun

ISSUED = "2026-10-16"  # runs out about 15 Dec


@pytest.fixture
def client():
    with TestClient(main.app) as c:
        yield c


def on(monkeypatch, day):
    monkeypatch.setattr(main, "today", lambda: day)


def env(monkeypatch, token="abc", issued=ISSUED):
    monkeypatch.setenv("SMASHRUN_TOKEN", token)
    if issued is None:
        monkeypatch.delenv("SMASHRUN_TOKEN_ISSUED", raising=False)
    else:
        monkeypatch.setenv("SMASHRUN_TOKEN_ISSUED", issued)


def test_token_expiry_is_60_days_after_issue(monkeypatch):
    env(monkeypatch)
    assert smashrun.token_expiry() == date(2026, 12, 15)
    env(monkeypatch, issued=None)
    assert smashrun.token_expiry() is None
    env(monkeypatch, issued="not a date")
    assert smashrun.token_expiry() is None


def test_warning_in_the_last_week(client, monkeypatch):
    env(monkeypatch)
    on(monkeypatch, date(2026, 12, 7))  # 8 days left: quiet
    assert client.get("/").context["token_warning"] is None
    on(monkeypatch, date(2026, 12, 10))  # 5 days left
    page = client.get("/")
    assert page.context["token_warning"] == {"expires": date(2026, 12, 15), "days": 5}
    assert "Smashrun token runs out" in page.text and "SMASHRUN_TOKEN_ISSUED" in page.text


def test_warning_after_expiry(client, monkeypatch):
    env(monkeypatch)
    on(monkeypatch, date(2026, 12, 20))
    page = client.get("/")
    assert page.context["token_warning"]["days"] == -5
    assert "Smashrun token ran out" in page.text


def test_no_warning_without_token_or_date(client, monkeypatch):
    on(monkeypatch, date(2026, 12, 14))
    env(monkeypatch, issued=None)
    assert client.get("/").context["token_warning"] is None
    env(monkeypatch, token="")
    assert client.get("/").context["token_warning"] is None
