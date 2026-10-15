"""M10 — the bootstrap loader lives in s0ma-core, and the old path still works.

Three contracts are locked down here:

1. **The deprecated re-export.** ``s0ma_dsl.runtime.bootstrap_imports``
   keeps working byte-for-byte for apps already calling it (INV-2: no
   silent rename), while emitting a ``DeprecationWarning`` that names
   ``s0ma.bootstrap``. Exercised end-to-end against a real build.
2. **One manifest truth.** The runtime reader in ``s0ma.bootstrap`` and
   the authoring reader in ``s0ma_dsl.codegen.build_manifest`` must agree
   about a real build — they read the same file for different purposes
   and must never drift apart.
3. **The runtime-honesty boundary.** In a venv holding **s0ma-core
   only**, the documented bootstrap runs: the loader imports, reads the
   manifest and starts importing built modules without any authoring
   package present. The remaining blocker is *emitted* code — every
   transpiled module still carries ``from
   s0ma_dsl.runtime_bridge.registration import ...`` — which is the
   separate runtime-free-emission design round, not this milestone. The
   test pins that boundary exactly where it is, so the day emission goes
   runtime-free it fails loudly and gets promoted to a full green path.

The core-only-venv gate for the loader itself lives in
``packages/s0ma-core/tests/test_bootstrap_imports.py``; core's suite owns
it because the property is core's. This module covers what needs the
transpiler at setup time: a real ``s0ma build`` output.
"""

from __future__ import annotations

import importlib
import shutil
import subprocess
import sys
import textwrap
import warnings
from pathlib import Path

import pytest

from s0ma_dsl.cli.main import EXIT_SUCCESS, S0maCLI
from s0ma_dsl.codegen.build_manifest import load_manifest

FIXTURE = Path(__file__).parent / "fixtures" / "multi_module_project"
EXPECTED_ORDER = ("models", "processing", "routing")

#: ``packages/s0ma-core`` in this checkout — the only distribution the
#: runtime-honesty venv is allowed to contain.
CORE_PACKAGE_ROOT = Path(__file__).resolve().parents[2] / "s0ma-core"


@pytest.fixture(scope="module")
def built_project(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """Build the multi-module fixture once for this module's tests."""
    out_dir = tmp_path_factory.mktemp("runtime_free") / "build"
    cli = S0maCLI()
    rc = cli.run([
        "build", str(FIXTURE),
        "--output-dir", str(out_dir),
        "--mode", "dev",
        "--no-cache",
    ])
    assert rc == EXIT_SUCCESS, "fixture build failed"
    return out_dir


# ---------------------------------------------------------------------------
# 1. The deprecated re-export
# ---------------------------------------------------------------------------


def test_importing_the_old_path_warns_and_names_the_new_one() -> None:
    """Importing ``s0ma_dsl.runtime`` warns once and points at s0ma.bootstrap."""
    sys.modules.pop("s0ma_dsl.runtime", None)
    try:
        with pytest.warns(DeprecationWarning) as record:
            module = importlib.import_module("s0ma_dsl.runtime")
    finally:
        sys.modules.pop("s0ma_dsl.runtime", None)

    messages = [str(w.message) for w in record]
    assert len(messages) == 1, messages
    assert "s0ma.bootstrap" in messages[0]
    assert callable(module.bootstrap_imports)


def test_new_path_is_silent() -> None:
    """``s0ma.bootstrap`` is the recommended import — no warning of any kind.

    Checked in a subprocess with warnings promoted to errors: importing
    the module in-process here would have to be forced (it is already
    resident), and re-executing it would hand this suite a second set of
    module-level objects.
    """
    proc = subprocess.run(
        [sys.executable, "-W", "error::DeprecationWarning", "-c",
         "import s0ma.bootstrap; print('silent')"],
        capture_output=True, text=True,
    )
    assert proc.returncode == 0, proc.stderr
    assert "silent" in proc.stdout


def test_deprecated_path_still_boots_a_real_build(built_project: Path) -> None:
    """The old import keeps working end-to-end: warning raised, modules loaded.

    Run in a subprocess so the transpiled modules register into a fresh
    component registry (re-importing them in-process would trip the
    registry's intentional double-registration guard).
    """
    code = textwrap.dedent(f"""
        import warnings
        from pathlib import Path

        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            from s0ma_dsl.runtime import bootstrap_imports

        kinds = [w.category.__name__ for w in caught]
        assert kinds == ["DeprecationWarning"], kinds
        assert "s0ma.bootstrap" in str(caught[0].message)

        modules = bootstrap_imports(Path({str(built_project)!r}))
        names = list(modules)
        assert names == {list(EXPECTED_ORDER)!r}, names
        print("OK:" + ",".join(names))
    """)
    proc = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True
    )
    assert proc.returncode == 0, (
        f"deprecated path broke:\nstdout={proc.stdout!r}\nstderr={proc.stderr!r}"
    )
    assert "OK:" + ",".join(EXPECTED_ORDER) in proc.stdout


def test_reexport_delegates_to_core() -> None:
    """The dsl wrapper forwards to the core implementation, unchanged."""
    import inspect

    from s0ma.bootstrap import bootstrap_imports as core_bootstrap

    with warnings.catch_warnings():
        warnings.simplefilter("ignore", DeprecationWarning)
        from s0ma_dsl.runtime import bootstrap_imports as dsl_bootstrap

    assert inspect.signature(dsl_bootstrap) == inspect.signature(core_bootstrap)
    assert "s0ma.bootstrap" in (dsl_bootstrap.__doc__ or "")


# ---------------------------------------------------------------------------
# 2. One manifest truth — the two readers must not drift
# ---------------------------------------------------------------------------


def test_both_manifest_readers_agree_about_a_real_build(
    built_project: Path,
) -> None:
    """Core's runtime read and the transpiler's read describe the same build.

    ``s0ma.bootstrap`` parses the manifest itself (stdlib only, so a
    deployed app needs no authoring package) while
    ``s0ma_dsl.codegen.build_manifest`` keeps the full authoring view.
    Two readers of one file is only safe while they agree; this is the
    gate that keeps them honest.
    """
    # The private helper is the runtime read path itself — this gate
    # exists to compare it against the authoring reader, so it reaches
    # past the public surface deliberately.
    from s0ma.bootstrap import _import_order

    authoring = load_manifest(built_project)
    authoring_source_order = tuple(
        name for name in authoring.topological_import_order
        if next(
            (m.role for m in authoring.modules if m.name == name), "source"
        ) == "source"
    )

    assert _import_order(built_project, {"source"}) == authoring_source_order
    assert authoring_source_order == EXPECTED_ORDER


def test_manifest_schema_identity_is_shared() -> None:
    """The schema constants and error type are one definition, not two copies."""
    from s0ma.bootstrap import (
        MANIFEST_FILENAME,
        MANIFEST_SCHEMA,
        VALID_ROLES,
        ManifestSchemaError,
    )

    from s0ma_dsl.codegen.build_manifest import (
        MANIFEST_FILENAME as DSL_MANIFEST_FILENAME,
    )
    from s0ma_dsl.codegen.build_manifest import (
        MANIFEST_SCHEMA as DSL_MANIFEST_SCHEMA,
    )
    from s0ma_dsl.codegen.build_manifest import (
        VALID_ROLES as DSL_VALID_ROLES,
    )
    from s0ma_dsl.codegen.build_manifest import (
        ManifestSchemaError as DslManifestSchemaError,
    )

    assert DSL_MANIFEST_SCHEMA is MANIFEST_SCHEMA
    assert DSL_MANIFEST_FILENAME is MANIFEST_FILENAME
    assert DSL_VALID_ROLES is VALID_ROLES
    assert DslManifestSchemaError is ManifestSchemaError


# ---------------------------------------------------------------------------
# 3. The runtime-honesty boundary, measured in a core-only venv
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def core_only_python(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """A venv containing s0ma-core and nothing else."""
    uv = shutil.which("uv")
    if uv is None:  # pragma: no cover - depends on the developer's box
        pytest.skip("uv is not on PATH; cannot build a core-only venv")
    if not (CORE_PACKAGE_ROOT / "pyproject.toml").is_file():  # pragma: no cover
        pytest.skip("not a repo checkout; s0ma-core sources unavailable")

    venv = tmp_path_factory.mktemp("core_only") / "venv"
    subprocess.run(
        [uv, "venv", "--python", sys.executable, str(venv)],
        check=True, capture_output=True, text=True,
    )
    python = (
        venv / "Scripts" / "python.exe"
        if sys.platform == "win32"
        else venv / "bin" / "python"
    )
    subprocess.run(
        [uv, "pip", "install", "--python", str(python), "--no-deps",
         str(CORE_PACKAGE_ROOT)],
        check=True, capture_output=True, text=True,
    )
    return python


def test_bootstrap_runs_without_the_authoring_packages(
    core_only_python: Path, built_project: Path
) -> None:
    """The bootstrap itself is no longer the thing that fails.

    Before M10 the blessed one-liner could not even be imported in a
    deployment environment: ``from s0ma_dsl.runtime import
    bootstrap_imports`` raised ``ModuleNotFoundError`` before any build
    output was touched. Now the loader imports from s0ma-core, reads the
    manifest and reaches the first built module.

    The failure that remains belongs to *emitted code*: every transpiled
    module opens with ``from s0ma_dsl.runtime_bridge.registration import
    ...``. Making emission runtime-free is its own design round; this
    assertion is the pin that says exactly how far the boot gets today.
    When emission stops importing the authoring package, this test fails
    — replace it with the plain success assertion at that point.
    """
    code = textwrap.dedent(f"""
        import importlib.util, traceback
        assert importlib.util.find_spec("s0ma_dsl") is None, "s0ma_dsl leaked in"

        from s0ma.bootstrap import bootstrap_imports  # core-only: must succeed
        print("BOOTSTRAP-IMPORTED")
        try:
            bootstrap_imports({str(built_project)!r})
        except ModuleNotFoundError:
            print("STOPPED-IN:" + traceback.format_exc().strip().splitlines()[-2].strip())
        else:
            print("FULL-BOOT")
    """)
    proc = subprocess.run(
        [str(core_only_python), "-c", code],
        capture_output=True, text=True, encoding="utf-8",
    )

    assert proc.returncode == 0, proc.stderr
    assert "BOOTSTRAP-IMPORTED" in proc.stdout, (
        "the loader itself could not be imported from s0ma-core alone:\n"
        f"{proc.stderr}"
    )
    if "FULL-BOOT" in proc.stdout:  # pragma: no cover - the future win
        pytest.fail(
            "emitted modules no longer need the authoring package: the "
            "runtime-free-emission round has landed. Replace this test's "
            "boundary assertion with a plain success assertion."
        )
    assert "STOPPED-IN:from s0ma_dsl.runtime_bridge.registration import" in (
        proc.stdout
    ), (
        "expected the boot to stop at the emitted registration import "
        f"(the documented remaining gap); got:\n{proc.stdout}\n{proc.stderr}"
    )
