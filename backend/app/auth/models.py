from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class AuthUser:
    id: str
    username: str
    display_name: str
    role: str
    password_hash: str
    is_active: bool
    created_at: str
    updated_at: str

    def safe_dict(self) -> dict[str, str]:
        return {
            "id": self.id,
            "username": self.username,
            "display_name": self.display_name,
            "role": self.role,
        }
