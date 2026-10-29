"""Answering questions end to end, with the stand-in models and the miniature data."""

import unicodedata
from collections.abc import Iterator
from pathlib import Path

import numpy as np
import pytest
import standin
from conftest import write_settings

from gagnvist.answering.pipeline import Pipeline, open_vector_index
from gagnvist.config import ConfigError, load_settings
from gagnvist.data.catalogue import read_metadata
from gagnvist.data.px_reader import PxFile
from gagnvist.models.client import ModelClient
from gagnvist.search.table_index import TableIndex
from gagnvist.search.vector_search import Card, VectorIndex, make_cards

ELECTIONS_EN = "Population/en/kosningar/forsetakosningar/KOS07112"
ELECTIONS_IS = "Population/is/kosningar/forsetakosningar/KOS07112"


@pytest.fixture
def pipeline(
    data_folder: Path, table_database: Path, standin_client: ModelClient
) -> Iterator[Pipeline]:
    tables = TableIndex(table_database)
    vectors = VectorIndex.build(make_cards(tables), standin_client.embed, standin.EMBEDDING_MODEL)
    with Pipeline(data_folder, tables, vectors, standin_client) as opened:
        yield opened


def published_number(data_folder: Path, folder: str, selection: dict[str, str]) -> float | None:
    """The number as data.px holds it, read without the pipeline."""
    return (
        PxFile(data_folder / folder / "data.px", read_metadata(data_folder, folder))
        .read(selection)
        .value
    )


def test_an_english_question_is_answered_from_the_english_table(
    pipeline: Pipeline, data_folder: Path
) -> None:
    answer = pipeline.answer(
        "Results of the presidential election 1980: "
        "how many valid votes did Vigdís Finnbogadóttir get in Reykjavík?"
    )
    assert answer.language == "en"
    assert answer.table.folder == ELECTIONS_EN
    votes = published_number(
        data_folder,
        ELECTIONS_EN,
        {"Candidate and year of election": "11", "Unit": "0", "Constituency": "1"},
    )
    assert [fact.cell.value for fact in answer.facts] == [votes]
    assert answer.facts[0].text.startswith(
        "Candidate and year of election: Vigdís Finnbogadóttir 1980; "
        "Unit: Number valid votes; Constituency: Reykjavík = "
    )
    assert str(int(votes or 0)) in answer.text
    assert answer.unsupported == []
    assert answer.years_not_covered == []  # 1980 is in the candidates' labels
    assert "KOS07112" in answer.source and "px.hagstofa.is/pxen/api/v1" in answer.source


def test_the_icelandic_question_gets_the_same_number_from_the_icelandic_table(
    pipeline: Pipeline,
) -> None:
    english = pipeline.answer(
        "Results of the presidential election 1980: "
        "how many valid votes did Vigdís Finnbogadóttir get in Reykjavík?"
    )
    icelandic = pipeline.answer(
        "Úrslit forsetakjörs 1980: hve mörg gild atkvæði fékk Vigdís Finnbogadóttir í Reykjavík?"
    )
    assert icelandic.language == "is"
    assert icelandic.table.folder == ELECTIONS_IS
    assert icelandic.facts[0].text.startswith("GIld atkvæði: Fjöldi; Frambjóðendur: Vigdís")
    assert [f.cell for f in icelandic.facts] == [f.cell for f in english.facts]


def test_a_question_with_decomposed_letters_is_read_like_any_other(pipeline: Pipeline) -> None:
    # Text pasted on a Mac can write í as i followed by a combining accent.
    question = (
        "Úrslit forsetakjörs 1980: hve mörg gild atkvæði fékk Vigdís Finnbogadóttir í Reykjavík?"
    )
    answer = pipeline.answer(unicodedata.normalize("NFD", question))
    assert answer.question == question and answer.language == "is"
    assert answer.table.folder == ELECTIONS_IS


def test_dimensions_the_question_leaves_out_get_their_defaults(pipeline: Pipeline) -> None:
    answer = pipeline.answer("Results of presidential elections: Vigdís Finnbogadóttir 1980")
    chosen = {d.code: c.label for d, c in answer.facts[0].categories}
    assert chosen["Constituency"] == "Whole Country"
    assert "Constituency: no category chosen, using 'Whole Country'" in answer.notes


def test_language_can_be_given(pipeline: Pipeline) -> None:
    answer = pipeline.answer("Vigdís Finnbogadóttir 1980", language="is")
    assert answer.table.language == "is"


def config_with(tmp_path: Path, index: Path, embeddings: str) -> Path:
    return write_settings(
        tmp_path,
        changes={'index = "index"': f'index = "{index.as_posix()}"',
                 'embeddings = "bge-m3"': f'embeddings = "{embeddings}"'},
    )  # fmt: skip


def test_a_missing_vector_index_is_explained(tmp_path: Path) -> None:
    settings = load_settings(config_with(tmp_path, tmp_path / "nothing", "bge-m3"))
    with pytest.raises(ConfigError, match="no vector index"):
        open_vector_index(settings)


def test_an_index_from_another_embedding_model_is_refused(tmp_path: Path) -> None:
    folder = tmp_path / "index"
    VectorIndex([Card("a", "en", "x")], np.ones((1, 2), dtype=np.float32), "model-a").save(folder)
    settings = load_settings(config_with(tmp_path, folder, "model-b"))
    with pytest.raises(ConfigError, match=r"'model-a', but the settings use 'model-b'"):
        open_vector_index(settings)


def test_a_year_the_table_does_not_cover_is_reported(pipeline: Pipeline) -> None:
    answer = pipeline.answer("Results of presidential elections: Vigdís Finnbogadóttir 2024")
    assert answer.table.folder == ELECTIONS_EN  # covers 1952-1996 only
    assert answer.years_not_covered == ["2024"]
