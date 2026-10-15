"""Rung 1 of the retrofit ladder — the perimeter, and nothing else.

Rung 0 read the tree and said what is in it. Rung 1 makes that tree a
s0ma project **without touching a line of application code**: it declares
where the code lives, which files are deliberate plain-Python exceptions,
which ``__init__.py`` files only mark a package, and the most forgiving
strictness mode there is. That is the whole of it.

Exactly two files may change, and the rest of the tree is not opened for
writing at all:

* ``pyproject.toml`` — the ``[tool.s0ma]`` table is **appended**, so the
  bytes that were there before remain a strict prefix of the bytes that
  are there after. A tree with no ``pyproject.toml`` gets a minimal one.
* ``AGENTS.md`` — one marked block is appended telling whoever works here
  next that a retrofit is under way, where the guide is, and what to run.
  A second run recognises its own block and changes nothing.

No starter module, no test directory, no adoption record, no build. That
restraint is the ruling (retrofit plan R-4): the ``UNKNOWN`` backlog that
``s0ma verify`` reports straight afterwards is the honest to-convert list,
and adopting files wholesale to make the first number look better would
hide the very work the ladder exists to do.

**Never leave a project that does not load.** Every write is followed by
loading the project the way the rest of the CLI loads it. If the loader
refuses — overlapping discovery roots is the one this meets in practice —
``pyproject.toml`` is restored to its exact previous bytes and the whole
command refuses, saying what was wrong and what to pass instead.

**A dry run runs the same check.** ``--dry-run`` renders the table into a
temporary directory of its own and loads *that*, so it reaches the same
verdict as the real run and refuses where the real run would refuse.
Nothing is written inside the project either way. A dry run that approved
a perimeter the real run then rejected was the pilot's worst kind of
surprise: it made the safe command the misleading one.
"""

from __future__ import annotations

import textwrap
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Sequence

    from s0ma_dsl.adopt.model import PerimeterSuggestion

__all__ = [
    "AGENTS_BLOCK_BEGIN",
    "AGENTS_BLOCK_END",
    "AGENTS_FILENAME",
    "PerimeterRefusedError",
    "PerimeterResult",
    "append_preserving",
    "apply_perimeter",
    "decide_test_roots",
    "refuse_if_already_a_project",
    "render_agents_block",
    "render_dry_run_text",
    "render_init_text",
    "render_table",
]


_WRAP = 88
"""The column the retrofit family's prose folds at.

The same width ``s0ma adopt scan`` reports at, so a person running rung 0
and then rung 1 reads one thing rather than two.
"""

AGENTS_FILENAME = "AGENTS.md"
"""The agent contract every s0ma project keeps at its root.

Agent-agnostic on purpose: ``AGENTS.md`` is the file every client reads,
and a Claude-specific ``CLAUDE.md`` in a project that has one is a single
``@AGENTS.md`` line pointing back here. ``s0ma adopt init`` never writes
``CLAUDE.md``: creating a client's configuration file inside somebody
else's repository is not the perimeter's business.
"""

AGENTS_BLOCK_BEGIN = "<!-- s0ma:retrofit:begin -->"
AGENTS_BLOCK_END = "<!-- s0ma:retrofit:end -->"
"""The markers around the block ``adopt init`` appends to ``AGENTS.md``.

HTML comments, so they are invisible wherever the file is rendered, and
stable, so a second run finds its own block and leaves the file exactly
as it is. Everything between them belongs to s0ma; everything outside
them belongs to whoever wrote it, and is never read, moved or rewritten.
"""


class PerimeterRefusedError(Exception):
    """A refusal, carrying the one plain sentence a reader can act on.

    Raised instead of returning a result so a caller cannot mistake a
    refusal for a half-written perimeter. Every raise site leaves the
    tree exactly as it found it — the one path that has already written
    restores the original bytes before raising.
    """


@dataclass(frozen=True, slots=True)
class PerimeterResult:
    """What rung 1 did, or what it would have done under ``--dry-run``."""

    root: Path
    """The tree the perimeter was set around."""

    pyproject_action: str
    """``"appended"`` to an existing file, or ``"created"`` from nothing."""

    table: str
    """The exact ``[tool.s0ma]`` text written (or that would be)."""

    agents_action: str
    """``"created"``, ``"appended"``, or ``"unchanged"`` (block already there)."""

    agents_block: str
    """The exact ``AGENTS.md`` block written (or that would be)."""

    source_roots: tuple[str, ...]
    """The declared source roots, in the order the table names them."""

    build_dir: str
    """The build directory the project will use — nothing there is ever edited."""

    written: tuple[str, ...]
    """Project-relative POSIX paths this run actually wrote. Empty on a dry run."""

    dry_run: bool
    """True when nothing was written."""


# ---------------------------------------------------------------------------
# The byte-preserving append
# ---------------------------------------------------------------------------


def append_preserving(path: Path, text: str) -> None:
    """Append *text* to *path* so the existing bytes stay a strict prefix.

    Bytes mode throughout, and deliberately so: a text-mode read/write
    round trip translates the newlines already in the file (universal
    newlines on the way in, the platform's own on the way out), which
    silently rewrites every line of somebody else's file on Windows. The
    contract this whole command rests on — *your bytes are still your
    bytes* — cannot survive that.

    One blank line separates what was there from what is added, which is
    the separator rule ``s0ma new project`` established for the same
    table (``cli/new_project.py``). An empty file gets no separator at
    all, so a created-then-appended file does not open with blank lines.

    The one copy of this contract in the retrofit family: the
    ``[tool.s0ma]`` table and the ``AGENTS.md`` block both go through it.
    """
    original = path.read_bytes() if path.is_file() else b""
    if not original:
        separator = b""
    elif original.endswith(b"\n"):
        separator = b"\n"
    else:
        separator = b"\n\n"
    path.write_bytes(original + separator + text.encode("utf-8"))


# ---------------------------------------------------------------------------
# What gets written
# ---------------------------------------------------------------------------


def render_table(suggestion: PerimeterSuggestion, *, test_roots: tuple[str, ...] | None) -> str:
    """The ``[tool.s0ma]`` table rung 1 writes, as text, always LF.

    Four settings and no more: where the code lives, which files are
    meant to stay plain Python, which ones only mark a package, and the
    mode. Nothing about authoring, feedback or build directories is
    declared — a perimeter states facts about the tree it was read from,
    and a posture is a decision somebody else gets to make later.

    The key order follows the one ``s0ma new project`` writes
    (``source_roots`` → ``test_roots`` → ``mode``, then the two
    exception lists), so a project initialized either way reads the same.
    An empty exception list is left out rather than written as ``[]``:
    there is nothing to say.

    *test_roots* has three answers, and :func:`decide_test_roots` is what
    works out which:

    * ``None`` — say nothing, because the default (``tests``) is already
      right or there is no test directory to name.
    * a non-empty tuple — the directories this project really keeps its
      tests in, written out. Naming them is what stops every test file
      counting as unconverted for ever.
    * ``()`` — write ``test_roots = []`` with the comment that explains
      it. That is for the one tree that has no room for a test root: the
      code sits in the project directory itself, s0ma refuses a test root
      nested inside a source root, and leaving the key out would produce a
      project that will not load at all.
    """
    lines = [
        "[tool.s0ma]",
        f"source_roots = {_toml_list(suggestion.source_roots)}",
    ]
    if test_roots == ():
        lines.extend(
            [
                "# The code sits in the project directory itself, so there is no",
                "# room for a separate test root inside it — s0ma refuses a test",
                "# root nested in a source root. Until the code moves into a",
                "# directory of its own, every test file here counts as",
                "# unconverted: naming a test root is what takes them off that",
                "# list.",
                "test_roots = []",
            ]
        )
    elif test_roots:
        lines.append(f"test_roots = {_toml_list(test_roots)}")
    lines.append(f'mode = "{suggestion.mode}"')
    if suggestion.bootstrap_files:
        lines.append(
            f"bootstrap_files = {_toml_list(suggestion.bootstrap_files)}"
        )
    if suggestion.package_markers:
        lines.append(
            f"package_markers = {_toml_list(suggestion.package_markers)}"
        )
    return "\n".join(lines) + "\n"


def render_agents_block(build_dir: str) -> str:
    """The block appended to ``AGENTS.md``, between its two markers.

    Three standing rules and one fact, written for whoever opens this
    repository next — a person or an agent — who will otherwise read a
    tree of plain Python with a ``[tool.s0ma]`` table on it and have to
    guess what is going on. *build_dir* is named outright because "never
    edit the build directory" is only actionable if the reader knows
    which directory that is.

    Every command named here has to exist in the shipped CLI. This block
    is written once into somebody else's repository, it carries no
    publication date, and the agent that reads it next will simply run
    what it finds — so a merely-planned command arrives as a broken
    instruction with nothing to date it against. It happened once: the
    block named ``s0ma adopt status`` for some weeks before that command
    was built. It exists now, and it is the right thing to name — one
    command that says which rung the project is on and what to run next
    beats two that leave the reader to work it out — but the rule
    outlives the incident, and two tests hold it: one walks every quoted
    command down the live parser (``test_adopt_init.py``), the other
    parses each as written (``test_adopt_status.py``).
    """
    return (
        f"{AGENTS_BLOCK_BEGIN}\n"
        "## s0ma — this project is being retrofitted\n"
        "\n"
        "This project is being brought into s0ma one module at a time, so most\n"
        "of the code here is still plain Python. That is expected: when\n"
        "`s0ma verify` calls a file `UNKNOWN`, it means \"not converted yet\",\n"
        "not \"broken\".\n"
        "\n"
        "- **Read the guide before converting anything.**\n"
        "  `s0ma docs show doc:guide/retrofit-existing-codebase` teaches the\n"
        "  whole path, rung by rung, and says what each command will show you.\n"
        f"- **Never edit anything under `{build_dir}/`.** Everything in there is\n"
        "  written from the sources on every build. An edit there is not kept —\n"
        "  the drift gate finds it and refuses rather than losing it quietly.\n"
        "- **When you are not sure what to do next, run `s0ma adopt status`.**\n"
        "  It says which rung the project is on and the one command to run now.\n"
        f"{AGENTS_BLOCK_END}\n"
    )


def _agents_file_text(project_name: str, block: str) -> str:
    """A whole ``AGENTS.md`` for a tree that has none, block and all."""
    return f"# {project_name} — agent guide\n\n{block}"


# ---------------------------------------------------------------------------
# Applying it
# ---------------------------------------------------------------------------


def apply_perimeter(
    root: Path,
    suggestion: PerimeterSuggestion,
    *,
    dry_run: bool,
    test_directories: Sequence[str] = (),
) -> PerimeterResult:
    """Write *suggestion* into *root*, or say what that would write.

    The order matters and is the whole safety story. Every refusal that
    can be decided by reading is decided before a byte is written; the
    one that cannot — whether the perimeter *loads* — is met by writing
    ``pyproject.toml``, loading the project the way the rest of the CLI
    loads it, and putting the file back byte for byte if it refuses. Only
    once it loads is ``AGENTS.md`` touched. So the tree is never left
    carrying a table that does not work.

    A dry run reaches the **same verdict**: it renders the same bytes into
    a temporary directory and loads that instead, so it refuses exactly
    where the real run would refuse, and writes nothing inside the project
    either way.

    *test_directories* are the top-level directories the scan found test
    files in; :func:`decide_test_roots` reads them to work out what the
    table should say about test roots.

    Safe to call on its own: it re-asks
    :func:`refuse_if_already_a_project` rather than trusting a caller to
    have asked. Raises :class:`PerimeterRefusedError` with one plain
    sentence for every refusal, and writes nothing when it raises.
    """
    from s0ma_dsl.project import S0maProject, _default_build_dir

    refuse_if_already_a_project(root)

    pyproject = root / "pyproject.toml"
    existing = _read_pyproject_document(pyproject)
    project_name = _project_name(existing, root)

    try:
        build_dir = _default_build_dir(project_name)
    except ValueError:
        raise PerimeterRefusedError(
            f"the project name {project_name!r} cannot be turned into a build "
            f"directory s0ma can import from, so there is nowhere to put the "
            f"built code. Set `[project].name` in pyproject.toml to a name "
            f"that starts with a letter or underscore, then run this again."
        ) from None

    table = render_table(
        suggestion,
        test_roots=decide_test_roots(
            root, suggestion.source_roots, test_directories
        ),
    )
    block = render_agents_block(build_dir)
    agents = root / AGENTS_FILENAME
    agents_action = _agents_action(agents)

    if dry_run:
        _refuse_if_it_would_not_load(
            root, suggestion, table=table, project_name=project_name
        )
        return PerimeterResult(
            root=root,
            pyproject_action="appended" if pyproject.is_file() else "created",
            table=table,
            agents_action=agents_action,
            agents_block=block,
            source_roots=tuple(suggestion.source_roots),
            build_dir=build_dir,
            written=(),
            dry_run=True,
        )

    if pyproject.is_file():
        original = pyproject.read_bytes()
        append_preserving(pyproject, table)
        pyproject_action = "appended"
    else:
        original = None
        pyproject.write_text(
            _minimal_pyproject(project_name, table),
            encoding="utf-8",
            newline="\n",
        )
        pyproject_action = "created"

    try:
        S0maProject.discover(root)
    except Exception as exc:  # noqa: BLE001 — every loader refusal is reported
        _restore(pyproject, original)
        raise PerimeterRefusedError(_load_refusal(exc, suggestion)) from None

    written = ["pyproject.toml"]
    if agents_action == "created":
        agents.write_text(
            _agents_file_text(project_name, block), encoding="utf-8", newline="\n"
        )
        written.append(AGENTS_FILENAME)
    elif agents_action == "appended":
        append_preserving(agents, block)
        written.append(AGENTS_FILENAME)

    return PerimeterResult(
        root=root,
        pyproject_action=pyproject_action,
        table=table,
        agents_action=agents_action,
        agents_block=block,
        source_roots=tuple(suggestion.source_roots),
        build_dir=build_dir,
        written=tuple(written),
        dry_run=False,
    )


def _refuse_if_it_would_not_load(
    root: Path,
    suggestion: PerimeterSuggestion,
    *,
    table: str,
    project_name: str,
) -> None:
    """Load the perimeter somewhere else, and refuse here if it will not.

    The real run answers this by writing ``pyproject.toml``, loading it and
    restoring the bytes on refusal. A dry run may not write inside the
    project at all, so it renders the same bytes into a temporary
    directory and loads *that*. The loader resolves the declared roots as
    paths and never requires them to exist, so the copy gives the same
    verdict — which is the point: a dry run that approves what the real
    run rejects is worse than no dry run.

    The temporary directory is removed whatever happens, and nothing under
    *root* is opened for writing.
    """
    import tempfile

    from s0ma_dsl.project import S0maProject

    pyproject = root / "pyproject.toml"
    with tempfile.TemporaryDirectory(prefix="s0ma-adopt-init-") as scratch:
        elsewhere = Path(scratch)
        rehearsal = elsewhere / "pyproject.toml"
        if pyproject.is_file():
            try:
                # The same bytes, through the same appender, so the copy
                # cannot differ from what the real run would produce.
                rehearsal.write_bytes(pyproject.read_bytes())
            except OSError:
                return
            append_preserving(rehearsal, table)
        else:
            rehearsal.write_text(
                _minimal_pyproject(project_name, table),
                encoding="utf-8",
                newline="\n",
            )
        try:
            S0maProject.discover(elsewhere)
        except Exception as exc:  # noqa: BLE001 — every loader refusal is reported
            raise PerimeterRefusedError(_load_refusal(exc, suggestion)) from None


def refuse_if_already_a_project(root: Path) -> None:
    """Refuse when *root* is a s0ma project, or its pyproject cannot be read.

    Three refusals in one place, because all three are answered by
    reading ``pyproject.toml`` once and all three mean the same thing to
    a reader: this command is not the one to run now. Called before
    anything is read from the rest of the tree, so a refusal costs a
    single file read.
    """
    import tomllib

    pyproject = root / "pyproject.toml"
    if not pyproject.is_file():
        return
    try:
        with pyproject.open("rb") as handle:
            document = tomllib.load(handle)
    except tomllib.TOMLDecodeError as exc:
        raise PerimeterRefusedError(
            f"pyproject.toml is not valid TOML ({exc}), so the perimeter "
            f"cannot be added to it safely. Fix the file, then run this again."
        ) from None
    except OSError as exc:
        raise PerimeterRefusedError(
            f"pyproject.toml could not be read ({exc}), so the perimeter "
            f"cannot be added to it. Check the file's permissions, then run "
            f"this again."
        ) from None

    declared = document.get("tool", {}).get("s0ma")
    if isinstance(declared, dict):
        raise PerimeterRefusedError(
            "this is already a s0ma project — pyproject.toml already has a "
            "[tool.s0ma] table, and rung 1 is done. Run `s0ma adopt scan` to "
            "see what is left to convert."
        )
    if declared is not None:
        raise PerimeterRefusedError(
            f"pyproject.toml has a `tool.s0ma` entry that is not a table "
            f"(it is {type(declared).__name__}), and appending the perimeter "
            f"under it would make the file invalid. Remove or fix that entry, "
            f"then run this again."
        )


# ---------------------------------------------------------------------------
# Rendering the two outputs
# ---------------------------------------------------------------------------


def render_init_text(result: PerimeterResult) -> str:
    """What was written, then the three commands to run next.

    Ends where every command in this family ends: with what to do now,
    and with the one thing a reader is otherwise going to misread — a
    backlog of ``UNKNOWN`` files that is the point rather than a problem.
    """
    verb = "Appended to" if result.pyproject_action == "appended" else "Created"
    lines = [
        f"{verb} pyproject.toml:",
        "",
        *[f"  {line}" for line in result.table.rstrip("\n").split("\n")],
        "",
    ]
    if result.agents_action == "created":
        told = (
            f"Wrote {AGENTS_FILENAME}, so whoever works here next reads the "
            f"same rules you do."
        )
    elif result.agents_action == "appended":
        told = (
            f"Added one marked block to {AGENTS_FILENAME}; everything that was "
            f"already in it is untouched."
        )
    else:
        told = (
            f"{AGENTS_FILENAME} already carries the s0ma block, so it was left "
            f"exactly as it was."
        )
    lines.extend(
        [
            *_wrap(told),
            *_wrap(
                "No application file was touched, and nothing else was written."
            ),
            "",
            *_next_command_lines(result),
        ]
    )
    return "\n".join(lines) + "\n"


def render_dry_run_text(result: PerimeterResult) -> str:
    """Exactly what a real run would write, and the news that it did not."""
    verb = (
        "append to pyproject.toml"
        if result.pyproject_action == "appended"
        else "create pyproject.toml holding"
    )
    lines = [
        "Dry run — nothing was written.",
        "",
        f"Would {verb}:",
        "",
        *[f"  {line}" for line in result.table.rstrip("\n").split("\n")],
        "",
    ]
    if result.agents_action == "unchanged":
        lines.extend(
            _wrap(
                f"Would leave {AGENTS_FILENAME} alone: it already carries the "
                f"s0ma block."
            )
        )
    else:
        where = (
            f"Would write {AGENTS_FILENAME} carrying this block"
            if result.agents_action == "created"
            else f"Would append this block to {AGENTS_FILENAME}"
        )
        lines.extend(
            [
                f"{where}:",
                "",
                *[
                    f"  {line}" if line else ""
                    for line in result.agents_block.rstrip("\n").split("\n")
                ],
                "",
            ]
        )
    lines.extend(
        _wrap(
            "Run `s0ma adopt init` without --dry-run to write them. No "
            "application file is touched either way."
        )
    )
    return "\n".join(lines) + "\n"


def _next_command_lines(result: PerimeterResult) -> list[str]:
    """The three commands, then the one sentence about ``UNKNOWN``.

    The three are the three a person actually wants after rung 1: does
    the toolchain agree this is a project, what does the project now
    think of itself, and what is that as one number to watch. ``verify``
    takes a target, so it is given the first declared source root — the
    form the guide shows.
    """
    target = result.source_roots[0] if result.source_roots else "."
    commands = (
        ("s0ma doctor", "does the toolchain agree this is a project?"),
        (f"s0ma verify --all {target}", "what the project now thinks of itself"),
        ("s0ma score", "the same facts as one number, to watch it move"),
    )
    width = max(len(command) for command, _ in commands)
    return [
        "Run these three next:",
        *[f"  {command:<{width}}   {gloss}" for command, gloss in commands],
        "",
        *_wrap(
            "Every application file will show as UNKNOWN: that is not a fault "
            "but the honest list of what is left to convert, and watching that "
            "number fall is how you know the work is real."
        ),
    ]


def _wrap(text: str) -> list[str]:
    """One sentence folded to :data:`_WRAP` columns, continuations indented."""
    return textwrap.wrap(
        text,
        width=_WRAP,
        subsequent_indent="  ",
        break_long_words=False,
        break_on_hyphens=False,
    ) or [text]


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------


def _read_pyproject_document(pyproject: Path) -> dict[str, object]:
    """The parsed ``pyproject.toml``, or an empty document when there is none.

    Only reached after :func:`refuse_if_already_a_project` has already
    established that the file parses, so a failure here is a race and
    reads as "no document" rather than crashing the command.
    """
    import tomllib

    if not pyproject.is_file():
        return {}
    try:
        with pyproject.open("rb") as handle:
            return tomllib.load(handle)
    except (OSError, tomllib.TOMLDecodeError):
        return {}


def _project_name(document: dict[str, object], root: Path) -> str:
    """The project's own name, or one derived from the directory.

    ``[project].name`` when the tree declares one — the same key
    ``S0maProject.discover`` reads, so the name in the table and the name
    in the loaded project are one name. Otherwise the directory's own
    name, sanitized to something PEP 508 accepts (the ASCII gate is
    deliberate: ``str.isalnum`` alone is Unicode-aware and would let a
    non-ASCII character through into ``[project].name``).
    """
    project = document.get("project")
    if isinstance(project, dict):
        declared = project.get("name")
        if isinstance(declared, str) and declared.strip():
            return declared
    sanitized = "".join(
        ch if (ch.isascii() and ch.isalnum()) or ch in "._-" else "-"
        for ch in root.name
    ).strip("._-")
    return sanitized or "s0ma-app"


def _minimal_pyproject(project_name: str, table: str) -> str:
    """A whole ``pyproject.toml`` for a tree that has none.

    The same four keys ``s0ma new project`` writes for the same case, and
    ``requires-python`` matches the toolchain's own support floor because
    the project model reads it back for the 3.11-compatibility check.
    """
    return (
        "[project]\n"
        f'name = "{project_name}"\n'
        'version = "0.1.0"\n'
        'requires-python = ">=3.11"\n'
        "\n" + table
    )


def _agents_action(agents: Path) -> str:
    """Whether the block has to be created, appended, or is already there."""
    if not agents.is_file():
        return "created"
    try:
        existing = agents.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return "appended"
    return "unchanged" if AGENTS_BLOCK_BEGIN in existing else "appended"


def decide_test_roots(
    root: Path,
    source_roots: Sequence[str],
    test_directories: Sequence[str] = (),
) -> tuple[str, ...] | None:
    """Which directories this project's tests live in, for the table to declare.

    Three answers, matching :func:`render_table`'s three cases: a tuple of
    directories to write out, ``None`` to say nothing because the default
    already covers it, and ``()`` for the flat tree that has no room for a
    test root at all.

    The evidence, best first:

    1. ``[tool.pytest.ini_options].testpaths`` — the project saying where
       its tests are, in a file it wrote for its own reasons.
    2. *test_directories* — the top-level directories the test files
       ``adopt scan`` classified actually sit in.

    Anything overlapping a source root is dropped, because that is the
    pair the project loader refuses; a directory inside a source root is
    already covered by that root anyway. When what is left is exactly the
    default (``tests``), nothing is written — the default says it.

    Why this matters beyond tidiness: a test file under no declared test
    root is ``UNKNOWN`` to ``s0ma verify``, for ever, and the backlog the
    guide tells people to watch fall is then mostly test files that were
    never going to be converted.
    """
    from s0ma_dsl.project import DEFAULT_TEST_ROOTS

    if _swallows_default_test_root(root, source_roots):
        return ()

    declared = _pytest_testpaths(root)
    candidates = declared or tuple(dict.fromkeys(test_directories))
    kept = tuple(
        entry
        for entry in candidates
        if (root / entry).is_dir() and not _overlaps_sources(root, source_roots, entry)
    )
    if not kept or kept == tuple(DEFAULT_TEST_ROOTS):
        return None
    return kept


def _pytest_testpaths(root: Path) -> tuple[str, ...]:
    """``[tool.pytest.ini_options].testpaths``, normalised, or empty."""
    document = _read_pyproject_document(root / "pyproject.toml")
    tool = document.get("tool")
    pytest_table = tool.get("pytest") if isinstance(tool, dict) else None
    options = (
        pytest_table.get("ini_options") if isinstance(pytest_table, dict) else None
    )
    declared = options.get("testpaths") if isinstance(options, dict) else None
    if not isinstance(declared, list):
        return ()
    return tuple(
        dict.fromkeys(
            entry.strip().replace("\\", "/").strip("/")
            for entry in declared
            if isinstance(entry, str) and entry.strip().strip("./")
        )
    )


def _overlaps_sources(root: Path, source_roots: Sequence[str], entry: str) -> bool:
    """True when *entry* and any source root sit inside one another."""
    from s0ma_dsl.project import _detect_overlapping_roots

    sources = tuple((root / value).resolve() for value in source_roots)
    return bool(_detect_overlapping_roots(sources, ((root / entry).resolve(),)))


def _swallows_default_test_root(root: Path, source_roots: Sequence[str]) -> bool:
    """True when the declared source roots swallow the default test root.

    ``[tool.s0ma].test_roots`` defaults to ``tests``, and s0ma refuses a
    test root that sits inside a source root, so a tree whose code is the
    project directory itself needs the key written out as empty or it
    will not load at all. Asked of the project model's own detector
    rather than re-deciding what "inside" means here.
    """
    from s0ma_dsl.project import DEFAULT_TEST_ROOTS, _detect_overlapping_roots

    sources = tuple((root / entry).resolve() for entry in source_roots)
    tests = tuple((root / entry).resolve() for entry in DEFAULT_TEST_ROOTS)
    return any(
        kind == "source-test"
        for _, _, kind in _detect_overlapping_roots(sources, tests)
    )


def _restore(pyproject: Path, original: bytes | None) -> None:
    """Put ``pyproject.toml`` back exactly as it was, or remove what we made."""
    if original is None:
        pyproject.unlink(missing_ok=True)
        return
    pyproject.write_bytes(original)


def _load_refusal(exc: Exception, suggestion: PerimeterSuggestion) -> str:
    """One plain sentence for a perimeter the project loader would not take.

    Overlapping discovery roots is the one this meets in practice, and
    since the roots written are now exactly the roots decided before
    anything was discovered, the pair that overlaps is one somebody asked
    for — ``--source-root . --source-root src``, say. The loader's own
    words are carried through, because they name the pair; the sentence
    after them names what was being written and what to pass instead,
    because a refusal a reader cannot act on is only half a refusal.
    ``s0ma adopt scan`` says more about the same tree, in more words, and
    is one command away.
    """
    said = _loader_sentence(exc)
    proposed = ", ".join(f"`{entry}`" for entry in suggestion.source_roots)
    return (
        f"that perimeter does not load, so nothing was kept and "
        f"pyproject.toml is exactly as you left it. s0ma said: {said} It was "
        f"about to declare {proposed or 'no source roots'}; name source roots "
        f"that do not sit inside one another — `s0ma adopt init --source-root "
        f"<dir> --source-root <dir>`, one for each directory that holds code — "
        f"and run this again."
    )


def _loader_sentence(exc: Exception) -> str:
    """The loader's refusal, trimmed to its headline and the pairs it names.

    A project-load error opens with its code and the rule, then lists the
    offending pairs as ``  - `` bullets, then repeats advice aimed at
    somebody hand-editing the table. Only the first two parts are worth
    carrying: the third is replaced by advice aimed at somebody running
    this command.
    """
    lines = [line.strip() for line in str(exc).strip().splitlines()]
    if not lines:
        return f"{exc.__class__.__name__}."
    head = lines[0]
    bullets = [line.lstrip("- ").strip() for line in lines[1:] if line.startswith("-")]
    if bullets:
        return f"{head.rstrip(':')} — " + "; ".join(bullets) + "."
    return head if head.endswith(".") else f"{head}."


def _toml_list(values: Sequence[str]) -> str:
    """A TOML array of basic strings, on one line, in the order given."""
    return "[" + ", ".join(_toml_string(value) for value in values) + "]"


def _toml_string(value: str) -> str:
    """One TOML basic string, with the four escapes a path could need."""
    escaped = (
        value.replace("\\", "\\\\")
        .replace('"', '\\"')
        .replace("\n", "\\n")
        .replace("\t", "\\t")
    )
    return f'"{escaped}"'
