"""Run a suite from a terminal: ``python -m harnesslib case-one case-two``."""

from __future__ import annotations

import argparse

from harnesslib.runner import run_suite


def main(argv: list[str] | None = None) -> int:
    """Parse the arguments, run the suite and print one line per case."""
    parser = argparse.ArgumentParser(prog="orchard", description="Run a suite of cases.")
    parser.add_argument("cases", nargs="*", help="the cases to run, in order")
    parser.add_argument("--suite", default="ad-hoc", help="a name for this run")
    args = parser.parse_args(argv)

    report = run_suite(args.suite, list(args.cases))
    for result in report["results"]:
        print(f"{result.case:<20} {result.outcome:<8} {result.seconds:>7.3f}s")
    print(f"{report['passed']} of {len(report['results'])} passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
