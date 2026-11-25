"""An app that grows build by build, kept as a studi0 fixture.

studi0 is a viewer of builds that land while it is open, so it has to be
checked on a project that really changes. This module keeps one: the app
``s0ma new project <name> --template pipeline`` scaffolds, in three builds.

* **Build 1:** the ``player`` file reads what is playing and the
  ``music`` file settles on a mood straight from the song.
* **Build 2:** ``music`` gains ``Features`` and ``measure_features``, and
  ``settle_mood`` now works from those scores.
* **Build 3:** the ``coach`` and ``page`` files arrive. This build is
  exactly the scaffold, file for file.

Layout, under ``tests/fixtures/``:

* ``pipeline_builds/.sources/build_N/`` holds each build's project file,
  ``src/``, ``tests/`` and ``bootstrap/``. The directory is hidden on
  purpose: this package's own ``[tool.s0ma]`` table names ``tests`` as a
  test root, and s0ma's discovery skips hidden directories, so these
  sources never join studi0's own build.
* ``pipeline_builds/build_N.graph.json`` is what
  ``s0ma_dsl.graph_export.collect_graph`` gives at full detail for that
  build, the same document ``/api/graph`` carries under ``graph``.
* ``pipeline_builds/unbuilt_answers.json`` is what studi0's own routing
  answers on ``/api/state``, on ``/api/graph``, and on any path it does
  not serve, for a project that has not been built.
* ``stepping_harness.html`` loads the real page assets in live mode and
  answers the page's own requests from these files, landing the builds
  one at a time. Open it from a static server rooted at
  ``packages/s0ma-studi0``; its header comment has the command.

Pinned here: every build passes ``s0ma build``, ``s0ma check --mode
release`` and its own tests; every build rebuilds to its committed graph;
build 3 is the scaffold; the unbuilt answers are the server's; and the
harness embeds exactly these files.

One value is normalized, and only one: ``freshness.transpiler_version``
names the s0ma-lang-dsl that built the graph, so it moves with every
release. The rebuilt graph must carry the running s0ma-lang-dsl's own
version there, and the comparison then sets that one key aside. No other
key is touched.

When a change to the language or to the template moves these files,
regenerate them, and the harness blocks that embed them, from
``packages/s0ma-studi0`` with::

    uv run python tests/test_pipeline_builds.py --write

Build 1 and build 2 are written by hand; ``--write`` never touches the
sources, only what is derived from them.
"""

from __future__ import annotations

import copy
import json
import re
import shutil
import sys
import tempfile
from pathlib import Path
from typing import Any

import pytest

PACKAGE_ROOT = Path(__file__).resolve().parents[1]
FIXTURE_DIR = PACKAGE_ROOT / "tests" / "fixtures"
BUILDS_DIR = FIXTURE_DIR / "pipeline_builds"
SOURCES_DIR = BUILDS_DIR / ".sources"
UNBUILT_ANSWERS = BUILDS_DIR / "unbuilt_answers.json"
STEPPING_HARNESS = FIXTURE_DIR / "stepping_harness.html"
TERMS_FIXTURE = FIXTURE_DIR / "sh0w_terms_fixture.json"

BUILDS = ("build_1", "build_2", "build_3")

#: The scaffold names its project after the directory it is made in, so
#: the fresh scaffold is made in a directory of this name.
PROJECT_NAME = "song"

#: A path studi0 does not serve, asked of the real routing to record the
#: answer the harness gives for anything the page asks that is not one
#: of the two API routes.
UNSERVED_PATH = "/api/not-served"

#: The one key the comparison sets aside, and why: see the module text.
VERSION_KEY = "transpiler_version"


def graph_path(build: str) -> Path:
    return BUILDS_DIR / f"{build}.graph.json"


def read(path: Path) -> str:
    """Read *path* as utf-8, never the platform's locale default."""
    return path.read_text(encoding="utf-8")


def dumps(document: object) -> str:
    """The one way these fixtures are written."""
    return json.dumps(document, indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def source_files(build: str) -> list[str]:
    """Every file a build keeps, as posix paths relative to the build."""
    root = SOURCES_DIR / build
    return sorted(
        path.relative_to(root).as_posix() for path in root.rglob("*") if path.is_file()
    )


def stage(build: str, root: Path) -> Path:
    """Copy a build's committed sources to *root*, unbuilt."""
    shutil.copytree(SOURCES_DIR / build, root)
    return root


def run_cli(*args: str) -> int:
    from s0ma_dsl.cli.main import S0maCLI

    return S0maCLI().run(list(args))


def build(root: Path) -> None:
    from s0ma_dsl.cli.main import EXIT_SUCCESS

    rc = run_cli("--project-root", str(root), "build", str(root), "--no-cache")
    assert rc == EXIT_SUCCESS, f"s0ma build failed for {root.name}"


def collect(root: Path) -> dict[str, Any]:
    from s0ma_dsl.graph_export import DETAIL_FULL, collect_graph

    return collect_graph(root, detail=DETAIL_FULL)


def without_version(graph: dict[str, Any]) -> dict[str, Any]:
    """*graph* with the toolchain's version set aside, and nothing else."""
    trimmed = copy.deepcopy(graph)
    trimmed["freshness"].pop(VERSION_KEY)
    return trimmed


def answers(root: Path) -> dict[str, Any]:
    """What studi0's routing answers for the project at *root*.

    The session is opened and given its first reading exactly as the
    watch gives it one, then asked through ``route_request``, the same
    function the HTTP handler calls.
    """
    from s0ma_studi0 import studi0_server, studi0_state

    session = studi0_state.create_session(root)
    studi0_state.refresh_session(session)
    recorded: dict[str, Any] = {}
    for path, key in (
        ("/api/state", "/api/state"),
        ("/api/graph", "/api/graph"),
        (UNSERVED_PATH, "any other path"),
    ):
        response = studi0_server.route_request(path, session)
        recorded[key] = {
            "status": response["status"],
            "content_type": response["content_type"],
            "body": json.loads(response["body"]),
        }
    return recorded


def _embedded(harness: str, element_id: str) -> object:
    """One JSON block the harness carries, by element id."""
    opener = '<script id="' + element_id + '" type="application/json">'
    start = harness.index(opener) + len(opener)
    end = harness.index("</" + "script>", start)
    return json.loads(harness[start:end])


def _splice(harness: str, element_id: str, document: object) -> str:
    opener = '<script id="' + element_id + '" type="application/json">'
    start = harness.index(opener) + len(opener)
    end = harness.index("</" + "script>", start)
    return harness[:start] + "\n" + dumps(document) + "    " + harness[end:]


def harness_blocks() -> dict[str, object]:
    """The data the harness must embed, by element id."""
    blocks: dict[str, object] = {
        "sh0w-unbuilt": json.loads(read(UNBUILT_ANSWERS)),
        "sh0w-terms": json.loads(read(TERMS_FIXTURE)),
    }
    for number, name in enumerate(BUILDS, start=1):
        blocks[f"sh0w-build-{number}"] = json.loads(read(graph_path(name)))
    return blocks


# ---------------------------------------------------------------------------
# Every build is a real, passing project
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def built(tmp_path_factory: pytest.TempPathFactory) -> dict[str, Path]:
    """Each build staged from its committed sources and built once."""
    base = tmp_path_factory.mktemp("pipeline_builds")
    roots: dict[str, Path] = {}
    for name in BUILDS:
        roots[name] = stage(name, base / name)
        build(roots[name])
    return roots


@pytest.mark.parametrize("name", BUILDS)
def test_every_build_passes_the_release_check(built: dict[str, Path], name: str) -> None:
    from s0ma_dsl.cli.main import EXIT_SUCCESS

    root = built[name]
    assert run_cli("--project-root", str(root), "check", "--mode", "release") == EXIT_SUCCESS


@pytest.mark.parametrize("name", BUILDS)
def test_every_build_passes_its_own_tests(built: dict[str, Path], name: str) -> None:
    from s0ma_dsl.cli.main import EXIT_SUCCESS

    root = built[name]
    assert run_cli("--project-root", str(root), "test", "--quiet") == EXIT_SUCCESS


@pytest.mark.parametrize("name", BUILDS)
def test_every_build_rebuilds_to_its_committed_graph(
    built: dict[str, Path], name: str
) -> None:
    import s0ma_dsl

    rebuilt = collect(built[name])
    committed = json.loads(read(graph_path(name)))
    assert rebuilt["freshness"][VERSION_KEY] == s0ma_dsl.__version__
    assert re.fullmatch(r"\d+\.\d+\.\d+", committed["freshness"][VERSION_KEY])
    assert without_version(rebuilt) == without_version(committed)


@pytest.mark.parametrize("name", BUILDS)
def test_the_server_serves_that_graph_as_fresh(built: dict[str, Path], name: str) -> None:
    """``/api/graph`` carries the committed graph, and ``/api/state`` says fresh.

    The harness answers a landed build's state with the unbuilt state
    answer and two values moved: the sequence number and the build
    status. Every other key must be what the server says for a build.
    """
    served = answers(built[name])
    unbuilt = json.loads(read(UNBUILT_ANSWERS))
    graph_answer = served["/api/graph"]
    assert graph_answer["status"] == 200
    assert without_version(graph_answer["body"]["graph"]) == without_version(
        json.loads(read(graph_path(name)))
    )
    state = served["/api/state"]
    assert state["status"] == 200
    expected = dict(unbuilt["/api/state"]["body"], build_status="fresh")
    assert state["body"] == expected


def test_the_builds_grow_as_described() -> None:
    """Which parts each build adds and changes, read from the graphs."""

    def parts(name: str) -> dict[str, Any]:
        components = json.loads(read(graph_path(name)))["components"]
        return {
            key: value
            for key, value in components.items()
            if value["declaration_type"] != "test"
        }

    first, second, third = (parts(name) for name in BUILDS)
    assert sorted(first) == [
        "music::Mood",
        "music::Track",
        "music::settle_mood",
        "player::read_now_playing",
    ]
    assert sorted(set(second) - set(first)) == ["music::Features", "music::measure_features"]
    assert first["music::settle_mood"] != second["music::settle_mood"]
    added = set(third) - set(second)
    assert {key.split("::")[0] for key in added} == {"coach", "page"}
    assert len(added) == 6
    assert len(third) == 12


def test_no_committed_graph_carries_an_absolute_path() -> None:
    absolute = re.compile(r"^(/|[A-Za-z]:[\\/]|\\\\)")

    def strings(value: object) -> list[str]:
        if isinstance(value, str):
            return [value]
        if isinstance(value, dict):
            return [s for key, item in value.items() for s in strings(key) + strings(item)]
        if isinstance(value, list):
            return [s for item in value for s in strings(item)]
        return []

    for name in BUILDS:
        found = [s for s in strings(json.loads(read(graph_path(name)))) if absolute.match(s)]
        assert not found, f"{name} carries absolute paths: {found[:3]}"


def test_build_3_is_the_pipeline_scaffold(tmp_path: Path) -> None:
    from s0ma_dsl.cli.main import EXIT_SUCCESS

    target = tmp_path / PROJECT_NAME
    rc = run_cli("new", "project", str(target), "--template", "pipeline", "--quiet")
    assert rc == EXIT_SUCCESS
    kept = source_files("build_3")
    assert "pyproject.toml" in kept
    for relative in kept:
        assert (target / relative).read_bytes() == (
            SOURCES_DIR / "build_3" / relative
        ).read_bytes(), f"{relative} differs from the scaffold"
    scaffolded = {
        path.relative_to(target).as_posix()
        for root in ("src", "tests", "bootstrap")
        for path in (target / root).rglob("*")
        if path.is_file()
    }
    assert scaffolded <= set(kept), "the scaffold writes a source the fixture does not keep"


def test_the_early_builds_share_what_did_not_change() -> None:
    """A file a later build did not touch is the same bytes in every build."""
    final = SOURCES_DIR / "build_3"
    for name in ("build_1", "build_2"):
        for relative in (
            "pyproject.toml",
            "src/player/player.s0ma",
            "tests/player/player_tests.s0ma",
        ):
            assert (SOURCES_DIR / name / relative).read_bytes() == (
                final / relative
            ).read_bytes(), f"{name}/{relative}"
    for relative in ("src/music/music.s0ma", "tests/music/music_tests.s0ma"):
        assert (SOURCES_DIR / "build_2" / relative).read_bytes() == (
            final / relative
        ).read_bytes(), f"build_2/{relative}"


def test_the_unbuilt_answers_are_the_servers(tmp_path: Path) -> None:
    root = stage("build_1", tmp_path / PROJECT_NAME)
    assert answers(root) == json.loads(read(UNBUILT_ANSWERS))


# ---------------------------------------------------------------------------
# The stepping harness
# ---------------------------------------------------------------------------


def test_stepping_harness_embeds_the_committed_fixtures() -> None:
    harness = read(STEPPING_HARNESS)
    for element_id, document in harness_blocks().items():
        assert _embedded(harness, element_id) == document, element_id


def test_stepping_harness_boots_the_real_page_in_live_mode() -> None:
    """The real assets, no fixture global, and ``fetch`` replaced first."""
    import s0ma_studi0

    graph_schema = s0ma_studi0.studi0_state.GRAPH_SCHEMA
    harness = read(STEPPING_HARNESS)
    assert "../../s0ma_src/assets/app.css" in harness
    assert '<script src="../../s0ma_src/assets/app.js"></script>' in harness
    assert "__S0MA_FIXTURE__" not in harness
    assert "__S0MA_TERMS__" not in harness
    assert harness.index("window.fetch = ") < harness.index("assets/app.js\"></script>")
    assert '"' + graph_schema + '"' in harness
    assert "Land the next build" in harness
    assert "Start over" in harness
    # The controls sit outside the page's mount, so the page owns its own.
    assert harness.index('id="stepper"') < harness.index('id="s0ma-sh0w"')
    assert "http://" not in harness
    assert "https://" not in harness


# ---------------------------------------------------------------------------
# Regeneration
# ---------------------------------------------------------------------------


def write_fixtures() -> None:
    """Rebuild every derived file from the committed sources."""
    with tempfile.TemporaryDirectory() as scratch:
        base = Path(scratch)
        for name in BUILDS:
            root = stage(name, base / name)
            build(root)
            graph_path(name).write_text(dumps(collect(root)), encoding="utf-8", newline="\n")
        unbuilt = stage("build_1", base / "unbuilt" / PROJECT_NAME)
        UNBUILT_ANSWERS.write_text(dumps(answers(unbuilt)), encoding="utf-8", newline="\n")
    harness = read(STEPPING_HARNESS)
    for element_id, document in harness_blocks().items():
        harness = _splice(harness, element_id, document)
    STEPPING_HARNESS.write_text(harness, encoding="utf-8", newline="\n")


if __name__ == "__main__":
    if sys.argv[1:] != ["--write"]:
        raise SystemExit("usage: python tests/test_pipeline_builds.py --write")
    write_fixtures()
