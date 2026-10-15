"""Tests whose authority is an internal working note, and how they behave
when that note is not in the checkout.

Some tests in this suite read a document that is not part of what s0ma
ships: an architecture plan, an initiative's plan. Reading the authority
rather than copying its numbers is deliberate — a table copied into a test
is a table that goes stale silently.

The documentation corpus's classification ledger used to be one of these
and is not any more: the front-door move put it under ``docs/s0ma_src/``
with every other gate input, so the three modules that read it read it
directly. A gate input the export withholds was the latent defect; a
helper that made those tests skip was the symptom.

The public repository is built by an export that withholds the working-note
corpus (plan 5, decision FD-2), so in that checkout those documents are
absent. There are only two honest things a test can do about that:

* **Skip, saying which document is missing and why.** What this module is
  for.
* **Read a stub left at the path.** Rejected. A pointer file at
  ``plans/…`` keeps the test green by lying about what the repository
  contains, and the assertion then proves a property of the stub.

Nothing here weakens a test in a checkout that HAS the document: every
helper resolves the real file and the assertions run unchanged. The skip
is reached only when the file genuinely is not there.

Usage::

    from tests._internal_corpus import internal_document, requires_internal

    PLAN = "plans/complete/s0ma-self-documenting-application-1.md"

    @requires_internal(PLAN, what="the architecture plan")
    class TestTheFiling:
        ...

    def test_something() -> None:
        path = internal_document(PLAN, what="the architecture plan")
        ...
"""

from __future__ import annotations

from pathlib import Path
from typing import NoReturn

import pytest

#: The monorepo root (this file: packages/s0ma-dsl/tests/<file>).
REPO_ROOT = Path(__file__).resolve().parents[3]


def _reason(candidates: tuple[str, ...], what: str) -> str:
    """One sentence a reader of a skipped test can act on."""
    where = " or ".join(candidates)
    return (
        f"{what} is not in this checkout ({where}). This test reads it as its "
        f"authority rather than copying its contents. The public export "
        f"withholds the internal working-note corpus (plan 5, FD-2), so the "
        f"test skips here rather than passing against a stub — in a checkout "
        f"that has the document it runs in full."
    )


def present(*candidates: str) -> bool:
    """True when at least one of these internal documents is here."""
    return any((REPO_ROOT / relative).is_file() for relative in candidates)


def internal_document(*candidates: str, what: str) -> Path:
    """The first of these documents that exists, or skip saying which.

    Several candidates are allowed because plans move — an initiative's
    plan is filed to ``plans/complete/`` when it closes, and a resolver
    that pinned one path would turn a filing into a red test.
    """
    for relative in candidates:
        path = REPO_ROOT / relative
        if path.is_file():
            return path
    skip(*candidates, what=what)


def skip(*candidates: str, what: str) -> NoReturn:
    """Skip the current test for an absent internal document."""
    pytest.skip(_reason(candidates, what))


def requires_internal(*candidates: str, what: str) -> pytest.MarkDecorator:
    """Skip this test or class unless one of these documents is here."""
    return pytest.mark.skipif(not present(*candidates), reason=_reason(candidates, what))
