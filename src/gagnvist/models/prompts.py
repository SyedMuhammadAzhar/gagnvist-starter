"""Every prompt the starter kit sends to the language model, in one place.

Changing how the model is asked is one of the easiest ways to improve the answers.
When you change a prompt, keep its inputs and the shape of the reply the code expects
(described at each function).
"""

from __future__ import annotations

import re

from gagnvist.data.catalogue import Category, Dimension, TableMetadata
from gagnvist.models.client import Message

# A dimension with more categories than this is shortened in the prompt (see
# _categories_for_prompt). Some tables have thousands, e.g. one per municipality and year.
MAX_CATEGORIES_SHOWN = 40

LANGUAGE_NAMES = {"is": "Icelandic", "en": "English"}

# Icelandic letters as the English tables write them: "Garðabær" becomes "Gardabaer".
_PLAIN_LETTERS = str.maketrans(
    {"á": "a", "é": "e", "í": "i", "ó": "o", "ú": "u", "ý": "y", "ö": "o", "ð": "d",
     "þ": "th", "æ": "ae"}
)  # fmt: skip

CHOOSE_CATEGORIES_SYSTEM = """\
You help answer questions from one statistical table published by Statistics Iceland.
You are given a question and the table's dimensions. Each dimension lists its categories
as "code: label".

For every dimension, choose the codes of the categories the question needs:
- If the question does not mention a dimension, choose its total category (such as
  "Total" or "Alls") if it has one, otherwise its first category.
- For a time dimension (years, months, ...), choose the periods the question asks
  about; if it names none, choose the most recent period.
- Use the codes exactly as listed, never the labels.

Answer with JSON only, in this shape:
{"categories": {"<dimension code>": ["<category code>", ...]}}"""

CHOOSE_CATEGORIES_SCHEMA = {
    "type": "object",
    "properties": {
        "categories": {
            "type": "object",
            "additionalProperties": {"type": "array", "items": {"type": "string"}},
        }
    },
    "required": ["categories"],
}

WRITE_ANSWER_SYSTEM = """\
You write a short, plain answer to a question about Statistics Iceland's data.
Use only the numbers listed in the facts, written exactly as they appear there, and do
not calculate new ones. Say what each number is about (period, group, place). If a fact
says no number is published, say so. Answer in {language}, in one to three sentences."""


def choose_categories_messages(question: str, title: str, metadata: TableMetadata) -> list[Message]:
    """Ask which categories of each dimension the question needs.

    Expected reply: JSON shaped like CHOOSE_CATEGORIES_SCHEMA.
    """
    dimensions = "\n\n".join(_describe_dimension(d, question) for d in metadata.dimensions)
    user = f"Question: {question}\n\nTable: {title}\n\nDimensions:\n\n{dimensions}"
    return [
        {"role": "system", "content": CHOOSE_CATEGORIES_SYSTEM},
        {"role": "user", "content": user},
    ]


def write_answer_messages(
    question: str, language: str, title: str, facts: list[str]
) -> list[Message]:
    """Ask for the answer, given the facts as lines of text.

    Expected reply: the answer as plain text.
    """
    system = WRITE_ANSWER_SYSTEM.format(language=LANGUAGE_NAMES.get(language, "English"))
    listed = "\n".join(f"- {fact}" for fact in facts)
    user = f"Question: {question}\n\nTable: {title}\n\nFacts:\n{listed}"
    return [{"role": "system", "content": system}, {"role": "user", "content": user}]


def _describe_dimension(dimension: Dimension, question: str) -> str:
    lines = [f'Dimension "{dimension.code}": {dimension.label}']
    shown, hidden = _categories_for_prompt(dimension, question)
    lines += [f"  {category.code}: {category.label}" for category in shown]
    if hidden:
        lines.append(f"  ... and {hidden} more categories not shown")
    return "\n".join(lines)


def _categories_for_prompt(dimension: Dimension, question: str) -> tuple[list[Category], int]:
    """The categories to show, and how many are left out.

    A long dimension is shortened to its first and last five categories (totals usually
    come first, the most recent periods last) and those whose label names something the
    question names (see :func:`_same_word`). This is a simple rule, and a good place to
    improve the starter kit.
    """
    categories = list(dimension.categories)
    if len(categories) <= MAX_CATEGORIES_SHOWN:
        return categories, 0
    asked = _words(question)
    matching = [
        c for c in categories if any(_same_word(a, w) for a in asked for w in _words(c.label))
    ]
    keep = set(categories[:5] + matching[: MAX_CATEGORIES_SHOWN - 10] + categories[-5:])
    shown = [c for c in categories if c in keep]
    return shown, len(categories) - len(shown)


def _words(text: str) -> set[str]:
    """The words and numbers in a text, in small letters without accents; "2020M03"
    counts as "2020", "m" and "03"."""
    return set(re.findall(r"\d+|[^\W\d_]+", text.lower().translate(_PLAIN_LETTERS)))


def _same_word(asked: str, written: str) -> bool:
    """Whether a word of the question and a word of a label name the same thing.

    Numbers must be equal, and so must short words ("cod"). Longer words count as the
    same when they begin alike for at least four letters and half the shorter word,
    because Icelandic changes the ends of names: "Akureyri" is "Akureyrarbaer" in a
    table, "Hafnarfirdi" is "Hafnarfjardarkaupstadur".
    """
    if asked.isdigit() or written.isdigit():
        return asked == written
    if len(asked) < 4 or len(written) < 4:
        return len(asked) == 3 and asked == written
    shared = 0  # how many letters they begin with alike
    for a, b in zip(asked, written, strict=False):
        if a != b:
            break
        shared += 1
    return shared >= max(4, min(len(asked), len(written)) / 2)
