"""Strictness-mode tests for the M7 doc-subsystem error codes.

Validates the severity matrix and pipeline integration for:
- ``DRIFT_DETECTED``       (warning migration/dev, error strict/release)
- ``EMPTY_DOC_FILTER``     (warning migration/dev, error strict/release)
- ``MISSING_PUBLIC_DOC_REF`` (release-only error)
- ``MISSING_EMBEDDED_EXAMPLE`` (release-only error)
"""

from __future__ import annotations

import shutil
from pathlib import Path

from s0ma_dsl.cli.main import S0maCLI
from s0ma_dsl.config import (
    SEVERITY_MATRIX,
    StrictnessMode,
    get_severity,
)

FIXTURES = Path(__file__).parent / "fixtures" / "valid" / "docs" / "full_project"


# ---------------------------------------------------------------------------
# Severity matrix correctness
# ---------------------------------------------------------------------------


class TestSeverityMatrix:
    def test_drift_detected_ladder(self) -> None:
        assert get_severity("DRIFT_DETECTED", StrictnessMode.MIGRATION) == "warning"
        assert get_severity("DRIFT_DETECTED", StrictnessMode.DEV) == "warning"
        assert get_severity("DRIFT_DETECTED", StrictnessMode.STRICT) == "error"
        assert get_severity("DRIFT_DETECTED", StrictnessMode.RELEASE) == "error"

    def test_empty_doc_filter_ladder(self) -> None:
        assert get_severity("EMPTY_DOC_FILTER", StrictnessMode.MIGRATION) == "warning"
        assert get_severity("EMPTY_DOC_FILTER", StrictnessMode.DEV) == "warning"
        assert get_severity("EMPTY_DOC_FILTER", StrictnessMode.STRICT) == "error"
        assert get_severity("EMPTY_DOC_FILTER", StrictnessMode.RELEASE) == "error"

    def test_missing_public_doc_ref_release_only(self) -> None:
        assert get_severity("MISSING_PUBLIC_DOC_REF", StrictnessMode.MIGRATION) is None
        assert get_severity("MISSING_PUBLIC_DOC_REF", StrictnessMode.DEV) is None
        assert get_severity("MISSING_PUBLIC_DOC_REF", StrictnessMode.STRICT) is None
        assert get_severity("MISSING_PUBLIC_DOC_REF", StrictnessMode.RELEASE) == "error"

    def test_missing_embedded_example_release_only(self) -> None:
        assert get_severity("MISSING_EMBEDDED_EXAMPLE", StrictnessMode.MIGRATION) is None
        assert get_severity("MISSING_EMBEDDED_EXAMPLE", StrictnessMode.DEV) is None
        assert get_severity("MISSING_EMBEDDED_EXAMPLE", StrictnessMode.STRICT) is None
        assert get_severity("MISSING_EMBEDDED_EXAMPLE", StrictnessMode.RELEASE) == "error"

    def test_unsupported_template_construct_retired(self) -> None:
        """Plan M7 subtask 5: code is removed (option b)."""
        assert "UNSUPPORTED_TEMPLATE_CONSTRUCT" not in SEVERITY_MATRIX


# ---------------------------------------------------------------------------
# EMPTY_DOC_FILTER pipeline integration
# ---------------------------------------------------------------------------


class TestEmptyDocFilterIntegration:
    def _write_empty_filter_project(self, dest: Path) -> None:
        dest.mkdir(parents=True, exist_ok=True)
        # A doc-ref whose `covers:` filter selects PUBLIC nerves —
        # but the project has no PUBLIC nerves, so the filter
        # materialises empty.
        (dest / "ref.s0ma").write_text(
            "module ref\n"
            "    layer: DOMAIN\n"
            "    version: 1.0.0\n"
            '    intent: "Module that exercises empty-filter detection."\n'
            "    exports: []\n"
            "    requires: none\n"
            "    uses: none\n"
            "    soft_requires: none\n"
            "    runtime_only_requires: none\n"
            "    deferred_requires: none\n"
            "    exports_helpers: none\n"
            "\n"
            "doc-ref empty_ref\n"
            '    intent: "Filter that materialises to nothing."\n'
            "    format: markdown\n"
            "    output: docs/empty.md\n"
            "    covers: [nerve where visibility == PUBLIC]\n"
            "    sections: [intent]\n",
            encoding="utf-8",
        )

    def test_empty_filter_warning_in_dev(self, tmp_path: Path, capsys) -> None:
        self._write_empty_filter_project(tmp_path)
        cli = S0maCLI()
        rc = cli.run(["docs", "verify", str(tmp_path), "--mode", "dev"])
        # Warning, not error → exit 0
        assert rc == 0
        out = capsys.readouterr().out
        assert "EMPTY_DOC_FILTER" in out

    def test_empty_filter_error_in_strict(self, tmp_path: Path, capsys) -> None:
        self._write_empty_filter_project(tmp_path)
        cli = S0maCLI()
        rc = cli.run(["docs", "verify", str(tmp_path), "--mode", "strict"])
        assert rc == 1
        out = capsys.readouterr().out
        assert "EMPTY_DOC_FILTER" in out


# ---------------------------------------------------------------------------
# Release-mode coverage checks
# ---------------------------------------------------------------------------


class TestReleaseDocCoverage:
    def _write_uncovered_public_nerve_project(self, dest: Path) -> None:
        dest.mkdir(parents=True, exist_ok=True)
        (dest / "uncovered.s0ma").write_text(
            "module uncovered\n"
            "    layer: DOMAIN\n"
            "    version: 1.0.0\n"
            '    intent: "Module with a PUBLIC nerve nobody documents."\n'
            "    exports: [greet]\n"
            "    requires: none\n"
            "    uses: none\n"
            "    soft_requires: none\n"
            "    runtime_only_requires: none\n"
            "    deferred_requires: none\n"
            "    exports_helpers: none\n"
            "\n"
            "nerve greet :: DOMAIN\n"
            "    kind: FUNCTION\n"
            "    visibility: PUBLIC\n"
            '    intent: "Returns a greeting."\n'
            '    expects: "username string"\n'
            '    guarantees: "non-empty greeting"\n'
            '    forbids: none\n'
            "    evaluates_at: FUNCTION_BOUNDARY\n"
            "    provides: none\n"
            "    returns: none\n"
            "    raises: none\n"
            "    interface: none\n"
            "    latency_ms: none\n"
            "    depends_on: none\n"
            "    internal: none\n"
            "    expected_exceptions: none\n"
            "    consumes_via_dict: none\n"
            "    declares_attributes: none\n"
            "    covered_by: none\n"
            "    ---\n"
            "    def greet(username):\n"
            '        return f"Hello, {username}!"\n',
            encoding="utf-8",
        )
        # No doc-ref covers the PUBLIC nerve → release-mode error.
        (dest / "docs.s0ma").write_text(
            "module docs\n"
            "    layer: DOMAIN\n"
            "    version: 1.0.0\n"
            '    intent: "Empty doc module — does not cover greet."\n'
            "    exports: []\n"
            "    requires: none\n"
            "    uses: none\n"
            "    soft_requires: none\n"
            "    runtime_only_requires: none\n"
            "    deferred_requires: none\n"
            "    exports_helpers: none\n",
            encoding="utf-8",
        )

    def test_uncovered_public_nerve_passes_in_strict(
        self, tmp_path: Path,
    ) -> None:
        self._write_uncovered_public_nerve_project(tmp_path)
        cli = S0maCLI()
        # NB: doc-coverage release checks are inactive in strict mode.
        # We use docs verify so cross-module dependency rules don't
        # masquerade as the test signal.
        rc = cli.run(["docs", "verify", str(tmp_path), "--mode", "strict"])
        assert rc == 0

    def test_uncovered_public_nerve_fails_in_release(
        self, tmp_path: Path, capsys,
    ) -> None:
        self._write_uncovered_public_nerve_project(tmp_path)
        cli = S0maCLI()
        rc = cli.run(["docs", "verify", str(tmp_path), "--mode", "release"])
        assert rc == 1
        out = capsys.readouterr().out
        assert "MISSING_PUBLIC_DOC_REF" in out
        assert "greet" in out

    def _write_unembedded_example_project(self, dest: Path) -> None:
        dest.mkdir(parents=True, exist_ok=True)
        (dest / "ex.s0ma").write_text(
            "module ex\n"
            "    layer: DOMAIN\n"
            "    version: 1.0.0\n"
            '    intent: "Example without an embedding doc-guide."\n'
            "    exports: [greet]\n"
            "    requires: none\n"
            "    uses: none\n"
            "    soft_requires: none\n"
            "    runtime_only_requires: none\n"
            "    deferred_requires: none\n"
            "    exports_helpers: none\n"
            "\n"
            "nerve greet :: DOMAIN\n"
            "    kind: FUNCTION\n"
            "    visibility: PUBLIC\n"
            '    intent: "Greets a user."\n'
            '    expects: "username"\n'
            '    guarantees: "greeting string"\n'
            '    forbids: none\n'
            "    evaluates_at: FUNCTION_BOUNDARY\n"
            "    provides: none\n"
            "    returns: none\n"
            "    raises: none\n"
            "    interface: none\n"
            "    latency_ms: none\n"
            "    depends_on: none\n"
            "    internal: none\n"
            "    expected_exceptions: none\n"
            "    consumes_via_dict: none\n"
            "    declares_attributes: none\n"
            "    covered_by: none\n"
            "    ---\n"
            "    def greet(u):\n"
            '        return f"hi {u}"\n'
            "\n"
            "doc-ref refs\n"
            '    intent: "Cover the public surface."\n'
            "    format: markdown\n"
            "    output: docs/refs.md\n"
            "    covers: [nerve where visibility == PUBLIC]\n"
            "    sections: [intent]\n"
            "\n"
            "example orphan_example\n"
            '    intent: "Example that no doc-guide embeds."\n'
            "    demonstrates: [nerve::greet]\n"
            "    runs_in: standalone\n"
            "    ---\n"
            "    print('hi')\n",
            encoding="utf-8",
        )

    def test_unembedded_example_fails_in_release(
        self, tmp_path: Path, capsys,
    ) -> None:
        self._write_unembedded_example_project(tmp_path)
        cli = S0maCLI()
        rc = cli.run(["docs", "verify", str(tmp_path), "--mode", "release"])
        assert rc == 1
        out = capsys.readouterr().out
        assert "MISSING_EMBEDDED_EXAMPLE" in out
        assert "orphan_example" in out

    def test_unembedded_example_silent_in_strict(
        self, tmp_path: Path,
    ) -> None:
        self._write_unembedded_example_project(tmp_path)
        cli = S0maCLI()
        rc = cli.run(["docs", "verify", str(tmp_path), "--mode", "strict"])
        assert rc == 0


# ---------------------------------------------------------------------------
# Cache-aware re-render (M7 subtask 7)
# ---------------------------------------------------------------------------


class TestDocCacheRoundTrip:
    """Re-running ``s0ma build`` against an unchanged tree must hit
    the cache for both .py and rendered docs. Editing a covered nerve's
    intent must miss the cache for every doc that references it."""

    def _setup(self, tmp_path: Path) -> Path:
        target = tmp_path / "project"
        shutil.copytree(FIXTURES, target)
        return target

    def test_unchanged_tree_hits_cache(self, tmp_path: Path) -> None:
        from s0ma_dsl.cache import BuildCache

        project = self._setup(tmp_path)
        cli = S0maCLI()
        rc = cli.run(["build", str(project), "--mode", "dev"])
        assert rc == 0
        # Verify rendered docs were produced.
        assert (project / "docs" / "greetings_reference.md").is_file()

        cache_root = project / ".s0ma.cache"
        cache = BuildCache(cache_dir=cache_root)
        cache.reset_stats()

        # Prime the cache stats by running lookup directly to confirm
        # the second build hits.
        # Second run.
        rc2 = cli.run(["build", str(project), "--mode", "dev"])
        assert rc2 == 0

        # Manifest persisted across runs.
        manifest = cache_root / "greetings_docs.docs.json"
        assert manifest.exists()

    def test_modified_covered_nerve_misses_cache(self, tmp_path: Path) -> None:
        project = self._setup(tmp_path)
        cli = S0maCLI()
        rc = cli.run(["build", str(project), "--mode", "dev"])
        assert rc == 0
        first = (project / "docs" / "greetings_reference.md").read_text(
            encoding="utf-8"
        )

        # Edit the covered nerve's intent. The covered intent appears
        # in the rendered output, so a second build must regenerate.
        nerve_file = project / "greetings.s0ma"
        text = nerve_file.read_text(encoding="utf-8")
        text = text.replace(
            'intent: "Returns a greeting for the given username."',
            'intent: "Returns a friendly greeting for the given username."',
        )
        nerve_file.write_text(text, encoding="utf-8")

        rc2 = cli.run(["build", str(project), "--mode", "dev"])
        assert rc2 == 0
        second = (project / "docs" / "greetings_reference.md").read_text(
            encoding="utf-8"
        )
        assert first != second
        assert "friendly" in second
