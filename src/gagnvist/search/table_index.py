"""A local SQLite database describing every table: what it is and how it is split.

``gagnvist build-index`` fills it once from the data folder (catalogue.csv plus every
metadata.json). Afterwards the program looks tables up here instead of opening
thousands of files, and you can explore the catalogue with plain SQL, for example
every English table that has a dimension called "Sex":

    SELECT t.title FROM tables t JOIN dimensions d ON d.folder = t.folder
    WHERE t.language = 'en' AND d.label = 'Sex';

The numbers themselves are not copied here: they stay in each table's data.px and are
read when needed (see :mod:`gagnvist.data.px_reader`).
"""

from __future__ import annotations

import logging
import sqlite3
from pathlib import Path

from gagnvist.data.catalogue import (
    CatalogueEntry,
    Category,
    Dimension,
    TableMetadata,
    read_catalogue,
    read_metadata,
)
from gagnvist.files import move_into_place

log = logging.getLogger(__name__)

SCHEMA = """
CREATE TABLE tables (
    folder          TEXT PRIMARY KEY,   -- path inside the data folder
    language        TEXT NOT NULL,      -- 'is' or 'en'
    table_code      TEXT NOT NULL,
    dataset         TEXT NOT NULL,
    title           TEXT NOT NULL,
    api_url         TEXT NOT NULL,
    last_updated    TEXT NOT NULL,
    cells           INTEGER NOT NULL,
    partner_folder  TEXT NOT NULL       -- the same table in the other language
);
CREATE TABLE dimensions (
    folder    TEXT NOT NULL REFERENCES tables (folder),
    position  INTEGER NOT NULL,         -- order in the table description
    code      TEXT NOT NULL,
    label     TEXT NOT NULL,
    is_time   INTEGER NOT NULL,         -- 1 for the time dimension
    PRIMARY KEY (folder, position)
);
CREATE TABLE categories (
    folder          TEXT NOT NULL,
    dimension_code  TEXT NOT NULL,
    position        INTEGER NOT NULL,   -- order within the dimension
    code            TEXT NOT NULL,
    label           TEXT NOT NULL,
    PRIMARY KEY (folder, dimension_code, position)
);
CREATE INDEX tables_by_code ON tables (table_code);
"""


def build_index(data_folder: Path, index_file: Path) -> int:
    """Create ``index_file`` from the data folder; return the number of tables.

    An existing index file is replaced only once the new one is complete.
    """
    entries = read_catalogue(data_folder)
    partial = index_file.with_name(index_file.name + ".partial")
    partial.unlink(missing_ok=True)
    db = sqlite3.connect(partial)
    try:
        with db:  # one transaction, committed at the end
            db.executescript(SCHEMA)
            for number, entry in enumerate(entries, 1):
                _insert(db, entry, read_metadata(data_folder, entry.folder))
                if number % 500 == 0:
                    log.info("  indexed %s of %s tables", f"{number:,}", f"{len(entries):,}")
    finally:
        db.close()  # before the rename: Windows cannot rename a file that is open
    move_into_place(partial, index_file)
    return len(entries)


class TableIndex:
    """Read access to an index file built by :func:`build_index`."""

    def __init__(self, index_file: Path) -> None:
        if not index_file.is_file():
            raise FileNotFoundError(f"{index_file} not found: run `gagnvist build-index` first")
        path = index_file.resolve()
        if str(path).startswith("\\\\"):
            # A Windows network share (\\server\share\...), which a file URI cannot name.
            self._db = sqlite3.connect(path)
            self._db.execute("PRAGMA query_only = ON")
        else:
            # Opened read-only. A file URI keeps characters such as "#" in the path intact.
            self._db = sqlite3.connect(path.as_uri() + "?mode=ro", uri=True)

    def close(self) -> None:
        self._db.close()

    def entries(self, language: str | None = None) -> list[CatalogueEntry]:
        """Every table, or every table in one language."""
        query = f"SELECT {_ENTRY_COLUMNS} FROM tables"
        rows = (
            self._db.execute(query + " WHERE language = ? ORDER BY folder", (language,))
            if language
            else self._db.execute(query + " ORDER BY folder")
        )
        return [_entry_from_row(row) for row in rows]

    def entry(self, folder: str) -> CatalogueEntry:
        row = self._db.execute(
            f"SELECT {_ENTRY_COLUMNS} FROM tables WHERE folder = ?", (folder,)
        ).fetchone()
        if row is None:
            raise KeyError(f"no table in the index at {folder!r}")
        return _entry_from_row(row)

    def metadata(self, folder: str) -> TableMetadata:
        """The table's description: dimensions and categories from its metadata.json, and
        the title from the catalogue (which always has one; metadata.json sometimes not)."""
        dimensions = []
        for code, label, is_time in self._db.execute(
            "SELECT code, label, is_time FROM dimensions WHERE folder = ? ORDER BY position",
            (folder,),
        ):
            categories = tuple(
                Category(code=c, label=lbl)
                for c, lbl in self._db.execute(
                    "SELECT code, label FROM categories "
                    "WHERE folder = ? AND dimension_code = ? ORDER BY position",
                    (folder, code),
                )
            )
            dimensions.append(Dimension(code, label, categories, bool(is_time)))
        if not dimensions:
            raise KeyError(f"no table in the index at {folder!r}")
        return TableMetadata(title=self.entry(folder).title, dimensions=tuple(dimensions))


_ENTRY_COLUMNS = (
    "folder, language, table_code, title, dataset, api_url, last_updated, cells, partner_folder"
)


def _entry_from_row(row: tuple[str, str, str, str, str, str, str, int, str]) -> CatalogueEntry:
    folder, language, table_code, title, dataset, api_url, last_updated, cells, partner = row
    return CatalogueEntry(
        folder=folder,
        language=language,
        table_code=table_code,
        title=title,
        dataset=dataset,
        api_url=api_url,
        last_updated=last_updated,
        cells=cells,
        partner_folder=partner,
    )


def _insert(db: sqlite3.Connection, entry: CatalogueEntry, metadata: TableMetadata) -> None:
    db.execute(
        f"INSERT INTO tables ({_ENTRY_COLUMNS}) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            entry.folder,
            entry.language,
            entry.table_code,
            entry.title,
            entry.dataset,
            entry.api_url,
            entry.last_updated,
            entry.cells,
            entry.partner_folder,
        ),
    )
    for position, dimension in enumerate(metadata.dimensions):
        db.execute(
            "INSERT INTO dimensions VALUES (?, ?, ?, ?, ?)",
            (entry.folder, position, dimension.code, dimension.label, int(dimension.is_time)),
        )
        db.executemany(
            "INSERT INTO categories VALUES (?, ?, ?, ?, ?)",
            (
                (entry.folder, dimension.code, i, category.code, category.label)
                for i, category in enumerate(dimension.categories)
            ),
        )
