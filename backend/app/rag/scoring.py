from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from typing import Any, Sequence

from .vector_store import SearchHit


@dataclass(slots=True)
class RankedHit:
    hit: SearchHit
    rank: int
    score: float
    section_key: str
    lexical_score: float = 0.0
    rerank_score: float | None = None


# Minimal deterministic stopwords: generic function words only. Technical
# vocabulary (spindle, lubrication, chuck, alarm, tool, energy, lockout,
# tagout, ...) is always preserved.
LEXICAL_STOPWORDS = frozenset(
    {
        "a", "an", "the", "and", "or", "of", "to", "in", "on", "for", "with",
        "by", "from", "as", "at", "is", "are", "was", "were", "be", "been",
        "do", "does", "did", "done", "how", "what", "which", "who", "whom",
        "when", "where", "why", "i", "me", "my", "you", "your", "it", "its",
        "this", "that", "these", "those", "there", "their", "not", "no",
        "if", "then", "than", "so", "such", "only", "also", "just", "very",
        "can", "could", "should", "would", "will", "about", "into", "over",
        "after", "before", "between", "during", "while", "s",
    }
)


def normalize_lexical_text(text: Any) -> str:
    """Lowercase, de-accent and collapse whitespace for lexical matching."""

    folded = unicodedata.normalize("NFKD", str(text or "")).casefold()
    folded = "".join(char for char in folded if not unicodedata.combining(char))
    return re.sub(r"\s+", " ", folded).strip()


def lexical_query_terms(query: str) -> list[str]:
    """Deterministic query token sequence with generic stopwords removed."""

    tokens = re.findall(r"[a-z0-9]+", normalize_lexical_text(query))
    kept = [token for token in tokens if token not in LEXICAL_STOPWORDS]
    return kept or tokens


def _field_tokens(text: Any) -> set[str]:
    return set(re.findall(r"[a-z0-9]+", normalize_lexical_text(text)))


def lexical_relevance(
    query_terms: Sequence[str],
    payload: dict[str, Any],
    *,
    content_weight: float = 0.5,
    heading_weight: float = 0.3,
    phrase_weight: float = 0.2,
) -> dict[str, float]:
    """Deterministic lexical signal in [0, 1] for one candidate chunk.

    Components: query-term coverage of the chunk text, coverage of the
    title/heading text, and coverage of adjacent query-term bigrams
    (exact technical phrase match). Weights should sum to ~1.
    """

    terms = [term for term in query_terms if term]
    if not terms:
        return {
            "content_coverage": 0.0,
            "heading_coverage": 0.0,
            "phrase_coverage": 0.0,
            "lexical_score": 0.0,
        }
    content_tokens = _field_tokens(payload.get("text"))
    content_flat = normalize_lexical_text(payload.get("text"))
    heading_text = " ".join(
        [str(payload.get("title") or "")]
        + [str(item) for item in (payload.get("heading_path") or [])]
    )
    heading_tokens = _field_tokens(heading_text)
    heading_flat = normalize_lexical_text(heading_text)
    content_coverage = sum(1 for term in terms if term in content_tokens) / len(terms)
    heading_coverage = sum(1 for term in terms if term in heading_tokens) / len(terms)
    if len(terms) < 2:
        phrase_coverage = 0.0
    else:
        bigrams = [" ".join(pair) for pair in zip(terms, terms[1:])]
        phrase_coverage = sum(
            1
            for bigram in bigrams
            if bigram in content_flat or bigram in heading_flat
        ) / len(bigrams)
    lexical = (
        content_weight * content_coverage
        + heading_weight * heading_coverage
        + phrase_weight * phrase_coverage
    )
    return {
        "content_coverage": round(content_coverage, 4),
        "heading_coverage": round(heading_coverage, 4),
        "phrase_coverage": round(phrase_coverage, 4),
        "lexical_score": round(min(max(lexical, 0.0), 1.0), 4),
    }


def payload_section_key(payload: dict[str, Any]) -> str:
    existing = payload.get("section_key")
    if existing:
        return str(existing)
    document_id = str(payload.get("document_id") or "")
    heading_path = payload.get("heading_path") or []
    if not heading_path:
        return f"{document_id}::prelude"
    return f"{document_id}::{' > '.join(str(item) for item in heading_path)}"


def _page_overlap(left: dict[str, Any], right: dict[str, Any]) -> bool:
    left_start = int(left.get("page_start") or 0)
    left_end = int(left.get("page_end") or left_start)
    right_start = int(right.get("page_start") or 0)
    right_end = int(right.get("page_end") or right_start)
    return left_start <= right_end and right_start <= left_end


def rank_hits(
    hits: Sequence[SearchHit],
    *,
    top_k: int,
    max_per_section: int = 3,
    score_epsilon: float = 0.02,
    query: str = "",
    lexical_weight: float = 0.0,
    lexical_content_weight: float = 0.5,
    lexical_heading_weight: float = 0.3,
    lexical_phrase_weight: float = 0.2,
) -> list[RankedHit]:
    """Hierarchy-aware re-ranking of raw vector search results.

    Keeps the strongest chunk per overlapping region, limits near-duplicate
    chunks from the same section, then backfills up to ``top_k`` so callers
    always receive the requested number of results when available.

    With ``lexical_weight > 0`` the acceptance order blends the vector score
    with a deterministic lexical signal::

        combined = (1 - lexical_weight) * vector + lexical_weight * lexical

    ``RankedHit.score`` always remains the raw vector score; the lexical and
    combined components travel in ``lexical_score``/``rerank_score``.
    """

    use_lexical = bool(query.strip()) and lexical_weight > 0.0
    terms = lexical_query_terms(query) if use_lexical else []
    scored: list[tuple[float, SearchHit, float]] = []
    for hit in hits:
        vector_score = hit.score
        lexical = 0.0
        if use_lexical:
            lexical = lexical_relevance(
                terms,
                hit.payload,
                content_weight=lexical_content_weight,
                heading_weight=lexical_heading_weight,
                phrase_weight=lexical_phrase_weight,
            )["lexical_score"]
        combined = (
            (1.0 - lexical_weight) * vector_score + lexical_weight * lexical
            if use_lexical
            else vector_score
        )
        scored.append((combined, hit, lexical))
    # Deterministic order: combined score first, chunk id tie-break.
    scored.sort(key=lambda entry: (-entry[0], entry[1].chunk_id))
    ordered = [entry_hit for _, entry_hit, _ in scored]
    lexical_by_chunk = {entry_hit.chunk_id: entry_lex for _, entry_hit, entry_lex in scored}
    combined_by_chunk = {entry_hit.chunk_id: entry_comb for entry_comb, entry_hit, _ in scored}
    accepted: list[RankedHit] = []
    seen_content: set[str] = set()
    section_counts: dict[str, int] = {}
    section_best: dict[str, float] = {}
    deferred: list[SearchHit] = []

    for hit in ordered:
        payload = hit.payload
        section_key = payload_section_key(payload)
        content_hash = str(payload.get("content_hash") or hit.chunk_id)
        if content_hash in seen_content:
            continue
        count = section_counts.get(section_key, 0)
        best_score = section_best.get(section_key, hit.score)
        if count >= max_per_section:
            deferred.append(hit)
            continue
        duplicate = False
        for chosen in accepted:
            if chosen.section_key != section_key:
                continue
            if abs(chosen.score - hit.score) <= score_epsilon and _page_overlap(
                chosen.hit.payload, payload
            ):
                duplicate = True
                break
        if duplicate:
            continue
        seen_content.add(content_hash)
        section_counts[section_key] = count + 1
        section_best[section_key] = max(best_score, hit.score)
        accepted.append(
            RankedHit(
                hit=hit,
                rank=len(accepted) + 1,
                score=hit.score,
                section_key=section_key,
                lexical_score=lexical_by_chunk.get(hit.chunk_id, 0.0),
                rerank_score=combined_by_chunk.get(hit.chunk_id) if use_lexical else None,
            )
        )
        if len(accepted) >= top_k:
            break

    if len(accepted) < top_k:
        accepted_ids = {ranked.hit.chunk_id for ranked in accepted}
        for hit in deferred:
            if hit.chunk_id in accepted_ids:
                continue
            content_hash = str(hit.payload.get("content_hash") or hit.chunk_id)
            if content_hash in seen_content:
                continue
            seen_content.add(content_hash)
            accepted.append(
                RankedHit(
                    hit=hit,
                    rank=len(accepted) + 1,
                    score=hit.score,
                    section_key=payload_section_key(hit.payload),
                    lexical_score=lexical_by_chunk.get(hit.chunk_id, 0.0),
                    rerank_score=combined_by_chunk.get(hit.chunk_id) if use_lexical else None,
                )
            )
            if len(accepted) >= top_k:
                break

    return accepted[:top_k]
