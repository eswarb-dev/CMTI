from __future__ import annotations

import argparse
import json
import re
import sys
import time
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pyarrow.parquet as pq

from ..contracts.query import QueryRequest
from ..core.config import Settings, get_settings

DEFAULT_THRESHOLDS = {
    "hit_at_1": 0.5,
    "hit_at_3": 0.7,
    "hit_at_5": 0.8,
    "mrr": 0.6,
}


@dataclass(slots=True)
class Check:
    name: str
    status: str
    detail: str

    def as_dict(self) -> dict[str, str]:
        return {"name": self.name, "status": self.status, "detail": self.detail}


def default_fixture_path(settings: Settings) -> Path:
    return settings.project_root / "backend" / "tests" / "rag" / "fixtures" / "retrieval_cases.json"


def load_cases(path: Path) -> tuple[list[dict[str, Any]], dict[str, float]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    cases = list(payload.get("cases") or [])
    thresholds = dict(DEFAULT_THRESHOLDS)
    thresholds.update({key: float(value) for key, value in (payload.get("thresholds") or {}).items()})
    return cases, thresholds


def _check(name: str, ok: bool, detail: str) -> Check:
    return Check(name=name, status="PASS" if ok else "FAIL", detail=detail)


def check_dataset_inputs(settings: Settings) -> list[Check]:
    checks: list[Check] = []
    manifest_ok = settings.document_manifest_path.exists()
    checks.append(
        _check(
            "corpus_manifest_present",
            manifest_ok,
            str(settings.document_manifest_path),
        )
    )
    required = [
        settings.document_pages_path,
        settings.document_metadata_path,
        settings.document_headings_path,
    ]
    missing = [str(path) for path in required if not path.exists()]
    checks.append(
        _check(
            "staged_artifacts_present",
            not missing,
            "all staged artifacts present" if not missing else f"missing: {missing}",
        )
    )
    checks.append(
        _check(
            "chunks_artifact_present",
            settings.document_chunks_path.exists(),
            str(settings.document_chunks_path),
        )
    )
    return checks


def check_chunk_quality(settings: Settings) -> list[Check]:
    checks: list[Check] = []
    if not settings.document_chunks_path.exists():
        checks.append(Check("chunk_quality", "FAIL", "chunk artifact missing"))
        return checks
    rows = pq.read_table(settings.document_chunks_path).to_pylist()
    ids = [row["chunk_id"] for row in rows]
    unique_ids = len(set(ids))
    checks.append(
        _check(
            "unique_chunk_ids",
            unique_ids == len(ids),
            f"{unique_ids}/{len(ids)} unique chunk ids",
        )
    )
    empty = [row["chunk_id"] for row in rows if not (row["text"] or "").strip()]
    checks.append(
        _check("no_empty_chunks", not empty, f"{len(empty)} empty chunks")
    )
    seen: set[tuple[str, str]] = set()
    duplicates = 0
    for row in rows:
        key = (str(row["document_id"]), str(row["content_hash"]))
        if key in seen:
            duplicates += 1
        seen.add(key)
    checks.append(
        _check(
            "no_duplicate_chunks",
            duplicates == 0,
            f"{duplicates} duplicated (document, content_hash) pairs",
        )
    )
    page_violations = [
        row["chunk_id"] for row in rows if int(row["page_start"]) > int(row["page_end"])
    ]
    checks.append(
        _check(
            "chunk_page_ranges_valid",
            not page_violations,
            f"{len(page_violations)} chunks with page_start > page_end",
        )
    )
    hierarchy_missing = [
        row["chunk_id"]
        for row in rows
        if row.get("heading_path") is None or row.get("section_key") in (None, "")
    ]
    checks.append(
        _check(
            "chunk_hierarchy_fields_present",
            not hierarchy_missing,
            f"{len(hierarchy_missing)} chunks without hierarchy metadata",
        )
    )
    return checks


def check_vector_store(settings: Settings) -> list[Check]:
    checks: list[Check] = []
    from .ingestion import MANIFEST_NAME, load_manifest
    from .vector_store import VectorStore

    store_path = settings.vector_store_path
    checks.append(_check("vector_store_present", store_path.exists(), str(store_path)))
    manifest = load_manifest(store_path / MANIFEST_NAME)
    checks.append(
        _check(
            "vector_store_manifest_present",
            manifest is not None,
            str(store_path / MANIFEST_NAME),
        )
    )
    chunk_rows = 0
    if settings.document_chunks_path.exists():
        chunk_rows = pq.read_table(settings.document_chunks_path, columns=["chunk_id"]).num_rows
    store = VectorStore(store_path, settings.rag_collection_name)
    try:
        count = store.point_count()
    finally:
        store.close()
    expected = int((manifest or {}).get("chunk_count") or chunk_rows)
    checks.append(
        _check(
            "indexed_chunk_count_matches",
            count == chunk_rows == expected,
            f"qdrant={count} parquet={chunk_rows} manifest={expected}",
        )
    )
    return checks


async def _collect_case_results(
    settings: Settings,
    cases: list[dict[str, Any]],
    retriever: Any | None = None,
) -> list[dict[str, Any]]:
    from .retrieval import DocumentRetrieverImpl

    owns_retriever = retriever is None
    active = retriever if retriever is not None else DocumentRetrieverImpl(settings=settings)
    collected: list[dict[str, Any]] = []
    try:
        for case in cases:
            query = QueryRequest(
                query_id=str(case.get("case_id") or "case"),
                query=str(case["query"]),
                machine_id=case.get("machine_id"),
                product_id=case.get("product_id"),
                batch_id=case.get("batch_id"),
                user_context=dict(case.get("user_context") or {}),
            )
            top_k = int(case.get("top_k") or 5)
            evidences = await active.retrieve(query, top_k)
            expected = [str(item) for item in (case.get("expected_document_ids") or [])]
            ranks = [
                index + 1
                for index, evidence in enumerate(evidences)
                if evidence.provenance.document_id in expected
            ]
            best_rank = min(ranks) if ranks else None
            requirements = content_requirements(case)
            returned = [
                {
                    "document_id": evidence.provenance.document_id,
                    "chunk_id": evidence.provenance.chunk_id,
                    "source_type": str(evidence.source_type),
                    "score": round(evidence.retrieval_score or 0.0, 4),
                    "title": evidence.title,
                    "text": evidence.content,
                    "heading_path": list((evidence.metadata or {}).get("heading_path") or []),
                }
                for evidence in evidences
            ]
            content_ranks = (
                [
                    index + 1
                    for index, item in enumerate(returned)
                    if requirements is not None and is_content_hit(item, requirements)
                ]
                if requirements is not None
                else []
            )
            collected.append(
                {
                    "case_id": case.get("case_id"),
                    "query": case["query"],
                    "expected_document_ids": expected,
                    "best_rank": best_rank,
                    "returned": returned,
                    "content_requirements": requirements,
                    "content_best_rank": min(content_ranks) if content_ranks else None,
                    "required_source_types": list(case.get("required_source_types") or []),
                    "filtered_on_source_type": bool(
                        (case.get("user_context") or {}).get("document_type")
                    ),
                }
            )
    finally:
        if owns_retriever:
            active.close()
    return collected


def compute_metrics(case_results: list[dict[str, Any]]) -> dict[str, Any]:
    if not case_results:
        return {"cases": 0, "hit_at_1": 0.0, "hit_at_3": 0.0, "hit_at_5": 0.0, "mrr": 0.0}
    hits = {1: 0, 3: 0, 5: 0}
    reciprocal_total = 0.0
    failures: list[str] = []
    for result in case_results:
        rank = result.get("best_rank")
        if rank is None:
            failures.append(str(result.get("case_id")))
            continue
        reciprocal_total += 1.0 / rank
        for depth in hits:
            if rank <= depth:
                hits[depth] += 1
    total = len(case_results)
    return {
        "cases": total,
        "hit_at_1": round(hits[1] / total, 3),
        "hit_at_3": round(hits[3] / total, 3),
        "hit_at_5": round(hits[5] / total, 3),
        "mrr": round(reciprocal_total / total, 3),
        "failed_cases": failures,
    }


CONTENT_METRIC_NAMES = ("content_hit_at_1", "content_hit_at_3", "content_hit_at_5")

# Fixture keys that turn a case into a content-evaluated case. Document and
# source-type expectations are reused from the existing fields; the keys below
# add the chunk/content-level requirements.
CONTENT_REQUIREMENT_KEYS = (
    "expected_keywords",
    "expected_keywords_any",
    "expected_heading_keywords",
    "forbidden_heading_keywords",
)


def _fold(text: Any) -> str:
    return unicodedata.normalize("NFKC", str(text or "")).casefold()


def _flat_text(text: Any) -> str:
    return re.sub(r"\s+", " ", _fold(text)).strip()


def _content_tokens(text: Any) -> set[str]:
    return set(re.findall(r"[a-z0-9]+", _fold(text)))


def _term_present(term: str, tokens: set[str], flat: str) -> bool:
    cleaned = _flat_text(term)
    if not cleaned:
        return False
    if re.fullmatch(r"[a-z0-9]+", cleaned):
        return cleaned in tokens
    return cleaned in flat


def content_requirements(case: dict[str, Any]) -> dict[str, Any] | None:
    """Return chunk-level requirements, or None if the case is doc-level only."""

    if not any(case.get(key) for key in CONTENT_REQUIREMENT_KEYS):
        return None
    return {
        "documents": [str(item) for item in (case.get("expected_document_ids") or [])],
        "source_types": [str(item) for item in (case.get("required_source_types") or [])],
        "keywords_all": [str(item) for item in (case.get("expected_keywords") or [])],
        "keywords_any": [str(item) for item in (case.get("expected_keywords_any") or [])],
        "heading_all": [str(item) for item in (case.get("expected_heading_keywords") or [])],
        "heading_forbidden": [str(item) for item in (case.get("forbidden_heading_keywords") or [])],
    }


def is_content_hit(item: dict[str, Any], requirements: dict[str, Any]) -> bool:
    """Deterministic chunk/content relevance: every applicable requirement holds.

    - expected document / source type (when the case declares them), AND
    - all ``expected_keywords`` present in chunk text, AND
    - at least one ``expected_keywords_any`` present (when declared), AND
    - all ``expected_heading_keywords`` present in title/headings, AND
    - no ``forbidden_heading_keywords`` present in title/headings.
    """

    if requirements["documents"] and item.get("document_id") not in requirements["documents"]:
        return False
    if requirements["source_types"] and item.get("source_type") not in requirements["source_types"]:
        return False
    tokens = _content_tokens(item.get("text"))
    flat = _flat_text(item.get("text"))
    if any(not _term_present(term, tokens, flat) for term in requirements["keywords_all"]):
        return False
    if requirements["keywords_any"] and not any(
        _term_present(term, tokens, flat) for term in requirements["keywords_any"]
    ):
        return False
    heading_text = _flat_text(item.get("title")) + "\n" + "\n".join(
        _flat_text(part) for part in (item.get("heading_path") or [])
    )
    heading_tokens = _content_tokens(heading_text)
    if any(
        not _term_present(term, heading_tokens, heading_text)
        for term in requirements["heading_all"]
    ):
        return False
    if any(
        _term_present(term, heading_tokens, heading_text)
        for term in requirements["heading_forbidden"]
    ):
        return False
    return True


def compute_content_metrics(case_results: list[dict[str, Any]]) -> dict[str, Any]:
    """ContentHit@k over content-evaluated cases only (info metrics, no thresholds)."""

    hits = {1: 0, 3: 0, 5: 0}
    reciprocal_total = 0.0
    evaluated = 0
    failures: list[str] = []
    for result in case_results:
        requirements = result.get("content_requirements")
        if not requirements:
            continue
        evaluated += 1
        ranks = [
            index + 1
            for index, item in enumerate(result.get("returned") or [])
            if is_content_hit(item, requirements)
        ]
        if not ranks:
            failures.append(str(result.get("case_id")))
            continue
        best = min(ranks)
        reciprocal_total += 1.0 / best
        for depth in hits:
            if best <= depth:
                hits[depth] += 1
    if not evaluated:
        return {
            "cases": 0,
            "content_hit_at_1": 0.0,
            "content_hit_at_3": 0.0,
            "content_hit_at_5": 0.0,
            "content_mrr": 0.0,
            "failed_cases": [],
        }
    return {
        "cases": evaluated,
        "content_hit_at_1": round(hits[1] / evaluated, 3),
        "content_hit_at_3": round(hits[3] / evaluated, 3),
        "content_hit_at_5": round(hits[5] / evaluated, 3),
        "content_mrr": round(reciprocal_total / evaluated, 3),
        "failed_cases": failures,
    }


def _source_scope_violated(result: dict[str, Any]) -> bool:
    """Scope semantics: a filtered case must return only scoped source types;
    an unfiltered case only needs its matched evidence to carry the expected
    source type (other source types may legitimately appear at other ranks)."""

    required = list(result.get("required_source_types") or [])
    returned = list(result.get("returned") or [])
    if not required:
        return False
    if result.get("filtered_on_source_type"):
        return any(item["source_type"] not in required for item in returned)
    matched = [
        item
        for item in returned
        if item["document_id"] in (result.get("expected_document_ids") or [])
    ]
    if not matched:
        return False
    return all(item["source_type"] not in required for item in matched)


def check_retrieval_quality(
    settings: Settings,
    *,
    fixture_path: Path | None = None,
    include_vector_checks: bool = True,
    retriever: Any | None = None,
) -> dict[str, Any]:
    fixture = fixture_path or default_fixture_path(settings)
    if not fixture.exists():
        return {
            "checks": [
                Check("retrieval_fixture_present", "FAIL", f"missing fixture: {fixture}")
            ],
            "metrics": {"cases": 0},
            "case_results": [],
        }
    cases, thresholds = load_cases(fixture)
    import asyncio

    case_results = asyncio.run(_collect_case_results(settings, cases, retriever))
    metrics = compute_metrics(case_results)
    content_metrics = compute_content_metrics(case_results)
    checks: list[Check] = [
        _check("retrieval_fixture_present", True, f"{len(cases)} cases in {fixture}"),
        _check("retrieval_cases_evaluated", metrics["cases"] == len(cases), f"{metrics['cases']}/{len(cases)}"),
    ]
    for metric_name in ("hit_at_1", "hit_at_3", "hit_at_5", "mrr"):
        threshold = thresholds.get(metric_name, DEFAULT_THRESHOLDS[metric_name])
        value = float(metrics.get(metric_name, 0.0))
        checks.append(
            _check(
                f"retrieval_{metric_name}",
                value >= threshold,
                f"{value} >= {threshold}",
            )
        )
    for metric_name in CONTENT_METRIC_NAMES:
        value = float(content_metrics.get(metric_name, 0.0))
        checks.append(
            _check(
                f"retrieval_{metric_name}",
                True,
                f"{value} over {content_metrics.get('cases', 0)} content cases (info only, no threshold)",
            )
        )
    source_failures = [
        result["case_id"]
        for result in case_results
        if _source_scope_violated(result)
    ]
    checks.append(
        _check(
            "evidence_source_type_scope",
            not source_failures,
            f"source type violations in cases: {source_failures}" if source_failures else "all scoped",
        )
    )
    _ = include_vector_checks
    return {
        "checks": checks,
        "metrics": metrics,
        "content_metrics": content_metrics,
        "case_results": case_results,
        "thresholds": thresholds,
    }


def run_validation(
    settings: Settings | None = None,
    *,
    fixture_path: Path | None = None,
    include_vector_checks: bool = True,
    log_progress: bool = False,
) -> dict[str, Any]:
    settings = settings or get_settings()
    started = time.perf_counter()
    checks: list[Check] = []
    checks.extend(check_dataset_inputs(settings))
    checks.extend(check_chunk_quality(settings))
    if include_vector_checks:
        checks.extend(check_vector_store(settings))
    retrieval = check_retrieval_quality(
        settings, fixture_path=fixture_path, include_vector_checks=include_vector_checks
    )
    checks.extend(retrieval["checks"])
    metrics = retrieval["metrics"]
    threshold_metrics = {
        name: {
            "value": metrics.get(name),
            "threshold": (retrieval.get("thresholds") or DEFAULT_THRESHOLDS).get(name),
            "status": next(
                (
                    check.status
                    for check in checks
                    if check.name == f"retrieval_{name}"
                ),
                "SKIP",
            ),
        }
        for name in ("hit_at_1", "hit_at_3", "hit_at_5", "mrr")
    }
    threshold_metrics["cases"] = {"value": metrics.get("cases"), "threshold": None, "status": "INFO"}
    failed = [check for check in checks if check.status == "FAIL"]
    result = {
        "status": "PASS" if not failed else "FAIL",
        "checks": [check.as_dict() for check in checks],
        "metrics": threshold_metrics,
        "content_metrics": retrieval.get("content_metrics", {"cases": 0}),
        "case_results": retrieval.get("case_results", []),
        "elapsed_seconds": round(time.perf_counter() - started, 2),
    }
    if log_progress:
        print(
            f"validation {result['status']} ({len(failed)} failed, {len(checks)} checks, "
            f"{result['elapsed_seconds']}s)",
            flush=True,
        )
        for check in checks:
            print(f"  [{check.status}] {check.name}: {check.detail}", flush=True)
    return result


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m app.rag.validation",
        description="Validate the ManufacturaIQ hierarchical document RAG index.",
    )
    parser.add_argument("--json", action="store_true", dest="as_json")
    parser.add_argument(
        "--fixture",
        default=None,
        help="path to retrieval_cases.json (defaults to backend/tests/rag/fixtures)",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    fixture = Path(args.fixture) if args.fixture else None
    result = run_validation(fixture_path=fixture, log_progress=not args.as_json)
    if args.as_json:
        print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
