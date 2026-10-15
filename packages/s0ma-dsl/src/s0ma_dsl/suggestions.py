"""Corrected-declaration rendering for self-healing contract diagnostics.

Batch-01c 0.13.0 M1. The cold-session anatomy measured 38/72 cold
``check`` calls failing on self-inflicted declaration mismatches
(``PROVIDES_KEY_MISMATCH`` / ``MISSING_PACKAGE``), each triggering a
2–6-turn guess-and-retry loop. The checker already computes the
declared-vs-actual sets it needs to *name* the mismatch; this module
turns those same sets into a **ready-to-paste corrected declaration
block** so the agent does not have to guess the fix.

Two invariants keep the suggestions honest:

* **Correct by construction.** Every renderer here consumes the exact
  resolved-actual values the checker used (a nerve's literal return-dict
  keys; a module's importable ``requires:`` remainder) — never a heuristic
  string edit of the author's text. Pasting a rendered block over the
  named declaration and re-checking clears that diagnostic class.
* **One canonical rendering.** The flat ``provides: [a, b]`` /
  ``requires: [...]`` inline forms are rendered here and nowhere else, so
  a suggested block reads in the DSL's own surface style (matching the
  ``provides: [...]`` form the diagnostics already quote). Callers that
  cannot render a *certain* block (a structured ``provides:`` triple, a
  ``requires:`` entry that actually names a s0ma module) must fall back
  to an explicit "cannot suggest" note rather than fabricate one — a
  wrong verbatim block is worse than none.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Iterable

    from s0ma_dsl.ast_nodes.nodes import RequiresEntry


def render_provides_block(names: Iterable[str]) -> str:
    """Render a flat ``provides:`` declaration block for *names*.

    Matches the canonical inline surface the validator's diagnostics
    already quote (``provides: [op_a, op_b]``). The caller passes the
    body's actual literal return-dict keys, so the rendered block, pasted
    over the nerve's ``provides:`` line, makes the declaration match the
    body exactly.
    """
    return f"provides: [{', '.join(names)}]"


def render_requires_entry(entry: RequiresEntry) -> str:
    """Render one :class:`RequiresEntry` back to its canonical source form.

    Round-trips through :func:`s0ma_dsl.parser.s0ma_parser._build_requires`
    to the same ``RequiresEntry`` (module_path / alias / is_from_import):

    * a plain import renders as the dotted ``module_path``;
    * a from-import with a capitalised final segment renders dotted
      (the parser's capitalisation heuristic re-derives the from-import,
      matching the common ``uuid.UUID`` author style);
    * any other from-import (a lowercased final segment — an explicit
      ``pkg:name`` colon override or a known-from-import like
      ``dataclasses.dataclass``) renders in the unambiguous colon form
      ``pkg:name`` so the from-import survives the round-trip.

    An ``alias`` appends `` as <alias>`` in every form.
    """
    if entry.is_from_import:
        pkg, _, name = entry.module_path.rpartition(".")
        # A capitalised final segment round-trips via the parser's
        # heuristic (``uuid.UUID``); anything else needs the explicit
        # colon form to survive as a from-import (``dataclasses:dataclass``).
        rendered = entry.module_path if name[:1].isupper() else f"{pkg}:{name}"
    else:
        rendered = entry.module_path
    if entry.alias:
        rendered = f"{rendered} as {entry.alias}"
    return rendered


def render_requires_block(
    entries: Iterable[RequiresEntry], field: str = "requires",
) -> str:
    """Render a ``requires:``-family declaration block for *entries*.

    The caller passes the module's remainder for one import field
    (``requires:`` or ``deferred_requires:``, named by *field*) after
    dropping the unresolvable entries, so the rendered block — pasted over
    that field's line — carries only importable dependencies. An empty
    remainder renders as ``<field>: []``.
    """
    return f"{field}: [{', '.join(render_requires_entry(e) for e in entries)}]"
