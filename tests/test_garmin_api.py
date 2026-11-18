from datetime import date, datetime, timedelta

import httpx
import pytest

from app import db, garmin_api

REAL_CLIENT = httpx.Client  # conftest replaces httpx.Client with one that fails
TOKEN_PATH = "/personalapitoken-service/personal-api/personal-api-key/token"


@pytest.fixture(autouse=True)
def key_and_clean_meta(monkeypatch):
    db.init()
    monkeypatch.setenv("GARMIN_API_KEY", "k")
    for k in ("garmin_token", "garmin_token_exp"):
        with db.conn() as c:
            c.execute("DELETE FROM meta WHERE key = ?", (k,))


def client_with(data_statuses=(200,), expires_in=86400):
    """A client whose token endpoint always works and whose data endpoint returns the given statuses in turn."""
    calls = {"exchange": [], "data": []}
    statuses = list(data_statuses)

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == TOKEN_PATH:
            calls["exchange"].append(request)
            return httpx.Response(200, json={"access_token": f"t{len(calls['exchange'])}", "expires_in": expires_in})
        calls["data"].append(request)
        return httpx.Response(statuses.pop(0) if len(statuses) > 1 else statuses[0], json={})

    return REAL_CLIENT(transport=httpx.MockTransport(handler)), calls


def test_token_exchanged_with_api_key_header():
    client, calls = client_with()
    garmin_api.get(client, "/x")
    req = calls["exchange"][0]
    assert req.method == "POST"
    assert req.headers["Authorization"] == "ApiKey k"
    assert calls["data"][0].headers["Authorization"] == "Bearer t1"


def test_token_cached_until_an_hour_left():
    client, calls = client_with()
    garmin_api.get(client, "/x")
    garmin_api.get(client, "/x")
    assert len(calls["exchange"]) == 1
    soon = (datetime.now() + timedelta(minutes=30)).timestamp()
    db.set_meta("garmin_token_exp", str(soon))
    garmin_api.get(client, "/x")
    assert len(calls["exchange"]) == 2


def test_401_refetches_token_once():
    client, calls = client_with(data_statuses=(401, 200))
    assert garmin_api.get(client, "/x").status_code == 200
    assert len(calls["exchange"]) == 2
    client, calls = client_with(data_statuses=(401, 401))
    with pytest.raises(garmin_api.SyncError):
        garmin_api.get(client, "/x")


def test_plain_text_jwt_token_uses_exp_claim():
    import base64
    import json
    import time
    exp = int(time.time()) + 7200
    seg = base64.urlsafe_b64encode(json.dumps({"exp": exp}).encode()).decode().rstrip("=")
    jwt = f"h.{seg}.s"

    def handler(request):
        if request.url.path == TOKEN_PATH:
            return httpx.Response(200, text=jwt, headers={"content-type": "text/plain"})
        return httpx.Response(200, json={})
    client = REAL_CLIENT(transport=httpx.MockTransport(handler))
    assert garmin_api.token(client) == jwt
    assert float(db.get_meta("garmin_token_exp")) == exp


def test_exchange_rejected_names_the_key():
    def handler(request):
        return httpx.Response(401, text="no")
    client = REAL_CLIENT(transport=httpx.MockTransport(handler))
    with pytest.raises(garmin_api.SyncError, match="GARMIN_API_KEY"):
        garmin_api.token(client)


def test_missing_key_raises(monkeypatch):
    monkeypatch.delenv("GARMIN_API_KEY")
    client, _ = client_with()
    with pytest.raises(garmin_api.SyncError, match="GARMIN_API_KEY is not set"):
        garmin_api.get(client, "/x")


def test_key_expiry(monkeypatch):
    monkeypatch.setenv("GARMIN_API_KEY_EXPIRES", "2027-11-01")
    assert garmin_api.key_expiry() == date(2027, 11, 1)
    for bad in ("", "soon"):
        monkeypatch.setenv("GARMIN_API_KEY_EXPIRES", bad)
        assert garmin_api.key_expiry() is None
