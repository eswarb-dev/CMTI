from __future__ import annotations

from typing import Annotated

import jwt
from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.api.schemas import AuthLoginRequest, AuthLoginResponse, AuthRegisterRequest, AuthUserResponse
from app.auth.service import AuthenticationError, AuthConfigurationError, DuplicateUsernameError, LocalAuthService
from app.auth.security import decode_access_token

router = APIRouter(prefix="/api/auth", tags=["auth"])
bearer = HTTPBearer(auto_error=False)


def get_auth_service(request: Request) -> LocalAuthService:
    return request.app.state.auth_service


@router.post("/login", response_model=AuthLoginResponse)
async def login(
    payload: AuthLoginRequest,
    service: Annotated[LocalAuthService, Depends(get_auth_service)],
) -> AuthLoginResponse:
    try:
        token, user = service.login(username=payload.username, password=payload.password)
    except AuthenticationError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid username or password.",
        ) from None
    except AuthConfigurationError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(exc),
        ) from None
    return AuthLoginResponse(access_token=token, token_type="bearer", user=user.safe_dict())


@router.post("/register", response_model=AuthLoginResponse, status_code=status.HTTP_201_CREATED)
async def register(
    payload: AuthRegisterRequest,
    service: Annotated[LocalAuthService, Depends(get_auth_service)],
) -> AuthLoginResponse:
    try:
        user = service.create_user(
            username=payload.username,
            display_name=payload.display_name,
            role=payload.role,
            password=payload.password,
        )
        token = service.issue_token(user)
    except DuplicateUsernameError:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="That username is already in use.",
        ) from None
    except AuthConfigurationError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(exc),
        ) from None
    return AuthLoginResponse(access_token=token, token_type="bearer", user=user.safe_dict())


@router.get("/me", response_model=AuthUserResponse)
async def me(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)],
    service: Annotated[LocalAuthService, Depends(get_auth_service)],
) -> AuthUserResponse:
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise unauthorized()
    if not service.jwt_secret:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="AUTH_JWT_SECRET is required for auth endpoints.",
        )
    try:
        claims = decode_access_token(credentials.credentials, secret=service.jwt_secret)
    except jwt.PyJWTError:
        raise unauthorized() from None
    subject = claims.get("sub")
    if not isinstance(subject, str):
        raise unauthorized()
    user = service.get_user_by_id(subject)
    if user is None or not user.is_active:
        raise unauthorized()
    return AuthUserResponse(**user.safe_dict())


@router.post("/logout")
async def logout() -> dict[str, str]:
    return {"status": "ok", "detail": "Remove the bearer token on the client."}


def unauthorized() -> HTTPException:
    return HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired token.")
