"""Measuring answers against questions with known answers."""

import json
from collections.abc import Iterator
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
import standin
from conftest import write_settings

from gagnvist.answering.pipeline import Pipeline
from gagnvist.cli import main
from gagnvist.evaluate import (
    LEVELS,
    Expected,
    Outcome,
    Part,
    Question,
    evaluate,
    not_right,
    read_questions,
    states_number,
    summary,
)
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
        ("It fell by 1,032.", -1032, True),  # signs are not read
        ("A share of 35.5%.", 35.45409358801392, True),
        ("A share of 35.46%.", 35.45409358801392, False),  # 35.454 rounds to 35.45
        # thousands set apart by spaces, as Icelandic is often written
        ("Verg landsframleiðsla var 4 941 210,91673494.", 4941210.91673494, True),
        ("Verg landsframleiðsla var 4 941 210,8.", 4941210.91673494, False),
        ("Árið 2026 bjuggu 139 804 manns í Reykjavík.", 139804, True),
        ("Árið 2026 bjuggu 139\u00a0804 manns í Reykjavík.", 139804, True),  # no-break space
        ("Árið 2026 bjuggu 139\u202f804 manns í Reykjavík.", 139804, True),  # narrow one
        ("Árið 2026 139 804 manns.", 139804, True),  # the year is not taken in
        ("Íbúum fjölgaði um 1 032.", -1032, True),
        ("Það voru 139 8040 manns.", 139804, False),  # groups of three digits only
    ],
)
def test_states_number(text: str, expected: float, states: bool) -> None:
    assert states_number(text, expected) is states


@pytest.mark.parametrize(
    ("text", "states"),
    [
        ("216,621,586 kg of cod were caught.", True),
        ("About 216,622 tonnes of cod were caught.", True),
        ("Alls veiddust 216.621,6 tonn af þorski.", True),
        ("About 217,000 tonnes of cod were caught.", False),
        ("216.6 thousand tonnes.", False),
    ],
)
def test_an_expected_number_counts_in_its_other_units(text: str, states: bool) -> None:
    cod = Expected(216621586, "kg", ((216621.586, "tonnes"),))
    assert cod.stated_in(text) is states


def test_the_example_questions_are_well_formed() -> None:
    questions = read_questions(EXAMPLES)
    assert len({q.id for q in questions}) == len(questions)
    assert {q.language for q in questions} == {"is", "en"}
    assert {q.level for q in questions} == set(LEVELS)
    by_topic: dict[str, list[Question]] = {}
    for q in questions:
        by_topic.setdefault(q.id.rsplit("-", 1)[0], []).append(q)
        assert all(part.table in part.accepted for part in q.parts)
        tables = {part.table for part in q.parts}
        if q.level == "easy":
            assert len(q.parts) == 1 and len(q.answers) == 1
            assert q.answers[0].value == q.parts[0].value
        elif q.level == "medium":
            assert len(q.parts) >= 2 and len(tables) == 1 and len(q.answers) == 1
        else:
            assert len(tables) >= 2
    for topic, pair in by_topic.items():
        assert sorted(q.language for q in pair) == ["en", "is"], topic
        english, icelandic = sorted(pair, key=lambda q: q.language)
        assert [a.value for a in english.answers] == [a.value for a in icelandic.answers], topic
        assert [p.value for p in english.parts] == [p.value for p in icelandic.parts], topic
        assert english.level == icelandic.level, topic
    for language in ("en", "is"):
        counts = {
            lvl: sum(q.language == language and q.level == lvl for q in questions) for lvl in LEVELS
        }
        assert counts["easy"] >= 10 and counts["medium"] >= 5 and counts["hard"] >= 5, counts


# Codes that name more than one table, accepted all the same: of the tables with the code,
# only one holds a cell with the expected number (MAN05302: births by months, not deaths by
# causes; MAN10001: populations by religious organizations, not the two quarterly tables).
SHARED_CODES = {"MAN05302", "MAN10001"}


def test_every_accepted_table_is_one_table_in_its_language() -> None:
    # Some codes name two or three different tables (MAN10001, for one); evaluate compares
    # codes, so a code the example questions accept must name exactly one table, unless only
    # one of its tables holds the number (SHARED_CODES).
    folders: dict[tuple[str, str], int] = {}
    for language in ("en", "is"):
        cards = Path(__file__).parents[1] / "cards" / f"cards-{language}.jsonl"
        for line in cards.read_text(encoding="utf-8").splitlines():
            key = (language, json.loads(line)["table_code"])
            folders[key] = folders.get(key, 0) + 1
    for q in read_questions(EXAMPLES):
        for part in q.parts:
            for code in part.accepted:
                count = folders.get((q.language, code), 0)
                assert count == 1 or (count > 1 and code in SHARED_CODES), (q.id, code)


def test_the_earlier_question_format_is_still_read() -> None:
    questions = {q.id: q for q in read_questions(QUESTIONS)}
    vigdis = questions["vigdis-1980-en"]
    assert vigdis.level == "easy"
    assert [a.value for a in vigdis.answers] == [15594]
    assert [(p.table, p.accepted) for p in vigdis.parts] == [("KOS07112", ("KOS07112",))]


def test_a_broken_questions_file_says_where(tmp_path: Path) -> None:
    broken = tmp_path / "questions.jsonl"
    broken.write_text('{"id": "x"}\n', encoding="utf-8")
    with pytest.raises(ValueError, match="line 1"):
        read_questions(broken)


# ------------------------------------------------------------------- verdicts
REYKJAVIK = Question(
    "population-reykjavik-en",
    "en",
    "easy",
    "How many people live in Reykjavík?",
    (Expected(139804, "people"),),
    (Part("MAN02005", ("MAN02005", "MAN03270"), {"Municipality": "Reykjavikurborg"}, 139804),),
)
TWO_TABLES = Question(
    "population-and-cpi-2026-en",
    "en",
    "hard",
    "How many people ..., and what was the CPI ...?",
    (Expected(394324, "people"), Expected(697.3, "index")),
    (Part("MAN00101", ("MAN00101",), {}, 394324), Part("VIS01000", ("VIS01000",), {}, 697.3)),
)


def _outcome(question: Question, text: str | None, *tables: str) -> Outcome:
    if text is None:
        return Outcome(question, None, "AnswerError: no table found", 0.5)
    entries = [SimpleNamespace(table_code=code) for code in tables]
    answer: Any = SimpleNamespace(text=text, table=entries[0], tables=tuple(entries), facts=[])
    return Outcome(question, answer, "", 1.0)


def test_a_right_number_from_an_accepted_table_is_right() -> None:
    outcome = _outcome(REYKJAVIK, "In 2026, 139,804 people lived in Reykjavík.", "MAN03270")
    assert outcome.correct and outcome.verdict == "right"


def test_a_right_number_from_another_table_is_not_counted() -> None:
    outcome = _outcome(REYKJAVIK, "139,804 people.", "MAN09000")
    assert not outcome.correct and outcome.numbers_right
    assert outcome.verdict == "other table"
    assert "answered from MAN09000, expected MAN02005/MAN03270" in outcome.why


def test_a_wrong_number_is_wrong_and_says_which() -> None:
    outcome = _outcome(REYKJAVIK, "About 140,000 people.", "MAN02005")
    assert outcome.verdict == "WRONG"
    assert outcome.why == "does not state 139,804 people"


def test_a_two_table_question_needs_both_numbers_and_both_tables() -> None:
    half = _outcome(TWO_TABLES, "394,324 people lived in Iceland.", "MAN00101")
    assert half.verdict == "WRONG"
    assert "states 394,324 but not 697.3 index" in half.why
    assert "expected MAN00101 and VIS01000" in half.why
    whole = _outcome(TWO_TABLES, "394,324 people; the index was 697.3.", "MAN00101", "VIS01000")
    assert whole.verdict == "right"
    lucky = _outcome(TWO_TABLES, "394,324 people; the index was 697.3.", "MAN00101")
    assert lucky.verdict == "other table"


def test_many_accepted_tables_are_named_shortly() -> None:
    many = Part("MAN00101", (*[f"MAN0{i}" for i in range(10)], "MAN00101"), {}, 394324)
    question = Question("q-en", "en", "easy", "?", (Expected(394324),), (many,))
    outcome = _outcome(question, "394,324", "SAM08004")
    assert outcome.why.endswith("expected MAN00101 (or 10 other tables with the same number)")


def test_an_answer_that_failed_is_an_error() -> None:
    outcome = _outcome(REYKJAVIK, None)
    assert outcome.verdict == "error" and not outcome.correct
    assert outcome.why == "AnswerError: no table found"


def test_the_summary_counts_by_level_and_language() -> None:
    icelandic = Question(
        "population-reykjavik-is",
        "is",
        "easy",
        "Hve margir búa í Reykjavík?",
        REYKJAVIK.answers,
        REYKJAVIK.parts,
    )
    outcomes = [
        _outcome(REYKJAVIK, "139,804", "MAN02005"),
        _outcome(icelandic, "140.000", "MAN02005"),
        _outcome(TWO_TABLES, "394,324", "MAN00101"),
    ]
    lines = summary(outcomes)
    assert lines[0].split() == ["Right", "answers", "English", "Icelandic", "Together"]
    assert lines[1].split() == ["easy", "1", "of", "1", "0", "of", "1", "1", "of", "2"]
    assert lines[2].split() == ["hard", "0", "of", "1", "-", "0", "of", "1"]
    assert lines[3].split() == ["all", "1", "of", "2", "0", "of", "1", "1", "of", "3"]
    wrong = "\n".join(not_right(outcomes))
    assert "population-reykjavik-is" in wrong and "population-and-cpi-2026-en" in wrong
    assert "population-reykjavik-en" not in wrong


# ------------------------------------------------------------------- with the pipeline
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
    assert "Right answers  English       Icelandic     Together" in printed
    assert "  all          1 of 1        1 of 1        2 of 2\n" in printed
    assert "Not right:" not in printed
    saved = list((tmp_path / "local" / "evaluations").glob("*.json"))
    assert len(saved) == 1
    rows = json.loads(saved[0].read_text(encoding="utf-8"))
    assert {row["verdict"] for row in rows} == {"right"}
    assert {row["level"] for row in rows} == {"easy"}


def test_the_evaluate_command_can_pick_a_language_and_a_level(
    pipeline: Pipeline,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    config = write_settings(tmp_path)
    monkeypatch.setattr(Pipeline, "from_settings", classmethod(lambda cls, settings: pipeline))
    assert main(["--config", str(config), "evaluate", str(QUESTIONS), "--language", "is"]) == 0
    printed = capsys.readouterr().out
    assert "Answering 1 question from" in printed and "vigdis-1980-is" in printed
    assert "vigdis-1980-en" not in printed
    assert main(["--config", str(config), "evaluate", str(QUESTIONS), "--level", "hard"]) == 0
    assert "No questions" in capsys.readouterr().out
