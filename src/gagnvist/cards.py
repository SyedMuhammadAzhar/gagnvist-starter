"""The table cards as a dataset of their own, in ``cards/``.

A card describes one table in one language: its title, its dimensions with every
category, the period it covers, where it is, and ``text``, the short text the search
embeds (made by :func:`gagnvist.search.vector_search.card_text`). The cards come with
the repository, so they can be read, reused or enriched without unpacking the data:

    cards/cards-is.jsonl   one Icelandic card per line
    cards/cards-en.jsonl   one English card per line, in the same order: line n is the
                           same table as line n of cards-is.jsonl
    cards/cards.csv        every card, one row each, without the categories
    cards/pairs.csv        one row per table: Icelandic and English side by side

Every table is in both languages, and its two cards share a ``pair`` id. A table whose
partner in the other language is missing gets no card.

``gagnvist build-cards`` makes the folder from the data; ``gagnvist build-vectors``
embeds the ``text`` of every card. To try richer cards, change the texts (by hand, with
a script or with a model) and build a new vector index from them.
"""

from __future__ import annotations

import csv
import json
import logging
import re
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from gagnvist.answering.choose_categories import looks_like_time, most_recent
from gagnvist.config import ConfigError
from gagnvist.data.catalogue import (
    CatalogueEntry,
    Dimension,
    TableMetadata,
    read_catalogue,
    read_metadata,
)
from gagnvist.search.vector_search import Card, card_text

log = logging.getLogger(__name__)

LANGUAGES = ("is", "en")
_YEAR = re.compile(r"(?<!\d)(?:1[89]\d\d|20\d\d)(?!\d)")


@dataclass(frozen=True)
class Period:
    """The time a table covers, from the labels of its time dimension."""

    dimension: str  # the label of the time dimension, e.g. "Year" or "Ár"
    earliest: str
    latest: str
    count: int  # how many periods


@dataclass(frozen=True)
class TableCard:
    """One table in one language."""

    pair: str  # the same on the table's Icelandic and English card, e.g. "P0001"
    entry: CatalogueEntry
    metadata: TableMetadata
    other_language_title: str
    period: Period | None
    text: str  # what the search embeds

    def to_json(self) -> dict[str, Any]:
        e = self.entry
        return {
            "pair": self.pair,
            "language": e.language,
            "table_code": e.table_code,
            "title": e.title,
            "other_language_title": self.other_language_title,
            "dataset": e.dataset,
            "subject_path": "/".join(e.folder.split("/")[2:-1]),
            "period": None if self.period is None else vars(self.period),
            "dimensions": [_dimension_json(d) for d in self.metadata.dimensions],
            "cells": e.cells,
            "last_updated": e.last_updated,
            "api_url": e.api_url,
            "folder": e.folder,
            "other_language_folder": e.partner_folder,
            "text": self.text,
        }


def make_table_cards(data_folder: Path) -> list[TableCard]:
    """A card for every table in the data folder that is in both languages, ordered
    by pair, Icelandic first."""
    entries = {e.folder: e for e in read_catalogue(data_folder)}
    icelandic = []
    for entry in entries.values():
        partner = entries.get(entry.partner_folder)
        if partner is None or partner.language == entry.language:
            log.warning("  skipped %s: no partner in the other language", entry.folder)
        elif partner.partner_folder != entry.folder:
            log.warning("  skipped %s: its partner points to another table", entry.folder)
        elif entry.language == "is":
            icelandic.append(entry)
    cards = []
    for number, entry in enumerate(sorted(icelandic, key=lambda e: e.folder), 1):
        pair = f"P{number:04d}"
        partner = entries[entry.partner_folder]
        described = {t.folder: read_metadata(data_folder, t.folder) for t in (entry, partner)}
        for table, other in ((entry, partner), (partner, entry)):
            metadata = described[table.folder]
            period = _period(_time_dimension(metadata, described[other.folder]))
            text = card_text(table, metadata)
            cards.append(TableCard(pair, table, metadata, other.title, period, text))
    return cards


def save_cards(cards: Sequence[TableCard], folder: Path) -> None:
    """Write the cards folder (see the module description)."""
    folder.mkdir(parents=True, exist_ok=True)
    for language in LANGUAGES:
        with (folder / f"cards-{language}.jsonl").open("w", encoding="utf-8", newline="\n") as f:
            for card in cards:
                if card.entry.language == language:
                    f.write(json.dumps(card.to_json(), ensure_ascii=False) + "\n")
    _write_csv(folder / "cards.csv", [_card_row(card) for card in cards])
    by_pair: dict[str, dict[str, TableCard]] = {}
    for card in cards:
        by_pair.setdefault(card.pair, {})[card.entry.language] = card
    _write_csv(folder / "pairs.csv", [_pair_row(p, both) for p, both in by_pair.items()])


def read_cards(folder: Path, language: str | None = None) -> list[dict[str, Any]]:
    """The cards in a cards folder, as written there: every card, or one language's."""
    cards: list[dict[str, Any]] = []
    for lang in [language] if language else LANGUAGES:
        path = folder / f"cards-{lang}.jsonl"
        if not path.is_file():
            raise FileNotFoundError(f"{path} not found: run `gagnvist build-cards` first")
        number = 0
        try:
            # utf-8-sig: a file saved by a Windows program may begin with a byte-order mark
            with path.open(encoding="utf-8-sig") as f:
                for number, line in enumerate(f, 1):  # noqa: B007 (used in the message)
                    if line.strip():
                        cards.append(json.loads(line))
        except UnicodeDecodeError:
            raise ConfigError(
                f"{path} is not saved as UTF-8: save it again as UTF-8 (in your own code: "
                "open(..., encoding='utf-8'))"
            ) from None
        except json.JSONDecodeError as e:
            raise ConfigError(
                f"{path}, line {number}: not a card in JSON ({e.msg}); every line must be "
                "one card, as in cards/cards-en.jsonl"
            ) from None
    return cards


def search_cards(folder: Path) -> list[Card]:
    """The text of every card, for the search (see ``gagnvist build-vectors``)."""
    return [Card(c["folder"], c["language"], c["text"]) for c in read_cards(folder)]


def _time_dimension(metadata: TableMetadata, partner: TableMetadata) -> Dimension | None:
    """The table's time dimension, looked for in this table and at the same place in the
    other language's table, whose name for it is sometimes the only clear one: first the
    dimension Statistics Iceland marks as time; else, of the dimensions named like time,
    the one with the most years in its labels (a table with both Month and Year covers
    the years). A dimension without years in its labels (Month alone, or Season) gives
    no period."""
    ours = metadata.dimensions

    def at_same_place(i: int, described: TableMetadata) -> bool:
        return i < len(ours) and len(ours[i].categories) == len(described.dimensions[i].categories)

    for described in (metadata, partner):
        flagged = [i for i, d in enumerate(described.dimensions) if d.is_time]
        if flagged and at_same_place(flagged[0], described):
            return ours[flagged[0]]
    named = [
        (sum(bool(_YEAR.search(c.label)) for c in ours[i].categories), -i, i)
        for described in (metadata, partner)
        for i, d in enumerate(described.dimensions)
        if looks_like_time(d) and at_same_place(i, described)
    ]
    if named and max(named)[0] > 0:
        return ours[max(named)[2]]
    return None


def _period(time: Dimension | None) -> Period | None:
    if time is None or not time.categories:
        return None
    latest = most_recent(time)
    at_latest = time.categories.index(latest)
    dated = [
        (min(int(year) for year in years), position)
        for position, category in enumerate(time.categories)
        if (years := _YEAR.findall(category.label))
    ]
    if dated:  # the lowest year, at the end furthest from the latest period
        lowest = min(year for year, _ in dated)
        positions = [position for year, position in dated if year == lowest]
        earliest = time.categories[max(positions, key=lambda p: abs(p - at_latest))]
    else:
        earliest = time.categories[0 if at_latest else -1]
    return Period(time.label, earliest.label, latest.label, len(time.categories))


def _dimension_json(dimension: Dimension) -> dict[str, Any]:
    return {
        "code": dimension.code,
        "label": dimension.label,
        "is_time": dimension.is_time,  # as Statistics Iceland marks it (about half the tables)
        "categories": [{"code": c.code, "label": c.label} for c in dimension.categories],
    }


def _card_row(card: TableCard) -> dict[str, Any]:
    e, period = card.entry, card.period
    return {
        "pair": card.pair,
        "language": e.language,
        "table_code": e.table_code,
        "dataset": e.dataset,
        "title": e.title,
        "other_language_title": card.other_language_title,
        "period_earliest": period.earliest if period else "",
        "period_latest": period.latest if period else "",
        "dimensions": " | ".join(d.label for d in card.metadata.dimensions),
        "categories": sum(len(d.categories) for d in card.metadata.dimensions),
        "cells": e.cells,
        "last_updated": e.last_updated,
        "api_url": e.api_url,
        "folder": e.folder,
        "text": card.text,
    }


def _pair_row(pair: str, both: dict[str, TableCard]) -> dict[str, Any]:
    icelandic, english = both["is"], both["en"]
    return {
        "pair": pair,
        "dataset": icelandic.entry.dataset,
        "table_code_is": icelandic.entry.table_code,
        "table_code_en": english.entry.table_code,
        "title_is": icelandic.entry.title,
        "title_en": english.entry.title,
        "folder_is": icelandic.entry.folder,
        "folder_en": english.entry.folder,
    }


def _write_csv(path: Path, rows: Sequence[dict[str, Any]]) -> None:
    # utf-8-sig: spreadsheet programs then show Icelandic letters correctly;
    # "\n": the repository keeps text files with Unix line endings (.gitattributes)
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0]) if rows else [], lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
