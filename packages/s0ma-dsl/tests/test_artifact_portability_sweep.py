"""Schema-driven artifact portability sweep (DSL-M3).

F-M2-1's meta-lesson: artifact portability/determinism violations were
fixed THREE separate times (F-M0-8 ``built_at``, F-M1-1 manifest/IR/map
absolute + as-passed paths, F-M2-1 ``@file()`` embed paths) because the
determinism suites' field coverage was fixture-driven, not schema-driven.
Each violation was an INV-5 breach a committed build cannot carry, and
each surfaced only when a new artifact field first entered a committed
build — never the day the field shipped.

This module closes that gap. It derives the path-typed and time-typed
field coverage from the artifact SCHEMAS (the IR component/module schema,
the build-manifest schema, the source-map shape) so that a FUTURE field
is caught the day it ships:

  - :data:`_SCHEMA_STRING_FIELD_CLASSIFICATION` classifies EVERY
    string-typed field of every artifact dataclass as PATH, TIME, or
    OPAQUE. A new string field on any schema dataclass makes
    :func:`test_every_schema_string_field_is_classified` fail until an
    author classifies it — which forces a conscious decision about
    whether the new field can carry a machine path or a timestamp.
  - A rich fixture project (multi-module + an ``@file()`` embed +
    rendered docs + a helper) exercises every writer that emits such a
    field, and the build's EVERY artifact byte is swept for the four
    leak classes (absolute paths, the project-root string, backslash
    separators, ISO-8601 timestamp shapes).
  - The negative proof injects a synthetic absolute-path value into a
    parsed artifact dict and asserts the sweep catches it — proving the
    detector actually detects.

See also the narrower, hand-written precedents in ``test_build_manifest``
(``test_project_build_records_portable_paths`` /
``test_project_build_records_portable_embed_paths``); this module
generalises them to a schema-derived, every-byte sweep.
"""

from __future__ import annotations

import dataclasses as dc
import json
import re
import textwrap
from typing import TYPE_CHECKING

import pytest

from s0ma_dsl.cli.main import EXIT_SUCCESS, S0maCLI
from s0ma_dsl.codegen.build_manifest import (
    ArtifactReference,
    BuildManifest,
    ExternalContentFileEntry,
    ModuleManifestEntry,
)
from s0ma_dsl.codegen.source_map import (
    DeclarationMapping,
    ModuleHeaderMapping,
    SourceMap,
)
from s0ma_dsl.ir.schema import IRModule

if TYPE_CHECKING:
    from pathlib import Path


# ---------------------------------------------------------------------------
# Schema-derived field classification — THE single enumeration.
#
# Every string-typed field of every artifact schema dataclass is
# classified here. The classification is what ties the sweep to the
# schema definitions: when a field is ADDED to any of these dataclasses
# (ir/schema.py::IRModule, codegen/build_manifest.py::{BuildManifest,
# ModuleManifestEntry, ExternalContentFileEntry},
# codegen/source_map.py::{SourceMap, DeclarationMapping,
# ModuleHeaderMapping}), test_every_schema_string_field_is_classified
# fails until the new field is classified here — forcing a conscious
# "can this carry a machine path or a wall-clock time?" decision before
# the field can ride a committed build undetected.
#
# Categories:
#   PATH   — holds a filesystem path; MUST be portable (project-root-
#            relative POSIX, or a build-dir-relative basename). Swept for
#            absolute paths, the project root, and backslash separators.
#   TIME   — holds a wall-clock timestamp; MUST be absent from committed
#            builds (INV-5). Swept for ISO-8601 shapes.
#   OPAQUE — neither a path nor a time (names, hashes, intents, versions,
#            line-range ints, nested dataclasses). Not individually
#            swept, but still covered by the whole-artifact byte sweep.
# ---------------------------------------------------------------------------

PATH = "PATH"
TIME = "TIME"
OPAQUE = "OPAQUE"

_SCHEMA_STRING_FIELD_CLASSIFICATION: dict[type, dict[str, str]] = {
    # IR component schema (the emitted ``.s0ma.json``). Only IRModule
    # carries path-typed fields; the nested component/edge dataclasses
    # hold names/intents/relations (OPAQUE) and are covered by the byte
    # sweep, not enumerated field-by-field here (they carry no path/time).
    IRModule: {
        "name": OPAQUE,
        "layer": OPAQUE,
        "version": OPAQUE,
        "intent": OPAQUE,
        "content_hash": OPAQUE,
        "source_file": PATH,
        "transpiled_file": PATH,
    },
    # Build manifest schema (``build.s0ma.json``).
    BuildManifest: {
        "schema": OPAQUE,
        "project": OPAQUE,
        "build_dir": PATH,
        "transpiler_version": OPAQUE,
        "built_at": TIME,
    },
    ModuleManifestEntry: {
        "name": OPAQUE,
        "source": PATH,
        "output": PATH,
        "ir": PATH,
        "source_map": PATH,
        "source_hash": OPAQUE,
        "output_hash": OPAQUE,
        "role": OPAQUE,
        # STD-M5 (usability plan): the module's logical position in the
        # source tree. Both are project-root-relative POSIX strings (the
        # configured source-root entry and the path relative to it), so
        # they are PATH-classified and swept for absolute prefixes,
        # backslashes, and the project root exactly like ``source``.
        "source_root": PATH,
        "logical_path": PATH,
    },
    ExternalContentFileEntry: {
        "path": PATH,
        "hash": OPAQUE,
    },
    ArtifactReference: {
        "path": PATH,
        "sha256": OPAQUE,
    },
    # Source-map shape (``.s0ma.map``).
    SourceMap: {
        "version": OPAQUE,
        "source_file": PATH,
        "output_file": PATH,
    },
    DeclarationMapping: {
        "name": OPAQUE,
        "type": OPAQUE,
        "body_source_file": PATH,
    },
    ModuleHeaderMapping: {},  # all fields are LineRange (OPAQUE, non-str)
}


def _string_fields(klass: type) -> set[str]:
    """Return the names of *klass*'s fields whose type mentions ``str``.

    A field is treated as string-typed (and thus needs classification)
    when its annotation contains the token ``str`` and is not a
    container-of-dataclasses (``tuple[...]`` / ``dict[...]``). This is the
    same surface a future path/time field would land on.
    """
    out: set[str] = set()
    for f in dc.fields(klass):
        ann = str(f.type)
        # Skip nested-dataclass containers and tuple/dict aggregates —
        # they are swept as bytes, not classified as scalar path/time.
        if ann.startswith(("tuple[", "dict[")):
            continue
        if "Mapping" in ann or "LineRange" in ann:
            continue
        if "str" in ann:
            out.add(f.name)
    return out


def _path_fields(klass: type) -> list[str]:
    """Return *klass*'s PATH-classified field names from the enumeration."""
    return [
        field
        for field, cat in _SCHEMA_STRING_FIELD_CLASSIFICATION[klass].items()
        if cat == PATH
    ]


# ---------------------------------------------------------------------------
# Leak detectors (the sweep primitives)
# ---------------------------------------------------------------------------

# ISO-8601 timestamp shapes: a date with a ``T`` separator and a time,
# e.g. ``2026-06-11T22:25:13Z`` or ``...+00:00``. Deliberately strict so a
# bare semver / date never false-positives.
_ISO_TIMESTAMP_RE = re.compile(
    r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}"
)


def _text_leaks(text: str, *, project_root: str, label: str) -> list[str]:
    """Whole-artifact-text leak sweep (project root + timestamps).

    Applied to EVERY emitted byte. Detects the project-root path (in both
    POSIX ``/`` and Windows ``\\`` separator forms — a build on Windows
    would record the latter if a writer skipped normalisation) and any
    ISO-8601 timestamp.

    Deliberately does NOT flag bare backslashes: emitted ``.py`` bodies
    and JSON string values legitimately contain ``\\n`` / ``\\t`` / ``\\\\``
    escapes (authored code, doc-guide prose). Backslash-as-path-separator
    is caught precisely where it matters instead — the project-root form
    above, the field-level PATH checks (:func:`_path_field_violations`),
    and the absolute-path JSON-value walker (:func:`_absolute_path_strings`,
    which recognises ``C:\\`` drive paths).
    """
    violations: list[str] = []
    root_windows = project_root.replace("/", "\\")
    if project_root in text:
        violations.append(
            f"{label}: contains the project-root path {project_root!r}"
        )
    if root_windows != project_root and root_windows in text:
        violations.append(
            f"{label}: contains the project-root path (Windows form) "
            f"{root_windows!r}"
        )
    for m in _ISO_TIMESTAMP_RE.finditer(text):
        violations.append(
            f"{label}: contains an ISO-8601 timestamp {m.group(0)!r}"
        )
    return violations


def _path_field_violations(
    field: str, value: object, *, project_root: str, where: str
) -> list[str]:
    """Portability check for a single PATH-classified scalar field value.

    A committed-build PATH field must be project-root-relative POSIX (or a
    build-dir-relative basename): never absolute, never backslash-bearing,
    never the project root. ``None`` / non-string / empty values are
    vacuously fine (an optional path that was not recorded).
    """
    if not isinstance(value, str) or not value:
        return []
    violations: list[str] = []
    if value.startswith("/") or re.match(r"[A-Za-z]:[\\/]", value):
        violations.append(f"{where}.{field} is an absolute path: {value!r}")
    if "\\" in value:
        violations.append(
            f"{where}.{field} contains a backslash separator: {value!r}"
        )
    if project_root in value:
        violations.append(
            f"{where}.{field} contains the project root: {value!r}"
        )
    return violations


def _absolute_path_strings(value: object) -> list[str]:
    """Yield every string in a parsed-JSON *value* that is an absolute path.

    Walks dicts/lists recursively. "Absolute" = POSIX-absolute (leading
    ``/``) or Windows-drive-absolute (``C:\\`` / ``C:/``). Used by the
    field-level sweep and the negative-proof detector.
    """
    found: list[str] = []

    def _walk(node: object) -> None:
        if isinstance(node, str):
            if node.startswith("/") or re.match(r"[A-Za-z]:[\\/]", node):
                found.append(node)
        elif isinstance(node, dict):
            for v in node.values():
                _walk(v)
        elif isinstance(node, list):
            for v in node:
                _walk(v)

    _walk(value)
    return found


# ---------------------------------------------------------------------------
# The rich fixture — every writer that emits a path/time field.
#
# - DOMAIN module ``core`` with a HELPER (forces the helper emit path and
#   the source-map helper mapping) and a PUBLIC nerve.
# - PRESENTATION module ``greeting`` with an ``@file()``-embedded CONSTANT
#   cell (forces the manifest's external_content_files + the source map's
#   body_source_file redirect) and a rendering nerve.
# - A doc-ref + a doc-guide + an example (forces the rendered docs under
#   build_dir/docs/, with their YAML front matter).
# ---------------------------------------------------------------------------

_CORE_MODULE = textwrap.dedent(
    """\
module core
    layer: DOMAIN
    version: 1.0.0
    intent: "Core domain module: a helper, a public nerve, and the rendered docs that cover it."
    exports: [greet]

    requires: none
    uses: none
    soft_requires: none
    runtime_only_requires: none
    deferred_requires: none
    exports_helpers: none
helper _shout :: DOMAIN
    intent: "Uppercase a string for emphasis — module-private helper."
    ---
    def _shout(text: str) -> str:
        \"""Return ``text`` upper-cased.\"""
        return text.upper()

nerve greet :: DOMAIN
    kind: FUNCTION
    visibility: PUBLIC
    intent: "Greet a named user, delegating emphasis to the module helper."
    expects: "name is a non-empty string"
    guarantees: "returns a greeting string containing the name"
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
    def greet(name: str) -> str:
        \"""Return a greeting for ``name``.\"""
        return _shout("hello ") + name

doc-ref api_reference
    intent: "Generated reference for every public nerve in the core module."
    format: markdown
    output: docs/api_reference.md
    covers: [nerve where visibility == PUBLIC]
    sections: [intent, expects, guarantees]

example greet_example
    intent: "Demonstrates calling the greet nerve with a sample username."
    demonstrates: [nerve::greet]
    runs_in: standalone
    ---
    from core import greet

    print(greet("Ada"))

doc-guide getting_started
    intent: "Hand-authored walk-through of the greeting happy path."
    format: markdown
    output: docs/getting_started.md
    covers: [nerve::greet]
    asserts: [nerve::greet.visibility == PUBLIC]
    examples: [example::greet_example]
    ---
    # Getting Started

    The {{nerve::greet}} nerve takes a username and returns a greeting.

    Example usage is embedded below.
"""
)

_GREETING_MODULE = textwrap.dedent(
    """\
module greeting
    layer: PRESENTATION
    version: 1.0.0
    intent: "Embeds a template via @file() — exercises the embed + source-map writers."
    exports: [GREETING_TEMPLATE, render_greeting]

    requires: none
    uses: none
    soft_requires: none
    runtime_only_requires: none
    deferred_requires: none
    exports_helpers: none
cell GREETING_TEMPLATE :: PRESENTATION
    kind: CONSTANT
    visibility: PUBLIC
    intent: "Greeting template text embedded from an external file with a declared placeholder."
    schema: "str constant; the __NAME__ marker is substituted at render time."
    content: @file("templates/greet.txt")
    placeholders: [__NAME__]

    invariants: none
    covered_by: none
nerve render_greeting :: PRESENTATION
    kind: FUNCTION
    visibility: PUBLIC
    intent: "Render the greeting template by substituting the declared placeholder marker."
    expects: "name is a plain string"
    guarantees: "returns the template with the marker replaced"
    forbids: none
    evaluates_at: FUNCTION_BOUNDARY
    depends_on:
        GREETING_TEMPLATE: {relation: READS, carries: "template text", coupling: TIGHT}
    provides: none
    returns: none
    raises: none
    interface: none
    latency_ms: none
    internal: none
    expected_exceptions: none
    consumes_via_dict: none
    declares_attributes: none
    covered_by: none
    ---
    def render_greeting(name: str) -> str:
        \"""Render the greeting for ``name``.\"""
        return GREETING_TEMPLATE.replace("__NAME__", name)
"""
)

_GREET_TEMPLATE_TEXT = "Hello __NAME__.\nSecond line stays verbatim.\n"


@pytest.fixture()
def sweep_project(tmp_path: Path) -> Path:
    """A multi-module [tool.s0ma] project exercising every path/time writer.

    Nested ``build_dir`` (``out/build``) so a relative-vs-absolute bug in
    any writer surfaces as the tmp-dir absolute path inside an artifact.

    STD-M5: ``core.s0ma`` lives in a feature subdirectory
    (``src/greetings/``) so the manifest's ``logical_path`` carries a
    multi-segment POSIX path (``greetings/core.s0ma``) — the shape a
    Windows build would record with backslashes if the writer skipped
    ``.as_posix()``. ``greeting.s0ma`` stays at the source-root top
    (``logical_path == "greeting.s0ma"``) so both the nested and the
    top-level cases are swept. The build directory stays flat regardless
    (Decision 3 / Option B): both modules emit as ``<name>.py`` at the
    build root.
    """
    project = tmp_path / "sweep_proj"
    (project / "src" / "greetings").mkdir(parents=True)
    (project / "src" / "templates").mkdir(parents=True)
    (project / "pyproject.toml").write_text(
        textwrap.dedent(
            """\
            [project]
            name = "sweep_proj"
            version = "0.1.0"

            [tool.s0ma]
            source_roots = ["src"]
            build_dir = "out/build"
            mode = "dev"
            """
        ),
        encoding="utf-8",
        newline="\n",
    )
    (project / "src" / "greetings" / "core.s0ma").write_text(
        _CORE_MODULE, encoding="utf-8", newline="\n"
    )
    (project / "src" / "greeting.s0ma").write_text(
        _GREETING_MODULE, encoding="utf-8", newline="\n"
    )
    (project / "src" / "templates" / "greet.txt").write_text(
        _GREET_TEMPLATE_TEXT, encoding="utf-8", newline="\n"
    )
    return project


def _build(project: Path) -> Path:
    """Build *project* (no --mode flag — the table declares dev) and return its build dir."""
    cli = S0maCLI()
    rc = cli.run([
        "--project-root", str(project),
        "build", str(project),
        "--no-cache",
    ])
    assert rc == EXIT_SUCCESS, "fixture project must build cleanly"
    return project / "out" / "build"


def _all_artifact_files(build_dir: Path) -> list[Path]:
    """Every emitted artifact file under *build_dir*, recursively (incl. docs/)."""
    return sorted(p for p in build_dir.rglob("*") if p.is_file())


# ---------------------------------------------------------------------------
# Schema coverage gate
# ---------------------------------------------------------------------------


def test_every_schema_string_field_is_classified() -> None:
    """Every string-typed schema field must be classified (PATH/TIME/OPAQUE).

    This is the schema-driven trip-wire: add a string field to any
    artifact schema dataclass and this test fails until you classify it
    in ``_SCHEMA_STRING_FIELD_CLASSIFICATION`` — forcing the "can this
    carry a machine path or a timestamp?" decision the moment the field
    ships, not when it first breaks a cross-machine build (F-M2-1).
    """
    for klass, classification in _SCHEMA_STRING_FIELD_CLASSIFICATION.items():
        actual = _string_fields(klass)
        classified = set(classification)
        missing = actual - classified
        assert not missing, (
            f"{klass.__module__}.{klass.__qualname__} has unclassified "
            f"string field(s) {sorted(missing)} — add them to "
            f"_SCHEMA_STRING_FIELD_CLASSIFICATION (PATH if they hold a "
            f"filesystem path, TIME if a timestamp, OPAQUE otherwise) so "
            f"the portability sweep covers them. This trip-wire is the "
            f"F-M2-1 fix: a new path/time field must be classified the "
            f"day it ships."
        )
        stale = classified - actual
        assert not stale, (
            f"{klass.__module__}.{klass.__qualname__} classifies "
            f"field(s) {sorted(stale)} that no longer exist on the "
            f"schema — remove them from the classification map."
        )


def test_classification_covers_the_three_artifact_schemas() -> None:
    """The enumeration spans IR, manifest, and source-map schemas.

    A blunt guard that the single classification table did not silently
    drop one of the three artifact families F-M2-1 names.
    """
    classified = set(_SCHEMA_STRING_FIELD_CLASSIFICATION)
    assert IRModule in classified, "IR component/module schema missing"
    assert {
        BuildManifest,
        ArtifactReference,
        ModuleManifestEntry,
        ExternalContentFileEntry,
    } <= classified, "build-manifest schema incompletely covered"
    assert {
        SourceMap,
        DeclarationMapping,
        ModuleHeaderMapping,
    } <= classified, "source-map shape incompletely covered"
    # At least one PATH and one TIME field must exist, or the sweep below
    # is vacuous.
    all_cats = {
        cat
        for fields in _SCHEMA_STRING_FIELD_CLASSIFICATION.values()
        for cat in fields.values()
    }
    assert PATH in all_cats
    assert TIME in all_cats


# ---------------------------------------------------------------------------
# The real corpus passes — every artifact byte is portable
# ---------------------------------------------------------------------------


def test_real_build_has_no_portability_leaks(sweep_project: Path) -> None:
    """Every artifact byte of the rich build is portable.

    Sweeps EVERY emitted file (recursively, including rendered docs)
    for the project-root path, backslash separators, and ISO-8601
    timestamps. This is the positive half of the F-M2-1 fix: the whole
    committed-build surface is checked, not the fields a hand-written
    fixture happened to touch.
    """
    build_dir = _build(sweep_project)
    project_root = str(sweep_project)

    artifacts = _all_artifact_files(build_dir)
    # Sanity: the fixture really did exercise the doc + embed writers.
    names = {p.name for p in artifacts}
    assert "build.s0ma.json" in names
    assert any(p.suffix == ".map" for p in artifacts), "no source maps emitted"
    assert (build_dir / "docs").is_dir(), "no rendered docs emitted"

    all_violations: list[str] = []
    for artifact in artifacts:
        text = artifact.read_text(encoding="utf-8")
        rel = artifact.relative_to(build_dir).as_posix()
        all_violations.extend(
            _text_leaks(text, project_root=project_root, label=rel)
        )
        # Field-level absolute-path sweep for JSON artifacts (IR, manifest,
        # source map): no string value anywhere may be an absolute path.
        if artifact.suffix == ".json" or artifact.name.endswith(".map"):
            try:
                parsed = json.loads(text)
            except json.JSONDecodeError:
                continue
            for abs_str in _absolute_path_strings(parsed):
                all_violations.append(
                    f"{rel}: JSON value is an absolute path {abs_str!r}"
                )

    assert not all_violations, (
        "artifact portability leak(s) detected:\n  "
        + "\n  ".join(all_violations)
    )


def test_schema_path_fields_are_portable_in_real_build(
    sweep_project: Path,
) -> None:
    """Each schema PATH field's emitted value is portable in the real build.

    Reads the actual emitted JSON artifacts and checks every PATH-classified
    field's value: not absolute, no backslash, not the project root. This
    asserts coverage at the schema-field granularity (not just whole-byte),
    so a field that leaks ONLY a relative-but-CWD-dependent path (which the
    whole-byte project-root sweep could miss) is still caught.
    """
    build_dir = _build(sweep_project)
    project_root = str(sweep_project)
    violations: list[str] = []

    def _check(klass: type, obj: dict[str, object], where: str) -> None:
        for field in _path_fields(klass):
            violations.extend(
                _path_field_violations(
                    field, obj.get(field), project_root=project_root, where=where
                )
            )

    # Manifest PATH fields (top-level + nested module/embed entries).
    manifest = json.loads(
        (build_dir / "build.s0ma.json").read_text(encoding="utf-8")
    )
    _check(BuildManifest, manifest, "manifest")
    for entry in manifest.get("modules", []):
        _check(
            ModuleManifestEntry, entry, f"manifest.modules[{entry.get('name')}]"
        )
    for key, entry in manifest.get("external_content_files", {}).items():
        _check(ExternalContentFileEntry, entry, f"external_content_files[{key}]")

    # IR PATH fields, per module.
    for ir_path in build_dir.glob("*.s0ma.json"):
        ir = json.loads(ir_path.read_text(encoding="utf-8"))
        _check(IRModule, ir.get("module", {}), f"{ir_path.name}.module")

    # Source-map PATH fields, per module (top-level + per declaration).
    for map_path in build_dir.glob("*.s0ma.map"):
        smap = json.loads(map_path.read_text(encoding="utf-8"))
        _check(SourceMap, smap, map_path.name)
        for decl in smap.get("mappings", {}).get("declarations", []):
            _check(
                DeclarationMapping,
                decl,
                f"{map_path.name}.{decl.get('name')}",
            )

    assert not violations, (
        "schema PATH-field leak(s):\n  " + "\n  ".join(violations)
    )


def test_manifest_records_logical_structure(sweep_project: Path) -> None:
    """STD-M5: each module's ``source_root`` + ``logical_path`` are recorded.

    The build manifest records each module's logical position in the
    source tree (Decision 3 / Option B) while the build directory stays
    flat. This pins the exact recorded values for the fixture — the
    nested module (``src/greetings/core.s0ma``) and the top-level one
    (``src/greeting.s0ma``) — and re-asserts at the field granularity
    that neither value carries a backslash separator or a drive-letter /
    absolute prefix (the cross-OS determinism hazard this milestone
    guards). The build dir staying flat is asserted too: both modules
    emit as ``<name>.py`` at the build root regardless of source nesting.
    """
    build_dir = _build(sweep_project)
    manifest = json.loads(
        (build_dir / "build.s0ma.json").read_text(encoding="utf-8")
    )
    by_name = {m["name"]: m for m in manifest["modules"]}
    assert set(by_name) == {"core", "greeting"}, by_name

    # Exact recorded logical structure (project-root-relative POSIX).
    assert by_name["core"]["source_root"] == "src"
    assert by_name["core"]["logical_path"] == "greetings/core.s0ma"
    assert by_name["greeting"]["source_root"] == "src"
    assert by_name["greeting"]["logical_path"] == "greeting.s0ma"

    # Field-level portability: forward-slash POSIX only, never absolute.
    # ``re`` / the absolute-prefix shape mirror the sweep primitives.
    for name, entry in by_name.items():
        for field in ("source_root", "logical_path"):
            value = entry[field]
            assert "\\" not in value, (
                f"{name}.{field} has a backslash separator: {value!r}"
            )
            assert not value.startswith("/"), (
                f"{name}.{field} is POSIX-absolute: {value!r}"
            )
            assert not re.match(r"[A-Za-z]:[\\/]", value), (
                f"{name}.{field} has a drive-letter prefix: {value!r}"
            )
            assert str(sweep_project) not in value, (
                f"{name}.{field} leaked the project root: {value!r}"
            )

    # Decision 3 / Option B: the build directory stays FLAT — the nested
    # source path is recorded in the manifest, not mirrored on disk.
    assert (build_dir / "core.py").is_file()
    assert (build_dir / "greeting.py").is_file()
    assert not (build_dir / "greetings").exists()


# ---------------------------------------------------------------------------
# Negative proof — the detector actually detects
# ---------------------------------------------------------------------------


def test_sweep_catches_injected_absolute_path(sweep_project: Path) -> None:
    """Injecting a synthetic absolute path into a parsed artifact is caught.

    Proves the detector is not vacuous: take a real, clean artifact dict,
    inject ``/private/var/evil/leaked.s0ma`` into a PATH-shaped field, and
    assert BOTH the whole-byte sweep and the recursive absolute-path
    walker flag it. Without this, a sweep that silently passes everything
    would look identical to a sweep that works.
    """
    build_dir = _build(sweep_project)
    manifest_text = (build_dir / "build.s0ma.json").read_text(encoding="utf-8")
    parsed = json.loads(manifest_text)

    # Real manifest is clean (guards the test's own premise).
    assert not _absolute_path_strings(parsed), (
        "fixture manifest already carries an absolute path — the negative "
        "proof needs a clean baseline"
    )

    injected = "/private/var/evil/leaked.s0ma"
    parsed["modules"][0]["source"] = injected

    # 1. The recursive absolute-path walker (used by the whole-artifact
    #    JSON sweep) finds it.
    found = _absolute_path_strings(parsed)
    assert injected in found, "absolute-path walker missed the injection"

    # 2. The field-level PATH check (used by the schema-field sweep) flags
    #    the very field it was injected into.
    field_violations = _path_field_violations(
        "source",
        parsed["modules"][0]["source"],
        project_root=str(sweep_project),
        where="manifest.modules[core]",
    )
    assert any("absolute path" in v for v in field_violations), (
        "field-level PATH check missed the injected absolute path"
    )


def test_sweep_catches_injected_timestamp() -> None:
    """The timestamp detector catches an injected ISO-8601 ``built_at``.

    The ``built_at`` field is TIME-classified and the writer never emits
    it (F-M0-8), but a regression that re-introduced it would carry an
    ISO-8601 string. Prove the whole-text sweep catches that shape so the
    sweep is not vacuous on the TIME axis.
    """
    tampered = json.dumps({"built_at": "2026-06-11T22:25:13Z"})
    violations = _text_leaks(
        tampered, project_root="/nonexistent-root", label="manifest"
    )
    assert any("ISO-8601 timestamp" in v for v in violations), (
        "timestamp detector missed an injected built_at"
    )


def test_sweep_catches_injected_backslash_path() -> None:
    """The field-level PATH check catches a Windows-style separator leak.

    A backslash separator in a PATH field (e.g. a Windows build that
    skipped POSIX normalisation recording ``src\\core.s0ma``) must be
    caught. The whole-text sweep deliberately tolerates backslashes (they
    appear as ``\\n`` escapes in code/prose bodies), so this guard lives at
    the field level where a backslash is unambiguously a path-separator
    leak.
    """
    violations = _path_field_violations(
        "source",
        "src\\core.s0ma",
        project_root="/nonexistent-root",
        where="manifest.modules[core]",
    )
    assert any("backslash" in v for v in violations), (
        "backslash detector missed an injected Windows path separator"
    )


def test_text_sweep_tolerates_escaped_newlines() -> None:
    """The whole-text sweep does NOT false-positive on ``\\n`` escapes.

    Emitted ``.py`` bodies and JSON doc-guide prose legitimately contain
    backslash-escape sequences. The whole-text sweep must not flag them —
    only the project root and timestamps. This pins the design decision so
    a future "tighten the backslash check" change cannot silently make the
    real-corpus sweep flaky.
    """
    body = json.dumps({"body": "from core import greet\n\nprint(greet('x'))"})
    assert "\\n" in body  # the literal escape is present in the bytes
    violations = _text_leaks(
        body, project_root="/nonexistent-root", label="core.py"
    )
    assert violations == [], (
        "whole-text sweep false-positived on a legitimate escape sequence"
    )
