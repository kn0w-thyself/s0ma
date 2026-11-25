"""An app that grows build by build, kept as a studi0 fixture.

studi0 is a viewer of builds that land while it is open, so it has to be
checked on a project that really changes. This module keeps one: the agent
sample ``s0ma new project --sample`` lays down, which is declared as five
ordered steps, plus one build more.

* **Builds 1 to 5:** the sample's steps 1 to 5, one build each. Each step
  adds modules and keeps every part the step before it built.
* **Build 6:** build 5 with one small change made by hand: the ``rules``
  module and its test are edited so the rule also hands off a reply that
  promises a delivery date. It is the same edit the guide's growth
  transcript makes, so a part that is already there changes.

No source is kept here. Each build's files are the template's own, from
``get_archetype("agent").files_through(N)``, written the way ``s0ma new
project`` writes them, and build 6 applies :data:`HAND_EDIT` on top.

Layout, under ``tests/fixtures/``:

* ``agent_builds/build_N.graph.json`` is what
  ``s0ma_dsl.graph_export.collect_graph`` gives at full detail for that
  build, the same document ``/api/graph`` carries under ``graph``.
* ``agent_builds/unbuilt_answers.json`` is what studi0's own routing
  answers on ``/api/state``, on ``/api/graph``, and on any path it does
  not serve, for a project that has not been built.
* ``stepping_harness.html`` loads the real page assets in live mode and
  answers the page's own requests from these files, landing the builds
  one at a time. Open it from a static server rooted at
  ``packages/s0ma-studi0``; its header comment has the command.

Pinned here: every build passes ``s0ma check --mode release`` and its own
tests; every build rebuilds to its committed graph and is served fresh;
the builds grow as described; build 6 changes exactly one part; the
unbuilt answers are the server's; and the harness embeds exactly these
files.

One value is normalized, and only one: ``freshness.transpiler_version``
names the s0ma-lang-dsl that built the graph, so it moves with every
release. The rebuilt graph must carry the running s0ma-lang-dsl's own
version there, and the comparison then sets that one key aside. No other
key is touched.

When a change to the language or to the template moves these files,
regenerate them, and the harness blocks that embed them, from
``packages/s0ma-studi0`` with::

    uv run python tests/test_agent_builds.py --write
"""

from __future__ import annotations

import copy
import json
import re
import sys
import tempfile
from pathlib import Path
from typing import Any

import pytest

PACKAGE_ROOT = Path(__file__).resolve().parents[1]
FIXTURE_DIR = PACKAGE_ROOT / "tests" / "fixtures"
BUILDS_DIR = FIXTURE_DIR / "agent_builds"
UNBUILT_ANSWERS = BUILDS_DIR / "unbuilt_answers.json"
STEPPING_HARNESS = FIXTURE_DIR / "stepping_harness.html"
TERMS_FIXTURE = FIXTURE_DIR / "sh0w_terms_fixture.json"

#: The sample the builds are made from, and its number of steps.
SAMPLE = "agent"
LAST_STEP = 5

#: One build per step, then the build with the hand edit.
BUILDS = tuple(f"build_{number}" for number in range(1, LAST_STEP + 2))
EDITED = BUILDS[-1]

#: The one hand edit build 6 makes after the last step, so a build changes
#: a part that is already there. Each file it writes is the template's own
#: file with exactly these lines replaced. The guide's growth transcript
#: makes the same edit (``packages/s0ma-dsl/tests/test_docs_journey_watch_an_app.py``).
HAND_EDIT: dict[str, tuple[tuple[str, str], ...]] = {
    "src/rules/rules.s0ma": (
        (
            '    forbids: "Never lets out a reply that promises a refund."',
            '    forbids: "Never lets out a reply that promises a refund or a delivery date."',
        ),
        (
            '        """Hand off any reply that promises a refund."""',
            '        """Hand off any reply that promises a refund or a delivery date."""',
        ),
        (
            '        if "refund" in reply.text.lower():',
            '        if any(word in reply.text.lower() for word in ("refund", "will arrive")):',
        ),
    ),
    "tests/rules/rules_tests.s0ma": (
        (
            '    intent: "A reply that promises a refund becomes a hand-off, and any other'
            ' reply goes out as it was."',
            '    intent: "A reply that promises a refund or a delivery date becomes a'
            ' hand-off, and any other reply goes out as it was."',
        ),
        (
            '        ok = Reply(action="answer", text="It ships today.")',
            '        assert keep_the_rules(Reply(action="answer", text="It will arrive on'
            ' Friday.")).action == "hand_off"\n'
            '        ok = Reply(action="answer", text="It ships today.")',
        ),
    ),
}

#: The parts the hand edit changes, and nothing else.
EDITED_PARTS = ["rules::keep_the_rules"]

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


def _archetype() -> Any:
    from s0ma_dsl.cli.templates import get_archetype

    return get_archetype(SAMPLE)


def build_files(build: str) -> dict[str, str]:
    """The sample's files for *build*, by relpath, as the scaffolder writes them."""
    from s0ma_dsl.cli.project_steps import template_bytes

    number = BUILDS.index(build) + 1
    step = min(number, LAST_STEP)
    files = {
        file.relpath: template_bytes(file).decode("utf-8")
        for file in _archetype().files_through(step)
    }
    if build == EDITED:
        for relpath, replacements in HAND_EDIT.items():
            text = files[relpath]
            for old, new in replacements:
                assert text.count(old) == 1, (relpath, old)
                text = text.replace(old, new)
            files[relpath] = text
    return files


def stage(build: str, root: Path) -> Path:
    """Lay down *build* at *root*, unbuilt, the way ``s0ma new project`` does."""
    from s0ma_dsl.cli.new_project import write_bare_project

    archetype = _archetype()
    write_bare_project(root, archetype, archetype.default_project_name, "dev", "on")
    for relpath, text in build_files(build).items():
        path = root.joinpath(*relpath.split("/"))
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8", newline="\n")
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


def harness_lines() -> list[str]:
    """The harness's status line before any build and after each one."""
    steps = _archetype().steps
    total = len(BUILDS)
    lines = ["Showing: nothing built yet."]
    for number, step in enumerate(steps, start=1):
        lines.append(f"Showing build {number} of {total}: step {number}, {step.name.lower()}.")
    lines.append(f"Showing build {total} of {total}: one rule changed by hand.")
    return lines


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
        "sh0w-lines": harness_lines(),
    }
    for number, name in enumerate(BUILDS, start=1):
        blocks[f"sh0w-build-{number}"] = json.loads(read(graph_path(name)))
    return blocks


def parts(name: str) -> dict[str, Any]:
    """A committed build's parts that are not tests, by canonical id."""
    components = json.loads(read(graph_path(name)))["components"]
    return {
        key: value
        for key, value in components.items()
        if value["declaration_type"] != "test"
    }


# ---------------------------------------------------------------------------
# Every build is a real, passing project
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def built(tmp_path_factory: pytest.TempPathFactory) -> dict[str, Path]:
    """Each build staged from the template and built once."""
    base = tmp_path_factory.mktemp("agent_builds")
    roots: dict[str, Path] = {}
    for name in BUILDS:
        roots[name] = stage(name, base / name)
        build(roots[name])
    return roots


def test_there_is_one_build_per_step_and_one_edited() -> None:
    assert len(_archetype().steps) == LAST_STEP
    assert BUILDS == tuple(f"build_{n}" for n in range(1, 7))
    assert sorted(p.name for p in BUILDS_DIR.iterdir()) == sorted(
        [*(f"{name}.graph.json" for name in BUILDS), "unbuilt_answers.json"]
    )


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
    """Each step adds parts only in the modules it adds, and keeps the rest as they were."""
    steps = _archetype().steps
    earlier: dict[str, Any] = {}
    for name, step in zip(BUILDS, steps, strict=False):
        now = parts(name)
        assert set(earlier) <= set(now), name
        for key, value in earlier.items():
            assert now[key] == value, f"{name} changed {key}"
        added = set(now) - set(earlier)
        assert added, name
        new_modules = {
            file.relpath.rsplit("/", 1)[-1].removesuffix(".s0ma")
            for file in step.files
            if file.relpath.endswith(".s0ma")
        }
        assert {key.split("::")[0] for key in added} <= new_modules, name
        earlier = now
    assert sorted(parts(BUILDS[0])) == ["inbox::Message", "inbox::read_message"]
    # Every part, tests included, as ``s0ma new project --step N`` reports it.
    counts = [len(json.loads(read(graph_path(name)))["components"]) for name in BUILDS]
    assert counts == [3, 6, 9, 14, 16, 16]


def test_the_edited_build_changes_exactly_one_part() -> None:
    last, edited = parts(BUILDS[LAST_STEP - 1]), parts(EDITED)
    assert sorted(edited) == sorted(last)
    changed = sorted(key for key in edited if edited[key] != last[key])
    assert changed == EDITED_PARTS


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


def test_the_last_step_is_what_the_sample_scaffolds(tmp_path: Path) -> None:
    """Build 5 is ``s0ma new project --sample``, file for file."""
    from s0ma_dsl.cli.main import EXIT_SUCCESS

    # The scaffold names its project after its folder.
    target = tmp_path / "scaffolded" / _archetype().default_project_name
    rc = run_cli("new", "project", str(target), "--template", SAMPLE, "--quiet")
    assert rc == EXIT_SUCCESS
    staged = stage(BUILDS[LAST_STEP - 1], tmp_path / "staged")
    kept = sorted(
        path.relative_to(staged).as_posix() for path in staged.rglob("*") if path.is_file()
    )
    assert "pyproject.toml" in kept
    for relative in kept:
        assert (target / relative).read_bytes() == (
            staged / relative
        ).read_bytes(), f"{relative} differs from the scaffold"


def test_the_unbuilt_answers_are_the_servers(tmp_path: Path) -> None:
    root = stage(BUILDS[0], tmp_path / "unbuilt")
    assert answers(root) == json.loads(read(UNBUILT_ANSWERS))


# ---------------------------------------------------------------------------
# The stepping harness
# ---------------------------------------------------------------------------


def test_stepping_harness_embeds_the_committed_fixtures() -> None:
    harness = read(STEPPING_HARNESS)
    for element_id, document in harness_blocks().items():
        assert _embedded(harness, element_id) == document, element_id
    assert len(re.findall(r'<script id="sh0w-build-\d+"', harness)) == len(BUILDS)


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
    """Rebuild every derived file from the template."""
    BUILDS_DIR.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as scratch:
        base = Path(scratch)
        for name in BUILDS:
            root = stage(name, base / name)
            build(root)
            graph_path(name).write_text(dumps(collect(root)), encoding="utf-8", newline="\n")
        unbuilt = stage(BUILDS[0], base / "unbuilt")
        UNBUILT_ANSWERS.write_text(dumps(answers(unbuilt)), encoding="utf-8", newline="\n")
    harness = read(STEPPING_HARNESS)
    for element_id, document in harness_blocks().items():
        harness = _splice(harness, element_id, document)
    STEPPING_HARNESS.write_text(harness, encoding="utf-8", newline="\n")


if __name__ == "__main__":
    if sys.argv[1:] != ["--write"]:
        raise SystemExit("usage: python tests/test_agent_builds.py --write")
    write_fixtures()
