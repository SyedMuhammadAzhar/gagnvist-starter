"""From a question to an answer, in four steps:

1. :mod:`~gagnvist.answering.find_tables`: the tables closest to the question;
2. :mod:`~gagnvist.answering.choose_categories`: the model chooses the numbers needed,
   the code checks its choice against the table;
3. :mod:`~gagnvist.answering.read_numbers`: the numbers are read from the data file;
4. :mod:`~gagnvist.answering.write_answer`: the model writes the answer from them.

Each step is a small module; improve one at a time and measure the effect with
``gagnvist evaluate``.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from types import TracebackType

from gagnvist.answering.choose_categories import choose_categories, years_not_covered
from gagnvist.answering.find_tables import find_tables
from gagnvist.answering.language import guess_language
from gagnvist.answering.read_numbers import Fact, read_numbers
from gagnvist.answering.write_answer import unsupported_numbers, write_answer
from gagnvist.config import ConfigError, Settings
from gagnvist.data.catalogue import CatalogueEntry
from gagnvist.models.client import ModelClient
from gagnvist.search.table_index import TableIndex
from gagnvist.search.vector_search import Match, VectorIndex


class AnswerError(Exception):
    """The question could not be answered, for example because no table was found."""


@dataclass(frozen=True)
class Answer:
    question: str
    language: str  # "is" or "en": the language of the question and of the answer
    text: str  # the answer, as the model wrote it
    table: CatalogueEntry  # the table the numbers come from
    facts: list[Fact]  # the numbers read from it
    candidates: list[Match]  # the tables the search found, best first
    notes: list[str]  # what was corrected along the way
    unsupported: list[str]  # numbers in the answer that are not in the facts
    years_not_covered: list[str]  # years the question names that the table lacks

    @property
    def source(self) -> str:
        """Where the numbers come from, for a person to check."""
        return (
            f'Statistics Iceland, table {self.table.table_code} "{self.table.title}" '
            f"(updated {self.table.last_updated[:10]}): {self.table.api_url}"
        )


class Pipeline:
    """Everything needed to answer questions: the tables, the search and the models."""

    def __init__(
        self, data_folder: Path, tables: TableIndex, vectors: VectorIndex, client: ModelClient
    ) -> None:
        self.data_folder = data_folder
        self.tables = tables
        self.vectors = vectors
        self.client = client

    @classmethod
    def from_settings(cls, settings: Settings) -> Pipeline:
        return cls(
            settings.data.folder,
            TableIndex(settings.table_database),
            open_vector_index(settings),
            ModelClient.from_settings(settings),
        )

    def close(self) -> None:
        self.tables.close()
        self.client.close()

    def __enter__(self) -> Pipeline:
        return self

    def __exit__(
        self,
        kind: type[BaseException] | None,
        error: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self.close()

    def answer(self, question: str, language: str | None = None) -> Answer:
        """Answer ``question``; its language is guessed unless given ("is" or "en")."""
        language = language or guess_language(question)
        candidates = find_tables(question, language, self.vectors, self.client)
        if not candidates:
            raise AnswerError(f"the vector index has no tables in language {language!r}")
        try:
            table = self.tables.entry(candidates[0].card.folder)
        except KeyError:
            raise AnswerError(
                f"the vector index lists {candidates[0].card.folder}, which the table "
                "database does not have: was one of them made from another data release?"
            ) from None
        metadata = self.tables.metadata(table.folder)

        choice = choose_categories(question, table.title, metadata, self.client)
        facts = read_numbers(self.data_folder, table, metadata, choice.selection)
        text = write_answer(question, language, table.title, facts, self.client)

        sources = [question, table.title, *(fact.text for fact in facts)]
        return Answer(
            question=question,
            language=language,
            text=text,
            table=table,
            facts=facts,
            candidates=candidates,
            notes=choice.notes,
            unsupported=unsupported_numbers(text, sources),
            years_not_covered=years_not_covered(question, table.title, metadata),
        )


def open_vector_index(settings: Settings) -> VectorIndex:
    """The vector index named in the settings, checked against the embedding model.

    A question must be embedded by the model that embedded the cards: vectors from two
    different models cannot be compared, even when they have the same length.
    """
    folder = settings.search.index
    if not (folder / "manifest.json").is_file():
        raise ConfigError(
            f"no vector index in {folder}: it ships with the repository, or can be made "
            "with `gagnvist build-vectors` (see [search] index in gagnvist.toml)"
        )
    index = VectorIndex.load(folder)
    if index.model != settings.models.embeddings:
        raise ConfigError(
            f"the vector index in {folder} was made with the embedding model "
            f"{index.model!r}, but the settings use {settings.models.embeddings!r}: set "
            "[search] index in gagnvist.toml to a new folder and run `gagnvist "
            "build-vectors` to fill it"
        )
    return index
