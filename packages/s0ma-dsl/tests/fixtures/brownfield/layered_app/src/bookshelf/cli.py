"""The command line: one sub-command per job done at the counter."""

from __future__ import annotations

import argparse
import json
from datetime import date

from . import api
from .config import DATA_DIR, LIBRARY_NAME
from .errors import BookshelfError


def build_parser() -> argparse.ArgumentParser:
    """The parser behind ``python -m bookshelf``."""
    parser = argparse.ArgumentParser(
        prog="bookshelf",
        description=f"{LIBRARY_NAME} counter tools.",
    )
    parser.add_argument("--data-dir", default=DATA_DIR, help="where the JSON tables are kept")
    parser.add_argument("--today", default=None, help="the date to judge lateness against")
    commands = parser.add_subparsers(dest="command", required=True)

    commands.add_parser("list", help="list every title the library owns")

    add = commands.add_parser("add", help="add a title to the catalogue")
    add.add_argument("isbn")
    add.add_argument("title")
    add.add_argument("author")
    add.add_argument("--copies", type=int, default=1)

    borrow = commands.add_parser("borrow", help="lend a copy to a member")
    borrow.add_argument("isbn")
    borrow.add_argument("card_number")

    commands.add_parser("overdue", help="list the loans that are late")
    return parser


def main(argv: list[str] | None = None) -> int:
    """Run one counter command and print what it returned, as JSON."""
    args = build_parser().parse_args(argv)
    catalog, register = api.build_services(args.data_dir)
    today = date.fromisoformat(args.today) if args.today else date.today()
    try:
        if args.command == "list":
            result: object = api.list_titles(catalog)
        elif args.command == "add":
            result = api.add_title(catalog, args.isbn, args.title, args.author, args.copies)
        elif args.command == "borrow":
            result = api.borrow_title(register, args.isbn, args.card_number, today)
        else:
            result = api.overdue_report(register, today)
    except BookshelfError as error:
        print(json.dumps(api.describe_failure(error), indent=2, sort_keys=True))
        return 1
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0
