from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

if __package__ is None or __package__ == "":
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scripts.demo_factory.generator import generate
from scripts.demo_factory.validators import validate


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate and validate the ManufacturaIQ demo factory dataset")
    parser.add_argument("--generate", action="store_true", help="Generate deterministic demo factory data")
    parser.add_argument("--validate", action="store_true", help="Validate generated demo factory data")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if not args.generate and not args.validate:
        raise SystemExit("Use --generate, --validate, or both.")
    if args.generate:
        manifest = generate()
        print(json.dumps({"generated": manifest["row_counts"]}, indent=2))
    if args.validate:
        result = validate()
        print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

