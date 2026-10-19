"""Finding the tables whose description is closest to a question.

Every table has a short text, its *card*: its title and the names of its dimensions
(see :func:`card_text`). The cards were turned into vectors once, by the shared
embedding model on LUMI, and the result ships with this repository in ``index/``:

    index/manifest.json   which model made the vectors, when, and from which card recipe
    index/cards.jsonl     one card per line: {"folder": ..., "language": ..., "text": ...}
    index/vectors.npy     one row per card, in the same order, each scaled to length 1

A question is turned into a vector by the same model, and the cards closest to it are
found by cosine similarity: a dot product, since every vector has length 1.

Richer cards (category labels, synonyms, short descriptions) are one of the easiest
ways to improve the search; see docs/re-embedding.md.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Callable, Sequence
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import numpy.typing as npt

from gagnvist.data.catalogue import CatalogueEntry, TableMetadata
from gagnvist.search.table_index import TableIndex

log = logging.getLogger(__name__)

Vectors = npt.NDArray[np.float32]
Embed = Callable[[Sequence[str]], Vectors]

CARD_RECIPE = "title. dimension labels, comma separated"
_BATCH_SIZE = 64


@dataclass(frozen=True)
class Card:
    """The text that stands for one table (in one language) in the search."""

    folder: str
    language: str
    text: str


@dataclass(frozen=True)
class Match:
    card: Card
    score: float  # cosine similarity: 1 is identical, 0 unrelated


def card_text(entry: CatalogueEntry, metadata: TableMetadata) -> str:
    """The card of a table: its title and the labels of its dimensions."""
    dimensions = ", ".join(d.label for d in metadata.dimensions)
    return f"{entry.title}. {dimensions}"


def make_cards(tables: TableIndex) -> list[Card]:
    """The card of every table in the table database, in both languages."""
    return [
        Card(entry.folder, entry.language, card_text(entry, tables.metadata(entry.folder)))
        for entry in tables.entries()
    ]


class VectorIndex:
    """Cards and their vectors, searchable by a question's vector."""

    def __init__(self, cards: Sequence[Card], vectors: Vectors, model: str) -> None:
        if len(cards) != len(vectors):
            raise ValueError(f"{len(cards)} cards but {len(vectors)} vectors")
        self.cards = list(cards)
        self.vectors = _unit_length(vectors)
        self.model = model

    @classmethod
    def build(cls, cards: Sequence[Card], embed: Embed, model: str) -> VectorIndex:
        """Turn every card into a vector with ``embed``, in batches."""
        if not cards:
            raise ValueError("there are no cards to embed")
        batches = []
        for start in range(0, len(cards), _BATCH_SIZE):
            batches.append(embed([card.text for card in cards[start : start + _BATCH_SIZE]]))
            done = min(start + _BATCH_SIZE, len(cards))
            if len(batches) % 10 == 0 or done == len(cards):
                log.info("  embedded %s of %s cards", f"{done:,}", f"{len(cards):,}")
        return cls(cards, np.vstack(batches).astype(np.float32), model)

    @classmethod
    def load(cls, folder: Path) -> VectorIndex:
        manifest = json.loads((folder / "manifest.json").read_text(encoding="utf-8"))
        with (folder / "cards.jsonl").open(encoding="utf-8") as f:
            cards = [Card(**json.loads(line)) for line in f if line.strip()]
        vectors = np.load(folder / "vectors.npy").astype(np.float32)
        return cls(cards, vectors, manifest["model"])

    def save(self, folder: Path) -> None:
        folder.mkdir(parents=True, exist_ok=True)
        with (folder / "cards.jsonl").open("w", encoding="utf-8") as f:
            for card in self.cards:
                f.write(json.dumps(asdict(card), ensure_ascii=False) + "\n")
        np.save(folder / "vectors.npy", self.vectors)
        manifest = {
            "model": self.model,
            "cards": len(self.cards),
            "dimensions": int(self.vectors.shape[1]),
            "card_recipe": CARD_RECIPE,
            "created": datetime.now(UTC).isoformat(timespec="seconds"),
        }
        (folder / "manifest.json").write_text(
            json.dumps(manifest, indent=2) + "\n", encoding="utf-8"
        )

    def search(
        self, query: Vectors, *, limit: int = 10, language: str | None = None
    ) -> list[Match]:
        """The ``limit`` cards closest to ``query``, best first."""
        if limit < 1:
            raise ValueError(f"ask for at least one table, not {limit}")
        if query.shape[-1] != self.vectors.shape[1]:
            raise ValueError(
                f"the question's vector has {query.shape[-1]} numbers but the index uses "
                f"{self.vectors.shape[1]}: was it made by another embedding model "
                f"than {self.model}?"
            )
        scores = self.vectors @ _unit_length(query.reshape(1, -1))[0]
        order = np.argsort(-scores)
        matches = []
        for i in order:
            card = self.cards[int(i)]
            if language is None or card.language == language:
                matches.append(Match(card, float(scores[i])))
                if len(matches) == limit:
                    break
        return matches


def _unit_length(vectors: Vectors) -> Vectors:
    lengths = np.linalg.norm(vectors, axis=1, keepdims=True)
    lengths[lengths == 0] = 1.0
    return (vectors / lengths).astype(np.float32)
