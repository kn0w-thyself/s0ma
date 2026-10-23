# Packaging a s0ma project as a wheel

A s0ma project is written in `.s0ma` files, and what runs is the Python that `s0ma build` writes from them. That is the one thing that makes packaging such a project different from packaging any other Python project: the wheel has to carry the build, and the build has to be made at the moment the wheel is made. This page walks through doing that, with the example project below, so that `pip install .`, `pip install -e .` and `pip install dist/nightwatch-*.whl` all work the way they do for any other project.

The example is called `nightwatch`. It has two `.s0ma` modules under `src/`, a Python package at `src/nightwatch/` that holds the plain-Python bootstrap, and a test root at `tests/`. Its `[tool.s0ma]` table says `source_roots = ["src"]`, `test_roots = ["tests"]` and `build_dir = "build"`, and `src/scheduler.s0ma` has `requires: [croniter]`, a package the application needs at runtime. The `pyproject.toml`, the hook and the bootstrap below are not just quoted: `packages/s0ma-dsl/tests/test_docs_packaging_guide.py` lifts them off this page, writes them into the project described here, and builds and runs that project before the page ships.

## Contents

- [1. What the wheel has to carry](#1-what-the-wheel-has-to-carry)
- [2. The build hook](#2-the-build-hook)
- [3. The environment the hook runs in](#3-the-environment-the-hook-runs-in)
- [4. The check baseline and the gate](#4-the-check-baseline-and-the-gate)
- [5. An editable install and a wheel install](#5-an-editable-install-and-a-wheel-install)
- [6. Two build directories, kept apart](#6-two-build-directories-kept-apart)
- [7. Locating the build at runtime](#7-locating-the-build-at-runtime)
- [8. The whole loop](#8-the-whole-loop)
- [Where to go next](#where-to-go-next)

## 1. What the wheel has to carry

Two things: the Python package you wrote, and the directory the build wrote. [What the build writes](what-the-build-writes.md) goes through that directory file by file; for packaging, the facts that matter are that every module is a flat `.py` file imported by its bare name, that `build.s0ma.json`, the manifest, lists the modules and the order to load them in, and that nothing in the directory is yours to edit.

The directory cannot ship under its checkout name. `build/` is the name `[tool.s0ma].build_dir` gives it in a checkout, and a top-level `build` in site-packages would collide with the `build` package that builds wheels. So the wheel carries it under a name that belongs to the project, `nightwatch_build/`, beside the `nightwatch/` package. The bootstrap in section 7 knows both places.

The package itself needs `s0ma-core` and `s0ma-dsl` at runtime, because every built module imports them to register what it declares. They go in `[project].dependencies` next to the packages your `requires:` lines name; the build asks for them with `HOST_RUNTIME_UNDECLARED` when they are missing. Until s0ma is published on the package index, neither name resolves there, so `[project].dependencies` and the `[build-system].requires` of section 2 have to point at the two wheels the root README's Install section builds. `uv add` with their paths writes the names into `[project].dependencies` and the paths into `[tool.uv.sources]`, a table uv also applies to `[build-system].requires`. pip reads no such table, so for pip each entry names its wheel directly, `s0ma-core @ file:///path/to/s0ma_core-<version>-py3-none-any.whl`, and hatchling accepts an entry like that in `[project].dependencies` only with `allow-direct-references = true` under `[tool.hatch.metadata]`.

## 2. The build hook

The build system is hatchling, and hatchling lets a project run its own code before it packages a wheel: a build hook. The hook's job is one command, `s0ma build`, run into a directory the wheel then includes and that the hook empties first. Here is `pyproject.toml`:

```toml
[build-system]
requires = ["hatchling", "s0ma-core", "s0ma-dsl"]
build-backend = "hatchling.build"

[project]
name = "nightwatch"
version = "0.1.0"
requires-python = ">=3.11"
dependencies = ["s0ma-core", "s0ma-dsl", "croniter"]

[tool.hatch.build.targets.wheel]
packages = ["src/nightwatch"]

[tool.hatch.build.targets.wheel.force-include]
".s0ma_wheel_build" = "nightwatch_build"

[tool.hatch.build.targets.wheel.hooks.custom]
path = "hatch_build.py"

[tool.hatch.build.targets.sdist]
exclude = ["/build", "/.s0ma_wheel_build", "/.s0ma", "/dist"]

[tool.s0ma]
source_roots = ["src"]
test_roots = ["tests"]
build_dir = "build"
bootstrap_files = ["src/nightwatch/__init__.py", "src/nightwatch/bootstrap.py"]
```

Read it table by table:

- `[build-system].requires` names `s0ma-core` and `s0ma-dsl` as well as hatchling, because the hook runs `s0ma build`. It is also all the build environment holds, which is what section 3 is about.
- `packages` ships `src/nightwatch/`, your plain Python.
- `force-include` ships the directory the hook builds, `.s0ma_wheel_build/`, under the name `nightwatch_build/` in the wheel.
- `hooks.custom` names the hook file.
- The sdist excludes the two build directories, the working state in `.s0ma/`, and `dist/`. A source distribution carries the `.s0ma` sources and the hook, and whoever builds a wheel from it runs the hook again.
- `[tool.s0ma].bootstrap_files` declares the two plain-Python files as the bootstrap they are, so `s0ma verify` does not report them as unknown Python.

And here is `hatch_build.py`, in full:

```python
"""Hatch build hook: run `s0ma build` before the wheel is packaged.

The wheel ships `.s0ma_wheel_build/` as `nightwatch_build/` (the
force-include table in pyproject.toml), so every wheel or editable
build first empties that directory and builds the `.s0ma` sources
into it. The developer's `build/` is never written here.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

from hatchling.builders.hooks.plugin.interface import BuildHookInterface


class S0maBuildHook(BuildHookInterface):
    PLUGIN_NAME = "s0ma-build"

    def initialize(self, version: str, build_data: dict[str, Any]) -> None:
        root = Path(self.root)
        wheel_build = root / ".s0ma_wheel_build"
        if wheel_build.exists():
            shutil.rmtree(wheel_build)
        command = [
            sys.executable, "-m", "s0ma_dsl",
            "--project-root", str(root),
            "build", "src",
            "--mode", "dev",
            "--output-dir", str(wheel_build),
            "--force-output-dir",
            "--no-cache",
            "--without-runtime-packages",
        ]
        self.app.display_info("Building the .s0ma sources into .s0ma_wheel_build/")
        result = subprocess.run(
            command, cwd=root, check=False, capture_output=True,
            encoding="utf-8", errors="replace",
        )
        if result.returncode != 0:
            raise RuntimeError(
                "`s0ma build` refused the wheel build. Fix what it reports "
                "and build again.\n" + result.stdout + result.stderr
            )
```

The hook is plain Python rather than a `.s0ma` module because it runs before the project has been built or installed: there is no build to import yet. It is not a runtime component either, which is why it is not in `bootstrap_files`; `s0ma verify .` lists it as unknown plain Python, which it is.

Each option on the command does one job:

| Option | Why it is there |
|---|---|
| `python -m s0ma_dsl` | The `s0ma` script may not be on the path inside a build environment; the module form works wherever `s0ma-dsl` is installed. |
| `--project-root` | Says which project this is, rather than leaving it to the working directory. |
| `build src` | Builds the directory `[tool.s0ma].source_roots` names and nothing else. The test root is not shipped. |
| `--mode dev` | The strictness mode `--without-runtime-packages` needs; section 3 says why. |
| `--output-dir`, `--force-output-dir` | Builds into the wheel's own directory. Without the second flag, an output directory that disagrees with `[tool.s0ma].build_dir` is refused, and here the disagreement is the point; section 6 says why. |
| `--no-cache` | The build's cache is memory for the next build, not something to ship. |
| `--without-runtime-packages` | Says what section 3 is about. |

A project with more than one source root runs one build per root into the same directory, passing the other roots with `--include` so that `uses:` entries across roots resolve, the way `s0ma test` builds a project.

## 3. The environment the hook runs in

When pip or uv builds a wheel, it does not run the build backend in your environment. It makes a fresh one, installs what `[build-system].requires` names and what those packages need, and runs hatchling there. That is build isolation, and it is what lets a project be installed on a machine that has nothing else set up. It also means the hook's `s0ma build` runs where `croniter` is not installed: of `[project].dependencies`, the build environment holds only what `[build-system].requires` names as well.

`s0ma build` checks every `requires:` entry, `deferred_requires:` entries included, by asking the interpreter it runs in whether the package can be found. In the isolated environment, `croniter` cannot, so the build reports `MISSING_PACKAGE` for it. In dev mode that is a warning and the build goes on; in strict and release mode it is an error and the build stops, which is the first reason the hook builds in dev mode. The entry is not wrong. The application will have `croniter`, because its own dependencies say so. The environment the build runs in simply is not the environment the application runs in, and the build has no way to tell the difference on its own: a misspelled `requires:` entry looks exactly the same to it.

So the hook tells it. `--without-runtime-packages` says that the environment this build runs in does not hold the project's runtime packages. With that said, a `requires:` entry the build cannot find is recorded instead of counted by the gate section 4 describes: the manifest, `build.s0ma.json`, lists the package the build looked for under `unverified_packages`, and `--format json` carries the same record as `build_environment`. The warning is still printed, and the text output adds one line saying which packages were not verified. A build made where every package is found records nothing, and its manifest is the same as one built without the flag.

Verification is not skipped. It moves to where it can be done. `s0ma check --mode strict`, run in your own environment and in CI, where the packages are installed, still reports a `requires:` entry that is missing for real, and `s0ma verify-host` imports the built modules under the application's own interpreter. Strict and release mode are the modes that verify every entry, so they refuse the flag: `s0ma build --mode strict --without-runtime-packages` is a usage error that says so, which is the second reason the hook builds in dev mode.

## 4. The check baseline and the gate

There is a second place where the missing package would have stopped the build, and it is the one that caught fr3d, the project this page was written for.

Every full-project `s0ma check` and `s0ma build` records the check-severity errors it found in `.s0ma/check-baseline.json`, the project's check baseline. It is working state, kept per machine, and it belongs out of version control with the rest of `.s0ma/`. The next build compares what it finds with that record, and an error that is not in it is NEW: one your edit introduced. The build refuses NEW check errors, and it ranks them the way `s0ma check` does, in strict terms, even in a dev build. That is the gate, and it is why a dev-mode warning can still stop a build. The refusal lists the errors, and `--allow-new-errors` is the override: build anyway, and record under `overridden_new_errors` in the manifest what was waved through.

Now put the two runs together. You run `s0ma check --mode strict` in your environment, where `croniter` is installed. It is green, and the baseline records no errors. Then pip builds the wheel in the isolated environment, where `croniter` is not installed, and `MISSING_PACKAGE` is a check error that the baseline does not hold. Nothing was edited, but the gate sees a NEW check error and refuses. A fresh clone, which has no baseline, builds; a developer's checkout, which usually has one, does not.

`--without-runtime-packages` is the answer to that too, and the refusal names it: when every NEW error is `MISSING_PACKAGE`, the refusal says the flag exists and what it does. With the flag, a `requires:` entry the build cannot find is an environment finding rather than a new contract error, so it does not refuse the build; any other NEW check error still does, and so does a `requires:` entry that names one of your own s0ma modules, because that entry belongs in `uses:` and no environment supplies it. The hook fails the wheel build with the refusal in its message, which is what you want: a wheel is not the place to find out that a `provides:` list and a body disagree. The two records are kept apart. `unverified_packages` is what the build could not check here, `overridden_new_errors` is what somebody chose to wave through, and a build made with the flag alone never writes the second.

The baseline is left alone too. Only a full-project build refreshes it, so the hook's build of `src` never would; and a full-project build made with the flag records nothing either, because what a build finds missing in a foreign environment says nothing about this checkout. The next full-project check or build made where the packages are installed records it.

## 5. An editable install and a wheel install

Both run the hook. Hatchling builds an editable install as a wheel too, so `pip install -e .` and `uv pip install -e .` transpile the sources into `.s0ma_wheel_build/` exactly as `pip install .` does. What differs is what lands in site-packages:

| | `pip install -e .` | `pip install .` or a wheel |
|---|---|---|
| `nightwatch/` | A path file that puts the checkout's `src/` on `sys.path`, so the package is imported from `src/nightwatch/`. Edits are live. | A copy. |
| `nightwatch_build/` | A copy, made from `.s0ma_wheel_build/` at install time. | A copy. |
| The build the bootstrap runs | The checkout's `build/`, written by `s0ma build`. The locator in section 7 looks beside `src/`, not in site-packages. | `nightwatch_build/` in site-packages, the only build there is. |

The copy an editable install leaves in site-packages is the trap. It was current when you installed; it is not updated by `s0ma build`, so it goes stale the first time you build again, and it is importable by its package name from anywhere in the environment. Nothing in the bootstrap imports it, and section 7 says what stops a process that does. When you need the build in site-packages refreshed, reinstall.

## 6. Two build directories, kept apart

The checkout has `build/`, which `s0ma build` and `s0ma test` write. Run with no directory named, both build the test roots as well as the source roots, so `build/` holds the test modules beside the source modules. The manifest keeps what earlier builds recorded, and the files of a module stay in the directory until `s0ma build --clean`. If the hook built into that same directory, the wheel would carry whatever tests and leftovers were there. So the wheel's build gets its own directory, `.s0ma_wheel_build/`, which only the hook writes, and the hook empties it before every build: the same rule holds there, and a module whose source you deleted would otherwise ship in the next wheel.

`s0ma build` refuses an `--output-dir` that disagrees with `[tool.s0ma].build_dir`, because a build landing in two places is the ordinary way a stale copy comes to be. The hook passes `--force-output-dir` to say that the disagreement is meant, and the build prints one line to say it noticed.

Keep all four out of version control: `build/`, `.s0ma_wheel_build/`, `dist/` and `.s0ma/`. The first two are derived from the sources, the third is the packaging tool's output, and the fourth is working state the check baseline lives in.

## 7. Locating the build at runtime

The built modules are imported by their bare names from whichever directory holds the build, and the application has to find that directory before it can import anything. There are two places it can be, one for each layout, and the bootstrap tries both. Here is `src/nightwatch/bootstrap.py`:

```python
"""Locate the build this install carries, and import it from there."""

from __future__ import annotations

import importlib
import os
import sys
from pathlib import Path
from types import ModuleType

from s0ma.bootstrap import bootstrap_imports

BUILD_PACKAGE = "nightwatch_build"


def locate_build() -> Path:
    """The build directory this copy of the package runs with.

    A checkout keeps the developer's build beside src/; an installed wheel
    carries the build next to the package in site-packages. The first
    candidate holding a manifest wins. An editable install imports this
    file from the checkout, so it runs the build `s0ma build` writes and
    never the copy the install left in site-packages.
    """
    here = Path(__file__).resolve()
    candidates = (
        here.parents[2] / "build",         # <checkout>/src/nightwatch/bootstrap.py
        here.parents[1] / BUILD_PACKAGE,   # <site-packages>/nightwatch/bootstrap.py
    )
    for candidate in candidates:
        if (candidate / "build.s0ma.json").is_file():
            return candidate.resolve()
    raise RuntimeError(
        "no s0ma build found: run `s0ma build` in the checkout, "
        "or install the wheel again"
    )


def _origin(module: ModuleType) -> Path | None:
    """The directory a module was loaded from, or None when it has none."""
    paths = list(getattr(module, "__path__", None) or [])
    if paths:
        return Path(paths[0]).resolve()
    location = getattr(module, "__file__", None)
    return Path(location).resolve().parent if location else None


def _elsewhere(module: ModuleType, build_dir: Path) -> Path | None:
    """Where the module came from, when that is not the located build."""
    origin = _origin(module)
    if origin is None or os.path.normcase(str(origin)) == os.path.normcase(str(build_dir)):
        return None
    return origin


def start() -> dict[str, ModuleType]:
    """Import every source module of the located build, and nothing else."""
    build_dir = locate_build()
    modules = bootstrap_imports(build_dir, roles=("source",))
    strays = [
        f"module {name!r} from {origin}"
        for name, module in modules.items()
        if (origin := _elsewhere(module, build_dir)) is not None
    ]
    package = sys.modules.get(BUILD_PACKAGE)
    if package is not None and (origin := _elsewhere(package, build_dir)) is not None:
        strays.append(f"the {BUILD_PACKAGE} package from {origin}")
    if strays:
        raise RuntimeError(
            f"nightwatch runs only the build at {build_dir}, but this process "
            f"holds {'; '.join(strays)}. Import built modules through "
            f"nightwatch.bootstrap, never as {BUILD_PACKAGE}.<module>."
        )
    return modules


def import_build_module(name: str) -> ModuleType:
    """One built module by its bare name, from the located build only."""
    build_dir = locate_build()
    entry = str(build_dir)
    if entry not in sys.path:
        sys.path.insert(0, entry)
    module = importlib.import_module(name)
    origin = _elsewhere(module, build_dir)
    if origin is not None:
        raise ImportError(f"{name!r} is imported from {origin}, not from the build at {build_dir}")
    return module
```

`locate_build` is the part that knows the two layouts. In a checkout, `bootstrap.py` is at `src/nightwatch/bootstrap.py` and the build is two directories up, at `build/`; in an installed wheel, it is at `site-packages/nightwatch/bootstrap.py` and the build is one directory up, at `nightwatch_build/`. An editable install is the first layout: Python imports `bootstrap.py` from the checkout, so the locator finds `build/`, the build `s0ma build` keeps current, and never looks at the copy the install left in site-packages. With no `build/` yet, it refuses and says to run `s0ma build`.

`start` imports the build with `bootstrap_imports` from `s0ma-core`, which puts the build directory first on `sys.path` and imports each module by its bare name, in the order the manifest records, so that every module is registered after the modules it uses. `roles=("source",)` leaves out the modules the manifest records as tests, which matters in a checkout, where the test roots are built into the same directory. `s0ma test` records their modules as tests; `s0ma build` with no directory named records them as source modules, so after such a build the bootstrap imports them too, until the next `s0ma test`.

Then it checks where everything came from, and that check is the reason the build is located rather than imported as a package. A built module registers its components when Python imports it. `scheduler` imported by its bare name from the located build, and `nightwatch_build.scheduler` imported through the package an install left in site-packages, are two different modules to Python, and after the next `s0ma build` they hold two different bodies. Importing both would register the same components twice, and the registry refuses the second registration with a `RegistrationError` that names both modules. What the registry cannot catch is a copy that registers nothing new: a module imported by its bare name from another directory before `start` ran, which Python hands back to `bootstrap_imports` as if it were the located one, or the `nightwatch_build` package itself, whose `__init__.py` declares nothing. So `start` refuses if any module it imported came from somewhere else, or if the `nightwatch_build` package has been imported from a directory other than the located one, and the message says what to do instead: import built modules through the bootstrap. `import_build_module` is that way in for code outside the bootstrap that needs one module by name.

## 8. The whole loop

In the checkout, where the runtime packages are installed:

```bash
s0ma check --mode strict      # verifies every requires: entry, records the baseline
s0ma build                    # the developer's build of every root, into build/
s0ma test                     # builds again, and runs the tests
```

Then the wheel. Either command builds in an isolated environment and runs the hook:

```bash
uv build --wheel
```

```bash
pyproject-build --wheel
```

`pyproject-build` is the command the `build` package installs. Run it by that name rather than as `python -m build`: from the checkout, `python -m build` finds the checkout's `build/` first, and the `__init__.py` that `s0ma build` writes there makes it a package that hides the tool.

Install the result into a fresh environment and run the application; the bootstrap finds `nightwatch_build/` beside the package. Or install the checkout as editable, and the bootstrap finds `build/`. When the wheel build is refused, the hook's error carries `s0ma build`'s own report. A usage error that names strict or release mode means the command has lost its `--mode dev`. A check error is fixed in the sources and proved green with `s0ma check --mode strict` before building again.

## Where to go next

- [What the build writes, and what each file is for](what-the-build-writes.md) opens the directory the wheel carries.
- [When s0ma refuses, and how to get back to green](drift-recovery.md) walks the refusals a build can meet in a checkout.
- [Runtime self-prompting with s0ma](../../packages/s0ma-dsl/docs/self_prompting.md) shows what an application does with the build once it is running.
- [ADR-015](../adr/ADR-015-build-without-runtime-packages.md) records why the gate treats a missing package this way, and what else was considered.
