"""Deterministic evidence fusion: validates, dedupes, orders, and detects conflicts."""

from __future__ import annotations

import hashlib
import logging
from typing import Any

from app.contracts.agents import AgentResult
from app.contracts.enums import AgentName, EvidenceSourceType, RiskLevel
from app.contracts.evidence import Evidence
from app.contracts.fusion import EvidenceBundle, EvidenceConflict
from app.contracts.query import QueryRequest
from app.protocols.fusion import EvidenceFusionService

__all__ = [
    "DeterministicEvidenceFusionService",
    "build_evidence_fusion_service",
]

logger = logging.getLogger(__name__)

_CANONICAL_AGENT_ORDER: tuple[AgentName, ...] = (
    AgentName.DOCUMENT,
    AgentName.MAINTENANCE,
    AgentName.QUALITY,
    AgentName.PRODUCTION,
)

_CONFLICT_SCHEMA = "source_integrity_conflict_v1"


def _stable_digest(*parts: str, length: int = 12) -> str:
    joined = "|".join(parts)
    return hashlib.sha256(joined.encode("utf-8")).hexdigest()[:length]


def _agent_sort_key(agent_name: AgentName) -> tuple[int, str]:
    try:
        idx = _CANONICAL_AGENT_ORDER.index(agent_name)
    except ValueError:
        idx = len(_CANONICAL_AGENT_ORDER)
    return (idx, agent_name.value)


def _provenance_identity(evidence: Evidence) -> str:
    p = evidence.provenance
    parts = [
        p.source_kind.value,
        p.source_dataset,
        p.source_id,
        p.record_id or "",
        p.document_id or "",
        p.chunk_id or "",
        str(p.page_start) if p.page_start is not None else "",
        str(p.page_end) if p.page_end is not None else "",
    ]
    return _stable_digest(*parts)


def _evidence_stable_payload(evidence: Evidence) -> str:
    return _stable_digest(
        evidence.evidence_id,
        evidence.source_type.value,
        evidence.title,
        evidence.content,
        evidence.machine_id or "",
        evidence.product_id or "",
        evidence.batch_id or "",
        evidence.observed_at.isoformat() if evidence.observed_at else "",
        str(evidence.retrieval_score) if evidence.retrieval_score is not None else "",
        str(evidence.decision_score) if evidence.decision_score is not None else "",
        _provenance_identity(evidence),
        str(sorted(evidence.metadata.items())),
    )


def _identity_fields_differ(a: Evidence, b: Evidence) -> bool:
    pa, pb = a.provenance, b.provenance
    if pa.source_kind != pb.source_kind:
        return True
    if pa.source_dataset != pb.source_dataset:
        return True
    if pa.source_id != pb.source_id:
        return True
    if pa.record_id != pb.record_id:
        return True
    if pa.document_id != pb.document_id:
        return True
    if pa.chunk_id != pb.chunk_id:
        return True
    if pa.page_start != pb.page_start:
        return True
    if pa.page_end != pb.page_end:
        return True
    return False


def _factual_fields_differ(a: Evidence, b: Evidence) -> bool:
    return (
        a.title != b.title
        or a.content != b.content
        or a.machine_id != b.machine_id
        or a.product_id != b.product_id
        or a.batch_id != b.batch_id
        or a.observed_at != b.observed_at
    )


class DeterministicEvidenceFusionService:
    """Deterministic evidence fusion implementing the frozen EvidenceFusionService protocol."""

    async def fuse(
        self,
        query: QueryRequest,
        agent_results: list[AgentResult],
    ) -> EvidenceBundle:
        query_id = query.query_id
        seen_ids: set[str] = set()
        seen_provenance: dict[str, str] = {}
        fused_evidence: list[Evidence] = []
        conflicts: list[EvidenceConflict] = []
        warnings: list[str] = []
        total_input = 0
        agents_with_errors: list[str] = []
        agents_with_warnings: list[str] = []

        ordered_results = sorted(agent_results, key=lambda r: _agent_sort_key(r.agent_name))

        for result in ordered_results:
            if result.query_id != query_id:
                raise ValueError(
                    f"AgentResult query_id mismatch: expected {query_id!r}, got {result.query_id!r}"
                )
            agent_name = result.agent_name.value
            if result.errors:
                agents_with_errors.append(agent_name)
                warnings.append(f"{agent_name} reported errors: {'; '.join(result.errors[:3])}")
            if result.warnings:
                agents_with_warnings.append(agent_name)
                warnings.append(f"{agent_name} reported warnings: {'; '.join(result.warnings[:3])}")

            for ev in result.evidence:
                total_input += 1
                ev_id = ev.evidence_id

                if ev_id in seen_ids:
                    existing = next(e for e in fused_evidence if e.evidence_id == ev_id)
                    if _evidence_stable_payload(existing) != _evidence_stable_payload(ev):
                        conflicts.append(self._make_conflict(existing, ev))
                    continue

                prov_id = _provenance_identity(ev)
                if prov_id in seen_provenance:
                    existing = next(
                        e for e in fused_evidence
                        if _provenance_identity(e) == prov_id
                    )
                    if _evidence_stable_payload(existing) != _evidence_stable_payload(ev):
                        conflicts.append(self._make_conflict(existing, ev))
                        continue

                seen_ids.add(ev_id)
                seen_provenance[prov_id] = ev_id
                fused_evidence.append(ev)

        by_agent: dict[str, int] = {}
        by_source: dict[str, int] = {}
        for ev in fused_evidence:
            agent_key = ev.source_type.value
            by_source[agent_key] = by_source.get(agent_key, 0) + 1

        for result in ordered_results:
            count = len(result.evidence)
            by_agent[result.agent_name.value] = by_agent.get(result.agent_name.value, 0) + count

        conflicts.sort(key=lambda c: (c.conflict_id, tuple(c.evidence_ids)))

        metadata: dict[str, Any] = {
            "agent_result_count": len(agent_results),
            "evidence_input_count": total_input,
            "evidence_output_count": len(fused_evidence),
            "duplicate_count": total_input - len(fused_evidence),
            "conflict_count": len(conflicts),
            "evidence_count_by_agent": dict(sorted(by_agent.items())),
            "evidence_count_by_source_type": dict(sorted(by_source.items())),
            "agents_with_errors": agents_with_errors,
            "agents_with_warnings": agents_with_warnings,
        }

        return EvidenceBundle(
            query_id=query_id,
            evidence=fused_evidence,
            conflicts=conflicts,
            missing_information=[],
            warnings=warnings,
            metadata=metadata,
        )

    @staticmethod
    def _make_conflict(a: Evidence, b: Evidence) -> EvidenceConflict:
        identity_fields_differ = _identity_fields_differ(a, b)
        factual_differ = _factual_fields_differ(a, b)
        if identity_fields_differ:
            conflict_type = "source_identity_mismatch"
            description = (
                "Same evidence_id maps to contradictory source identity fields."
            )
        elif factual_differ:
            conflict_type = "factual_payload_mismatch"
            description = (
                "Same source identity has incompatible factual fields."
            )
        else:
            conflict_type = "duplicate_payload_mismatch"
            description = (
                "Same evidence_id has differing stable payload."
            )
        digest = _stable_digest(
            conflict_type,
            a.evidence_id,
            b.evidence_id,
            _CONFLICT_SCHEMA,
        )
        return EvidenceConflict(
            conflict_id=f"CONFLICT-{digest}",
            evidence_ids=sorted({a.evidence_id, b.evidence_id}),
            conflict_type=conflict_type,
            description=description,
            severity=RiskLevel.MEDIUM,
            resolved=False,
            resolution_note=None,
        )


def build_evidence_fusion_service() -> DeterministicEvidenceFusionService:
    """Construct a DeterministicEvidenceFusionService."""
    return DeterministicEvidenceFusionService()
