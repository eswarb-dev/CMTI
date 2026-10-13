from __future__ import annotations

from app.rag.scoring import (
    lexical_query_terms,
    lexical_relevance,
    payload_section_key,
    rank_hits,
)
from app.rag.vector_store import SearchHit


def hit(chunk_id: str, score: float, **payload) -> SearchHit:
    base = {
        "chunk_id": chunk_id,
        "content_hash": f"hash-{chunk_id}",
        "document_id": "DOC-TEST",
        "heading_path": ["Chapter 1"],
        "page_start": 1,
        "page_end": 1,
    }
    base.update(payload)
    return SearchHit(chunk_id=chunk_id, score=score, payload=base)


def test_payload_section_key_prefers_explicit_key_then_heading_path() -> None:
    assert payload_section_key({"section_key": "DOC-TEST::Chapter 1"}) == "DOC-TEST::Chapter 1"
    assert payload_section_key({"document_id": "D", "heading_path": ["A", "B"]}) == "D::A > B"
    assert payload_section_key({"document_id": "D", "heading_path": []}) == "D::prelude"


def test_rank_hits_orders_by_score_then_chunk_id() -> None:
    hits = [
        hit("CHUNK-B", 0.80),
        hit("CHUNK-A", 0.90),
        hit("CHUNK-C", 0.85),
    ]

    ranked = rank_hits(hits, top_k=3)

    assert [item.hit.chunk_id for item in ranked] == ["CHUNK-A", "CHUNK-C", "CHUNK-B"]
    assert [item.rank for item in ranked] == [1, 2, 3]
    assert ranked[0].score == 0.90


def test_rank_hits_drops_duplicate_content_hashes() -> None:
    hits = [
        hit("CHUNK-A", 0.90),
        hit("CHUNK-B", 0.80, content_hash="hash-CHUNK-A"),
        hit("CHUNK-C", 0.70),
    ]

    ranked = rank_hits(hits, top_k=3)

    assert [item.hit.chunk_id for item in ranked] == ["CHUNK-A", "CHUNK-C"]


def test_rank_hits_limits_chunks_per_section_then_backfills() -> None:
    same_section = [
        hit(f"CHUNK-{index}", 0.90 - index * 0.05) for index in range(4)
    ]

    capped = rank_hits(same_section, top_k=3, max_per_section=3)
    assert len(capped) == 3
    assert all(item.section_key == "DOC-TEST::Chapter 1" for item in capped)

    backfilled = rank_hits(same_section, top_k=4, max_per_section=3)
    assert len(backfilled) == 4
    assert backfilled[-1].hit.chunk_id == "CHUNK-3"


def test_rank_hits_suppresses_overlapping_near_duplicates_in_a_section() -> None:
    hits = [
        hit("CHUNK-A", 0.80, page_start=3, page_end=5),
        hit("CHUNK-B", 0.795, page_start=4, page_end=6),
        hit("CHUNK-C", 0.70, page_start=9, page_end=11),
    ]

    ranked = rank_hits(hits, top_k=2, max_per_section=3)

    assert [item.hit.chunk_id for item in ranked] == ["CHUNK-A", "CHUNK-C"]


def test_rank_hits_keeps_similar_scoring_from_different_sections() -> None:
    hits = [
        hit("CHUNK-A", 0.80, page_start=1, page_end=2),
        hit(
            "CHUNK-B",
            0.795,
            page_start=1,
            page_end=2,
            heading_path=["Chapter 2"],
            section_key="DOC-TEST::Chapter 2",
        ),
    ]

    ranked = rank_hits(hits, top_k=2)

    assert [item.hit.chunk_id for item in ranked] == ["CHUNK-A", "CHUNK-B"]


def test_rank_hits_backfills_after_section_caps_for_diverse_results() -> None:
    hits = [hit(f"CHUNK-{index}", 0.90 - index * 0.01) for index in range(5)]

    ranked = rank_hits(hits, top_k=5, max_per_section=1)

    assert len(ranked) == 5
    assert [item.rank for item in ranked] == [1, 2, 3, 4, 5]


def test_rank_hits_returns_at_most_top_k() -> None:
    hits = [hit(f"CHUNK-{index}", 0.90 - index * 0.01) for index in range(6)]

    assert len(rank_hits(hits, top_k=2)) == 2
    assert rank_hits([], top_k=5) == []


def test_lexical_query_terms_drop_stopwords_but_keep_technical_terms() -> None:
    terms = lexical_query_terms("How do I lubricate the spindle?")

    assert terms == ["lubricate", "spindle"]
    assert "the" not in terms
    assert lexical_query_terms("SINUMERIK tool management") == ["sinumerik", "tool", "management"]
    assert lexical_query_terms("G00 rapid motion") == ["g00", "rapid", "motion"]


def test_lexical_relevance_scores_content_heading_and_phrase() -> None:
    payload = {
        "text": "Open the tool management lists to edit tool data for the magazine.",
        "title": "Milling",
        "heading_path": ["14.1 Lists for the tool management"],
    }
    components = lexical_relevance(["sinumerik", "tool", "management"], payload)

    assert components["content_coverage"] == round(2 / 3, 4)
    assert components["heading_coverage"] == round(2 / 3, 4)
    assert components["phrase_coverage"] == 0.5
    assert 0.0 <= components["lexical_score"] <= 1.0

    empty = lexical_relevance([], payload)
    assert empty["lexical_score"] == 0.0


def test_rank_hits_without_query_keeps_pure_vector_order() -> None:
    hits = [
        hit("CHUNK-A", 0.80, text="unrelated body"),
        hit(
            "CHUNK-B",
            0.79,
            text="tool management magazine lists",
            heading_path=["Chapter 2"],
            section_key="DOC-TEST::Chapter 2",
            page_start=9,
            page_end=11,
        ),
    ]

    ranked = rank_hits(hits, top_k=2, query="tool management", lexical_weight=0.0)

    assert [item.hit.chunk_id for item in ranked] == ["CHUNK-A", "CHUNK-B"]
    assert all(item.lexical_score == 0.0 for item in ranked)
    assert all(item.rerank_score is None for item in ranked)
    assert [item.score for item in ranked] == [0.80, 0.79]


def test_rank_hits_lexical_blend_promotes_phrase_match_but_keeps_vector_score() -> None:
    hits = [
        hit("CHUNK-A", 0.81, text="general product overview of the control system"),
        hit(
            "CHUNK-B",
            0.79,
            text="open the tool management lists to edit tool data",
            title="Milling",
            heading_path=["14.1 Lists for the tool management"],
        ),
    ]

    ranked = rank_hits(hits, top_k=2, query="tool management", lexical_weight=0.5)

    assert [item.hit.chunk_id for item in ranked] == ["CHUNK-B", "CHUNK-A"]
    # Policy: score stays the raw vector similarity; blend lives in metadata.
    assert ranked[0].score == 0.79
    assert ranked[0].lexical_score > ranked[1].lexical_score
    assert ranked[0].rerank_score is not None
    assert ranked[0].rerank_score > ranked[1].rerank_score


def test_rank_hits_lexical_order_is_deterministic() -> None:
    hits = [
        hit("CHUNK-A", 0.81, text="general product overview"),
        hit("CHUNK-B", 0.79, text="tool management lists and magazine"),
    ]
    first = rank_hits(hits, top_k=2, query="tool management", lexical_weight=0.1)
    second = rank_hits(hits, top_k=2, query="tool management", lexical_weight=0.1)

    assert [item.hit.chunk_id for item in first] == [item.hit.chunk_id for item in second]
