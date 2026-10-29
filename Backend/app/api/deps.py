"""Shared API dependencies: settings, database, storage, authentication, CSRF, RBAC and rate limits."""

from __future__ import annotations

from collections.abc import Callable
from typing import Annotated

from fastapi import Depends, Request, Response
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.core.enums import Permission
from app.core.exceptions import AuthenticationError, AuthorizationError, ErrorCode, RateLimitedError
from app.core.logging import user_id_var
from app.core.rate_limit import limiter
from app.core.security import ACCESS_COOKIE, CSRF_COOKIE, CSRF_HEADER, REFRESH_COOKIE, decode_access_token
from app.db.session import get_db
from app.services import api_key_service, auth_service
from app.services.auth_service import IssuedTokens
from app.services.context import Actor, RequestContext
from app.services.storage import StorageBackend, get_storage
from app.utils.hashing import constant_time_equals

SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}

SettingsDep = Annotated[Settings, Depends(get_settings)]
DbDep = Annotated[Session, Depends(get_db)]


def storage_dep(settings: SettingsDep) -> StorageBackend:
    return get_storage(settings)


StorageDep = Annotated[StorageBackend, Depends(storage_dep)]


def request_context(request: Request) -> RequestContext:
    client = request.client.host if request.client else None
    return RequestContext(
        ip_address=client,
        user_agent=request.headers.get("user-agent", "")[:200] or None,
        request_id=getattr(request.state, "request_id", None),
    )


ContextDep = Annotated[RequestContext, Depends(request_context)]


def _token(request: Request) -> tuple[str | None, bool]:
    header = request.headers.get("authorization", "")
    if header.lower().startswith("bearer "):
        return header[7:].strip() or None, False
    return request.cookies.get(ACCESS_COOKIE), True


def verify_csrf(request: Request) -> None:
    """Double-submit check for cookie-authenticated, state-changing requests."""
    if request.method in SAFE_METHODS:
        return
    cookie = request.cookies.get(CSRF_COOKIE)
    header = request.headers.get(CSRF_HEADER)
    if not cookie or not header or not constant_time_equals(cookie, header):
        raise AuthorizationError(
            "Your request couldn't be verified. Refresh the page and try again.", code=ErrorCode.CSRF_FAILED
        )


# The only routes an API key opens: scanning documents and reading their results.
API_KEY_ROUTES = ("/documents", "/scans", "/findings", "/redactions", "/reports")


def current_actor(request: Request, db: DbDep, settings: SettingsDep, context: ContextDep) -> Actor:
    token, via_cookie = _token(request)
    if not token:
        raise AuthenticationError()
    if not via_cookie and api_key_service.is_api_key(token):
        path = request.url.path.removeprefix(settings.api_prefix)
        if not any(path == route or path.startswith(route + "/") for route in API_KEY_ROUTES):
            raise AuthorizationError("API keys can only scan documents and read their results.")
        actor = api_key_service.authenticate(db, token, context)
    else:
        claims = decode_access_token(settings, token)
        user = auth_service.authenticate(db, claims)
        if via_cookie:
            verify_csrf(request)
        actor = Actor(user=user, session_id=claims.session_id, context=context)
    request.state.user_id = str(actor.user.id)
    user_id_var.set(str(actor.user.id))
    return actor


ActorDep = Annotated[Actor, Depends(current_actor)]


def require(permission: Permission) -> Callable[[Actor], Actor]:
    def dependency(actor: ActorDep) -> Actor:
        actor.require(permission)
        return actor

    return dependency


def rate_limit(bucket: str, setting: str, *, per: str = "user") -> Callable[..., None]:
    """Limits requests per user (or per client IP when unauthenticated)."""

    def dependency(request: Request, settings: SettingsDep) -> None:
        identity = getattr(request.state, "user_id", None) if per == "user" else None
        identity = identity or (request.client.host if request.client else "unknown")
        retry_after = limiter.hit(f"{bucket}:{identity}", getattr(settings, setting))
        if retry_after is not None:
            raise RateLimitedError(retry_after=retry_after)

    return dependency


# ----------------------------------------------------------------------------- cookies


def set_session_cookies(response: Response, tokens: IssuedTokens, settings: Settings) -> None:
    secure, domain = settings.cookie_secure, settings.cookie_domain
    response.set_cookie(
        ACCESS_COOKIE,
        tokens.access_token,
        max_age=settings.access_token_expire_minutes * 60,
        httponly=True,
        samesite="lax",
        path="/",
        secure=secure,
        domain=domain,
    )
    response.set_cookie(
        REFRESH_COOKIE,
        tokens.refresh_token,
        max_age=settings.refresh_token_expire_days * 86400,
        httponly=True,
        samesite="strict",
        path=f"{settings.api_prefix}/auth",
        secure=secure,
        domain=domain,
    )
    # Readable by the frontend so it can echo it in the X-CSRF-Token header.
    response.set_cookie(
        CSRF_COOKIE,
        tokens.csrf_token,
        max_age=settings.refresh_token_expire_days * 86400,
        httponly=False,
        samesite="strict",
        path="/",
        secure=secure,
        domain=domain,
    )


def clear_session_cookies(response: Response, settings: Settings) -> None:
    secure, domain = settings.cookie_secure, settings.cookie_domain
    response.delete_cookie(ACCESS_COOKIE, path="/", httponly=True, samesite="lax", secure=secure, domain=domain)
    response.delete_cookie(
        REFRESH_COOKIE,
        path=f"{settings.api_prefix}/auth",
        httponly=True,
        samesite="strict",
        secure=secure,
        domain=domain,
    )
    response.delete_cookie(CSRF_COOKIE, path="/", samesite="strict", secure=secure, domain=domain)
