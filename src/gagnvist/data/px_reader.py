"""Reading numbers from a table's ``data.px`` file.

A px file is PxWeb's own format: a header of ``KEYWORD=value;`` statements, then a line
``DATA=`` followed by the numbers. The header says how the numbers are laid out:

- ``STUB`` names the dimensions that form the rows, ``HEADING`` those that form the
  columns. The numbers are written row by row, one row per line.
- ``VALUES("dimension")`` lists the labels of a dimension's categories in order, and
  ``CODES("dimension")`` their codes.

The number for one category of every dimension therefore sits at a row and a column
computed from the categories' positions, like finding a cell in a spreadsheet.

Two things to know about Statistics Iceland's px files:

- each file declares its own text encoding in ``CODEPAGE``: UTF-8 (those begin with a
  byte-order mark), ISO-8859-15, Windows-1252, or for a few English tables GB18030
  (their text is plain ASCII, so it reads the same);
- a missing number is written as a marker in quotes, such as ``".."`` (see MARKERS).
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from math import prod
from pathlib import Path

from gagnvist.data.catalogue import Dimension, TableMetadata

MARKERS = {
    "-": "zero",
    "..": "not available",
    ".": "not applicable",
    "...": "no number given",  # the files do not say why; mostly early years
}

_CODEPAGES = {"windows-1252": "cp1252", "ansi": "cp1252"}
_STATEMENT = re.compile(r'([A-Z][A-Z0-9-]*)((?:\[[a-z]{2}\])?(?:\((?:"[^"]*"|[^)"])*\))?)\s*=')
_LIST_PART = re.compile(r'"([^"]*)"|,')


class PxError(Exception):
    """A px file could not be read, or does not match its table description."""


@dataclass(frozen=True)
class Cell:
    """One number of a table."""

    value: float | None  # None when the table has no number here
    marker: str | None  # how a missing (or zero) number is written, e.g. ".."; see MARKERS


@dataclass(frozen=True)
class _PxDimension:
    """A dimension as the px file lays it out."""

    dimension: Dimension  # the matching dimension of the table description
    codes: tuple[str, ...]  # its category codes, in the order the file uses


class PxFile:
    """A table's data.px, ready to read numbers from.

    Only the header is read when the object is created; numbers are read on request.
    """

    def __init__(self, path: Path, metadata: TableMetadata) -> None:
        self.path = path
        header, self._data_start = _read_header(path)
        statements = _parse_statements(header)
        stub = _items(statements.get("STUB", ""))
        heading = _items(statements.get("HEADING", ""))
        other_names = _names_in_other_languages(statements, len(stub) + len(heading))
        layout = [
            _match_dimension(name, other_names[i], statements, metadata)
            for i, name in enumerate(stub + heading)
        ]
        if sorted(d.dimension.code for d in layout) != sorted(d.code for d in metadata.dimensions):
            raise PxError(f"{path}: the file's dimensions do not match the table description")
        self._rows = layout[: len(stub)]
        self._columns = layout[len(stub) :]
        self._columns_per_row = prod(len(d.codes) for d in self._columns)

    def read(self, selection: Mapping[str, str]) -> Cell:
        """The number for one category of every dimension: {dimension code: category code}."""
        return self.read_many([selection])[0]

    def read_many(self, selections: Sequence[Mapping[str, str]]) -> list[Cell]:
        """Several numbers at once, reading the file only as far as needed."""
        positions = [self._position(selection) for selection in selections]
        rows_needed = {row for row, _ in positions}
        rows = self._read_rows(rows_needed)
        return [_parse_value(rows[row][column]) for row, column in positions]

    def _position(self, selection: Mapping[str, str]) -> tuple[int, int]:
        """(row, column) of the cell for these categories."""
        return _flat_index(self._rows, selection), _flat_index(self._columns, selection)

    def _read_rows(self, wanted: set[int]) -> dict[int, list[str]]:
        """The values of the wanted rows, each split into its columns."""
        found: dict[int, list[str]] = {}
        last = max(wanted)
        with self.path.open("rb") as f:
            f.seek(self._data_start)
            for row, line in enumerate(f):
                if row in wanted:
                    found[row] = self._row_values(row, line)
                if row >= last:
                    break
        if len(found) != len(wanted):
            raise PxError(f"{self.path}: the data ends before row {last}")
        return found

    def _row_values(self, row: int, line: bytes) -> list[str]:
        """The values written on one line of the data (the last line ends with ';')."""
        try:
            values = line.decode("ascii").replace(";", " ").split()
        except UnicodeDecodeError:
            raise PxError(f"{self.path}: row {row} contains unexpected characters") from None
        if len(values) != self._columns_per_row:
            raise PxError(
                f"{self.path}: row {row} has {len(values)} values, expected {self._columns_per_row}"
            )
        return values


def _read_header(path: Path) -> tuple[str, int]:
    """The header as text, and the byte offset where the numbers start."""
    raw = _read_until_data(path)
    match = re.search(rb"(?m)^DATA=\s*?\r?\n", raw)
    if not match:
        raise PxError(f"{path}: no DATA section found")
    head = raw[: match.start()]
    if head.startswith(b"\xef\xbb\xbf"):
        head = head[3:]
    declared = re.search(rb'CODEPAGE="([^"]+)"', head)
    encoding = declared.group(1).decode("ascii").lower() if declared else "utf-8"
    encoding = _CODEPAGES.get(encoding, encoding)
    try:
        text = head.decode(encoding)
    except (LookupError, UnicodeDecodeError) as e:
        raise PxError(f"{path}: header is not in its declared encoding {encoding!r}") from e
    return text, match.end()


def _read_until_data(path: Path) -> bytes:
    """The start of a large file, up to and including the DATA= line."""
    chunks = []
    with path.open("rb") as f:
        for line in f:
            chunks.append(line)
            if line.startswith(b"DATA="):
                break
    return b"".join(chunks)


def _parse_statements(header: str) -> dict[str, str]:
    """The header's statements as {keyword: value}; the first occurrence wins.

    A keyword carries its language and argument, e.g. ``VALUES[en]("Year")``. A value
    may span several lines and contain semicolons inside quotes.
    """
    statements: dict[str, str] = {}
    position = 0
    while True:
        match = _STATEMENT.search(header, position)
        if not match:
            return statements
        end, in_quotes = match.end(), False
        while end < len(header) and (in_quotes or header[end] != ";"):
            if header[end] == '"':
                in_quotes = not in_quotes
            end += 1
        statements.setdefault(match.group(1) + match.group(2), header[match.end() : end].strip())
        position = end + 1


def _items(value: str) -> list[str]:
    """The entries of a px list. Entries are separated by commas; a long entry may be
    written as several quoted pieces on successive lines, which together form it."""
    items: list[str] = []
    pieces: list[str] = []
    for match in _LIST_PART.finditer(value):
        if match.group(0) == ",":
            items.append("".join(pieces))
            pieces = []
        else:
            pieces.append(match.group(1))
    if pieces:
        items.append("".join(pieces))
    return items


def _names_in_other_languages(statements: Mapping[str, str], count: int) -> list[list[str]]:
    """For each dimension position, its name in the file's other languages.

    A bilingual file names its dimensions in its main language in STUB and HEADING, and
    in each other language in STUB[xx] and HEADING[xx], in the same order."""
    names: list[list[str]] = [[] for _ in range(count)]
    for language in {k[4:8] for k in statements if k.startswith("STUB[")}:
        translated = _items(statements.get(f"STUB{language}", "")) + _items(
            statements.get(f"HEADING{language}", "")
        )
        if len(translated) == count:
            for position, name in enumerate(translated):
                names[position].append(name)
    return names


def _match_dimension(
    name: str, other_names: Sequence[str], statements: Mapping[str, str], metadata: TableMetadata
) -> _PxDimension:
    """Find which dimension of the table description the px file's ``name`` is.

    The px file names a dimension by its label in the file's main language, while the
    description uses the code and the label of the edition's own language. Clues are
    tried from strongest to weakest, and a clue counts only if exactly one dimension
    fits it: the dimension code the file declares, then the name in any of the file's
    languages, then the list of category codes (two dimensions can share that list,
    e.g. "Sex" and "Age" both coded Total, 1, 2).
    """
    declared = _items(statements.get(f'VARIABLECODE("{name}")', ""))
    codes = _items(statements.get(f'CODES("{name}")', ""))
    names = {name, *other_names}
    clues = (
        lambda d: bool(declared) and d.code == declared[0],
        lambda d: d.label in names or d.code in names,
        lambda d: bool(codes) and [c.code for c in d.categories] == codes,
    )
    for clue in clues:
        fits = [d for d in metadata.dimensions if clue(d)]
        if len(fits) == 1:
            dimension = fits[0]
            break
    else:
        raise PxError(
            f"dimension {name!r} of the px file cannot be matched to the table description"
        )
    if codes:
        return _PxDimension(dimension, tuple(codes))
    labels = _items(statements.get(f'VALUES("{name}")', ""))
    if len(labels) != len(dimension.categories):
        raise PxError(
            f"dimension {name!r} lists {len(labels)} categories in the px file "
            f"and {len(dimension.categories)} in the table description"
        )
    return _PxDimension(dimension, tuple(c.code for c in dimension.categories))


def _flat_index(layout: Sequence[_PxDimension], selection: Mapping[str, str]) -> int:
    """Position of a combination of categories, counting the last dimension fastest."""
    index = 0
    for px_dimension in layout:
        code = selection.get(px_dimension.dimension.code)
        if code is None:
            raise KeyError(f"choose a category of dimension {px_dimension.dimension.code!r}")
        try:
            position = px_dimension.codes.index(code)
        except ValueError:
            raise KeyError(
                f"dimension {px_dimension.dimension.code!r} has no category {code!r} "
                "in the data file"
            ) from None
        index = index * len(px_dimension.codes) + position
    return index


def _parse_value(token: str) -> Cell:
    """One value as written in the file: a number, or a marker in quotes."""
    marker = token.strip('"')
    if token.startswith('"') or marker in MARKERS:
        return Cell(value=0.0 if marker == "-" else None, marker=marker)
    return Cell(value=float(token), marker=None)
