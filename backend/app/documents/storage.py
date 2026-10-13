"""Durable original-file storage with untrusted-filename handling."""

from __future__ import annotations

import hashlib
import os
import re
from pathlib import Path
from typing import BinaryIO

_SAFE_STEM = re.compile(r"[^A-Za-z0-9._-]+")


def sanitize_stored_name(document_id: str, extension: str = ".pdf") -> str:
    """System-controlled filename; the original name never touches the path."""

    stem = _SAFE_STEM.sub("_", document_id).strip("._") or "document"
    return f"{stem}{extension.lower()}"


def assert_safe_relative(name: str) -> None:
    """Reject traversal, absolute paths, and separator abuse in a filename."""

    if not name or name != Path(name).name:
        raise ValueError(f"unsafe filename: {name!r}")
    if ".." in Path(name).parts:
        raise ValueError(f"unsafe filename: {name!r}")


class StoredUpload:
    __slots__ = ("path", "sha256", "size_bytes")

    def __init__(self, path: Path, sha256: str, size_bytes: int) -> None:
        self.path = path
        self.sha256 = sha256
        self.size_bytes = size_bytes


class DocumentStorage:
    """Original-file storage rooted at a dedicated directory."""

    def __init__(self, root: Path | str) -> None:
        self.root = Path(root)
        self.originals = self.root / "originals"
        self.processing = self.root / "processing"
        self.registry_dir = self.root / "registry"
        self.vectors = self.root / "vectors"
        for directory in (self.originals, self.processing, self.registry_dir, self.vectors):
            directory.mkdir(parents=True, exist_ok=True)

    def original_path(self, stored_filename: str) -> Path:
        assert_safe_relative(stored_filename)
        return self.originals / stored_filename

    def has_original(self, stored_filename: str) -> bool:
        try:
            return self.original_path(stored_filename).is_file()
        except ValueError:
            return False

    def store_stream(
        self,
        stream: BinaryIO,
        *,
        stored_filename: str,
        max_bytes: int,
        chunk_size: int = 1024 * 256,
    ) -> StoredUpload:
        """Stream to a temp file with size cap + SHA-256, then atomic move."""

        assert_safe_relative(stored_filename)
        target = self.originals / stored_filename
        tmp_path = self.processing / f"{stored_filename}.part"
        digest = hashlib.sha256()
        size = 0
        try:
            with open(tmp_path, "wb") as handle:
                while True:
                    chunk = stream.read(chunk_size)
                    if not chunk:
                        break
                    size += len(chunk)
                    if size > max_bytes:
                        raise ValueError(
                            f"upload exceeds maximum size of {max_bytes} bytes"
                        )
                    digest.update(chunk)
                    handle.write(chunk)
        except BaseException:
            try:
                os.remove(tmp_path)
            except OSError:
                pass
            raise
        os.replace(tmp_path, target)
        return StoredUpload(path=target, sha256=digest.hexdigest(), size_bytes=size)

    def remove_original(self, stored_filename: str) -> bool:
        try:
            path = self.original_path(stored_filename)
        except ValueError:
            return False
        try:
            os.remove(path)
            return True
        except OSError:
            return False
