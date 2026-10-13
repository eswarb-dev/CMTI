from __future__ import annotations

import argparse
import getpass
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.auth.repository import DuplicateUsernameError, LocalAuthRepository
from app.auth.service import LocalAuthService
from app.core.config import get_settings


def create_local_user(
    *,
    username: str,
    display_name: str,
    role: str,
    password: str,
    confirm_password: str,
) -> int:
    if password != confirm_password:
        print("Password confirmation does not match.", file=sys.stderr)
        return 2
    settings = get_settings()
    repository = LocalAuthRepository(settings.auth_database_path)
    repository.initialize()
    try:
        LocalAuthService(repository, jwt_secret=settings.auth_jwt_secret).create_user(
            username=username,
            display_name=display_name,
            role=role,
            password=password,
        )
    except DuplicateUsernameError:
        print("Username already exists.", file=sys.stderr)
        return 3
    finally:
        repository.close()
    print("Local user created.")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Create a local ManufacturaIQ prototype user.")
    parser.add_argument("--username")
    parser.add_argument("--display-name")
    parser.add_argument("--role")
    args = parser.parse_args()

    username = args.username or input("Username: ")
    display_name = args.display_name or input("Display name: ")
    role = args.role or input("Role: ")
    password = getpass.getpass("Password: ")
    confirm_password = getpass.getpass("Confirm password: ")
    return create_local_user(
        username=username,
        display_name=display_name,
        role=role,
        password=password,
        confirm_password=confirm_password,
    )


if __name__ == "__main__":
    raise SystemExit(main())
