"""Telling whether a question is in Icelandic or English."""

from __future__ import annotations

import re

# Short words that are common in questions, in each language.
_ICELANDIC_WORDS = {
    "í", "á", "og", "er", "eru", "var", "voru", "hvað", "hve", "hversu", "hver", "hvert",
    "hvaða", "hvar", "hvenær", "margir", "margar", "mörg", "mikið", "árið", "milli",
    "frá", "til", "með", "fyrir", "eftir", "um",
}  # fmt: skip
_ENGLISH_WORDS = {
    "the", "in", "of", "and", "is", "are", "was", "were", "what", "how", "many", "much",
    "which", "who", "when", "where", "did", "does", "do", "between", "from", "for", "by",
}  # fmt: skip
# Letters that English does not use.
_ICELANDIC_LETTERS = set("ðþæö")


def guess_language(question: str) -> str:
    """The language of a question: "is" for Icelandic, "en" for English.

    A simple rule: count the common words of each language. On a tie (for example a
    question of only names and numbers), letters English does not use decide. Names
    alone do not decide, so "How many people live in Garðabær?" is English.
    """
    words = re.findall(r"\w+", question.lower())
    icelandic = sum(word in _ICELANDIC_WORDS for word in words)
    english = sum(word in _ENGLISH_WORDS for word in words)
    if icelandic != english:
        return "is" if icelandic > english else "en"
    return "is" if _ICELANDIC_LETTERS & set(question.lower()) else "en"
