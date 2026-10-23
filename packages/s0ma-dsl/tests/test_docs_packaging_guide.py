"""The packaging guide's code is run, not quoted.

``docs/guides/packaging.md`` writes out two files in full: the hatchling
build hook that transpiles the ``.s0ma`` sources at wheel-build time, and
the bootstrap that locates the build at runtime and refuses any other copy
of it. A guide whose listings nobody runs is the drift this repository's
documentation exists to prevent, so this suite lifts both listings off the
page, writes them into the project the page describes, and runs them the
way a packaging tool and an installed application would:

* the hook, against a build environment that lacks the runtime package,
  with a check baseline recorded where the package was present (fr3d's
  shape), builds into the wheel's own directory, records the unverified
  package, leaves the developer's build directory and the baseline alone,
  empties its directory so a deleted module is not shipped, and fails the
  wheel build on a new contract error;
* the bootstrap runs the checkout's build in a checkout and in an editable
  install, finds the wheel's build beside the package in a site-packages
  layout, imports the modules in manifest order from the located
  directory, and refuses to run when a module or the build package has
  been imported from somewhere else, the registry refusing the case where
  a module came in through the package.

hatchling is not a dependency of this package, so the hook is run against
a stand-in for its hook interface with the two members the hook uses: the
project root and the display methods.
"""

from __future__ import annotations

import importlib
import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
import textwrap
from contextlib import contextmanager, redirect_stdout
from io import StringIO
from pathlib import Path
from types import ModuleType
from typing import TYPE_CHECKING

import pytest

from s0ma_dsl.check_baseline import baseline_path
from s0ma_dsl.cli.main import S0maCLI
from s0ma_dsl.codegen.build_manifest import load_manifest

if TYPE_CHECKING:
    from collections.abc import Iterator

REPO_ROOT = Path(__file__).resolve().parents[3]
GUIDE = REPO_ROOT / "docs" / "guides" / "packaging.md"

requires_checkout = pytest.mark.skipif(
    not GUIDE.is_file(), reason="not a git checkout (wheel-install context)"
)
pytestmark = requires_checkout

#: The runtime package the application has and the build environment lacks;
#: the guide's example requires ``croniter``, and the test substitutes a name
#: no real distribution can shadow.
PACKAGE = "pkg_the_application_installs"

_FENCE = re.compile(r"```(?P<lang>\w+)\n(?P<body>.*?)```", re.DOTALL)


def _listing(language: str, marker: str) -> str:
    """The guide's fenced block in *language* whose text holds *marker*."""
    text = GUIDE.read_text(encoding="utf-8")
    for found in _FENCE.finditer(text):
        if found.group("lang") == language and marker in found.group("body"):
            return found.group("body")
    raise AssertionError(f"the guide has no {language} listing holding {marker!r}")


def _hook_source() -> str:
    return _listing("python", "class S0maBuildHook")


def _bootstrap_source() -> str:
    return _listing("python", "def locate_build")


def _pyproject_source() -> str:
    return _listing("toml", "[tool.s0ma]")


# ---------------------------------------------------------------------------
# The project the page describes
# ---------------------------------------------------------------------------

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

_AGENDA_HEAD = """\
module agenda
    layer: APPLICATION
    version: 0.1.0
    intent: "Assemble the operations the scheduler's callers run."
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
    intent: "Return a dict of operations."
    expects: "no arguments"
    guarantees: "returns a dict of operations"
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
_AGENDA_GREEN = _AGENDA_HEAD + "        return {'assemble': assemble, 'validate': validate}\n"
_AGENDA_BROKEN = _AGENDA_HEAD + "        return {'assemble': assemble, 'validat': validate}\n"
#: A third module, built into the wheel once and then deleted from the sources.
_LEGACY = _AGENDA_GREEN.replace("module agenda", "module legacy").replace(
    "assembler", "legacy_assembler",
)


def _make_project(root: Path) -> Path:
    """The guide's project: its pyproject, hook and bootstrap, lifted off
    the page, around two modules and one runtime package."""
    (root / "src" / "nightwatch").mkdir(parents=True)
    (root / "tests").mkdir()
    pyproject = _pyproject_source().replace(
        'dependencies = ["s0ma-core", "s0ma-dsl", "croniter"]',
        f'dependencies = ["s0ma-core", "s0ma-dsl", "{PACKAGE}"]',
    )
    (root / "pyproject.toml").write_text(pyproject, encoding="utf-8")
    (root / "hatch_build.py").write_text(_hook_source(), encoding="utf-8")
    (root / "src" / "nightwatch" / "__init__.py").write_text(
        '"""nightwatch."""\n', encoding="utf-8",
    )
    (root / "src" / "nightwatch" / "bootstrap.py").write_text(
        _bootstrap_source(), encoding="utf-8",
    )
    (root / "src" / "scheduler.s0ma").write_text(_SCHEDULER, encoding="utf-8")
    (root / "src" / "agenda.s0ma").write_text(_AGENDA_GREEN, encoding="utf-8")
    return root


def _make_site(root: Path) -> Path:
    """A directory holding the runtime package, for the environments that
    have it: the developer's checks and the running application."""
    package = root / "runtime-site" / PACKAGE
    package.mkdir(parents=True)
    (package / "__init__.py").write_text(
        "def next_after(expression, start):\n    return start\n",
        encoding="utf-8",
    )
    return package.parent


@pytest.fixture
def project(tmp_path: Path) -> Path:
    return _make_project(tmp_path / "nightwatch")


@pytest.fixture
def runtime_site(tmp_path: Path) -> Path:
    return _make_site(tmp_path)


def _check_strict_where_the_package_is(root: Path, site: Path) -> bytes:
    """The developer's strict check, green, recording the baseline."""
    with pytest.MonkeyPatch.context() as mp:
        mp.syspath_prepend(str(site))
        importlib.invalidate_caches()
        out = StringIO()
        with redirect_stdout(out):
            rc = S0maCLI().run(
                ["--project-root", str(root), "check", "--mode", "strict"]
            )
        assert rc == 0, out.getvalue()
    importlib.invalidate_caches()
    return baseline_path(root).read_bytes()


# ---------------------------------------------------------------------------
# The hook, run as hatchling runs it
# ---------------------------------------------------------------------------


class _App:
    """The two display methods the hook calls on hatchling's app."""

    def __init__(self) -> None:
        self.lines: list[str] = []

    def display_info(self, message: str) -> None:
        self.lines.append(message)

    def display_warning(self, message: str) -> None:
        self.lines.append(message)


@contextmanager
def _hook_interface() -> Iterator[None]:
    """A stand-in for ``hatchling.builders.hooks.plugin.interface`` with
    the two members the hook uses: the project root and the app."""
    interface = ModuleType("hatchling.builders.hooks.plugin.interface")

    class BuildHookInterface:
        def __init__(self, root: str, app: _App) -> None:
            self.root = root
            self.app = app

    interface.BuildHookInterface = BuildHookInterface  # type: ignore[attr-defined]
    parents = (
        "hatchling",
        "hatchling.builders",
        "hatchling.builders.hooks",
        "hatchling.builders.hooks.plugin",
    )
    with pytest.MonkeyPatch.context() as mp:
        for name in parents:
            if name not in sys.modules:
                mp.setitem(sys.modules, name, ModuleType(name))
        mp.setitem(sys.modules, interface.__name__, interface)
        yield


def _load_hook(root: Path) -> type:
    spec = importlib.util.spec_from_file_location(
        f"hatch_build_{abs(hash(str(root)))}", root / "hatch_build.py",
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.S0maBuildHook


def _run_hook(root: Path) -> _App:
    """``initialize`` as hatchling calls it. The build runs in a subprocess
    that has what this interpreter has and nothing more: the runtime
    package lives on a directory no interpreter was given, which is what a
    PEP 517 build environment looks like to the build."""
    app = _App()
    with _hook_interface():
        _load_hook(root)(str(root), app).initialize("standard", {})
    return app


class TestTheHook:
    def test_it_builds_the_wheel_directory_where_the_package_is_absent(
        self, project: Path, runtime_site: Path,
    ) -> None:
        """fr3d's shape, with the guide's hook: a green strict baseline
        recorded where the package is, then the wheel build where it is
        not. The hook builds, records the package as unverified, and
        touches neither the developer's build nor the baseline."""
        record = _check_strict_where_the_package_is(project, runtime_site)

        app = _run_hook(project)

        wheel_build = project / ".s0ma_wheel_build"
        manifest = load_manifest(wheel_build)
        assert {entry.name for entry in manifest.modules} == {"agenda", "scheduler"}
        assert manifest.unverified_packages == (PACKAGE,)
        assert manifest.overridden_new_errors == ()
        assert not (wheel_build / ".s0ma.cache").exists()
        assert not (project / "build").exists()
        assert baseline_path(project).read_bytes() == record
        assert any("Building the .s0ma sources" in line for line in app.lines)

    def test_it_fails_the_wheel_build_on_a_new_contract_error(
        self, project: Path, runtime_site: Path,
    ) -> None:
        _check_strict_where_the_package_is(project, runtime_site)
        (project / "src" / "agenda.s0ma").write_text(_AGENDA_BROKEN, encoding="utf-8")

        with pytest.raises(RuntimeError) as refused:
            _run_hook(project)
        message = str(refused.value)
        assert "refused the wheel build" in message
        assert "PROVIDES_KEY_MISMATCH" in message
        assert "BUILD REFUSED" in message
        assert not (project / ".s0ma_wheel_build").exists()

    def test_a_module_deleted_from_the_sources_is_not_shipped(
        self, project: Path,
    ) -> None:
        """The manifest keeps what earlier builds recorded, so a wheel
        directory built into twice would ship a module whose source is
        gone. The hook empties the directory first."""
        legacy = project / "src" / "legacy.s0ma"
        legacy.write_text(_LEGACY, encoding="utf-8")
        _run_hook(project)
        wheel_build = project / ".s0ma_wheel_build"
        assert "legacy" in {entry.name for entry in load_manifest(wheel_build).modules}

        legacy.unlink()
        _run_hook(project)

        manifest = load_manifest(wheel_build)
        assert {entry.name for entry in manifest.modules} == {"agenda", "scheduler"}
        assert "legacy" not in manifest.topological_import_order
        assert not (wheel_build / "legacy.py").exists()

    def test_the_hook_passes_the_flag_rather_than_retrying(self) -> None:
        source = _hook_source()
        assert "--without-runtime-packages" in source
        assert "--allow-new-errors" not in source
        assert "--no-cache" in source and "--force-output-dir" in source
        assert '"--mode", "dev"' in source


# ---------------------------------------------------------------------------
# The bootstrap, run as an installed application runs it
# ---------------------------------------------------------------------------

_START = textwrap.dedent(
    """
    import importlib.util, json, sys
    from pathlib import Path
    from s0ma.exceptions import S0maError
    bootstrap = Path(sys.argv[1])
    spec = importlib.util.spec_from_file_location("nightwatch.bootstrap", bootstrap)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    {prelude}
    try:
        modules = module.start()
    except (RuntimeError, S0maError) as refused:
        print(json.dumps({{"refused": str(refused), "by": type(refused).__name__}}))
    else:
        print(json.dumps({{
            "build_dir": str(module.locate_build()),
            "modules": {{name: m.__file__ for name, m in modules.items()}},
            "one": module.import_build_module("scheduler").__file__,
        }}))
    """
)


def _start(bootstrap: Path, site: Path, prelude: str = "") -> dict:
    """Run the guide's ``start`` in a fresh interpreter, with the runtime
    package importable the way it is where the application runs."""
    env = dict(os.environ)
    env["PYTHONPATH"] = os.pathsep.join(
        p for p in (str(site), env.get("PYTHONPATH", "")) if p
    )
    result = subprocess.run(
        [sys.executable, "-c", _START.format(prelude=prelude), str(bootstrap)],
        check=False, capture_output=True, encoding="utf-8", env=env,
    )
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout.strip().splitlines()[-1])


def _build_checkout(root: Path, site: Path) -> None:
    """The developer's build into build/, where the package is installed."""
    with pytest.MonkeyPatch.context() as mp:
        mp.syspath_prepend(str(site))
        importlib.invalidate_caches()
        out = StringIO()
        with redirect_stdout(out):
            rc = S0maCLI().run(
                ["--project-root", str(root), "build", str(root), "--no-cache", "--quiet"]
            )
        assert rc == 0, out.getvalue()
    importlib.invalidate_caches()


class TestTheBootstrap:
    def test_a_checkout_runs_the_build_beside_src(
        self, project: Path, runtime_site: Path,
    ) -> None:
        _build_checkout(project, runtime_site)
        bootstrap = project / "src" / "nightwatch" / "bootstrap.py"

        found = _start(bootstrap, runtime_site)

        build_dir = (project / "build").resolve()
        assert Path(found["build_dir"]) == build_dir
        assert set(found["modules"]) == {"agenda", "scheduler"}
        recorded = load_manifest(build_dir).topological_import_order
        assert list(found["modules"]) == [name for name in recorded if name in found["modules"]]
        for location in found["modules"].values():
            assert Path(location).resolve().parent == build_dir
        assert Path(found["one"]).resolve().parent == build_dir

    def test_an_installed_wheel_runs_the_build_beside_the_package(
        self, project: Path, runtime_site: Path, tmp_path: Path,
    ) -> None:
        """The site-packages layout: nightwatch/ and nightwatch_build/
        side by side, no checkout anywhere above them."""
        _check_strict_where_the_package_is(project, runtime_site)
        _run_hook(project)
        site_packages = tmp_path / "site-packages"
        shutil.copytree(project / "src" / "nightwatch", site_packages / "nightwatch")
        shutil.copytree(project / ".s0ma_wheel_build", site_packages / "nightwatch_build")

        found = _start(site_packages / "nightwatch" / "bootstrap.py", runtime_site)

        build_dir = (site_packages / "nightwatch_build").resolve()
        assert Path(found["build_dir"]) == build_dir
        for location in found["modules"].values():
            assert Path(location).resolve().parent == build_dir

    def test_a_checkout_wins_over_the_copy_an_editable_install_left(
        self, project: Path, runtime_site: Path, tmp_path: Path,
    ) -> None:
        """The editable layout: the bootstrap is imported from the checkout,
        and the install's copy of the wheel's build sits in site-packages,
        importable by its package name. The checkout's build/ is what runs,
        and the copy is never imported."""
        _check_strict_where_the_package_is(project, runtime_site)
        _run_hook(project)
        _build_checkout(project, runtime_site)
        site_packages = tmp_path / "site-packages"
        shutil.copytree(project / ".s0ma_wheel_build", site_packages / "nightwatch_build")
        prelude = f"sys.path.insert(0, {str(site_packages)!r})"

        found = _start(project / "src" / "nightwatch" / "bootstrap.py", runtime_site, prelude)

        build_dir = (project / "build").resolve()
        assert Path(found["build_dir"]) == build_dir
        for location in found["modules"].values():
            assert Path(location).resolve().parent == build_dir

    def test_it_refuses_a_build_package_imported_from_elsewhere(
        self, project: Path, runtime_site: Path, tmp_path: Path,
    ) -> None:
        """The stale copy: nightwatch_build imported as a package from a
        site-packages directory while the located build is the checkout's."""
        _check_strict_where_the_package_is(project, runtime_site)
        _run_hook(project)
        _build_checkout(project, runtime_site)
        stale = tmp_path / "stale-site-packages"
        shutil.copytree(project / ".s0ma_wheel_build", stale / "nightwatch_build")
        prelude = f"sys.path.insert(0, {str(stale)!r}); import nightwatch_build"

        found = _start(project / "src" / "nightwatch" / "bootstrap.py", runtime_site, prelude)

        assert found["by"] == "RuntimeError"
        assert "nightwatch_build package" in found["refused"]
        assert "never as nightwatch_build.<module>" in found["refused"]

    def test_the_registry_refuses_a_module_imported_through_the_package(
        self, project: Path, runtime_site: Path, tmp_path: Path,
    ) -> None:
        """A module imported as nightwatch_build.<module> registered its
        components, so the bare import of the located build cannot register
        them again: the registry refuses before the bootstrap's own check."""
        _run_hook(project)
        _build_checkout(project, runtime_site)
        stale = tmp_path / "stale-site-packages"
        shutil.copytree(project / ".s0ma_wheel_build", stale / "nightwatch_build")
        prelude = f"sys.path.insert(0, {str(stale)!r}); import nightwatch_build.scheduler"

        found = _start(project / "src" / "nightwatch" / "bootstrap.py", runtime_site, prelude)

        assert found["by"] == "RegistrationError"
        assert "already registered" in found["refused"]
        assert "nightwatch_build.scheduler" in found["refused"]

    def test_it_refuses_a_module_already_imported_from_another_build(
        self, project: Path, runtime_site: Path, tmp_path: Path,
    ) -> None:
        _check_strict_where_the_package_is(project, runtime_site)
        _run_hook(project)
        _build_checkout(project, runtime_site)
        other = tmp_path / "other"
        shutil.copytree(project / ".s0ma_wheel_build", other)
        prelude = f"sys.path.insert(0, {str(other)!r}); import scheduler"

        found = _start(project / "src" / "nightwatch" / "bootstrap.py", runtime_site, prelude)

        assert found["by"] == "RuntimeError"
        assert "module 'scheduler' from" in found["refused"]

    def test_no_build_anywhere_says_what_to_run(self, project: Path, runtime_site: Path) -> None:
        env = dict(os.environ)
        env["PYTHONPATH"] = os.pathsep.join(
            p for p in (str(runtime_site), env.get("PYTHONPATH", "")) if p
        )
        result = subprocess.run(
            [
                sys.executable, "-c",
                textwrap.dedent(
                    """
                    import importlib.util, sys
                    location = importlib.util.spec_from_file_location
                    spec = location("nightwatch.bootstrap", sys.argv[1])
                    module = importlib.util.module_from_spec(spec)
                    spec.loader.exec_module(module)
                    try:
                        module.locate_build()
                    except RuntimeError as exc:
                        print(exc)
                    """
                ),
                str(project / "src" / "nightwatch" / "bootstrap.py"),
            ],
            check=False, capture_output=True, encoding="utf-8", env=env,
        )
        assert result.returncode == 0, result.stderr
        assert "run `s0ma build` in the checkout" in result.stdout
