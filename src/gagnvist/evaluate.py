"""Measuring the starter kit: ask questions whose answers are known, and count.

A questions file has one question per line (JSON Lines), with the number the answer
should give, read from the table by the organizers:

    {"id": "population-reykjavik-en", "language": "en", "level": "basic",
     "question": "How many people live in Reykjavík?", "table": "MAN02005",
     "categories": {...}, "answer": 139804, "answer_is": {...}}

An answer counts as correct when it states that number, written plainly or with
thousands separators, in English or Icelandic style, and rounded to no fewer digits than
it shows ("4941210.9" is a correct way to write 4941210.9167). The table the question was
answered from is reported too, since a right number from another table is a lucky guess
more often than not.

``questions/examples.jsonl`` holds examples to start from. Write your own in the same
form, keep them, and evaluate after every change: that tells you whether it helped.
"""

from __future__ import annotations

import json
import re
import time
from collections.abc import Callable, Iterable
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from gagnvist.answering.pipeline import Answer, AnswerError, Pipeline
from gagnvist.data.px_reader import PxError
from gagnvist.models.client import ModelError

_NUMBER = re.compile(r"\d+(?:[.,]\d+)*")


@dataclass(frozen=True)
class Question:
    id: str
    language: str
    level: str  # "basic", or "harder": a known weak spot of the starter kit
    question: str
    table: str  # the table code the answer is in
    answer: float  # the number the answer should state
    answer_is: dict[str, str]  # what the number is: {dimension label: category label}


@dataclass(frozen=True)
class Outcome:
    question: Question
    answer: Answer | None  # None if no answer could be given
    error: str  # why not, if so
    seconds: float

    @property
    def correct(self) -> bool:
        return self.answer is not None and states_number(self.answer.text, self.question.answer)

    @property
    def right_table(self) -> bool:
        return self.answer is not None and self.answer.table.table_code == self.question.table


def read_questions(path: Path) -> list[Question]:
    """The questions in a JSON Lines file."""
    questions = []
    with path.open(encoding="utf-8-sig") as lines:
        for number, line in enumerate(lines, 1):
            if not line.strip():
                continue
            try:
                raw: dict[str, Any] = json.loads(line)
                questions.append(
                    Question(
                        id=str(raw["id"]),
                        language=str(raw["language"]),
                        level=str(raw.get("level", "basic")),
                        question=str(raw["question"]),
                        table=str(raw["table"]),
                        answer=float(raw["answer"]),
                        answer_is={str(k): str(v) for k, v in raw.get("answer_is", {}).items()},
                    )
                )
            except (ValueError, KeyError, TypeError, AttributeError) as e:
                raise ValueError(f"{path}, line {number}: not a question ({e})") from e
    return questions


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
    """Whether ``text`` states ``expected``, possibly rounded to the digits it shows."""
    for written in _NUMBER.findall(text):
        for value, decimals in _readings(written):
            if abs(value - expected) <= 0.5 * 10**-decimals + 1e-9:
                return True
    return False


def save(outcomes: list[Outcome], path: Path) -> None:
    """Write the outcomes as JSON, to compare one run with another later."""
    path.parent.mkdir(parents=True, exist_ok=True)
    rows = [
        {
            "id": o.question.id,
            "question": o.question.question,
            "expected": o.question.answer,
            "expected_table": o.question.table,
            "correct": o.correct,
            "right_table": o.right_table,
            "table": o.answer.table.table_code if o.answer else None,
            "answer": o.answer.text if o.answer else None,
            "numbers": [f.text for f in o.answer.facts] if o.answer else [],
            "error": o.error,
            "seconds": round(o.seconds, 2),
        }
        for o in outcomes
    ]
    path.write_text(json.dumps(rows, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")


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
