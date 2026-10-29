"""Reading the chosen numbers and writing them as facts."""

from pathlib import Path

import pytest

from gagnvist.answering.read_numbers import format_cell, read_numbers
from gagnvist.data.catalogue import read_catalogue, read_metadata
from gagnvist.data.px_reader import Cell


def test_facts_name_their_categories_and_hold_the_published_numbers(data_folder: Path) -> None:
    entry = next(
        e for e in read_catalogue(data_folder) if e.table_code == "VIS13401" and e.language == "en"
    )
    metadata = read_metadata(data_folder, entry.folder)
    facts = read_numbers(data_folder, entry, metadata, {"Year": ["2024", "2025"], "Item": ["avg"]})
    # The last two rows of the data in data.px are "119.7724 4.1406" and "124.9000 4.3000".
    assert [fact.text for fact in facts] == [
        "Year: 2024; Item: Annual average = 119.7724",
        "Year: 2025; Item: Annual average = 124.9",
    ]


def test_combinations_follow_the_selection(data_folder: Path) -> None:
    entry = next(
        e for e in read_catalogue(data_folder) if e.table_code == "SAM91452" and e.language == "is"
    )
    metadata = read_metadata(data_folder, entry.folder)
    facts = read_numbers(data_folder, entry, metadata, {"Ár": ["2016"], "Landsvæði": ["2", "1"]})
    assert [fact.categories[1][1].code for fact in facts] == ["2", "1"]


@pytest.mark.parametrize(
    ("cell", "text"),
    [
        (Cell(387758.0, None), "387758"),
        (Cell(124.8811, None), "124.8811"),
        (Cell(-3.0, None), "-3"),
        (Cell(0.0, "-"), "0"),
        (Cell(None, ".."), 'no number published ("..": not available)'),
    ],
)
def test_format_cell(cell: Cell, text: str) -> None:
    assert format_cell(cell) == text
