"""The build gate and the environment the build runs in.

``s0ma build`` refuses NEW check errors against the project's check
baseline (``test_build_new_error_gate.py``). One code is different from
every other check-severity code: ``MISSING_PACKAGE`` is raised when the
interpreter running the build cannot find a ``requires:`` entry, so its
truth depends on the environment, not on the authored source. A PEP 517
build environment holds ``[build-system].requires`` and nothing else, so
every third-party ``requires:`` entry is missing there, and a baseline
recorded in the developer's environment makes each one look NEW. That is
the shape fr3d's wheel build met: a green strict baseline, then a refusal
in the isolated build environment on ``MISSING_PACKAGE`` alone.

The gate cannot tell that case from a misspelled ``requires:`` entry, so
it does not guess. The caller who knows that the environment is the cause
says so with ``--without-runtime-packages``, and then:

* a ``requires:`` entry the build cannot find is recorded in the manifest
  under ``unverified_packages`` and in the JSON report under
  ``build_environment``, and does not count as a NEW check error;
* a genuinely new contract error still refuses the build;
* nothing is waved through, so ``overridden_new_errors`` stays empty;
* the baseline is left alone, because a foreign environment's findings
  say nothing about this checkout's debt;
* strict and release mode refuse the flag, because they exist to verify
  what the flag says cannot be verified here.

Without the flag nothing changes, except that a refusal whose every NEW
error is ``MISSING_PACKAGE`` now says the flag exists.

The two environments are simulated in process: a package that exists
only on a directory this suite puts on ``sys.path`` for the baseline run
and takes off again for the build, which is what the resolver's
``importlib.util.find_spec`` probe sees in a PEP 517 build environment.
"""

from __future__ import annotations

import importlib
import io
import json
from contextlib import redirect_stdout
from typing import TYPE_CHECKING

import pytest

from s0ma_dsl.check_baseline import (
    ENVIRONMENT_CODES,
    baseline_path,
    is_environment_diagnostic,
)
from s0ma_dsl.cli.main import EXIT_USAGE_ERROR, S0maCLI
from s0ma_dsl.codegen.build_manifest import (
    MANIFEST_FILENAME,
    ManifestSchemaError,
    load_manifest,
)
from s0ma_dsl.errors import S0maError

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

#: A package the application has at runtime and the build environment does
#: not. The name is unique to this suite so no real distribution can shadow
#: it.
PACKAGE = "pkg_installed_only_where_the_app_runs"

_PYPROJECT = """\
[project]
name = "wheel_app"
version = "0.1.0"

[tool.s0ma]
source_roots = ["src"]
build_dir = "build"
"""

# Two modules, so the cross-module resolver (and with it the requires:
# probe that raises MISSING_PACKAGE) runs on every build.
_SCHEDULER = f"""\
module scheduler
    layer: DOMAIN
    version: 0.1.0
    intent: "Compute the next run time of a cron expression."
    exports: [next_run]
    requires: [{PACKAGE}]
    uses: none
    soft_requires: none
    runtime_only_requires: none
    deferred_requires: none
    exports_helpers: none

nerve next_run :: DOMAIN
    kind: FUNCTION
    visibility: PUBLIC
    intent: "Return the next run time after start for a cron expression."
    expects: "expression is a five-field cron expression"
    guarantees: "returns a time after start"
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
    def next_run(expression, start):
        return {PACKAGE}.next_after(expression, start)
"""

# A SERVICE whose factory defines every provides: name; only the returned
# dict's keys vary, so the one contract finding the broken form adds is
# PROVIDES_KEY_MISMATCH: a warning in dev, an error in strict, which is
# exactly the class of error the gate exists to refuse.
_OPS_HEAD = """\
module ops
    layer: APPLICATION
    version: 0.1.0
    intent: "Operations the scheduler's callers assemble."
    exports: [assembler]
    requires: none
    uses: none
    soft_requires: none
    runtime_only_requires: none
    deferred_requires: none
    exports_helpers: none

nerve assembler :: APPLICATION
    kind: SERVICE
    visibility: PUBLIC
    intent: "Return a dict of ops."
    expects: "no arguments"
    guarantees: "returns a dict of ops"
    forbids: none
    provides: [assemble, validate]
    evaluates_at: FUNCTION_BOUNDARY
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
    def assembler():
        def assemble():
            return 1
        def validate():
            return 1
"""
_OPS_GREEN = _OPS_HEAD + "        return {'assemble': assemble, 'validate': validate}\n"
_OPS_BROKEN = _OPS_HEAD + "        return {'assemble': assemble, 'validat': validate}\n"

# The scheduler with ``ops``, a s0ma module of this project, listed under
# requires: as well. The checker reports that entry as MISSING_PACKAGE too,
# but it is misplaced in every environment (it belongs in uses:), so it is
# a contract error and not a finding about the environment.
_SCHEDULER_REQUIRING_OPS = _SCHEDULER.replace(
    f"requires: [{PACKAGE}]", f"requires: [{PACKAGE}, ops]",
).replace(
    "next_after(expression, start)", "next_after(expression, ops.assembler)",
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_project(root: Path, ops: str = _OPS_GREEN) -> Path:
    src = root / "src"
    src.mkdir(parents=True)
    (root / "pyproject.toml").write_text(_PYPROJECT, encoding="utf-8")
    (src / "scheduler.s0ma").write_text(_SCHEDULER, encoding="utf-8")
    (src / "ops.s0ma").write_text(ops, encoding="utf-8")
    return root


def _write_ops(root: Path, source: str) -> None:
    (root / "src" / "ops.s0ma").write_text(source, encoding="utf-8")


def _make_site(root: Path) -> Path:
    """A directory holding the runtime package, to put on ``sys.path``."""
    package = root / "site" / PACKAGE
    package.mkdir(parents=True)
    (package / "__init__.py").write_text(
        "def next_after(expression, start):\n    return start\n",
        encoding="utf-8",
    )
    return package.parent


@pytest.fixture
def project(tmp_path: Path) -> Path:
    return _make_project(tmp_path / "p")


@pytest.fixture
def site(tmp_path: Path) -> Path:
    return _make_site(tmp_path)


@pytest.fixture
def package_present(site: Path) -> Iterator[None]:
    """The developer's environment: the runtime package is importable."""
    with pytest.MonkeyPatch.context() as mp:
        mp.syspath_prepend(str(site))
        importlib.invalidate_caches()
        yield
    importlib.invalidate_caches()


def _run(root: Path, *argv: str) -> int:
    return S0maCLI().run(["--project-root", str(root), *argv])


def _build(root: Path, *extra: str, mode: str = "dev") -> int:
    return _run(root, "build", str(root), "--mode", mode, "--no-cache", *extra)


def _build_json(root: Path, *extra: str, mode: str = "dev") -> tuple[int, dict]:
    buf = io.StringIO()
    with redirect_stdout(buf):
        rc = _build(root, "--format", "json", *extra, mode=mode)
    return rc, json.loads(buf.getvalue())


def _record_green_baseline(root: Path, site: Path) -> bytes:
    """A strict check where the package is installed; returns the record."""
    with pytest.MonkeyPatch.context() as mp:
        mp.syspath_prepend(str(site))
        importlib.invalidate_caches()
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = _run(root, "check", "--mode", "strict")
        assert rc == 0, buf.getvalue()
    importlib.invalidate_caches()
    record = baseline_path(root).read_bytes()
    assert json.loads(record)["anchor"] == []
    return record


def _manifest(root: Path) -> dict:
    return json.loads((root / "build" / MANIFEST_FILENAME).read_text("utf-8"))


# ---------------------------------------------------------------------------
# An environment change is not an edit
# ---------------------------------------------------------------------------


class TestAnEnvironmentChangeIsNotAnEdit:
    def test_the_build_without_the_package_refuses_and_names_the_flag(
        self, project: Path, site: Path, capsys: pytest.CaptureFixture[str],
    ) -> None:
        """fr3d's case: green baseline with the package, refusal without it.

        Nothing was edited between the two runs. Without the flag the gate
        still refuses, because it cannot tell the environment from a typo;
        what changes is that the refusal says which flag answers it.
        """
        _record_green_baseline(project, site)
        capsys.readouterr()

        rc = _build(project)
        out = capsys.readouterr().out
        assert rc != 0
        assert "BUILD REFUSED" in out
        assert "[NEW]" in out and "MISSING_PACKAGE" in out
        assert "--without-runtime-packages" in out
        assert "PEP 517 build environment" in out
        assert not (project / "build" / MANIFEST_FILENAME).exists()

        rc, doc = _build_json(project)
        assert rc != 0
        assert doc["build_refused"]["reason"] == "NEW_CHECK_ERRORS"
        assert "--without-runtime-packages" in doc["build_refused"]["environment_hint"]
        assert [e["code"] for e in doc["errors"]] == ["MISSING_PACKAGE"]

    def test_the_flag_builds_and_records_the_unverified_package(
        self, project: Path, site: Path, capsys: pytest.CaptureFixture[str],
    ) -> None:
        record = _record_green_baseline(project, site)
        capsys.readouterr()

        rc, doc = _build_json(project, "--without-runtime-packages")
        assert rc == 0, doc
        assert "build_refused" not in doc
        # Nothing was overridden: the package is classified, not waved through.
        assert "build_override" not in doc
        environment = doc["build_environment"]
        assert environment["without_runtime_packages"] is True
        assert environment["unverified_packages"] == [PACKAGE]
        assert environment["unverified_package_count"] == 1
        assert [d["code"] for d in environment["diagnostics"]] == ["MISSING_PACKAGE"]
        # The diagnostic itself is still reported, as the dev warning it is.
        assert "MISSING_PACKAGE" in {w["code"] for w in doc["warnings"]}

        manifest = load_manifest(project / "build")
        assert manifest.unverified_packages == (PACKAGE,)
        assert manifest.overridden_new_errors == ()
        raw = _manifest(project)
        assert raw["unverified_packages"] == [PACKAGE]
        assert "overridden_new_errors" not in raw
        # The baseline is the developer's record, and this build was not
        # made in the developer's environment: it is byte-for-byte as it was.
        assert baseline_path(project).read_bytes() == record

    def test_the_text_report_says_what_was_not_verified(
        self, project: Path, site: Path, capsys: pytest.CaptureFixture[str],
    ) -> None:
        _record_green_baseline(project, site)
        capsys.readouterr()
        rc = _build(project, "--without-runtime-packages", "--quiet")
        out = capsys.readouterr().out
        assert rc == 0
        assert "built without the project's runtime packages" in out
        assert PACKAGE in out
        assert "recorded in the build manifest as unverified" in out
        assert "built with --allow-new-errors" not in out

    def test_the_flag_never_writes_a_baseline(
        self, project: Path, capsys: pytest.CaptureFixture[str],
    ) -> None:
        """A fresh clone: no baseline, the wheel build runs first.

        A full-project build normally seeds the baseline. A build made
        without the runtime packages would seed it with findings about a
        foreign environment, so it seeds nothing; the next check or build
        made where the packages are installed does.
        """
        assert not baseline_path(project).exists()
        rc, doc = _build_json(project, "--without-runtime-packages")
        assert rc == 0, doc
        assert doc["build_environment"]["unverified_packages"] == [PACKAGE]
        assert load_manifest(project / "build").unverified_packages == (PACKAGE,)
        assert not baseline_path(project).exists()


# ---------------------------------------------------------------------------
# A new contract error still refuses
# ---------------------------------------------------------------------------


class TestANewContractErrorStillRefuses:
    def test_under_the_flag_the_contract_error_alone_refuses(
        self, project: Path, site: Path, capsys: pytest.CaptureFixture[str],
    ) -> None:
        _record_green_baseline(project, site)
        capsys.readouterr()
        _write_ops(project, _OPS_BROKEN)

        rc, doc = _build_json(project, "--without-runtime-packages")
        assert rc != 0
        assert doc["build_refused"]["reason"] == "NEW_CHECK_ERRORS"
        assert doc["build_refused"]["new_error_count"] == 1
        # The refusal lists the contract error and not the environment
        # finding, and it does not suggest a flag that is already passed.
        assert [e["code"] for e in doc["errors"]] == ["PROVIDES_KEY_MISMATCH"]
        assert doc["errors"][0]["delta_label"] == "NEW"
        assert "environment_hint" not in doc["build_refused"]
        # The delta counts what can refuse, and nothing else: the
        # environment finding is in the refusal's record, not its count.
        assert [k["code"] for k in doc["delta"]["new"]] == ["PROVIDES_KEY_MISMATCH"]
        assert doc["delta"]["summary"].startswith("1 failure(s): 1 NEW")
        assert doc["build_environment"]["unverified_packages"] == [PACKAGE]
        assert not (project / "build" / MANIFEST_FILENAME).exists()

        rc = _build(project, "--without-runtime-packages")
        out = capsys.readouterr().out
        assert rc != 0
        assert "BUILD REFUSED: 1 NEW check error(s)" in out
        assert "PROVIDES_KEY_MISMATCH" in out
        assert "Every NEW error is MISSING_PACKAGE" not in out
        assert (
            "Not counted above, because --without-runtime-packages was "
            f"passed: 1 requires: entry this environment cannot find ({PACKAGE})."
        ) in out

    def test_allow_new_errors_records_the_override_and_the_packages_apart(
        self, project: Path, site: Path, capsys: pytest.CaptureFixture[str],
    ) -> None:
        """The two records never merge: what was waved through is one
        list, what could not be verified is another."""
        _record_green_baseline(project, site)
        capsys.readouterr()
        _write_ops(project, _OPS_BROKEN)

        rc, doc = _build_json(
            project, "--without-runtime-packages", "--allow-new-errors",
        )
        assert rc == 0, doc
        assert doc["build_override"]["new_error_count"] == 1
        assert [e["code"] for e in doc["build_override"]["new_errors"]] == [
            "PROVIDES_KEY_MISMATCH",
        ]
        assert doc["build_environment"]["unverified_packages"] == [PACKAGE]
        manifest = load_manifest(project / "build")
        assert manifest.overridden_new_errors == (
            "PROVIDES_KEY_MISMATCH@src/ops.s0ma",
        )
        assert manifest.unverified_packages == (PACKAGE,)

    def test_a_misspelled_requires_in_the_developer_environment_still_refuses(
        self, project: Path, site: Path, capsys: pytest.CaptureFixture[str],
    ) -> None:
        """Without the flag the gate is exactly what it was.

        A developer whose environment lacks the package (a typo, or a
        package never installed) is refused as before: the classification
        only applies when the caller states the environment is the cause.
        """
        _record_green_baseline(project, site)
        capsys.readouterr()
        # Simulate the typo: the required name is not importable here and
        # nobody said the environment is to blame.
        rc, doc = _build_json(project)
        assert rc != 0
        assert doc["build_refused"]["reason"] == "NEW_CHECK_ERRORS"
        assert [e["code"] for e in doc["errors"]] == ["MISSING_PACKAGE"]
        assert "build_environment" not in doc
        assert not (project / "build" / MANIFEST_FILENAME).exists()

    def test_a_requires_entry_naming_a_s0ma_module_still_refuses(
        self, project: Path, site: Path, capsys: pytest.CaptureFixture[str],
    ) -> None:
        """A s0ma module under requires: is not an environment finding.

        The checker reports it as MISSING_PACKAGE, but no environment
        supplies it: it belongs in uses:. So the flag does not classify
        it, the manifest does not list it as an unverified package, and a
        refusal made without the flag does not suggest the flag for it.
        """
        _record_green_baseline(project, site)
        capsys.readouterr()
        (project / "src" / "scheduler.s0ma").write_text(
            _SCHEDULER_REQUIRING_OPS, encoding="utf-8",
        )

        rc, doc = _build_json(project, "--without-runtime-packages")
        assert rc != 0, doc
        assert doc["build_refused"]["new_error_count"] == 1
        assert [
            (e["code"], e["context"]["import_path"]) for e in doc["errors"]
        ] == [("MISSING_PACKAGE", "ops")]
        assert not (project / "build" / MANIFEST_FILENAME).exists()

        with pytest.MonkeyPatch.context() as mp:
            mp.syspath_prepend(str(site))
            importlib.invalidate_caches()
            rc, doc = _build_json(project)
        importlib.invalidate_caches()
        assert rc != 0, doc
        assert [e["context"]["import_path"] for e in doc["errors"]] == ["ops"]
        assert "environment_hint" not in doc["build_refused"]

        rc, doc = _build_json(
            project, "--without-runtime-packages", "--allow-new-errors",
        )
        assert rc == 0, doc
        assert doc["build_environment"]["unverified_packages"] == [PACKAGE]
        manifest = load_manifest(project / "build")
        assert manifest.unverified_packages == (PACKAGE,)
        assert manifest.overridden_new_errors == (
            "MISSING_PACKAGE@src/scheduler.s0ma",
        )

    def test_a_dev_error_blocks_before_the_gate_as_before(
        self, project: Path, capsys: pytest.CaptureFixture[str],
    ) -> None:
        """The flag changes the gate's classification and nothing else:
        an error in the build's own mode still stops the build first."""
        (project / "src" / "broken.s0ma").write_text(
            "module broken\n    layer: DOMAIN\n", encoding="utf-8",
        )
        rc, doc = _build_json(project, "--without-runtime-packages")
        assert rc != 0
        assert doc["summary"]["errors"] >= 1
        assert "build_refused" not in doc
        assert not (project / "build" / MANIFEST_FILENAME).exists()


# ---------------------------------------------------------------------------
# The flag's edges
# ---------------------------------------------------------------------------


class TestTheFlagsEdges:
    @pytest.mark.parametrize("mode", ["strict", "release"])
    def test_verifying_modes_refuse_the_flag(
        self, project: Path, mode: str, capsys: pytest.CaptureFixture[str],
    ) -> None:
        rc = _build(project, "--without-runtime-packages", mode=mode)
        captured = capsys.readouterr()
        assert rc == EXIT_USAGE_ERROR
        assert f"does not combine with {mode} mode" in captured.err
        assert "Pass --mode dev or --mode migration here" in captured.err
        assert not (project / "build").exists()

    def test_a_strict_project_table_is_refused_by_name(
        self, project: Path, capsys: pytest.CaptureFixture[str],
    ) -> None:
        """The mode can come from [tool.s0ma].mode with no --mode flag.

        The refusal then names the mode rather than a flag nobody passed,
        and says that --mode dev overrides the table, which it does.
        """
        pyproject = project / "pyproject.toml"
        pyproject.write_text(
            pyproject.read_text("utf-8") + 'mode = "strict"\n', encoding="utf-8",
        )
        rc = _run(
            project, "build", str(project), "--no-cache",
            "--without-runtime-packages",
        )
        err = capsys.readouterr().err
        assert rc == EXIT_USAGE_ERROR
        assert "does not combine with strict mode" in err
        assert "with --mode strict" not in err
        assert "(either overrides [tool.s0ma].mode)" in err
        assert not (project / "build").exists()

        rc, doc = _build_json(project, "--without-runtime-packages", mode="dev")
        assert rc == 0, doc
        assert doc["build_environment"]["unverified_packages"] == [PACKAGE]

    def test_no_manifest_is_named_when_none_is_written(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str],
    ) -> None:
        """A tree without [tool.s0ma] and without --output-dir has no build
        directory, so the build writes no manifest and the note says
        nothing about one."""
        root = tmp_path / "loose"
        src = root / "src"
        src.mkdir(parents=True)
        (src / "scheduler.s0ma").write_text(_SCHEDULER, encoding="utf-8")
        (src / "ops.s0ma").write_text(_OPS_GREEN, encoding="utf-8")
        rc = _run(
            root, "build", str(src), "--mode", "dev", "--no-cache",
            "--without-runtime-packages", "--quiet",
        )
        out = capsys.readouterr().out
        assert rc == 0
        assert not list(root.rglob(MANIFEST_FILENAME))
        assert f"not verified here ({PACKAGE})." in out
        assert "build manifest" not in out

    def test_nothing_missing_is_an_ordinary_build(
        self, project: Path, package_present: None, capsys: pytest.CaptureFixture[str],
    ) -> None:
        """Where every requires: entry is found, the flag records nothing:
        the manifest is byte-identical to one built without the flag."""
        assert _build(project, "--quiet") == 0
        plain = (project / "build" / MANIFEST_FILENAME).read_bytes()
        rc, doc = _build_json(project, "--without-runtime-packages")
        assert rc == 0, doc
        assert doc["build_environment"]["unverified_packages"] == []
        flagged = (project / "build" / MANIFEST_FILENAME).read_bytes()
        assert flagged == plain
        assert "unverified_packages" not in flagged.decode("utf-8")
        assert load_manifest(project / "build").unverified_packages == ()
        capsys.readouterr()
        rc = _build(project, "--without-runtime-packages", "--quiet")
        assert "built without the project's runtime packages" not in capsys.readouterr().out
        assert rc == 0

    def test_migration_mode_takes_the_flag(
        self, project: Path, capsys: pytest.CaptureFixture[str],
    ) -> None:
        rc, doc = _build_json(project, "--without-runtime-packages", mode="migration")
        assert rc == 0, doc
        assert doc["build_environment"]["unverified_packages"] == [PACKAGE]

    def test_the_environment_codes_are_the_one_probe_of_the_environment(self) -> None:
        """Every other check-severity code is a statement about the source."""
        assert frozenset({"MISSING_PACKAGE"}) == ENVIRONMENT_CODES
        missing = S0maError(
            code="MISSING_PACKAGE", message="m", file="src/x.s0ma", line=0,
            column=0, severity="warning", remediation="",
        )
        mismatch = S0maError(
            code="PROVIDES_KEY_MISMATCH", message="m", file="src/x.s0ma",
            line=0, column=0, severity="warning", remediation="",
        )
        assert is_environment_diagnostic(missing)
        assert not is_environment_diagnostic(mismatch)
        # A requires: entry naming a s0ma module of the project is settled
        # by the source, so it is not an environment finding.
        names_a_module = S0maError(
            code="MISSING_PACKAGE", message="m", file="src/x.s0ma", line=0,
            column=0, severity="warning", remediation="",
            context={"import_path": "ops"},
        )
        assert is_environment_diagnostic(names_a_module)
        assert not is_environment_diagnostic(names_a_module, {"ops", "x"})
        assert is_environment_diagnostic(missing, {"ops", "x"})


# ---------------------------------------------------------------------------
# The manifest field
# ---------------------------------------------------------------------------


class TestTheManifestField:
    def test_round_trip_sorted_and_distinct(self, tmp_path: Path) -> None:
        from s0ma_dsl.codegen.build_manifest import build_manifest, emit_manifest

        manifest = build_manifest(
            project_name="wheel_app",
            build_dir="build",
            modules=[],
            transpiler_version="0.0.0",
            unverified_packages=("httpx", "anthropic", "httpx"),
        )
        assert manifest.unverified_packages == ("anthropic", "httpx")
        emit_manifest(manifest, tmp_path)
        raw = json.loads((tmp_path / MANIFEST_FILENAME).read_text("utf-8"))
        assert raw["unverified_packages"] == ["anthropic", "httpx"]
        assert load_manifest(tmp_path).unverified_packages == ("anthropic", "httpx")

    def test_a_manifest_without_the_key_loads_empty(self, tmp_path: Path) -> None:
        from s0ma_dsl.codegen.build_manifest import build_manifest, emit_manifest

        emit_manifest(
            build_manifest(
                project_name="wheel_app", build_dir="build", modules=[],
                transpiler_version="0.0.0",
            ),
            tmp_path,
        )
        raw = json.loads((tmp_path / MANIFEST_FILENAME).read_text("utf-8"))
        assert "unverified_packages" not in raw
        assert load_manifest(tmp_path).unverified_packages == ()

    def test_a_key_that_is_not_a_list_is_refused(self, tmp_path: Path) -> None:
        from s0ma_dsl.codegen.build_manifest import build_manifest, emit_manifest

        emit_manifest(
            build_manifest(
                project_name="wheel_app", build_dir="build", modules=[],
                transpiler_version="0.0.0",
            ),
            tmp_path,
        )
        path = tmp_path / MANIFEST_FILENAME
        raw = json.loads(path.read_text("utf-8"))
        raw["unverified_packages"] = "httpx"
        path.write_text(json.dumps(raw), encoding="utf-8")
        with pytest.raises(ManifestSchemaError, match="unverified_packages"):
            load_manifest(tmp_path)
