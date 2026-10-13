from __future__ import annotations

from app.contracts.query import QueryRequest
from app.rag.retrieval import merge_comparison_hits, split_comparison_query
from app.rag.scoring import RankedHit
from app.rag.vector_store import SearchHit


def make_query(text: str) -> QueryRequest:
    return QueryRequest(query_id="Q-COMP", query=text)


def ranked(chunk_id: str, score: float) -> RankedHit:
    return RankedHit(
        hit=SearchHit(chunk_id=chunk_id, score=score, payload={"chunk_id": chunk_id, "text": chunk_id}),
        rank=1,
        score=score,
        section_key=chunk_id,
        lexical_score=0.0,
        rerank_score=score,
    )


def test_comparison_detector_extracts_supported_forms() -> None:
    assert split_comparison_query("Compare Haas Safe Run with SINUMERIK collision avoidance.") == (
        "Haas Safe Run",
        "SINUMERIK collision avoidance",
    )
    assert split_comparison_query("Compare alpha and beta") == ("alpha", "beta")
    assert split_comparison_query("alpha vs beta") == ("alpha", "beta")
    assert split_comparison_query("difference between alpha and beta") == ("alpha", "beta")
    assert split_comparison_query("spindle warm-up procedure") is None


def test_comparison_merge_preserves_both_sides_before_filling_by_score() -> None:
    merged = merge_comparison_hits(
        [ranked("left-1", 0.90), ranked("left-2", 0.89), ranked("left-3", 0.88)],
        [ranked("right-1", 0.70), ranked("right-2", 0.69)],
        top_k=4,
    )
    assert [item.hit.chunk_id for item in merged][:2] == ["left-1", "right-1"]
    assert "left-2" in [item.hit.chunk_id for item in merged]


async def test_actual_corpus_comparison_returns_haas_safe_run_and_sinumerik_collision(retriever) -> None:
    evidence = await retriever.retrieve(
        make_query("Compare Haas Safe Run with SINUMERIK collision avoidance."),
        top_k=8,
    )
    combined = "\n".join(f"{item.title}\n{item.content}" for item in evidence).casefold()
    assert "safe run" in combined
    assert "rapid motion" in combined or "g00" in combined
    assert "collision avoidance" in combined
    assert "protection area" in combined or "collision pairs" in combined or "clearance" in combined
