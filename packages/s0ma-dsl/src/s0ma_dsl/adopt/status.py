"""Where a project stands on the retrofit ladder, and the one thing to do next.

``s0ma adopt status`` is the command for coming back. A retrofit is walked
over days or weeks — scan, init, then per module baseline, draft, author,
check, build, verify parity, delete the original — and the person who opens
the repository on a Tuesday morning has usually lost the thread. This reads
the tree and answers four questions in one screen: where am I, what is done,
what is left, and what is the one command to run now.

**It writes nothing anywhere** (retrofit rule R-2) and it never imports or
executes the code it is reading (R-1). Everything below is a file read: the
``[tool.s0ma]`` table, the scan's own reading of the tree, the ``.s0ma``
sources, the committed baselines, the build manifest, and the modules the
build emitted (parsed, never imported).

Nothing here is a second opinion. The conversion set and the file classes
come from the classifier ``s0ma verify`` and ``s0ma score`` already share
(:func:`s0ma_dsl.cli.score._verify_surface`); the conversion order comes from
the scan (:func:`s0ma_dsl.adopt.report.build_scan_report`); the parity
verdicts come from :func:`s0ma_dsl.adopt.parity.compare_surfaces`. A number
this command prints is a number one of those would print.

The rungs
---------

The ladder has five rungs and this reports four of them. Rung 2 — registering
Python in place — is a documented way-station rather than a position, so a
project is never *at* it; the files it produces are counted as
``adopted in place`` wherever the project stands.

===== ===================================================================
Rung  Reported when
===== ===================================================================
0     There is no ``[tool.s0ma]`` table: nothing is set up yet.
1     The perimeter is set and nothing has been converted.
3     Something has been converted or drafted and plain Python remains.
4     Nothing in the conversion set is plain Python any more and no draft
      is unfinished: what is left is tightening the strictness mode.
===== ===================================================================

The next step
-------------

One command, chosen by this table, read top to bottom — the first row whose
condition holds wins. "In flight" means a module that has been started and is
not finished: everything from *a baseline has been taken* to *parity is clean
and the original is still there*. Where several modules are in flight the row
is chosen for the one **furthest along** — finish what is started before
starting another — and ties are broken by the scan's conversion order.

===== ========================================== ==============================
Row   When                                       Command
===== ========================================== ==============================
1     Rung 0 — no ``[tool.s0ma]`` table          ``s0ma adopt scan``
2     Nothing to convert was found at all        ``s0ma adopt scan``
3     In flight: parity clean, the ``.py`` is    ``s0ma adopt verify-parity M``
      still there
4     In flight: parity found differences        ``s0ma adopt verify-parity M``
5     In flight: built, nothing recorded of      ``s0ma adopt baseline M``
      what the Python promised
6     In flight: the draft is authored and not   ``s0ma build``
      built
7     In flight: the draft still has             ``s0ma check``
      placeholders or quarantined source
8     In flight: a baseline and no draft         ``s0ma adopt draft M``
9     Nothing in flight, plain Python left       ``s0ma adopt baseline FIRST``
10    Nothing left to convert, mode below        ``s0ma check --mode NEXT``
      ``release``
11    Nothing left to convert, mode ``release``  ``s0ma score --gate
                                                 --gate-mode release``
===== ========================================== ==============================

Row 3's command is a re-reading rather than a deletion: the deletion itself
is one line of shell that differs per platform, and the half that is easy to
forget is the other one — a package whose module moves into the build
directory needs its name aliased in the same commit or its siblings stop
importing it. ``s0ma adopt verify-parity`` prints those lines, computed for
this project (:func:`alias_plan`), together with the two other things a
conversion is not finished without: the runtime has to be declared and
installed, and the build directory has to ship. Rows 3 to 8 all name a
command that runs offline; none sends a reader to a document to find out
what to type.
"""

from __future__ import annotations

import textwrap
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import TYPE_CHECKING, Any

from s0ma_dsl.adopt.model import (
    DRAFT_INTENT_MARKER,
    DRAFT_UNPLACED_MARKER,
    LadderStatus,
)
from s0ma_dsl.discovery import iter_visible_files

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence
    from pathlib import Path

    from s0ma_dsl.adopt.model import ScanReport
    from s0ma_dsl.adopt.parity import BaselineEntry
    from s0ma_dsl.project import S0maProject

__all__ = [
    "ALIAS_PLACEMENT",
    "MAX_STATUS_LINES",
    "MODE_LADDER",
    "PARITY_BASELINE_NOT_BUILT",
    "PARITY_BUILT_WITHOUT_BASELINE",
    "PARITY_DIFFERENCES",
    "PARITY_SAME_SURFACE",
    "RUNG_LABELS",
    "RUNTIME_DISTRIBUTIONS",
    "STATE_ADOPTED_IN_PLACE",
    "STATE_AUTHORED",
    "STATE_BASELINE_TAKEN",
    "STATE_BUILT_WITHOUT_BASELINE",
    "STATE_CONVERTED",
    "STATE_DRAFTED",
    "STATE_PARITY_CLEAN",
    "STATE_PARITY_DIFFERS",
    "STATE_PLAIN_PYTHON",
    "STATUS_SCHEMA",
    "AliasPlan",
    "LadderReading",
    "ModuleState",
    "alias_plan",
    "before_you_delete",
    "ladder_status",
    "read_ladder",
    "render_status_text",
]

STATUS_SCHEMA = "s0ma-adopt-status@1"
"""Canonical schema string for ``s0ma adopt status --format json``.

Additive fields ride ``@1`` and ``@2`` is a breaking change, the rule the
whole ``s0ma-adopt-*`` family inherits. Like the scan report and unlike the
baseline record, this document is printed and never written to a file
(rule R-2), so the version travels with the document.
"""

MAX_STATUS_LINES = 15
"""How many lines the text form may take.

A status is read at a glance, between two other things, by somebody who has
not read the guide. Fifteen lines is a third of what ``adopt scan`` is
allowed and it is a budget rather than an average: the in-flight line is the
one section the project controls the length of, so that is the section that
gives way, and it says how many modules it left unnamed.
"""

RUNG_LABELS: Mapping[int, str] = {
    0: "nothing set up yet",
    1: "perimeter set, nothing converted yet",
    3: "converting",
    4: "ratcheting",
}
"""The plain-language name of each reported rung (rung 2 is a way-station)."""

MODE_LADDER: tuple[str, ...] = ("migration", "dev", "strict", "release")
"""The strictness modes in the order rung 4 climbs them.

The same ladder ``docs/guides/retrofit-existing-codebase.md`` teaches and the
same order :data:`s0ma_dsl.cli.score.MODE_FLOORS` prices. The last entry is
the top: at ``release`` there is no mode to move to, so the next step becomes
proving the floor rather than raising it.
"""

# ---------------------------------------------------------------------------
# The closed vocabularies
#
# Two of them, and they are deliberately separate. A *state* is where one
# module stands; a *parity verdict* is what the comparison said about it,
# which is a fact about a build and not a position on the ladder. A module
# can be `converted` with no verdict at all (nothing was recorded of what its
# Python promised), and a verdict can exist for a module that is finished.
# ---------------------------------------------------------------------------

STATE_PLAIN_PYTHON = "plain-python"
"""Not started: a ``.py`` in the conversion set with no ``.s0ma`` beside it."""

STATE_ADOPTED_IN_PLACE = "adopted-in-place"
"""Registered where it stands by ``s0ma adopt file`` — rung 2's way-station."""

STATE_BASELINE_TAKEN = "baseline-taken"
"""What its Python promises is recorded; the draft has not been written."""

STATE_DRAFTED = "drafted"
"""A draft exists and still carries placeholders or quarantined source."""

STATE_AUTHORED = "authored"
"""The draft is fully written and nothing has been built from it yet."""

STATE_BUILT_WITHOUT_BASELINE = "built-without-baseline"
"""Built, with nothing recorded to compare it against — and the ``.py`` is
still there, so the record can still be taken."""

STATE_PARITY_DIFFERS = "parity-differs"
"""Built and compared, and the surface is not what the Python promised."""

STATE_PARITY_CLEAN = "parity-clean"
"""Built, compared, unchanged — and the original ``.py`` is still there."""

STATE_CONVERTED = "converted"
"""Finished: the module is a ``.s0ma`` source and its Python file is gone."""

#: How far along each state is. The in-flight module with the highest rank
#: chooses the next step, so that a retrofit finishes what it started. The
#: two ends are not in flight: nothing has begun at ``plain-python`` and
#: nothing is left at ``converted``. ``adopted-in-place`` is not in flight
#: either — it is a way-station somebody chose, not an unfinished conversion.
_PROGRESS: Mapping[str, int] = {
    STATE_PLAIN_PYTHON: 0,
    STATE_ADOPTED_IN_PLACE: 0,
    STATE_BASELINE_TAKEN: 1,
    STATE_DRAFTED: 2,
    STATE_AUTHORED: 3,
    STATE_BUILT_WITHOUT_BASELINE: 4,
    STATE_PARITY_DIFFERS: 5,
    STATE_PARITY_CLEAN: 6,
    STATE_CONVERTED: 7,
}

#: The states a module is *in flight* at: started and not finished.
_IN_FLIGHT = frozenset({
    STATE_BASELINE_TAKEN,
    STATE_DRAFTED,
    STATE_AUTHORED,
    STATE_BUILT_WITHOUT_BASELINE,
    STATE_PARITY_DIFFERS,
    STATE_PARITY_CLEAN,
})

PARITY_SAME_SURFACE = "same-surface"
"""The built module offers what the baseline recorded."""

PARITY_DIFFERENCES = "differences"
"""The comparison found something; the count rides beside it."""

PARITY_BUILT_WITHOUT_BASELINE = "built-without-baseline"
"""Built, and there is no record to judge it against."""

PARITY_BASELINE_NOT_BUILT = "baseline-not-built"
"""Recorded, and nothing of that name has been built yet."""

#: The closing line of every status, whatever it says above it. One id
#: for "the guide", and it is the guide: the ``AGENTS.md`` block this
#: family writes names the same page, and a reader who met two different
#: ids could not tell which one was meant (G3c). The journey is the
#: machine-checked path, not the page a person reads.
_GUIDE_COMMAND = "s0ma docs show doc:guide/retrofit-existing-codebase"

#: The column the retrofit family folds its prose at, as `adopt scan` and
#: `adopt init` do, so one ladder reads as one thing.
_WRAP = 88

#: Roles `discover_sources` gives a file that a conversion is about.
#: Package markers and test files are not converted; a file the perimeter
#: exempts is dropped separately, by the classifier `s0ma verify` shares.
_CONVERTIBLE_ROLES = frozenset({"app", "script"})


@dataclass(frozen=True, slots=True)
class ModuleState:
    """Where one module of the conversion set stands.

    * ``module`` — the dotted name the scan and the baselines file use.
    * ``path`` — the file somebody would open for this module today,
      project-relative and forward-slashed: the ``.s0ma`` once one exists,
      the ``.py`` until then.
    * ``python_path`` — where its Python is, or ``None`` once it is gone.
    * ``state`` — one of the ``STATE_*`` vocabulary above.
    * ``placeholders`` — how many ``FIXME(adopt):`` fields the draft still
      carries; ``0`` when there is no draft or none are left.
    * ``quarantined`` — whether the draft still carries source the harvester
      could not place. Either one keeps a draft unfinished.
    * ``baseline`` — whether what its Python promised has been recorded.
    * ``parity`` — the verdict, one of the ``PARITY_*`` vocabulary, or
      ``None`` where nothing has been built at all.
    * ``differences`` — how many the comparison found; ``0`` unless the
      verdict is :data:`PARITY_DIFFERENCES`.
    """

    module: str
    path: str
    python_path: str | None
    state: str
    placeholders: int
    quarantined: bool
    baseline: bool
    parity: str | None
    differences: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "baseline": self.baseline,
            "differences": self.differences,
            "module": self.module,
            "parity": self.parity,
            "path": self.path,
            "placeholders": self.placeholders,
            "python_path": self.python_path,
            "quarantined": self.quarantined,
            "state": self.state,
        }


@dataclass(frozen=True, slots=True)
class LadderReading:
    """Everything one reading of the ladder says.

    :class:`~s0ma_dsl.adopt.model.LadderStatus` is the frozen summary — the
    rung, the counts, the mode and the one next command — and this carries
    it together with the two things a summary has no room for: the state of
    every module in the conversion set, and the next step written out as a
    sentence a person can act on.

    * ``status`` — the summary, exactly as the model froze it.
    * ``project`` — the project's own name, or ``None`` at rung 0 where
      there is no ``[tool.s0ma]`` table to read one from.
    * ``modules`` — the conversion set, in the scan's conversion order.
    * ``next_step`` — what to do next in plain words. The command that goes
      with it is ``status.next_command``.
    * ``in_flight`` — the modules that are started and unfinished, furthest
      along first. ``status.next_module`` is the first of them when there is
      one.
    * ``source_root`` — the project's first source root, project-relative.
      ``s0ma build`` no longer needs it named (G3b); it is still the one
      directory an agent most often wants to know about.
    * ``alias`` — the lines that point the converted module's old name at
      the built one, when that is the step this project is standing on,
      else ``None``. Computed from this project's own layout.
    """

    status: LadderStatus
    project: str | None
    modules: tuple[ModuleState, ...]
    next_step: str
    in_flight: tuple[str, ...]
    source_root: str | None
    alias: AliasPlan | None = None

    def to_dict(self) -> dict[str, Any]:
        """The reading as the ``s0ma-adopt-status@1`` document.

        Deterministic by construction: the module list is in the scan's
        order, the counts are sorted by name, and nothing here reads a
        clock, an environment variable or an absolute path.

        ``before_you_delete`` is additive under ``@1``: it is present
        only where a module is converted, compared clean and still has
        its Python file, and it carries the same three facts the text
        form teaches — bind the old name, declare the runtime, ship the
        build directory.
        """
        document = {
            **self.status.to_dict(),
            "schema": STATUS_SCHEMA,
            "project": self.project,
            "modules": [module.to_dict() for module in self.modules],
            "next_step": self.next_step,
            "in_flight": list(self.in_flight),
            "source_root": self.source_root,
        }
        if self.alias is not None:
            document["before_you_delete"] = before_you_delete(
                self.alias, modules=[self.alias.module]
            )
        return document


# ---------------------------------------------------------------------------
# Reading the ladder
# ---------------------------------------------------------------------------


def read_ladder(root: Path) -> LadderReading:
    """Read *root* and say where it stands on the retrofit ladder.

    One pass and no writes. The tree is read by the scan, the file classes
    by the classifier ``s0ma verify`` shares, the drafts by their own bytes,
    the baselines by the committed record and the built modules by the build
    manifest. Nothing is imported and nothing is executed.

    A tree with no ``[tool.s0ma]`` table of its own is rung 0 — the table
    has to be on *this* tree, exactly as ``s0ma adopt scan`` requires, so a
    plain-Python directory sitting inside a s0ma repository is not read as
    the outer repository's project.
    """
    from s0ma_dsl.adopt.discovery import _project_declared_at
    from s0ma_dsl.adopt.report import build_scan_report

    project = _project_declared_at(root)
    report = build_scan_report(root)
    drafts = _drafts(project)
    baselines = _baselines(root, project)
    built, has_build = _built(project, root)

    modules = _module_states(
        report,
        project=project,
        drafts=drafts,
        baselines=baselines,
        built=built,
        has_build=has_build,
    )
    counts = _counts(modules, baselines=baselines, has_build=has_build)
    rung = _rung(project, modules)
    mode = _mode(project)
    source_root = _first_source_root(project, root)
    in_flight = _in_flight(modules)
    alias = _alias_for(in_flight, project=project, root=root, built=built)
    step, command, next_module = _next_step(
        rung=rung,
        modules=modules,
        in_flight=in_flight,
        mode=mode,
        alias=alias,
    )
    # `ScanReport.project` is a read-only Mapping of mixed-typed facts, so
    # the name comes back as an object until it is asked to be a string.
    declared = report.project.get("name") if project is not None else None
    name = declared if isinstance(declared, str) else None

    return LadderReading(
        status=LadderStatus(
            rung=rung,
            rung_label=RUNG_LABELS[rung],
            mode=mode,
            counts=counts,
            score=_score(project, mode),
            score_floor=_floor(mode),
            next_module=next_module,
            next_command=command,
        ),
        project=name,
        modules=modules,
        next_step=step,
        in_flight=tuple(state.module for state in in_flight),
        source_root=source_root,
        alias=alias,
    )


def _alias_for(
    in_flight: Sequence[ModuleState],
    *,
    project: S0maProject | None,
    root: Path,
    built: Mapping[str, Path],
) -> AliasPlan | None:
    """The alias plan for the module the next step is about, or ``None``.

    Only one state needs it: converted, compared clean, and the original
    Python still on disk. That is the last step of the ladder and the one
    a person cannot derive — so the reading carries the lines rather than
    the name of a document that has them.
    """
    if project is None or not in_flight:
        return None
    state = in_flight[0]
    if state.state != STATE_PARITY_CLEAN or state.python_path is None:
        return None
    emitted = built.get(state.module)
    if emitted is None:  # pragma: no cover - parity-clean implies a build
        return None
    return alias_plan(
        root,
        module=state.module,
        python_path=state.python_path,
        build_dir=_relative(project.build_dir, root),
        built_module=emitted.stem,
    )


def ladder_status(root: Path) -> LadderStatus:
    """The summary alone: rung, counts, mode, score and the next command.

    The frozen interface of this module (retrofit plan §5.1). It is
    :meth:`LadderReading.status` — call :func:`read_ladder` instead when the
    per-module detail or the sentence beside the command is wanted, so the
    tree is read once rather than twice.
    """
    return read_ladder(root).status


# ---------------------------------------------------------------------------
# The last step of the ladder, computed rather than cited
# ---------------------------------------------------------------------------

#: The distributions a built module imports at load time. Both are needed
#: by every generated file — ``s0ma.decorators`` for the registration
#: decorator, ``s0ma_dsl.runtime_bridge`` for the registration calls — so
#: a project that converts a module and does not declare them ships an
#: application that cannot import itself (pilot defect G2-4).
RUNTIME_DISTRIBUTIONS: tuple[str, ...] = ("s0ma-core", "s0ma-dsl")

#: Where the block goes inside the package's ``__init__.py``, in the one
#: form a reader can follow to the letter. "At the top" is wrong for most
#: packages and quietly dangerous: a module docstring has to stay first,
#: and Python refuses a ``from __future__`` import that is not the first
#: statement after it — so somebody taking "at the top" literally writes
#: a ``SyntaxError`` into the riskiest step of the ladder (G3c). Both the
#: text and the document say this, from here, so the two cannot drift.
ALIAS_PLACEMENT = (
    "below its docstring and any `from __future__` line, above the "
    "package's own imports"
)


@dataclass(frozen=True, slots=True)
class AliasPlan:
    """The exact lines that point a converted module's old name at the built one.

    A build directory is flat by contract: the module drafted from
    ``src/bookshelf/errors.py`` is importable as ``errors``, never as
    ``bookshelf.errors``. So the moment the Python file goes, every
    ``from .errors import …`` in the package stops resolving until the
    package's own ``__init__.py`` binds the built module under the old
    name — twice, because a pre-populated ``sys.modules`` entry means the
    import system never sets the parent attribute (friction F-E2-1).

    Nothing here is cited from a guide: every value is read off *this*
    project, because the one number a reader cannot derive is how far the
    package sits below the project root (the guide's worked example needs
    ``parents[2]`` for a ``src/`` layout and the pilot's four flat
    packages needed ``parents[1]``).

    * ``module`` — the dotted name the Python had.
    * ``python_path`` — the file to delete, project-relative.
    * ``package_init`` — the ``__init__.py`` the lines go into, or
      ``None`` when the module is not inside a package and no alias is
      needed (nothing can write ``from .x import`` without one).
    * ``place`` — where in that file they go
      (:data:`ALIAS_PLACEMENT`), which is a field rather than prose
      because an agent reading the document has to place them as
      carefully as a person reading the sentence.
    * ``build_dir`` — the build directory, project-relative.
    * ``built_module`` — the flat name the build gave it.
    * ``attribute`` — the name its siblings import it by.
    * ``lines`` — the block to paste, or empty with no package.
    """

    module: str
    python_path: str
    package_init: str | None
    build_dir: str
    built_module: str
    attribute: str
    lines: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "attribute": self.attribute,
            "build_dir": self.build_dir,
            "built_module": self.built_module,
            "lines": list(self.lines),
            "module": self.module,
            "package_init": self.package_init,
            "place": ALIAS_PLACEMENT,
            "python_path": self.python_path,
        }


def alias_plan(
    root: Path,
    *,
    module: str,
    python_path: str,
    build_dir: str,
    built_module: str,
) -> AliasPlan:
    """Work out the alias lines for *module* in *root*; never read the code.

    *python_path* and *build_dir* are project-relative POSIX strings, and
    every path this returns is one too (NFR-7). The only thing looked at
    on disk is whether the Python file's own directory carries an
    ``__init__.py``: with one, the module is inside a package and the
    lines are needed; without one, there is nothing to alias and the
    caller says so instead.
    """
    python = PurePosixPath(python_path)
    attribute = python.stem
    init = python.parent / "__init__.py"
    if not (root / init).is_file():
        return AliasPlan(
            module=module,
            python_path=python_path,
            package_init=None,
            build_dir=build_dir,
            built_module=built_module,
            attribute=attribute,
            lines=(),
        )
    # `parents[N]` counts the directories between the __init__.py and the
    # project root: one hop per path segment above the file itself. For
    # `src/bookshelf/__init__.py` that is 2, and for a package sitting at
    # the top of the repository it is 1.
    climb = len(init.parts) - 1
    return AliasPlan(
        module=module,
        python_path=python_path,
        package_init=init.as_posix(),
        build_dir=build_dir,
        built_module=built_module,
        attribute=attribute,
        lines=(
            "import sys",
            "from pathlib import Path",
            "",
            "from s0ma.bootstrap import bootstrap_imports",
            "",
            f'_BUILT = bootstrap_imports(Path(__file__).resolve().parents[{climb}]'
            f' / "{build_dir}")',
            f'{attribute} = _BUILT["{built_module}"]',
            f'sys.modules[f"{{__name__}}.{attribute}"] = {attribute}',
        ),
    )


def before_you_delete(plan: AliasPlan | None, *, modules: Sequence[str]) -> dict[str, Any]:
    """The three facts a conversion is not finished without, as a document.

    Composed for the JSON form of ``s0ma adopt verify-parity`` and
    ``s0ma adopt status`` so an agent reads the same three things a
    person does: bind the old name, declare the runtime, ship the build
    directory. ``alias`` is ``None`` where more than one module was
    compared at once (the lines are per package) or where the module is
    not in a package.
    """
    return {
        "alias": plan.to_dict() if plan is not None and plan.lines else None,
        "declare_runtime": list(RUNTIME_DISTRIBUTIONS),
        "modules": list(modules),
        "ship_build_dir": plan.build_dir if plan is not None else None,
    }


# ---------------------------------------------------------------------------
# What the tree holds
# ---------------------------------------------------------------------------


def _drafts(project: S0maProject | None) -> dict[str, Path]:
    """Dotted module name → the ``.s0ma`` source that converts it.

    Named the way the Python was: a draft written from
    ``src/bookshelf/errors.py`` lands at ``src/bookshelf/errors.s0ma``
    (§5.5), so its dotted name is its path inside the source root with the
    separators turned into dots — the same rule discovery applies to a
    ``.py``. That holds the naming together after the Python file is gone,
    which is the one moment nothing else can supply the dotted name.

    A ``.s0ma`` written somewhere else with ``--out`` is not found here, and
    would not be built either: the build reads the source roots.

    A source root that is itself a package contributes its own name, the
    way :func:`~s0ma_dsl.adopt.discovery.package_prefix` explains: with
    ``harness`` as a source root, ``harness/cli.s0ma`` is ``harness.cli``
    here and in the scan, so one module cannot arrive under two names and
    be counted twice.
    """
    from s0ma_dsl.adopt.discovery import package_prefix

    found: dict[str, Path] = {}
    if project is None:
        return found
    for source_root in project.source_roots:
        prefix = package_prefix(source_root)
        for path in iter_visible_files(source_root, "*.s0ma"):
            try:
                relative = path.relative_to(source_root)
            except ValueError:  # pragma: no cover - iter_visible_files walks it
                continue
            module = prefix + ".".join([*relative.parts[:-1], relative.stem])
            found.setdefault(module, path)
    return found


def _baselines(root: Path, project: S0maProject | None) -> dict[str, BaselineEntry]:
    """The committed baselines, or nothing when there are none to read.

    A record that will not load reads as no baselines at all rather than as
    a refusal: a status reports, and ``s0ma adopt baseline`` is the surface
    that says so loudly.
    """
    from s0ma_dsl.adopt.parity import BaselineRecordError, load_baselines

    if project is None:
        return {}
    try:
        return load_baselines(root)
    except BaselineRecordError:
        return {}


def _built(
    project: S0maProject | None, root: Path
) -> tuple[dict[str, Path], bool]:
    """What the build emitted, by module name, and whether there is a build.

    The two are separate answers. No build at all means every parity verdict
    is honestly unknown; a build that contains one module means the other
    ten are *not built*, which is a different thing and is reported as one.
    """
    from s0ma.bootstrap import ManifestSchemaError

    from s0ma_dsl.codegen.build_manifest import load_manifest

    if project is None:
        return {}, False
    try:
        manifest = load_manifest(project.build_dir)
    except (ManifestSchemaError, OSError):
        return {}, False

    from s0ma_dsl.adopt.discovery import package_prefix

    prefixes = {
        _relative(source_root, root): package_prefix(source_root)
        for source_root in project.source_roots
    }
    found: dict[str, Path] = {}
    for entry in manifest.modules:
        path = project.build_dir / entry.output
        logical = str(getattr(entry, "logical_path", "") or "")
        if logical:
            # The dotted name the Python had, recovered the way
            # `verify-parity` recovers it: s0ma module names are flat, so
            # `logical_path` is the only thing that joins `errors` back to
            # `bookshelf.errors`. It is relative to the module's own source
            # root, so a root that is itself a package contributes its name
            # here too — otherwise `harness/cli.s0ma` would be `cli` to the
            # build and `harness.cli` to the scan.
            prefix = prefixes.get(str(getattr(entry, "source_root", "") or ""), "")
            found.setdefault(
                prefix + logical.removesuffix(".s0ma").replace("/", "."), path
            )
        found.setdefault(entry.name, path)
    return found, True


# ---------------------------------------------------------------------------
# The conversion set, module by module
# ---------------------------------------------------------------------------


def _module_states(
    report: ScanReport,
    *,
    project: S0maProject | None,
    drafts: Mapping[str, Path],
    baselines: Mapping[str, BaselineEntry],
    built: Mapping[str, Path],
    has_build: bool,
) -> tuple[ModuleState, ...]:
    """Every module a conversion is about, in the scan's conversion order.

    The set is the union of two readings, because neither alone is complete
    once a conversion has started: the application Python the perimeter has
    not exempted, and every ``.s0ma`` source in the source roots — which is
    what is left of a module after its Python file is deleted.
    """
    exempt, adopted = _classified(project)
    order = {module: index for index, module in enumerate(report.graph.order)}
    paths = {
        census.source.module: census.source.path
        for census in report.modules
        if census.source.role in _CONVERTIBLE_ROLES
    }
    root = project.root if project is not None else None

    candidates = {
        module for module, path in paths.items() if path not in exempt
    } | set(drafts)
    states = [
        _module_state(
            module,
            python_path=paths.get(module),
            draft=drafts.get(module),
            adopted=paths.get(module) in adopted,
            baseline=module in baselines,
            built=built.get(module),
            has_build=has_build,
            baselines=baselines,
            root=root,
        )
        for module in candidates
    ]
    # The scan's order first, so "the next module" and "the furthest along"
    # break their ties the same way the conversion plan reads; anything the
    # scan never saw (a draft whose Python is gone) sorts after it by name.
    return tuple(
        sorted(
            states,
            key=lambda state: (order.get(state.module, len(order)), state.module),
        )
    )


def _module_state(
    module: str,
    *,
    python_path: str | None,
    draft: Path | None,
    adopted: bool,
    baseline: bool,
    built: Path | None,
    has_build: bool,
    baselines: Mapping[str, BaselineEntry],
    root: Path | None,
) -> ModuleState:
    """One module's state, its draft's debt and its parity verdict."""
    placeholders, quarantined = _draft_debt(draft)
    parity, differences = _parity(
        module,
        built=built,
        has_build=has_build,
        baselines=baselines,
    )
    shown = (
        _relative(draft, root)
        if draft is not None and root is not None
        else python_path
    )

    if draft is None:
        state = (
            STATE_ADOPTED_IN_PLACE
            if adopted
            else STATE_BASELINE_TAKEN
            if baseline
            else STATE_PLAIN_PYTHON
        )
    elif placeholders or quarantined:
        state = STATE_DRAFTED
    elif built is None:
        state = STATE_AUTHORED
    elif python_path is None:
        state = STATE_CONVERTED
    elif parity == PARITY_DIFFERENCES:
        state = STATE_PARITY_DIFFERS
    elif parity == PARITY_SAME_SURFACE:
        state = STATE_PARITY_CLEAN
    else:
        state = STATE_BUILT_WITHOUT_BASELINE

    return ModuleState(
        module=module,
        path=shown or module,
        python_path=python_path,
        state=state,
        placeholders=placeholders,
        quarantined=quarantined,
        baseline=baseline,
        parity=parity,
        differences=differences,
    )


def _draft_debt(draft: Path | None) -> tuple[int, bool]:
    """How many placeholders a draft still carries, and whether it quarantines.

    Counted from the draft's own bytes, which is where every other caller
    counts them too (friction F-D4-3): nothing in the frozen draft model
    holds the number, because a placeholder is the emitter's decision rather
    than the harvester's. The markers are imported, never re-typed — they
    are part of the ``@1`` contract and the checker matches the same text.
    """
    from s0ma_dsl.adopt.harvest import UNPLACED_CELL_PREFIX

    if draft is None:
        return 0, False
    try:
        text = draft.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        # A draft that cannot be read is reported as carrying no debt
        # rather than as a crash; `s0ma check` is the surface that refuses.
        return 0, False
    quarantined = DRAFT_UNPLACED_MARKER in text or UNPLACED_CELL_PREFIX in text
    return text.count(DRAFT_INTENT_MARKER), quarantined


def _parity(
    module: str,
    *,
    built: Path | None,
    has_build: bool,
    baselines: Mapping[str, BaselineEntry],
) -> tuple[str | None, int]:
    """The verdict for one module, computed rather than remembered.

    Nothing records what a previous ``s0ma adopt verify-parity`` said, and
    nothing should: a verdict is only true of the bytes on disk right now.
    So this runs the comparison itself, through the same
    :func:`~s0ma_dsl.adopt.parity.compare_surfaces` the command runs, over
    the built module parsed and never imported.

    ``None`` until something has been built: with no build directory the
    question has not been asked of any module, and answering it per module
    would read as a finding.
    """
    from s0ma_dsl.adopt.parity import compare_surfaces
    from s0ma_dsl.adopt.surface import SurfaceReadError, static_surface

    if not has_build:
        return None, 0
    entry = baselines.get(module)
    if built is None:
        return (PARITY_BASELINE_NOT_BUILT, 0) if entry is not None else (None, 0)
    if entry is None:
        return PARITY_BUILT_WITHOUT_BASELINE, 0
    try:
        surface = static_surface(built, module=module)
    except SurfaceReadError:
        # An emitted file that will not parse is not a parity finding: the
        # build is what refuses on it, and saying "differences" here would
        # name the wrong problem.
        return None, 0
    result = compare_surfaces(entry.surface, surface, built_path=built.name)
    if result.clean:
        return PARITY_SAME_SURFACE, 0
    return PARITY_DIFFERENCES, len(result.findings)


def _classified(
    project: S0maProject | None,
) -> tuple[frozenset[str], frozenset[str]]:
    """The perimeter's exempt files and the adopted ones, as verify sees them.

    Imported, never re-derived (the rule ``adopt scan``'s reconciliation
    follows): a file this calls exempt is a file ``s0ma verify`` calls
    ``BOOTSTRAP`` or ``PACKAGE_MARKER``, and one it calls adopted is one
    verify calls ``ADOPTED``. Both come back as project-relative,
    forward-slashed paths, which is how the census names a file.
    """
    if project is None:
        return frozenset(), frozenset()

    from s0ma_dsl.cli.score import _verify_surface

    surface = _verify_surface(project)
    if surface is None:
        return frozenset(), frozenset()
    root = project.root

    def shown(paths: Sequence[Path]) -> frozenset[str]:
        return frozenset(_relative(path, root) for path in paths)

    return (
        shown(surface["bootstrap_paths"]) | shown(surface["marker_paths"]),
        shown(surface["adopted_paths"]),
    )


# ---------------------------------------------------------------------------
# The summary
# ---------------------------------------------------------------------------


def _counts(
    modules: Sequence[ModuleState],
    *,
    baselines: Mapping[str, BaselineEntry],
    has_build: bool,
) -> tuple[tuple[str, int], ...]:
    """The counts, sorted by name.

    The four parity counts appear only where there is a build: with nothing
    built they would all be zero, and four zeroes read as four answers
    rather than as an unasked question.
    """
    by_state: dict[str, int] = {}
    for state in modules:
        by_state[state.state] = by_state.get(state.state, 0) + 1
    converted = sum(
        by_state.get(state, 0)
        for state in (
            STATE_AUTHORED,
            STATE_BUILT_WITHOUT_BASELINE,
            STATE_PARITY_DIFFERS,
            STATE_PARITY_CLEAN,
            STATE_CONVERTED,
        )
    )
    counts: dict[str, int] = {
        "modules": len(modules),
        "converted": converted,
        "drafted": by_state.get(STATE_DRAFTED, 0),
        "adopted-in-place": by_state.get(STATE_ADOPTED_IN_PLACE, 0),
        "plain-python": by_state.get(STATE_PLAIN_PYTHON, 0)
        + by_state.get(STATE_BASELINE_TAKEN, 0),
        "baselines": len(baselines),
        "placeholders": sum(state.placeholders for state in modules),
    }
    if has_build:
        by_parity: dict[str, int] = {}
        for state in modules:
            if state.parity is not None:
                by_parity[state.parity] = by_parity.get(state.parity, 0) + 1
        counts["parity-same-surface"] = by_parity.get(PARITY_SAME_SURFACE, 0)
        counts["parity-differences"] = by_parity.get(PARITY_DIFFERENCES, 0)
        counts["parity-built-without-baseline"] = by_parity.get(
            PARITY_BUILT_WITHOUT_BASELINE, 0
        )
        counts["parity-baseline-not-built"] = by_parity.get(
            PARITY_BASELINE_NOT_BUILT, 0
        )
    return tuple(sorted(counts.items()))


def _rung(project: S0maProject | None, modules: Sequence[ModuleState]) -> int:
    """Which rung the project is on, by the plan's own table (§4).

    Rung 2 is never reported: registering Python in place is a way-station
    somebody passes through, not a position on the ladder, and the files it
    produces are counted wherever the project stands.
    """
    if project is None:
        return 0
    started = [
        state
        for state in modules
        if state.state
        not in (STATE_PLAIN_PYTHON, STATE_ADOPTED_IN_PLACE, STATE_BASELINE_TAKEN)
    ]
    if not started:
        return 1
    unfinished = any(
        state.state in (STATE_PLAIN_PYTHON, STATE_BASELINE_TAKEN, STATE_DRAFTED)
        for state in modules
    )
    return 3 if unfinished else 4


def _mode(project: S0maProject | None) -> str | None:
    """The strictness mode this project is in, or ``None`` at rung 0.

    A project whose table declares no mode is read the way the rest of the
    toolchain reads it — ``s0ma_dsl.cli.score.DEFAULT_MODE`` — rather than
    reported as having none: a status that said "no mode" would be
    describing the table, and what the reader needs is the reading their
    commands will get. ``s0ma adopt init`` writes one, so this is the case
    of a table somebody wrote by hand.
    """
    if project is None:
        return None
    from s0ma_dsl.cli.score import DEFAULT_MODE

    return project.mode or DEFAULT_MODE


def _floor(mode: str | None) -> float | None:
    """The score floor *mode*'s gate demands, or ``None`` at rung 0.

    ``s0ma score`` is report-only until ``--gate-mode`` pins a mode; this is
    the number that pinning *this* mode would hold the project to, which is
    what makes rung 4 a measurable step rather than a feeling.
    """
    if mode is None:
        return None
    from s0ma_dsl.cli.score import MODE_FLOORS

    return MODE_FLOORS.get(mode)


def _score(project: S0maProject | None, mode: str | None) -> float | None:
    """The project's overall self-knowledge score, or ``None``.

    Composed from ``s0ma score``'s own report rather than re-derived, so the
    number here is the number that command prints. It is read-only: the
    report is built from parsed sources and classified files and nothing on
    the way writes (proved for every state by the zero-write tests).

    ``None`` is a real answer and a common one early on — a project with
    nothing converted has no measurable faculty to average — and it is also
    what a refusal comes back as, because a status reports where things
    stand and must not fail on a project that is halfway through anything.
    """
    if project is None or mode is None:
        return None
    from s0ma_dsl.cli.score import build_score_report

    try:
        report = build_score_report(project, mode=mode)
    except Exception:  # noqa: BLE001 - a status never fails; see the docstring
        return None
    overall = report.get("overall")
    return float(overall) if isinstance(overall, (int, float)) else None


def _in_flight(modules: Sequence[ModuleState]) -> tuple[ModuleState, ...]:
    """The started-and-unfinished modules, furthest along first.

    Ties are broken by the conversion order, which *modules* is already in,
    so a stable sort on the progress rank alone is the whole rule.
    """
    started = [state for state in modules if state.state in _IN_FLIGHT]
    return tuple(sorted(started, key=lambda state: -_PROGRESS[state.state]))


def _first_source_root(project: S0maProject | None, root: Path) -> str | None:
    """The project's first source root, project-relative and forward-slashed.

    It used to be threaded into every message that named ``s0ma build``,
    because the command would not run without a directory (friction
    F-E2-2). It runs bare now, so this is a fact the reading reports
    rather than an argument it has to supply.
    """
    if project is None or not project.source_roots:
        return None
    return _relative(project.source_roots[0], root)


# ---------------------------------------------------------------------------
# The next step — the decision table in the module docstring, as code
# ---------------------------------------------------------------------------


def _next_step(
    *,
    rung: int,
    modules: Sequence[ModuleState],
    in_flight: Sequence[ModuleState],
    mode: str | None,
    alias: AliasPlan | None = None,
) -> tuple[str, str, str | None]:
    """The sentence, the command and the module the next step is about.

    The rows of the table in this module's docstring, in its order. The
    first row whose condition holds wins, which is why "in flight" is asked
    before "what is left": a retrofit that starts a second module before
    finishing the first ends with two half-converted modules and no way to
    run the tests on either.
    """
    if rung == 0:
        return (
            "Nothing is set up here yet. This reads the codebase without "
            "changing any of it and says what is in it, in what order to "
            "convert it, and what the perimeter would be.",
            "s0ma adopt scan",
            None,
        )
    if not modules:
        return (
            "No application code was found to convert. Check that this is "
            "the right directory, and that [tool.s0ma].source_roots names "
            "where your code really lives.",
            "s0ma adopt scan",
            None,
        )
    if in_flight:
        return _next_for(in_flight[0], alias=alias)

    waiting = [state for state in modules if state.state == STATE_PLAIN_PYTHON]
    if waiting:
        first = waiting[0].module
        return (
            f"{first} is the first module of the conversion order that is "
            f"still plain Python. Record what it promises its callers before "
            f"you change anything about it — that record cannot be taken "
            f"once the file is gone.",
            f"s0ma adopt baseline {first}",
            first,
        )
    return _next_mode(mode)


def _next_for(
    state: ModuleState, *, alias: AliasPlan | None = None
) -> tuple[str, str, str | None]:
    """Rows 3 to 8: what the module furthest along needs next."""
    module = state.module
    if state.state == STATE_PARITY_CLEAN:
        python = state.python_path or f"{module}'s Python file"
        # One line, and it is the half people forget: the build directory
        # is flat, so deleting the Python without binding the old name
        # leaves the package unable to import itself. The other two facts
        # (declare the runtime, ship the build directory) and the lines
        # themselves come from the command named here — a command that
        # runs offline, unlike a pointer into a guide that an installed
        # toolchain may not be able to open.
        where = f" in {alias.package_init}" if alias is not None and alias.lines else ""
        return (
            f"{module} is converted and unchanged. Before you delete {python}, "
            f"this prints the lines that point its old name at the built "
            f"module{where}, and the two other things the step needs.",
            f"s0ma adopt verify-parity {module}",
            module,
        )
    if state.state == STATE_PARITY_DIFFERS:
        count = state.differences
        what = "one difference" if count == 1 else f"{count} differences"
        return (
            f"{module} was built, and its surface is not what the Python "
            f"promised: {what}. This names each one, with the text before "
            f"and after, so you can decide whether the conversion or the "
            f"baseline is the thing to change.",
            f"s0ma adopt verify-parity {module}",
            module,
        )
    if state.state == STATE_BUILT_WITHOUT_BASELINE:
        return (
            f"{module} has been built and nothing was recorded of what its "
            f"Python promised, so there is nothing to compare it against. "
            f"The Python file is still there, so the record can still be "
            f"taken — after that, `s0ma adopt verify-parity {module}`.",
            f"s0ma adopt baseline {module}",
            module,
        )
    if state.state == STATE_AUTHORED:
        return (
            f"{state.path} is written and has no placeholders left. Build it, "
            f"so there is a module to compare with the baseline. Run this from "
            f"the project and it builds every source root you declared.",
            "s0ma build",
            module,
        )
    if state.state == STATE_DRAFTED:
        return (
            f"{state.path} still carries {_debt(state)}. Write them — each "
            f"one says what belongs there — and then read back what is left; "
            f"a draft with a placeholder in it is refused in every mode, on "
            f"purpose.",
            "s0ma check",
            module,
        )
    return (
        f"{module} has a baseline and no draft yet. This turns its Python "
        f"into a .s0ma draft, deriving the structure and leaving every field "
        f"that says what something is for as a line for you to write. The "
        f"Python file is not touched.",
        f"s0ma adopt draft {module}",
        module,
    )


def _next_mode(mode: str | None) -> tuple[str, str, str | None]:
    """Rows 10 and 11: nothing left to convert, so the mode is the work."""
    current = mode or MODE_LADDER[0]
    index = MODE_LADDER.index(current) if current in MODE_LADDER else 0
    if index >= len(MODE_LADDER) - 1:
        return (
            "Everything is converted and the mode is already release, the "
            "strictest reading there is. This proves the project clears that "
            "mode's floor, and refuses if it ever falls back below it.",
            "s0ma score --gate --gate-mode release",
            None,
        )
    nxt = MODE_LADDER[index + 1]
    return (
        f"Everything is converted. What is left is the strictness mode: "
        f"move {current} up to {nxt}, one step at a time. This says what "
        f"{nxt} would refuse before you set it in pyproject.toml.",
        f"s0ma check --mode {nxt}",
        None,
    )


def _debt(state: ModuleState) -> str:
    """What a draft still owes, in words: placeholders, quarantine, or both."""
    parts = []
    if state.placeholders:
        count = state.placeholders
        parts.append(f"{count} {_plural(count, 'placeholder', 'placeholders')}")
    if state.quarantined:
        parts.append("source it could not place, quarantined as data")
    return " and ".join(parts) if parts else "work still to finish"


# ---------------------------------------------------------------------------
# The text form
# ---------------------------------------------------------------------------


def render_status_text(reading: LadderReading) -> str:
    """The reading as the screen somebody reads between two other things.

    At most :data:`MAX_STATUS_LINES` lines, in the order the questions get
    asked: which rung, what the numbers are, what is in flight, what to run
    now, and where the whole path is written down. The in-flight line is the
    section that gives way when a long sentence needs the room — the next
    step names that module anyway, so nothing is lost but a repetition.
    """
    head = [*_heading_lines(reading), ""]
    tail = [
        *_next_lines(reading),
        "",
        f"The whole path, rung by rung: {_GUIDE_COMMAND}",
    ]
    flight = _flight_lines(reading)
    if len(head) + len(flight) + len(tail) > MAX_STATUS_LINES:
        flight = []
    return "\n".join([*head, *flight, *tail]) + "\n"


def _heading_lines(reading: LadderReading) -> list[str]:
    """Which rung, the counts as one block, and where the mode stands."""
    status = reading.status
    counts = dict(status.counts)
    who = reading.project or "This codebase"
    lines = [
        f"{who} — rung {status.rung} of 4: {status.rung_label}.",
        _progress_sentence(counts),
    ]
    if status.mode is None:
        lines.extend(
            _wrap(
                "There is no [tool.s0ma] table here yet, so there is no "
                "mode, no score and nothing built.",
                indent="  ",
            )
        )
        return lines
    lines.extend(_wrap(_tally_sentence(counts), indent="  "))
    lines.append(_mode_sentence(status))
    return lines


def _progress_sentence(counts: Mapping[str, int]) -> str:
    """The headline: how much of the conversion set is done."""
    total = counts.get("modules", 0)
    converted = counts.get("converted", 0)
    plain = counts.get("plain-python", 0)
    if total == 0:
        return "No application code was found to convert."
    if converted == 0:
        return (
            f"Nothing converted yet: {total} "
            f"{'module' if total == 1 else 'modules'} to convert."
        )
    if plain == 0:
        return (
            f"All {total} {'module' if total == 1 else 'modules'} converted."
        )
    return f"{converted} of {total} modules converted, {plain} still plain Python."


def _tally_sentence(counts: Mapping[str, int]) -> str:
    """Everything else worth a number, as one compact block.

    The parity buckets appear only where a build exists, and only the ones
    with something in them: a run of zeroes reads as four answers where the
    honest reading is that nothing has been compared.
    """
    parts = [
        f"drafted {counts.get('drafted', 0)}",
        f"placeholders {counts.get('placeholders', 0)}",
        f"adopted in place {counts.get('adopted-in-place', 0)}",
        f"baselines {counts.get('baselines', 0)}",
    ]
    if "parity-same-surface" in counts:
        verdicts = [
            (counts["parity-same-surface"], "same surface"),
            (counts["parity-differences"], "with differences"),
            (counts["parity-built-without-baseline"], "built without a baseline"),
            (counts["parity-baseline-not-built"], "recorded but not built"),
        ]
        named = [f"{count} {what}" for count, what in verdicts if count]
        parts.append(
            f"parity: {', '.join(named)}" if named else "parity: nothing compared"
        )
    return " · ".join(parts)


def _mode_sentence(status: LadderStatus) -> str:
    """The mode, its floor, and the score against it."""
    floor = (
        f"floor {status.score_floor:.0f}%"
        if status.score_floor is not None
        else "no floor"
    )
    score = (
        f"score {status.score:.1f}%"
        if status.score is not None
        else "score not measurable yet (`s0ma score` says why)"
    )
    return f"  mode {status.mode} ({floor}) · {score}"


def _plural(count: int, singular: str, plural: str) -> str:
    """*singular* when there is one of something, *plural* otherwise."""
    return singular if count == 1 else plural


def _flight_lines(reading: LadderReading) -> list[str]:
    """What is started and unfinished — the furthest along, and how many.

    One module is named because one module is what the next step is about.
    The others are counted rather than listed: naming them would invite
    somebody to pick one up, which is the opposite of what the rule says.
    """
    if not reading.in_flight:
        return []
    first = reading.in_flight[0]
    rest = len(reading.in_flight)
    others = "" if rest == 1 else f" ({rest} unfinished)"
    state = next(
        module for module in reading.modules if module.module == first
    )
    return [*_wrap(f"In flight: {first}{others} — {_in_words(state)}."), ""]


def _in_words(state: ModuleState) -> str:
    """One module's state as a sentence fragment, not as its token."""
    if state.state == STATE_BASELINE_TAKEN:
        return "its baseline is recorded, no draft yet"
    if state.state == STATE_DRAFTED:
        return f"a draft carrying {_debt(state)}"
    if state.state == STATE_AUTHORED:
        return "the draft is written, nothing built from it yet"
    if state.state == STATE_BUILT_WITHOUT_BASELINE:
        return "built, with nothing recorded to compare it against"
    if state.state == STATE_PARITY_DIFFERS:
        count = state.differences
        return (
            f"built, {count} "
            f"{_plural(count, 'difference', 'differences')} from what its "
            f"Python promised"
        )
    return "built, unchanged, the .py is still there"


def _next_lines(reading: LadderReading) -> list[str]:
    """The step in words and the command on its own line."""
    label = (
        "Next — finish what is started before starting another:"
        if reading.in_flight
        else "Next:"
    )
    return [
        label,
        *_wrap(reading.next_step, indent="  "),
        f"  {reading.status.next_command}",
    ]


def _wrap(text: str, *, indent: str = "") -> list[str]:
    """One sentence folded to :data:`_WRAP` columns, continuations indented."""
    return textwrap.wrap(
        text,
        width=_WRAP,
        initial_indent=indent,
        subsequent_indent=f"{indent}  ",
        break_long_words=False,
        break_on_hyphens=False,
    ) or [f"{indent}{text}"]


def _relative(path: Path, root: Path) -> str:
    """*path* as a project-relative, forward-slashed string (NFR-7)."""
    try:
        return path.relative_to(root).as_posix()
    except ValueError:  # pragma: no cover - every path here is inside the root
        return path.name
