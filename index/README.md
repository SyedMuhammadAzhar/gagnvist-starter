# The vector index

The tables' cards and their vectors, used by `gagnvist ask` and `gagnvist find-tables`
to find the tables closest to a question (see `src/gagnvist/search/vector_search.py`):

| File | Holds |
|---|---|
| `manifest.json` | which embedding model made the vectors, when, and from which card recipe |
| `cards.jsonl` | one card per line: the table's folder, its language and the card's text |
| `vectors.npy` | one vector per card, in the same order |

The organizers make it with the shared embedding model on LUMI and ship it here, so
that every team starts from the same index. If it is missing, make it yourself with
`gagnvist build-vectors` (a few minutes with the shared models connected).

An index only works with the embedding model that made it: a question must be embedded
by the same model as the cards. To try another model or richer cards, build a new index
in a folder of its own; see [docs/re-embedding.md](../docs/re-embedding.md).
