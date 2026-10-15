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
import subprocess
import sys
from typing import TYPE_CHECKING

import pytest

from s0ma_dsl.cli.main import (
    EXIT_SUCCESS,
    EXIT_USAGE_ERROR,
    EXIT_VALIDATION_ERROR,
    S0maCLI,
)

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
# STD-M7: --template archetypes (service / library / cli)
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
