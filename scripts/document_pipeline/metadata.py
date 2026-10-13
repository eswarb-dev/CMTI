from __future__ import annotations

import re
from pathlib import Path

from .config import RAW_DOCUMENT_ROOT


def classify_document(path: Path) -> str:
    try:
        relative = path.relative_to(RAW_DOCUMENT_ROOT)
        parts = [part.lower() for part in relative.parts]
    except ValueError:
        # Synthetic/temporary corpora live outside the canonical raw root;
        # fall back to filename-only classification.
        parts = []
    name = path.stem.lower()
    text = " ".join(parts + [name])
    if "safety" in parts or "safety" in name:
        return "SAFETY"
    if "sop" in parts or "sop" in name or "procedure" in name:
        return "SOP"
    if "drive" in parts or "drive" in name or "sinamics" in name:
        return "DRIVE_MANUAL"
    if "maintenance" in name:
        return "MAINTENANCE_MANUAL"
    if "service" in name:
        return "SERVICE_MANUAL"
    if "operator" in name or "operation" in name:
        return "OPERATOR_MANUAL"
    if "programming" in name or "program" in name:
        return "PROGRAMMING_MANUAL"
    if "manual" in text and "cnc" in text:
        return "MACHINE_MANUAL"
    if "reference" in name:
        return "TECHNICAL_REFERENCE"
    return "UNKNOWN"


def refine_document_type(current_type: str, text: str | None = None, pdf_metadata: dict | None = None) -> str:
    combined = f"{text or ''}\n{(pdf_metadata or {}).get('title', '')}\n{(pdf_metadata or {}).get('subject', '')}".lower()
    if "lockout" in combined and "tagout" in combined:
        return "SAFETY"
    if "operator" in combined or "operating manual" in combined:
        return "OPERATOR_MANUAL"
    return current_type


def metadata_from_text(path: Path, first_page_text: str | None = None, pdf_metadata: dict | None = None) -> dict[str, str | None]:
    pdf_metadata = pdf_metadata or {}
    text = f"{path.stem}\n{first_page_text or ''}\n{pdf_metadata.get('title', '')}\n{pdf_metadata.get('author', '')}\n{pdf_metadata.get('subject', '')}"
    lower = text.lower()
    manufacturer = None
    machine_family = None
    model = None
    if "haas automation" in lower:
        manufacturer = "Haas Automation"
    if "siemens" in lower:
        manufacturer = "Siemens"
    if "sinumerik 828d" in lower:
        machine_family = "SINUMERIK 828D"
    elif "lathe operator" in lower:
        machine_family = "CNC Lathe"
    elif "mill operator" in lower or "milling" in lower:
        machine_family = "CNC Mill"
    revision = None
    match = re.search(r"\bRevision\s+([A-Z0-9.\-]+)\b", text, re.IGNORECASE)
    if match:
        revision = match.group(1)
    publication_date = None
    match = re.search(r"\b(20\d{2}[-/]\d{2}[-/]\d{2})\b", text)
    if match:
        publication_date = match.group(1).replace("/", "-")
    else:
        match = re.search(r"\b(0[1-9]|1[0-2])/(20\d{2})\b", text)
        if match:
            publication_date = f"{match.group(2)}-{match.group(1)}"
        else:
            month_match = re.search(
                r"\b(January|February|March|April|May|June|July|August|September|October|November|December)\s+(20\d{2})\b",
                text,
                re.IGNORECASE,
            )
            if month_match:
                publication_date = f"{month_match.group(1).title()} {month_match.group(2)}"
            else:
                revised_year = re.search(r"\b(20\d{2})\s*\(Revised\)", text, re.IGNORECASE)
                if revised_year:
                    publication_date = revised_year.group(1)
    title = pdf_metadata.get("title") or first_nonempty_line(first_page_text) or path.stem
    return {
        "manufacturer": manufacturer,
        "machine_family": machine_family,
        "model": model,
        "title": title,
        "revision": revision,
        "publication_date": publication_date,
    }


def first_nonempty_line(text: str | None) -> str | None:
    if not text:
        return None
    for line in text.splitlines():
        stripped = line.strip()
        if stripped:
            return stripped[:240]
    return None

