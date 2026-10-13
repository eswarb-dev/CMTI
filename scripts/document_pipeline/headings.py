from __future__ import annotations

import re


KEYWORDS = {
    "SAFETY",
    "MAINTENANCE",
    "TROUBLESHOOTING",
    "OPERATION",
    "INSTALLATION",
    "ALARMS",
    "SERVICE",
    "DIAGNOSTICS",
}


def candidate_headings(document_id: str, page_number: int, text: str) -> list[dict]:
    headings = []
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or len(line) > 120:
            continue
        numbered = re.match(r"^(\d+(?:\.\d+){0,4})\s+(.+)$", line)
        if numbered:
            headings.append(
                {
                    "document_id": document_id,
                    "page_number": page_number,
                    "heading_text": line,
                    "heading_level_guess": numbered.group(1).count(".") + 1,
                    "detection_method": "numbered_heading",
                    "confidence_rule": "line starts with section number pattern",
                }
            )
            continue
        upper = line.upper()
        if upper in KEYWORDS or (upper == line and 4 <= len(line) <= 60 and any(ch.isalpha() for ch in line)):
            headings.append(
                {
                    "document_id": document_id,
                    "page_number": page_number,
                    "heading_text": line,
                    "heading_level_guess": 1,
                    "detection_method": "keyword_or_all_caps",
                    "confidence_rule": "short all-caps line or known section keyword",
                }
            )
    return headings

