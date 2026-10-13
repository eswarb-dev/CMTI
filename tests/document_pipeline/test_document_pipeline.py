from __future__ import annotations

import json
import sys
from pathlib import Path

import polars as pl
import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))

from scripts.document_pipeline.diagnostics import classify_page_quality
from scripts.document_pipeline.headings import candidate_headings
from scripts.document_pipeline.metadata import metadata_from_text, refine_document_type
from scripts.document_pipeline.provenance import document_id_for_hash, sha256_file
from scripts.document_pipeline.run import extract, require_pdf_backend
from scripts.document_pipeline.validators import validate_corpus

# NOTE: integration tests below must NEVER touch canonical STEP 03 paths.
# All extraction/validation output is redirected into pytest tmp_path.
# A session guard in conftest.py additionally fails the suite if any canonical
# STEP 03 artifact hash changes.


def test_stable_document_id_generation() -> None:
    sha = "7f84d2a19c31abcdef"
    assert document_id_for_hash(sha) == "DOC-7F84D2A19C31"
    assert document_id_for_hash(sha) == document_id_for_hash(sha)


def test_sha256_stability(tmp_path: Path) -> None:
    path = tmp_path / "sample.txt"
    path.write_text("stable bytes", encoding="utf-8")
    assert sha256_file(path) == sha256_file(path)


def test_candidate_heading_detection() -> None:
    headings = candidate_headings("DOC-TEST", 1, "1.2 Maintenance\nbody\nSAFETY\nnormal line")
    texts = {item["heading_text"] for item in headings}
    assert "1.2 Maintenance" in texts
    assert "SAFETY" in texts


def test_sparse_page_classification() -> None:
    assert classify_page_quality(0, 0, 0) == ("EMPTY", False)
    assert classify_page_quality(20, 3, 0) == ("SPARSE", False)
    assert classify_page_quality(20, 3, 2) == ("POSSIBLE_SCAN", True)
    assert classify_page_quality(500, 80, 0) == ("GOOD", False)


def isolated_outputs(tmp_path: Path) -> dict[str, Path]:
    raw = tmp_path / "raw"
    staged = tmp_path / "staged" / "documents"
    raw.mkdir(parents=True, exist_ok=True)
    return {
        "raw_root": raw,
        "staged_root": staged,
        "manifest_path": tmp_path / "manifests" / "documents.json",
        "report_path": tmp_path / "reports" / "DOCUMENT_CORPUS_REPORT.md",
        "pages_path": staged / "pages" / "document_pages.parquet",
        "metadata_path": staged / "metadata" / "document_metadata.parquet",
        "headings_path": staged / "metadata" / "candidate_headings.parquet",
    }


def write_tmp_text_corpus(raw: Path) -> list[Path]:
    first = raw / "safety_notice.txt"
    first.write_text(
        "SAFETY NOTICE\n\nLockout and tagout procedures protect operators from "
        "hazardous energy during maintenance. Always isolate energy sources "
        "before servicing the machine. Verify isolation with a test start.\n",
        encoding="utf-8",
    )
    second = raw / "operator_notes.txt"
    second.write_text(
        "OPERATOR NOTES\n\nCheck coolant level before each shift. Report unusual "
        "vibration to the supervisor. Keep the work area clean and dry.\n",
        encoding="utf-8",
    )
    return [first, second]


def test_empty_document_handling_creates_artifacts(tmp_path: Path) -> None:
    outputs = isolated_outputs(tmp_path)

    result = extract(
        raw_root=outputs["raw_root"],
        staged_root=outputs["staged_root"],
        manifest_path=outputs["manifest_path"],
        report_path=outputs["report_path"],
    )

    assert result == {"status": "DOCUMENT CORPUS EMPTY", "documents": 0}
    assert outputs["manifest_path"].is_file()
    assert outputs["pages_path"].is_file()
    assert outputs["metadata_path"].is_file()
    assert outputs["headings_path"].is_file()
    assert outputs["report_path"].is_file()
    assert json.loads(outputs["manifest_path"].read_text(encoding="utf-8")) == []


def test_extract_and_validate_small_tmp_corpus(tmp_path: Path) -> None:
    outputs = isolated_outputs(tmp_path)
    write_tmp_text_corpus(outputs["raw_root"])

    result = extract(
        raw_root=outputs["raw_root"],
        staged_root=outputs["staged_root"],
        manifest_path=outputs["manifest_path"],
        report_path=outputs["report_path"],
    )

    assert result["status"] == "extracted"
    assert result["documents"] == 2
    assert result["pages"] == 2

    validation = validate_corpus(
        raw_root=outputs["raw_root"],
        staged_root=outputs["staged_root"],
        manifest_path=outputs["manifest_path"],
    )
    assert validation["status"] == "passed"
    assert validation["documents"] == 2
    assert validation["pages"] == 2

    manifest = json.loads(outputs["manifest_path"].read_text(encoding="utf-8"))
    assert isinstance(manifest, list)
    assert len(manifest) == 2
    assert {item["extraction_status"] for item in manifest} == {"extracted"}


def test_page_ordering_and_provenance_schema(tmp_path: Path) -> None:
    outputs = isolated_outputs(tmp_path)
    write_tmp_text_corpus(outputs["raw_root"])
    extract(
        raw_root=outputs["raw_root"],
        staged_root=outputs["staged_root"],
        manifest_path=outputs["manifest_path"],
        report_path=outputs["report_path"],
    )

    pages = pl.read_parquet(outputs["pages_path"])
    expected = {"document_id", "filename", "page_number", "text", "source_relative_path"}
    assert expected <= set(pages.columns)
    for document_id in pages["document_id"].unique().to_list():
        numbers = pages.filter(pl.col("document_id") == document_id).sort("page_number")["page_number"].to_list()
        assert numbers == list(range(1, len(numbers) + 1))


def test_no_modification_of_source_files(tmp_path: Path) -> None:
    outputs = isolated_outputs(tmp_path)
    sources = write_tmp_text_corpus(outputs["raw_root"])
    before = {path.name: sha256_file(path) for path in sources}

    extract(
        raw_root=outputs["raw_root"],
        staged_root=outputs["staged_root"],
        manifest_path=outputs["manifest_path"],
        report_path=outputs["report_path"],
    )
    manifest = json.loads(outputs["manifest_path"].read_text(encoding="utf-8"))
    assert len(manifest) == len(sources)
    for path in sources:
        assert sha256_file(path) == before[path.name]
    for item in manifest:
        source = outputs["raw_root"] / item["relative_path"]
        assert source.is_file()
        assert sha256_file(source) == item["sha256"]


def test_pdf_backend_requirement_fails_before_any_write(tmp_path: Path, monkeypatch) -> None:
    outputs = isolated_outputs(tmp_path)
    (outputs["raw_root"] / "manual.pdf").write_bytes(b"%PDF-1.4 synthetic")
    monkeypatch.setitem(sys.modules, "fitz", None)

    with pytest.raises(RuntimeError, match="PyMuPDF"):
        require_pdf_backend([{"filename": "manual.pdf"}])

    with pytest.raises(RuntimeError, match="PyMuPDF"):
        extract(
            raw_root=outputs["raw_root"],
            staged_root=outputs["staged_root"],
            manifest_path=outputs["manifest_path"],
            report_path=outputs["report_path"],
        )
    assert not outputs["manifest_path"].exists()
    assert not outputs["pages_path"].exists()


def test_small_pdf_extraction_when_backend_available(tmp_path: Path) -> None:
    fitz = pytest.importorskip("fitz")
    outputs = isolated_outputs(tmp_path)
    pdf_path = outputs["raw_root"] / "tiny_manual.pdf"
    document = fitz.open()
    for text in ("Tiny manual page one.", "Tiny manual page two."):
        page = document.new_page()
        page.insert_text((72, 72), text)
    document.save(pdf_path)
    document.close()

    result = extract(
        raw_root=outputs["raw_root"],
        staged_root=outputs["staged_root"],
        manifest_path=outputs["manifest_path"],
        report_path=outputs["report_path"],
    )
    assert result["status"] == "extracted"
    assert result["pages"] == 2

    validation = validate_corpus(
        raw_root=outputs["raw_root"],
        staged_root=outputs["staged_root"],
        manifest_path=outputs["manifest_path"],
    )
    assert validation["status"] == "passed"
    assert validation["pages"] == 2


def test_duplicate_file_detection_by_hash(tmp_path: Path) -> None:
    a = tmp_path / "a.pdf"
    b = tmp_path / "b.pdf"
    a.write_bytes(b"same")
    b.write_bytes(b"same")
    assert sha256_file(a) == sha256_file(b)
    assert document_id_for_hash(sha256_file(a)) == document_id_for_hash(sha256_file(b))


def test_pdf_metadata_refinement_from_source_text() -> None:
    haas = metadata_from_text(Path("mill_operator_manual.pdf"), "Haas Automation Inc.\nMill Operator's Manual\nRevision V\nDecember 2025")
    assert haas["manufacturer"] == "Haas Automation"
    assert haas["machine_family"] == "CNC Mill"
    assert haas["revision"] == "V"
    assert haas["publication_date"] == "December 2025"
    siemens = metadata_from_text(
        Path("828D_milling_op_man_0721_en-US.pdf"),
        "SINUMERIK 828D\nMilling\nOperating Manual\n07/2021",
        {"author": "Siemens AG", "subject": "SINUMERIK 828D", "title": "Milling"},
    )
    assert siemens["manufacturer"] == "Siemens"
    assert siemens["machine_family"] == "SINUMERIK 828D"
    assert siemens["publication_date"] == "2021-07"
    assert refine_document_type("MACHINE_MANUAL", "Operating Manual", {"title": "Milling"}) == "OPERATOR_MANUAL"
