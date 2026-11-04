import pytest
from pydantic import SecretStr
from test_phase4_api import client as client

from vision_rag.api import security
from vision_rag.config import Settings, settings


def test_auth_covers_all_api_resources_and_cookies_revoke(client, monkeypatch):
    secret = "test-access-token-" + "a" * 32
    monkeypatch.setattr(settings, "access_token", SecretStr(secret))
    security.clear_sessions()
    for path in (
        "/api/v1/documents",
        "/api/v1/stats",
        "/api/v1/diagnostics",
        "/api/v1/versions/missing/file",
        "/api/v1/versions/missing/pages/1",
        "/api/v1/conversations",
        "/api/v1/messages/missing/events",
        "/api/v1/findings",
        "/api/v1/findings/missing/export",
        "/openapi.json",
    ):
        assert client.get(path).status_code == 401
    assert client.get("/health").status_code == 200
    assert client.post("/api/v1/query", json={"query": "private"}).status_code == 401
    response = client.post("/api/v1/session", json={"token": secret})
    assert response.status_code == 200
    cookie = response.headers["set-cookie"]
    assert "HttpOnly" in cookie and "SameSite=strict" in cookie
    assert secret not in cookie
    session = client.cookies.get(security.COOKIE)
    assert client.get("/api/v1/documents").status_code == 200
    client.delete("/api/v1/session")
    assert client.get("/api/v1/documents").status_code == 401
    client.cookies.set(security.COOKIE, session)
    assert client.get("/api/v1/documents").status_code == 401
    assert (
        client.get(
            "/api/v1/documents", headers={"Authorization": f"Bearer {secret}"}
        ).status_code
        == 200
    )


def test_origin_host_body_limit_and_secret_free_errors(client, monkeypatch):
    assert (
        client.get(
            "/api/v1/documents", headers={"Origin": "https://untrusted.invalid"}
        ).status_code
        == 403
    )
    assert (
        client.get("/health", headers={"Host": "untrusted.invalid"}).status_code == 400
    )
    assert client.get("/api/v1/session?access_token=do-not-echo").status_code == 400
    monkeypatch.setattr(settings, "max_request_mb", 1)
    assert (
        client.post("/api/v1/query", content=b"x" * (1024 * 1024 + 1)).status_code
        == 413
    )
    bad = "do-not-echo-private-request"
    response = client.post("/api/v1/session", json={"token": bad, "extra": bad})
    assert response.status_code == 422 and bad not in response.text
    assert (
        client.get("/")
        .headers["content-security-policy"]
        .startswith("default-src 'self'")
    )
    assert (
        "access-control-allow-origin"
        not in client.get(
            "/health", headers={"Origin": "https://untrusted.invalid"}
        ).headers
    )


def test_login_backoff_and_profile_fail_closed(client, monkeypatch):
    monkeypatch.setattr(settings, "access_token", SecretStr("a" * 40))
    security.clear_sessions()
    for _ in range(5):
        assert (
            client.post("/api/v1/session", json={"token": "wrong"}).status_code == 401
        )
    assert client.post("/api/v1/session", json={"token": "wrong"}).status_code == 429
    config = Settings(_env_file=None, bind_host="0.0.0.0")
    with pytest.raises(ValueError):
        config.check_deployment()


def test_chunked_limits_and_network_tls_fail_before_processing(client, monkeypatch):
    body = (b"x" * 65536 for _ in range(17))
    assert client.post("/api/v1/query", content=body).status_code == 413
    monkeypatch.setattr(settings, "bind_host", "0.0.0.0")
    assert client.get("/api/v1/documents").status_code == 403
    assert client.get("/health").status_code == 200
    config = Settings(_env_file=None, deployment_profile="authenticated")
    with pytest.raises(ValueError):
        config.check_deployment()
