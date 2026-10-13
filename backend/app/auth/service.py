from __future__ import annotations

from app.auth.models import AuthUser
from app.auth.repository import DuplicateUsernameError, LocalAuthRepository
from app.auth.security import create_access_token, hash_password, verify_password


class AuthenticationError(ValueError):
    pass


class AuthConfigurationError(RuntimeError):
    pass


class LocalAuthService:
    def __init__(
        self,
        repository: LocalAuthRepository,
        *,
        jwt_secret: str | None,
        access_token_minutes: int = 480,
    ) -> None:
        self.repository = repository
        self.jwt_secret = jwt_secret.strip() if isinstance(jwt_secret, str) else None
        self.access_token_minutes = access_token_minutes

    def create_user(
        self,
        *,
        username: str,
        display_name: str,
        role: str,
        password: str,
    ) -> AuthUser:
        if not password:
            raise ValueError("password must not be empty")
        return self.repository.create_user(
            username=username,
            display_name=display_name,
            role=role,
            password_hash=hash_password(password),
        )

    def authenticate(self, *, username: str, password: str) -> AuthUser:
        user = self.repository.get_user_by_username(username)
        if user is None or not user.is_active or not verify_password(password, user.password_hash):
            raise AuthenticationError("Invalid username or password.")
        return user

    def issue_token(self, user: AuthUser) -> str:
        if not self.jwt_secret:
            raise AuthConfigurationError("AUTH_JWT_SECRET is required for auth endpoints.")
        return create_access_token(
            user,
            secret=self.jwt_secret,
            lifetime_minutes=self.access_token_minutes,
        )

    def login(self, *, username: str, password: str) -> tuple[str, AuthUser]:
        user = self.authenticate(username=username, password=password)
        return self.issue_token(user), user

    def get_user_by_id(self, user_id: str) -> AuthUser | None:
        return self.repository.get_user_by_id(user_id)


__all__ = ["AuthenticationError", "AuthConfigurationError", "DuplicateUsernameError", "LocalAuthService"]
