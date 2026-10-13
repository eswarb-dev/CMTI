from __future__ import annotations

from dataclasses import replace

import pyarrow.parquet as pq

from app.rag.ingestion import (
    can_reuse_index,
    chunk_statistics,
    chunking_config_from_settings,
    compute_fingerprint,
    load_manifest,
    write_chunks_parquet,
)
from app.rag.models import CHUNK_FIELDS, ChunkRecord
from app.rag.vector_store import point_id_for


def read_artifact_chunks(path) -> list[ChunkRecord]:
    rows = pq.read_table(path).to_pylist()
    return [ChunkRecord.from_payload(row) for row in rows]


def test_point_ids_are_deterministic_and_unique_per_chunk() -> None:
    assert point_id_for("CHUNK-A") == point_id_for("CHUNK-A")
    assert point_id_for("CHUNK-A") != point_id_for("CHUNK-B")
    assert point_id_for("CHUNK-A") != point_id_for("CHUNK-A ")


def test_fingerprint_is_stable_and_sensitive_to_chunk_and_config_changes(
    settings, chunks
) -> None:
    chunking = chunking_config_from_settings(settings)
    config_dict = {
        "target_tokens": chunking.target_tokens,
        "overlap_tokens": chunking.overlap_tokens,
        "max_tokens": chunking.max_tokens,
        "min_tokens": chunking.min_tokens,
    }

    first = compute_fingerprint(settings, config_dict, chunks)
    second = compute_fingerprint(settings, config_dict, chunks)
    assert first == second

    changed_chunks = list(chunks)
    changed_chunks[0] = replace(chunks[0], chunk_id="CHUNK-CHANGED")
    assert compute_fingerprint(settings, config_dict, changed_chunks) != first

    assert compute_fingerprint(settings, {**config_dict, "target_tokens": 128}, chunks) != first
    assert compute_fingerprint(settings, config_dict) != first


def test_manifest_matches_the_current_chunk_artifact(settings) -> None:
    manifest = load_manifest(settings.vector_store_path / "manifest.json")

    assert manifest is not None
    assert manifest["ingestion_version"] == "step06.v1"
    assert manifest["collection"] == settings.rag_collection_name

    chunks = read_artifact_chunks(settings.document_chunks_path)
    assert int(manifest["chunk_count"]) == len(chunks)

    fingerprint = compute_fingerprint(settings, manifest["chunking_config"], chunks)
    assert fingerprint == manifest["fingerprint"]


def test_can_reuse_index_gates_on_fingerprint_chunk_count_and_paths(settings, chunks) -> None:
    manifest = load_manifest(settings.vector_store_path / "manifest.json")
    assert manifest is not None

    fingerprint = str(manifest["fingerprint"])
    chunk_count = int(manifest["chunk_count"])

    assert can_reuse_index(settings, fingerprint, chunk_count, manifest)
    assert not can_reuse_index(settings, fingerprint, chunk_count, None)
    assert not can_reuse_index(settings, fingerprint + "x", chunk_count, manifest)
    assert not can_reuse_index(settings, fingerprint, chunk_count + 1, manifest)


def test_chunk_artifact_round_trip_preserves_contract_fields(tmp_path, chunks) -> None:
    target = tmp_path / "document_chunks.parquet"

    write_chunks_parquet(chunks, target)
    table = pq.read_table(target)
    rows = table.to_pylist()

    assert table.column_names == list(CHUNK_FIELDS)
    assert len(rows) == len(chunks)

    rebuilt = [ChunkRecord.from_payload(row) for row in rows]
    original = chunks[0]
    sample = rebuilt[0]
    assert sample.chunk_id == original.chunk_id
    assert sample.text == original.text
    assert sample.heading_path == original.heading_path
    assert sample.source_type == original.source_type
    assert sample.content_hash == original.content_hash


def test_chunk_statistics_report_a_healthy_artifact(settings, chunks) -> None:
    stats = chunk_statistics(chunks)

    assert stats["chunk_count"] == len(chunks) == 2193
    assert stats["documents_with_chunks"] == 4
    assert stats["unique_content_hashes"] == stats["chunk_count"]
    assert stats["duplicate_ids"] == 0
    assert stats["empty_text_chunks"] == 0
    assert stats["page_range_violations"] == 0
    assert stats["token_max"] <= settings.rag_chunk_max_tokens
    assert stats["token_min"] < stats["token_median"] <= stats["token_max"]
    assert stats["sections_with_path"] > stats["sections_without_path"] > 0
