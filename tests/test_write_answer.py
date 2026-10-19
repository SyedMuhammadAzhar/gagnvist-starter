"""Checking the numbers in an answer against the facts."""

import pytest

from gagnvist.answering.write_answer import unsupported_numbers

SOURCES = ["How many people lived in Iceland in 2024?", "Year: 2024; Sex: Total = 387758"]


@pytest.mark.parametrize(
    "answer",
    [
        "In 2024, 387758 people lived in Iceland.",
        "In 2024, 387,758 people lived in Iceland.",
        "Árið 2024 bjuggu 387.758 manns á Íslandi.",
    ],
)
def test_numbers_from_the_facts_are_supported(answer: str) -> None:
    assert unsupported_numbers(answer, SOURCES) == []


def test_a_number_not_in_the_facts_is_reported() -> None:
    answer = "In 2024, about 400,000 people lived in Iceland, up 2.5% from 2023."
    assert unsupported_numbers(answer, SOURCES) == ["400,000", "2.5", "2023"]


def test_decimals_written_the_icelandic_way_match() -> None:
    assert unsupported_numbers("Hækkunin var 4,3%", ["Item: Annual change, % = 4.3"]) == []


def test_a_rounded_number_is_reported() -> None:
    assert unsupported_numbers("The index was 124.9.", ["= 124.8811"]) == ["124.9"]
