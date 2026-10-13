from __future__ import annotations

from app.rag.hierarchy import (
    HierarchyConfig,
    build_document_sections,
    clean_page_lines,
    detect_line_heading,
    detect_page_headings,
    is_page_marker,
    is_toc_page,
    normalize_heading,
)
from app.rag.models import DocumentNode, PageRecord

CONFIG = HierarchyConfig()


def make_document(document_id: str = "DOC-TEST") -> DocumentNode:
    return DocumentNode(
        document_id=document_id,
        filename="test.pdf",
        relative_path="datasets/raw/test.pdf",
        document_type="OPERATOR_MANUAL",
        manufacturer="ACME",
        title="Test Manual",
        language="English",
    )


def make_page(page_number: int, text: str) -> PageRecord:
    return PageRecord(
        document_id="DOC-TEST", page_number=page_number, text=text, page_quality="GOOD"
    )


def test_edge_page_markers_are_blank_but_inner_markers_survive() -> None:
    lines = ["12", "First body line", "42", "Second body line", "13"]
    cleaned = clean_page_lines(lines, window=2)

    assert cleaned[0] == ""
    assert cleaned[4] == ""
    assert cleaned[2] == "42"
    assert cleaned[1] == "First body line"


def test_page_marker_recognises_digits_and_small_roman_numerals_only() -> None:
    assert is_page_marker("104")
    assert is_page_marker("xiv")
    assert not is_page_marker("mmxx")
    assert not is_page_marker("Chapter 5")
    assert not is_page_marker("")


def test_toc_pages_are_detected_and_produce_no_headings() -> None:
    toc_lines = [
        "1. Introduction .............. 3",
        "2. Safety .................... 7",
        "3. Operation ................. 15",
        "4. Maintenance ............... 41",
        "5. Troubleshooting ........... 63",
        "6. Specifications ............ 87",
    ]
    assert is_toc_page(toc_lines)
    assert detect_page_headings(toc_lines, 5, CONFIG) == []

    body_lines = [
        "1. Introduction .............. 3",
        "2. Safety .................... 7",
        "3. Operation ................. 15",
    ]
    assert not is_toc_page(body_lines)


def test_numbered_and_chapter_headings_are_detected_with_levels() -> None:
    chapter = detect_line_heading(["Chapter 3: Safety Systems"], 0, 3, CONFIG)
    assert chapter is not None
    assert chapter.level == 1
    assert chapter.method == "chapter_heading"
    assert chapter.text == "Chapter 3: Safety Systems"

    split_chapter = detect_line_heading(["Chapter 3", "Safety Systems"], 0, 3, CONFIG)
    assert split_chapter is not None
    assert split_chapter.method == "chapter_heading"
    assert split_chapter.text == "Chapter 3 Safety Systems"
    assert split_chapter.consumed_lines == 1

    section = detect_line_heading(["4.11 Chuck Removal"], 0, 9, CONFIG)
    assert section is not None
    assert section.level == 2
    assert section.method == "numbered_heading"
    assert section.text == "4.11 Chuck Removal"

    subsection = detect_line_heading(["7.1.1 G00 Rapid Motion"], 0, 12, CONFIG)
    assert subsection is not None
    assert subsection.level == 3
    assert subsection.text == "7.1.1 G00 Rapid Motion"


def test_split_number_heading_merges_number_with_next_line_title() -> None:
    lines = ["6.2", "Starting and stopping a spindle manually"]
    match = detect_line_heading(lines, 0, 4, CONFIG)

    assert match is not None
    assert match.method == "split_number_heading"
    assert match.level == 2
    assert match.text == "6.2 Starting and stopping a spindle manually"
    assert match.consumed_lines == 1


def test_structural_keyword_heading_detected_only_for_exact_keyword() -> None:
    keyword = detect_line_heading(["SAFETY"], 0, 1, CONFIG)
    assert keyword is not None
    assert keyword.level == 1
    assert keyword.method == "structural_keyword_heading"

    assert detect_line_heading(["SAFETY IS IMPORTANT"], 0, 1, CONFIG) is None


def test_unnumbered_heading_requires_a_preceding_blank_line() -> None:
    eligible = ["", "Operator Safety Procedures", "This section explains the rules."]
    heading = detect_line_heading(eligible, 1, 1, CONFIG)
    assert heading is not None
    assert heading.method == "unnumbered_heading"
    assert heading.level == 1
    assert heading.text == "Operator Safety Procedures"

    attached = ["Body text that precedes it.", "Operator Safety Procedures", "More body text."]
    assert detect_line_heading(attached, 1, 1, CONFIG) is None


def test_wrapped_lines_and_trailing_references_are_rejected() -> None:
    trailing_ref = ["3.1 Safety Regulations   42"]
    assert detect_line_heading(trailing_ref, 0, 1, CONFIG) is None

    connector = ["2. Preparation and", "more text follows here"]
    assert detect_line_heading(connector, 0, 1, CONFIG) is None

    long_trailing = [
        "4.5 Check That the machine coolant level is verified daily",
        "and then restart the machine before resuming production work",
    ]
    assert detect_line_heading(long_trailing, 0, 1, CONFIG) is None


def test_duplicate_running_header_is_removed_from_body() -> None:
    document = make_document()
    pages = [
        make_page(1, "SAFETY\nAlways wear eye protection."),
        make_page(2, "SAFETY\nKeep guards in place while milling."),
    ]

    sections, stats = build_document_sections(document, pages, CONFIG)

    assert stats["duplicate_header_lines"] == 1
    assert len(sections) == 1
    assert sections[0].heading_path == ["SAFETY"]
    assert "Keep guards in place while milling." in sections[0].text


def test_stale_unnumbered_parent_is_popped_for_numbered_child() -> None:
    document = make_document()
    pages = [
        make_page(
            1,
            "\n".join(
                [
                    "",
                    "General Machine Information",
                    "Read this section before operating the machine.",
                    "4.11 Chuck Removal",
                    "Remove the chuck before mounting a new workpiece.",
                ]
            ),
        )
    ]

    sections, stats = build_document_sections(document, pages, CONFIG)

    assert stats["stale_parents_popped"] == 1
    assert sections[0].heading_path == ["General Machine Information"]
    assert sections[1].heading_path == ["4.11 Chuck Removal"]
    assert sections[1].level == 2


def test_section_hierarchy_fields_and_page_ranges_are_reconstructed() -> None:
    document = make_document()
    pages = [
        make_page(1, "Chapter 1: Safety\nAlways wear eye protection when the spindle runs."),
        make_page(2, "1.1 Personal Protective Equipment\nWear safety glasses at all times."),
    ]

    sections, stats = build_document_sections(document, pages, CONFIG)

    assert stats["sections"] == 2
    chapter = sections[0]
    assert chapter.heading_path == ["Chapter 1: Safety"]
    assert chapter.chapter == "Chapter 1: Safety"
    assert chapter.page_start == 1 and chapter.page_end == 1

    child = sections[1]
    assert child.heading_path == ["Chapter 1: Safety", "1.1 Personal Protective Equipment"]
    assert child.chapter == "Chapter 1: Safety"
    assert child.section == "1.1 Personal Protective Equipment"
    assert child.subsection is None
    assert child.level == 2
    assert child.page_start == 2 and child.page_end == 2
    assert child.section_key.startswith("DOC-TEST::Chapter 1: Safety")


def test_heading_text_is_preserved_verbatim_after_whitespace_normalisation() -> None:
    assert normalize_heading("  4.11   Chuck   Removal  ") == "4.11 Chuck Removal"

    lines = ["  4.11   Chuck   Removal  "]
    match = detect_line_heading(lines, 0, 1, CONFIG)
    assert match is not None
    assert match.text == "4.11 Chuck Removal"
