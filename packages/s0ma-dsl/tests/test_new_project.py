"""Tests for ``s0ma new project`` (FR-DSL-5 v1.1, UX-M3, STD-M6).

Covers the feature-first end-to-end path (STD-M6): initialize → a
feature-first tree (``src/<feature>/<module>.s0ma`` +
``tests/<feature>/<module>_tests.s0ma`` + ``src/app_map.s0ma``) → AGENTS.md
and a thin CLAUDE.md (exactly ``@AGENTS.md``) → the ``[tool.s0ma].authoring``
key (``on`` default, ``off`` with ``--default-off``) → the project builds,
the app map renders to ``build/docs/``, and ``s0ma check`` passes →
``bootstrap_imports`` of the build dir actually imports the starter module
(in a subprocess so the registry stays clean). Also the byte-preserving
``[tool.s0ma]`` append, every refusal path (existing ``[tool.s0ma]`` table,
existing starter/app-map/AGENTS.md/CLAUDE.md files) with atomicity, and the
``--format json`` shapes. FB-M9 adds the beta feedback scaffold: the
``[tool.s0ma].feedback = "suggest"`` posture (FD-13), the created-if-absent
``/s0ma-feedback`` Claude Code skill (FD-7), and the AGENTS.md standing rule
that teaches recognition without teaching consent.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from typing import TYPE_CHECKING, Any

import pytest

from s0ma_dsl.cli.main import (
    EXIT_SUCCESS,
    EXIT_USAGE_ERROR,
    EXIT_VALIDATION_ERROR,
    S0maCLI,
)
from s0ma_dsl.cli.migrate_grammar import current_grammar_source
from s0ma_dsl.cli.templates import TEMPLATE_CHOICES, ArchetypeFile

if TYPE_CHECKING:
    from pathlib import Path

MCP_HINT = "claude mcp add s0ma -- s0ma-mcp"

_S0MA_TABLE = (
    "[tool.s0ma]\n"
    'source_roots = ["src"]\n'
    'test_roots = ["tests"]\n'
    'build_dir = "build"\n'
    'mode = "dev"\n'
    # STD-M4: the authoring posture is written so the key exists from M4
    # onward ("on" by default; "off" with --default-off).
    'authoring = "on"\n'
    # FD-13: the beta feedback posture — an agent may OFFER to draft s0ma
    # feedback at s0ma-specific friction. "off" silences the offers and
    # nothing else; feedback the user asks for explicitly never depends
    # on this key.
    'feedback = "suggest"\n'
)


@pytest.fixture
def cli() -> S0maCLI:
    return S0maCLI()


def _snapshot(root: Path) -> dict[str, str]:
    """Relative path -> content for every file under *root*."""
    if not root.exists():
        return {}
    return {
        str(p.relative_to(root)): p.read_text(encoding="utf-8")
        for p in sorted(root.rglob("*"))
        if p.is_file()
    }


# ---------------------------------------------------------------------------
# Feature-first end-to-end (STD-M6)
# ---------------------------------------------------------------------------


class TestEndToEnd:
    def test_fresh_dir_initializes_builds_and_prints_next_steps(
        self, cli: S0maCLI, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        target = tmp_path / "demo-app"

        rc = cli.run(["new", "project", str(target)])

        assert rc == EXIT_SUCCESS
        # Config: the [tool.s0ma] table with src/build dirs and the mode.
        text = (target / "pyproject.toml").read_text(encoding="utf-8")
        assert "[tool.s0ma]" in text
        assert 'source_roots = ["src"]' in text
        assert 'test_roots = ["tests"]' in text
        assert 'build_dir = "build"' in text
        assert 'mode = "dev"' in text
        # STD-M4: the authoring posture key is written, defaulting to "on".
        assert 'authoring = "on"' in text
        assert 'name = "demo-app"' in text
        # STD-M6 feature-first: a feature dir holds the starter module
        # (underscore <feature>_<layer> name), tests mirror it, and the
        # project ships a project-wide app map.
        assert (target / "src" / "core" / "core_domain.s0ma").is_file()
        assert (
            target / "tests" / "core" / "core_domain_tests.s0ma"
        ).is_file()
        assert (target / "src" / "app_map.s0ma").is_file()
        # STD-M6: AGENTS.md (canonical) + a thin CLAUDE.md that is exactly
        # the @AGENTS.md import (one source of truth, P-2).
        assert (target / "AGENTS.md").is_file()
        assert (target / "CLAUDE.md").read_text(encoding="utf-8") == (
            "@AGENTS.md\n"
        )
        # First build landed: flat layout + manifest + rendered app map.
        assert (target / "build" / "core_domain.py").is_file()
        assert (target / "build" / "app_map.py").is_file()
        assert (target / "build" / "build.s0ma.json").is_file()
        assert (target / "build" / "docs" / "architecture_map.md").is_file()
        assert (
            target / "build" / "docs" / "public_api_reference.md"
        ).is_file()
        # Next steps serve the human readership (P-5): bootstrap
        # snippet, check command, MCP registration hint, the new files.
        out = capsys.readouterr().out
        assert "Next steps:" in out
        assert "from s0ma.bootstrap import bootstrap_imports" in out
        # D-5 (Windows plan): as_posix()-rendered on every OS (identical
        # to str() on POSIX; never backslashed on Windows).
        assert f'bootstrap_imports("{(target / "build").as_posix()}")' in out
        assert "s0ma check" in out
        assert MCP_HINT in out
        assert "s0ma://guide/getting-started" in out
        assert "AGENTS.md" in out
        assert "CLAUDE.md" in out
        assert "app map" in out
        # The one-time @AGENTS.md import approval note (STD-M6).
        assert "@AGENTS.md import" in out

    def test_agents_md_carries_the_standing_rules(
        self, cli: S0maCLI, tmp_path: Path
    ) -> None:
        """AGENTS.md is the canonical, agent-agnostic s0ma contract."""
        target = tmp_path / "agentsproj"
        assert cli.run(
            ["new", "project", str(target), "--quiet"]
        ) == EXIT_SUCCESS

        agents = (target / "AGENTS.md").read_text(encoding="utf-8")
        # .s0ma-first authoring rule + the MCP server + registration hint.
        assert "s0ma-authoring" in agents
        assert "never as bare Python" in agents
        assert MCP_HINT in agents
        assert "s0ma://guide/getting-started" in agents
        # The orient → scaffold → check → build loop.
        assert "project_status" in agents
        assert "build_project" in agents
        # Feature-first layout + the patterns-guide pointer.
        assert "feature-first" in agents
        assert "s0ma://guide/patterns" in agents
        # Pilot-01 (memo P1-5): the in-context guide is the survival
        # card (under 4 KB); the quick reference is consulted per-topic,
        # never held in context — the doctrine must not drift back.
        assert "s0ma://guide/survival-card" in agents
        assert "keep `s0ma://guide/quick-reference` in context" not in agents
        # The STD-M4 confirmation handshake, verbatim, for authoring-on.
        assert (
            "s0ma project; authoring is ON — confirm you will author "
            "components as .s0ma via this server before writing code"
        ) in agents
        # The one-time-approval note near the top.
        assert "one-time approval dialog" in agents

    def test_agents_md_carries_the_feedback_standing_rule(
        self, cli: S0maCLI, tmp_path: Path
    ) -> None:
        """FB-M9 T3: the same recognition rule the MCP server serves.

        Three parts, and each is load-bearing: react to an EXPLICIT ask
        (never to a mood), confirm the target when the user never named
        s0ma (A-1 — other tools collect feedback too), and never submit
        outside the client's own approval interaction.
        """
        target = tmp_path / "fbrules"
        assert cli.run(
            ["new", "project", str(target), "--quiet"]
        ) == EXIT_SUCCESS

        agents = (target / "AGENTS.md").read_text(encoding="utf-8")
        assert "explicitly ask to send feedback about s0ma" in agents
        assert "never named s0ma or kn0wthyself" in agents
        assert "other tools" in agents and "collect feedback too" in agents
        assert "Never submit without the client's approval interaction" in agents
        assert "never read frustration as consent" in agents
        # A-2: the served word is "feedback data", never "payload".
        assert "feedback data" in agents
        assert "payload" not in agents.lower()

    def test_s0ma_check_passes_in_the_new_project(
        self, cli: S0maCLI, tmp_path: Path
    ) -> None:
        target = tmp_path / "checkme"
        assert cli.run(
            ["new", "project", str(target), "--quiet"]
        ) == EXIT_SUCCESS

        rc = cli.run(["--project-root", str(target), "check"])

        assert rc == EXIT_SUCCESS

    def test_s0ma_check_passes_in_release_mode(
        self, cli: S0maCLI, tmp_path: Path
    ) -> None:
        """The scaffold clears the strictest gate out of the box.

        Release mode makes public doc-refs and test coverage hard
        requirements; the app map + the mirrored starter test satisfy
        them, so a fresh project is release-clean immediately.
        """
        target = tmp_path / "releaseme"
        assert cli.run(
            ["new", "project", str(target), "--quiet"]
        ) == EXIT_SUCCESS

        rc = cli.run(
            ["--project-root", str(target), "check", "--mode", "release"]
        )

        assert rc == EXIT_SUCCESS

    def test_app_map_renders_and_drift_check_passes(
        self, cli: S0maCLI, tmp_path: Path
    ) -> None:
        """The app map renders to build/docs and is drift-free as built."""
        target = tmp_path / "appmapproj"
        assert cli.run(
            ["new", "project", str(target), "--quiet"]
        ) == EXIT_SUCCESS

        guide = (
            target / "build" / "docs" / "architecture_map.md"
        ).read_text(encoding="utf-8")
        # The three faculties + the resolved starter-nerve reference.
        assert "proprioception" in guide
        assert "interoception" in guide
        assert "metacognition" in guide
        assert "describe_self" in guide

        rc = cli.run(
            ["--project-root", str(target), "docs", "check-drift",
             str(target / "src")]
        )
        assert rc == EXIT_SUCCESS

    def test_starter_test_runs_green(
        self, cli: S0maCLI, tmp_path: Path
    ) -> None:
        """The scaffolded `.s0ma` test executes under `s0ma test`."""
        target = tmp_path / "testme"
        assert cli.run(
            ["new", "project", str(target), "--quiet"]
        ) == EXIT_SUCCESS

        rc = cli.run(["--project-root", str(target), "test", "--quiet"])

        assert rc == EXIT_SUCCESS

    def test_bootstrap_imports_the_starter_module(
        self, cli: S0maCLI, tmp_path: Path
    ) -> None:
        """The printed bootstrap snippet actually works on the build.

        Runs in a subprocess: importing the built module registers its
        components with the process-global registry, which must not
        leak into this test process.
        """
        target = tmp_path / "bootme"
        assert cli.run(
            ["new", "project", str(target), "--quiet"]
        ) == EXIT_SUCCESS

        build_dir = target / "build"
        script = (
            "from s0ma.bootstrap import bootstrap_imports\n"
            f"modules = bootstrap_imports({str(build_dir)!r})\n"
            "assert 'core_domain' in modules, sorted(modules)\n"
            "print('BOOTSTRAP_OK', sorted(modules))\n"
        )
        result = subprocess.run(
            [sys.executable, "-c", script],
            capture_output=True,
            text=True,
            timeout=120,
            check=False,
        )

        assert result.returncode == 0, result.stderr
        assert "BOOTSTRAP_OK" in result.stdout
        assert "core_domain" in result.stdout

    def test_quiet_prints_only_the_one_line_summary(
        self, cli: S0maCLI, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        target = tmp_path / "quietproj"

        rc = cli.run(["new", "project", str(target), "--quiet"])

        assert rc == EXIT_SUCCESS
        out = capsys.readouterr().out
        assert out.count("\n") == 1
        assert out.startswith("s0ma new project: initialized")


# ---------------------------------------------------------------------------
# Byte-preserving [tool.s0ma] append
# ---------------------------------------------------------------------------


class TestPyprojectAppend:
    def test_append_preserves_every_original_byte(
        self, cli: S0maCLI, tmp_path: Path
    ) -> None:
        target = tmp_path / "existing"
        target.mkdir()
        original = (
            "[project]\n"
            'name = "keeper"\n'
            'version = "1.2.3"\n'
            "\n"
            "[tool.black]\n"
            "line-length = 120\n"
        )
        (target / "pyproject.toml").write_text(original, encoding="utf-8")

        rc = cli.run(["new", "project", str(target), "--quiet"])

        assert rc == EXIT_SUCCESS
        text = (target / "pyproject.toml").read_text(encoding="utf-8")
        # The original content is a strict prefix — nothing rewritten,
        # nothing reformatted — and the insertion point is exactly one
        # separator line followed by the table.
        assert text.startswith(original)
        assert text[len(original):] == "\n" + _S0MA_TABLE

    def test_append_when_original_lacks_a_trailing_newline(
        self, cli: S0maCLI, tmp_path: Path
    ) -> None:
        target = tmp_path / "no-newline"
        target.mkdir()
        original = '[project]\nname = "raw"\nversion = "0.0.1"'
        (target / "pyproject.toml").write_text(original, encoding="utf-8")

        rc = cli.run(["new", "project", str(target), "--quiet"])

        assert rc == EXIT_SUCCESS
        text = (target / "pyproject.toml").read_text(encoding="utf-8")
        assert text.startswith(original)
        assert text[len(original):] == "\n\n" + _S0MA_TABLE

    def test_append_preserves_crlf_original_in_bytes_space(
        self, cli: S0maCLI, tmp_path: Path
    ) -> None:
        """The byte-preservation contract holds for a CRLF pyproject.

        W-3 (Windows plan): asserted in BYTES space — text-mode reads
        hide newline damage behind universal-newline translation. The
        CRLF original must survive byte-for-byte as a strict prefix on
        every OS; the appended table itself is always LF by contract.
        """
        target = tmp_path / "crlf"
        target.mkdir()
        original = (
            b"[project]\r\n"
            b'name = "keeper"\r\n'
            b'version = "1.2.3"\r\n'
        )
        (target / "pyproject.toml").write_bytes(original)

        rc = cli.run(["new", "project", str(target), "--quiet"])

        assert rc == EXIT_SUCCESS
        data = (target / "pyproject.toml").read_bytes()
        assert data.startswith(original), (
            "CRLF original must remain a strict byte-prefix of the result"
        )
        assert data[len(original):] == b"\n" + _S0MA_TABLE.encode("utf-8")


# ---------------------------------------------------------------------------
# Refusal paths (atomic: list every reason, change nothing)
# ---------------------------------------------------------------------------


class TestRefusals:
    def test_existing_tool_s0ma_table_refuses_atomically(
        self, cli: S0maCLI, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        target = tmp_path / "claimed"
        target.mkdir()
        (target / "pyproject.toml").write_text(
            '[project]\nname = "claimed"\n\n[tool.s0ma]\nbuild_dir = "out"\n',
            encoding="utf-8",
        )
        before = _snapshot(target)

        rc = cli.run(["new", "project", str(target)])

        assert rc == EXIT_VALIDATION_ERROR
        assert _snapshot(target) == before, "refusal must change nothing"
        out = capsys.readouterr().out
        assert "refusing to initialize" in out
        assert "already has a [tool.s0ma] table" in out

    def test_existing_module_file_refuses_atomically(
        self, cli: S0maCLI, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        target = tmp_path / "modtaken"
        (target / "src" / "core").mkdir(parents=True)
        (target / "src" / "core" / "core_domain.s0ma").write_text(
            "module core_domain\n", encoding="utf-8"
        )
        before = _snapshot(target)

        rc = cli.run(["new", "project", str(target)])

        assert rc == EXIT_VALIDATION_ERROR
        assert _snapshot(target) == before
        assert not (target / "pyproject.toml").exists()
        out = capsys.readouterr().out
        assert "starter module file already exists" in out

    def test_existing_agents_md_refuses_atomically(
        self, cli: S0maCLI, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """STD-M6: never clobber an existing agent contract."""
        target = tmp_path / "hasagents"
        target.mkdir()
        (target / "AGENTS.md").write_text(
            "# my own rules\n", encoding="utf-8"
        )
        before = _snapshot(target)

        rc = cli.run(["new", "project", str(target)])

        assert rc == EXIT_VALIDATION_ERROR
        assert _snapshot(target) == before
        assert not (target / "pyproject.toml").exists()
        out = capsys.readouterr().out
        assert "AGENTS.md already exists" in out

    def test_existing_claude_md_refuses_atomically(
        self, cli: S0maCLI, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """STD-M6: never clobber an existing CLAUDE.md."""
        target = tmp_path / "hasclaude"
        target.mkdir()
        (target / "CLAUDE.md").write_text(
            "# my own memory\n", encoding="utf-8"
        )
        before = _snapshot(target)

        rc = cli.run(["new", "project", str(target)])

        assert rc == EXIT_VALIDATION_ERROR
        assert _snapshot(target) == before
        out = capsys.readouterr().out
        assert "CLAUDE.md already exists" in out

    def test_every_reason_is_listed_in_one_refusal(
        self, cli: S0maCLI, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        target = tmp_path / "doubly"
        (target / "src" / "core").mkdir(parents=True)
        (target / "pyproject.toml").write_text(
            "[tool.s0ma]\n", encoding="utf-8"
        )
        (target / "src" / "core" / "core_domain.s0ma").write_text(
            "module core_domain\n", encoding="utf-8"
        )
        (target / "AGENTS.md").write_text("mine\n", encoding="utf-8")

        rc = cli.run(["new", "project", str(target)])

        assert rc == EXIT_VALIDATION_ERROR
        out = capsys.readouterr().out
        assert "already has a [tool.s0ma] table" in out
        assert "starter module file already exists" in out
        assert "AGENTS.md already exists" in out

    def test_unparseable_pyproject_refuses(
        self, cli: S0maCLI, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        target = tmp_path / "broken"
        target.mkdir()
        (target / "pyproject.toml").write_text(
            "[project\nthis is not toml", encoding="utf-8"
        )
        before = _snapshot(target)

        rc = cli.run(["new", "project", str(target)])

        assert rc == EXIT_VALIDATION_ERROR
        assert _snapshot(target) == before
        assert "could not be parsed" in capsys.readouterr().out


# ---------------------------------------------------------------------------
# Usage errors
# ---------------------------------------------------------------------------


class TestUsageErrors:
    def test_target_is_a_file(
        self, cli: S0maCLI, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        target = tmp_path / "afile"
        target.write_text("not a directory\n", encoding="utf-8")

        rc = cli.run(["new", "project", str(target)])

        assert rc == EXIT_USAGE_ERROR
        assert "not a directory" in capsys.readouterr().out

    def test_digit_leading_dir_requires_explicit_name(
        self, cli: S0maCLI, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        target = tmp_path / "123app"

        rc = cli.run(["new", "project", str(target)])

        assert rc == EXIT_USAGE_ERROR
        assert "--name" in capsys.readouterr().out
        assert not target.exists(), "usage error must create nothing"

    def test_name_override_drives_project_naming(
        self, cli: S0maCLI, tmp_path: Path
    ) -> None:
        """--name drives [project].name; the feature stays `core`.

        STD-M6: the starter feature/module are layout fixtures (`core` /
        `core_<layer>`), independent of the project name, so a
        digit-leading directory just needs a valid --name for the
        pyproject.
        """
        target = tmp_path / "123app"

        rc = cli.run(
            ["new", "project", str(target), "--name", "renamed-app",
             "--quiet"]
        )

        assert rc == EXIT_SUCCESS
        assert (target / "src" / "core" / "core_domain.s0ma").is_file()
        text = (target / "pyproject.toml").read_text(encoding="utf-8")
        assert 'name = "renamed-app"' in text

    def test_layer_drives_the_starter_module_name(
        self, cli: S0maCLI, tmp_path: Path
    ) -> None:
        """--layer selects the feature module's layer (and its stem)."""
        target = tmp_path / "applayer"

        rc = cli.run(
            ["new", "project", str(target), "--layer", "APPLICATION",
             "--quiet"]
        )

        assert rc == EXIT_SUCCESS
        assert (
            target / "src" / "core" / "core_application.s0ma"
        ).is_file()
        # The app map's layer assertion tracks the starter's actual layer.
        app_map = (target / "src" / "app_map.s0ma").read_text(
            encoding="utf-8"
        )
        assert "describe_self.layer == APPLICATION" in app_map
        # And the project still passes check.
        assert cli.run(
            ["--project-root", str(target), "check"]
        ) == EXIT_SUCCESS


# ---------------------------------------------------------------------------
# --format json shapes (D-1: machine output first)
# ---------------------------------------------------------------------------


class TestJsonShapes:
    def test_success_shape(
        self, cli: S0maCLI, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        target = tmp_path / "jsonproj"

        rc = cli.run(["new", "project", str(target), "--format", "json"])

        assert rc == EXIT_SUCCESS
        report = json.loads(capsys.readouterr().out)
        assert report["ok"] is True
        assert report["project_root"] == str(target)
        assert report["project_name"] == "jsonproj"
        assert report["mode"] == "dev"
        # STD-M4: the authoring posture defaults to "on" and is reported.
        assert report["authoring"] == "on"
        # STD-M6: feature-first facts + the new files.
        assert report["feature"] == "core"
        assert report["pyproject"]["action"] == "created"
        assert report["module"]["name"] == "core_domain"
        assert report["module"]["source"].endswith("core_domain.s0ma")
        assert report["test"]["source"].endswith("core_domain_tests.s0ma")
        assert report["app_map"]["source"].endswith("app_map.s0ma")
        assert report["agents_file"]["path"].endswith("AGENTS.md")
        assert report["claude_file"]["path"].endswith("CLAUDE.md")
        # The first build builds src + tests: feature module, app map, test.
        assert report["build"]["modules"] == [
            "app_map",
            "core_domain",
            "core_domain_tests",
        ]
        next_steps = report["next_steps"]
        assert next_steps["check"] == "s0ma check"
        assert next_steps["mcp_hint"] == MCP_HINT
        assert next_steps["getting_started"] == "s0ma://guide/getting-started"
        assert "from s0ma.bootstrap import bootstrap_imports" in (
            next_steps["bootstrap_snippet"]
        )
        # D-5 (Windows plan): the snippet path is as_posix()-rendered on
        # every OS (identical to str() on POSIX; never backslashed).
        assert (target / "build").as_posix() in next_steps[
            "bootstrap_snippet"
        ]

    def test_bootstrap_snippet_is_valid_python_on_every_os(
        self, cli: S0maCLI, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """The snippet compiles — the D-5 regression guard.

        A native Windows build_dir inside the quoted string is a
        SyntaxError (``"C:\\Users\\..."`` trips the ``\\U`` unicode
        escape), so ``compile()`` is the cross-platform assertion of
        the actual Windows failure mode.
        """
        target = tmp_path / "snippetproj"

        rc = cli.run(["new", "project", str(target), "--format", "json"])

        assert rc == EXIT_SUCCESS
        report = json.loads(capsys.readouterr().out)
        snippet = report["next_steps"]["bootstrap_snippet"]
        compile(snippet, "<bootstrap_snippet>", "exec")
        assert "\\" not in snippet, "snippet must never contain backslashes"

    def test_appended_action_reported(
        self, cli: S0maCLI, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        target = tmp_path / "appendjson"
        target.mkdir()
        (target / "pyproject.toml").write_text(
            '[project]\nname = "appendjson"\n', encoding="utf-8"
        )

        rc = cli.run(["new", "project", str(target), "--format", "json"])

        assert rc == EXIT_SUCCESS
        report = json.loads(capsys.readouterr().out)
        assert report["pyproject"]["action"] == "appended"

    def test_refusal_shape(
        self, cli: S0maCLI, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        target = tmp_path / "refusejson"
        target.mkdir()
        (target / "pyproject.toml").write_text(
            "[tool.s0ma]\n", encoding="utf-8"
        )

        rc = cli.run(["new", "project", str(target), "--format", "json"])

        assert rc == EXIT_VALIDATION_ERROR
        report = json.loads(capsys.readouterr().out)
        assert report["ok"] is False
        assert len(report["refusals"]) == 1
        assert "[tool.s0ma]" in report["refusals"][0]

    def test_declared_mode_is_written_and_reported(
        self, cli: S0maCLI, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        target = tmp_path / "strictproj"

        rc = cli.run(
            ["new", "project", str(target), "--mode", "strict",
             "--format", "json"]
        )

        assert rc == EXIT_SUCCESS
        report = json.loads(capsys.readouterr().out)
        assert report["mode"] == "strict"
        text = (target / "pyproject.toml").read_text(encoding="utf-8")
        assert 'mode = "strict"' in text


# ---------------------------------------------------------------------------
# STD-M4/M6: --default-off writes the authoring posture (+ AGENTS.md)
# ---------------------------------------------------------------------------


class TestAuthoringFlag:
    """``--default-off`` flips the written ``[tool.s0ma].authoring`` key
    and the AGENTS.md handshake guidance.
    """

    def test_default_writes_authoring_on(
        self, cli: S0maCLI, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        target = tmp_path / "onproj"

        rc = cli.run(["new", "project", str(target), "--format", "json"])

        assert rc == EXIT_SUCCESS
        report = json.loads(capsys.readouterr().out)
        assert report["authoring"] == "on"
        text = (target / "pyproject.toml").read_text(encoding="utf-8")
        assert 'authoring = "on"' in text
        # The written key round-trips through the project model as "on".
        from s0ma_dsl.project import S0maProject

        assert S0maProject.discover(target).authoring == "on"

    def test_default_off_writes_authoring_off(
        self, cli: S0maCLI, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        target = tmp_path / "offproj"

        rc = cli.run(
            ["new", "project", str(target), "--default-off",
             "--format", "json"]
        )

        assert rc == EXIT_SUCCESS
        report = json.loads(capsys.readouterr().out)
        assert report["authoring"] == "off"
        text = (target / "pyproject.toml").read_text(encoding="utf-8")
        assert 'authoring = "off"' in text
        assert 'authoring = "on"' not in text
        # The written key round-trips through the project model as "off".
        from s0ma_dsl.project import S0maProject

        assert S0maProject.discover(target).authoring == "off"

    def test_default_off_agents_md_omits_the_handshake(
        self, cli: S0maCLI, tmp_path: Path
    ) -> None:
        """An authoring-off project documents the OFF posture, no prompt."""
        target = tmp_path / "offagents"
        assert cli.run(
            ["new", "project", str(target), "--default-off", "--quiet"]
        ) == EXIT_SUCCESS

        agents = (target / "AGENTS.md").read_text(encoding="utf-8")
        assert "authoring is ON" not in agents
        assert "posture is OFF" in agents
        # The thin CLAUDE.md is identical regardless of posture.
        assert (target / "CLAUDE.md").read_text(encoding="utf-8") == (
            "@AGENTS.md\n"
        )

    def test_default_off_appends_off_to_existing_pyproject(
        self, cli: S0maCLI, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """The flag also drives the byte-preserving append path."""
        target = tmp_path / "appendoff"
        target.mkdir()
        (target / "pyproject.toml").write_text(
            '[project]\nname = "appendoff"\n', encoding="utf-8"
        )

        rc = cli.run(
            ["new", "project", str(target), "--default-off", "--quiet"]
        )

        assert rc == EXIT_SUCCESS
        text = (target / "pyproject.toml").read_text(encoding="utf-8")
        assert 'authoring = "off"' in text

    def test_default_off_renders_in_text_summary(
        self, cli: S0maCLI, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        target = tmp_path / "offtext"

        rc = cli.run(["new", "project", str(target), "--default-off"])

        assert rc == EXIT_SUCCESS
        out = capsys.readouterr().out
        assert "authoring = off" in out


# ---------------------------------------------------------------------------
# FB-M9 (FD-13 + FD-7): the feedback posture and the /s0ma-feedback skill
# ---------------------------------------------------------------------------


class TestFeedbackScaffold:
    """What a new beta project receives so feedback can reach the team.

    Two artifacts, with deliberately different natures. The
    ``[tool.s0ma] feedback = "suggest"`` key is *configuration* the MCP
    server reads per rules render to decide whether an agent may OFFER to
    draft feedback. The ``/s0ma-feedback`` skill is a *file in the user's
    client configuration*, so it is created only when absent, never
    clobbers one the user has, never causes a refusal — and is always
    listed in the summary, because that listing is the installation
    disclosure.
    """

    SKILL_PARTS = (".claude", "skills", "s0ma-feedback", "SKILL.md")

    def test_the_created_pyproject_declares_the_suggest_posture(
        self, cli: S0maCLI, tmp_path: Path
    ) -> None:
        target = tmp_path / "fbnew"

        assert cli.run(
            ["new", "project", str(target), "--quiet"]
        ) == EXIT_SUCCESS

        text = (target / "pyproject.toml").read_text(encoding="utf-8")
        assert 'feedback = "suggest"' in text
        # Written after `authoring`, so the STD-M6 key order still holds.
        assert text.index('authoring = "on"') < text.index('feedback = ')

    def test_the_appended_table_declares_it_too(
        self, cli: S0maCLI, tmp_path: Path
    ) -> None:
        target = tmp_path / "fbappend"
        target.mkdir()
        (target / "pyproject.toml").write_text(
            '[project]\nname = "fbappend"\nversion = "0.1.0"\n',
            encoding="utf-8",
        )

        assert cli.run(
            ["new", "project", str(target), "--quiet"]
        ) == EXIT_SUCCESS

        assert 'feedback = "suggest"' in (
            (target / "pyproject.toml").read_text(encoding="utf-8")
        )

    def test_default_off_does_not_touch_the_feedback_posture(
        self, cli: S0maCLI, tmp_path: Path
    ) -> None:
        """Feedback is user-invoked, not authoring-mode-gated."""
        target = tmp_path / "fboff"

        assert cli.run(
            ["new", "project", str(target), "--default-off", "--quiet"]
        ) == EXIT_SUCCESS

        text = (target / "pyproject.toml").read_text(encoding="utf-8")
        assert 'authoring = "off"' in text
        assert 'feedback = "suggest"' in text
        assert (target.joinpath(*self.SKILL_PARTS)).is_file()

    def test_the_skill_is_written_when_absent(
        self, cli: S0maCLI, tmp_path: Path
    ) -> None:
        target = tmp_path / "fbskill"

        assert cli.run(
            ["new", "project", str(target), "--quiet"]
        ) == EXIT_SUCCESS

        skill = (target.joinpath(*self.SKILL_PARTS)).read_text(encoding="utf-8")
        # Frontmatter: the name Claude Code turns into /s0ma-feedback.
        assert skill.startswith("---\nname: s0ma-feedback\ndescription: ")
        assert "you approve the exact feedback data before anything is sent" in (
            skill
        )
        # Body: the same journey, in order, ending at the CLI fallback.
        anchors = [
            "prepare_feedback",
            "redaction report",
            "submit_feedback",
            "`s0ma feedback`",
        ]
        positions = [skill.index(anchor) for anchor in anchors]
        assert positions == sorted(positions)
        # Seeded from the argument; one question only when there is none.
        assert "typed after `/s0ma-feedback`" in skill
        assert "ONE short question" in skill
        # A-1 lives here as the contrast: invoking the command IS the
        # statement that this is about s0ma.
        assert "without naming s0ma or kn0wthyself, ask first" in skill
        # A-2 voice, and the approval interaction is never claimed.
        assert "payload" not in skill.lower()
        assert "never state or assume that the user approved" in skill
        # LF everywhere (INV-5 determinism / NFR-7 platforms).
        assert "\r" not in skill

    def test_an_existing_skill_is_kept_and_never_causes_a_refusal(
        self, cli: S0maCLI, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Created-if-absent — deliberately NOT in the atomic-refusal set."""
        target = tmp_path / "fbkeep"
        skill_path = target.joinpath(*self.SKILL_PARTS)
        skill_path.parent.mkdir(parents=True)
        skill_path.write_text("mine, not yours\n", encoding="utf-8")

        rc = cli.run(["new", "project", str(target), "--format", "json"])

        assert rc == EXIT_SUCCESS
        report = json.loads(capsys.readouterr().out)
        assert report["ok"] is True
        assert report["feedback_skill"]["created"] is False
        assert skill_path.read_text(encoding="utf-8") == "mine, not yours\n"

    def test_the_printed_summary_discloses_both(
        self, cli: S0maCLI, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        target = tmp_path / "fbprint"

        rc = cli.run(["new", "project", str(target)])

        assert rc == EXIT_SUCCESS
        out = capsys.readouterr().out
        assert "feedback = suggest" in out
        assert ".claude/skills/s0ma-feedback/SKILL.md" in out
        assert "/s0ma-feedback skill" in out

    def test_the_json_summary_discloses_both(
        self, cli: S0maCLI, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        target = tmp_path / "fbjson"

        rc = cli.run(["new", "project", str(target), "--format", "json"])

        assert rc == EXIT_SUCCESS
        report = json.loads(capsys.readouterr().out)
        assert report["feedback"] == "suggest"
        assert report["feedback_skill"]["created"] is True
        assert report["feedback_skill"]["path"] == str(target.joinpath(*self.SKILL_PARTS))

    def test_the_archetype_path_carries_the_same_two_facts(
        self, cli: S0maCLI, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        target = tmp_path / "fb-lib"

        rc = cli.run(
            ["new", "project", str(target), "--template", "library",
             "--format", "json"]
        )

        assert rc == EXIT_SUCCESS
        report = json.loads(capsys.readouterr().out)
        assert report["feedback"] == "suggest"
        assert report["feedback_skill"]["created"] is True
        text = (target / "pyproject.toml").read_text(encoding="utf-8")
        assert 'feedback = "suggest"' in text
        assert (target.joinpath(*self.SKILL_PARTS)).is_file()

    def test_the_archetype_bootstrap_list_still_follows_the_posture(
        self, cli: S0maCLI, tmp_path: Path
    ) -> None:
        """Key order: base table, then feedback, then bootstrap_files."""
        target = tmp_path / "fb-svc"

        assert cli.run(
            ["new", "project", str(target), "--template", "service", "--quiet"]
        ) == EXIT_SUCCESS

        text = (target / "pyproject.toml").read_text(encoding="utf-8")
        assert text.index('feedback = "suggest"') < text.index("bootstrap_files")

    def test_the_scaffolded_project_reads_back_as_suggest(
        self, cli: S0maCLI, tmp_path: Path
    ) -> None:
        """The written key parses as the exact value the server matches on."""
        import tomllib

        target = tmp_path / "fbread"
        assert cli.run(
            ["new", "project", str(target), "--quiet"]
        ) == EXIT_SUCCESS

        with (target / "pyproject.toml").open("rb") as fh:
            data = tomllib.load(fh)
        assert data["tool"]["s0ma"]["feedback"] == "suggest"


# ---------------------------------------------------------------------------
# STD-M7: --template archetypes (service / library / cli / pipeline)
# ---------------------------------------------------------------------------


class TestArchetypeTemplates:
    """Each ``--template`` archetype scaffolds a complete, compiling mini-app.

    The acceptance gate: for every template, scaffold to a temp dir, build,
    and check — all green — plus assert the expected feature layout, the
    AGENTS.md + thin CLAUDE.md, the rendering app map, and the
    boundary-doctrine bootstrap wiring. Kept fast (one build+check each;
    release-mode check folded into the same scaffold).
    """

    @pytest.mark.parametrize(
        ("template", "expected_features", "expected_modules"),
        [
            (
                "service",
                ["catalog", "ordering", "api"],
                [
                    "api_presentation",
                    "api_presentation_tests",
                    "app_map",
                    "catalog_domain",
                    "catalog_domain_tests",
                    "ordering_application",
                    "ordering_application_tests",
                ],
            ),
            (
                "library",
                ["toolkit"],
                [
                    "app_map",
                    "toolkit_api",
                    "toolkit_domain",
                    "toolkit_domain_tests",
                ],
            ),
            (
                "cli",
                ["greeting", "console"],
                [
                    "app_map",
                    "console_presentation",
                    "console_presentation_tests",
                    "greeting_application",
                    "greeting_application_tests",
                    "greeting_domain",
                    "greeting_domain_tests",
                ],
            ),
            (
                "pipeline",
                ["player", "music", "coach", "page"],
                [
                    "app_map",
                    "coach",
                    "coach_tests",
                    "music",
                    "music_tests",
                    "page",
                    "page_tests",
                    "player",
                    "player_tests",
                ],
            ),
        ],
    )
    def test_archetype_scaffolds_builds_and_checks(
        self,
        cli: S0maCLI,
        tmp_path: Path,
        template: str,
        expected_features: list[str],
        expected_modules: list[str],
    ) -> None:
        target = tmp_path / f"{template}-app"

        rc = cli.run(
            ["new", "project", str(target), "--template", template, "--quiet"]
        )
        assert rc == EXIT_SUCCESS

        # Feature-first layout: each feature directory exists under src/.
        for feature in expected_features:
            assert (target / "src" / feature).is_dir()
        # The project-wide app map ships with every archetype.
        assert (target / "src" / "app_map.s0ma").is_file()
        # AGENTS.md (canonical) + a thin CLAUDE.md that is exactly @AGENTS.md.
        assert (target / "AGENTS.md").is_file()
        assert (target / "CLAUDE.md").read_text(encoding="utf-8") == (
            "@AGENTS.md\n"
        )
        # The first build built the whole project (src + tests) flat.
        built = sorted(
            p.stem
            for p in (target / "build").glob("*.py")
            if p.name != "__init__.py"
        )
        assert built == expected_modules
        # The app map rendered to build/docs and cannot drift.
        assert (target / "build" / "docs" / "architecture_map.md").is_file()
        assert (
            target / "build" / "docs" / "public_api_reference.md"
        ).is_file()

        # check passes in dev AND release (the strictest gate) out of the box.
        assert cli.run(["--project-root", str(target), "check"]) == (
            EXIT_SUCCESS
        )
        assert cli.run(
            ["--project-root", str(target), "check", "--mode", "release"]
        ) == EXIT_SUCCESS
        # The rendered app map is drift-free as built.
        assert cli.run(
            ["--project-root", str(target), "docs", "check-drift",
             str(target / "src")]
        ) == EXIT_SUCCESS

    def test_service_teaches_cross_feature_depends_on(
        self, cli: S0maCLI, tmp_path: Path
    ) -> None:
        """The service archetype wires PRESENTATION → APPLICATION → DOMAIN."""
        target = tmp_path / "svc"
        assert cli.run(
            ["new", "project", str(target), "--template", "service",
             "--quiet"]
        ) == EXIT_SUCCESS

        # The application service depends_on the domain (qualified, cross-
        # feature); the presentation boundary depends_on the application.
        app_src = (
            target / "src" / "ordering" / "ordering_application.s0ma"
        ).read_text(encoding="utf-8")
        assert "uses: [catalog_domain.Product, catalog_domain.price_of]" in (
            app_src
        )
        assert "catalog_domain.price_of: {relation: CALLS" in app_src
        api_src = (
            target / "src" / "api" / "api_presentation.s0ma"
        ).read_text(encoding="utf-8")
        assert "ordering_application.submit_order: {relation: CALLS" in api_src

        # The sanctioned bootstrap is declared so verify classifies it
        # BOOTSTRAP, not UNKNOWN — the boundary doctrine made executable.
        pyproject = (target / "pyproject.toml").read_text(encoding="utf-8")
        assert 'bootstrap_files = ["bootstrap/main.py"]' in pyproject
        assert (target / "bootstrap" / "main.py").is_file()

    def test_library_teaches_covered_by(
        self, cli: S0maCLI, tmp_path: Path
    ) -> None:
        """The library archetype shows exports + covered_by on a thin facade."""
        target = tmp_path / "lib"
        assert cli.run(
            ["new", "project", str(target), "--template", "library",
             "--quiet"]
        ) == EXIT_SUCCESS

        api_src = (
            target / "src" / "toolkit" / "toolkit_api.s0ma"
        ).read_text(encoding="utf-8")
        # The public facade carries covered_by (external pytest credit) and
        # has no in-language test — release mode passes on that credit.
        assert "covered_by:" in api_src
        assert "exports: [normalize_title]" in api_src
        # Layer-light: no bootstrap_files key for a pure library.
        pyproject = (target / "pyproject.toml").read_text(encoding="utf-8")
        assert "bootstrap_files" not in pyproject

    def test_cli_teaches_argparse_remainder(
        self, cli: S0maCLI, tmp_path: Path
    ) -> None:
        """The cli archetype ships the argparse.REMAINDER bootstrap shim."""
        target = tmp_path / "clip"
        assert cli.run(
            ["new", "project", str(target), "--template", "cli", "--quiet"]
        ) == EXIT_SUCCESS

        shim = (target / "bootstrap" / "cli.py").read_text(encoding="utf-8")
        assert "argparse.REMAINDER" in shim
        # The leading-'--' strip the quick reference documents.
        assert 'rest[0] == "--"' in shim
        # It dispatches to the PRESENTATION router nerve.
        assert 'modules["console_presentation"].dispatch' in shim
        pyproject = (target / "pyproject.toml").read_text(encoding="utf-8")
        assert 'bootstrap_files = ["bootstrap/cli.py"]' in pyproject

    def test_pipeline_is_one_module_per_layer_and_runs(
        self, cli: S0maCLI, tmp_path: Path
    ) -> None:
        """The pipeline archetype has one module per layer, and its parts run.

        Its own tests pass under ``s0ma test``, and the bootstrap prints the
        page for a built-in song. The bootstrap runs in a subprocess so the
        built modules do not register into this process's registry.
        """
        target = tmp_path / "pipe"
        assert cli.run(
            ["new", "project", str(target), "--template", "pipeline",
             "--quiet"]
        ) == EXIT_SUCCESS

        layers = {
            "player": "INFRASTRUCTURE",
            "music": "DOMAIN",
            "coach": "APPLICATION",
            "page": "PRESENTATION",
        }
        for module, layer in layers.items():
            source = (target / "src" / module / f"{module}.s0ma").read_text(
                encoding="utf-8"
            )
            assert source.startswith(f"module {module}\n    layer: {layer}\n")
        # The watcher observes the mood nerve, and the observation resolves.
        coach_py = (target / "build" / "coach.py").read_text(encoding="utf-8")
        assert '"resolved_observes": ["music::settle_mood"]' in coach_py
        pyproject = (target / "pyproject.toml").read_text(encoding="utf-8")
        assert 'bootstrap_files = ["bootstrap/main.py"]' in pyproject

        assert cli.run(
            ["--project-root", str(target), "test", "--quiet"]
        ) == EXIT_SUCCESS

        result = subprocess.run(
            [sys.executable, str(target / "bootstrap" / "main.py"), "1"],
            capture_output=True,
            text=True,
            timeout=120,
            check=False,
        )
        assert result.returncode == 0, result.stderr
        assert "now playing: Night Drive" in result.stdout
        assert "<h1>The mood is tense</h1>" in result.stdout

    def test_archetype_tests_run_green(
        self, cli: S0maCLI, tmp_path: Path
    ) -> None:
        """The scaffolded `.s0ma` tests execute under `s0ma test`."""
        target = tmp_path / "svc-test"
        assert cli.run(
            ["new", "project", str(target), "--template", "service",
             "--quiet"]
        ) == EXIT_SUCCESS

        assert cli.run(
            ["--project-root", str(target), "test", "--quiet"]
        ) == EXIT_SUCCESS

    def test_archetype_json_shape(
        self, cli: S0maCLI, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        target = tmp_path / "svc-json"

        rc = cli.run(
            ["new", "project", str(target), "--template", "service",
             "--format", "json"]
        )

        assert rc == EXIT_SUCCESS
        report = json.loads(capsys.readouterr().out)
        assert report["ok"] is True
        assert report["template"] == "service"
        assert report["features"] == ["catalog", "ordering", "api"]
        assert report["bootstrap_files"] == ["bootstrap/main.py"]
        assert report["teaches"]
        assert report["agents_file"]["path"].endswith("AGENTS.md")
        assert report["claude_file"]["path"].endswith("CLAUDE.md")
        assert "submit_order" not in report["build"]["modules"]  # nerve, not module
        assert "ordering_application" in report["build"]["modules"]
        assert report["next_steps"]["test"] == "s0ma test"

    def test_archetype_default_off_writes_off(
        self, cli: S0maCLI, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """--default-off rides through the archetype path too."""
        target = tmp_path / "lib-off"

        rc = cli.run(
            ["new", "project", str(target), "--template", "library",
             "--default-off", "--format", "json"]
        )

        assert rc == EXIT_SUCCESS
        report = json.loads(capsys.readouterr().out)
        assert report["authoring"] == "off"
        text = (target / "pyproject.toml").read_text(encoding="utf-8")
        assert 'authoring = "off"' in text
        agents = (target / "AGENTS.md").read_text(encoding="utf-8")
        assert "posture is OFF" in agents

    def test_archetype_refuses_existing_project_atomically(
        self, cli: S0maCLI, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        target = tmp_path / "claimed"
        target.mkdir()
        (target / "pyproject.toml").write_text(
            '[project]\nname = "claimed"\n\n[tool.s0ma]\nbuild_dir = "out"\n',
            encoding="utf-8",
        )
        before = _snapshot(target)

        rc = cli.run(
            ["new", "project", str(target), "--template", "service"]
        )

        assert rc == EXIT_VALIDATION_ERROR
        assert _snapshot(target) == before, "refusal must change nothing"
        assert "already has a [tool.s0ma] table" in capsys.readouterr().out

    def test_archetype_appends_to_existing_pyproject(
        self, cli: S0maCLI, tmp_path: Path
    ) -> None:
        """An archetype byte-preservingly appends [tool.s0ma] when present."""
        target = tmp_path / "existing"
        target.mkdir()
        original = '[project]\nname = "keeper"\nversion = "1.0.0"\n'
        (target / "pyproject.toml").write_text(original, encoding="utf-8")

        rc = cli.run(
            ["new", "project", str(target), "--template", "cli", "--quiet"]
        )

        assert rc == EXIT_SUCCESS
        text = (target / "pyproject.toml").read_text(encoding="utf-8")
        assert text.startswith(original)
        assert 'bootstrap_files = ["bootstrap/cli.py"]' in text


# ---------------------------------------------------------------------------
# The agent template: five ordered steps, laid down whole
# ---------------------------------------------------------------------------

#: The decided name and one-line intent of each agent step, word for word.
_AGENT_STEPS: tuple[tuple[str, str], ...] = (
    (
        "What it hears",
        "A customer's message, and the order number in it if there is one.",
    ),
    (
        "What it must and must never do",
        "It answers or hands off to a person, and it never promises a refund.",
    ),
    (
        "Its tools",
        "A short list of common answers, and a way to look up an order.",
    ),
    (
        "How it decides",
        "It picks one of three: answer from the list, look up the order, or "
        "hand off to a person. A scripted stand-in plays the model, so it "
        "runs with no account.",
    ),
    (
        "The check that watches it",
        "It counts how many messages get handed to a person.",
    ),
)

#: What the bootstrap prints for its default message after steps 1 to N.
_AGENT_FIRST_LINE = {
    1: "heard: Where is my order A1234? (order number: A1234)",
    2: "heard: Where is my order A1234? (order number: A1234)",
    3: "heard: Where is my order A1234? (order number: A1234)",
    4: "answer: Order A1234 is shipped on Monday.",
    5: "answer: Order A1234 is shipped on Monday.",
}


def _expected_sample_files(files: tuple[ArchetypeFile, ...]) -> dict[str, bytes]:
    """What laying down *files* writes: ``.s0ma`` sources in the current grammar."""
    return {
        f.relpath: (
            current_grammar_source(f.content, f.relpath)
            if f.relpath.endswith(".s0ma")
            else f.content
        ).encode("utf-8")
        for f in files
    }


def _written_sample_files(target: Path) -> dict[str, bytes]:
    """Every file under ``src/``, ``tests/`` and ``bootstrap/``, by POSIX path."""
    return {
        p.relative_to(target).as_posix(): p.read_bytes()
        for top in ("src", "tests", "bootstrap")
        for p in sorted((target / top).rglob("*"))
        if p.is_file()
    }


class TestAgentTemplate:
    """``--template agent``: a small support-inbox agent in five steps.

    Every prefix of its steps is a clean project, and laying it down whole
    writes exactly the files of all five steps.
    """

    def test_the_decided_words_are_exact(self) -> None:
        from s0ma_dsl.cli.templates import get_archetype

        agent = get_archetype("agent")
        assert tuple((step.name, step.intent) for step in agent.steps) == (
            _AGENT_STEPS
        )
        assert agent.called == "a small agent"
        assert agent.noun == "agent"
        assert agent.example_question == (
            "what is this agent never allowed to do?"
        )

    def test_files_through_applies_the_steps_in_order(self) -> None:
        """A later step replaces an earlier file in place; the count is checked."""
        from s0ma_dsl.cli.templates import get_archetype

        agent = get_archetype("agent")
        sizes = [len(agent.files_through(n)) for n in range(1, 6)]
        assert sizes == [4, 6, 8, 13, 15]
        assert agent.files_through(5) == agent.files
        first = {f.relpath: f for f in agent.files_through(1)}
        whole = {f.relpath: f for f in agent.files}
        # Step 4 replaces the bootstrap step 1 wrote.
        assert first["bootstrap/main.py"] != whole["bootstrap/main.py"]
        assert whole["bootstrap/main.py"] in agent.steps[3].files
        assert [f.relpath for f in agent.files][:4] == [
            f.relpath for f in agent.files_through(1)
        ]
        for count in (0, 6):
            with pytest.raises(ValueError):
                agent.files_through(count)
        assert agent.through_step(2).files == agent.files_through(2)
        assert agent.through_step(2).features == ("inbox", "rules")

    @pytest.mark.parametrize("count", [1, 2, 3, 4, 5])
    def test_steps_one_to_n_make_a_clean_project(
        self,
        cli: S0maCLI,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
        monkeypatch: pytest.MonkeyPatch,
        count: int,
    ) -> None:
        """Steps 1 to N check in dev and release mode, build, test, and run.

        Nothing printed carries a diagnostic, a warning, or the nudge to
        declare a health_command. The bootstrap runs in a subprocess so the
        built modules stay out of this process's registry.
        """
        from s0ma_dsl.cli import templates

        whole = templates.get_archetype("agent")
        monkeypatch.setitem(
            templates._ARCHETYPES, "agent", lambda: whole.through_step(count)
        )
        target = tmp_path / f"agent-{count}"
        assert cli.run(_new_project_argv(target, "agent")) == EXIT_SUCCESS
        capsys.readouterr()
        assert _written_sample_files(target) == _expected_sample_files(
            whole.files_through(count)
        )

        root = ["--project-root", str(target)]
        for argv in (
            [*root, "check"],
            [*root, "check", "--mode", "release"],
            [*root, "build", str(target)],
            [*root, "test"],
        ):
            assert cli.run(argv) == EXIT_SUCCESS, argv
            captured = capsys.readouterr()
            printed = captured.out + captured.err
            assert _DIAGNOSTIC_LINE.findall(printed) == [], (argv, printed)
            assert "no health_command declared" not in printed, argv
            if argv[2] != "test":  # pytest's own summary is not ours
                assert "warning" not in printed.lower(), (argv, printed)
            if argv[2] == "build":
                assert "verify: python bootstrap/main.py" in printed

        result = subprocess.run(
            [sys.executable, str(target / "bootstrap" / "main.py")],
            capture_output=True,
            text=True,
            timeout=120,
            check=False,
        )
        assert result.returncode == 0, result.stderr
        assert result.stderr == ""
        assert result.stdout.splitlines() == [_AGENT_FIRST_LINE[count]]

    def test_the_whole_sample_is_the_files_of_every_step(
        self, cli: S0maCLI, tmp_path: Path
    ) -> None:
        """The one-shot project is byte for byte the files of steps 1 to 5."""
        from s0ma_dsl.cli.templates import get_archetype

        target = tmp_path / "agent-whole"
        assert cli.run(_new_project_argv(target, "agent")) == EXIT_SUCCESS

        expected = _expected_sample_files(
            get_archetype("agent").files_through(5)
        )
        assert _written_sample_files(target) == expected
        pyproject = (target / "pyproject.toml").read_text(encoding="utf-8")
        assert 'bootstrap_files = ["bootstrap/main.py"]' in pyproject
        assert 'health_command = "python bootstrap/main.py"' in pyproject

    def test_files_are_lf_and_keep_their_backslashes(
        self, cli: S0maCLI, tmp_path: Path
    ) -> None:
        """No CR on any platform, and a regex's \\b stays two characters."""
        target = tmp_path / "agent-bytes"
        assert cli.run(_new_project_argv(target, "agent")) == EXIT_SUCCESS

        for relpath, data in _written_sample_files(target).items():
            assert b"\r" not in data, relpath
            assert b"\x08" not in data, relpath
        inbox = (target / "src" / "inbox" / "inbox.s0ma").read_bytes()
        assert b're.search(r"\\bA\\d{4}\\b", tidy)' in inbox

    def test_json_says_what_the_sample_is(
        self, cli: S0maCLI, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        target = tmp_path / "agent-json"
        argv = ["new", "project", str(target), "--template", "agent",
                "--format", "json"]
        assert cli.run(argv) == EXIT_SUCCESS

        report = json.loads(capsys.readouterr().out)
        assert report["ok"] is True
        assert report["template"] == "agent"
        assert report["called"] == "a small agent"
        assert report["noun"] == "agent"
        assert report["example_question"] == (
            "what is this agent never allowed to do?"
        )
        assert report["steps"] == [
            {"number": number, "name": name, "intent": intent}
            for number, (name, intent) in enumerate(_AGENT_STEPS, start=1)
        ]
        # Both counts are read from the built project: modules as the
        # build's closing line counts them, parts as the Components column
        # of `s0ma inspect --all` adds up.
        assert report["modules"] == 14
        assert report["parts"] == 16
        assert report["features"] == [
            "inbox", "rules", "tools", "model", "stand_in", "triage", "watch",
        ]

    def test_a_template_without_steps_reports_no_steps(
        self, cli: S0maCLI, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        target = tmp_path / "svc-nosteps"
        argv = ["new", "project", str(target), "--template", "service",
                "--format", "json"]
        assert cli.run(argv) == EXIT_SUCCESS

        report = json.loads(capsys.readouterr().out)
        for key in (
            "called", "noun", "example_question", "steps", "modules", "parts"
        ):
            assert key not in report

    def test_the_cli_offers_exactly_the_template_list(self) -> None:
        import argparse

        parser = S0maCLI().build_parser()
        (commands,) = (
            a for a in parser._actions
            if isinstance(a, argparse._SubParsersAction)
        )
        new = commands.choices["new"]
        (template,) = (a for a in new._actions if a.dest == "template")
        assert list(template.choices) == list(TEMPLATE_CHOICES)
        assert "agent" in TEMPLATE_CHOICES


#: What ``s0ma build`` and ``s0ma inspect --all`` show after steps 0 to N:
#: ``(modules, parts)``.
_AGENT_COUNTS = {0: (0, 0), 1: (3, 3), 2: (5, 6), 3: (7, 9), 4: (12, 14), 5: (14, 16)}


def _project_files(target: Path) -> dict[str, bytes]:
    """Every file a person keeps: all but ``build/``, caches, and dot folders.

    ``.claude/`` is kept, since the scaffold writes it.
    """
    files: dict[str, bytes] = {}
    for path in sorted(target.rglob("*")):
        if not path.is_file():
            continue
        parts = path.relative_to(target).parts
        if parts[0] == "build" or "__pycache__" in parts:
            continue
        if any(p.startswith(".") for p in parts) and parts[0] != ".claude":
            continue
        files["/".join(parts)] = path.read_bytes()
    return files


def _every_byte(target: Path) -> dict[str, bytes]:
    """Every file under *target*, the build included."""
    return {
        p.relative_to(target).as_posix(): p.read_bytes()
        for p in sorted(target.rglob("*"))
        if p.is_file()
    }


def _step_argv(target: Path, step: int, *extra: str) -> list[str]:
    return ["new", "project", str(target), "--template", "agent",
            "--step", str(step), *extra]


def _run_json(
    cli: S0maCLI, argv: list[str], capsys: pytest.CaptureFixture[str]
) -> tuple[int, dict[str, Any]]:
    capsys.readouterr()
    rc = cli.run([*argv, "--format", "json"])
    return rc, json.loads(capsys.readouterr().out)


def _step_line(number: int) -> str:
    name, intent = _AGENT_STEPS[number - 1]
    return f"Step {number} of 5: {name}. {intent}"


class TestAgentSteps:
    """``--step N`` and ``--sample``: the agent laid down one step at a time.

    No state file is kept; the step a project is on is read from its files.
    """

    def test_walking_every_step_ends_where_the_one_shot_ends(
        self, cli: S0maCLI, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Step 0, then 1 to 5, one call each; every stop checks, builds, tests."""
        target = tmp_path / "walk"
        assert cli.run(_step_argv(target, 0)) == EXIT_SUCCESS
        out = capsys.readouterr().out
        assert out == (
            f"Step 0 of 5: the project is ready at {target}, and nothing "
            f"is built yet.\n"
        )
        assert not (target / "build").exists()
        assert not list(target.rglob("*.s0ma"))

        root = ["--project-root", str(target)]
        for number in range(1, 6):
            assert cli.run(_step_argv(target, number)) == EXIT_SUCCESS
            out = capsys.readouterr().out
            assert out.splitlines()[0] == _step_line(number)
            modules, parts = _AGENT_COUNTS[number]
            assert (
                f"{modules} module(s) built with {parts} parts, mode dev)."
                in out.splitlines()[1]
            )
            for argv in (
                [*root, "check"],
                [*root, "check", "--mode", "release"],
                [*root, "build", str(target)],
                [*root, "test"],
            ):
                assert cli.run(argv) == EXIT_SUCCESS, (number, argv)
                captured = capsys.readouterr()
                printed = captured.out + captured.err
                assert _DIAGNOSTIC_LINE.findall(printed) == [], (argv, printed)

        whole = tmp_path / "walk"
        one_shot = tmp_path / "one-shot" / "walk"
        assert cli.run(_new_project_argv(one_shot, "agent")) == EXIT_SUCCESS
        assert _project_files(whole) == _project_files(one_shot)

    @pytest.mark.parametrize("number", [0, 2, 5])
    def test_a_step_run_again_changes_nothing(
        self,
        cli: S0maCLI,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
        number: int,
    ) -> None:
        target = tmp_path / f"again-{number}"
        assert cli.run(_step_argv(target, number)) == EXIT_SUCCESS
        first = capsys.readouterr().out.splitlines()[0]
        before = _every_byte(target)

        assert cli.run(_step_argv(target, number)) == EXIT_SUCCESS
        out = capsys.readouterr().out.splitlines()
        assert out[0] == first
        assert _every_byte(target) == before

        rc, report = _run_json(cli, _step_argv(target, number), capsys)
        assert rc == EXIT_SUCCESS
        assert report["unchanged"] is True
        assert report["files_written"] == []
        assert _every_byte(target) == before

    def test_an_edited_file_the_next_step_replaces_is_refused(
        self, cli: S0maCLI, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Step 4 replaces the bootstrap; an edit to it stops the call."""
        target = tmp_path / "edited"
        assert cli.run(_step_argv(target, 3)) == EXIT_SUCCESS
        bootstrap = target / "bootstrap" / "main.py"
        bootstrap.write_bytes(bootstrap.read_bytes() + b"# mine\n")
        before = _every_byte(target)
        capsys.readouterr()

        assert cli.run(_step_argv(target, 4)) == EXIT_VALIDATION_ERROR
        out = capsys.readouterr().out
        assert "(nothing was changed)" in out
        assert (
            "  - bootstrap/main.py has changes of yours, and step 4 would "
            "replace it\n"
        ) in out
        assert _every_byte(target) == before

        rc, report = _run_json(cli, _step_argv(target, 5), capsys)
        assert rc == EXIT_VALIDATION_ERROR
        assert report["ok"] is False
        assert report["at_step"] == 3
        assert _every_byte(target) == before

    def test_files_no_later_step_touches_are_kept_and_reported(
        self, cli: S0maCLI, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """An added file and an edit to a file no later step replaces."""
        target = tmp_path / "kept"
        assert cli.run(_step_argv(target, 4)) == EXIT_SUCCESS
        (target / "notes.md").write_text("my notes\n", encoding="utf-8")
        bootstrap = target / "bootstrap" / "main.py"
        edited = bootstrap.read_bytes() + b"# mine\n"
        bootstrap.write_bytes(edited)

        rc, report = _run_json(cli, _step_argv(target, 5), capsys)
        assert rc == EXIT_SUCCESS
        assert report["files_kept"] == ["bootstrap/main.py", "notes.md"]
        assert report["files_written"] == [
            "src/watch/watch.s0ma", "tests/watch/watch_tests.s0ma",
        ]
        assert bootstrap.read_bytes() == edited
        assert (target / "notes.md").read_text(encoding="utf-8") == "my notes\n"

        capsys.readouterr()
        assert cli.run(_step_argv(target, 5)) == EXIT_SUCCESS
        out = capsys.readouterr().out
        assert "  notes.md  kept as you left it\n" in out
        assert "  bootstrap/main.py  kept as you left it\n" in out

    @pytest.mark.parametrize("start", [None, 0, 2])
    def test_the_last_step_finishes_from_anywhere(
        self,
        cli: S0maCLI,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
        start: int | None,
    ) -> None:
        target = tmp_path / "finish"
        if start is not None:
            assert cli.run(_step_argv(target, start)) == EXIT_SUCCESS
        rc, report = _run_json(cli, _step_argv(target, 5), capsys)
        assert rc == EXIT_SUCCESS
        assert report["finished"] is True

        one_shot = tmp_path / "one-shot" / "finish"
        assert cli.run(_new_project_argv(one_shot, "agent")) == EXIT_SUCCESS
        assert _project_files(target) == _project_files(one_shot)

    def test_going_back_a_step_is_refused(
        self, cli: S0maCLI, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        target = tmp_path / "back"
        assert cli.run(_step_argv(target, 3)) == EXIT_SUCCESS
        before = _every_byte(target)
        capsys.readouterr()

        assert cli.run(_step_argv(target, 1)) == EXIT_VALIDATION_ERROR
        assert capsys.readouterr().out == (
            f"s0ma new project: {target} is at step 3 of 5, and --step does "
            f"not go back to step 1.\n"
        )
        assert _every_byte(target) == before

    def test_step_needs_a_template_made_of_steps(
        self, cli: S0maCLI, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        target = tmp_path / "svc"
        argv = ["new", "project", str(target), "--template", "service",
                "--step", "1"]
        assert cli.run(argv) == EXIT_USAGE_ERROR
        assert capsys.readouterr().out == (
            "s0ma new project: --template service has no steps, so --step "
            "does not apply to it.\n"
        )
        assert cli.run(["new", "project", str(target), "--step", "1"]) == (
            EXIT_USAGE_ERROR
        )
        assert "--step needs --template or --sample" in capsys.readouterr().out
        assert not target.exists()

    @pytest.mark.parametrize("number", [-1, 6])
    def test_a_step_out_of_range_names_the_range(
        self,
        cli: S0maCLI,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
        number: int,
    ) -> None:
        target = tmp_path / "range"
        assert cli.run(_step_argv(target, number)) == EXIT_USAGE_ERROR
        assert capsys.readouterr().out == (
            f"s0ma new project: --step must be between 0 and 5 for "
            f"--template agent, not {number}.\n"
        )
        assert not target.exists()

    def test_a_s0ma_project_from_something_else_is_refused(
        self, cli: S0maCLI, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        target = tmp_path / "other"
        assert cli.run(_new_project_argv(target, "service")) == EXIT_SUCCESS
        before = _every_byte(target)
        capsys.readouterr()

        assert cli.run(_step_argv(target, 1)) == EXIT_VALIDATION_ERROR
        out = capsys.readouterr().out
        assert "this is already a s0ma project" in out
        assert _every_byte(target) == before

    def test_sample_alone_is_the_whole_sample_in_its_own_folder(
        self,
        cli: S0maCLI,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        from s0ma_dsl.cli.templates import FIRST_RUN_SAMPLE, get_archetype

        assert FIRST_RUN_SAMPLE == "agent"
        assert get_archetype("agent").default_project_name == "support-agent"
        monkeypatch.chdir(tmp_path)
        rc, report = _run_json(cli, ["new", "project", "--sample"], capsys)
        assert rc == EXIT_SUCCESS
        target = tmp_path / "support-agent"
        assert report["project_root"] == str(target.resolve())
        assert report["project_name"] == "support-agent"
        assert report["template"] == "agent"
        assert "step" not in report

        one_shot = tmp_path / "one-shot" / "support-agent"
        assert cli.run(_new_project_argv(one_shot, "agent")) == EXIT_SUCCESS
        assert _project_files(target) == _project_files(one_shot)

    def test_sample_step_zero_says_where_the_project_is(
        self,
        cli: S0maCLI,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.chdir(tmp_path)
        argv = ["new", "project", "--sample", "--step", "0"]
        rc, report = _run_json(cli, argv, capsys)
        assert rc == EXIT_SUCCESS
        target = (tmp_path / "support-agent").resolve()
        assert report["project_root"] == str(target)

        # The next call names the same folder and goes on from there.
        rc, report = _run_json(
            cli,
            ["new", "project", report["project_root"], "--sample",
             "--step", "1"],
            capsys,
        )
        assert rc == EXIT_SUCCESS
        assert report["step"]["number"] == 1
        assert report["pyproject"]["action"] == "kept"

    def test_sample_with_a_name_uses_that_folder(
        self, cli: S0maCLI, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        target = tmp_path / "my-helper"
        rc, report = _run_json(
            cli, ["new", "project", str(target), "--sample", "--step", "1"],
            capsys,
        )
        assert rc == EXIT_SUCCESS
        assert report["project_root"] == str(target)
        assert report["project_name"] == "my-helper"
        assert not (tmp_path / "support-agent").exists()

    def test_sample_with_template_is_an_error(
        self, cli: S0maCLI, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        target = tmp_path / "both"
        argv = ["new", "project", str(target), "--sample", "--template",
                "agent"]
        assert cli.run(argv) == EXIT_USAGE_ERROR
        assert capsys.readouterr().out == (
            "s0ma new project: use --sample or --template, not both.\n"
        )
        assert not target.exists()

    def test_a_project_without_a_folder_is_an_error(
        self, cli: S0maCLI, capsys: pytest.CaptureFixture[str]
    ) -> None:
        assert cli.run(["new", "project"]) == EXIT_USAGE_ERROR
        assert "name the folder for the project" in capsys.readouterr().out

    @pytest.mark.parametrize("number", [0, 3, 5])
    def test_the_json_shape(
        self,
        cli: S0maCLI,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
        number: int,
    ) -> None:
        target = tmp_path / f"shape-{number}"
        rc, report = _run_json(cli, _step_argv(target, number), capsys)
        assert rc == EXIT_SUCCESS
        assert set(report) == {
            "ok", "project_root", "project_name", "template", "mode",
            "authoring", "feedback", "features", "pyproject", "sources",
            "bootstrap_files", "agents_file", "claude_file",
            "feedback_skill", "launch_config", "build", "teaches",
            "next_steps", "called", "noun", "example_question", "steps",
            "modules",
            "parts", "step", "line", "finished", "unchanged",
            "files_written", "files_kept",
        }
        name, intent = _AGENT_STEPS[number - 1] if number else (None, None)
        assert report["step"] == {
            "number": number, "of": 5, "name": name, "intent": intent,
        }
        assert (report["modules"], report["parts"]) == _AGENT_COUNTS[number]
        assert report["finished"] is (number == 5)
        assert report["unchanged"] is False
        assert report["files_kept"] == []
        assert len(report["steps"]) == 5
        bare = ["pyproject.toml", "AGENTS.md", "CLAUDE.md",
                ".claude/skills/s0ma-feedback/SKILL.md", ".claude/launch.json"]
        if number == 0:
            assert report["build"] is None
            assert report["files_written"] == bare
            assert report["sources"] == []
            assert report["features"] == []
        else:
            from s0ma_dsl.cli.templates import get_archetype

            files = get_archetype("agent").files_through(number)
            assert report["files_written"] == bare + [f.relpath for f in files]
            assert len(report["build"]["modules"]) == report["modules"]
        if number == 3:
            assert report["line"] == _step_line(3)
            assert report["features"] == ["inbox", "rules", "tools"]

    def test_parts_are_what_inspect_all_shows(
        self, cli: S0maCLI, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """The whole sample's counts agree with ``build`` and ``inspect --all``."""
        target = tmp_path / "counted"
        rc, report = _run_json(
            cli, ["new", "project", str(target), "--template", "agent"], capsys
        )
        assert rc == EXIT_SUCCESS

        root = ["--project-root", str(target)]
        assert cli.run([*root, "inspect", "--all", "--format", "json"]) == (
            EXIT_SUCCESS
        )
        survey = json.loads(capsys.readouterr().out)
        assert report["parts"] == sum(row["components"] for row in survey)

        assert cli.run([*root, "inspect", "--all"]) == EXIT_SUCCESS
        table = capsys.readouterr().out.splitlines()
        column = table[0].index("Components") + len("Components")
        shown = sum(
            int(line[:column].split()[-1]) for line in table[2:len(survey) + 2]
        )
        assert report["parts"] == shown

        assert cli.run([*root, "build", str(target)]) == EXIT_SUCCESS
        built = re.search(
            r"Build complete: (\d+) module\(s\)", capsys.readouterr().out
        )
        assert built is not None
        assert report["modules"] == int(built.group(1))

    def test_crlf_copies_still_count_as_the_templates(
        self, cli: S0maCLI, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """A checkout that turned LF into CRLF is not read as an edit.

        What the command writes is LF on every platform, and the paths it
        reports are POSIX.
        """
        target = tmp_path / "crlf"
        assert cli.run(_step_argv(target, 3)) == EXIT_SUCCESS
        for path in list((target / "src").rglob("*.s0ma")) + [
            target / "bootstrap" / "main.py"
        ]:
            path.write_bytes(path.read_bytes().replace(b"\n", b"\r\n"))

        rc, report = _run_json(cli, _step_argv(target, 3), capsys)
        assert rc == EXIT_SUCCESS
        assert report["unchanged"] is True

        rc, report = _run_json(cli, _step_argv(target, 4), capsys)
        assert rc == EXIT_SUCCESS, report
        assert "bootstrap/main.py" in report["files_written"]
        assert report["files_kept"] == []
        for relpath in report["files_written"]:
            assert "\\" not in relpath
            data = target.joinpath(*relpath.split("/")).read_bytes()
            assert b"\r" not in data, relpath


# ---------------------------------------------------------------------------
# A new project is clean, and carries a launch entry for studi0
# ---------------------------------------------------------------------------

#: Every way ``s0ma new project`` makes a project: no template, then each
#: template it offers.
_EVERY_SCAFFOLD: tuple[str | None, ...] = (None, *TEMPLATE_CHOICES)

#: A diagnostic line, at any severity: ``<file>:<line>: <SEVERITY> [<CODE>]``.
_DIAGNOSTIC_LINE = re.compile(r":\d+: [A-Z]+ \[[A-Z0-9_]+\]")

#: The exact bytes of ``.claude/launch.json``.
_LAUNCH_JSON = (
    "{\n"
    '  "version": "0.0.1",\n'
    '  "configurations": [\n'
    "    {\n"
    '      "name": "studi0",\n'
    '      "url": "http://studi0.localhost:5710",\n'
    '      "port": 5710\n'
    "    }\n"
    "  ]\n"
    "}\n"
)

_LAUNCH_PARTS = (".claude", "launch.json")


def _new_project_argv(target: Path, template: str | None) -> list[str]:
    argv = ["new", "project", str(target), "--quiet"]
    if template is not None:
        argv += ["--template", template]
    return argv


class TestFreshProjectIsClean:
    """A new project's first commands print no diagnostic at all.

    The created ``[project]`` table names the runtime the generated Python
    imports, so the build has no ``HOST_RUNTIME_UNDECLARED`` to report; the
    sources were already clean. Checked for every scaffold, in both check
    modes, then through a build and a test run.
    """

    @pytest.mark.parametrize("template", _EVERY_SCAFFOLD)
    def test_check_build_and_test_print_no_diagnostic(
        self,
        cli: S0maCLI,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
        template: str | None,
    ) -> None:
        target = tmp_path / f"{template or 'plain'}-clean"
        assert cli.run(_new_project_argv(target, template)) == EXIT_SUCCESS
        capsys.readouterr()

        root = ["--project-root", str(target)]
        for argv in (
            [*root, "check"],
            [*root, "check", "--mode", "release"],
            [*root, "build", str(target)],
            [*root, "test"],
        ):
            assert cli.run(argv) == EXIT_SUCCESS, argv
            captured = capsys.readouterr()
            printed = captured.out + captured.err
            assert _DIAGNOSTIC_LINE.findall(printed) == [], (argv, printed)
            assert "HOST_RUNTIME_UNDECLARED" not in printed, argv

    @pytest.mark.parametrize("template", _EVERY_SCAFFOLD)
    def test_the_created_pyproject_names_the_runtime(
        self, cli: S0maCLI, tmp_path: Path, template: str | None
    ) -> None:
        import tomllib

        target = tmp_path / f"{template or 'plain'}-deps"
        assert cli.run(_new_project_argv(target, template)) == EXIT_SUCCESS

        text = (target / "pyproject.toml").read_text(encoding="utf-8")
        # Bare names, no version floor, inside [project] and before the
        # s0ma table.
        line = 'dependencies = ["s0ma-lang-core", "s0ma-lang-dsl"]\n'
        assert line in text
        assert text.index(line) < text.index("[tool.s0ma]")
        data = tomllib.loads(text)
        assert data["project"]["dependencies"] == ["s0ma-lang-core", "s0ma-lang-dsl"]

    @pytest.mark.parametrize("template", _EVERY_SCAFFOLD)
    def test_an_existing_pyproject_keeps_its_bytes(
        self, cli: S0maCLI, tmp_path: Path, template: str | None
    ) -> None:
        """The append path adds the s0ma table and nothing else: a
        ``[project]`` table the person already has is not edited, so it
        gains no dependency line."""
        target = tmp_path / f"{template or 'plain'}-keep"
        target.mkdir()
        original = b'[project]\r\nname = "keeper"\r\nversion = "1.0.0"\r\n'
        (target / "pyproject.toml").write_bytes(original)

        assert cli.run(_new_project_argv(target, template)) == EXIT_SUCCESS

        written = (target / "pyproject.toml").read_bytes()
        assert written.startswith(original)
        assert b"dependencies" not in written
        assert written[len(original):].startswith(b"\n[tool.s0ma]\n")


class TestLaunchConfig:
    """``.claude/launch.json``: the Claude Desktop app's entry for studi0.

    One configuration with a ``url`` and no command, so the app attaches to
    a studi0 already running and starts nothing. Like the feedback skill it
    is a file in the user's client configuration: created only when absent,
    never part of the atomic refusal, and listed in the summary either way.
    """

    @pytest.mark.parametrize("template", _EVERY_SCAFFOLD)
    def test_the_bytes_are_exact(
        self, cli: S0maCLI, tmp_path: Path, template: str | None
    ) -> None:
        target = tmp_path / f"{template or 'plain'}-launch"
        assert cli.run(_new_project_argv(target, template)) == EXIT_SUCCESS

        assert target.joinpath(*_LAUNCH_PARTS).read_bytes() == (
            _LAUNCH_JSON.encode("ascii")
        )

    def test_the_entry_starts_nothing_and_its_port_is_the_urls(self) -> None:
        from urllib.parse import urlsplit

        from s0ma_dsl.cli import new_project

        (entry,) = json.loads(new_project._launch_config_json())["configurations"]
        assert set(entry) == {"name", "url", "port"}
        parts = urlsplit(entry["url"])
        assert parts.path == ""
        assert parts.port == entry["port"]

    @pytest.mark.parametrize("template", _EVERY_SCAFFOLD)
    def test_an_existing_file_is_kept_and_never_causes_a_refusal(
        self,
        cli: S0maCLI,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
        template: str | None,
    ) -> None:
        target = tmp_path / f"{template or 'plain'}-mine"
        launch_path = target.joinpath(*_LAUNCH_PARTS)
        launch_path.parent.mkdir(parents=True)
        mine = b'{"version": "0.0.1", "configurations": []}\r\n'
        launch_path.write_bytes(mine)

        argv = ["new", "project", str(target), "--format", "json"]
        if template is not None:
            argv += ["--template", template]
        assert cli.run(argv) == EXIT_SUCCESS

        report = json.loads(capsys.readouterr().out)
        assert report["launch_config"] == {
            "path": str(launch_path),
            "created": False,
        }
        assert launch_path.read_bytes() == mine

    @pytest.mark.parametrize("template", _EVERY_SCAFFOLD)
    def test_the_summary_lists_it(
        self,
        cli: S0maCLI,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
        template: str | None,
    ) -> None:
        target = tmp_path / f"{template or 'plain'}-listed"
        argv = ["new", "project", str(target)]
        if template is not None:
            argv += ["--template", template]
        assert cli.run(argv) == EXIT_SUCCESS

        out = capsys.readouterr().out
        assert (
            "  .claude/launch.json     opens studi0 beside the chat "
            "(Claude Desktop app)\n"
        ) in out


class TestFeedbackSkillWithNoKey:
    """What the skill says when the tool reports no license key."""

    def test_it_points_to_the_public_issue_tracker(self) -> None:
        from s0ma_dsl.cli import new_project

        skill = " ".join(new_project._feedback_skill_md().split())
        assert "https://github.com/kn0w-thyself/s0ma/issues" in skill
        assert (
            "If the tool says this machine is not set up to send feedback, "
            "there are two cases and you cannot tell which, so say both "
            "briefly."
        ) in skill
        # A user with a key only has to enroll; the tracker is for no key.
        assert (
            "With a s0ma license key, the command the tool names connects "
            "this machine, and the user runs it in a terminal."
        ) in skill
        assert "With no license key, the feedback channel cannot take this report" in skill
        assert "an issue there is public" in skill
        assert "never paste the drafted report into an issue yourself" in skill
        assert "Do not look for a key file, and never read or ask for a key." in skill
