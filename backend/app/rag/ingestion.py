from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
import time
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Sequence

import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq

from ..core.config import Settings, get_settings
from .chunking import (
    ChunkingConfig,
    HeuristicTokenCounter,
    TokenCounter,
    TransformersTokenCounter,
    build_document_chunks,
)
from .embeddings import EmbeddingModel, build_embedding_model
from .hierarchy import HierarchyConfig, build_document_sections
from .models import CHUNK_FIELDS, INGESTION_VERSION, SOURCE_DATASET, ChunkRecord, DocumentNode, PageRecord
from .vector_store import VectorStore

MANIFEST_NAME = "manifest.json"


def log(message: str) -> None:
    print(message, flush=True)


def read_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def write_json_atomic(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, ensure_ascii=False, sort_keys=True)
        handle.write("\n")
    temporary.replace(path)


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def load_documents(settings: Settings) -> list[DocumentNode]:
    entries = read_json(settings.document_manifest_path)
    if not isinstance(entries, list) or not entries:
        raise ValueError("document corpus manifest is empty")
    return [DocumentNode.from_manifest_entry(entry) for entry in entries]


def load_pages(settings: Settings) -> tuple[dict[str, list[PageRecord]], dict[str, int]]:
    rows = pq.read_table(settings.document_pages_path).to_pylist()
    pages_by_document: dict[str, list[PageRecord]] = defaultdict(list)
    quality_counts: Counter[str] = Counter()
    for row in rows:
        quality = str(row.get("text_quality") or "UNKNOWN")
        quality_counts[quality] += 1
        text = row.get("text") or ""
        if not text.strip():
            quality_counts["excluded_no_text"] += 1
            continue
        pages_by_document[str(row["document_id"])].append(
            PageRecord(
                document_id=str(row["document_id"]),
                page_number=int(row["page_number"]),
                text=text,
                page_quality=quality,
                is_sample_page=bool(row.get("possible_scanned_page")),
            )
        )
    return dict(pages_by_document), dict(quality_counts)


def load_candidate_heading_texts(settings: Settings) -> dict[str, set[str]]:
    if not settings.document_headings_path.exists():
        return {}
    rows = pq.read_table(settings.document_headings_path).to_pylist()
    grouped: dict[str, set[str]] = defaultdict(set)
    for row in rows:
        text = str(row.get("heading_text") or "").strip()
        if text:
            grouped[str(row["document_id"])].add(text)
    return dict(grouped)


def chunking_config_from_settings(settings: Settings) -> ChunkingConfig:
    return ChunkingConfig(
        target_tokens=settings.rag_chunk_target_tokens,
        overlap_tokens=settings.rag_chunk_overlap_tokens,
        max_tokens=settings.rag_chunk_max_tokens,
        min_tokens=settings.rag_chunk_min_tokens,
    )


def select_token_counter(settings: Settings) -> TokenCounter:
    counter = TransformersTokenCounter.load(settings.embedding_model)
    if counter is not None:
        return counter
    log("WARNING: tokenizer unavailable, falling back to deterministic heuristic counter")
    return HeuristicTokenCounter()


@dataclass(slots=True)
class ChunkBuildResult:
    chunks: list[ChunkRecord]
    sections_per_document: dict[str, int]
    hierarchy_stats: dict[str, dict[str, Any]]
    token_counter: str
    chunking_config: dict[str, Any]


def build_all_chunks(
    settings: Settings,
    *,
    log_progress: bool = True,
) -> ChunkBuildResult:
    documents = load_documents(settings)
    pages_by_document, _quality_counts = load_pages(settings)
    candidates = load_candidate_heading_texts(settings)
    hierarchy_config = HierarchyConfig(page_marker_window=settings.rag_header_lines)
    chunking_config = chunking_config_from_settings(settings)
    counter = select_token_counter(settings)
    embedding_model = settings.embedding_model

    chunks: list[ChunkRecord] = []
    sections_per_document: dict[str, int] = {}
    hierarchy_stats: dict[str, dict[str, Any]] = {}

    for document in documents:
        pages = pages_by_document.get(document.document_id, [])
        if not pages:
            hierarchy_stats[document.document_id] = {"error": "no staged pages"}
            sections_per_document[document.document_id] = 0
            continue
        sections, stats = build_document_sections(document, pages, hierarchy_config)
        candidate_texts = candidates.get(document.document_id, set())
        if candidate_texts:
            section_texts = {
                heading
                for section in sections
                for heading in section.heading_path
            }
            stats["candidate_heading_total"] = len(candidate_texts)
            stats["candidate_headings_recovered"] = len(candidate_texts & section_texts)
        stats["pages_ingested"] = len(pages)
        stats["pages_total"] = document.page_count or len(pages)
        hierarchy_stats[document.document_id] = dict(stats)
        sections_per_document[document.document_id] = len(sections)
        document_chunks = build_document_chunks(
            document,
            sections,
            chunking_config,
            counter,
            embedding_model=embedding_model,
            ingestion_version=INGESTION_VERSION,
        )
        chunks.extend(document_chunks)
        if log_progress:
            log(
                f"  {document.document_id}: {len(pages)} pages -> "
                f"{len(sections)} sections -> {len(document_chunks)} chunks"
            )

    return ChunkBuildResult(
        chunks=chunks,
        sections_per_document=sections_per_document,
        hierarchy_stats=hierarchy_stats,
        token_counter=counter.name,
        chunking_config=asdict(chunking_config),
    )


def write_chunks_parquet(chunks: Sequence[ChunkRecord], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    columns: dict[str, list[Any]] = {name: [] for name in CHUNK_FIELDS}
    for chunk in chunks:
        payload = chunk.to_payload()
        for name in CHUNK_FIELDS:
            value = payload[name]
            columns[name].append(value)
    table = pa.table({name: pa.array(values) for name, values in columns.items()})
    temporary = path.with_suffix(path.suffix + ".tmp")
    pq.write_table(table, temporary)
    temporary.replace(path)


def compute_fingerprint(
    settings: Settings,
    chunking_config: dict[str, Any],
    chunks: Sequence[ChunkRecord] | None = None,
) -> str:
    documents = load_documents(settings)
    chunk_digest = ""
    if chunks:
        ids = sorted(chunk.chunk_id for chunk in chunks)
        chunk_digest = hashlib.sha256("\n".join(ids).encode("utf-8")).hexdigest()
    payload = {
        "documents": sorted(
            (entry.document_id, entry.sha256 or "") for entry in documents
        ),
        "files": {
            "pages": file_sha256(settings.document_pages_path),
            "metadata": file_sha256(settings.document_metadata_path),
            "headings": file_sha256(settings.document_headings_path)
            if settings.document_headings_path.exists()
            else "",
            "manifest": file_sha256(settings.document_manifest_path),
        },
        "chunk_ids": chunk_digest,
        "chunk_count": len(chunks) if chunks else 0,
        "chunking": chunking_config,
        "embedding_model": settings.embedding_model,
        "ingestion_version": INGESTION_VERSION,
        "collection": settings.rag_collection_name,
    }
    encoded = json.dumps(payload, sort_keys=True, default=str).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def embed_chunks(
    chunks: Sequence[ChunkRecord],
    embedder: EmbeddingModel,
    *,
    batch_size: int = 64,
    log_progress: bool = True,
) -> np.ndarray:
    vectors: list[np.ndarray] = []
    total = len(chunks)
    for start in range(0, total, batch_size):
        batch = chunks[start : start + batch_size]
        vectors.append(embedder.encode([chunk.text for chunk in batch]))
        if log_progress and (start // batch_size) % 10 == 0:
            log(f"  embedded {min(start + batch_size, total)}/{total} chunks")
    if not vectors:
        return np.zeros((0, embedder.dimension), dtype=np.float32)
    return np.vstack(vectors)


def build_store_atomic(
    final_path: Path,
    collection: str,
    chunks: Sequence[ChunkRecord],
    vectors: np.ndarray,
    *,
    log_progress: bool = True,
) -> dict[str, Any]:
    """Build a fresh index in a temp directory, then swap it into place."""

    final_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = final_path.parent / f".{final_path.name}.tmp"
    backup = final_path.parent / f".{final_path.name}.old"
    if temporary.exists():
        shutil.rmtree(temporary, ignore_errors=True)
    if backup.exists():
        shutil.rmtree(backup, ignore_errors=True)

    store = VectorStore(temporary, collection)
    started = time.perf_counter()
    try:
        dimension = int(vectors.shape[1]) if vectors.ndim == 2 and vectors.shape[0] else 0
        store.ensure_collection(dimension)
        written = store.upsert(
            [chunk.chunk_id for chunk in chunks],
            vectors.tolist(),
            [chunk.to_payload() for chunk in chunks],
        )
        indexed = store.point_count()
    finally:
        store.close()
    if indexed != written:
        shutil.rmtree(temporary, ignore_errors=True)
        raise RuntimeError(f"index write mismatch: wrote {written}, found {indexed}")

    if final_path.exists():
        final_path.rename(backup)
    temporary.rename(final_path)
    if backup.exists():
        shutil.rmtree(backup, ignore_errors=True)
    if log_progress:
        log(f"  indexed {indexed} points in {time.perf_counter() - started:.1f}s")
    return {"indexed_points": indexed, "collection": collection, "dimension": int(vectors.shape[1])}


def chunk_statistics(chunks: Sequence[ChunkRecord]) -> dict[str, Any]:
    if not chunks:
        return {"chunk_count": 0}
    token_counts = [chunk.token_count for chunk in chunks]
    return {
        "chunk_count": len(chunks),
        "documents_with_chunks": len({chunk.document_id for chunk in chunks}),
        "unique_content_hashes": len({(chunk.document_id, chunk.content_hash) for chunk in chunks}),
        "token_min": min(token_counts),
        "token_mean": round(sum(token_counts) / len(token_counts), 1),
        "token_median": sorted(token_counts)[len(token_counts) // 2],
        "token_max": max(token_counts),
        "chunks_per_document": dict(Counter(chunk.document_id for chunk in chunks)),
        "sections_with_path": sum(1 for chunk in chunks if chunk.heading_path),
        "sections_without_path": sum(1 for chunk in chunks if not chunk.heading_path),
        "page_range_violations": sum(1 for chunk in chunks if chunk.page_start > chunk.page_end),
        "empty_text_chunks": sum(1 for chunk in chunks if not chunk.text.strip()),
        "duplicate_ids": len(chunks) - len({chunk.chunk_id for chunk in chunks}),
    }


def load_manifest(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    try:
        payload = read_json(path)
    except (OSError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def can_reuse_index(
    settings: Settings,
    fingerprint: str,
    chunk_count: int,
    manifest: dict[str, Any] | None,
) -> bool:
    if not manifest:
        return False
    if manifest.get("fingerprint") != fingerprint:
        return False
    if int(manifest.get("chunk_count") or 0) != chunk_count:
        return False
    if not settings.document_chunks_path.exists():
        return False
    if not settings.vector_store_path.exists():
        return False
    return True


def run_retrieval_sanity(retriever_settings: Settings) -> list[dict[str, Any]]:
    """Run the four sample queries from the STEP 06 brief."""

    import asyncio

    from ..contracts.query import QueryRequest
    from .retrieval import DocumentRetrieverImpl

    samples = [
        "How do I lubricate the spindle?",
        "What is the lockout/tagout procedure?",
        "How do I reset an alarm on the Siemens 828D?",
        "What is the maximum spindle speed of the Haas machine?",
    ]

    async def _run() -> list[dict[str, Any]]:
        retriever = DocumentRetrieverImpl(settings=retriever_settings)
        collected: list[dict[str, Any]] = []
        try:
            for text in samples:
                query = QueryRequest(query_id="sanity", query=text)
                evidences = await retriever.retrieve(query, 5)
                collected.append(
                    {
                        "query": text,
                        "results": [
                            {
                                "rank": index + 1,
                                "score": round(evidence.retrieval_score or 0.0, 4),
                                "document_id": evidence.provenance.document_id,
                                "title": evidence.title,
                                "pages": [
                                    evidence.provenance.page_start,
                                    evidence.provenance.page_end,
                                ],
                                "source_type": str(evidence.source_type),
                            }
                            for index, evidence in enumerate(evidences)
                        ],
                    }
                )
        finally:
            retriever.close()
        return collected

    return asyncio.run(_run())


def build_report(
    settings: Settings,
    *,
    fingerprint: str,
    chunk_result: ChunkBuildResult,
    chunks: Sequence[ChunkRecord],
    embedding_info: dict[str, Any],
    store_info: dict[str, Any],
    manifest: dict[str, Any],
    validation_result: dict[str, Any] | None,
    sanity_results: list[dict[str, Any]],
    hierarchy_rules: list[str],
    generated_at: str,
    reused: bool,
) -> str:
    stats = chunk_statistics(chunks)
    documents = load_documents(settings)
    pages_by_document, quality_counts = load_pages(settings)
    lines: list[str] = []
    append = lines.append

    append("# ManufacturaIQ RAG Build Report")
    append("")
    append(f"- Generated: {generated_at}")
    append(f"- Ingestion version: `{INGESTION_VERSION}`")
    append(f"- Command: `D:\\CMTI\\.venv\\Scripts\\python.exe -m app.rag.ingestion`")
    append(f"- Interpreter: `D:\\CMTI\\.venv\\Scripts\\python.exe` (project virtualenv only)")
    append(f"- Index reused without rebuild: {'yes' if reused else 'no'}")
    append("")

    append("## 1. Dataset inputs")
    append("")
    append("| Artifact | Path |")
    append("| --- | --- |")
    append(f"| Corpus manifest | `{settings.document_manifest_path}` |")
    append(f"| Staged pages | `{settings.document_pages_path}` |")
    append(f"| Document metadata | `{settings.document_metadata_path}` |")
    append(f"| Candidate headings | `{settings.document_headings_path}` |")
    append(f"| Chunk artifact | `{settings.document_chunks_path}` |")
    append(f"| Vector store | `{settings.vector_store_path}` |")
    append("")
    append("Page quality distribution and exclusions:")
    append("")
    for key in sorted(quality_counts):
        append(f"- {key}: {quality_counts[key]}")
    append("")
    append(f"Documents ingested: {len(documents)}")
    append("")
    append("| document_id | filename | type | manufacturer | pages used (text only) | sections | chunks |")
    append("| --- | --- | --- | --- | --- | --- | --- |")
    chunk_counts = stats.get("chunks_per_document", {})
    for document in documents:
        append(
            f"| {document.document_id} | {document.filename} | {document.document_type} | "
            f"{document.manufacturer or '-'} | {len(pages_by_document.get(document.document_id, []))} | "
            f"{chunk_result.sections_per_document.get(document.document_id, 0)} | "
            f"{chunk_counts.get(document.document_id, 0)} |"
        )
    append("")

    append("## 2. Hierarchy reconstruction rules")
    append("")
    for rule in hierarchy_rules:
        append(f"- {rule}")
    append("")
    append("Per-document hierarchy statistics:")
    append("")
    append("| document_id | headings | toc pages | duplicate header lines suppressed | stale parents popped |")
    append("| --- | --- | --- | --- | --- |")
    for document_id, document_stats in chunk_result.hierarchy_stats.items():
        heading_total = sum(
            value for key, value in document_stats.items() if str(key).startswith("headings:")
        )
        append(
            f"| {document_id} | {heading_total} | {document_stats.get('toc_pages', 0)} | "
            f"{document_stats.get('duplicate_header_lines', 0)} | "
            f"{document_stats.get('stale_parents_popped', 0)} |"
        )
    append("")

    append("## 3. Section-aware chunking")
    append("")
    append(f"- Token counter: `{chunk_result.token_counter}`")
    append(f"- Target tokens: {chunk_result.chunking_config['target_tokens']}")
    append(f"- Overlap tokens: {chunk_result.chunking_config['overlap_tokens']}")
    append(f"- Max tokens: {chunk_result.chunking_config['max_tokens']}")
    append(f"- Chunk count: {stats['chunk_count']}")
    append(
        "- Token size: min {token_min} / mean {token_mean} / median {token_median} / max {token_max}".format(
            **stats
        )
    )
    append(f"- Unique chunk ids: {stats['chunk_count'] - stats['duplicate_ids']}")
    append(f"- Empty chunks: {stats['empty_text_chunks']}")
    append(f"- Page range violations: {stats['page_range_violations']}")
    append(
        f"- Chunks with hierarchy path: {stats['sections_with_path']} "
        f"(without: {stats['sections_without_path']})"
    )
    append("")

    append("## 4. Embeddings")
    append("")
    for key, value in embedding_info.items():
        append(f"- {key}: `{value}`")
    append("")

    append("## 5. Vector store")
    append("")
    for key, value in store_info.items():
        append(f"- {key}: `{value}`")
    append(f"- manifest: `{settings.vector_store_path / MANIFEST_NAME}`")
    append(f"- manifest created_at: `{manifest.get('created_at', 'n/a')}`")
    append(f"- manifest token_counter: `{manifest.get('token_counter', 'n/a')}`")
    append(f"- fingerprint: `{fingerprint}`")
    append("")

    append("## 6. Retrieval quality metrics")
    append("")
    if validation_result:
        metrics = validation_result.get("metrics", {})
        append("| metric | value | threshold | status |")
        append("| --- | --- | --- | --- |")
        for name, metric in metrics.items():
            append(
                f"| {name} | {metric.get('value')} | {metric.get('threshold')} | {metric.get('status')} |"
            )
        append("")
        append(f"Cases evaluated: {metrics.get('cases', {}).get('value', 'n/a')}")
    else:
        append("_Validation was not run for this build._")
    append("")

    append("## 6b. Content-level retrieval metrics")
    append("")
    if validation_result:
        content_metrics = validation_result.get("content_metrics") or {}
        append("| metric | value |")
        append("| --- | --- |")
        for name in ("cases", "content_hit_at_1", "content_hit_at_3", "content_hit_at_5", "content_mrr"):
            append(f"| {name} | {content_metrics.get(name, 'n/a')} |")
        append("")
        append(f"Content cases without a content hit: {content_metrics.get('failed_cases', [])}")
        append("")
        append("_ContentHit metrics are informational only and carry no pass/fail thresholds._")
    else:
        append("_Validation was not run for this build._")
    append("")

    append("## 7. Validation checks")
    append("")
    if validation_result:
        append("| check | status | detail |")
        append("| --- | --- | --- |")
        for check in validation_result.get("checks", []):
            detail = str(check.get("detail", "")).replace("|", "/")
            append(f"| {check['name']} | {check['status']} | {detail} |")
        append("")
        append(f"Overall: **{validation_result.get('status', 'UNKNOWN')}**")
    else:
        append("_Validation was not run for this build._")
    append("")

    append("## 8. Retrieval sanity queries")
    append("")
    for entry in sanity_results:
        append(f"### {entry['query']}")
        append("")
        append("| rank | score | document_id | pages | source_type | title |")
        append("| --- | --- | --- | --- | --- | --- |")
        for result in entry["results"]:
            pages = f"{result['pages'][0]}-{result['pages'][1]}"
            title = str(result["title"]).replace("|", "/")
            append(
                f"| {result['rank']} | {result['score']} | {result['document_id']} | "
                f"{pages} | {result['source_type']} | {title} |"
            )
        append("")

    append("## 9. How to rerun")
    append("")
    append("```")
    append("cd D:\\CMTI\\backend")
    append("D:\\CMTI\\.venv\\Scripts\\python.exe -m app.rag.ingestion --force")
    append("D:\\CMTI\\.venv\\Scripts\\python.exe -m app.rag.validation")
    append('D:\\CMTI\\.venv\\Scripts\\python.exe -m app.rag.retrieval "spindle lubrication"')
    append("```")
    append("")
    return "\n".join(lines)


def run_ingestion(
    settings: Settings | None = None,
    *,
    force: bool = False,
    chunks_only: bool = False,
    device: str | None = None,
    log_progress: bool = True,
) -> dict[str, Any]:
    settings = settings or get_settings()
    started = time.perf_counter()
    generated_at = datetime.now(timezone.utc).isoformat(timespec="seconds")

    if log_progress:
        log("== STEP 06 ingestion: hierarchy -> chunks -> embeddings -> qdrant ==")

    chunk_result = build_all_chunks(settings, log_progress=log_progress)
    chunks = chunk_result.chunks
    if not chunks:
        raise RuntimeError("no chunks produced from staged artifacts")

    fingerprint = compute_fingerprint(settings, chunk_result.chunking_config, chunks)
    manifest_path = settings.vector_store_path / MANIFEST_NAME
    existing_manifest = load_manifest(manifest_path)
    write_chunks_parquet(chunks, settings.document_chunks_path)
    if log_progress:
        log(f"  wrote {len(chunks)} chunks to {settings.document_chunks_path}")

    embedder = build_embedding_model(settings.embedding_model, device=device)
    store_info: dict[str, Any] = {
        "collection": settings.rag_collection_name,
        "path": str(settings.vector_store_path),
        "status": "skipped",
    }
    embedding_info: dict[str, Any] = {"embedding_model": settings.embedding_model}
    reused = False

    manifest: dict[str, Any]
    if chunks_only:
        if log_progress:
            log("  --chunks-only: skipping embedding and vector store build")
        store_info["status"] = "chunks_only"
        manifest = {}
    elif not force and can_reuse_index(settings, fingerprint, len(chunks), existing_manifest):
        reused = True
        store_info["status"] = "reused"
        manifest = dict(existing_manifest or {})
        embedding_info.update(
            {
                "dimension": manifest.get("embedding_dimension"),
                "device": manifest.get("device"),
                "load_seconds": "reused",
            }
        )
        if log_progress:
            log("  fingerprint match: reusing existing vector index")
    else:
        if log_progress:
            log(f"  embedding {len(chunks)} chunks with {settings.embedding_model}")
        embedder.load()
        vectors = embed_chunks(chunks, embedder, log_progress=log_progress)
        embedding_info.update(embedder.describe())
        store_info.update(
            build_store_atomic(
                settings.vector_store_path,
                settings.rag_collection_name,
                chunks,
                vectors,
                log_progress=log_progress,
            )
        )
        store_info["status"] = "built"
        manifest = {
            "fingerprint": fingerprint,
            "chunk_count": len(chunks),
            "documents": [
                {"document_id": entry.document_id, "sha256": entry.sha256}
                for entry in load_documents(settings)
            ],
            "collection": settings.rag_collection_name,
            "qdrant_path": str(settings.vector_store_path),
            "chunk_parquet": str(settings.document_chunks_path),
            "embedding_model": settings.embedding_model,
            "embedding_dimension": embedding_info.get("dimension"),
            "device": embedding_info.get("device"),
            "token_counter": chunk_result.token_counter,
            "chunking_config": chunk_result.chunking_config,
            "ingestion_version": INGESTION_VERSION,
            "source_dataset": SOURCE_DATASET,
            "created_at": generated_at,
        }

    if manifest:
        write_json_atomic(manifest_path, manifest)

    validation_result: dict[str, Any] | None = None
    sanity_results: list[dict[str, Any]] = []
    if not chunks_only:
        from .validation import run_validation

        validation_result = run_validation(settings, log_progress=log_progress)
        sanity_results = run_retrieval_sanity(settings)
        if log_progress:
            log(f"  validation: {validation_result.get('status')}")
            for check in validation_result.get("checks", []):
                if check["status"] != "PASS":
                    log(f"    {check['status']}: {check['name']} - {check.get('detail', '')}")

    hierarchy_rules = [
        "Source of truth: staged page text only (no PDF re-parsing).",
        "Edge page markers (first/last 3 physical lines matching digits or roman numerals <= 50) are blanked before analysis.",
        "Pages with >= 5 dot-leader lines or >= 5 numbered contents entries are treated as contents pages: no headings are detected there.",
        "Headings: `Chapter N[: Title]`, `N.N Title` single line, `N.N` + title on the following line, and an uppercase structural keyword allowlist.",
        "Unnumbered Title Case headings are accepted only after a blank line and when followed by another line on the same page.",
        "Wrapped-line guards: connector last words, long trailing sentences and lowercase continuations reject body text.",
        "Repeat suppression: a heading (level + text) already seen in the document is treated as a running header and removed from body text.",
        "Stale parent suppression: an unnumbered parent is popped when a numbered child heading starts a new branch.",
        "Original heading text is preserved verbatim; missing hierarchy levels are never invented.",
    ]

    report = build_report(
        settings,
        fingerprint=fingerprint,
        chunk_result=chunk_result,
        chunks=chunks,
        embedding_info=embedding_info,
        store_info=store_info,
        manifest=manifest,
        validation_result=validation_result,
        sanity_results=sanity_results,
        hierarchy_rules=hierarchy_rules,
        generated_at=generated_at,
        reused=reused,
    )
    settings.rag_build_report_path.parent.mkdir(parents=True, exist_ok=True)
    settings.rag_build_report_path.write_text(report, encoding="utf-8")
    if log_progress:
        log(f"  report written to {settings.rag_build_report_path}")
        log(f"  done in {time.perf_counter() - started:.1f}s")

    return {
        "chunks": len(chunks),
        "fingerprint": fingerprint,
        "reused": reused,
        "store": store_info,
        "validation": validation_result,
        "sanity": sanity_results,
        "statistics": chunk_statistics(chunks),
        "sections": chunk_result.sections_per_document,
    }


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m app.rag.ingestion",
        description="Build the ManufacturaIQ hierarchical document RAG index.",
    )
    parser.add_argument("--force", action="store_true", help="rebuild even if the fingerprint matches")
    parser.add_argument("--chunks-only", action="store_true", help="skip embeddings and vector store build")
    parser.add_argument("--device", default=None, help="torch device override (cpu, cuda, mps)")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    try:
        result = run_ingestion(force=args.force, chunks_only=args.chunks_only, device=args.device)
    except Exception as exc:  # pragma: no cover - CLI failure path
        print(f"ingestion failed: {exc}", file=sys.stderr)
        return 1
    validation = result.get("validation")
    if validation and validation.get("status") != "PASS":
        return 2
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
