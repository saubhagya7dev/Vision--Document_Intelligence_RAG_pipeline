import pytest

from vision_rag.config import settings


@pytest.fixture(autouse=True)
def isolated_http_security(monkeypatch):
    # TestClient's synthetic host is never enabled in a real server profile.
    monkeypatch.setattr(
        settings, "allowed_hosts", ["testserver", "localhost", "127.0.0.1", "::1"]
    )
    monkeypatch.setattr(settings, "access_token", None)
    monkeypatch.setattr(settings, "deployment_profile", "local")
