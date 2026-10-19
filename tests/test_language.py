"""Guessing the language of a question."""

import pytest

from gagnvist.answering.language import guess_language


@pytest.mark.parametrize(
    ("question", "language"),
    [
        ("How many people live in Reykjavík?", "en"),
        ("How many people live in Garðabær?", "en"),  # a place name does not decide
        ("Population of Iceland 2024", "en"),
        ("Hve margir búa í Reykjavík?", "is"),
        ("Hvað voru gistinætur margar árið 2016?", "is"),
        ("Mannfjöldi Garðabæjar 2024", "is"),  # no common words: the letters decide
        ("KOS07112 1980", "en"),
    ],
)
def test_guess_language(question: str, language: str) -> None:
    assert guess_language(question) == language
