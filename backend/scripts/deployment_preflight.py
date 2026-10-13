"""Read-only deployment preflight checks for ManufacturaIQ.

This script reports configured deployment paths and provider presence without
printing secret values or modifying databases, vectors, documents, or caches.
"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from pathlib import Path

from app.core.config import Settings, get_settings


@dataclass(slots=True)
class Check:
    name: str
    status: str
    detail: str


def _is_relative_to(path: Path, parent: Path) -> bool:
    try:
        path.resolve().relative_to(parent.resolve())
        return True
    except ValueError:
        return False


def _exists_dir(path: Path) -> bool:
    return path.exists() and path.is_dir()


def _writable_dir(path: Path) -> bool:
    return _exists_dir(path) and os.access(path, os.W_OK)


def build_checks(settings: Settings | None = None) -> list[Check]:
    resolved = settings or get_settings()
    persistent_root = Path(os.environ.get("MANUFACTURAIQ_PERSISTENT_ROOT", "/var/data"))

    checks: list[Check] = []
    checks.append(
        Check(
            "Persistent root",
            "PASS" if _writable_dir(persistent_root) else "FAIL",
            str(persistent_root),
        )
    )
    checks.append(
        Check(
            "Manufacturing DB",
            "PASS" if resolved.database_path.is_file() else "FAIL",
            str(resolved.database_path),
        )
    )
    auth_path = resolved.auth_database_path
    auth_on_disk = _is_relative_to(auth_path, persistent_root)
    auth_exists = auth_path.is_file()
    checks.append(
        Check(
            "Auth DB path",
            "PASS" if auth_on_disk and auth_exists else "FAIL",
            f"{auth_path} ({'under persistent root' if auth_on_disk else 'not under persistent root'})",
        )
    )
    checks.append(
        Check(
            "Static RAG store",
            "PASS" if _exists_dir(resolved.vector_store_path) else "FAIL",
            str(resolved.vector_store_path),
        )
    )
    doc_root = resolved.document_storage_root
    doc_dirs = [doc_root / name for name in ("originals", "processing", "registry", "vectors")]
    missing_doc_dirs = [str(path) for path in doc_dirs if not _exists_dir(path)]
    checks.append(
        Check(
            "Document storage",
            "PASS" if not missing_doc_dirs and _writable_dir(doc_root) else "FAIL",
            str(doc_root) if not missing_doc_dirs else "missing: " + ", ".join(missing_doc_dirs),
        )
    )
    hf_home = os.environ.get("HF_HOME")
    if hf_home:
        hf_path = Path(hf_home)
        checks.append(
            Check(
                "Hugging Face cache",
                "PASS" if _is_relative_to(hf_path, persistent_root) else "WARN",
                str(hf_path),
            )
        )
    else:
        checks.append(Check("Hugging Face cache", "WARN", "HF_HOME not set"))
    checks.append(
        Check(
            "Gemini configured",
            "PASS" if bool(resolved.gemini_api_key) else "FAIL",
            "configured" if resolved.gemini_api_key else "missing GEMINI_API_KEY",
        )
    )
    checks.append(
        Check(
            "TypeSafe configured",
            "PASS" if bool(resolved.typesafe_api_key) else "OPTIONAL/FALLBACK",
            "configured" if resolved.typesafe_api_key else "deterministic fallback will be used",
        )
    )
    localhost_only = resolved.cors_allowed_origins == ["http://localhost:5173"]
    checks.append(
        Check(
            "CORS configured",
            "PASS" if resolved.cors_allowed_origins and not localhost_only else "FAIL",
            ", ".join(resolved.cors_allowed_origins),
        )
    )
    return checks


def main() -> int:
    print("ManufacturaIQ Deployment Preflight")
    print()
    checks = build_checks()
    for check in checks:
        print(f"{check.name:<24}: {check.status:<17} {check.detail}")
    failed = [check for check in checks if check.status == "FAIL"]
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
