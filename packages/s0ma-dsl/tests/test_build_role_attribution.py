"""The build records each module's role from the root its file lives under.

A bare ``s0ma build`` (the command ``s0ma doctor`` recommends),
``s0ma build .`` and ``s0ma build <project root>`` walk the project's
``source_roots`` and ``test_roots`` together. They used to record every
module with ``role: "source"``, because only ``s0ma test``'s build helper
set a role, and it set one role for a whole pass. After such a build,
``bootstrap_imports`` with its default roles imported the test modules into
the application, and anything else keyed on the role saw the tests as part
of it.

The build now decides the role per module: ``test`` for a file under a
configured test root, ``source`` for one under a source root, whichever
path the caller named. The test runner's explicit role still wins when it
is set. A module under no configured root is recorded as ``source`` and
reported with ``MODULE_OUTSIDE_PROJECT_ROOTS``; a synthetic project has no
roots and records ``source`` silently.

Every project here is written by :func:`_project` with a per-test prefix on
its module and component names. The transpiled modules register components
in s0ma's global registry when they are imported, and the registry refuses
a second registration of the same name within one pytest process, so each
test that imports for real imports names nobody else has used.
"""

from __future__ import annotations

import json
import re
import sys
import textwrap
from pathlib import Path
from typing import TYPE_CHECKING

from s0ma.bootstrap import bootstrap_imports

from s0ma_dsl.check_baseline import is_check_severity_error
from s0ma_dsl.cli.main import EXIT_SUCCESS, S0maCLI
from s0ma_dsl.codegen.build_manifest import VALID_ROLES, load_manifest
from s0ma_dsl.codegen.self_context import SELF_CONTEXT_FILENAME
from s0ma_dsl.config import StrictnessMode, get_severity
from s0ma_dsl.errors import S0maError
from s0ma_dsl.project import S0maProject

if TYPE_CHECKING:
    import pytest

CODE = "MODULE_OUTSIDE_PROJECT_ROOTS"


# ---------------------------------------------------------------------------
# The project under test
# ---------------------------------------------------------------------------

_NERVE_TAIL = """\
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
"""


def _calc(p: str) -> str:
    return textwrap.dedent(f'''\
        module {p}_calc
            layer: DOMAIN
            version: 1.0.0
            intent: "Adds integers for the role attribution tests."
            exports: [{p}_add]

            requires: none
            uses: none
            soft_requires: none
            runtime_only_requires: none
            deferred_requires: none
            exports_helpers: none
        nerve {p}_add :: DOMAIN
            kind: FUNCTION
            visibility: PUBLIC
            intent: "Adds two integers and returns the sum."
            expects: "Two integer arguments."
            guarantees: "Returns the integer sum of the two arguments."
        ''') + _NERVE_TAIL + textwrap.dedent(f'''\
            ---
            def {p}_add(a: int, b: int) -> int:
                return a + b
        ''')


def _fmt(p: str) -> str:
    return textwrap.dedent(f'''\
        module {p}_fmt
            layer: APPLICATION
            version: 1.0.0
            intent: "Formats sums for the role attribution tests."
            uses: [{p}_calc.{p}_add]
            exports: [{p}_format_sum]

            requires: none
            soft_requires: none
            runtime_only_requires: none
            deferred_requires: none
            exports_helpers: none
        nerve {p}_format_sum :: APPLICATION
            kind: FUNCTION
            visibility: PUBLIC
            intent: "Formats the sum of two integers as a labelled string."
            expects: "Two integer arguments."
            guarantees: "Returns a string of the form 'sum: <a+b>'."
        ''') + _NERVE_TAIL + textwrap.dedent(f'''\
            ---
            def {p}_format_sum(a: int, b: int) -> str:
                return f"sum: {{{p}_add(a, b)}}"
        ''')


def _test_calc(p: str) -> str:
    return textwrap.dedent(f'''\
        module test_{p}_calc
            layer: DOMAIN
            version: 1.0.0
            intent: "Verifies the adder for the role attribution tests."
            uses: [{p}_calc.{p}_add]
            exports: []

            requires: none
            soft_requires: none
            runtime_only_requires: none
            deferred_requires: none
            exports_helpers: none
        test test_{p}_add_sums :: DOMAIN
            intent: "Verifies that the adder returns the integer sum."
            tests: [{p}_calc.{p}_add]
            expects: none
            depends_on: none
            mocks: none
            ---
            def test_{p}_add_sums():
                assert {p}_add(2, 3) == 5
        ''')


def _test_fmt(p: str) -> str:
    return textwrap.dedent(f'''\
        module test_{p}_fmt
            layer: APPLICATION
            version: 1.0.0
            intent: "Verifies the formatter for the role attribution tests."
            uses: [{p}_fmt.{p}_format_sum]
            exports: []

            requires: none
            soft_requires: none
            runtime_only_requires: none
            deferred_requires: none
            exports_helpers: none
        test test_{p}_format_sum_labels :: APPLICATION
            intent: "Verifies that the formatter labels the sum."
            tests: [{p}_fmt.{p}_format_sum]
            expects: none
            depends_on: none
            mocks: none
            ---
            def test_{p}_format_sum_labels():
                assert {p}_format_sum(2, 3) == "sum: 5"
        ''')


def _extra(p: str) -> str:
    return textwrap.dedent(f'''\
        module {p}_extra
            layer: DOMAIN
            version: 1.0.0
            intent: "A module that lives under no configured root."
            exports: [{p}_extra_value]

            requires: none
            uses: none
            soft_requires: none
            runtime_only_requires: none
            deferred_requires: none
            exports_helpers: none
        nerve {p}_extra_value :: DOMAIN
            kind: FUNCTION
            visibility: PUBLIC
            intent: "Returns a fixed integer."
            expects: "No arguments."
            guarantees: "Returns one."
        ''') + _NERVE_TAIL + textwrap.dedent(f'''\
            ---
            def {p}_extra_value() -> int:
                return 1
        ''')


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8", newline="\n")


def _project(tmp_path: Path, p: str, *, extras: bool = False) -> Path:
    """A real project: two modules under ``src``, two test modules under
    ``tests`` and, when asked, one module under ``extras``, which is under
    no configured root."""
    root = tmp_path / f"{p}_project"
    _write(
        root / "pyproject.toml",
        textwrap.dedent(f'''\
            [project]
            name = "{p}_project"
            version = "0.1.0"

            [tool.s0ma]
            source_roots = ["src"]
            test_roots = ["tests"]
            build_dir = "{p}_build"
            bootstrap_files = []
            '''),
    )
    _write(root / "src" / f"{p}_calc.s0ma", _calc(p))
    _write(root / "src" / f"{p}_fmt.s0ma", _fmt(p))
    _write(root / "tests" / f"test_{p}_calc.s0ma", _test_calc(p))
    _write(root / "tests" / f"test_{p}_fmt.s0ma", _test_fmt(p))
    if extras:
        _write(root / "extras" / f"{p}_extra.s0ma", _extra(p))
    return root


def _build_dir(root: Path, p: str) -> Path:
    return root / f"{p}_build"


def _run(root: Path, *argv: str) -> int:
    return S0maCLI().run(["--project-root", str(root), *argv])


def _roles(build_dir: Path) -> dict[str, str]:
    return {entry.name: entry.role for entry in load_manifest(build_dir).modules}


def _expected_roles(p: str) -> dict[str, str]:
    return {
        f"{p}_calc": "source",
        f"{p}_fmt": "source",
        f"test_{p}_calc": "test",
        f"test_{p}_fmt": "test",
    }


def _module_names(p: str) -> list[str]:
    return [f"{p}_calc", f"{p}_fmt", f"test_{p}_calc", f"test_{p}_fmt", f"{p}_extra"]


def _bootstrap_source_names(build_dir: Path, p: str) -> list[str]:
    """What ``bootstrap_imports`` with its default roles imports from the
    build, with the imports undone afterwards so the next test starts
    clean."""
    for name in _module_names(p):
        sys.modules.pop(name, None)
    try:
        imported = bootstrap_imports(build_dir, roles=("source",))
        return sorted(imported)
    finally:
        for name in _module_names(p):
            sys.modules.pop(name, None)
        build_str = str(build_dir)
        while build_str in sys.path:
            sys.path.remove(build_str)


def _companion_agrees_with_manifest(build_dir: Path) -> None:
    """The self-context companion describes exactly the manifest modules
    whose role passes the filter the companion records.

    The companion written by this tree carries no ``roles`` in its
    provenance and lists every module. A role filter that records
    ``provenance.roles`` is arriving in a separate change; under it the
    companion lists the source modules alone. This assertion holds either
    way, and the stricter half fires once the filter is present.
    """
    document = json.loads(
        (build_dir / SELF_CONTEXT_FILENAME).read_text(encoding="utf-8")
    )
    manifest = load_manifest(build_dir)
    provenance = document["provenance"]
    roles = set(provenance.get("roles", sorted(VALID_ROLES)))
    described = {entry.name for entry in manifest.modules if entry.role in roles}
    assert {component["module"] for component in document["components"]} == described
    assert {
        Path(record["path"]).name.removesuffix(".s0ma.json")
        for record in document["source_ir"]
    } == described
    if "roles" in provenance:
        assert list(provenance["roles"]) == ["source"]
        test_modules = {entry.name for entry in manifest.modules if entry.role == "test"}
        assert not test_modules & {component["module"] for component in document["components"]}


# ---------------------------------------------------------------------------
# The bare build
# ---------------------------------------------------------------------------


class TestTheBareBuild:
    def test_it_records_each_module_with_the_role_of_its_root(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        p = "bare"
        root = _project(tmp_path, p)

        assert _run(root, "build") == EXIT_SUCCESS
        out = capsys.readouterr()

        manifest = load_manifest(_build_dir(root, p))
        assert _roles(_build_dir(root, p)) == _expected_roles(p)
        assert {entry.name: entry.source_root for entry in manifest.modules} == {
            f"{p}_calc": "src",
            f"{p}_fmt": "src",
            f"test_{p}_calc": "tests",
            f"test_{p}_fmt": "tests",
        }
        assert CODE not in out.out + out.err

    def test_the_import_order_lists_every_module_after_what_it_uses(
        self, tmp_path: Path
    ) -> None:
        p = "topo"
        root = _project(tmp_path, p)

        assert _run(root, "build") == EXIT_SUCCESS

        order = list(load_manifest(_build_dir(root, p)).topological_import_order)
        assert sorted(order) == sorted(_expected_roles(p))
        assert order.index(f"{p}_calc") < order.index(f"{p}_fmt")
        assert order.index(f"{p}_calc") < order.index(f"test_{p}_calc")
        assert order.index(f"{p}_fmt") < order.index(f"test_{p}_fmt")

    def test_bootstrap_imports_loads_the_application_alone(
        self, tmp_path: Path
    ) -> None:
        p = "boot"
        root = _project(tmp_path, p)

        assert _run(root, "build") == EXIT_SUCCESS

        assert _bootstrap_source_names(_build_dir(root, p), p) == [
            f"{p}_calc", f"{p}_fmt",
        ]

    def test_the_companion_agrees_with_the_manifest(self, tmp_path: Path) -> None:
        p = "comp"
        root = _project(tmp_path, p)

        assert _run(root, "build") == EXIT_SUCCESS

        _companion_agrees_with_manifest(_build_dir(root, p))

    def test_naming_the_project_root_records_the_same_roles(
        self, tmp_path: Path
    ) -> None:
        """``s0ma build <project root>`` is what the MCP build tool runs."""
        p = "named"
        root = _project(tmp_path, p)

        assert _run(root, "build", str(root)) == EXIT_SUCCESS

        assert _roles(_build_dir(root, p)) == _expected_roles(p)


# ---------------------------------------------------------------------------
# Built by root
# ---------------------------------------------------------------------------


class TestABuildByRoot:
    def test_a_source_root_alone_records_source_entries_only(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        p = "srconly"
        root = _project(tmp_path, p)

        assert _run(root, "build", str(root / "src")) == EXIT_SUCCESS
        out = capsys.readouterr()

        manifest = load_manifest(_build_dir(root, p))
        assert _roles(_build_dir(root, p)) == {
            f"{p}_calc": "source", f"{p}_fmt": "source",
        }
        assert set(manifest.topological_import_order) == {f"{p}_calc", f"{p}_fmt"}
        assert {entry.source_root for entry in manifest.modules} == {"src"}
        assert CODE not in out.out + out.err

    def test_the_test_root_merges_in_with_the_test_role(
        self, tmp_path: Path
    ) -> None:
        p = "byroot"
        root = _project(tmp_path, p)

        assert _run(root, "build", str(root / "src")) == EXIT_SUCCESS
        # A test root built on its own resolves its ``uses:`` against the
        # source root through ``--include``, as ``s0ma test`` arranges.
        assert _run(
            root, "build", str(root / "tests"), "--include", str(root / "src"),
        ) == EXIT_SUCCESS

        assert _roles(_build_dir(root, p)) == _expected_roles(p)
        assert _bootstrap_source_names(_build_dir(root, p), p) == [
            f"{p}_calc", f"{p}_fmt",
        ]
        _companion_agrees_with_manifest(_build_dir(root, p))


# ---------------------------------------------------------------------------
# The test runner
# ---------------------------------------------------------------------------


class TestTheTestRunner:
    def test_s0ma_test_records_what_it_always_did(self, tmp_path: Path) -> None:
        p = "runner"
        root = _project(tmp_path, p)

        assert _run(root, "test", "--quiet") == EXIT_SUCCESS

        assert _roles(_build_dir(root, p)) == _expected_roles(p)
        assert _bootstrap_source_names(_build_dir(root, p), p) == [
            f"{p}_calc", f"{p}_fmt",
        ]
        _companion_agrees_with_manifest(_build_dir(root, p))

    def test_a_bare_build_after_s0ma_test_leaves_the_roles_as_they_were(
        self, tmp_path: Path
    ) -> None:
        p = "after"
        root = _project(tmp_path, p)

        assert _run(root, "test", "--quiet") == EXIT_SUCCESS
        before = _roles(_build_dir(root, p))
        assert _run(root, "build") == EXIT_SUCCESS

        assert _roles(_build_dir(root, p)) == before == _expected_roles(p)

    def test_the_explicit_role_of_the_build_helper_still_wins(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """``_run_build_for_test`` states a role for a whole pass; that
        statement is kept, even for a directory under no configured root,
        and no warning is raised for it."""
        p = "explicit"
        root = _project(tmp_path, p, extras=True)
        project = S0maProject.discover(root)
        cli = S0maCLI()

        rc = cli._run_build_for_test(
            project_dir=root / "tests",
            output_dir=_build_dir(root, p),
            include_dirs=[root / "src"],
            mode="dev",
            s0ma_project=project,
            quiet=False,
            role="test",
        )
        assert rc == EXIT_SUCCESS
        rc = cli._run_build_for_test(
            project_dir=root / "extras",
            output_dir=_build_dir(root, p),
            include_dirs=[],
            mode="dev",
            s0ma_project=project,
            quiet=False,
            role="test",
        )
        assert rc == EXIT_SUCCESS
        out = capsys.readouterr()

        assert _roles(_build_dir(root, p)) == {
            f"test_{p}_calc": "test",
            f"test_{p}_fmt": "test",
            f"{p}_extra": "test",
        }
        assert CODE not in out.out + out.err


# ---------------------------------------------------------------------------
# A module under no configured root
# ---------------------------------------------------------------------------


class TestAModuleUnderNoConfiguredRoot:
    def test_it_is_recorded_as_source_and_reported(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        p = "outside"
        root = _project(tmp_path, p, extras=True)

        assert _run(root, "build") == EXIT_SUCCESS
        bare = capsys.readouterr()
        assert _run(root, "build", str(root / "extras")) == EXIT_SUCCESS
        extras = capsys.readouterr()

        manifest = load_manifest(_build_dir(root, p))
        roles = _roles(_build_dir(root, p))
        assert roles == {**_expected_roles(p), f"{p}_extra": "source"}
        extra = next(entry for entry in manifest.modules if entry.name == f"{p}_extra")
        assert extra.source_root == ""
        # The bare build never reaches extras, so it has nothing to report;
        # the build of extras reports the one module, once, as a warning.
        assert CODE not in bare.out + bare.err
        assert (extras.out + extras.err).count(CODE) == 1
        assert "WARNING" in extras.out + extras.err
        assert "recorded it with role source" in extras.out + extras.err

    def test_the_json_report_carries_the_warning_and_its_context(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        p = "outjson"
        root = _project(tmp_path, p, extras=True)

        assert _run(root, "build", str(root / "extras"), "--format", "json") == EXIT_SUCCESS
        report = json.loads(capsys.readouterr().out)

        warnings = [w for w in report["warnings"] if w["code"] == CODE]
        assert len(warnings) == 1
        assert warnings[0]["severity"] == "warning"
        assert warnings[0]["context"] == {
            "module": f"{p}_extra",
            "source_roots": ["src"],
            "test_roots": ["tests"],
        }
        assert "[tool.s0ma].source_roots or test_roots" in warnings[0]["remediation"]
        assert report["errors"] == []

    def test_the_warning_is_never_a_check_error(self) -> None:
        """A warning in every mode, so the build gate and the check baseline
        never see it."""
        assert {get_severity(CODE, mode) for mode in StrictnessMode} == {"warning"}
        diagnostic = S0maError(
            code=CODE,
            message="a module under no configured root",
            file="extras/example.s0ma",
            line=1,
            column=0,
            severity="warning",
            remediation="declare the directory as a root",
        )
        assert not is_check_severity_error(diagnostic)


# ---------------------------------------------------------------------------
# Without a project
# ---------------------------------------------------------------------------


def test_a_synthetic_project_records_source_silently(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """With no ``[tool.s0ma]`` table there are no roots to be outside of."""
    p = "synthetic"
    plain = tmp_path / "plain"
    _write(plain / f"{p}_calc.s0ma", _calc(p))
    _write(plain / f"{p}_fmt.s0ma", _fmt(p))

    rc = S0maCLI().run([
        "--project-root", str(plain),
        "build", str(plain),
        "--output-dir", str(plain / "out"),
    ])
    out = capsys.readouterr()

    assert rc == EXIT_SUCCESS
    assert _roles(plain / "out") == {f"{p}_calc": "source", f"{p}_fmt": "source"}
    assert CODE not in out.out + out.err


# ---------------------------------------------------------------------------
# The command doctor recommends
# ---------------------------------------------------------------------------


def test_the_command_doctor_recommends_writes_a_correct_manifest(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    p = "doctor"
    root = _project(tmp_path, p)

    assert _run(root, "doctor", "--format", "json") == EXIT_SUCCESS
    before = json.loads(capsys.readouterr().out)
    suggested = before["project"]["suggested_next_action"]
    # The dash is the one doctor prints between the command and its reason.
    assert suggested == "run `s0ma build` \u2014 project not built yet"

    match = re.search(r"`([^`]+)`", suggested)
    assert match is not None
    command = match.group(1).split()
    assert command[0] == "s0ma"
    assert _run(root, *command[1:]) == EXIT_SUCCESS
    capsys.readouterr()

    assert _roles(_build_dir(root, p)) == _expected_roles(p)
    assert _bootstrap_source_names(_build_dir(root, p), p) == [
        f"{p}_calc", f"{p}_fmt",
    ]
    assert _run(root, "doctor", "--format", "json") == EXIT_SUCCESS
    after = json.loads(capsys.readouterr().out)
    assert after["project"]["suggested_next_action"] == "run `s0ma check`"
