from __future__ import annotations

from app.contracts.evidence import Evidence, EvidenceProvenance
from app.contracts.enums import EvidenceSourceType, SourceKind


def document_evidence() -> Evidence:
    return Evidence(
        evidence_id="EV-DOC-001",
        source_type=EvidenceSourceType.MANUAL,
        provenance=EvidenceProvenance(
            source_kind=SourceKind.DOCUMENT,
            source_dataset="technical_document_corpus",
            source_id="DOC-ABCDEF123456",
            source_file="manuals/cnc/example.pdf",
            document_id="DOC-ABCDEF123456",
            page_start=120,
            page_end=120,
            section="Spindle",
        ),
        title="Spindle example",
        content="Example test content only.",
        metadata={"example": True},
    )


def structured_evidence() -> Evidence:
    return Evidence(
        evidence_id="EV-TEL-001",
        source_type=EvidenceSourceType.TELEMETRY,
        provenance=EvidenceProvenance(
            source_kind=SourceKind.DEMO_FACTORY,
            source_dataset="manufacturaiq_demo_factory",
            source_id="telemetry.parquet",
            record_id="TEL-000001",
        ),
        machine_id="CNC-05",
        product_id="SHAFT-A",
        title="Telemetry summary example",
        content="Example synthetic telemetry evidence only.",
        metadata={"window": "test"},
    )

