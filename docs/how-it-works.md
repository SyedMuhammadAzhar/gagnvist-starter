# How it works

`gagnvist ask` answers a question in four steps. Each step is one small module in
`src/gagnvist/answering/`, joined together in `pipeline.py`, and each is a place where
the starter kit can be made better. This page explains what each step does, where it is
weak, and some ideas for improving it.

```text
question
   │
   ▼  1. find_tables.py         the tables whose cards are closest to the question
table
   │
   ▼  2. choose_categories.py   the language model chooses categories; the code checks them
categories
   │
   ▼  3. read_numbers.py        the numbers, straight from the table's data.px
numbers
   │
   ▼  4. write_answer.py        the language model writes the answer from those numbers
answer + source + checks
```

Before the first step, the question's language is guessed (`language.py`): an Icelandic
question is answered from the Icelandic edition of the tables, in Icelandic, and an
English question from the English edition, in English.

## 1. Finding the table

**What it does.** Every table has a *card*: its title followed by the names of its
dimensions, for example *"Population by municipality, age and sex 1998-2026 ...
Municipality, Age, Year, Sex"*. The organizers turned every card into a vector with
the shared embedding model, once, and ship the result in `index/`. For a question, the
same model turns the question into a vector, and the cards closest to it (by cosine
similarity) are the candidates. The first one is used; `gagnvist ask --show-steps` and
`gagnvist find-tables` show the others.

**Where it is weak.**

- **Look-alike tables.** Statistics Iceland often publishes several tables with nearly
  the same title: a current series and an older one that stops earlier, or the same
  figures split in different ways. The closest card is then a coin toss. Asked for the
  building cost index in 2024, the search may well pick the older table that ends in
  2021. The program warns when the question names a year the table does not cover
  ("Check: the question names 2024, which this table does not cover").
- **What the card does not say.** A card names the dimensions, not their categories, so
  a question about *Reykjavík* or *cod* is matched only through words like
  *municipality* or *species*.

**Ideas.** Richer cards (category labels, the years covered, units); letting the
language model choose among the top candidates (*reranking*); combining the vector
search with keyword search; preferring tables that cover the period asked about;
asking the user back when two candidates look equally good. See
[re-embedding.md](re-embedding.md) for changing the cards or the embedding model.

## 2. Choosing the categories

**What it does.** A table holds one number for every combination of categories, one
from each dimension. The language model gets the question and the table's dimensions,
each category written as `code: label`, and answers in JSON with the codes it chose
(`models/prompts.py` has the exact prompt). The program then checks the answer
(`check_proposal`):

- codes the table does not have are dropped, with a note (a model often answers with a
  label where a code is expected);
- a dimension left without a choice gets a default: its total ("Total", "Alls"), or for
  a time dimension its latest period, or otherwise its first category;
- at most 50 numbers are read.

A dimension with more than 40 categories is shortened in the prompt: its first and last
five categories, and those whose labels name something the question names. Icelandic
inflects names ("Akureyri" in a question is "Akureyrarbær" in a table), so words that
begin alike count as the same.

**Where it is weak.** A category the question names in other words (*the capital* for
Reykjavík) may never be shown to the model. Questions that need a calculation (a sum,
a change from one year to another, a share) get the numbers, but no calculation.

**Ideas.** Search the categories with embeddings too; show the model more of a long
dimension when it is unsure; compute sums, changes and shares in code from the numbers
read, and give the results to the model as facts.

## 3. Reading the numbers

**What it does.** The chosen numbers are read from the table's `data.px`
(`data/px_reader.py`). No model is involved: the numbers are exactly the ones Statistics
Iceland published. A number the table does not give appears as a marker, which is
explained in the answer (`..` not available, `.` not applicable, `-` exactly zero).
This step is rarely the problem.

## 4. Writing the answer

**What it does.** The language model gets the question and the numbers as lines of
text (*"Municipality: Reykjavikurborg; Age: Total; Year: 2026; Sex: Total = 139804"*)
and writes one to three sentences, in the question's language, using only those
numbers. The program then adds the source (the table, its code, when it was updated and
its address), and two checks:

- every number in the answer that is not among the numbers read (or in the question)
  is reported, so that a number the model made up, or rounded, is caught;
- every year the question names that the table does not cover is reported.

**Ideas.** Write numbers the way each language does (139.804 in Icelandic, 139,804 in
English); give the model the unit of each number; answer "I don't know" when the checks
fail rather than show a doubtful answer.

## Measuring

`gagnvist evaluate` runs the whole pipeline on questions with known answers and counts
the right ones, and how many came from the right table (see the README). The second
number tells you whether to work on the search (step 1) or on the rest (steps 2 to 4).

## Beyond the starter kit

Real questions are often harder than one number from one table: comparisons between
places or years, figures from two tables put side by side, follow-up questions. The
starter kit answers none of these well, which leaves room for your own designs.
