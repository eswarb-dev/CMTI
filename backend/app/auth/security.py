from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import bcrypt
import jwt

from app.auth.models import AuthUser

JWT_ALGORITHM = "HS256"


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode("utf-8"), password_hash.encode("utf-8"))
    except ValueError:
        return False


def create_access_token(user: AuthUser, *, secret: str, lifetime_minutes: int) -> str:
    now = datetime.now(UTC)
    payload = {
        "sub": user.id,
        "username": user.username,
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(minutes=lifetime_minutes)).timestamp()),
        "jti": str(uuid4()),
    }
    return jwt.encode(payload, secret, algorithm=JWT_ALGORITHM)


def decode_access_token(token: str, *, secret: str) -> dict[str, object]:
    return jwt.decode(token, secret, algorithms=[JWT_ALGORITHM])
