# Changing the cards or the embedding model

The search (step 1, see [how-it-works.md](how-it-works.md)) compares the question's
vector with the vectors of the tables' *cards*. Both are made by the same embedding
model. The cards come with the repository in `cards/`, in both languages (see
[cards/README.md](../cards/README.md)); the text of each is made by one function,
`card_text` in `src/gagnvist/search/vector_search.py`:

```python
def card_text(entry: CatalogueEntry, metadata: TableMetadata) -> str:
    """The card of a table: its title and the labels of its dimensions."""
    dimensions = ", ".join(d.label for d in metadata.dimensions)
    return f"{entry.title}. {dimensions}"
```

A vector index only works with the model that made it, and with the questions embedded
by that same model. So every change to the cards or the model means a new index. Keep
the shipped one in `index/`, and build yours in a folder of its own.

## Richer cards

1. Make new card texts, in a cards folder of your own. Either write the folder with a
   script (or by hand, or with a model): [cards/README.md](../cards/README.md) has an
   example. Or change `card_text`, for example to add the labels of a few categories,
   the years the table covers, or its dataset, and let `gagnvist build-cards` write
   the folder. Keep cards short: a card of a few hundred words says less, to an
   embedding model, than a card of a few dozen.
2. Point the starter kit to your cards and to a new index folder, in `.env` (not in
   `gagnvist.toml`, which `git pull` updates), and build the index there (a few
   minutes):

   ```bash
   GAGNVIST_SEARCH_INDEX=local/index-richer-cards
   GAGNVIST_SEARCH_CARDS=local/cards-richer
   ```

   ```bash
   gagnvist build-cards      # only if you changed card_text
   gagnvist build-vectors
   ```

3. Measure: `gagnvist evaluate`. To compare with the shipped index, remove the two
   lines from `.env` and evaluate once more.

## Another embedding model

1. Download it and serve it on LUMI (see [lumi.md](lumi.md)); on JURECA the same with
   `jureca` in place of `lumi`, and port 8812 instead of 8802 below (see
   [jureca.md, section 8](jureca.md#8-the-lumi-guides-read-for-jureca)):

   ```bash
   gagnvist lumi download intfloat/multilingual-e5-large
   gagnvist lumi start embeddings multilingual-e5-large
   gagnvist lumi connect --job <job id>          # leave it open
   ```

2. Put the lines that `connect` prints into `.env`:

   ```bash
   GAGNVIST_EMBEDDINGS_MODEL=multilingual-e5-large
   GAGNVIST_EMBEDDINGS_URL=http://127.0.0.1:8802/v1
   GAGNVIST_EMBEDDINGS_KEY=...
   ```

   and a new index folder:

   ```bash
   GAGNVIST_SEARCH_INDEX=local/index-e5
   ```

3. `gagnvist build-vectors`, then `gagnvist evaluate`.

   Keep the tunnel to the shared models open too (`gagnvist lumi connect`, in a terminal
   of its own): `ask` and `evaluate` still use the shared chat model. That makes three
   terminals: the shared models' tunnel, your embedding server's tunnel, and your work.

Some embedding models expect a word before every text: the e5 models, for example,
want `query: ` before a question and `passage: ` before a document. Add them to the
cards' texts and in `find_tables` (`answering/find_tables.py`), where the question is
embedded. The model's page on Hugging Face says what it expects. The shared model,
bge-m3, needs none.

`gagnvist ask` refuses an index made by another model than the one in the settings
(`[models] embeddings` in `gagnvist.toml`, or `GAGNVIST_EMBEDDINGS_MODEL` in `.env`),
since comparing vectors from two models gives nonsense.
