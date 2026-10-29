from __future__ import annotations

from fastapi import APIRouter, Depends, Request, Response, status

from app.api.deps import (
    ActorDep,
    ContextDep,
    DbDep,
    SettingsDep,
    clear_session_cookies,
    rate_limit,
    set_session_cookies,
    verify_csrf,
)
from app.core.exceptions import AuthenticationError
from app.core.security import ACCESS_COOKIE, REFRESH_COOKIE, decode_access_token
from app.schemas.auth import ChangePasswordRequest, LoginRequest, SessionOut
from app.schemas.common import ERROR_RESPONSES, Envelope, ok
from app.schemas.user import UserOut
from app.services import auth_service

router = APIRouter(prefix="/auth", tags=["Authentication"], responses=ERROR_RESPONSES)


@router.post(
    "/login",
    response_model=Envelope[UserOut],
    summary="Sign in (administrators)",
    description="Verifies credentials and sets HTTP-only session cookies (access, refresh) "
    "plus a readable CSRF cookie. "
    "Repeated failures lock the account with exponential backoff.",
    dependencies=[Depends(rate_limit("login", "rate_limit_login", per="ip"))],
)
def login(
    body: LoginRequest, response: Response, db: DbDep, settings: SettingsDep, context: ContextDep
) -> dict[str, object]:
    user, tokens = auth_service.login(db, settings, username=body.username, password=body.password, context=context)
    set_session_cookies(response, tokens, settings)
    return ok(auth_service.user_out(user))


@router.post(
    "/refresh",
    response_model=Envelope[UserOut],
    summary="Rotate session tokens",
    description="Exchanges the refresh cookie for new tokens. Reusing an old refresh token revokes the whole session.",
    dependencies=[Depends(rate_limit("refresh", "rate_limit_login", per="ip"))],
)
def refresh(
    request: Request, response: Response, db: DbDep, settings: SettingsDep, context: ContextDep
) -> dict[str, object]:
    token = request.cookies.get(REFRESH_COOKIE)
    if not token:
        raise AuthenticationError("Your session has expired. Please sign in again.")
    verify_csrf(request)
    user, tokens = auth_service.refresh(db, settings, refresh_token=token, context=context)
    set_session_cookies(response, tokens, settings)
    return ok(auth_service.user_out(user))


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT, summary="Sign out of this session")
def logout(request: Request, response: Response, db: DbDep, settings: SettingsDep, context: ContextDep) -> Response:
    token = request.cookies.get(ACCESS_COOKIE)
    user = family = None
    if token:
        try:
            claims = decode_access_token(settings, token)
            verify_csrf(request)
            user = auth_service.authenticate(db, claims)
            family = claims.session_id
        except Exception:  # an expired/invalid session can always be cleared locally
            user = family = None
    auth_service.logout(db, user=user, family_id=family, context=context)
    result = Response(status_code=status.HTTP_204_NO_CONTENT)
    clear_session_cookies(result, settings)
    return result


@router.get("/me", response_model=Envelope[UserOut], summary="Current user (session restore)")
def me(actor: ActorDep) -> dict[str, object]:
    return ok(auth_service.user_out(actor.user))


@router.post(
    "/change-password", status_code=status.HTTP_204_NO_CONTENT, summary="Change password (ends other sessions)"
)
def change_password(body: ChangePasswordRequest, db: DbDep, actor: ActorDep) -> Response:
    auth_service.change_password(
        db,
        user=actor.user,
        current_password=body.current_password,
        new_password=body.new_password,
        current_family=actor.session_id,
        context=actor.context,
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/sessions", response_model=Envelope[list[SessionOut]], summary="Active sessions")
def sessions(db: DbDep, actor: ActorDep) -> dict[str, object]:
    return ok(auth_service.list_sessions(db, user=actor.user, current_family=actor.session_id))


@router.post("/sessions/revoke-all", status_code=status.HTTP_204_NO_CONTENT, summary="Sign out of every session")
def revoke_all(db: DbDep, actor: ActorDep, settings: SettingsDep) -> Response:
    auth_service.revoke_all(db, user=actor.user, context=actor.context)
    result = Response(status_code=status.HTTP_204_NO_CONTENT)
    clear_session_cookies(result, settings)
    return result
