"""Step 4: write the answer from the numbers that were read.

The language model writes the sentences, but the numbers come from the table: the model
is told to use only the facts it is given, and :func:`unsupported_numbers` lists every
number in its answer that the facts do not contain, so that a wrong number is caught
instead of trusted.

Ideas to improve this step: format numbers the way each language does (387.758 in
Icelandic, 387,758 in English) and teach the check to accept both; let the code do any
arithmetic (sums, changes, shares) and give the model the results as facts.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from contextlib import suppress

from gagnvist.answering.read_numbers import Fact
from gagnvist.models import prompts
from gagnvist.models.client import ModelClient

_NUMBER = re.compile(r"\d+(?:[.,]\d+)*")


def write_answer(
    question: str, language: str, title: str, facts: list[Fact], client: ModelClient
) -> str:
    """The model's answer to the question, written from the facts."""
    messages = prompts.write_answer_messages(question, language, title, [f.text for f in facts])
    return client.chat(messages)


def unsupported_numbers(answer: str, sources: Iterable[str]) -> list[str]:
    """The numbers written in ``answer`` that appear in none of the ``sources`` texts.

    Numbers are compared by value. Each is read both the English way (1,234.5) and the
    Icelandic way (1.234,5), so "387,758" and "387.758" both match "387758".
    """
    allowed: set[float] = set()
    for text in sources:
        for number in _NUMBER.findall(text):
            allowed |= _possible_values(number)
    return [number for number in _NUMBER.findall(answer) if not _possible_values(number) & allowed]


def _possible_values(number: str) -> set[float]:
    values = set()
    for thousands, decimal in ((",", "."), (".", ",")):
        with suppress(ValueError):  # e.g. "1.2.3" cannot be read the English way
            values.add(float(number.replace(thousands, "").replace(decimal, ".")))
    return values
