"""Lint the structure of a CSV file before a parser or a database does.

A CSV that "loads fine" can still be wrong: a BOM that hides the first column name, a
duplicated header that silently drops a column when it becomes a ``dict``, a row with
one field too few that shifts every value after it.

    >>> from columncheck import lint_csv
    >>> problems = lint_csv("a,b\\n1\\n")
    >>> problems[0].code
    'ragged-row'

Standard library only, Python 3.9+.
"""

from __future__ import annotations

import csv
import io
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass

__all__ = ["Problem", "lint_csv", "sniff_delimiter"]

__version__ = "0.1.0"


@dataclass(frozen=True)
class Problem:
    """One structural problem, located by line and (when it makes sense) column."""

    line: int
    column: int | None
    code: str
    message: str

    def __str__(self) -> str:
        where = f"line {self.line}"
        if self.column is not None:
            where += f", column {self.column}"
        return f"{where}: {self.message} ({self.code})"


def _decode(text: str | bytes, encoding: str) -> tuple[str | None, Problem | None]:
    if isinstance(text, bytes):
        try:
            return text.decode(encoding), None
        except UnicodeDecodeError as error:
            return None, Problem(1, None, "encoding", f"not valid {encoding}: {error}")
    return text, None


def lint_csv(
    text: str | bytes,
    *,
    delimiter: str = ",",
    expected_header: Sequence[str] | None = None,
    allow_ragged: bool = False,
    encoding: str = "utf-8",
) -> list[Problem]:
    """Report structural problems in a CSV document.

    Checks the byte order mark, NUL bytes, empty or duplicated header names, padded
    header names, rows whose field count differs from the header, and (when
    ``expected_header`` is given) columns that are missing or unexpected.
    """
    if len(delimiter) != 1:
        raise ValueError(f"delimiter must be one character, not {delimiter!r}")
    document, decoding_problem = _decode(text, encoding)
    if decoding_problem is not None:
        return [decoding_problem]
    assert document is not None

    problems: list[Problem] = []
    if document.startswith("\ufeff"):
        document = document[1:]
        problems.append(
            Problem(
                1,
                None,
                "bom",
                "starts with a byte order mark; the first column name may be read as '\\ufeffname'",
            )
        )
    if "\x00" in document:
        index = document.index("\x00")
        problems.append(
            Problem(document.count("\n", 0, index) + 1, None, "nul-byte", "contains a NUL byte")
        )
        document = document.replace("\x00", "")

    reader = csv.reader(io.StringIO(document), delimiter=delimiter)
    try:
        header = next(reader)
    except StopIteration:
        return sorted(
            [*problems, Problem(1, None, "empty-file", "the file has no header row")],
            key=_order,
        )
    except csv.Error as error:
        return sorted(
            [*problems, Problem(1, None, "malformed", f"cannot read the header: {error}")],
            key=_order,
        )

    if not any(field.strip() for field in header):
        problems.append(Problem(1, None, "empty-header", "the header row is empty"))
    for index, name in enumerate(header, start=1):
        if not name.strip():
            problems.append(Problem(1, index, "empty-header", f"column {index} has no name"))
        elif name != name.strip():
            problems.append(
                Problem(1, index, "padded-header", f"column {index} is padded: {name!r}")
            )
    seen: dict[str, int] = {}
    for index, name in enumerate(header, start=1):
        key = name.strip()
        if not key:
            continue
        if key in seen:
            problems.append(
                Problem(
                    1,
                    index,
                    "duplicate-header",
                    f"{key!r} already appears in column {seen[key]}",
                )
            )
        else:
            seen[key] = index

    if expected_header is not None:
        wanted = [column.strip() for column in expected_header]
        present = {name.strip() for name in header}
        for name in wanted:
            if name not in present:
                problems.append(Problem(1, None, "missing-column", f"expected column {name!r}"))
        for name in header:
            if name.strip() and name.strip() not in wanted:
                problems.append(
                    Problem(1, None, "extra-column", f"unexpected column {name.strip()!r}")
                )

    width = len(header)
    while True:
        try:
            row = next(reader)
        except StopIteration:
            break
        except csv.Error as error:
            problems.append(Problem(reader.line_num, None, "malformed", str(error)))
            break
        if not row:
            continue
        if len(row) != width and not allow_ragged:
            problems.append(
                Problem(
                    reader.line_num,
                    None,
                    "ragged-row",
                    f"{len(row)} field(s), header has {width}",
                )
            )
    return sorted(problems, key=_order)


def _order(problem: Problem) -> tuple[int, int]:
    return (problem.line, problem.column or 0)


def sniff_delimiter(text: str | bytes, candidates: str = ",;\t|") -> str:
    """Guess the delimiter: the candidate that splits the first rows most consistently."""
    document, problem = _decode(text, "utf-8")
    if problem is not None or document is None:
        raise ValueError("cannot sniff a delimiter from undecodable bytes")
    best_delimiter = candidates[0]
    best_score = (0, 0)
    for candidate in candidates:
        rows = []
        try:
            for row in csv.reader(io.StringIO(document), delimiter=candidate):
                rows.append(len(row))
                if len(rows) >= 50:
                    break
        except csv.Error:  # pragma: no cover - a broken candidate is simply not chosen
            continue
        if not rows:
            continue
        counts = Counter(rows)
        width, agree = counts.most_common(1)[0]
        score = (agree, width)
        if score > best_score:
            best_score = score
            best_delimiter = candidate
    return best_delimiter
