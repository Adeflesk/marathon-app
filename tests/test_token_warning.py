from datetime import date

import pytest
from fastapi.testclient import TestClient

from app import main

EXPIRES = "2026-12-15"


@pytest.fixture
def client():
    with TestClient(main.app) as c:
        yield c


def on(monkeypatch, day):
    monkeypatch.setattr(main, "today", lambda: day)


def env(monkeypatch, key="abc", expires=EXPIRES):
    monkeypatch.setenv("GARMIN_API_KEY", key)
    if expires is None:
        monkeypatch.delenv("GARMIN_API_KEY_EXPIRES", raising=False)
    else:
        monkeypatch.setenv("GARMIN_API_KEY_EXPIRES", expires)


def test_warning_in_the_last_week(client, monkeypatch):
    env(monkeypatch)
    on(monkeypatch, date(2026, 12, 7))  # 8 days left: quiet
    assert client.get("/").context["token_warning"] is None
    on(monkeypatch, date(2026, 12, 10))  # 5 days left
    page = client.get("/")
    assert page.context["token_warning"] == {"expires": date(2026, 12, 15), "days": 5}
    assert "Your Garmin key runs out" in page.text and "GARMIN_API_KEY_EXPIRES" in page.text
    assert "connect.garmin.com/app/settings/personalApiToken" in page.text


def test_no_warning_30_days_out(client, monkeypatch):
    env(monkeypatch)
    on(monkeypatch, date(2026, 11, 15))
    page = client.get("/")
    assert page.context["token_warning"] is None and "Your Garmin key" not in page.text


def test_warning_after_expiry(client, monkeypatch):
    env(monkeypatch)
    on(monkeypatch, date(2026, 12, 20))
    page = client.get("/")
    assert page.context["token_warning"]["days"] == -5
    assert "Your Garmin key ran out" in page.text


def test_no_warning_without_key_or_date(client, monkeypatch):
    on(monkeypatch, date(2026, 12, 14))
    env(monkeypatch, expires=None)
    assert client.get("/").context["token_warning"] is None
    env(monkeypatch, key="")
    assert client.get("/").context["token_warning"] is None
