"""The manifest-driven bootstrap (``s0ma.bootstrap``) — M10 relocation.

Two kinds of coverage live here:

1. **In-process contract tests** — import order, the ``roles`` filter,
   ``sys.path`` idempotence, and every manifest failure mode. These are
   the invariants the loader carried while it lived in ``s0ma_dsl``,
   verified against the core implementation that now owns them.
2. **The runtime-honesty gate** (``TestCoreOnlyVenv``) — a real venv
   containing **s0ma-core and nothing else** boots a build through
   ``s0ma.bootstrap.bootstrap_imports``. This is the wall a bench spike
   hit: with the loader in the authoring package (proprietary at the
   time), the documented one-line bootstrap died with
   ``ModuleNotFoundError: No module named 's0ma_dsl'`` in exactly such
   an environment. PRD INV-9
   forbids a license-gated import on a deployed system's boot path, so
   the wall is now a permanent test.

The builds used here are written by hand (a manifest plus plain-Python
modules) rather than produced by the transpiler: core's suite must not
depend on the authoring package, and the property under test is that the
*loader* needs nothing but the standard library and s0ma-core.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import textwrap
from pathlib import Path
from typing import TYPE_CHECKING, Any

import pytest

from s0ma.bootstrap import (
    MANIFEST_FILENAME,
    MANIFEST_SCHEMA,
    ManifestSchemaError,
    bootstrap_imports,
)

if TYPE_CHECKING:
    from collections.abc import Iterator

#: This repo's ``packages/s0ma-core`` directory (the installable core
#: package). ``None`` when the suite runs outside a repo checkout.
CORE_PACKAGE_ROOT = Path(__file__).resolve().parents[1]


# ---------------------------------------------------------------------------
# Hand-written build fixtures
# ---------------------------------------------------------------------------


def _entry(name: str, *, role: str = "source") -> dict[str, Any]:
    """One manifest module row with every field the schema requires."""
    return {
        "name": name,
        "source": f"src/{name}.s0ma",
        "output": f"{name}.py",
        "ir": f"{name}.s0ma.json",
        "source_map": f"{name}.s0ma.map",
        "source_hash": "sha256:" + "0" * 16,
        "output_hash": "sha256:" + "1" * 16,
        "role": role,
    }


def _write_build(
    build_dir: Path,
    *,
    modules: dict[str, str],
    order: list[str] | None,
    roles: dict[str, str] | None = None,
    schema: str = MANIFEST_SCHEMA,
) -> Path:
    """Write a build directory: one ``.py`` per module plus the manifest.

    *modules* maps module name to module body. *order* is written to
    ``topological_import_order`` (omitted entirely when ``None``, the
    shape of a pre-M10 manifest).
    """
    build_dir.mkdir(parents=True, exist_ok=True)
    (build_dir / "__init__.py").write_text("", encoding="utf-8", newline="\n")
    role_of = roles or {}
    for name, body in modules.items():
        (build_dir / f"{name}.py").write_text(
            textwrap.dedent(body), encoding="utf-8", newline="\n"
        )
    payload: dict[str, Any] = {
        "schema": schema,
        "project": "fixture",
        "build_dir": build_dir.name,
        "transpiler_version": "0.0.0-test",
        "modules": [
            _entry(name, role=role_of.get(name, "source"))
            for name in sorted(modules)
        ],
    }
    if order is not None:
        payload["topological_import_order"] = order
    (build_dir / MANIFEST_FILENAME).write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    return build_dir


@pytest.fixture()
def _clean_sys_state() -> Iterator[None]:
    """Restore ``sys.path`` / ``sys.modules`` around an in-process import."""
    saved_path = list(sys.path)
    saved_modules = set(sys.modules)
    yield
    sys.path[:] = saved_path
    for name in set(sys.modules) - saved_modules:
        del sys.modules[name]


# ---------------------------------------------------------------------------
# 1. Import order and returned mapping
# ---------------------------------------------------------------------------


@pytest.mark.usefixtures("_clean_sys_state")
def test_imports_follow_the_recorded_topological_order(tmp_path: Path) -> None:
    """Modules load dependency-first, in the manifest's recorded order."""
    build = _write_build(
        tmp_path / "build",
        modules={
            "leaf_domain": "VALUE = 'leaf'\n",
            "mid_application": "import leaf_domain\nVALUE = leaf_domain.VALUE + '+mid'\n",
            "top_presentation": (
                "import mid_application\nVALUE = mid_application.VALUE + '+top'\n"
            ),
        },
        order=["leaf_domain", "mid_application", "top_presentation"],
    )

    modules = bootstrap_imports(build)

    assert list(modules) == ["leaf_domain", "mid_application", "top_presentation"]
    assert modules["top_presentation"].VALUE == "leaf+mid+top"


@pytest.mark.usefixtures("_clean_sys_state")
def test_falls_back_to_manifest_order_when_topology_absent(tmp_path: Path) -> None:
    """A pre-M10 manifest (no order field) imports alphabetically."""
    build = _write_build(
        tmp_path / "build",
        modules={"beta_domain": "VALUE = 'b'\n", "alpha_domain": "VALUE = 'a'\n"},
        order=None,
    )

    modules = bootstrap_imports(build)

    assert list(modules) == ["alpha_domain", "beta_domain"]


@pytest.mark.usefixtures("_clean_sys_state")
def test_accepts_a_string_build_dir(tmp_path: Path) -> None:
    """``build_dir`` may be any value ``Path()`` accepts, not just a Path."""
    build = _write_build(
        tmp_path / "build",
        modules={"solo_domain": "VALUE = 1\n"},
        order=["solo_domain"],
    )

    modules = bootstrap_imports(str(build))

    assert modules["solo_domain"].VALUE == 1


# ---------------------------------------------------------------------------
# 2. Role filtering (0.14.0 contract, preserved by the move)
# ---------------------------------------------------------------------------


@pytest.mark.usefixtures("_clean_sys_state")
def test_roles_default_to_source_only(tmp_path: Path) -> None:
    """A unified manifest imports only its source modules by default."""
    build = _write_build(
        tmp_path / "build",
        modules={"unit_domain": "VALUE = 1\n", "unit_domain_tests": "VALUE = 2\n"},
        order=["unit_domain", "unit_domain_tests"],
        roles={"unit_domain_tests": "test"},
    )

    assert list(bootstrap_imports(build)) == ["unit_domain"]
    assert list(bootstrap_imports(build, roles=("test",))) == ["unit_domain_tests"]
    assert list(bootstrap_imports(build, roles=("source", "test"))) == [
        "unit_domain",
        "unit_domain_tests",
    ]
    assert bootstrap_imports(build, roles=()) == {}


def test_unknown_role_is_a_caller_bug(tmp_path: Path) -> None:
    """An unrecognised role raises ``ValueError`` before anything imports."""
    build = _write_build(
        tmp_path / "build",
        modules={"unit_domain": "VALUE = 1\n"},
        order=["unit_domain"],
    )

    with pytest.raises(ValueError, match="roles must be a subset"):
        bootstrap_imports(build, roles=("source", "bogus"))


# ---------------------------------------------------------------------------
# 3. sys.path handling
# ---------------------------------------------------------------------------


@pytest.mark.usefixtures("_clean_sys_state")
def test_sys_path_insertion_is_idempotent(tmp_path: Path) -> None:
    """Repeat calls never duplicate the build directory on ``sys.path``."""
    build = _write_build(
        tmp_path / "build",
        modules={"solo_domain": "VALUE = 1\n"},
        order=["solo_domain"],
    )

    bootstrap_imports(build)
    bootstrap_imports(build)

    assert sys.path.count(str(build)) == 1
    assert sys.path[0] == str(build)


@pytest.mark.usefixtures("_clean_sys_state")
def test_sys_path_insert_false_leaves_sys_path_alone(tmp_path: Path) -> None:
    """``sys_path_insert=False`` mutates nothing — the caller arranged it."""
    build = _write_build(
        tmp_path / "build",
        modules={"solo_domain": "VALUE = 1\n"},
        order=["solo_domain"],
    )
    before = list(sys.path)

    with pytest.raises(ModuleNotFoundError):
        bootstrap_imports(build, sys_path_insert=False)

    assert sys.path == before


# ---------------------------------------------------------------------------
# 4. Manifest failure modes — loud, never a silent fallback
# ---------------------------------------------------------------------------


def test_missing_manifest_names_the_remediation(tmp_path: Path) -> None:
    empty = tmp_path / "build"
    empty.mkdir()

    with pytest.raises(ManifestSchemaError) as excinfo:
        bootstrap_imports(empty)

    assert "Build manifest not found" in str(excinfo.value)
    assert "s0ma build" in str(excinfo.value)


def test_corrupt_manifest_json_raises(tmp_path: Path) -> None:
    build = tmp_path / "build"
    build.mkdir()
    (build / MANIFEST_FILENAME).write_text(
        "{not json", encoding="utf-8", newline="\n"
    )

    with pytest.raises(ManifestSchemaError, match="not valid JSON"):
        bootstrap_imports(build)


def test_schema_mismatch_raises(tmp_path: Path) -> None:
    build = _write_build(
        tmp_path / "build",
        modules={"solo_domain": "VALUE = 1\n"},
        order=["solo_domain"],
        schema="s0ma-build-manifest@99",
    )

    with pytest.raises(ManifestSchemaError, match="expected 's0ma-build-manifest@1'"):
        bootstrap_imports(build)


def test_truncated_module_entry_raises(tmp_path: Path) -> None:
    build = tmp_path / "build"
    build.mkdir()
    (build / MANIFEST_FILENAME).write_text(
        json.dumps(
            {
                "schema": MANIFEST_SCHEMA,
                "project": "fixture",
                "build_dir": "build",
                "transpiler_version": "0.0.0-test",
                "modules": [{"name": "solo_domain"}],
                "topological_import_order": ["solo_domain"],
            }
        )
        + "\n",
        encoding="utf-8",
        newline="\n",
    )

    with pytest.raises(ManifestSchemaError, match="missing required"):
        bootstrap_imports(build)


def test_non_array_topological_order_raises(tmp_path: Path) -> None:
    build = _write_build(
        tmp_path / "build",
        modules={"solo_domain": "VALUE = 1\n"},
        order=None,
    )
    payload = json.loads((build / MANIFEST_FILENAME).read_text(encoding="utf-8"))
    payload["topological_import_order"] = "solo_domain"
    (build / MANIFEST_FILENAME).write_text(
        json.dumps(payload) + "\n", encoding="utf-8", newline="\n"
    )

    with pytest.raises(ManifestSchemaError, match="not a JSON array"):
        bootstrap_imports(build)


# ---------------------------------------------------------------------------
# 5. The runtime-honesty gate: a venv with s0ma-core and nothing else
# ---------------------------------------------------------------------------


class TestCoreOnlyVenv:
    """Boot a build in an environment that has only s0ma-core installed.

    The venv is built once per module: ``uv venv`` + ``uv pip install
    --no-deps <repo>/packages/s0ma-core``. Nothing else goes in, so an
    import of the authoring packages inside it is a hard failure — which
    is the point.
    """

    @pytest.fixture(scope="class")
    def core_only_python(self, tmp_path_factory: pytest.TempPathFactory) -> Path:
        uv = shutil.which("uv")
        if uv is None:  # pragma: no cover - depends on the developer's box
            pytest.skip("uv is not on PATH; cannot build a core-only venv")
        if not (CORE_PACKAGE_ROOT / "pyproject.toml").is_file():  # pragma: no cover
            pytest.skip("not a repo checkout; s0ma-core sources unavailable")

        venv = tmp_path_factory.mktemp("core_only") / "venv"
        subprocess.run(
            [uv, "venv", "--python", sys.executable, str(venv)],
            check=True,
            capture_output=True,
            text=True,
        )
        python = (
            venv / "Scripts" / "python.exe"
            if sys.platform == "win32"
            else venv / "bin" / "python"
        )
        subprocess.run(
            [
                uv, "pip", "install",
                "--python", str(python),
                "--no-deps",
                str(CORE_PACKAGE_ROOT),
            ],
            check=True,
            capture_output=True,
            text=True,
        )
        return python

    @staticmethod
    def _run(python: Path, script: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [str(python), "-c", textwrap.dedent(script)],
            capture_output=True,
            text=True,
            encoding="utf-8",
        )

    def test_the_venv_really_has_no_authoring_packages(
        self, core_only_python: Path
    ) -> None:
        """Guard the guard: s0ma imports, s0ma_dsl does not exist."""
        result = self._run(
            core_only_python,
            """
            import importlib.util
            import s0ma.bootstrap
            assert importlib.util.find_spec("s0ma_dsl") is None, "s0ma_dsl leaked in"
            print("core-only")
            """,
        )
        assert result.returncode == 0, result.stderr
        assert "core-only" in result.stdout

    def test_build_boots_through_the_core_bootstrap(
        self, core_only_python: Path, tmp_path: Path
    ) -> None:
        """The blessed one-liner loads a build with core alone installed.

        This is the M10 acceptance in one assertion: no authoring package
        is installed, and the documented bootstrap still returns the
        build's modules in dependency-first order.
        """
        build = _write_build(
            tmp_path / "build",
            modules={
                "leaf_domain": "VALUE = 'leaf'\n",
                "mid_application": (
                    "import leaf_domain\nVALUE = leaf_domain.VALUE + '+mid'\n"
                ),
            },
            order=["leaf_domain", "mid_application"],
        )

        result = self._run(
            core_only_python,
            f"""
            import json
            from s0ma.bootstrap import bootstrap_imports

            modules = bootstrap_imports({str(build)!r})
            print(json.dumps({{
                "order": list(modules),
                "value": modules["mid_application"].VALUE,
            }}))
            """,
        )

        assert result.returncode == 0, (
            "the core-only bootstrap failed — a deployed app cannot boot "
            f"with s0ma-core alone:\n{result.stderr}"
        )
        payload = json.loads(result.stdout.strip().splitlines()[-1])
        assert payload["order"] == ["leaf_domain", "mid_application"]
        assert payload["value"] == "leaf+mid"

    def test_importing_the_bootstrap_warns_about_nothing(
        self, core_only_python: Path
    ) -> None:
        """``s0ma.bootstrap`` is the recommended path — it must be silent."""
        result = self._run(
            core_only_python,
            """
            import warnings
            warnings.simplefilter("error")
            import s0ma.bootstrap  # noqa: F401
            print("silent")
            """,
        )
        assert result.returncode == 0, result.stderr
        assert "silent" in result.stdout
