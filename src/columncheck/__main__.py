"""Command line entry point: ``columncheck`` or ``python -m columncheck``."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import lint_csv, sniff_delimiter


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="columncheck",
        description="Check the structure of a CSV file: header, field counts, encoding.",
    )
    parser.add_argument("path", type=Path, metavar="FILE")
    parser.add_argument("--delimiter", default=",", help="field delimiter (default ',')")
    parser.add_argument(
        "--sniff",
        action="store_true",
        help="guess the delimiter from the file instead of using --delimiter",
    )
    parser.add_argument(
        "--header",
        metavar="A,B,C",
        help="the columns the file is supposed to have, comma separated",
    )
    parser.add_argument(
        "--allow-ragged",
        action="store_true",
        help="do not report rows with a different field count",
    )
    parser.add_argument("--encoding", default="utf-8")
    parser.add_argument("--json", action="store_true", help="print JSON")
    args = parser.parse_args(argv)

    if not args.path.is_file():
        print(f"no such file: {args.path}", file=sys.stderr)
        return 2
    data = args.path.read_bytes()
    delimiter = sniff_delimiter(data) if args.sniff else args.delimiter
    expected = args.header.split(",") if args.header else None
    try:
        problems = lint_csv(
            data,
            delimiter=delimiter,
            expected_header=expected,
            allow_ragged=args.allow_ragged,
            encoding=args.encoding,
        )
    except ValueError as error:
        print(f"error: {error}", file=sys.stderr)
        return 2

    if args.json:
        print(
            json.dumps(
                [
                    {
                        "line": problem.line,
                        "column": problem.column,
                        "code": problem.code,
                        "message": problem.message,
                    }
                    for problem in problems
                ],
                indent=2,
            )
        )
    else:
        for problem in problems:
            print(f"{args.path}:{problem.line}: {problem.message} ({problem.code})")
        labels = ", ".join(sorted({problem.code for problem in problems})) or "nothing"
        print(f"{len(problems)} problem(s), delimiter {delimiter!r}: {labels}", file=sys.stderr)
    return 1 if problems else 0


if __name__ == "__main__":
    raise SystemExit(main())
