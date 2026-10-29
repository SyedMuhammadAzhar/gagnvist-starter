# Questions with known answers

`gagnvist evaluate` answers every question in [examples.jsonl](examples.jsonl) and tells
you which answers are right, which are not, and why. Evaluate after every change: that
tells you whether it helped.

There are 30 questions, each asked in English and in Icelandic (60 in all), ten at each
of three levels:

| Level | What the question needs | Per language | Example |
|---|---|---|---|
| `easy` | one number from one table | 10 | How many people lived in Reykjavík on 1 January 2026? |
| `medium` | a calculation with several numbers from the same table | 10 | By how many people did the population of Reykjavík grow from 1 January 2025 to 1 January 2026? |
| `hard` | numbers from two different tables | 10 | How many people lived in Iceland on 1 January 2026, and what was the consumer price index in September 2026? |

Even an easy question can be hard to find. Many tables look as if they answer "How many
people lived in Reykjavík on 1 January 2026?", but some give another number: the average
over a year, the population on 1 December, at the end of a quarter, in the urban area of
Reykjavík, or in Greater Reykjavík.

## Running it

```bash
gagnvist evaluate                          # all 60 questions
gagnvist evaluate --language is            # only the Icelandic ones (or --language en)
gagnvist evaluate --level easy             # one level; repeat it: --level medium --level hard
gagnvist evaluate --only reykjavik         # only the questions whose id contains this text
gagnvist evaluate my-questions.jsonl       # your own questions
```

For every question it prints one line: `right`, `WRONG`, `other table` (the right number,
but from a table that does not hold it: not counted as right) or `error` (no answer
could be given), with the table the answer came from and the expected number. Then the
right answers by level and language, and for every answer that is not right, the
question, the expected answer, what the answer said, and why it is not right. It looks
like this (n stands for your numbers):

```text
Right answers  English       Icelandic     Together
  easy         n of 10       n of 10       n of 20
  medium       n of 10       n of 10       n of 20
  hard         n of 10       n of 10       n of 20
  all          n of 30       n of 30       n of 60

Not right:
  population-and-cpi-2026-en  (hard)  How many people lived in Iceland on 1 January 2026, and ...
    expected  394,324 people and 697.3, from MAN00101 + VIS01000: both numbers
    answer    (what the answer said)
    why       states 394,324 but not 697.3; answered from MAN00101, expected MAN00101 (or 17 other tables with the same number) and VIS01000/VIS01002
```

Every run is saved in `local/evaluations/`, so that two runs can be compared.

## When an answer counts as right

An answer is right when it states **every** expected number, and the numbers come from
the right tables.

- **A number is stated** when the answer writes it plainly or with thousands separators,
  in English or Icelandic style or with spaces (139,804, 139.804 or 139 804), rounded to
  no fewer digits than it shows: 35.5% and 35% are right ways to write 35.454%, but
  35.46% is not, and "about 140,000" is not 139,804. Some questions also accept another
  unit: GDP in billions or trillions as well as millions of krónur.
- **The right tables**: every expected number comes from a table cell, and `accepted`
  lists every table that holds exactly that number in the same sense. For "How many
  people lived in Reykjavík on 1 January 2026?" these are the population table by
  municipality, the table of Reykjavík's districts, three more tables by municipality,
  and the table of immigrants in Reykjavík by district, which also gives the whole
  population of each district. An answer from any other table is not counted, even when
  it happens to state the number. Tables are named by their codes; two of the codes
  accepted (MAN05302 and MAN10001) also name other tables, which do not hold the number.
- **Hard questions** need both numbers and both tables. The starter kit answers from one
  table; if yours combines several, put the others in `Answer.extra_tables`
  (`answering/pipeline.py`) so that `evaluate` sees them.

## The file

Each line is one question:

```json
{"id": "reykjavik-growth-2026-en", "language": "en", "level": "medium",
 "question": "By how many people did the population of Reykjavík grow from 1 January 2025 to 1 January 2026?",
 "answers": [{"value": 1032.0, "unit": "people"}],
 "how": "Reykjavík on 1 January 2026 minus Reykjavík on 1 January 2025",
 "parts": [
  {"table": "MAN02005",
   "accepted": ["MAN02005", "MAN03270", "MAN04203", "MAN04208", "MAN12104", "MAN43006"],
   "categories": {"Sveitarfélag": "0000", "Aldur": "-1", "Ár": "2026", "Kyn": "0"},
   "labels": {"Municipality": "Reykjavikurborg", "Age": "Total", "Year": "2026", "Sex": "Total"},
   "value": 139804.0},
  {"table": "MAN02005",
   "accepted": ["MAN02005", "MAN03270", "MAN04203", "MAN04208", "MAN12104", "MAN43006"],
   "categories": {"Sveitarfélag": "0000", "Aldur": "-1", "Ár": "2025", "Kyn": "0"},
   "labels": {"Municipality": "Reykjavikurborg", "Age": "Total", "Year": "2025", "Sex": "Total"},
   "value": 138772.0}]}
```

(In the file, each question is on a single line.)

| Field | Meaning |
|---|---|
| `id` | a short name, unique in the file; the two languages share it, ending `-en` or `-is` |
| `language` | `is` or `en` |
| `level` | `easy`, `medium` or `hard` |
| `question` | the question, as a user would ask it |
| `answers` | every number the answer must state: `value`, `unit`, and `also` for the same number in other units |
| `how` | how the answer follows from the parts, or a note on look-alike tables |
| `parts` | the table cells the answer is based on: the `table`, the `accepted` tables, the category code chosen in each dimension (`categories`), the same choice in labels (`labels`), and the cell's `value` |

The category codes are those of the table in the question's language. They are often
the same in both languages, but not always: in the catch table SJA01101, Reykjavík is
place of landing 47 in English and 46 in Icelandic.

The earlier form of this file (one `table`, `categories`, `answer` and `answer_is` per
question) is read too, as easy questions.

## How the answers were checked

Every expected number was read from the data release in four ways, and all four had to
agree: with the starter kit's own reader in the English table and in the Icelandic table,
with a separately written reader, and from Statistics Iceland's live API (on 29 October
2026). Every calculated answer was computed again from those reads. The accepted tables
were found by searching the data in both languages for cells with the same number,
compared as numbers (394324 and 394324.00 are the same): in every table for numbers with
five or more significant digits, in the same part of the data (Population, Economy, ...)
for three or four, and in the same subject for shorter ones. A table was accepted only if
its cell, read by its labels, is the same thing: not the end of a quarter for 1 January,
not a projection, not an index labelled with another month. Where a question had more
than one answer in the data, its wording was made precise, for example by naming the
date.

## Writing your own

Write questions in the same form, and keep some to yourselves: never look at how the
system does on them while you work, and measure on them at the end. Questions you have
tuned the system for say less about how well it works.

To find the numbers: find the table with `gagnvist find-tables`, look at its dimensions
and categories (in the table database, or its `metadata.json`), and read the cell with
Python:

```python
from pathlib import Path
from gagnvist.data.px_reader import PxFile
from gagnvist.search.table_index import TableIndex

tables = TableIndex(Path("local/tables.sqlite"))
entry = next(e for e in tables.entries("en") if e.table_code == "MAN02005")
table = PxFile(Path("data") / entry.folder / "data.px", tables.metadata(entry.folder))
print(table.read({"Sveitarfélag": "0000", "Aldur": "-1", "Ár": "2026", "Kyn": "0"}))
```

Some table codes name two different tables (MAN10001, for example), so look a table up
by its folder when the code is not enough. A question needs at least `id`, `language`,
`question`, `answers` (with `value`) and `parts` (with `table` and `value`); `accepted`
defaults to the part's own table.
