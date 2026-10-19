# Questions with known answers

`gagnvist evaluate` answers every question in a file like
[examples.jsonl](examples.jsonl) and counts how many answers state the right number.
Each line is one question:

```json
{"id": "population-reykjavik-en", "language": "en", "level": "basic",
 "question": "How many people live in Reykjavík?",
 "table": "MAN02005",
 "categories": {"Sveitarfélag": "0000", "Aldur": "-1", "Ár": "2026", "Kyn": "0"},
 "answer": 139804,
 "answer_is": {"Municipality": "Reykjavikurborg", "Age": "Total", "Year": "2026", "Sex": "Total"}}
```

(In the file, each question is on a single line.)

| Field | Meaning |
|---|---|
| `id` | a short name, unique in the file |
| `language` | `is` or `en` |
| `level` | `basic`, or `harder` for a known weak spot of the starter kit |
| `question` | the question, as a user would ask it |
| `table` | the code of the table the answer is in |
| `categories` | the category code chosen in each dimension, to reach the number |
| `answer` | the number, read from the table |
| `answer_is` | the same choice, in labels, for people to read |

The answers in `examples.jsonl` were read from the data release with the starter kit's
own reader, and agree between the Icelandic and the English tables. An answer counts as
right when it states the number, rounded to no fewer digits than it shows.

To write your own: find the table with `gagnvist find-tables`, look at its dimensions
and categories (in the table database, or its `metadata.json`), and read the number
with Python:

```python
from pathlib import Path
from gagnvist.data.px_reader import PxFile
from gagnvist.search.table_index import TableIndex

tables = TableIndex(Path("local/tables.sqlite"))
entry = next(e for e in tables.entries("en") if e.table_code == "MAN02005")
table = PxFile(Path("data") / entry.folder / "data.px", tables.metadata(entry.folder))
print(table.read({"Sveitarfélag": "0000", "Aldur": "-1", "Ár": "2026", "Kyn": "0"}))
```

Keep some questions to yourselves, never look at how the system does on them while you
work, and measure on them at the end: questions you have tuned the system for say less
about how well it works.
