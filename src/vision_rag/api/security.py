"""Single-owner sessions and request boundaries for the fixed server workspace."""

import hashlib
import secrets
from collections import defaultdict, deque
from threading import Lock
from time import monotonic
from typing import Any
from urllib.parse import urlsplit

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, SecretStr
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from vision_rag.config import settings

router = APIRouter()
COOKIE = "vision_session"
_lock = Lock()
_sessions: dict[str, float] = {}
_failures: dict[str, deque[float]] = defaultdict(deque)


def authenticated(request: Request) -> bool:
    if not settings.access_token:
        return True
    authorization = request.headers.get("authorization", "")
    expected = settings.access_token.get_secret_value()
    if authorization.startswith("Bearer "):
        return secrets.compare_digest(authorization[7:].encode(), expected.encode())
    cookie = request.cookies.get(COOKIE)
    if not cookie:
        return False
    key = hashlib.sha256(cookie.encode()).hexdigest()
    with _lock:
        expiry = _sessions.get(key, 0)
        if expiry <= monotonic():
            _sessions.pop(key, None)
            return False
        return True


def clear_sessions() -> None:
    with _lock:
        _sessions.clear()
        _failures.clear()


class Login(BaseModel):
    model_config = ConfigDict(extra="forbid")
    token: SecretStr = Field(min_length=1, max_length=512)


@router.get("/session")
def session(request: Request) -> dict[str, Any]:
    return {
        "required": settings.access_token is not None,
        "authenticated": authenticated(request),
    }


@router.post("/session")
def login(body: Login, request: Request) -> JSONResponse:
    if not settings.access_token:
        return JSONResponse({"authenticated": True})
    peer = request.client.host if request.client else "unknown"
    with _lock:
        if peer not in _failures and len(_failures) >= 1024:
            _failures.pop(next(iter(_failures)))
        attempts = _failures[peer]
        while attempts and attempts[0] < monotonic() - 60:
            attempts.popleft()
        if len(attempts) >= 5:
            raise HTTPException(429, "Too many sign-in attempts; retry in one minute")
        if not secrets.compare_digest(
            body.token.get_secret_value().encode(),
            settings.access_token.get_secret_value().encode(),
        ):
            attempts.append(monotonic())
            raise HTTPException(401, "Invalid access token")
        # Keep bounded session state and make logout/restart revoke sessions.
        for key, expiry in list(_sessions.items()):
            if expiry <= monotonic():
                del _sessions[key]
        if len(_sessions) >= 100:
            raise HTTPException(
                429, "Too many active sessions; restart or sign out unused sessions"
            )
        token = secrets.token_urlsafe(32)
        _sessions[hashlib.sha256(token.encode()).hexdigest()] = (
            monotonic() + settings.session_seconds
        )
        _failures.pop(peer, None)
    response = JSONResponse({"authenticated": True})
    response.set_cookie(
        COOKIE,
        token,
        httponly=True,
        secure=settings.session_cookie_secure,
        samesite="strict",
        max_age=settings.session_seconds,
        path="/",
    )
    return response


@router.delete("/session")
def logout(request: Request) -> JSONResponse:
    cookie = request.cookies.get(COOKIE, "")
    with _lock:
        _sessions.pop(hashlib.sha256(cookie.encode()).hexdigest(), None)
    response = JSONResponse({"authenticated": False})
    response.delete_cookie(
        COOKIE,
        path="/",
        secure=settings.session_cookie_secure,
        httponly=True,
        samesite="strict",
    )
    return response


class RequestBoundary:
    """ASGI boundary runs before multipart parsing and document/model work."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        request = Request(scope)
        path = scope.get("path", "")
        try:
            authority = urlsplit("//" + request.headers.get("host", ""))
            hostname = authority.hostname
            authority.port
            if authority.username or authority.password:
                raise ValueError("Invalid authority")
        except ValueError:
            await JSONResponse({"detail": "Invalid Host"}, status_code=400)(
                scope, receive, send
            )
            return
        status, detail = 0, ""
        if hostname not in settings.allowed_hosts:
            status, detail = 400, "Host is not allowed"
        origin = request.headers.get("origin")
        same = f"{request.url.scheme}://{request.url.netloc}"
        sensitive = path.startswith("/api/") or path in (
            "/docs",
            "/openapi.json",
            "/redoc",
        )
        if sensitive and (
            (origin and origin != same and origin not in settings.cors_origins)
            or (
                request.headers.get("sec-fetch-site") == "cross-site"
                and origin not in settings.cors_origins
            )
        ):
            status, detail = 403, "Cross-site access is not allowed"
        preflight = request.method == "OPTIONS" and origin in settings.cors_origins
        if (
            sensitive
            and path != "/api/v1/session"
            and not preflight
            and not authenticated(request)
        ):
            status, detail = 401, "Sign in to access this workspace"
        # Reject credentials in URLs rather than encouraging token-bearing source links.
        if sensitive and any(
            k in request.query_params for k in ("token", "access_token", "api_key")
        ):
            status, detail = 400, "Credentials must not be placed in URLs"
        if (
            sensitive
            and settings.bind_host not in ("127.0.0.1", "localhost", "::1")
            and request.url.scheme != "https"
        ):
            status, detail = 403, "HTTPS is required for network workspace access"
        upload = request.method == "POST" and (
            path == "/api/v1/ingest" or path.endswith("/versions")
        )
        limit = (settings.max_request_mb if upload else 1) * 1024 * 1024
        if path == "/api/v1/session":
            limit = 4096
        length = request.headers.get("content-length")
        if length:
            try:
                if int(length) < 0:
                    raise ValueError()
                if int(length) > limit:
                    status, detail = 413, "Request body exceeds the configured limit"
            except ValueError:
                status, detail = 400, "Invalid Content-Length"
        if status:
            await JSONResponse({"detail": detail}, status_code=status)(
                scope, receive, send
            )
            return

        received, started = 0, False

        async def limited_receive() -> Message:
            nonlocal received
            message = await receive()
            received += len(message.get("body", b""))
            if received > limit:
                raise BodyLimit()
            return message

        async def secured_send(message: Message) -> None:
            nonlocal started
            # Request parsers may translate a receive error into a generic 400.
            # Preserve the boundary's 413 without reading the remaining upload.
            if received > limit:
                if not started:
                    started = True
                    await JSONResponse(
                        {"detail": "Request body exceeds the configured limit"},
                        status_code=413,
                    )(scope, receive, send)
                return
            if message["type"] == "http.response.start":
                started = True
                headers = list(message.get("headers", []))
                headers.extend(
                    [
                        (b"x-content-type-options", b"nosniff"),
                        (b"referrer-policy", b"no-referrer"),
                        (b"x-frame-options", b"DENY"),
                        (
                            b"content-security-policy",
                            b"default-src 'self'; script-src 'self'; "
                            b"style-src 'self' 'unsafe-inline' "
                            b"https://fonts.googleapis.com; "
                            b"font-src 'self' https://fonts.gstatic.com; "
                            b"img-src 'self' data: blob:; connect-src 'self'; "
                            b"frame-ancestors 'none'; base-uri 'self'; "
                            b"form-action 'self'; object-src 'none'",
                        ),
                    ]
                )
                message["headers"] = headers
            await send(message)

        try:
            await self.app(scope, limited_receive, secured_send)
        except BodyLimit:
            if not started:
                await JSONResponse(
                    {"detail": "Request body exceeds the configured limit"},
                    status_code=413,
                )(scope, receive, send)


class BodyLimit(HTTPException):
    def __init__(self) -> None:
        super().__init__(413, "Request body exceeds the configured limit")
