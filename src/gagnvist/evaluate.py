"""Measuring the starter kit: ask questions whose answers are known, and count.

The questions come in three levels:

- ``easy``: one number from one table;
- ``medium``: a calculation with several numbers from the same table (a change, a sum,
  a share);
- ``hard``: numbers from two different tables.

A questions file has one question per line (JSON Lines)::

    {"id": "reykjavik-growth-2026-en", "language": "en", "level": "medium",
     "question": "By how many people did the population of Reykjavík grow ...?",
     "answers": [{"value": 1032, "unit": "people"}],
     "how": "Reykjavík on 1 January 2026 minus Reykjavík on 1 January 2025",
     "parts": [{"table": "MAN02005", "accepted": ["MAN02005", "MAN03270"],
                "categories": {...}, "labels": {...}, "value": 139804}, ...]}

``answers`` are the numbers the answer must state; ``parts`` are the table cells they come
from, each with the tables that hold exactly the same number (``accepted``).

An answer is **right** when it states every expected number and, for every part, the
answer used one of that part's accepted tables. A number counts as stated when the answer
writes it plainly or with thousands separators, in English or Icelandic style or with
spaces, rounded to no fewer digits than it shows ("4941210.9" is a right way to write
4941210.9167), or in one of the other units the question lists (cod in tonnes as well as
kilograms, say). A right number from another table is reported, but not counted as right:
more often than not it is a lucky guess.

Files in the starter kit's earlier form (one ``table``, ``categories``, ``answer`` and
``answer_is``) are read too, as easy questions.
"""

from __future__ import annotations

import json
import re
import time
from collections.abc import Callable, Iterable, Sequence
from contextlib import suppress
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from gagnvist.answering.pipeline import Answer, AnswerError, Pipeline
from gagnvist.data.px_reader import PxError
from gagnvist.models.client import ModelError

LEVELS = ("easy", "medium", "hard")
LANGUAGES = {"en": "English", "is": "Icelandic"}
_NUMBER = re.compile(r"\d+(?:[.,]\d+)*")
# thousands set apart by spaces, as Icelandic is often written: 4 941 210,9 (also with a
# no-break, thin or narrow no-break space); a year before it is not taken in: "2026 139 804"
_SPACED_NUMBER = re.compile(r"(?<!\d)\d{1,3}(?:[ \u00a0\u2009\u202f]\d{3})+(?:[.,]\d+)?(?!\d)")


@dataclass(frozen=True)
class Expected:
    """A number the answer must state, and the same number in other units."""

    value: float
    unit: str = ""
    also: tuple[tuple[float, str], ...] = ()  # (value, unit) pairs that count too

    def stated_in(self, text: str) -> bool:
        return any(states_number(text, value) for value in (self.value, *(v for v, _ in self.also)))

    def __str__(self) -> str:
        shown = _with_unit(self.value, self.unit)
        others = " or ".join(_with_unit(v, u) for v, u in self.also)
        return f"{shown} (or {others})" if others else shown


def _with_unit(value: float, unit: str) -> str:
    return (
        f"{format_number(value)}{unit}" if unit == "%" else f"{format_number(value)} {unit}".strip()
    )


@dataclass(frozen=True)
class Part:
    """One table cell the answer is based on."""

    table: str  # the table the expected number was read from
    accepted: tuple[str, ...]  # every table that holds exactly the same number
    labels: dict[str, str]  # which cell: {dimension label: category label}
    value: float


@dataclass(frozen=True)
class Question:
    id: str
    language: str
    level: str  # "easy", "medium" or "hard"
    question: str
    answers: tuple[Expected, ...]
    parts: tuple[Part, ...]
    how: str = ""  # how the answers follow from the parts, for people

    @property
    def expected_tables(self) -> str:
        return " + ".join(dict.fromkeys(part.table for part in self.parts))


@dataclass(frozen=True)
class Outcome:
    question: Question
    answer: Answer | None  # None if no answer could be given
    error: str  # why not, if so
    seconds: float
    stated: tuple[bool, ...] = field(init=False)  # for each expected number: stated?

    def __post_init__(self) -> None:
        text = self.answer.text if self.answer is not None else ""
        object.__setattr__(self, "stated", tuple(e.stated_in(text) for e in self.question.answers))

    @property
    def tables_used(self) -> list[str]:
        return [table.table_code for table in self.answer.tables] if self.answer else []

    @property
    def numbers_right(self) -> bool:
        return self.answer is not None and all(self.stated)

    @property
    def right_table(self) -> bool:
        used = set(self.tables_used)
        return self.answer is not None and all(used & set(p.accepted) for p in self.question.parts)

    @property
    def correct(self) -> bool:
        return self.numbers_right and self.right_table

    @property
    def verdict(self) -> str:
        if self.answer is None:
            return "error"
        if self.correct:
            return "right"
        return "other table" if self.numbers_right else "WRONG"

    @property
    def why(self) -> str:
        """Why the answer is not right, for people."""
        if self.answer is None:
            return self.error
        reasons = []
        missing = [str(e) for e, s in zip(self.question.answers, self.stated, strict=True) if not s]
        if missing and len(missing) < len(self.stated):
            found = [
                format_number(e.value)
                for e, s in zip(self.question.answers, self.stated, strict=True)
                if s
            ]
            reasons.append(f"states {', '.join(found)} but not {', '.join(missing)}")
        elif missing:
            reasons.append(
                "does not state " + " or ".join(missing)
                if len(missing) == 1
                else "states none of the expected numbers"
            )
        if not self.right_table:
            reasons.append(
                f"answered from {', '.join(self.tables_used)}, expected "
                + " and ".join(_tables_for(p) for p in _distinct_parts(self.question))
            )
        return "; ".join(reasons)


def _tables_for(part: Part) -> str:
    """The tables that hold a part's number, shortly: all of them when they are few."""
    if len(part.accepted) <= 3:
        return "/".join(part.accepted)
    return f"{part.table} (or {len(part.accepted) - 1} other tables with the same number)"


def _distinct_parts(question: Question) -> list[Part]:
    seen, parts = set(), []
    for part in question.parts:
        if part.accepted not in seen:
            seen.add(part.accepted)
            parts.append(part)
    return parts


def read_questions(path: Path) -> list[Question]:
    """The questions in a JSON Lines file."""
    questions = []
    with path.open(encoding="utf-8-sig") as lines:
        for number, line in enumerate(lines, 1):
            if not line.strip():
                continue
            try:
                questions.append(_question(json.loads(line)))
            except (ValueError, KeyError, TypeError, AttributeError) as e:
                raise ValueError(f"{path}, line {number}: not a question ({e})") from e
    return questions


def _question(raw: dict[str, Any]) -> Question:
    if "answers" not in raw:  # the earlier form: one table, one number
        table = str(raw["table"])
        value = float(raw["answer"])
        labels = {str(k): str(v) for k, v in raw.get("answer_is", {}).items()}
        return Question(
            str(raw["id"]),
            str(raw["language"]),
            "easy",
            str(raw["question"]),
            (Expected(value),),
            (Part(table, (table,), labels, value),),
        )
    answers = tuple(
        Expected(
            float(a["value"]),
            str(a.get("unit", "")),
            tuple((float(o["value"]), str(o.get("unit", ""))) for o in a.get("also", [])),
        )
        for a in raw["answers"]
    )
    parts = tuple(
        Part(
            str(p["table"]),
            tuple(str(t) for t in p.get("accepted", [p["table"]])),
            {str(k): str(v) for k, v in p.get("labels", {}).items()},
            float(p["value"]),
        )
        for p in raw["parts"]
    )
    if not answers or not parts:
        raise ValueError("a question needs at least one answer and one part")
    return Question(
        str(raw["id"]),
        str(raw["language"]),
        str(raw.get("level", "easy")),
        str(raw["question"]),
        answers,
        parts,
        str(raw.get("how", "")),
    )


def evaluate(
    pipeline: Pipeline,
    questions: Iterable[Question],
    on_outcome: Callable[[Outcome], None] = lambda outcome: None,
) -> list[Outcome]:
    """Answer every question; call ``on_outcome`` after each one."""
    outcomes = []
    for question in questions:
        started = time.perf_counter()
        answer, error = None, ""
        try:
            answer = pipeline.answer(question.question)
        except (AnswerError, ModelError, PxError, KeyError) as e:
            error = f"{type(e).__name__}: {e}"
        outcome = Outcome(question, answer, error, time.perf_counter() - started)
        on_outcome(outcome)
        outcomes.append(outcome)
    return outcomes


def states_number(text: str, expected: float) -> bool:
    """Whether ``text`` states ``expected``, possibly rounded to the digits it shows.

    Signs are not read: "fell by 1,032" states -1032 as well as 1032."""
    target = abs(expected)
    spaced = ["".join(number.split()) for number in _SPACED_NUMBER.findall(text)]
    for written in [*_NUMBER.findall(text), *spaced]:
        for value, decimals in _readings(written):
            if abs(value - target) <= 0.5 * 10**-decimals + 1e-9:
                return True
    return False


def _readings(written: str) -> list[tuple[float, int]]:
    """The values a number can stand for, read the English way (1,234.5) and the
    Icelandic way (1.234,5), each with how many decimals it shows."""
    readings = []
    for thousands, decimal in ((",", "."), (".", ",")):
        with suppress(ValueError):
            plain = written.replace(thousands, "")
            decimals = len(plain.split(decimal)[1]) if decimal in plain else 0
            readings.append((float(plain.replace(decimal, ".")), decimals))
    return readings


def format_number(value: float) -> str:
    """A number for people: thousands separated, at most four decimals."""
    if value == int(value) and abs(value) < 1e15:
        return f"{int(value):,}"
    return f"{value:,.4f}".rstrip("0").rstrip(".")


# --------------------------------------------------------------------------- the report
def outcome_line(outcome: Outcome) -> str:
    """One line for one answer."""
    q = outcome.question
    expected = " + ".join(format_number(e.value) for e in q.answers)
    if outcome.answer is None:
        return f"  {'error':<11} {q.level:<7} {q.id:<36} {outcome.error[:100]}"
    used = ", ".join(outcome.tables_used)
    tables = used if outcome.right_table else f"{used} (expected {q.expected_tables})"
    return (
        f"  {outcome.verdict:<11} {q.level:<7} {q.id:<36} expected {expected:<22} "
        f"from {tables:<28} {outcome.seconds:5.1f} s"
    )


def summary(outcomes: Sequence[Outcome]) -> list[str]:
    """The table of right answers by level and language."""
    languages = [code for code in LANGUAGES if any(o.question.language == code for o in outcomes)]
    others = sorted({o.question.language for o in outcomes} - set(LANGUAGES))
    columns = [(LANGUAGES.get(code, code), [code]) for code in languages + others]
    if len(columns) > 1:
        columns.append(("Together", languages + others))
    levels = [lvl for lvl in LEVELS if any(o.question.level == lvl for o in outcomes)]
    levels += sorted({o.question.level for o in outcomes} - set(LEVELS))

    def cell(level: str | None, codes: list[str]) -> str:
        group = [
            o
            for o in outcomes
            if o.question.language in codes and (level is None or o.question.level == level)
        ]
        return f"{sum(o.correct for o in group)} of {len(group)}" if group else "-"

    lines = [("Right answers  " + "".join(f"{name:<14}" for name, _ in columns)).rstrip()]
    for level in [*levels, None]:
        name = level or "all"
        row = f"  {name:<12} " + "".join(f"{cell(level, codes):<14}" for _, codes in columns)
        lines.append(row.rstrip())
    lucky = sum(o.verdict == "other table" for o in outcomes)
    if lucky:
        lines.append(
            f"  (and {lucky} right number{'s' if lucky != 1 else ''} from another table, "
            "not counted: see below)"
        )
    return lines


def not_right(outcomes: Sequence[Outcome]) -> list[str]:
    """For every answer that is not right: the question, what was expected, what was said."""
    lines = []
    for o in outcomes:
        if o.correct:
            continue
        q = o.question
        lines.append(f"  {q.id}  ({q.level})  {q.question}")
        lines.append(
            f"    expected  {' and '.join(str(e) for e in q.answers)}, from {q.expected_tables}"
            + (f": {q.how}" if q.how and q.level != "easy" else "")
        )
        if o.answer is not None:
            text = " ".join(o.answer.text.split())
            lines.append(f"    answer    {text[:220]}{'...' if len(text) > 220 else ''}")
        lines.append(f"    why       {o.why}")
    return lines


def save(outcomes: list[Outcome], path: Path) -> None:
    """Write the outcomes as JSON, to compare one run with another later."""
    path.parent.mkdir(parents=True, exist_ok=True)
    rows = [
        {
            "id": o.question.id,
            "language": o.question.language,
            "level": o.question.level,
            "question": o.question.question,
            "verdict": o.verdict,
            "correct": o.correct,
            "numbers_right": o.numbers_right,
            "right_table": o.right_table,
            "expected": [{"value": e.value, "unit": e.unit} for e in o.question.answers],
            "stated": list(o.stated),
            "expected_tables": [list(p.accepted) for p in o.question.parts],
            "tables": o.tables_used,
            "answer": o.answer.text if o.answer else None,
            "numbers": [f.text for f in o.answer.facts] if o.answer else [],
            "why": "" if o.correct else o.why,
            "error": o.error,
            "seconds": round(o.seconds, 2),
        }
        for o in outcomes
    ]
    path.write_text(
        json.dumps(rows, ensure_ascii=False, indent=1) + "\n", encoding="utf-8", newline="\n"
    )
