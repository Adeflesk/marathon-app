import os
import tempfile
from pathlib import Path

# DB_PATH is read when app.db is imported, so set it before any app import.
_TMP = Path(tempfile.mkdtemp(prefix="marathon-test-"))
os.environ["DB_PATH"] = str(_TMP / "marathon.db")
os.environ.pop("APP_PASSWORD", None)

import pytest  # noqa: E402

from app import config, smashrun  # noqa: E402


@pytest.fixture(autouse=True)
def no_settings_file(monkeypatch):
    """Tests see DEFAULTS only, never the developer's settings.json."""
    monkeypatch.setattr(config, "SETTINGS_PATH", _TMP / "absent-settings.json")


@pytest.fixture(autouse=True)
def no_smashrun(monkeypatch):
    """No test reaches the real Smashrun: no token from .env, and any request fails (tests that sync fake it)."""
    monkeypatch.delenv("SMASHRUN_TOKEN", raising=False)

    def offline(*args, **kwargs):
        raise RuntimeError("no network in tests")
    monkeypatch.setattr(smashrun.httpx, "Client", offline)


@pytest.fixture
def settings():
    return config.load_settings()
