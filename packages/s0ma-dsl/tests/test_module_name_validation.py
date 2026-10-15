"""Tests for the M4 (feedback 5–6) MODULE_NAME_STEM_MISMATCH check.

The intra-module validator must enforce that the source filename's stem
equals the declared ``module <name>``. This is a hard correctness
invariant: the module name is the canonical identity used as the cache
key, the basis for output filenames, and the import name resolved by
``uses:`` references. Allowing the two to diverge produces silent
broken imports at runtime (feedback-6 CRIT-2).

Tests:
  - ``test_matching_module_name_passes`` — the matching fixture validates clean.
  - ``test_mismatched_module_name_errors`` — the mismatched fixture produces
    exactly one MODULE_NAME_STEM_MISMATCH error with the documented remediation.
  - ``test_cache_key_uses_module_name`` — transpiling a fixture writes
    output files named after ``module.name`` (which the validator now
    requires to equal the file stem).

See:
  - plans/feedback_5-6/feedback_5-6_plan.md, Milestone 4
  - docs/adr/ADR-006-canonical-module-identity.md
"""

from __future__ import annotations

from pathlib import Path

from s0ma_dsl.config import StrictnessMode
from s0ma_dsl.parser.s0ma_parser import parse_s0ma_with_warnings
from s0ma_dsl.semantic.validator import validate_module

_FIXTURES = Path(__file__).parent / "fixtures"


def _parse_and_validate(
    fixture_path: Path,
    *,
    mode: StrictnessMode = StrictnessMode.DEV,
):
    """Parse a fixture and run intra-module validation.

    Returns ``(module, all_diagnostics)`` where ``all_diagnostics``
    folds in both parser warnings and validator errors. Mirrors the
    pipeline order used by ``s0ma check``.
    """
    source = fixture_path.read_text(encoding="utf-8")
    module, warnings = parse_s0ma_with_warnings(
        source, str(fixture_path), mode=mode,
    )
    errors = validate_module(module, mode=mode, filename=str(fixture_path))
    return module, list(warnings) + list(errors)


class TestModuleNameStemMismatch:
    """The MODULE_NAME_STEM_MISMATCH check fires when stem != module name."""

    def test_matching_module_name_passes(self) -> None:
        """A fixture whose stem == declared module name validates clean.

        ``module_name_matches_stem.s0ma`` declares
        ``module module_name_matches_stem`` — the validator must emit
        zero MODULE_NAME_STEM_MISMATCH diagnostics.
        """
        fixture = _FIXTURES / "module_name_matches_stem.s0ma"
        _, diags = _parse_and_validate(fixture)
        mismatches = [d for d in diags if d.code == "MODULE_NAME_STEM_MISMATCH"]
        assert mismatches == [], (
            f"matching fixture must validate clean of MODULE_NAME_STEM_MISMATCH, "
            f"got: {[d.message for d in mismatches]}"
        )

    def test_mismatched_module_name_errors(self) -> None:
        """A fixture whose stem != module name produces one MODULE_NAME_STEM_MISMATCH.

        ``module_name_mismatched.s0ma`` declares ``module wrong_name``.
        The validator must emit exactly one error with the documented
        remediation pointing to both the rename-the-file and the
        rename-the-declaration options.
        """
        fixture = _FIXTURES / "module_name_mismatched.s0ma"
        _, diags = _parse_and_validate(fixture)
        mismatches = [d for d in diags if d.code == "MODULE_NAME_STEM_MISMATCH"]

        assert len(mismatches) == 1, (
            f"mismatched fixture must produce exactly one "
            f"MODULE_NAME_STEM_MISMATCH error, got: "
            f"{[d.message for d in mismatches]}"
        )
        err = mismatches[0]
        assert err.severity == "error"
        assert err.context["declared_module_name"] == "wrong_name"
        assert err.context["actual_file_stem"] == "module_name_mismatched"
        # Remediation must surface both options the spec promises.
        assert "Rename the source file" in err.remediation
        assert "module_name_mismatched.s0ma" in err.remediation or (
            "wrong_name.s0ma" in err.remediation
        )

    def test_mismatched_errors_in_strict_mode(self) -> None:
        """MODULE_NAME_STEM_MISMATCH is an error in strict mode too.

        Per the SEVERITY_MATRIX entry, the code is ``error`` in every
        StrictnessMode — there is no warning ladder.
        """
        fixture = _FIXTURES / "module_name_mismatched.s0ma"
        _, diags = _parse_and_validate(fixture, mode=StrictnessMode.STRICT)
        mismatches = [d for d in diags if d.code == "MODULE_NAME_STEM_MISMATCH"]
        assert len(mismatches) == 1
        assert mismatches[0].severity == "error"

    def test_mismatched_errors_in_release_mode(self) -> None:
        """MODULE_NAME_STEM_MISMATCH is an error in release mode too.

        Hard invariant: a divergent stem/name pair must never be
        allowed to ship.
        """
        fixture = _FIXTURES / "module_name_mismatched.s0ma"
        _, diags = _parse_and_validate(fixture, mode=StrictnessMode.RELEASE)
        mismatches = [d for d in diags if d.code == "MODULE_NAME_STEM_MISMATCH"]
        assert len(mismatches) == 1
        assert mismatches[0].severity == "error"


class TestCacheKeyUsesModuleName:
    """The transpiler writes outputs named after ``module.name``.

    Under the M4 invariant, the validator guarantees ``stem ==
    module.name`` on any file that reaches emission, so the two are
    equivalent — but the canonical identity is the module name, and
    this test pins that contract by exercising a fixture whose output
    files must therefore exist under ``<module.name>.{py,s0ma.json,
    s0ma.map}``.
    """

    def test_cache_key_uses_module_name(self, tmp_path: Path) -> None:
        from s0ma_dsl.cli.main import _transpile_single_file

        fixture = _FIXTURES / "module_name_matches_stem.s0ma"
        out_dir = tmp_path / "out"
        out_dir.mkdir()

        diagnostics, outputs = _transpile_single_file(
            fixture,
            mode=StrictnessMode.DEV,
            output_dir=out_dir,
        )
        blocking = [d for d in diagnostics if d.severity == "error"]
        assert blocking == [], (
            f"matching fixture must transpile cleanly, got errors: "
            f"{[d.message for d in blocking]}"
        )

        # Output filenames must derive from module.name.
        assert (out_dir / "module_name_matches_stem.py").exists()
        assert (out_dir / "module_name_matches_stem.s0ma.json").exists()
        # Source map is optional but the helper emits it by default.
        assert (out_dir / "module_name_matches_stem.s0ma.map").exists()


class TestModuleNameExtractor:
    """The cache's module-name extractor finds the canonical identity
    without invoking the full parser.
    """

    def test_extracts_simple_module_name(self, tmp_path: Path) -> None:
        from s0ma_dsl.cache import extract_module_name

        src = tmp_path / "any_filename.s0ma"
        src.write_text(
            "module canonical_name\n"
            "    layer: DOMAIN\n"
            "    version: 1.0.0\n",
            encoding="utf-8",
        )
        # The extractor returns the *declared* name, not the stem —
        # so the cache key follows the IR's identity even before the
        # validator catches the mismatch on the next pass.
        assert extract_module_name(src) == "canonical_name"

    def test_falls_back_to_stem_when_header_missing(self, tmp_path: Path) -> None:
        from s0ma_dsl.cache import extract_module_name

        # No ``module`` declaration — the file will fail parse, but the
        # cache must not crash. Falling back to the stem keeps the
        # cache layout deterministic for the diagnostic path.
        src = tmp_path / "headerless.s0ma"
        src.write_text("# just a comment\n", encoding="utf-8")
        assert extract_module_name(src) == "headerless"

    def test_skips_leading_comment_lines(self, tmp_path: Path) -> None:
        from s0ma_dsl.cache import extract_module_name

        src = tmp_path / "with_preamble.s0ma"
        src.write_text(
            "# vim: ft=s0ma\n"
            "\n"
            "module declared_name\n"
            "    layer: DOMAIN\n",
            encoding="utf-8",
        )
        assert extract_module_name(src) == "declared_name"
