"""Discovery skips hidden subtrees — nested checkouts cannot collide.

An agent harness that checks a working copy out *inside* the tree it is
working on (Claude Code session worktrees at
``.claude/worktrees/<name>/`` — full copies of the same project) made
``s0ma build <project_root>`` discover every module twice and fail with
``MODULE_NAME_COLLISION``, once per module per worktree. The workaround
was to scope discovery by hand (``s0ma build src``).

The rule these tests pin: a path is skipped when any directory component
**below the search root** is hidden (dot-prefixed) or machine-owned
(``__pycache__``). It generalises the pre-existing special cases — the
``.s0ma`` working-state dir, ``.s0ma.cache``, ``.git``, ``.venv`` — so a
harness nobody has thought of yet is excluded the day it appears.

The load-bearing subtlety, covered by
:class:`TestAnchorInsideHiddenDirectory`: the check runs on the path
below the anchor, never on the absolute path. A project may legitimately
*live* inside a hidden directory — a worktree at
``.claude/worktrees/<name>/`` is itself a working project root — and
testing absolute components would make discovery return nothing at all
for exactly the checkouts this rule exists to disambiguate.
"""

from __future__ import annotations

from textwrap import dedent
from typing import TYPE_CHECKING

import pytest

from s0ma_dsl.adoption_policy import _project_paths
from s0ma_dsl.cli.main import (
    EXIT_SUCCESS,
    S0maCLI,
    _discover_raw_python_tests,
    _discover_s0ma_files,
)
from s0ma_dsl.discovery import (
    is_in_hidden_subtree,
    iter_visible_dirs,
    iter_visible_files,
)
from s0ma_dsl.project import S0maProject

if TYPE_CHECKING:
    from pathlib import Path


_MODULE_S0MA = """\
module {name}
    layer: DOMAIN
    version: 0.1.0
    intent: "Hidden-dir discovery fixture."
    exports: [do_{name}]
    uses: none
    requires: none
    soft_requires: none
    runtime_only_requires: none
    deferred_requires: none
    exports_helpers: none

nerve do_{name} :: DOMAIN
    kind: FUNCTION
    visibility: PUBLIC
    intent: "A simple function for hidden-dir discovery coverage."
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


def _write_project(root: Path, *, name: str = "copy") -> Path:
    """Stand up a minimal project with one module at ``src/<name>.s0ma``."""
    root.mkdir(parents=True, exist_ok=True)
    (root / "pyproject.toml").write_text(
        dedent("""
            [project]
            name = "hidden_dir_proj"
            version = "0.1.0"

            [tool.s0ma]
            source_roots = ["src"]
        """).lstrip(),
        encoding="utf-8",
    )
    src = root / "src"
    src.mkdir(exist_ok=True)
    (src / f"{name}.s0ma").write_text(
        _MODULE_S0MA.format(name=name), encoding="utf-8"
    )
    return src


def _add_worktree_copy(root: Path, *, worktree: str = "x", name: str = "copy") -> Path:
    """Nest a full checkout of the project under ``.claude/worktrees/``."""
    nested = root / ".claude" / "worktrees" / worktree
    _write_project(nested, name=name)
    return nested


class TestDiscoveryIgnoresNestedCheckouts:
    """The reported failure: a worktree copy must not collide."""

    def test_worktree_copy_not_discovered(self, tmp_path: Path) -> None:
        root = tmp_path / "proj"
        src = _write_project(root)
        _add_worktree_copy(root)

        discovered = _discover_s0ma_files(str(root))

        assert discovered == [src / "copy.s0ma"]

    def test_build_at_project_root_does_not_collide(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str],
    ) -> None:
        """``s0ma build <project_root>`` is green with a worktree present.

        This is the end-to-end shape of the report: before the guard,
        ``src/copy.s0ma`` and ``.claude/worktrees/x/src/copy.s0ma`` both
        declared ``module copy`` and the build died with
        ``MODULE_NAME_COLLISION``.
        """
        root = tmp_path / "proj"
        _write_project(root)
        _add_worktree_copy(root)

        rc = S0maCLI().run([
            "build", str(root),
            "--output-dir", str(tmp_path / "build"),
            "--mode", "dev",
            "--no-cache",
        ])

        captured = capsys.readouterr()
        assert "MODULE_NAME_COLLISION" not in captured.out + captured.err
        assert rc == EXIT_SUCCESS

    def test_two_worktrees_still_discover_one_module(self, tmp_path: Path) -> None:
        """The reported tree had several worktrees, each a full copy."""
        root = tmp_path / "proj"
        src = _write_project(root)
        _add_worktree_copy(root, worktree="alpha")
        _add_worktree_copy(root, worktree="beta")

        assert _discover_s0ma_files(str(root)) == [src / "copy.s0ma"]


class TestAnchorInsideHiddenDirectory:
    """A project may itself live under a hidden directory."""

    def test_discovery_inside_a_worktree_finds_its_own_sources(
        self, tmp_path: Path,
    ) -> None:
        """Anchoring *at* the worktree still discovers that worktree's module.

        The hidden check is relative to the search root. Were it applied
        to absolute components, a session working inside
        ``.claude/worktrees/<name>/`` would discover nothing.
        """
        root = tmp_path / "proj"
        _write_project(root)
        nested = _add_worktree_copy(root)

        discovered = _discover_s0ma_files(str(nested))

        assert discovered == [nested / "src" / "copy.s0ma"]

    def test_explicit_source_root_inside_hidden_dir_is_honoured(
        self, tmp_path: Path,
    ) -> None:
        """An explicitly named root under a hidden dir is not second-guessed."""
        root = tmp_path / "proj"
        _write_project(root)
        nested = _add_worktree_copy(root)

        discovered = _discover_s0ma_files(str(nested / "src"))

        assert discovered == [nested / "src" / "copy.s0ma"]


class TestExcludedDirectoryShapes:
    """Which directory names are skipped, and which are not."""

    @pytest.mark.parametrize(
        "hidden_dir",
        [".claude", ".git", ".venv", ".s0ma", ".s0ma.cache", "__pycache__"],
    )
    def test_excluded_dirs_are_skipped(
        self, tmp_path: Path, hidden_dir: str,
    ) -> None:
        src = tmp_path / "src"
        src.mkdir()
        kept = src / "kept.s0ma"
        kept.write_text("module kept\n", encoding="utf-8")
        buried = src / hidden_dir / "buried.s0ma"
        buried.parent.mkdir(parents=True)
        buried.write_text("module buried\n", encoding="utf-8")

        assert iter_visible_files(src, "*.s0ma") == [kept]

    def test_ordinary_dirs_are_still_walked(self, tmp_path: Path) -> None:
        """The guard is about hidden dirs, not about nesting."""
        src = tmp_path / "src"
        nested = src / "domain" / "billing"
        nested.mkdir(parents=True)
        deep = nested / "deep.s0ma"
        deep.write_text("module deep\n", encoding="utf-8")

        assert iter_visible_files(src, "*.s0ma") == [deep]

    def test_s0ma_working_state_directory_is_not_returned_as_a_file(
        self, tmp_path: Path,
    ) -> None:
        """A ``.s0ma`` *directory* also matches ``*.s0ma``.

        Handing it to the parser died with ``Is a directory``; only real
        files are ever returned.
        """
        src = tmp_path / "src"
        src.mkdir()
        (src / ".s0ma").mkdir()
        (src / ".s0ma" / "registry.db").write_text("", encoding="utf-8")

        assert iter_visible_files(src, "*.s0ma") == []
        assert _discover_s0ma_files(str(src)) == []

    def test_hidden_file_is_not_excluded(self, tmp_path: Path) -> None:
        """The rule is about directory components, not basenames."""
        src = tmp_path / "src"
        src.mkdir()
        dotfile = src / ".hidden.s0ma"
        dotfile.write_text("module hidden\n", encoding="utf-8")

        assert iter_visible_files(src, "*.s0ma") == [dotfile]

    def test_explicit_file_argument_is_never_filtered(
        self, tmp_path: Path,
    ) -> None:
        """Naming a file directly is an explicit instruction, not discovery."""
        root = tmp_path / "proj"
        _write_project(root)
        nested = _add_worktree_copy(root)
        target = nested / "src" / "copy.s0ma"

        assert _discover_s0ma_files(str(target)) == [target]


class TestPredicate:
    """``is_in_hidden_subtree`` — used where globs stay path-shaped."""

    def test_file_under_hidden_dir_is_excluded(self, tmp_path: Path) -> None:
        path = tmp_path / ".claude" / "worktrees" / "x" / "fixture.json"
        assert is_in_hidden_subtree(path, tmp_path) is True

    def test_visible_file_is_not_excluded(self, tmp_path: Path) -> None:
        path = tmp_path / "tests" / "fixtures" / "fixture.json"
        assert is_in_hidden_subtree(path, tmp_path) is False

    def test_root_relative_not_absolute(self, tmp_path: Path) -> None:
        """Hidden components *above* the anchor do not exclude."""
        root = tmp_path / ".claude" / "worktrees" / "x"
        path = root / "tests" / "fixture.json"
        assert is_in_hidden_subtree(path, root) is False

    def test_path_outside_root_is_excluded(self, tmp_path: Path) -> None:
        """Discovery cannot reason about ownership outside its anchor."""
        root = tmp_path / "proj"
        root.mkdir()
        assert is_in_hidden_subtree(tmp_path / "elsewhere.json", root) is True


class TestVisibleDirs:
    """``s0ma migrate-layout`` deletes what this returns."""

    def test_cache_dir_in_nested_checkout_is_not_returned(
        self, tmp_path: Path,
    ) -> None:
        """A sibling checkout owns its own artifacts — never delete them."""
        own = tmp_path / "build" / "__s0ma_cache__"
        own.mkdir(parents=True)
        foreign = (
            tmp_path / ".claude" / "worktrees" / "x" / "build" / "__s0ma_cache__"
        )
        foreign.mkdir(parents=True)

        assert iter_visible_dirs(tmp_path, "__s0ma_cache__") == [own]

    def test_matches_are_not_descended_into(self, tmp_path: Path) -> None:
        outer = tmp_path / "build" / "__s0ma_cache__"
        nested = outer / "inner" / "__s0ma_cache__"
        nested.mkdir(parents=True)

        assert iter_visible_dirs(tmp_path, "__s0ma_cache__") == [outer]


class TestOtherWalkers:
    """The guard reaches the other walkers that answer "what is ours?"."""

    def test_raw_python_test_discovery_skips_nested_checkout(
        self, tmp_path: Path,
    ) -> None:
        tests = tmp_path / "tests"
        tests.mkdir()
        own = tests / "test_smoke.py"
        own.write_text("def test_smoke():\n    assert True\n", encoding="utf-8")
        foreign = tests / ".claude" / "worktrees" / "x" / "test_smoke.py"
        foreign.parent.mkdir(parents=True)
        foreign.write_text("def test_smoke():\n    assert True\n", encoding="utf-8")

        assert _discover_raw_python_tests([tests]) == [own.resolve()]

    def test_project_paths_report_excludes_nested_checkout(
        self, tmp_path: Path,
    ) -> None:
        """Adoption reporting must not count a copy as unmodeled debt."""
        root = tmp_path / "proj"
        _write_project(root)
        _add_worktree_copy(root)

        paths = _project_paths(S0maProject.discover(root))

        assert "src/copy.s0ma" in paths
        assert not [p for p in paths if p.startswith(".claude/")]
