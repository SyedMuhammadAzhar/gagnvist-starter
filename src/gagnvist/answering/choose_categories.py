"""Step 2: choose which numbers of the table the question needs.

A table holds one number for every combination of categories, one from each dimension.
The language model reads the question and the table's dimensions and proposes
categories (see :func:`gagnvist.models.prompts.choose_categories_messages`). The
proposal is then checked, because a model may invent a code, give a label where a code
is expected, or skip a dimension:

- codes the table does not have are dropped, with a note;
- a dimension left without categories gets a default (:func:`default_category`);
- at most MAX_NUMBERS combinations are kept.

Ideas to improve this step: show the model fewer, better-chosen categories of long
dimensions; let it ask back when the question is unclear; support questions that need
a calculation over several numbers (a sum, a change, a share).
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from math import prod

from gagnvist.data.catalogue import Category, Dimension, TableMetadata
from gagnvist.models import prompts
from gagnvist.models.client import ModelClient

MAX_NUMBERS = 50

Selection = dict[str, list[str]]  # {dimension code: [category codes]}

# How total categories are labelled: "Total", "Alls", "Males and females, total", ...
_TOTAL_WORDS = {"total", "alls", "samtals"}
_TOTAL_STARTS = ("all ", "allir", "allt ", "whole country", "landið")
# ... and labels that use those words for something else: a share of a total ("% of
# total deaths", "Hlutfall af heild"), or "alls staðar" ("everywhere").
_NOT_TOTAL_MARKS = ("%", "percent", "prósent", "hlutfall", "share", "proportion",
                    "of total", "af heild", "alls staðar")  # fmt: skip
# Names of time dimensions (by code or label).
_TIME_NAMES = {"ár", "year", "mánuður", "month", "ársfjórðungur", "quarter", "tímabil", "period"}
_YEAR = re.compile(r"(?<!\d)(?:1[89]\d\d|20\d\d)(?!\d)")
# Periods within a year written as codes: 2026M06 (month), 2026Q2 or 2026K2 (quarter).
_PERIOD_CODE = re.compile(r"(\d{4})[MQKH](\d{1,2})")


@dataclass(frozen=True)
class Choice:
    selection: Selection  # the categories to read, for every dimension of the table
    notes: list[str]  # what was corrected in the model's proposal


def choose_categories(
    question: str, title: str, metadata: TableMetadata, client: ModelClient
) -> Choice:
    """Ask the model which categories the question needs, then check its proposal."""
    messages = prompts.choose_categories_messages(question, title, metadata)
    reply = client.chat_json(messages, prompts.CHOOSE_CATEGORIES_SCHEMA)
    return check_proposal(reply.get("categories"), metadata)


def check_proposal(proposal: object, metadata: TableMetadata) -> Choice:
    """Turn the model's proposal, {dimension code: [category codes]}, into a selection
    of categories the table has."""
    notes: list[str] = []
    if not isinstance(proposal, Mapping):
        notes.append("the model proposed no categories; using the defaults")
        proposal = {}
    unknown_dimensions = [str(code) for code in proposal if code not in _codes(metadata)]
    if unknown_dimensions:
        notes.append(f"ignored {_listed(unknown_dimensions)}: not a dimension code of the table")

    selection: Selection = {}
    for dimension in metadata.dimensions:
        proposed = proposal.get(dimension.code)
        if isinstance(proposed, str):  # one code instead of a list of one
            proposed = [proposed]
        codes = [str(code) for code in proposed] if isinstance(proposed, list) else []
        # In table order, each code once (a table description can list a code twice).
        chosen = list(dict.fromkeys(c.code for c in dimension.categories if c.code in codes))
        unknown = [code for code in codes if code not in {c.code for c in dimension.categories}]
        if unknown:
            notes.append(
                f"{dimension.code}: ignored {_listed(unknown)}: not a category code "
                "of this dimension"
            )
        if not chosen:
            default = default_category(dimension)
            chosen = [default.code]
            notes.append(f"{dimension.code}: no category chosen, using {default.label!r}")
        selection[dimension.code] = chosen
    return Choice(_limit(selection, metadata, notes), notes)


def default_category(dimension: Dimension) -> Category:
    """The category to use when the question does not say: the dimension's total if it
    has one, the most recent period of a time dimension, otherwise the first category."""
    for category in dimension.categories:
        if is_total(category):
            return category
    if looks_like_time(dimension):
        return most_recent(dimension)
    return dimension.categories[0]


def is_total(category: Category) -> bool:
    """Whether the category's label says it is a total: "Total", "Alls", "Iceland,
    total", "5. Total income", but not a share of one such as "% of total deaths"."""
    label = category.label.lower()
    if any(mark in label for mark in _NOT_TOTAL_MARKS):
        return False
    return bool(_TOTAL_WORDS & set(re.findall(r"\w+", label))) or label.startswith(_TOTAL_STARTS)


def looks_like_time(dimension: Dimension) -> bool:
    """Whether the dimension is the table's time (years, months, ...).

    Statistics Iceland marks the time dimension in only about half of the tables; in the
    others it is recognised by its name, e.g. "Year" or "Ár".
    """
    return (
        dimension.is_time
        or dimension.code.lower() in _TIME_NAMES
        or dimension.label.lower() in _TIME_NAMES
    )


def most_recent(dimension: Dimension) -> Category:
    """The latest period of a time dimension.

    Periods usually run from oldest to newest, but not in every table (some list the
    newest month first), and labels take many forms ("2024", "2024M06", "2008, July",
    "1/9 2009-31/8 2010"). So the latest is the period with the highest year in its
    label, and among periods of the same year, the one furthest in the direction the
    table runs. A dimension without years in its labels: its last category.
    """
    dated = _dated(dimension)
    if not dated:
        return dimension.categories[-1]
    forward = _runs_oldest_first(dimension, dated)
    position, _ = max(dated, key=lambda item: (item[1], item[0] if forward else -item[0]))
    return dimension.categories[position]


def years_not_covered(question: str, title: str, metadata: TableMetadata) -> list[str]:
    """The years the question names that the table does not cover.

    A year counts as covered if the label of any category (not only of the time
    dimension: election tables put it in the candidate's label) or the title mentions
    it. Many tables have look-alikes that stop earlier, such as an older series of the
    same statistic, so a table found for "2024" may end in 2021: the categories then
    fall back to its latest period, and this check says so.
    """
    labels = " ".join(c.label for dimension in metadata.dimensions for c in dimension.categories)
    years = dict.fromkeys(_YEAR.findall(question))  # in order, without repeats
    return [year for year in years if year not in labels and year not in title]


def _limit(selection: Selection, metadata: TableMetadata, notes: list[str]) -> Selection:
    """Keep at most MAX_NUMBERS combinations by shortening the longest choices: the
    oldest periods go first in a time dimension, the last categories in the others."""
    wanted = prod(len(codes) for codes in selection.values())
    if wanted <= MAX_NUMBERS:
        return selection
    limited = {code: list(codes) for code, codes in selection.items()}
    while prod(len(codes) for codes in limited.values()) > MAX_NUMBERS:
        longest = max(limited, key=lambda code: len(limited[code]))
        dimension = metadata.dimension(longest)
        dated = _dated(dimension) if looks_like_time(dimension) else []
        limited[longest].pop(0 if dated and _runs_oldest_first(dimension, dated) else -1)
    notes.append(f"the proposal needs {wanted:,} numbers; only {MAX_NUMBERS} are read")
    return limited


def _dated(dimension: Dimension) -> list[tuple[int, int]]:
    """(position, year) of the categories whose label names a year, the highest if it
    names several. Labels that start with the date are preferred, so that a label like
    "Change 2023-2024" counts only when no label starts with a date."""
    found = [
        (position, max(int(year) for year in years))
        for position, category in enumerate(dimension.categories)
        if (years := _YEAR.findall(category.label))
    ]
    starting = [
        item for item in found if dimension.categories[item[0]].label.lstrip()[:1].isdigit()
    ]
    return starting or found


def _runs_oldest_first(dimension: Dimension, dated: list[tuple[int, int]]) -> bool:
    """Whether the periods run from oldest to newest: told by their years, or, if the
    first and the last have the same year, by period codes such as 2026M01 and 2026M12.
    Otherwise assume they do, as nearly all tables list them that way."""
    (first, first_year), (last, last_year) = dated[0], dated[-1]
    if first_year != last_year:
        return first_year < last_year
    codes = [_PERIOD_CODE.fullmatch(dimension.categories[i].label.strip()) for i in (first, last)]
    if codes[0] and codes[1]:
        return int(codes[0][2]) <= int(codes[1][2])
    return True


def _codes(metadata: TableMetadata) -> set[str]:
    return {dimension.code for dimension in metadata.dimensions}


def _listed(codes: list[str]) -> str:
    return ", ".join(repr(code) for code in codes)
