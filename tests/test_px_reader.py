"""Reading numbers from data.px files.

Expected values come straight from the files, independently of the reader: the first
and the last value of a px file's data are the cells for the first and the last
category of every dimension, whatever order the file lists its dimensions in.
"""

import itertools
import re
from pathlib import Path

import pytest

from gagnvist.data.catalogue import CatalogueEntry, TableMetadata, read_catalogue, read_metadata
from gagnvist.data.px_reader import Cell, PxFile, _parse_value


def _open(data_folder: Path, code: str, language: str) -> tuple[PxFile, TableMetadata, Path]:
    entry: CatalogueEntry = next(
        e for e in read_catalogue(data_folder) if e.table_code == code and e.language == language
    )
    metadata = read_metadata(data_folder, entry.folder)
    path = data_folder / entry.folder / "data.px"
    return PxFile(path, metadata), metadata, path


def _raw_values(path: Path) -> list[str]:
    raw = path.read_bytes()
    data = raw[raw.index(b"\nDATA=") + len(b"\nDATA=") :].decode("ascii")
    return data.replace(";", " ").split()


TABLES = ["SAM91452", "KOS02105", "HEI11505", "KOS07112", "VIS13401", "HEI02601"]


@pytest.mark.parametrize("language", ["is", "en"])
@pytest.mark.parametrize("code", TABLES)
def test_first_and_last_cells_match_the_file(data_folder: Path, code: str, language: str) -> None:
    px, metadata, path = _open(data_folder, code, language)
    first = {d.code: d.categories[0].code for d in metadata.dimensions}
    last = {d.code: d.categories[-1].code for d in metadata.dimensions}
    values = _raw_values(path)
    assert px.read(first) == _parse_value(values[0])
    assert px.read(last) == _parse_value(values[-1])


def test_known_numbers() -> None:
    assert _parse_value("68224") == Cell(68224.0, None)
    assert _parse_value("28.4") == Cell(28.4, None)


# The two editions of these tables publish identical numbers. (VIS13401 does not: see
# test_editions_can_differ.)
IDENTICAL_EDITIONS = ["SAM91452", "KOS02105", "HEI11505", "KOS07112", "HEI02601"]


@pytest.mark.parametrize("code", IDENTICAL_EDITIONS)
def test_both_editions_hold_the_same_numbers(data_folder: Path, code: str) -> None:
    px_is, meta_is, _ = _open(data_folder, code, "is")
    px_en, meta_en, _ = _open(data_folder, code, "en")
    # Pair the dimensions by their category codes: the two editions may list them in a
    # different order and name them differently (KOS07112 does both). Two dimensions
    # can share a code list ("Unit" and "Sex" both 0, 1 in HEI02601); then position decides.
    partner = {}
    for position, d in enumerate(meta_is.dimensions):
        codes = [c.code for c in d.categories]
        same = [e for e in meta_en.dimensions if [c.code for c in e.categories] == codes]
        if len(same) > 1:
            same = [e for e in same if meta_en.dimensions.index(e) == position]
        assert len(same) == 1, f"cannot pair dimension {d.code!r}"
        partner[d.code] = same[0].code
    combinations = list(
        itertools.product(*[[c.code for c in d.categories] for d in meta_is.dimensions])
    )
    selections_is = [
        dict(zip([d.code for d in meta_is.dimensions], combo, strict=True))
        for combo in combinations
    ]
    selections_en = [{partner[k]: v for k, v in s.items()} for s in selections_is]
    assert px_is.read_many(selections_is) == px_en.read_many(selections_en)


def test_markers_are_read_as_written(data_folder: Path) -> None:
    px, metadata, path = _open(data_folder, "HEI11505", "en")
    combinations = itertools.product(*[[c.code for c in d.categories] for d in metadata.dimensions])
    cells = px.read_many(
        [dict(zip([d.code for d in metadata.dimensions], c, strict=True)) for c in combinations]
    )
    raw = path.read_text(encoding="cp1252")
    for marker in ("-", "..", "."):
        in_file = len(re.findall(r'"' + re.escape(marker) + r'"', raw.split("DATA=", 1)[1]))
        assert sum(c.marker == marker for c in cells) == in_file
    assert all(c.value == 0.0 for c in cells if c.marker == "-")
    assert all(c.value is None for c in cells if c.marker in ("..", "."))


def test_unknown_category_or_missing_dimension_raise_key_error(data_folder: Path) -> None:
    px, metadata, _ = _open(data_folder, "KOS02105", "en")
    selection = {d.code: d.categories[0].code for d in metadata.dimensions}
    with pytest.raises(KeyError, match="no category"):
        px.read({**selection, metadata.dimensions[0].code: "no such category"})
    del selection[metadata.dimensions[0].code]
    with pytest.raises(KeyError, match="choose a category"):
        px.read(selection)


def test_editions_can_differ(data_folder: Path) -> None:
    """Statistics Iceland's two editions do not always agree: for 2025, VIS13401 has
    124.8811 in Icelandic and 124.9 in English. Each edition is read as published."""
    px_is, _, _ = _open(data_folder, "VIS13401", "is")
    px_en, _, _ = _open(data_folder, "VIS13401", "en")
    assert px_is.read({"Ár": "2025", "Liður": "avg"}).value == 124.8811
    assert px_en.read({"Year": "2025", "Item": "avg"}).value == 124.9
