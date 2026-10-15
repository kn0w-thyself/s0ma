"""Command-line entry point for the corner-shop stock script."""

from __future__ import annotations

import argparse

import inventory
import report

DEFAULT_STOCK = {"bread": 12, "milk": 4, "eggs": 30, "tea": 3}


def build_parser() -> argparse.ArgumentParser:
    """The argument parser this script is driven by."""
    parser = argparse.ArgumentParser(description="Corner-shop stock keeping.")
    parser.add_argument(
        "--add", nargs=2, metavar=("NAME", "QUANTITY"), action="append",
        default=[], help="add QUANTITY units of NAME",
    )
    parser.add_argument(
        "--remove", nargs=2, metavar=("NAME", "QUANTITY"), action="append",
        default=[], help="remove QUANTITY units of NAME",
    )
    return parser


def apply_changes(
    stock: dict[str, int],
    added: list[list[str]],
    removed: list[list[str]],
) -> dict[str, int]:
    """Apply every addition and then every removal, in the order given."""
    for name, quantity in added:
        stock = inventory.add_item(stock, name, int(quantity))
    for name, quantity in removed:
        stock = inventory.remove_item(stock, name, int(quantity))
    return stock


def main(argv: list[str] | None = None) -> int:
    """Print a stock report once the requested changes have been applied."""
    args = build_parser().parse_args(argv)
    stock = apply_changes(dict(DEFAULT_STOCK), args.add, args.remove)
    print(report.render(stock))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
