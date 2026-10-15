"""Doc-consistency meta-tests (feedback 5–6 plan, M19a).

These tests are CI guardrails against drift between the formal documentation
surfaces (spec, ADR index, traceability matrix, pointer files) and the code
those documents describe. They are intentionally lightweight: each one reads a
file from disk and asserts a cross-reference invariant. The purpose is to
*fail loudly* the next time someone introduces a new error code without
registering it in the traceability matrix, or bumps the spec version without
updating the spec file's name, or deletes an ADR without updating the index.

The plan: feedback_5-6 plan, M19a, "Doc-consistency meta-tests".
"""

from __future__ import annotations

import ast
import importlib.util
import re
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from s0ma_dsl.config import (
    ERROR_CODE_DESCRIPTIONS,
    OUT_OF_MATRIX_CODES_THAT_MUST_STILL_BE_TRACEABLE,
    SEVERITY_MATRIX,
)

if TYPE_CHECKING:
    from types import ModuleType

# ---------------------------------------------------------------------------
# Locate the repo root deterministically: the tests live at <root>/tests/, so
# the project root is the parent of this file's parent. Doing the lookup once
# and reusing the result keeps every test independent of the pytest invocation
# directory.
# ---------------------------------------------------------------------------

REPO_ROOT = Path(__file__).resolve().parent.parent
DOCS = REPO_ROOT / "docs"
ADR_DIR = DOCS / "adr"
S0MA_DSL_SRC = REPO_ROOT / "src" / "s0ma_dsl"

# ---------------------------------------------------------------------------
# Current language-spec version.
#
# Through 0.16.0 the spec filename tracked ``s0ma_dsl.__version__``
# one-to-one. From 0.5.0 (the monorepo consolidation) every package in the
# repo versions in lockstep (PRD INV-4), so the *distribution* version and
# the *language-spec* version are decoupled: this constant pins the most
# recent language-spec cut, and historical spec files are never renamed.
# Bump it — and rotate the pointer files per the one-release-pointer
# policy — whenever a new spec is cut.
# ---------------------------------------------------------------------------

CURRENT_SPEC_VERSION = "0.17.0"


# ---------------------------------------------------------------------------
# Spec presence + version alignment
# ---------------------------------------------------------------------------


def test_spec_path_matches_version() -> None:
    """The on-disk spec filename must match ``CURRENT_SPEC_VERSION``.

    The spec file is the formal/normative surface; its filename encodes the
    language-spec version. If we bump the spec version in this file without
    renaming/cutting the spec file (or vice versa), this fires immediately so
    the inconsistency cannot ship. (Pre-consolidation this checked
    ``s0ma_dsl.__version__``; lockstep packaging decoupled the two — see the
    CURRENT_SPEC_VERSION comment above.)
    """

    version = CURRENT_SPEC_VERSION
    expected = DOCS / f"s0ma-dsl-spec-v{version}.md"
    assert expected.exists(), (
        f"Expected spec file {expected.name!r} to exist for "
        f"CURRENT_SPEC_VERSION == {version!r}, but it is missing. "
        f"Either cut/rename the spec file to match, or update "
        f"CURRENT_SPEC_VERSION to match an existing spec."
    )

    # Sanity check: the spec's title banner should mention the same version.
    text = expected.read_text(encoding="utf-8")
    assert f"**Version:** {version}" in text, (
        f"{expected.name} exists but its title-banner version line does "
        f"not say {version!r}. Update the banner so the file name and "
        f"the in-file version agree."
    )


# ---------------------------------------------------------------------------
# Every error code in the severity matrix must be traceable
# ---------------------------------------------------------------------------


def test_error_codes_in_traceability() -> None:
    """Every error code in SEVERITY_MATRIX must appear in spec_traceability.md.

    The traceability matrix is the canonical rule-to-implementation map. If a
    new error code lands in ``s0ma_dsl.config.SEVERITY_MATRIX`` without a
    corresponding row, the next contributor reading the matrix sees a
    half-described system. This test catches the drift the moment the code
    lands.
    """

    traceability_path = DOCS / "spec_traceability.md"
    assert traceability_path.exists(), (
        f"Expected {traceability_path} to exist; the traceability matrix "
        f"is the canonical rule-to-implementation map."
    )
    text = traceability_path.read_text(encoding="utf-8")

    missing: list[str] = []
    for code in sorted(SEVERITY_MATRIX.keys()):
        # Codes are listed in the matrix as backtick-quoted identifiers in
        # the "Error Code" column. We require the exact `<CODE>` token to
        # appear at least once — the row may also reference the code in
        # prose, but the leading-cell match is the load-bearing presence
        # check.
        if f"`{code}`" not in text:
            missing.append(code)

    assert not missing, (
        f"The following error codes are registered in SEVERITY_MATRIX but "
        f"not present in docs/spec_traceability.md: {missing}. Add a row "
        f"for each (the existing rows show the format)."
    )


# ---------------------------------------------------------------------------
# Pointer file invariants
# ---------------------------------------------------------------------------


def test_pointer_file_present() -> None:
    """The previous spec version's pointer file must redirect to the current.

    Per the existing one-release-pointer policy, the immediately-prior spec
    file lives on for one release as a pointer to the current spec, then is
    deleted in the release after. This test enforces the *present-and-points*
    half of that policy.
    """

    pointer = DOCS / "s0ma-dsl-spec-v0.16.0.md"
    assert pointer.exists(), (
        f"Expected {pointer.name} to exist as a one-release pointer to "
        f"the current spec. Per the spec-version policy, the prior spec "
        f"file lives one release as a redirect."
    )
    text = pointer.read_text(encoding="utf-8")
    assert "s0ma-dsl-spec-v0.17.0.md" in text, (
        f"{pointer.name} exists but does not link to the current spec "
        f"file (s0ma-dsl-spec-v0.17.0.md). Update the pointer body."
    )


def test_no_v0_10_1_pointer() -> None:
    """The two-releases-old pointer file must be absent.

    The one-release-pointer policy says we keep at most *one* prior pointer
    at a time. Any further-back pointer should be deleted. This is the
    *deleted* half of the policy — paired with ``test_pointer_file_present``.
    """

    stale = DOCS / "s0ma-dsl-spec-v0.10.1.md"
    assert not stale.exists(), (
        f"{stale.name} should have been deleted when v0.13.0 shipped (per "
        f"the one-release-pointer policy: only the immediately-prior spec "
        f"file may live on as a pointer). Run `git rm` on it."
    )


def test_no_v0_11_0_pointer() -> None:
    """The v0.11.0 pointer was deleted in the 0.16.0 cut.

    The 0.15.0 release left the v0.11.0 pointer in place as the single
    one-release marker (it pointed at v0.15.0). The 0.16.0 release rotates
    the pointer forward: v0.11.0 is deleted, and a fresh v0.15.0 pointer
    file replaces it, redirecting to v0.16.0. This test enforces the
    deleted half of that rotation.
    """

    stale = DOCS / "s0ma-dsl-spec-v0.11.0.md"
    assert not stale.exists(), (
        f"{stale.name} should have been deleted when v0.16.0 shipped (per "
        f"the one-release-pointer policy: only the immediately-prior spec "
        f"file — now v0.15.0 — may live on as a pointer). Run `git rm` on it."
    )


def test_no_v0_15_0_pointer() -> None:
    """The v0.15.0 pointer was deleted in the 0.17.0 cut (DSL-M1).

    The 0.16.0 release left the v0.15.0 pointer in place as the single
    one-release marker (it pointed at v0.16.0, declaring
    deletion-after-0.16.0). The 0.17.0 spec cut rotates the pointer
    forward per its own declared schedule: v0.15.0 is deleted, and a
    fresh v0.16.0 pointer file replaces it, redirecting to v0.17.0.
    This test enforces the deleted half of that rotation.
    """

    stale = DOCS / "s0ma-dsl-spec-v0.15.0.md"
    assert not stale.exists(), (
        f"{stale.name} should have been deleted when v0.17.0 shipped (per "
        f"the one-release-pointer policy: only the immediately-prior spec "
        f"file — now v0.16.0 — may live on as a pointer). Run `git rm` on it."
    )


# ---------------------------------------------------------------------------
# ADR index
# ---------------------------------------------------------------------------


def test_adr_index_present() -> None:
    """The ADR index lists every ADR file in the directory.

    A reader walking into ``docs/adr/`` should land on a README that names
    every decision. Adding an ADR without indexing it is the same kind of
    silent-failure pattern this plan exists to retire.
    """

    index_path = ADR_DIR / "README.md"
    assert index_path.exists(), (
        f"Expected {index_path} to exist as the ADR index. Create one that "
        f"lists every ADR-NNN-*.md file in chronological order."
    )
    index_text = index_path.read_text(encoding="utf-8")

    adr_files = sorted(
        p.name for p in ADR_DIR.glob("ADR-*.md") if p.is_file()
    )
    assert adr_files, "Expected at least one ADR-NNN-*.md file under docs/adr/."

    missing = [name for name in adr_files if name not in index_text]
    assert not missing, (
        f"The ADR index ({index_path}) does not reference these ADR "
        f"files: {missing}. Add a row for each."
    )


# ---------------------------------------------------------------------------
# Out-of-matrix error codes (G6 feedback 5–6 cleanup)
#
# G6 promoted ``OUT_OF_MATRIX_CODES_THAT_MUST_STILL_BE_TRACEABLE`` from a
# test-local tuple to a public export of ``s0ma_dsl.config``. Keeping the
# canonical list next to ``SEVERITY_MATRIX`` (rather than duplicated here)
# is what makes the new ``test_every_error_code_literal_is_registered``
# meta-test single-source-of-truth: every code literal in
# ``src/s0ma_dsl/`` must be in ``SEVERITY_MATRIX.keys()`` or
# ``OUT_OF_MATRIX_CODES_THAT_MUST_STILL_BE_TRACEABLE``, full stop.
#
# Adding a code to that tuple is a deliberate documentation choice, not a
# workaround for "I don't want to think about severity yet". See
# ``docs/coding_agent_handbook.md`` §2.3 (Error Codes) for the decision
# rule future contributors must follow.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("code", OUT_OF_MATRIX_CODES_THAT_MUST_STILL_BE_TRACEABLE)
def test_out_of_matrix_codes_in_traceability(code: str) -> None:
    """Hand-emitted (non-matrix) codes are still in the traceability matrix.

    Every code in ``OUT_OF_MATRIX_CODES_THAT_MUST_STILL_BE_TRACEABLE``
    fires from a project-load-time / pre-flight surface that does not
    consult ``SEVERITY_MATRIX`` — but it still needs a row in the
    traceability matrix so future contributors can trace the rule to
    its implementation.
    """

    text = (DOCS / "spec_traceability.md").read_text(encoding="utf-8")
    assert f"`{code}`" in text, (
        f"Code {code!r} is emitted directly (not via SEVERITY_MATRIX) "
        f"and is registered in "
        f"OUT_OF_MATRIX_CODES_THAT_MUST_STILL_BE_TRACEABLE — it must "
        f"still appear in docs/spec_traceability.md so future "
        f"contributors can trace the rule to its implementation. Add "
        f"a row."
    )


# ---------------------------------------------------------------------------
# G6-specific cross-reference invariant (feedback 5–6 cleanup)
#
# G6 audits every error code literal in ``src/s0ma_dsl/`` and pins each one
# to either ``SEVERITY_MATRIX`` (mode-graded codes that fire from the
# validator/resolver/check pipeline) or
# ``OUT_OF_MATRIX_CODES_THAT_MUST_STILL_BE_TRACEABLE`` (structural /
# load-time codes that bypass the strictness ladder). The meta-test below
# walks the source tree with ``ast.parse`` — not grep — so codes
# constructed via ``S0maError(code="X")``, positional ``S0maParseError("X",
# ...)`` arguments, or surfaced via the ``"<CODE>: ..."`` message-prefix
# convention used by load-time errors that don't construct ``S0maError``
# (e.g. ``project.py`` raising ``ValueError("OVERLAPPING_DISCOVERY_ROOTS:
# ...")``) all get pinned.
#
# The four error constructors below are the canonical entry points for
# emitting structured diagnostics; the prefix regex covers the load-time
# / pre-flight surfaces that emit error-code-shaped messages without
# going through the constructors.
# ---------------------------------------------------------------------------

_ERROR_CONSTRUCTORS: frozenset[str] = frozenset({
    "S0maError",
    "S0maParseError",
    "S0maSemanticError",
    "S0maResolutionError",
})

# Allow-list: codes that are emitted somewhere in src/s0ma_dsl/ as a
# message prefix or string literal that is NOT actually an error code.
# Currently empty; populated only with explicit comment + rationale.
_NON_ERROR_CODE_LITERALS: frozenset[str] = frozenset({
    # Documentation-string identifier in ``runtime/__init__.py``: the
    # docstring describes how a consumer project hand-maintains a
    # ``MODULE_IMPORT_ORDER`` tuple in their bootstrap module. It is a
    # Python identifier referenced in docs, not an error code.
    "MODULE_IMPORT_ORDER",
})


# Anywhere in a string, an UPPER_SNAKE_CASE token followed by ":" + space.
# We require at least one underscore (so single-word labels like "ERROR:"
# don't match) and at least four characters total. This catches both the
# "FOO_BAR: ..." convention used by ``project.py`` for load-time errors
# AND the "s0ma test: STALE_GENERATED_CONFTEST: ..." convention used by
# ``cli/main.py`` for pre-flight messages that prepend a program-name
# tag before the error code.
_PREFIX_CODE_RE = re.compile(r"\b([A-Z][A-Z0-9]*(?:_[A-Z0-9]+)+):\s")


def _is_error_constructor(node: ast.expr) -> str | None:
    """Return the constructor name if ``node`` is a call to an error class.

    Matches both ``S0maError(...)`` and ``module.S0maError(...)`` shapes.
    Returns the bare class name; returns ``None`` for any other expression.
    """

    if isinstance(node, ast.Name) and node.id in _ERROR_CONSTRUCTORS:
        return node.id
    if isinstance(node, ast.Attribute) and node.attr in _ERROR_CONSTRUCTORS:
        return node.attr
    return None


def _looks_like_error_code(value: str) -> bool:
    """Return ``True`` if a string literal looks like an UPPER_SNAKE_CASE code.

    Uppercase letters / digits / underscores only; at least two characters;
    does not start with a digit. We accept single-word codes here because
    legitimate codes ("PARSE_ERROR" → still has an underscore; but a
    hypothetical single-word code shouldn't be filtered out at extraction
    time) — the registry-side check catches anything that slips through.
    """

    return bool(
        value
        and value.replace("_", "").isalnum()
        and value.isupper()
        and len(value) >= 2
        and not value[0].isdigit()
    )


def _extract_error_code_literals(source_root: Path) -> set[str]:
    """Walk every ``.py`` file under ``source_root`` and extract error codes.

    Returns the union of:
      1. ``code="<CODE>"`` keyword arguments to any call.
      2. The first-positional string argument to calls that target the
         four error constructors (``S0maError``, ``S0maParseError``,
         ``S0maSemanticError``, ``S0maResolutionError``).
      3. ``<CODE>: `` prefix tokens inside any string literal or
         f-string. The prefix regex matches both bare prefixes (the
         ``project.py`` convention) and prefixes that follow a
         program-name tag (the ``cli/main.py`` ``"s0ma test: <CODE>:
         ..."`` convention).

    Filters out any token in ``_NON_ERROR_CODE_LITERALS`` (currently the
    docstring identifier ``MODULE_IMPORT_ORDER``).

    Filters out the literal ``"BAD_CODE"`` produced by tests that
    intentionally construct a fictional error to exercise diagnostic
    formatting — ``src/s0ma_dsl/`` should never reference a code by
    that token, and the filter is here as a defensive belt-and-braces.
    """

    found: set[str] = set()

    for py_path in sorted(source_root.rglob("*.py")):
        source = py_path.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(py_path))

        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                # 1) keyword "code"
                for kw in node.keywords:
                    if (
                        kw.arg == "code"
                        and isinstance(kw.value, ast.Constant)
                        and isinstance(kw.value.value, str)
                        and _looks_like_error_code(kw.value.value)
                    ):
                        found.add(kw.value.value)

                # 2) Error constructor with first positional string
                if _is_error_constructor(node.func) and node.args:
                    first = node.args[0]
                    if (
                        isinstance(first, ast.Constant)
                        and isinstance(first.value, str)
                        and _looks_like_error_code(first.value)
                    ):
                        found.add(first.value)

            # 3) Prefix-token convention in any string constant
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                for m in _PREFIX_CODE_RE.finditer(node.value):
                    found.add(m.group(1))

            # 3b) Prefix-token convention across the static segments of
            # an f-string. We concatenate the static segments separated
            # by a NUL placeholder so a code straddling two segments
            # cannot accidentally form (we never want to match
            # "_".join([dynamic, "TOKEN", "TAIL"]) as one code).
            if isinstance(node, ast.JoinedStr):
                parts: list[str] = []
                for v in node.values:
                    if isinstance(v, ast.Constant) and isinstance(v.value, str):
                        parts.append(v.value)
                    else:
                        parts.append("\x00")
                joined = "".join(parts)
                for m in _PREFIX_CODE_RE.finditer(joined):
                    found.add(m.group(1))

    return found - _NON_ERROR_CODE_LITERALS


def test_every_error_code_literal_is_registered() -> None:
    """Every error code literal in ``src/s0ma_dsl/`` is registered.

    The audit walks every ``.py`` file under ``src/s0ma_dsl/`` with
    ``ast.parse`` and extracts every error code literal — keyword
    ``code="..."`` arguments, positional first-string arguments to error
    constructors, and ``"<CODE>: ..."`` message-prefix tokens used by
    load-time / pre-flight error sites that don't go through
    ``S0maError``. Every extracted code MUST appear in either
    ``SEVERITY_MATRIX`` or
    ``OUT_OF_MATRIX_CODES_THAT_MUST_STILL_BE_TRACEABLE``.

    A future contributor adding a new error code outside both registries
    fires this test loudly with a directive to register the code (see
    ``docs/coding_agent_handbook.md`` §2.3 for the decision rule).
    """

    assert S0MA_DSL_SRC.is_dir(), (
        f"Expected {S0MA_DSL_SRC} to exist; the audit walks every .py "
        f"file under that root."
    )

    extracted = _extract_error_code_literals(S0MA_DSL_SRC)
    registered = set(SEVERITY_MATRIX.keys()) | set(
        OUT_OF_MATRIX_CODES_THAT_MUST_STILL_BE_TRACEABLE
    )

    unregistered = sorted(extracted - registered)
    assert not unregistered, (
        f"The following error code literal(s) appear in src/s0ma_dsl/ "
        f"but are not registered in SEVERITY_MATRIX or "
        f"OUT_OF_MATRIX_CODES_THAT_MUST_STILL_BE_TRACEABLE: "
        f"{unregistered}.\n\n"
        f"Decision rule (docs/coding_agent_handbook.md §2.3): default "
        f"to registering in SEVERITY_MATRIX with appropriate severity-"
        f"by-mode mappings. Only add to "
        f"OUT_OF_MATRIX_CODES_THAT_MUST_STILL_BE_TRACEABLE if the code "
        f"is structurally always-one-severity (no mode variation makes "
        f"sense) AND fires from a surface that does not carry a "
        f"strictness mode (project load, file discovery, pre-flight "
        f"check). Document the rationale in a one-line comment per "
        f"entry in either registry. Then add a traceability row in "
        f"docs/spec_traceability.md so the rule can be traced to its "
        f"implementation."
    )


# ---------------------------------------------------------------------------
# F4-specific cross-reference invariants (feedback 5–6 follow-up plan)
#
# F1 introduced the canonical-body invariant and the ADR documenting it
# (ADR-009). F3 introduced the NO_PAGE_COMPOSER_DECLARED error code. F4 pins
# both as load-bearing: ADR-009 must exist with the canonical-body decision,
# and NO_PAGE_COMPOSER_DECLARED must be in the spec traceability matrix
# (otherwise the page-composer guidance is half-described).
# ---------------------------------------------------------------------------


def test_adr_009_canonical_body_storage_present() -> None:
    """ADR-009 must exist and document the canonical-body decision (F1, F4).

    F1's structural change — bodies are dedented exactly once at parse time,
    and the canonical form is the single source of truth — is the load-bearing
    architectural decision the rest of the validator/codegen pipeline depends
    on. ADR-009 is its durable rationale; if the file disappears or the
    decision drifts, this fires.
    """

    adr_path = ADR_DIR / "ADR-009-canonical-body-storage.md"
    assert adr_path.exists(), (
        f"Expected {adr_path} to exist as the F1 architectural decision "
        f"record. F1 (feedback 5–6 follow-up) made the canonical dedented "
        f"body the single source of truth across validator, codegen, IR, "
        f"derived edges, source map, and doc subsystem. Re-create the ADR "
        f"if it was deleted (see plans/5-6_follow-up_plan.md F4)."
    )
    text = adr_path.read_text(encoding="utf-8")

    # Sanity check on shape: the ADR must mention the canonical-body decision
    # and the parser-owns-it invariant. We do not pin the exact prose, but the
    # two load-bearing concepts must appear.
    for token in (
        "body_extractor",
        "canonical",
        "Alternatives Considered",
    ):
        assert token in text, (
            f"ADR-009 ({adr_path}) does not mention {token!r}. The ADR's "
            f"load-bearing claims are (a) parse-time dedent owned by "
            f"body_extractor, (b) canonical body is the single source of "
            f"truth, (c) explicit Alternatives Considered enumeration. If "
            f"any drifts out of the file, this fires."
        )


def test_no_page_composer_declared_in_traceability() -> None:
    """NO_PAGE_COMPOSER_DECLARED must be in the spec traceability matrix (F3, F4).

    F3 added the error code as part of replacing M18's heuristic page-composer
    detection. The traceability matrix is the canonical rule-to-implementation
    map; the meta-test ``test_error_codes_in_traceability`` already enforces
    this for every code in SEVERITY_MATRIX, but F4 pins NO_PAGE_COMPOSER_DECLARED
    explicitly so a future SEVERITY_MATRIX refactor cannot accidentally drop
    this code's traceability row without surfacing the gap.
    """

    text = (DOCS / "spec_traceability.md").read_text(encoding="utf-8")
    assert "`NO_PAGE_COMPOSER_DECLARED`" in text, (
        "NO_PAGE_COMPOSER_DECLARED (added in F3 for the explicit page-composer "
        "marker) must appear in docs/spec_traceability.md. The matrix row "
        "spells out which spec section, fixture, and source file own the "
        "rule. See feedback_5-6 follow-up F3 for the surrounding context."
    )


def test_adr_index_includes_009() -> None:
    """The ADR index must reference ADR-009 explicitly.

    The general ``test_adr_index_present`` test already enforces that every
    on-disk ADR is referenced by name. F4 adds an explicit pin for ADR-009
    so a refactor that re-numbers or re-organises the ADRs cannot silently
    lose F1's architectural record.
    """

    index_path = ADR_DIR / "README.md"
    text = index_path.read_text(encoding="utf-8")
    assert "ADR-009-canonical-body-storage.md" in text, (
        f"ADR-009 must be linked from {index_path}. F1's architectural "
        f"decision (canonical dedented body as single source of truth) is "
        f"load-bearing across the validator/codegen/IR pipeline; the index "
        f"row is how a future contributor finds the rationale."
    )


# ---------------------------------------------------------------------------
# G9 (feedback 5–6 cleanup): ADR-010 pins for derived doc targets
#
# G7a introduced the ``covers: { source: <name> }`` sub-key form of the
# ``doc-ref`` declaration; G7b cut the hand-authored Common Errors table over
# to a derived bracketed region. ADR-010 documents the structural decision
# (discriminated-union grammar; sub-key form chosen over polymorphic bare
# strings) and sets the precedent for future derived-doc registries. G9 pins
# its existence so a future ADR re-numbering or refactor cannot silently lose
# the rationale.
# ---------------------------------------------------------------------------


def test_adr_010_present() -> None:
    """ADR-010 must exist and document the derived-doc-targets decision (G7, G9).

    G7a's grammar extension is the first non-component target type for
    ``doc-ref``; the chosen sub-key form sets the canonical shape for every
    future derived-doc registry. ADR-010 is the durable rationale; if the
    file disappears or the decision drifts, this fires.
    """

    adr_path = ADR_DIR / "ADR-010-derived-doc-targets.md"
    assert adr_path.exists(), (
        f"Expected {adr_path} to exist as the G7 architectural decision "
        f"record. G7a (feedback 5–6 cleanup) extended the doc-ref ``covers:`` "
        f"grammar with a discriminated-union sub-key form; G7b cut the "
        f"hand-authored Common Errors table over to a derived region. "
        f"Re-create the ADR if it was deleted (see "
        f"plans/5-6_cleanup_plan.md G7 and G9)."
    )
    text = adr_path.read_text(encoding="utf-8")

    # Sanity check on shape: the ADR must mention the load-bearing concepts.
    # We do not pin the exact prose, but the four load-bearing tokens must
    # appear so a future copy-edit cannot silently lose any of them.
    for token in (
        "covers: { source:",
        "error_codes",
        "discriminated union",
        "Alternatives Considered",
    ):
        assert token in text, (
            f"ADR-010 ({adr_path}) does not mention {token!r}. The ADR's "
            f"load-bearing claims are (a) discriminated-union grammar with "
            f"the sub-key form, (b) error_codes as the first registered "
            f"source, (c) explicit Alternatives Considered enumeration. If "
            f"any drifts out of the file, this fires."
        )


def test_adr_index_includes_010() -> None:
    """The ADR index must reference ADR-010 explicitly.

    The general ``test_adr_index_present`` test already enforces that every
    on-disk ADR is referenced by name. G9 adds an explicit pin for ADR-010
    so a refactor that re-numbers or re-organises the ADRs cannot silently
    lose G7's architectural record.
    """

    index_path = ADR_DIR / "README.md"
    text = index_path.read_text(encoding="utf-8")
    assert "ADR-010-derived-doc-targets.md" in text, (
        f"ADR-010 must be linked from {index_path}. G7's architectural "
        f"decision (the discriminated-union grammar for doc-ref covers) is "
        f"the canonical shape every future derived-doc registry will reuse; "
        f"the index row is how a future contributor finds the rationale."
    )


# ---------------------------------------------------------------------------
# G1-specific cross-reference invariants (feedback 5–6 cleanup plan)
#
# G1 introduces ``PACKAGE_MARKER`` as the fourth ``s0ma verify`` status,
# the ``[tool.s0ma].package_markers`` declarative escape hatch, and the
# ``CONFLICTING_PACKAGE_DECLARATION`` load-time error code. The matrix-wide
# meta-tests above already cover any code in ``SEVERITY_MATRIX``;
# ``CONFLICTING_PACKAGE_DECLARATION`` is hand-emitted by
# ``S0maProject._from_tool_s0ma`` (it never reaches the resolver / strictness
# ladder) and so must be tracked in the
# ``OUT_OF_MATRIX_CODES_THAT_MUST_STILL_BE_TRACEABLE`` list and pinned
# explicitly in the traceability matrix below.
# ---------------------------------------------------------------------------


def test_conflicting_package_declaration_in_traceability() -> None:
    """``CONFLICTING_PACKAGE_DECLARATION`` must appear in the traceability matrix.

    G1 adds the error as a project-load-time diagnostic (it never enters the
    severity matrix because it is structural — a misconfigured
    ``[tool.s0ma]`` table fails before any strictness mode is consulted).
    The traceability matrix is the canonical rule-to-implementation map;
    the explicit pin guards against a future package-markers refactor
    losing the row without surfacing the gap.
    """

    text = (DOCS / "spec_traceability.md").read_text(encoding="utf-8")
    assert "`CONFLICTING_PACKAGE_DECLARATION`" in text, (
        "CONFLICTING_PACKAGE_DECLARATION (added in G1 for the "
        "[tool.s0ma].package_markers escape hatch) must appear in "
        "docs/spec_traceability.md. The matrix row spells out which "
        "spec section, fixture, and source file own the rule. See "
        "feedback_5-6 cleanup plan G1 for the surrounding context."
    )


# ---------------------------------------------------------------------------
# G2-specific cross-reference invariants (feedback 5–6 cleanup plan)
#
# G2 introduces ``OVERLAPPING_DISCOVERY_ROOTS`` as a pre-flight
# project-load-time diagnostic when ``[tool.s0ma].source_roots`` /
# ``[tool.s0ma].test_roots`` overlap (one is a subpath of the other,
# or two are identical). Unlike ``CONFLICTING_PACKAGE_DECLARATION``,
# this code IS in ``SEVERITY_MATRIX`` (error in every mode) — the
# matrix-wide ``test_error_codes_in_traceability`` already enforces a
# traceability row. The explicit pin below makes the row's absence a
# CI failure with a G2-specific message so a future
# ``SEVERITY_MATRIX`` refactor cannot accidentally drop the row
# without surfacing the gap, and so the diagnostic prose's load-
# bearing pieces (the "disjoint" wording in the spec, the two-option
# remediation in the migration guide) are pinned independently of
# the matrix row's presence.
# ---------------------------------------------------------------------------


def test_overlapping_discovery_roots_in_traceability() -> None:
    """``OVERLAPPING_DISCOVERY_ROOTS`` must appear in the traceability matrix.

    The matrix-wide ``test_error_codes_in_traceability`` would catch a
    missing row, but this test pins the code by name so the failure
    message links directly to G2 — making the remediation obvious to
    a future contributor who has never read the cleanup plan.
    """

    text = (DOCS / "spec_traceability.md").read_text(encoding="utf-8")
    assert "`OVERLAPPING_DISCOVERY_ROOTS`" in text, (
        "OVERLAPPING_DISCOVERY_ROOTS (added in G2 for the source_roots / "
        "test_roots disjoint-roots rule) must appear in "
        "docs/spec_traceability.md. The matrix row spells out which "
        "spec section, fixture, and source file own the rule. See "
        "feedback_5-6 cleanup plan G2 for the surrounding context."
    )


def test_spec_documents_disjoint_discovery_roots_rule() -> None:
    """The spec's `[tool.s0ma]` section must document the disjoint-roots rule.

    G2's behavioural change is that overlapping ``source_roots`` /
    ``test_roots`` raise at project-load time. The spec is the
    canonical user-facing description of ``[tool.s0ma]``; if the
    ``OVERLAPPING_DISCOVERY_ROOTS`` rule is not documented there, a
    consumer reading the spec would miss the new constraint.
    """

    spec_path = DOCS / f"s0ma-dsl-spec-v{CURRENT_SPEC_VERSION}.md"
    text = spec_path.read_text(encoding="utf-8")
    assert "OVERLAPPING_DISCOVERY_ROOTS" in text, (
        f"{spec_path.name} does not document OVERLAPPING_DISCOVERY_ROOTS. "
        f"G2 (feedback 5–6 cleanup) added the disjoint-roots rule to "
        f"[tool.s0ma].source_roots / [tool.s0ma].test_roots; the spec's "
        f"§4.13 must enumerate the rule alongside the other validation "
        f"rules so consumers reading the spec see the constraint."
    )


# ---------------------------------------------------------------------------
# G3-specific cross-reference invariants (feedback 5–6 cleanup plan)
#
# G3 introduces ``INVALID_PROJECT_NAME_FOR_BUILD_DIR`` as a load-time
# diagnostic when ``[project].name`` (or an explicit
# ``[tool.s0ma].build_dir`` last path component) cannot be turned into
# a valid Python identifier even after sanitization. Like
# ``OVERLAPPING_DISCOVERY_ROOTS``, this code IS in ``SEVERITY_MATRIX``
# (error in every mode). The matrix-wide
# ``test_error_codes_in_traceability`` already enforces a traceability
# row; the explicit pin below makes the row's absence a CI failure
# with a G3-specific message and pins the spec prose's load-bearing
# pieces (the sanitization rule and the explicit-validation rule)
# independently of the matrix row's presence.
# ---------------------------------------------------------------------------


def test_invalid_project_name_for_build_dir_in_traceability() -> None:
    """``INVALID_PROJECT_NAME_FOR_BUILD_DIR`` must appear in the traceability matrix.

    The matrix-wide ``test_error_codes_in_traceability`` would catch a
    missing row, but this test pins the code by name so the failure
    message links directly to G3 — making the remediation obvious to
    a future contributor who has never read the cleanup plan.
    """

    text = (DOCS / "spec_traceability.md").read_text(encoding="utf-8")
    assert "`INVALID_PROJECT_NAME_FOR_BUILD_DIR`" in text, (
        "INVALID_PROJECT_NAME_FOR_BUILD_DIR (added in G3 for the "
        "default build_dir sanitization rule) must appear in "
        "docs/spec_traceability.md. The matrix row spells out which "
        "spec section, fixture, and source file own the rule. See "
        "feedback_5-6 cleanup plan G3 for the surrounding context."
    )


def test_spec_documents_build_dir_sanitization_rule() -> None:
    """The spec's `[tool.s0ma]` section must document the sanitization rule.

    G3's behavioural change is that the default `build_dir` now
    sanitizes non-identifier characters in `[project].name` and
    validates explicit `build_dir` basenames. The spec is the canonical
    user-facing description of `[tool.s0ma]`; if the sanitization rule
    is not documented there a consumer reading the spec would miss the
    new behaviour and might still set `build_dir` explicitly out of
    habit.
    """

    spec_path = DOCS / f"s0ma-dsl-spec-v{CURRENT_SPEC_VERSION}.md"
    text = spec_path.read_text(encoding="utf-8")
    assert "INVALID_PROJECT_NAME_FOR_BUILD_DIR" in text, (
        f"{spec_path.name} does not document "
        f"INVALID_PROJECT_NAME_FOR_BUILD_DIR. G3 (feedback 5–6 cleanup) "
        f"added the default build_dir sanitization rule and the "
        f"explicit-build_dir basename-validation rule to "
        f"[tool.s0ma].build_dir; the spec's §4.13 must enumerate the "
        f"rule alongside the other validation rules so consumers "
        f"reading the spec see the constraint."
    )


# ---------------------------------------------------------------------------
# G5-specific cross-reference invariants (feedback 5–6 cleanup plan)
#
# G5 introduces ``STALE_GENERATED_CONFTEST`` as a ``s0ma test`` pre-flight
# diagnostic when the project carries a generated conftest whose banner
# version does not match the running s0ma-dsl version and whose body has
# been customized (or whose body shape we can't classify). The code IS in
# ``SEVERITY_MATRIX`` (error in every mode); the matrix-wide
# ``test_error_codes_in_traceability`` already enforces a traceability row.
# The explicit pins below (a) make the row's absence a CI failure with a
# G5-specific message and (b) pin the spec prose's load-bearing pieces (the
# banner format and the staleness-classifier contract) independently of
# the matrix row's presence.
# ---------------------------------------------------------------------------


def test_stale_generated_conftest_in_traceability() -> None:
    """``STALE_GENERATED_CONFTEST`` must appear in the traceability matrix.

    The matrix-wide ``test_error_codes_in_traceability`` would catch a
    missing row, but this test pins the code by name so the failure
    message links directly to G5 — making the remediation obvious to a
    future contributor who has never read the cleanup plan.
    """

    text = (DOCS / "spec_traceability.md").read_text(encoding="utf-8")
    assert "`STALE_GENERATED_CONFTEST`" in text, (
        "STALE_GENERATED_CONFTEST (added in G5 for the generated-conftest "
        "banner + staleness detection) must appear in "
        "docs/spec_traceability.md. The matrix row spells out which "
        "spec section, fixture, and source file own the rule. See "
        "feedback_5-6 cleanup plan G5 for the surrounding context."
    )


def test_spec_documents_conftest_banner_and_staleness() -> None:
    """The spec's §4.15 (Test Execution) section must document the
    banner format and the five-state classifier.

    G5's behavioural change is that ``s0ma test`` reads a banner on
    the generated conftest before invoking pytest. The spec is the
    canonical user-facing description of ``s0ma test``; if the banner
    contract is not documented there a consumer reading the spec
    would miss the new pre-flight surface.
    """

    spec_path = DOCS / f"s0ma-dsl-spec-v{CURRENT_SPEC_VERSION}.md"
    text = spec_path.read_text(encoding="utf-8")
    assert "STALE_GENERATED_CONFTEST" in text, (
        f"{spec_path.name} does not document STALE_GENERATED_CONFTEST. "
        f"G5 (feedback 5–6 cleanup) added the generated-conftest "
        f"banner + staleness contract to s0ma test's pre-flight; the "
        f"spec's §4.15 must enumerate the rule alongside the other "
        f"runner contracts so consumers reading the spec see the "
        f"constraint."
    )
    # The five classifier states are the canonical user-visible
    # surface; pinning the names here guards against doc drift.
    for state in (
        "absent",
        "current",
        "untouched_stale",
        "customized_stale",
        "unrecognized",
    ):
        assert state in text, (
            f"{spec_path.name} does not name the {state!r} classifier "
            f"state. G5's spec section must enumerate all five states "
            f"(absent / current / untouched_stale / customized_stale / "
            f"unrecognized); a consumer reading the spec needs the full "
            f"list to understand which state their conftest is in."
        )


# ---------------------------------------------------------------------------
# G7a (feedback 5–6 cleanup): ``ERROR_CODE_DESCRIPTIONS`` parity pin.
#
# G7a registered ``ERROR_CODE_DESCRIPTIONS`` next to ``SEVERITY_MATRIX`` as
# the canonical code → human-readable description mapping the doc-ref
# renderer reads from. The dict's invariant is that every code in
# ``SEVERITY_MATRIX | OUT_OF_MATRIX_CODES_THAT_MUST_STILL_BE_TRACEABLE``
# has a description, and no orphan descriptions exist for unregistered
# codes. ``test_doc_ref_error_codes.py`` already pins this for the rendering
# path; the duplicate here lives in the cross-cutting doc-consistency suite
# so a contributor running ``pytest tests/test_doc_consistency.py`` to
# validate documentation surfaces also sees the failure.
# ---------------------------------------------------------------------------


def test_error_code_descriptions_match_severity_registries() -> None:
    """``ERROR_CODE_DESCRIPTIONS`` covers every registered code, no extras.

    G7a (feedback 5–6 cleanup) added the description registry as the
    canonical code → human-readable description mapping for the doc-ref
    error-codes renderer. The dict must stay in lock-step with the union
    of ``SEVERITY_MATRIX`` and
    ``OUT_OF_MATRIX_CODES_THAT_MUST_STILL_BE_TRACEABLE``: every registered
    code needs a description, and the dict carries no orphan entries. Both
    halves of the invariant matter — a missing description renders as an
    em-dash in the generated table (silent drift), and an orphan
    description marks a code that has been retired without cleaning up
    every surface that mentions it.
    """

    every_code = set(SEVERITY_MATRIX.keys()) | set(
        OUT_OF_MATRIX_CODES_THAT_MUST_STILL_BE_TRACEABLE
    )
    described = set(ERROR_CODE_DESCRIPTIONS)

    missing = sorted(every_code - described)
    assert not missing, (
        f"ERROR_CODE_DESCRIPTIONS is missing entries for the following "
        f"registered codes: {missing}. Add a one-sentence description for "
        f"each in src/s0ma_dsl/config.py (next to SEVERITY_MATRIX). G7a's "
        f"doc-ref error-codes renderer reads from this dict — a missing "
        f"entry surfaces as an em-dash in the generated table, which is "
        f"silent drift the renderer cannot recover from."
    )

    extras = sorted(described - every_code)
    assert not extras, (
        f"ERROR_CODE_DESCRIPTIONS carries entries for codes that are not "
        f"registered in SEVERITY_MATRIX or "
        f"OUT_OF_MATRIX_CODES_THAT_MUST_STILL_BE_TRACEABLE: {extras}. "
        f"Either register the code (see docs/coding_agent_handbook.md "
        f"§2.3 for the decision rule) or remove the orphan description."
    )


# ---------------------------------------------------------------------------
# G7b (feedback 5–6 cleanup): Common Errors table pin.
#
# ``docs/_generated/common_errors.md`` is the rendered table portion of the
# ``doc-ref`` declared in ``docs/_generators/common_errors.s0ma`` (committed,
# regenerated by ``make docs-derived``), and it is what the authoring server
# serves to agents as ``s0ma://guide/errors``.
#
# The meta-test below re-renders the ``doc-ref`` at test time and compares
# its table portion against the committed artifact. The comparison is against
# the renderer's CURRENT output, so a hand-edit to the artifact — or a code
# registered without re-running the render — fails loudly with a remediation
# pointing at ``s0ma docs render`` (or the ``make docs-derived`` wrapper).
#
# Until 2026-09-29 the same table was also copied into a bracketed region of
# the hand-authored quick reference, and a second test held that copy to the
# renderer. That document is retired (owner ruling; the generated quick
# reference and the served error catalog cover it), and so is that test.
# ---------------------------------------------------------------------------


_COMMON_ERRORS_GENERATOR = (
    REPO_ROOT / "docs" / "_generators" / "common_errors.s0ma"
)
_COMMON_ERRORS_GENERATED = (
    REPO_ROOT / "docs" / "_generated" / "common_errors.md"
)


def _render_common_errors_doc_ref() -> str:
    """Re-render the in-repo ``CommonErrorsTable`` doc-ref.

    Mirrors the ``s0ma docs render docs/_generators/`` invocation but stays
    in-process so the test does not shell out. Uses the same renderer the
    CLI uses (``render_doc_ref_markdown``), so any future renderer change
    is reflected here without test-side maintenance.
    """

    from s0ma_dsl.codegen.doc_emitter.markdown import render_doc_ref_markdown
    from s0ma_dsl.parser.s0ma_parser import parse_s0ma
    from s0ma_dsl.resolver.doc_resolver import build_project_index

    text = _COMMON_ERRORS_GENERATOR.read_text(encoding="utf-8")
    module = parse_s0ma(text, filename=str(_COMMON_ERRORS_GENERATOR))
    assert len(module.doc_refs) == 1, (
        f"Expected exactly one doc-ref in {_COMMON_ERRORS_GENERATOR}; "
        f"found {len(module.doc_refs)}. The G7b in-repo generator should "
        f"declare a single CommonErrorsTable doc-ref."
    )
    index = build_project_index({module.module.name: module})
    # The frontmatter inputs (content_hash, schema_version) do not affect
    # the table portion the meta-test compares against, so any
    # deterministic stand-in is fine. We pin the values here so a future
    # contributor reading this test sees the frontmatter is intentionally
    # placeholder-shaped. (``transpiler_version`` was dropped from the
    # front matter in 0.8.0 per ADR-011 §(f).)
    return render_doc_ref_markdown(
        module.doc_refs[0],
        index=index,
        content_hash="1:" + "0" * 64,
        schema_version="1.2.0",
    )


def _extract_table_from_render(rendered: str) -> str:
    """Return the ``| Code | ...`` table portion of a doc-ref render.

    The renderer emits frontmatter + heading + intent + table; only the
    table is compared (frontmatter carries version metadata that the
    comparison should not be coupled to). This helper finds the first
    ``| Code |`` line and returns everything from there to end-of-string
    with a single trailing newline.
    """

    lines = rendered.splitlines()
    starts = [i for i, line in enumerate(lines) if line.startswith("| Code |")]
    assert starts, (
        "Rendered doc-ref output does not contain a `| Code |` table "
        "header line. The renderer's source-registry branch must emit a "
        "Markdown table; if the format changed, update this helper to "
        "extract the new table shape."
    )
    table_lines = lines[starts[0]:]
    # Strip trailing blank lines so the comparison is robust against the
    # renderer's trailing-newline convention.
    while table_lines and not table_lines[-1].strip():
        table_lines.pop()
    return "\n".join(table_lines) + "\n"


def test_common_errors_generated_artifact_matches_doc_ref_output() -> None:
    """The committed `docs/_generated/common_errors.md` matches the renderer.

    The pin that catches drift between the renderer and the committed
    artifact — the file the authoring server serves as
    ``s0ma://guide/errors``. A consumer reading it must see the registry
    as it is today, not as it was when somebody last remembered to render.

    Remediation: run ``make docs-derived``.
    """

    assert _COMMON_ERRORS_GENERATED.exists(), (
        f"Expected {_COMMON_ERRORS_GENERATED}. Run `make docs-derived`."
    )
    on_disk = _COMMON_ERRORS_GENERATED.read_text(encoding="utf-8")

    on_disk_table = _extract_table_from_render(on_disk)
    rendered_table = _extract_table_from_render(_render_common_errors_doc_ref())

    assert on_disk_table == rendered_table, (
        f"The table portion of {_COMMON_ERRORS_GENERATED} does not match "
        f"the renderer's current output. The committed artifact has "
        f"drifted from the canonical registry — typically because a new "
        f"error code was registered without re-running "
        f"`make docs-derived`. Run it to regenerate."
    )


# ---------------------------------------------------------------------------
# The spec's field table is the toolchain's field classification
# ---------------------------------------------------------------------------

#: The monorepo's generator for the spec's field table. It renders from
#: ``s0ma_dsl.semantic_state.FIELD_CLASSIFICATIONS``; this test holds the
#: committed table to that render, the way the Common Errors pins above hold
#: the quick reference to its doc-ref.
_FIELD_TABLE_GENERATOR = REPO_ROOT.parent.parent / "scripts" / "generate_spec_field_table.py"


def _field_table_generator() -> ModuleType:
    assert _FIELD_TABLE_GENERATOR.is_file(), (
        f"Expected the spec field-table generator at {_FIELD_TABLE_GENERATOR}."
    )
    loader_spec = importlib.util.spec_from_file_location(
        "generate_spec_field_table", _FIELD_TABLE_GENERATOR
    )
    assert loader_spec is not None and loader_spec.loader is not None
    module = importlib.util.module_from_spec(loader_spec)
    loader_spec.loader.exec_module(module)
    return module


def test_spec_field_table_matches_field_classifications() -> None:
    """Spec §4.14.5's table is rendered from the classification the check enforces.

    The table is the one statement of which lines each declaration must write;
    the declaration sections and Appendix A point at it. A classification
    changed without regenerating the table, or a table edited by hand, fails
    here with the command that fixes it.
    """

    generator = _field_table_generator()
    spec = DOCS / f"s0ma-dsl-spec-v{CURRENT_SPEC_VERSION}.md"
    text = spec.read_text(encoding="utf-8")
    assert text.count(generator.START) == 1 and text.count(generator.END) == 1, (
        f"{spec.name} must carry the generated field-table markers exactly once, "
        "in section 4.14.5."
    )
    committed = text.split(generator.START, 1)[1].split(generator.END, 1)[0]

    assert committed.strip("\n") == generator.render_table(), (
        f"The field table in {spec.name} section 4.14.5 differs from "
        "s0ma_dsl.semantic_state.FIELD_CLASSIFICATIONS. Run "
        "`uv run python scripts/generate_spec_field_table.py --write` from the "
        "repository root, review the diff, and commit the table with the "
        "classification change it reflects."
    )
