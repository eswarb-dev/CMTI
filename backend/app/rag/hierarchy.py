from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass
from typing import Iterable, Sequence

from .models import DocumentNode, HeadingMatch, PageRecord, SectionNode

PATTERN_PURE_NUMBER = re.compile(r"^\d{1,2}(?:\.\d{1,2}){0,3}$")
PATTERN_NUMBERED = re.compile(r"^(\d{1,2}(?:\.\d{1,2}){0,3})\s+(.+)$")
PATTERN_CHAPTER = re.compile(r"^Chapter\s+(\d{1,2})\s*[:\-–]?\s*(.*)$", re.IGNORECASE)
PATTERN_PAGE_MARKER = re.compile(r"^(?:page\s*)?\d{1,5}$", re.IGNORECASE)
PATTERN_ROMAN = re.compile(r"^[ivxlcdm]{1,8}$", re.IGNORECASE)
PATTERN_DOT_LEADER = re.compile(r"(?:\.\s*){3,}|\.{4,}")
PATTERN_TRAILING_REF = re.compile(r"\s{2,}\d{1,4}$|\.{2,}\s*\d{1,4}$")
PATTERN_TRAILING_ROMAN_REF = re.compile(r"\s{2,}[ivxlcdm]{1,5}$", re.IGNORECASE)

STRUCTURAL_KEYWORDS = frozenset(    {
        "SAFETY",
        "MAINTENANCE",
        "TROUBLESHOOTING",
        "OPERATION",
        "OPERATIONS",
        "INSTALLATION",
        "ALARMS",
        "ALARM",
        "SERVICE",
        "DIAGNOSTICS",
        "INTRODUCTION",
        "REFERENCES",
        "INDEX",
        "SETUP",
        "PROGRAMMING",
        "SPECIFICATIONS",
        "DESCRIPTION",
        "GENERAL",
        "CONTENTS",
        "SUMMARY",
    }
)

NUMBERED_HEADING_METHODS = frozenset({"numbered_heading", "split_number_heading"})

CONNECTOR_LAST_WORDS = frozenset(
    {
        "a",
        "an",
        "and",
        "as",
        "at",
        "by",
        "for",
        "from",
        "in",
        "into",
        "is",
        "of",
        "on",
        "or",
        "that",
        "the",
        "to",
        "with",
        "which",
        "are",
        "be",
        "been",
        "it",
        "its",
    }
)

_ROMAN_VALUES = {"i": 1, "v": 5, "x": 10, "l": 50, "c": 100, "d": 500, "m": 1000}


@dataclass(slots=True)
class HierarchyConfig:
    """Deterministic hierarchy reconstruction settings."""

    page_marker_window: int = 3
    toc_dotted_line_min: int = 5
    toc_numbered_entry_min: int = 5
    max_heading_length: int = 110
    max_title_length: int = 70
    min_unnumbered_words: int = 3
    max_unnumbered_words: int = 12
    max_numbered_words: int = 14
    detect_unnumbered: bool = True


def normalize_heading(text: str) -> str:
    """Collapse whitespace while preserving original wording and casing."""

    return re.sub(r"\s+", " ", text).strip()


def has_dot_leader(text: str) -> bool:
    return bool(PATTERN_DOT_LEADER.search(text))


def is_page_marker(text: str) -> bool:
    stripped = text.strip()
    if not stripped:
        return False
    if PATTERN_PAGE_MARKER.match(stripped):
        return True
    if PATTERN_ROMAN.match(stripped):
        return _roman_value(stripped) <= 50
    return False


def _roman_value(text: str) -> int:
    lowered = text.lower()
    if not all(char in _ROMAN_VALUES for char in lowered):
        return 0
    total = 0
    previous = 0
    for char in reversed(lowered):
        value = _ROMAN_VALUES[char]
        if value < previous:
            total -= value
        else:
            total += value
            previous = value
    return total


def clean_page_lines(lines: Sequence[str], window: int = 3) -> list[str]:
    """Blank edge page markers so headers/footers never enter chunk text."""

    cleaned = list(lines)
    count = len(cleaned)
    for index in range(min(window, count)):
        if is_page_marker(cleaned[index]):
            cleaned[index] = ""
    for index in range(max(0, count - window), count):
        if is_page_marker(cleaned[index]):
            cleaned[index] = ""
    return cleaned


def is_toc_page(
    lines: Sequence[str],
    dotted_line_min: int = 5,
    numbered_entry_min: int = 5,
    config: HierarchyConfig | None = None,
) -> bool:
    """Detect contents pages dominated by dot leaders or numbered entries."""

    non_empty = [line.strip() for line in lines if line.strip()]
    if not non_empty:
        return False
    dotted = sum(1 for line in non_empty if has_dot_leader(line))
    if dotted >= dotted_line_min:
        return True
    if numbered_entry_min <= 0:
        return False
    settings = config or HierarchyConfig()
    entries = 0
    for position in range(len(non_empty) - 1):
        line = non_empty[position]
        if PATTERN_PURE_NUMBER.match(line) and _valid_child_title(non_empty[position + 1], settings):
            entries += 1
        elif PATTERN_NUMBERED.match(line) and PATTERN_TRAILING_REF.search(line):
            entries += 1
    return entries >= numbered_entry_min


def _next_non_empty(lines: Sequence[str], start: int) -> tuple[int, str] | None:
    for index in range(start, len(lines)):
        stripped = lines[index].strip()
        if stripped:
            return index, stripped
    return None


def _previous_non_empty(lines: Sequence[str], start: int) -> tuple[int, str] | None:
    for index in range(start - 1, -1, -1):
        stripped = lines[index].strip()
        if stripped:
            return index, stripped
    return None


def _looks_like_wrapped_sentence(title: str, following: str | None) -> bool:
    words = title.split()
    if title.endswith((".", "!", "?", ":", ";")):
        return False
    if words and words[-1].lower() in CONNECTOR_LAST_WORDS:
        return True
    if following and len(words) >= 6 and following[:1].islower() and len(following) >= 25:
        return True
    return False


def _valid_child_title(title: str, config: HierarchyConfig) -> bool:
    if not title or len(title) > config.max_title_length:
        return False
    if has_dot_leader(title) or PATTERN_TRAILING_REF.search(title):
        return False
    if not any(char.isalpha() for char in title):
        return False
    if title.endswith(".") and len(title) > 40:
        return False
    if PATTERN_PURE_NUMBER.match(title) or PATTERN_NUMBERED.match(title):
        return False
    return True


def _looks_like_unnumbered_heading(text: str, config: HierarchyConfig) -> bool:
    if not config.detect_unnumbered:
        return False
    if not (3 <= len(text) <= config.max_title_length):
        return False
    words = text.split()
    if not (config.min_unnumbered_words <= len(words) <= config.max_unnumbered_words):
        return False
    if not text[0].isalpha() or not text[0].isupper():
        return False
    if not any(char.islower() for char in text):
        return False
    if any(char.isdigit() for char in text):
        return False
    if text.endswith((".", ",", ";", ":", "-", "—", "?", "!")):
        return False
    if words[-1].lower() in CONNECTOR_LAST_WORDS:
        return False
    if has_dot_leader(text) or PATTERN_TRAILING_REF.search(text):
        return False
    return True


def detect_line_heading(
    lines: Sequence[str],
    index: int,
    page_number: int,
    config: HierarchyConfig,
) -> HeadingMatch | None:
    """Apply conservative, deterministic heading rules to a single line."""

    raw = lines[index]
    # Guards run against the raw line: trailing page references survive only
    # because whitespace normalisation would collapse the spacing that marks
    # them (e.g. "4.43 Set a Work Offset    123").
    if has_dot_leader(raw) or PATTERN_TRAILING_REF.search(raw) or PATTERN_TRAILING_ROMAN_REF.search(raw):
        return None
    text = normalize_heading(raw)
    if not text or len(text) > config.max_heading_length:
        return None

    split_match = PATTERN_PURE_NUMBER.match(text)
    if split_match:
        upcoming = _next_non_empty(lines, index + 1)
        if upcoming is None:
            return None
        next_index, title = upcoming
        if not _valid_child_title(title, config):
            return None
        level = text.count(".") + 1
        return HeadingMatch(
            level=level,
            text=normalize_heading(f"{text} {title}"),
            method="split_number_heading",
            page_number=page_number,
            line_index=index,
            consumed_lines=next_index - index,
        )

    chapter_match = PATTERN_CHAPTER.match(text)
    if chapter_match:
        trailing = normalize_heading(chapter_match.group(2) or "")
        if trailing and any(char.isalpha() for char in trailing) and len(trailing) <= config.max_title_length:
            return HeadingMatch(
                level=1,
                text=text,
                method="chapter_heading",
                page_number=page_number,
                line_index=index,
            )
        upcoming = _next_non_empty(lines, index + 1)
        consumed = 0
        heading_text = text
        if upcoming is not None:
            next_index, title = upcoming
            if _valid_child_title(title, config):
                heading_text = normalize_heading(f"{text} {title}")
                consumed = next_index - index
        return HeadingMatch(
            level=1,
            text=heading_text,
            method="chapter_heading",
            page_number=page_number,
            line_index=index,
            consumed_lines=consumed,
        )

    numbered_match = PATTERN_NUMBERED.match(text)
    if numbered_match:
        title = normalize_heading(numbered_match.group(2))
        words = title.split()
        if not words or not any(char.isalpha() for char in title):
            return None
        if len(words) > config.max_numbered_words:
            return None
        if words[0][:1].islower():
            return None
        following = _next_non_empty(lines, index + 1)
        following_text = following[1] if following else None
        if _looks_like_wrapped_sentence(title, following_text):
            return None
        level = numbered_match.group(1).count(".") + 1
        return HeadingMatch(
            level=level,
            text=text,
            method="numbered_heading",
            page_number=page_number,
            line_index=index,
        )

    if text.upper() == text and any(char.isalpha() for char in text) and text in STRUCTURAL_KEYWORDS:
        return HeadingMatch(
            level=1,
            text=text,
            method="structural_keyword_heading",
            page_number=page_number,
            line_index=index,
        )

    if _looks_like_unnumbered_heading(text, config):
        if index > 0 and lines[index - 1].strip():
            return None
        following = _next_non_empty(lines, index + 1)
        if following is None:
            return None
        return HeadingMatch(
            level=1,
            text=text,
            method="unnumbered_heading",
            page_number=page_number,
            line_index=index,
        )

    return None


def detect_page_headings(
    lines: Sequence[str],
    page_number: int,
    config: HierarchyConfig,
) -> list[HeadingMatch]:
    """Detect headings for one already-cleaned page."""

    if is_toc_page(lines, config.toc_dotted_line_min, config.toc_numbered_entry_min, config):
        return []
    matches: list[HeadingMatch] = []
    index = 0
    while index < len(lines):
        match = detect_line_heading(lines, index, page_number, config)
        if match is None:
            index += 1
            continue
        matches.append(match)
        index += 1 + max(match.consumed_lines, 0)
    return matches


@dataclass(slots=True)
class _SectionBuilder:
    document_id: str
    ordinal: int = 0
    heading_path: list[list[str]] | None = None
    level: int = 0
    text: str = ""
    spans: list[tuple[int, int, int]] = None  # type: ignore[assignment]
    page_start: int = 0
    page_end: int = 0
    method: str = "document_start"

    def __post_init__(self) -> None:
        self.heading_path = []
        self.spans = []

    def start(self, heading_path: list[str], level: int, method: str, page_number: int) -> None:
        self.heading_path = list(heading_path)
        self.level = level
        self.text = ""
        self.spans = []
        self.page_start = page_number
        self.page_end = page_number
        self.method = method

    def add_line(self, page_number: int, line: str) -> None:
        if self.text:
            start = len(self.text)
            self.text = f"{self.text}\n{line}"
            end = len(self.text)
        else:
            start = 0
            self.text = line
            end = len(line)
        self.spans.append((start, end, page_number))
        if not self.page_start:
            self.page_start = page_number
        self.page_end = page_number

    def close(self) -> SectionNode | None:
        if not self.text.strip():
            return None
        path = list(self.heading_path or [])
        section = SectionNode(
            document_id=self.document_id,
            section_ordinal=self.ordinal + 1,
            heading_path=path,
            chapter=path[0] if path else None,
            section=path[1] if len(path) > 1 else None,
            subsection=" > ".join(path[2:]) if len(path) > 2 else None,
            level=self.level,
            page_start=self.page_start or 1,
            page_end=self.page_end or self.page_start or 1,
            text=self.text,
            page_spans=list(self.spans),
            heading_method=self.method,
        )
        self.text = ""
        self.spans = []
        self.ordinal += 1
        return section


def build_document_sections(
    document: DocumentNode,
    pages: Iterable[PageRecord],
    config: HierarchyConfig,
) -> tuple[list[SectionNode], dict[str, object]]:
    """Rebuild a heading hierarchy for one document from staged page text."""

    ordered_pages = sorted(pages, key=lambda page: page.page_number)
    stack: list[tuple[int, str, str]] = []
    seen_headings: set[tuple[int, str]] = set()
    sections: list[SectionNode] = []
    builder = _SectionBuilder(document_id=document.document_id)
    builder.start([], 0, "document_start", ordered_pages[0].page_number if ordered_pages else 1)
    stats: Counter[str] = Counter()

    for page in ordered_pages:
        raw_lines = (page.text or "").splitlines()
        lines = clean_page_lines(raw_lines, config.page_marker_window)
        if not any(line.strip() for line in lines):
            continue
        if is_toc_page(lines, config.toc_dotted_line_min, config.toc_numbered_entry_min, config):
            stats["toc_pages"] += 1
            toc_page = True
        else:
            toc_page = False
        index = 0
        while index < len(lines):
            match = None if toc_page else detect_line_heading(lines, index, page.page_number, config)
            if match is None:
                stripped = lines[index].rstrip()
                if stripped:
                    builder.add_line(page.page_number, stripped)
                    stats["body_lines"] += 1
                index += 1
                continue
            key = (match.level, match.text)
            if key in seen_headings:
                stats["duplicate_header_lines"] += 1
                for offset in range(1 + max(match.consumed_lines, 0)):
                    if index + offset < len(lines) and lines[index + offset].strip():
                        stats["suppressed_lines"] += 1
                    if index + offset < len(lines):
                        lines[index + offset] = ""
                index += 1 + max(match.consumed_lines, 0)
                continue
            seen_headings.add(key)
            stats[f"headings:{match.method}"] += 1
            while stack and stack[-1][0] >= match.level:
                stack.pop()
            if (
                match.level >= 2
                and match.method in NUMBERED_HEADING_METHODS
                and stack
                and stack[-1][2] == "unnumbered_heading"
            ):
                stats["stale_parents_popped"] += 1
                stack.pop()
            stack.append((match.level, match.text, match.method))
            closed = builder.close()
            if closed is not None:
                sections.append(closed)
            builder.start([title for _, title, _ in stack], match.level, match.method, page.page_number)
            builder.add_line(page.page_number, match.text)
            stats["heading_lines"] += 1
            index += 1 + max(match.consumed_lines, 0)

    final = builder.close()
    if final is not None:
        sections.append(final)
    stats["sections"] = len(sections)
    return sections, dict(stats)
