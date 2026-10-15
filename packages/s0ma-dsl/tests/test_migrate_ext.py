"""Tests for ``s0ma migrate-ext`` (the legacy extension-family migration).

Together with ``s0ma_dsl/cli/migrate_ext.py``, this file is the ONLY
place the legacy letter-o spelling may appear; every legacy literal is
marked ``# legacy-spelling: intentional`` for the CI spelling guard.

Covers (per the consolidation plan, M3 step 7): dry-run, real run,
idempotency, collision refusal, and the legacy config-table rewrite —
plus suffix anchoring, quiet mode, and cache-dir removal.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from s0ma_dsl.cli.main import EXIT_SUCCESS, EXIT_VALIDATION_ERROR, S0maCLI

if TYPE_CHECKING:
    from pathlib import Path

# ---------------------------------------------------------------------------
# Old-spelling project scaffold
# ---------------------------------------------------------------------------

# The scaffold models a pre-2.0.0 project; built by concatenation so each
# legacy line carries its own marker for the CI spelling guard.
_LEGACY_PYPROJECT = (
    "[project]\n"
    'name = "legacy-app"\n'
    'version = "0.1.0"\n'
    "\n"
    "[tool.soma]\n"  # legacy-spelling: intentional
    'source_roots = ["src"]\n'
    'build_dir = "build"\n'
    "\n"
    "[tool.soma.fixtures_format]\n"  # legacy-spelling: intentional
    '"tests/fixtures/*.jsonl" = "jsonl"\n'
    "\n"
    "[tool.ruff]\n"
    "line-length = 88\n"
)

_LEGACY_MODULE = """\
module legacy_app

nerve Greeter:
  intent: "Say hello."
"""


def _make_legacy_project(root: Path) -> Path:
    """Author a pre-2.0.0 (letter-o spelling) project under *root*."""
    proj = root / "legacy_project"
    src = proj / "src"
    build = proj / "build"
    src.mkdir(parents=True)
    build.mkdir(parents=True)

    (proj / "pyproject.toml").write_text(_LEGACY_PYPROJECT, encoding="utf-8")
    # Legacy sources, IR, source map, and build manifest.
    (src / "app.soma").write_text(  # legacy-spelling: intentional
        _LEGACY_MODULE, encoding="utf-8"
    )
    (src / "nested").mkdir()
    (src / "nested" / "util.soma").write_text(  # legacy-spelling: intentional
        _LEGACY_MODULE, encoding="utf-8"
    )
    (build / "app.py").write_text("# transpiled output\n", encoding="utf-8")
    (build / "app.soma.json").write_text("{}\n", encoding="utf-8")  # legacy-spelling: intentional
    (build / "app.soma.map").write_text("{}\n", encoding="utf-8")  # legacy-spelling: intentional
    (build / "build.soma.json").write_text("{}\n", encoding="utf-8")  # legacy-spelling: intentional
    # Legacy cache directories (both generations).
    legacy_build_cache = proj / ".soma.cache"  # legacy-spelling: intentional
    legacy_build_cache.mkdir()
    (legacy_build_cache / "app.hash").write_text("sha256:0\n", encoding="utf-8")
    legacy_import_cache = src / "__soma_cache__"  # legacy-spelling: intentional
    legacy_import_cache.mkdir()
    (legacy_import_cache / "app.py").write_text("# cached\n", encoding="utf-8")
    # A near-miss that must NOT be renamed (suffix is anchored).
    (src / "notes.soma.bak").write_text(  # legacy-spelling: intentional
        "not an artifact\n", encoding="utf-8"
    )
    return proj


def _snapshot(proj: Path) -> dict[str, str]:
    """Relative path -> content for every file under *proj*."""
    return {
        str(p.relative_to(proj)): p.read_text(encoding="utf-8")
        for p in sorted(proj.rglob("*"))
        if p.is_file()
    }


@pytest.fixture
def cli() -> S0maCLI:
    return S0maCLI()


# ---------------------------------------------------------------------------
# Dry run
# ---------------------------------------------------------------------------


class TestDryRun:
    def test_dry_run_changes_nothing_and_prints_plan(
        self, cli: S0maCLI, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        proj = _make_legacy_project(tmp_path)
        before = _snapshot(proj)

        rc = cli.run(["migrate-ext", str(proj), "--dry-run"])

        assert rc == EXIT_SUCCESS
        assert _snapshot(proj) == before, "dry-run must not touch the tree"
        out = capsys.readouterr().out
        assert "would rename" in out
        assert "would remove" in out
        assert "would rewrite" in out
        assert "(dry-run: nothing was changed)" in out
        # The plan covers all four artifact kinds.
        assert "src/app.soma -> src/app.s0ma" in out  # legacy-spelling: intentional
        manifest_rename = (
            "build/build.soma.json -> build/build.s0ma.json"  # legacy-spelling: intentional
        )
        assert manifest_rename in out


# ---------------------------------------------------------------------------
# Real run
# ---------------------------------------------------------------------------


class TestRealRun:
    def test_full_migration(
        self, cli: S0maCLI, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        proj = _make_legacy_project(tmp_path)

        rc = cli.run(["migrate-ext", str(proj)])

        assert rc == EXIT_SUCCESS
        # Sources, IR, map, and manifest renamed (nested included).
        assert (proj / "src" / "app.s0ma").is_file()
        assert (proj / "src" / "nested" / "util.s0ma").is_file()
        assert (proj / "build" / "app.s0ma.json").is_file()
        assert (proj / "build" / "app.s0ma.map").is_file()
        assert (proj / "build" / "build.s0ma.json").is_file()
        assert not (proj / "src" / "app.soma").exists()  # legacy-spelling: intentional
        # Non-artifact near-miss untouched (rename anchors at the suffix).
        assert (proj / "src" / "notes.soma.bak").is_file()  # legacy-spelling: intentional
        # Legacy caches removed wholesale.
        assert not (proj / ".soma.cache").exists()  # legacy-spelling: intentional
        assert not (proj / "src" / "__soma_cache__").exists()  # legacy-spelling: intentional
        # Transpiled .py content is never rewritten (rebuild re-emits it).
        assert (proj / "build" / "app.py").read_text(encoding="utf-8") == (
            "# transpiled output\n"
        )
        out = capsys.readouterr().out
        assert "renamed:" in out and "removed:" in out and "rewrote:" in out
        assert "5 file(s) renamed, 2 legacy cache dir(s) removed" in out

    def test_pyproject_table_rewrite_is_byte_precise(
        self, cli: S0maCLI, tmp_path: Path
    ) -> None:
        proj = _make_legacy_project(tmp_path)

        rc = cli.run(["migrate-ext", str(proj)])

        assert rc == EXIT_SUCCESS
        text = (proj / "pyproject.toml").read_text(encoding="utf-8")
        assert "[tool.s0ma]" in text
        assert "[tool.s0ma.fixtures_format]" in text
        assert "[tool.soma]" not in text  # legacy-spelling: intentional
        assert "[tool.soma." not in text  # legacy-spelling: intentional
        # Every non-header byte is preserved.
        expected = _LEGACY_PYPROJECT.replace(
            "[tool.soma]", "[tool.s0ma]"  # legacy-spelling: intentional
        ).replace(
            "[tool.soma.fixtures_format]",  # legacy-spelling: intentional
            "[tool.s0ma.fixtures_format]",
        )
        assert text == expected

    def test_pyproject_rewrite_preserves_mixed_endings_in_bytes_space(
        self, cli: S0maCLI, tmp_path: Path
    ) -> None:
        """The rewrite is byte-preserving for CRLF / mixed-ending files.

        W-3 (Windows plan): asserted in BYTES space — text-mode reads
        hide newline damage behind universal-newline translation. Only
        the legacy header line's characters change; every line keeps
        its own original ending (CRLF lines stay CRLF, LF lines stay
        LF) on every OS.
        """
        proj = tmp_path / "p"
        proj.mkdir()
        original = (
            b"[project]\r\n"
            b'name = "legacy"\r\n'
            b"\n"
            b"[tool.soma]\r\n"  # legacy-spelling: intentional
            b"strict = true\n"
        )
        (proj / "pyproject.toml").write_bytes(original)

        rc = cli.run(["migrate-ext", str(proj)])

        assert rc == EXIT_SUCCESS
        data = (proj / "pyproject.toml").read_bytes()
        expected = original.replace(
            b"[tool.soma]", b"[tool.s0ma]"  # legacy-spelling: intentional
        )
        assert data == expected, (
            "every byte except the header spelling must survive, "
            "including each line's own ending"
        )

    def test_unrelated_tool_table_not_rewritten(
        self, cli: S0maCLI, tmp_path: Path
    ) -> None:
        proj = tmp_path / "p"
        proj.mkdir()
        # [tool.somax] shares the prefix but differs —  # legacy-spelling: intentional
        # it must survive; the lone legacy source makes the run non-empty.
        (proj / "pyproject.toml").write_text(
            "[tool.somax]\nkey = 1\n",  # legacy-spelling: intentional
            encoding="utf-8",
        )
        (proj / "m.soma").write_text(  # legacy-spelling: intentional
            _LEGACY_MODULE, encoding="utf-8"
        )

        rc = cli.run(["migrate-ext", str(proj)])

        assert rc == EXIT_SUCCESS
        assert (proj / "pyproject.toml").read_text(encoding="utf-8") == (
            "[tool.somax]\nkey = 1\n"  # legacy-spelling: intentional
        )

    def test_quiet_prints_only_summary(
        self, cli: S0maCLI, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        proj = _make_legacy_project(tmp_path)

        rc = cli.run(["migrate-ext", str(proj), "--quiet"])

        assert rc == EXIT_SUCCESS
        out = capsys.readouterr().out
        assert "renamed:" not in out and "removed:" not in out
        assert "s0ma migrate-ext: 5 file(s) renamed" in out


# ---------------------------------------------------------------------------
# Idempotency
# ---------------------------------------------------------------------------


class TestIdempotency:
    def test_second_run_is_a_no_op(
        self, cli: S0maCLI, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        proj = _make_legacy_project(tmp_path)

        assert cli.run(["migrate-ext", str(proj)]) == EXIT_SUCCESS
        after_first = _snapshot(proj)
        capsys.readouterr()

        rc = cli.run(["migrate-ext", str(proj)])

        assert rc == EXIT_SUCCESS
        assert _snapshot(proj) == after_first
        assert "nothing to migrate" in capsys.readouterr().out


# ---------------------------------------------------------------------------
# Collision refusal
# ---------------------------------------------------------------------------


class TestCollisionRefusal:
    def test_existing_target_aborts_whole_migration(
        self, cli: S0maCLI, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        proj = _make_legacy_project(tmp_path)
        # Pre-create ONE rename target; the whole plan must be refused.
        (proj / "src" / "app.s0ma").write_text("existing\n", encoding="utf-8")
        before = _snapshot(proj)

        rc = cli.run(["migrate-ext", str(proj)])

        assert rc == EXIT_VALIDATION_ERROR
        assert _snapshot(proj) == before, "collision must abort with no changes"
        out = capsys.readouterr().out
        assert "refusing to migrate" in out
        collision_line = (
            "src/app.soma -> src/app.s0ma (target exists)"  # legacy-spelling: intentional
        )
        assert collision_line in out
        # The untouched sibling proves nothing was applied.
        assert (proj / "src" / "nested" / "util.soma").is_file()  # legacy-spelling: intentional
