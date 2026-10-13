from __future__ import annotations

from collections import Counter


def classify_page_quality(character_count: int, word_count: int, image_count: int) -> tuple[str, bool]:
    if character_count == 0 and word_count == 0:
        return ("POSSIBLE_SCAN", True) if image_count > 0 else ("EMPTY", False)
    if character_count < 80 or word_count < 10:
        return ("POSSIBLE_SCAN", True) if image_count > 0 else ("SPARSE", False)
    return "GOOD", False


def repeated_header_footer(pages: list[dict]) -> tuple[dict[int, str | None], dict[int, str | None]]:
    first_lines = Counter()
    last_lines = Counter()
    page_lines: dict[int, list[str]] = {}
    for page in pages:
        lines = [line.strip() for line in page.get("text", "").splitlines() if line.strip()]
        page_lines[page["page_number"]] = lines
        if lines:
            first_lines[lines[0]] += 1
            last_lines[lines[-1]] += 1
    threshold = max(2, len(pages) // 2)
    headers: dict[int, str | None] = {}
    footers: dict[int, str | None] = {}
    for number, lines in page_lines.items():
        headers[number] = lines[0] if lines and first_lines[lines[0]] >= threshold else None
        footers[number] = lines[-1] if lines and last_lines[lines[-1]] >= threshold else None
    return headers, footers

