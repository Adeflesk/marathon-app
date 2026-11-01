import struct

import pytest
from fastapi.testclient import TestClient

from app import main


@pytest.fixture
def client():
    with TestClient(main.app) as c:
        yield c


def test_manifest_opens_full_screen(client):
    r = client.get("/manifest.webmanifest")
    assert r.status_code == 200 and r.headers["content-type"].startswith("application/manifest+json")
    m = r.json()
    assert m["display"] == "standalone" and m["start_url"] == "/" and m["short_name"]
    sizes = {(i["sizes"], i["type"]) for i in m["icons"]}
    assert {("192x192", "image/png"), ("512x512", "image/png")} <= sizes
    assert all("maskable" in i.get("purpose", "") for i in m["icons"] if i["type"] == "image/png")


def test_icons_are_pngs_of_their_size(client):
    for n in (192, 512):
        r = client.get(f"/icon-{n}.png")
        assert r.status_code == 200 and r.headers["content-type"] == "image/png"
        assert r.content[:8] == b"\x89PNG\r\n\x1a\n"
        assert struct.unpack(">II", r.content[16:24]) == (n, n)
    assert client.get("/icon.svg").headers["content-type"].startswith("image/svg+xml")


def test_every_page_links_the_manifest(client):
    for path in ("/", "/plan", "/progress", "/race"):
        assert '<link rel="manifest" href="/manifest.webmanifest">' in client.get(path).text, path


def test_manifest_and_icons_skip_the_password(client, monkeypatch):
    """Android fetches the manifest and icons without the login, so they must load without it."""
    monkeypatch.setenv("APP_PASSWORD", "secret")
    for path in ("/manifest.webmanifest", "/icon-192.png", "/icon-512.png", "/icon.svg"):
        assert client.get(path).status_code == 200, path
    assert client.get("/").status_code == 401
    assert client.get("/backup.db").status_code == 401
    assert client.get("/icon-192.png/../backup.db").status_code in (401, 404)
