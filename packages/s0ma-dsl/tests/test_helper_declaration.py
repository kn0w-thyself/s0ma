"""Tests for the ``helper`` declaration kind (M13, feedback 5–6).

The M13 milestone introduces ``helper`` as a fourth top-level declaration
kind alongside ``nerve``, ``cell``, and ``ganglion``. The semantics, per
the M13 plan section:

  - **Module-private**: helpers live at module scope but are *not*
    registered as components. Codegen emits a plain ``def`` with no
    ``@component`` decorator and no ``register_*()`` call. The
    ``__all__`` list is unaffected.
  - **Introspectable**: helpers appear in the IR's ``helpers`` array
    and in ``s0ma inspect`` under a separate ``[helpers]`` section so
    the principle "machines sense their own components" is preserved
    even though the helper is not in the component graph.
  - **Intra-module access**: a nerve in the same module may call a
    helper directly — helpers are in scope.
  - **Test cross-module access**: a module that contains at least one
    ``test`` declaration may import a helper from another module via
    ``uses:`` (mirroring ``visibility: TEST`` from M8).
  - **Production cross-module access is hard-blocked**: a production
    module that adds a helper to its ``uses:`` triggers
    ``HELPER_PRIVATE_TO_MODULE`` (error in every strictness mode).

These tests exercise the five scenarios listed in the M13 plan and pin
the structural shape of the new declaration kind against the IR.

See:
  - plans/feedback_5-6/feedback_5-6_plan.md, Milestone 13
  - plans/feedback_5-6/s0ma-dsl-feedback-5.md MS 1 (~160 lines of nested helpers)
  - plans/feedback_5-6/s0ma-dsl-feedback-6.md MS 13/16 (recorder duplication)
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from s0ma_dsl.ast_nodes.nodes import HelperDecl, S0maModule
from s0ma_dsl.config import StrictnessMode
from s0ma_dsl.parser.s0ma_parser import parse_s0ma_with_warnings
from s0ma_dsl.resolver.dependency import DependencyResolver

if TYPE_CHECKING:
    from s0ma_dsl.errors import S0maError

_FIXTURES = Path(__file__).parent / "fixtures" / "helper_declarations"


def _load_project(fixture_dir: Path) -> tuple[
    dict[str, S0maModule], dict[str, str]
]:
    """Parse every ``.s0ma`` file under ``fixture_dir`` into a project view."""
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


class TestHelperEmission:
    """Codegen emits helpers as plain module-scope ``def``s."""

    def test_helper_emits_plain_def(self, tmp_path: Path) -> None:
        """Generated ``.py`` has ``def _format_attendee`` and no ``register_*()``.

        The helper must NOT carry an ``@component`` decorator and must NOT
        appear in any ``register_*(...)`` call. It must NOT appear in the
        module's ``__all__`` list. The body is emitted verbatim under a
        ``# Helper: <intent>`` comment so readers of the generated source
        see why the helper exists.
        """
        from s0ma_dsl.cli.main import S0maCLI

        clean_dir = _FIXTURES / "clean"
        build_dir = tmp_path / "build"
        cli = S0maCLI()
        rc = cli.run([
            "build",
            str(clean_dir / "src" / "sample"),
            "--output-dir", str(build_dir),
        ])
        assert rc == 0, "fixture build must succeed"

        py_path = build_dir / "event_builder.py"
        assert py_path.exists(), f"emitted .py not found at {py_path}"
        py_content = py_path.read_text(encoding="utf-8")

        # The helper appears as a plain top-level ``def``.
        assert "def _format_attendee(" in py_content
        assert "def _format_event_body(" in py_content

        # The helper must NOT carry an @component decorator and must
        # not appear in any register_*() call.
        assert "register_helper(" not in py_content
        # No @component decorator before the helper def. The def is
        # anchored by a ``# Helper:`` comment — and, since 0.13.0 M3, the
        # passive ``# s0ma:`` source pointer sits between that anchor and
        # the def (at the body boundary). Both comment lines precede the
        # def; neither is a ``@component(`` line.
        helper_def_idx = py_content.index("def _format_attendee(")
        prefix_lines = py_content[:helper_def_idx].rstrip().split("\n")
        pointer_line = prefix_lines[-1] if prefix_lines else ""
        anchor_line = prefix_lines[-2] if len(prefix_lines) >= 2 else ""
        assert pointer_line.startswith("# s0ma:"), (
            f"helper def must be preceded by its M3 source pointer; "
            f"got preceding line: {pointer_line!r}"
        )
        assert anchor_line.startswith("# Helper:"), (
            f"helper def must be anchored by a '# Helper:' comment; "
            f"got line above the pointer: {anchor_line!r}"
        )

        # __all__ excludes the helper.
        assert '"_format_attendee"' not in py_content
        assert '"_format_event_body"' not in py_content
        # The exported nerve is in __all__.
        assert '"build_event_payload"' in py_content


class TestHelperVisibility:
    """Intra-module / cross-module / test-module access semantics."""

    def test_helper_visible_intra_module(self) -> None:
        """A nerve in the same module may call a helper directly.

        The clean fixture's ``build_event_payload`` calls
        ``_format_event_body`` which calls ``_format_attendee`` —
        all intra-module. The strict-mode resolver must produce zero
        errors, and the parsed module must record both helpers.
        """
        modules, _filenames = _load_project(_FIXTURES / "clean")
        event_builder = modules["event_builder"]
        helpers_by_name = {h.name: h for h in event_builder.helpers}
        assert set(helpers_by_name) == {
            "_format_attendee", "_format_event_body",
        }
        # The intra-module reference path must validate clean.
        diagnostics = _resolve(_FIXTURES / "clean")
        errors = [d for d in diagnostics if d.severity == "error"]
        assert errors == [], (
            f"clean fixture must validate without errors; got: "
            f"{[(d.code, d.message) for d in errors]}"
        )

    def test_helper_invisible_to_production_other_module(self) -> None:
        """A production module that ``uses:`` a helper must error.

        Fixture: ``violation/`` declares two modules. ``event_builder``
        carries the helpers; ``production_consumer`` is a production
        module (zero ``test`` declarations) that adds
        ``event_builder._format_attendee`` to its ``uses:`` list. The
        resolver must emit exactly one ``HELPER_PRIVATE_TO_MODULE``
        with the offending source/target context fields populated.
        """
        diagnostics = _resolve(_FIXTURES / "violation")
        violations = [
            d for d in diagnostics if d.code == "HELPER_PRIVATE_TO_MODULE"
        ]
        assert len(violations) == 1, (
            f"expected exactly one HELPER_PRIVATE_TO_MODULE; got: "
            f"{[(d.code, d.message) for d in diagnostics]}"
        )
        violation = violations[0]
        ctx = violation.context or {}
        assert ctx.get("source_module") == "production_consumer"
        assert ctx.get("target_module") == "event_builder"
        assert ctx.get("target_component") == "_format_attendee"
        assert ctx.get("target_kind") == "helper"
        assert violation.severity == "error"

    def test_helper_visible_to_test_module(self) -> None:
        """A test module in another file may import a helper.

        Fixture: ``clean/`` ships ``tests/event_builder_tests.s0ma``,
        whose ``uses:`` list reaches ``event_builder._format_attendee``.
        Because the consumer carries at least one ``test`` declaration,
        the access-control rule allows the import — no
        ``HELPER_PRIVATE_TO_MODULE`` is emitted, and the import is
        otherwise valid.
        """
        diagnostics = _resolve(_FIXTURES / "clean")
        helper_violations = [
            d for d in diagnostics if d.code == "HELPER_PRIVATE_TO_MODULE"
        ]
        assert helper_violations == [], (
            f"test-module access must NOT emit HELPER_PRIVATE_TO_MODULE; "
            f"got: {[(d.code, d.message) for d in helper_violations]}"
        )
        # Helpers are also exempt from the export check — the resolver
        # must not fire ``NOT_EXPORTED`` against the helper either.
        not_exported = [
            d for d in diagnostics
            if d.code == "NOT_EXPORTED"
            and (d.context or {}).get("target_component", "").startswith("_")
        ]
        assert not_exported == [], (
            f"helpers are not exported; NOT_EXPORTED must not fire on "
            f"helper imports. Got: {[(d.code, d.message) for d in not_exported]}"
        )


class TestHelperIntrospection:
    """``s0ma inspect`` shows helpers in a separate ``[helpers]`` section."""

    def test_inspect_shows_helpers(
        self, capsys: pytest.CaptureFixture[str], tmp_path: Path,
    ) -> None:
        """Build the fixture, run ``s0ma inspect``, assert the helpers section.

        The IR records each helper under ``IRDocument.helpers`` (a new
        top-level array introduced in schema 1.2.0). The pretty-printer
        renders a ``Helpers (N):`` block with one row per helper, tagged
        ``[helper]`` so the reader can distinguish them from the
        component graph above.
        """
        from s0ma_dsl.cli.main import S0maCLI

        clean_dir = _FIXTURES / "clean"
        build_dir = tmp_path / "build"
        cli = S0maCLI()
        rc = cli.run([
            "build",
            str(clean_dir / "src" / "sample"),
            "--output-dir", str(build_dir),
        ])
        capsys.readouterr()
        assert rc == 0, "fixture build must succeed"

        ir_path = build_dir / "event_builder.s0ma.json"
        assert ir_path.exists(), f"IR not emitted at {ir_path}"
        ir = json.loads(ir_path.read_text(encoding="utf-8"))

        # IR records helpers in their own array, NOT under components.
        helper_names = {h["name"] for h in ir.get("helpers", [])}
        assert helper_names == {"_format_attendee", "_format_event_body"}, (
            f"expected helpers in IR; got: {helper_names}"
        )
        component_ids = {c["canonical_id"] for c in ir["components"]}
        assert "event_builder::_format_attendee" not in component_ids, (
            "helpers must NOT appear in the IR components array"
        )
        assert "event_builder::_format_event_body" not in component_ids

        # Each helper carries its intent and a canonical_id.
        helpers_by_name = {h["name"]: h for h in ir["helpers"]}
        assert helpers_by_name["_format_attendee"]["canonical_id"] == (
            "event_builder::_format_attendee"
        )
        assert "Format a single attendee" in (
            helpers_by_name["_format_attendee"]["intent"]["value"]
        )

        # Run ``s0ma inspect`` in-process and capture stdout.
        rc_inspect = cli.run(["inspect", str(ir_path)])
        captured = capsys.readouterr()
        assert rc_inspect == 0, (
            f"`s0ma inspect` failed: stderr={captured.err!r}"
        )
        # The pretty-printer renders a ``Helpers (N):`` section header
        # followed by one row per helper tagged ``[helper]``.
        assert "Helpers (2):" in captured.out, (
            f"expected 'Helpers (2):' in inspect output; got:\n"
            f"{captured.out}"
        )
        assert "event_builder::_format_attendee [helper]" in captured.out
        assert "event_builder::_format_event_body [helper]" in captured.out


class TestHelperModeIndependence:
    """``HELPER_PRIVATE_TO_MODULE`` is an error in every strictness mode."""

    @pytest.mark.parametrize(
        "mode",
        list(StrictnessMode),
        ids=lambda m: m.value,
    )
    def test_violation_fires_in_every_mode(
        self, mode: StrictnessMode,
    ) -> None:
        """The access-control rule cannot be downgraded by mode.

        Mirrors the mode-independence pin used for the M5
        ``AMBIGUOUS_TEST_TARGET`` and M8 ``TEST_VISIBILITY_VIOLATION``
        rules: a future severity-matrix edit cannot silently weaken the
        helper privacy rule.
        """
        diagnostics = _resolve(_FIXTURES / "violation", mode=mode)
        violations = [
            d for d in diagnostics if d.code == "HELPER_PRIVATE_TO_MODULE"
        ]
        assert len(violations) == 1, (
            f"mode={mode.value}: expected exactly one violation; got: "
            f"{[(d.code, d.message) for d in diagnostics]}"
        )
        assert violations[0].severity == "error"


class TestHelperASTShape:
    """The ``HelperDecl`` dataclass enforces the M13 contract."""

    def test_helperdecl_has_no_visibility_or_kind_fields(self) -> None:
        """Helpers do not have ``kind`` or ``visibility`` fields by design.

        The M13 plan is explicit: helpers IS module-private, IS
        introspectable, IS NOT a registered component. They have no
        ``kind`` and no ``visibility`` field — both are component
        contracts that don't apply to helpers. Pin the dataclass shape
        so a future "add visibility for completeness" refactor can't
        slip past review.
        """
        modules, _filenames = _load_project(_FIXTURES / "clean")
        event_builder = modules["event_builder"]
        helper = event_builder.helpers[0]
        assert isinstance(helper, HelperDecl)
        assert not hasattr(helper, "kind"), (
            "HelperDecl must not carry a 'kind' field"
        )
        assert not hasattr(helper, "visibility"), (
            "HelperDecl must not carry a 'visibility' field"
        )
        assert not hasattr(helper, "expects"), (
            "HelperDecl must not carry an 'expects' field"
        )
        assert not hasattr(helper, "guarantees"), (
            "HelperDecl must not carry a 'guarantees' field"
        )
        # Required positive fields.
        assert helper.name.startswith("_")
        assert helper.intent  # required by parser
        assert helper.body is not None
