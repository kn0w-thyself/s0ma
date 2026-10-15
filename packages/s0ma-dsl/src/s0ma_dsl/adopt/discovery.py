"""Discovery — which Python files a tree owns, and what each one is for.

Rung 0 of the retrofit ladder starts here. Before anything can be
proposed, converted or measured, one question has to be answered
honestly: *which files are this project's own source, and what is each
one for?* :func:`discover_sources` answers it by walking the tree and
nothing else.

What this module will not do
----------------------------

* **It never imports or executes the tree** (retrofit rule R-1). Roles
  are decided from :mod:`ast` over file text; a file that cannot be
  parsed is still discovered, it just falls back to the plainest role.
* **It never writes anything** (retrofit rule R-2) — no cache, no
  temporary file beside the sources, no ``__pycache__`` (nothing is
  imported, so none is produced). In particular it does not call
  :func:`s0ma_dsl.derived_surface.derive_python_surface`, which caches
  under ``.s0ma.cache/``.
* **It never follows a symlink out of the tree.** A symlinked directory
  is never descended into at all, which also makes a symlink loop a
  non-event rather than a recursion error.

What "owns" means
-----------------

Every discovered file is attributed to exactly one *source root* — the
longest configured (or inferred) root that contains it, or ``"."`` for
anything outside them all. The source root decides the dotted module
name, so ``src/bookshelf/api.py`` under source root ``src`` is
``bookshelf.api`` while ``tests/test_catalog.py`` outside it is
``tests.test_catalog``. :func:`discover_sources` walks the whole tree:
tests and scripts usually sit *outside* the source roots and a report
that never saw them could not say how much of the tree is test code.

Scoping: what the roots are *for*
---------------------------------

Naming source roots is how somebody says "this is my code and that is
not". A repository with sample applications, reference solutions or
fixture trees beside its own packages is the ordinary case, not the
exotic one, and reading those trees as material to convert made the
first real pilot's numbers fifteen times too large.

So :func:`discover_within` reads application code **only** from the
roots it is given. Everything else is still *counted* — the scan says
how many other Python files there are and which directories they sit in,
in one line — but it is never opened, never censused and never offered
for conversion. Counting costs a directory listing; reading costs the
file. :func:`discover_sources` keeps its whole-tree behaviour for
callers that want the unfiltered reading.

Which roots, when nobody has said
---------------------------------

:func:`infer_own_source_roots` answers "several packages sit side by side
here — which of them is this project?" from the tree's own evidence, and
returns ``None`` rather than guessing. See its docstring for the rules.

Exclusions compose rather than compete
--------------------------------------

The house rule for "not project source" lives in
:mod:`s0ma_dsl.discovery` (:func:`~s0ma_dsl.discovery.is_excluded_dir_name`
— hidden directories and ``__pycache__``). This module adds the
directories a *brownfield* tree carries that a s0ma project does not
(:data:`ADOPT_EXCLUDED_DIR_NAMES`), and the project's own configured
build directory. Nothing here re-implements the house rule; it calls it.

Consumers: ``adopt/census.py`` (per-file facts), ``adopt/graph.py``
(first-party resolution), ``adopt/proposals.py`` (the perimeter
suggestion) and ``adopt/report.py``.
"""

from __future__ import annotations

import ast
import re
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from s0ma_dsl.adopt.model import SourceFile
from s0ma_dsl.discovery import is_excluded_dir_name

if TYPE_CHECKING:
    from collections.abc import Iterator, Sequence

    from s0ma_dsl.project import S0maProject

__all__ = [
    "ADOPT_EXCLUDED_DIR_NAMES",
    "ADOPT_EXCLUDED_DIR_SUFFIXES",
    "ROOTS_DECLARED",
    "ROOTS_GIVEN",
    "ROOTS_INFERRED",
    "ROOTS_PROPOSED",
    "DiscoveryScope",
    "OwnSourceRoots",
    "discover_sources",
    "discover_within",
    "infer_own_source_roots",
    "is_transpiled_artifact",
    "package_prefix",
    "resolve_source_roots",
    "source_root_origin",
]

#: Where a scan's source roots came from. Reported so the text and the
#: JSON can say whether the reader chose them, the project declares them,
#: the scan worked them out, or nothing narrowed the tree at all.
ROOTS_GIVEN = "given"
ROOTS_DECLARED = "declared"
ROOTS_PROPOSED = "proposed"
ROOTS_INFERRED = "inferred"


#: Directory names a brownfield tree carries that the house rule in
#: :mod:`s0ma_dsl.discovery` does not name, because a s0ma project never
#: grows them: unhidden virtual environments (``venv`` / ``env``), a
#: JavaScript toolchain's dependency tree, and the two conventional
#: packaging output directories.
#:
#: The trade-off in ``build`` and ``dist`` is deliberate and worth
#: stating: a project whose *source* lives in a package literally named
#: ``build`` will not be scanned there. That shape is rare, the
#: setuptools output directory is not, and a scan that walked a build
#: tree would report every module twice — once as source and once as a
#: copy — which is the failure that is expensive to explain.
ADOPT_EXCLUDED_DIR_NAMES: frozenset[str] = frozenset(
    {"venv", "env", "node_modules", "build", "dist", "site-packages"}
)

#: Directory name *suffixes* that mark installation metadata rather than
#: source. Matched on the whole basename, so ``s0ma_dsl.egg-info`` is
#: skipped and a package named ``egginfo`` is not.
ADOPT_EXCLUDED_DIR_SUFFIXES: tuple[str, ...] = (".egg-info", ".egg-link", ".dist-info")

# The transpiler's per-file hash headers. A file carrying *both* is a
# generated s0ma artifact: it already has a ``.s0ma`` source, so
# discovering it as retrofit material would offer to convert a
# conversion. These two patterns mirror the private pair in
# ``cli/adopt_commands.py`` exactly (same anchors, same capture) and are
# restated rather than imported on purpose: ``adopt/`` is library code
# and importing a private name out of a CLI handler module would invert
# the dependency direction the package layout depends on.
_SOURCE_HASH_RE = re.compile(r"^# s0ma-source-hash:\s*sha256:(\w+)$", re.MULTILINE)
_OUTPUT_HASH_RE = re.compile(r"^# s0ma-output-hash:\s*sha256:(\w+)$", re.MULTILINE)

# The four role strings, fixed by ``model.SourceFile``.
_ROLE_APP = "app"
_ROLE_TEST = "test"
_ROLE_SCRIPT = "script"
_ROLE_PACKAGE_MARKER = "package_marker"

# Directory names that make everything below them test code, and the
# filename shapes that make a single file test code. Compared exactly as
# written — a directory named ``Tests`` is not matched — because a
# case-insensitive comparison would classify differently on a
# case-folding filesystem than on a case-sensitive one, and a scan has
# to say the same thing on macOS, Linux and Windows.
_TEST_DIR_NAMES = frozenset({"tests", "test"})
_TEST_FILE_NAMES = frozenset({"conftest.py"})
_TEST_FILE_PREFIX = "test_"
_TEST_FILE_SUFFIX = "_test.py"

#: Fallback dotted name for the degenerate case of an ``__init__.py``
#: sitting directly at a source root that is the project root itself,
#: where there is no directory name left to take the package name from.
_ROOT_PACKAGE_FALLBACK = "__root__"


def is_transpiled_artifact(text: str) -> bool:
    """Return ``True`` when *text* is transpiler output, not hand-written source.

    A generated module carries both of the transpiler's hash headers.
    One alone is not enough: a hand-written file that happens to quote a
    header (this module does, in a comment) must not be mistaken for
    generated code.
    """
    return bool(_SOURCE_HASH_RE.search(text) and _OUTPUT_HASH_RE.search(text))


def resolve_source_roots(root: Path, source_roots: Sequence[str] | None = None) -> tuple[str, ...]:
    """Return the tree's source roots as project-relative POSIX strings.

    Precedence, highest first:

    1. *source_roots* as given by the caller (``--source-root`` on the
       command line). An explicit answer is never second-guessed.
    2. ``[tool.s0ma].source_roots`` when *root* itself declares a s0ma
       project.
    3. Inference: ``"src"`` when a ``src/<package>/__init__.py`` exists,
       otherwise ``"."`` — the root itself.

    ``"."`` means the project root, matching
    :attr:`~s0ma_dsl.adopt.model.SourceFile.source_root`'s convention for
    a flat tree. Results are de-duplicated with order preserved.
    """
    if source_roots is not None:
        declared = tuple(_normalise_root(value) for value in source_roots)
        return _dedupe(declared) or (".",)

    project = _project_declared_at(root)
    if project is not None:
        configured: list[str] = []
        for candidate in project.source_roots:
            relative = _relative_posix(candidate, root)
            if relative is not None:
                configured.append(relative)
        if configured:
            return _dedupe(tuple(configured))

    src = root / "src"
    if src.is_dir() and any(
        child.is_dir() and (child / "__init__.py").is_file() for child in _sorted_children(src)
    ):
        return ("src",)
    return (".",)


def source_root_origin(root: Path, source_roots: Sequence[str] | None = None) -> str:
    """Who decided the source roots: the caller, the project, or the scan.

    The same three-step precedence :func:`resolve_source_roots` follows,
    reported rather than applied. A report says which it was because the
    three mean different things to a reader: ``given`` is their own
    answer, ``declared`` is their project's, and ``inferred`` is the
    scan's best reading of a tree nobody has said anything about.
    """
    if source_roots is not None:
        return ROOTS_GIVEN
    project = _project_declared_at(root)
    if project is not None and any(
        _relative_posix(candidate, root) is not None for candidate in project.source_roots
    ):
        return ROOTS_DECLARED
    return ROOTS_INFERRED


@dataclass(frozen=True, slots=True)
class OwnSourceRoots:
    """Top-level packages a tree's own evidence says are the project's code."""

    source_roots: tuple[str, ...]
    """The directories to read as source, sorted, never containing ``"."``."""

    reason: str
    """One plain sentence naming the evidence, for the report to print."""


def infer_own_source_roots(root: Path) -> OwnSourceRoots | None:
    """Which top-level packages are this project's own code, or ``None``.

    Only asked of a tree that has said nothing — no ``--source-root``, no
    ``[tool.s0ma]``, and no ``src/`` layout to infer from. Left alone,
    such a tree is read as one source root, ``"."``, which means every
    Python file under it: the sample applications a benchmark runs, the
    reference solutions a linter is tested against, the fixture trees a
    generator writes. That reading is what made the first real pilot's
    scan report fifteen times more work than there was.

    **What counts as the project's own code**

    * A top-level directory that is a Python package (it has an
      ``__init__.py``) and is **named by the tree's own packaging**:
      ``[tool.setuptools].packages``, ``[tool.setuptools.packages.find]``,
      ``[tool.hatch.build.targets.wheel].packages``,
      ``[tool.poetry].packages``, or the module half of a
      ``[project.scripts]`` entry point. A project saying "these are my
      packages" is the best evidence there is, and it is evidence the
      author wrote for another reason, so it cannot have been tuned to
      please a scan.
    * Failing that: a top-level package that **another top-level package
      imports**. Code that reaches across to code is one program.

    **What counts as data**

    A directory whose Python is named by nothing and imported by nothing,
    and which holds several self-contained trees. It is not listed here
    because it is never a candidate — the rule is stated the other way
    round on purpose, so a directory has to *earn* its way into the
    perimeter rather than argue its way out.

    **When unsure, say nothing**

    ``None`` comes back — and the caller falls back to reading the whole
    tree — whenever the evidence is thin: fewer than two packages side by
    side with no packaging declaration, no package importing another, or
    a package that imports something outside the candidates (which would
    mean the perimeter proposed here cannot hold the project's own
    imports). The scan then proposes the whole directory, says so, and
    ``--source-root`` settles it.

    Reads ``pyproject.toml`` and the candidate packages' own files; writes
    nothing, imports nothing (retrofit rules R-1 and R-2).
    """
    candidates = _top_level_packages(root)
    if not candidates:
        return None

    named, keys = _packaged_top_level_names(root)
    declared = tuple(name for name in candidates if name in named)
    if declared:
        return OwnSourceRoots(
            source_roots=declared,
            reason=(
                f"{_join_backticked(declared)} "
                f"{'is' if len(declared) == 1 else 'are'} what this project "
                f"packages ({_join_backticked(keys)} in pyproject.toml "
                f"{'names' if len(keys) == 1 else 'name'} "
                f"{'it' if len(declared) == 1 else 'them'})"
            ),
        )

    if len(candidates) < 2:
        return None
    reaches, strays = _package_imports(root, candidates)
    if strays or not reaches:
        return None
    return OwnSourceRoots(
        source_roots=candidates,
        reason=(
            f"{_join_backticked(candidates)} are packages sitting side by side "
            f"here and they import each other, so they are one project"
        ),
    )


def _top_level_packages(root: Path) -> tuple[str, ...]:
    """Directories directly under *root* that are Python packages, sorted."""
    return tuple(
        sorted(
            child.name
            for child in _sorted_children(root)
            if child.is_dir()
            and not child.is_symlink()
            and not _is_skipped_dir_name(child.name)
            and (child / "__init__.py").is_file()
        )
    )


def _packaged_top_level_names(root: Path) -> tuple[frozenset[str], tuple[str, ...]]:
    """Top-level names the tree's packaging declares, and the keys that said so.

    Only *top-level* names are collected: a ``src``-layout declaration
    such as ``packages = ["src/bookshelf"]`` names a package that is not a
    directory under the root, so it contributes nothing here and the
    ordinary ``src`` inference keeps the tree. Anything unreadable or
    shaped unexpectedly is skipped rather than guessed at.
    """
    document = _pyproject_document(root)
    if not document:
        return frozenset(), ()

    found: dict[str, None] = {}
    keys: list[str] = []

    def take(key: str, names: Sequence[str]) -> None:
        kept = [name for name in names if name and "/" not in name and "." not in name]
        if kept:
            keys.append(key)
            found.update(dict.fromkeys(kept))

    tool = document.get("tool")
    tool = tool if isinstance(tool, dict) else {}

    setuptools = tool.get("setuptools")
    if isinstance(setuptools, dict):
        packages = setuptools.get("packages")
        if isinstance(packages, list):
            take("[tool.setuptools].packages", [p for p in packages if isinstance(p, str)])
        elif isinstance(packages, dict):
            take("[tool.setuptools].packages.find", _find_includes(packages.get("find")))
        find = setuptools.get("packages.find")
        if isinstance(find, dict):
            take("[tool.setuptools.packages.find]", _find_includes(find))

    hatch = _dig(tool, ("hatch", "build", "targets", "wheel"))
    if isinstance(hatch, dict) and isinstance(hatch.get("packages"), list):
        take(
            "[tool.hatch.build.targets.wheel].packages",
            [p for p in hatch["packages"] if isinstance(p, str)],
        )

    poetry = tool.get("poetry")
    if isinstance(poetry, dict) and isinstance(poetry.get("packages"), list):
        take(
            "[tool.poetry].packages",
            [
                entry["include"]
                for entry in poetry["packages"]
                if isinstance(entry, dict) and isinstance(entry.get("include"), str)
            ],
        )

    for table in ("scripts", "gui-scripts"):
        entries = document.get("project", {})
        entries = entries.get(table) if isinstance(entries, dict) else None
        if isinstance(entries, dict):
            take(
                f"[project.{table}]",
                [
                    str(target).split(":", 1)[0].split(".", 1)[0]
                    for target in entries.values()
                    if isinstance(target, str)
                ],
            )

    return frozenset(found), tuple(keys)


def _find_includes(find: object) -> list[str]:
    """``include`` patterns of a setuptools ``packages.find`` table, un-globbed."""
    if not isinstance(find, dict):
        return []
    where = find.get("where")
    if isinstance(where, list) and any(entry not in ("", ".") for entry in where):
        # A `where` pointing at src/ is a layout the ordinary inference
        # already reads correctly; nothing to add.
        return []
    include = find.get("include")
    if not isinstance(include, list):
        return []
    return [entry.split("*", 1)[0].rstrip(".") for entry in include if isinstance(entry, str)]


def _dig(table: dict[str, object], path: Sequence[str]) -> object:
    """Walk nested TOML tables, returning ``None`` at the first missing step."""
    current: object = table
    for key in path:
        if not isinstance(current, dict):
            return None
        current = current.get(key)
    return current


def _package_imports(
    root: Path, candidates: tuple[str, ...]
) -> tuple[bool, tuple[str, ...]]:
    """Do the candidate packages import each other, and do they import elsewhere?

    Returns ``(reaches, strays)``: whether one candidate imports another,
    and the sorted top-level names a candidate imports that are Python
    directories under this root but *not* candidates. A stray is why the
    answer has to be "unsure": scoping to the candidates would put an
    import the project really makes outside the perimeter.
    """
    neighbours = {
        child.name
        for child in _sorted_children(root)
        if child.is_dir() and not _is_skipped_dir_name(child.name)
    }
    reaches = False
    strays: set[str] = set()
    for package in candidates:
        for path in _walk_python_files(root / package, skipped=frozenset()):
            relative = _relative_posix(path, root)
            if relative is None or _is_test_path(relative):
                continue
            for name in _top_level_import_names(_read_text(path)):
                if name == package:
                    continue
                if name in candidates:
                    reaches = True
                elif name in neighbours:
                    strays.add(name)
    return reaches, tuple(sorted(strays))


def _top_level_import_names(text: str | None) -> frozenset[str]:
    """The first dotted segment of every absolute import in *text*.

    Relative imports are skipped: they can never cross out of the package
    they are written in, so they say nothing about which packages belong
    together.
    """
    tree = _parse(text)
    if tree is None:
        return frozenset()
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name.split(".", 1)[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            names.add(node.module.split(".", 1)[0])
    return frozenset(names)


def _join_backticked(items: Sequence[str]) -> str:
    """``a``, ``b`` and ``c`` — the house's list voice, in backticks."""
    quoted = [f"`{item}`" for item in items]
    if len(quoted) <= 1:
        return "".join(quoted)
    return ", ".join(quoted[:-1]) + f" and {quoted[-1]}"


def discover_sources(
    root: Path, source_roots: Sequence[str] | None = None
) -> tuple[SourceFile, ...]:
    """Return every Python file *root* owns, sorted by path.

    The walk prunes machine-owned directories (the house rule plus
    :data:`ADOPT_EXCLUDED_DIR_NAMES`), the project's configured build
    directory, and generated transpiler output. What survives is
    hand-written Python, each file attributed to a source root, given the
    dotted module name it would import as, and labelled with one role:

    * ``"test"`` — under a ``tests``/``test`` directory, or named
      ``test_*.py``, ``*_test.py`` or ``conftest.py``.
    * ``"package_marker"`` — an ``__init__.py`` carrying nothing but a
      docstring, imports and ``__all__``.
    * ``"script"`` — carries an ``if __name__ == "__main__":`` guard and
      sits outside any package.
    * ``"app"`` — everything else: the application code a retrofit
      converts.

    Reads only, on every path (retrofit rules R-1 and R-2). Returns an
    empty tuple when *root* is not a directory.

    The whole tree, whatever the roots are: use :func:`discover_within`
    when only the project's own code is wanted and everything else should
    be counted rather than read.
    """
    return _discover(root, resolve_source_roots(root, source_roots), scoped=False).sources


@dataclass(frozen=True, slots=True)
class DiscoveryScope:
    """What a scan read as the project's own code, and what it left outside."""

    source_roots: tuple[str, ...]
    """The roots the walk read application code from, in the order given."""

    sources: tuple[SourceFile, ...]
    """Every Python file inside those roots, classified, sorted by path."""

    outside: tuple[str, ...]
    """Project-relative POSIX paths of the Python files outside them.

    Counted, never opened: these files are not part of this scan, so
    reading them would cost time and offer work nobody asked for.
    """

    outside_tests: tuple[str, ...]
    """The subset of :attr:`outside` that is test code by name or place.

    Decided from the path alone, which costs nothing, so a report can
    still say how much of what it left out was a test suite.
    """

    @property
    def directories_outside(self) -> tuple[tuple[str, int], ...]:
        """``(directory, file count)`` for what was left out, biggest first.

        The directory is the top-level one, because that is the unit a
        reader recognises (``samples/``, ``fixtures/``) and the unit
        ``--source-root`` works in. Ties break by name so the line reads
        the same on every machine.
        """
        counts: dict[str, int] = {}
        for path in self.outside:
            head = path.split("/", 1)[0] if "/" in path else "."
            counts[head] = counts.get(head, 0) + 1
        return tuple(sorted(counts.items(), key=lambda item: (-item[1], item[0])))


def discover_within(root: Path, source_roots: Sequence[str]) -> DiscoveryScope:
    """Discover the Python inside *source_roots*, and count the rest.

    The scoping rule in one sentence: **a file is part of the scan when a
    named source root contains it.** A root of ``"."`` is the project
    directory itself and therefore contains everything, which is exactly
    what a flat tree wants.

    Files outside every named root are recorded as paths and nothing
    more. They are not read, not parsed, not censused and not proposed
    for conversion — but they are counted, and their top-level
    directories are counted with them, so the report can say what it left
    out and the reader can name it with ``--source-root`` if the scan got
    it wrong.

    Reads only (retrofit rules R-1 and R-2).
    """
    return _discover(root, tuple(source_roots) or (".",), scoped=True)


def _discover(
    root: Path, roots: tuple[str, ...], *, scoped: bool
) -> DiscoveryScope:
    """The one walk both entry points share; *scoped* decides what is read."""
    if not root.is_dir():
        return DiscoveryScope(source_roots=roots, sources=(), outside=(), outside_tests=())

    ownership = _ownership_order(roots)
    covers_everything = "." in roots
    skipped = _skipped_directories(root)

    discovered: list[SourceFile] = []
    outside: list[str] = []
    outside_tests: list[str] = []
    for path in _walk_python_files(root, skipped=skipped):
        relative = _relative_posix(path, root)
        if relative is None:
            continue
        owning_root = _owning_source_root(relative, ownership)
        if scoped and owning_root == "." and not covers_everything:
            outside.append(relative)
            if _is_test_path(relative):
                outside_tests.append(relative)
            continue
        text = _read_text(path)
        if text is not None and is_transpiled_artifact(text):
            continue
        discovered.append(
            SourceFile(
                path=relative,
                module=_module_name(relative, owning_root, root),
                source_root=owning_root,
                role=_classify_role(path, relative, text),
            )
        )
    return DiscoveryScope(
        source_roots=roots,
        sources=tuple(sorted(discovered, key=lambda source: source.path)),
        outside=tuple(sorted(outside)),
        outside_tests=tuple(sorted(outside_tests)),
    )


# ---------------------------------------------------------------------------
# Walking
# ---------------------------------------------------------------------------


def _walk_python_files(root: Path, *, skipped: frozenset[Path]) -> Iterator[Path]:
    """Yield every ``.py`` file under *root*, pruning as documented above.

    Iterative rather than recursive, and symlinked directories are never
    entered, so neither a deep tree nor a symlink loop can end the scan
    with an exception.
    """
    pending = [root]
    root_resolved = _safe_resolve(root)
    while pending:
        directory = pending.pop()
        try:
            entries = sorted(directory.iterdir())
        except OSError:
            # An unreadable directory is reported by its absence rather
            # than by a crash: a scan is a read of someone else's tree
            # and has no business refusing over a permission bit.
            continue
        for entry in entries:
            if entry.is_symlink():
                if _keeps_symlinked_file(entry, root_resolved):
                    yield entry
                continue
            if entry.is_dir():
                if _is_skipped_dir_name(entry.name):
                    continue
                if _safe_resolve(entry) in skipped:
                    continue
                pending.append(entry)
            elif entry.suffix == ".py" and entry.is_file():
                yield entry


def _keeps_symlinked_file(entry: Path, root_resolved: Path | None) -> bool:
    """Return ``True`` for a symlink the walk may report as a source file.

    A symlink to a *directory* is never kept and never entered —
    following one is how a walk both double-counts a subtree and loops
    forever, and neither failure is worth the rare tree that wants it. A
    symlink to a *file* is kept only while its target still sits inside
    the project, because a scan may not reach outside the root it was
    handed.
    """
    if entry.is_dir():
        return False
    if entry.suffix != ".py" or not entry.is_file():
        return False
    target = _safe_resolve(entry)
    if target is None or root_resolved is None:
        return False
    return target.is_relative_to(root_resolved)


def _is_skipped_dir_name(name: str) -> bool:
    """Return ``True`` when a directory of this name is never walked."""
    if is_excluded_dir_name(name):
        return True
    if name in ADOPT_EXCLUDED_DIR_NAMES:
        return True
    return name.endswith(ADOPT_EXCLUDED_DIR_SUFFIXES)


def _skipped_directories(root: Path) -> frozenset[Path]:
    """Return resolved directories to prune because the project declares them.

    Today that is the configured (or defaulted) s0ma build directory: a
    tree partway through a retrofit has generated Python in it, and
    offering to convert generated Python is the one thing a scan must
    never do. ``.s0ma.cache`` needs no entry — it is hidden, so the house
    rule already prunes it.
    """
    project = _project_declared_at(root)
    if project is None:
        return frozenset()
    build_dir = _safe_resolve(project.build_dir)
    return frozenset() if build_dir is None else frozenset({build_dir})


# ---------------------------------------------------------------------------
# Source roots, ownership and module names
# ---------------------------------------------------------------------------


def _ownership_order(roots: tuple[str, ...]) -> tuple[str, ...]:
    """Return *roots* longest-first, so the most specific one claims a file."""
    return tuple(sorted(roots, key=lambda value: (-len(value), value)))


def _owning_source_root(relative: str, ownership: tuple[str, ...]) -> str:
    """Return the source root *relative* belongs to, or ``"."`` for none."""
    for candidate in ownership:
        if candidate == ".":
            continue
        if relative.startswith(f"{candidate}/"):
            return candidate
    return "."


def package_prefix(source_root: Path) -> str:
    """The dotted prefix a source root contributes to the names beneath it.

    A source root that is **itself a Python package** — ``harness/``, with
    its own ``__init__.py`` — is imported by its own name, because what
    sits on the import path is the directory *above* it. So
    ``harness/cli.py`` is ``harness.cli`` however the perimeter is written,
    and the first-party import graph resolves ``from harness.runner import
    …`` to the module that really is ``harness.runner``.

    A source root that is not a package (``src``, or the project directory
    itself) contributes nothing, which is the ``src``-layout convention
    unchanged: ``src/bookshelf/api.py`` stays ``bookshelf.api``.

    The one rule, in one place: ``adopt/status.py`` asks the same question
    of a ``.s0ma`` draft and of a built module, so a module cannot be
    called two things by two commands. (The *s0ma* module name is flat and
    is declared in the draft — ``module cli`` — which is a different name
    for a different thing, and the draft says so.)
    """
    name = source_root.name
    if not name or name == ".":
        return ""
    return f"{name}." if (source_root / "__init__.py").is_file() else ""


def _module_name(relative: str, source_root: str, root: Path) -> str:
    """Return the dotted name *relative* would import as under *source_root*.

    ``__init__.py`` names its package rather than itself, so
    ``bookshelf/__init__.py`` is ``bookshelf``. A source root that is
    itself a package contributes its own name as a prefix
    (:func:`package_prefix`). The one degenerate case — an ``__init__.py``
    sitting directly at a source root, which would leave no name at all —
    takes the containing directory's name, and
    :data:`_ROOT_PACKAGE_FALLBACK` when even that is empty.

    The result is what Python *would* call the module; it is not checked
    for being a legal identifier. A directory named ``my-dir`` yields
    ``my-dir.mod``, which is the truth about an unimportable file and is
    more useful in a report than a silently corrected name.
    """
    inner = relative if source_root == "." else relative[len(source_root) + 1 :]
    parts = inner.split("/")
    if parts[-1] == "__init__.py":
        parts = parts[:-1]
    else:
        parts[-1] = parts[-1].removesuffix(".py")
    name = ".".join(part for part in parts if part)
    if name:
        if source_root == ".":
            return name
        return package_prefix(root / source_root) + name
    if source_root != ".":
        return Path(source_root).name or _ROOT_PACKAGE_FALLBACK
    return root.name or _ROOT_PACKAGE_FALLBACK


# ---------------------------------------------------------------------------
# Roles
# ---------------------------------------------------------------------------


def _classify_role(path: Path, relative: str, text: str | None) -> str:
    """Return the one role *path* carries, most specific rule first."""
    if _is_test_path(relative):
        return _ROLE_TEST
    tree = _parse(text)
    if path.name == "__init__.py":
        # An ``__init__.py`` that will not parse is deliberately *not* a
        # marker: "when in doubt, not a marker" keeps a real-but-broken
        # package file visible as application code rather than filed away
        # as harmless. The same conservative default that
        # ``project.is_empty_package_marker`` takes.
        if tree is not None and _is_package_marker(tree):
            return _ROLE_PACKAGE_MARKER
        return _ROLE_APP
    if tree is not None and _has_main_guard(tree) and not _inside_package(path):
        return _ROLE_SCRIPT
    return _ROLE_APP


def _is_test_path(relative: str) -> bool:
    """Return ``True`` for a file that is test code by location or by name."""
    parts = relative.split("/")
    if any(part in _TEST_DIR_NAMES for part in parts[:-1]):
        return True
    name = parts[-1]
    if name in _TEST_FILE_NAMES or name.startswith(_TEST_FILE_PREFIX):
        return True
    return name.endswith(_TEST_FILE_SUFFIX)


def _is_package_marker(tree: ast.Module) -> bool:
    """Return ``True`` for an ``__init__.py`` that only marks a package.

    Wider than :func:`s0ma_dsl.project.is_empty_package_marker`, on
    purpose and in one direction only: that function decides what
    ``s0ma verify`` may auto-classify as ``PACKAGE_MARKER`` and so admits
    a docstring and nothing else. This is a *discovery hint* feeding the
    perimeter suggestion, where the re-export ``__init__.py`` — imports
    and an ``__all__``, no logic — is the common shape and is equally not
    application code. An ``__init__.py`` carrying anything else is
    ``"app"``, and the perimeter suggestion says so out loud rather than
    declaring it a marker.
    """
    for index, statement in enumerate(tree.body):
        if index == 0 and _is_docstring(statement):
            continue
        if isinstance(statement, (ast.Import, ast.ImportFrom)):
            continue
        if _is_dunder_all(statement):
            continue
        return False
    return True


def _has_main_guard(tree: ast.Module) -> bool:
    """Return ``True`` when a top-level ``if __name__ == "__main__":`` exists."""
    return any(
        isinstance(statement, ast.If) and _is_main_guard_test(statement.test)
        for statement in tree.body
    )


def _is_main_guard_test(test: ast.expr) -> bool:
    """Return ``True`` for ``__name__ == "__main__"`` written either way round."""
    if not isinstance(test, ast.Compare) or len(test.ops) != 1:
        return False
    if not isinstance(test.ops[0], ast.Eq):
        return False
    left, right = test.left, test.comparators[0]
    return _is_main_pair(left, right) or _is_main_pair(right, left)


def _is_main_pair(name_side: ast.expr, value_side: ast.expr) -> bool:
    """Return ``True`` when *name_side* is ``__name__`` and *value_side* ``"__main__"``."""
    return (
        isinstance(name_side, ast.Name)
        and name_side.id == "__name__"
        and isinstance(value_side, ast.Constant)
        and value_side.value == "__main__"
    )


def _inside_package(path: Path) -> bool:
    """Return ``True`` when *path* sits in a directory carrying ``__init__.py``."""
    return (path.parent / "__init__.py").is_file()


# ---------------------------------------------------------------------------
# Small shared readers
# ---------------------------------------------------------------------------


def _is_docstring(statement: ast.stmt) -> bool:
    """Return ``True`` for a bare string-literal statement."""
    return (
        isinstance(statement, ast.Expr)
        and isinstance(statement.value, ast.Constant)
        and isinstance(statement.value.value, str)
    )


def _is_dunder_all(statement: ast.stmt) -> bool:
    """Return ``True`` for an assignment whose target is ``__all__``."""
    if isinstance(statement, ast.Assign):
        return any(
            isinstance(target, ast.Name) and target.id == "__all__"
            for target in statement.targets
        )
    if isinstance(statement, ast.AnnAssign):
        return isinstance(statement.target, ast.Name) and statement.target.id == "__all__"
    return False


def _parse(text: str | None) -> ast.Module | None:
    """Return the parsed module, or ``None`` when it cannot be read or parsed."""
    if text is None:
        return None
    try:
        return ast.parse(text)
    except (SyntaxError, ValueError):
        return None


def _read_text(path: Path) -> str | None:
    """Return *path*'s UTF-8 text, or ``None`` when it is unreadable.

    Strict decoding: a file that is not UTF-8 is not silently mangled
    into something that parses. The census reports it as a parse error
    instead, which is a fact a person can act on.
    """
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None


def _sorted_children(directory: Path) -> tuple[Path, ...]:
    """Return *directory*'s entries sorted, or empty when unreadable."""
    try:
        return tuple(sorted(directory.iterdir()))
    except OSError:
        return ()


def _safe_resolve(path: Path) -> Path | None:
    """Return the fully resolved *path*, or ``None`` when it cannot be resolved."""
    try:
        return path.resolve()
    except OSError:
        return None


def _relative_posix(path: Path, root: Path) -> str | None:
    """Return *path* relative to *root* as a POSIX string, or ``None``.

    Every path this package records is project-relative and
    forward-slashed, so one scan report reads the same on Windows as it
    does anywhere else. A path that is not under *root* returns ``None``
    and its file is dropped: discovery cannot name what it does not own.
    """
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        pass
    resolved_path, resolved_root = _safe_resolve(path), _safe_resolve(root)
    if resolved_path is None or resolved_root is None:
        return None
    try:
        return resolved_path.relative_to(resolved_root).as_posix()
    except ValueError:
        return None


def _normalise_root(value: str) -> str:
    """Return a caller-supplied source root as a project-relative POSIX string."""
    text = value.strip().replace("\\", "/").strip("/")
    if not text or text == ".":
        return "."
    return Path(text).as_posix()


def _dedupe(values: tuple[str, ...]) -> tuple[str, ...]:
    """Return *values* without repeats, first occurrence winning."""
    return tuple(dict.fromkeys(values))


def _pyproject_document(root: Path) -> dict[str, object]:
    """*root*'s parsed ``pyproject.toml``, or an empty document.

    Unreadable or malformed reads as "says nothing": every caller here is
    gathering evidence, and a scan reports rather than refusing.
    """
    pyproject = root / "pyproject.toml"
    if not pyproject.is_file():
        return {}
    try:
        with pyproject.open("rb") as handle:
            document = tomllib.load(handle)
    except (OSError, tomllib.TOMLDecodeError):
        return {}
    return document


def _project_declared_at(root: Path) -> S0maProject | None:
    """Return the s0ma project *root* itself declares, or ``None``.

    Deliberately *not* :meth:`S0maProject.discover` on its own:
    ``discover`` walks upward until it finds a ``[tool.s0ma]`` table, so
    scanning a plain-Python directory that happens to sit inside a s0ma
    repository would silently adopt the outer repository's source roots
    and build directory. The table has to be on *this* tree's own
    ``pyproject.toml`` to count; anything malformed reads as "no project"
    because a scan reports, it never refuses.
    """
    from s0ma_dsl.errors import S0maProjectNotFound
    from s0ma_dsl.project import S0maProject

    pyproject = root / "pyproject.toml"
    if not pyproject.is_file():
        return None
    try:
        with pyproject.open("rb") as handle:
            document = tomllib.load(handle)
    except (OSError, tomllib.TOMLDecodeError):
        return None
    if not isinstance(document.get("tool", {}).get("s0ma"), dict):
        return None
    try:
        return S0maProject.discover(root)
    except (S0maProjectNotFound, OSError, ValueError):
        return None
