"""The scan report — rung 0's deliverable, assembled and rendered.

``s0ma adopt scan`` is the first thing anybody runs at the bottom of the
retrofit ladder, and the only thing it produces is this report. It
answers three questions in one pass: *what is in this tree*, *in what
order would I convert it*, and *what should I look at before I start*.

Two public functions
--------------------

:func:`build_scan_report` runs the whole rung-0 pipeline — discovery,
census, import classification, graph, proposals, perimeter, effort,
warnings — and returns one frozen
:class:`~s0ma_dsl.adopt.model.ScanReport`. Everything downstream reads
that record; nothing re-walks the tree.

:func:`render_scan_text` turns the reading into the one screen a person
reads, and :func:`render_detail_text` turns one module of it into the
fuller account ``--detail`` prints. Both are pure functions over the
record, so the text and the JSON can never describe different scans.

What the scan is *about*
------------------------

A scan is about the project's own code and not about every Python file
under the directory it was pointed at. Which files those are is the
:class:`ScanScope`: the source roots, who chose them, and a tally of
everything left outside them. :func:`read_scan` returns the scope beside
the report as a :class:`ScanReading` — the same shape ``adopt status``
uses (``LadderReading`` beside ``LadderStatus``), because the frozen
model in ``adopt/model.py`` is sized for the report and adding a field to
it is not this milestone's to do.

Scoping is what makes the numbers agree. The headline counts, the
conversion order, the effort bands and the perimeter are all about the
files inside the roots — which is the same set ``s0ma verify`` and
``s0ma score`` classify — so the census in the JSON is that set too, and
what is outside is summarised by directory rather than detailed file by
file.

The three promises, again
-------------------------

* **Nothing is imported or executed** (retrofit rule R-1): every fact
  comes from :mod:`ast` over file text, by way of ``adopt/census.py``.
* **Nothing is written** (retrofit rule R-2): no cache, no report file,
  no ``__pycache__`` beside the sources. The report goes to stdout and
  the caller decides whether to keep it.
* **A scan reports; it never refuses.** A file that will not parse, a
  cycle, a name the framework already owns — each is a
  :class:`~s0ma_dsl.adopt.model.ScanWarning` in the report, and the
  command still exits 0. The only refusals are about the *request*: a
  path that does not exist, or a tree with no Python in it.

What the warnings say
---------------------

Five codes, four of them frozen by the plan's §5.4 and one ruled at the
B4 gate:

* ``ADOPT_SCAN_PARSE_ERROR`` — a file could not be read as Python.
* ``ADOPT_SCAN_CYCLE`` — modules that import each other at load time.
* ``ADOPT_SCAN_NAME_COLLISION`` — a definition whose name s0ma's own
  components already occupy (from ``adopt/proposals.py``).
* ``ADOPT_SCAN_DYNAMIC_EXPORTS`` — a module builds ``__all__`` at run
  time, so a static reader cannot say what it exports.
* ``ADOPT_SCAN_DEFERRED_CYCLE`` — **the B4 ruling.** Two modules that
  refer to each other, where one side's import sits inside a function.
  There is *no* load-time cycle, so the report says zero cycles and
  means it; but the pair is one edit away from one, and the import has
  to stay inside the function when the module is converted. Saying
  nothing would leave somebody to rediscover that by breaking it.

These are report-only strings and not minted diagnostics: they name
nothing the language refuses, so the negative-inventory bijection does
not apply to them (plan §5.4).
"""

from __future__ import annotations

import ast
import textwrap
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from s0ma_dsl.adopt.census import census_file
from s0ma_dsl.adopt.discovery import (
    ROOTS_GIVEN,
    ROOTS_INFERRED,
    ROOTS_PROPOSED,
    DiscoveryScope,
    _project_declared_at,
    discover_sources,
    discover_within,
    infer_own_source_roots,
    resolve_source_roots,
    source_root_origin,
)
from s0ma_dsl.adopt.graph import build_graph, classify_imports
from s0ma_dsl.adopt.model import SCAN_SCHEMA, ScanReport, ScanWarning
from s0ma_dsl.adopt.proposals import (
    collision_warnings,
    estimate_effort,
    propose,
    suggest_perimeter,
)

if TYPE_CHECKING:
    from collections.abc import Sequence
    from pathlib import Path

    from s0ma_dsl.adopt.model import (
        EntityFact,
        GraphFacts,
        ModuleCensus,
        Proposal,
        SourceFile,
    )
    from s0ma_dsl.project import S0maProject

__all__ = [
    "MAX_TEXT_LINES",
    "ORDER_PREVIEW",
    "WARNING_CYCLE",
    "WARNING_DEFERRED_CYCLE",
    "WARNING_DYNAMIC_EXPORTS",
    "WARNING_PARSE_ERROR",
    "ScanReading",
    "ScanScope",
    "build_scan_report",
    "read_scan",
    "render_detail_text",
    "render_scan_text",
]


# ---------------------------------------------------------------------------
# Warning codes
#
# ``ADOPT_SCAN_NAME_COLLISION`` is not re-spelled here: it is minted by
# ``adopt/proposals.py`` as ``WARNING_NAME_COLLISION`` and the warnings
# that carry it are built there too, so this module never types the
# string at all.
# ---------------------------------------------------------------------------

WARNING_PARSE_ERROR = "ADOPT_SCAN_PARSE_ERROR"
"""A file in the tree could not be read as Python for this interpreter."""

WARNING_CYCLE = "ADOPT_SCAN_CYCLE"
"""Two or more modules import each other when they load."""

WARNING_DYNAMIC_EXPORTS = "ADOPT_SCAN_DYNAMIC_EXPORTS"
"""A module assembles ``__all__`` at run time, so nothing static can read it."""

WARNING_DEFERRED_CYCLE = "ADOPT_SCAN_DEFERRED_CYCLE"
"""A pair that is not a cycle only because one import sits inside a function."""


#: How many modules of the conversion order the one-screen report lists
#: before it says how many more there are. Ten is the guide's promise
#: ("the first ten modules of a leaf-first conversion order").
ORDER_PREVIEW = 10

#: The one-screen budget the text report is held to, in lines. The plan
#: fixes it at forty for a fifty-module project; :func:`render_scan_text`
#: enforces it by trimming the warning list rather than by hoping the
#: sections came out short, because the warning list is the only section
#: whose length the scanned tree controls.
MAX_TEXT_LINES = 40

#: Columns the wrapped prose in the text report is folded at. Narrow
#: enough for a split terminal, wide enough that a plain sentence is one
#: or two lines rather than five.
_WRAP = 88

_ROLE_TEST = "test"
_ROLE_APP = "app"
_ROLE_PACKAGE_MARKER = "package_marker"

_BAND_WIDTH = 6
_MODULE_WIDTH = 34
_LAYER_WIDTH = 14


# ---------------------------------------------------------------------------
# T1 — assembly
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ScanScope:
    """Which directories the scan read as this project's code, and what it did not."""

    source_roots: tuple[str, ...]
    """The roots the scan read application code from."""

    origin: str
    """Who chose them: ``given``, ``declared``, ``proposed`` or ``inferred``."""

    reason: str | None
    """Why these roots, when the scan worked them out; ``None`` otherwise."""

    outside_files: int
    """How many Python files sit outside the roots and are not in this scan."""

    outside_tests: int
    """How many of those are test code, by name or by place."""

    directories: tuple[tuple[str, int], ...]
    """``(top-level directory, file count)`` for what was left out, biggest first."""

    test_directories: tuple[str, ...]
    """Top-level directories holding test files, inside the roots or outside.

    What ``s0ma adopt init`` writes into ``test_roots``, so the tree's own
    tests are named rather than left counting as unconverted for ever.
    """

    def sentence(self) -> str | None:
        """The one line saying what was left out, or ``None`` when nothing was.

        A scope that left out nothing but test files says nothing: the
        headline already counts those ("5 test files seen and left out of
        the numbers above"), and a second line about the same five would
        cost a screen that has a cycle warning to print.
        """
        if self.outside_files <= self.outside_tests:
            return None
        where = ", ".join(
            f"{'the project directory' if name == '.' else name + '/'} {count}"
            for name, count in self.directories
        )
        tests = f", {self.outside_tests} of them tests" if self.outside_tests else ""
        return (
            f"{self.outside_files} other Python "
            f"{'file is' if self.outside_files == 1 else 'files are'} outside them "
            f"and not in this scan{tests}: {where}."
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_roots": list(self.source_roots),
            "origin": self.origin,
            "reason": self.reason,
            "outside_files": self.outside_files,
            "outside_tests": self.outside_tests,
            "directories_outside": [
                {"directory": name, "files": count} for name, count in self.directories
            ],
            "test_directories": list(self.test_directories),
        }


@dataclass(frozen=True, slots=True)
class ScanReading:
    """Everything ``s0ma adopt scan`` found: the report, and what it is about."""

    report: ScanReport
    """The frozen rung-0 record (plan §5.2)."""

    scope: ScanScope
    """Which files the report covers, and what it left out."""

    def to_dict(self) -> dict[str, Any]:
        """The ``s0ma-adopt-scan@1`` document, with ``scope`` alongside.

        An added field rides the ``@1`` schema (``model.SCAN_SCHEMA``'s
        own versioning rule): nothing that read the old document stops
        working, and an agent that wants to know what was left out no
        longer has to infer it from a census it was not given.
        """
        return {**self.report.to_dict(), "scope": self.scope.to_dict()}


def read_scan(
    root: Path, source_roots: Sequence[str] | None = None, *, scoped: bool = True
) -> ScanReading:
    """Read *root* and return everything rung 0 has to say about it.

    The whole pipeline in one call: decide which directories hold this
    project's code, discover the files in them, take a census of each,
    resolve where every import comes from, build the first-party graph,
    propose a layer for each module, suggest the perimeter, size the work,
    and collect the warnings.

    **Deciding the roots** takes the first answer that exists:

    1. *source_roots* as given (``--source-root``).
    2. ``[tool.s0ma].source_roots``, when the tree is already a project.
    3. A ``src/`` layout, when there is one.
    4. The top-level packages the tree's own packaging names or its own
       imports join up (:func:`~s0ma_dsl.adopt.discovery.infer_own_source_roots`).
    5. The project directory itself — everything.

    Everything outside the chosen roots is counted and named by directory
    in the :class:`ScanScope`, never read. When *root* already declares a
    ``[tool.s0ma]`` project, ``classification`` carries the same per-class
    counts ``s0ma verify`` reports over the same files, so the headline
    and the classification are two readings of one set.

    *scoped* is what rung 0 wants and is the default. ``scoped=False``
    censuses the whole tree instead, roots or no roots, for the two
    commands that resolve *one named file* — ``adopt draft`` and ``adopt
    baseline`` — which have to be able to see a file in order to say a
    useful sentence about why they will not convert it, and which have
    their own rule about where a file outside the roots may be drafted to.

    Reads only. Nothing is imported, executed or written (R-1, R-2).
    """
    roots = resolve_source_roots(root, source_roots)
    origin = source_root_origin(root, source_roots)
    reason: str | None = None
    if scoped and origin == ROOTS_INFERRED and roots == (".",):
        own = infer_own_source_roots(root)
        if own is not None:
            roots, origin, reason = own.source_roots, ROOTS_PROPOSED, own.reason

    found = (
        discover_within(root, roots)
        if scoped
        else DiscoveryScope(
            source_roots=roots,
            sources=discover_sources(root, roots),
            outside=(),
            outside_tests=(),
        )
    )
    sources = found.sources
    censuses = classify_imports(
        tuple(census_file(root, source) for source in sources)
    )
    graph = build_graph(censuses)
    proposals = propose(censuses, graph)
    perimeter = suggest_perimeter(
        # Unscoped, the roots are only a naming convention and the files
        # decide the perimeter, exactly as they did before scoping existed.
        root, sources, censuses, source_roots=roots if scoped else None
    )
    effort = estimate_effort(censuses, graph)
    project = _project_declared_at(root)
    scope = ScanScope(
        source_roots=roots,
        origin=origin,
        reason=reason,
        outside_files=len(found.outside),
        outside_tests=len(found.outside_tests),
        directories=found.directories_outside,
        test_directories=_test_directories(sources, found.outside_tests),
    )

    report = ScanReport(
        schema=SCAN_SCHEMA,
        project=_project_facts(project),
        summary=_summary(censuses, graph, scope),
        modules=censuses,
        graph=graph,
        proposals=proposals,
        perimeter=perimeter,
        effort=effort,
        classification=_classification(project),
        warnings=_warnings(root, censuses, graph),
    )
    return ScanReading(report=report, scope=scope)


def _test_directories(
    sources: Sequence[SourceFile], outside_tests: Sequence[str]
) -> tuple[str, ...]:
    """Top-level directories holding test files, from both sides of the scope.

    Top-level because that is the unit ``test_roots`` is written in. A test
    file sitting directly at the project root contributes nothing: its
    directory is the project, which is never a test root.
    """
    paths = [source.path for source in sources if source.role == _ROLE_TEST]
    paths.extend(outside_tests)
    return tuple(sorted({path.split("/", 1)[0] for path in paths if "/" in path}))


def build_scan_report(
    root: Path, source_roots: Sequence[str] | None = None, *, scoped: bool = True
) -> ScanReport:
    """The scan report alone — the frozen entry point of plan §5.1.

    :func:`read_scan` reads the tree once and returns this report together
    with the scope that says which files it covers. Call that instead when
    the scope is wanted, rather than reading the tree twice; *scoped* means
    what it means there.
    """
    return read_scan(root, source_roots, scoped=scoped).report


def _project_facts(project: S0maProject | None) -> dict[str, object]:
    """What the tree already declares about itself, or the three nulls.

    ``name`` is the project's own name from ``[project].name``, which a
    tree usually has whether or not it has ever heard of s0ma; it is
    reported only when a ``[tool.s0ma]`` table makes the rest of this
    record meaningful, so the three fields are answered together or not
    at all.
    """
    if project is None:
        return {"has_s0ma_config": False, "mode": None, "name": None}
    return {
        "has_s0ma_config": True,
        "mode": project.mode,
        "name": project.project_name,
    }


def _summary(
    censuses: Sequence[ModuleCensus], graph: GraphFacts, scope: ScanScope
) -> dict[str, int]:
    """The headline counts, over the modules a conversion is about.

    Two sets are counted and then set aside, and the report says how big
    each was rather than leaving a reader to wonder:

    * **Test files** (``test_files``) — a retrofit does not convert a test
      suite, and folding its lines into the total would make every tree
      look twice the size of the work in front of it. The count covers
      test files inside the source roots and outside them alike.
    * **Everything outside the source roots** (``outside_files``) — not
      this project's code at all, so not read and not counted anywhere
      else. :meth:`ScanScope.sentence` names the directories.
    """
    modules = [
        census for census in censuses if census.source.role != _ROLE_TEST
    ]
    return {
        "outside_files": scope.outside_files,
        "modules": len(modules),
        "packages": sum(
            1
            for census in modules
            if census.source.path.rsplit("/", 1)[-1] == "__init__.py"
        ),
        "lines": sum(census.lines for census in modules),
        "sloc": sum(census.sloc for census in modules),
        "public_entities": sum(
            1
            for census in modules
            for entity in census.entities
            if entity.public
        ),
        "registered_entities": sum(
            1
            for census in modules
            for entity in census.entities
            if entity.registered
        ),
        "cycles": len(graph.cycles),
        "parse_errors": sum(
            1 for census in censuses if census.parse_error is not None
        ),
        "test_files": (
            sum(1 for census in censuses if census.source.role == _ROLE_TEST)
            + scope.outside_tests
        ),
    }


# ---------------------------------------------------------------------------
# T2 — reconciliation with what `s0ma verify` would say
# ---------------------------------------------------------------------------


def _classification(project: S0maProject | None) -> dict[str, int] | None:
    """Verify's per-class counts, or ``None`` when there is no project.

    The classifier is imported, not shelled out to, and it is the one
    ``s0ma score`` already reuses from ``s0ma verify``
    (``cli/score.py``'s ``_verify_surface``, whose docstring says in as
    many words that it applies the verify classifier's exact rules). One
    implementation, so the ``UNKNOWN`` number a scan prints is the
    ``UNKNOWN`` number a verify prints and not a second opinion about the
    same tree.

    ``COMPONENTIZED`` is the score's own word for a file carrying the
    transpiler's hash headers. It is deliberately not reported as verify's
    ``OK``: verify re-hashes those files and may call one ``EDITED`` or
    ``STALE``, and this reading does not re-derive drift, so claiming
    ``OK`` would claim a check nobody ran.
    """
    if project is None:
        return None

    from s0ma_dsl.cli.score import _verify_surface

    surface = _verify_surface(project)
    if surface is None:
        return {
            "ADOPTED": 0,
            "BOOTSTRAP": 0,
            "COMPONENTIZED": 0,
            "PACKAGE_MARKER": 0,
            "UNKNOWN": 0,
        }
    return {
        "ADOPTED": int(surface["adopted"]),
        "BOOTSTRAP": len(surface["bootstrap_paths"]),
        "COMPONENTIZED": int(surface["componentized"]),
        "PACKAGE_MARKER": len(surface["marker_paths"]),
        "UNKNOWN": int(surface["unknown"]),
    }


# ---------------------------------------------------------------------------
# Warnings
# ---------------------------------------------------------------------------


def _warnings(
    root: Path, censuses: Sequence[ModuleCensus], graph: GraphFacts
) -> tuple[ScanWarning, ...]:
    """Everything worth saying that is not a refusal, in a stable order."""
    found: list[ScanWarning] = [
        *_parse_error_warnings(censuses),
        *_cycle_warnings(graph),
        *_deferred_cycle_warnings(censuses, graph),
        *_dynamic_export_warnings(root, censuses),
        *collision_warnings(censuses),
    ]
    return tuple(
        sorted(found, key=lambda item: (item.code, item.module or "", item.message))
    )


def _parse_error_warnings(
    censuses: Sequence[ModuleCensus],
) -> list[ScanWarning]:
    """One warning per file that could not be read as Python."""
    return [
        ScanWarning(
            code=WARNING_PARSE_ERROR,
            module=census.source.module,
            message=(
                f"`{census.source.path}` could not be read as Python, so nothing "
                f"in it was counted: {census.parse_error} Everything else in the "
                f"scan is unaffected."
            ),
        )
        for census in sorted(censuses, key=lambda item: item.source.path)
        if census.parse_error is not None
    ]


def _cycle_warnings(graph: GraphFacts) -> list[ScanWarning]:
    """One warning per load-time import cycle."""
    return [
        ScanWarning(
            code=WARNING_CYCLE,
            module=cycle[0],
            message=(
                f"{_join_names(cycle)} import each other when they load, so none "
                f"of them can be converted before the others. Break the circle "
                f"first — usually by moving the shared thing into a module of its "
                f"own, or by moving one of the imports inside the function that "
                f"uses it — or convert the whole group in one go."
            ),
        )
        for cycle in graph.cycles
    ]


def _deferred_cycle_warnings(
    censuses: Sequence[ModuleCensus], graph: GraphFacts
) -> list[ScanWarning]:
    """The B4 ruling: a pair that avoids a cycle by one deferred import.

    ``A`` imports ``B`` when it loads and ``B`` imports ``A`` inside a
    function. There is no load-time cycle and the report says so — but
    move that import up to the top of the file, or let a conversion write
    it into ``requires:`` instead of ``deferred_requires:``, and there is.

    Only *function-scoped* imports qualify. An ``if TYPE_CHECKING:``
    import is deferred too, and it also lands in
    :attr:`~s0ma_dsl.adopt.model.GraphFacts.deferred_edges`, but it never
    runs at all: it cannot become a cycle by being left alone, and the
    harvester already refuses to promote a first-party one. Warning about
    it would be warning about nothing.

    One warning per pair, keyed on the module holding the deferred import
    so the same pair cannot be reported twice.
    """
    load_time = set(graph.edges)
    function_scoped = _function_scoped_targets(censuses)

    found: list[ScanWarning] = []
    for importer, target in graph.deferred_edges:
        if (importer, target) in load_time:
            # It is imported at the top of the file as well, so the
            # function-scoped copy changes nothing about the load order.
            continue
        if (target, importer) not in load_time:
            continue
        if target not in function_scoped.get(importer, frozenset()):
            continue
        found.append(
            ScanWarning(
                code=WARNING_DEFERRED_CYCLE,
                module=importer,
                message=(
                    f"`{importer}` and `{target}` refer to each other, and the "
                    f"only reason that is not a circle is that `{importer}` does "
                    f"its import inside a function instead of at the top of the "
                    f"file. It has to stay that way: when you convert "
                    f"`{importer}`, the import belongs under `deferred_requires:` "
                    f"and not under `requires:`. Moving it up — or letting a "
                    f"draft write it as an ordinary requirement — makes a circle "
                    f"the build will refuse."
                ),
            )
        )
    return found


def _function_scoped_targets(
    censuses: Sequence[ModuleCensus],
) -> dict[str, frozenset[str]]:
    """Per module, the first-party modules it imports inside a function.

    Read straight off the census rather than off the graph, because the
    graph folds function-scoped and type-checking imports into one tuple
    and the ruling above is about the first kind only.
    """
    modules = frozenset(census.source.module for census in censuses)
    scoped: dict[str, set[str]] = {}
    for census in censuses:
        for record in census.imports:
            if not record.deferred:
                continue
            for candidate in _import_candidates(record.module, record.names):
                if candidate in modules:
                    scoped.setdefault(census.source.module, set()).add(candidate)
    return {name: frozenset(targets) for name, targets in scoped.items()}


def _import_candidates(module: str, names: Sequence[str]) -> tuple[str, ...]:
    """Every dotted name one import statement could be reaching.

    ``from a.b import c`` reaches ``a.b.c`` if that is a module and
    ``a.b`` either way; ``import a.b.c`` reaches ``a.b.c``, ``a.b`` and
    ``a``. The same longest-prefix question ``adopt/graph.py`` asks, asked
    again here over one statement because the graph's answer has already
    been collapsed into edges by the time this runs.
    """
    if not module or module.startswith("."):
        return ()
    parts = module.split(".")
    candidates = [
        ".".join(parts[: index + 1]) for index in reversed(range(len(parts)))
    ]
    candidates.extend(f"{module}.{name}" for name in names)
    return tuple(candidates)


def _dynamic_export_warnings(
    root: Path, censuses: Sequence[ModuleCensus]
) -> list[ScanWarning]:
    """One warning per module that builds ``__all__`` at run time.

    A census carries ``dunder_all=None`` for two different modules: one
    that declares no ``__all__`` at all, and one that builds it out of a
    loop or a concatenation. Those are the same record and a very
    different fact, so the distinction is drawn here, once, over the few
    files that could possibly be the second kind: a module is only looked
    at again when its text mentions ``__all__`` and its census came back
    with none. On the ordinary tree that is no files at all.

    Reads; never writes, never imports the module (R-1, R-2).
    """
    found: list[ScanWarning] = []
    for census in sorted(censuses, key=lambda item: item.source.path):
        if census.parse_error is not None or census.dunder_all is not None:
            continue
        if not _assigns_dunder_all(root / census.source.path):
            continue
        found.append(
            ScanWarning(
                code=WARNING_DYNAMIC_EXPORTS,
                module=census.source.module,
                message=(
                    f"`{census.source.path}` builds its list of exports while it "
                    f"runs instead of writing it out, so reading the file cannot "
                    f"say what this module offers the rest of the program. The "
                    f"scan has counted every name without a leading underscore "
                    f"instead. Write the list out as plain text before converting "
                    f"this one, or check the converted module's exports by hand."
                ),
            )
        )
    return found


def _assigns_dunder_all(path: Path) -> bool:
    """Does this file assign ``__all__`` at the top level, in any form?"""
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return False
    try:
        tree = ast.parse(text)
    except (SyntaxError, ValueError):
        return False
    for statement in tree.body:
        targets: list[ast.expr] = []
        if isinstance(statement, ast.Assign):
            targets = list(statement.targets)
        elif isinstance(statement, ast.AugAssign | ast.AnnAssign):
            targets = [statement.target]
        for target in targets:
            if isinstance(target, ast.Name) and target.id == "__all__":
                return True
    return False


# ---------------------------------------------------------------------------
# T3 — the one screen
# ---------------------------------------------------------------------------


def render_scan_text(reading: ScanReading) -> str:
    """The reading as the one screen a person reads, ending in what to run.

    Five parts in the order somebody needs them: what was found, the
    perimeter the scan would declare, the conversion order, what is worth
    knowing before starting, and the next command. Held to
    :data:`MAX_TEXT_LINES` lines — the warning list is the one section a
    scanned tree controls the length of, so that is the section that gives
    way, and it says how many it left out.
    """
    report = reading.report
    head = [
        *_found_lines(reading),
        "",
        *_perimeter_lines(reading),
        "",
        *_order_lines(report),
        "",
        *_cycle_lines(report),
    ]
    tail = ["", *_next_lines(report)]
    budget = MAX_TEXT_LINES - len(head) - len(tail)
    body = _warning_lines(report, budget=budget)
    return "\n".join([*head, *body, *tail]) + "\n"


def _found_lines(reading: ScanReading) -> list[str]:
    """What is in the tree, in three sentences.

    For a tree that is already a s0ma project the classification has the
    last word: it is the reading ``s0ma verify`` and ``s0ma score`` give,
    it covers the same files the counts above it cover, and a headline
    that disagreed with it would send somebody off to reconcile two true
    numbers about one tree.
    """
    report = reading.report
    summary = report.summary
    name = report.project.get("name")
    where = f" in {name}" if isinstance(name, str) and name else ""
    packages = summary["packages"]
    package_note = (
        " across " + _plural(packages, "package", "packages")
        if packages
        else " (no packages)"
    )

    lines = [
        f"Scanned{where}: "
        f"{_plural(summary['modules'], 'module', 'modules')}{package_note}, "
        f"{summary['lines']:,} lines, {summary['sloc']:,} of them code.",
        f"{_plural(summary['public_entities'], 'public thing', 'public things')} "
        f"to convert; {_registered_phrase(summary['registered_entities'])}.",
    ]
    aside: list[str] = []
    if summary["test_files"]:
        aside.append(
            f"{_plural(summary['test_files'], 'test file', 'test files')} seen "
            f"and left out of the numbers above"
        )
    if summary["parse_errors"]:
        aside.append(
            f"{_plural(summary['parse_errors'], 'file', 'files')} could not be "
            f"read as Python"
        )
    if aside:
        lines.append(_sentence_case(_join(aside)) + ".")
    if report.classification is not None:
        lines.append(_classification_sentence(report))
    return _wrap_all(lines)


def _classification_sentence(report: ScanReport) -> str:
    """The same reading `s0ma verify` gives, as one sentence.

    Every class with something in it is named, so the sentence adds up to
    the module count above it rather than quoting one number out of five.
    """
    classification = report.classification or {}
    mode = report.project.get("mode")
    in_mode = f", in {mode} mode" if isinstance(mode, str) and mode else ""
    total = sum(classification.values())
    said = {
        "UNKNOWN": ("is not converted yet", "are not converted yet"),
        "COMPONENTIZED": ("is built from a s0ma source", "are built from s0ma sources"),
        "ADOPTED": ("is registered in place", "are registered in place"),
        "PACKAGE_MARKER": ("only marks a package", "only mark a package"),
        "BOOTSTRAP": ("starts the application", "start the application"),
    }
    parts = [
        f"{count} {said[name][0] if count == 1 else said[name][1]}"
        for name, count in sorted(classification.items())
        if count and name in said
    ]
    return (
        f"This tree is already a s0ma project{in_mode}: of the "
        f"{_plural(total, 'file', 'files')} inside the perimeter, "
        f"{_join(parts) or 'none is classified'} — the same reading "
        f"`s0ma verify` and `s0ma score` give."
    )


def _registered_phrase(registered: int) -> str:
    """How many of them the runtime already knows about, in plain words."""
    if registered == 0:
        return "none of them are registered with s0ma yet"
    return (
        f"{registered} of them already carry a s0ma decorator and keep the "
        f"meaning written on it"
    )


def _perimeter_lines(reading: ScanReading) -> list[str]:
    """The `[tool.s0ma]` settings rung 1 would write, and what they leave out."""
    perimeter = reading.report.perimeter
    scope = reading.scope
    lines = [
        "Perimeter it would declare (`s0ma adopt init` writes this):",
        f"  source roots    {_join_paths(perimeter.source_roots)}",
        f"  bootstrap files {_join_paths(perimeter.bootstrap_files)}",
        f"  package markers {_join_paths(perimeter.package_markers)}",
        f"  mode            {perimeter.mode}",
    ]
    if scope.reason:
        lines.extend(
            _wrap_one(
                f"  Those roots because {scope.reason}.",
                indent="  ",
            )
        )
    sentence = scope.sentence()
    if sentence is not None:
        # When the reader named the roots there is nothing to offer: they
        # already said what their code is. Otherwise the way to disagree
        # with the scan belongs in the same sentence as the exclusion.
        offer = (
            ""
            if scope.origin == ROOTS_GIVEN
            else " Name them with --source-root if they are this project's code."
        )
        lines.extend(_wrap_one(f"  {sentence}{offer}", indent="  "))
    if perimeter.notes:
        lines.append(
            f"  {_plural(len(perimeter.notes), 'note', 'notes')} about the "
            f"perimeter — `--format json` prints them in full."
        )
    return lines


def _order_lines(report: ScanReport) -> list[str]:
    """The first ten of the conversion order, with band and proposed layer."""
    rows = _order_rows(report)
    exempt = _exempt_modules(report)
    if not rows:
        return ["Nothing to convert: no application modules were found."]

    lines = [
        f"Convert in this order, leaves first "
        f"({_plural(len(rows), 'module', 'modules')}):",
        f"  {'module':<{_MODULE_WIDTH}} {'size':<{_BAND_WIDTH}} proposed layer",
    ]
    for module, band, layer in rows[:ORDER_PREVIEW]:
        lines.append(
            f"  {module:<{_MODULE_WIDTH}} {band:<{_BAND_WIDTH}} {layer}"
        )
    remaining = len(rows) - ORDER_PREVIEW
    if remaining > 0:
        lines.append(
            f"  ... and {remaining} more — `--format json` lists every one."
        )
    if exempt:
        lines.extend(
            _wrap_one(
                f"  Not in that list: {_join_paths(sorted(exempt.values()))} — "
                f"declared above under `bootstrap_files`, so "
                f"{'it stays' if len(exempt) == 1 else 'they stay'} plain "
                f"Python; a s0ma project names its entry points.",
                indent="  ",
            )
        )
    return lines


def _exempt_modules(report: ScanReport) -> dict[str, str]:
    """Dotted name to path for every module the perimeter keeps out of the work.

    A file declared under ``bootstrap_files`` is a deliberate plain-Python
    exception. Offering it for conversion on the same screen that exempts
    it is one screen saying two things, and the pilot met exactly that on
    a ``__main__.py``.
    """
    exempt = set(report.perimeter.bootstrap_files)
    return {
        census.source.module: census.source.path
        for census in report.modules
        if census.source.path in exempt
    }


def _order_rows(report: ScanReport) -> list[tuple[str, str, str]]:
    """``(module, effort band, proposed layer)`` in conversion order."""
    bands = dict(report.effort.per_module)
    roles = {
        census.source.module: census.source.role for census in report.modules
    }
    layers = {
        proposal.module: _layer_label(proposal, roles.get(proposal.module))
        for proposal in report.proposals
    }
    exempt = _exempt_modules(report)
    return [
        (module, bands.get(module, "?"), layers.get(module, "yours to choose"))
        for module in report.graph.order
        if module not in exempt
    ]


def _layer_label(proposal: Proposal, role: str | None) -> str:
    """One column's worth of what the scan thinks the layer is.

    A package marker gets the truth about itself instead of a layer: rung
    1 declares it under ``package_markers`` and nobody converts it, so
    offering a layer for it would invite work that does not exist.
    """
    if role == _ROLE_PACKAGE_MARKER:
        return "package marker — nothing to convert"
    if proposal.layer is None:
        return "yours to choose"
    return f"{proposal.layer} ({proposal.confidence} confidence)"


def _cycle_lines(report: ScanReport) -> list[str]:
    """The cycle question, answered whether or not the answer is "none".

    Rung 0's single most consequential finding is whether the conversion
    order is a line or a knot, and "there are no cycles" is an answer
    somebody came for. Leaving it to the warning list would mean silence
    on the good case, which reads as "not checked".
    """
    count = len(report.graph.cycles)
    if count == 0:
        return _wrap_all(
            [
                "Import cycles: none at load time. Every module can be converted "
                "after the ones it imports, which is what makes the order above a "
                "plan rather than a suggestion."
            ]
        )
    return _wrap_all(
        [
            f"Import cycles: {count}. The modules in one cycle import each other "
            f"when they load, so they have to be converted together or untangled "
            f"first — each one is named below."
        ]
    )


def _warning_lines(report: ScanReport, *, budget: int) -> list[str]:
    """What is worth knowing, folded to fit whatever room is left.

    The section never overruns: warnings are added while they fit, and
    the ones that do not are counted in a final line that always fits
    because room for it is kept back first.
    """
    if not report.warnings:
        return ["", "Nothing else worth flagging."]

    header = f"Worth knowing ({len(report.warnings)}):"
    # Room for the blank line, the header and the "... and N more" is kept
    # back before a single warning is laid out, so the trailer that counts
    # what was left out can never be what pushes the screen over.
    room = max(budget - 3, 0)
    lines: list[str] = []
    shown = 0
    for warning in report.warnings:
        folded = _wrap_one(
            f"  {warning.code}"
            + (f" · {warning.module}" if warning.module else "")
            + f" — {warning.message}",
            indent="    ",
        )
        if len(lines) + len(folded) > room:
            break
        lines.extend(folded)
        shown += 1

    rest = len(report.warnings) - shown
    trailer = (
        [f"  ... and {rest} more — `--format json` prints every one."]
        if rest
        else []
    )
    return ["", header, *lines, *trailer]


def _next_lines(report: ScanReport) -> list[str]:
    """The last thing on the screen: the one command to run now."""
    if not report.project.get("has_s0ma_config"):
        return _wrap_all(
            [
                "Next: `s0ma adopt init` — it writes the perimeter above into "
                "pyproject.toml and touches no application file."
            ]
        )
    first = _first_convertible(report)
    if first is None:
        return _wrap_all(
            [
                "Next: `s0ma adopt status` — this tree is already a s0ma project "
                "and there is no plain-Python module left to convert."
            ]
        )
    return _wrap_all(
        [
            f"Next: `s0ma adopt baseline {first}` — record what that module "
            f"promises before you change anything about it."
        ]
    )


def _first_convertible(report: ScanReport) -> str | None:
    """The first real module of the conversion order.

    Package markers are skipped because nobody converts one, and so is
    anything the perimeter exempts: pointing at a file the same screen
    declares as bootstrap would be the tool arguing with itself.
    """
    roles = {
        census.source.module: census.source.role for census in report.modules
    }
    exempt = _exempt_modules(report)
    for module in report.graph.order:
        if roles.get(module) == _ROLE_APP and module not in exempt:
            return module
    return None


# ---------------------------------------------------------------------------
# T3 — `--detail MODULE`
# ---------------------------------------------------------------------------


def render_detail_text(report: ScanReport, module: str) -> str:
    """One module, in full: its census, its proposal, and both its edges.

    Raises :class:`KeyError` when *module* is not in the report; the
    command turns that into a refusal that names what to run instead.
    """
    census = _census_of(report, module)
    if census is None:
        raise KeyError(module)

    lines = [
        f"{module} — {census.source.path}",
        f"  {census.lines:,} lines, {census.sloc:,} of them code; "
        f"{_effects_phrase(census.top_level_effects)}.",
        f"  role: {census.source.role}; source root: {census.source.source_root}",
        f"  content hash: {census.content_hash}",
    ]
    if census.parse_error is not None:
        lines.append(f"  could not be read as Python: {census.parse_error}")
    lines.extend(["", *_detail_proposal(report, module)])
    lines.extend(["", *_detail_entities(census)])
    lines.extend(["", *_detail_imports(census)])
    lines.extend(["", *_detail_edges(report, module)])
    return "\n".join(lines) + "\n"


def _census_of(report: ScanReport, module: str) -> ModuleCensus | None:
    """The census for *module*, or ``None`` when the scan never saw it."""
    for census in report.modules:
        if census.source.module == module:
            return census
    return None


def _effects_phrase(effects: int) -> str:
    """How much of the module runs the moment it is imported."""
    if effects == 0:
        return "nothing runs when it is imported"
    return (
        f"{_plural(effects, 'statement runs', 'statements run')} the moment it "
        f"is imported, and each one has to be placed by hand"
    )


def _detail_proposal(report: ScanReport, module: str) -> list[str]:
    """The proposal for one module, with every reason spelled out."""
    proposal = next(
        (item for item in report.proposals if item.module == module), None
    )
    if proposal is None:
        return ["Proposed layer: not proposed (this file is a test)."]

    band = dict(report.effort.per_module).get(module, "not sized")
    layer = proposal.layer or "yours to choose"
    lines = [
        f"Proposed layer: {layer} ({proposal.confidence} confidence); "
        f"effort band: {band}."
    ]
    for reason in proposal.reasons:
        lines.extend(_wrap_one(f"  - {reason}", indent="    "))
    kinds = ", ".join(f"{kind} {count}" for kind, count in proposal.kind_mix)
    lines.append(f"  kinds it looks like: {kinds or 'nothing the scan recognised'}")
    return lines


def _detail_entities(census: ModuleCensus) -> list[str]:
    """Everything the module defines, in source order."""
    if not census.entities:
        return ["Defines nothing at the top level."]
    lines = [f"Defines ({len(census.entities)}):"]
    lines.extend(_entity_line(entity) for entity in census.entities)
    return lines


def _entity_line(entity: EntityFact) -> str:
    """One definition, on one line."""
    visibility = "public" if entity.public else "internal"
    registered = " · already registered with s0ma" if entity.registered else ""
    return (
        f"  line {entity.line:>4}  {entity.name:<28} {entity.category:<15} "
        f"{visibility:<8} looks like {entity.kind_hint}{registered}"
    )


def _detail_imports(census: ModuleCensus) -> list[str]:
    """Every import, with where it comes from and whether it runs at load."""
    if not census.imports:
        return ["Imports nothing."]
    lines = [f"Imports ({len(census.imports)}):"]
    for record in census.imports:
        when = (
            " (inside a function)"
            if record.deferred
            else " (for type checking only)"
            if record.type_checking
            else ""
        )
        names = f" — {', '.join(record.names)}" if record.names else ""
        lines.append(
            f"  line {record.line:>4}  {record.module:<32} "
            f"{record.origin}{when}{names}"
        )
    return lines


def _detail_edges(report: ScanReport, module: str) -> list[str]:
    """Who leans on this module, and what it leans on, inside the project."""
    imports = sorted(
        target for importer, target in report.graph.edges if importer == module
    )
    imported_by = sorted(
        importer for importer, target in report.graph.edges if target == module
    )
    deferred = sorted(
        target
        for importer, target in report.graph.deferred_edges
        if importer == module
    )
    return _wrap_all(
        [
            f"Imports from this project ({len(imports)}): {_join_names(imports)}",
            f"Imported by ({len(imported_by)}): {_join_names(imported_by)}",
            f"Imports later, inside a function or for type checking "
            f"({len(deferred)}): {_join_names(deferred)}",
        ]
    )


# ---------------------------------------------------------------------------
# Small shared wording helpers
# ---------------------------------------------------------------------------


def _plural(count: int, singular: str, plural: str) -> str:
    """``"1 module"`` / ``"11 modules"``, with a thousands separator."""
    return f"{count:,} {singular if count == 1 else plural}"


def _join(items: Sequence[str]) -> str:
    """``"a"`` / ``"a and b"`` / ``"a, b and c"``."""
    if not items:
        return ""
    if len(items) == 1:
        return items[0]
    return f"{', '.join(items[:-1])} and {items[-1]}"


def _join_names(names: Sequence[str]) -> str:
    """A list of dotted names in back-ticks, or ``"none"``."""
    return _join([f"`{name}`" for name in names]) or "none"


def _join_paths(paths: Sequence[str]) -> str:
    """A list of project-relative paths, or ``"none"``."""
    return ", ".join(paths) if paths else "none"


def _sentence_case(text: str) -> str:
    """Capitalise the first letter and leave every other one alone."""
    return text[:1].upper() + text[1:] if text else text


def _wrap_one(text: str, *, indent: str = "") -> list[str]:
    """One string folded to :data:`_WRAP` columns, continuations indented."""
    return textwrap.wrap(
        text,
        width=_WRAP,
        subsequent_indent=indent,
        break_long_words=False,
        break_on_hyphens=False,
    ) or [text]


def _wrap_all(lines: Sequence[str]) -> list[str]:
    """Several strings, each folded, in order."""
    return [folded for line in lines for folded in _wrap_one(line, indent="  ")]
