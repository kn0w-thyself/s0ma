"""Tests for M-14 (POST-10d/e/f/g) — Validator improvements round 2.

Four independent validator-surface fixes bundled in 0.16.0:

* **POST-10d** — ``MODULE_NAME_COLLISION`` diagnostic now suggests a
  descriptive suffix (e.g. ``foo_unit``, ``unit_foo``, ``foo_lib``)
  rather than the generic "rename one of the modules". When the
  colliding files live under a configured ``test_roots`` directory,
  the hint also surfaces the new
  ``[tool.s0ma].test_module_name_prefix_by_dir`` opt-in flag.

* **POST-10e** — ``s0ma check`` walks across multiple .s0ma files
  now runs project-level invariants (e.g. ``MODULE_NAME_COLLISION``
  across the file set) so the discovery loop is the same as
  ``s0ma build``. A single-file invocation does not engage the
  cross-module checks — they require ≥2 modules by definition.

* **POST-10f** — ``BARE_IMPORT`` remediation text is context-aware:
  it tells the author "this name is already declared in ``uses:``"
  when applicable, or "did you mean to add ``<name>`` to
  ``requires:``?" otherwise.

* **POST-10g** — A new ``REQUIRES_DOTTED_LOWERCASE_HINT`` validator
  warning fires when a ``requires:`` entry like ``uuid.uuid4`` is
  authored in dotted form but its last segment is lowercase (the
  parser's UPPER_CASE heuristic misses these), and the body
  references the lowercase last segment as a bare identifier. The
  remediation suggests the colon-override shape ``uuid:uuid4``.

Each ``TestPOST10*`` group reads top-to-bottom as the contract the
corresponding sub-fix promises.
"""

from __future__ import annotations

import os
from contextlib import contextmanager
from pathlib import Path
from textwrap import dedent
from typing import TYPE_CHECKING

import pytest

from s0ma_dsl.cli.main import (
    EXIT_SUCCESS,
    EXIT_VALIDATION_ERROR,
    S0maCLI,
)
from s0ma_dsl.config import StrictnessMode
from s0ma_dsl.parser.s0ma_parser import parse_s0ma_with_warnings
from s0ma_dsl.project import S0maProject
from s0ma_dsl.semantic.validator import validate_module

if TYPE_CHECKING:
    from collections.abc import Iterator

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


@pytest.fixture()
def cli() -> S0maCLI:
    return S0maCLI()


@contextmanager
def _chdir(target: Path) -> Iterator[None]:
    prev = Path.cwd()
    try:
        os.chdir(target)
        yield
    finally:
        os.chdir(prev)


_VALID_SOURCE_S0MA = """\
module {name}
    layer: DOMAIN
    version: 0.1.0
    intent: "Round-2 fixtures — production-side module."
    exports: [do_{name}]
    requires: none
    uses: none
    soft_requires: none
    runtime_only_requires: none
    deferred_requires: none
    exports_helpers: none

nerve do_{name} :: DOMAIN
    kind: FUNCTION
    visibility: PUBLIC
    intent: "A simple function for round-2 coverage."
    expects: "none"
    guarantees: "Returns a string"
    forbids: none
    evaluates_at: FUNCTION_BOUNDARY
    provides: none
    returns: none
    raises: none
    interface: none
    latency_ms: none
    depends_on: none
    internal: none
    expected_exceptions: none
    consumes_via_dict: none
    declares_attributes: none
    covered_by: none
    ---
    def do_{name}() -> str:
        return "{name}"
"""


def _write_pyproject(
    root: Path,
    *,
    project_name: str = "round2_proj",
    source_roots: list[str] | None = None,
    test_roots: list[str] | None = None,
    test_module_name_prefix_by_dir: bool | None = None,
) -> Path:
    body = dedent(f"""
        [project]
        name = "{project_name}"
        version = "0.1.0"

        [tool.s0ma]
    """).lstrip()
    if source_roots is not None:
        body += f"source_roots = {source_roots!r}\n"
    if test_roots is not None:
        body += f"test_roots = {test_roots!r}\n"
    if test_module_name_prefix_by_dir is not None:
        body += (
            f"test_module_name_prefix_by_dir = "
            f"{'true' if test_module_name_prefix_by_dir else 'false'}\n"
        )
    pyproject = root / "pyproject.toml"
    pyproject.write_text(body, encoding="utf-8")
    return pyproject


# ===========================================================================
# POST-10d — MODULE_NAME_COLLISION descriptive-suffix hint
# ===========================================================================


class TestPOST10dCollisionHint:
    """Two source files declaring the same `module <name>` fire
    ``MODULE_NAME_COLLISION`` with a descriptive-suffix steering hint."""

    def test_collision_fires_with_descriptive_suffix_suggestion(
        self,
        cli: S0maCLI,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ):
        """Two ``.s0ma`` files declaring ``module foo`` in different
        subdirs of ``tests/`` fire ``MODULE_NAME_COLLISION``. The
        diagnostic's remediation now names a descriptive-suffix
        candidate (e.g. ``foo_unit`` / ``unit_foo``) rather than the
        generic pre-0.16.0 ``"Rename one of the modules"`` message.
        """
        root = tmp_path / "proj"
        root.mkdir()
        tests = root / "tests"
        unit = tests / "unit"
        integration = tests / "integration"
        for d in (tests, unit, integration):
            d.mkdir()
        _write_pyproject(
            root, source_roots=[], test_roots=["tests"],
        )
        (unit / "foo.s0ma").write_text(
            _VALID_SOURCE_S0MA.format(name="foo"), encoding="utf-8"
        )
        (integration / "foo.s0ma").write_text(
            _VALID_SOURCE_S0MA.format(name="foo"), encoding="utf-8"
        )
        with _chdir(root):
            exit_code = cli.run(["check", "--mode", "dev"])
        assert exit_code == EXIT_VALIDATION_ERROR
        captured = capsys.readouterr()
        assert "MODULE_NAME_COLLISION" in captured.out
        # The descriptive-suffix hint must surface in either the
        # remediation or message body.
        combined = captured.out
        assert (
            "foo_unit" in combined
            or "foo_integration" in combined
            or "unit_foo" in combined
            or "integration_foo" in combined
        ), (
            "Expected a descriptive-suffix hint "
            "(foo_unit / foo_integration / unit_foo / integration_foo) "
            f"in the diagnostic; got:\n{combined}"
        )

    def test_collision_hint_mentions_prefix_by_dir_opt_in_when_under_tests(
        self,
        cli: S0maCLI,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ):
        """When a colliding file lives under a configured test root and
        the project has not opted in to
        ``test_module_name_prefix_by_dir``, the remediation surfaces
        the opt-in flag as an alternative to a hand-rename."""
        root = tmp_path / "proj"
        root.mkdir()
        tests = root / "tests"
        tests.mkdir()
        unit = tests / "unit"
        unit.mkdir()
        _write_pyproject(
            root, source_roots=[], test_roots=["tests"],
        )
        (tests / "foo.s0ma").write_text(
            _VALID_SOURCE_S0MA.format(name="foo"), encoding="utf-8"
        )
        (unit / "foo.s0ma").write_text(
            _VALID_SOURCE_S0MA.format(name="foo"), encoding="utf-8"
        )
        with _chdir(root):
            cli.run(["check", "--mode", "dev"])
        captured = capsys.readouterr()
        assert "test_module_name_prefix_by_dir" in captured.out, (
            "Expected the diagnostic to surface the opt-in flag; got:\n"
            f"{captured.out}"
        )

    def test_test_module_name_prefix_by_dir_true_resolves_collision(
        self,
        cli: S0maCLI,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ):
        """With ``test_module_name_prefix_by_dir = true``, two
        ``module foo`` declarations in different test subdirs are
        treated as distinct effective names
        (``unit_foo`` / ``integration_foo``) and no collision fires."""
        root = tmp_path / "proj"
        root.mkdir()
        tests = root / "tests"
        unit = tests / "unit"
        integration = tests / "integration"
        for d in (tests, unit, integration):
            d.mkdir()
        _write_pyproject(
            root,
            source_roots=[],
            test_roots=["tests"],
            test_module_name_prefix_by_dir=True,
        )
        (unit / "foo.s0ma").write_text(
            _VALID_SOURCE_S0MA.format(name="foo"), encoding="utf-8"
        )
        (integration / "foo.s0ma").write_text(
            _VALID_SOURCE_S0MA.format(name="foo"), encoding="utf-8"
        )
        with _chdir(root):
            exit_code = cli.run(["check", "--mode", "dev"])
        captured = capsys.readouterr()
        assert exit_code == EXIT_SUCCESS, (
            f"Expected no collision with prefix_by_dir on; got:\n"
            f"{captured.out}\nstderr: {captured.err}"
        )
        assert "MODULE_NAME_COLLISION" not in captured.out

    def test_prefix_by_dir_does_not_affect_source_root_modules(
        self,
        cli: S0maCLI,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ):
        """Production modules under ``source_roots`` are unaffected by
        ``test_module_name_prefix_by_dir``; they still require unique
        declared names. Two ``module foo`` files in ``src/`` always
        collide regardless of the flag's value."""
        root = tmp_path / "proj"
        root.mkdir()
        src = root / "src"
        a = src / "a"
        b = src / "b"
        for d in (src, a, b):
            d.mkdir()
        _write_pyproject(
            root,
            source_roots=["src"],
            test_roots=[],
            test_module_name_prefix_by_dir=True,
        )
        (a / "foo.s0ma").write_text(
            _VALID_SOURCE_S0MA.format(name="foo"), encoding="utf-8"
        )
        (b / "foo.s0ma").write_text(
            _VALID_SOURCE_S0MA.format(name="foo"), encoding="utf-8"
        )
        with _chdir(root):
            exit_code = cli.run(["check", "--mode", "dev"])
        captured = capsys.readouterr()
        assert exit_code == EXIT_VALIDATION_ERROR
        assert "MODULE_NAME_COLLISION" in captured.out

    def test_project_synthetic_fallback_has_field_default_false(self):
        """``S0maProject.synthetic_fallback`` preserves the default
        ``test_module_name_prefix_by_dir = False`` so a project that
        never declared ``[tool.s0ma]`` continues to use the strict
        pre-0.16.0 collision behaviour."""
        proj = S0maProject.synthetic_fallback("/tmp")
        assert proj.test_module_name_prefix_by_dir is False


# ===========================================================================
# POST-10e — s0ma check tests/ surfaces project-level invariants
# ===========================================================================


class TestPOST10eMultiFileSurfacesProjectInvariants:
    """``s0ma check`` with a multi-file input runs project-level
    invariants (MODULE_NAME_COLLISION) across the file set; a
    single-file invocation does not (no cross-module work to do)."""

    def test_check_directory_with_duplicate_modules_fires_collision(
        self,
        cli: S0maCLI,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ):
        """``s0ma check tests/`` with two files declaring ``module
        foo`` surfaces ``MODULE_NAME_COLLISION`` at check time
        (previously this only surfaced at ``s0ma build``)."""
        root = tmp_path / "proj"
        root.mkdir()
        tests = root / "tests"
        tests.mkdir()
        _write_pyproject(
            root, source_roots=[], test_roots=["tests"],
        )
        (tests / "alpha.s0ma").write_text(
            _VALID_SOURCE_S0MA.format(name="shared"), encoding="utf-8"
        )
        (tests / "beta.s0ma").write_text(
            _VALID_SOURCE_S0MA.format(name="shared"), encoding="utf-8"
        )
        with _chdir(root):
            exit_code = cli.run([
                "check", str(tests), "--mode", "dev",
            ])
        captured = capsys.readouterr()
        assert exit_code == EXIT_VALIDATION_ERROR
        assert "MODULE_NAME_COLLISION" in captured.out

    def test_single_file_check_does_not_trigger_project_invariants(
        self,
        cli: S0maCLI,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ):
        """A single-file invocation parses + intra-module-validates
        only — no cross-module / collision pass fires. This is the
        pre-POST-10e behaviour and POST-10e preserves it."""
        root = tmp_path / "proj"
        root.mkdir()
        src = root / "src"
        src.mkdir()
        _write_pyproject(
            root, source_roots=["src"], test_roots=[],
        )
        (src / "alpha.s0ma").write_text(
            _VALID_SOURCE_S0MA.format(name="alpha"), encoding="utf-8"
        )
        with _chdir(root):
            exit_code = cli.run([
                "check", str(src / "alpha.s0ma"), "--mode", "dev",
            ])
        captured = capsys.readouterr()
        assert exit_code == EXIT_SUCCESS
        assert "MODULE_NAME_COLLISION" not in captured.out

    def test_multi_path_check_aggregates_collision_diagnostic(
        self,
        cli: S0maCLI,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ):
        """``s0ma check src/ tests/`` aggregates per-file findings and
        surfaces the project-level collision in the unified report.
        Closes the discovery-gap that pre-POST-10e left between
        ``s0ma check`` and ``s0ma build``."""
        root = tmp_path / "proj"
        root.mkdir()
        src = root / "src"
        tests = root / "tests"
        for d in (src, tests):
            d.mkdir()
        _write_pyproject(
            root, source_roots=["src"], test_roots=["tests"],
        )
        # Same module name in src/ and tests/ — would silently slip
        # through a per-file pass but the multi-file ``s0ma check``
        # must surface it.
        (src / "shared.s0ma").write_text(
            _VALID_SOURCE_S0MA.format(name="shared"), encoding="utf-8"
        )
        (tests / "shared.s0ma").write_text(
            _VALID_SOURCE_S0MA.format(name="shared"), encoding="utf-8"
        )
        with _chdir(root):
            exit_code = cli.run([
                "check", str(src), str(tests), "--mode", "dev",
            ])
        captured = capsys.readouterr()
        assert exit_code == EXIT_VALIDATION_ERROR
        assert "MODULE_NAME_COLLISION" in captured.out


# ===========================================================================
# POST-10f — BARE_IMPORT remediation text refinement
# ===========================================================================


class TestPOST10fBareImportRemediationRefinement:
    """The body-level ``BARE_IMPORT`` diagnostic's remediation is
    context-aware: the message changes based on whether the imported
    name is already in ``uses:``, ``requires:``, or neither."""

    def test_bare_import_with_name_in_uses_says_remove_the_bare_import(self):
        """When the body imports a name that the module already
        declares in ``uses:``, the remediation explains the duplication
        and asks the author to drop the bare import."""
        source = dedent("""\
module foo
    layer: DOMAIN
    version: 0.1.0
    intent: "Body-import test fixture."
    uses: [other.bar]
    exports: [do_foo]

    requires: none
    soft_requires: none
    runtime_only_requires: none
    deferred_requires: none
    exports_helpers: none
nerve do_foo :: DOMAIN
    kind: FUNCTION
    visibility: PUBLIC
    intent: "Calls bar after a redundant bare import."
    expects: "none"
    guarantees: "Returns bar()'s value"
    forbids: none
    evaluates_at: FUNCTION_BOUNDARY
    provides: none
    returns: none
    raises: none
    interface: none
    latency_ms: none
    depends_on: none
    internal: none
    expected_exceptions: none
    consumes_via_dict: none
    declares_attributes: none
    covered_by: none
    ---
    def do_foo():
        import bar
        return bar()
""").lstrip()
        _, warnings = parse_s0ma_with_warnings(
            source, "foo.s0ma", mode=StrictnessMode.DEV,
        )
        bare = [w for w in warnings if w.code == "BARE_IMPORT"]
        assert bare, f"Expected BARE_IMPORT in warnings; got {warnings}"
        remediation = bare[0].remediation or ""
        assert "already declared in `uses:" in remediation
        assert "delete" in remediation.lower()
        assert "import bar" in remediation
        # Pilot01: sequenced as step 2 of one fix, not a contradiction.
        assert "that half is done" in remediation

    def test_bare_import_unknown_name_suggests_requires(self):
        """When the body imports a name not in ``uses:`` and not in
        ``requires:``, the remediation steers toward ``requires:``."""
        source = dedent("""\
module foo
    layer: DOMAIN
    version: 0.1.0
    intent: "Body-import test fixture — unknown name."
    exports: [do_foo]

    requires: none
    uses: none
    soft_requires: none
    runtime_only_requires: none
    deferred_requires: none
    exports_helpers: none
nerve do_foo :: DOMAIN
    kind: FUNCTION
    visibility: PUBLIC
    intent: "Imports requests directly from the body."
    expects: "none"
    guarantees: "Returns whatever requests.get returns."
    forbids: none
    evaluates_at: FUNCTION_BOUNDARY
    provides: none
    returns: none
    raises: none
    interface: none
    latency_ms: none
    depends_on: none
    internal: none
    expected_exceptions: none
    consumes_via_dict: none
    declares_attributes: none
    covered_by: none
    ---
    def do_foo():
        import requests
        return requests.get("x")
""").lstrip()
        _, warnings = parse_s0ma_with_warnings(
            source, "foo.s0ma", mode=StrictnessMode.DEV,
        )
        bare = [w for w in warnings if w.code == "BARE_IMPORT"]
        assert bare
        remediation = bare[0].remediation or ""
        assert "requires:" in remediation
        assert "requests" in remediation
        # Pilot01: the not-declared variant spells out BOTH parts of
        # the single fix simultaneously (header add + body delete), so
        # a half-compliant agent cannot land in a thrash loop.
        assert "ONE edit" in remediation
        assert "add `requests` to the module header's `requires:` list" in remediation
        assert "delete the `import requests` line" in remediation

    def test_bare_import_with_name_in_requires_says_already_declared(self):
        """When the body redundantly bare-imports a name already
        in ``requires:``, the remediation acknowledges the existing
        declaration rather than telling the author to add it again."""
        source = dedent("""\
module foo
    layer: DOMAIN
    version: 0.1.0
    intent: "Body-import test fixture — name in requires."
    requires: [json]
    exports: [do_foo]

    uses: none
    soft_requires: none
    runtime_only_requires: none
    deferred_requires: none
    exports_helpers: none
nerve do_foo :: DOMAIN
    kind: FUNCTION
    visibility: PUBLIC
    intent: "Redundantly imports json from the body."
    expects: "none"
    guarantees: "Returns a JSON dump."
    forbids: none
    evaluates_at: FUNCTION_BOUNDARY
    provides: none
    returns: none
    raises: none
    interface: none
    latency_ms: none
    depends_on: none
    internal: none
    expected_exceptions: none
    consumes_via_dict: none
    declares_attributes: none
    covered_by: none
    ---
    def do_foo():
        import json
        return json.dumps({})
""").lstrip()
        _, warnings = parse_s0ma_with_warnings(
            source, "foo.s0ma", mode=StrictnessMode.DEV,
        )
        bare = [w for w in warnings if w.code == "BARE_IMPORT"]
        assert bare
        remediation = bare[0].remediation or ""
        # ``requires`` is the active declaration that should be cited —
        # pilot01: by its ACTUAL list name, not a four-way parenthetical.
        assert "already declared in `requires:`" in remediation
        assert "soft_requires" not in remediation
        assert "that half is done" in remediation
        assert "delete the `import json` line" in remediation

    def test_bare_import_in_deferred_requires_names_the_actual_list(self):
        """Pilot01 (c): when the name is already declared in
        ``deferred_requires:``, the remediation names THAT list
        specifically and reads as step 2 of the same fix — never as a
        contradiction of the header edit the author just made."""
        source = dedent("""\
module foo
    layer: DOMAIN
    version: 0.1.0
    intent: "Body-import test fixture — name in deferred_requires."
    deferred_requires: [sys]
    exports: [do_foo]

    requires: none
    uses: none
    soft_requires: none
    runtime_only_requires: none
    exports_helpers: none
nerve do_foo :: DOMAIN
    kind: FUNCTION
    visibility: PUBLIC
    intent: "Half-fixed bare import: declared but not deleted."
    expects: "none"
    guarantees: "Returns sys.path."
    forbids: none
    evaluates_at: FUNCTION_BOUNDARY
    provides: none
    returns: none
    raises: none
    interface: none
    latency_ms: none
    depends_on: none
    internal: none
    expected_exceptions: none
    consumes_via_dict: none
    declares_attributes: none
    covered_by: none
    ---
    def do_foo():
        import sys
        return sys.path
""").lstrip()
        _, warnings = parse_s0ma_with_warnings(
            source, "foo.s0ma", mode=StrictnessMode.DEV,
        )
        bare = [w for w in warnings if w.code == "BARE_IMPORT"]
        assert bare
        remediation = bare[0].remediation or ""
        # Names the actual list — not the four-way parenthetical.
        assert "already declared in `deferred_requires:`" in remediation
        assert "soft_requires" not in remediation
        assert "runtime_only_requires" not in remediation
        # Sequenced, not contradictory: acknowledges the done half and
        # asks only for the remaining body-line deletion.
        assert "that half is done" in remediation
        assert "delete the `import sys` line" in remediation
        assert "complete fix" in remediation
        # It must NOT tell the author to add the declaration again.
        assert "add `sys`" not in remediation

    def test_bare_import_not_declared_is_one_edit_two_parts(self):
        """Pilot01 (c): the not-declared variant frames the fix as ONE
        edit with two explicit, simultaneous parts."""
        source = dedent("""\
module foo
    layer: DOMAIN
    version: 0.1.0
    intent: "Body-import test fixture — undeclared name."
    exports: [do_foo]

    requires: none
    uses: none
    soft_requires: none
    runtime_only_requires: none
    deferred_requires: none
    exports_helpers: none
nerve do_foo :: DOMAIN
    kind: FUNCTION
    visibility: PUBLIC
    intent: "Bare import of an undeclared module."
    expects: "none"
    guarantees: "Returns sys.path."
    forbids: none
    evaluates_at: FUNCTION_BOUNDARY
    provides: none
    returns: none
    raises: none
    interface: none
    latency_ms: none
    depends_on: none
    internal: none
    expected_exceptions: none
    consumes_via_dict: none
    declares_attributes: none
    covered_by: none
    ---
    def do_foo():
        import sys
        return sys.path
""").lstrip()
        _, warnings = parse_s0ma_with_warnings(
            source, "foo.s0ma", mode=StrictnessMode.DEV,
        )
        bare = [w for w in warnings if w.code == "BARE_IMPORT"]
        assert bare
        remediation = bare[0].remediation or ""
        assert "ONE edit" in remediation
        assert "(1) add `sys` to the module header's `requires:` list" in remediation
        assert "(2) delete the `import sys` line" in remediation
        assert "deferred_requires:" in remediation
        # The invariant that prevents the observed half-fix loop:
        assert (
            "a bare import in the body is always an error even after "
            "the header declares it" in remediation
        )

    def test_bare_import_from_import_form_handled(self):
        """The remediation refinement also tailors ``from X import Y``
        statements: the imported names (Y) are the local bindings the
        check consults."""
        source = dedent("""\
module foo
    layer: DOMAIN
    version: 0.1.0
    intent: "Body-import test fixture — from-import form."
    uses: [other.bar]
    exports: [do_foo]

    requires: none
    soft_requires: none
    runtime_only_requires: none
    deferred_requires: none
    exports_helpers: none
nerve do_foo :: DOMAIN
    kind: FUNCTION
    visibility: PUBLIC
    intent: "from-import for bar."
    expects: "none"
    guarantees: "Returns bar()'s value"
    forbids: none
    evaluates_at: FUNCTION_BOUNDARY
    provides: none
    returns: none
    raises: none
    interface: none
    latency_ms: none
    depends_on: none
    internal: none
    expected_exceptions: none
    consumes_via_dict: none
    declares_attributes: none
    covered_by: none
    ---
    def do_foo():
        from somewhere import bar
        return bar()
""").lstrip()
        _, warnings = parse_s0ma_with_warnings(
            source, "foo.s0ma", mode=StrictnessMode.DEV,
        )
        bare = [w for w in warnings if w.code == "BARE_IMPORT"]
        assert bare
        remediation = bare[0].remediation or ""
        assert "already declared in `uses:" in remediation

    def test_bare_from_import_not_declared_suggests_colon_override(self):
        """Adversarial-review regression (pilot01 batch): for an
        undeclared ``from M import N`` the suggested requires token must
        be the colon-override ``M:N`` (which emits ``from M import N``)
        — never the bare bound name ``N``, which checks clean but
        transpiles to a literal ``import N`` that breaks at import
        time."""
        source = dedent("""\
module foo
    layer: DOMAIN
    version: 0.1.0
    intent: "Body-import test fixture — undeclared from-import."
    exports: [do_foo]

    requires: none
    uses: none
    soft_requires: none
    runtime_only_requires: none
    deferred_requires: none
    exports_helpers: none
nerve do_foo :: DOMAIN
    kind: FUNCTION
    visibility: PUBLIC
    intent: "from-import of an undeclared name."
    expects: "none"
    guarantees: "Returns a path string."
    forbids: none
    evaluates_at: FUNCTION_BOUNDARY
    provides: none
    returns: none
    raises: none
    interface: none
    latency_ms: none
    depends_on: none
    internal: none
    expected_exceptions: none
    consumes_via_dict: none
    declares_attributes: none
    covered_by: none
    ---
    def do_foo():
        from pathlib import Path
        return str(Path("."))
""").lstrip()
        _, warnings = parse_s0ma_with_warnings(
            source, "foo.s0ma", mode=StrictnessMode.DEV,
        )
        bare = [w for w in warnings if w.code == "BARE_IMPORT"]
        assert bare
        remediation = bare[0].remediation or ""
        assert "ONE edit" in remediation
        assert "`pathlib:Path`" in remediation
        assert "add `Path` to" not in remediation
        assert "delete the `from pathlib import Path` line" in remediation

    def test_bare_multi_import_not_declared_names_every_token(self):
        """Adversarial-review regression (pilot01 batch): ``import os,
        sys`` must suggest declaring BOTH names before the delete step —
        naming only the first would orphan the sibling when the agent
        deletes the whole line."""
        source = dedent("""\
module foo
    layer: DOMAIN
    version: 0.1.0
    intent: "Body-import test fixture — undeclared multi-import."
    exports: [do_foo]

    requires: none
    uses: none
    soft_requires: none
    runtime_only_requires: none
    deferred_requires: none
    exports_helpers: none
nerve do_foo :: DOMAIN
    kind: FUNCTION
    visibility: PUBLIC
    intent: "Multi-name bare import."
    expects: "none"
    guarantees: "Returns a platform string."
    forbids: none
    evaluates_at: FUNCTION_BOUNDARY
    provides: none
    returns: none
    raises: none
    interface: none
    latency_ms: none
    depends_on: none
    internal: none
    expected_exceptions: none
    consumes_via_dict: none
    declares_attributes: none
    covered_by: none
    ---
    def do_foo():
        import os, sys
        return os.name + sys.platform
""").lstrip()
        _, warnings = parse_s0ma_with_warnings(
            source, "foo.s0ma", mode=StrictnessMode.DEV,
        )
        bare = [w for w in warnings if w.code == "BARE_IMPORT"]
        assert bare
        remediation = bare[0].remediation or ""
        assert "`os`" in remediation
        assert "`sys`" in remediation
        assert "ONE edit" in remediation

    def test_bare_dotted_import_not_declared_keeps_full_path(self):
        """``import a.b`` must suggest the full dotted token ``a.b``
        (which emits ``import a.b``), not just the bound root ``a``."""
        source = dedent("""\
module foo
    layer: DOMAIN
    version: 0.1.0
    intent: "Body-import test fixture — dotted bare import."
    exports: [do_foo]

    requires: none
    uses: none
    soft_requires: none
    runtime_only_requires: none
    deferred_requires: none
    exports_helpers: none
nerve do_foo :: DOMAIN
    kind: FUNCTION
    visibility: PUBLIC
    intent: "Dotted bare import."
    expects: "none"
    guarantees: "Returns a joined path."
    forbids: none
    evaluates_at: FUNCTION_BOUNDARY
    provides: none
    returns: none
    raises: none
    interface: none
    latency_ms: none
    depends_on: none
    internal: none
    expected_exceptions: none
    consumes_via_dict: none
    declares_attributes: none
    covered_by: none
    ---
    def do_foo():
        import os.path
        return os.path.join("a", "b")
""").lstrip()
        _, warnings = parse_s0ma_with_warnings(
            source, "foo.s0ma", mode=StrictnessMode.DEV,
        )
        bare = [w for w in warnings if w.code == "BARE_IMPORT"]
        assert bare
        remediation = bare[0].remediation or ""
        assert "`os.path`" in remediation


# ===========================================================================
# POST-10g — uuid.uuid4 colon-override hint
# ===========================================================================


class TestPOST10gUuidColonOverrideHint:
    """A ``requires:`` entry with a lowercase last segment and a body
    that references the last segment as a bare identifier fires the
    new ``REQUIRES_DOTTED_LOWERCASE_HINT`` warning, suggesting the
    colon-override shape ``uuid:uuid4``."""

    def test_uuid_uuid4_in_requires_fires_hint(self):
        """The canonical motivating case: ``requires: [uuid.uuid4]``
        with a body using ``uuid4()`` directly. The hint must
        suggest the colon-override form."""
        source = dedent("""\
module hint_a
    layer: DOMAIN
    version: 0.1.0
    intent: "uuid hint test fixture — dotted form."
    requires: [uuid.uuid4]
    exports: [do_hint_a]

    uses: none
    soft_requires: none
    runtime_only_requires: none
    deferred_requires: none
    exports_helpers: none
nerve do_hint_a :: DOMAIN
    kind: FUNCTION
    visibility: PUBLIC
    intent: "Uses uuid4 as a bare identifier."
    expects: "none"
    guarantees: "Returns a uuid string."
    forbids: none
    evaluates_at: FUNCTION_BOUNDARY
    provides: none
    returns: none
    raises: none
    interface: none
    latency_ms: none
    depends_on: none
    internal: none
    expected_exceptions: none
    consumes_via_dict: none
    declares_attributes: none
    covered_by: none
    ---
    def do_hint_a():
        return str(uuid4())
""").lstrip()
        module, _ = parse_s0ma_with_warnings(
            source, "hint_a.s0ma", mode=StrictnessMode.DEV,
        )
        errors = validate_module(
            module, mode=StrictnessMode.DEV, filename="hint_a.s0ma",
        )
        hints = [
            e for e in errors
            if e.code == "REQUIRES_DOTTED_LOWERCASE_HINT"
        ]
        assert hints, (
            f"Expected REQUIRES_DOTTED_LOWERCASE_HINT; got {[e.code for e in errors]}"
        )
        h = hints[0]
        assert h.severity == "warning"
        assert "uuid:uuid4" in (h.remediation or "")
        assert "uuid4" in (h.message or "")

    def test_uuid_uppercase_segment_no_hint(self):
        """The control case: ``requires: [uuid.UUID]`` (uppercase last
        segment) is already recognised as a from-import by the
        parser's heuristic and no hint fires."""
        source = dedent("""\
module hint_b
    layer: DOMAIN
    version: 0.1.0
    intent: "uuid hint negative case — UPPER_CASE last segment."
    requires: [uuid.UUID]
    exports: [do_hint_b]

    uses: none
    soft_requires: none
    runtime_only_requires: none
    deferred_requires: none
    exports_helpers: none
nerve do_hint_b :: DOMAIN
    kind: FUNCTION
    visibility: PUBLIC
    intent: "Uses UUID()."
    expects: "none"
    guarantees: "Returns a UUID."
    forbids: none
    evaluates_at: FUNCTION_BOUNDARY
    provides: none
    returns: none
    raises: none
    interface: none
    latency_ms: none
    depends_on: none
    internal: none
    expected_exceptions: none
    consumes_via_dict: none
    declares_attributes: none
    covered_by: none
    ---
    def do_hint_b():
        return UUID(int=0)
""").lstrip()
        module, _ = parse_s0ma_with_warnings(
            source, "hint_b.s0ma", mode=StrictnessMode.DEV,
        )
        errors = validate_module(
            module, mode=StrictnessMode.DEV, filename="hint_b.s0ma",
        )
        hints = [
            e for e in errors
            if e.code == "REQUIRES_DOTTED_LOWERCASE_HINT"
        ]
        assert hints == []

    def test_colon_form_already_authored_no_hint(self):
        """When the author already uses the colon-override form
        ``requires: [uuid:uuid4]``, the hint stays silent —
        the heuristic-confusion premise no longer holds."""
        source = dedent("""\
module hint_c
    layer: DOMAIN
    version: 0.1.0
    intent: "uuid hint negative case — colon-override already authored."
    requires: [uuid:uuid4]
    exports: [do_hint_c]

    uses: none
    soft_requires: none
    runtime_only_requires: none
    deferred_requires: none
    exports_helpers: none
nerve do_hint_c :: DOMAIN
    kind: FUNCTION
    visibility: PUBLIC
    intent: "Uses uuid4() with the colon-override binding."
    expects: "none"
    guarantees: "Returns a uuid string."
    forbids: none
    evaluates_at: FUNCTION_BOUNDARY
    provides: none
    returns: none
    raises: none
    interface: none
    latency_ms: none
    depends_on: none
    internal: none
    expected_exceptions: none
    consumes_via_dict: none
    declares_attributes: none
    covered_by: none
    ---
    def do_hint_c():
        return str(uuid4())
""").lstrip()
        module, _ = parse_s0ma_with_warnings(
            source, "hint_c.s0ma", mode=StrictnessMode.DEV,
        )
        errors = validate_module(
            module, mode=StrictnessMode.DEV, filename="hint_c.s0ma",
        )
        hints = [
            e for e in errors
            if e.code == "REQUIRES_DOTTED_LOWERCASE_HINT"
        ]
        assert hints == []

    def test_dotted_lowercase_without_body_reference_no_hint(self):
        """The hint requires the body to actually reference the
        lowercase last segment. If the body uses only the first
        segment (``uuid.uuid4()`` qualified call), the hint stays
        silent because the heuristic's confusion is not the active
        author error."""
        source = dedent("""\
module hint_d
    layer: DOMAIN
    version: 0.1.0
    intent: "uuid hint negative — qualified call only."
    requires: [uuid.uuid4]
    exports: [do_hint_d]

    uses: none
    soft_requires: none
    runtime_only_requires: none
    deferred_requires: none
    exports_helpers: none
nerve do_hint_d :: DOMAIN
    kind: FUNCTION
    visibility: PUBLIC
    intent: "Uses uuid.uuid4() qualified."
    expects: "none"
    guarantees: "Returns a uuid string."
    forbids: none
    evaluates_at: FUNCTION_BOUNDARY
    provides: none
    returns: none
    raises: none
    interface: none
    latency_ms: none
    depends_on: none
    internal: none
    expected_exceptions: none
    consumes_via_dict: none
    declares_attributes: none
    covered_by: none
    ---
    def do_hint_d():
        return "no-op"
""").lstrip()
        module, _ = parse_s0ma_with_warnings(
            source, "hint_d.s0ma", mode=StrictnessMode.DEV,
        )
        errors = validate_module(
            module, mode=StrictnessMode.DEV, filename="hint_d.s0ma",
        )
        hints = [
            e for e in errors
            if e.code == "REQUIRES_DOTTED_LOWERCASE_HINT"
        ]
        assert hints == []
