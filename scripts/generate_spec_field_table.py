#!/usr/bin/env python3
"""Render the DSL spec's field table from the toolchain's own classification.

Section 4.14.5 of the current DSL specification is the one statement of which
lines each declaration must write and which states each line accepts. The
table between its markers is rendered here from
``s0ma_dsl.semantic_state.FIELD_CLASSIFICATIONS`` (the machine twin of the
0.14.0 schema-and-surface-budget contract, section 3), so the specification
and the check cannot say two different things.

Default mode is a read-only gate: it exits 1 and names the fix when the
committed table differs from the render. Pass ``--write`` after a deliberate
change to the classification, review the diff, and commit the classification,
the spec and the spec's packaged copy together.
``packages/s0ma-dsl/tests/test_doc_consistency.py`` asserts the same equality
on every test run.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from s0ma_dsl.semantic_state import (
    FIELD_CLASSIFICATIONS,
    FIELD_SOURCE_NAMES,
    FieldClassification,
)

ROOT = Path(__file__).resolve().parent.parent
SPEC_DIR = ROOT / "packages/s0ma-dsl/docs"
PACKAGED_DIR = ROOT / "packages/s0ma-mcp/src/s0ma_mcp/_docs"

START = "<!-- BEGIN GENERATED FIELD TABLE: scripts/generate_spec_field_table.py -->"
END = "<!-- END GENERATED FIELD TABLE -->"

#: How the table names a declaration kind whose key is not its written keyword.
LABELS: dict[str, str] = {
    "axon": "standalone axon",
    "doc_ref": "doc-ref",
    "doc_guide": "doc-guide",
}

#: The semantic-required columns, by the states a field accepts.
SR_COLUMNS: tuple[tuple[str, ...], ...] = (("V",), ("V", "P"), ("V", "N", "P"))

HEADER = "| Declaration | SR / V | SR / V,P | SR / V,N,P | SC | PO | D |"
RULE = "|---|---|---|---|---|---|---|"


class GenerationError(RuntimeError):
    """The classification or the spec's markers are not what the table expects."""


def _states(row: FieldClassification) -> tuple[str, ...]:
    allowed = (("V", row.allow_value), ("N", row.allow_none), ("P", row.allow_pending))
    return tuple(letter for letter, ok in allowed if ok)


def _name(declaration: str, field: str) -> str:
    """The field as a person writes it, with the IR's name when that differs."""

    written = FIELD_SOURCE_NAMES.get((declaration, field), field)
    if written == field:
        return f"`{field}`"
    return f"`{written}` (IR: `{field}`)"


def _cell(items: list[str], separator: str = ", ") -> str:
    return separator.join(items).replace("|", "\\|") if items else "—"


def render_table() -> str:
    """The Markdown table section 4.14.5 carries between its markers."""

    lines = [HEADER, RULE]
    for declaration, rows in FIELD_CLASSIFICATIONS.items():
        required: dict[tuple[str, ...], list[str]] = {column: [] for column in SR_COLUMNS}
        conditional: list[str] = []
        presentation: list[str] = []
        derived: list[str] = []
        for field, row in rows.items():
            name = _name(declaration, field)
            states = _states(row)
            if row.field_class == "semantic-required-state":
                if states not in required:
                    raise GenerationError(
                        f"{declaration}.{field} is semantic-required with states "
                        f"{','.join(states)}, which no column of the table holds; "
                        "decide where it belongs and extend SR_COLUMNS deliberately"
                    )
                required[states].append(name)
            elif row.field_class == "semantic-conditional-state":
                conditional.append(f"{name} {','.join(states)} ({row.applicability})")
            elif row.field_class == "presentation-optional":
                presentation.append(name)
            elif row.field_class == "derived":
                derived.append(name)
            else:
                raise GenerationError(
                    f"{declaration}.{field} has field class {row.field_class!r}, "
                    "which the table does not know"
                )
        cells = [
            LABELS.get(declaration, declaration),
            *(_cell(required[column]) for column in SR_COLUMNS),
            _cell(conditional, "; "),
            _cell(presentation),
            _cell(derived),
        ]
        lines.append("| " + " | ".join(cells) + " |")
    return "\n".join(lines)


def spec_path() -> Path:
    """The one spec file that carries the markers."""

    carriers = [
        path
        for path in sorted(SPEC_DIR.glob("s0ma-dsl-spec-v*.md"))
        if START in path.read_bytes().decode("utf-8")
    ]
    if len(carriers) != 1:
        found = ", ".join(path.name for path in carriers) or "none"
        raise GenerationError(
            f"expected exactly one spec under {SPEC_DIR} carrying the field-table "
            f"markers, found: {found}"
        )
    return carriers[0]


def with_table(text: str, table: str) -> str:
    """``text`` with the region between the markers replaced by ``table``."""

    if text.count(START) != 1 or text.count(END) != 1:
        raise GenerationError("the spec must carry each field-table marker exactly once")
    head, rest = text.split(START, 1)
    _old, tail = rest.split(END, 1)
    return f"{head}{START}\n{table}\n{END}{tail}"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--write",
        action="store_true",
        help="rewrite the table in the spec and in its packaged copy",
    )
    args = parser.parse_args(argv)

    spec = spec_path()
    current = spec.read_bytes().decode("utf-8")
    expected = with_table(current, render_table())
    shown = spec.relative_to(ROOT).as_posix()
    if current == expected:
        print(f"{shown}: the field table matches FIELD_CLASSIFICATIONS.")
        return 0
    if not args.write:
        print(
            f"{shown}: the field table differs from FIELD_CLASSIFICATIONS. "
            "Run `uv run python scripts/generate_spec_field_table.py --write`, "
            "review the diff, and commit it with the classification.",
            file=sys.stderr,
        )
        return 1
    spec.write_bytes(expected.encode("utf-8"))
    packaged = PACKAGED_DIR / spec.name
    if packaged.exists():
        packaged.write_bytes(expected.encode("utf-8"))
    print(f"{shown}: field table rewritten (and its packaged copy, if present).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
