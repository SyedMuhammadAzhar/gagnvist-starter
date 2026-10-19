"""The prompts sent to the language model."""

from gagnvist.data.catalogue import Category, Dimension, TableMetadata
from gagnvist.models.prompts import (
    MAX_CATEGORIES_SHOWN,
    choose_categories_messages,
    write_answer_messages,
)

SEX = Dimension(
    "Kyn", "Sex", (Category("0", "Total"), Category("1", "Males"), Category("2", "Females")), False
)
MUNICIPALITY = Dimension(
    "Sveitarfélag",
    "Municipality",
    (*(Category(str(1000 + i), f"Place {i}") for i in range(99)), Category("8000", "Höfn")),
    False,
)


def test_every_dimension_is_listed_with_codes_and_labels() -> None:
    messages = choose_categories_messages("How many females?", "People", TableMetadata("t", (SEX,)))
    assert [m["role"] for m in messages] == ["system", "user"]
    user = messages[1]["content"]
    assert user.startswith("Question: How many females?\n\nTable: People")
    assert 'Dimension "Kyn": Sex\n  0: Total\n  1: Males\n  2: Females' in user


def test_a_long_dimension_is_shortened_but_keeps_what_the_question_names() -> None:
    metadata = TableMetadata("t", (MUNICIPALITY,))
    user = choose_categories_messages("People in Höfn", "People", metadata)[1]["content"]
    category_lines = [line for line in user.splitlines() if line.startswith("  ")]
    assert "  8000: Höfn" in category_lines  # named in the question (and the last one)
    assert "  1000: Place 0" in category_lines  # the first categories are always shown
    assert category_lines[-1] == "  ... and 90 more categories not shown"
    assert len(category_lines) - 1 <= MAX_CATEGORIES_SHOWN


def test_answer_prompt_names_the_language_and_lists_the_facts() -> None:
    messages = write_answer_messages(
        "Hve margir?", "is", "Mannfjöldi", ["Ár: 2024 = 5", "Ár: 2025 = 6"]
    )
    assert "Answer in Icelandic" in messages[0]["content"]
    assert messages[1]["content"].endswith("Facts:\n- Ár: 2024 = 5\n- Ár: 2025 = 6")


def test_a_month_named_in_the_question_is_shown_from_a_long_series() -> None:
    months = tuple(
        Category(f"{year}M{month:02}", f"{year}M{month:02}")
        for year in range(2000, 2026)
        for month in range(1, 13)
    )
    metadata = TableMetadata("t", (Dimension("Mánuður", "Month", months, True),))
    user = choose_categories_messages("Guests in 2013", "Hotels", metadata)[1]["content"]
    assert "  2013M03: 2013M03" in user.splitlines()


TOWNS = Dimension(
    "Sveitarfélag",
    "Municipality",
    (
        *(Category(str(i), f"Place {i}") for i in range(30)),
        Category("6000", "Akureyrarbaer"),
        Category("1400", "Hafnarfjardarkaupstadur"),
        Category("4200", "Ísafjarðarbær"),
        *(Category(str(i), f"Place {i}") for i in range(30, 60)),
    ),
    False,
)


def test_a_town_is_found_although_tables_spell_and_inflect_it_differently() -> None:
    def shown(question: str) -> list[str]:
        user = choose_categories_messages(question, "People", TableMetadata("t", (TOWNS,)))
        return [line.strip() for line in user[1]["content"].splitlines() if line.startswith("  ")]

    assert "6000: Akureyrarbaer" in shown("How many people live in Akureyri?")
    assert "1400: Hafnarfjardarkaupstadur" in shown("Hve margir búa í Hafnarfirði?")
    assert "4200: Ísafjarðarbær" in shown("Population of Isafjordur")
    assert "6000: Akureyrarbaer" not in shown("How many people live in Ísafjörður?")
