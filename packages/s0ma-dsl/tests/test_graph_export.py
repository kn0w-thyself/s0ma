"""M1 (studi0 v1) — the single graph-export mechanism.

``s0ma_dsl.graph_export.collect_graph`` is the one aggregation path for
component-graph data: ``s0ma graph`` renders it, and the studi0 viewer
consumes the same document (studi0 plan §3.1/§3.2, scope note §1 "no
duplicate mechanisms").

These tests lock three things:

1. **Back-compat.** ``nodes`` / ``edges.authored`` / ``edges.derived``
   carry exactly what the pre-extraction ``_cmd_graph`` produced. The
   historical recipe is re-implemented verbatim in
   :func:`_legacy_graph_payload` below so the assertion is against the
   old algorithm, not against the new code's own output.
2. **The ``s0ma-graph@2`` additions** — ``schema``,
   ``edges.verification`` and ``integrations`` at both detail levels;
   ``components``, ``modules`` and ``freshness`` at ``detail="full"``.
3. **Determinism and INV-5** — two runs produce identical JSON, and no
   emitted path is absolute.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any

import pytest

from s0ma_dsl.cli.main import EXIT_SUCCESS, S0maCLI
from s0ma_dsl.graph_export import (
    GRAPH_SCHEMA,
    NoIRArtifactsError,
    collect_graph,
    discover_ir_files,
)

# ---------------------------------------------------------------------------
# Fixture paths and staging helpers
# ---------------------------------------------------------------------------

GOLDEN_PROJECT_DIR = (
    Path(__file__).parent / "fixtures" / "valid" / "golden_project"
)

#: A [tool.s0ma] table for the staged copy of the golden project. The
#: fixture ships bare ``.s0ma`` files (it is used by the single-file
#: pipeline tests); staging it as a real project exercises the
#: project-root branch of ``collect_graph`` and gives the manifest a
#: portable root to record sources against.
STAGED_PYPROJECT = """[project]
name = "golden_project"
version = "0.0.1"

[tool.s0ma]
source_roots = ["src"]
test_roots = ["tests"]
build_dir = "golden_project_build"
bootstrap_files = []
"""


def _build_flat(source: Path, out_dir: Path) -> Path:
    """Build *source* into *out_dir* with no project resolution.

    This is the historical ``s0ma graph <build_dir>`` shape: a flat
    directory of IR artifacts plus a manifest.
    """
    rc = S0maCLI().run([
        "build", str(source),
        "--output-dir", str(out_dir),
        "--mode", "dev",
        "--no-cache",
    ])
    assert rc == EXIT_SUCCESS, "fixture build failed"
    return out_dir


def _stage_project(root: Path) -> Path:
    """Stage the golden fixture as a real ``[tool.s0ma]`` project and build it."""
    shutil.copytree(GOLDEN_PROJECT_DIR, root / "src")
    (root / "pyproject.toml").write_text(
        STAGED_PYPROJECT, encoding="utf-8", newline="\n"
    )
    rc = S0maCLI().run([
        "--project-root", str(root),
        "build", str(root),
        "--mode", "dev",
        "--no-cache",
    ])
    assert rc == EXIT_SUCCESS, "staged project build failed"
    return root


@pytest.fixture(scope="module")
def golden_build(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """A built, read-only golden project as a flat build directory."""
    out_dir = tmp_path_factory.mktemp("golden_flat") / "build"
    return _build_flat(GOLDEN_PROJECT_DIR, out_dir)


@pytest.fixture(scope="module")
def golden_project_root(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """A built, read-only golden project resolved through ``[tool.s0ma]``."""
    return _stage_project(tmp_path_factory.mktemp("golden_project_root"))


@pytest.fixture()
def mutable_project_root(tmp_path: Path) -> Path:
    """A staged project a test may edit (freshness flip)."""
    return _stage_project(tmp_path / "project")


# ---------------------------------------------------------------------------
# The frozen @1 recipe
# ---------------------------------------------------------------------------


def _legacy_graph_payload(target: Path) -> dict[str, Any]:
    """Reproduce the pre-M1 ``_cmd_graph`` JSON aggregation verbatim.

    Copied from ``cli/main.py`` as it stood before the extraction: nodes
    are the set of ``canonical_id`` values across every discovered IR
    file; authored and derived edges are concatenated in file-discovery
    order with no sorting or de-duplication. Nothing here may be
    "improved" — it is the contract the ``@2`` payload must keep.
    """
    all_nodes: set[str] = set()
    all_authored: list[dict[str, Any]] = []
    all_derived: list[dict[str, Any]] = []

    for ir_path in discover_ir_files(target):
        data = json.loads(ir_path.read_text(encoding="utf-8"))
        for comp in data.get("components", []):
            all_nodes.add(comp.get("canonical_id", ""))
        edges = data.get("edges", {})
        all_authored.extend(edges.get("authored", []))
        all_derived.extend(edges.get("derived", []))

    return {
        "nodes": sorted(all_nodes),
        "edges": {"authored": all_authored, "derived": all_derived},
    }


# ---------------------------------------------------------------------------
# Back-compat
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("detail", ["summary", "full"])
def test_v1_shape_preserved(golden_build: Path, detail: str) -> None:
    """The @1 keys keep their exact historical content at both detail levels."""
    legacy = _legacy_graph_payload(golden_build)
    payload = collect_graph(golden_build, detail=detail)

    assert payload["nodes"] == legacy["nodes"]
    assert payload["edges"]["authored"] == legacy["edges"]["authored"]
    assert payload["edges"]["derived"] == legacy["edges"]["derived"]

    # The fixture is only a back-compat lock if it actually carries data.
    assert legacy["nodes"], "golden fixture produced no nodes"
    assert legacy["edges"]["authored"], "golden fixture produced no authored edges"
    assert legacy["edges"]["derived"], "golden fixture produced no derived edges"


def test_summary_top_level_keys_are_closed(golden_build: Path) -> None:
    """``summary`` is the @1 shape plus exactly the three @2 additions."""
    payload = collect_graph(golden_build)
    assert set(payload) == {"schema", "nodes", "edges", "integrations"}
    assert set(payload["edges"]) == {"authored", "derived", "verification"}
    assert payload["schema"] == GRAPH_SCHEMA == "s0ma-graph@2"


def test_cli_json_matches_collect_graph(
    golden_build: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """``s0ma graph --format json`` is a thin renderer over collect_graph."""
    rc = S0maCLI().run(["graph", str(golden_build), "--format", "json"])
    assert rc == EXIT_SUCCESS
    emitted = json.loads(capsys.readouterr().out)
    assert emitted == collect_graph(golden_build)


def test_cli_text_and_dot_ignore_detail(
    golden_build: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """``--detail`` is documented as json-only; text and dot are unaffected."""
    for output_format in ("text", "dot"):
        assert (
            S0maCLI().run(
                ["graph", str(golden_build), "--format", output_format]
            )
            == EXIT_SUCCESS
        )
        without = capsys.readouterr().out
        assert (
            S0maCLI().run([
                "graph", str(golden_build),
                "--format", output_format,
                "--detail", "full",
            ])
            == EXIT_SUCCESS
        )
        assert capsys.readouterr().out == without


# ---------------------------------------------------------------------------
# @2 content
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("detail", ["summary", "full"])
def test_verification_edges_and_integrations_at_both_levels(
    golden_build: Path, detail: str
) -> None:
    """Verification edges and the IR integrations section ride at both levels."""
    payload = collect_graph(golden_build, detail=detail)

    verification = payload["edges"]["verification"]
    assert verification, "golden fixture declares tests: edges"
    for edge in verification:
        assert set(edge) == {"test", "validates", "origin"}
        assert edge["origin"] == "tests_field"
    # Every verification edge points at a real node on both ends.
    nodes = set(payload["nodes"])
    for edge in verification:
        assert edge["test"] in nodes
        assert edge["validates"] in nodes

    # The golden fixture predates `integration` declarations, so the
    # section is present and empty — the key exists unconditionally.
    assert payload["integrations"] == []


def test_full_detail_components_are_verbatim_ir(golden_build: Path) -> None:
    """Every IRComponent field survives the export untouched."""
    payload = collect_graph(golden_build, detail="full")
    components = payload["components"]

    assert set(components) == set(payload["nodes"])

    ir_by_id: dict[str, dict[str, Any]] = {}
    module_of: dict[str, dict[str, Any]] = {}
    for ir_path in discover_ir_files(golden_build):
        data = json.loads(ir_path.read_text(encoding="utf-8"))
        for comp in data["components"]:
            ir_by_id[comp["canonical_id"]] = comp
            module_of[comp["canonical_id"]] = data["module"]

    for canonical_id, exported in components.items():
        source = ir_by_id[canonical_id]
        # All seven IRComponent fields, verbatim (``location`` gains the
        # owning module's file; its IR keys are still there untouched).
        for field in (
            "canonical_id",
            "declaration_type",
            "kind",
            "visibility",
            "intent",
            "fields",
        ):
            assert exported[field] == source[field], field
        assert exported["location"]["start_line"] == source["location"]["start_line"]
        assert exported["location"]["end_line"] == source["location"]["end_line"]
        assert exported["location"]["line"] == source["location"]["start_line"]
        # Plus the two owning-module facts the IR records once per module.
        assert exported["module"] == module_of[canonical_id]["name"]
        assert exported["layer"] == module_of[canonical_id]["layer"]


def test_full_detail_modules(golden_build: Path) -> None:
    """``modules`` records name, layer, intent and sorted component ids."""
    payload = collect_graph(golden_build, detail="full")
    modules = payload["modules"]

    names = [module["name"] for module in modules]
    assert names == sorted(names)
    assert set(names) == {
        "data_models",
        "task_adapter",
        "task_monitor",
        "task_orchestrator",
        "task_service",
        "task_tests",
    }

    covered: list[str] = []
    for module in modules:
        assert set(module) == {"name", "layer", "intent", "components"}
        assert module["components"] == sorted(module["components"])
        assert module["intent"] is not None
        covered.extend(module["components"])
    # Modules partition the node set.
    assert sorted(covered) == payload["nodes"]


def test_locations_are_project_relative(golden_project_root: Path) -> None:
    """INV-5: no absolute machine path reaches the payload."""
    payload = collect_graph(golden_project_root, detail="full")

    files = {
        component["location"]["file"]
        for component in payload["components"].values()
    }
    assert files, "expected component locations"
    for file in files:
        assert not Path(file).is_absolute(), file
        assert file.startswith("src/"), file
        assert "\\" not in file, "paths are POSIX on every OS"

    # Belt and braces: the staging root must not appear anywhere in the
    # serialized document.
    serialized = json.dumps(payload, sort_keys=True)
    assert str(golden_project_root) not in serialized


@pytest.mark.parametrize(
    ("recorded", "expected"),
    [
        # Project builds record portable POSIX already (SH-M1).
        ("src/order.s0ma", "src/order.s0ma"),
        # Absolute recordings degrade to the basename rather than leak a
        # machine path — under either OS's spelling, since a manifest
        # written on one platform may be read on the other (NFR-7).
        ("/srv/build/src/order.s0ma", "order.s0ma"),
        ("C:\\work\\src\\order.s0ma", "order.s0ma"),
        ("", ""),
    ],
)
def test_recorded_paths_are_never_absolute(recorded: str, expected: str) -> None:
    """INV-5 holds for every manifest spelling, on every platform."""
    from s0ma_dsl.graph_export import _project_relative

    assert _project_relative(recorded, None) == expected


def test_paths_under_the_project_root_become_root_relative() -> None:
    """An absolute recording inside the project is re-anchored, not truncated."""
    from s0ma_dsl.graph_export import _project_relative

    root = Path("/srv/proj") if Path("/").is_absolute() else Path("C:/proj")
    assert (
        _project_relative(str(root / "src" / "order.s0ma"), root)
        == "src/order.s0ma"
    )


# ---------------------------------------------------------------------------
# Project-root resolution
# ---------------------------------------------------------------------------


def test_project_root_target_scans_build_dir(golden_project_root: Path) -> None:
    """A [tool.s0ma] project root resolves to its configured build_dir."""
    from_root = collect_graph(golden_project_root, detail="full")
    from_build_dir = collect_graph(
        golden_project_root / "golden_project_build", detail="full"
    )
    assert from_root["nodes"] == from_build_dir["nodes"]
    assert from_root["nodes"], "expected a non-empty graph"


def test_cli_accepts_a_project_root(
    golden_project_root: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """``s0ma graph <project_root> --format json`` works end to end."""
    rc = S0maCLI().run([
        "graph", str(golden_project_root), "--format", "json",
    ])
    assert rc == EXIT_SUCCESS
    payload = json.loads(capsys.readouterr().out)
    assert payload["schema"] == GRAPH_SCHEMA
    assert payload["nodes"]


# ---------------------------------------------------------------------------
# Freshness
# ---------------------------------------------------------------------------


def test_freshness_flips_when_a_source_changes(
    mutable_project_root: Path,
) -> None:
    """A touched source moves the build from fresh to stale, naming the module."""
    before = collect_graph(mutable_project_root, detail="full")["freshness"]
    assert before == {
        "basis": "build.s0ma.json",
        "manifest_found": True,
        "status": "fresh",
        "stale_modules": [],
        "transpiler_version": before["transpiler_version"],
    }
    assert before["transpiler_version"], "manifest records a transpiler version"

    source = mutable_project_root / "src" / "task_monitor.s0ma"
    source.write_text(
        source.read_text(encoding="utf-8") + "\n",
        encoding="utf-8",
        newline="\n",
    )

    after = collect_graph(mutable_project_root, detail="full")["freshness"]
    assert after["status"] == "stale"
    assert after["stale_modules"] == ["task_monitor"]


def test_freshness_absent_without_a_manifest(
    golden_build: Path, tmp_path: Path
) -> None:
    """No manifest, no freshness key — the payload never guesses."""
    bare = tmp_path / "bare"
    bare.mkdir()
    for ir_path in discover_ir_files(golden_build):
        shutil.copyfile(ir_path, bare / ir_path.name)

    payload = collect_graph(bare, detail="full")
    assert "freshness" not in payload
    assert payload["nodes"], "the graph itself still renders"


def test_freshness_is_full_detail_only(golden_project_root: Path) -> None:
    """Summary stays cheap: no manifest read, no freshness key."""
    assert "freshness" not in collect_graph(golden_project_root)


# ---------------------------------------------------------------------------
# Determinism (INV-5)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("detail", ["summary", "full"])
def test_collect_graph_is_deterministic(
    golden_project_root: Path, detail: str
) -> None:
    """Two runs over identical inputs serialize identically."""
    first = json.dumps(
        collect_graph(golden_project_root, detail=detail), sort_keys=True
    )
    second = json.dumps(
        collect_graph(golden_project_root, detail=detail), sort_keys=True
    )
    assert first == second


# ---------------------------------------------------------------------------
# Failure modes
# ---------------------------------------------------------------------------


def test_missing_target_raises_no_ir_artifacts(tmp_path: Path) -> None:
    """An empty target is a usage error, not an empty graph."""
    with pytest.raises(NoIRArtifactsError):
        collect_graph(tmp_path / "nope")


def test_unknown_detail_level_is_rejected(golden_build: Path) -> None:
    """Detail levels are a closed set."""
    with pytest.raises(ValueError, match="detail level"):
        collect_graph(golden_build, detail="everything")


def test_reserved_ledgers_are_excluded_from_discovery(
    golden_build: Path,
) -> None:
    """The adoption ledger and build manifest never enter IR discovery.

    Regression (narration-spike finding, 2026-08-16): ``adopted.s0ma.json``
    carries ``schema`` but not the canonical ``schema_version``, so on any
    project with adopted files the discovery glob fed it to
    ``validate_ir_schema_version`` and every consumer of discovery —
    ``s0ma verify``'s staleness pass first among them — hard-failed with
    UNSUPPORTED_IR_SCHEMA_MAJOR. Pilot-03's adoption ladder was green at
    0.13.0; the guard's application to discovered files broke it in the
    0.14/0.15 waves.
    """
    ledger = golden_build / "adopted.s0ma.json"
    ledger.write_text(
        json.dumps({"schema": "s0ma-adopted@1", "files": []}, sort_keys=True),
        encoding="utf-8",
    )
    try:
        discovered = {p.name for p in discover_ir_files(golden_build)}
        assert "adopted.s0ma.json" not in discovered
        assert "build.s0ma.json" not in discovered
        # And the aggregation consumes the same discovery without tripping
        # the IR schema guard on the ledger.
        payload = collect_graph(golden_build, detail="summary")
        assert payload["schema"] == GRAPH_SCHEMA
    finally:
        ledger.unlink()
