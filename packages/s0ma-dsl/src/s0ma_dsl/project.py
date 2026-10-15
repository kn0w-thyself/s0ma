"""Declarative project model for s0ma-dsl tools.

Every CLI subcommand resolves a :class:`S0maProject` first and operates
against the resolved project. The project is rooted at the consumer's
``pyproject.toml`` and configured via a ``[tool.s0ma]`` table.

This module is the canonical answer to the question "where does the source
live, where does the build go, which ``.py`` files are bootstrap exceptions?"
for any consumer of the s0ma DSL toolchain.

PRD references: feedback-5.5 (output-layout incoherence), feedback-6 CRIT-3
(``s0ma test`` cannot find ``src/``), ADR-005 (project discovery).
"""

from __future__ import annotations

import ast
import re
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

from s0ma.decorators import component
from s0ma.types import ComponentKind, Layer

from s0ma_dsl.adoption_policy import AdoptionException, parse_exceptions

__all__ = [
    "S0maProject",
    "RunbookEnvVar",
    "DEFAULT_SOURCE_ROOTS",
    "DEFAULT_TEST_ROOTS",
    "DEFAULT_TEST_RUNNER",
    "DEFAULT_TEST_LAYERING",
    "DEFAULT_TEST_MODULE_NAME_PREFIX_BY_DIR",
    "SUPPORTED_TEST_RUNNERS",
    "SUPPORTED_ATTRIBUTE_BUDGETS",
    "SUPPORTED_TEST_LAYERINGS",
    "SUPPORTED_PROJECT_MODES",
    "SUPPORTED_AUTHORING",
    "DEFAULT_AUTHORING",
    "SUPPORTED_FIXTURE_FORMATS",
    "is_empty_package_marker",
    "_detect_overlapping_roots",
    "_default_build_dir",
    "_parse_requires_python",
]


# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------

DEFAULT_SOURCE_ROOTS: tuple[str, ...] = ("src",)
DEFAULT_TEST_ROOTS: tuple[str, ...] = ("tests",)
DEFAULT_TEST_RUNNER: str = "pytest"

# M15 (feedback 5–6) — declare the runner names this version recognises.
# Today only ``pytest`` is supported; the surface is forward-looking so a
# future milestone can add others without changing the project-discovery
# error path. The validator below references this set by name.
SUPPORTED_TEST_RUNNERS: frozenset[str] = frozenset({"pytest"})

# M18 (feedback 5–6) — supported budget shapes for
# ``[tool.s0ma.attribute_budgets]``. Each project picks a shape per
# namespace; the resolver enforces it across the project. See
# ``s0ma_dsl.resolver.dependency`` for the enforcement code path and
# ``docs/s0ma-dsl-spec-v0.13.0.md`` §4.13 for the project-config surface.
SUPPORTED_ATTRIBUTE_BUDGETS: frozenset[str] = frozenset({
    "exactly_one_per_page",
    "unique_in_project",
    "warn_on_duplicate",
})

# M-10 (POST-6) — supported values for ``[tool.s0ma].test_layering``.
# ``"strict"`` (default) preserves the existing cross-module layer
# reachability rule for every module, including test-context modules.
# ``"permissive"`` exempts test-context modules (those with ≥1 ``test``
# declaration) from the cross-layer check so a PRESENTATION test fixture
# can ``uses:`` an INFRASTRUCTURE service without firing
# ``CROSS_LAYER_DEPENDENCY``. Production modules (zero ``test``
# declarations) are unaffected under either value. See the validator
# code path in ``s0ma_dsl.resolver.dependency._check_cross_layer_dependencies``
# and spec §4.13 + §4.0.2 for the project-config surface.
DEFAULT_TEST_LAYERING: str = "strict"
SUPPORTED_TEST_LAYERINGS: frozenset[str] = frozenset({"strict", "permissive"})

# DSL-M3 (F-M1-2) — the project's declared strictness mode. ``[tool.s0ma].mode``
# was a documentation-only key until 0.8.0: ``s0ma new project`` wrote it but
# nothing read it back, so a project declaring ``mode = "strict"`` still
# checked/built in the CLI's built-in default unless every invocation passed
# ``--mode`` explicitly. This constant is the set the loader validates the key
# against; the CLI resolves the effective mode as ``--mode flag > table > the
# command's own built-in default`` (see ``s0ma_dsl.cli.main._resolve_mode``).
# The field is OPTIONAL — when the table omits it the value is ``None`` and the
# CLI falls through to each command's built-in default, preserving the
# pre-0.8.0 behaviour (``check`` defaults strict, ``build``/``transpile``/…
# default dev) exactly. Synthetic-fallback projects (no ``[tool.s0ma]`` table)
# always carry ``None`` for the same reason. The four values mirror
# ``s0ma_dsl.config.StrictnessMode``; an unrecognised value is a load-time
# error in the loader's existing style (named supported set + remediation).
SUPPORTED_PROJECT_MODES: frozenset[str] = frozenset(
    {"migration", "dev", "strict", "release"}
)

# STD-M4 (usability plan) — the project's authoring posture, read from
# ``[tool.s0ma].authoring``. ``"on"`` (the default when the key is
# absent) declares that components are authored as ``.s0ma`` through the
# ``s0ma-authoring`` MCP server; the server's ``project_status`` handshake
# asks the agent to confirm that discipline before writing code. ``"off"``
# opts the project out of the handshake (e.g. a library that has finished
# its s0ma authoring, or a project deliberately mixing in plain Python).
# Unlike ``mode`` the key is NOT optional-as-``None``: an absent key takes
# the documented default ``"on"`` so every project carries a definite
# posture. An unrecognised value is a load-time error in the loader's
# existing style (named supported set + remediation), the same shape as
# ``test_layering`` / ``mode``. ``s0ma new project`` writes the key for
# fresh projects (``"on"`` by default, ``"off"`` with ``--default-off``).
DEFAULT_AUTHORING: str = "on"
SUPPORTED_AUTHORING: frozenset[str] = frozenset({"on", "off"})

# M-14 (POST-10d) — opt-in flag for automatic test-module name prefixing
# by parent directory. Off by default. When ``True`` is set on the
# project's ``[tool.s0ma]`` table, the CLI helpers that load
# test-context modules under a configured ``test_roots`` directory
# treat the immediate parent directory of each test file as a name
# prefix when checking for ``MODULE_NAME_COLLISION``. The motivating
# case is a project with parallel test subdirs (e.g.
# ``tests/unit/foo.s0ma`` + ``tests/integration/foo.s0ma``) where the
# author wants both files to keep ``module foo`` declarations rather
# than hand-renaming to ``foo_unit`` / ``foo_integration``. The
# project-level invariant still ensures *effective* names are unique;
# the dir-prefix is the discriminator. See the helper
# :func:`S0maProject.effective_test_module_name` and the collision-
# check call sites in ``s0ma_dsl/cli/main.py`` `_cmd_check` /
# `_cmd_build`.
DEFAULT_TEST_MODULE_NAME_PREFIX_BY_DIR: bool = False

# M-18 (POST-12g, 0.16.0) — supported fixture-format values for
# ``[tool.s0ma].fixtures_format``. Each value names a validator
# applied to non-``.s0ma`` files under ``test_roots`` that match a
# configured glob:
#
# * ``"ndjson"`` — every line in the file is a single JSON document
#   (newline-delimited). Empty lines and trailing whitespace are
#   tolerated; every non-empty line MUST parse via ``json.loads``.
# * ``"json"`` — the file is a single JSON document (one top-level
#   value, validated via ``json.loads`` on the full text).
# * ``"yaml"`` — the file is a single YAML document (validated via
#   ``yaml.safe_load`` on the full text). Requires PyYAML (already a
#   transitive dependency of s0ma-core).
#
# Any other value raises a ``ValueError`` at project-load time so a
# typo cannot silently disable the check.
SUPPORTED_FIXTURE_FORMATS: frozenset[str] = frozenset({
    "ndjson", "json", "yaml",
})

# O1 (0.11.0, batch-01a) — the sub-keys a single ``[tool.s0ma.env.<NAME>]``
# subtable may declare. Any other key is a load-time error so a typo
# (``require`` for ``required``) cannot silently drop the contract.
_RUNBOOK_ENV_FIELDS: frozenset[str] = frozenset({"required", "fail_fast", "default"})


# ---------------------------------------------------------------------------
# RunbookEnvVar (O1, 0.11.0 batch-01a)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class RunbookEnvVar:
    """One declared environment variable in the project's ops runbook.

    O1 (0.11.0, batch-01a): authored under ``[tool.s0ma.env.<NAME>]`` in
    ``pyproject.toml``, one subtable per variable the built application
    reads from its environment. Carries only the *contract* — never a
    live value:

    * :attr:`required` — the app cannot run without it (default
      ``False``).
    * :attr:`fail_fast` — a missing/invalid value should abort at
      startup rather than surface on first use (default ``False``).
    * :attr:`default` — the fallback the app uses when the variable is
      unset (a committed, non-secret default; ``None`` when none is
      declared).

    Deliberately NOT a ``@component`` — this is a plain configuration
    value object hanging off :class:`S0maProject` (the registered
    component). Keeping it out of the framework census avoids the
    self-model count churn a decorated helper class would cause.
    """

    required: bool = False
    fail_fast: bool = False
    default: str | None = None


# ---------------------------------------------------------------------------
# S0maProject
# ---------------------------------------------------------------------------


@component(
    name="S0maDSL_S0maProject",
    kind=ComponentKind.MODEL,
    layer=Layer.FRAMEWORK,
    intent=(
        "Declarative project model resolved from [tool.s0ma] in pyproject.toml; canonical "
        "configuration entry point for every CLI subcommand."
    ),
    is_framework=True,
    idempotent=True,
)
@dataclass(frozen=True)
class S0maProject:
    """Resolved, validated project configuration.

    A ``S0maProject`` is produced by :meth:`S0maProject.discover`. Every
    field is absolute (``Path``) where applicable and every path is rooted
    at :attr:`root`. Construction does not require any path to exist on
    disk — discovery surfaces missing-path warnings rather than errors so
    that fresh consumer projects can be configured ahead of scaffolding.

    Authors should not construct this dataclass directly outside of tests;
    use :meth:`S0maProject.discover` so that the project root, defaults,
    and synthetic-fallback signalling stay consistent.
    """

    root: Path
    """Project root: directory containing the ``pyproject.toml`` (or the
    discovery ``start`` path when ``synthetic`` is True)."""

    project_name: str
    """Project name from ``[project].name`` in ``pyproject.toml``. When
    ``synthetic`` is True this is the basename of :attr:`root`."""

    source_roots: tuple[Path, ...]
    """Absolute directories holding ``.s0ma`` source modules. Default
    when ``[tool.s0ma]`` is empty: ``(root / "src",)``."""

    test_roots: tuple[Path, ...]
    """Absolute directories holding ``.s0ma`` test modules. Default when
    ``[tool.s0ma]`` is empty: ``(root / "tests",)``."""

    build_dir: Path
    """Absolute directory for transpiled build artifacts. Default when
    ``[tool.s0ma]`` is empty: ``root / "<project_name>_build"``."""

    bootstrap_files: tuple[Path, ...]
    """Absolute paths to plain-Python files that are intentional
    bootstrap exceptions and should not be flagged by drift / missing-IR
    checks. Authored explicitly in ``[tool.s0ma].bootstrap_files``."""

    package_markers: tuple[Path, ...] = field(default_factory=tuple)
    """Absolute paths to ``__init__.py``
    files that the author explicitly classifies as package markers.

    Mirrors :attr:`bootstrap_files` — authored under
    ``[tool.s0ma].package_markers`` as a list of relative paths,
    resolved to absolute paths at discovery time, surfaces missing
    on-disk paths as :attr:`warnings` rather than errors so a fresh
    project can declare entries before scaffolding.

    Most package markers do not need to be declared: ``s0ma verify``
    auto-classifies any ``__init__.py`` whose body is empty, whitespace
    only, or a single docstring as ``PACKAGE_MARKER`` via
    :func:`is_empty_package_marker`. The escape hatch exists for
    ``__init__.py`` files that carry ``__all__`` re-exports, imports,
    or any executable content the author wants acknowledged as a
    marker rather than reported as ``UNKNOWN``.

    A file appearing in BOTH ``bootstrap_files`` and
    ``package_markers`` is a load-time configuration error
    (``CONFLICTING_PACKAGE_DECLARATION``)."""

    test_runner: str = DEFAULT_TEST_RUNNER
    """The test runner this project uses, named once for the whole project.

    The transpiler uses it to decide what runner-specific stubs to emit
    (today: none — pytest discovers tests by function name). Default
    ``"pytest"``; ``"nose"`` or any other unsupported value is rejected at
    discovery time with a friendly error pointing back to the supported
    set."""

    attribute_budgets: dict[str, str] = field(default_factory=dict)
    """Project-level budgets for ``declares_attributes:`` namespaces.

    Authored under
    ``[tool.s0ma.attribute_budgets]``; maps a namespace
    (``landmark``, ``route``, ``css_class``) to one of the supported
    shapes (:data:`SUPPORTED_ATTRIBUTE_BUDGETS`). When this dict is
    empty, ``declares_attributes:`` is purely descriptive and no
    cross-component budget check fires. The resolver consults this
    dict via the project handle on every ``s0ma check`` /
    ``s0ma build`` invocation."""

    requires_python: tuple[str, ...] | None = None
    """The project's declared Python version
    floor, captured verbatim from ``[project].requires-python`` in
    ``pyproject.toml`` as a tuple of PEP 440-style specifier clauses.

    Examples of how the raw string maps to this tuple:

    * ``">=3.11"`` → ``(">=3.11",)``
    * ``">=3.11,<3.13"`` → ``(">=3.11", "<3.13")``
    * ``">=3.12"`` → ``(">=3.12",)``
    * field absent → ``None``

    The check time consumer of this field is the validator's
    ``PARSE_GRAMMAR_FORWARD_INCOMPAT`` pass — it fires only when the
    declared range *includes* 3.11 (the conservative trigger). A
    project pinned to ``>=3.12`` has opted in to PEP 701 nested-quote
    f-strings, PEP 695 type-parameter syntax, and the 3.12 walrus
    relaxation — the pass stays silent for those projects so the
    grammar surface is not over-policed. ``None`` (no field) also
    stays silent because the project has not declared an intent the
    transpiler can check against. See the validator code path in
    ``s0ma_dsl.semantic.validator._check_python_grammar_compat`` and
    the helpers in ``s0ma_dsl.semantic.python_compat``."""

    test_layering: Literal["strict", "permissive"] = "strict"
    """Cross-module layer-reachability stance
    for test-context modules.

    ``"strict"`` (default) — preserves the pre-0.16.0 behaviour:
    every module's ``uses:`` entries are checked against the
    cross-layer reachability matrix (spec §4.0.2) regardless of
    whether the module carries any ``test`` declarations. A
    PRESENTATION test module instantiating an INFRASTRUCTURE service
    fires ``CROSS_LAYER_DEPENDENCY`` exactly as a production module
    doing the same would.

    ``"permissive"`` — exempts modules that contain at least one
    ``test`` declaration from the cross-module layer check. The
    carve-out mirrors the M13 helper-access rule: "module with ≥1
    test declaration" is the trigger. Production modules (zero
    ``test`` declarations) still get the strict check, so this
    opt-in does not relax the rule for shipped code. Authored under
    ``[tool.s0ma].test_layering``.

    Any other string value raises ``ValueError`` at project-load
    time naming the supported set."""

    test_module_name_prefix_by_dir: bool = False
    """Whether to auto-prefix test modules by parent
    directory when checking for ``MODULE_NAME_COLLISION``.

    Default ``False`` — preserves the pre-0.16.0 behaviour: a file
    declaring ``module foo`` collides with any other file declaring
    ``module foo`` regardless of directory.

    Set to ``True`` to opt the project into a directory-aware
    collision-discriminator: when the colliding files both live
    under a configured ``test_roots`` directory, the immediate
    parent-directory name is treated as an implicit prefix
    (``tests/unit/foo.s0ma`` → effective name ``unit_foo``;
    ``tests/integration/foo.s0ma`` → effective name
    ``integration_foo``). The author can keep parallel
    ``module foo`` declarations across test subdirs without a
    hand-rename — the project-level invariant still ensures that
    *effective* names are unique. Production modules (under
    ``source_roots``) are unaffected by this flag; they continue to
    require unique declared names. Authored under
    ``[tool.s0ma].test_module_name_prefix_by_dir``."""

    fixtures_format: dict[str, str] | None = None
    """The expected format for non-``.s0ma`` test
    fixtures.

    Maps a filename glob (e.g. ``"*.jsonl"``, ``"*.yaml"``) to one of
    the supported format validators (:data:`SUPPORTED_FIXTURE_FORMATS`).
    Authored under ``[tool.s0ma].fixtures_format`` as a TOML inline
    or stand-alone table:

    .. code-block:: toml

        [tool.s0ma.fixtures_format]
        "*.jsonl" = "ndjson"
        "*.yaml" = "yaml"
        "*.json" = "json"

    When the field is set, ``s0ma check`` walks every configured
    ``test_roots`` directory looking for files that match each glob
    and validates them via the format-specific parser. Failures fire
    :data:`FIXTURE_FORMAT_INVALID` (warning in dev/migration, error
    in strict/release). Files that do not match any configured glob
    are ignored — fixtures stay opt-in.

    ``None`` (default — field absent under ``[tool.s0ma]``) skips
    the entire fixture-validation pass. An empty dict ``{}`` has the
    same effect as ``None`` (no globs configured), but a missing
    field is distinguished from an explicit empty mapping at the
    discovery layer so projects can express "I have no fixtures yet"
    distinctly from "I have not yet thought about fixtures".

    Unsupported values (``"yaml-stream"``, ``"toml"``, …) raise
    ``ValueError`` at project-load time naming
    :data:`SUPPORTED_FIXTURE_FORMATS`."""

    mode: Literal["migration", "dev", "strict", "release"] | None = None
    """The project's declared strictness mode, read from
    ``[tool.s0ma].mode``.

    ``None`` (the default — field absent under
    ``[tool.s0ma]``, or any synthetic-fallback project) means the project
    expresses no preference and every CLI subcommand uses its own built-in
    default mode.

    When set, this is the **default** mode for project-resolved CLI
    invocations: ``s0ma check`` / ``s0ma build`` / ``s0ma topo`` /
    ``s0ma migrate-layout`` / ``s0ma test`` and ``s0ma transpile`` consult
    it when ``--mode`` is omitted, so walking the dev→strict→release ramp
    is a one-line ``pyproject.toml`` change rather than a flag on every
    invocation. An explicit ``--mode`` on the command line always wins
    (``--mode flag > [tool.s0ma].mode > the command's built-in default``).
    The resolution lives in :func:`s0ma_dsl.cli.main._resolve_mode`.

    Authored under ``[tool.s0ma].mode`` as one of ``"migration"``,
    ``"dev"``, ``"strict"``, ``"release"`` (mirroring
    :class:`s0ma_dsl.config.StrictnessMode`). Any other value raises
    ``ValueError`` at project-load time naming the supported set, so a
    typo cannot silently select an unintended strictness. ``s0ma new
    project`` writes this key for fresh projects."""

    authoring: Literal["on", "off"] = "on"
    """The project's authoring posture, read from
    ``[tool.s0ma].authoring``.

    ``"on"`` (the default — and the value when the key is absent under
    ``[tool.s0ma]``) declares that this project's components are
    authored as ``.s0ma`` through the ``s0ma-authoring`` MCP server. The
    server's ``project_status`` tool reads this posture and, for an
    ``"on"`` project, returns a confirmation handshake in
    ``suggested_next_action`` asking the agent to confirm it will author
    components as ``.s0ma`` via the server before writing code.

    ``"off"`` opts the project out of that handshake — for a project
    that has finished its ``.s0ma`` authoring, or one deliberately
    mixing in plain Python where the agent should not be prompted.

    Unlike :attr:`mode`, this field is never ``None``: an absent key
    takes the documented default ``"on"`` so every resolved project
    (including synthetic fallbacks) carries a definite posture. Authored
    under ``[tool.s0ma].authoring`` as ``"on"`` or ``"off"``; any other
    value raises ``ValueError`` at project-load time naming the
    supported set (:data:`SUPPORTED_AUTHORING`), the same loud-error
    style as :attr:`test_layering` / :attr:`mode`. ``s0ma new project``
    writes this key for fresh projects (``"on"`` by default, ``"off"``
    with ``--default-off``)."""

    run_command: str | None = None
    """The command that runs the built
    application, verbatim as authored under ``[tool.s0ma].run_command``
    (e.g. ``"uv run myapp"``). Optional — ``None`` when the key is
    absent. Rendered into the ``s0ma://project/runbook`` resource and
    the ``project_status`` runtime section so an agent operating the app
    starts from the declared command rather than guessing."""

    health_command: str | None = None
    """The command that checks the running
    application's health, verbatim as authored under
    ``[tool.s0ma].health_command`` (e.g.
    ``"curl -fsS localhost:8080/health"``). Optional — ``None`` when the
    key is absent."""

    venv_path: str | None = None
    """Project-relative host virtual-environment path for ``verify-host``.

    The value is retained as authored so ordinary static project discovery
    never resolves or executes it. The explicit host-verification surface
    validates containment, selects the platform Python beneath the venv,
    and refuses missing/escaping paths without falling back to s0ma's own
    interpreter. An external interpreter must be supplied with ``--python``.
    """

    adoption_exempt: tuple[AdoptionException, ...] = field(default_factory=tuple)
    """Project-local adoption classifications.

    These entries enumerate intentional vendored/generated/data/bootstrap
    paths during authoring. They never waive a caller-pinned gate; only an
    explicit ``s0ma-adoption-policy@1`` invocation input can do that.
    """

    env: dict[str, RunbookEnvVar] = field(default_factory=dict)
    """The environment variables the built
    application reads, keyed by name, each carrying its
    :class:`RunbookEnvVar` contract (required / fail_fast / default).
    Authored as ``[tool.s0ma.env.<NAME>]`` subtables. Empty when no
    ``env`` table is declared. The runbook resource and
    ``project_status`` render the declared/required/missing-required
    summary from this mapping and the live process environment — names
    and contracts only, never live values."""

    state_paths: tuple[str, ...] = field(default_factory=tuple)
    """Project-relative paths (verbatim as
    authored under ``[tool.s0ma].state_paths``) that hold **runtime
    state** — data the running application produces and owns, NOT
    derivable from source. The load-bearing semantics: these paths must
    never be reverted, restored from a committed version, or regenerated
    — doing so destroys real data. This is the key the bench's
    git-revert-of-live-DB failure needs (agents treated committed state
    as the deliverable and reverted the live runtime store). Kept as the
    authored strings (not resolved to absolute paths) so the runbook
    renders portable, machine-independent text. Empty when absent."""

    runbook_notes: tuple[str, ...] = field(default_factory=tuple)
    """Free-form operational notes authored under
    ``[tool.s0ma].runbook_notes`` — either a single string (one note) or
    a list of strings (several). Normalised to a tuple of non-empty note
    lines; empty when absent. Rendered verbatim in the runbook's Notes
    section."""

    synthetic: bool = False
    """``True`` when the project was constructed via the legacy fallback
    (no ``[tool.s0ma]`` table found). Synthetic projects emit a
    one-line warning at CLI entry; their defaults are best-effort."""

    warnings: tuple[str, ...] = field(default_factory=tuple)
    """Non-fatal advisory messages produced during discovery (e.g.
    bootstrap files that do not exist on disk yet). The CLI surfaces
    these as one-line notices."""

    # ---- Construction ---------------------------------------------------

    @classmethod
    def discover(cls, start: Path | str) -> S0maProject:
        """Walk upward from *start* until a ``pyproject.toml`` containing
        a ``[tool.s0ma]`` table is found, parse it, and return the
        resolved project.

        Raises :class:`S0maProjectNotFound` when no ``pyproject.toml``
        with a ``[tool.s0ma]`` table is reachable from *start*. Callers
        that want the legacy fallback (synthetic project + warning)
        should call :meth:`synthetic_fallback` after catching the error.
        """
        # Local import — avoid module-import cycle with errors.py via
        # transitive imports through codegen.
        from s0ma_dsl.errors import S0maProjectNotFound

        start_path = Path(start).resolve()
        if start_path.is_file():
            start_path = start_path.parent

        for candidate in (start_path, *start_path.parents):
            pyproject = candidate / "pyproject.toml"
            if not pyproject.is_file():
                continue
            data = _read_pyproject(pyproject)
            tool_s0ma = data.get("tool", {}).get("s0ma")
            if tool_s0ma is None:
                # Keep walking — a higher-level pyproject.toml may carry
                # the [tool.s0ma] table even if a leaf one does not.
                continue
            project_name = (
                data.get("project", {}).get("name")
                or candidate.name
            )
            # M-12 (POST-8, 0.16.0): capture ``[project].requires-python``
            # so the validator can flag 3.12-only grammar when the project
            # is pinned to a range that still includes 3.11. The field is
            # optional under PEP 621; absence maps to ``None`` and the
            # compat check stays silent (conservative default).
            requires_python_raw = data.get("project", {}).get(
                "requires-python"
            )
            return cls._from_tool_s0ma(
                root=candidate,
                project_name=project_name,
                table=tool_s0ma,
                requires_python_raw=requires_python_raw,
            )

        raise S0maProjectNotFound(
            f"No [tool.s0ma] table found in any pyproject.toml on the "
            f"path from {start_path} to filesystem root.",
            start=start_path,
        )

    @classmethod
    def find_unused_tool_s0ma_table(cls, positional: Path | str) -> Path | None:
        """Return the ``pyproject.toml`` carrying a ``[tool.s0ma]`` table on
        the path from *positional* upward, or ``None`` if none is reachable.

        DSL-M4 (F-M0-1): ``s0ma build <project_dir>`` anchors discovery on
        the CWD, not on the positional argument. When that CWD-anchored
        :meth:`discover` fails but the *positional* path itself contains (or
        sits under) a ``[tool.s0ma]`` table, the synthetic-fallback warning
        names this file and suggests ``--project-root`` so the author is not
        left wondering why their configured ``build_dir`` was ignored. This
        is detection only — it does not change which project is resolved
        (that behaviour change is deferred per plan §1.5).
        """
        start_path = Path(positional).resolve()
        if start_path.is_file():
            start_path = start_path.parent
        for candidate in (start_path, *start_path.parents):
            pyproject = candidate / "pyproject.toml"
            if not pyproject.is_file():
                continue
            try:
                data = _read_pyproject(pyproject)
            except (OSError, tomllib.TOMLDecodeError):
                # A malformed pyproject is not our concern here — the
                # warning is best-effort; only flag a cleanly-parseable
                # table.
                return None
            if data.get("tool", {}).get("s0ma") is not None:
                return pyproject
        return None

    @classmethod
    def synthetic_fallback(
        cls,
        start: Path | str,
        *,
        project_name: str | None = None,
    ) -> S0maProject:
        """Build a best-effort synthetic project for the legacy
        explicit-mode invocation.

        Used by the CLI when ``S0maProject.discover`` raises and the user
        supplied explicit path / output args. The resulting project has
        ``synthetic=True``; callers must surface a one-line warning.
        """
        root = Path(start).resolve()
        if root.is_file():
            root = root.parent
        name = project_name or root.name
        return cls(
            root=root,
            project_name=name,
            source_roots=tuple((root / r).resolve() for r in DEFAULT_SOURCE_ROOTS),
            test_roots=tuple((root / r).resolve() for r in DEFAULT_TEST_ROOTS),
            build_dir=(root / f"{name}_build").resolve(),
            bootstrap_files=(),
            package_markers=(),
            test_runner=DEFAULT_TEST_RUNNER,
            attribute_budgets={},
            requires_python=None,
            test_layering=DEFAULT_TEST_LAYERING,  # type: ignore[arg-type]
            test_module_name_prefix_by_dir=DEFAULT_TEST_MODULE_NAME_PREFIX_BY_DIR,
            fixtures_format=None,
            mode=None,
            authoring=DEFAULT_AUTHORING,  # type: ignore[arg-type]
            adoption_exempt=(),
            synthetic=True,
            warnings=(),
        )

    # ---- Internal -------------------------------------------------------

    @classmethod
    def _from_tool_s0ma(
        cls,
        *,
        root: Path,
        project_name: str,
        table: dict[str, Any],
        requires_python_raw: Any = None,
    ) -> S0maProject:
        warnings: list[str] = []

        source_roots_raw = table.get("source_roots", list(DEFAULT_SOURCE_ROOTS))
        test_roots_raw = table.get("test_roots", list(DEFAULT_TEST_ROOTS))
        # G3 (feedback 5–6 cleanup): the default ``build_dir`` is
        # derived through :func:`_default_build_dir`, which sanitizes
        # non-identifier characters in ``project_name`` (hyphens,
        # dots, spaces) to underscores and raises
        # ``INVALID_PROJECT_NAME_FOR_BUILD_DIR`` for irrecoverable
        # shapes (digit-start, sanitized-to-empty). When the author
        # set ``build_dir`` explicitly we still validate that the
        # last path component (the importable basename) is a valid
        # Python identifier — the contract is the same whether the
        # value is derived or hand-authored: ``from <basename>
        # import <module>`` must be importable.
        build_dir_explicit = "build_dir" in table
        build_dir_raw = table.get("build_dir")
        bootstrap_raw = table.get("bootstrap_files", [])
        package_markers_raw = table.get("package_markers", [])
        test_runner_raw = table.get("test_runner", DEFAULT_TEST_RUNNER)

        _ensure_list_of_str("source_roots", source_roots_raw)
        _ensure_list_of_str("test_roots", test_roots_raw)
        if build_dir_explicit and not isinstance(build_dir_raw, str):
            raise _toml_type_error("build_dir", "string", build_dir_raw)
        _ensure_list_of_str("bootstrap_files", bootstrap_raw)
        _ensure_list_of_str("package_markers", package_markers_raw)
        if not isinstance(test_runner_raw, str):
            raise _toml_type_error("test_runner", "string", test_runner_raw)

        # G3 (feedback 5–6 cleanup): resolve the build-dir basename
        # contract. Default path: sanitize ``project_name`` via
        # :func:`_default_build_dir`. Explicit path: validate that
        # the last path component is a valid Python identifier (the
        # full path may include parent directories — ``out/foo_bar``
        # is fine, ``out/foo-bar`` is not, because ``foo-bar`` is the
        # importable token).
        if build_dir_explicit:
            assert isinstance(build_dir_raw, str)  # narrowed above
            basename = Path(build_dir_raw).name
            if not basename.isidentifier():
                raise ValueError(
                    f"INVALID_PROJECT_NAME_FOR_BUILD_DIR: explicit "
                    f"[tool.s0ma].build_dir = {build_dir_raw!r} resolves "
                    f"to basename {basename!r}, which is not a valid "
                    f"Python identifier. The build directory's last path "
                    f"component is the import token used by the runtime "
                    f"bridge (`from {basename} import <module>`); a "
                    f"non-identifier basename produces a silent "
                    f"ModuleNotFoundError at runtime. Set "
                    f"[tool.s0ma].build_dir to a path whose final "
                    f"component is a valid Python identifier (e.g. "
                    f"underscores instead of hyphens)."
                )
            build_dir_value = build_dir_raw
        else:
            build_dir_value = _default_build_dir(project_name)

        # M15 (feedback 5–6) — only ``pytest`` is supported in this
        # version. A friendly error names the supported set and the
        # remediation so the author can either correct the spelling or
        # pin the project to ``"pytest"`` explicitly.
        if test_runner_raw not in SUPPORTED_TEST_RUNNERS:
            supported = ", ".join(
                repr(r) for r in sorted(SUPPORTED_TEST_RUNNERS)
            )
            raise ValueError(
                f"[tool.s0ma].test_runner = {test_runner_raw!r} is not "
                f"supported. Only {supported} is supported in this "
                f"version of s0ma-dsl. Add 'pytest' to the project's "
                f"pyproject.toml and re-run."
            )

        source_roots = tuple((root / r).resolve() for r in source_roots_raw)
        test_roots = tuple((root / r).resolve() for r in test_roots_raw)

        # G2 (feedback 5–6 cleanup): pre-flight overlap detection. When
        # any source_root and test_root overlap (one is a subpath of
        # the other or they resolve to the same path), or when two
        # source_roots / two test_roots overlap, ``_discover_s0ma_files``
        # would walk the same files twice and the cross-module resolver
        # would register each ``module <name>`` declaration twice — the
        # user then sees an opaque ``MODULE_NAME_COLLISION`` against a
        # file colliding with itself. G2 surfaces this as a structural
        # configuration error at project-load time so the diagnostic
        # arrives before any subcommand runs. Silent dedup is rejected
        # on principles grounds (see plan G2: it would paper over the
        # misconfiguration so the author never learns the roots are
        # ambiguous, and a future tooling change that depends on root
        # semantics would silently break).
        overlaps = _detect_overlapping_roots(source_roots, test_roots)
        if overlaps:
            raise ValueError(_format_overlapping_roots_error(overlaps, root))

        build_dir = (root / build_dir_value).resolve()
        bootstrap_files = tuple(
            (root / b).resolve() for b in bootstrap_raw
        )
        package_markers = tuple(
            (root / p).resolve() for p in package_markers_raw
        )

        # G1 (feedback 5–6 cleanup): a file declared in BOTH
        # ``bootstrap_files`` and ``package_markers`` is a
        # mis-configuration — the two lists answer different questions
        # ("is this an intentional plain-Python entry point?" vs. "is
        # this a Python package marker?") and a single file cannot be
        # both. Fire ``CONFLICTING_PACKAGE_DECLARATION`` loudly at
        # project-load time so the author gets the diagnostic before
        # any subcommand runs. Error in every mode — silent no-op is
        # forbidden.
        bootstrap_set = set(bootstrap_files)
        conflicts = sorted(
            str(p) for p in package_markers if p in bootstrap_set
        )
        if conflicts:
            joined = "\n  - ".join(conflicts)
            raise ValueError(
                f"CONFLICTING_PACKAGE_DECLARATION: the following file(s) "
                f"appear in both [tool.s0ma].bootstrap_files and "
                f"[tool.s0ma].package_markers — declare each in exactly "
                f"one list:\n  - {joined}"
            )

        # Surface (but do not error on) bootstrap files that do not yet
        # exist. A fresh consumer project can declare them ahead of
        # scaffolding.
        for bf in bootstrap_files:
            if not bf.exists():
                warnings.append(
                    f"Declared bootstrap_file does not exist on disk: {bf}"
                )

        # G1 (feedback 5–6 cleanup): same not-yet-on-disk
        # accommodation for ``package_markers`` — declarative escape
        # hatch entries surface as warnings, not errors, so a project
        # can declare them ahead of scaffolding (mirroring
        # ``bootstrap_files``).
        for pm in package_markers:
            if not pm.exists():
                warnings.append(
                    f"Declared package_marker does not exist on disk: {pm}"
                )

        # M-10 (POST-6, 0.16.0): parse ``[tool.s0ma].test_layering``.
        # ``"strict"`` (default) preserves the pre-0.16.0 cross-module
        # layer-reachability behaviour for every module, including
        # test-context modules. ``"permissive"`` carves out modules
        # that contain at least one ``test`` declaration so a
        # PRESENTATION test fixture can instantiate an INFRASTRUCTURE
        # service without firing ``CROSS_LAYER_DEPENDENCY``.
        # Production modules (zero ``test`` declarations) still get
        # the strict check under either value — the opt-in does not
        # relax the rule for shipped code. Unknown values raise
        # ``ValueError`` at project-load time naming the supported set
        # so a typo cannot silently disable the carve-out.
        test_layering_raw = table.get("test_layering", DEFAULT_TEST_LAYERING)
        if not isinstance(test_layering_raw, str):
            raise _toml_type_error(
                "test_layering", "string", test_layering_raw,
            )
        if test_layering_raw not in SUPPORTED_TEST_LAYERINGS:
            supported = ", ".join(
                repr(s) for s in sorted(SUPPORTED_TEST_LAYERINGS)
            )
            raise ValueError(
                f"[tool.s0ma].test_layering = {test_layering_raw!r} is "
                f"not supported. Supported values: {supported}. "
                f"Default (when omitted) is 'strict' — every module's "
                f"`uses:` entries are checked against the cross-module "
                f"layer-reachability matrix (spec §4.0.2). Set to "
                f"'permissive' to exempt modules with at least one "
                f"`test` declaration from the check; production "
                f"modules remain strict regardless."
            )

        # DSL-M3 (F-M1-2): parse ``[tool.s0ma].mode``. Until 0.8.0 this
        # key was declarative-only — ``s0ma new project`` wrote it but
        # nothing read it back, so a project declaring ``mode = "strict"``
        # still ran in the CLI's built-in default mode unless every
        # invocation passed ``--mode``. The field is OPTIONAL: an absent
        # key leaves ``mode`` as ``None`` and the CLI falls through to each
        # command's built-in default (preserving the pre-0.8.0 behaviour
        # exactly — ``check`` strict, ``build``/``transpile``/… dev). When
        # present it becomes the default mode for project-resolved
        # invocations (an explicit ``--mode`` flag still wins). An
        # unrecognised value raises ``ValueError`` at load time naming the
        # supported set so a typo cannot silently select an unintended
        # strictness — the same loud-error style as ``test_layering`` /
        # ``test_runner`` above. The resolution precedence lives in
        # ``s0ma_dsl.cli.main._resolve_mode``.
        mode_raw = table.get("mode")
        mode_value: str | None
        if mode_raw is None:
            mode_value = None
        else:
            if not isinstance(mode_raw, str):
                raise _toml_type_error("mode", "string", mode_raw)
            if mode_raw not in SUPPORTED_PROJECT_MODES:
                supported = ", ".join(
                    repr(m) for m in sorted(SUPPORTED_PROJECT_MODES)
                )
                raise ValueError(
                    f"[tool.s0ma].mode = {mode_raw!r} is not a supported "
                    f"strictness mode. Supported values: {supported}. "
                    f"This key sets the default mode for project-resolved "
                    f"`s0ma check` / `s0ma build` invocations (the "
                    f"dev->strict->release ramp); an explicit `--mode` on "
                    f"the command line overrides it. Omit the key to use "
                    f"each command's built-in default."
                )
            mode_value = mode_raw

        # STD-M4 (usability plan): parse ``[tool.s0ma].authoring``. The
        # key declares whether components are authored as ``.s0ma`` via
        # the ``s0ma-authoring`` MCP server (``"on"`` — the handshake is
        # surfaced by the server's ``project_status`` tool) or not
        # (``"off"``). Unlike ``mode`` the key is NOT optional-as-``None``:
        # an absent key takes the documented default ``"on"`` so every
        # project carries a definite posture. An unrecognised value raises
        # ``ValueError`` at load time naming the supported set — the same
        # loud-error style as ``test_layering`` / ``mode`` above, so a
        # typo cannot silently flip the project's posture.
        authoring_raw = table.get("authoring", DEFAULT_AUTHORING)
        if not isinstance(authoring_raw, str):
            raise _toml_type_error("authoring", "string", authoring_raw)
        if authoring_raw not in SUPPORTED_AUTHORING:
            supported = ", ".join(repr(a) for a in sorted(SUPPORTED_AUTHORING))
            raise ValueError(
                f"[tool.s0ma].authoring = {authoring_raw!r} is not "
                f"supported. Supported values: {supported}. Default "
                f"(when omitted) is 'on' — this project's components are "
                f"authored as .s0ma via the s0ma-authoring MCP server, "
                f"and `project_status` asks the agent to confirm that "
                f"discipline before writing code. Set to 'off' to opt out "
                f"of the confirmation handshake."
            )

        # M-14 (POST-10d, 0.16.0): parse
        # ``[tool.s0ma].test_module_name_prefix_by_dir``. The flag opts
        # the project into directory-aware ``MODULE_NAME_COLLISION``
        # checking for test-context files: the immediate parent
        # directory of a test file becomes an implicit prefix on the
        # declared module name when the collision check runs. Default
        # ``False`` preserves the pre-0.16.0 behaviour. Authored as a
        # TOML boolean; any other type raises a friendly error so a
        # quoted "true" string cannot silently disable the carve-out.
        test_module_name_prefix_by_dir_raw = table.get(
            "test_module_name_prefix_by_dir",
            DEFAULT_TEST_MODULE_NAME_PREFIX_BY_DIR,
        )
        if not isinstance(test_module_name_prefix_by_dir_raw, bool):
            raise _toml_type_error(
                "test_module_name_prefix_by_dir",
                "bool",
                test_module_name_prefix_by_dir_raw,
            )

        # M18 (feedback 5–6): parse ``[tool.s0ma.attribute_budgets]``.
        # Each key is a namespace (matching the left-hand side of a
        # ``declares_attributes:`` entry); each value is one of the
        # supported budget shapes. Unknown shapes raise a friendly
        # error pointing at the supported set so a typo cannot silently
        # disable enforcement.
        attribute_budgets_raw = table.get("attribute_budgets", {})
        if not isinstance(attribute_budgets_raw, dict):
            raise _toml_type_error(
                "attribute_budgets", "table (mapping)", attribute_budgets_raw
            )
        attribute_budgets: dict[str, str] = {}
        for ns, shape in attribute_budgets_raw.items():
            if not isinstance(ns, str) or not ns:
                raise ValueError(
                    f"[tool.s0ma.attribute_budgets] keys must be non-empty "
                    f"strings; got {ns!r}."
                )
            if not isinstance(shape, str):
                raise ValueError(
                    f"[tool.s0ma.attribute_budgets].{ns} must be a string; "
                    f"got {type(shape).__name__}: {shape!r}."
                )
            if shape not in SUPPORTED_ATTRIBUTE_BUDGETS:
                supported = ", ".join(
                    repr(s) for s in sorted(SUPPORTED_ATTRIBUTE_BUDGETS)
                )
                raise ValueError(
                    f"[tool.s0ma.attribute_budgets].{ns} = {shape!r} is "
                    f"not a supported budget shape. Supported shapes: "
                    f"{supported}."
                )
            attribute_budgets[ns] = shape

        # M-12 (POST-8, 0.16.0): parse ``[project].requires-python``
        # into a tuple of PEP 440-style specifier clauses. The field
        # comes from the standard PEP 621 ``[project]`` table — not
        # from ``[tool.s0ma]`` — and is forwarded into the discovery
        # path via the keyword argument. A non-string value is a
        # malformed pyproject.toml; surface a friendly error so the
        # author gets a precise diagnostic instead of an opaque
        # downstream traceback.
        requires_python = _parse_requires_python(requires_python_raw)

        # M-18 (POST-12g, 0.16.0): parse
        # ``[tool.s0ma.fixtures_format]``. Maps a filename glob
        # (``"*.jsonl"``) to a supported validator name
        # (:data:`SUPPORTED_FIXTURE_FORMATS`). The field is optional —
        # an absent table leaves ``fixtures_format`` as ``None`` and
        # the entire fixture-validation pass is skipped. An empty
        # mapping is preserved as an empty dict (distinct from
        # absent — the project is opting in to "I have no globs
        # configured yet" rather than "I have not thought about
        # fixtures"). Unknown format values raise ``ValueError`` at
        # load time naming the supported set so a typo cannot
        # silently disable the check.
        fixtures_format_raw = table.get("fixtures_format")
        fixtures_format: dict[str, str] | None
        if fixtures_format_raw is None:
            fixtures_format = None
        else:
            if not isinstance(fixtures_format_raw, dict):
                raise _toml_type_error(
                    "fixtures_format",
                    "table (mapping)",
                    fixtures_format_raw,
                )
            fixtures_format = {}
            for glob, fmt in fixtures_format_raw.items():
                if not isinstance(glob, str) or not glob:
                    raise ValueError(
                        f"[tool.s0ma.fixtures_format] keys must be "
                        f"non-empty filename globs; got {glob!r}."
                    )
                if not isinstance(fmt, str):
                    raise ValueError(
                        f"[tool.s0ma.fixtures_format].{glob} must be a "
                        f"string naming a supported format; got "
                        f"{type(fmt).__name__}: {fmt!r}."
                    )
                if fmt not in SUPPORTED_FIXTURE_FORMATS:
                    supported = ", ".join(
                        repr(s) for s in sorted(SUPPORTED_FIXTURE_FORMATS)
                    )
                    raise ValueError(
                        f"[tool.s0ma.fixtures_format].{glob} = {fmt!r} "
                        f"is not a supported fixture format. Supported "
                        f"formats: {supported}."
                    )
                fixtures_format[glob] = fmt

        # O1 (0.11.0, batch-01a): the ops runbook keys, all OPTIONAL. An
        # absent key leaves the project with no runbook and the
        # ``s0ma://project/runbook`` resource then serves the teaching
        # variant (what to declare, where). ``state_paths`` in particular
        # marks runtime state that is NOT derivable from source and must
        # never be reverted or regenerated — the ground the bench's
        # git-revert-of-live-DB failure needs taught. Every shape error is
        # a load-time ``ValueError`` in the existing ``[tool.s0ma]`` style
        # so a typo cannot silently disable an ops contract.
        run_command = _parse_optional_str(table, "run_command")
        health_command = _parse_optional_str(table, "health_command")
        venv_path = _parse_optional_str(table, "venv_path")
        state_paths_raw = table.get("state_paths", [])
        _ensure_list_of_str("state_paths", state_paths_raw)
        state_paths = tuple(state_paths_raw)
        runbook_notes = _parse_runbook_notes(table.get("runbook_notes"))
        env = _parse_runbook_env(table.get("env"))
        adoption_exempt_raw = table.get("adoption_exempt", [])
        try:
            adoption_exempt = parse_exceptions(
                adoption_exempt_raw,
                source="[tool.s0ma].adoption_exempt",
            )
        except ValueError as exc:
            raise ValueError(str(exc)) from exc

        return cls(
            root=root,
            project_name=project_name,
            source_roots=source_roots,
            test_roots=test_roots,
            build_dir=build_dir,
            bootstrap_files=bootstrap_files,
            package_markers=package_markers,
            test_runner=test_runner_raw,
            attribute_budgets=attribute_budgets,
            requires_python=requires_python,
            test_layering=test_layering_raw,  # type: ignore[arg-type]
            test_module_name_prefix_by_dir=test_module_name_prefix_by_dir_raw,
            fixtures_format=fixtures_format,
            mode=mode_value,  # type: ignore[arg-type]
            authoring=authoring_raw,  # type: ignore[arg-type]
            run_command=run_command,
            health_command=health_command,
            venv_path=venv_path,
            adoption_exempt=adoption_exempt,
            env=env,
            state_paths=state_paths,
            runbook_notes=runbook_notes,
            synthetic=False,
            warnings=tuple(warnings),
        )

    # ---- M-14 (POST-10d) — effective module name helper ----------------

    def is_under_test_roots(self, path: Path) -> bool:
        """Return ``True`` iff *path* is under any configured test root.

        Used by the ``MODULE_NAME_COLLISION`` checker (CLI ``_cmd_check``
        / ``_cmd_build``) to decide whether the new
        ``test_module_name_prefix_by_dir`` flag applies. Production
        modules under ``source_roots`` always use their declared name
        verbatim; only test-context modules participate in the
        directory-aware discriminator.
        """
        target = path.resolve()
        for root in self.test_roots:
            try:
                target.relative_to(root.resolve())
                return True
            except ValueError:
                continue
        return False

    def effective_module_name(
        self,
        declared_name: str,
        path: Path,
    ) -> str:
        """Compute the effective module name used for collision checks.

        Returns the declared name verbatim when
        :attr:`test_module_name_prefix_by_dir` is ``False`` or when
        *path* is not under any configured test root. Otherwise
        returns ``"<parent_dir>_<declared_name>"`` so two test files
        named ``foo.s0ma`` in different subdirs of ``tests/`` do not
        collide. Identifier safety: parent-dir segments with
        non-identifier characters are sanitized to underscores (the
        same shape :func:`_default_build_dir` applies to project
        names).
        """
        if not self.test_module_name_prefix_by_dir:
            return declared_name
        if not self.is_under_test_roots(path):
            return declared_name
        parent = path.resolve().parent.name
        # Strip non-identifier characters the same way
        # ``_default_build_dir`` does for project names. An empty
        # parent stem (top-level test file) skips the prefix.
        prefix = re.sub(r"\W", "_", parent) if parent else ""
        if not prefix or not prefix.isidentifier():
            return declared_name
        return f"{prefix}_{declared_name}"

    def health_echo(self) -> str:
        """Render the one-line post-build health nudge (0.13.0 M4).

        Ship-without-running was the common thread of batch-01c's worst
        outcomes (a green build, no runtime probe, a service left down), so
        a green build now points the author at the way to verify it. When a
        verification command is declared under ``[tool.s0ma]`` — preferring
        :attr:`health_command`, falling back to :attr:`run_command` (O1,
        0.11.0) — this returns ``"verify: <command>"``; when neither is
        declared it returns the not-a-fault nudge to declare one (worded in
        the 0.12.0 M1 style so an absent command never reads as an error).
        The single canonical source of the echo wording — the CLI's
        ``build`` summary and the MCP ``build_project`` result both render
        it from here so the two surfaces can never drift.
        """
        command = self.health_command or self.run_command
        if command:
            return f"verify: {command}"
        return (
            "no health_command declared — declare one in [tool.s0ma] "
            "so builds can point at it"
        )


# ---------------------------------------------------------------------------
# Package-marker auto-detection (G1, feedback 5–6 cleanup)
# ---------------------------------------------------------------------------


@component(
    name="S0maDSL_is_empty_package_marker",
    kind=ComponentKind.FUNCTION,
    layer=Layer.FRAMEWORK,
    intent=(
        "Structurally classify an __init__.py as an empty package marker "
        "(empty/whitespace/single-docstring body) by AST inspection."
    ),
    is_framework=True,
    idempotent=True,
)
def is_empty_package_marker(path: Path) -> bool:
    """Return ``True`` iff *path* is an empty Python package marker.

    G1 (feedback 5–6 cleanup): a Python package marker is an
    ``__init__.py`` whose body carries no executable content. The
    canonical shapes are:

    * Empty file (zero bytes / whitespace only).
    * Single module-level string literal (a docstring).

    Both shapes are *definitionally* package markers under Python's
    own conventions — a directory with such an ``__init__.py``
    becomes an importable package without contributing any runtime
    behaviour. ``s0ma verify`` auto-classifies them as
    ``PACKAGE_MARKER`` so consumers do not have to enumerate every
    package layer under ``[tool.s0ma].bootstrap_files``.

    The check is structural, not size-based: a long but non-executable
    docstring is still a package marker; a one-byte assignment is not.
    Any executable content — imports, ``__all__``, assignments, calls,
    classes, functions — disqualifies the file.

    Returns ``False`` (without raising) for paths that:

    * Do not have stem ``__init__`` and suffix ``.py``.
    * Cannot be read as UTF-8 text (binary file masquerading as ``.py``).
    * Cannot be parsed by :func:`ast.parse` (syntax error).

    The conservative default ("when in doubt, not a marker") keeps
    real-but-broken ``__init__.py`` files surfacing as ``UNKNOWN`` so
    they get the remediation message rather than being silently
    classified as harmless.
    """
    if path.stem != "__init__" or path.suffix != ".py":
        return False
    try:
        source = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return False
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return False
    body = tree.body
    if not body:
        # Empty / whitespace-only file.
        return True
    if len(body) != 1:
        return False
    stmt = body[0]
    # Single module-level docstring: an ``Expr`` wrapping a ``Constant``
    # whose value is a string.
    return bool(
        isinstance(stmt, ast.Expr)
        and isinstance(stmt.value, ast.Constant)
        and isinstance(stmt.value.value, str)
    )


# ---------------------------------------------------------------------------
# Overlap detection (G2, feedback 5–6 cleanup)
# ---------------------------------------------------------------------------


@component(
    name="S0maDSL_detect_overlapping_roots",
    kind=ComponentKind.FUNCTION,
    layer=Layer.FRAMEWORK,
    intent=(
        "Detect structural overlaps between resolved source_roots and test_roots — identical "
        "paths, source nested under source, source nested under test, or vice versa."
    ),
    is_framework=True,
    idempotent=True,
)
def _detect_overlapping_roots(
    source_roots: tuple[Path, ...],
    test_roots: tuple[Path, ...],
) -> list[tuple[Path, Path, str]]:
    """Return every overlapping pair across ``source_roots`` / ``test_roots``.

    G2 (feedback 5–6 cleanup): two declared discovery roots overlap
    when one resolves to a subpath of the other, or when they resolve
    to the same path. Either shape causes ``_discover_s0ma_files`` to
    walk the same ``.s0ma`` files from both anchors, which makes the
    cross-module resolver register each ``module <name>`` twice and
    the user then sees an opaque ``MODULE_NAME_COLLISION`` against a
    file colliding with itself.

    The returned triples are ``(root_a, root_b, kind)`` where ``kind``
    is one of:

    * ``"source-source"`` — two distinct ``source_roots`` overlap;
    * ``"test-test"`` — two distinct ``test_roots`` overlap;
    * ``"source-test"`` — a ``source_root`` and a ``test_root``
      overlap (in either nesting direction, or identically).

    The ordering inside each pair is normalised so that ``root_a`` is
    the *enclosing* (or equal) path and ``root_b`` is the *enclosed*
    one — except for the same-kind cases where the lists' declaration
    order is preserved for diagnostics. Identity (the same resolved
    path appearing in two roots — e.g. ``source_roots`` and
    ``test_roots`` both list ``"src"``) is treated as overlap; the
    diagnostic message handles equality and proper-nesting uniformly.

    Inputs are expected to be already absolute (each entry has been
    passed through ``Path.resolve()`` by ``_from_tool_s0ma``); the
    detector does not call ``.resolve()`` itself so symlinks /
    relative-path resolution stays the caller's responsibility.

    Returns an empty list when every pair across the union of
    ``source_roots`` and ``test_roots`` is disjoint.
    """
    overlaps: list[tuple[Path, Path, str]] = []

    # Same-list pairs: source-source and test-test overlap. Walk the
    # upper triangle (i < j) so each unordered pair surfaces exactly
    # once. The list-internal index ordering is preserved so the
    # diagnostic message names the pair in the order the author wrote
    # them.
    for kind, roots in (("source-source", source_roots), ("test-test", test_roots)):
        for i in range(len(roots)):
            for j in range(i + 1, len(roots)):
                a, b = roots[i], roots[j]
                if _paths_overlap(a, b):
                    overlaps.append((a, b, kind))

    # Cross-list pairs: every source_root × every test_root.
    for s in source_roots:
        for t in test_roots:
            if _paths_overlap(s, t):
                overlaps.append((s, t, "source-test"))

    return overlaps


def _paths_overlap(a: Path, b: Path) -> bool:
    """Return ``True`` iff *a* and *b* overlap (equal, or one nests under the other)."""
    if a == b:
        return True
    return a.is_relative_to(b) or b.is_relative_to(a)


def _render_root_for_diagnostic(path: Path, project_root: Path) -> str:
    """Render a discovery root for the overlapping-roots diagnostic.

    W-2 (Windows plan): relative paths in user-facing diagnostics are
    POSIX-rendered (``/``) on every OS — the root is echoed back the
    way the author wrote it in ``[tool.s0ma]`` (a ``/``-separated path
    relative to the project root). A root that resolves outside the
    project root (e.g. ``../shared/src``) falls back to its native
    absolute rendering, which W-2 keeps platform-native.
    """
    if path == project_root:
        return "."
    if path.is_relative_to(project_root):
        return path.relative_to(project_root).as_posix()
    return str(path)


def _format_overlapping_roots_error(
    overlaps: list[tuple[Path, Path, str]],
    project_root: Path,
) -> str:
    """Build the ``OVERLAPPING_DISCOVERY_ROOTS`` diagnostic message.

    G2 (feedback 5–6 cleanup): the message names every offending pair
    and proposes the two clean-config options. Putting the formatting
    in its own helper keeps the message shape stable (the doc-
    consistency / test pins reach in here for the exact prose).
    Roots inside the project render relative + POSIX (W-2; see
    ``_render_root_for_diagnostic``).
    """
    pair_lines: list[str] = []
    for a, b, kind in overlaps:
        a_repr = _render_root_for_diagnostic(a, project_root)
        b_repr = _render_root_for_diagnostic(b, project_root)
        if a == b:
            pair_lines.append(
                f"  - {kind}: `{a_repr}` is declared in both lists (identical path)"
            )
        elif b.is_relative_to(a):
            pair_lines.append(
                f"  - {kind}: `{b_repr}` is nested under `{a_repr}`"
            )
        else:
            # a is nested under b (the only remaining shape).
            pair_lines.append(
                f"  - {kind}: `{a_repr}` is nested under `{b_repr}`"
            )
    pairs = "\n".join(pair_lines)
    return (
        "OVERLAPPING_DISCOVERY_ROOTS: [tool.s0ma].source_roots and "
        "[tool.s0ma].test_roots must be disjoint — no root may be a "
        "subpath of another, and no two roots of the same kind may "
        "overlap. The following overlap(s) were detected:\n"
        f"{pairs}\n"
        "Overlapping roots cause every .s0ma file under the nested "
        "path to be discovered twice and collide with itself. Choose "
        "one of:\n"
        "  1. Move tests outside the source root: "
        "test_roots = [\"tests\"]\n"
        "  2. Narrow source_roots to disjoint layer subdirectories: "
        "source_roots = [\"src/<proj>/application\", "
        "\"src/<proj>/domain\", \"src/<proj>/presentation\"]"
    )


# ---------------------------------------------------------------------------
# Default-build-dir derivation (G3, feedback 5–6 cleanup)
# ---------------------------------------------------------------------------


@component(
    name="S0maDSL_default_build_dir",
    kind=ComponentKind.FUNCTION,
    layer=Layer.FRAMEWORK,
    intent=(
        "Derive the default build_dir basename from a project name; sanitize non-identifier "
        "characters, raise INVALID_PROJECT_NAME_FOR_BUILD_DIR for irrecoverable shapes."
    ),
    is_framework=True,
    idempotent=True,
)
def _default_build_dir(project_name: str) -> str:
    """Return the default ``[tool.s0ma].build_dir`` value for *project_name*.

    G3 (feedback 5–6 cleanup): the M6a build-dir contract is that
    ``s0ma build`` writes ``<build_dir>/<module>.py`` and the runtime
    bridge imports via ``from <build_dir_basename> import <module>``.
    The basename therefore MUST be a valid Python identifier. The
    pre-G3 derivation was the literal ``f"{project_name}_build"``,
    which silently produced an un-importable directory whenever
    ``project_name`` contained a hyphen, dot, space, or any other
    non-word character (the kn0wthyself-website-2 shape that hit
    M20 finding #5: `[project].name = "kn0wthyself-website-2"` →
    ``kn0wthyself-website-2_build/``, transpile succeeds, runtime
    bridge fails with ``ModuleNotFoundError`` only when consumers
    wire it up).

    G3 splits the failure modes into:

    * **Recoverable**: hyphens, dots, spaces, exclamation marks —
      every non-word character (``\\W``) sanitizes to ``_``. The
      result is a valid identifier; the build directory is
      importable. Common: ``foo-bar`` → ``foo_bar_build``,
      ``foo.bar`` → ``foo_bar_build``, ``foo bar`` →
      ``foo_bar_build``.
    * **Irrecoverable**: name starts with a digit (``123foo``), or
      the sanitization produces an empty string (``""``, which is
      defensive — ``[project].name`` is required by PEP 621 and
      always non-empty in practice). Underscoring does not help
      either case, so the helper raises ``ValueError`` whose message
      starts ``INVALID_PROJECT_NAME_FOR_BUILD_DIR:`` and instructs
      the author to set ``[tool.s0ma].build_dir`` explicitly to a
      valid Python identifier.

    Edge case: a single underscore (``_``) is a valid Python
    identifier and sanitizes to itself; the helper returns
    ``"__build"``. Unusual but accepted — the author can always
    override with an explicit ``build_dir``.
    """
    sanitized = re.sub(r"\W", "_", project_name)
    if not sanitized.isidentifier():
        raise ValueError(
            f"INVALID_PROJECT_NAME_FOR_BUILD_DIR: cannot derive a valid "
            f"Python-importable build_dir from project name "
            f"{project_name!r} (sanitized to {sanitized!r}, which is "
            f"not a valid Python identifier — names that start with a "
            f"digit, or that sanitize to the empty string, cannot be "
            f"recovered by the underscore substitution rule). The "
            f"build directory's last path component is the import "
            f"token used by the runtime bridge "
            f"(`from <build_dir_basename> import <module>`); a "
            f"non-identifier basename produces a silent "
            f"ModuleNotFoundError at runtime. Set "
            f"[tool.s0ma].build_dir explicitly to a valid Python "
            f"identifier (e.g. an underscored form prefixed with a "
            f"letter)."
        )
    return f"{sanitized}_build"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _read_pyproject(path: Path) -> dict[str, Any]:
    """Parse a ``pyproject.toml`` with the stdlib ``tomllib`` parser."""
    with path.open("rb") as fh:
        return tomllib.load(fh)


def _ensure_list_of_str(key: str, value: Any) -> None:
    """Validate that *value* is a list of strings."""
    if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
        raise _toml_type_error(key, "list of strings", value)


def _toml_type_error(key: str, expected: str, actual: Any) -> ValueError:
    """Build a uniform error for malformed ``[tool.s0ma]`` values."""
    return ValueError(
        f"[tool.s0ma].{key} must be a {expected}; got {type(actual).__name__}: {actual!r}"
    )


# ---------------------------------------------------------------------------
# Runbook-key parsing (O1, 0.11.0 batch-01a)
# ---------------------------------------------------------------------------


def _parse_optional_str(table: dict[str, Any], key: str) -> str | None:
    """Return ``table[key]`` as a string, or ``None`` when the key is absent.

    O1 (0.11.0): the runbook's ``run_command`` / ``health_command`` keys
    are optional single strings. A present-but-non-string value is a
    load-time error in the standard ``[tool.s0ma]`` style so a typo (e.g.
    a TOML array where a string was meant) cannot silently disable the
    field.
    """
    value = table.get(key)
    if value is None:
        return None
    if not isinstance(value, str):
        raise _toml_type_error(key, "string", value)
    return value


def _parse_runbook_notes(raw: Any) -> tuple[str, ...]:
    """Normalise ``[tool.s0ma].runbook_notes`` to a tuple of note lines.

    O1 (0.11.0): accepts either a single string (one note) or a list of
    strings (several), the friendly either/or shape TOML authors expect
    for free-form prose. Whitespace-only entries are dropped and an
    absent key yields an empty tuple. A non-string / non-list value, or a
    list carrying a non-string entry, is a load-time error naming the
    accepted shapes.
    """
    if raw is None:
        return ()
    if isinstance(raw, str):
        stripped = raw.strip()
        return (stripped,) if stripped else ()
    if isinstance(raw, list):
        notes: list[str] = []
        for entry in raw:
            if not isinstance(entry, str):
                raise _toml_type_error(
                    "runbook_notes", "string or list of strings", raw
                )
            stripped = entry.strip()
            if stripped:
                notes.append(stripped)
        return tuple(notes)
    raise _toml_type_error("runbook_notes", "string or list of strings", raw)


def _parse_runbook_env(raw: Any) -> dict[str, RunbookEnvVar]:
    """Parse ``[tool.s0ma.env]`` into a ``name -> RunbookEnvVar`` mapping.

    O1 (0.11.0): each ``[tool.s0ma.env.<NAME>]`` subtable declares one
    environment variable the built application reads — ``required``
    (bool, default false), ``fail_fast`` (bool, default false — abort at
    startup rather than on first use when the value is missing), and an
    optional ``default`` string. An absent ``env`` table yields an empty
    mapping. Every shape error (non-table value, unknown sub-key,
    non-bool flag, non-string default) is a load-time error naming the
    accepted set so a typo cannot silently drop an env contract.
    """
    if raw is None:
        return {}
    if not isinstance(raw, dict):
        raise _toml_type_error("env", "table (mapping)", raw)
    env: dict[str, RunbookEnvVar] = {}
    for name, spec in raw.items():
        if not isinstance(name, str) or not name:
            raise ValueError(
                f"[tool.s0ma.env] keys must be non-empty environment "
                f"variable names; got {name!r}."
            )
        if not isinstance(spec, dict):
            raise ValueError(
                f"[tool.s0ma.env.{name}] must be a table declaring the "
                f"variable's contract (required / fail_fast / default); "
                f"got {type(spec).__name__}: {spec!r}."
            )
        unknown = sorted(set(spec) - _RUNBOOK_ENV_FIELDS)
        if unknown:
            supported = ", ".join(sorted(_RUNBOOK_ENV_FIELDS))
            raise ValueError(
                f"[tool.s0ma.env.{name}] has unsupported key(s) "
                f"{', '.join(unknown)}; supported: {supported}."
            )
        required = spec.get("required", False)
        fail_fast = spec.get("fail_fast", False)
        default = spec.get("default")
        if not isinstance(required, bool):
            raise _toml_type_error(f"env.{name}.required", "bool", required)
        if not isinstance(fail_fast, bool):
            raise _toml_type_error(f"env.{name}.fail_fast", "bool", fail_fast)
        if default is not None and not isinstance(default, str):
            raise _toml_type_error(f"env.{name}.default", "string", default)
        env[name] = RunbookEnvVar(
            required=required, fail_fast=fail_fast, default=default
        )
    return env


# ---------------------------------------------------------------------------
# requires-python parsing (M-12, POST-8)
# ---------------------------------------------------------------------------


def _parse_requires_python(raw: Any) -> tuple[str, ...] | None:
    """Parse ``[project].requires-python`` into a tuple of clauses.

    M-12 (POST-8, 0.16.0): PEP 621 declares ``requires-python`` as a
    single PEP 440 version specifier string (e.g. ``">=3.11"``,
    ``">=3.11,<3.13"``, ``"~=3.12"``). The string is comma-separated
    in the multi-clause form. This helper splits on the comma and
    strips whitespace so the validator can iterate clauses without
    re-parsing.

    Returns ``None`` for an absent field (the caller should not fire
    the compat check). Raises ``ValueError`` for malformed values
    (non-string, empty after stripping) — the diagnostic identifies
    ``[project].requires-python`` so the author can fix the
    pyproject.toml directly.
    """
    if raw is None:
        return None
    if not isinstance(raw, str):
        raise ValueError(
            f"[project].requires-python must be a string; got "
            f"{type(raw).__name__}: {raw!r}. PEP 621 requires this "
            f"field to be a PEP 440 version specifier (e.g. '>=3.11', "
            f"'>=3.11,<3.13')."
        )
    stripped = raw.strip()
    if not stripped:
        # Empty string is malformed — same status as a non-string
        # value. Surface a friendly diagnostic rather than silently
        # treating it as absent.
        raise ValueError(
            "[project].requires-python is an empty string; either "
            "delete the field (= no Python version floor declared) "
            "or set it to a PEP 440 version specifier (e.g. '>=3.11')."
        )
    parts = tuple(p.strip() for p in stripped.split(",") if p.strip())
    if not parts:
        # All-whitespace clauses split out to nothing — the same
        # malformed shape as an empty string. Surface the diagnostic.
        raise ValueError(
            "[project].requires-python contains only whitespace / "
            "empty clauses; supply at least one PEP 440 specifier "
            "(e.g. '>=3.11')."
        )
    return parts
