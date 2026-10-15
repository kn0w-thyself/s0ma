"""Discovery: which Python files a tree owns, and what each one is for (B1).

``adopt/discovery.py`` is the first thing a retrofit runs and the first
thing a user reads. Everything downstream — the census, the import
graph, the conversion order, the perimeter ``adopt init`` writes — is
built on the answer, so these tests pin the answer's edges rather than
its happy path:

- **Each rule has a negative.** A directory named ``build`` is skipped
  and one named ``builder`` is not; ``test_x.py`` is test code and
  ``latest.py`` is not. A rule with no negative case is a rule that
  quietly matches everything.
- **Nothing is written, ever** (retrofit rule R-2). The tree is hashed
  before and after a full discovery and has to be byte-identical, with
  no file and no directory added — not a cache, not a ``__pycache__``.
- **Nothing is imported** (retrofit rule R-1). The trees below contain
  modules that would raise on import; discovery reads them happily.
- **The same tree gives the same answer.** Paths are project-relative
  and forward-slashed, and the order never depends on the order the
  files were created in.

Sources are written inline into ``tmp_path``: these tests own their
inputs, so a change to a shared fixture application cannot move what
they assert.
"""

from __future__ import annotations

import hashlib
import sys
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from s0ma_dsl.adopt.discovery import (
    ROOTS_DECLARED,
    ROOTS_GIVEN,
    ROOTS_INFERRED,
    discover_sources,
    discover_within,
    infer_own_source_roots,
    is_transpiled_artifact,
    resolve_source_roots,
    source_root_origin,
)

if TYPE_CHECKING:
    from s0ma_dsl.adopt.model import SourceFile

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def write(root: Path, relative: str, text: str = "") -> Path:
    """Write *text* to ``root/relative``, creating parents. UTF-8, LF."""
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8", newline="\n")
    return path


def paths(sources: tuple[SourceFile, ...]) -> list[str]:
    """Return the discovered paths, for readable assertions."""
    return [source.path for source in sources]


def role_of(sources: tuple[SourceFile, ...], path: str) -> str:
    """Return the role recorded for *path*; fail loudly when it is absent."""
    for source in sources:
        if source.path == path:
            return source.role
    raise AssertionError(f"{path} was not discovered; discovery found {paths(sources)}")


def module_of(sources: tuple[SourceFile, ...], path: str) -> str:
    """Return the dotted module recorded for *path*."""
    for source in sources:
        if source.path == path:
            return source.module
    raise AssertionError(f"{path} was not discovered; discovery found {paths(sources)}")


def tree_fingerprint(root: Path) -> list[tuple[str, str]]:
    """Return every path under *root* with a hash of its bytes.

    Directories are included (with an empty hash) so that a stray cache
    *directory* is caught even when it is empty, and files are hashed so
    that an in-place rewrite is caught even when the name is unchanged.
    """
    entries: list[tuple[str, str]] = []
    for path in sorted(root.rglob("*")):
        relative = path.relative_to(root).as_posix()
        if path.is_dir():
            entries.append((f"{relative}/", ""))
        else:
            entries.append((relative, hashlib.sha256(path.read_bytes()).hexdigest()))
    return entries


# ---------------------------------------------------------------------------
# Source roots
# ---------------------------------------------------------------------------


def test_flat_tree_has_the_root_itself_as_its_source_root(tmp_path: Path) -> None:
    write(tmp_path, "inventory.py", "VALUE = 1\n")
    assert resolve_source_roots(tmp_path) == (".",)
    sources = discover_sources(tmp_path)
    assert [source.source_root for source in sources] == ["."]
    assert module_of(sources, "inventory.py") == "inventory"


def test_src_layout_is_inferred_when_it_holds_a_package(tmp_path: Path) -> None:
    write(tmp_path, "src/bookshelf/__init__.py", '"""Bookshelf."""\n')
    write(tmp_path, "src/bookshelf/catalog.py", "def find():\n    return None\n")
    assert resolve_source_roots(tmp_path) == ("src",)
    sources = discover_sources(tmp_path)
    assert module_of(sources, "src/bookshelf/catalog.py") == "bookshelf.catalog"
    assert module_of(sources, "src/bookshelf/__init__.py") == "bookshelf"


def test_src_without_a_package_is_not_a_source_root(tmp_path: Path) -> None:
    """The negative of the rule above: ``src/`` alone proves nothing."""
    write(tmp_path, "src/loose.py", "VALUE = 1\n")
    assert resolve_source_roots(tmp_path) == (".",)
    assert module_of(discover_sources(tmp_path), "src/loose.py") == "src.loose"


def test_explicit_source_roots_win_over_inference(tmp_path: Path) -> None:
    write(tmp_path, "src/bookshelf/__init__.py", "")
    write(tmp_path, "lib/tool/__init__.py", "")
    write(tmp_path, "lib/tool/run.py", "def go():\n    return 1\n")
    sources = discover_sources(tmp_path, ["lib"])
    assert module_of(sources, "lib/tool/run.py") == "tool.run"
    # Anything outside the declared root still shows up, owned by ".".
    assert module_of(sources, "src/bookshelf/__init__.py") == "src.bookshelf"


def test_configured_source_roots_are_read_from_tool_s0ma(tmp_path: Path) -> None:
    write(
        tmp_path,
        "pyproject.toml",
        '[project]\nname = "demo"\nversion = "0.1.0"\n\n[tool.s0ma]\nsource_roots = ["lib"]\n',
    )
    write(tmp_path, "lib/tool/__init__.py", "")
    write(tmp_path, "lib/tool/run.py", "def go():\n    return 1\n")
    assert resolve_source_roots(tmp_path) == ("lib",)
    assert module_of(discover_sources(tmp_path), "lib/tool/run.py") == "tool.run"


def test_an_outer_projects_table_is_never_adopted(tmp_path: Path) -> None:
    """A plain tree inside a s0ma repository is still a plain tree.

    ``S0maProject.discover`` walks *upward* until it meets a
    ``[tool.s0ma]`` table. Scanning a brownfield directory that happens
    to live inside a s0ma repository — a fixture tree, a vendored
    dependency, an example — must not silently inherit the outer
    repository's source roots and build directory.
    """
    write(
        tmp_path,
        "pyproject.toml",
        '[project]\nname = "outer"\nversion = "0.1.0"\n\n[tool.s0ma]\n'
        'source_roots = ["outer_src"]\nbuild_dir = "outer_build"\n',
    )
    inner = tmp_path / "inner"
    write(inner, "src/bookshelf/__init__.py", "")
    write(inner, "src/bookshelf/catalog.py", "def find():\n    return None\n")
    write(inner, "outer_build/generated.py", "X = 1\n")

    assert resolve_source_roots(inner) == ("src",)
    sources = discover_sources(inner)
    # The outer project's build directory means nothing here, so the
    # directory that happens to share its name is ordinary source.
    assert "outer_build/generated.py" in paths(sources)


def test_a_malformed_pyproject_reads_as_no_project(tmp_path: Path) -> None:
    write(tmp_path, "pyproject.toml", "[tool.s0ma\nthis is not toml")
    write(tmp_path, "inventory.py", "VALUE = 1\n")
    assert resolve_source_roots(tmp_path) == (".",)
    assert paths(discover_sources(tmp_path)) == ["inventory.py"]


# ---------------------------------------------------------------------------
# What the walk skips
# ---------------------------------------------------------------------------


def test_machine_owned_directories_are_pruned(tmp_path: Path) -> None:
    write(tmp_path, "keep.py", "VALUE = 1\n")
    for skipped in (
        ".venv",
        ".git",
        ".s0ma.cache",
        ".claude",
        "__pycache__",
        "venv",
        "env",
        "node_modules",
        "build",
        "dist",
        "site-packages",
        "demo.egg-info",
        "demo.dist-info",
    ):
        write(tmp_path, f"{skipped}/hidden_module.py", "VALUE = 1\n")
    assert paths(discover_sources(tmp_path)) == ["keep.py"]


def test_directories_that_merely_look_machine_owned_are_kept(tmp_path: Path) -> None:
    """The negative of the rule above: prefix matches are not matches."""
    for kept in ("builder", "distribution", "environment", "testing_tools", "egginfo"):
        write(tmp_path, f"{kept}/module.py", "VALUE = 1\n")
    assert paths(discover_sources(tmp_path)) == [
        "builder/module.py",
        "distribution/module.py",
        "egginfo/module.py",
        "environment/module.py",
        "testing_tools/module.py",
    ]


def test_the_configured_build_directory_is_pruned(tmp_path: Path) -> None:
    write(
        tmp_path,
        "pyproject.toml",
        '[project]\nname = "demo"\nversion = "0.1.0"\n\n[tool.s0ma]\n'
        'source_roots = ["src"]\nbuild_dir = "demo_build"\n',
    )
    write(tmp_path, "src/demo/__init__.py", "")
    write(tmp_path, "demo_build/demo/generated.py", "VALUE = 1\n")
    assert paths(discover_sources(tmp_path)) == ["src/demo/__init__.py"]


def test_transpiled_artifacts_are_not_retrofit_material(tmp_path: Path) -> None:
    generated = (
        "# s0ma-source-hash: sha256:aaaa\n"
        "# s0ma-output-hash: sha256:bbbb\n"
        "def already_converted() -> int:\n    return 1\n"
    )
    write(tmp_path, "generated.py", generated)
    write(tmp_path, "handwritten.py", "def convert_me() -> int:\n    return 1\n")
    assert paths(discover_sources(tmp_path)) == ["handwritten.py"]


def test_one_hash_header_alone_is_not_an_artifact(tmp_path: Path) -> None:
    """The negative: a file that merely mentions a header is hand-written."""
    write(tmp_path, "mentions.py", "# s0ma-source-hash: sha256:aaaa\nVALUE = 1\n")
    assert paths(discover_sources(tmp_path)) == ["mentions.py"]
    assert is_transpiled_artifact("# s0ma-output-hash: sha256:bbbb\n") is False
    assert (
        is_transpiled_artifact(
            "# s0ma-source-hash: sha256:aaaa\n# s0ma-output-hash: sha256:bbbb\n"
        )
        is True
    )


def test_only_python_files_are_discovered(tmp_path: Path) -> None:
    write(tmp_path, "module.py", "VALUE = 1\n")
    write(tmp_path, "module.pyi", "VALUE: int\n")
    write(tmp_path, "notes.txt", "hello\n")
    write(tmp_path, "data.json", "{}\n")
    assert paths(discover_sources(tmp_path)) == ["module.py"]


def test_a_missing_root_is_an_empty_answer_not_an_error(tmp_path: Path) -> None:
    assert discover_sources(tmp_path / "nowhere") == ()


# ---------------------------------------------------------------------------
# Roles
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "relative",
    [
        "tests/check_behaviour.py",
        "test/check_behaviour.py",
        "src/pkg/tests/check_behaviour.py",
        "test_catalog.py",
        "catalog_test.py",
        "conftest.py",
        "src/pkg/conftest.py",
    ],
)
def test_test_code_is_recognised_by_place_or_by_name(tmp_path: Path, relative: str) -> None:
    write(tmp_path, relative, "def check() -> None:\n    assert True\n")
    assert role_of(discover_sources(tmp_path), relative) == "test"


@pytest.mark.parametrize(
    "relative",
    ["latest.py", "contest.py", "testing/helpers.py", "attest.py", "tests_helper.py"],
)
def test_names_that_merely_contain_test_are_application_code(
    tmp_path: Path, relative: str
) -> None:
    """The negative of the rule above, where a sloppier match would fire."""
    write(tmp_path, relative, "def run() -> None:\n    return None\n")
    assert role_of(discover_sources(tmp_path), relative) == "app"


def test_a_re_export_init_is_a_package_marker(tmp_path: Path) -> None:
    write(
        tmp_path,
        "src/bookshelf/__init__.py",
        '"""The bookshelf package."""\n\n'
        "from bookshelf.catalog import find\n\n"
        '__all__ = ["find"]\n',
    )
    write(tmp_path, "src/bookshelf/catalog.py", "def find():\n    return None\n")
    assert role_of(discover_sources(tmp_path), "src/bookshelf/__init__.py") == "package_marker"


def test_an_empty_init_is_a_package_marker(tmp_path: Path) -> None:
    write(tmp_path, "src/bookshelf/__init__.py", "")
    write(tmp_path, "src/bookshelf/catalog.py", "def find():\n    return None\n")
    assert role_of(discover_sources(tmp_path), "src/bookshelf/__init__.py") == "package_marker"


def test_an_init_that_carries_logic_is_application_code(tmp_path: Path) -> None:
    """The negative: a marker marks, it does not do."""
    write(
        tmp_path,
        "src/bookshelf/__init__.py",
        '"""The bookshelf package."""\n\ndef configure() -> None:\n    return None\n',
    )
    write(tmp_path, "src/bookshelf/catalog.py", "def find():\n    return None\n")
    assert role_of(discover_sources(tmp_path), "src/bookshelf/__init__.py") == "app"


def test_an_unparseable_init_is_application_code_not_a_marker(tmp_path: Path) -> None:
    """When in doubt, not a marker — a broken package file stays visible."""
    write(tmp_path, "src/bookshelf/__init__.py", "def broken(:\n")
    write(tmp_path, "src/bookshelf/catalog.py", "def find():\n    return None\n")
    assert role_of(discover_sources(tmp_path), "src/bookshelf/__init__.py") == "app"


def test_a_main_guard_outside_a_package_is_a_script(tmp_path: Path) -> None:
    write(
        tmp_path,
        "run.py",
        "import argparse\n\n\ndef main() -> None:\n    argparse.ArgumentParser()\n\n\n"
        'if __name__ == "__main__":\n    main()\n',
    )
    assert role_of(discover_sources(tmp_path), "run.py") == "script"


def test_the_guard_is_recognised_written_either_way_round(tmp_path: Path) -> None:
    write(tmp_path, "run.py", 'if "__main__" == __name__:\n    print("go")\n')
    assert role_of(discover_sources(tmp_path), "run.py") == "script"


def test_a_main_guard_inside_a_package_is_application_code(tmp_path: Path) -> None:
    """The negative: a package module is converted, not treated as a script."""
    write(tmp_path, "src/bookshelf/__init__.py", "")
    write(
        tmp_path,
        "src/bookshelf/cli.py",
        'def main() -> None:\n    return None\n\n\nif __name__ == "__main__":\n    main()\n',
    )
    assert role_of(discover_sources(tmp_path), "src/bookshelf/cli.py") == "app"


def test_a_file_without_a_guard_is_application_code(tmp_path: Path) -> None:
    write(tmp_path, "run.py", "def main() -> None:\n    return None\n")
    assert role_of(discover_sources(tmp_path), "run.py") == "app"


def test_a_guard_nested_inside_a_function_is_not_a_main_guard(tmp_path: Path) -> None:
    write(
        tmp_path,
        "run.py",
        'def main() -> None:\n    if __name__ == "__main__":\n        return None\n',
    )
    assert role_of(discover_sources(tmp_path), "run.py") == "app"


def test_a_file_that_is_not_utf8_is_still_discovered(tmp_path: Path) -> None:
    """Discovery reports the file; the census explains what is wrong with it."""
    path = tmp_path / "latin.py"
    path.write_bytes(b'VALUE = "caf\xe9"\n')
    sources = discover_sources(tmp_path)
    assert paths(sources) == ["latin.py"]
    assert role_of(sources, "latin.py") == "app"


def test_module_names_are_derived_even_when_they_are_not_importable(
    tmp_path: Path,
) -> None:
    """A directory Python could never import still gets its honest name."""
    write(tmp_path, "my-dir/module.py", "VALUE = 1\n")
    assert module_of(discover_sources(tmp_path), "my-dir/module.py") == "my-dir.module"


def test_an_init_at_the_source_root_takes_the_directory_name(tmp_path: Path) -> None:
    """The degenerate case: no path segment is left to name the package."""
    write(tmp_path, "pkg/__init__.py", "")
    write(tmp_path, "pkg/mod.py", "VALUE = 1\n")
    sources = discover_sources(tmp_path, ["pkg"])
    assert module_of(sources, "pkg/__init__.py") == "pkg"
    # A source root that is itself a package contributes its own name: what
    # sits on the import path is the directory ABOVE it, so this file is
    # `pkg.mod` to Python and to the import graph, whatever the perimeter
    # is written as.
    assert module_of(sources, "pkg/mod.py") == "pkg.mod"


def test_a_source_root_that_is_not_a_package_contributes_no_prefix(
    tmp_path: Path,
) -> None:
    """The `src/` convention is unchanged: `src` is a path, not a package."""
    write(tmp_path, "src/bookshelf/__init__.py", "")
    write(tmp_path, "src/bookshelf/mod.py", "VALUE = 1\n")
    sources = discover_sources(tmp_path, ["src"])
    assert module_of(sources, "src/bookshelf/mod.py") == "bookshelf.mod"


# ---------------------------------------------------------------------------
# Symlinks
# ---------------------------------------------------------------------------


@pytest.mark.skipif(
    sys.platform == "win32",
    reason="creating a directory symlink needs elevation or developer mode on Windows",
)
def test_a_symlink_loop_does_not_stop_the_walk(tmp_path: Path) -> None:
    """A directory symlink is never entered, so a loop is a non-event."""
    write(tmp_path, "pkg/__init__.py", "")
    write(tmp_path, "pkg/module.py", "VALUE = 1\n")
    (tmp_path / "pkg" / "loop").symlink_to(tmp_path / "pkg", target_is_directory=True)

    sources = discover_sources(tmp_path)
    assert paths(sources) == ["pkg/__init__.py", "pkg/module.py"]


@pytest.mark.skipif(
    sys.platform == "win32",
    reason="creating a file symlink needs elevation or developer mode on Windows",
)
def test_a_symlink_pointing_out_of_the_tree_is_dropped(tmp_path: Path) -> None:
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "stranger.py").write_text("VALUE = 1\n", encoding="utf-8", newline="\n")

    project = tmp_path / "project"
    write(project, "own.py", "VALUE = 1\n")
    (project / "borrowed.py").symlink_to(outside / "stranger.py")

    assert paths(discover_sources(project)) == ["own.py"]


@pytest.mark.skipif(
    sys.platform == "win32",
    reason="creating a file symlink needs elevation or developer mode on Windows",
)
def test_a_symlink_pointing_inside_the_tree_is_kept(tmp_path: Path) -> None:
    """The negative of the rule above: in-tree links are the project's own."""
    write(tmp_path, "real.py", "VALUE = 1\n")
    (tmp_path / "alias.py").symlink_to(tmp_path / "real.py")
    assert paths(discover_sources(tmp_path)) == ["alias.py", "real.py"]


# ---------------------------------------------------------------------------
# Determinism and the zero-write promise
# ---------------------------------------------------------------------------


def test_results_are_sorted_and_repeatable(tmp_path: Path) -> None:
    for relative in ("zebra.py", "alpha.py", "pkg/middle.py", "pkg/__init__.py", "beta.py"):
        write(tmp_path, relative, "VALUE = 1\n")
    first = discover_sources(tmp_path)
    second = discover_sources(tmp_path)
    assert first == second
    assert paths(first) == sorted(paths(first))
    assert paths(first) == [
        "alpha.py",
        "beta.py",
        "pkg/__init__.py",
        "pkg/middle.py",
        "zebra.py",
    ]


def test_every_recorded_path_is_relative_and_forward_slashed(tmp_path: Path) -> None:
    write(tmp_path, "src/deep/nested/module.py", "VALUE = 1\n")
    write(tmp_path, "src/deep/__init__.py", "")
    write(tmp_path, "src/deep/nested/__init__.py", "")
    for source in discover_sources(tmp_path):
        assert "\\" not in source.path
        assert not source.path.startswith("/")
        assert not Path(source.path).is_absolute()
        assert str(tmp_path) not in source.path
        assert "\\" not in source.source_root


def test_discovery_writes_nothing_at_all(tmp_path: Path) -> None:
    """Retrofit rule R-2, proved by hashing the tree either side of a scan."""
    write(
        tmp_path,
        "pyproject.toml",
        '[project]\nname = "demo"\nversion = "0.1.0"\n\n[tool.s0ma]\nsource_roots = ["src"]\n',
    )
    write(tmp_path, "src/demo/__init__.py", '"""Demo."""\n')
    write(tmp_path, "src/demo/service.py", "import json\n\n\ndef load():\n    return json\n")
    write(tmp_path, "tests/test_service.py", "def test_load():\n    assert True\n")
    write(tmp_path, "run.py", 'if __name__ == "__main__":\n    print("go")\n')
    write(tmp_path, "broken.py", "def broken(:\n")

    before = tree_fingerprint(tmp_path)
    assert discover_sources(tmp_path)
    assert tree_fingerprint(tmp_path) == before


def test_nothing_in_the_tree_is_ever_imported(tmp_path: Path) -> None:
    """Retrofit rule R-1: a module that detonates on import scans fine."""
    write(
        tmp_path,
        "explodes.py",
        'raise SystemExit("this module must never be executed")\n',
    )
    write(tmp_path, "also_explodes.py", "import definitely_not_installed_anywhere\n")
    assert paths(discover_sources(tmp_path)) == ["also_explodes.py", "explodes.py"]


# ---------------------------------------------------------------------------
# Scoping (G3a, defect G2-5): the roots decide what is READ
# ---------------------------------------------------------------------------


def _three_package_tree(root: Path, *, packaged: bool = True) -> None:
    """Three sibling packages, a directory of samples, and a test suite."""
    write(root, "app/__init__.py", '"""App."""\n')
    write(
        root,
        "app/service.py",
        "from core.util import helper\n\n\ndef go():\n    return helper()\n",
    )
    write(root, "core/__init__.py", '"""Core."""\n')
    write(root, "core/util.py", "def helper():\n    return 1\n")
    write(root, "plugins/__init__.py", '"""Plugins."""\n')
    write(root, "plugins/first.py", "from core.util import helper\n\n\nVALUE = helper\n")
    write(root, "samples/one/main.py", 'def main():\n    return "one"\n')
    write(root, "samples/two/main.py", 'def main():\n    return "two"\n')
    write(root, "suite/test_app.py", "def test_go():\n    assert True\n")
    table = '\n[tool.setuptools]\npackages = ["app", "core", "plugins"]\n' if packaged else ""
    write(root, "pyproject.toml", f'[project]\nname = "demo"\nversion = "0.1.0"\n{table}')


def test_named_roots_are_the_only_thing_read(tmp_path: Path) -> None:
    """G2-5: with roots named, everything else is counted and never opened."""
    _three_package_tree(tmp_path)
    scope = discover_within(tmp_path, ("app", "core"))

    assert paths(scope.sources) == [
        "app/__init__.py",
        "app/service.py",
        "core/__init__.py",
        "core/util.py",
    ]
    assert scope.outside == (
        "plugins/__init__.py",
        "plugins/first.py",
        "samples/one/main.py",
        "samples/two/main.py",
        "suite/test_app.py",
    )
    assert scope.outside_tests == ("suite/test_app.py",)
    assert scope.directories_outside == (("plugins", 2), ("samples", 2), ("suite", 1))


def test_a_root_of_the_project_directory_leaves_nothing_outside(tmp_path: Path) -> None:
    """`.` contains everything, which is exactly what a flat tree wants."""
    _three_package_tree(tmp_path)
    scope = discover_within(tmp_path, (".",))
    assert scope.outside == ()
    assert len(scope.sources) == len(discover_sources(tmp_path))


def test_scoping_never_changes_what_a_module_is_called(tmp_path: Path) -> None:
    """The dotted name is Python's, whatever the perimeter is written as."""
    _three_package_tree(tmp_path)
    scope = discover_within(tmp_path, ("app", "core"))
    scoped = {source.path: source.module for source in scope.sources}
    whole = {source.path: source.module for source in discover_sources(tmp_path)}
    assert scoped == {path: whole[path] for path in scoped}
    assert scoped["app/service.py"] == "app.service"


# ---------------------------------------------------------------------------
# Which roots, when nobody has said (G3a, defect G2-1)
# ---------------------------------------------------------------------------


def test_the_packaging_names_the_project_own_packages(tmp_path: Path) -> None:
    """[tool.setuptools].packages is the best evidence a tree can offer."""
    _three_package_tree(tmp_path)
    own = infer_own_source_roots(tmp_path)
    assert own is not None
    assert own.source_roots == ("app", "core", "plugins")
    assert "[tool.setuptools].packages" in own.reason


def test_packages_that_import_each_other_are_one_project(tmp_path: Path) -> None:
    """With no packaging declaration, a cross-package import is the evidence."""
    _three_package_tree(tmp_path, packaged=False)
    own = infer_own_source_roots(tmp_path)
    assert own is not None
    assert own.source_roots == ("app", "core", "plugins")
    assert "import each other" in own.reason


def test_a_directory_of_samples_is_never_proposed(tmp_path: Path) -> None:
    """Data earns no place in the perimeter: it is not a package at all."""
    _three_package_tree(tmp_path)
    own = infer_own_source_roots(tmp_path)
    assert own is not None
    assert "samples" not in own.source_roots
    assert "suite" not in own.source_roots


def test_one_lonely_package_is_not_enough_to_narrow_a_tree(tmp_path: Path) -> None:
    """Conservative: one package beside loose scripts stays the whole tree."""
    write(tmp_path, "solo/__init__.py", '"""Solo."""\n')
    write(tmp_path, "solo/thing.py", "VALUE = 1\n")
    write(tmp_path, "helper.py", "VALUE = 2\n")
    assert infer_own_source_roots(tmp_path) is None


def test_packages_that_ignore_each_other_are_not_claimed_as_one(tmp_path: Path) -> None:
    """No declaration and no import between them: the scan says nothing."""
    write(tmp_path, "left/__init__.py", "")
    write(tmp_path, "left/thing.py", "import json\n\nVALUE = json\n")
    write(tmp_path, "right/__init__.py", "")
    write(tmp_path, "right/other.py", "VALUE = 2\n")
    assert infer_own_source_roots(tmp_path) is None


def test_a_package_reaching_outside_the_candidates_makes_it_unsure(
    tmp_path: Path,
) -> None:
    """Scoping would put a real import outside the perimeter — so: no answer."""
    _three_package_tree(tmp_path, packaged=False)
    write(tmp_path, "samples/__main__.py", "VALUE = 1\n")
    write(
        tmp_path,
        "app/reaches.py",
        "import samples.one.main\n\nVALUE = samples\n",
    )
    assert infer_own_source_roots(tmp_path) is None


def test_a_src_layout_is_left_to_the_ordinary_inference(tmp_path: Path) -> None:
    """`src` is a path, not a package; nothing here second-guesses it."""
    write(tmp_path, "src/demo/__init__.py", "")
    write(tmp_path, "src/demo/thing.py", "VALUE = 1\n")
    assert infer_own_source_roots(tmp_path) is None
    assert resolve_source_roots(tmp_path) == ("src",)


def test_the_origin_says_who_chose_the_roots(tmp_path: Path) -> None:
    """A report says whether the roots are the reader's, the project's or its own."""
    _three_package_tree(tmp_path)
    assert source_root_origin(tmp_path, ["app"]) == ROOTS_GIVEN
    assert source_root_origin(tmp_path) == ROOTS_INFERRED
    write(
        tmp_path,
        "pyproject.toml",
        '[project]\nname = "demo"\nversion = "0.1.0"\n\n'
        '[tool.s0ma]\nsource_roots = ["app"]\ntest_roots = ["suite"]\n',
    )
    assert source_root_origin(tmp_path) == ROOTS_DECLARED
