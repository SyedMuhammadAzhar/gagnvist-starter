"""Step 1: find the tables that can answer the question.

The question is turned into a vector by the embedding model and compared with the
vector of every table's card, its title and dimension names (see
:mod:`gagnvist.search.vector_search`).

Ideas to improve this step:

- richer cards, for example with category labels or a short description
  (docs/re-embedding.md);
- let the language model choose among the top candidates (a reranker);
- combine with keyword search, for example SQLite's full-text search over titles;
- ask the user when the top candidates look alike (many tables share a title);
- prefer a table that covers the period the question names (see
  :func:`~gagnvist.answering.choose_categories.years_not_covered`).
"""

from __future__ import annotations

from gagnvist.models.client import ModelClient
from gagnvist.search.vector_search import Match, VectorIndex


def find_tables(
    question: str, language: str, index: VectorIndex, client: ModelClient, *, limit: int = 5
) -> list[Match]:
    """The tables in ``language`` whose cards are closest to the question, best first."""
    query = client.embed([question])[0]
    return index.search(query, limit=limit, language=language)
