"""The frozen data model of the ``s0ma adopt`` retrofit family.

Every mechanism in the retrofit ladder — scan, init, draft, baseline,
verify-parity, status — meets here. This module is pure data: no file
I/O, no ``ast``, no project resolution, no imports from the rest of
``s0ma_dsl``. That is deliberate. The scanner, the harvester, the
surface reader and the parity comparer are written by separate hands
and land at different times; a shared, dependency-free vocabulary is
what lets them agree without reading each other's code.

House rules these types obey
----------------------------

* ``@dataclass(frozen=True, slots=True)`` — a record that has been
  measured must not be edited afterwards, and ``slots`` keeps the
  census cheap on a large tree (a scan holds one record per file).
* **Tuples, never lists.** Sequence fields are ordered, hashable and
  final. Every field's docstring says what the order *means* (source
  order, sorted, leaf-first), because a later milestone's golden file
  depends on it.
* **No defaults.** Every field is supplied at construction. An omitted
  field would be a silent zero in a report someone is about to make a
  conversion decision from.
* **Explicit** :meth:`to_dict` **on every type, never**
  :func:`dataclasses.asdict`. ``asdict`` deep-copies, recurses into
  types it does not own, and hides the tuple-to-list choice this
  module makes on purpose. Hand-written dumps are the only way the
  JSON shape stays reviewable.
* Plain JSON types out: ``str``, ``int``, ``float``, ``bool``, ``None``,
  ``list``, ``dict``. Tuples become lists; pairs become two-item lists;
  nested records become dicts. Keys are sorted at dump time by
  :func:`dump_json`, so :meth:`to_dict` may list them in reading order.
* Paths are **project-relative and POSIX** (``Path.as_posix()``) in
  every field that carries one. Nothing in this model may hold an
  absolute machine path, a wall-clock time, or a backslash separator:
  scan reports and baseline files are committed artifacts that have to
  be byte-identical on macOS, Linux and Windows.

Where each type comes from
--------------------------

The scan vocabulary (:class:`SourceFile` through :class:`ScanReport`)
is frozen by the retrofit plan's §5.2. The draft, surface, parity and
status records are derived from the task text of the milestones that
consume them and are frozen into §5.2 at the A1 gate.

Consumers: ``adopt/discovery.py``, ``adopt/census.py``, ``adopt/graph.py``,
``adopt/proposals.py``, ``adopt/report.py``, ``adopt/harvest.py``,
``adopt/draft_emit.py``, ``adopt/surface.py``, ``adopt/parity.py``,
``adopt/status.py`` and the ``s0ma adopt`` CLI handlers.

The per-file adoption record store (``s0ma_dsl/adoption.py``,
``s0ma-adopted-files@1``) is a different, older family and is not
touched by this module.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Mapping

__all__ = [
    # Schema constants and the canonical dump helper.
    "SCAN_SCHEMA",
    "BASELINE_SCHEMA",
    "BASELINE_FILENAME",
    "DRAFT_INTENT_MARKER",
    "DRAFT_UNPLACED_MARKER",
    "dump_json",
    # Rung 0 — assess (scan).
    "SourceFile",
    "EntityFact",
    "ImportFact",
    "ModuleCensus",
    "GraphFacts",
    "Proposal",
    "PerimeterSuggestion",
    "EffortEstimate",
    "ScanWarning",
    "ScanReport",
    # Rung 3 — convert (draft).
    "DraftDeclaration",
    "DraftUnplaced",
    "DraftModule",
    # Rung 3 — convert (parity).
    "SurfaceEntry",
    "ModuleSurface",
    "ParityFinding",
    "ParityResult",
    # Across the ladder — status.
    "LadderStatus",
]


# ---------------------------------------------------------------------------
# Schema constants
#
# Versioning rule for both schema strings, inherited from the
# ``build.s0ma.json`` / ``adopted.s0ma.json`` family: **additive fields
# ride the same ``@1`` string**. A reader that does not know a new field
# ignores it and keeps working. ``@2`` is reserved for a breaking change
# — a removed field, a renamed field, or a changed meaning for an
# existing one — and a reader that meets an unknown major must refuse
# with the migration path named, never guess.
# ---------------------------------------------------------------------------

SCAN_SCHEMA = "s0ma-adopt-scan@1"
"""Canonical schema string for a ``s0ma adopt scan --format json`` report.

Additive fields ride ``@1``; ``@2`` is a breaking change. The scan
report is printed to stdout and never written to disk (retrofit rule
R-2, zero-write reads), so the version travels with the document
rather than with a file on the tree.
"""

BASELINE_SCHEMA = "s0ma-adopt-baseline@1"
"""Canonical schema string for the committed parity-baseline record.

Additive fields ride ``@1``; ``@2`` is a breaking change. Unlike the
scan report this document is *durable* — it is captured before a Python
file is deleted and read back long afterwards — so a reader meeting an
unknown major refuses rather than comparing against a shape it does not
understand.
"""

BASELINE_FILENAME = "adopt-baseline.s0ma.json"
"""On-disk filename for the parity baselines, at the project root.

One file for the whole project (retrofit rule R-3), beside
``pyproject.toml`` and ``adopted.s0ma.json``, in the established
``<name>.s0ma.json`` family: committed, diffable, deterministic.
"""

DRAFT_INTENT_MARKER = "FIXME(adopt):"
"""Prefix that marks un-authored meaning in a generated draft.

``s0ma adopt draft`` derives structure and never invents meaning
(retrofit ruling D-3). Every field it cannot derive is emitted as
``FIXME(adopt): <what to write here, in plain words>``. The
``ADOPT_PLACEHOLDER_INTENT`` diagnostic matches this prefix and is an
error in *every* mode (ruling R-5), so a project cannot build green
with a placeholder still in it.

Part of the ``@1`` contract: the draft emitter writes this text and the
checker matches it, so changing the spelling is a breaking change.
"""

DRAFT_UNPLACED_MARKER = "adopt: unplaced"
"""Marker that labels source the harvester could not place in a declaration.

Nothing in a converted module is allowed to go missing. Source text
that is neither a declaration body nor a header fact is carried into
the draft under this marker, with its original line range and a plain
reason, and the ``ADOPT_UNPLACED_CODE`` diagnostic then refuses the
build until a person has placed it.

Part of the ``@1`` contract, like :data:`DRAFT_INTENT_MARKER`.
"""


# ---------------------------------------------------------------------------
# Canonical JSON
# ---------------------------------------------------------------------------


def dump_json(obj: object) -> str:
    """Render *obj* as the retrofit family's canonical JSON text.

    *obj* must already be plain JSON types — call :meth:`to_dict` on a
    record first. The settings are the whole point and are shared by
    every artifact this family writes or prints:

    * ``sort_keys=True`` — key order never depends on construction
      order, so two runs of the same scan diff empty.
    * ``indent=2`` — reviewable in a pull request.
    * ``ensure_ascii=False`` — a name with an accent in it stays
      readable instead of turning into ``\\uXXXX`` escapes.
    * a single trailing newline — the POSIX convention every other
      ``<name>.s0ma.json`` in the project follows.

    Callers write the result with ``encoding="utf-8"`` and
    ``newline="\\n"``.
    """
    return json.dumps(obj, sort_keys=True, indent=2, ensure_ascii=False) + "\n"


def _string_pairs(items: tuple[tuple[str, str], ...]) -> list[list[str]]:
    """Render a tuple of string pairs as JSON two-item lists, order kept."""
    return [[left, right] for left, right in items]


def _count_pairs(items: tuple[tuple[str, int], ...]) -> list[list[Any]]:
    """Render a tuple of (name, count) pairs as JSON two-item lists."""
    return [[name, count] for name, count in items]


# ---------------------------------------------------------------------------
# Rung 0 — assess: what is in the tree
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class SourceFile:
    """One Python file discovered in the project tree.

    * ``path`` — project-relative POSIX path of the file.
    * ``module`` — the dotted module name the file would import as.
    * ``source_root`` — project-relative POSIX path of the source root
      the file was found under (``"."`` for a flat tree).
    * ``role`` — ``"app"`` (application code, the conversion target),
      ``"test"``, ``"script"`` or ``"package_marker"`` (an ``__init__.py``
      that only marks a package).
    """

    path: str
    module: str
    source_root: str
    role: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "path": self.path,
            "module": self.module,
            "source_root": self.source_root,
            "role": self.role,
        }


@dataclass(frozen=True, slots=True)
class EntityFact:
    """One top-level definition found in a module, read statically.

    "Public" follows core's own definition (``import_hook``'s
    ``_get_unregistered_entities``) so the scan's numbers agree with
    what the runtime would say about the same tree.

    * ``name`` — the defined name as written.
    * ``category`` — ``"function"``, ``"async_function"``, ``"class"``
      or ``"constant"``.
    * ``line`` — 1-based line of the ``def``/``class``/assignment.
    * ``public`` — visible on the module's public surface.
    * ``kind_hint`` — the component kind this entity would most likely
      become (``"MODEL"``, ``"SERVICE"``, ``"CONSTANT"``, …), guessed
      from shape alone; a hint, never a decision.
    * ``decorators`` — decorator expressions as written, source order.
    * ``bases`` — base-class expressions as written, source order;
      empty for anything that is not a class.
    * ``has_docstring`` — the definition carries a docstring.
    * ``registered`` — the definition already carries a s0ma
      ``@component``/``@internal`` decorator (rung 2, registered in
      place); its authored meaning is real and must be carried forward,
      not replaced by a placeholder.
    """

    name: str
    category: str
    line: int
    public: bool
    kind_hint: str
    decorators: tuple[str, ...]
    bases: tuple[str, ...]
    has_docstring: bool
    registered: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "category": self.category,
            "line": self.line,
            "public": self.public,
            "kind_hint": self.kind_hint,
            "decorators": list(self.decorators),
            "bases": list(self.bases),
            "has_docstring": self.has_docstring,
            "registered": self.registered,
        }


@dataclass(frozen=True, slots=True)
class ImportFact:
    """One import statement in a module, with where and how it runs.

    * ``module`` — the dotted import target as written, with relative
      forms (``from . import x``) already resolved to absolute.
    * ``names`` — the names bound by the statement, source order;
      empty for a plain ``import x``.
    * ``line`` — 1-based line of the statement.
    * ``deferred`` — the import sits inside a function or method, so it
      does not run at module load.
    * ``type_checking`` — the import sits under ``if TYPE_CHECKING:``
      and never runs at all.
    * ``origin`` — ``"stdlib"``, ``"first_party"`` (another module in
      this project), ``"third_party"`` or ``"unresolved"``.
    """

    module: str
    names: tuple[str, ...]
    line: int
    deferred: bool
    type_checking: bool
    origin: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "module": self.module,
            "names": list(self.names),
            "line": self.line,
            "deferred": self.deferred,
            "type_checking": self.type_checking,
            "origin": self.origin,
        }


@dataclass(frozen=True, slots=True)
class ModuleCensus:
    """Everything one file tells a static reader, in one record.

    * ``source`` — the discovered file this census describes.
    * ``lines`` — total physical lines in the file.
    * ``sloc`` — lines that are neither blank nor comment-only.
    * ``entities`` — top-level definitions, source order.
    * ``imports`` — import statements, source order.
    * ``dunder_all`` — the literal ``__all__`` as written, source
      order; ``None`` when the module declares none (which is not the
      same as declaring an empty one).
    * ``has_main_guard`` — the file carries an
      ``if __name__ == "__main__":`` block.
    * ``top_level_effects`` — count of top-level statements that are
      not an import, a definition, a constant assignment, the module
      docstring, ``__all__`` or the main guard. Anything above zero is
      work the conversion has to place by hand.
    * ``parse_error`` — one plain sentence when the file could not be
      parsed; ``None`` when it parsed. A census with a parse error
      carries empty ``entities``/``imports`` rather than partial ones.
    * ``content_hash`` — ``"sha256:<hex>"`` over the file's UTF-8 text,
      the same convention as ``adoption.compute_adopted_hash`` (text-mode
      reading, so a CRLF checkout does not read as drift).
    """

    source: SourceFile
    lines: int
    sloc: int
    entities: tuple[EntityFact, ...]
    imports: tuple[ImportFact, ...]
    dunder_all: tuple[str, ...] | None
    has_main_guard: bool
    top_level_effects: int
    parse_error: str | None
    content_hash: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "source": self.source.to_dict(),
            "lines": self.lines,
            "sloc": self.sloc,
            "entities": [entity.to_dict() for entity in self.entities],
            "imports": [record.to_dict() for record in self.imports],
            "dunder_all": None if self.dunder_all is None else list(self.dunder_all),
            "has_main_guard": self.has_main_guard,
            "top_level_effects": self.top_level_effects,
            "parse_error": self.parse_error,
            "content_hash": self.content_hash,
        }


@dataclass(frozen=True, slots=True)
class GraphFacts:
    """The project's first-party import graph, and the order it implies.

    Only first-party edges are carried: the question the graph answers
    is "which of my own modules must I convert first", and stdlib or
    third-party targets never move.

    * ``edges`` — ``(importer, imported)`` pairs that run at module
      load, sorted.
    * ``deferred_edges`` — the same shape for function-scoped imports,
      sorted. They are the escape hatch a cycle usually hides behind.
    * ``cycles`` — each cycle's members, each cycle sorted internally,
      the outer tuple sorted.
    * ``order`` — every module, leaf-first: a module appears after
      everything it imports at load time. Members of one cycle are
      adjacent and in alphabetical order, because nothing can break the
      tie honestly.
    * ``fan_in`` — ``(module, count)`` pairs: how many modules import
      this one. High fan-in means converting it late is expensive.
    * ``fan_out`` — ``(module, count)`` pairs: how many modules this one
      imports. High fan-out means it cannot be converted early.
    """

    edges: tuple[tuple[str, str], ...]
    deferred_edges: tuple[tuple[str, str], ...]
    cycles: tuple[tuple[str, ...], ...]
    order: tuple[str, ...]
    fan_in: tuple[tuple[str, int], ...]
    fan_out: tuple[tuple[str, int], ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "edges": _string_pairs(self.edges),
            "deferred_edges": _string_pairs(self.deferred_edges),
            "cycles": [list(cycle) for cycle in self.cycles],
            "order": list(self.order),
            "fan_in": _count_pairs(self.fan_in),
            "fan_out": _count_pairs(self.fan_out),
        }


@dataclass(frozen=True, slots=True)
class Proposal:
    """What the scan suggests for one module, and why it says so.

    A proposal is advice with its reasoning attached, never a decision:
    the layer a module belongs in is an authored judgement.

    * ``module`` — the dotted module the proposal is about.
    * ``layer`` — the suggested layer name; ``None`` when the evidence
      does not point anywhere and the author must choose.
    * ``confidence`` — ``"low"``, ``"medium"`` or ``"high"``. Only
      ``"high"`` is written into a draft unasked.
    * ``reasons`` — one plain sentence per piece of evidence, in the
      order they were weighed. A proposal with no reasons is a guess
      and must not be shown.
    * ``kind_mix`` — ``(kind, count)`` pairs of the component kinds the
      module's entities look like, sorted by kind.
    """

    module: str
    layer: str | None
    confidence: str
    reasons: tuple[str, ...]
    kind_mix: tuple[tuple[str, int], ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "module": self.module,
            "layer": self.layer,
            "confidence": self.confidence,
            "reasons": list(self.reasons),
            "kind_mix": _count_pairs(self.kind_mix),
        }


@dataclass(frozen=True, slots=True)
class PerimeterSuggestion:
    """The ``[tool.s0ma]`` settings ``s0ma adopt init`` would write.

    Rung 1 makes the tree a s0ma project without touching a line of
    application code. This record is what that would look like, so a
    person can read it before anything is written.

    * ``source_roots`` — project-relative POSIX directories to declare
      as source roots, in the order they should be written.
    * ``bootstrap_files`` — project-relative POSIX paths to declare as
      bootstrap (hand-written and exempt), sorted.
    * ``package_markers`` — project-relative POSIX paths of
      ``__init__.py`` files that only mark a package, sorted.
    * ``mode`` — the strictness mode to start in. Always
      ``"migration"``: a tree that has not converted anything yet
      cannot honestly claim more.
    * ``notes`` — plain sentences about anything the reader should
      decide rather than accept.
    """

    source_roots: tuple[str, ...]
    bootstrap_files: tuple[str, ...]
    package_markers: tuple[str, ...]
    mode: str
    notes: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_roots": list(self.source_roots),
            "bootstrap_files": list(self.bootstrap_files),
            "package_markers": list(self.package_markers),
            "mode": self.mode,
            "notes": list(self.notes),
        }


@dataclass(frozen=True, slots=True)
class EffortEstimate:
    """How much work the conversion looks like, in bands rather than hours.

    * ``bands`` — ``(band, count)`` pairs for ``"small"``, ``"medium"``
      and ``"large"``, in that order. All three are always present,
      including zeroes, so a report never has to explain a gap.
    * ``per_module`` — ``(module, band)`` pairs, sorted by module.
    * ``basis`` — one sentence saying what the bands are measured from,
      printed with the estimate so nobody reads it as a schedule.
    """

    bands: tuple[tuple[str, int], ...]
    per_module: tuple[tuple[str, str], ...]
    basis: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "bands": _count_pairs(self.bands),
            "per_module": _string_pairs(self.per_module),
            "basis": self.basis,
        }


@dataclass(frozen=True, slots=True)
class ScanWarning:
    """Something the scan noticed that a person should know about.

    These are report-only strings carried in the report, not raised
    diagnostics: a scan reads and never refuses.

    * ``code`` — the warning's code, e.g. ``"ADOPT_SCAN_PARSE_ERROR"``,
      ``"ADOPT_SCAN_CYCLE"``, ``"ADOPT_SCAN_NAME_COLLISION"``,
      ``"ADOPT_SCAN_DYNAMIC_EXPORTS"``.
    * ``module`` — the dotted module it is about; ``None`` when it is
      about the project as a whole.
    * ``message`` — one plain sentence, written for someone who has not
      read the guide, that says what was found and what to do.
    """

    code: str
    module: str | None
    message: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "module": self.module,
            "message": self.message,
        }


@dataclass(frozen=True, slots=True)
class ScanReport:
    """The whole of what ``s0ma adopt scan`` found — rung 0's deliverable.

    Built by reading files and nothing else: the scan never imports the
    project, never executes it, and writes nothing anywhere (retrofit
    rules R-1 and R-2). The report is printed, not saved.

    * ``schema`` — :data:`SCAN_SCHEMA`.
    * ``project`` — ``has_s0ma_config`` (bool), ``mode`` (str or None)
      and ``name`` (str or None): what the tree already declares.
    * ``summary`` — the headline counts, name to integer.
    * ``modules`` — one census per discovered file, sorted by path.
    * ``graph`` — the first-party import graph and its leaf-first order.
    * ``proposals`` — one per application module, in ``graph.order``.
    * ``perimeter`` — the ``[tool.s0ma]`` settings ``adopt init`` would
      write.
    * ``effort`` — the conversion-size bands.
    * ``classification`` — verify-class counts (``ADOPTED``,
      ``UNKNOWN``, …) when the tree already is a s0ma project;
      ``None`` when there is no ``[tool.s0ma]`` yet to classify against.
    * ``warnings`` — everything worth saying that is not a refusal.
    """

    schema: str
    project: Mapping[str, object]
    summary: Mapping[str, int]
    modules: tuple[ModuleCensus, ...]
    graph: GraphFacts
    proposals: tuple[Proposal, ...]
    perimeter: PerimeterSuggestion
    effort: EffortEstimate
    classification: Mapping[str, int] | None
    warnings: tuple[ScanWarning, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "project": dict(self.project),
            "summary": dict(self.summary),
            "modules": [census.to_dict() for census in self.modules],
            "graph": self.graph.to_dict(),
            "proposals": [proposal.to_dict() for proposal in self.proposals],
            "perimeter": self.perimeter.to_dict(),
            "effort": self.effort.to_dict(),
            "classification": None if self.classification is None else dict(self.classification),
            "warnings": [warning.to_dict() for warning in self.warnings],
        }


# ---------------------------------------------------------------------------
# Rung 3 — convert: the draft a module becomes
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class DraftDeclaration:
    """One declaration in a generated draft: structure kept, meaning not invented.

    * ``name`` — the declared name, as written in the Python source.
    * ``form`` — the ``.s0ma`` declaration form: ``"nerve"`` (a public
      function), ``"helper"`` (an underscore-private function) or
      ``"cell"`` (a class or an upper-case constant).
    * ``kind`` — the component kind for a cell (``"MODEL"``,
      ``"CONSTANT"``, …), taken from the census hint; ``None`` for a
      nerve or a helper, which have no kind.
    * ``intent`` — the intent lifted verbatim from an existing s0ma
      ``@component`` decorator. ``None`` means there was none and the
      emitter writes a :data:`DRAFT_INTENT_MARKER` placeholder: a real
      authored intent is never overwritten, and a missing one is never
      guessed.
    * ``layer`` — a per-declaration layer lifted from ``@component``;
      ``None`` means the module's layer applies.
    * ``fields`` — ``(field, text)`` pairs for the remaining authored
      header fields lifted verbatim from ``@component`` (``schema``,
      ``expects``, ``guarantees``, ``forbids``, …), in the order they are emitted.
    * ``body`` — the verbatim source text emitted after the ``---``
      separator: the definition and its decorators exactly as written,
      minus any s0ma registration decorator (whose content has moved
      into the fields above).
    * ``start_line`` — 1-based first source line this declaration
      accounts for, including a comment block sitting directly above
      the definition.
    * ``end_line`` — 1-based last source line, inclusive. Together with
      ``start_line`` this is how the harvester proves nothing was lost.
    """

    name: str
    form: str
    kind: str | None
    intent: str | None
    layer: str | None
    fields: tuple[tuple[str, str], ...]
    body: str
    start_line: int
    end_line: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "form": self.form,
            "kind": self.kind,
            "intent": self.intent,
            "layer": self.layer,
            "fields": _string_pairs(self.fields),
            "body": self.body,
            "start_line": self.start_line,
            "end_line": self.end_line,
        }


@dataclass(frozen=True, slots=True)
class DraftUnplaced:
    """Source the harvester could not place, carried instead of dropped.

    Nothing in a converted module goes missing quietly. Text that is
    neither a declaration body nor a header fact lands here, is emitted
    under :data:`DRAFT_UNPLACED_MARKER`, and refuses the build via
    ``ADOPT_UNPLACED_CODE`` until a person has placed it.

    * ``text`` — the verbatim source lines, unchanged.
    * ``start_line`` — 1-based first source line, inclusive.
    * ``end_line`` — 1-based last source line, inclusive.
    * ``reason`` — one plain sentence saying why it could not be
      placed, e.g. "module-level statement with a side effect".
    """

    text: str
    start_line: int
    end_line: int
    reason: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "text": self.text,
            "start_line": self.start_line,
            "end_line": self.end_line,
            "reason": self.reason,
        }


@dataclass(frozen=True, slots=True)
class DraftModule:
    """A Python module as the harvester sees it, ready for the draft emitter.

    The split of labour is the point: this record holds everything that
    can be *derived* from the source, and holds ``None`` wherever
    meaning would have to be invented. The emitter turns those
    ``None``\\ s into :data:`DRAFT_INTENT_MARKER` placeholders, and
    ``s0ma check`` refuses the project until they are written.

    * ``module`` — the dotted module name the draft declares.
    * ``source_path`` — project-relative POSIX path of the Python file
      harvested.
    * ``source_hash`` — ``"sha256:<hex>"`` of that file; the emitter
      writes ``metadata: adopt_source: "<source_path>@<source_hash>"``
      so a draft always says which bytes it came from.
    * ``layer`` — the module's single layer (one per module is a
      language rule), from the ``--layer`` argument, a high-confidence
      proposal, or a lifted ``@component``; ``None`` when the emitter
      must ask.
    * ``intent`` — the module intent lifted verbatim from a registered
      module-level ``@component``; ``None`` when the emitter writes a
      placeholder.
    * ``docstring`` — the Python module's docstring, carried verbatim
      so whoever finishes the draft can see it. It is never promoted to
      the intent on its own: prose about a file is not a declared
      intent.
    * ``requires`` — dotted modules for the header's ``requires:``
      (load-time imports a body actually references), sorted.
    * ``deferred_requires`` — dotted modules for ``deferred_requires:``
      (function-scoped imports), sorted.
    * ``uses`` — first-party modules for ``uses:``, i.e. targets that
      already exist as ``.s0ma`` sources in this project, sorted.
    * ``exports`` — public names for ``exports:``, from ``__all__`` in
      its declared order, else the public declaration names in source
      order.
    * ``declarations`` — the draft's declarations in **source order**,
      so the draft reads like the file it came from.
    * ``unplaced`` — source nothing else accounted for, source order.
    * ``notes`` — plain sentences for whoever finishes the draft, e.g.
      a first-party import that had to become ``requires`` because its
      target has not been converted yet.
    """

    module: str
    source_path: str
    source_hash: str
    layer: str | None
    intent: str | None
    docstring: str | None
    requires: tuple[str, ...]
    deferred_requires: tuple[str, ...]
    uses: tuple[str, ...]
    exports: tuple[str, ...]
    declarations: tuple[DraftDeclaration, ...]
    unplaced: tuple[DraftUnplaced, ...]
    notes: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "module": self.module,
            "source_path": self.source_path,
            "source_hash": self.source_hash,
            "layer": self.layer,
            "intent": self.intent,
            "docstring": self.docstring,
            "requires": list(self.requires),
            "deferred_requires": list(self.deferred_requires),
            "uses": list(self.uses),
            "exports": list(self.exports),
            "declarations": [declaration.to_dict() for declaration in self.declarations],
            "unplaced": [block.to_dict() for block in self.unplaced],
            "notes": list(self.notes),
        }


# ---------------------------------------------------------------------------
# Rung 3 — convert: proving behaviour survived
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class SurfaceEntry:
    """One public name on a module's surface, normalised for comparison.

    Normalisation is the whole point: two files that differ only in
    blank lines, comments, import order or quote style must produce
    equal entries. Everything here is ``ast.unparse`` output or
    cleaned-up docstring text, never raw source.

    * ``name`` — the public name within the module: a top-level name,
      or ``"Class.member"`` for a public method or class-level
      attribute. The surface is a flat, sorted list; the dotted name is
      what a parity finding quotes.
    * ``category`` — ``"function"``, ``"async_function"``, ``"class"``,
      ``"constant"``, ``"method"``, ``"async_method"`` or
      ``"attribute"``. A method that stops being async is a real break,
      so sync and async are different categories.
    * ``signature`` — the normalised parameter list and return
      annotation, e.g. ``"(self, *, limit: int = 10) -> list[Book]"``;
      ``self``/``cls`` are kept and defaults are unparsed. ``None`` for
      a constant or an attribute, which have no signature.
    * ``annotation`` — the declared type of a constant or a class-level
      attribute, unparsed: ``title: str`` records ``"str"``, and
      ``copies: int = 1`` records ``"int"`` beside a ``value`` of
      ``"1"``. A quoted forward reference is recorded as written
      (``"'Book'"``, quotes normalised by ``ast.unparse``), because
      what the file declares is all a reader that never imports it can
      know. ``None`` for functions, methods and classes — whose types
      live in ``signature`` — and for a name assigned without a
      declared type. A dataclass field changing from ``str`` to ``int``
      is the commonest change a conversion makes, and without this it
      would pass parity silently.
    * ``decorators`` — decorator expressions, unparsed, source order.
    * ``bases`` — base-class expressions, unparsed, source order;
      empty for anything that is not a class.
    * ``docstring`` — the docstring after ``inspect.cleandoc``;
      ``None`` when there is none.
    * ``value`` — for a constant or a class attribute, the unparsed
      literal; the marker ``"<non-literal>"`` when the value is
      computed rather than written out (comparing computed values
      statically would be a lie). ``None`` for anything else.
    """

    name: str
    category: str
    signature: str | None
    annotation: str | None
    decorators: tuple[str, ...]
    bases: tuple[str, ...]
    docstring: str | None
    value: str | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "category": self.category,
            "signature": self.signature,
            "annotation": self.annotation,
            "decorators": list(self.decorators),
            "bases": list(self.bases),
            "docstring": self.docstring,
            "value": self.value,
        }


@dataclass(frozen=True, slots=True)
class ModuleSurface:
    """A module's public surface, read statically and never imported.

    Captured from the original Python before it is deleted, and read
    again from the built module afterwards. If the two agree, the
    conversion kept its promise.

    * ``module`` — the dotted module the surface describes.
    * ``entries`` — every public name, **sorted by** ``name``, so a
      class and its members sit together and two captures of the same
      module are byte-identical.
    * ``dunder_all`` — the literal ``__all__`` in its declared order;
      ``None`` when the module declares none. Order is kept here for
      the record, but the comparer ignores it: the emitter generates
      its own ordering.
    """

    module: str
    entries: tuple[SurfaceEntry, ...]
    dunder_all: tuple[str, ...] | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "module": self.module,
            "entries": [entry.to_dict() for entry in self.entries],
            "dunder_all": None if self.dunder_all is None else list(self.dunder_all),
        }


@dataclass(frozen=True, slots=True)
class ParityFinding:
    """One difference between a baseline surface and the built module.

    * ``kind`` — ``"missing"`` (in the baseline, gone from the build),
      ``"extra"`` (in the build, not in the baseline),
      ``"signature_changed"``, ``"annotation_changed"`` (a declared
      type changed — the commonest silent break in a converted
      dataclass), ``"doc_changed"``, ``"bases_changed"``,
      ``"decorators_changed"`` or ``"value_changed"``.
    * ``symbol`` — the :attr:`SurfaceEntry.name` the finding is about.
    * ``before`` — the baseline's text for the aspect that changed;
      ``None`` when there was nothing before (an ``"extra"``).
    * ``after`` — the built module's text for it; ``None`` when there
      is nothing after (a ``"missing"``).
    * ``detail`` — one plain sentence saying what changed and what to
      do about it, written for someone reading a failing command.
    """

    kind: str
    symbol: str
    before: str | None
    after: str | None
    detail: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "symbol": self.symbol,
            "before": self.before,
            "after": self.after,
            "detail": self.detail,
        }


@dataclass(frozen=True, slots=True)
class ParityResult:
    """The verdict for one module: did the conversion keep its surface?

    * ``module`` — the dotted module compared.
    * ``built_path`` — project-relative POSIX path of the built ``.py``
      the baseline was compared against, so the verdict says what it
      actually read.
    * ``findings`` — every difference, sorted by ``(symbol, kind)`` so
      a reader works down the module a name at a time. Empty means
      clean.

    :attr:`clean` is derived, never stored: a result with findings
    cannot be labelled clean by accident.
    """

    module: str
    built_path: str
    findings: tuple[ParityFinding, ...]

    @property
    def clean(self) -> bool:
        """True when nothing differs — the only passing verdict."""
        return not self.findings

    def to_dict(self) -> dict[str, Any]:
        return {
            "module": self.module,
            "built_path": self.built_path,
            "clean": self.clean,
            "findings": [finding.to_dict() for finding in self.findings],
        }


# ---------------------------------------------------------------------------
# Across the ladder — where am I?
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class LadderStatus:
    """Where a project stands on the retrofit ladder, and what to do next.

    Read-only by construction: ``s0ma adopt status`` writes nothing
    anywhere (retrofit rule R-2).

    * ``rung`` — the rung reached: ``0`` (assess: no ``[tool.s0ma]``
      yet), ``1`` (perimeter set, nothing converted), ``3``
      (converting, module by module) or ``4`` (ratcheting the mode up).
      Rung 2, registering Python in place, is a documented way-station
      and is never reported as a position.
    * ``rung_label`` — the rung's plain-language name, for people who
      have not read the guide.
    * ``mode`` — the project's configured strictness mode
      (``"migration"``, ``"dev"``, ``"strict"``, ``"release"``);
      ``None`` at rung 0, where there is no configuration to read.
    * ``counts`` — ``(name, count)`` pairs, sorted by name: converted
      modules, adopted files, ``UNKNOWN`` files, baselines captured,
      and parity verdicts where a build exists.
    * ``score`` — the project's current overall score, 0–100; ``None``
      when it cannot be computed yet.
    * ``score_floor`` — the floor the current mode has to clear;
      ``None`` when there is no mode yet.
    * ``next_module`` — the next module to convert: the first entry of
      the scan's leaf-first order that is still plain Python.
      ``None`` when there is nothing left to convert.
    * ``next_command`` — the exact command to run next, ready to paste.
      Always present: even a finished project has a next step.
    """

    rung: int
    rung_label: str
    mode: str | None
    counts: tuple[tuple[str, int], ...]
    score: float | None
    score_floor: float | None
    next_module: str | None
    next_command: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "rung": self.rung,
            "rung_label": self.rung_label,
            "mode": self.mode,
            "counts": _count_pairs(self.counts),
            "score": self.score,
            "score_floor": self.score_floor,
            "next_module": self.next_module,
            "next_command": self.next_command,
        }
