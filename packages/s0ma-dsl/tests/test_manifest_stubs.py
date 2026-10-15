"""M-8 (POST-14, 0.15.x) — Build manifest companion Python stub.

Locks down the post-M-8 contract for ``<build_dir>/build.s0ma.pyi``:

- ``s0ma build`` writes the stub alongside ``build.s0ma.json`` on
  every successful build (gated on the same ``errors_so_far == 0``
  predicate as the manifest itself).
- The stub names every emitted module with ``ModuleType`` typing plus
  a ``BootstrapModules`` ``TypedDict`` enumerating the modules.
- The stub is byte-deterministic across two builds of the same
  project (matches the manifest's "no churn on repeat builds"
  guarantee, modulo the manifest's own ``built_at`` timestamp).
- A build that fails (errors > 0) emits neither manifest nor stub.
- The stub regenerates correctly when modules are added or removed
  between builds.
- :func:`s0ma.bootstrap.bootstrap_imports` continues to work
  unchanged whether the stub is present (M-8+) or absent (pre-M-8
  back-compat).
- The stub body parses as valid Python via :mod:`ast` — a cheap
  proxy for mypy/pyright digestibility without requiring a type-check
  subprocess.

Pairs with ``tests/test_build_manifest.py`` (manifest invariants)
and ``tests/test_build_layout.py`` (flat-layout invariants).
"""

from __future__ import annotations

import ast
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

from s0ma_dsl import __version__ as transpiler_version
from s0ma_dsl.cli.main import EXIT_SUCCESS, S0maCLI
from s0ma_dsl.codegen.build_manifest import (
    MANIFEST_FILENAME,
    MANIFEST_STUB_FILENAME,
    build_manifest,
)
from s0ma_dsl.codegen.manifest_stub_emitter import (
    STUB_FILENAME,
    emit_manifest_stub,
    render_manifest_stub,
)

FIXTURE = Path(__file__).parent / "fixtures" / "multi_module_project"
EXPECTED_MODULES = ("models", "processing", "routing")


# ---------------------------------------------------------------------------
# Build-time fixture
# ---------------------------------------------------------------------------


@pytest.fixture()
def built_project(tmp_path: Path) -> Path:
    """Build the multi_module_project fixture into a fresh tmp output dir.

    Same shape as the fixture in ``tests/test_build_manifest.py`` — the
    M-8 stub rides on the same build invocation, so the fixture is
    intentionally identical so the assertions can compare like-for-like.
    """
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
# Acceptance — stub emission
# ---------------------------------------------------------------------------


def test_stub_constant_matches_emitter() -> None:
    """``MANIFEST_STUB_FILENAME`` (the build-manifest constant) and the
    emitter module's ``STUB_FILENAME`` agree on the filename.

    Other tooling (``s0ma migrate-layout``, ``s0ma verify``, future
    commands) imports the constant from ``build_manifest`` to name the
    stub without pulling in the emitter; the constant must therefore
    track the emitter's actual output.
    """
    assert MANIFEST_STUB_FILENAME == STUB_FILENAME == "build.s0ma.pyi"


def test_build_emits_stub_alongside_manifest(built_project: Path) -> None:
    """A fresh build produces a ``build.s0ma.pyi`` at the build root.

    Acceptance criterion (M-8): every successful build that emits a
    manifest also emits the companion stub as a sibling file. The two
    files live next to each other so consumers can point a type
    checker at the build directory and pick up both at once.
    """
    stub_path = built_project / STUB_FILENAME
    manifest_path = built_project / MANIFEST_FILENAME
    assert manifest_path.is_file(), "fixture build did not produce a manifest"
    assert stub_path.is_file(), (
        f"missing stub at {stub_path}; "
        f"the build directory contained: "
        f"{sorted(p.name for p in built_project.iterdir())}"
    )


def test_stub_lists_every_module_with_module_type(
    built_project: Path,
) -> None:
    """The stub names every emitted module with ``ModuleType`` typing.

    Acceptance criterion: each module name from the manifest appears in
    the stub body as ``<name>: ModuleType`` (the bare module-level
    declaration) and also inside the ``BootstrapModules`` TypedDict.
    """
    stub = (built_project / STUB_FILENAME).read_text(encoding="utf-8")
    for name in EXPECTED_MODULES:
        assert f"{name}: ModuleType" in stub, (
            f"stub missing module-level `{name}: ModuleType` declaration; "
            f"body was:\n{stub}"
        )
    assert "class BootstrapModules(TypedDict):" in stub
    assert "from types import ModuleType" in stub
    assert "from typing import TypedDict" in stub


def test_stub_is_byte_deterministic_across_builds(tmp_path: Path) -> None:
    """Two clean builds of the same project produce identical stubs.

    The renderer is a pure function of the manifest plus the
    transpiler version — no clocks, no environment, no filesystem
    reads. Two clean builds against the same source set must therefore
    produce byte-identical stub files. This is the "no churn on
    repeat builds" guarantee the manifest itself can't make (its
    ``built_at`` field changes every second).
    """
    out_a = tmp_path / "build_a"
    out_b = tmp_path / "build_b"
    cli = S0maCLI()
    rc_a = cli.run([
        "build", str(FIXTURE),
        "--output-dir", str(out_a),
        "--mode", "dev",
        "--no-cache",
    ])
    rc_b = cli.run([
        "build", str(FIXTURE),
        "--output-dir", str(out_b),
        "--mode", "dev",
        "--no-cache",
    ])
    assert rc_a == EXIT_SUCCESS == rc_b
    stub_a = (out_a / STUB_FILENAME).read_bytes()
    stub_b = (out_b / STUB_FILENAME).read_bytes()
    assert stub_a == stub_b, (
        "stub bytes drifted across two builds of the same project; "
        "rendering is supposed to be a pure function of the manifest"
    )


def test_stub_header_lists_transpiler_version(built_project: Path) -> None:
    """The stub header carries the s0ma-dsl version that produced it.

    The header comment serves two roles:

    - "Auto-generated by `s0ma build`" — explicit do-not-edit marker
      so users (and shell-based grep workflows) recognise the file as
      a build artefact.
    - "Produced by s0ma-dsl <version>." — pins the transpiler version
      the stub encodes expectations for, so consumers reading the
      file know which release's bootstrap contract it matches.
    """
    stub = (built_project / STUB_FILENAME).read_text(encoding="utf-8")
    assert "Auto-generated by `s0ma build`" in stub
    assert f"Produced by s0ma-dsl {transpiler_version}." in stub


def test_stub_body_parses_as_valid_python(built_project: Path) -> None:
    """The stub body parses as a valid Python module.

    mypy / pyright both require a syntactically valid ``.pyi`` to read
    declarations from. Parsing via :func:`ast.parse` is a cheap proxy
    for "the type checker will at least open this file" without
    requiring mypy itself as a test dependency.
    """
    stub = (built_project / STUB_FILENAME).read_text(encoding="utf-8")
    # ``ast.parse`` raises ``SyntaxError`` if the body is malformed.
    module = ast.parse(stub)
    # ``BootstrapModules`` is declared as a class with the TypedDict
    # base. Verify the AST carries that exact class so downstream
    # consumers reading the stub for completion / hover info reliably
    # find the type name.
    class_names = [
        node.name for node in module.body
        if isinstance(node, ast.ClassDef)
    ]
    assert "BootstrapModules" in class_names, (
        f"expected BootstrapModules class in stub AST; saw classes "
        f"{class_names}"
    )


def test_build_with_errors_skips_stub(tmp_path: Path) -> None:
    """A build that fails to write a manifest skips the stub too.

    The pair is consistent by construction: the stub-emission call
    site is gated on the manifest having been written, which itself is
    gated on ``errors_so_far == 0``. A build with at least one error
    produces neither file, so consumers never see a half-built pair.
    """
    bad_dir = tmp_path / "bad_project"
    bad_dir.mkdir()
    # A .s0ma file with a parse-error so the build returns non-zero.
    (bad_dir / "broken.s0ma").write_text(
        "module broken\n    layer: NOT_A_REAL_LAYER\n",
        encoding="utf-8",
    )
    out_dir = tmp_path / "build"
    cli = S0maCLI()
    rc = cli.run([
        "build", str(bad_dir),
        "--output-dir", str(out_dir),
        "--mode", "dev",
        "--no-cache",
    ])
    # The exact exit code depends on the parser's diagnostic shape;
    # what we lock here is that on any failure, neither file lands.
    assert rc != EXIT_SUCCESS
    if out_dir.is_dir():
        assert not (out_dir / STUB_FILENAME).exists(), (
            "stub leaked from a failed build"
        )
        assert not (out_dir / MANIFEST_FILENAME).exists(), (
            "manifest leaked from a failed build"
        )


def test_stub_regenerates_after_module_added(tmp_path: Path) -> None:
    """Adding a module to a project updates the stub on the next build.

    The stub is overwritten on every successful build; there is no
    incremental-merge step. After adding a new ``.s0ma`` source to a
    project, the next build's stub must list the new module's
    ``ModuleType`` declaration.
    """
    proj = tmp_path / "growing_project"
    proj.mkdir()
    (proj / "alpha.s0ma").write_text(
        textwrap.dedent("""\
module alpha
    layer: DOMAIN
    version: 1.0.0
    intent: "Alpha."
    exports: [Alpha]

    requires: none
    uses: none
    soft_requires: none
    runtime_only_requires: none
    deferred_requires: none
    exports_helpers: none
cell Alpha :: DOMAIN
    kind: MODEL
    visibility: PUBLIC
    intent: "Alpha cell."
    schema: "Dataclass."
    invariants: none
    covered_by: none
    ---
    class Alpha:
        name: str
""").lstrip(),
        encoding="utf-8",
    )
    out_dir = tmp_path / "build"
    cli = S0maCLI()
    rc = cli.run([
        "build", str(proj),
        "--output-dir", str(out_dir),
        "--mode", "dev",
        "--no-cache",
    ])
    assert rc == EXIT_SUCCESS
    stub_v1 = (out_dir / STUB_FILENAME).read_text(encoding="utf-8")
    assert "alpha: ModuleType" in stub_v1
    assert "beta: ModuleType" not in stub_v1

    # Add a sibling module and rebuild.
    (proj / "beta.s0ma").write_text(
        textwrap.dedent("""\
module beta
    layer: DOMAIN
    version: 1.0.0
    intent: "Beta."
    exports: [Beta]

    requires: none
    uses: none
    soft_requires: none
    runtime_only_requires: none
    deferred_requires: none
    exports_helpers: none
cell Beta :: DOMAIN
    kind: MODEL
    visibility: PUBLIC
    intent: "Beta cell."
    schema: "Dataclass."
    invariants: none
    covered_by: none
    ---
    class Beta:
        name: str
""").lstrip(),
        encoding="utf-8",
    )
    rc2 = cli.run([
        "build", str(proj),
        "--output-dir", str(out_dir),
        "--mode", "dev",
        "--no-cache",
    ])
    assert rc2 == EXIT_SUCCESS
    stub_v2 = (out_dir / STUB_FILENAME).read_text(encoding="utf-8")
    assert "alpha: ModuleType" in stub_v2
    assert "beta: ModuleType" in stub_v2


def test_stub_regenerates_after_module_removed(tmp_path: Path) -> None:
    """Removing a ``.s0ma`` source drops it from the next clean build's stub.

    The build pipeline's PRE-3 manifest-merge logic preserves prior
    entries that the current build does not overwrite (so a source
    build followed by a test build retains both sets of modules in
    one manifest). A clean build (``--clean``) starts from a blank
    manifest, so removing a source from disk and rebuilding ``--clean``
    drops the module's entry — and therefore its stub declaration —
    cleanly.
    """
    proj = tmp_path / "shrinking_project"
    proj.mkdir()
    for name in ("alpha", "beta"):
        (proj / f"{name}.s0ma").write_text(
            textwrap.dedent(f"""
                module {name}
                    layer: DOMAIN
                    version: 1.0.0
                    intent: "{name.title()}."
                    exports: [{name.title()}]
                    requires: none
                    uses: none
                    soft_requires: none
                    runtime_only_requires: none
                    deferred_requires: none
                    exports_helpers: none

                cell {name.title()} :: DOMAIN
                    kind: MODEL
                    visibility: PUBLIC
                    intent: "{name.title()} cell."
                    schema: "Dataclass."
                    invariants: none
                    covered_by: none
                    ---
                    class {name.title()}:
                        name: str
            """).lstrip(),
            encoding="utf-8",
        )
    out_dir = tmp_path / "build"
    cli = S0maCLI()
    rc = cli.run([
        "build", str(proj),
        "--output-dir", str(out_dir),
        "--mode", "dev",
        "--no-cache",
    ])
    assert rc == EXIT_SUCCESS
    stub_v1 = (out_dir / STUB_FILENAME).read_text(encoding="utf-8")
    assert "alpha: ModuleType" in stub_v1
    assert "beta: ModuleType" in stub_v1

    # Remove the beta source and rebuild with --clean so the manifest
    # is rewritten from scratch (the regular merge path preserves
    # prior entries by design, used for source+test interleaving).
    (proj / "beta.s0ma").unlink()
    rc2 = cli.run([
        "build", str(proj),
        "--output-dir", str(out_dir),
        "--mode", "dev",
        "--no-cache",
        "--clean",
    ])
    assert rc2 == EXIT_SUCCESS
    stub_v2 = (out_dir / STUB_FILENAME).read_text(encoding="utf-8")
    assert "alpha: ModuleType" in stub_v2
    assert "beta: ModuleType" not in stub_v2, (
        "stub still names a removed module — the regeneration step "
        "did not re-derive from the freshly-rewritten manifest"
    )


def test_bootstrap_imports_works_when_stub_present(
    built_project: Path,
) -> None:
    """``bootstrap_imports`` is indifferent to the stub's presence.

    The stub is *advisory*: it lives next to the manifest so type
    checkers find it, but :func:`s0ma.bootstrap.bootstrap_imports`
    does not read it at runtime. This test confirms the runtime helper
    works exactly as before with the stub present (the fixture build
    produces the stub by construction).
    """
    assert (built_project / STUB_FILENAME).is_file()
    code = textwrap.dedent(f"""
        from pathlib import Path
        from s0ma.bootstrap import bootstrap_imports
        imported = bootstrap_imports(Path({str(built_project)!r}))
        names = set(imported.keys())
        expected = {set(EXPECTED_MODULES)!r}
        assert names == expected, (names, expected)
        print('OK')
    """)
    proc = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, (
        f"bootstrap_imports failed with stub present:\n"
        f"stdout={proc.stdout!r}\nstderr={proc.stderr!r}"
    )
    assert "OK" in proc.stdout


def test_bootstrap_imports_works_when_stub_absent(
    built_project: Path,
) -> None:
    """Removing the stub does not affect ``bootstrap_imports``.

    Pre-M-8 build directories (or any environment where the stub has
    been deleted out of band) must continue to bootstrap exactly the
    same way. The stub does not contribute to runtime behaviour;
    deleting it changes the dict by exactly zero entries.
    """
    (built_project / STUB_FILENAME).unlink()
    assert not (built_project / STUB_FILENAME).exists()
    code = textwrap.dedent(f"""
        from pathlib import Path
        from s0ma.bootstrap import bootstrap_imports
        imported = bootstrap_imports(Path({str(built_project)!r}))
        names = set(imported.keys())
        expected = {set(EXPECTED_MODULES)!r}
        assert names == expected, (names, expected)
        print('OK')
    """)
    proc = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, (
        f"bootstrap_imports failed with stub absent:\n"
        f"stdout={proc.stdout!r}\nstderr={proc.stderr!r}"
    )
    assert "OK" in proc.stdout


def test_render_empty_project_stub(tmp_path: Path) -> None:
    """A manifest with zero modules emits a minimal but valid stub.

    Acceptance criterion: an empty project (no ``.s0ma`` sources)
    still produces a stub that parses as valid Python, names
    ``BootstrapModules`` (with an empty body, ``pass``), and carries
    the header comments. Consumers referencing ``BootstrapModules``
    from a wrapper resolve the name even in pre-source states.
    """
    manifest = build_manifest(
        project_name="empty",
        build_dir=tmp_path,
        modules=[],
        transpiler_version="9.9.9",
        built_at="2026-04-28T00:00:00Z",
    )
    body = render_manifest_stub(manifest, transpiler_version="9.9.9")
    # Parses.
    ast.parse(body)
    # Carries the header + class declaration.
    assert "Auto-generated by `s0ma build`" in body
    assert "Produced by s0ma-dsl 9.9.9." in body
    assert "class BootstrapModules(TypedDict):" in body
    # Body is the ``pass`` placeholder (no module declarations).
    assert "    pass" in body
    # No stray module-level ``: ModuleType`` lines.
    assert ": ModuleType" not in body.replace(
        "from types import ModuleType", ""
    ).replace(
        "class BootstrapModules(TypedDict):", ""
    )


def test_emit_manifest_stub_writes_expected_path(tmp_path: Path) -> None:
    """``emit_manifest_stub`` returns the path it wrote to.

    Mirrors :func:`s0ma_dsl.codegen.build_manifest.emit_manifest`'s
    contract: the function returns the absolute path the file lives
    at, so the build pipeline can append it to ``all_outputs`` for the
    user-visible summary line.
    """
    manifest = build_manifest(
        project_name="demo",
        build_dir=tmp_path,
        modules=[],
        transpiler_version="0.15.x",
        built_at="2026-04-28T00:00:00Z",
    )
    written = emit_manifest_stub(
        manifest, tmp_path, transpiler_version="0.15.x",
    )
    assert written == tmp_path / STUB_FILENAME
    assert written.is_file()
    # Re-emitting overwrites the file (idempotent).
    written2 = emit_manifest_stub(
        manifest, tmp_path, transpiler_version="0.15.x",
    )
    assert written2 == written
    assert written.read_text(encoding="utf-8") == written2.read_text(
        encoding="utf-8"
    )
