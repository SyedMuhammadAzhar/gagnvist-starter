# The table cards

A *card* describes one table in one language: its title, its dimensions and their
categories, the period it covers, and the short text the search embeds. There is one
card per table and language: 1,886 tables, each in Icelandic and in English, so 3,772
cards. They are made from the data release of 18 October 2026, and you can use them
without unpacking the data.

| File | Holds |
|---|---|
| `cards-is.jsonl` | the 1,886 Icelandic cards, one JSON object per line |
| `cards-en.jsonl` | the 1,886 English cards, in the same order: line *n* is the same table as line *n* of `cards-is.jsonl` |
| `cards.csv` | all 3,772 cards, one row each, without the categories |
| `pairs.csv` | the 1,886 tables, with the Icelandic and English codes, titles and folders side by side |

The two CSV files open in Excel, Numbers or LibreOffice. They are saved as UTF-8 with a
byte-order mark, so Icelandic letters show correctly.

## A card

The English card of MAN02005, with the categories cut short (the file has all of them):

```json
{
  "pair": "P0884",
  "language": "en",
  "table_code": "MAN02005",
  "title": "Population by municipality, age and sex 1998-2026 - Division into municipalites as of 1 January 2026",
  "other_language_title": "Mannfjöldi eftir kyni, aldri og sveitarfélögum 1998-2026 - Sveitarfélagaskipan 1. janúar 2026",
  "dataset": "Population",
  "subject_path": "mannfjoldi/2_byggdir/sveitarfelog",
  "period": {"dimension": "Year", "earliest": "1998", "latest": "2026", "count": 29},
  "dimensions": [
    {"code": "Sveitarfélag", "label": "Municipality", "is_time": false,
     "categories": [{"code": "9999", "label": "Total"}, {"code": "0000", "label": "Reykjavikurborg"}, "... 61 more"]},
    {"code": "Aldur", "label": "Age", "is_time": false, "categories": ["... 111 categories"]},
    {"code": "Ár", "label": "Year", "is_time": true, "categories": ["... 29 categories"]},
    {"code": "Kyn", "label": "Sex", "is_time": false, "categories": ["... 4 categories"]}
  ],
  "cells": 811188,
  "last_updated": "2026-03-12T08:57:08",
  "api_url": "https://px.hagstofa.is/pxen/api/v1/en/Ibuar/mannfjoldi/2_byggdir/sveitarfelog/MAN02005.px",
  "folder": "Population/en/mannfjoldi/2_byggdir/sveitarfelog/MAN02005",
  "other_language_folder": "Population/is/mannfjoldi/2_byggdir/sveitarfelog/MAN02005",
  "text": "Population by municipality, age and sex 1998-2026 - Division into municipalites as of 1 January 2026. Municipality, Age, Year, Sex"
}
```

| Field | What it is |
|---|---|
| `pair` | the same on a table's Icelandic and English card |
| `title` | Statistics Iceland's title for the table, in the card's language |
| `other_language_title` | the same table's title in the other language |
| `dataset` | Population, Society, Economy, Business_Sectors or Environment |
| `subject_path` | where the table sits in Statistics Iceland's API, below the dataset |
| `period` | the time the table covers: the time dimension's name, its earliest and latest period, and how many periods; `null` if the table has no time dimension |
| `dimensions` | every dimension with every category, codes and labels, as the API describes them; `is_time` is Statistics Iceland's own mark, which about half the tables have |
| `cells` | how many numbers the table holds |
| `folder` | the table's folder in the data; the program finds the table by it |
| `text` | what the search embeds: the title, then the dimension names |

## Where the values come from

- **Titles** are Statistics Iceland's, as its website lists them. Each was checked
  against the title inside the table's own px file, in the same language: they agree
  for all 3,772. Two things were repaired: runs of spaces are made one (190 titles),
  and six census titles (CEN0031 to CEN0033, in both languages) had a broken dash,
  which the API sends as a control character.
- **Dimensions and categories** are copied from each table's `metadata.json`.
- **The period** comes from the time dimension. It is recognised by its name (Year, Ár,
  Month, Mánuður, Quarter, Period, ...) in either language: when only one language's
  name is clear, as with "Tímabil" and "Season", both cards use it. The earliest and
  latest periods are found from the years in the labels. 3,254 cards have a period; 518
  have none, such as a census or a single election.
- **`text`** is made by `card_text` in `src/gagnvist/search/vector_search.py`.

## Both languages

Every table is here in both languages. Tables that Statistics Iceland publishes in only
one language are not in the data at all: the data's README lists the 89 left out, and
why. A few things are kept as Statistics Iceland publishes them:

- in 7 tables the code differs between the languages, e.g. VIN06101 in Icelandic is
  VIN08601 in English (`pairs.csv` shows both);
- SJA07002's English title is in Icelandic (its labels are in English);
- a few tables name a dimension differently in the two languages, or give it a
  placeholder name such as `stub1`.

## Richer cards

The search uses only `text`. To try richer cards, write them into a folder of your own
and build a new vector index from it. A script that adds the period to every text:

```python
import json
from pathlib import Path

source, target = Path("cards"), Path("local/cards-with-period")
target.mkdir(parents=True, exist_ok=True)
for language in ("is", "en"):
    with (source / f"cards-{language}.jsonl").open(encoding="utf-8") as cards, \
         (target / f"cards-{language}.jsonl").open("w", encoding="utf-8") as out:
        for line in cards:
            card = json.loads(line)
            if card["period"]:
                card["text"] += f". {card['period']['earliest']} to {card['period']['latest']}"
            out.write(json.dumps(card, ensure_ascii=False) + "\n")
```

Then point `gagnvist.toml` to the new cards and to a new index folder:

```toml
[search]
index = "local/index-with-period"
cards = "local/cards-with-period"
```

and run `gagnvist build-vectors` (a few minutes with the shared models connected),
then `gagnvist evaluate`. `build-vectors` reads only `folder`, `language` and `text`
from the two `.jsonl` files; keep `folder` as it is.

From Python, `read_cards` gives the cards as dictionaries:

```python
from pathlib import Path
from gagnvist.cards import read_cards

english = read_cards(Path("cards"), "en")
```

## Making them again

`gagnvist build-cards --replace` writes this folder again from the data (after
`gagnvist get-data`), for example after a change to `card_text`.
