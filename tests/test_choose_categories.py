"""Checking the categories the model proposes."""

from pathlib import Path

import pytest

from gagnvist.answering.choose_categories import (
    MAX_NUMBERS,
    check_proposal,
    choose_categories,
    default_category,
    is_total,
    years_not_covered,
)
from gagnvist.data.catalogue import Category, Dimension, TableMetadata, read_metadata
from gagnvist.models.client import ModelClient

YEAR = Dimension("Ár", "Year", tuple(Category(str(y), str(y)) for y in range(2000, 2025)), False)
SEX = Dimension(
    "Kyn", "Sex", (Category("1", "Males"), Category("2", "Females"), Category("T", "Total")), False
)
UNIT = Dimension("Eining", "Unit", (Category("n", "Number"), Category("p", "Percent")), False)
TABLE = TableMetadata("People", (YEAR, SEX, UNIT))


def test_valid_codes_are_kept_in_table_order_without_repeats() -> None:
    choice = check_proposal({"Ár": ["2024", "2020", "2024"], "Kyn": ["2"], "Eining": ["n"]}, TABLE)
    assert choice.selection == {"Ár": ["2020", "2024"], "Kyn": ["2"], "Eining": ["n"]}
    assert choice.notes == []


def test_a_label_given_instead_of_a_code_is_dropped_and_noted() -> None:
    choice = check_proposal({"Ár": ["2024"], "Kyn": ["Females"], "Eining": ["n"]}, TABLE)
    assert choice.selection["Kyn"] == ["T"]  # the default: the total
    assert choice.notes == [
        "Kyn: ignored 'Females': not a category code of this dimension",
        "Kyn: no category chosen, using 'Total'",
    ]


def test_a_dimension_named_by_its_label_is_noted_and_gets_the_default() -> None:
    choice = check_proposal({"Year": ["2020"], "Kyn": ["1"], "Eining": ["p"]}, TABLE)
    assert choice.selection["Ár"] == ["2024"]  # the default: the most recent year
    assert "ignored 'Year': not a dimension code of the table" in choice.notes


def test_a_reply_without_categories_gives_the_defaults() -> None:
    choice = check_proposal(None, TABLE)
    assert choice.selection == {"Ár": ["2024"], "Kyn": ["T"], "Eining": ["n"]}
    assert choice.notes[0] == "the model proposed no categories; using the defaults"


def test_too_many_numbers_are_cut_down_dropping_the_oldest_years() -> None:
    choice = check_proposal(
        {"Ár": [c.code for c in YEAR.categories], "Kyn": ["1", "2", "T"]}, TABLE
    )
    selection = choice.selection
    assert len(selection["Ár"]) * len(selection["Kyn"]) <= MAX_NUMBERS
    assert selection["Ár"][-1] == "2024"
    assert selection["Ár"][0] != "2000"
    assert f"the proposal needs 75 numbers; only {MAX_NUMBERS} are read" in choice.notes


def test_defaults_total_then_latest_period_then_first() -> None:
    assert default_category(SEX).label == "Total"
    assert default_category(YEAR).label == "2024"  # recognised as time by its name
    assert default_category(UNIT).label == "Number"


@pytest.mark.parametrize(
    "label", ["Total", "Alls", "Males and females, total", "Allt landið", "Whole country"]
)
def test_totals_are_recognised(label: str) -> None:
    dimension = Dimension("x", "x", (Category("a", "Something"), Category("b", label)), False)
    assert default_category(dimension).code == "b"


def test_a_time_dimension_without_the_time_mark_still_defaults_to_the_latest(
    data_folder: Path,
) -> None:
    folder = "Economy/en/visitolur/2_byggingarvisitala/byggingarvisitala/VIS13401"
    year = read_metadata(data_folder, folder).dimension("Year")
    assert not year.is_time  # Statistics Iceland does not mark it
    assert default_category(year).code == "2025"


def test_choose_categories_asks_the_model(standin_client: ModelClient) -> None:
    choice = choose_categories("How many Females in 2010?", "People", TABLE, standin_client)
    assert choice.selection == {"Ár": ["2010"], "Kyn": ["2"], "Eining": ["n"]}


def test_a_single_code_instead_of_a_list_is_accepted() -> None:
    choice = check_proposal({"Ár": "2020", "Kyn": ["1"], "Eining": ["n"]}, TABLE)
    assert choice.selection["Ár"] == ["2020"]
    assert choice.notes == []


NEWEST_FIRST = Dimension(
    "Mánuður", "Month", tuple(Category(f"m{i}", f"2026M{12 - i:02}") for i in range(12)), False
)


def test_the_latest_period_is_found_when_the_newest_comes_first() -> None:
    assert default_category(NEWEST_FIRST).label == "2026M12"


def test_cutting_down_keeps_the_newest_periods_when_the_newest_comes_first() -> None:
    table = TableMetadata("t", (NEWEST_FIRST, SEX, UNIT))
    every_month = [c.code for c in NEWEST_FIRST.categories]
    choice = check_proposal(
        {"Mánuður": every_month, "Kyn": ["1", "2", "T"], "Eining": ["n", "p"]}, table
    )
    assert choice.selection["Mánuður"][0] == "m0"  # 2026M12 is kept
    assert "m11" not in choice.selection["Mánuður"]  # 2026M01 is dropped


def test_years_the_table_does_not_cover_are_found() -> None:
    assert years_not_covered("Females in 2010 and 2025?", "People", TABLE) == ["2025"]
    assert years_not_covered("Females in 2010?", "People", TABLE) == []


def test_a_year_in_the_title_counts_as_covered() -> None:
    no_time = TableMetadata("Census 2021", (SEX,))
    assert years_not_covered("Females in the 2021 census", "Census 2021", no_time) == []


def test_a_code_listed_twice_in_the_table_description_is_chosen_once() -> None:
    twice = Dimension("x", "x", (Category("B.3g", "Gross"), Category("B.3g", "Net")), False)
    choice = check_proposal({"x": ["B.3g"]}, TableMetadata("t", (twice,)))
    assert choice.selection == {"x": ["B.3g"]}


def test_the_latest_period_is_found_from_years_anywhere_in_the_labels() -> None:
    def time(*labels: str) -> Dimension:
        return Dimension(
            "t", "Time", tuple(Category(str(i), x) for i, x in enumerate(labels)), True
        )

    assert default_category(time("2008, March", "2008, July")).label == "2008, July"
    assert default_category(time("2006", "1/9 2009-31/8 2010")).label == "1/9 2009-31/8 2010"
    assert default_category(time("2023", "2024", "Change 2023-2024")).label == "2024"
    assert default_category(time("January", "February")).label == "February"


def test_the_fixture_with_months_in_words_defaults_to_the_latest(data_folder: Path) -> None:
    folder = "Society/en/felagsmal/jafnrettismal/2_kkahrifastodur/HEI02601"
    metadata = read_metadata(data_folder, folder)
    time_dimensions = [
        d for d in metadata.dimensions if any("2008" in c.label for c in d.categories)
    ]
    assert time_dimensions
    latest = default_category(time_dimensions[0]).label
    assert latest.startswith("2008") and "March" not in latest, latest


@pytest.mark.parametrize(
    ("label", "total"),
    [
        ("Total", True),
        ("Alls", True),
        ("Males and females, total", True),
        ("Karlar og konur alls", True),
        ("Total 1952", True),
        ("Allt landið", True),
        ("5. Total income (5=1+2+3+4)", True),
        ("Vinnsluvirði alls (á grunnverði)", True),
        ("% of total deaths", False),
        ("Kjósendur af íbúum alls, %", False),
        ("Vilt þú að atkvæði kjósenda alls staðar vegi jafnt?", False),
        ("Percentage of total output", False),
        ("Hlutfall af heild", False),
        ("Total, % change", False),
    ],
)
def test_totals_but_not_shares_of_totals(label: str, total: bool) -> None:
    assert is_total(Category("x", label)) is total
