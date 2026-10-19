"""Searching the table cards by vector."""

from collections.abc import Sequence
from pathlib import Path

import numpy as np
import pytest

from gagnvist.data.catalogue import read_catalogue, read_metadata
from gagnvist.search.vector_search import Card, VectorIndex, Vectors, card_text

CARDS = [
    Card("a/is", "is", "Mannfjöldi"),
    Card("a/en", "en", "Population"),
    Card("b/en", "en", "Fish catch"),
]
VECTORS = np.array([[1.0, 0.0, 0.0], [0.9, 0.1, 0.0], [0.0, 0.0, 1.0]], dtype=np.float32)


def test_closest_card_comes_first() -> None:
    index = VectorIndex(CARDS, VECTORS, model="test")
    matches = index.search(np.array([1.0, 0.05, 0.0], dtype=np.float32), limit=3)
    assert [m.card.folder for m in matches] == ["a/is", "a/en", "b/en"]
    assert matches[0].score == pytest.approx(1.0, abs=0.01)


def test_search_can_keep_to_one_language() -> None:
    index = VectorIndex(CARDS, VECTORS, model="test")
    matches = index.search(np.array([1.0, 0.0, 0.0], dtype=np.float32), language="en")
    assert [m.card.folder for m in matches] == ["a/en", "b/en"]


def test_saved_index_loads_back(tmp_path: Path) -> None:
    VectorIndex(CARDS, VECTORS, model="bge-m3").save(tmp_path)
    loaded = VectorIndex.load(tmp_path)
    assert loaded.cards == CARDS
    assert loaded.model == "bge-m3"
    np.testing.assert_allclose(loaded.vectors, VectorIndex(CARDS, VECTORS, "x").vectors)


def test_a_vector_from_another_model_is_refused() -> None:
    index = VectorIndex(CARDS, VECTORS, model="bge-m3")
    with pytest.raises(ValueError, match="another embedding model"):
        index.search(np.ones(4, dtype=np.float32))


def test_build_embeds_every_card_in_batches() -> None:
    calls: list[int] = []

    def embed(texts: Sequence[str]) -> Vectors:
        calls.append(len(texts))
        return np.array([[len(t), 1.0] for t in texts], dtype=np.float32)

    cards = [Card(f"t{i}", "en", "x" * (i + 1)) for i in range(150)]
    index = VectorIndex.build(cards, embed, model="test")
    assert calls == [64, 64, 22]
    assert len(index.vectors) == 150


def test_card_text_is_title_and_dimensions(data_folder: Path) -> None:
    entry = next(
        e for e in read_catalogue(data_folder) if e.table_code == "KOS07112" and e.language == "en"
    )
    text = card_text(entry, read_metadata(data_folder, entry.folder))
    assert text.startswith(entry.title)
    assert text.endswith("Candidate and year of election, Unit, Constituency")
