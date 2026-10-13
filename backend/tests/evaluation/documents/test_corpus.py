from __future__ import annotations

from evaluation.documents import corpus as corpus_module


def test_corpus_size_and_determinism() -> None:
    first = corpus_module.get_corpus()
    assert 12 <= len(first) <= 20
    assert corpus_module.corpus_fingerprint() == corpus_module.corpus_fingerprint()
    labels = [item.label for item in first]
    assert len(set(labels)) == len(labels)


def test_corpus_ground_truth_present() -> None:
    for item in corpus_module.get_corpus():
        assert item.unique_phrases
        assert item.queries
        assert item.topic
        assert item.filename.endswith(".pdf")


def test_write_pdf_deterministic(tmp_path) -> None:
    import fitz

    first = tmp_path / "a.pdf"
    second = tmp_path / "b.pdf"
    pages = ["Deterministic content here. " * 10]
    corpus_module.write_pdf(first, pages)
    corpus_module.write_pdf(second, pages)

    def texts(path) -> list[str]:
        document = fitz.open(path)
        try:
            return [page.get_text("text") for page in document]
        finally:
            document.close()

    assert texts(first) == texts(second)
    assert "Deterministic content here." in texts(first)[0]


def test_prompt_injection_item_marked() -> None:
    items = [i for i in corpus_module.get_corpus() if "injection" in i.topic]
    assert len(items) == 1
    assert "Ignore previous instructions" in items[0].pages[0]


def test_negative_inputs_defined() -> None:
    from evaluation.documents import campaign as campaign_module

    assert campaign_module.NEGATIVE_CASES == ("non-pdf", "fake-pdf", "malformed",
                                             "encrypted", "image-only")
