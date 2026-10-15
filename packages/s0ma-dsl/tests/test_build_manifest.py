"""M6b (feedback 5–6, ADR-007) — build manifest invariants.

Locks down the post-M6b build-manifest contract:

- ``s0ma build`` emits a single ``build.s0ma.json`` at the build root,
  carrying every required field of the ``s0ma-build-manifest@1`` schema.
- The manifest is internally consistent: each listed module has its
  ``.py`` / ``.s0ma.json`` / ``.s0ma.map`` triple on disk, and the
  recorded source/output hashes match the bytes those files contain.
- The runtime bridge's manifest-driven import path is the source of
  truth for ``what was built``: pointed at a build dir, it reads the
  manifest and imports exactly those modules.
- A missing/malformed manifest raises a loud, remediating error rather
  than silently falling back to filesystem traversal.

Pairs with ``tests/test_migrate_layout.py`` (the migration-command
half of M6b) and ``tests/test_build_layout.py`` (the M6a layout half).
"""

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

from s0ma_dsl import __version__ as transpiler_version
from s0ma_dsl.cli.main import EXIT_SUCCESS, S0maCLI
from s0ma_dsl.codegen.build_manifest import (
    MANIFEST_FILENAME,
    MANIFEST_SCHEMA,
    ManifestSchemaError,
    ModuleManifestEntry,
    build_manifest,
    compute_file_hash,
    emit_manifest,
    load_manifest,
)

FIXTURE = Path(__file__).parent / "fixtures" / "multi_module_project"
EXPECTED_MODULES = ("models", "processing", "routing")


# ---------------------------------------------------------------------------
# Build-time fixture
# ---------------------------------------------------------------------------


@pytest.fixture()
def built_project(tmp_path: Path) -> Path:
    """Build the multi_module_project fixture into a fresh tmp output dir."""
    out_dir = tmp_path / "build"
    cli = S0maCLI()
    rc = cli.run([
        "build", str(FIXTURE),
        "--output-dir", str(out_dir),
        "--mode", "dev",
        "--no-cache",
    ])
    assert rc == EXIT_SUCCESS, "fixture build failed"
    return out_dir


# ---------------------------------------------------------------------------
# Acceptance — manifest emission
# ---------------------------------------------------------------------------


def test_build_emits_manifest(built_project: Path) -> None:
    """A fresh build produces a build.s0ma.json at the build root.

    Acceptance criterion (M6b): every successful build emits a
    manifest. The manifest is JSON-decodable, has the canonical schema
    string, and lists every emitted module.
    """
    manifest_path = built_project / MANIFEST_FILENAME
    assert manifest_path.is_file(), (
        f"missing build manifest at {manifest_path}; "
        f"the build directory contained: "
        f"{sorted(p.name for p in built_project.iterdir())}"
    )

    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    # Required top-level fields, every type-checked.
    assert payload["schema"] == MANIFEST_SCHEMA
    assert isinstance(payload["project"], str) and payload["project"]
    assert isinstance(payload["build_dir"], str) and payload["build_dir"]
    assert payload["transpiler_version"] == transpiler_version
    # SH-M1 (selfhost plan, INV-5): the build pipeline no longer stamps
    # wall-clock time into the manifest — the key is absent so two
    # builds of the same input are byte-identical. (Explicitly-set
    # values still round-trip; see test_built_at_round_trips_when_set.)
    assert "built_at" not in payload, (
        f"built_at must not be emitted by the build pipeline (INV-5): "
        f"{payload.get('built_at')!r}"
    )

    # Every fixture module is listed exactly once.
    listed = {m["name"] for m in payload["modules"]}
    assert listed == set(EXPECTED_MODULES), (
        f"manifest module set mismatch; expected {set(EXPECTED_MODULES)} "
        f"got {listed}"
    )

    references = payload["self_context"]
    assert set(references) == {"json", "prompt_card"}
    for reference in references.values():
        assert "\\" not in reference["path"]
        artifact = built_project / reference["path"]
        assert artifact.is_file()
        assert compute_file_hash(artifact.read_bytes()) == reference["sha256"]


def test_legacy_manifest_loads_without_self_context(tmp_path: Path) -> None:
    """The additive field does not break pre-M6 manifest readers."""
    manifest = build_manifest(
        project_name="legacy",
        build_dir="build",
        modules=[],
        transpiler_version="0.13.0",
    )
    emit_manifest(manifest, tmp_path)
    loaded = load_manifest(tmp_path)
    assert loaded.schema == MANIFEST_SCHEMA
    assert loaded.self_context is None


def test_build_manifest_is_valid(built_project: Path) -> None:
    """Every module entry resolves to a real triple with matching hashes.

    Acceptance criterion (M6b): the manifest is internally consistent
    with what landed on disk. Source-hash and output-hash claims must
    actually match the bytes of the files they reference.
    """
    manifest = load_manifest(built_project)
    assert manifest.schema == MANIFEST_SCHEMA
    assert {m.name for m in manifest.modules} == set(EXPECTED_MODULES)

    for entry in manifest.modules:
        # Triple exists on disk under the basenames the manifest names.
        py_path = built_project / entry.output
        ir_path = built_project / entry.ir
        map_path = built_project / entry.source_map
        assert py_path.is_file(), (
            f"manifest names {entry.output} for module {entry.name} but "
            f"that file is not present"
        )
        assert ir_path.is_file()
        assert map_path.is_file()

        # Source hash matches what the original .s0ma file contains.
        source_path = Path(entry.source)
        assert source_path.is_file(), (
            f"manifest source path is not on disk: {source_path}"
        )
        expected_source_hash = compute_file_hash(
            source_path.read_text(encoding="utf-8")
        )
        assert entry.source_hash == expected_source_hash, (
            f"source_hash for {entry.name} drifted from disk content"
        )

        # Output hash matches the .py the build wrote.
        expected_output_hash = compute_file_hash(
            py_path.read_text(encoding="utf-8")
        )
        assert entry.output_hash == expected_output_hash, (
            f"output_hash for {entry.name} drifted from disk content"
        )


def test_runtime_bridge_reads_manifest(
    built_project: Path, tmp_path: Path,
) -> None:
    """The runtime bridge imports modules listed in the manifest, in order.

    Acceptance criterion (M6b): ``import_modules_from_manifest`` is the
    runtime's source of truth for what to import. Stub the manifest
    against the real fixture build to keep the test honest, then run
    the import through a child process so the manifest-driven sys.path
    insert does not pollute the test session.
    """
    code = textwrap.dedent(f"""
        from pathlib import Path
        from s0ma_dsl.runtime_bridge.registration import (
            import_modules_from_manifest,
        )
        imported = import_modules_from_manifest(Path({str(built_project)!r}))
        names = list(imported.keys())
        # Manifest-driven order: alphabetical pre-M10. Verify the
        # *set* matches the expected modules and that the dict has
        # exactly one entry per module name.
        expected = {set(EXPECTED_MODULES)!r}
        assert set(names) == expected, (set(names), expected)
        assert len(names) == len(set(names))
        # Every imported value is a real Python module exposing the
        # canonical module name as its __name__.
        for name, mod in imported.items():
            assert mod.__name__ == name, (mod.__name__, name)
        print('OK')
    """)
    proc = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, (
        f"manifest-driven import failed:\n"
        f"stdout={proc.stdout!r}\nstderr={proc.stderr!r}"
    )
    assert "OK" in proc.stdout


def test_manifest_missing_raises_schema_error(tmp_path: Path) -> None:
    """A loud failure is required when the manifest is missing.

    The plan calls out "no silent fallbacks" — a build directory
    without a manifest is a coherent error, not a recover-and-guess
    state. The exception's message must point at the remediation
    (`s0ma build` to (re)generate, `s0ma migrate-layout` for legacy).
    """
    build_dir = tmp_path / "no_manifest_here"
    build_dir.mkdir()
    with pytest.raises(ManifestSchemaError) as excinfo:
        load_manifest(build_dir)
    msg = str(excinfo.value)
    assert "s0ma build" in msg
    assert "migrate-layout" in msg


def test_manifest_schema_mismatch_raises(tmp_path: Path) -> None:
    """A manifest with the wrong schema string raises, does not silently parse.

    When M10 / M12 extend the schema additively under
    ``s0ma-build-manifest@1`` they *do not* bump the schema string.
    A future ``s0ma-build-manifest@2`` is reserved for breaking
    changes. This test pins that contract: a manifest with any other
    schema string is rejected at load time.
    """
    build_dir = tmp_path / "bad_schema"
    build_dir.mkdir()
    bogus = {
        "schema": "s0ma-build-manifest@99",
        "project": "x",
        "build_dir": str(build_dir),
        "transpiler_version": "0.0.0",
        "built_at": "2026-04-28T00:00:00Z",
        "modules": [],
    }
    (build_dir / MANIFEST_FILENAME).write_text(
        json.dumps(bogus), encoding="utf-8"
    )
    with pytest.raises(ManifestSchemaError):
        load_manifest(build_dir)


# ---------------------------------------------------------------------------
# Round-trip and helper-level invariants
# ---------------------------------------------------------------------------


def test_manifest_round_trip(tmp_path: Path) -> None:
    """``emit_manifest`` then ``load_manifest`` round-trips byte-equal data."""
    entry = ModuleManifestEntry(
        name="alpha",
        source="/abs/path/alpha.s0ma",
        output="alpha.py",
        ir="alpha.s0ma.json",
        source_map="alpha.s0ma.map",
        source_hash="sha256:" + "0" * 64,
        output_hash="sha256:" + "1" * 64,
    )
    manifest = build_manifest(
        project_name="demo",
        build_dir=tmp_path,
        modules=[entry],
        transpiler_version="0.12.0",
        built_at="2026-04-28T00:00:00Z",
    )
    emitted = emit_manifest(manifest, tmp_path)
    assert emitted == tmp_path / MANIFEST_FILENAME

    loaded = load_manifest(tmp_path)
    assert loaded.to_dict() == manifest.to_dict()


def test_manifest_modules_sorted_by_name(tmp_path: Path) -> None:
    """Pre-M10, manifest module order is alphabetical for determinism."""
    out_of_order = [
        ModuleManifestEntry(
            name=name,
            source=f"/abs/{name}.s0ma",
            output=f"{name}.py",
            ir=f"{name}.s0ma.json",
            source_map=f"{name}.s0ma.map",
            source_hash="sha256:" + "0" * 64,
            output_hash="sha256:" + "1" * 64,
        )
        for name in ("zeta", "alpha", "mu")
    ]
    manifest = build_manifest(
        project_name="demo",
        build_dir=tmp_path,
        modules=out_of_order,
        transpiler_version="0.12.0",
        built_at="2026-04-28T00:00:00Z",
    )
    assert [m.name for m in manifest.modules] == ["alpha", "mu", "zeta"]


def test_compute_file_hash_uses_sha256_with_prefix() -> None:
    """``compute_file_hash`` returns the canonical ``sha256:<hex>`` form.

    The IR's ``content_hash`` field uses the same convention; the
    manifest's hashes mirror it so downstream consumers can read both
    with one parser.
    """
    text = "hello manifest"
    expected = hashlib.sha256(text.encode("utf-8")).hexdigest()
    assert compute_file_hash(text) == f"sha256:{expected}"
    # Bytes branch is equivalent to the str branch on UTF-8 text.
    assert compute_file_hash(text.encode("utf-8")) == f"sha256:{expected}"


def test_manifest_stdout_summary_mentions_manifest(
    tmp_path: Path, capsys: pytest.CaptureFixture[str],
) -> None:
    """The build's stdout summary points at the manifest by name.

    Acceptance criterion (M6b): the user-visible summary includes
    "manifest: build.s0ma.json" so consumers know where to read.
    """
    out_dir = tmp_path / "fr3d_build"
    cli = S0maCLI()
    rc = cli.run([
        "build", str(FIXTURE),
        "--output-dir", str(out_dir),
        "--mode", "dev",
        "--no-cache",
    ])
    assert rc == EXIT_SUCCESS
    out = capsys.readouterr().out
    # New-shape summary line, one of the M6b acceptance criteria.
    assert (
        f"Build complete: 3 module(s) → {out_dir.as_posix()} "
        f"(manifest: {MANIFEST_FILENAME})"
        in out
    )


# ---------------------------------------------------------------------------
# SH-M1 (selfhost plan) — INV-5 portable artifacts
# ---------------------------------------------------------------------------


SH_M1_MODULE = textwrap.dedent(
    """\
module portable
    layer: DOMAIN
    version: 1.0.0
    intent: "Single module proving INV-5 portable artifact recording."
    exports: [answer]

    requires: none
    uses: none
    soft_requires: none
    runtime_only_requires: none
    deferred_requires: none
    exports_helpers: none
nerve answer :: DOMAIN
    kind: FUNCTION
    visibility: PUBLIC
    intent: "Return the canonical fixed answer for the portability test."
    expects: "no arguments"
    guarantees: "returns the integer 42"
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
    def answer() -> int:
        return 42
"""
)


@pytest.fixture()
def portable_project(tmp_path: Path) -> Path:
    """A real [tool.s0ma] project in a tmp dir (nested build_dir)."""
    project = tmp_path / "portable_proj"
    (project / "src").mkdir(parents=True)
    (project / "pyproject.toml").write_text(
        textwrap.dedent(
            """\
            [project]
            name = "portable_proj"
            version = "0.1.0"

            [tool.s0ma]
            source_roots = ["src"]
            build_dir = "out/portable_build"
            """
        ),
        encoding="utf-8",
        newline="\n",
    )
    (project / "src" / "portable.s0ma").write_text(
        SH_M1_MODULE, encoding="utf-8", newline="\n"
    )
    return project


def test_project_build_records_portable_paths(portable_project: Path) -> None:
    """SH-M1 / INV-5: project-resolved builds embed no machine paths.

    The manifest's ``source`` and ``build_dir`` and the IR's / source
    map's ``source_file`` are recorded project-root-relative in POSIX
    form, and ``built_at`` is absent — so the committed-build equality
    gate (FR-MCP-11, plan D-4) can byte-compare rebuilds across
    machines, working directories, and operating systems.
    """
    cli = S0maCLI()
    rc = cli.run([
        "--project-root", str(portable_project),
        "build", str(portable_project),
        "--mode", "dev",
        "--no-cache",
    ])
    assert rc == EXIT_SUCCESS
    build_dir = portable_project / "out" / "portable_build"

    payload = json.loads(
        (build_dir / MANIFEST_FILENAME).read_text(encoding="utf-8")
    )
    assert payload["build_dir"] == "out/portable_build", payload["build_dir"]
    assert "built_at" not in payload
    (entry,) = payload["modules"]
    assert entry["source"] == "src/portable.s0ma", entry["source"]

    ir = json.loads(
        (build_dir / "portable.s0ma.json").read_text(encoding="utf-8")
    )
    assert ir["module"]["source_file"] == "src/portable.s0ma", (
        ir["module"]["source_file"]
    )

    smap = json.loads(
        (build_dir / "portable.s0ma.map").read_text(encoding="utf-8")
    )
    assert smap["source_file"] == "src/portable.s0ma", smap["source_file"]

    # No artifact byte anywhere may contain the tmp dir's absolute path
    # (INV-5: no absolute machine paths in emitted artifacts).
    needle = str(portable_project)
    for artifact in sorted(build_dir.iterdir()):
        if artifact.is_file():
            assert needle not in artifact.read_text(encoding="utf-8"), (
                f"absolute machine path leaked into {artifact.name}"
            )


def test_project_rebuild_is_byte_identical(portable_project: Path) -> None:
    """SH-M1 / P-4: two cold project builds produce identical bytes.

    Pre-SH-M1 the manifest's ``built_at`` differed between any two
    runs by design; with the field gone the whole build directory is
    byte-stable — the property the selfhost-build equality stage in
    ``scripts/check.py`` stands on.
    """
    cli = S0maCLI()
    args = [
        "--project-root", str(portable_project),
        "build", str(portable_project),
        "--mode", "dev",
        "--no-cache",
    ]
    build_dir = portable_project / "out" / "portable_build"

    assert cli.run(args) == EXIT_SUCCESS
    first = {
        p.name: p.read_bytes() for p in build_dir.iterdir() if p.is_file()
    }
    assert cli.run(args) == EXIT_SUCCESS
    second = {
        p.name: p.read_bytes() for p in build_dir.iterdir() if p.is_file()
    }
    assert first == second


SH_M2_EMBED_MODULE = textwrap.dedent(
    """\
module greeting
    layer: PRESENTATION
    version: 1.0.0
    intent: "Embedded-template module proving INV-5 portable @file() path recording."
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
    intent: "Greeting template text embedded from an external file with declared placeholders."
    schema: "str constant; the __NAME__ marker is substituted at render time."
    content: @file("templates/greet.txt")
    placeholders: [__NAME__]

    invariants: none
    covered_by: none
nerve render_greeting :: PRESENTATION
    kind: FUNCTION
    visibility: PUBLIC
    intent: "Renders the greeting template by substituting the declared placeholder marker."
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

SH_M2_EMBED_TEXT = "Hello __NAME__.\nSecond line stays verbatim.\n"


@pytest.fixture()
def embed_project(tmp_path: Path) -> Path:
    """A [tool.s0ma] project whose one module embeds an @file() template."""
    project = tmp_path / "embed_proj"
    (project / "src" / "templates").mkdir(parents=True)
    (project / "pyproject.toml").write_text(
        textwrap.dedent(
            """\
            [project]
            name = "embed_proj"
            version = "0.1.0"

            [tool.s0ma]
            source_roots = ["src"]
            build_dir = "out/embed_build"
            """
        ),
        encoding="utf-8",
        newline="\n",
    )
    (project / "src" / "greeting.s0ma").write_text(
        SH_M2_EMBED_MODULE, encoding="utf-8", newline="\n"
    )
    (project / "src" / "templates" / "greet.txt").write_text(
        SH_M2_EMBED_TEXT, encoding="utf-8", newline="\n"
    )
    return project


def test_project_build_records_portable_embed_paths(
    embed_project: Path,
) -> None:
    """SH-M2 / INV-5: ``@file()`` embeds record no machine paths either.

    The source map's ``body_source_file`` redirect for an embedded
    CONSTANT cell is recorded project-root-relative in POSIX form (it
    was the one remaining artifact field that embedded the resolved
    absolute path), the manifest's ``external_content_files`` keeps the
    as-authored relative path, and no artifact byte anywhere contains
    the project's absolute path — so committed builds with embedded
    prompt/SQL/HTML templates byte-reproduce across machines and OSes.
    """
    cli = S0maCLI()
    args = [
        "--project-root", str(embed_project),
        "build", str(embed_project),
        "--mode", "dev",
        "--no-cache",
    ]
    assert cli.run(args) == EXIT_SUCCESS
    build_dir = embed_project / "out" / "embed_build"

    smap = json.loads(
        (build_dir / "greeting.s0ma.map").read_text(encoding="utf-8")
    )
    (cell_mapping,) = [
        d
        for d in smap["mappings"]["declarations"]
        if d["name"] == "GREETING_TEMPLATE"
    ]
    assert cell_mapping["body_source_file"] == "src/templates/greet.txt", (
        cell_mapping["body_source_file"]
    )

    payload = json.loads(
        (build_dir / MANIFEST_FILENAME).read_text(encoding="utf-8")
    )
    embed_entry = payload["external_content_files"]["greeting::GREETING_TEMPLATE"]
    assert embed_entry["path"] == "templates/greet.txt", embed_entry["path"]

    # No artifact byte anywhere may contain the tmp dir's absolute path
    # (INV-5: no absolute machine paths in emitted artifacts).
    needle = str(embed_project)
    for artifact in sorted(build_dir.iterdir()):
        if artifact.is_file():
            assert needle not in artifact.read_text(encoding="utf-8"), (
                f"absolute machine path leaked into {artifact.name}"
            )

    # And the embed-carrying build stays byte-deterministic (P-4).
    first = {
        p.name: p.read_bytes() for p in build_dir.iterdir() if p.is_file()
    }
    assert cli.run(args) == EXIT_SUCCESS
    second = {
        p.name: p.read_bytes() for p in build_dir.iterdir() if p.is_file()
    }
    assert first == second


def test_synthetic_transpile_keeps_legacy_embed_paths(tmp_path: Path) -> None:
    """No-project transpiles keep the resolved-absolute embed redirect.

    The portable form needs a project root to be relative to; the
    synthetic fallback documents the legacy behavior (same policy split
    as SH-M1's ``source_file`` recording).
    """
    workdir = tmp_path / "loose"
    (workdir / "templates").mkdir(parents=True)
    (workdir / "greeting.s0ma").write_text(
        SH_M2_EMBED_MODULE, encoding="utf-8", newline="\n"
    )
    (workdir / "templates" / "greet.txt").write_text(
        SH_M2_EMBED_TEXT, encoding="utf-8", newline="\n"
    )
    cli = S0maCLI()
    rc = cli.run(
        ["transpile", str(workdir / "greeting.s0ma"), "--mode", "dev"]
    )
    assert rc == EXIT_SUCCESS
    smap = json.loads(
        (workdir / "greeting.s0ma.map").read_text(encoding="utf-8")
    )
    (cell_mapping,) = [
        d
        for d in smap["mappings"]["declarations"]
        if d["name"] == "GREETING_TEMPLATE"
    ]
    recorded = Path(cell_mapping["body_source_file"])
    assert recorded.is_absolute()
    assert recorded == (workdir / "templates" / "greet.txt").resolve()


def test_built_at_round_trips_when_set(tmp_path: Path) -> None:
    """An explicitly-set ``built_at`` still emits and loads (legacy fixtures)."""
    manifest = build_manifest(
        project_name="demo",
        build_dir=tmp_path,
        modules=[],
        transpiler_version="0.12.0",
        built_at="2026-04-28T00:00:00Z",
    )
    emit_manifest(manifest, tmp_path)
    payload = json.loads(
        (tmp_path / MANIFEST_FILENAME).read_text(encoding="utf-8")
    )
    assert payload["built_at"] == "2026-04-28T00:00:00Z"
    assert load_manifest(tmp_path).built_at == "2026-04-28T00:00:00Z"


def test_manifest_without_built_at_loads(tmp_path: Path) -> None:
    """SH-M1: ``built_at`` is optional on load (new manifests omit it)."""
    raw = {
        "schema": MANIFEST_SCHEMA,
        "project": "demo",
        "build_dir": "out",
        "transpiler_version": "0.12.0",
        "modules": [],
        "topological_import_order": [],
    }
    (tmp_path / MANIFEST_FILENAME).write_text(
        json.dumps(raw), encoding="utf-8"
    )
    loaded = load_manifest(tmp_path)
    assert loaded.built_at == ""
    assert "built_at" not in loaded.to_dict()


# ---------------------------------------------------------------------------
# STD-M5 (usability plan) — logical structure (source_root + logical_path)
# ---------------------------------------------------------------------------


_MULTI_SOURCE_ROOT_FIXTURE = (
    Path(__file__).parent / "fixtures" / "multi_source_root_project"
)


def test_multi_root_build_records_logical_structure(tmp_path: Path) -> None:
    """STD-M5: ``source_root`` is the *configured entry the module came from*.

    The ``multi_source_root_project`` fixture declares THREE distinct
    source roots (``domain`` / ``application`` / ``presentation``) plus a
    ``tests`` root. Each module's manifest entry must record the specific
    root it was discovered under — not a fixed ``"src"`` — and a
    ``logical_path`` relative to *that* root, both project-root-relative
    POSIX (Decision 3 / Option B). The build directory stays flat.
    """
    project = tmp_path / "multi_root_proj"
    shutil.copytree(_MULTI_SOURCE_ROOT_FIXTURE, project)

    cli = S0maCLI()
    rc = cli.run([
        "--project-root", str(project),
        "build", str(project),
        "--mode", "dev",
        "--no-cache",
    ])
    assert rc == EXIT_SUCCESS

    build_dir = project / "multi_source_root_project_build"
    payload = json.loads(
        (build_dir / MANIFEST_FILENAME).read_text(encoding="utf-8")
    )
    by_name = {m["name"]: m for m in payload["modules"]}

    # Each module records the configured root it actually came from.
    expected = {
        "order_model": ("domain", "order_model.s0ma"),
        "order_service": ("application", "order_service.s0ma"),
        "order_summary": ("application", "order_summary.s0ma"),
        "order_view": ("presentation", "order_view.s0ma"),
        "test_cross_root": ("tests", "test_cross_root.s0ma"),
    }
    for name, (source_root, logical_path) in expected.items():
        assert name in by_name, f"{name} missing from manifest"
        assert by_name[name]["source_root"] == source_root, (
            f"{name}: {by_name[name]['source_root']!r} != {source_root!r}"
        )
        assert by_name[name]["logical_path"] == logical_path, (
            f"{name}: {by_name[name]['logical_path']!r} != {logical_path!r}"
        )

    # Portability: forward-slash POSIX only, never absolute, never the root.
    needle = str(project)
    for name, entry in by_name.items():
        for field in ("source_root", "logical_path"):
            value = entry[field]
            assert "\\" not in value, f"{name}.{field} backslash: {value!r}"
            assert not value.startswith("/"), f"{name}.{field} abs: {value!r}"
            assert needle not in value, f"{name}.{field} root: {value!r}"

    # Decision 3 / Option B: the build dir is FLAT — no per-root subdirs.
    for sub in ("domain", "application", "presentation", "tests"):
        assert not (build_dir / sub).exists(), (
            f"build dir nested a {sub!r} subdir — Option B keeps it flat"
        )


def test_logical_structure_round_trips() -> None:
    """STD-M5: ``source_root`` / ``logical_path`` round-trip through to_dict."""
    entry = ModuleManifestEntry(
        name="orders_domain",
        source="src/orders/orders_domain.s0ma",
        output="orders_domain.py",
        ir="orders_domain.s0ma.json",
        source_map="orders_domain.s0ma.map",
        source_hash="sha256:" + "0" * 64,
        output_hash="sha256:" + "1" * 64,
        source_root="src",
        logical_path="orders/orders_domain.s0ma",
    )
    d = entry.to_dict()
    assert d["source_root"] == "src"
    assert d["logical_path"] == "orders/orders_domain.s0ma"


def test_empty_logical_structure_omitted_from_dict() -> None:
    """STD-M5: empty logical structure is omitted (byte-identical to pre-M5).

    A module with no recordable root (synthetic build / outside every
    root) keeps the empty-string defaults, and ``to_dict`` drops the
    keys so the manifest bytes match a pre-STD-M5 build exactly.
    """
    entry = ModuleManifestEntry(
        name="loose",
        source="loose.s0ma",
        output="loose.py",
        ir="loose.s0ma.json",
        source_map="loose.s0ma.map",
        source_hash="sha256:" + "0" * 64,
        output_hash="sha256:" + "1" * 64,
    )
    assert entry.source_root == ""
    assert entry.logical_path == ""
    d = entry.to_dict()
    assert "source_root" not in d
    assert "logical_path" not in d


def test_manifest_without_logical_structure_loads(tmp_path: Path) -> None:
    """STD-M5: pre-M5 manifests (no logical fields) load with empty defaults."""
    raw = {
        "schema": MANIFEST_SCHEMA,
        "project": "demo",
        "build_dir": "out",
        "transpiler_version": "0.12.0",
        "modules": [
            {
                "name": "legacy",
                "source": "src/legacy.s0ma",
                "output": "legacy.py",
                "ir": "legacy.s0ma.json",
                "source_map": "legacy.s0ma.map",
                "source_hash": "sha256:" + "0" * 64,
                "output_hash": "sha256:" + "1" * 64,
            }
        ],
        "topological_import_order": [],
    }
    (tmp_path / MANIFEST_FILENAME).write_text(
        json.dumps(raw), encoding="utf-8"
    )
    loaded = load_manifest(tmp_path)
    (entry,) = loaded.modules
    assert entry.source_root == ""
    assert entry.logical_path == ""
    # And the round-tripped dict omits the empty keys.
    assert "source_root" not in entry.to_dict()
    assert "logical_path" not in entry.to_dict()


def test_synthetic_transpile_omits_logical_structure(tmp_path: Path) -> None:
    """STD-M5: a no-project transpile records no logical structure.

    The portable form needs a configured source root to be relative to;
    a synthetic-fallback ``transpile`` (no ``[tool.s0ma]`` table) has no
    anchor, so the manifest omits both fields — mirroring the SH-M1
    policy split for ``source`` / ``build_dir``.
    """
    workdir = tmp_path / "loose"
    out_dir = tmp_path / "out"
    workdir.mkdir(parents=True)
    (workdir / "portable.s0ma").write_text(
        SH_M1_MODULE, encoding="utf-8", newline="\n"
    )
    cli = S0maCLI()
    rc = cli.run([
        "transpile", str(workdir / "portable.s0ma"),
        "--output-dir", str(out_dir),
        "--mode", "dev",
    ])
    assert rc == EXIT_SUCCESS
    payload = json.loads(
        (out_dir / MANIFEST_FILENAME).read_text(encoding="utf-8")
    )
    (entry,) = payload["modules"]
    assert "source_root" not in entry
    assert "logical_path" not in entry


def test_inspect_surfaces_logical_structure(tmp_path: Path, capsys) -> None:
    """STD-M5: ``s0ma inspect`` shows logical structure (text + JSON)."""
    project = tmp_path / "multi_root_proj"
    shutil.copytree(_MULTI_SOURCE_ROOT_FIXTURE, project)
    cli = S0maCLI()
    assert cli.run([
        "--project-root", str(project),
        "build", str(project),
        "--mode", "dev",
        "--no-cache",
    ]) == EXIT_SUCCESS

    # Text output carries a "Logical path" + "Source root" line.
    assert cli.run([
        "--project-root", str(project),
        "inspect", "order_service",
    ]) == EXIT_SUCCESS
    text = capsys.readouterr().out
    assert "Logical path: order_service.s0ma" in text
    assert "Source root: application" in text

    # JSON output carries the structured ``logical_structure`` block.
    assert cli.run([
        "--project-root", str(project),
        "inspect", "order_view", "--format", "json",
    ]) == EXIT_SUCCESS
    payload = json.loads(capsys.readouterr().out)
    assert payload["logical_structure"] == {
        "source_root": "presentation",
        "logical_path": "order_view.s0ma",
    }
