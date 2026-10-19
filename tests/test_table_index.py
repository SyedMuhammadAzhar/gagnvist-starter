"""The local database of table descriptions."""

from collections.abc import Iterator
from pathlib import Path

import pytest

from gagnvist.data.catalogue import read_catalogue, read_metadata
from gagnvist.search.table_index import TableIndex, build_index


@pytest.fixture
def index(data_folder: Path, tmp_path: Path) -> Iterator[TableIndex]:
    database = tmp_path / "tables.sqlite"
    assert build_index(data_folder, database) == 12
    opened = TableIndex(database)
    yield opened
    opened.close()


def test_every_table_is_indexed(index: TableIndex) -> None:
    assert len(index.entries()) == 12
    assert len(index.entries(language="is")) == len(index.entries(language="en")) == 6


def test_entries_match_the_catalogue(index: TableIndex, data_folder: Path) -> None:
    for entry in read_catalogue(data_folder):
        assert index.entry(entry.folder) == entry


def test_descriptions_match_metadata_json(index: TableIndex, data_folder: Path) -> None:
    for entry in read_catalogue(data_folder):
        from_index = index.metadata(entry.folder)
        from_file = read_metadata(data_folder, entry.folder)
        assert from_index.dimensions == from_file.dimensions
        assert from_index.title == entry.title  # the catalogue's title, always present


def test_unknown_folder_raises_key_error(index: TableIndex) -> None:
    with pytest.raises(KeyError):
        index.entry("no/such/table")
    with pytest.raises(KeyError):
        index.metadata("no/such/table")


def test_rebuilding_replaces_the_old_index(data_folder: Path, tmp_path: Path) -> None:
    database = tmp_path / "tables.sqlite"
    build_index(data_folder, database)
    build_index(data_folder, database)
    assert len(TableIndex(database).entries()) == 12
    assert not (tmp_path / "tables.sqlite.partial").exists()


def test_a_missing_index_says_how_to_build_it(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError, match="build-index"):
        TableIndex(tmp_path / "tables.sqlite")


def test_a_path_with_unusual_characters_works(tmp_path: Path, data_folder: Path) -> None:
    folder = tmp_path / "C# projects 100%"
    folder.mkdir()
    index_file = folder / "tables.sqlite"
    build_index(data_folder, index_file)
    index = TableIndex(index_file)
    assert len(index.entries()) == 12
    index.close()
    assert sorted(p.name for p in folder.iterdir()) == ["tables.sqlite"]  # no stray files
