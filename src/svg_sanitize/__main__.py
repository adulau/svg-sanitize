"""CLI: python -m svg_sanitize untrusted.svg -o clean.svg"""

import argparse
import sys
from pathlib import Path

from . import Limits, SVGValidationError, sanitize_svg


def main() -> int:
    parser = argparse.ArgumentParser(description="Strip SVG down to static visual primitives")
    parser.add_argument("input", type=Path, help="SVG input file")
    parser.add_argument("-o", "--output", type=Path, help="SVG output file (default stdout)")
    args = parser.parse_args()
    limits = Limits()
    try:
        with args.input.open("rb") as f:
            content = f.read(limits.max_input_bytes + 1)
        cleaned = sanitize_svg(content, limits=limits)
        if args.output:
            args.output.write_text(cleaned + "\n", encoding="utf-8")
        else:
            sys.stdout.write(cleaned + "\n")
    except (SVGValidationError, OSError) as exc:
        print(f"svg-sanitize: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
