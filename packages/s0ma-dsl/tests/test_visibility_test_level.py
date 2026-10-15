"""Tests for ``visibility: TEST`` — the third declarative visibility level (M8).

The M8 milestone introduces ``Visibility.TEST`` as a first-class language
level. The semantics, per ADR-008 and spec §4.10.1:

  - **Intra-module**: production code in the same module can call a
    ``TEST``-visibility component just like any other intra-module
    reference (no ``uses:`` needed).
  - **Cross-module test access**: a module that contains at least one
    ``test`` declaration may add a ``TEST``-visibility component to its
    ``uses:`` list. The cross-module import resolves cleanly.
  - **Cross-module production access is hard-blocked**: a module that
    contains zero ``test`` declarations may **not** add a
    ``TEST``-visibility component to its ``uses:`` list. The resolver
    emits ``TEST_VISIBILITY_VIOLATION`` (error in every strictness mode).
  - **Export discipline**: ``TEST`` components are not in the public
    export surface. Omitting them from ``exports:`` is correct and
    expected; including them is a ``VISIBILITY_MISMATCH`` error.

These tests exercise the five scenarios listed in the M8 plan plus an
``inspect``-output check that pins the new pretty-printer label.

See:
  - plans/feedback_5-6/feedback_5-6_plan.md, Milestone 8
  - plans/feedback_5-6/s0ma-dsl-feedback-5.5.md lines 984–1019
  - docs/adr/ADR-008-test-visibility.md
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from s0ma_dsl.ast_nodes.enums import Visibility
from s0ma_dsl.config import StrictnessMode
from s0ma_dsl.parser.s0ma_parser import parse_s0ma_with_warnings
from s0ma_dsl.resolver.dependency import DependencyResolver

if TYPE_CHECKING:
    from s0ma_dsl.ast_nodes.nodes import S0maModule
    from s0ma_dsl.errors import S0maError

_FIXTURES = Path(__file__).parent / "fixtures" / "visibility_test_level"


def _load_project(fixture_dir: Path) -> tuple[
    dict[str, S0maModule], dict[str, str]
]:
    """Parse every ``.s0ma`` file under ``fixture_dir`` into a project view.

    Walks both the ``src/`` and ``tests/`` subtrees because M8's check
    is sensitive to which modules are test-shaped (any ``test`` decl
    counts).
    """
    modules: dict[str, S0maModule] = {}
    filenames: dict[str, str] = {}
    for s0ma_path in sorted(fixture_dir.rglob("*.s0ma")):
        source = s0ma_path.read_text(encoding="utf-8")
        module, _warnings = parse_s0ma_with_warnings(
            source, str(s0ma_path), mode=StrictnessMode.STRICT,
        )
        modules[module.module.name] = module
        filenames[module.module.name] = str(s0ma_path)
    return modules, filenames


def _resolve(
    fixture_dir: Path, mode: StrictnessMode = StrictnessMode.STRICT,
) -> list[S0maError]:
    """Run the cross-module dependency resolver against a fixture project."""
    modules, filenames = _load_project(fixture_dir)
    resolver = DependencyResolver(mode=mode)
    return resolver.resolve(modules, filenames=filenames, check_imports=False)


class TestTestVisibilityAccessControl:
    """The four core access-control scenarios from the M8 plan."""

    def test_test_visibility_accessible_from_test_module(self) -> None:
        """A test module can ``uses:`` a TEST-visibility nerve cleanly.

        Fixture: ``clean/`` declares ``text_helpers.escape_text`` with
        ``visibility: TEST`` and a sibling test module that imports it
        via ``uses: [text_helpers.escape_text]``. The strict-mode
        resolver must produce zero errors against this combination —
        if it does, the access-control rule is wrong by construction.
        """
        diagnostics = _resolve(_FIXTURES / "clean")
        errors = [d for d in diagnostics if d.severity == "error"]
        assert errors == [], (
            f"clean fixture must validate without errors; got: "
            f"{[(d.code, d.message) for d in errors]}"
        )

    def test_test_visibility_inaccessible_from_production_module(self) -> None:
        """A production module that ``uses:`` a TEST nerve must error.

        Fixture: ``violation/`` declares ``text_helpers.escape_text``
        (TEST visibility) and a *production* consumer that adds it to
        ``uses:``. The consumer has zero ``test`` declarations, so it
        does not qualify as a test consumer. The resolver must emit
        exactly one ``TEST_VISIBILITY_VIOLATION`` against the
        offending ``uses:`` entry.
        """
        diagnostics = _resolve(_FIXTURES / "violation")
        violations = [
            d for d in diagnostics if d.code == "TEST_VISIBILITY_VIOLATION"
        ]
        assert len(violations) == 1, (
            f"expected exactly one TEST_VISIBILITY_VIOLATION; got: "
            f"{[(d.code, d.message) for d in diagnostics]}"
        )
        violation = violations[0]
        # Pin the diagnostic's load-bearing context fields so future
        # refactors can't silently drop them.
        ctx = violation.context or {}
        assert ctx.get("source_module") == "production_consumer"
        assert ctx.get("target_module") == "text_helpers"
        assert ctx.get("target_component") == "escape_text"
        assert ctx.get("target_visibility") == "TEST"
        assert violation.severity == "error"

    def test_test_visibility_intra_module_access_works(self) -> None:
        """Intra-module references to a TEST nerve are unconstrained.

        Visibility levels gate *cross-module* access. A PUBLIC nerve
        in the same module that calls a TEST nerve does not need a
        ``uses:`` entry and is not subject to the
        ``TEST_VISIBILITY_VIOLATION`` rule. Fixture: ``clean/``'s
        ``render_html`` (PUBLIC) calls ``escape_text`` (TEST) inline.
        """
        modules, _filenames = _load_project(_FIXTURES / "clean")
        text_helpers = modules["text_helpers"]
        # Sanity-check the fixture: the two nerves exist with the
        # expected visibilities.
        nerve_by_name = {n.name: n for n in text_helpers.nerves}
        assert nerve_by_name["escape_text"].visibility == Visibility.TEST
        assert nerve_by_name["render_html"].visibility == Visibility.PUBLIC
        # The strict resolver run from the previous test already proved
        # the intra-module reference is accepted; this test pins the
        # structural shape so a future refactor that splits the rule
        # into a per-decl check sees the intra-module path explicitly.
        diagnostics = _resolve(_FIXTURES / "clean")
        intra_module_violations = [
            d for d in diagnostics
            if d.code == "TEST_VISIBILITY_VIOLATION"
            and (d.context or {}).get("source_module") == "text_helpers"
        ]
        assert intra_module_violations == [], (
            "intra-module TEST access must not fire "
            "TEST_VISIBILITY_VIOLATION"
        )

    def test_inspect_shows_test_visibility_distinctly(
        self, capsys: pytest.CaptureFixture[str], tmp_path: Path,
    ) -> None:
        """``s0ma inspect`` renders ``[TEST <KIND> nerve]`` for TEST nerves.

        Builds the clean fixture into a tmp build dir, then invokes the
        in-process ``s0ma inspect <build_dir>/text_helpers.s0ma.json``
        and asserts the human-readable summary contains the new
        ``TEST`` label alongside the existing ``PUBLIC``/``INTERNAL``
        labels.
        """
        from s0ma_dsl.cli.main import S0maCLI

        clean_dir = _FIXTURES / "clean"
        build_dir = tmp_path / "build"
        cli = S0maCLI()
        # Build the source roots into the temp dir.
        rc = cli.run([
            "build",
            str(clean_dir / "src" / "sample"),
            "--output-dir", str(build_dir),
        ])
        # Drain captured output from the build pass before we run
        # inspect so the `inspect` capture is isolated.
        capsys.readouterr()
        assert rc == 0, "fixture build must succeed"
        ir_path = build_dir / "text_helpers.s0ma.json"
        assert ir_path.exists(), f"IR not emitted at {ir_path}"
        # Sanity-check the IR records visibility=TEST.
        ir = json.loads(ir_path.read_text(encoding="utf-8"))
        visibilities = {
            c["canonical_id"]: c.get("visibility") for c in ir["components"]
        }
        assert visibilities.get("text_helpers::escape_text") == "TEST"
        assert visibilities.get("text_helpers::render_html") == "PUBLIC"
        # Now invoke `s0ma inspect` in-process and capture stdout.
        rc_inspect = cli.run(["inspect", str(ir_path)])
        captured = capsys.readouterr()
        assert rc_inspect == 0, (
            f"`s0ma inspect` failed: stderr={captured.err!r}"
        )
        # The pretty-printer renders `<canonical_id> [VIS KIND
        # nerve]`. Pin both the TEST tag and confirm the PUBLIC nerve
        # still renders correctly alongside it.
        assert "[TEST FUNCTION nerve]" in captured.out, (
            f"expected '[TEST FUNCTION nerve]' in inspect output; "
            f"got:\n{captured.out}"
        )
        assert "[PUBLIC FUNCTION nerve]" in captured.out, (
            "PUBLIC label must continue to render alongside TEST"
        )

    def test_test_visibility_does_not_require_export_entry(self) -> None:
        """Omitting a TEST nerve from ``exports:`` is not a NOT_EXPORTED error.

        The production-side claim: TEST components are not part of the
        public export surface. The intra-module
        ``_check_visibility_export_consistency`` validator must not
        fire ``VISIBILITY_MISMATCH`` for a non-exported TEST component;
        the cross-module phase-2 resolver must not fire
        ``NOT_EXPORTED`` when a test-consumer ``uses:`` it.
        """
        diagnostics = _resolve(_FIXTURES / "clean")
        not_exported_for_escape_text = [
            d for d in diagnostics
            if d.code == "NOT_EXPORTED"
            and (d.context or {}).get("target_component") == "escape_text"
        ]
        assert not_exported_for_escape_text == [], (
            "TEST-visibility nerves are exempt from NOT_EXPORTED; got: "
            f"{[(d.code, d.message) for d in not_exported_for_escape_text]}"
        )
        # The intra-module validator runs at parse time, not in the
        # resolver — so the parse step already proved
        # `_check_visibility_export_consistency` accepted the fixture.
        # Pin that explicitly so a future refactor that moves the
        # check elsewhere preserves the contract.
        from s0ma_dsl.semantic.validator import IntraModuleValidator
        modules, _filenames = _load_project(_FIXTURES / "clean")
        text_helpers = modules["text_helpers"]
        validator = IntraModuleValidator(filename=str(
            _FIXTURES / "clean" / "src" / "sample" / "text_helpers.s0ma"
        ))
        intra_errors = validator.validate(text_helpers)
        visibility_mismatches = [
            e for e in intra_errors if e.code == "VISIBILITY_MISMATCH"
        ]
        assert visibility_mismatches == [], (
            f"non-exported TEST nerves must not trigger "
            f"VISIBILITY_MISMATCH; got: "
            f"{[e.message for e in visibility_mismatches]}"
        )


class TestTestVisibilityModeIndependence:
    """``TEST_VISIBILITY_VIOLATION`` is an error in every strictness mode."""

    @pytest.mark.parametrize(
        "mode",
        list(StrictnessMode),
        ids=lambda m: m.value,
    )
    def test_violation_fires_in_every_mode(
        self, mode: StrictnessMode,
    ) -> None:
        """The access-control rule cannot be downgraded by mode.

        ``TEST_VISIBILITY_VIOLATION`` is registered in
        ``SEVERITY_MATRIX`` as ``error`` for migration, dev, strict, and
        release. This test pins that contract by re-running the
        violation fixture against each mode.
        """
        diagnostics = _resolve(_FIXTURES / "violation", mode=mode)
        violations = [
            d for d in diagnostics if d.code == "TEST_VISIBILITY_VIOLATION"
        ]
        assert len(violations) == 1, (
            f"mode={mode.value}: expected exactly one violation; got: "
            f"{[(d.code, d.message) for d in diagnostics]}"
        )
        assert violations[0].severity == "error"
