"""Measuring answers against questions with known answers."""

from collections.abc import Iterator
from pathlib import Path

import pytest
import standin
from conftest import write_settings

from gagnvist.answering.pipeline import Pipeline
from gagnvist.cli import main
from gagnvist.evaluate import evaluate, read_questions, states_number
from gagnvist.models.client import ModelClient
from gagnvist.search.table_index import TableIndex
from gagnvist.search.vector_search import VectorIndex, make_cards

QUESTIONS = Path(__file__).parent / "fixtures" / "questions.jsonl"
EXAMPLES = Path(__file__).parents[1] / "questions" / "examples.jsonl"


@pytest.mark.parametrize(
    ("text", "expected", "states"),
    [
        ("In 2026, 139804 people lived in Reykjavík.", 139804, True),
        ("In 2026, 139,804 people lived in Reykjavík.", 139804, True),
        ("Árið 2026 bjuggu 139.804 manns í Reykjavík.", 139804, True),
        ("About 140,000 people live in Reykjavík.", 139804, False),
        ("GDP was 4,941,210.9 million ISK.", 4941210.91673494, True),  # rounded, correctly
        ("GDP was 4941211 million ISK.", 4941210.91673494, True),
        ("GDP was 4941210.8 million ISK.", 4941210.91673494, False),  # wrongly rounded
        ("Atvinnuleysi var 6,5%.", 6.5, True),
        ("The index was 119.8.", 119.7724, True),
        ("The index was 119.7.", 119.7724, False),
    ],
)
def test_states_number(text: str, expected: float, states: bool) -> None:
    assert states_number(text, expected) is states


def test_the_example_questions_are_well_formed() -> None:
    questions = read_questions(EXAMPLES)
    assert len(questions) >= 20
    assert len({q.id for q in questions}) == len(questions)
    assert {q.language for q in questions} == {"is", "en"}
    by_topic: dict[str, set[float]] = {}
    for question in questions:
        by_topic.setdefault(question.id.rsplit("-", 1)[0], set()).add(question.answer)
    assert all(len(answers) == 1 for answers in by_topic.values())  # same number in both languages


def test_a_broken_questions_file_says_where(tmp_path: Path) -> None:
    broken = tmp_path / "questions.jsonl"
    broken.write_text('{"id": "x"}\n', encoding="utf-8")
    with pytest.raises(ValueError, match="line 1"):
        read_questions(broken)


@pytest.fixture
def pipeline(
    data_folder: Path, table_database: Path, standin_client: ModelClient
) -> Iterator[Pipeline]:
    tables = TableIndex(table_database)
    vectors = VectorIndex.build(make_cards(tables), standin_client.embed, standin.EMBEDDING_MODEL)
    with Pipeline(data_folder, tables, vectors, standin_client) as opened:
        yield opened


def test_evaluate_counts_right_answers_and_right_tables(pipeline: Pipeline) -> None:
    outcomes = evaluate(pipeline, read_questions(QUESTIONS))
    by_id = {o.question.id: o for o in outcomes}
    assert by_id["vigdis-1980-en"].correct and by_id["vigdis-1980-en"].right_table
    assert by_id["vigdis-1980-is"].correct and by_id["vigdis-1980-is"].right_table
    assert all(o.error == "" for o in outcomes)


def test_the_evaluate_command_prints_a_summary_and_saves_the_answers(
    pipeline: Pipeline,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    config = write_settings(tmp_path)
    monkeypatch.setattr(Pipeline, "from_settings", classmethod(lambda cls, settings: pipeline))
    assert main(["--config", str(config), "evaluate", str(QUESTIONS), "--only", "vigdis"]) == 0
    printed = capsys.readouterr().out
    assert "Correct answers: 2 of 2 (100%)" in printed
    saved = list((tmp_path / "local" / "evaluations").glob("*.json"))
    assert len(saved) == 1
