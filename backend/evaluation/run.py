"""STEP 18A evaluation CLI (stdlib argparse, no heavy framework).

Examples:
    python -m evaluation.run --mode offline --dry-run
    python -m evaluation.run --mode offline --list-cases
    python -m evaluation.run --mode offline --suite smoke
    python -m evaluation.run --mode offline --suite core --category document
    python -m evaluation.run --mode offline --suite smoke --repeat 2
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

DEFAULT_OUTPUT_ROOT = Path(__file__).resolve().parents[2] / "reports" / "evaluation"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="ManufacturaIQ system evaluation harness")
    parser.add_argument("--mode", choices=["offline", "gemini-live", "full-provider"],
                        default="offline")
    parser.add_argument("--suite", choices=["smoke", "core"], default="smoke")
    parser.add_argument("--case-id", default=None)
    parser.add_argument("--case-ids", default=None,
                        help="comma-separated case IDs (subset of the suite)")
    parser.add_argument("--category", default=None)
    parser.add_argument("--repeat", type=int, default=1)
    parser.add_argument("--output-dir", default=None)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--list-cases", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    from evaluation.cases import get_suite, list_suites
    from evaluation.runner import check_determinism, evaluate_suite, summarize
    from evaluation.reports import write_run

    args = build_parser().parse_args(argv)
    if args.repeat < 1:
        print("error: --repeat must be >= 1", file=sys.stderr)
        return 2
    try:
        cases = get_suite(args.suite)
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    selected = [c for c in cases
                if (args.case_id is None or c.case_id == args.case_id)
                and (args.case_ids is None or c.case_id in args.case_ids.split(","))
                and (args.category is None or c.category == args.category)]
    if (args.case_id or args.case_ids) and not selected:
        print(f"error: no matching cases in suite {args.suite!r}", file=sys.stderr)
        return 2

    if args.dry_run:
        by_category: dict[str, int] = {}
        for case in selected:
            by_category[case.category] = by_category.get(case.category, 0) + 1
        print(f"suite={args.suite} mode={args.mode} cases={len(selected)}")
        for category in sorted(by_category):
            print(f"  {category}: {by_category[category]}")
        print(f"suites available: {list_suites()}")
        print("dry-run: no workflow invocation, no provider calls")
        return 0

    if args.list_cases:
        for case in selected:
            scope = ",".join(x for x in (case.machine_id, case.product_id, case.batch_id) if x) or "-"
            print(f"{case.case_id}\t{case.category}\t{scope}\t{case.query[:80]}")
        return 0

    if args.mode != "offline":
        import os

        if not os.environ.get("GEMINI_API_KEY") and "GEMINI_API_KEY" not in _env_file_keys():
            print("warning: GEMINI_API_KEY not configured; live reasoning will report UNAVAILABLE",
                  file=sys.stderr)

    result = asyncio.run(evaluate_suite(
        args.suite, args.mode,
        case_filter=lambda c: (args.case_id is None or c.case_id == args.case_id)
        and (args.case_ids is None or c.case_id in args.case_ids.split(","))
        and (args.category is None or c.category == args.category),
        repeat=args.repeat,
    ))
    summary = summarize(result["payloads"])
    determinism = check_determinism(result["payloads"]) if args.repeat > 1 else {
        "repeated_cases": 0, "mismatched_cases": []}
    root = Path(args.output_dir) if args.output_dir else DEFAULT_OUTPUT_ROOT / result["run"].run_id
    paths = write_run(root, result["run"], result["payloads"], summary, determinism)
    print(f"run_id={result['run'].run_id} cases={len(result['payloads'])} "
          f"failures={summary['cases_with_failures']}")
    for name, path in paths.items():
        print(f"  {name}: {path}")
    return 0


def _env_file_keys() -> set[str]:
    try:
        lines = (Path(__file__).resolve().parents[1] / ".env").read_text(encoding="utf-8").splitlines()
    except OSError:
        return set()
    keys = set()
    for line in lines:
        if "=" not in line:
            continue
        name, _, value = line.partition("=")
        if value.strip():
            keys.add(name.strip())
    return keys


if __name__ == "__main__":
    raise SystemExit(main())
