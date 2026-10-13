from __future__ import annotations

from evaluation.metrics import bundle_fingerprint, determinism_equal


def _bundle(ids=("E1", "E2"), conflicts=("C1",)):
    return {
        "query_id": "Q-1",
        "evidence": [{"evidence_id": i} for i in ids],
        "conflicts": [{"conflict_id": c} for c in conflicts],
    }


def test_identical_bundles_compare_equal() -> None:
    assert determinism_equal(bundle_fingerprint(_bundle()), bundle_fingerprint(_bundle()))


def test_reordered_evidence_compares_unequal() -> None:
    assert not determinism_equal(bundle_fingerprint(_bundle(("E1", "E2"))),
                                 bundle_fingerprint(_bundle(("E2", "E1"))))


def test_conflict_difference_detected() -> None:
    assert not determinism_equal(bundle_fingerprint(_bundle(conflicts=("C1",))),
                                 bundle_fingerprint(_bundle(conflicts=("C2",))))
