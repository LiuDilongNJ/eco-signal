"""登录 API 路由。 / Login API routes."""
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, Response as FastAPIResponse, status
from fastapi.security import OAuth2PasswordRequestForm

from app.api.deps import RedisDep, SessionDep
from app.core.config import settings
from app.core.request import get_client_ip
from app.schemas import NewPassword, Token
from app.schemas.response import ApiResponse, api_success
from app.services import auth_service

router = APIRouter(tags=["登录 / login"])


@router.post(
    "/auth-tokens",
    response_model=Token,
    summary="登录获取访问令牌 / Login Access Token",
)
async def login_access_token(
    session: SessionDep,
    redis: RedisDep,
    request: Request,
    response: FastAPIResponse,
    form_data: Annotated[OAuth2PasswordRequestForm, Depends()],
) -> Token:
    """
    兼容 OAuth2 的令牌登录，获取用于未来请求的访问令牌。 / OAuth2 compatible token login, get an access token for future requests.
    """
    token, refresh_token, refresh_max_age = await auth_service.login(
        session,
        redis,
        form_data.username,
        form_data.password,
        client_ip=get_client_ip(request),
        user_agent=request.headers.get("user-agent"),
    )
    response.set_cookie(
        key=settings.AUTH_REFRESH_COOKIE_NAME,
        value=refresh_token,
        httponly=True,
        secure=settings.AUTH_REFRESH_COOKIE_SECURE,
        samesite=settings.AUTH_REFRESH_COOKIE_SAMESITE,
        max_age=refresh_max_age,
        path=settings.AUTH_REFRESH_COOKIE_PATH,
    )
    return token


@router.post(
    "/auth-token-refreshes",
    response_model=ApiResponse[Token],
    summary="刷新访问令牌 / Refresh Access Token",
)
async def refresh_access_token(
    session: SessionDep,
    redis: RedisDep,
    request: Request,
    response: FastAPIResponse,
) -> ApiResponse[Token]:
    """
    使用 refresh cookie 轮换并签发新的访问令牌。 / Rotate refresh cookie and issue a new access token.
    """
    refresh_token = request.cookies.get(settings.AUTH_REFRESH_COOKIE_NAME)
    if not refresh_token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing refresh token",
        )
    token, new_refresh_token, refresh_max_age = await auth_service.refresh_access_token(
        session,
        redis,
        refresh_token,
        client_ip=get_client_ip(request),
        user_agent=request.headers.get("user-agent"),
    )
    response.set_cookie(
        key=settings.AUTH_REFRESH_COOKIE_NAME,
        value=new_refresh_token,
        httponly=True,
        secure=settings.AUTH_REFRESH_COOKIE_SECURE,
        samesite=settings.AUTH_REFRESH_COOKIE_SAMESITE,
        max_age=refresh_max_age,
        path=settings.AUTH_REFRESH_COOKIE_PATH,
    )
    return api_success(data=token, message="ok")


@router.delete(
    "/auth-tokens/current",
    response_model=ApiResponse,
    summary="登出当前会话 / Logout Current Session",
)
async def logout_current_token(
    redis: RedisDep,
    request: Request,
    response: FastAPIResponse,
) -> ApiResponse:
    """
    撤销当前 refresh 会话并清除 refresh cookie。 / Revoke current refresh session and clear refresh cookie.
    """
    refresh_token = request.cookies.get(settings.AUTH_REFRESH_COOKIE_NAME)
    result = await auth_service.logout(redis, refresh_token, revoke_family=True)
    response.delete_cookie(
        key=settings.AUTH_REFRESH_COOKIE_NAME,
        path=settings.AUTH_REFRESH_COOKIE_PATH,
    )
    return result


@router.post("/password-resets", response_model=ApiResponse, summary="重置密码 / Reset Password")
async def reset_password(session: SessionDep, redis: RedisDep, body: NewPassword) -> ApiResponse:
    """
    使用令牌重置密码。 / Reset password using token.
    """
    return await auth_service.reset_password(session, redis, body.token, body.new_password)
