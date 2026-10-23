"""Python code emitter for the s0ma DSL transpiler.

Generates valid, inspectable Python files from parsed S0maModule ASTs.
Emits @component-decorated Python code, __all__ from exports, import
statements in PEP 8 order, and registration calls for modules,
constants, types, standalone axons, ganglia, and tests.

The emitter consumes the AST directly (for body text and field values).
Per PRD §2.1.5, the IR is the canonical internal truth — the emitter
should eventually consume the IR for resolved data.

For ganglion and test emission (M12), optional project-level context
enables observes pattern resolution and privileged import generation.
Without project context, ganglia and tests emit with unresolved patterns.

PRD references: FR-20 (ganglia), FR-21 (tests), FR-22 (privileged imports),
                FR-25 (Python emission), §2.2.1–2.2.6 (declaration behavior)
Spec references: §4.3.1 (observes patterns), §4.7.2 (PEP 8 import ordering),
                 §4.8 (test declarations), §4.10.6 (privileged imports)
"""

from __future__ import annotations

import ast
import hashlib
import inspect
import os
import re
import sys
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, cast

from s0ma.decorators import component
from s0ma.types import ComponentKind, Layer

from s0ma_dsl.ast_nodes.enums import (
    Kind,
)
from s0ma_dsl.ast_nodes.enums import (
    Layer as DslLayer,
)
from s0ma_dsl.ast_nodes.nodes import (
    AssertBoolean,
    AssertComparison,
    BooleanPredicate,
    CellDecl,
    ComparisonPredicate,
    DocGuideDecl,
    DocRefDecl,
    EntityRefAst,
    ExampleDecl,
    FilterExprAst,
    GanglionDecl,
    HelperDecl,
    IntegrationDecl,
    NerveDecl,
    RequiresEntry,
    S0maModule,
    SectionAst,
    SourceLocation,
    StandaloneAxonDecl,
    TestDecl,
    UsesEntry,
)
from s0ma_dsl.codegen.observes_resolver import (
    ObservesResolver,
    PrivilegedImportInfo,
    ProjectContext,
    ResolvedObserves,
    determine_privileged_imports,
)
from s0ma_dsl.config import StrictnessMode
from s0ma_dsl.ir.constant_values import constant_literal
from s0ma_dsl.ir.schema import TRANSPILER_VERSION

if TYPE_CHECKING:
    from s0ma_dsl.errors import S0maResolutionError

__all__ = [
    "PythonEmitter",
    "embedded_output_hash",
    "emit_python",
    "inject_hashes",
    "is_hand_edited",
    "overwrite_loses_hand_edit",
    "recompute_output_hash",
]


# ---------------------------------------------------------------------------
# Checksum embedding for drift detection (MS 5b)
# ---------------------------------------------------------------------------

# Lines matching this pattern are excluded when computing the output hash
# to avoid circular dependency.
_HASH_LINE_RE = re.compile(r"^# s0ma-(source|output)-hash:.*$", flags=re.MULTILINE)

# The embedded ``# s0ma-output-hash: sha256:<h>`` marker, used to read the
# hash back for drift/edit detection (B2, 0.11.0).
_OUTPUT_HASH_RE = re.compile(
    r"^# s0ma-output-hash:\s*sha256:(\w+)$", flags=re.MULTILINE
)


def inject_hashes(python_output: str, source_text: str) -> str:
    """Replace hash placeholders in emitted Python with actual SHA-256 checksums.

    Parameters
    ----------
    python_output:
        The emitted Python source containing ``__S0MA_SOURCE_HASH__`` and
        ``__S0MA_OUTPUT_HASH__`` placeholders.
    source_text:
        The raw ``.s0ma`` source file content used to compute the source hash.

    Returns
    -------
    str
        The Python source with both hash placeholders replaced.
    """
    source_hash = hashlib.sha256(source_text.encode("utf-8")).hexdigest()[:16]

    # Compute output hash from content with hash lines stripped
    output_for_hash = _HASH_LINE_RE.sub("", python_output)
    output_hash = hashlib.sha256(output_for_hash.encode("utf-8")).hexdigest()[:16]

    result = python_output.replace("__S0MA_SOURCE_HASH__", f"sha256:{source_hash}")
    result = result.replace("__S0MA_OUTPUT_HASH__", f"sha256:{output_hash}")
    return result


def recompute_output_hash(python_source: str) -> str:
    """Recompute the output-hash of emitted Python (hash lines excluded).

    The single source of truth for the computation ``inject_hashes`` and
    ``s0ma verify`` both perform: strip the two ``# s0ma-*-hash`` comment
    lines, then sha256 the remaining bytes and take the first 16 hex
    chars. Factored out (B2, 0.11.0) so the build write-guard, ``s0ma
    check``'s drift pass, and ``s0ma verify``'s ``EDITED`` classifier
    all compare hashes exactly the same way.
    """
    stripped = _HASH_LINE_RE.sub("", python_source)
    return hashlib.sha256(stripped.encode("utf-8")).hexdigest()[:16]


def embedded_output_hash(python_source: str) -> str | None:
    """The ``# s0ma-output-hash`` value embedded in emitted Python, or None.

    ``None`` means the file carries no output-hash header — it is not a
    transpiler-generated file (a bootstrap module, a package marker, or a
    hand-written ``.py``), so the drift/edit machinery does not apply.
    """
    match = _OUTPUT_HASH_RE.search(python_source)
    return match.group(1) if match else None


def is_hand_edited(python_source: str) -> bool:
    """True iff a generated ``.py`` was edited by hand after transpilation.

    A generated file embeds ``# s0ma-output-hash: sha256:<h>`` where
    ``<h>`` is the hash of its own body (hash lines excluded). If the
    recomputed hash disagrees, the body changed since transpilation — a
    hand edit ``s0ma build`` would otherwise silently overwrite. A file
    with no embedded output-hash is *not* generated and returns
    ``False`` (never a false accusation against a bootstrap file).
    """
    embedded = embedded_output_hash(python_source)
    if embedded is None:
        return False
    return recompute_output_hash(python_source) != embedded


def overwrite_loses_hand_edit(existing: str, replacement: str) -> bool:
    """True iff writing *replacement* over *existing* would lose a hand edit.

    Both halves must hold: *existing* was edited by hand
    (:func:`is_hand_edited`), and its body — the two ``# s0ma-*-hash``
    lines aside — differs from *replacement*'s. The second half is what
    lets an edit that has been moved into the ``.s0ma`` source through:
    the regenerated file then carries the very body the hand-edited one
    does, only its hash lines differ, and overwriting it loses nothing.
    The build write-guard refuses exactly when this is true.
    """
    if not is_hand_edited(existing):
        return False
    return _HASH_LINE_RE.sub("", existing) != _HASH_LINE_RE.sub("", replacement)

# Nerve kinds that map directly to s0ma ComponentKind
_NERVE_KIND_MAP: dict[Kind, str] = {
    Kind.SERVICE: "ComponentKind.SERVICE",
    Kind.FUNCTION: "ComponentKind.FUNCTION",
    Kind.ADAPTER: "ComponentKind.ADAPTER",
    Kind.ORCHESTRATOR: "ComponentKind.ORCHESTRATOR",
    Kind.FRAMEWORK: "ComponentKind.SERVICE",
}

# Cell kinds that use @component (mapped to ComponentKind.MODEL)
_CELL_DECORATOR_KINDS: frozenset[Kind] = frozenset({
    Kind.MODEL,
    Kind.ENUM,
    Kind.EXCEPTION,
    Kind.CONFIG,
})

# Cell kinds that use register_constant() / register_type()
_CELL_REGISTER_KINDS: frozenset[Kind] = frozenset({
    Kind.CONSTANT,
    Kind.TYPE,
})

# Known Python stdlib top-level module names (Python 3.10+)
_STDLIB_MODULES: frozenset[str] = frozenset(
    getattr(sys, "stdlib_module_names", set())
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _constant_value_literal(value: object) -> str:
    """Render a constant's carried literal as Python source.

    Strings go through :func:`_py_str_literal`; ``None``, booleans and
    numbers through ``repr``; a list element by element. The reader
    (``s0ma_dsl.ir.constant_values``) admits nothing else.
    """
    if isinstance(value, str):
        return _py_str_literal(value)
    if isinstance(value, list):
        return "[" + ", ".join(_constant_value_literal(item) for item in value) + "]"
    return repr(value)


def _py_str_literal(value: str) -> str:
    """Emit a Python string literal that is safe regardless of contents.

    Escaping (quotes, backslashes, control characters, Unicode) is
    delegated entirely to Python's ``repr()``. The result is guaranteed
    to round-trip through ``ast.parse()``.

    Quote-style policy: prefer double-quotes for readability and to
    match the historical s0ma emission convention
    (``register_module(name="x")``). When the input contains a literal
    double-quote, we fall back to ``repr()``'s default (single-quoted
    with escaped contents) — this is what ``repr()`` itself does, and
    it keeps the output unambiguous without manual escaping.

    This is the canonical helper for interpolating *any* string —
    metadata, schema text, intent prose, etc. — into emitted Python.
    Hand-rolled escaping (e.g. ``f'"{escape(x)}"'``) is forbidden:
    it has historically corrupted strings containing ``\"`` and
    backslashes (see feedback-5.5 lines 90–176, M2).
    """
    rendered = repr(value)
    # ``repr()`` switches to a double-quoted form only when the input
    # contains a single quote but no double quote. We invert that
    # preference: emit double-quoted when safe, otherwise fall through.
    if rendered.startswith("'") and rendered.endswith("'"):  # noqa: SIM102 — comment on inner branch needs the split
        # Re-render with double quotes only if doing so doesn't require
        # extra escaping — i.e. the input contains no double-quote.
        if '"' not in value:
            inner = rendered[1:-1]
            # ``repr()`` only escapes single-quotes inside a single-quoted
            # string. Strip the backslash-escape so the contents move
            # cleanly into a double-quoted wrapper. No other escape
            # sequence in repr's output is quote-sensitive.
            inner = inner.replace("\\'", "'")
            return f'"{inner}"'
    return rendered


def _contract_forbids_part(forbids: str) -> str:
    """Return the ``forbids=[...]`` argument line of an emitted ``Contract(...)``.

    The authored sentence travels whole, as one list item, through
    :func:`_py_str_literal`.
    """
    return f"\n        forbids=[{_py_str_literal(forbids)}]"


def _join_contract_parts(parts: list[str]) -> str:
    """Join ``Contract(...)`` argument lines into the emitted layout.

    Each part starts with its own line break and indent; a closing comma
    and line break put ``)`` back at the parameter indent. No parts means
    no ``contracts=`` parameter at all, so the result is ``""``.
    """
    if not parts:
        return ""
    return ",".join(parts) + ",\n    "


def _authored_metadata_items(
    entries: tuple[tuple[str, object], ...],
) -> list[str]:
    """Render authored ``metadata:`` entries as emitted dict items.

    DSL-M1 (0.8.0, ADR-011 §(a)): the authored map MERGES into the
    registration ``metadata=`` dict the emitter already writes —
    authored items are APPENDED AFTER the emitter-written items, in
    authored order (collisions are impossible here: the semantic
    validator rejected reserved keys at check time). Value rendering
    follows the F7 rule — Python literals, never JSON (``True``, not
    ``true``): strings through :func:`_py_str_literal`, bools/ints/
    floats through ``repr``, list values as ``[...]`` of string
    literals.
    """
    items: list[str] = []
    for key, value in entries:
        if isinstance(value, tuple):
            rendered = "[" + ", ".join(
                _py_str_literal(item) for item in value
            ) + "]"
        elif isinstance(value, str):
            rendered = _py_str_literal(value)
        else:
            # bool / int / float — repr() is the Python literal form.
            rendered = repr(value)
        items.append(f'"{key}": {rendered}')
    return items


def _serves_as_stamp_lines(nerve: NerveDecl) -> list[str]:
    """The ``__name__``/``__qualname__`` stamp for a ``serves_as:`` nerve.

    DSL-M1 (0.8.0, ADR-011 §(b)): appended IMMEDIATELY after the
    decorated def's last body line, at module scope, separated by one
    blank line, before any subsequent emitted statement. Decorate-
    then-stamp is the load-bearing invariant — ``@component`` runs at
    def time and derives ``qualified_name`` from the symbol BEFORE the
    stamp executes, so ``ComponentSpec`` keeps the declaration
    identifier, the module attribute keeps the declaration name, and
    only the callable's ``__name__``/``__qualname__`` carry the served
    name (exactly what schema-title derivation reads — the F-M4-2 fix
    at the artifact level). Nerves emit only module-level callables,
    so the ``__qualname__`` leaf IS the whole ``__qualname__``.
    """
    if nerve.serves_as is None:
        return []
    served = _py_str_literal(nerve.serves_as)
    return [
        "",
        f"{nerve.name}.__name__ = {served}",
        f"{nerve.name}.__qualname__ = {served}",
    ]


def _embedded_content_literal(value: str) -> str:
    '''Render the body of an ``@file()``-embedded CONSTANT cell.

    M12 (feedback 5–6): the content can be arbitrary text — typically a
    multi-line HTML, SQL, or prompt template. We prefer raw triple-
    quoted strings (``r"""..."""``) for readability and to keep the
    output diff-friendly: no escape processing, the embedded content
    reads identically in the generated ``.py`` and the original file.
    We fall back to ``repr()`` only when the content contains the
    triple-quote sequence (which would close the raw-triple-quoted
    literal prematurely) or a trailing backslash (raw strings cannot
    terminate with one cleanly).

    Both branches must round-trip through ``ast.parse`` (the M2 build
    invariant). The returned string evaluates to ``value`` byte-for-byte
    when read back via the generated module.
    '''
    # Triple-quote collision: the closing triple-quote would be
    # ambiguous. A trailing backslash also breaks raw strings — a raw
    # string literal cannot end with an odd number of backslashes
    # because the backslash escapes the closing quote even in raw mode.
    # Fall through to ``repr()`` in either case.
    if '"""' in value or value.endswith("\\"):
        return repr(value)
    return f'r"""{value}"""'


def _top_level_package(module_path: str) -> str:
    """Extract the top-level package name from a dotted import path."""
    return module_path.split(".")[0]


def _is_stdlib(module_path: str) -> bool:
    """Check if a module path refers to a Python stdlib module."""
    top = _top_level_package(module_path)
    return top in _STDLIB_MODULES


def _requires_to_import_line(entry: RequiresEntry) -> str:
    """Convert a RequiresEntry to a Python import statement."""
    if entry.is_from_import:
        parts = entry.module_path.rsplit(".", 1)
        if len(parts) == 2:
            pkg, name = parts
            if entry.alias:
                return f"from {pkg} import {name} as {entry.alias}"
            return f"from {pkg} import {name}"
        # Single-segment from-import (unusual but handle it)
        if entry.alias:
            return f"import {entry.module_path} as {entry.alias}"
        return f"import {entry.module_path}"
    else:
        if entry.alias:
            return f"import {entry.module_path} as {entry.alias}"
        return f"import {entry.module_path}"


def _canonical_dependency_name(target: str) -> str:
    """Render an inline depends_on target for the emitted ``dependencies=[...]``.

    DSL-M2 (0.8.0, ADR-011 §(d)): QUALIFIED targets
    (``module.declaration``) carry the canonical ``module::declaration``
    string — the registry's canonical-ID alphabet, matching
    ``register_relationship`` targets and ``_resolve_axon_target``'s
    dotted→``::`` conversion. Unqualified local targets keep today's
    bare-name strings byte-identically (L-7).
    """
    if "." in target:
        target_mod, target_decl = target.split(".", 1)
        return f"{target_mod}::{target_decl}"
    return target


def _deferred_local_name(entry: RequiresEntry) -> str:
    """The name a ``deferred_requires:`` entry binds in a consuming body.

    DSL-M2 (0.8.0, ADR-011 §(c)): mirrors the resolver's
    ``_requires_local_name`` evidence rule — alias wins, then the
    from-import leaf, then the top-level package of a plain import.
    """
    if entry.alias:
        return entry.alias
    if entry.is_from_import:
        return entry.module_path.rsplit(".", 1)[-1]
    return entry.module_path.split(".")[0]


def _def_body_referenced_names(
    node: ast.FunctionDef | ast.AsyncFunctionDef,
) -> set[str]:
    """Names referenced inside a def's BODY (not decorators/signature).

    DSL-M2 (0.8.0, ADR-011 §(c)): the consumption evidence for the
    deferred-import body injection. Mirrors the resolver's
    ``_extract_identifiers`` shape — ``Name`` ids plus the root name of
    every ``Attribute`` chain — but scoped to the statements of ONE
    def body, because that is the unit that receives an injected
    import. Decorator expressions, parameter defaults, and annotations
    are deliberately excluded: they execute at def (module) time, where
    a deferred name is unreachable (``DEFERRED_IMPORT_MODULE_SCOPE``
    owns that diagnostic at check time).
    """
    names: set[str] = set()
    for stmt in node.body:
        for sub in ast.walk(stmt):
            if isinstance(sub, ast.Name):
                names.add(sub.id)
            elif isinstance(sub, ast.Attribute):
                root: ast.expr = sub
                while isinstance(root, ast.Attribute):
                    root = root.value
                if isinstance(root, ast.Name):
                    names.add(root.id)
    return names


def _uses_to_import_line(entry: UsesEntry) -> str:
    """Convert a UsesEntry to a Python import statement.

    Uses entries are ``module.component`` — always a from-import.
    """
    parts = entry.qualified_name.rsplit(".", 1)
    if len(parts) == 2:
        mod, comp = parts
        if entry.alias:
            return f"from {mod} import {comp} as {entry.alias}"
        return f"from {mod} import {comp}"
    # Bare name (shouldn't happen for uses, but handle gracefully)
    return f"import {entry.qualified_name}"


# B3 (0.11.0, batch-01a): collision-safe loader for a ``uses:`` entry that
# targets a built s0ma module whose NAME shadows a Python stdlib module
# (``io``, ``json``, ``csv`` …). A plain ``import io`` / ``from io import
# x`` resolves to the stdlib module already resident in ``sys.modules``,
# so the built module is unreachable and the symbol is missing at runtime
# — the failure that forced the batch-01a agent into a hand-written
# importlib shim. This loader loads the built sibling ``.py`` from the
# consumer's own package directory under a mangled key, bypassing the
# stdlib cache and leaving the real stdlib module untouched. The
# root-cause steer is ``MODULE_SHADOWS_STDLIB`` (an error in
# strict/release), so this code is only ever emitted for a dev/migration
# build of a shadowing module; non-shadowing projects (every self-host
# module included) never trigger it and are byte-identical.
_SHADOWED_LOADER_HELPER = (
    "def _s0ma_import_shadowed(_name):\n"
    "    # B3: load a built s0ma module whose name shadows a stdlib module\n"
    "    # from this package dir, bypassing the stdlib module cached in\n"
    "    # sys.modules. Rename the module (MODULE_SHADOWS_STDLIB) to avoid.\n"
    "    import importlib.util as _ilu\n"
    "    import sys as _sys\n"
    "    from pathlib import Path as _Path\n"
    "    _key = '_s0ma_shadowed__' + _name\n"
    "    _mod = _sys.modules.get(_key)\n"
    "    if _mod is None:\n"
    "        _spec = _ilu.spec_from_file_location(\n"
    "            _key, _Path(__file__).resolve().parent / (_name + '.py')\n"
    "        )\n"
    "        _mod = _ilu.module_from_spec(_spec)\n"
    "        _sys.modules[_key] = _mod\n"
    "        _spec.loader.exec_module(_mod)\n"
    "    return _mod"
)


def _uses_shadowed_load_line(entry: UsesEntry) -> str:
    """Emit the collision-safe binding for a stdlib-shadowing ``uses:`` entry.

    Mirrors ``_uses_to_import_line``'s binding name exactly (alias, else
    the dotted leaf, else the bare module name) but sources it from
    ``_s0ma_import_shadowed`` instead of a plain import.
    """
    parts = entry.qualified_name.rsplit(".", 1)
    if len(parts) == 2:
        mod, comp = parts
        local = entry.alias or comp
        return f'{local} = _s0ma_import_shadowed("{mod}").{comp}'
    # Bare module reference — bind the module object itself.
    mod = entry.qualified_name
    local = entry.alias or mod
    return f'{local} = _s0ma_import_shadowed("{mod}")'


# ---------------------------------------------------------------------------
# Python Emitter
# ---------------------------------------------------------------------------


@component(
    name="S0maDSL_PythonEmitter",
    kind=ComponentKind.SERVICE,
    layer=Layer.FRAMEWORK,
    intent=(
        "Generates valid, inspectable Python source code from a parsed S0maModule. "
        "Emits @component-decorated functions and classes, PEP 8-ordered imports, "
        "__all__ exports, and registration calls."
    ),
    idempotent=True,
    is_framework=True,
)
@dataclass
class PythonEmitter:
    """Generates Python source from a parsed S0maModule.

    Consumes the AST and produces @component-decorated Python code
    with PEP 8-ordered imports, ``__all__`` exports, and registration
    calls for modules, constants, types, standalone axons, ganglia,
    and tests.

    For full ganglion and test emission, provide ``project_context``
    to enable observes pattern resolution and privileged imports.
    Without it, ganglia and tests emit with unresolved patterns.
    """

    module_name: str = ""
    project_context: ProjectContext | None = None
    mode: StrictnessMode = StrictnessMode.DEV
    filename: str = ""

    # Project-wide doc content hashes computed by
    # ``s0ma_dsl.codegen.doc_emitter.compute_doc_hashes``. Map keyed by
    # ``(decl_kind, decl_name)`` where ``decl_kind`` is one of
    # ``"doc-ref"`` or ``"doc-guide"``. When ``None``, doc-* registration
    # calls fall back to the empty-string placeholder (the M5 default
    # behaviour, retained so existing callers that haven't migrated to
    # the M6 hash pipeline keep working).
    doc_hashes: dict[tuple[str, str], str] | None = None

    # Populated during emit() for privileged import generation
    _privileged_imports: list[PrivilegedImportInfo] = field(
        default_factory=list, init=False, repr=False
    )
    _resolved_observes: dict[str, list[ResolvedObserves]] = field(
        default_factory=dict, init=False, repr=False
    )
    _emit_errors: list[S0maResolutionError] = field(
        default_factory=list, init=False, repr=False
    )
    # DSL-M2 (0.8.0, ADR-011 §(c)): the module's ``deferred_requires:``
    # entries, captured at emit() time so every body-emission path can
    # run the per-def import injection without re-threading the module.
    _deferred_requires: tuple[RequiresEntry, ...] = field(
        default=(), init=False, repr=False
    )

    def emit(self, module: S0maModule) -> str:
        """Generate complete Python source for a .s0ma module.

        Parameters
        ----------
        module:
            A fully parsed and validated S0maModule.

        Returns
        -------
        str
            Valid Python source code.
        """
        self.module_name = module.module.name
        self._privileged_imports = []
        self._resolved_observes = {}
        self._emit_errors = []
        self._deferred_requires = module.module.deferred_requires

        # Pre-resolve ganglia observes and determine privileged imports
        if self.project_context is not None:
            self._resolve_all_ganglia(module)
            self._resolve_all_tests(module)

        sections: list[str] = []

        sections.append(self._emit_header(module))
        sections.append(self._emit_imports(module))
        sections.append(self._emit_all(module))
        sections.append(self._emit_register_module(module))
        markers = self._emit_doc_markers(module)
        if markers:
            sections.append(markers)

        # Declarations in source order
        for decl in module.all_declarations:
            section = self._emit_declaration(decl, module)
            if section:
                sections.append(section)

        # Join with double newlines, ensure trailing newline
        result = "\n\n".join(s for s in sections if s)
        if not result.endswith("\n"):
            result += "\n"
        return result

    @property
    def errors(self) -> list[S0maResolutionError]:
        """Errors collected during emission (e.g., EMPTY_OBSERVES)."""
        return list(self._emit_errors)

    @property
    def privileged_imports(self) -> list[PrivilegedImportInfo]:
        """Privileged imports determined during emission."""
        return list(self._privileged_imports)

    # -------------------------------------------------------------------
    # File header
    # -------------------------------------------------------------------

    def _emit_header(self, module: S0maModule) -> str:
        """Emit module docstring and transpiler comment with hash placeholders.

        Hash lines are placeholders replaced by ``inject_hashes()`` after
        the full output is generated.
        """
        mod = module.module
        # Normalize intent whitespace
        intent = " ".join(mod.intent.split())
        lines = [
            f'"""{mod.name} — {intent}',
            "",
            f"Auto-generated by s0ma DSL transpiler v{TRANSPILER_VERSION}.",
            "Do not edit manually — edit the .s0ma source instead.",
            '"""',
            "# s0ma-source-hash: __S0MA_SOURCE_HASH__",
            "# s0ma-output-hash: __S0MA_OUTPUT_HASH__",
        ]
        return "\n".join(lines)

    # -------------------------------------------------------------------
    # Import generation (PEP 8 ordering)
    # -------------------------------------------------------------------

    def _emit_imports(self, module: S0maModule) -> str:
        """Emit import statements in PEP 8 order.

        Groups:
        1. Standard library
        2. Third-party packages
        3. s0ma framework
        4. Project s0ma components (uses)
        5. Privileged imports (ganglia/tests only, marked with comment)
        """
        stdlib_imports: list[str] = []
        third_party_imports: list[str] = []
        soft_require_blocks: list[str] = []
        s0ma_framework_imports: list[str] = []
        project_imports: list[str] = []
        privileged_import_lines: list[str] = []

        # Categorize requires entries
        for req in module.module.requires:
            line = _requires_to_import_line(req)
            if _is_stdlib(req.module_path):
                stdlib_imports.append(line)
            else:
                third_party_imports.append(line)

        # POST-10b (0.16.0): ``runtime_only_requires:`` entries emit the
        # same import line as ``requires:`` — the field's purpose is the
        # vestigial-check exemption, not a different emission shape.
        # Categorised stdlib-vs-third-party identically.
        for req in module.module.runtime_only_requires:
            line = _requires_to_import_line(req)
            if _is_stdlib(req.module_path):
                stdlib_imports.append(line)
            else:
                third_party_imports.append(line)

        # Soft requires — try/except ImportError blocks.
        #
        # POST-10j (0.16.0): dotted ``soft_requires:`` entries are
        # auto-promoted to the from-import shape for the try/except
        # wrapper. The pre-0.16.0 behaviour for a dotted lowercase
        # entry like ``soft_requires: [importlib.metadata]`` was to
        # emit ``try: import importlib.metadata; except ImportError:
        # importlib = None`` — which (a) overwrites the top-level
        # ``importlib`` binding (breaking any other consumer of the
        # parent module elsewhere in the file) and (b) leaves the
        # ``metadata`` name still unbound when the import succeeds,
        # so consuming code that references ``metadata`` directly
        # raises ``NameError``. The correct codegen for the common
        # author intent — "try to import this submodule, fall back
        # gracefully" — is ``try: from importlib import metadata;
        # except ImportError: metadata = None``. The colon-override
        # form (``soft_requires: [requests:Session]``) was already
        # handled correctly by ``_requires_to_import_line`` because
        # the parser sets ``is_from_import=True`` for that branch;
        # the fix here normalises the dotted form to the same shape.
        for req in module.module.soft_requires:
            effective_is_from_import = req.is_from_import or (
                "." in req.module_path
            )
            if effective_is_from_import:
                parts = req.module_path.rsplit(".", 1)
                if len(parts) == 2:
                    pkg, name = parts
                    if req.alias:
                        import_line = f"from {pkg} import {name} as {req.alias}"
                    else:
                        import_line = f"from {pkg} import {name}"
                    local_name = req.alias or name
                else:
                    # Single-segment ``is_from_import=True`` is unusual
                    # (the parser only sets it for dotted entries) —
                    # fall back to a plain import for safety.
                    if req.alias:
                        import_line = f"import {req.module_path} as {req.alias}"
                    else:
                        import_line = f"import {req.module_path}"
                    local_name = req.alias or req.module_path
            else:
                if req.alias:
                    import_line = f"import {req.module_path} as {req.alias}"
                else:
                    import_line = f"import {req.module_path}"
                local_name = req.alias or req.module_path.split(".")[0]
            soft_require_blocks.append(
                f"try:\n    {import_line}\nexcept ImportError:\n    {local_name} = None"
            )

        # s0ma framework imports — determine what's needed
        s0ma_framework_imports.extend(self._determine_s0ma_imports(module))

        # Project imports from uses.
        #
        # B3 (0.11.0): a `uses:` entry targeting a s0ma module whose name
        # shadows a stdlib module cannot use a plain import (the stdlib
        # module is cached in sys.modules and wins). Those entries are
        # diverted to a collision-safe sibling-file load in an UNSORTED
        # group (the loader `def` must precede its rebindings — sorting
        # would move an `io = _s0ma_import_shadowed(...)` before the
        # `def`, a NameError). Non-shadowing uses keep the plain,
        # sorted from-imports, so every non-shadowing project (self-host
        # included) is byte-identical.
        shadowed_use_lines: list[str] = []
        for uses in module.module.uses:
            if _is_stdlib(uses.qualified_name):
                shadowed_use_lines.append(_uses_shadowed_load_line(uses))
            else:
                project_imports.append(_uses_to_import_line(uses))
        if shadowed_use_lines:
            shadowed_use_lines.insert(0, _SHADOWED_LOADER_HELPER)

        # Privileged imports for ganglia and tests (M12, PRD FR-22)
        # These bypass normal export checks for observation/verification
        if self._privileged_imports:
            privileged_import_lines.append(
                "# Privileged imports — cross-module INTERNAL access "
                "(observation/verification only)"
            )
            for priv in self._privileged_imports:
                privileged_import_lines.append(
                    f"from {priv.module_name} import {priv.component_name}"
                    f"  # {priv.import_kind}"
                )

        # Build grouped output
        groups: list[str] = []
        for group in [
            sorted(stdlib_imports),
            sorted(third_party_imports),
            soft_require_blocks,  # Already in source order
            sorted(s0ma_framework_imports),
            sorted(project_imports),
            shadowed_use_lines,  # B3: loader def + rebindings, ordered
            privileged_import_lines,  # Already ordered deterministically
        ]:
            if group:
                groups.append("\n".join(group))

        return "\n\n".join(groups)

    def _determine_s0ma_imports(self, module: S0maModule) -> list[str]:
        """Determine which s0ma framework imports are needed."""
        imports: list[str] = []

        # Ganglia also need @component decorator
        has_decorated = (
            bool(module.nerves) or bool(module.ganglia) or any(
                cell.kind in _CELL_DECORATOR_KINDS for cell in module.cells
            )
        )

        if has_decorated:
            imports.append("from s0ma.decorators import component")

        # Collect s0ma.types members needed
        types_needed: list[str] = []
        # Layer is always needed — register_module() uses Layer.X
        types_needed.append("Layer")
        if has_decorated:
            types_needed.append("ComponentKind")

        if types_needed:
            members = ", ".join(sorted(set(types_needed)))
            imports.append(f"from s0ma.types import {members}")

        # Contract needed if any nerve has expects/guarantees/latency_ms/
        # forbids, or any ganglion has forbids (its one contract line).
        needs_contract = any(
            nerve.expects or nerve.guarantees or nerve.latency_ms or nerve.forbids
            for nerve in module.nerves
        ) or any(ganglion.forbids for ganglion in module.ganglia)
        if needs_contract:
            imports.append("from s0ma.models import Contract")

        # Registration function imports
        reg_funcs: list[str] = []
        reg_funcs.append("register_module")

        if any(cell.kind == Kind.CONSTANT for cell in module.cells):
            reg_funcs.append("register_constant")
        if any(cell.kind == Kind.TYPE for cell in module.cells):
            reg_funcs.append("register_type")
        if module.axons:
            reg_funcs.append("register_relationship")
        if module.tests:
            reg_funcs.append("register_test")
        if module.doc_refs:
            reg_funcs.append("register_doc_ref")
        if module.doc_guides:
            reg_funcs.append("register_doc_guide")
        if module.examples:
            reg_funcs.append("register_example")
        # POST-5 (0.16.0): each ``integration`` declaration produces four
        # auto-emitted helpers registered via ``register_integration_helper``.
        if module.integrations:
            reg_funcs.append("register_integration_helper")

        members = ", ".join(sorted(reg_funcs))
        imports.append(
            f"from s0ma_dsl.runtime_bridge.registration import {members}"
        )

        return imports

    # -------------------------------------------------------------------
    # __all__ generation
    # -------------------------------------------------------------------

    def _emit_all(self, module: S0maModule) -> str:
        """Emit ``__all__`` from the module's exports list.

        POST-4c (0.15.0): ``exports_helpers:`` entries are appended to
        ``__all__`` so re-exported helpers participate in the same
        ``from module import *`` surface as regular exports. The
        consumer's access-control rule (test-context only) is
        enforced separately at resolution time; what ``__all__``
        records is the *reachable* surface.
        """
        exports = module.module.exports
        # POST-4c (0.15.0): append re-exported helpers. Order preserved
        # for determinism — exports first, then exports_helpers in
        # declaration order.
        all_names: tuple[str, ...] = (
            *exports,
            *module.module.exports_helpers,
        )
        if not all_names:
            return "__all__: list[str] = []"

        items = ", ".join(_py_str_literal(e) for e in all_names)
        return f"__all__ = [{items}]"

    # -------------------------------------------------------------------
    # register_module() call
    # -------------------------------------------------------------------

    def _emit_register_module(self, module: S0maModule) -> str:
        """Emit module-level registration call."""
        mod = module.module
        # M14 (feedback 5–6): metadata strings round-trip verbatim through
        # the emitter. Earlier code collapsed whitespace via
        # ``" ".join(...split())`` which destroyed the line breaks of
        # YAML literal-block-scalar content. ``_py_str_literal`` (M2)
        # already produces a valid Python literal regardless of content
        # so no further normalisation is needed.
        intent = mod.intent
        exports_list = ", ".join(_py_str_literal(e) for e in mod.exports)
        tags_list = (
            ", ".join(_py_str_literal(t) for t in mod.tags) if mod.tags else ""
        )

        lines = [
            "register_module(",
            f"    name={_py_str_literal(mod.name)},",
            f"    layer={_layer_ref(mod.layer)},",
            f"    version={_py_str_literal(mod.version)},",
            f"    intent={_py_str_literal(intent)},",
            f"    exports=[{exports_list}],",
        ]
        if tags_list:
            lines.append(f"    tags=[{tags_list}],")
        lines.append(")")

        return "\n".join(lines)

    # -------------------------------------------------------------------
    # Declaration dispatch
    # -------------------------------------------------------------------

    def _emit_declaration(
        self,
        decl: NerveDecl
        | CellDecl
        | GanglionDecl
        | TestDecl
        | StandaloneAxonDecl
        | HelperDecl
        | IntegrationDecl
        | DocRefDecl
        | DocGuideDecl
        | ExampleDecl,
        module: S0maModule,
    ) -> str:
        """Emit Python code for a single declaration."""
        if isinstance(decl, NerveDecl):
            return self._emit_nerve(decl, module)
        elif isinstance(decl, CellDecl):
            return self._emit_cell(decl, module)
        elif isinstance(decl, StandaloneAxonDecl):
            return self._emit_standalone_axon(decl, module)
        elif isinstance(decl, GanglionDecl):
            return self._emit_ganglion(decl, module)
        elif isinstance(decl, TestDecl):
            return self._emit_test(decl, module)
        elif isinstance(decl, HelperDecl):
            return self._emit_helper(decl, module)
        elif isinstance(decl, IntegrationDecl):
            return self._emit_integration(decl, module)
        elif isinstance(decl, DocRefDecl):
            return self._emit_doc_ref(decl, module)
        elif isinstance(decl, DocGuideDecl):
            return self._emit_doc_guide(decl, module)
        elif isinstance(decl, ExampleDecl):
            return self._emit_example(decl, module)
        return ""

    # -------------------------------------------------------------------
    # Nerve emission (§2.2.2)
    # -------------------------------------------------------------------

    def _inject_deferred_imports(self, body: str) -> str:
        """Inject ``deferred_requires:`` imports into consuming def bodies.

        DSL-M2 (0.8.0, ADR-011 §(c)): entries in ``deferred_requires:``
        emit NOTHING at module top. For each def in the authored body
        whose BODY references an entry's bound name (the same
        body-reference evidence the vestigial machinery uses), the
        import statement is injected at the top of that def's body —
        after the docstring when present (PEP 257; ``__doc__``
        unaffected), before the first authored statement. Multiple
        consumed entries form one contiguous block in
        ``deferred_requires:`` entry order.

        Injection targets are the OUTERMOST def positions: module-level
        defs and methods at class-body level. References inside nested
        defs count as evidence for their outermost enclosing def — the
        outer def runs at call time, so the injected import covers the
        nested scope. References outside every def body (cell
        assignments, class-scope field defaults, decorator expressions)
        are not injectable; ``DEFERRED_IMPORT_MODULE_SCOPE`` rejects
        them at check time, and this method deliberately leaves such
        bodies untouched.

        Validation runs on authored source; this injection is a
        post-validation emitter step, so ``BARE_IMPORT`` never sees the
        injected lines.
        """
        if not self._deferred_requires or not body:
            return body
        try:
            tree = ast.parse(body)
        except SyntaxError:
            # Malformed bodies are diagnosed by the body extractor /
            # ast.parse build invariant — emit verbatim here.
            return body

        targets: list[ast.FunctionDef | ast.AsyncFunctionDef] = []
        for node in tree.body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                targets.append(node)
            elif isinstance(node, ast.ClassDef):
                targets.extend(
                    sub
                    for sub in node.body
                    if isinstance(sub, (ast.FunctionDef, ast.AsyncFunctionDef))
                )
        if not targets:
            return body

        lines = body.split("\n")
        # Bottom-up so earlier insertions don't shift later positions.
        for node in sorted(
            targets, key=lambda n: n.body[0].lineno, reverse=True,
        ):
            referenced = _def_body_referenced_names(node)
            consumed = [
                entry
                for entry in self._deferred_requires
                if _deferred_local_name(entry) in referenced
            ]
            if not consumed:
                continue
            first = node.body[0]
            is_docstring = (
                isinstance(first, ast.Expr)
                and isinstance(first.value, ast.Constant)
                and isinstance(first.value.value, str)
            )
            if is_docstring:
                # After the docstring (its end line is 1-based; list
                # index end_lineno IS the line after it).
                insert_at = first.end_lineno or first.lineno
                anchor = node.body[1] if len(node.body) > 1 else first
            else:
                insert_at = first.lineno - 1
                anchor = first
            indent = " " * anchor.col_offset
            lines[insert_at:insert_at] = [
                indent + _requires_to_import_line(entry)
                for entry in consumed
            ]
        return "\n".join(lines)

    def _emit_nerve(self, nerve: NerveDecl, module: S0maModule) -> str:
        """Emit a @component-decorated function or class for a nerve declaration.

        Maps DSL fields to @component parameters per PRD §2.2.2.
        SERVICE and ADAPTER nerves may have class bodies, which are emitted
        with a dict-compatible factory wrapper for backward compatibility.
        Abstract nerves without a body get NotImplementedError stubs for
        each interface method.
        """
        body = self._canonical_body(nerve.body)
        if not body:
            if nerve.abstract and nerve.interface:
                body = self._generate_abstract_stub(nerve)
            else:
                body = f"def {nerve.name}():\n    pass"

        # DSL-M2 (0.8.0, ADR-011 §(c)): deferred imports land inside
        # consuming def bodies (function nerves: the top-level def;
        # class nerves: each consuming method).
        body = self._inject_deferred_imports(body)

        if _is_class_body(body):
            return self._emit_class_nerve(nerve, module, body)
        return self._emit_function_nerve(nerve, module, body)

    def _generate_abstract_stub(self, nerve: NerveDecl) -> str:
        """Generate a stub body raising NotImplementedError for each interface method."""
        stubs: list[str] = []
        for method in nerve.interface:
            stubs.append(f"    def {method}(*args, **kwargs):")
            stubs.append(f"        raise NotImplementedError(\"{method}\")")
            stubs.append("")
        stub_body = "\n".join(stubs).rstrip()
        return f"def {nerve.name}():\n{stub_body}"

    def _emit_function_nerve(
        self, nerve: NerveDecl, module: S0maModule, body: str,
    ) -> str:
        """Emit a standard @component-decorated function nerve."""
        params = self._build_nerve_decorator_params(nerve)

        decorator_lines = ["@component("]
        decorator_lines.extend(params)
        decorator_lines.append(")")

        lines = decorator_lines + [body]
        lines.extend(_serves_as_stamp_lines(nerve))
        return "\n".join(lines)

    def _emit_class_nerve(
        self, nerve: NerveDecl, module: S0maModule, body: str,
    ) -> str:
        """Emit a class-based nerve with a dict-compatible factory wrapper.

        The user-authored class is renamed to ``_<Name>Impl``. A factory
        function with the original name is decorated with ``@component``
        and returns a dict mapping public method names to bound methods,
        preserving the ``service["method"](args)`` calling convention.
        """
        class_name = _extract_class_name(body)
        impl_name = f"_{nerve.name}Impl"

        renamed_body = _rename_class(body, class_name, impl_name)

        init_params = _extract_init_params(body)
        factory_params = ", ".join(init_params) if init_params else "*args, **kwargs"
        factory_args = ", ".join(
            p.split(":")[0].split("=")[0].strip() for p in init_params
        ) if init_params else "*args, **kwargs"

        # Build the method dict from provides or public methods
        if nerve.provides:
            dict_entries = "\n".join(
                f'        "{m}": instance.{m},' for m in nerve.provides
            )
            dict_body = f"{{\n{dict_entries}\n    }}"
        else:
            public_methods = _extract_public_methods(body)
            if public_methods:
                dict_entries = "\n".join(
                    f'        "{m}": instance.{m},' for m in public_methods
                )
                dict_body = f"{{\n{dict_entries}\n    }}"
            else:
                dict_body = (
                    "{\n"
                    "        name: getattr(instance, name)\n"
                    "        for name in dir(instance)\n"
                    "        if not name.startswith(\"_\") and callable(getattr(instance, name))\n"
                    "    }"
                )

        params = self._build_nerve_decorator_params(nerve)

        lines: list[str] = []
        lines.append(renamed_body)
        lines.append("")
        lines.append("")
        lines.append("@component(")
        lines.extend(params)
        lines.append(")")
        lines.append(f"def {nerve.name}({factory_params}):")
        lines.append(f'    """Dict-compatible factory for {nerve.name}."""')
        lines.append(f"    instance = {impl_name}({factory_args})")
        lines.append(f"    return {dict_body}")
        lines.extend(_serves_as_stamp_lines(nerve))

        return "\n".join(lines)

    def _build_nerve_decorator_params(self, nerve: NerveDecl) -> list[str]:
        """Build @component decorator parameter lines for a nerve."""
        # M14: preserve multi-line metadata verbatim (see _emit_register_module).
        intent = nerve.intent
        kind_ref = _NERVE_KIND_MAP.get(nerve.kind, "ComponentKind.FUNCTION")
        layer_ref = _layer_ref(nerve.layer)

        params: list[str] = [
            f"    name={_py_str_literal(nerve.name)},",
            f"    kind={kind_ref},",
            f"    layer={layer_ref},",
            f"    intent={_py_str_literal(intent)},",
        ]

        contract_parts = self._build_contract_parts(nerve)
        if contract_parts:
            params.append(f"    contracts=Contract({contract_parts}),")

        dep_names = [
            _canonical_dependency_name(axon.target)
            for axon in nerve.depends_on
        ]
        if dep_names:
            dep_list = ", ".join(_py_str_literal(d) for d in dep_names)
            params.append(f"    dependencies=[{dep_list}],")

        metadata = self._build_nerve_metadata(nerve)
        if metadata:
            params.append(f"    metadata={metadata},")

        return params

    def _build_contract_parts(self, nerve: NerveDecl) -> str:
        """Build Contract() constructor arguments from nerve fields."""
        parts: list[str] = []

        if nerve.expects:
            # M14: preserve multi-line metadata verbatim.
            parts.append(
                f"\n        preconditions=[{_py_str_literal(nerve.expects)}]"
            )

        if nerve.guarantees:
            parts.append(
                f"\n        postconditions=[{_py_str_literal(nerve.guarantees)}]"
            )

        # ``none`` and ``pending`` leave ``nerve.forbids`` empty: nothing is
        # emitted for them.
        if nerve.forbids:
            parts.append(_contract_forbids_part(nerve.forbids))

        if nerve.latency_ms is not None:
            parts.append(f"\n        max_latency_ms={nerve.latency_ms}")

        return _join_contract_parts(parts)

    def _build_nerve_metadata(self, nerve: NerveDecl) -> str | None:
        """Build metadata dict for DSL-specific nerve fields."""
        items: list[str] = []

        items.append(f'"visibility": {_py_str_literal(nerve.visibility.value)}')
        items.append(
            f'"evaluates_at": {_py_str_literal(nerve.evaluates_at.value)}'
        )

        if nerve.provides:
            provides_list = ", ".join(_py_str_literal(p) for p in nerve.provides)
            items.append(f'"provides": [{provides_list}]')

        # POST-3a (0.15.0): emit ``provides_contracts`` as a list-of-dicts
        # when at least one ``provides:`` entry carries a per-method
        # ``returns:`` / ``expects:`` / ``guarantees:`` triple. The
        # legacy flat form leaves this key out so emitted modules with
        # bare ``provides: [foo, bar]`` carry no new metadata surface.
        # Consumers (fr3d settings / OAuth nerves) read the dict from
        # the emitted registry to introspect per-method contracts
        # without re-parsing the .s0ma source. Each entry is a Python
        # dict literal keyed by ``"name"`` plus whichever of
        # ``"returns"`` / ``"expects"`` / ``"guarantees"`` the author
        # declared — absent slots are omitted entirely.
        if any(entry.has_triple for entry in nerve.provides_entries):
            entry_dicts: list[str] = []
            for entry in nerve.provides_entries:
                pairs = [f'"name": {_py_str_literal(entry.name)}']
                if entry.returns is not None:
                    pairs.append(f'"returns": {_py_str_literal(entry.returns)}')
                if entry.expects is not None:
                    pairs.append(f'"expects": {_py_str_literal(entry.expects)}')
                if entry.guarantees is not None:
                    pairs.append(f'"guarantees": {_py_str_literal(entry.guarantees)}')
                entry_dicts.append("{" + ", ".join(pairs) + "}")
            items.append(f'"provides_contracts": [{", ".join(entry_dicts)}]')

        if nerve.returns:
            returns_list = ", ".join(_py_str_literal(r) for r in nerve.returns)
            items.append(f'"returns": [{returns_list}]')

        if nerve.raises:
            raises_list = ", ".join(_py_str_literal(r) for r in nerve.raises)
            items.append(f'"raises": [{raises_list}]')

        if nerve.abstract:
            # F7: emit Python boolean literal (True), not JSON-style ``true``.
            # The metadata dict is interpolated into emitted Python source, so
            # bare ``true`` becomes a NameError at import time. See
            # fr3d/docs/s0ma-dsl-feedback-7.md (finding #1).
            items.append('"abstract": True')

        if nerve.interface:
            interface_list = ", ".join(
                _py_str_literal(m) for m in nerve.interface
            )
            items.append(f'"interface": [{interface_list}]')

        # POST-12a (0.16.0): emit ``expected_exceptions`` into the
        # registered metadata so consumers can introspect the Python
        # exception envelope a nerve catches by design without
        # re-parsing the source. Each entry is the dotted Python path
        # exactly as the author wrote it (``json.JSONDecodeError``,
        # ``urllib.error.HTTPError``); the emitter does not resolve
        # the import — the field is metadata, not a binding.
        if nerve.expected_exceptions:
            exc_list = ", ".join(
                _py_str_literal(e) for e in nerve.expected_exceptions
            )
            items.append(f'"expected_exceptions": [{exc_list}]')

        # POST-12f (0.16.0): emit ``deferred`` into the registered
        # metadata so downstream consumers (the ``s0ma deferred-surface``
        # reporter being the motivating one) can enumerate deferred
        # declarations from the registry without scanning .s0ma source.
        if nerve.deferred is not None:
            items.append(f'"deferred": {_py_str_literal(nerve.deferred)}')

        # POST-12d (0.16.0): emit ``consumes_via_dict`` into the
        # registered metadata as a list of dicts ``{"contract": ..., "param": ...}``
        # so the registry exposes the duck-typed coupling surface
        # without consumers having to re-read the .s0ma source. Each
        # entry is the verbatim contract + param identifiers; the
        # field is metadata, not a binding (no import is emitted for
        # the contract name).
        if nerve.consumes_via_dict:
            consumes_dicts: list[str] = []
            for consumes_entry in nerve.consumes_via_dict:
                consumes_pairs = (
                    f'"contract": {_py_str_literal(consumes_entry.contract)}, '
                    f'"param": {_py_str_literal(consumes_entry.param)}'
                )
                consumes_dicts.append("{" + consumes_pairs + "}")
            items.append(
                f'"consumes_via_dict": [{", ".join(consumes_dicts)}]',
            )

        # DSL-M2 (0.8.0, ADR-011 §(e)): external test-evidence credit
        # rides the registered metadata under the reserved
        # ``covered_by`` key so doc-refs (and any registry consumer)
        # render the coverage claim from the registry snapshot without
        # IR access.
        if nerve.covered_by:
            covered_list = ", ".join(
                _py_str_literal(c) for c in nerve.covered_by
            )
            items.append(f'"covered_by": [{covered_list}]')

        # DSL-M1 (0.8.0, ADR-011 §(b)): the public serving name rides
        # the registered metadata under the reserved ``serves_as`` key
        # so registry-deriving consumers (the s0ma-mcp bootstrap bridge
        # being the motivating one) read the served name without IR
        # access. Written BEFORE the authored merge below — it is an
        # emitter-written reserved key, not an authored entry.
        if nerve.serves_as is not None:
            items.append(f'"serves_as": {_py_str_literal(nerve.serves_as)}')

        # DSL-M1 (0.8.0, ADR-011 §(a)): authored ``metadata:`` entries
        # merge into this dict AFTER the emitter-written keys, in
        # authored order. Reserved-key collisions were rejected at
        # validation (``METADATA_RESERVED_KEY``), so the append is safe.
        items.extend(_authored_metadata_items(nerve.metadata))

        return "{" + ", ".join(items) + "}"

    # -------------------------------------------------------------------
    # Cell emission (§2.2.3)
    # -------------------------------------------------------------------

    def _emit_cell(self, cell: CellDecl, module: S0maModule) -> str:
        """Emit code for a cell declaration.

        For MODEL/ENUM/EXCEPTION/CONFIG: @component-decorated class.
        For CONSTANT: bare assignment + register_constant() call.
        For TYPE: bare assignment + register_type() call.
        """
        if cell.kind == Kind.CONSTANT:
            return self._emit_constant_cell(cell)
        elif cell.kind == Kind.TYPE:
            return self._emit_type_cell(cell)
        else:
            return self._emit_class_cell(cell)

    def _emit_class_cell(self, cell: CellDecl) -> str:
        """Emit a @component-decorated class for a cell (MODEL/ENUM/EXCEPTION/CONFIG)."""
        # M14: preserve multi-line metadata verbatim (see _emit_register_module).
        intent = cell.intent
        layer_ref = _layer_ref(cell.layer)

        params: list[str] = [
            f"    name={_py_str_literal(cell.name)},",
            "    kind=ComponentKind.MODEL,",
            f"    layer={layer_ref},",
            f"    intent={_py_str_literal(intent)},",
        ]

        # DSL-specific metadata
        metadata_items: list[str] = [
            f'"visibility": {_py_str_literal(cell.visibility.value)}',
            f'"kind_detail": {_py_str_literal(cell.kind.value)}',
        ]
        if cell.schema:
            metadata_items.append(f'"schema": {_py_str_literal(cell.schema)}')
        if cell.invariants:
            metadata_items.append(f'"invariants": {_py_str_literal(cell.invariants)}')
        # POST-2 (0.15.0): surface ``category: capability | behaviour`` in
        # the registered metadata so consumers can pivot on it at runtime
        # without re-reading the IR.
        if cell.category:
            metadata_items.append(f'"category": {_py_str_literal(cell.category)}')
        # POST-12f (0.16.0): surface ``deferred:`` reason in metadata so
        # consumers can enumerate stub bodies without re-parsing source.
        if cell.deferred is not None:
            metadata_items.append(f'"deferred": {_py_str_literal(cell.deferred)}')
        # POST-12c (0.16.0): surface ``dataclass_invariants:`` in the
        # registered metadata so downstream introspection consumers
        # (future linters, doc renderers, runtime contract enforcers)
        # can read the declared invariants from the registry without
        # re-parsing the .s0ma source. Each entry is a Python boolean
        # expression preserved verbatim as a string — s0ma does not
        # runtime-evaluate the expressions; consumers that want to
        # enforce them do their own ``eval``.
        if cell.dataclass_invariants:
            inv_list = ", ".join(
                _py_str_literal(inv) for inv in cell.dataclass_invariants
            )
            metadata_items.append(
                f'"dataclass_invariants": [{inv_list}]',
            )

        # DSL-M2 (0.8.0, ADR-011 (e)): reserved ``covered_by`` key —
        # see _build_nerve_metadata.
        if cell.covered_by:
            covered_list = ", ".join(
                _py_str_literal(c) for c in cell.covered_by
            )
            metadata_items.append(f'"covered_by": [{covered_list}]')
        # DSL-M1 (0.8.0): authored ``metadata:`` appends after the
        # emitter-written keys (see _build_nerve_metadata).
        metadata_items.extend(_authored_metadata_items(cell.metadata))

        metadata = "{" + ", ".join(metadata_items) + "}"
        params.append(f"    metadata={metadata},")

        decorator_lines = ["@component("]
        decorator_lines.extend(params)
        decorator_lines.append(")")

        body = self._canonical_body(cell.body)
        if not body:
            body = f"class {cell.name}:\n    pass"

        # DSL-M2 (0.8.0, ADR-011 §(c)): a class cell's METHOD bodies
        # run at call time, so they may consume deferred imports;
        # class-scope references were rejected at check time
        # (DEFERRED_IMPORT_MODULE_SCOPE).
        body = self._inject_deferred_imports(body)

        lines = decorator_lines + [body]
        return "\n".join(lines)

    def _emit_constant_cell(self, cell: CellDecl) -> str:
        """Emit a constant assignment + register_constant() call."""
        # M14: preserve multi-line metadata verbatim.
        intent = cell.intent
        layer_ref = _layer_ref(cell.layer)

        # M12 (feedback 5–6): if the cell uses ``content: @file("path")``,
        # synthesise the assignment from the embedded content. We prefer
        # ``r"""..."""`` for readability (the embedded HTML/SQL/prompt is
        # typically already escape-light) but fall through to ``repr()``
        # when ``"""`` appears in the content — the M2 ``ast.parse``
        # build invariant catches anything we get wrong.
        if cell.embedded_content is not None:
            body = (
                f"{cell.name} = "
                f"{_embedded_content_literal(cell.embedded_content)}"
            )
        else:
            body = self._canonical_body(cell.body)
            if not body:
                body = f"{cell.name} = None"

        # Schema and metadata. M14: preserve multi-line metadata verbatim.
        metadata_items: list[str] = [
            f'"visibility": {_py_str_literal(cell.visibility.value)}'
        ]
        if cell.schema:
            metadata_items.append(f'"schema": {_py_str_literal(cell.schema)}')
        # POST-2 (0.15.0): emit ``category`` into the registered metadata.
        if cell.category:
            metadata_items.append(f'"category": {_py_str_literal(cell.category)}')
        # POST-12f (0.16.0): emit ``deferred:`` reason into metadata.
        if cell.deferred is not None:
            metadata_items.append(f'"deferred": {_py_str_literal(cell.deferred)}')
        # DSL-M2 (0.8.0, ADR-011 (e)): reserved ``covered_by`` key —
        # see _build_nerve_metadata.
        if cell.covered_by:
            covered_list = ", ".join(
                _py_str_literal(c) for c in cell.covered_by
            )
            metadata_items.append(f'"covered_by": [{covered_list}]')
        # DSL-M1 (0.8.0): authored ``metadata:`` appends after the
        # emitter-written keys (see _build_nerve_metadata).
        metadata_items.extend(_authored_metadata_items(cell.metadata))

        metadata = "{" + ", ".join(metadata_items) + "}"

        reg_lines = [
            "",
            "register_constant(",
            f"    name={_py_str_literal(cell.name)},",
            f"    module_path={_py_str_literal(self.module_name)},",
            f"    layer={layer_ref},",
            f"    intent={_py_str_literal(intent)},",
        ]
        # The constant's literal rides the registration as ``value=`` when
        # the body assigns one (same rule as the IR's ``fields.value``, see
        # ``s0ma_dsl.ir.constant_values``), so the registry carries the
        # value the build saw. It is written as the JSON-shaped literal the
        # IR holds, tuples as lists, so the two surfaces agree byte for
        # byte on what the constant is.
        has_value, value = constant_literal(cell)
        if has_value:
            reg_lines.append(f"    value={_constant_value_literal(value)},")
        reg_lines.extend([
            f"    metadata={metadata},",
            ")",
        ])

        return body + "\n".join(reg_lines)

    def _emit_type_cell(self, cell: CellDecl) -> str:
        """Emit a type alias + register_type() call."""
        # M14: preserve multi-line metadata verbatim.
        intent = cell.intent
        layer_ref = _layer_ref(cell.layer)

        body = self._canonical_body(cell.body)
        if not body:
            body = f"{cell.name} = None"

        metadata_items: list[str] = [
            f'"visibility": {_py_str_literal(cell.visibility.value)}'
        ]
        if cell.schema:
            metadata_items.append(f'"schema": {_py_str_literal(cell.schema)}')
        # POST-2 (0.15.0): emit ``category`` into the registered metadata.
        if cell.category:
            metadata_items.append(f'"category": {_py_str_literal(cell.category)}')
        # POST-12f (0.16.0): emit ``deferred:`` reason into metadata.
        if cell.deferred is not None:
            metadata_items.append(f'"deferred": {_py_str_literal(cell.deferred)}')
        # DSL-M2 (0.8.0, ADR-011 (e)): reserved ``covered_by`` key —
        # see _build_nerve_metadata.
        if cell.covered_by:
            covered_list = ", ".join(
                _py_str_literal(c) for c in cell.covered_by
            )
            metadata_items.append(f'"covered_by": [{covered_list}]')
        # DSL-M1 (0.8.0): authored ``metadata:`` appends after the
        # emitter-written keys (see _build_nerve_metadata).
        metadata_items.extend(_authored_metadata_items(cell.metadata))
        metadata = "{" + ", ".join(metadata_items) + "}"

        reg_lines = [
            "",
            "register_type(",
            f"    name={_py_str_literal(cell.name)},",
            f"    module_path={_py_str_literal(self.module_name)},",
            f"    layer={layer_ref},",
            f"    intent={_py_str_literal(intent)},",
            f"    metadata={metadata},",
            ")",
        ]

        return body + "\n".join(reg_lines)

    # -------------------------------------------------------------------
    # Standalone axon emission (§2.2.6)
    # -------------------------------------------------------------------

    def _emit_standalone_axon(
        self, axon: StandaloneAxonDecl, module: S0maModule
    ) -> str:
        """Emit a register_relationship() call for a standalone axon."""
        # M14: preserve multi-line metadata verbatim.
        intent = axon.intent

        # Resolve target canonical ID
        target_canonical = self._resolve_axon_target(axon.target, module)

        lines = [
            f"# Standalone axon: {axon.source} -> {axon.target}",
            "register_relationship(",
            f"    source={_py_str_literal(f'{self.module_name}::{axon.source}')},",
            f"    target={_py_str_literal(target_canonical)},",
            f"    relation={_py_str_literal(axon.relation.value)},",
            f"    intent={_py_str_literal(intent)},",
            f"    carries={_py_str_literal(axon.carries)},",
            f"    coupling={_py_str_literal(axon.coupling.value)},",
            ")",
        ]
        return "\n".join(lines)

    def _resolve_axon_target(
        self, target: str, module: S0maModule
    ) -> str:
        """Resolve a standalone axon target to a canonical ID.

        Uses the same resolution logic as the IR builder:
        1. If qualified (contains dot), convert to canonical.
        2. If matches a uses entry, use its canonical ID.
        3. Otherwise, local reference.
        """
        if "." in target:
            parts = target.rsplit(".", 1)
            return f"{parts[0]}::{parts[1]}"

        # Check uses entries
        for uses in module.module.uses:
            local_name = uses.alias
            if local_name is None and "." in uses.qualified_name:
                local_name = uses.qualified_name.rsplit(".", 1)[1]
            elif local_name is None:
                local_name = uses.qualified_name
            if local_name == target:
                qn = uses.qualified_name
                if "." in qn:
                    parts = qn.rsplit(".", 1)
                    return f"{parts[0]}::{parts[1]}"
                return qn

        return f"{self.module_name}::{target}"

    # -------------------------------------------------------------------
    # Ganglion emission (§2.2.4, M12)
    # -------------------------------------------------------------------

    def _emit_ganglion(
        self, ganglion: GanglionDecl, module: S0maModule
    ) -> str:
        """Emit a @component-decorated function for a ganglion declaration.

        Includes evaluator-specific metadata with resolved observes
        patterns (if project context is available) per PRD §2.2.4.
        """
        # M14: preserve multi-line metadata verbatim.
        intent = ganglion.intent
        layer_ref = _layer_ref(ganglion.layer)

        params: list[str] = [
            f"    name={_py_str_literal(ganglion.name)},",
            "    kind=ComponentKind.SERVICE,",
            f"    layer={layer_ref},",
            f"    intent={_py_str_literal(intent)},",
        ]

        # ``forbids:`` is the one contract line a ganglion carries. It takes
        # the position and layout the nerve emitter gives ``contracts=``;
        # ``none`` and ``pending`` leave ``ganglion.forbids`` empty and emit
        # nothing.
        contract_parts = _join_contract_parts(
            [_contract_forbids_part(ganglion.forbids)] if ganglion.forbids else []
        )
        if contract_parts:
            params.append(f"    contracts=Contract({contract_parts}),")

        # Dependencies from depends_on
        dep_names = [
            _canonical_dependency_name(axon.target)
            for axon in ganglion.depends_on
        ]
        if dep_names:
            dep_list = ", ".join(_py_str_literal(d) for d in dep_names)
            params.append(f"    dependencies=[{dep_list}],")

        # Build evaluator-specific metadata
        metadata_items: list[str] = [
            f'"visibility": {_py_str_literal(ganglion.visibility.value)}',
            f'"scope": {_py_str_literal(ganglion.scope.value)}',
        ]

        # Include resolved observes if available, otherwise raw patterns
        resolved = self._resolved_observes.get(ganglion.name)
        if resolved:
            # Collect all resolved canonical IDs
            all_targets: list[str] = []
            for r in resolved:
                all_targets.extend(r.resolved_targets)
            all_targets_sorted = sorted(set(all_targets))
            targets_repr = (
                "["
                + ", ".join(_py_str_literal(t) for t in all_targets_sorted)
                + "]"
            )
            metadata_items.append(f'"resolved_observes": {targets_repr}')
            # Also include original patterns for traceability
            patterns_repr = (
                "["
                + ", ".join(_py_str_literal(p) for p in ganglion.observes)
                + "]"
            )
            metadata_items.append(f'"observes_patterns": {patterns_repr}')
        else:
            observes_repr = (
                "["
                + ", ".join(_py_str_literal(o) for o in ganglion.observes)
                + "]"
            )
            metadata_items.append(f'"observes": {observes_repr}')

        # Include priors and on_anomaly. M14: preserve multi-line content.
        metadata_items.append(f'"priors": {_py_str_literal(ganglion.priors)}')
        metadata_items.append(
            f'"on_anomaly": {_py_str_literal(ganglion.on_anomaly)}'
        )

        # POST-12f (0.16.0): surface ``deferred:`` reason in metadata.
        if ganglion.deferred is not None:
            metadata_items.append(
                f'"deferred": {_py_str_literal(ganglion.deferred)}'
            )

        # DSL-M2 (0.8.0, ADR-011 (e)): reserved ``covered_by`` key —
        # see _build_nerve_metadata.
        if ganglion.covered_by:
            covered_list = ", ".join(
                _py_str_literal(c) for c in ganglion.covered_by
            )
            metadata_items.append(f'"covered_by": [{covered_list}]')
        # DSL-M1 (0.8.0): authored ``metadata:`` appends after the
        # emitter-written keys (see _build_nerve_metadata).
        metadata_items.extend(_authored_metadata_items(ganglion.metadata))

        metadata = "{" + ", ".join(metadata_items) + "}"
        params.append(f"    metadata={metadata},")

        decorator_lines = ["@component("]
        decorator_lines.extend(params)
        decorator_lines.append(")")

        body = self._canonical_body(ganglion.body)
        if not body:
            body = f"def {ganglion.name}():\n    pass"

        # DSL-M2 (0.8.0, ADR-011 §(c)): deferred-import injection.
        body = self._inject_deferred_imports(body)

        return "\n".join(decorator_lines + [body])

    # -------------------------------------------------------------------
    # Test emission (§2.2.5, M12)
    # -------------------------------------------------------------------

    def _emit_test(self, test: TestDecl, module: S0maModule) -> str:
        """Emit a pytest-compatible test function with register_test() call.

        Per PRD §2.2.5, tests are emitted as pytest-discoverable functions
        with verification relationship registration via register_test().
        """
        body = self._canonical_body(test.body)
        if not body:
            body = f"def {test.name}():\n    pass"

        # DSL-M2 (0.8.0, ADR-011 §(c)): deferred-import injection.
        body = self._inject_deferred_imports(body)

        # Comment indicating which components this test validates
        tests_list = ", ".join(test.tests)
        comment = f"# Test: validates {tests_list}"

        # register_test() call for runtime test registration. M14:
        # preserve multi-line metadata verbatim.
        intent = test.intent
        validates_items = ", ".join(_py_str_literal(t) for t in test.tests)

        reg_lines = [
            "",
            "",
            "# Register test verification relationship",
            "register_test(",
            f"    name={_py_str_literal(f'{self.module_name}::{test.name}')},",
            f"    intent={_py_str_literal(intent)},",
            f"    validates=[{validates_items}],",
            ")",
        ]

        return f"{comment}\n{body}" + "\n".join(reg_lines)

    # -------------------------------------------------------------------
    # Helper emission (M13, feedback 5–6)
    # -------------------------------------------------------------------

    def _emit_helper(self, helper: HelperDecl, module: S0maModule) -> str:
        """Emit a helper declaration as a plain module-scope ``def`` or ``class``.

        M13 (feedback 5–6): helpers are module-private functions that are
        introspectable via ``s0ma inspect`` (their declaration appears in
        the IR's ``helpers`` array) but are *not* registered as
        components. Codegen therefore emits a plain ``def`` (or
        ``class``, per POST-4a) with no ``@component`` decorator and no
        ``register_*()`` call.

        A short comment above the body records the helper's intent so
        that readers of the generated ``.py`` see the same explanation
        the IR does. The body itself is dedented and emitted verbatim;
        M2's ``ast.parse`` invariant runs against the full emitted
        module so any malformed helper body is caught at build time.

        POST-4a (0.15.0): class-bodied helpers emit as plain
        ``class <Name>:`` — no decorator, no ``register_*`` call. The
        ``body_kind`` field on :class:`HelperDecl` distinguishes the
        two shapes; the comment header is the same in both cases.

        POST-4b (0.15.0): inline helpers (``inline=True``) emit
        exactly like block-form function helpers — a ``# Helper:`` line
        followed by the single-line ``def``. The shorthand is purely
        a parser-level surface.
        """
        body = self._canonical_body(helper.body)
        if not body:
            # Defensive: the parser already errors on a missing body, so
            # this branch is unreachable in practice. Kept for symmetry
            # with _emit_nerve / _emit_test.
            body = f"def {helper.name}():\n    pass"

        # DSL-M2 (0.8.0, ADR-011 §(c)): deferred-import injection.
        body = self._inject_deferred_imports(body)

        # Helper intent is rendered as a single-line ``# Helper: ...``
        # comment, so collapse whitespace here. The IR retains the full
        # multi-line value; this collapse is purely cosmetic for the
        # generated ``.py`` comment which must fit on one line.
        intent = " ".join(helper.intent.split())
        comment = f"# Helper: {intent}"
        return f"{comment}\n{body}"

    # -------------------------------------------------------------------
    # Integration emission (POST-5, 0.16.0)
    # -------------------------------------------------------------------

    def _emit_integration(
        self, integ: IntegrationDecl, module: S0maModule,
    ) -> str:
        """Emit four auto-emitted helpers for an ``integration`` declaration.

        Each integration declaration produces four module-scoped helper
        functions registered via :func:`register_integration_helper`:

        * ``get_factory()`` — wraps the named SERVICE-kind factory nerve
          and returns whatever the factory returns (typically a dict of
          callables). Module-scoped registration leverages the s0ma-core
          ``module_scoped=True`` flag so two integrations in different
          modules can share the helper name without registry collision.
        * ``get_manifest() -> dict`` — returns the declaration's
          ``manifest:`` dict literal verbatim. Downstream consumers
          (the orchestration layer) read the manifest at integration
          time without parsing the .s0ma source.
        * ``smoke_test_primary()`` — wraps the named smoke-test nerve.
          The wrapper preserves the original return value.
        * ``get_smoke_test() -> Callable`` — returns the
          ``smoke_test_primary`` callable so an orchestrator can hold
          a reference, run it lazily, or compose it.

        The four helpers are *not* registered with the ``@component``
        decorator because the decorator does not expose
        ``module_scoped``. Instead, a thin runtime-bridge helper
        (``register_integration_helper``) constructs the ComponentSpec
        directly with ``module_scoped=True`` and attaches it to the
        function as ``__component__``.

        The integration's ``intent:`` field flows into every helper's
        intent (suffixed with a per-helper qualifier so each spec
        carries a distinctive description). The integration's
        ``manifest:`` rides through the registered spec's ``metadata``
        dict under ``"integration_manifest"`` so the runtime can
        introspect manifest details without re-emitting the .s0ma
        source.
        """
        # Collapse intent whitespace for single-line use in registrations.
        base_intent = " ".join(integ.intent.split())
        manifest_literal = _format_dict(dict(integ.manifest), indent="    ")
        module_path_lit = _py_str_literal(module.module.name)
        integ_name_lit = _py_str_literal(integ.name)

        # Each helper's intent is the integration's intent plus a
        # per-helper qualifier so the registry shows distinct prose
        # rather than four identical entries.
        intents = {
            "get_factory": f"Auto-emitted factory accessor for integration "
            f"'{integ.name}'. {base_intent}",
            "get_manifest": f"Auto-emitted manifest accessor for integration "
            f"'{integ.name}'. {base_intent}",
            "smoke_test_primary": f"Auto-emitted smoke-test wrapper for integration "
            f"'{integ.name}'. {base_intent}",
            "get_smoke_test": f"Auto-emitted smoke-test accessor for integration "
            f"'{integ.name}'. {base_intent}",
        }

        # The common metadata dict carried on each helper's
        # ComponentSpec. Authors querying the registry can ask "what
        # integration does this helper belong to?" via the
        # ``"integration"`` key, and "what does the integration
        # advertise?" via the ``"integration_manifest"`` key.
        metadata_dict = {
            "integration": integ.name,
            "integration_manifest": dict(integ.manifest),
            "integration_helper": True,
        }
        metadata_literal = _format_dict(metadata_dict, indent="    ")

        lines: list[str] = []
        lines.append(f"# Integration: {integ.name} — {base_intent}")

        # Authors may attach an optional body to the integration. The
        # body is emitted verbatim before the four helpers so any
        # supporting declarations (constants, inline helpers, etc.) the
        # author included flow through unchanged.
        body = self._canonical_body(integ.body)
        if body:
            lines.append(body)

        # get_factory()
        lines.append("")
        lines.append("def get_factory():")
        lines.append(
            f'    """Return the constructed factory for {integ.name}."""'
        )
        lines.append(f"    return {integ.factory}()")
        lines.append("register_integration_helper(")
        lines.append("    get_factory,")
        lines.append("    name=\"get_factory\",")
        lines.append(f"    intent={_py_str_literal(intents['get_factory'])},")
        lines.append(f"    module_path={module_path_lit},")
        lines.append(f"    metadata={metadata_literal},")
        lines.append(")")

        # get_manifest()
        lines.append("")
        lines.append("def get_manifest():")
        lines.append(
            f'    """Return the manifest dict declared on {integ.name}."""'
        )
        lines.append(f"    return {manifest_literal}")
        lines.append("register_integration_helper(")
        lines.append("    get_manifest,")
        lines.append("    name=\"get_manifest\",")
        lines.append(f"    intent={_py_str_literal(intents['get_manifest'])},")
        lines.append(f"    module_path={module_path_lit},")
        lines.append(f"    metadata={metadata_literal},")
        lines.append(")")

        # smoke_test_primary()
        lines.append("")
        lines.append("def smoke_test_primary(*args, **kwargs):")
        lines.append(
            f'    """Invoke the smoke_test_primary for {integ.name}."""'
        )
        lines.append(
            f"    return {integ.smoke_test_primary}(*args, **kwargs)"
        )
        lines.append("register_integration_helper(")
        lines.append("    smoke_test_primary,")
        lines.append("    name=\"smoke_test_primary\",")
        lines.append(
            f"    intent={_py_str_literal(intents['smoke_test_primary'])},"
        )
        lines.append(f"    module_path={module_path_lit},")
        lines.append(f"    metadata={metadata_literal},")
        lines.append(")")

        # get_smoke_test()
        lines.append("")
        lines.append("def get_smoke_test():")
        lines.append(
            f'    """Return the smoke_test_primary callable for {integ.name}."""'
        )
        lines.append("    return smoke_test_primary")
        lines.append("register_integration_helper(")
        lines.append("    get_smoke_test,")
        lines.append("    name=\"get_smoke_test\",")
        lines.append(
            f"    intent={_py_str_literal(intents['get_smoke_test'])},"
        )
        lines.append(f"    module_path={module_path_lit},")
        lines.append(f"    metadata={metadata_literal},")
        lines.append(")")

        # Module-level marker symbol. The integration declaration's name
        # is exposed as a module attribute that bundles the four
        # auto-emitted helpers — so consumers can write
        # ``uses: [<module>.<IntegrationName>]`` and call
        # ``IntegrationName.get_factory()`` etc. through the imported
        # symbol. Without this, ``from <module> import <IntegrationName>``
        # would ImportError because the four helpers carry the bare names
        # ``get_factory`` / ``get_manifest`` / etc. on the module — not
        # the integration's name. The marker is a thin dict-shape
        # introspection surface (deliberately not a class — sticking to
        # primitives keeps the emit deterministic and pickle-safe).
        lines.append("")
        lines.append(
            "# Integration marker symbol — bundles the four auto-emitted "
            "helpers under the integration's declared name."
        )
        lines.append(f"{integ.name} = {{")
        lines.append('    "get_factory": get_factory,')
        lines.append('    "get_manifest": get_manifest,')
        lines.append('    "smoke_test_primary": smoke_test_primary,')
        lines.append('    "get_smoke_test": get_smoke_test,')
        lines.append(f'    "name": {integ_name_lit},')
        lines.append(f'    "version": {_py_str_literal(integ.version)},')
        lines.append("}")

        return "\n".join(lines)

    # -------------------------------------------------------------------
    # Doc subsystem emission (plan M5)
    # -------------------------------------------------------------------

    def _emit_doc_markers(self, module: S0maModule) -> str:
        """Emit module-level marker attributes for doc declarations.

        The s0ma framework's import hook (``s0ma.import_hook``) inspects
        ``__s0ma_doc_ref__`` / ``__s0ma_doc_guide__`` / ``__s0ma_example__``
        on every imported module and verifies that every listed name was
        actually registered. Emitting these as plain tuples — sorted for
        determinism — makes them usable both as a hook contract and as a
        machine-readable inventory of the module's doc surface.
        """
        lines: list[str] = []
        if module.doc_refs:
            names = ", ".join(_py_str_literal(d.name) for d in module.doc_refs)
            lines.append(f"__s0ma_doc_ref__ = ({names},)")
        if module.doc_guides:
            names = ", ".join(
                _py_str_literal(d.name) for d in module.doc_guides
            )
            lines.append(f"__s0ma_doc_guide__ = ({names},)")
        if module.examples:
            names = ", ".join(_py_str_literal(d.name) for d in module.examples)
            lines.append(f"__s0ma_example__ = ({names},)")
        return "\n".join(lines)

    def _doc_span_filename(self) -> str:
        """Return the filename to bake into doc-* registration source spans.

        Doc registrations participate in the s0ma-core ``content_hash``
        transitive walk; including an absolute path leaks filesystem
        layout into the hash and makes drift detection / golden tests
        non-portable. We normalise to ``basename(self.filename)`` so the
        runtime registration carries the same stable form the M6 hash
        pipeline uses (see ``s0ma_dsl.codegen.doc_emitter.content_hashes``).
        Diagnostics retain ``self.filename`` directly — only what gets
        baked into a stored registration is normalised.
        """
        return os.path.basename(self.filename) if self.filename else ""

    def _emit_doc_ref(
        self, decl: DocRefDecl, module: S0maModule
    ) -> str:
        """Emit a ``register_doc_ref()`` call for a doc-ref declaration.

        Doc-refs have no Python body — they exist only as metadata + a
        renderer-driven output file (M6). The emitted Python is a single
        registration call that the import hook resolves against the
        registry to enforce the marker contract.
        """
        # M14: preserve multi-line metadata verbatim.
        intent = decl.intent
        covers_lines = _format_list_of_dicts(
            [_filter_to_dict(f) for f in decl.covers], indent="    "
        )
        sections_lines = _format_list_of_dicts(
            [_section_to_dict(s) for s in decl.sections], indent="    "
        )
        span = _source_span_repr(
            self._doc_span_filename(), decl.location, indent="    ",
        )
        comment = f"# Doc-ref: {decl.name} ({decl.format} -> {decl.output})"
        digest = ""
        if self.doc_hashes is not None:
            digest = self.doc_hashes.get(("doc-ref", decl.name), "")
        lines = [
            comment,
            "register_doc_ref(",
            f"    name={_py_str_literal(decl.name)},",
            f"    module={_py_str_literal(decl.module_location)},",
            f"    intent={_py_str_literal(intent)},",
            f"    format={_py_str_literal(decl.format)},",
            f"    output={_py_str_literal(decl.output)},",
            f"    covers={covers_lines},",
            f"    sections={sections_lines},",
            # Transitive content hash from s0ma_dsl.codegen.doc_emitter.
            # Falls back to "" for callers that have not opted into the
            # M6 hash pipeline (kept for back-compat with M5 emission
            # paths and unit tests that don't seed a hash index).
            f"    content_hash={_py_str_literal(digest)},",
            f"    source_span={span},",
            ")",
        ]
        return "\n".join(lines)

    def _emit_doc_guide(
        self, decl: DocGuideDecl, module: S0maModule
    ) -> str:
        """Emit a ``register_doc_guide()`` call for a doc-guide declaration.

        The prose body is passed verbatim as a triple-quoted string so the
        runtime registry sees the exact authored text (per plan §M5
        deliverables — "Prose body passed as a string literal").
        """
        # M14: preserve multi-line metadata verbatim.
        intent = decl.intent
        covers_lines = _format_list_of_dicts(
            [_entity_ref_to_dict(r) for r in decl.covers], indent="    "
        )
        examples_lines = _format_list_of_dicts(
            [_entity_ref_to_dict(r) for r in decl.examples], indent="    "
        )
        asserts_lines = _format_list_of_dicts(
            [
                _assert_to_dict(a, self._doc_span_filename(), decl.location)
                for a in decl.asserts
            ],
            indent="    ",
        )
        body_literal = _py_str_literal(decl.prose_body)
        span = _source_span_repr(
            self._doc_span_filename(), decl.location, indent="    ",
        )
        comment = f"# Doc-guide: {decl.name} ({decl.format} -> {decl.output})"
        digest = ""
        if self.doc_hashes is not None:
            digest = self.doc_hashes.get(("doc-guide", decl.name), "")
        lines = [
            comment,
            "register_doc_guide(",
            f"    name={_py_str_literal(decl.name)},",
            f"    module={_py_str_literal(decl.module_location)},",
            f"    intent={_py_str_literal(intent)},",
            f"    format={_py_str_literal(decl.format)},",
            f"    output={_py_str_literal(decl.output)},",
            f"    covers={covers_lines},",
            f"    asserts={asserts_lines},",
            f"    examples={examples_lines},",
            f"    body={body_literal},",
            f"    content_hash={_py_str_literal(digest)},",
            f"    source_span={span},",
            ")",
        ]
        return "\n".join(lines)

    def _emit_example(
        self, decl: ExampleDecl, module: S0maModule
    ) -> str:
        """Emit a ``register_example()`` call for an example declaration.

        The Python body is passed as a string literal — examples are not
        executed at import time. The s0ma example runner (M7) executes
        them in subprocess isolation when explicitly invoked.
        """
        # M14: preserve multi-line metadata verbatim.
        intent = decl.intent
        demonstrates_lines = _format_list_of_dicts(
            [_entity_ref_to_dict(r) for r in decl.demonstrates], indent="    "
        )
        # F1: ``decl.python_body`` is canonical (dedented at parse time).
        body_text = decl.python_body or ""
        body_literal = _py_str_literal(body_text)
        span = _source_span_repr(
            self._doc_span_filename(), decl.location, indent="    ",
        )
        comment = f"# Example: {decl.name} (demonstrates: {len(decl.demonstrates)})"
        lines = [
            comment,
            "register_example(",
            f"    name={_py_str_literal(decl.name)},",
            f"    module={_py_str_literal(decl.module_location)},",
            f"    intent={_py_str_literal(intent)},",
            f"    demonstrates={demonstrates_lines},",
            f"    runs_in={_py_str_literal(decl.runs_in)},",
            f"    body={body_literal},",
            f"    source_span={span},",
            ")",
        ]
        return "\n".join(lines)

    # -------------------------------------------------------------------
    # Pre-resolution helpers (M12)
    # -------------------------------------------------------------------

    def _resolve_all_ganglia(self, module: S0maModule) -> None:
        """Pre-resolve all ganglion observes patterns for this module."""
        if self.project_context is None:
            return

        resolver = ObservesResolver(mode=self.mode, filename=self.filename)

        for ganglion in module.ganglia:
            source_line = ganglion.location.start_line if ganglion.location else 0
            resolved, errors = resolver.resolve_patterns(
                ganglion.observes, self.project_context, source_line
            )
            self._resolved_observes[ganglion.name] = resolved
            self._emit_errors.extend(errors)

            # Determine privileged imports for this ganglion
            all_targets: list[str] = []
            for r in resolved:
                all_targets.extend(r.resolved_targets)

            privileged = determine_privileged_imports(
                current_module_name=self.module_name,
                resolved_canonical_ids=all_targets,
                context=self.project_context,
                import_kind="privileged_observation",
                referenced_in="observes",
            )
            self._privileged_imports.extend(privileged)

    def _resolve_all_tests(self, module: S0maModule) -> None:
        """Pre-determine privileged imports for all test declarations."""
        if self.project_context is None:
            return

        all_components = self.project_context.all_component_names()

        for test in module.tests:
            # Resolve test targets to canonical IDs
            resolved_ids: list[str] = []
            for target_name in test.tests:
                if "::" in target_name:
                    # Already canonical
                    resolved_ids.append(target_name)
                elif "." in target_name:
                    # Qualified: module.component
                    parts = target_name.rsplit(".", 1)
                    resolved_ids.append(f"{parts[0]}::{parts[1]}")
                elif target_name in all_components:
                    _, canonical, _ = all_components[target_name]
                    resolved_ids.append(canonical)
                else:
                    # Local reference
                    resolved_ids.append(f"{self.module_name}::{target_name}")

            privileged = determine_privileged_imports(
                current_module_name=self.module_name,
                resolved_canonical_ids=resolved_ids,
                context=self.project_context,
                import_kind="privileged_verification",
                referenced_in="tests",
            )
            self._privileged_imports.extend(privileged)

        # Deduplicate privileged imports (same component may be referenced
        # by multiple tests or both ganglia and tests)
        seen: set[str] = set()
        unique: list[PrivilegedImportInfo] = []
        for p in sorted(self._privileged_imports, key=lambda x: x.canonical_id):
            if p.canonical_id not in seen:
                seen.add(p.canonical_id)
                unique.append(p)
        self._privileged_imports = unique

    # -------------------------------------------------------------------
    # Body helpers
    # -------------------------------------------------------------------

    def _canonical_body(self, body: str | None) -> str:
        """Return the canonical (already-dedented) body text from the AST.

        F1 (feedback 5–6 follow-up): bodies on AST declarations are
        canonical Python-ready form — the parser dedented them once at
        parse time. Codegen reads them verbatim. ``None``/empty bodies
        return ``""`` so the caller can substitute a stub.

        DSL-M3 (F-M3-8, P-7): body docstrings are normalised to their PEP
        257 ``inspect.cleandoc`` form at emit time so the emitted
        ``__doc__`` is interpreter-independent at the ARTIFACT level.
        CPython 3.13 dedents ``__doc__`` at compile time
        (python/cpython#81283) while ≤3.12 preserves the source
        indentation, so byte-identical emitted code would otherwise serve
        different ``__doc__`` bytes per interpreter (the F-M3-8 CI failure).
        Normalising here — the single chokepoint every body-carrying
        declaration (nerve/cell/ganglion/test/helper) flows through, and
        BEFORE deferred-import injection so the "after the docstring"
        anchor still lands correctly — collapses both raw forms to one
        canonical string in the source itself. This is the plan's one
        deliberate emitted-bytes change to existing projects (L-7).
        """
        if not body:
            return ""
        return _normalize_body_docstrings(body)


# ---------------------------------------------------------------------------
# Module-level helpers
# ---------------------------------------------------------------------------


# DSL-M3 (F-M3-8): the docstring-literal prefixes Python permits — any
# combination of raw / byte / unicode markers before the quote. Byte
# strings (``b"..."``) are never docstrings, but matching the prefix
# defensively keeps the splitter total.
_DOCSTRING_PREFIX_RE = re.compile(r'^([A-Za-z]*)("""|\'\'\'|"|\')')


def _cleandoc_segment_inner(inner: str) -> str:
    """Apply ``inspect.cleandoc``'s whitespace algorithm to SOURCE text.

    *inner* is the raw source between a string literal's quotes (escapes
    NOT resolved). Returns the same text with the cleandoc transformation
    applied to whitespace only — common leading indentation stripped from
    every line after the first, the first line left-stripped, and leading
    / trailing blank lines removed. Operating on the source (rather than
    re-rendering from the parsed value) means escapes and raw-string
    prefixes survive untouched: the ONLY change is whitespace.

    Mirrors the CPython ``inspect.cleandoc`` reference implementation
    (margin via ``sys.maxsize`` over non-first lines) so the resulting
    literal's *value* equals ``inspect.cleandoc(original_value)`` — which
    the caller verifies before trusting it.
    """
    lines = inner.split("\n")
    margin = sys.maxsize
    for line in lines[1:]:
        stripped = line.lstrip()
        if stripped:
            margin = min(margin, len(line) - len(stripped))
    if lines:
        lines[0] = lines[0].lstrip()
    if margin < sys.maxsize:
        for i in range(1, len(lines)):
            lines[i] = lines[i][margin:]
    while lines and not lines[-1].strip():
        lines.pop()
    while lines and not lines[0].strip():
        lines.pop(0)
    return "\n".join(lines)


def _normalize_body_docstrings(body: str) -> str:
    """Rewrite every docstring literal in *body* to its cleandoc form.

    DSL-M3 (F-M3-8, P-7): makes the emitted ``__doc__`` interpreter-
    independent at the artifact level (see :meth:`PythonEmitter._canonical_body`).
    Finds the docstring of the module and of every function / async
    function / class definition in *body*, and replaces each whose value
    is not already cleandoc-normalised with a whitespace-normalised
    literal (escapes and string prefixes preserved — only whitespace
    changes). Replacements are applied end-to-start so byte offsets stay
    valid.

    Safety net: a docstring is only rewritten when re-parsing the new
    literal confirms its value equals ``inspect.cleandoc(original_value)``.
    Any literal whose source-level whitespace transform would not
    reproduce that value exactly (pathological tab / escaped-whitespace
    cases) is left verbatim — correctness beats coverage. Bodies that do
    not parse (rare, but ``_canonical_body`` is not a validator) are
    returned unchanged.
    """
    try:
        tree = ast.parse(body)
    except SyntaxError:
        return body

    targets: list[ast.Constant] = []
    for node in ast.walk(tree):
        if isinstance(
            node,
            (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef),
        ):
            first = node.body[0] if node.body else None
            if (
                isinstance(first, ast.Expr)
                and isinstance(first.value, ast.Constant)
                and isinstance(first.value.value, str)
            ):
                targets.append(first.value)

    if not targets:
        return body

    lines = body.split("\n")
    # End-to-start so earlier replacements do not shift later spans.
    targets.sort(key=lambda n: (n.lineno, n.col_offset), reverse=True)
    for doc in targets:
        # Only str-valued Constants are appended to ``targets`` above
        # (the isinstance(..., str) guard), so this is always a str.
        original_value = cast("str", doc.value)
        cleaned_value = inspect.cleandoc(original_value)
        if cleaned_value == original_value:
            continue  # already normalised — leave the bytes untouched

        segment = ast.get_source_segment(body, doc)
        if segment is None:
            continue
        match = _DOCSTRING_PREFIX_RE.match(segment)
        if match is None:
            continue
        prefix, quote = match.group(1), match.group(2)
        if not segment.endswith(quote):
            continue
        inner = segment[len(prefix) + len(quote): len(segment) - len(quote)]
        new_inner = _cleandoc_segment_inner(inner)
        if new_inner == inner:
            continue
        new_segment = f"{prefix}{quote}{new_inner}{quote}"

        # Safety: only trust the rewrite when the new literal's VALUE is
        # exactly inspect.cleandoc(original) — never silently change a
        # docstring's meaning to save bytes.
        try:
            reparsed = ast.literal_eval(new_segment)
        except (SyntaxError, ValueError):
            continue
        if reparsed != cleaned_value:
            continue

        sl, sc = doc.lineno, doc.col_offset
        el, ec = doc.end_lineno or doc.lineno, doc.end_col_offset or 0
        if sl == el:
            lines[sl - 1] = (
                lines[sl - 1][:sc] + new_segment + lines[sl - 1][ec:]
            )
        else:
            lines[sl - 1] = lines[sl - 1][:sc] + new_segment + lines[el - 1][ec:]
            del lines[sl:el]

    return "\n".join(lines)


def _layer_ref(layer: DslLayer) -> str:
    """Convert a DSL Layer enum to a s0ma Layer reference string."""
    return f"Layer.{layer.value}"


def _is_class_body(body: str) -> bool:
    """Check if dedented body text starts with a class definition."""
    for line in body.split("\n"):
        stripped = line.strip()
        if stripped and not stripped.startswith("#"):
            return stripped.startswith("class ")
    return False


def _extract_class_name(body: str) -> str:
    """Extract the class name from a class-body string using AST."""
    try:
        tree = ast.parse(body)
        for node in ast.iter_child_nodes(tree):
            if isinstance(node, ast.ClassDef):
                return node.name
    except SyntaxError:
        pass
    match = re.match(r"class\s+(\w+)", body.strip())
    return match.group(1) if match else "Impl"


def _rename_class(body: str, old_name: str, new_name: str) -> str:
    """Rename the top-level class definition in body text."""
    return re.sub(
        rf"^(class\s+){re.escape(old_name)}(\s*[\(:])",
        rf"\g<1>{new_name}\2",
        body,
        count=1,
        flags=re.MULTILINE,
    )


def _extract_init_params(body: str) -> list[str]:
    """Extract ``__init__`` parameters (excluding ``self``) from a class body."""
    try:
        tree = ast.parse(body)
    except SyntaxError:
        return []

    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef):
            for item in node.body:
                if isinstance(item, ast.FunctionDef) and item.name == "__init__":
                    params: list[str] = []
                    args = item.args
                    # positional args (skip self)
                    all_args = args.args[1:]  # skip self
                    defaults = args.defaults
                    n_defaults = len(defaults)
                    n_no_default = len(all_args) - n_defaults

                    for i, arg in enumerate(all_args):
                        param = arg.arg
                        if arg.annotation:
                            param += f": {ast.unparse(arg.annotation)}"
                        if i >= n_no_default:
                            default = defaults[i - n_no_default]
                            param += f" = {ast.unparse(default)}"
                        params.append(param)

                    # *args
                    if args.vararg:
                        p = f"*{args.vararg.arg}"
                        if args.vararg.annotation:
                            p += f": {ast.unparse(args.vararg.annotation)}"
                        params.append(p)

                    # **kwargs
                    if args.kwarg:
                        p = f"**{args.kwarg.arg}"
                        if args.kwarg.annotation:
                            p += f": {ast.unparse(args.kwarg.annotation)}"
                        params.append(p)

                    return params
    return []


def _python_string_literal(s: str) -> str:
    """Backwards-compatible alias for :func:`_py_str_literal`.

    Retained because internal callers and tests imported this name from
    early milestones. New code should prefer :func:`_py_str_literal`.
    """
    return _py_str_literal(s)


def _format_list_of_dicts(items: list[dict[str, Any]], indent: str = "    ") -> str:
    """Format a list of dicts as a multi-line Python list literal.

    Empty list → ``[]``. Otherwise, each dict is rendered on its own line
    with the given indent prefix. Keys are sorted for deterministic
    output per PRD §2.5.3.
    """
    if not items:
        return "[]"
    lines = ["["]
    for item in items:
        rendered = _format_dict(item, indent + "    ")
        lines.append(f"{indent}    {rendered},")
    lines.append(f"{indent}]")
    return "\n".join(lines)


def _format_dict(d: dict[str, Any], indent: str) -> str:
    """Format a dict as a single-line or multi-line Python literal.

    Keys are sorted. Values may be primitives, lists, or dicts; nested
    structures recurse. Output is deterministic.
    """
    if not d:
        return "{}"
    parts: list[str] = []
    for key in sorted(d.keys()):
        value = d[key]
        parts.append(f"{_py_str_literal(key)}: {_format_value(value, indent)}")
    return "{" + ", ".join(parts) + "}"


def _format_value(value: Any, indent: str) -> str:
    """Format an arbitrary value as a Python source literal."""
    if value is None:
        return "None"
    if isinstance(value, bool):
        return "True" if value else "False"
    if isinstance(value, (int, float)):
        return repr(value)
    if isinstance(value, str):
        return _py_str_literal(value)
    if isinstance(value, dict):
        return _format_dict(value, indent)
    if isinstance(value, (list, tuple)):
        if not value:
            return "[]"
        rendered = [_format_value(v, indent) for v in value]
        return "[" + ", ".join(rendered) + "]"
    return _py_str_literal(str(value))


def _entity_ref_to_dict(ref: EntityRefAst) -> dict[str, Any]:
    """Convert an EntityRefAst to the runtime-bridge dict shape.

    Maps DSL-side ``kind`` + ``name`` + ``field_path`` onto the s0ma-side
    :class:`EntityRef` schema. The ``field_path`` is preserved as a list
    so the runtime can address dotted-field references; the runtime-bridge
    coercer accepts only ``kind`` + ``name`` + ``module`` today, so the
    ``field_path`` lives in a side-channel key the coercer ignores. This
    keeps the IR and the runtime registration in sync without requiring a
    breaking change to the framework's ``EntityRef`` shape.
    """
    out: dict[str, Any] = {"kind": ref.kind, "name": ref.name}
    if ref.field_path:
        out["field_path"] = list(ref.field_path)
    return out


def _filter_to_dict(fexpr: FilterExprAst) -> dict[str, Any]:
    """Convert a FilterExprAst to the runtime-bridge FilterExpr dict.

    The runtime FilterExpr carries ``target_kind`` + ``predicate`` (string
    form) + ``raw``. The DSL-side AST has structured predicate trees;
    we serialise the predicate to a deterministic single-line form so it
    round-trips and is comparable across runs.
    """
    return {
        "target_kind": fexpr.kind,
        "predicate": _predicate_to_string(fexpr.predicate),
        "raw": fexpr.raw,
    }


def _predicate_to_string(
    pred: BooleanPredicate | ComparisonPredicate | None,
) -> str | None:
    """Serialise a structured predicate AST as a deterministic string."""
    if pred is None:
        return None
    if isinstance(pred, BooleanPredicate):
        if pred.operator == "not" and len(pred.operands) == 1:
            return f"not ({_predicate_to_string(pred.operands[0])})"
        joined = f" {pred.operator} ".join(
            f"({_predicate_to_string(o)})" for o in pred.operands
        )
        return joined
    if isinstance(pred, ComparisonPredicate):
        lhs = pred.lhs
        if isinstance(lhs, tuple):
            lhs_str = ".".join(lhs)
        elif isinstance(lhs, EntityRefAst):
            base = f"{lhs.kind}::{lhs.name}"
            if lhs.field_path:
                base += "." + ".".join(lhs.field_path)
            lhs_str = base
        else:
            lhs_str = str(lhs)
        rhs = pred.rhs
        if isinstance(rhs, tuple):
            rhs_str = "[" + ", ".join(repr(r) for r in rhs) + "]"
        else:
            rhs_str = str(rhs)
        return f"{lhs_str} {pred.operator} {rhs_str}"
    return None


def _section_to_dict(section: SectionAst) -> dict[str, Any]:
    """Convert a SectionAst to the runtime-bridge Section dict.

    The runtime ``Section`` carries ``title`` + ``iterate`` + ``group_by``
    + ``render``. We map the DSL-side discriminated union onto these:

    - bare field-name section → ``title=field_name``, ``iterate=None``,
      ``render={"field": field_name}``.
    - iteration section → ``title=for var in <coll>`` shorthand,
      ``iterate=<collection raw>``, ``group_by=iteration.group_by``,
      ``render={"iteration": <structured>}``.
    """
    if section.field_name is not None:
        return {
            "title": section.field_name,
            "iterate": None,
            "group_by": None,
            "render": {"field": section.field_name},
        }
    it = section.iteration
    if it is None:
        return {"title": "", "iterate": None, "group_by": None, "render": {}}
    coll = it.collection
    if isinstance(coll, FilterExprAst):
        coll_dict = {"type": "filter", "value": _filter_to_dict(coll)}
        coll_repr = coll.raw or coll.kind
    elif isinstance(coll, EntityRefAst):
        coll_dict = {"type": "entity_ref", "value": _entity_ref_to_dict(coll)}
        coll_repr = coll.raw or f"{coll.kind}::{coll.name}"
    else:
        coll_dict = {"type": "unknown", "value": None}
        coll_repr = ""
    return {
        "title": f"for {it.var} in {coll_repr}",
        "iterate": coll_repr,
        "group_by": it.group_by,
        "render": {
            "iteration": {
                "var": it.var,
                "collection": coll_dict,
                "ordered_by": list(it.ordered_by),
                "group_by": it.group_by,
            },
        },
    }


def _assert_to_dict(
    a: AssertComparison | AssertBoolean,
    filename: str,
    base_loc: SourceLocation | None,
) -> dict[str, Any]:
    """Convert an AssertComparison/AssertBoolean to AssertExpr dict shape.

    The runtime ``AssertExpr`` carries ``expression`` + ``source_span``.
    We serialise the structured assert AST as a single-line expression
    string the evaluator can re-parse, and use the enclosing declaration's
    source span when the assert node has no location of its own.
    """
    expression = _assert_to_string(a)
    loc = getattr(a, "location", None) or base_loc
    span_dict = _source_span_dict(filename, loc)
    return {
        "expression": expression,
        "source_span": span_dict,
    }


def _assert_to_string(a: AssertComparison | AssertBoolean) -> str:
    """Serialise a structured assert AST as a deterministic expression string."""
    if isinstance(a, AssertBoolean):
        if a.operator == "not" and len(a.operands) == 1:
            return f"not ({_assert_to_string(a.operands[0])})"
        return f" {a.operator} ".join(
            f"({_assert_to_string(o)})" for o in a.operands
        )
    if isinstance(a, AssertComparison):
        lhs = a.lhs
        base = f"{lhs.kind}::{lhs.name}"
        if lhs.field_path:
            base += "." + ".".join(lhs.field_path)
        rhs = a.rhs
        if isinstance(rhs, tuple):
            rhs_str = "[" + ", ".join(repr(r) for r in rhs) + "]"
        else:
            rhs_str = str(rhs)
        return f"{base} {a.operator} {rhs_str}"
    return ""


def _source_span_dict(filename: str, loc: SourceLocation | None) -> dict[str, Any]:
    """Build a SourceSpan-shaped dict for emission."""
    return {
        "file": filename or "",
        "start_line": loc.start_line if loc else 0,
        "end_line": loc.end_line if loc else 0,
    }


def _source_span_repr(
    filename: str, loc: SourceLocation | None, indent: str = "    "
) -> str:
    """Render a SourceSpan dict literal for inclusion in emitted Python."""
    span = _source_span_dict(filename, loc)
    return _format_dict(span, indent)


def _extract_public_methods(body: str) -> list[str]:
    """Extract public method names (not starting with ``_``) from a class body."""
    try:
        tree = ast.parse(body)
    except SyntaxError:
        return []

    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef):
            methods: list[str] = []
            for item in node.body:
                if (
                    isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef))
                    and not item.name.startswith("_")
                ):
                    methods.append(item.name)
            return methods
    return []


# ---------------------------------------------------------------------------
# Convenience function
# ---------------------------------------------------------------------------


@component(
    name="S0maDSL_emit_python",
    kind=ComponentKind.FUNCTION,
    layer=Layer.FRAMEWORK,
    intent=(
        "Convenience function to generate Python source code from a parsed "
        "S0maModule. Delegates to PythonEmitter. Accepts optional project "
        "context for ganglion/test emission with observes resolution."
    ),
    idempotent=True,
    is_framework=True,
)
def emit_python(
    module: S0maModule,
    *,
    project_context: ProjectContext | None = None,
    mode: StrictnessMode = StrictnessMode.DEV,
    filename: str = "",
    doc_hashes: dict[tuple[str, str], str] | None = None,
) -> str:
    """Generate Python source code from a parsed S0maModule.

    Parameters
    ----------
    module:
        A fully parsed and validated S0maModule.
    project_context:
        Optional project-level context for observes resolution
        and privileged imports.
    mode:
        Strictness mode for error severity.
    filename:
        Source file path for error reporting.

    Returns
    -------
    str
        Valid Python source code.
    """
    emitter = PythonEmitter(
        project_context=project_context,
        mode=mode,
        filename=filename,
        doc_hashes=doc_hashes,
    )
    return emitter.emit(module)
