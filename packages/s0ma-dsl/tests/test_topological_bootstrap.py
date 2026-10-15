"""M10 (feedback 5–6) — topological bootstrap invariants.

Locks down the M10 contract:

- ``s0ma build`` records ``topological_import_order`` in the manifest,
  computed from every module's ``uses:`` edges. Stable across runs
  (Kahn's algorithm with alphabetical tie-breaking).
- :func:`s0ma.bootstrap.bootstrap_imports` reads the manifest and
  imports modules in that order — every consumer of a module is
  imported strictly after its dependencies.
- ``s0ma topo`` prints the topological order one module per line.
- Cyclic ``uses:`` graphs surface ``MODULE_DEPENDENCY_CYCLE`` at build
  time, not as a runtime ``ImportError``.

Pairs with ``tests/test_build_manifest.py`` (the M6b manifest invariants)
and ``tests/test_build_layout.py`` (the M6a flat layout).
"""

from __future__ import annotations

import json
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

from s0ma_dsl.cli.main import EXIT_SUCCESS, EXIT_VALIDATION_ERROR, S0maCLI
from s0ma_dsl.codegen.build_manifest import MANIFEST_FILENAME, load_manifest
from s0ma_dsl.resolver.topological import (
    ModuleDependencyCycleError,
    compute_topological_order,
)

FIXTURE = Path(__file__).parent / "fixtures" / "multi_module_project"
EXPECTED_ORDER = ("models", "processing", "routing")


# ---------------------------------------------------------------------------
# Build-time fixture
# ---------------------------------------------------------------------------


@pytest.fixture()
def built_project(tmp_path: Path) -> Path:
    """Build the multi_module_project fixture into a fresh tmp output dir.

    Each test gets its own freshly-built directory so the
    ``sys.path`` mutations from one test cannot leak into another.
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
# 1. Build emits topological order
# ---------------------------------------------------------------------------


def test_build_emits_topological_order(built_project: Path) -> None:
    """The manifest carries the dependency-first import order.

    For ``multi_module_project``: ``processing`` uses ``models`` and
    ``routing`` uses ``processing`` (and ``models`` directly), so the
    only valid import order is ``models → processing → routing``.
    Kahn's algorithm with alphabetical tie-breaking produces exactly
    this order, and the recorded value must match the manifest's
    ``modules`` list as a set (no module is silently dropped).
    """
    manifest_path = built_project / MANIFEST_FILENAME
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))

    assert "topological_import_order" in payload, (
        "manifest must carry topological_import_order under M10"
    )
    order = payload["topological_import_order"]
    assert isinstance(order, list)
    assert tuple(order) == EXPECTED_ORDER

    # The set of modules in the topological order must equal the set
    # of modules in the manifest's ``modules`` list — neither side may
    # silently drop a module.
    module_names = {m["name"] for m in payload["modules"]}
    assert set(order) == module_names

    # Schema string is unchanged — M10 is purely additive.
    assert payload["schema"] == "s0ma-build-manifest@1"

    # Round-trips through ``load_manifest``.
    manifest = load_manifest(built_project)
    assert manifest.topological_import_order == EXPECTED_ORDER


def test_topological_order_is_deterministic(tmp_path: Path) -> None:
    """Two builds of the same fixture record the same order.

    Kahn's algorithm with alphabetical tie-breaking is deterministic;
    a re-build of the same source must produce the same
    ``topological_import_order`` list.
    """
    cli = S0maCLI()
    out1 = tmp_path / "build1"
    out2 = tmp_path / "build2"
    assert cli.run([
        "build", str(FIXTURE), "--output-dir", str(out1), "--no-cache",
    ]) == EXIT_SUCCESS
    assert cli.run([
        "build", str(FIXTURE), "--output-dir", str(out2), "--no-cache",
    ]) == EXIT_SUCCESS

    p1 = json.loads((out1 / MANIFEST_FILENAME).read_text())
    p2 = json.loads((out2 / MANIFEST_FILENAME).read_text())
    assert p1["topological_import_order"] == p2["topological_import_order"]


# ---------------------------------------------------------------------------
# 2. bootstrap_imports loads in order
# ---------------------------------------------------------------------------


def test_bootstrap_imports_loads_in_order(built_project: Path) -> None:
    """``bootstrap_imports`` imports modules in the manifest's order.

    Run in a subprocess so the s0ma component registry the transpiled
    modules write to is fresh — re-importing the modules in-process
    would hit ``RegistrationError`` (the registry is module-global
    and intentionally rejects double-registration).

    The test uses a sentinel side-effect: it records the order in
    which the helper places entries into the returned dict and
    asserts it matches ``EXPECTED_ORDER``.
    """
    code = textwrap.dedent(f"""
        from pathlib import Path
        from s0ma.bootstrap import bootstrap_imports

        modules = bootstrap_imports(Path({str(built_project)!r}))
        names = list(modules.keys())
        expected = {list(EXPECTED_ORDER)!r}
        assert names == expected, (names, expected)
        for name, mod in modules.items():
            assert mod.__name__ == name, (mod.__name__, name)
        print("OK:" + ",".join(names))
    """)
    proc = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, (
        f"bootstrap_imports failed:\n"
        f"stdout={proc.stdout!r}\nstderr={proc.stderr!r}"
    )
    assert "OK:" + ",".join(EXPECTED_ORDER) in proc.stdout


def test_bootstrap_imports_is_sys_path_idempotent(built_project: Path) -> None:
    """Re-invoking the helper does not duplicate sys.path entries.

    The helper is documented as idempotent — re-running it must leave
    ``sys.path`` unchanged after the first invocation. Run in a
    subprocess so the in-test registry mutations from the first call
    do not collide with the second call.
    """
    code = textwrap.dedent(f"""
        import sys
        from pathlib import Path
        from s0ma.bootstrap import bootstrap_imports

        build_str = {str(built_project)!r}
        bootstrap_imports(Path(build_str))
        first = sys.path.count(build_str)
        # Re-invoke. Modules are already in sys.modules, so importlib
        # short-circuits — but the sys.path insertion path runs again.
        bootstrap_imports(Path(build_str))
        second = sys.path.count(build_str)
        assert first == 1, first
        assert second == 1, second
        print("OK")
    """)
    proc = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, (
        f"idempotency check failed:\n"
        f"stdout={proc.stdout!r}\nstderr={proc.stderr!r}"
    )
    assert "OK" in proc.stdout


# ---------------------------------------------------------------------------
# 3. s0ma topo prints order
# ---------------------------------------------------------------------------


def test_s0ma_topo_prints_order(capsys: pytest.CaptureFixture[str]) -> None:
    """``s0ma topo <project>`` prints the order, one module per line."""
    cli = S0maCLI()
    rc = cli.run(["topo", str(FIXTURE)])
    assert rc == EXIT_SUCCESS

    out = capsys.readouterr().out
    lines = [line for line in out.strip().splitlines() if line.strip()]
    assert tuple(lines) == EXPECTED_ORDER


def test_s0ma_topo_json_format(capsys: pytest.CaptureFixture[str]) -> None:
    """``s0ma topo --format json`` emits JSON with the order field."""
    cli = S0maCLI()
    rc = cli.run(["topo", str(FIXTURE), "--format", "json"])
    assert rc == EXIT_SUCCESS

    payload = json.loads(capsys.readouterr().out)
    assert payload == {"topological_import_order": list(EXPECTED_ORDER)}


def test_s0ma_topo_subprocess(tmp_path: Path) -> None:
    """End-to-end: invoking ``s0ma`` as a subprocess produces the same order.

    Belt-and-braces guard — the in-process CLI test exercises the
    Python entry point; the subprocess test exercises the installed
    console-script wrapper that consumers actually invoke.
    """
    result = subprocess.run(
        ["s0ma", "topo", str(FIXTURE)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, (
        f"s0ma topo failed: stderr={result.stderr!r}"
    )
    lines = [
        line
        for line in result.stdout.strip().splitlines()
        if line.strip() and not line.startswith("warning")
    ]
    assert tuple(lines) == EXPECTED_ORDER


# ---------------------------------------------------------------------------
# 4. Cyclic dependencies error at build time
# ---------------------------------------------------------------------------


CYCLE_FIXTURE = (
    Path(__file__).parent / "fixtures" / "invalid" / "circular_deps"
)


def test_cyclic_dependency_errors_at_build(tmp_path: Path) -> None:
    """A project with cyclic ``uses:`` edges fails the build.

    The four-phase resolver fires ``CIRCULAR_DEPENDENCY`` first
    (DFS-based detection during Phase 1). ``MODULE_DEPENDENCY_CYCLE``
    is the topological-sort-path's defensive surface — both paths
    exit non-zero. The acceptance criterion is "cyclic dependencies
    are detected at build time, not runtime", which both error codes
    satisfy.
    """
    cli = S0maCLI()
    out_dir = tmp_path / "build"
    rc = cli.run([
        "build", str(CYCLE_FIXTURE),
        "--output-dir", str(out_dir),
        "--no-cache",
    ])
    # Build fails — cycle is rejected before any artifact is emitted.
    assert rc == EXIT_VALIDATION_ERROR
    # No manifest is written when the build aborts on a cycle.
    assert not (out_dir / MANIFEST_FILENAME).is_file()


def test_compute_topological_order_raises_on_cycle(tmp_path: Path) -> None:
    """:func:`compute_topological_order` raises with the cycle's modules.

    A direct unit test of the algorithm — independent of the build
    pipeline — that exercises the ``MODULE_DEPENDENCY_CYCLE`` surface.
    """
    from s0ma_dsl.parser.s0ma_parser import parse_s0ma

    modules = {}
    for path in sorted(CYCLE_FIXTURE.glob("*.s0ma")):
        text = path.read_text(encoding="utf-8")
        parsed = parse_s0ma(text, filename=str(path))
        modules[parsed.module.name] = parsed

    with pytest.raises(ModuleDependencyCycleError) as excinfo:
        compute_topological_order(modules)

    err = excinfo.value
    # Both modules participate in the cycle and must be named.
    assert set(err.cycle_modules) == {"alpha", "beta"}
    msg = str(err)
    assert "alpha" in msg and "beta" in msg
    assert "cycle" in msg.lower()


def test_s0ma_topo_surfaces_cycle(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """``s0ma topo`` on a cyclic project surfaces the cycle error.

    The four-phase resolver does not run in the ``topo`` path (it's
    the standalone topological-sort path), so this test exercises the
    ``MODULE_DEPENDENCY_CYCLE`` surface directly.
    """
    cli = S0maCLI()
    rc = cli.run(["topo", str(CYCLE_FIXTURE)])
    assert rc == EXIT_VALIDATION_ERROR

    output = capsys.readouterr()
    combined = (output.out + output.err).lower()
    assert "module_dependency_cycle" in combined or "cycle" in combined
    assert "alpha" in combined and "beta" in combined


# ---------------------------------------------------------------------------
# Algorithm-level invariants
# ---------------------------------------------------------------------------


def test_topological_sort_alphabetical_tiebreak() -> None:
    """When in-degrees tie, alphabetical order breaks the tie.

    Builds a tiny in-memory project where three modules ``a``, ``b``,
    ``c`` all have no edges. Kahn's tie-breaker must emit them in
    alphabetical order: ``a → b → c``.
    """
    from s0ma_dsl.ast_nodes.enums import Layer
    from s0ma_dsl.ast_nodes.nodes import ModuleDecl, S0maModule

    def _make(name: str) -> S0maModule:
        return S0maModule(
            module=ModuleDecl(
                name=name,
                layer=Layer.DOMAIN,
                version="1.0.0",
                intent=f"{name} test module",
                exports=(),
            ),
        )

    modules = {"c": _make("c"), "a": _make("a"), "b": _make("b")}
    order = compute_topological_order(modules)
    assert order == ("a", "b", "c")


def test_topological_sort_ignores_external_uses() -> None:
    """``uses:`` entries pointing outside the project are not edges.

    The topological order constrains *in-project* ordering only;
    references to context-only or external modules do not influence
    the result.
    """
    from s0ma_dsl.ast_nodes.enums import Layer
    from s0ma_dsl.ast_nodes.nodes import (
        ModuleDecl,
        S0maModule,
        UsesEntry,
    )

    a_uses_external = ModuleDecl(
        name="a",
        layer=Layer.DOMAIN,
        version="1.0.0",
        intent="a",
        exports=(),
        uses=(UsesEntry(qualified_name="external.thing", alias=None),),
    )
    b = ModuleDecl(
        name="b",
        layer=Layer.DOMAIN,
        version="1.0.0",
        intent="b",
        exports=(),
    )
    modules = {
        "a": S0maModule(module=a_uses_external),
        "b": S0maModule(module=b),
    }
    order = compute_topological_order(modules)
    assert set(order) == {"a", "b"}
    # Tie-broken alphabetically since neither has in-project edges.
    assert order == ("a", "b")
