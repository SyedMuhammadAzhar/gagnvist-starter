"""The ``gagnvist`` command: one entry point for every step of the starter kit.

Each sub-command only reads the settings, calls the library and prints the outcome;
the work itself lives in the packages (``gagnvist.data``, ``gagnvist.search``, ...), so
everything here can also be done from Python or a notebook.
"""

from __future__ import annotations

import argparse
import io
import logging
import sys
import time
from collections.abc import Callable, Sequence
from contextlib import closing
from pathlib import Path

import numpy as np

from gagnvist import __version__
from gagnvist.answering.find_tables import find_tables
from gagnvist.answering.language import guess_language
from gagnvist.answering.pipeline import Answer, AnswerError, Pipeline, open_vector_index
from gagnvist.cards import make_table_cards, save_cards, search_cards
from gagnvist.config import DEFAULT_CONFIG_FILE, ConfigError, Settings, load_settings
from gagnvist.data.download import CheckResult, DataError, check_data, get_data
from gagnvist.data.px_reader import PxError
from gagnvist.evaluate import evaluate, not_right, outcome_line, read_questions, save, summary
from gagnvist.lumi.cli import add_lumi_commands
from gagnvist.lumi.connection import LumiError
from gagnvist.models.client import ModelClient, ModelError
from gagnvist.search.table_index import TableIndex, build_index
from gagnvist.search.vector_search import VectorIndex

Command = Callable[[argparse.Namespace, Settings], int]


def main(argv: Sequence[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        if isinstance(stream, io.TextIOWrapper):  # never crash on a character a console lacks
            stream.reconfigure(errors="replace")
    logging.basicConfig(level=logging.WARNING, format="%(message)s")
    logging.getLogger("gagnvist").setLevel(logging.INFO)  # progress messages, not httpx's
    parser = _build_parser()
    args = parser.parse_args(argv)
    try:
        settings = load_settings(args.config)
        command: Command = args.command
        return command(args, settings)
    except (
        ConfigError,
        DataError,
        PxError,
        ModelError,
        AnswerError,
        LumiError,
        FileNotFoundError,
    ) as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    except PermissionError as e:
        print(
            f"error: {e}. If another program has the file open (an app of yours, a database "
            "viewer, a sync service such as OneDrive), close it and try again.",
            file=sys.stderr,
        )
        return 1
    except OSError as e:  # e.g. a full disk
        print(f"error: {e}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("stopped", file=sys.stderr)
        return 130


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="gagnvist",
        description="Answer questions in Icelandic or English from Statistics Iceland's tables.",
    )
    parser.add_argument("--version", action="version", version=f"gagnvist {__version__}")
    parser.add_argument(
        "--config",
        type=Path,
        default=DEFAULT_CONFIG_FILE,
        help="the shared settings (default: gagnvist.toml in the current folder; your "
        "personal settings are read from .env next to it)",
    )
    commands = parser.add_subparsers(title="commands", metavar="COMMAND", required=True)

    get = commands.add_parser("get-data", help="unpack the data and check every file")
    get.add_argument(
        "--zip", type=Path, help="use this data zip instead of the one in data-release/"
    )
    get.set_defaults(command=_get_data)

    check = commands.add_parser("check-data", help="check every data file against its checksum")
    check.set_defaults(command=_check_data)

    index = commands.add_parser(
        "build-index", help="build the local database of table descriptions"
    )
    index.set_defaults(command=_build_index)

    cards = commands.add_parser(
        "build-cards", help="write every table's card, in both languages, into the cards folder"
    )
    cards.add_argument(
        "--replace", action="store_true", help="replace the cards already in that folder"
    )
    cards.set_defaults(command=_build_cards)

    trial = commands.add_parser(
        "try-models", help="send one small request to the chat model and the embedding model"
    )
    trial.set_defaults(command=_try_models)

    vectors = commands.add_parser(
        "build-vectors", help="embed every table's card into a new vector index"
    )
    vectors.add_argument(
        "--replace", action="store_true", help="replace the index already in that folder"
    )
    vectors.set_defaults(command=_build_vectors)

    find = commands.add_parser("find-tables", help="list the tables closest to a question")
    find.add_argument("question")
    find.add_argument("--language", choices=["is", "en"], help="default: guessed from the question")
    find.add_argument("--limit", type=_positive, default=10, help="how many tables (default: 10)")
    find.set_defaults(command=_find_tables)

    ask = commands.add_parser("ask", help="answer a question from the tables")
    ask.add_argument("question")
    ask.add_argument("--language", choices=["is", "en"], help="default: guessed from the question")
    ask.add_argument(
        "--show-steps", action="store_true", help="also show the tables found and the choices made"
    )
    ask.set_defaults(command=_ask)

    check = commands.add_parser(
        "evaluate", help="answer questions with known answers, and count the right ones"
    )
    check.add_argument(
        "questions",
        nargs="?",
        type=Path,
        help="a .jsonl file of questions (default: questions/examples.jsonl)",
    )
    check.add_argument(
        "--language",
        choices=["is", "en"],
        help="only the questions in this language (default: both)",
    )
    check.add_argument(
        "--level",
        choices=["easy", "medium", "hard"],
        action="append",
        help="only the questions of this level; repeat it for several (default: all)",
    )
    check.add_argument("--only", help="only the questions whose id contains this text")
    check.set_defaults(command=_evaluate)

    add_lumi_commands(commands)
    return parser


def _get_data(args: argparse.Namespace, settings: Settings) -> int:
    zip_file: Path | None = args.zip
    if zip_file is not None and not zip_file.is_file():
        raise DataError(f"{zip_file} not found")
    result = get_data(
        settings.data.folder,
        archive=settings.data.archive,
        url=settings.data.download_url,
        sha256=settings.data.sha256,
        zip_file=zip_file,
    )
    return _report(result, settings.data.folder)


def _check_data(args: argparse.Namespace, settings: Settings) -> int:
    return _report(check_data(settings.data.folder), settings.data.folder)


def _build_index(args: argparse.Namespace, settings: Settings) -> int:
    settings.local_folder.mkdir(parents=True, exist_ok=True)
    count = build_index(settings.data.folder, settings.table_database)
    print(f"Indexed {count:,} tables into {settings.table_database}")
    return 0


def _build_cards(args: argparse.Namespace, settings: Settings) -> int:
    folder = settings.search.cards
    if (folder / "cards-is.jsonl").is_file() and not args.replace:
        raise ConfigError(
            f"{folder} already holds cards. Add GAGNVIST_SEARCH_CARDS=local/cards-mine (or "
            "another new folder) to .env, or add --replace to overwrite them"
        )
    cards = make_table_cards(settings.data.folder)
    save_cards(cards, folder)
    print(f"Wrote {len(cards):,} cards ({len(cards) // 2:,} tables in both languages) to {folder}")
    return 0


def _try_models(args: argparse.Namespace, settings: Settings) -> int:
    with closing(ModelClient.from_settings(settings)) as client:
        started = time.perf_counter()
        reply = client.chat(
            [{"role": "user", "content": "Say hello in Icelandic, in one short sentence."}],
            max_tokens=60,
        )
        seconds = time.perf_counter() - started
        print(f"Chat model {client.chat_endpoint.model} answered in {seconds:.1f} s: {reply}")

        texts = ["Mannfjöldi á Íslandi", "Population of Iceland"]
        started = time.perf_counter()
        first, second = client.embed(texts)
        seconds = time.perf_counter() - started
        similarity = float(first @ second / (np.linalg.norm(first) * np.linalg.norm(second)))
        print(
            f"Embedding model {client.embedding_endpoint.model} answered in {seconds:.1f} s: "
            f"{len(first)} numbers per text; {texts[0]!r} and {texts[1]!r} have "
            f"similarity {similarity:.2f}"
        )
    return 0


def _build_vectors(args: argparse.Namespace, settings: Settings) -> int:
    folder = settings.search.index
    if (folder / "manifest.json").is_file() and not args.replace:
        raise ConfigError(
            f"{folder} already holds a vector index. Add GAGNVIST_SEARCH_INDEX="
            "local/index-mine (or another new folder) to .env, or add --replace to "
            "overwrite it"
        )
    cards = search_cards(settings.search.cards)
    with closing(ModelClient.from_settings(settings)) as client:
        index = VectorIndex.build(cards, client.embed, client.embedding_endpoint.model)
    index.save(settings.search.index)
    print(f"Embedded {len(cards):,} cards with {index.model} into {settings.search.index}")
    return 0


def _find_tables(args: argparse.Namespace, settings: Settings) -> int:
    language = args.language or guess_language(args.question)
    vectors = open_vector_index(settings)
    with closing(ModelClient.from_settings(settings)) as client:
        matches = find_tables(args.question, language, vectors, client, limit=args.limit)
    with closing(TableIndex(settings.table_database)) as tables:
        for rank, match in enumerate(matches, 1):
            try:
                entry = tables.entry(match.card.folder)
            except KeyError:
                raise AnswerError(
                    f"the vector index lists {match.card.folder}, which the table database "
                    "does not have: was one of them made from another data release?"
                ) from None
            print(f"{rank:3}. {match.score:.3f}  {entry.table_code:<10}  {entry.title}")
    return 0


def _ask(args: argparse.Namespace, settings: Settings) -> int:
    with Pipeline.from_settings(settings) as pipeline:
        answer = pipeline.answer(args.question, args.language)
    if args.show_steps:
        _print_steps(answer)
    print(answer.text)
    print()
    print(f"Source: {answer.source}")
    print("Numbers used:")
    for fact in answer.facts:
        print(f"  {fact.text}")
    if answer.years_not_covered:
        print(
            f"Check: the question names {', '.join(answer.years_not_covered)}, "
            "which this table does not cover."
        )
    if answer.unsupported:
        print(
            f"Check: the answer mentions {', '.join(answer.unsupported)}, "
            "which the numbers read do not contain."
        )
    return 0


def _evaluate(args: argparse.Namespace, settings: Settings) -> int:
    path = args.questions or settings.project_folder / "questions" / "examples.jsonl"
    if not path.is_file():
        raise FileNotFoundError(f"{path} not found")
    try:
        questions = [
            q
            for q in read_questions(path)
            if (not args.only or args.only in q.id)
            and (not args.language or q.language == args.language)
            and (not args.level or q.level in args.level)
        ]
    except ValueError as e:
        raise ConfigError(str(e)) from None
    if not questions:
        print(f"No questions in {path} match the options given.")
        return 0
    plural = "s" if len(questions) != 1 else ""
    print(f"Answering {len(questions)} question{plural} from {path} ...")
    with Pipeline.from_settings(settings) as pipeline:
        outcomes = evaluate(pipeline, questions, lambda outcome: print(outcome_line(outcome)))
    print()
    for line in summary(outcomes):
        print(line)
    wrong = not_right(outcomes)
    if wrong:
        print()
        print("Not right:")
        for line in wrong:
            print(line)
    saved = settings.local_folder / "evaluations" / time.strftime("%Y-%m-%d-%H%M%S.json")
    save(outcomes, saved)
    print()
    print(f"Every answer is saved in {saved}")
    return 0


def _print_steps(answer: Answer) -> None:
    print(f"Language: {answer.language}")
    print("Tables found (the first is used):")
    for rank, match in enumerate(answer.candidates, 1):
        print(f"  {rank}. {match.score:.3f}  {match.card.text[:100]}")
    if answer.notes:
        print("Corrections to the model's choice of categories:")
        for note in answer.notes:
            print(f"  {note}")
    print()


def _positive(text: str) -> int:
    """An argparse type: a whole number of at least 1."""
    number = int(text)
    if number < 1:
        raise argparse.ArgumentTypeError(f"give a number of at least 1, not {number}")
    return number


def _report(result: CheckResult, folder: Path) -> int:
    if result.ok:
        print(f"The data in {folder} is complete: all {result.files_checked:,} files check out.")
        return 0
    print(f"The data in {folder} is NOT complete:")
    for name in result.missing[:10]:
        print(f"  missing: {name}")
    for name in result.damaged[:10]:
        print(f"  damaged: {name}")
    hidden = max(0, len(result.missing) - 10) + max(0, len(result.damaged) - 10)
    if hidden:
        print(f"  ... and {hidden:,} more")
    return 1
