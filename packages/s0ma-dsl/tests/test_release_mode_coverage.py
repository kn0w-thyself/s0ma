"""Tests for release-mode test-coverage canonicalisation (M5, feedback 5–6).

The release-mode ``MISSING_TEST_COVERAGE`` check used to compare bare
``nerve.name`` strings against the raw contents of ``test.tests``,
silently ignoring qualified test targets like ``module.Nerve``. This
produced 51 false positives in fr3d's M14 release-mode run.

After M5, both sides of the comparison are canonicalised to
``module::component`` via
:func:`s0ma_dsl.resolver.namespaces.resolve_test_target_canonical`,
which is the single source of truth shared with the IR builder. A
bare target that matches multiple modules now raises a distinct
``AMBIGUOUS_TEST_TARGET`` diagnostic instead of being silently
mis-resolved.

These tests exercise the four scenarios listed in the M5 plan:

  - ``test_release_accepts_qualified_test_target`` — fixture writes
    ``tests: [my_module.MyNerve]`` and the release check is silent.
  - ``test_release_accepts_bare_test_target`` — bare-name coverage of
    an actually-covered nerve still works.
  - ``test_release_flags_truly_uncovered_nerve`` — a genuinely
    uncovered PUBLIC nerve still produces exactly one
    ``MISSING_TEST_COVERAGE`` error.
  - ``test_ambiguous_bare_target_emits_distinct_error`` — two modules
    each defining ``SharedNerve`` plus a third with bare
    ``tests: [SharedNerve]`` produces an ``AMBIGUOUS_TEST_TARGET``
    error rather than a silent miss.

See:
  - plans/feedback_5-6/feedback_5-6_plan.md, Milestone 5
  - plans/feedback_5-6/s0ma-dsl-feedback-5.5.md lines 1099–1136
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from s0ma_dsl.config import StrictnessMode
from s0ma_dsl.parser.s0ma_parser import parse_s0ma_with_warnings
from s0ma_dsl.resolver.dependency import DependencyResolver

if TYPE_CHECKING:
    from s0ma_dsl.ast_nodes.nodes import S0maModule
    from s0ma_dsl.errors import S0maError

_FIXTURES = Path(__file__).parent / "fixtures" / "release_qualified_test_targets"


def _load_project(fixture_dir: Path) -> tuple[dict[str, S0maModule], dict[str, str]]:
    """Parse every ``.s0ma`` file under ``fixture_dir`` into a project view.

    Returns ``(modules, filenames)`` with both dicts keyed by the
    declared module name (the canonical identity, per M4). Mirrors the
    pipeline ``s0ma check`` runs for a multi-file project — parser
    first, resolver second — without involving the CLI's project model.
    """
    modules: dict[str, S0maModule] = {}
    filenames: dict[str, str] = {}
    for s0ma_path in sorted(fixture_dir.glob("*.s0ma")):
        source = s0ma_path.read_text(encoding="utf-8")
        module, _warnings = parse_s0ma_with_warnings(
            source, str(s0ma_path), mode=StrictnessMode.RELEASE,
        )
        modules[module.module.name] = module
        filenames[module.module.name] = str(s0ma_path)
    return modules, filenames


def _release_diagnostics(fixture_dir: Path) -> list[S0maError]:
    """Run the release-mode dependency resolver against a fixture project.

    Skips import resolution (``check_imports=False``) so the test does
    not depend on the fixture's ``requires:`` entries being installed
    in the test environment.
    """
    modules, filenames = _load_project(fixture_dir)
    resolver = DependencyResolver(mode=StrictnessMode.RELEASE)
    return resolver.resolve(modules, filenames=filenames, check_imports=False)


class TestReleaseQualifiedTargets:
    """The four M5 scenarios — qualified, bare, uncovered, ambiguous."""

    def test_release_accepts_qualified_test_target(self) -> None:
        """A ``tests: [my_module.MyNerve]`` entry covers ``my_module::MyNerve``.

        This is the regression for the fr3d M14 false-positive cluster:
        the qualified form must canonicalise to the same key as the
        nerve's per-module check key, so the release coverage check
        sees the nerve as covered.
        """
        diagnostics = _release_diagnostics(_FIXTURES / "qualified")
        coverage = [d for d in diagnostics if d.code == "MISSING_TEST_COVERAGE"]
        assert coverage == [], (
            f"qualified target must canonicalise as covered, got: "
            f"{[d.message for d in coverage]}"
        )

    def test_release_accepts_bare_test_target(self) -> None:
        """A bare ``tests: [BareNerve]`` entry covers the same-module nerve.

        Bare names resolve intra-module first; the canonical form is
        ``bare_module::BareNerve`` on both sides of the check.
        """
        diagnostics = _release_diagnostics(_FIXTURES / "bare")
        coverage = [d for d in diagnostics if d.code == "MISSING_TEST_COVERAGE"]
        assert coverage == [], (
            f"bare same-module target must validate as covered, got: "
            f"{[d.message for d in coverage]}"
        )

    def test_release_flags_truly_uncovered_nerve(self) -> None:
        """A PUBLIC nerve with no covering test still triggers the error.

        The fix must not regress the genuine no-coverage case: the
        ``uncovered`` fixture has two PUBLIC nerves, ``CoveredNerve``
        (covered by a test) and ``UncoveredNerve`` (not). Exactly one
        ``MISSING_TEST_COVERAGE`` error must fire, and it must name
        ``UncoveredNerve``.
        """
        diagnostics = _release_diagnostics(_FIXTURES / "uncovered")
        coverage = [d for d in diagnostics if d.code == "MISSING_TEST_COVERAGE"]
        assert len(coverage) == 1, (
            f"expected exactly one MISSING_TEST_COVERAGE, got: "
            f"{[d.message for d in coverage]}"
        )
        err = coverage[0]
        assert err.severity == "error"
        assert err.context["nerve"] == "UncoveredNerve"
        assert err.context["module"] == "uncovered_module"
        # Remediation must surface both the bare and qualified forms,
        # so the user knows the canonical-form options.
        assert "UncoveredNerve" in err.remediation
        assert "uncovered_module.UncoveredNerve" in err.remediation
        # Canonical ID must round-trip into the diagnostic context for
        # downstream tooling.
        assert err.context["canonical_id"] == "uncovered_module::UncoveredNerve"

    def test_ambiguous_bare_target_emits_distinct_error(self) -> None:
        """Two modules each defining ``SharedNerve`` make a bare target ambiguous.

        ``module_c_tests`` writes ``tests: [SharedNerve]``. Because both
        ``module_a`` and ``module_b`` declare a ``SharedNerve``, the
        bare reference cannot be resolved to a single canonical ID —
        the resolver returns an ``AmbiguousTestTarget`` sentinel and
        the dependency resolver emits ``AMBIGUOUS_TEST_TARGET``.

        The two PUBLIC ``SharedNerve`` nerves remain uncovered (because
        the ambiguous reference cannot canonicalise to either of
        them), so ``MISSING_TEST_COVERAGE`` also fires for them. That
        is the documented behaviour: ambiguity does not silently
        satisfy coverage; the user must qualify the target.
        """
        diagnostics = _release_diagnostics(_FIXTURES / "ambiguous")
        ambiguous = [d for d in diagnostics if d.code == "AMBIGUOUS_TEST_TARGET"]
        assert len(ambiguous) == 1, (
            f"expected exactly one AMBIGUOUS_TEST_TARGET, got: "
            f"{[d.message for d in ambiguous]}"
        )
        err = ambiguous[0]
        assert err.severity == "error", (
            "AMBIGUOUS_TEST_TARGET is an error in every mode"
        )
        assert err.context["raw_target"] == "SharedNerve"
        candidates = set(err.context["candidates"])
        assert candidates == {
            "module_a::SharedNerve",
            "module_b::SharedNerve",
        }
        # Remediation must point the user at the qualified form and
        # surface the candidate canonical IDs so the fix is mechanical.
        assert "Qualify the target" in err.remediation
        assert "<module>.SharedNerve" in err.remediation
        assert "module_a::SharedNerve" in err.remediation
        assert "module_b::SharedNerve" in err.remediation

    def test_ambiguous_target_fires_in_every_mode(self) -> None:
        """``AMBIGUOUS_TEST_TARGET`` is mode-independent (correctness invariant).

        A real ambiguity is not a style preference: the IR cannot
        render a verification edge with two valid targets. The severity
        matrix marks it ``error`` in MIGRATION/DEV/STRICT/RELEASE
        alike, mirroring ``MODULE_NAME_STEM_MISMATCH`` (M4).
        """
        modules, filenames = _load_project(_FIXTURES / "ambiguous")
        for mode in StrictnessMode:
            resolver = DependencyResolver(mode=mode)
            diagnostics = resolver.resolve(
                modules, filenames=filenames, check_imports=False
            )
            ambiguous = [
                d for d in diagnostics if d.code == "AMBIGUOUS_TEST_TARGET"
            ]
            assert len(ambiguous) == 1, (
                f"AMBIGUOUS_TEST_TARGET must fire in mode {mode.name}, got: "
                f"{[d.message for d in ambiguous]}"
            )
            assert ambiguous[0].severity == "error"


class TestCanonicalResolverSharedAcrossPasses:
    """The IR builder and the dependency resolver canonicalise identically.

    Per M5's hard-right-path principle: there is exactly one helper
    (:func:`canonicalize_qualified_target`) that splits a qualified
    target into ``module::component``. Both the IR builder's
    ``_resolve_target_canonical`` and the dependency resolver's
    ``resolve_test_target_canonical`` call into it, so the two passes
    cannot drift on syntactic split rules.
    """

    def test_ir_builder_uses_namespaces_helper(self) -> None:
        """``IRBuilder._resolve_target_canonical`` delegates to the shared helper."""
        from s0ma_dsl.ir.builder import IRBuilder
        from s0ma_dsl.resolver.namespaces import canonicalize_qualified_target

        # Bare target — both helpers prefix with the source module.
        assert (
            IRBuilder._resolve_target_canonical("MyNerve", "my_module")
            == canonicalize_qualified_target("MyNerve", "my_module")
            == "my_module::MyNerve"
        )

        # Qualified target — both split on the last dot identically.
        assert (
            IRBuilder._resolve_target_canonical(
                "other_module.OtherNerve", "my_module",
            )
            == canonicalize_qualified_target(
                "other_module.OtherNerve", "my_module",
            )
            == "other_module::OtherNerve"
        )
