"""Strictness modes and configuration for the s0ma DSL transpiler.

Implements the four strictness modes (migration, dev, strict, release) that
PRD FR-DSL-6 requires, and the severity matrix that maps each error code to
a severity which may vary by mode. The matrix is authoritative here: the
numbered section this module used to cite for it belonged to the retired
pre-monorepo s0ma-dsl PRD, and the current PRD requires the four modes
without enumerating what each code does in each one.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from s0ma.decorators import component
from s0ma.types import ComponentKind, Layer

__all__ = [
    "StrictnessMode",
    "TranspilerConfig",
    "get_severity",
    "SEVERITY_MATRIX",
    "OUT_OF_MATRIX_CODES_THAT_MUST_STILL_BE_TRACEABLE",
    "ERROR_CODE_DESCRIPTIONS",
]


@component(
    name="S0maDSL_StrictnessMode",
    kind=ComponentKind.MODEL,
    layer=Layer.FRAMEWORK,
    intent=(
        "Enumeration of the four strictness modes that control error severity in the transpiler."
    ),
    idempotent=True,
    is_framework=True,
)
class StrictnessMode(Enum):
    """The four enforcement levels for the transpiler.

    Controls which findings are errors vs. warnings.
    Teams progress from MIGRATION → DEV → STRICT → RELEASE
    without changing the language itself.
    """

    MIGRATION = "migration"
    DEV = "dev"
    STRICT = "strict"
    RELEASE = "release"


# ---------------------------------------------------------------------------
# The severity matrix. Authoritative here — PRD FR-DSL-6 requires the four
# modes; it does not enumerate the per-code severities.
#
# Keys are error codes. Values are dicts mapping StrictnessMode → severity.
# "error" = compilation blocked. "warning" = informational. None = not applicable.
# ---------------------------------------------------------------------------

SEVERITY_MATRIX: dict[str, dict[StrictnessMode, str | None]] = {
    # --- Structural errors: ALWAYS error in ALL modes ---
    "PARSE_ERROR":          dict.fromkeys(StrictnessMode, "error"),
    "SEMANTIC_PENDING_INVALID": dict.fromkeys(StrictnessMode, "error"),
    "SEMANTIC_PENDING_REASON_EMPTY": dict.fromkeys(StrictnessMode, "error"),
    "SEMANTIC_REQUIRED_STATE_OMITTED": dict.fromkeys(StrictnessMode, "error"),
    "SEMANTIC_NONE_NOT_ALLOWED": dict.fromkeys(StrictnessMode, "error"),
    "SEMANTIC_PENDING_NOT_ALLOWED": dict.fromkeys(StrictnessMode, "error"),
    "SEMANTIC_DERIVED_FIELD_AUTHORED": dict.fromkeys(StrictnessMode, "error"),
    # 0.14 M4: reproducible gate impact is computed from the immutable
    # first-contact path anchor, not by promoting this authoring diagnostic.
    # The finding therefore stays advisory in every authoring mode while a
    # caller-pinned score reports its separate gate-relevant count.
    "NEW_FILE_ROSTER_ONLY": dict.fromkeys(StrictnessMode, "warning"),
    # 0.14 M3A: acknowledged semantic debt is visible throughout the
    # authoring ladder and cannot pass a strict/release gate. Because the
    # syntax did not exist before M3A, a strict pending occurrence is newly
    # introduced by definition during this compatibility milestone; M3B
    # owns baseline-aware requiredness enforcement for migrated corpora.
    "SEMANTIC_PENDING_DEBT": {
        StrictnessMode.MIGRATION: "warning",
        StrictnessMode.DEV: "warning",
        StrictnessMode.STRICT: "error",
        StrictnessMode.RELEASE: "error",
    },
    # PRE-7 (0.14.0): block-list grammar diagnostics. Both fire from
    # the parser when a YAML-style ``- item`` block on ``uses:``,
    # ``requires:``, ``exports:``, or ``raises:`` is malformed. They
    # belong with ``PARSE_ERROR`` semantically — a malformed module
    # cannot meaningfully proceed through later passes — so they hold
    # the same always-error severity in every strictness mode.
    "EMPTY_BLOCK_LIST":     dict.fromkeys(StrictnessMode, "error"),
    "INCONSISTENT_BLOCK_LIST_INDENT": dict.fromkeys(StrictnessMode, "error"),
    # POST-3a (0.15.0): structured ``provides:`` grammar diagnostics.
    # Both fire from the parser, never from a validator pass, so they
    # share the always-error semantics of the PRE-7 block-list codes —
    # a malformed ``provides:`` block cannot proceed through the rest
    # of the pipeline.
    "MIXED_PROVIDES_FORMS": dict.fromkeys(StrictnessMode, "error"),
    "DUPLICATE_PROVIDES_NAME": dict.fromkeys(StrictnessMode, "error"),
    "MISSING_FIELD":        dict.fromkeys(StrictnessMode, "error"),
    "INVALID_KIND":         dict.fromkeys(StrictnessMode, "error"),
    "VISIBILITY_MISMATCH":  dict.fromkeys(StrictnessMode, "error"),
    "LAYER_MISMATCH":       dict.fromkeys(StrictnessMode, "error"),
    "NAMESPACE_COLLISION":  dict.fromkeys(StrictnessMode, "error"),
    "INVALID_AXON_RELATION": dict.fromkeys(StrictnessMode, "error"),
    "INVALID_RAISES_TARGET": dict.fromkeys(StrictnessMode, "error"),
    "DUPLICATE_DECLARATION": dict.fromkeys(StrictnessMode, "error"),
    "INVALID_VERSION":      dict.fromkeys(StrictnessMode, "error"),
    "CLASS_BODY_IN_NERVE":  dict.fromkeys(StrictnessMode, "error"),
    # M4 (feedback 5–6): the source filename's stem must equal the
    # declared module name. Hard invariant — error in every mode —
    # because the module name is the canonical identity (cache key,
    # `uses:` import path) and a mismatch produces silent broken
    # imports at runtime. See ADR-006.
    "MODULE_NAME_STEM_MISMATCH": dict.fromkeys(StrictnessMode, "error"),
    # M5 (feedback 5–6): a bare test target that matches components in
    # multiple modules is ambiguous — the dependency resolver cannot
    # know which one the author intended. Always an error: a real
    # ambiguity is a correctness bug, not a style preference (same
    # precedent as MODULE_NAME_STEM_MISMATCH). Remediation is to
    # qualify the target with its owning module name. See ADR-006 /
    # plan M5.
    "AMBIGUOUS_TEST_TARGET": dict.fromkeys(StrictnessMode, "error"),
    # M8 (feedback 5–6): a production module attempts to consume a
    # ``visibility: TEST`` component cross-module. ``TEST`` visibility
    # is the third declarative level — it grants test modules in any
    # project module access while still hiding the component from
    # production cross-module callers. A production module reaching
    # for a TEST-visibility nerve is a hard correctness violation: the
    # access-control matrix is the load-bearing contract, and getting
    # it wrong undermines the whole point of the visibility model.
    # Always an error in every mode (see ADR-008 / plan M8).
    "TEST_VISIBILITY_VIOLATION": dict.fromkeys(StrictnessMode, "error"),
    # M9 (feedback 5–6): cross-module ``uses:`` declarations that target
    # a higher layer than the consuming module. Layer discipline is one
    # of s0ma's load-bearing architectural promises (the M14 audit case
    # — three real violations slipped through 13 milestones because the
    # validator only enforced layer rules within a module, not across
    # ``uses:`` declarations). Severity ladders with mode: warning in
    # migration/dev (so authors see violations as they develop), error
    # in strict and release (so the violations cannot ship). See plan
    # M9 + feedback-5.5 lines 1157–1177.
    "CROSS_LAYER_DEPENDENCY": {
        StrictnessMode.MIGRATION: "warning",
        StrictnessMode.DEV: "warning",
        StrictnessMode.STRICT: "error",
        StrictnessMode.RELEASE: "error",
    },
    "PARSE_DOC_REF_BODY_PROHIBITED": dict.fromkeys(StrictnessMode, "error"),
    # G6 (feedback 5–6 cleanup): two source files in the same project
    # both declare ``module <name>`` for the same name. The cross-module
    # resolver, the cache, the IR's module index, and the doc registry
    # all key on the declared module name; two files claiming the same
    # name produces undefined behaviour at every downstream stage. The
    # diagnostic names both files so the author can rename one. Always
    # an error in every mode — same load-bearing identity invariant
    # as ``MODULE_NAME_STEM_MISMATCH``: silent precedence rules
    # ("first file wins", "alphabetical", etc.) would obscure the
    # author's intent. See plan G6 / cli/main.py and cli/docs_commands.py
    # for the six emit sites (every multi-module ingestion path covers
    # the case).
    "MODULE_NAME_COLLISION": dict.fromkeys(StrictnessMode, "error"),
    # B1 (0.11.0, batch-01a): subscripting a bare ``uses: [mod]`` module
    # object (``mod["key"]``). Nerve bodies are emitted verbatim, so an
    # author-written subscript of a module object compiles cleanly and
    # crashes at runtime as ``TypeError: 'module' object is not
    # subscriptable``. Always an error in every mode — a guaranteed
    # runtime crash, same load-bearing-correctness family as
    # ``MODULE_NAME_STEM_MISMATCH`` (silent broken runtime). Emit site:
    # ``semantic/validator.py::_check_module_object_subscript``.
    "MODULE_SUBSCRIPT": dict.fromkeys(StrictnessMode, "error"),
    # B3 (0.11.0, batch-01a): a module whose declared name shadows a
    # Python stdlib module (``io``, ``json``, ``csv`` …). The stdlib
    # module is already resident in ``sys.modules`` at interpreter
    # start, so the built module cannot be imported by its bare name
    # and cross-module ``uses:`` resolution fails at runtime. Severity
    # ladders with mode (warning in migration/dev so authors see it as
    # they build, error in strict/release because the project will not
    # bootstrap and must not ship) — the ``CROSS_LAYER_DEPENDENCY``
    # precedent. Emit site:
    # ``semantic/validator.py::_check_module_shadows_stdlib``; the
    # scaffold path warns pre-emptively at ``s0ma new module``.
    "MODULE_SHADOWS_STDLIB": {
        StrictnessMode.MIGRATION: "warning",
        StrictnessMode.DEV: "warning",
        StrictnessMode.STRICT: "error",
        StrictnessMode.RELEASE: "error",
    },
    # DSL-M1 (0.8.0, ADR-011 §(a)): authored ``metadata:`` shape
    # diagnostics. All three are error in every mode — they are
    # shape/contract violations of the L-1 value set, not style
    # preferences: an out-of-shape value cannot ride the IR or the
    # emitted registration dict, a duplicate or malformed key has no
    # well-defined dict form, and a reserved-key collision would let
    # authored data overwrite emitter-written registration facts (P-2).
    # Emit site: ``semantic/validator.py::_check_metadata_fields``.
    "METADATA_INVALID_KEY": dict.fromkeys(StrictnessMode, "error"),
    "METADATA_INVALID_VALUE": dict.fromkeys(StrictnessMode, "error"),
    "METADATA_RESERVED_KEY": dict.fromkeys(StrictnessMode, "error"),
    # DSL-M1 (0.8.0, ADR-011 §(b)): ``serves_as:`` contract diagnostics.
    # Error in every mode — a non-identifier served name cannot become
    # the emitted callable's __name__, and served names form one flat
    # namespace per module AND per project build (the collision check
    # runs in the semantic validator for the module scope and in the
    # dependency resolver for the cross-module scope).
    "SERVES_AS_INVALID": dict.fromkeys(StrictnessMode, "error"),
    "SERVES_AS_COLLISION": dict.fromkeys(StrictnessMode, "error"),
    # DSL-M2 (0.8.0, ADR-011 §(c)): ``deferred_requires:`` contract
    # diagnostics. Error in every mode — a target listed in both
    # ``deferred_requires:`` and another requires-family list has two
    # contradictory failure-time choices (import-time vs call-time),
    # and a deferred name consumed at a module-scope execution
    # position (cell body, class scope, decorator expression,
    # parameter default, annotation) is consumed at import time,
    # before any injected in-body import could run — deferral is
    # semantically impossible there. Emit site:
    # ``resolver/dependency.py::_check_deferred_requires_contracts``.
    "DUPLICATE_REQUIRES_ENTRY": dict.fromkeys(StrictnessMode, "error"),
    "DEFERRED_IMPORT_MODULE_SCOPE": dict.fromkeys(StrictnessMode, "error"),
    # DSL-M2 (0.8.0, ADR-011 §(e)): ``covered_by:`` shape diagnostic.
    # Error in every mode — the field is the release gate's external
    # test-evidence credit; an empty list or empty entry would credit
    # coverage with no auditable evidence. Emit site:
    # ``semantic/validator.py::_check_covered_by_fields``.
    "COVERED_BY_EMPTY": dict.fromkeys(StrictnessMode, "error"),
    # G6 (feedback 5–6 cleanup): the doc renderer
    # (``codegen/doc_emitter/renderer.py::render_module_docs``) raised
    # ``DocRenderError`` while rendering a ``doc-ref`` or ``doc-guide``
    # output (e.g. an unsupported ``format:`` / ``output:`` combination).
    # The CLI catches the exception, wraps it as a ``S0maError`` with
    # this code, and surfaces it through the same diagnostic pipeline as
    # validator errors. Always an error in every mode — a renderer that
    # cannot produce its declared output is structurally broken; the
    # build cannot ship the docs in any strictness mode (the alternative,
    # silently dropping the doc, is exactly the failure mode "no silent
    # failures" rules out). Two emit sites: ``cli/main.py::_cmd_build``
    # and ``cli/docs_commands.py::_cmd_check_docs``.
    "DOC_RENDER_ERROR": dict.fromkeys(StrictnessMode, "error"),
    # ADR-013 §4: a `doc-ref` whose `format:` is not one the derived source
    # it covers declares. Always an error in every mode, for exactly the
    # reason `DOC_RENDER_ERROR` above is unconditional: a doc that cannot
    # produce its declared output is structurally broken, and a degraded
    # rendering is worse than a failure — the shape this code replaces was
    # `format: html` over a derived source emitting a heading, an intent,
    # and no content, silently, in every strictness mode. Never a warning.
    # Emit site: `codegen/doc_emitter/derived_sources.py::records_for`,
    # surfaced through the same two CLI catch sites as `DOC_RENDER_ERROR`.
    # Naming boundary (ADR-013 §4): this is the DSL's `DOC_*` namespace;
    # the documentation application's `DOC_*` codes (architecture plan §11)
    # are a separate set in a shared prefix and neither side may take a
    # name the other has.
    "DOC_SOURCE_FORMAT_UNSUPPORTED": dict.fromkeys(StrictnessMode, "error"),
    # G6 (feedback 5–6 cleanup): a nerve declares ``interface: [...]``
    # but is not marked ``abstract: true``. The two fields are
    # contradictory by design — ``interface:`` enumerates the methods a
    # concrete construction MUST implement, which only makes sense on an
    # abstract nerve. Always an error in every mode: the contradiction
    # is structural (no migration runway softens it) and a runtime
    # consumer of the resulting Python would import a class with no
    # interface contract, masking the correctness intent. Single emit
    # site: ``semantic/validator.py::_check_interface_implementations``.
    "INTERFACE_ON_NON_ABSTRACT": dict.fromkeys(StrictnessMode, "error"),
    # G6 (feedback 5–6 cleanup): a concrete nerve declares
    # ``CONSTRUCTS <abstract>`` but its body does not define every
    # method named in the abstract's ``interface:`` list (or has no
    # body at all). The transpiler emits the concrete nerve as a
    # subclass of the abstract; missing methods produce ``NotImplementedError``
    # at runtime when the consumer calls the unimplemented method —
    # the canonical motivating example is a renderer / strategy
    # subclass missing a ``render`` method that the abstract advertises.
    # Always an error in every mode: same load-bearing structural
    # correctness rule as ``CONSTANT_NAME_MISMATCH`` and
    # ``MODULE_NAME_STEM_MISMATCH`` (declared identity must match
    # implemented identity; silent drift is the failure mode the rule
    # exists to prevent). Two emit sites: intra-module check in
    # ``semantic/validator.py::_check_interface_implementations``,
    # cross-module check in ``resolver/dependency.py``.
    "MISSING_INTERFACE_METHODS": dict.fromkeys(StrictnessMode, "error"),
    # G6 (feedback 5–6 cleanup): a nerve declares ``provides: [...]``
    # but its body does not define a ``def`` (or ``async def``) for
    # every name in the list. ``provides:`` is the load-bearing
    # contract the concrete body must satisfy — the codegen emits the
    # nerve's body unchanged and downstream consumers consume the
    # named functions; a missing ``def`` produces a runtime
    # ``AttributeError`` at the call site. Always an error in every
    # mode: same structural correctness invariant as
    # ``MISSING_INTERFACE_METHODS``. Single emit site:
    # ``semantic/validator.py::_check_provides_fields``.
    "MISSING_PROVIDED_FUNCTION": dict.fromkeys(StrictnessMode, "error"),
    # G6 (feedback 5–6 cleanup): a nerve declares ``returns: [k1, k2]``
    # but its body's terminal ``return {...}`` dict literal does not
    # carry a key named ``k1`` (or ``k2``). The ``returns:`` field
    # documents the public contract of the function's return value —
    # downstream consumers (and the doc subsystem's ``{{nerve::X.k1}}``
    # references) trust the named keys are populated. A mismatch
    # produces a runtime ``KeyError`` when the consumer reads the
    # absent key. Always an error in every mode: same structural
    # invariant as ``MISSING_PROVIDED_FUNCTION`` (declared shape must
    # match implemented shape). Single emit site:
    # ``semantic/validator.py::_check_returns_fields``.
    "MISSING_RETURN_KEY": dict.fromkeys(StrictnessMode, "error"),
    # M2: template & assert expression grammars — structural, always error.
    # The grammar already rejects unsupported constructs as
    # TEMPLATE_SYNTAX_ERROR, so M7 retired the dangling
    # UNSUPPORTED_TEMPLATE_CONSTRUCT code (plan M7 subtask 5, option b).
    "TEMPLATE_SYNTAX_ERROR": dict.fromkeys(StrictnessMode, "error"),
    "ASSERT_SYNTAX_ERROR":   dict.fromkeys(StrictnessMode, "error"),
    # M3: prose body parser — raw code blocks are always a structural error;
    # the heuristic "possible unresolved reference" warning fires in every
    # mode except RELEASE, where it promotes to an error (design §6.2).
    "PROSE_RAW_CODE_BLOCK":  dict.fromkeys(StrictnessMode, "error"),
    # M4: doc-subsystem reference resolution & assert evaluation.
    # Structural failures — the referenced component does not exist, is of
    # the wrong kind, or exposes no such field — are always errors. Assert
    # failures are load-bearing by design (§8.4) and also always errors;
    # the weaker "UNEVALUABLE" code surfaces when a field cannot be read
    # and is likewise always an error to prevent silent drift.
    "UNRESOLVED_REFERENCE":  dict.fromkeys(StrictnessMode, "error"),
    "ENTITY_KIND_MISMATCH":  dict.fromkeys(StrictnessMode, "error"),
    "FIELD_NOT_FOUND":       dict.fromkeys(StrictnessMode, "error"),
    "UNREGISTERED_EXAMPLE":  dict.fromkeys(StrictnessMode, "error"),
    "ASSERT_FAILED":         dict.fromkeys(StrictnessMode, "error"),
    "ASSERT_UNEVALUABLE":    dict.fromkeys(StrictnessMode, "error"),
    "NOT_EXPORTED":         dict.fromkeys(StrictnessMode, "error"),
    "DOES_NOT_EXIST":       dict.fromkeys(StrictnessMode, "error"),
    "CIRCULAR_DEPENDENCY":  dict.fromkeys(StrictnessMode, "error"),
    # M10 (feedback 5–6): topological sort detected a cycle in the
    # module dependency graph (uses: edges). Surfaced by the build
    # path's topological-sort step (see resolver.topological) and by
    # `s0ma topo`. Fires defensively when ``CIRCULAR_DEPENDENCY`` (the
    # four-phase resolver's DFS detection) does not run — for example
    # when ``s0ma topo`` is invoked on a project before a full build.
    # Always an error: a cyclic uses: graph cannot be imported in any
    # order, so the build cannot complete with the graph as written.
    # The remediation is the same as for ``CIRCULAR_DEPENDENCY`` —
    # break the cycle via inversion or a shared lower-layer module.
    "MODULE_DEPENDENCY_CYCLE": dict.fromkeys(StrictnessMode, "error"),
    # M12 (feedback 5–6): CONSTANT cells may use ``content: @file("path")``
    # to embed an external file (HTML, SQL, prompt text) by reference
    # rather than inline as a triple-quoted body. The parser resolves the
    # path relative to the .s0ma file's directory and reads the file as
    # UTF-8 at parse time. If the file is missing or unreadable, the
    # parser/check pipeline raises ``EMBEDDED_FILE_NOT_FOUND``. Always an
    # error in every strictness mode: a missing embed is the same kind of
    # silent-broken-build hazard that ``MODULE_NAME_STEM_MISMATCH``
    # guards against — a triple-quoted body that the .s0ma file
    # advertises as present but isn't would produce an undefined-name
    # ``NameError`` at runtime in the consuming module. See plan M12 and
    # the kn0wthyself viz_template.s0ma case (feedback-5 MS 2/3) for the
    # canonical motivating example.
    "EMBEDDED_FILE_NOT_FOUND": dict.fromkeys(StrictnessMode, "error"),
    # M17 (feedback 5–6): a CONSTANT cell whose declaration name does
    # not match the Python identifier its body assigns to. The
    # transpiler emits ``from <module> import <cell_name>``, so a
    # mismatch produces a runtime ``ImportError`` in the consuming
    # module — the canonical motivating example is the kn0wthyself
    # ``cell VizTemplate`` with body ``VIZ_TEMPLATE = '''...'''``
    # (feedback-5 MS 2). The cell name IS the canonical IR identity
    # (same precedent as MODULE_NAME_STEM_MISMATCH and
    # AMBIGUOUS_TEST_TARGET); divergence is a hard correctness
    # violation, not a strictness preference. Always an error in every
    # mode. Cells whose body is supplied via ``content: @file("...")``
    # (M12) are exempt because the codegen synthesises the
    # ``<cell_name> = <literal>`` assignment from the embedded file
    # contents, guaranteeing equality by construction.
    "CONSTANT_NAME_MISMATCH": dict.fromkeys(StrictnessMode, "error"),
    # D3 (beta-prep-1-retrofit): the two refusals that keep a DRAFT from
    # building as though it were finished. ``s0ma adopt draft`` derives a
    # module's structure from existing Python and never invents its
    # meaning, so what it emits carries un-authored fields (marked
    # ``FIXME(adopt):``) and, where it could not place a piece of source
    # in any declaration, a quarantine cell holding that text verbatim
    # (marked ``adopt: unplaced``). Both are error in EVERY mode,
    # migration included — retrofit ruling R-5. That is deliberate and it
    # is the only severity that makes sense: migration exists to let a
    # half-converted project keep working, not to let un-written meaning
    # or un-placed code pass for done. Softening either code to a warning
    # in migration would let `s0ma build` and `s0ma score` credit a draft
    # as a finished module, which is exactly the dishonesty the adoption
    # ladder is built to avoid.
    "ADOPT_PLACEHOLDER_INTENT": dict.fromkeys(StrictnessMode, "error"),
    "ADOPT_UNPLACED_CODE": dict.fromkeys(StrictnessMode, "error"),
    # M13 (feedback 5–6): a production module attempts to consume a
    # ``helper`` declaration cross-module. Helpers are module-private by
    # design — they live at module scope, are not registered as
    # components, but are introspectable via ``s0ma inspect``. Test
    # modules in the project may reach a helper via ``uses:`` (the same
    # carve-out as ``visibility: TEST``); production cross-module access
    # is hard-blocked. Always an error in every strictness mode: the
    # access-control rule is the load-bearing contract that lets helpers
    # exist as a fourth declaration kind without polluting the component
    # graph or the public export surface. See ADR-008 / plan M13.
    "HELPER_PRIVATE_TO_MODULE": dict.fromkeys(StrictnessMode, "error"),
    # POST-4c (0.15.0): the module's ``exports_helpers:`` list names an
    # identifier that is not a helper declaration in this module. The
    # cross-module reachability widener can only point at helpers that
    # exist; pointing at a missing or non-helper name is a hard
    # mis-configuration and produces an error in every mode. The
    # validator emits this code; the parser does not (so authors can
    # still write ``exports_helpers: [_typo]`` and learn from the
    # validator pass).
    "EXPORTED_HELPER_NOT_FOUND": dict.fromkeys(StrictnessMode, "error"),
    # POST-5 (0.16.0): the integration declaration's ``factory:`` field
    # names a nerve that does not exist in the same module. Codegen
    # cannot synthesise ``get_factory()`` without a factory target — the
    # auto-emitted helper would compile but raise ``NameError`` at
    # import. Always an error in every strictness mode (same load-
    # bearing-identity invariant as ``HELPER_PRIVATE_TO_MODULE`` and
    # ``EXPORTED_HELPER_NOT_FOUND``).
    "INTEGRATION_FACTORY_NOT_FOUND": dict.fromkeys(StrictnessMode, "error"),
    # POST-5 (0.16.0): the integration declaration's ``factory:`` field
    # names a nerve that exists but is not ``kind: SERVICE``. The
    # IntegrationManifest pattern only makes sense over a SERVICE
    # factory (which returns a dict of callables); pointing
    # ``factory:`` at a FUNCTION nerve, an ADAPTER nerve, etc. would
    # produce an auto-emitted ``get_factory()`` whose return type
    # doesn't match the integration contract. Always an error.
    "INTEGRATION_FACTORY_NOT_SERVICE": dict.fromkeys(StrictnessMode, "error"),
    # POST-5 (0.16.0): the integration declaration's
    # ``smoke_test_primary:`` field names a nerve that is neither
    # declared in the same module nor reachable via ``uses:``. Codegen
    # cannot synthesise the smoke-test helpers without a target. Always
    # an error.
    "INTEGRATION_SMOKE_TEST_NOT_FOUND": dict.fromkeys(StrictnessMode, "error"),
    # POST-5 (0.16.0): the integration declaration's ``manifest:`` map
    # carries a key whose name violates the basic shape contract — the
    # key is not a valid Python identifier OR the value is a
    # non-JSON-serialisable type. The check is deliberately permissive:
    # any identifier-shaped key with a primitive value (str / int /
    # float / bool / list / dict) is accepted. Always an error because
    # the manifest is the on-the-wire payload returned by the
    # auto-emitted ``get_manifest()``.
    "INTEGRATION_INVALID_MANIFEST_KEY": dict.fromkeys(StrictnessMode, "error"),
    # M18 (feedback 5–6): a nerve's ``declares_attributes:`` entry
    # violates a project-configured budget under
    # ``[tool.s0ma.attribute_budgets]``. Severity depends on the
    # configured shape, not solely on strictness mode:
    # ``exactly_one_per_page`` and ``unique_in_project`` shapes raise
    # an error in dev/strict/release (warning in migration so authors
    # can wire things up); ``warn_on_duplicate`` is always a warning.
    # The shape-specific override is applied by the resolver before
    # consulting this matrix — what we register here is the default
    # severity ladder for the *error*-shaped budgets. The resolver
    # synthesises ``warning``-severity diagnostics directly for the
    # ``warn_on_duplicate`` shape regardless of mode.
    "ATTRIBUTE_BUDGET_VIOLATION": {
        StrictnessMode.MIGRATION: "warning",
        StrictnessMode.DEV: "error",
        StrictnessMode.STRICT: "error",
        StrictnessMode.RELEASE: "error",
    },
    # F3 (feedback 5–6 follow-up): the project configures an
    # ``exactly_one_per_page`` attribute budget but no nerve in the
    # project is marked ``is_page_composer: true``. The
    # ``exactly_one_per_page`` shape requires an explicit page-composer
    # declaration to scope the per-page reachable nerve set; M18's
    # heuristic ("top-level module in the uses: graph") was opaque and
    # silently no-opped when no module qualified. F3 replaces it with
    # explicit declaration and surfaces this configuration error in
    # every mode — silent no-op is forbidden by the principle
    # "no silent failures." Severity is ``error`` in every mode
    # (including migration) because the budget cannot run without a
    # composer; the project is mis-configured, not stylistically lax.
    "NO_PAGE_COMPOSER_DECLARED": dict.fromkeys(StrictnessMode, "error"),
    # G2 (feedback 5–6 cleanup): structural overlap between
    # ``[tool.s0ma].source_roots`` and ``[tool.s0ma].test_roots`` (or
    # within either list). Examples that fire this code:
    #   - a ``test_root`` is a subpath of a ``source_root`` (the
    #     kn0wthyself-website-2 shape — tests live under ``src/<proj>/tests``);
    #   - a ``source_root`` is a subpath of a ``test_root`` (opposite direction);
    #   - two ``source_roots`` (or two ``test_roots``) where one is a
    #     subpath of the other;
    #   - any pair of declared roots that resolve to the same path.
    # When roots overlap, ``_discover_s0ma_files`` walks the same files
    # from both anchors, the cross-module resolver registers each
    # ``module <name>`` declaration twice, and the user gets an opaque
    # ``MODULE_NAME_COLLISION`` against a file colliding with itself —
    # several command invocations downstream from the actual mistake.
    # G2 fires this code at ``S0maProject._from_tool_s0ma`` time with a
    # remediation message naming both offending paths and the two clean
    # configurations the project should choose between (move tests
    # outside the source root, or narrow the source roots to disjoint
    # layer subdirs). Always an error in every mode — silent dedup is
    # explicitly rejected on principles grounds (see plan G2).
    "OVERLAPPING_DISCOVERY_ROOTS": dict.fromkeys(StrictnessMode, "error"),
    # G3 (feedback 5–6 cleanup): the project's ``[project].name`` (or
    # explicit ``[tool.s0ma].build_dir`` last path component) cannot be
    # turned into a valid Python identifier even after sanitizing every
    # non-word character (``\W`` → ``_``). The build-dir derivation is
    # a contract: ``s0ma build`` writes ``<build_dir>/<module>.py`` and
    # the M6a runtime bridge imports via ``from <build_dir_basename>
    # import <module>``. If ``<build_dir_basename>`` is not a valid
    # Python identifier the import silently fails at runtime — the
    # transpile succeeds, the artifacts land on disk, and consumers
    # see ``ModuleNotFoundError`` only when they wire up the runtime
    # bridge (the kn0wthyself-website-2 shape from M20 finding #5).
    # G3 sanitizes recoverable shapes automatically (``foo-bar`` →
    # ``foo_bar_build``, ``foo.bar`` → ``foo_bar_build``, etc.) and
    # fires this code loudly for the irrecoverable shapes — names that
    # start with a digit, or sanitize to the empty string. The
    # remediation message instructs the author to set
    # ``[tool.s0ma].build_dir`` explicitly to a valid Python
    # identifier. Always an error in every mode — a name the
    # transpiler cannot turn into a Python-importable directory is a
    # structural project-config error, not a strictness preference.
    "INVALID_PROJECT_NAME_FOR_BUILD_DIR": dict.fromkeys(StrictnessMode, "error"),
    # G5 (feedback 5–6 cleanup): the project's generated conftest at the
    # canonical location (``<project.root>/conftest.py``) was emitted by
    # an older s0ma-dsl version and either (a) has been hand-edited
    # since generation, or (b) was generated by a pre-G5 release that
    # did not embed a banner. Either way, the runtime contract the
    # conftest depends on may have evolved (the kn0wthyself-website-2
    # M20 finding #7 case: a months-old conftest patched
    # ``s0ma.runtime_bridge.registration.register_module``, but
    # ``s0ma.runtime_bridge`` no longer exists in 0.12, and pytest
    # aborted at import time with an opaque ``AttributeError``). G5
    # surfaces this loudly at ``s0ma test`` pre-flight time, before
    # pytest is invoked. The remediation is to either delete the
    # conftest and run ``s0ma test-conftest`` again, or to inspect /
    # preserve customizations and run ``s0ma test-conftest --force``.
    # Always an error in every strictness mode — silent runtime
    # ``try/except`` swallowing was rejected on principles grounds: an
    # opaque pytest-import-time error is exactly the failure mode the
    # "no silent failures" rule exists to prevent. See plan G5 and the
    # detector / classifier in
    # ``src/s0ma_dsl/cli/main.py:_classify_conftest``.
    "STALE_GENERATED_CONFTEST": dict.fromkeys(StrictnessMode, "error"),
    # M-12 (POST-8, 0.16.0): an emitted body authors a Python 3.12-only
    # grammar construct (PEP 701 nested-quote f-string, walrus operator
    # inside a comprehension, or PEP 695 type-parameter / type-alias
    # syntax) while the project's ``[project].requires-python`` range
    # still includes Python 3.11. The check fires from
    # ``IntraModuleValidator._check_python_grammar_compat`` at
    # ``s0ma check`` time. Always an error in every strictness mode:
    # the construct compiles cleanly under the transpiler's 3.12
    # parser but would fail at import on a 3.11 consumer interpreter
    # — there is no migration runway that turns this softer than
    # ``error``, because the cost of shipping un-importable code to a
    # 3.11 environment is total. The motivating case: an operator
    # workstation running 3.11 builds a project pinned ``>=3.11`` on a
    # 3.12 dev box; the bodies would silently land in the wheel and
    # break at first import. Catching at check time closes the gap.
    # See plan post-Phase-2 M-12, spec §4.13 (requires-python capture),
    # and the detection helpers in ``s0ma_dsl.semantic.python_compat``.
    "PARSE_GRAMMAR_FORWARD_INCOMPAT": dict.fromkeys(StrictnessMode, "error"),

    # 0.14 M2: build/transpile can prove only that emitted Python will
    # import the s0ma runtimes, not that the host has installed them.
    # Keep this static guidance a warning in every mode; ``verify-host``
    # owns the explicit, executable release verdict.
    "HOST_RUNTIME_UNDECLARED": dict.fromkeys(StrictnessMode, "warning"),
    # A build of a real project recorded a module whose file lives under
    # none of the configured ``source_roots`` or ``test_roots`` (``s0ma
    # build examples/`` in a project whose roots are ``src`` and
    # ``tests``). The build decides each manifest entry's role from the
    # root the file lives under; a file under no root has no root to
    # answer, so the entry is written with role ``source``, because
    # nothing declares the module a test, and this says so and names the
    # roots so the directory can be declared. A warning in every mode: it
    # describes the project's declared perimeter, not the module's
    # source, so the build gate must never refuse a build over it
    # (``is_check_severity_error`` reads the strict column).
    "MODULE_OUTSIDE_PROJECT_ROOTS": dict.fromkeys(StrictnessMode, "warning"),

    # --- Behavioral/hygiene rules: vary by mode ---
    "PROHIBITED_CONSTRUCT": {
        StrictnessMode.MIGRATION: "warning",
        StrictnessMode.DEV: "warning",
        StrictnessMode.STRICT: "error",
        StrictnessMode.RELEASE: "error",
    },
    "BARE_IMPORT": {
        StrictnessMode.MIGRATION: "warning",
        StrictnessMode.DEV: "warning",
        StrictnessMode.STRICT: "error",
        StrictnessMode.RELEASE: "error",
    },
    "MISSING_PACKAGE": {
        StrictnessMode.MIGRATION: "warning",
        StrictnessMode.DEV: "warning",
        StrictnessMode.STRICT: "error",
        StrictnessMode.RELEASE: "error",
    },
    "VESTIGIAL_IMPORT": {
        StrictnessMode.MIGRATION: "warning",
        StrictnessMode.DEV: "warning",
        StrictnessMode.STRICT: "error",
        StrictnessMode.RELEASE: "error",
    },
    "EMPTY_OBSERVES": {
        StrictnessMode.MIGRATION: "warning",
        StrictnessMode.DEV: "warning",
        StrictnessMode.STRICT: "error",
        StrictnessMode.RELEASE: "error",
    },
    "DUPLICATE_AXON": {
        StrictnessMode.MIGRATION: "warning",
        StrictnessMode.DEV: "warning",
        StrictnessMode.STRICT: "error",
        StrictnessMode.RELEASE: "error",
    },
    "POSSIBLE_UNRESOLVED_REFERENCE": {
        StrictnessMode.MIGRATION: "warning",
        StrictnessMode.DEV: "warning",
        StrictnessMode.STRICT: "warning",
        StrictnessMode.RELEASE: "error",
    },
    # POST-3b (0.15.0): a ``test`` declaration lists one or more
    # ``mocks: [<NerveName>]`` targets and the test body constructs a
    # dict literal whose keys are a non-trivial mismatch with the
    # target nerve's ``provides:`` set. The validator detects the
    # mock-shape pattern conservatively (a dict literal in the body
    # whose key set is non-empty and substantially overlaps with the
    # target's provides) and reports keys that the target declares
    # but the mock omits or keys that the mock declares but the target
    # does not. The motivating consumer is fr3d's Phase 2 Frontend
    # track where mock dicts for SERVICE-nerve fakes drift silently
    # from the production surface; catching the drift at check time
    # closes the silent-mock class without forcing authors to import
    # the production surface into the test. Severity ladders with
    # mode: warning in migration/dev (so authors still see the
    # finding while iterating), error in strict and release (where
    # silent drift is unacceptable). The check is conservative — when
    # the body has no detectable mock-shape literal, the validator
    # skips the check silently; false positives are worse than false
    # negatives.
    "MOCK_KEY_MISMATCH": {
        StrictnessMode.MIGRATION: "warning",
        StrictnessMode.DEV: "warning",
        StrictnessMode.STRICT: "error",
        StrictnessMode.RELEASE: "error",
    },
    # POST-3c (0.15.0): a nerve declares ``provides: [...]`` (flat or
    # structured form) and the body terminates with a ``return {...}``
    # literal whose literal-string keys do not exactly match the
    # ``provides:`` set. This is the strict-mode generalisation of the
    # POST-3a check on the structured form: M-4 fired
    # ``MISSING_RETURN_KEY`` for the structured form only; POST-3c
    # extends the check to the flat form too, but as a soft-by-default
    # finding so dev iteration is not punished. Catches the
    # ``return {"asemble": assemble}`` typo class on any SERVICE nerve
    # that declares ``provides:`` — the canonical example the spec's
    # §4.1.3 three-way coupling diagram calls out. The check is
    # *literal-keys-only*: a body that computes its return dict
    # dynamically (``return {k: v for k, v in ...}`` or ``return
    # dict(...)`` or string-formatted keys) is intentionally skipped
    # — false positives on legitimate dynamic returns would erode
    # author trust in the check. Severity ladders with mode: warning
    # in migration/dev, error in strict and release.
    "PROVIDES_KEY_MISMATCH": {
        StrictnessMode.MIGRATION: "warning",
        StrictnessMode.DEV: "warning",
        StrictnessMode.STRICT: "error",
        StrictnessMode.RELEASE: "error",
    },
    # POST-10g (0.16.0): a ``requires:`` (or ``soft_requires:`` /
    # ``runtime_only_requires:``) entry is authored in dotted form
    # ``uuid.uuid4`` whose last segment is lowercase. The parser's
    # UPPER_CASE heuristic decides "is this a from-import?" by
    # inspecting the first character of the last segment; ``UUID``
    # triggers the heuristic and the entry becomes
    # ``from uuid import UUID``, but ``uuid4`` does NOT trigger it and
    # the entry stays as a plain ``import uuid.uuid4`` (binding only
    # ``uuid`` in the namespace). When a body references the
    # lowercase last segment as a bare identifier (e.g.
    # ``return uuid4()``), the author almost certainly meant the
    # explicit colon-override shape ``uuid:uuid4``. This hint fires
    # at warning severity in every mode so the steer never hard-fails
    # a build but always surfaces. Severity stays warning even in
    # release because the colon-override is a steering tip — the
    # existing code path either works (if the heuristic happened to
    # pick up the right shape) or fails loudly through a separate
    # diagnostic (``VESTIGIAL_IMPORT`` on ``uuid``, plus a ``NameError``
    # at runtime), and POST-10g's value is shortening the diagnostic
    # ladder, not gating release.
    "REQUIRES_DOTTED_LOWERCASE_HINT": dict.fromkeys(StrictnessMode, "warning"),
    # POST-10h (0.16.0): a body (test, nerve, helper, ganglion, or
    # cell) calls ``dataclasses.field(default=[...])`` or
    # ``dataclasses.field(default={...})`` — i.e. supplies a mutable
    # collection literal as the ``default=`` argument. Python evaluates
    # ``default`` once at class-body time and re-uses the same object
    # across every instance, producing the classic shared-mutable-
    # default bug. The correct shape is ``default_factory=list`` (or
    # ``default_factory=dict``) so each instance gets a fresh
    # collection. The lint fires from
    # ``IntraModuleValidator._check_mutable_dataclass_default`` and
    # walks every authored body via ``ast.parse`` looking for the
    # specific ``dataclasses.field(default=<List|Dict|Set>)`` call
    # shape. Severity ladders with mode: warning in migration/dev
    # so authors see the finding while iterating, error in strict and
    # release where shipping a known-buggy default is unacceptable.
    "MUTABLE_DEFAULT": {
        StrictnessMode.MIGRATION: "warning",
        StrictnessMode.DEV: "warning",
        StrictnessMode.STRICT: "error",
        StrictnessMode.RELEASE: "error",
    },
    # POST-10i (0.16.0): a body contains two ``def`` declarations with
    # the same name inside a single enclosing function scope (most
    # commonly a SERVICE nerve's factory body where the author meant
    # the second ``def`` to be a sibling but accidentally re-typed the
    # first name). Python silently accepts the redefinition — the
    # second binding shadows the first — and the returned dict from
    # the factory ends up keyed to a function the author didn't
    # intend. This is a structural authoring bug, not a strictness
    # preference, so the lint fires as an error in every strictness
    # mode (same precedent as ``DUPLICATE_DECLARATION`` at module
    # scope). The detector walks every body and, for each
    # ``ast.FunctionDef`` / ``ast.AsyncFunctionDef`` node, examines
    # its direct child ``ast.FunctionDef`` / ``ast.AsyncFunctionDef``
    # nodes for name collisions. Class bodies and nested-class methods
    # are intentionally excluded (Python allows ``def foo`` once per
    # method-name in a class body and the relevant collision detector
    # there is ``CLASS_BODY_IN_NERVE``).
    "DUPLICATE_INNER_FUNCTION": dict.fromkeys(StrictnessMode, "error"),
    # POST-10k (0.16.0): a module's ``uses:`` declarations import two
    # or more entries from the same parent module (e.g.
    # ``uses: [other.A, other.B]``) but the module's bodies only
    # reference a subset of those names (e.g. only ``A``). The
    # asymmetry suggests the author over-imported (perhaps copy-pasted
    # the symmetric pair from a sibling module) and that the unused
    # entry should be trimmed. Severity ladders with mode: warning in
    # migration/dev so authors see the finding while iterating, error
    # in strict only (release falls back to strict per the existing
    # pattern for hygiene-class diagnostics that the
    # ``VESTIGIAL_IMPORT`` ladder already covers in release — POST-10k
    # is a narrower symmetry-shaped subset of that family).
    "CROSS_MODULE_USES_ASYMMETRY": {
        StrictnessMode.MIGRATION: "warning",
        StrictnessMode.DEV: "warning",
        StrictnessMode.STRICT: "error",
        StrictnessMode.RELEASE: "error",
    },
    # POST-12b (0.16.0): a CONSTANT cell uses ``content: @file("...")``
    # and declares ``placeholders: [__SYSTEM_NAME__, ...]`` but one or
    # more declared placeholders are absent from the embedded file's
    # content. The author asserted the file would contain the placeholder
    # string (so a downstream renderer can substitute it at runtime),
    # but the assertion does not hold — the build would emit a constant
    # whose string body is missing the marker the runtime needs. Always
    # an error in every strictness mode: a declared placeholder that
    # never appears is a hard correctness violation (same precedent as
    # ``CONSTANT_NAME_MISMATCH`` — declared shape must match actual
    # shape). Single emit site:
    # ``semantic/validator.py::_check_placeholders``.
    "PLACEHOLDER_NOT_FOUND": dict.fromkeys(StrictnessMode, "error"),
    # POST-12b (0.16.0): the embedded file's content contains a
    # placeholder-shaped string (matching ``__[A-Z][A-Z0-9_]*__``) that
    # is NOT listed in the cell's ``placeholders:`` field. The
    # placeholder convention is the load-bearing contract a downstream
    # template renderer relies on; an undeclared placeholder means
    # either (a) the file carries a marker the renderer will not
    # substitute (silent rendering bug at runtime) or (b) the marker
    # was added without updating the cell declaration (drift). The
    # ``placeholders:`` field is the author's explicit assertion of
    # which markers the file carries; an undeclared marker is the
    # asymmetry between declared and actual surface that the lint
    # exists to flag. Severity ladders with mode: warning in
    # migration/dev (so authors iterate without being punished), error
    # in strict and release (where the drift cannot ship). Single emit
    # site: ``semantic/validator.py::_check_placeholders``.
    "UNDECLARED_PLACEHOLDER": {
        StrictnessMode.MIGRATION: "warning",
        StrictnessMode.DEV: "warning",
        StrictnessMode.STRICT: "error",
        StrictnessMode.RELEASE: "error",
    },
    # POST-12c (0.16.0): a MODEL cell's ``dataclass_invariants:`` block
    # declares an assertion expression that does not parse as a Python
    # boolean expression via ``ast.parse(expr, mode="eval")``. The
    # invariants are *not* runtime-evaluated by s0ma — they are pure
    # metadata for downstream introspection — but the parser
    # syntax-checks each entry at check time so authors discover
    # malformed expressions before they reach the registered metadata
    # dict. The motivating failure mode: an author writes
    # ``len(latency_samples <= 100`` (missing close paren) and the
    # invariant rides through the IR uncaught; a downstream tool that
    # *does* try to evaluate the expression at runtime would crash
    # opaquely. Always an error in every strictness mode — same load-
    # bearing-correctness invariant as ``PARSE_ERROR`` (the expression
    # must be syntactically Python; nothing about the surface mode
    # softens that). Single emit site:
    # ``semantic/validator.py::_check_dataclass_invariants``.
    "INVALID_DATACLASS_INVARIANT": dict.fromkeys(StrictnessMode, "error"),
    # POST-12d (0.16.0): a nerve's ``consumes_via_dict:`` entry names
    # a ``contract:`` that does not resolve to a known cell in the
    # current module or to a ``uses:`` target, OR names a ``param:``
    # that is not a parameter on the nerve body's outer function. The
    # field is the explicit surface for duck-typed couplings — when a
    # nerve body reads an injected dependency via ``config["api_key"]``
    # rather than ``config.api_key`` the contract relationship was
    # historically invisible. ``consumes_via_dict:`` declares it
    # explicitly so the registry can reason about the coupling.
    # Misconfiguration (a contract that does not exist, a param that
    # is not on the nerve's signature) is a hard authoring bug — the
    # author has named a non-existent dependency, which would either
    # crash at runtime or silently mis-thread the parameter. Always
    # an error in every strictness mode (same precedent as
    # ``INTERFACE_ON_NON_ABSTRACT`` and ``HELPER_PRIVATE_TO_MODULE``).
    # Single emit site:
    # ``semantic/validator.py::_check_consumes_via_dict``.
    "CONSUMES_VIA_DICT_INVALID": dict.fromkeys(StrictnessMode, "error"),
    # POST-12g (0.16.0): a non-``.s0ma`` fixture file under a
    # configured ``test_roots`` directory matches a glob declared in
    # ``[tool.s0ma].fixtures_format`` but fails its declared format —
    # e.g. a ``.jsonl`` fixture whose line 3 is invalid JSON, or a
    # ``.yaml`` fixture that PyYAML cannot parse. The format checker
    # surfaces the offending line number (for line-based formats)
    # alongside the parser-thrown error so authors can locate the
    # bug. Severity ladders with mode: warning in migration/dev (so
    # authors writing/refining fixtures see the finding without being
    # blocked), error in strict and release (where shipping malformed
    # test fixtures is unacceptable — a malformed fixture either
    # crashes a test at import time or, worse, silently mis-loads).
    # The validator runs from ``cli/main.py::_cmd_check`` after the
    # standard ``.s0ma`` validation pass — fixtures are non-``.s0ma``
    # so they participate in the project hygiene check but never go
    # through the parser. Single emit site: see
    # ``cli/main.py::_validate_fixtures_format``.
    "FIXTURE_FORMAT_INVALID": {
        StrictnessMode.MIGRATION: "warning",
        StrictnessMode.DEV: "warning",
        StrictnessMode.STRICT: "error",
        StrictnessMode.RELEASE: "error",
    },
    # M7: doc-subsystem CLI/strictness/drift integration.
    # Drift detection mirrors the design §11.11 ladder: lenient for
    # migration/dev (warnings), strict for strict/release.
    "DRIFT_DETECTED": {
        StrictnessMode.MIGRATION: "warning",
        StrictnessMode.DEV: "warning",
        StrictnessMode.STRICT: "error",
        StrictnessMode.RELEASE: "error",
    },
    # EMPTY_DOC_FILTER mirrors the existing EMPTY_OBSERVES semantics for
    # ganglia: a filter that materialises to zero entities is a
    # warning while authors are still wiring things up, but a hard
    # error at strict / release.
    "EMPTY_DOC_FILTER": {
        StrictnessMode.MIGRATION: "warning",
        StrictnessMode.DEV: "warning",
        StrictnessMode.STRICT: "error",
        StrictnessMode.RELEASE: "error",
    },
    # Quick-reference landing (owner decision 2026-09-29): three things a
    # person could write and s0ma would silently not act on. Each used to
    # be a rule a reader had to be warned about in prose; each is now a
    # report. All three ladder the way every other "this is probably a
    # mistake" finding here does — warning in migration/dev, so a project
    # that carried one of these unnoticed keeps building day to day after
    # an upgrade, and error in strict and release, where s0ma's own
    # packages build and where a line that does nothing cannot ship.
    #
    # ``UNKNOWN_FIELD``: a well-formed field line whose name that kind of
    # declaration does not have — a misspelling (``guarantes:``), a field
    # of another kind (``expects:`` on a helper), or a header-line fact
    # written as a field (``layer:`` on a nerve). The line was stored and
    # never read. The known set is read from ``FIELD_CLASSIFICATIONS``,
    # not kept here. Single emit site:
    # ``parser/s0ma_parser.py::_check_declaration_lines``.
    "UNKNOWN_FIELD": {
        StrictnessMode.MIGRATION: "warning",
        StrictnessMode.DEV: "warning",
        StrictnessMode.STRICT: "error",
        StrictnessMode.RELEASE: "error",
    },
    # ``UNRECOGNIZED_LINE``: a line inside a declaration's description
    # that is not a field, not part of a block, and not a comment — in
    # practice a field, or a ``depends_on:`` entry, indented by the wrong
    # number of spaces. The splitter skipped it without a word. Same emit
    # site as ``UNKNOWN_FIELD``.
    "UNRECOGNIZED_LINE": {
        StrictnessMode.MIGRATION: "warning",
        StrictnessMode.DEV: "warning",
        StrictnessMode.STRICT: "error",
        StrictnessMode.RELEASE: "error",
    },
    # ``TEST_NOT_COLLECTED``: a ``test`` declaration whose code defines
    # nothing the test runner will run. pytest collects functions named
    # ``test*`` (and ``test*`` methods of ``Test*`` classes); a body that
    # defines only ``def check_dates()`` is emitted, registered as
    # coverage for the parts it names, and never executed. Single emit
    # site: ``semantic/validator.py::_check_test_collection``.
    "TEST_NOT_COLLECTED": {
        StrictnessMode.MIGRATION: "warning",
        StrictnessMode.DEV: "warning",
        StrictnessMode.STRICT: "error",
        StrictnessMode.RELEASE: "error",
    },

    # --- Release-only checks ---
    "MISSING_TEST_COVERAGE": {
        StrictnessMode.MIGRATION: None,
        StrictnessMode.DEV: None,
        StrictnessMode.STRICT: None,
        StrictnessMode.RELEASE: "error",
    },
    # Release-only doc-subsystem coverage checks (plan §11.11 release
    # row, M7 subtask 4).
    "MISSING_PUBLIC_DOC_REF": {
        StrictnessMode.MIGRATION: None,
        StrictnessMode.DEV: None,
        StrictnessMode.STRICT: None,
        StrictnessMode.RELEASE: "error",
    },
    "MISSING_EMBEDDED_EXAMPLE": {
        StrictnessMode.MIGRATION: None,
        StrictnessMode.DEV: None,
        StrictnessMode.STRICT: None,
        StrictnessMode.RELEASE: "error",
    },
}


# ---------------------------------------------------------------------------
# Out-of-matrix error code registry (G6 feedback 5–6 cleanup)
#
# Some error codes do not pass through ``SEVERITY_MATRIX``. They fire from
# pre-flight or load-time surfaces that run before any strictness mode is
# consulted; they are structural / configuration-shaped diagnostics that the
# strictness ladder cannot legitimately make softer than ``error``. Every
# such code MUST appear in this tuple so the meta-test
# ``test_every_error_code_literal_is_registered`` (in
# ``tests/test_doc_consistency.py``) can pin every code literal in
# ``src/s0ma_dsl/`` to either ``SEVERITY_MATRIX`` or this list.
#
# Adding a code here is a deliberate documentation choice, not a workaround
# for "I don't want to think about severity yet". Default to registering in
# ``SEVERITY_MATRIX``; only use this list when the code is structurally
# always-one-severity (no mode variation makes sense) AND fires from a
# surface that does not carry a strictness mode (project load, file
# discovery, pre-flight conftest classification). Document the rationale in
# a one-line comment per entry.
#
# See ``docs/coding_agent_handbook.md`` §2.3 (Error Codes) for the
# decision rule future contributors must follow when adding a new code.
# ---------------------------------------------------------------------------

OUT_OF_MATRIX_CODES_THAT_MUST_STILL_BE_TRACEABLE: tuple[str, ...] = (
    # 0.14 M4: adoption-command advisory emitted from migration intake,
    # which has no authoring strictness mode. It is always a warning and
    # never gate input because persisted re-adoption history is mutable.
    "ADOPTED_CHURN",
    # 0.14 M3A canonical-IR reader refusal. Schema compatibility is a
    # document-shape invariant independent of authoring strictness.
    "UNSUPPORTED_IR_SCHEMA_MAJOR",
    # 0.14 M3A grammar-migration preflight/apply failures run outside the
    # authoring strictness ladder and always refuse the whole plan.
    "GRAMMAR_MIGRATION_PARSE_ERROR",
    "GRAMMAR_MIGRATION_OUTPUT_INVALID",
    "GRAMMAR_MIGRATION_CONFLICT",
    "GRAMMAR_MIGRATION_APPLY_FAILED",
    "GRAMMAR_MIGRATION_ROLLBACK_FAILED",
    # 0.14 M1: verify pre-flight result when a tree contains zero
    # hash-bearing modeled modules. Always exits EXIT_NOTHING_VERIFIED (4),
    # independent of authoring strictness.
    "HOLLOW_MODEL",
    # 0.14 M1: aggregate core-verifier fault for caller-discovered entries
    # absent from the canonical registry. Core owns the emitter, while this
    # registry keeps the agent-facing error catalog complete.
    "UNREGISTERED_SURFACE",
    # M3: warning emitted directly (not via SEVERITY_MATRIX) by the
    # scope-aware test-helper-collision analyzer in
    # ``semantic/validator.py``. Always-warning by design: two
    # same-named test helpers in the same module are a hygiene smell
    # but never a correctness violation (the test framework picks one
    # deterministically), so the strictness ladder has no legitimate
    # severity-by-mode reading.
    "HELPER_NAME_COLLISION",
    # G1 (feedback 5–6 cleanup): project-load-time error fired by
    # ``S0maProject._from_tool_s0ma`` when the same file is listed
    # under both ``[tool.s0ma].bootstrap_files`` and
    # ``[tool.s0ma].package_markers``. Configuration-shaped: never
    # reaches the strictness ladder, so it lives outside
    # ``SEVERITY_MATRIX`` but must still be traceable.
    "CONFLICTING_PACKAGE_DECLARATION",
    # M-16 (POST-11a, 0.16.0): pre-flight refusal fired by
    # ``_cmd_build`` when ``--output-dir`` disagrees with the resolved
    # ``[tool.s0ma].build_dir`` and ``--force-output-dir`` is not set.
    # Configuration-shaped (the project model is the canonical source
    # of truth for the build dir); the strictness ladder has no
    # legitimate severity-by-mode reading because the conflict fires
    # before any ``.s0ma`` parsing happens. Always exits with
    # ``EXIT_USAGE_ERROR`` (2). Suppressing the refusal with
    # ``--force-output-dir`` still emits a one-line stderr notice for
    # telemetry but does not fire the registered code.
    "BUILD_DIR_OVERRIDE_CONFLICT",
    # B2 (0.11.0, batch-01a): a generated ``.py`` was hand-edited after
    # transpilation — its embedded ``# s0ma-output-hash`` no longer
    # matches its content. Fired two ways, both with a directly-set
    # severity (never through the strictness ladder, because the
    # condition is generated-file state, not source strictness): the
    # ``build``/``transpile`` write path REFUSES with severity ``error``
    # (unless ``--force``), and the ``check`` drift pass surfaces it as
    # severity ``warning`` so a silent revert is visible before the next
    # build clobbers it. This is the silent-revert that detonated
    # batch-01a run ``P1_P_r02`` (acceptance 1/24). Emit sites:
    # ``cli/main.py::_transpile_single_file`` (refuse) and
    # ``cli/main.py::_cmd_check`` (drift pass).
    "GENERATED_FILE_DRIFT",
)


# ---------------------------------------------------------------------------
# Error-code human-readable descriptions (G7a feedback 5–6 cleanup)
#
# Canonical short description for every error code in the union of
# ``SEVERITY_MATRIX`` and ``OUT_OF_MATRIX_CODES_THAT_MUST_STILL_BE_TRACEABLE``.
# These are the descriptions the doc subsystem's ``doc-ref`` renderer pulls
# in when authoring a code → description table from the registry; they are
# intentionally one-sentence triggers (not full remediation prose), mirroring
# the "Code | Fix" shape the hand-authored quick-reference table had before
# the table was generated (and, since 2026-09-29, the document retired).
#
# Invariant pinned by ``test_error_code_descriptions_complete``: every code in
# ``SEVERITY_MATRIX | OUT_OF_MATRIX_CODES_THAT_MUST_STILL_BE_TRACEABLE`` MUST
# have an entry here. Adding a new error code requires three coordinated
# edits: (1) register it in the appropriate severity registry above; (2)
# add a description here; (3) add a row in ``docs/spec_traceability.md``.
# The meta-tests in ``tests/test_doc_consistency.py`` enforce all three.
# ---------------------------------------------------------------------------

ERROR_CODE_DESCRIPTIONS: dict[str, str] = {
    "ADOPTED_CHURN": (
        "A roster file has been re-adopted at least three times; componentize "
        "it instead of repeatedly refreshing interim migration telemetry."
    ),
    "NEW_FILE_ROSTER_ONLY": (
        "A Python file first seen after the project's s0ma baseline is only "
        "roster-adopted; author it as a canonical component with author_module."
    ),
    "HOLLOW_MODEL": (
        "Verification found zero modeled s0ma modules; roster adoption "
        "verifies bytes but cannot answer semantic questions about the code."
    ),
    "UNREGISTERED_SURFACE": (
        "A caller-discovered declaration or source module is absent from the "
        "canonical component registry."
    ),
    "ADOPT_PLACEHOLDER_INTENT": (
        "A field still carries the `FIXME(adopt):` placeholder `s0ma adopt "
        "draft` left for a person to replace; write the sentence in your own "
        "words, because a draft derives structure and never invents meaning."
    ),
    "ADOPT_UNPLACED_CODE": (
        "A module still carries an `adopt: unplaced` quarantine cell holding "
        "source text the draft could not place; move the text into the "
        "declaration it belongs to, or delete it, and delete the cell."
    ),
    "PARSE_ERROR": "Source file failed to parse as a valid .s0ma module.",
    "SEMANTIC_PENDING_INVALID": (
        "A pending semantic-state value is malformed; use pending with one quoted reason."
    ),
    "SEMANTIC_PENDING_REASON_EMPTY": (
        "A pending semantic-state value has an empty or whitespace-only reason."
    ),
    "SEMANTIC_REQUIRED_STATE_OMITTED": (
        "A semantic-required declaration field was omitted instead of carrying an "
        "explicit value, none, or reasoned pending state."
    ),
    "SEMANTIC_NONE_NOT_ALLOWED": (
        "A declaration field used none where the normative field matrix requires a value."
    ),
    "SEMANTIC_PENDING_NOT_ALLOWED": (
        "A structural or otherwise non-deferrable declaration field used pending."
    ),
    "SEMANTIC_DERIVED_FIELD_AUTHORED": (
        "Authored source attempted to set a field owned by parsing, resolution, or emission."
    ),
    "SEMANTIC_PENDING_DEBT": (
        "A semantic declaration field is explicitly pending with an authored reason; it "
        "earns zero completeness credit and blocks strict/release acceptance."
    ),
    "UNSUPPORTED_IR_SCHEMA_MAJOR": (
        "A canonical IR reader received an unsupported schema major and requires migration "
        "and rebuild."
    ),
    "GRAMMAR_MIGRATION_PARSE_ERROR": (
        "Whole-project grammar migration preflight could not parse one authored source."
    ),
    "GRAMMAR_MIGRATION_OUTPUT_INVALID": (
        "A proposed grammar migration rewrite failed the parser invariant before apply."
    ),
    "GRAMMAR_MIGRATION_CONFLICT": (
        "A grammar-migration target changed or ceased to be a regular file after planning."
    ),
    "GRAMMAR_MIGRATION_APPLY_FAILED": (
        "An atomic grammar-migration replacement failed and prior replacements were restored."
    ),
    "GRAMMAR_MIGRATION_ROLLBACK_FAILED": (
        "The grammar migrator could not restore one or more files after an apply failure."
    ),
    "EMPTY_BLOCK_LIST": (
        "A YAML-style block list ('- item' per line) on uses/requires/exports/"
        "raises has no items — use the inline form ``field: []`` instead."
    ),
    "INCONSISTENT_BLOCK_LIST_INDENT": (
        "Items in a YAML-style block list use different indentation columns; "
        "all '- item' lines under a field must share the same indent."
    ),
    "MIXED_PROVIDES_FORMS": (
        "A nerve's `provides:` block mixes the flat form ('- name') and the "
        "structured form ('- name:' with indented returns:/expects:/guarantees: "
        "sub-fields). Pick one form per block."
    ),
    "DUPLICATE_PROVIDES_NAME": (
        "A nerve's structured `provides:` block lists the same operation name "
        "twice — each entry must be unique."
    ),
    "MISSING_FIELD": "A required field on a declaration is absent.",
    "INVALID_KIND": "A declaration's `kind:` value is not valid for its declaration type.",
    "VISIBILITY_MISMATCH": "A component's visibility does not match its module's exports list.",
    "LAYER_MISMATCH": "A component's declared layer does not match its module's layer.",
    "NAMESPACE_COLLISION": "Two names collide in the same namespace within a module.",
    "INVALID_AXON_RELATION": (
        "An axon uses a relation outside the allowed set (CALLS, READS, CONSTRUCTS, CONFIGURES, "
        "PRODUCES, CONSUMES)."
    ),
    "INVALID_RAISES_TARGET": (
        "A nerve's `raises:` references a `requires:` import (must be a component-ref)."
    ),
    "DUPLICATE_DECLARATION": "Two top-level declarations share the same name in one module.",
    "INVALID_VERSION": "A module's `version:` value is not valid semver.",
    "CLASS_BODY_IN_NERVE": "A nerve body contains a `class` definition (nerves must be functions).",
    "MODULE_NAME_STEM_MISMATCH": (
        "The source filename's stem does not match the declared `module <name>`."
    ),
    "METADATA_INVALID_KEY": (
        "A `metadata:` key is not identifier-shaped, or the same key is authored twice in one map."
    ),
    "METADATA_INVALID_VALUE": (
        "A `metadata:` value is outside the shape set (quoted string | int | float | bool | "
        "list of strings) — nested maps, null entries, unquoted bare tokens, and the inline "
        "`metadata: {...}` form are rejected."
    ),
    "METADATA_RESERVED_KEY": (
        "A `metadata:` key collides with a reserved registration-metadata key the emitter writes "
        "(see `RESERVED_COMPONENT_METADATA_KEYS`); set the owning declaration field instead."
    ),
    "SERVES_AS_INVALID": (
        "A `serves_as:` value is not identifier-shaped — the served name becomes the emitted "
        "callable's `__name__`."
    ),
    "SERVES_AS_COLLISION": (
        "Two declarations carry the same `serves_as:` value (served names form one flat "
        "namespace, validated per module and per project build)."
    ),
    "DUPLICATE_REQUIRES_ENTRY": (
        "The same import target appears in `deferred_requires:` and another requires-family "
        "list of the same module header — module-top import and call-time deferral are "
        "different failure-time choices; one target, one list."
    ),
    "DEFERRED_IMPORT_MODULE_SCOPE": (
        "A `deferred_requires:` name is consumed at a module-scope execution position (cell "
        "body, class-scope statement, decorator expression, parameter default, or annotation) "
        "— those run at import time, before any injected in-body import could; move the entry "
        "back to `requires:` or restructure the consumer into a function body."
    ),
    "COVERED_BY_EMPTY": (
        "A `covered_by:` field is present with an empty list, or an entry is empty/whitespace "
        "— the field is the release gate's external test-evidence credit and an empty claim "
        "credits coverage with no auditable evidence."
    ),
    "AMBIGUOUS_TEST_TARGET": "A bare `tests:` entry resolves to components in two or more modules.",
    "TEST_VISIBILITY_VIOLATION": (
        "A production module attempts to `uses:` a `visibility: TEST` component cross-module."
    ),
    "CROSS_LAYER_DEPENDENCY": (
        "A `uses:` entry targets a module at a layer not in the source layer's reachable set."
    ),
    "PARSE_DOC_REF_BODY_PROHIBITED": (
        "A `doc-ref` declaration carries a `---` body (its content is renderer-synthesised)."
    ),
    "MODULE_NAME_COLLISION": (
        "Two source files declare the same `module <name>` in one project. Rename one with a "
        "descriptive suffix — `<name>_test`, `<name>_lib`, `<dir>_<name>`. For test-context "
        "modules under a `test_roots` directory, "
        "`[tool.s0ma].test_module_name_prefix_by_dir = true` prefixes them by their parent "
        "directory instead of a hand-rename."
    ),
    "MODULE_SUBSCRIPT": (
        "A body subscripts a bare `uses: [mod]` module object (`mod[\"key\"]`). A bare "
        "uses entry imports the whole module, not a component, so the subscript raises "
        "`TypeError: 'module' object is not subscriptable` at runtime — import the symbol "
        "with `uses: [mod.symbol]` (emits `from mod import symbol`) instead."
    ),
    "MODULE_SHADOWS_STDLIB": (
        "A module's declared name shadows a Python stdlib module (io, json, csv, …). The "
        "stdlib module is already loaded, so the built module cannot be imported by its "
        "bare name and cross-module `uses:` resolution fails at runtime — rename the module "
        "(and its file) to a non-stdlib name."
    ),
    "GENERATED_FILE_DRIFT": (
        "A generated .py was hand-edited after transpilation (its embedded "
        "`# s0ma-output-hash` no longer matches its content). A build will not "
        "overwrite it until the .s0ma source says the same thing: move the changes "
        "into the source, or pass --force to discard them. `s0ma check` surfaces this "
        "as a warning; `s0ma build` refuses, whether or not the source changed since "
        "the last build."
    ),
    "HOST_RUNTIME_UNDECLARED": (
        "Generated Python imports s0ma-core and s0ma-dsl, but the project does not declare "
        "both host runtime distributions. Naming them in [project].dependencies clears the "
        "finding; the environment that runs the application must also have them installed, "
        "and `s0ma verify-host` is how that is proved."
    ),
    "MODULE_OUTSIDE_PROJECT_ROOTS": (
        "A built module's file lives under none of the project's `[tool.s0ma].source_roots` "
        "or `test_roots`, so the build recorded it with role `source` by default. Add its "
        "directory to one of the two lists so the build can record which it is, or move the "
        "file under a configured root."
    ),
    "DOC_RENDER_ERROR": (
        "The doc renderer raised `DocRenderError` while emitting a `doc-ref` or `doc-guide`."
    ),
    "DOC_SOURCE_FORMAT_UNSUPPORTED": (
        "A `doc-ref` requests a `format:` its derived `covers: { source: ... }` does not "
        "declare; widen the source's registration or change the format."
    ),
    "INTERFACE_ON_NON_ABSTRACT": (
        "A nerve declares `interface:` but is not marked `abstract: true`."
    ),
    "MISSING_INTERFACE_METHODS": (
        "A concrete nerve `CONSTRUCTS` an abstract but does not define every method in the "
        "abstract's `interface:` list."
    ),
    "MISSING_PROVIDED_FUNCTION": (
        "A nerve declares `provides:` names but its body does not define every name as a `def`."
    ),
    "MISSING_RETURN_KEY": (
        "A nerve declares `returns:` keys but its body's terminal `return {...}` literal omits one "
        "or more."
    ),
    "TEMPLATE_SYNTAX_ERROR": (
        "A template expression `{{...}}` or `covers:` filter fails the narrow doc-subsystem "
        "grammar."
    ),
    "ASSERT_SYNTAX_ERROR": (
        "A doc-guide `asserts:` expression falls outside the narrow assert grammar."
    ),
    "PROSE_RAW_CODE_BLOCK": (
        "A `doc-guide` body contains a raw fenced code block (use `{{example::X}}` instead)."
    ),
    "UNRESOLVED_REFERENCE": (
        "A `{{kind::name}}` token references an entity that does not exist in the project registry."
    ),
    "ENTITY_KIND_MISMATCH": (
        "A `{{kind::name}}` token references an entity of a different kind than declared."
    ),
    "FIELD_NOT_FOUND": (
        "A `{{kind::name.field}}` token references a field that does not exist on the entity."
    ),
    "UNREGISTERED_EXAMPLE": (
        "An `examples:` entry or `{{example::X}}` token references an unregistered example."
    ),
    "ASSERT_FAILED": "A doc-guide `asserts:` expression evaluated to false.",
    "ASSERT_UNEVALUABLE": (
        "A doc-guide `asserts:` expression references a field or entity that cannot be evaluated."
    ),
    "NOT_EXPORTED": (
        "A `uses:` entry or qualified `depends_on:` target references a component that is not "
        "in its module's exports list."
    ),
    "DOES_NOT_EXIST": (
        "A `uses:` entry, `depends_on:` target, or qualified `depends_on:` target "
        "(`module.declaration`) references a component or module that does not exist in the "
        "project."
    ),
    "CIRCULAR_DEPENDENCY": (
        "The four-phase resolver's DFS detected a cycle in the declared cross-module "
        "architecture edges (`uses:` entries plus qualified `depends_on:` targets)."
    ),
    "MODULE_DEPENDENCY_CYCLE": (
        "Topological sort detected a cycle in the project module `uses:` graph."
    ),
    "EMBEDDED_FILE_NOT_FOUND": (
        "A `cell ... content: @file(\"path\")` directive references "
        "a missing or unreadable file."
    ),
    "CONSTANT_NAME_MISMATCH": (
        "A `kind: CONSTANT` cell's declaration name does not match the Python identifier its body "
        "assigns to."
    ),
    "HELPER_PRIVATE_TO_MODULE": (
        "A production module attempts to consume a `helper` declaration from another module via "
        "`uses:`."
    ),
    "EXPORTED_HELPER_NOT_FOUND": (
        "A module's `exports_helpers:` entry names an identifier that is not a `helper` "
        "declaration in this module."
    ),
    "INTEGRATION_FACTORY_NOT_FOUND": (
        "An `integration` declaration's `factory:` field names a nerve that does not exist in the "
        "same module."
    ),
    "INTEGRATION_FACTORY_NOT_SERVICE": (
        "An `integration` declaration's `factory:` field names a nerve whose `kind:` is not "
        "`SERVICE`."
    ),
    "INTEGRATION_SMOKE_TEST_NOT_FOUND": (
        "An `integration` declaration's `smoke_test_primary:` field names a target that is neither "
        "a nerve in the same module nor a reachable `uses:` entry."
    ),
    "INTEGRATION_INVALID_MANIFEST_KEY": (
        "An `integration` declaration's `manifest:` map carries an invalid key or value (keys must "
        "be Python identifiers; values must be JSON-serialisable primitives)."
    ),
    "ATTRIBUTE_BUDGET_VIOLATION": (
        "A nerve's `declares_attributes:` entry violates a project-configured "
        "`[tool.s0ma.attribute_budgets]` rule."
    ),
    "NO_PAGE_COMPOSER_DECLARED": (
        "The project configures an `exactly_one_per_page` budget but no nerve carries "
        "`is_page_composer: true`."
    ),
    "OVERLAPPING_DISCOVERY_ROOTS": (
        "The project's `[tool.s0ma].source_roots` and `[tool.s0ma].test_roots` overlap "
        "structurally."
    ),
    "INVALID_PROJECT_NAME_FOR_BUILD_DIR": (
        "The project's `[project].name` cannot be turned into a valid Python identifier for the "
        "build dir."
    ),
    "STALE_GENERATED_CONFTEST": (
        "The project's generated `conftest.py` was emitted by an older s0ma-dsl version and may "
        "have diverged from the runtime contract."
    ),
    "PARSE_GRAMMAR_FORWARD_INCOMPAT": (
        "A body authors Python 3.12-only grammar (PEP 701 nested-quote f-string, "
        "walrus-in-comprehension, or PEP 695 type-parameter / type-alias) while "
        "`[project].requires-python` still admits 3.11."
    ),
    "PROHIBITED_CONSTRUCT": (
        "A body uses `exec()`, `eval()`, `__import__()`, or another prohibited dynamic-execution "
        "construct."
    ),
    "BARE_IMPORT": (
        "A nerve or test body contains a bare `import` statement. The fix is one edit with "
        "two parts: declare the dependency in the module header — `requires:` for Python "
        "imports, `deferred_requires:` for a call-time import, `uses:` for s0ma components "
        "— and delete the import line from the body. The transpiler writes the import lines "
        "from the declarations."
    ),
    "MISSING_PACKAGE": (
        "A `requires:` entry references a Python module that is not importable in the project's "
        "environment."
    ),
    "VESTIGIAL_IMPORT": (
        "A declared `uses:` or `requires:` entry has no evidence of use in the consuming module's "
        "bodies."
    ),
    "EMPTY_OBSERVES": "A ganglion's `observes:` glob pattern resolves to zero matching nerves.",
    "DUPLICATE_AXON": (
        "The same axon relationship is declared twice (inline and standalone, or duplicated "
        "derived)."
    ),
    "POSSIBLE_UNRESOLVED_REFERENCE": (
        "A backtick-quoted identifier-shaped span in a `doc-guide` body is outside `{{...}}` and "
        "may be an unresolved reference."
    ),
    "MOCK_KEY_MISMATCH": (
        "A `test` declaration's `mocks: [<NerveName>]` target's mock-shape dict in the body "
        "exposes a key set that does not match the target nerve's `provides:` (missing or "
        "extra keys)."
    ),
    "PROVIDES_KEY_MISMATCH": (
        "A nerve declares `provides: [...]` (flat or structured) and its body's terminal "
        "`return {...}` literal-string keys do not exactly match the `provides:` set."
    ),
    "REQUIRES_DOTTED_LOWERCASE_HINT": (
        "A `requires:` entry like `uuid.uuid4` is authored in dotted form with a lowercase last "
        "segment, while the body uses the last segment as a bare identifier (e.g. `uuid4()`). "
        "Suggests the colon-override shape (e.g. `uuid:uuid4`) so the parser emits `from uuid "
        "import uuid4` deterministically."
    ),
    "MUTABLE_DEFAULT": (
        "A body calls `dataclasses.field(default=[...])` or `dataclasses.field(default={...})` "
        "with a mutable collection literal as the `default=` argument. Python evaluates "
        "`default` once at class-body time and shares the same object across instances. "
        "Use `default_factory=list` / `default_factory=dict` instead so each instance gets a "
        "fresh collection."
    ),
    "DUPLICATE_INNER_FUNCTION": (
        "A body contains two `def` declarations with the same name inside one enclosing "
        "function scope (e.g. a SERVICE factory body redefines its inner `def foo()` twice). "
        "Python silently shadows the first binding; the returned surface ends up keyed to a "
        "function the author did not intend."
    ),
    "CROSS_MODULE_USES_ASYMMETRY": (
        "A module's `uses:` declarations import two or more entries from the same parent "
        "module but the bodies only reference a subset. Suggests the unreferenced entries "
        "be trimmed from `uses:`. Narrower than `VESTIGIAL_IMPORT`: only fires when ≥2 "
        "siblings from the same parent module are declared together."
    ),
    "PLACEHOLDER_NOT_FOUND": (
        "A CONSTANT cell's `placeholders:` field declares a marker string "
        "(e.g. `__SYSTEM_NAME__`) that is absent from the `content: @file(...)` "
        "embedded file's content."
    ),
    "UNDECLARED_PLACEHOLDER": (
        "A CONSTANT cell's `content: @file(...)` embedded content contains a "
        "placeholder-shaped string matching `__[A-Z][A-Z0-9_]*__` that is not "
        "listed in the cell's `placeholders:` field."
    ),
    "FIXTURE_FORMAT_INVALID": (
        "A non-`.s0ma` fixture file under a configured `test_roots` directory "
        "matches a glob declared in `[tool.s0ma].fixtures_format` but fails "
        "its declared format (e.g. an invalid line in a `.jsonl` file or a "
        "malformed `.yaml` document)."
    ),
    "INVALID_DATACLASS_INVARIANT": (
        "A MODEL cell's `dataclass_invariants:` entry is not a syntactically "
        "valid Python boolean expression (fails `ast.parse(expr, mode=\"eval\")`). "
        "Invariants are metadata for downstream introspection only and are not "
        "runtime-evaluated by s0ma, but the parser syntax-checks each entry "
        "so malformed expressions are caught at check time rather than crashing "
        "a downstream consumer that tries to evaluate them."
    ),
    "CONSUMES_VIA_DICT_INVALID": (
        "A nerve's `consumes_via_dict:` entry names a `contract:` that resolves to no known "
        "cell or `uses:` target, or a `param:` that is not a parameter of the nerve body's "
        "outer function. The field declares a real dependency, so both halves must exist: "
        "declare the contract, or correct the param name."
    ),
    "DRIFT_DETECTED": (
        "A re-render of a `doc-ref` or `doc-guide` produces bytes that differ from the on-disk doc "
        "artifact."
    ),
    "EMPTY_DOC_FILTER": "A `doc-ref`'s `covers:` filter materialises to zero entities.",
    "UNKNOWN_FIELD": (
        "A declaration carries a field that kind of declaration does not have — usually a "
        "misspelt name, or a field that belongs to another kind. s0ma does not read the line, "
        "so whatever it was meant to say is not said; correct the name or remove the line."
    ),
    "UNRECOGNIZED_LINE": (
        "A line inside a declaration's description is not a field, not part of a block, and not "
        "a comment — usually a field indented by the wrong number of spaces. s0ma does not read "
        "the line; start a field with exactly four spaces, or remove the line."
    ),
    "TEST_NOT_COLLECTED": (
        "A `test` declaration's code defines no function named `test...`, so the test runner "
        "never runs it, while the declaration still counts as coverage for the parts it names. "
        "Name the function `test_<something>`."
    ),
    "MISSING_TEST_COVERAGE": (
        "A PUBLIC nerve has no `test` declaration covering it (release-mode only)."
    ),
    "MISSING_PUBLIC_DOC_REF": "A PUBLIC nerve is not covered by any `doc-ref` (release-mode only).",
    "MISSING_EMBEDDED_EXAMPLE": (
        "A registered `example` is not embedded in any `doc-guide` (release-mode only)."
    ),
    "HELPER_NAME_COLLISION": (
        "Two test bodies in one module define a same-named top-level `def` / `async def`."
    ),
    "CONFLICTING_PACKAGE_DECLARATION": (
        "A file path appears in both `[tool.s0ma].bootstrap_files` and "
        "`[tool.s0ma].package_markers`."
    ),
    "BUILD_DIR_OVERRIDE_CONFLICT": (
        "`s0ma build --output-dir <path>` was invoked with a path that disagrees with the "
        "resolved `[tool.s0ma].build_dir`. Drop `--output-dir` to let the project model resolve "
        "the build dir, or pass `--force-output-dir` to proceed with the override "
        "(a one-line stderr notice is emitted)."
    ),
}


@component(
    name="S0maDSL_get_severity",
    kind=ComponentKind.FUNCTION,
    layer=Layer.FRAMEWORK,
    intent=(
        "Look up the severity for an error code under a given strictness mode from the severity "
        "matrix."
    ),
    idempotent=True,
    is_framework=True,
)
def get_severity(error_code: str, mode: StrictnessMode) -> str | None:
    """Look up the severity for an error code under a given strictness mode.

    Returns ``"error"``, ``"warning"``, or ``None`` (not applicable in this mode).
    Raises ``KeyError`` if the error code is not in the severity matrix.
    """
    return SEVERITY_MATRIX[error_code][mode]


@component(
    name="S0maDSL_TranspilerConfig",
    kind=ComponentKind.MODEL,
    layer=Layer.FRAMEWORK,
    intent=(
        "Configuration for a transpiler invocation, including strictness mode and output "
        "options."
    ),
    idempotent=True,
    is_framework=True,
)
@dataclass
class TranspilerConfig:
    """Configuration for a single transpiler invocation."""

    mode: StrictnessMode = StrictnessMode.DEV
    """Active strictness mode."""

    output_dir: str | None = None
    """Output directory for generated files. None = same as source."""

    emit_ir: bool = True
    """Whether to generate .s0ma.json files."""

    emit_source_map: bool = True
    """Whether to generate .s0ma.map files."""

    output_format: str = "text"
    """Diagnostic output format: 'text' or 'json'."""

    extra: dict[str, Any] = field(default_factory=dict)
    """Extensible settings for future use."""
