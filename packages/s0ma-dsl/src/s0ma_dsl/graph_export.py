"""The single graph-export mechanism for ``.s0ma.json`` artifacts.

``s0ma graph`` (text / json / dot) and every out-of-process consumer —
notably the studi0 viewer — read the component graph through this one
module. There is deliberately no parallel extraction path: studi0 never
opens IR JSON itself, it calls :func:`collect_graph` (studi0 plan §3.1,
scope note §1 "no duplicate mechanisms").

The JSON payload is versioned ``s0ma-graph@2`` (:data:`GRAPH_SCHEMA`). It
is a superset of the historical unversioned shape: ``nodes``,
``edges.authored`` and ``edges.derived`` keep their exact previous
content and ordering, and ``schema``, ``edges.verification`` and
``integrations`` are added at both detail levels. ``detail="full"`` adds
``components``, ``modules`` and — when a build manifest is found —
``freshness``.

Truth discipline:

- Component, module, edge and integration content is copied **verbatim**
  from the IR. Nothing is invented and no unknown field is dropped, so
  the canonical ``s0ma-ir@3`` state wrappers
  (``{"state": "value"|"none"|"pending", ...}``) on ``intent`` and on
  ``fields`` leaves survive into the payload. Consumers project them for
  display (see ``s0ma_dsl.cli.main._ir_semantic_value``); this module
  never flattens them, because the ``pending`` reason *is* the honest
  answer about authoring debt.
- Paths are project-relative POSIX, never absolute (INV-5).
- Output is deterministic: identical inputs produce an identical dict.
  Files are discovered in sorted order, new lists are sorted, and the
  payload carries no wall-clock time and no randomness.
"""

from __future__ import annotations

import contextlib
import json
import tomllib
from dataclasses import dataclass
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import TYPE_CHECKING, Any

from s0ma_dsl.adopt.model import BASELINE_FILENAME
from s0ma_dsl.adoption import ADOPTED_FILENAME
from s0ma_dsl.codegen.build_manifest import MANIFEST_FILENAME
from s0ma_dsl.discovery import iter_visible_files
from s0ma_dsl.ir.schema import validate_ir_schema_version

if TYPE_CHECKING:
    from s0ma_dsl.codegen.build_manifest import BuildManifest

__all__ = [
    "DETAIL_FULL",
    "DETAIL_LEVELS",
    "DETAIL_SUMMARY",
    "GRAPH_SCHEMA",
    "GraphExportError",
    "IRReadError",
    "NoIRArtifactsError",
    "collect_graph",
    "discover_ir_files",
]

#: Versioned schema string stamped on every payload.
GRAPH_SCHEMA = "s0ma-graph@2"

DETAIL_SUMMARY = "summary"
DETAIL_FULL = "full"

#: Accepted ``detail`` values, in increasing order of verbosity.
DETAIL_LEVELS = (DETAIL_SUMMARY, DETAIL_FULL)

#: The manifest ``freshness`` is derived from. Recorded in the payload so
#: a consumer can name its evidence without hard-coding the filename.
FRESHNESS_BASIS = "build.s0ma.json"


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class GraphExportError(Exception):
    """Base class for graph-aggregation failures."""


class NoIRArtifactsError(GraphExportError):
    """No ``.s0ma.json`` artifacts were found at the requested target.

    The CLI renders this as a usage error (exit code 2) — the same
    outcome the pre-extraction ``_cmd_graph`` produced.
    """


class IRReadError(GraphExportError):
    """An IR artifact could not be read or parsed.

    ``str()`` reproduces the CLI's historical wording verbatim so the
    thin command wrapper can print it unchanged.
    """

    def __init__(self, path: Path, cause: Exception) -> None:
        super().__init__(f"Error reading {path}: {cause}")
        self.path = path
        self.cause = cause


# ---------------------------------------------------------------------------
# Discovery
# ---------------------------------------------------------------------------

#: Reserved project ledgers that match ``*.s0ma.json`` but are not IR
#: documents (each carries its own schema, without ``schema_version``).
#:
#: Every name is imported from the module that writes the file rather
#: than spelled again here: a record the toolchain writes into a user's
#: tree and then refuses to read is the worst kind of first impression,
#: and that is exactly what happened when the retrofit's parity baseline
#: landed at the project root and `s0ma verify --all .` began failing
#: with ``UNSUPPORTED_IR_SCHEMA_MAJOR`` (pilot defect G2-2).
_RESERVED_LEDGERS = (
    MANIFEST_FILENAME,
    ADOPTED_FILENAME,
    BASELINE_FILENAME,
)


def discover_ir_files(target: Path) -> list[Path]:
    """Discover ``.s0ma.json`` files from a path.

    A file target resolves to itself; a directory target is walked
    recursively through :func:`s0ma_dsl.discovery.iter_visible_files`,
    so hidden and machine-owned subtrees (nested checkouts, caches) are
    pruned by the one canonical visibility rule. The reserved project
    ledgers — the build manifest (``build.s0ma.json``) and the adoption
    ledger (``adopted.s0ma.json``) — are not IR documents and are always
    excluded: both carry their own schemas without the canonical
    ``schema_version`` field, so feeding them to the IR schema guard
    hard-fails every consumer on any project that has adopted files.
    Results are sorted, which is what makes every downstream aggregation
    order deterministic.

    This is the one discovery implementation in the codebase —
    ``S0maCLI._discover_ir_files`` delegates here.
    """
    if target.is_file() and target.name.endswith(".s0ma.json"):
        return [target]
    if target.is_dir():
        return sorted(
            path
            for path in iter_visible_files(target, "*.s0ma.json")
            if path.name not in _RESERVED_LEDGERS
        )
    return []


@dataclass(frozen=True)
class _ScanContext:
    """Where to read IR, where to look for a manifest, what root to relativise against."""

    ir_root: Path
    manifest_dir: Path
    project_root: Path | None


def _has_tool_s0ma_table(pyproject: Path) -> bool:
    """True when *pyproject* parses and carries a ``[tool.s0ma]`` table."""
    try:
        with pyproject.open("rb") as handle:
            document = tomllib.load(handle)
    except (OSError, tomllib.TOMLDecodeError):
        # A malformed pyproject.toml is not this module's business to
        # diagnose (``s0ma doctor`` owns that). Treat the directory as a
        # plain directory of artifacts.
        return False
    tool = document.get("tool")
    return isinstance(tool, dict) and isinstance(tool.get("s0ma"), dict)


def _resolve_scan_context(target: Path) -> _ScanContext:
    """Decide what to scan for *target*.

    Three shapes are accepted (studi0 plan §3.1):

    1. A ``.s0ma.json`` file — scanned as itself; the manifest, if any,
       is looked up beside it.
    2. A **project root** — a directory whose ``pyproject.toml`` carries
       ``[tool.s0ma]``. The configured ``build_dir`` is resolved through
       :class:`s0ma_dsl.project.S0maProject` (the one project-config
       mechanism) and scanned; the project root anchors relative paths.
    3. Any other directory — scanned as-is, exactly as before.
    """
    if target.is_dir() and _has_tool_s0ma_table(target / "pyproject.toml"):
        from s0ma_dsl.errors import S0maProjectNotFound
        from s0ma_dsl.project import S0maProject

        try:
            project = S0maProject.discover(target)
        except (S0maProjectNotFound, ValueError, OSError):
            # A table that does not resolve (bad build_dir basename,
            # overlapping roots, …) is reported by `s0ma check` /
            # `s0ma doctor`. The read-only graph view degrades to
            # plain directory scanning rather than refusing to render.
            pass
        else:
            return _ScanContext(
                ir_root=project.build_dir,
                manifest_dir=project.build_dir,
                project_root=project.root,
            )

    if target.is_file():
        return _ScanContext(
            ir_root=target,
            manifest_dir=target.parent,
            project_root=None,
        )
    return _ScanContext(ir_root=target, manifest_dir=target, project_root=None)


# ---------------------------------------------------------------------------
# Path handling (INV-5: never an absolute machine path in a payload)
# ---------------------------------------------------------------------------


def _looks_absolute(raw: str) -> bool:
    """True for a path that is absolute on *either* OS.

    A manifest written on Linux can be read on Windows and vice versa
    (NFR-7), and each platform's :class:`~pathlib.Path` sees only its own
    absolute spellings — ``Path("/srv/app.s0ma").is_absolute()`` is
    ``False`` on Windows, ``Path("C:/app.s0ma").is_absolute()`` is
    ``False`` on POSIX. Checking both spellings keeps the INV-5
    guarantee (no absolute path in a payload) platform-independent.
    """
    if raw.startswith(("/", "\\")):
        return True
    return Path(raw).is_absolute() or PureWindowsPath(raw).drive != ""


def _basename(raw: str) -> str:
    """The final component of *raw* under either OS's separator rules."""
    return PureWindowsPath(PurePosixPath(raw).name).name


def _project_relative(raw: str, project_root: Path | None) -> str:
    """Render an IR-recorded source path as a relative POSIX string.

    Builds against a resolved ``[tool.s0ma]`` project already record
    project-root-relative POSIX paths (SH-M1); those pass through
    untouched. Absolute values — synthetic-fallback builds, pre-SH-M1
    artifacts — are made relative to *project_root* when they sit under
    it, and otherwise degrade to the bare filename. An absolute path is
    never emitted (INV-5).
    """
    if not raw:
        return ""
    path = Path(raw)
    if not _looks_absolute(raw):
        return path.as_posix()

    if project_root is not None:
        candidates = [path]
        roots = [project_root]
        # Compare both the recorded and the symlink-resolved spellings:
        # a build recorded under /tmp and a project root resolved to
        # /private/tmp describe the same file.
        with contextlib.suppress(OSError):  # pragma: no cover - defensive
            candidates.append(path.resolve())
        with contextlib.suppress(OSError):  # pragma: no cover - defensive
            roots.append(project_root.resolve())
        for candidate in candidates:
            for root in roots:
                try:
                    return candidate.relative_to(root).as_posix()
                except ValueError:
                    continue
    return _basename(raw)


def _component_location(raw: Any, source_file: str) -> dict[str, Any]:
    """Return the component's location with a project-relative ``file``.

    The IR's own keys (``start_line`` / ``end_line``) are preserved
    verbatim. ``file`` is added because the IR records the source path
    once per module, not per component, and ``line`` is the frozen
    payload contract's name for the declaration's first line.
    """
    location: dict[str, Any] = dict(raw) if isinstance(raw, dict) else {}
    location["file"] = source_file
    start_line = location.get("start_line")
    if isinstance(start_line, int):
        location["line"] = start_line
    return location


# ---------------------------------------------------------------------------
# Freshness
# ---------------------------------------------------------------------------


def _derive_project_root(manifest_dir: Path, manifest: BuildManifest) -> Path:
    """Best-effort project root for a build directory reached without a project.

    The manifest records ``build_dir`` as a project-root-relative POSIX
    string (SH-M1), so walking up that many components from the build
    directory recovers the root. Absolute or empty recordings (synthetic
    builds) fall back to the build directory itself.
    """
    recorded = Path(manifest.build_dir)
    if not manifest.build_dir or recorded.is_absolute():
        return manifest_dir
    root = manifest_dir
    for _ in recorded.parts:
        root = root.parent
    return root


def _collect_freshness(
    manifest_dir: Path, project_root: Path | None
) -> dict[str, Any] | None:
    """Compare recorded source hashes against the sources on disk.

    Returns ``None`` when no readable manifest is present — the payload
    then carries no ``freshness`` key at all (studi0 plan §3.2), and the
    consumer reports the build as ``missing``.

    When a manifest *is* found, ``status`` is:

    - ``fresh`` — every recorded module's source still hashes to the
      recorded value;
    - ``stale`` — at least one does not, and ``stale_modules`` names
      them. A recorded source that can no longer be read counts as
      stale: the build no longer corresponds to the tree, and claiming
      freshness we cannot verify would be the dishonest answer (this
      matches how ``s0ma doctor`` treats an orphaned module);
    - ``missing`` — the manifest records no modules at all, so nothing
      is built.

    Hashing goes through :func:`s0ma_dsl.codegen.build_manifest.compute_file_hash`
    — the same helper the manifest writer used — so the comparison can
    never drift from the recording.
    """
    from s0ma_dsl.codegen.build_manifest import (
        BuildManifest,
        ManifestSchemaError,
        compute_file_hash,
        load_manifest,
    )

    try:
        manifest = load_manifest(manifest_dir)
    except ManifestSchemaError:
        return None

    root = (
        project_root
        if project_root is not None
        else _derive_project_root(manifest_dir, manifest)
    )

    stale: list[str] = []
    for entry in manifest.modules:
        source = BuildManifest.resolve_source(entry, root)
        try:
            current = compute_file_hash(source.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError):
            # The recorded source is gone, unreadable, or no longer
            # decodable as UTF-8: the build no longer corresponds to the
            # tree. That is a staleness fact to report, not an exception
            # to raise out of a read-only viewer.
            stale.append(entry.name)
            continue
        if current != entry.source_hash:
            stale.append(entry.name)

    if not manifest.modules:
        status = "missing"
    elif stale:
        status = "stale"
    else:
        status = "fresh"

    return {
        "basis": FRESHNESS_BASIS,
        "manifest_found": True,
        "status": status,
        "stale_modules": sorted(stale),
        "transpiler_version": manifest.transpiler_version,
    }


# ---------------------------------------------------------------------------
# Aggregation
# ---------------------------------------------------------------------------


def _load_ir(path: Path) -> dict[str, Any]:
    """Read and schema-validate one IR document.

    Raises
    ------
    IRSchemaVersionError
        Propagated unchanged — the CLI reports it as a validation error.
    IRReadError
        For unreadable or malformed JSON; ``str()`` matches the CLI's
        historical message.
    """
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        raise IRReadError(path, exc) from exc
    if not isinstance(raw, dict):  # pragma: no cover - defensive
        raise IRReadError(path, TypeError("IR document is not a JSON object"))
    data: dict[str, Any] = raw
    validate_ir_schema_version(data)
    return data


def collect_graph(
    target: Path,
    *,
    detail: str = DETAIL_SUMMARY,
) -> dict[str, Any]:
    """Aggregate ``s0ma-graph@2`` data from ``.s0ma.json`` artifacts.

    *target* is a ``.s0ma.json`` file, a directory containing them, or a
    project root — a directory whose ``pyproject.toml`` carries
    ``[tool.s0ma]``, in which case the configured ``build_dir`` is
    resolved and scanned.

    *detail* is ``"summary"`` (default) or ``"full"``; ``"full"`` adds
    ``components``, ``modules`` and ``freshness``.

    Raises
    ------
    ValueError
        For an unknown *detail* level.
    NoIRArtifactsError
        When the target yields no IR artifacts.
    IRReadError
        When an artifact cannot be read or parsed.
    IRSchemaVersionError
        When an artifact's schema version is not supported — the same
        exception the CLI path has always raised.
    """
    if detail not in DETAIL_LEVELS:
        raise ValueError(
            f"Unknown graph detail level {detail!r}; "
            f"expected one of {', '.join(DETAIL_LEVELS)}."
        )

    context = _resolve_scan_context(target)
    ir_files = discover_ir_files(context.ir_root)
    if not ir_files:
        raise NoIRArtifactsError(f"No .s0ma.json files found at: {target}")

    nodes: set[str] = set()
    authored: list[dict[str, Any]] = []
    derived: list[dict[str, Any]] = []
    verification: list[dict[str, Any]] = []
    integrations: list[dict[str, Any]] = []
    components: dict[str, dict[str, Any]] = {}
    modules: dict[str, dict[str, Any]] = {}

    want_full = detail == DETAIL_FULL

    for ir_path in ir_files:
        data = _load_ir(ir_path)

        raw_module = data.get("module", {})
        module_block: dict[str, Any] = (
            raw_module if isinstance(raw_module, dict) else {}
        )
        module_name = str(module_block.get("name", ""))
        source_file = _project_relative(
            str(module_block.get("source_file", "")), context.project_root
        )

        module_components: list[str] = []
        for comp in data.get("components", []):
            canonical_id = comp.get("canonical_id", "")
            nodes.add(canonical_id)
            module_components.append(canonical_id)
            if not want_full:
                continue
            # Verbatim pass-through of every IRComponent field, plus the
            # two owning-module facts the node inspector needs (the IR
            # records them once per module, not per component).
            entry = dict(comp)
            entry["module"] = module_name
            entry["layer"] = module_block.get("layer")
            entry["location"] = _component_location(
                comp.get("location"), source_file
            )
            components[canonical_id] = entry

        edges = data.get("edges", {})
        authored.extend(edges.get("authored", []))
        derived.extend(edges.get("derived", []))
        verification.extend(edges.get("verification", []))
        integrations.extend(data.get("integrations", []))

        if want_full:
            existing = modules.get(module_name)
            merged = (
                list(existing["components"]) if existing is not None else []
            )
            merged.extend(module_components)
            modules[module_name] = {
                "name": module_name,
                "layer": module_block.get("layer"),
                "intent": module_block.get("intent"),
                "components": sorted(set(merged)),
            }

    graph: dict[str, Any] = {
        "schema": GRAPH_SCHEMA,
        "nodes": sorted(nodes),
        "edges": {
            # ``authored`` / ``derived`` keep their historical
            # discovery-order content byte-for-byte (the @1 shape is a
            # subset of @2). Ordering is deterministic because
            # ``discover_ir_files`` sorts. ``verification`` is new, so it
            # is sorted on its own natural key.
            "authored": authored,
            "derived": derived,
            "verification": sorted(
                verification,
                key=lambda edge: (
                    str(edge.get("test", "")),
                    str(edge.get("validates", "")),
                    str(edge.get("origin", "")),
                ),
            ),
        },
        "integrations": sorted(
            integrations,
            key=lambda integration: (
                str(integration.get("canonical_id", "")),
                str(integration.get("name", "")),
            ),
        ),
    }

    if want_full:
        graph["components"] = dict(sorted(components.items()))
        graph["modules"] = [modules[name] for name in sorted(modules)]
        freshness = _collect_freshness(
            context.manifest_dir, context.project_root
        )
        if freshness is not None:
            graph["freshness"] = freshness

    return graph
