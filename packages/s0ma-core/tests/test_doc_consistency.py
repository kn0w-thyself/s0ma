"""Doc-consistency meta-tests for s0ma-core's specification surface.

CI guardrails against drift between core's formal documentation surface and
the package it describes. They are intentionally lightweight: each reads a
file from disk and asserts one cross-reference invariant. The purpose is to
*fail loudly* the next time somebody rolls core's version without cutting the
matching spec file, or lets a superseded document sit in the tree with nothing
saying so.

This mirrors the convention ``packages/s0ma-dsl/tests/test_doc_consistency.py``
has enforced for the language spec since its first cut. Core had no equivalent,
and the July 2026 codebase review recorded the consequence as DOC-8: the core
spec was filed at v0.2.0 with later surfaces "folded in", pinned by nothing,
while the package shipped release after release past it. The August 2026 docs
audit found the same file still frozen at the pre-monorepo boundary with no
supersession banner. Both are closed by the rotation these tests now hold in
place.

Owner ruling OP-4 (plan the docs-function plan (internal) §12, milestone G3) is
what these encode: core keeps a *living* current spec at the current version,
prior cuts are pinned as history and never renamed, and a version-pin test
keeps the current one honest.
"""

from __future__ import annotations

import re
import tomllib
from pathlib import Path

# ---------------------------------------------------------------------------
# Locate the package root deterministically: the tests live at <root>/tests/,
# so the package root is the parent of this file's parent. Doing the lookup
# once keeps every test independent of the pytest invocation directory.
# ---------------------------------------------------------------------------

PACKAGE_ROOT = Path(__file__).resolve().parent.parent
DOCS = PACKAGE_ROOT / "docs"
PYPROJECT = PACKAGE_ROOT / "pyproject.toml"

# ---------------------------------------------------------------------------
# Current core-spec version.
#
# Unlike the DSL — whose *language* spec versions on an axis of its own,
# decoupled from the distribution version since the monorepo consolidation —
# core's spec describes the runtime surface of this package, so it is cut at
# the package's own version and pinned to it by
# ``test_current_spec_version_matches_package_version`` below. Bump this and
# cut the matching file in the same act; historical spec files are never
# renamed.
# ---------------------------------------------------------------------------

CURRENT_CORE_SPEC_VERSION = "0.21.1"

#: The last spec cut before the monorepo consolidation. Kept in the tree as
#: pinned history per OP-4 — never renamed, never deleted, and never allowed
#: to sit there unbannered (which is precisely the state the August audit
#: found it in).
HISTORICAL_CORE_SPEC = "s0ma-core-spec-v0.2.0.md"


def _spec_path(version: str) -> Path:
    """The on-disk path a core spec of ``version`` must occupy."""

    return DOCS / f"s0ma-core-spec-v{version}.md"


def _package_version() -> str:
    """Read ``project.version`` from the package manifest.

    Parsed with tomllib rather than imported: importing ``s0ma`` runs
    bootstrap registration machinery, and a version pin has no business
    booting a registry to read a string.
    """

    with PYPROJECT.open("rb") as handle:
        data = tomllib.load(handle)
    version = data["project"]["version"]
    assert isinstance(version, str)
    return version


# ---------------------------------------------------------------------------
# Spec presence + version alignment
# ---------------------------------------------------------------------------


def test_current_spec_path_matches_version() -> None:
    """The on-disk spec filename must match ``CURRENT_CORE_SPEC_VERSION``.

    The spec file is core's normative surface and its filename encodes the
    version it was cut at. If the constant moves without the file being cut
    (or the reverse), this fires immediately so the inconsistency cannot
    ship.
    """

    expected = _spec_path(CURRENT_CORE_SPEC_VERSION)
    assert expected.exists(), (
        f"Expected spec file {expected.name!r} to exist for "
        f"CURRENT_CORE_SPEC_VERSION == {CURRENT_CORE_SPEC_VERSION!r}, but it "
        f"is missing. Either cut the spec file to match, or update "
        f"CURRENT_CORE_SPEC_VERSION to match an existing spec."
    )

    # The title banner must agree with the filename. Same assertion the DSL
    # suite makes, and for the same reason: a filename and an in-file version
    # that disagree leave a reader with no way to tell which one is the cut.
    text = expected.read_text(encoding="utf-8")
    assert f"**Version:** {CURRENT_CORE_SPEC_VERSION}" in text, (
        f"{expected.name} exists but its title-banner version line does not "
        f"say {CURRENT_CORE_SPEC_VERSION!r}. Update the banner so the file "
        f"name and the in-file version agree."
    )


def test_current_spec_version_matches_package_version() -> None:
    """The current spec is cut at the package's own version.

    This is the pin DOC-8 asked for. Core's spec documents this package's
    runtime surface, so a version roll that does not cut a spec leaves the
    only normative statement of that surface describing an older package —
    which is exactly how v0.2.0 survived to 0.17.0 unnoticed. Rolling the
    version now requires cutting the spec in the same change, or CI says so.
    """

    package_version = _package_version()
    assert package_version == CURRENT_CORE_SPEC_VERSION, (
        f"CURRENT_CORE_SPEC_VERSION is {CURRENT_CORE_SPEC_VERSION!r} but "
        f"s0ma-core's project.version is {package_version!r}. A version roll "
        f"must cut a matching spec: copy the current spec to "
        f"docs/s0ma-core-spec-v{package_version}.md, update its "
        f"'**Version:**' banner and its contents for what changed, banner the "
        f"outgoing cut as historical, and bump this constant. Historical spec "
        f"files are never renamed."
    )


# ---------------------------------------------------------------------------
# Historical cuts stay in the tree, and stay marked
# ---------------------------------------------------------------------------


def test_historical_spec_is_retained() -> None:
    """The pre-monorepo cut is kept as history, not deleted.

    OP-4 chose rotate-and-pin over archive: the old cut is the honest record
    of what core promised at the 0.4.0 boundary, and deleting it would erase
    the provenance the current spec's own §13 cites.
    """

    historical = DOCS / HISTORICAL_CORE_SPEC
    assert historical.exists(), (
        f"{HISTORICAL_CORE_SPEC} is missing. Historical spec cuts are kept "
        f"and never renamed (OP-4). If it truly had to move, update this "
        f"test and the current spec's provenance section together."
    )


def test_historical_spec_is_bannered() -> None:
    """A superseded spec must say so, in the file, above its own content.

    The audit's finding was not that the old spec existed — it was that it
    sat there reading as current, with no banner and no pointer, while an
    agent served it had no way to know. The banner must both declare itself
    historical and name the current cut, so a reader who lands on it mid-file
    or follows an old link is told where to go.
    """

    text = (DOCS / HISTORICAL_CORE_SPEC).read_text(encoding="utf-8")
    head = text[:2000]

    assert "Historical" in head, (
        f"{HISTORICAL_CORE_SPEC} does not declare itself historical in its "
        f"opening banner. A superseded spec with no banner reads as current "
        f"guidance — the exact defect the August 2026 docs audit recorded."
    )
    assert _spec_path(CURRENT_CORE_SPEC_VERSION).name in head, (
        f"{HISTORICAL_CORE_SPEC}'s banner does not name the current spec "
        f"({_spec_path(CURRENT_CORE_SPEC_VERSION).name}). Rotating the spec "
        f"means repointing the outgoing cut's banner at the incoming one."
    )


# ---------------------------------------------------------------------------
# The enumeration-deferral discipline
# ---------------------------------------------------------------------------

#: A hand-written component count — "44 components", "61 framework
#: components". This is the single defect class that killed both documents
#: this milestone retired: architecture.md's inventory said 44 while the
#: package registered 59, and the old spec's counts had been wrong for
#: releases. The current spec states contracts and routes every count to the
#: generated pages, and this keeps it that way.
COUNT_CLAIM_RE = re.compile(r"\b\d+\s+(?:\w+\s+)?components?\b", re.IGNORECASE)


def test_current_spec_states_no_component_counts() -> None:
    """The current spec defers inventories; it never restates a count.

    Not a style rule. A count written by hand in a document nothing
    regenerates is wrong from the first commit that adds a component, and
    every reader who trusts it is misled with no way to notice. The generated
    component index owns this answer; the spec's §12 routes to it.
    """

    spec = _spec_path(CURRENT_CORE_SPEC_VERSION)
    offenders = [
        line.strip()
        for line in spec.read_text(encoding="utf-8").splitlines()
        if COUNT_CLAIM_RE.search(line)
    ]
    assert not offenders, (
        f"{spec.name} states a component count in prose:\n  "
        + "\n  ".join(offenders)
        + "\nThe spec states contracts, not inventories. Delete the count and "
        "link to docs/architecture/component-index.md, which is generated "
        "from the registry on every build."
    )


def test_current_spec_routes_to_the_generated_inventories() -> None:
    """Deferring only works if the spec says where to go instead.

    A document that omits the counts *and* omits the pointer has not deferred
    anything — it has just left the reader without an answer. This pins the
    routing half of the discipline: the current spec must link the generated
    pages that own what it declines to restate.
    """

    text = _spec_path(CURRENT_CORE_SPEC_VERSION).read_text(encoding="utf-8")
    for target in (
        "docs/architecture/component-index.md",
        "docs/reference/packages.md",
        "docs/reference/surfaces-index.md",
    ):
        assert target in text, (
            f"The current core spec does not reference {target}. It states no "
            f"inventories of its own, so it has to name the generated pages "
            f"that hold them (spec §12)."
        )
