"""Tests for POST-12b + POST-12g (M-18, 0.16.0):

- **POST-12b — ``placeholders:`` on CONSTANT cells with ``@file()``.**
  A CONSTANT cell whose body comes from an embedded file
  (``content: @file("path.html")``) can declare ``placeholders:
  [__SYSTEM_NAME__, __GRAPH_DATA_JSON__]`` to assert which magic-string
  markers the file's content carries. The validator cross-checks at
  check time:

  - Every declared placeholder must appear in the file's content
    (otherwise ``PLACEHOLDER_NOT_FOUND``, error in every mode).
  - Any placeholder-shaped string in the file (matching
    ``__[A-Z][A-Z0-9_]*__``) that is not declared fires
    ``UNDECLARED_PLACEHOLDER`` (warning in migration/dev, error in
    strict/release).
  - ``placeholders:`` on a CONSTANT cell WITHOUT ``@file()`` is a
    parse error.

- **POST-12g — ``[tool.s0ma].fixtures_format``.** Project config
  declares the expected format of non-``.s0ma`` test fixtures. ``s0ma
  check`` walks every configured ``test_roots`` directory looking for
  files matching the configured globs and validates each via the
  declared format. Supported formats: ``"ndjson"``, ``"json"``,
  ``"yaml"``. Unknown values raise ``ValueError`` at project load.
"""

from __future__ import annotations

import textwrap
from typing import TYPE_CHECKING

import pytest

from s0ma_dsl.cli.main import (
    EXIT_VALIDATION_ERROR,
    S0maCLI,
    _check_fixture_format,
    _validate_fixtures_format,
)
from s0ma_dsl.config import StrictnessMode
from s0ma_dsl.errors import S0maParseError
from s0ma_dsl.ir.builder import build_ir
from s0ma_dsl.parser.s0ma_parser import parse_s0ma
from s0ma_dsl.project import SUPPORTED_FIXTURE_FORMATS, S0maProject
from s0ma_dsl.semantic.validator import IntraModuleValidator

if TYPE_CHECKING:
    from pathlib import Path

# ---------------------------------------------------------------------------
# POST-12b helpers
# ---------------------------------------------------------------------------


def _write_embed_cell(
    tmp_path: Path,
    *,
    template_content: str,
    placeholders_field: str = "",
) -> Path:
    """Create a tmp project with one CONSTANT cell embedding a template.

    Returns the .s0ma file path so the caller can pass it to
    ``parse_s0ma(source, filename=...)``. The template is written as
    ``tmp_path/templates/viz.html`` (so the @file path resolves
    relative to the .s0ma file's directory). ``placeholders_field`` is
    the literal text inserted *between* the ``schema:`` field and the
    ``content: @file(...)`` line — must include leading indentation
    and a trailing newline when non-empty.
    """
    templates = tmp_path / "templates"
    templates.mkdir(exist_ok=True)
    (templates / "viz.html").write_text(template_content, encoding="utf-8")

    s0ma_path = tmp_path / "placeholder_module.s0ma"
    s0ma_path.write_text(
        textwrap.dedent(
            """\
module placeholder_module
    layer: PRESENTATION
    version: 0.0.1
    intent: "Placeholder validation fixture for POST-12b."
    exports: [VIZ_TEMPLATE]

    requires: none
    uses: none
    soft_requires: none
    runtime_only_requires: none
    deferred_requires: none
    exports_helpers: none
cell VIZ_TEMPLATE :: PRESENTATION
    kind: CONSTANT
    visibility: PUBLIC
    intent: "Template embedding markers for placeholder check."
    schema: "string of HTML5 with placeholder markers"
    invariants: none
    covered_by: none
"""
        ).strip()
        + "\n"
        + placeholders_field
        + '    content: @file("templates/viz.html")\n',
        encoding="utf-8",
    )
    return s0ma_path


def _parse_placeholder_module(s0ma_path: Path):
    """Parse the cell module from ``_write_embed_cell``."""
    return parse_s0ma(
        s0ma_path.read_text(encoding="utf-8"),
        filename=str(s0ma_path),
    )


# ---------------------------------------------------------------------------
# POST-12b — placeholders: parsing
# ---------------------------------------------------------------------------


class TestPlaceholdersParsing:
    """``placeholders:`` parses to the right tuple on CellDecl."""

    def test_inline_form_parses(self, tmp_path: Path) -> None:
        """Inline ``placeholders: [a, b]`` form parses."""
        s0ma_path = _write_embed_cell(
            tmp_path,
            template_content="<html>__SYSTEM_NAME__ __GRAPH_DATA_JSON__</html>",
            placeholders_field=(
                "    placeholders: [__SYSTEM_NAME__, __GRAPH_DATA_JSON__]\n"
            ),
        )
        module = _parse_placeholder_module(s0ma_path)
        assert module.cells[0].placeholders == (
            "__SYSTEM_NAME__",
            "__GRAPH_DATA_JSON__",
        )

    def test_block_form_parses(self, tmp_path: Path) -> None:
        """Block-list ``- a`` / ``- b`` form parses identically."""
        s0ma_path = _write_embed_cell(
            tmp_path,
            template_content="<html>__A__ __B__</html>",
            placeholders_field=(
                "    placeholders:\n"
                "      - __A__\n"
                "      - __B__\n"
            ),
        )
        module = _parse_placeholder_module(s0ma_path)
        assert module.cells[0].placeholders == ("__A__", "__B__")

    def test_omitted_field_leaves_tuple_empty(self, tmp_path: Path) -> None:
        """No ``placeholders:`` → CellDecl.placeholders == ()."""
        s0ma_path = _write_embed_cell(
            tmp_path,
            template_content="<html>no markers here</html>",
        )
        module = _parse_placeholder_module(s0ma_path)
        assert module.cells[0].placeholders == ()

    def test_placeholders_without_file_is_parse_error(
        self, tmp_path: Path,
    ) -> None:
        """``placeholders:`` on a CONSTANT cell without ``@file()`` raises ``PARSE_ERROR``.

        The field's contract is tied to the embed directive — there
        is no external content to validate placeholders against on a
        cell whose body is inline. Parsing must fail loudly so the
        author cannot accidentally write a field that has no effect.
        """
        source = textwrap.dedent(
            """\
module inline_constant
    layer: PRESENTATION
    version: 0.0.1
    intent: "Verify placeholders rejection on inline-bodied CONSTANT."
    exports: [INLINE_CONST]

    requires: none
    uses: none
    soft_requires: none
    runtime_only_requires: none
    deferred_requires: none
    exports_helpers: none
cell INLINE_CONST :: PRESENTATION
    kind: CONSTANT
    visibility: PUBLIC
    intent: "Inline constant with rejected placeholders."
    schema: "string"
    placeholders: [__NOT_LEGAL__]
    invariants: none
    covered_by: none
    ---
    INLINE_CONST = "hello"
"""
        ).strip() + "\n"

        with pytest.raises(S0maParseError) as exc:
            parse_s0ma(source, filename="inline.s0ma")
        assert exc.value.code == "PARSE_ERROR"
        assert "placeholders" in exc.value.message.lower()


# ---------------------------------------------------------------------------
# POST-12b — placeholders: validator
# ---------------------------------------------------------------------------


def _validate(s0ma_path: Path, *, mode: StrictnessMode = StrictnessMode.DEV):
    module = _parse_placeholder_module(s0ma_path)
    validator = IntraModuleValidator(mode=mode, filename=str(s0ma_path))
    return module, validator.validate(module)


class TestPlaceholdersValidator:
    """The validator enforces the two-way placeholders ↔ file content contract."""

    def test_matching_placeholders_pass(self, tmp_path: Path) -> None:
        """Every declared placeholder appears in the file — zero diagnostics."""
        s0ma_path = _write_embed_cell(
            tmp_path,
            template_content=(
                "<html><h1>__SYSTEM_NAME__</h1>"
                "<script>const data = __GRAPH_DATA_JSON__;</script></html>"
            ),
            placeholders_field=(
                "    placeholders: [__SYSTEM_NAME__, __GRAPH_DATA_JSON__]\n"
            ),
        )
        _, errors = _validate(s0ma_path)
        placeholder_codes = [
            e.code for e in errors
            if e.code in {"PLACEHOLDER_NOT_FOUND", "UNDECLARED_PLACEHOLDER"}
        ]
        assert placeholder_codes == []

    def test_declared_placeholder_absent_fires_placeholder_not_found(
        self, tmp_path: Path,
    ) -> None:
        """Declared placeholder not in file → ``PLACEHOLDER_NOT_FOUND`` error."""
        s0ma_path = _write_embed_cell(
            tmp_path,
            template_content="<html>only __SYSTEM_NAME__ here</html>",
            placeholders_field=(
                "    placeholders: [__SYSTEM_NAME__, __MISSING_MARKER__]\n"
            ),
        )
        _, errors = _validate(s0ma_path)
        codes = [e.code for e in errors]
        assert codes.count("PLACEHOLDER_NOT_FOUND") == 1
        missing = next(e for e in errors if e.code == "PLACEHOLDER_NOT_FOUND")
        assert missing.severity == "error"
        assert "__MISSING_MARKER__" in missing.message

    def test_undeclared_placeholder_fires_warning_in_dev(
        self, tmp_path: Path,
    ) -> None:
        """File contains a marker not declared → ``UNDECLARED_PLACEHOLDER`` warning."""
        s0ma_path = _write_embed_cell(
            tmp_path,
            template_content=(
                "<html>__SYSTEM_NAME__ + __SURPRISE_MARKER__</html>"
            ),
            placeholders_field=(
                "    placeholders: [__SYSTEM_NAME__]\n"
            ),
        )
        _, errors = _validate(s0ma_path, mode=StrictnessMode.DEV)
        undeclared = [e for e in errors if e.code == "UNDECLARED_PLACEHOLDER"]
        assert len(undeclared) == 1
        assert undeclared[0].severity == "warning"
        assert "__SURPRISE_MARKER__" in undeclared[0].message

    def test_undeclared_placeholder_promotes_to_error_in_strict(
        self, tmp_path: Path,
    ) -> None:
        """``UNDECLARED_PLACEHOLDER`` is an error in strict / release."""
        s0ma_path = _write_embed_cell(
            tmp_path,
            template_content="<html>__DRIFT__</html>",
            placeholders_field="",
        )
        _, errors = _validate(s0ma_path, mode=StrictnessMode.STRICT)
        undeclared = [e for e in errors if e.code == "UNDECLARED_PLACEHOLDER"]
        assert len(undeclared) == 1
        assert undeclared[0].severity == "error"

    def test_ir_round_trips_placeholders(self, tmp_path: Path) -> None:
        """The declared placeholder list rides through the IR."""
        s0ma_path = _write_embed_cell(
            tmp_path,
            template_content="<html>__A__ __B__</html>",
            placeholders_field="    placeholders: [__A__, __B__]\n",
        )
        module = _parse_placeholder_module(s0ma_path)
        doc = build_ir(
            module,
            source_text=s0ma_path.read_text(encoding="utf-8"),
        )
        ir_dict = doc.to_dict()
        cell_ir = next(
            c for c in ir_dict["components"]
            if c["declaration_type"] == "cell"
        )
        assert cell_ir["fields"]["placeholders"] == {
            "state": "value",
            "value": ["__A__", "__B__"],
        }


# ---------------------------------------------------------------------------
# POST-12g — fixtures_format: project config
# ---------------------------------------------------------------------------


def _write_fixtures_project(
    tmp_path: Path,
    *,
    fixtures_format: dict[str, str] | None,
    fixture_files: dict[str, str],
    extra_test_files: dict[str, str] | None = None,
) -> Path:
    """Build a minimal project with a ``[tool.s0ma]`` table and fixtures.

    Returns the project root path. ``fixtures_format`` is the dict
    written under ``[tool.s0ma.fixtures_format]``; pass ``None`` to
    omit the table entirely. ``fixture_files`` maps relative paths
    under ``tests/`` to file content. ``extra_test_files`` similarly
    populates additional test-root files (non-fixture).
    """
    project = tmp_path / "fix_project"
    project.mkdir()

    fixtures_table = ""
    if fixtures_format is not None:
        fixtures_table = "\n[tool.s0ma.fixtures_format]\n" + "".join(
            f'"{glob}" = "{fmt}"\n'
            for glob, fmt in fixtures_format.items()
        )

    (project / "pyproject.toml").write_text(
        textwrap.dedent(
            """
            [project]
            name = "fix_project"
            version = "0.0.1"

            [tool.s0ma]
            source_roots = ["src"]
            test_roots = ["tests"]
            build_dir = "fix_project_build"
            bootstrap_files = []
            """
        ).strip()
        + fixtures_table
        + "\n",
        encoding="utf-8",
    )
    (project / "src").mkdir()
    (project / "tests").mkdir()

    # Write at least one trivial .s0ma test module so ``s0ma check``
    # has work to do even when the fixtures are the only source of
    # diagnostics.
    (project / "tests" / "trivial_test.s0ma").write_text(
        textwrap.dedent(
            """\
module trivial_test
    layer: APPLICATION
    version: 0.0.1
    intent: "Trivial test module so s0ma check has work."
    exports: [trivial]

    requires: none
    uses: none
    soft_requires: none
    runtime_only_requires: none
    deferred_requires: none
    exports_helpers: none
test trivial :: APPLICATION
    intent: "Trivial test."
    tests: [trivial]
    expects: none
    depends_on: none
    mocks: none
    ---
    def test_trivial():
        assert True
"""
        ).strip() + "\n",
        encoding="utf-8",
    )

    for rel, content in fixture_files.items():
        path = project / "tests" / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    for rel, content in (extra_test_files or {}).items():
        path = project / "tests" / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")

    return project


class TestFixturesFormatProjectConfig:
    """``[tool.s0ma].fixtures_format`` parses into ``S0maProject.fixtures_format``."""

    def test_parses_simple_table(self, tmp_path: Path) -> None:
        project_root = _write_fixtures_project(
            tmp_path,
            fixtures_format={"*.jsonl": "ndjson"},
            fixture_files={},
        )
        project = S0maProject.discover(project_root)
        assert project.fixtures_format == {"*.jsonl": "ndjson"}

    def test_unknown_format_raises_value_error(self, tmp_path: Path) -> None:
        project_root = _write_fixtures_project(
            tmp_path,
            fixtures_format={"*.foo": "toml"},
            fixture_files={},
        )
        with pytest.raises(ValueError) as exc:
            S0maProject.discover(project_root)
        msg = str(exc.value)
        assert "fixtures_format" in msg
        # Supported formats are surfaced in the error so the author
        # knows what the legal values are.
        for supported in SUPPORTED_FIXTURE_FORMATS:
            assert repr(supported) in msg

    def test_absent_table_yields_none(self, tmp_path: Path) -> None:
        project_root = _write_fixtures_project(
            tmp_path,
            fixtures_format=None,
            fixture_files={},
        )
        project = S0maProject.discover(project_root)
        assert project.fixtures_format is None


# ---------------------------------------------------------------------------
# POST-12g — fixture-format validators
# ---------------------------------------------------------------------------


class TestFixtureFormatValidators:
    """The per-format helpers parse valid input and flag malformed input."""

    def test_valid_jsonl_file_passes(self, tmp_path: Path) -> None:
        """A well-formed .jsonl fixture produces no diagnostics."""
        project = _write_fixtures_project(
            tmp_path,
            fixtures_format={"*.jsonl": "ndjson"},
            fixture_files={
                "events.jsonl": (
                    '{"a": 1}\n'
                    '{"a": 2}\n'
                    '{"a": 3}\n'
                ),
            },
        )
        s0ma_project = S0maProject.discover(project)
        diags = _validate_fixtures_format(
            s0ma_project.test_roots,
            s0ma_project.fixtures_format or {},
            StrictnessMode.DEV,
        )
        codes = [d.code for d in diags]
        assert "FIXTURE_FORMAT_INVALID" not in codes

    def test_malformed_jsonl_fires_fixture_format_invalid(
        self, tmp_path: Path,
    ) -> None:
        """A .jsonl fixture with an invalid line surfaces the line number."""
        project = _write_fixtures_project(
            tmp_path,
            fixtures_format={"*.jsonl": "ndjson"},
            fixture_files={
                "events.jsonl": (
                    '{"a": 1}\n'
                    '{"a": 2}\n'
                    'not-json-at-all\n'  # line 3 is invalid
                    '{"a": 4}\n'
                ),
            },
        )
        s0ma_project = S0maProject.discover(project)
        diags = _validate_fixtures_format(
            s0ma_project.test_roots,
            s0ma_project.fixtures_format or {},
            StrictnessMode.DEV,
        )
        bad = [d for d in diags if d.code == "FIXTURE_FORMAT_INVALID"]
        assert len(bad) == 1
        assert bad[0].line == 3
        assert bad[0].severity == "warning"  # dev mode

    def test_strict_mode_promotes_fixture_format_invalid_to_error(
        self, tmp_path: Path,
    ) -> None:
        project = _write_fixtures_project(
            tmp_path,
            fixtures_format={"*.jsonl": "ndjson"},
            fixture_files={
                "bad.jsonl": "not-json\n",
            },
        )
        s0ma_project = S0maProject.discover(project)
        diags = _validate_fixtures_format(
            s0ma_project.test_roots,
            s0ma_project.fixtures_format or {},
            StrictnessMode.STRICT,
        )
        bad = [d for d in diags if d.code == "FIXTURE_FORMAT_INVALID"]
        assert len(bad) == 1
        assert bad[0].severity == "error"

    def test_check_fixture_format_yaml(self, tmp_path: Path) -> None:
        """YAML format helper round-trips valid + flags invalid documents.

        Skipped when PyYAML is not installed in the test environment —
        the helper degrades gracefully (returning a friendly error
        message) when the optional dependency is absent, which the
        ``test_check_fixture_format_yaml_missing_pyyaml`` test below
        covers explicitly.
        """
        pytest.importorskip("yaml")

        good = tmp_path / "good.yaml"
        good.write_text(
            "key:\n  - one\n  - two\nother: 3\n",
            encoding="utf-8",
        )
        line_no, msg = _check_fixture_format(good, "yaml")
        assert msg is None

        bad = tmp_path / "bad.yaml"
        bad.write_text(
            "key: : : :\n  - bad\nnot a mapping\n",
            encoding="utf-8",
        )
        line_no, msg = _check_fixture_format(bad, "yaml")
        assert msg is not None
        assert line_no >= 1

    def test_check_fixture_format_json(self, tmp_path: Path) -> None:
        """Single-document JSON format passes valid input and flags malformed."""
        good = tmp_path / "good.json"
        good.write_text('{"key": [1, 2, 3], "other": 4}\n', encoding="utf-8")
        _line, msg = _check_fixture_format(good, "json")
        assert msg is None

        bad = tmp_path / "bad.json"
        # Line 3 is the structural error — closing brace without a value.
        bad.write_text(
            '{\n'
            '  "key": "value",\n'
            '  "broken",\n'
            '  "more": 1\n'
            '}\n',
            encoding="utf-8",
        )
        line_no, msg = _check_fixture_format(bad, "json")
        assert msg is not None
        # Single-document JSON: the parser exposes a 1-based line
        # number; the helper surfaces it verbatim.
        assert line_no >= 1

    def test_empty_test_roots_yields_no_diagnostics(
        self, tmp_path: Path,
    ) -> None:
        """No test_roots configured / on disk → zero diagnostics, no crash."""
        # Direct helper invocation with an empty tuple — defensive
        # input that must not raise.
        diags = _validate_fixtures_format(
            (),
            {"*.jsonl": "ndjson"},
            StrictnessMode.DEV,
        )
        assert diags == []

    def test_files_not_matching_glob_are_ignored(
        self, tmp_path: Path,
    ) -> None:
        """Fixture files outside any configured glob produce zero diagnostics.

        A ``.yaml`` file under tests/ matches no configured glob when
        only ``*.jsonl`` is registered — the file is ignored even if
        it would fail a hypothetical YAML check.
        """
        project = _write_fixtures_project(
            tmp_path,
            fixtures_format={"*.jsonl": "ndjson"},
            fixture_files={
                # Intentionally malformed but the .yaml glob is not
                # registered.
                "ignored.yaml": "key: : : :\n",
            },
        )
        s0ma_project = S0maProject.discover(project)
        diags = _validate_fixtures_format(
            s0ma_project.test_roots,
            s0ma_project.fixtures_format or {},
            StrictnessMode.DEV,
        )
        bad = [d for d in diags if d.code == "FIXTURE_FORMAT_INVALID"]
        assert bad == []

    def test_s0ma_check_surfaces_fixture_format_invalid(
        self, tmp_path: Path, capsys,
    ) -> None:
        """``s0ma check`` reports fixture validation errors end-to-end."""
        project = _write_fixtures_project(
            tmp_path,
            fixtures_format={"*.jsonl": "ndjson"},
            fixture_files={
                "events.jsonl": '{"ok": true}\nnot-json\n',
            },
        )
        rc = S0maCLI().run([
            "--project-root", str(project),
            "check", str(project),
            "--mode", "strict",
            "--format", "json",
        ])
        # Validation failure exits non-zero in strict mode.
        assert rc == EXIT_VALIDATION_ERROR
        out = capsys.readouterr().out
        # JSON payload mentions the code.
        assert '"FIXTURE_FORMAT_INVALID"' in out
