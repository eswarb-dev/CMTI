from __future__ import annotations

import pytest

from evaluation.run import build_parser, main


def test_parser_defaults() -> None:
    args = build_parser().parse_args([])
    assert args.mode == "offline"
    assert args.suite == "smoke"
    assert args.repeat == 1
    assert args.dry_run is False
    assert args.list_cases is False


def test_parser_rejects_unknown_mode() -> None:
    with pytest.raises(SystemExit):
        build_parser().parse_args(["--mode", "nope"])


def test_dry_run_reports_without_workflow(capsys) -> None:
    assert main(["--mode", "offline", "--suite", "smoke", "--dry-run"]) == 0
    out = capsys.readouterr().out
    assert "cases=" in out
    assert "no workflow invocation" in out


def test_list_cases_stable(capsys) -> None:
    assert main(["--mode", "offline", "--suite", "smoke", "--list-cases"]) == 0
    first = capsys.readouterr().out
    assert main(["--mode", "offline", "--suite", "smoke", "--list-cases"]) == 0
    assert capsys.readouterr().out == first


def test_unknown_case_id_rejected() -> None:
    assert main(["--mode", "offline", "--suite", "smoke", "--case-id", "NOPE"]) == 2


def test_repeat_validation() -> None:
    assert main(["--mode", "offline", "--repeat", "0", "--dry-run"]) == 2
