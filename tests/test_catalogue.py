"""Reading catalogue.csv and metadata.json."""

from pathlib import Path

import pytest

from gagnvist.data.catalogue import clean_title, read_catalogue, read_metadata


def test_titles_are_cleaned() -> None:
    # as the API lists census table CEN0031: a Windows-1252 en dash as a control character
    assert clean_title("region 24.\x96 30. January 1981") == "region 24.\u2013 30. January 1981"
    assert clean_title("  Erlendir farþegar 1971-1999  ") == "Erlendir farþegar 1971-1999"
    assert clean_title("Keflavik Airport  2015-") == "Keflavik Airport 2015-"


def test_every_table_is_listed_in_both_languages(data_folder: Path) -> None:
    entries = read_catalogue(data_folder)
    assert len(entries) == 12
    assert sum(e.language == "is" for e in entries) == sum(e.language == "en" for e in entries) == 6


def test_partner_links_point_back(data_folder: Path) -> None:
    entries = {e.folder: e for e in read_catalogue(data_folder)}
    for entry in entries.values():
        partner = entries[entry.partner_folder]
        assert partner.partner_folder == entry.folder
        assert partner.language != entry.language
        assert partner.table_code == entry.table_code


def test_metadata_describes_dimensions_and_categories(data_folder: Path) -> None:
    entry = next(
        e for e in read_catalogue(data_folder) if e.table_code == "KOS07112" and e.language == "en"
    )
    metadata = read_metadata(data_folder, entry.folder)
    assert [len(d.categories) for d in metadata.dimensions] == [20, 2, 9]
    assert metadata.dimension("Unit").category("1").label == "Percentage"


def test_time_dimension_is_marked(data_folder: Path) -> None:
    entry = next(
        e for e in read_catalogue(data_folder) if e.table_code == "SAM91452" and e.language == "is"
    )
    metadata = read_metadata(data_folder, entry.folder)
    assert [d.code for d in metadata.dimensions if d.is_time] == ["Ár"]


def test_missing_title_is_none_and_the_catalogue_has_it(data_folder: Path) -> None:
    entry = next(
        e for e in read_catalogue(data_folder) if e.table_code == "HEI02601" and e.language == "is"
    )
    assert read_metadata(data_folder, entry.folder).title is None
    assert entry.title


def test_unknown_codes_raise_key_error(data_folder: Path) -> None:
    entry = read_catalogue(data_folder)[0]
    metadata = read_metadata(data_folder, entry.folder)
    with pytest.raises(KeyError):
        metadata.dimension("no such dimension")
    with pytest.raises(KeyError):
        metadata.dimensions[0].category("no such category")
