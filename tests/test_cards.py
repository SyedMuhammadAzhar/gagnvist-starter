"""The table cards as a dataset of their own (cards/)."""

import csv
import json
import shutil
from collections import Counter
from contextlib import closing
from pathlib import Path

import pytest
from conftest import write_settings

from gagnvist.cards import make_table_cards, read_cards, save_cards, search_cards
from gagnvist.cli import main
from gagnvist.data.catalogue import read_metadata
from gagnvist.search.table_index import TableIndex
from gagnvist.search.vector_search import Card, card_text, make_cards


def test_every_table_gets_a_card_in_each_language(data_folder: Path) -> None:
    cards = make_table_cards(data_folder)
    assert len(cards) == 12
    languages_per_pair: dict[str, list[str]] = {}
    for card in cards:
        languages_per_pair.setdefault(card.pair, []).append(card.entry.language)
    assert all(languages == ["is", "en"] for languages in languages_per_pair.values())


def test_a_card_knows_its_partner_and_holds_the_search_text(data_folder: Path) -> None:
    cards = {(c.entry.table_code, c.entry.language): c for c in make_table_cards(data_folder)}
    english, icelandic = cards["KOS07112", "en"], cards["KOS07112", "is"]
    assert english.pair == icelandic.pair
    assert english.other_language_title == icelandic.entry.title
    metadata = read_metadata(data_folder, english.entry.folder)
    assert english.text == card_text(english.entry, metadata)


def test_the_period_runs_from_the_earliest_to_the_latest(data_folder: Path) -> None:
    periods = [c.period for c in make_table_cards(data_folder) if c.period]
    assert periods
    for period in periods:
        assert period.earliest <= period.latest  # every fixture labels periods by year


def test_a_table_without_its_partner_gets_no_card(data_folder: Path, tmp_path: Path) -> None:
    copy = tmp_path / "data"
    shutil.copytree(data_folder, copy)
    catalogue = copy / "catalogue.csv"
    lines = catalogue.read_text(encoding="utf-8").splitlines(keepends=True)
    kept = [line for line in lines if ",en,HEI11505," not in line]
    assert len(kept) == len(lines) - 1
    catalogue.write_text("".join(kept), encoding="utf-8")
    codes = Counter(c.entry.table_code for c in make_table_cards(copy))
    assert "HEI11505" not in codes
    assert len(codes) == 5


def test_saved_cards_read_back_and_match_the_search_cards(
    data_folder: Path, table_database: Path, tmp_path: Path
) -> None:
    save_cards(make_table_cards(data_folder), tmp_path)
    icelandic, english = read_cards(tmp_path, "is"), read_cards(tmp_path, "en")
    assert [c["pair"] for c in icelandic] == [c["pair"] for c in english]
    assert {c["language"] for c in english} == {"en"}
    assert icelandic[0]["dimensions"][0]["categories"]  # categories are included
    with closing(TableIndex(table_database)) as tables:
        expected = make_cards(tables)
    assert sorted(search_cards(tmp_path), key=_key) == sorted(expected, key=_key)


def test_the_csv_files_open_in_a_spreadsheet(data_folder: Path, tmp_path: Path) -> None:
    save_cards(make_table_cards(data_folder), tmp_path)
    with (tmp_path / "cards.csv").open(encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f))
    with (tmp_path / "pairs.csv").open(encoding="utf-8-sig", newline="") as f:
        pairs = list(csv.DictReader(f))
    assert len(rows) == 12 and len(pairs) == 6
    assert {r["language"] for r in rows} == {"is", "en"}
    assert all(p["title_is"] and p["title_en"] for p in pairs)


def test_missing_cards_say_how_to_make_them(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError, match="build-cards"):
        search_cards(tmp_path)


def test_the_build_cards_command_keeps_existing_cards(
    data_folder: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    config = write_settings(tmp_path, changes={'folder = "data"': f"folder = {str(data_folder)!r}"})
    assert main(["--config", str(config), "build-cards"]) == 0
    assert "12 cards (6 tables in both languages)" in capsys.readouterr().out
    assert (tmp_path / "cards" / "cards-en.jsonl").is_file()
    assert main(["--config", str(config), "build-cards"]) == 1
    assert "--replace" in capsys.readouterr().err
    assert main(["--config", str(config), "build-cards", "--replace"]) == 0


def _key(card: Card) -> tuple[str, str]:
    return (card.folder, card.language)


REPOSITORY = Path(__file__).parents[1]


def test_the_shipped_index_holds_exactly_the_shipped_cards() -> None:
    """The vector index that comes with the repository was made from cards/ as it is:
    the same texts in the same order (a changed card needs `gagnvist build-vectors`)."""
    shipped = search_cards(REPOSITORY / "cards")
    with (REPOSITORY / "index" / "cards.jsonl").open(encoding="utf-8") as f:
        indexed = [Card(**json.loads(line)) for line in f if line.strip()]
    assert indexed == shipped
    assert len(shipped) == 2 * len(read_cards(REPOSITORY / "cards", "is"))


def test_the_language_differences_name_real_pairs() -> None:
    with (REPOSITORY / "cards" / "pairs.csv").open(encoding="utf-8-sig", newline="") as f:
        pairs = {row["pair"]: row for row in csv.DictReader(f)}
    path = REPOSITORY / "cards" / "language-differences.csv"
    with path.open(encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f))
    assert rows
    for row in rows:
        pair = pairs[row["pair"]]
        assert (row["table_code_is"], row["table_code_en"]) == (
            pair["table_code_is"],
            pair["table_code_en"],
        )
        assert row["difference"] in {
            "numbers differ",
            "different categories",
            "same numbers, other order",
            "rounding",
        }
