from __future__ import annotations

import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path

import jwt
from fastapi.testclient import TestClient

from app.auth.repository import DuplicateUsernameError, LocalAuthRepository
from app.auth.security import create_access_token, decode_access_token, verify_password
from app.auth.service import AuthenticationError, LocalAuthService
from app.core.config import Settings
from app.main import create_app


class NoCallOrchestrator:
    async def run(self, query):  # pragma: no cover
        raise AssertionError("auth tests do not call query")


def make_service(tmp_path: Path, *, secret: str = "test-secret-with-at-least-32-bytes-for-hs256") -> LocalAuthService:
    repository = LocalAuthRepository(tmp_path / "auth.db")
    repository.initialize()
    return LocalAuthService(repository, jwt_secret=secret, access_token_minutes=30)


def test_auth_db_initializes_and_repeated_init_is_safe(tmp_path: Path):
    db_path = tmp_path / "auth.db"
    repo = LocalAuthRepository(db_path)
    repo.initialize()
    repo.initialize()
    assert db_path.exists()
    tables = sqlite3.connect(db_path).execute(
        "SELECT name FROM sqlite_master WHERE type = 'table'"
    ).fetchall()
    assert ("users",) in tables
    repo.close()


def test_create_user_username_uniqueness_and_password_hashing(tmp_path: Path):
    service = make_service(tmp_path)
    user = service.create_user(
        username=" Eswar ",
        display_name="Eswar Balu",
        role="Manufacturing Engineer",
        password="private-pass",
    )
    assert user.id
    assert user.username == "Eswar"
    assert user.password_hash != "private-pass"
    assert verify_password("private-pass", user.password_hash)
    assert not verify_password("wrong-pass", user.password_hash)
    try:
        service.create_user(username="eswar", display_name="Other", role="Admin", password="another-pass")
    except DuplicateUsernameError:
        pass
    else:
        raise AssertionError("duplicate username should fail")
    service.repository.close()


def test_correct_wrong_unknown_and_disabled_authentication(tmp_path: Path):
    service = make_service(tmp_path)
    service.create_user(
        username="eswar",
        display_name="Eswar Balu",
        role="Manufacturing Engineer",
        password="private-pass",
    )
    assert service.authenticate(username="ESWAR", password="private-pass").display_name == "Eswar Balu"
    for username, password in [("eswar", "wrong-pass"), ("unknown", "private-pass")]:
        try:
            service.authenticate(username=username, password=password)
        except AuthenticationError as exc:
            assert str(exc) == "Invalid username or password."
        else:
            raise AssertionError("auth should fail")
    service.repository.set_user_active("eswar", False)
    try:
        service.authenticate(username="eswar", password="private-pass")
    except AuthenticationError as exc:
        assert str(exc) == "Invalid username or password."
    else:
        raise AssertionError("disabled user should fail")
    service.repository.close()


def test_login_token_claims_are_minimal_and_exclude_password(tmp_path: Path):
    service = make_service(tmp_path)
    user = service.create_user(username="eswar", display_name="Eswar Balu", role="Admin", password="private-pass")
    token, logged_in = service.login(username="eswar", password="private-pass")
    claims = decode_access_token(token, secret="test-secret-with-at-least-32-bytes-for-hs256")
    assert logged_in.id == user.id
    assert claims["sub"] == user.id
    assert claims["username"] == "eswar"
    assert "iat" in claims
    assert "exp" in claims
    assert "password" not in claims
    assert "password_hash" not in claims
    service.repository.close()


def test_auth_api_login_me_and_safe_responses(tmp_path: Path):
    settings = Settings(project_root=tmp_path, auth_jwt_secret="test-secret-with-at-least-32-bytes-for-hs256")
    service = make_service(tmp_path / "backend" / "data")
    service.create_user(username="eswar", display_name="Eswar Balu", role="Manufacturing Engineer", password="private-pass")
    app = create_app(orchestrator=NoCallOrchestrator(), settings=settings, auth_service=service)
    with TestClient(app) as client:
        login = client.post("/api/auth/login", json={"username": "eswar", "password": "private-pass"})
        assert login.status_code == 200
        body = login.json()
        assert body["token_type"] == "bearer"
        assert body["user"] == {
            "id": body["user"]["id"],
            "username": "eswar",
            "display_name": "Eswar Balu",
            "role": "Manufacturing Engineer",
        }
        assert "password_hash" not in str(body)
        me = client.get("/api/auth/me", headers={"Authorization": f"Bearer {body['access_token']}"})
        assert me.status_code == 200
        assert me.json()["display_name"] == "Eswar Balu"
        assert "password_hash" not in str(me.json())
        assert client.get("/api/auth/me").status_code == 401
        assert client.get("/api/auth/me", headers={"Authorization": "Bearer bad"}).status_code == 401
    service.repository.close()


def test_register_valid_user_success_hashes_password_and_token_works(tmp_path: Path):
    settings = Settings(project_root=tmp_path, auth_jwt_secret="test-secret-with-at-least-32-bytes-for-hs256")
    service = make_service(tmp_path / "backend" / "data")
    app = create_app(orchestrator=NoCallOrchestrator(), settings=settings, auth_service=service)
    with TestClient(app) as client:
        response = client.post(
            "/api/auth/register",
            json={
                "username": " new-user ",
                "display_name": "New User",
                "role": "Engineer",
                "password": "private-pass",
            },
        )
        assert response.status_code == 201
        body = response.json()
        assert body["token_type"] == "bearer"
        assert body["user"]["username"] == "new-user"
        assert "password" not in body
        assert "password_hash" not in str(body)
        user = service.repository.get_user_by_username("NEW-USER")
        assert user is not None
        assert user.password_hash != "private-pass"
        assert verify_password("private-pass", user.password_hash)
        me = client.get("/api/auth/me", headers={"Authorization": f"Bearer {body['access_token']}"})
        assert me.status_code == 200
        assert me.json()["display_name"] == "New User"
    service.repository.close()


def test_register_duplicate_username_case_insensitive_returns_409(tmp_path: Path):
    settings = Settings(project_root=tmp_path, auth_jwt_secret="test-secret-with-at-least-32-bytes-for-hs256")
    service = make_service(tmp_path / "backend" / "data")
    service.create_user(username="new-user", display_name="New User", role="Engineer", password="private-pass")
    app = create_app(orchestrator=NoCallOrchestrator(), settings=settings, auth_service=service)
    with TestClient(app) as client:
        response = client.post(
            "/api/auth/register",
            json={
                "username": "NEW-USER",
                "display_name": "Other User",
                "role": "Engineer",
                "password": "other-pass",
            },
        )
        assert response.status_code == 409
        assert response.json()["detail"] == "That username is already in use."
    service.repository.close()


def test_register_validation_rejects_bad_username_password_display_and_role(tmp_path: Path):
    settings = Settings(project_root=tmp_path, auth_jwt_secret="test-secret-with-at-least-32-bytes-for-hs256")
    service = make_service(tmp_path / "backend" / "data")
    app = create_app(orchestrator=NoCallOrchestrator(), settings=settings, auth_service=service)
    bad_payloads = [
        {"username": "ab", "display_name": "New User", "role": "Engineer", "password": "private-pass"},
        {"username": "new-user", "display_name": "New User", "role": "Engineer", "password": "short"},
        {"username": "new-user", "display_name": "   ", "role": "Engineer", "password": "private-pass"},
        {"username": "new-user", "display_name": "New User", "role": "Admin", "password": "private-pass"},
    ]
    with TestClient(app) as client:
        for payload in bad_payloads:
            assert client.post("/api/auth/register", json=payload).status_code == 422
    service.repository.close()


def test_register_does_not_touch_manufacturing_db_or_document_registry(tmp_path: Path):
    settings = Settings(project_root=tmp_path, auth_jwt_secret="test-secret-with-at-least-32-bytes-for-hs256")
    service = make_service(tmp_path / "backend" / "data")
    app = create_app(orchestrator=NoCallOrchestrator(), settings=settings, auth_service=service)
    document_registry = tmp_path / "data" / "documents" / "registry.json"
    with TestClient(app) as client:
        assert client.post(
            "/api/auth/register",
            json={
                "username": "new-user",
                "display_name": "New User",
                "role": "Engineer",
                "password": "private-pass",
            },
        ).status_code == 201
    assert settings.auth_database_path.exists()
    assert not settings.default_database_path.exists()
    assert not document_registry.exists()
    service.repository.close()


def test_login_failure_generic_and_expired_token_rejected(tmp_path: Path):
    settings = Settings(project_root=tmp_path, auth_jwt_secret="test-secret-with-at-least-32-bytes-for-hs256")
    service = make_service(tmp_path / "backend" / "data")
    user = service.create_user(username="eswar", display_name="Eswar Balu", role="Admin", password="private-pass")
    app = create_app(orchestrator=NoCallOrchestrator(), settings=settings, auth_service=service)
    with TestClient(app) as client:
        wrong = client.post("/api/auth/login", json={"username": "unknown", "password": "private-pass"})
        assert wrong.status_code == 401
        assert wrong.json()["detail"] == "Invalid username or password."
        token = create_expired_token(user.id)
        assert client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"}).status_code == 401
    service.repository.close()


def test_auth_db_separate_from_manufacturing_db(tmp_path: Path):
    settings = Settings(project_root=tmp_path, auth_jwt_secret="test-secret-with-at-least-32-bytes-for-hs256")
    app = create_app(orchestrator=NoCallOrchestrator(), settings=settings)
    with TestClient(app):
        pass
    assert settings.auth_database_path.exists()
    assert settings.auth_database_path.name == "auth.db"
    assert settings.auth_database_path != settings.default_database_path
    assert not settings.default_database_path.exists()


def create_expired_token(user_id: str) -> str:
    now = datetime.now(UTC)
    return jwt.encode(
        {
            "sub": user_id,
            "username": "eswar",
            "iat": int((now - timedelta(hours=2)).timestamp()),
            "exp": int((now - timedelta(hours=1)).timestamp()),
        },
        "test-secret-with-at-least-32-bytes-for-hs256",
        algorithm="HS256",
    )
