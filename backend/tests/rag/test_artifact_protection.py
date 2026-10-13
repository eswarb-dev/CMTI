from __future__ import annotations

import hashlib
from pathlib import Path

import pytest


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


@pytest.fixture(scope="session", autouse=True)
def _guard_canonical_step06_artifacts(settings):
    """Fail the suite if any test recreates or overwrites canonical artifacts.

    RAG unit tests may READ document_chunks.parquet, the vector store and its
    manifest, and may write only inside ``tmp_path``. The corpus fingerprint
    recorded in the vector manifest must survive the whole test session.
    """

    from app.rag.ingestion import load_manifest

    chunks_path = Path(settings.document_chunks_path)
    manifest_path = Path(settings.vector_store_path) / "manifest.json"
    manifest = load_manifest(manifest_path)
    before = {
        "chunks_sha256": _sha256(chunks_path),
        "manifest_fingerprint": (manifest or {}).get("fingerprint"),
        "manifest_chunk_count": (manifest or {}).get("chunk_count"),
    }
    assert before["manifest_fingerprint"], "vector manifest fingerprint missing"
    yield
    assert _sha256(chunks_path) == before["chunks_sha256"], (
        "canonical chunk artifact was rewritten during tests"
    )
    after = load_manifest(manifest_path) or {}
    assert after.get("fingerprint") == before["manifest_fingerprint"], (
        "vector manifest fingerprint changed during tests"
    )
    assert after.get("chunk_count") == before["manifest_chunk_count"], (
        "vector manifest chunk count changed during tests"
    )


def test_canonical_chunk_artifact_hash_is_stable(settings) -> None:
    assert Path(settings.document_chunks_path).is_file()
