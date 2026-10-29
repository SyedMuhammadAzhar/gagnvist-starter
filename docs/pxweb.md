# Statistics Iceland's tables in ten minutes

Statistics Iceland (Hagstofa Íslands) publishes its statistics as tables, with software
called **PxWeb**: you can browse them at [px.hagstofa.is](https://px.hagstofa.is/), and
programs read them through PxWeb's API. The data release of the hackathon is a copy of
those tables, as the API gave them on 18 October 2026: 1,886 tables, each in an
Icelandic and an English edition.

## A table

Take *MAN02005, Population by municipality, age and sex 1998-2026*. It is split four
ways: by municipality, age, year and sex. Each way is a **dimension**, and each value of
a dimension is a **category**:

| Dimension | Categories |
|---|---|
| Municipality | Total, Reykjavikurborg, Kopavogsbaer, ... (63) |
| Age | Total, In 1st year, ..., 109 years (111) |
| Year | 1998, 1999, ..., 2026 (29) |
| Sex | Total, Males, Females, Non-binary/Other (4) |

The table holds one number for every combination: 63 × 111 × 29 × 4, about 810,000
numbers. To read one, choose one category of every dimension.

## Codes and labels

Every dimension and every category has a **code** and a **label**:

| | Code | Label (English) | Label (Icelandic) |
|---|---|---|---|
| dimension | `Sveitarfélag` | Municipality | Sveitarfélag |
| its category | `9999` | Total | Alls |
| its category | `0000` | Reykjavikurborg | Reykjavíkurborg |
| its category | `1000` | Kopavogsbaer | Kópavogsbær |

Labels are for people and differ between the two languages; codes are what programs
use, and are mostly the same in both. The API only understands codes, and so does the
starter kit: the language model sees both, and must answer with codes.

Some things to know:

- Codes are often Icelandic words, even in the English edition (`Sveitarfélag`, `Ár`).
- The English edition sometimes writes Icelandic names without Icelandic letters
  ("Reykjavikurborg", "Akureyrarbaer").
- The two editions of a table usually hold the same numbers, but not always: one may be
  rounded where the other is not (the building cost index for 2025 is 124.8811 in one
  edition and 124.9 in the other).
- Not every table has a "Total" category in every dimension, and some tables have
  several (one per year, for example).
- Units vary: people, kilograms, millions of krónur, percentages, index points. The
  unit is often a dimension of its own ("Unit", "Eining").

## Missing numbers

Where a table has no number, it writes a marker instead:

| Marker | Meaning |
|---|---|
| `..` | not available |
| `.` | not applicable |
| `-` | zero (read as 0) |
| `...` | no number; the files do not say why (used in a few tables, mostly for early years) |

## Look-alike tables

Statistics Iceland often publishes several tables about the same thing: a current
series and older ones that stop earlier (the building cost index exists both from 2010
to 2021 and from 2022 on), or the same figures by month and by year, or with different
splits. Their titles can be nearly the same. Choosing between them is one of the hard
parts of the hackathon.

## The files

The data comes with the repository, zipped in `data-release/`. `gagnvist get-data`
unpacks it into the data folder, `data/`, which holds:

- `catalogue.csv`: every table in both languages, one row each: dataset, language,
  table code, title, folder, the table's API address, when it was last updated, its
  number of cells, and the folder of the same table in the other language;
- a folder per table and language, `<dataset>/<is|en>/<API path>/<file name>/`, with
  (the file name is the table's name in the API, usually its code: `SAM07501e` and
  `SJA06100b` are two of the exceptions):
  - `metadata.json`: the table's description as the API gives it: the title (161 of
    the 3,772 tables have none), and every dimension with its code, label, and the codes and labels of its categories;
  - `data.px`: the numbers, in PxWeb's own file format: a header that lists the
    dimensions and categories, then the numbers, row by row;
- `README.md`: what the release contains, and which tables were left out and why;
- `SHA256SUMS.txt`: a checksum of every file (`gagnvist check-data` uses it).

### Corrections to the data's own README

`data/README.md` comes inside the data zip, which stays as it is so that everyone's copy
is the same. Five things in it are not right:

- **Encodings.** Of the 3,772 `data.px` files, 1,632 are UTF-8 (each with a byte-order
  mark), 1,336 ISO-8859-15, 795 Windows-1252, and 9 English tables declare GB18030 (their
  text is plain ASCII, so it reads the same). It says "mostly UTF-8".
- **Markers.** `-` is zero, and `...` is not "provisional": no file says what it means
  (see [Missing numbers](#missing-numbers)).
- **Pairs.** Not every pair holds the same figures: `catalogue.csv` pairs VIS06123 and
  VIS06125 by address, although their two editions are crossed. The cards pair them by
  content (see [cards/README.md](../cards/README.md#both-languages)).
- **`catalogue.csv`** has one more column than it lists: `pairing`, which says how each
  pair was confirmed.
- **Checking on Windows** is the command `gagnvist check-data`, not a script.

`gagnvist build-index` puts every table's description into one SQLite database,
`local/tables.sqlite`, which you can query yourself (see
`src/gagnvist/search/table_index.py` for its tables).

To see a table on the website, search for its code at
[px.hagstofa.is](https://px.hagstofa.is/). Its API address, in the catalogue and in
every answer's source, gives its description as JSON when opened in a browser.
