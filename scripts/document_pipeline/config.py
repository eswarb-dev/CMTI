from __future__ import annotations

from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DATASETS_ROOT = PROJECT_ROOT / "datasets"
RAW_DOCUMENT_ROOT = DATASETS_ROOT / "raw" / "documents"
STAGED_DOCUMENT_ROOT = DATASETS_ROOT / "staged" / "documents"
PAGES_DIR = STAGED_DOCUMENT_ROOT / "pages"
METADATA_DIR = STAGED_DOCUMENT_ROOT / "metadata"
DIAGNOSTICS_DIR = STAGED_DOCUMENT_ROOT / "diagnostics"
MANIFEST_PATH = DATASETS_ROOT / "manifests" / "documents.json"
REPORT_PATH = DATASETS_ROOT / "reports" / "DOCUMENT_CORPUS_REPORT.md"

RAW_DIRECTORIES = [
    RAW_DOCUMENT_ROOT / "manuals" / "cnc",
    RAW_DOCUMENT_ROOT / "manuals" / "drives",
    RAW_DOCUMENT_ROOT / "manuals" / "general",
    RAW_DOCUMENT_ROOT / "sop",
    RAW_DOCUMENT_ROOT / "safety",
]

SUPPORTED_EXTENSIONS = {".pdf", ".txt", ".md", ".docx"}

DOCUMENT_TYPES = {
    "MACHINE_MANUAL",
    "SERVICE_MANUAL",
    "MAINTENANCE_MANUAL",
    "OPERATOR_MANUAL",
    "PROGRAMMING_MANUAL",
    "DRIVE_MANUAL",
    "SOP",
    "SAFETY",
    "TECHNICAL_REFERENCE",
    "UNKNOWN",
}

