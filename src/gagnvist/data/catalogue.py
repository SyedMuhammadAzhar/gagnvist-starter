"""What the data folder holds: the catalogue of tables and each table's description.

The data folder lists every table once per language in ``catalogue.csv``. Each table
has its own folder with two files:

- ``metadata.json``: the table's description, exactly as Statistics Iceland's API
  gives it: its title and its dimensions, and for every dimension the code and the
  label of each category.
- ``data.px``: the numbers (read by :mod:`gagnvist.data.px_reader`).

Words used throughout the code, as PxWeb uses them:

- a **dimension** is one way the table is split, e.g. *Year* or *Sex*;
- a **category** is one value of a dimension, e.g. *2024* or *Females*;
- every category has a **code** (what a program uses) and a **label** (what a person
  reads). Labels differ between the two languages; codes usually do not.
"""

from __future__ import annotations

import csv
import json
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class CatalogueEntry:
    """One table in one language: a row of catalogue.csv."""

    folder: str  # path inside the data folder, e.g. "Population/en/.../KOS07112"
    language: str  # "is" or "en"
    table_code: str  # Statistics Iceland's code, e.g. "KOS07112"
    title: str
    dataset: str  # "Population", "Society", "Economy", "Business_Sectors", "Environment"
    api_url: str  # where Statistics Iceland's API publishes this table
    last_updated: str
    cells: int  # how many numbers data.px holds
    partner_folder: str  # the same table in the other language


@dataclass(frozen=True)
class Category:
    code: str
    label: str


@dataclass(frozen=True)
class Dimension:
    code: str
    label: str
    categories: tuple[Category, ...]
    is_time: bool  # True for the table's time dimension (years, months, ...)

    def category(self, code: str) -> Category:
        """The category with this code; KeyError if the dimension has none."""
        for category in self.categories:
            if category.code == code:
                return category
        raise KeyError(f"dimension {self.code!r} has no category with code {code!r}")


@dataclass(frozen=True)
class TableMetadata:
    """A table's description, read from its metadata.json."""

    # Statistics Iceland's API leaves the title out of some descriptions (161 of the
    # 3,772 tables); the catalogue always has it (CatalogueEntry.title).
    title: str | None
    dimensions: tuple[Dimension, ...]

    def dimension(self, code: str) -> Dimension:
        """The dimension with this code; KeyError if the table has none."""
        for dimension in self.dimensions:
            if dimension.code == code:
                return dimension
        raise KeyError(f"the table has no dimension with code {code!r}")


# Two tables whose Icelandic and English editions sit at each other's addresses:
# VIS06123 in Icelandic is the same table as VIS06125 in English, and the other way
# round (their titles say so, and their numbers are identical). catalogue.csv pairs
# them by address; this corrects it, without changing the data release.
_PARTNER_CORRECTIONS = {
    "Economy/is/visitolur/3_verdsamanburdur/verdsamanburdureldra/VIS06123":
        "Economy/en/visitolur/3_verdsamanburdur/verdsamanburdureldra/VIS06125",
    "Economy/en/visitolur/3_verdsamanburdur/verdsamanburdureldra/VIS06125":
        "Economy/is/visitolur/3_verdsamanburdur/verdsamanburdureldra/VIS06123",
    "Economy/is/visitolur/3_verdsamanburdur/verdsamanburdureldra/VIS06125":
        "Economy/en/visitolur/3_verdsamanburdur/verdsamanburdureldra/VIS06123",
    "Economy/en/visitolur/3_verdsamanburdur/verdsamanburdureldra/VIS06123":
        "Economy/is/visitolur/3_verdsamanburdur/verdsamanburdureldra/VIS06125",
}  # fmt: skip


def clean_text(text: str) -> str:
    """A title or label as a person should read it: runs of spaces made one, and
    characters that reached the text as control characters repaired. (Statistics
    Iceland's API sends some titles and category labels with U+0096, a Windows-1252 en
    dash, where U+2013 belongs, or with Windows-1252 quote marks; many have extra spaces.)"""
    repaired = "".join(_from_windows_1252(c) if "\x80" <= c <= "\x9f" else c for c in text)
    return " ".join(repaired.split())


def _from_windows_1252(character: str) -> str:
    try:
        return bytes([ord(character)]).decode("cp1252")
    except UnicodeDecodeError:  # five codes have no character in Windows-1252
        return ""


def read_catalogue(data_folder: Path) -> list[CatalogueEntry]:
    """Every table in the data folder, in both languages."""
    path = data_folder / "catalogue.csv"
    if not path.is_file():
        raise FileNotFoundError(f"{path} not found: is {data_folder} the data folder?")
    with path.open(encoding="utf-8", newline="") as f:
        return [
            CatalogueEntry(
                folder=row["folder"],
                language=row["language"],
                table_code=row["table_code"],
                title=clean_text(row["title"]),
                dataset=row["dataset"],
                api_url=row["api_url"],
                last_updated=row["last_updated"],
                cells=int(row["cells"]),
                partner_folder=_PARTNER_CORRECTIONS.get(
                    row["folder"], row["other_language_folder"]
                ),
            )
            for row in csv.DictReader(f)
        ]


def read_metadata(data_folder: Path, folder: str) -> TableMetadata:
    """The description of the table in ``data_folder / folder``."""
    with (data_folder / folder / "metadata.json").open(encoding="utf-8") as f:
        raw = json.load(f)
    return TableMetadata(
        title=clean_text(raw["title"]) if raw.get("title") else None,
        dimensions=tuple(
            Dimension(
                code=variable["code"],
                label=clean_text(variable["text"]),
                categories=tuple(
                    Category(code=code, label=clean_text(label))
                    for code, label in zip(variable["values"], variable["valueTexts"], strict=True)
                ),
                is_time=bool(variable.get("time", False)),
            )
            for variable in raw["variables"]
        ),
    )
