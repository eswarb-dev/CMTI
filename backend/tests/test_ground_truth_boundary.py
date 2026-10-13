from __future__ import annotations

from pathlib import Path


def test_application_code_does_not_reference_ground_truth_file() -> None:
    app_root = Path(__file__).resolve().parents[1] / "app"
    offenders: list[Path] = []
    for path in app_root.rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        if "demo_cases.json" in text:
            offenders.append(path)
    assert offenders == []


def test_application_code_does_not_reference_hidden_simulated_cause() -> None:
    app_root = Path(__file__).resolve().parents[1] / "app"
    offenders: list[Path] = []
    for path in app_root.rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        if "hidden_simulated_cause" in text:
            offenders.append(path)
    assert offenders == []

