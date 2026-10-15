"""The packaged teaching slice: it ships, it matches, and it still answers.

Milestone F8 of the docs-function plan (internal) §11, owner decision D-9.

Four questions, and each of them is one this package got wrong before:

1. **Does the teaching content ship?** It did not. ``packages =
   ["src/s0ma"]`` shipped the package and the user guide the teaching
   module read lived in the repository, so every pip-installed copy of
   s0ma answered every teaching question with "documentation files are not
   available in this installation". :class:`TestPackagedSlice` and
   :class:`TestWheelCarriesTheSlice` are that failure, pinned from both
   sides — in this process, and inside a real wheel installed into an
   empty environment with no s0ma-dsl and no s0ma-mcp beside it.
2. **Is the copy the same file?** The slice is generated into
   ``docs/_generated/core-teaching-slice.json`` and mirrored into the
   packaged tree; two copies of anything is a drift surface, so
   :class:`TestMirrorDrift` compares the bytes. It skips outside a
   checkout, which is exactly where a skipping gate becomes a gate that
   proves nothing — so the class carries a companion that runs everywhere
   and asserts the packaged file is really there and really parses. A
   skipped comparison plus a passing presence check is a report; a skipped
   comparison alone is silence.
3. **Does every question still answer?** The twelve keyword groups this
   package answered on before are re-pointed at current topics rather than
   retired, and :class:`TestLegacyVocabulary` walks the whole vocabulary,
   one pinned case per keyword.
4. **Did it cost a dependency?** D-9 says the slice must create no upward
   dependency on s0ma-dsl, s0ma-mcp or s0ma-studi0.
   :class:`TestNoUpwardDependency` reads the imports out of the module's
   own source and then proves the runtime claim the source can only
   suggest: after a real teaching answer, in a fresh interpreter, none of
   the three has been imported.
5. **Does an answer say which build it is from?** Milestone H2 added the
   fifth, and it is a question this package used to answer wrongly rather
   than not at all: every answer named a release version flat, so a wheel
   built from ``main`` told its reader it was teaching the released
   0.18.1. :class:`TestTheAnswerSaysWhichBuild` holds the labelling rule
   — bare version for a release build, ``0.18.1 (preview)`` otherwise —
   and the default that makes a slice which says nothing read as preview
   rather than as released.
"""

from __future__ import annotations

import ast
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

import pytest

import s0ma
from s0ma._bootstrap import bootstrap_register
from s0ma.api.teaching import _TOPIC_TO_HEADING as LEGACY_TABLE
from s0ma.api.teaching import (
    SLICE_SCHEMA,
    TeachingProvider,
    TeachingSlice,
    packaged_slice,
    resolve_slice_path,
)
from s0ma.registry import ComponentRegistry

# ---------------------------------------------------------------------------
# Where things are
# ---------------------------------------------------------------------------

#: The mirror inside the packaged tree — the file the wheel carries.
MIRROR = Path(s0ma.__file__).resolve().parent / "_teaching" / "slice.json"

#: The documentation application's own output, relative to a checkout.
ARTIFACT = ("docs", "_generated", "core-teaching-slice.json")

#: This module's own file, for finding the checkout above it.
HERE = Path(__file__).resolve()

#: Honest floors on what the slice must carry. Under the live counts, for
#: the reason every floor in this repository is under its count: a floor at
#: the count fails the day somebody writes one more concept. What they
#: catch is a *family* going missing, which is the failure that would ship
#: a wheel teaching half the product while every byte comparison passed.
FLOORS = {"concepts": 30, "surfaces": 36, "journeys": 4, "indexes": 4}

#: Every keyword this package answered on before the slice existed, taken
#: from the table itself rather than written out again — a list copied here
#: would stop matching the day somebody edited that one.
LEGACY_KEYWORDS = sorted({word for keywords, _ in LEGACY_TABLE for word in keywords})


def checkout_artifact() -> Path | None:
    """The documentation application's slice in the checkout above this file."""
    for parent in HERE.parents:
        candidate = parent.joinpath(*ARTIFACT)
        if candidate.is_file():
            return candidate
    return None


@pytest.fixture()
def registry_with_framework() -> ComponentRegistry:
    """A fresh registry holding the framework's own components."""
    registry = ComponentRegistry(persist=False)
    bootstrap_register(registry)
    return registry


@pytest.fixture()
def teacher(registry_with_framework: ComponentRegistry) -> TeachingProvider:
    """A provider reading the packaged slice, as an installed copy would."""
    return TeachingProvider(registry_with_framework)


# ---------------------------------------------------------------------------
# The slice ships
# ---------------------------------------------------------------------------


class TestPackagedSlice:
    """The teaching content is inside the package and readable from it."""

    def test_the_packaged_slice_is_readable(self) -> None:
        found = packaged_slice()
        assert found is not None, (
            "s0ma/_teaching/slice.json is not readable as package data. The "
            "teaching content ships inside the wheel; without it every "
            "installed copy degrades to the message F8 removed."
        )
        where, text = found
        assert where == "s0ma/_teaching/slice.json"
        assert text

    def test_it_names_the_schema_this_reader_understands(self) -> None:
        document = json.loads(MIRROR.read_text(encoding="utf-8"))
        assert document["schema"] == SLICE_SCHEMA

    def test_it_carries_its_build_identity(self) -> None:
        current = TeachingSlice.load(*_packaged())
        assert current.release_version
        assert current.snapshot_hash.startswith("sha256:")
        assert current.model_schema.startswith("s0ma-docs-model@")
        assert current.build_channel

    def test_the_shipped_slice_declares_its_channel(self) -> None:
        """H2's additive field, present in the file the wheel really ships.

        Read off the document rather than off the reader, because the
        reader defaults a missing channel to preview — which is the right
        behaviour for an old slice and would quietly hide a generator that
        had stopped writing the field.
        """
        source = json.loads(MIRROR.read_text(encoding="utf-8"))["source"]
        assert source["build_channel"], source
        assert source["build_channel"] == TeachingSlice.load(*_packaged()).build_channel

    @pytest.mark.parametrize("group", sorted(FLOORS))
    def test_it_carries_enough_to_teach_from(self, group: str) -> None:
        document = json.loads(MIRROR.read_text(encoding="utf-8"))
        assert document["counts"][group] >= FLOORS[group]

    def test_every_topic_the_keywords_point_at_is_present(self) -> None:
        """The compatibility promise, checked against the shipped file.

        The generator refuses to render a slice whose keyword vocabulary
        points at a topic it did not select, so this can only fail if the
        committed file was produced some other way — which is worth
        knowing.
        """
        current = TeachingSlice.load(*_packaged())
        addressable = set(current.topics) | set(current.indexes)
        assert set(current.keywords.values()) <= addressable

    def test_the_provider_finds_it_without_being_told(
        self, teacher: TeachingProvider
    ) -> None:
        assert teacher.slice_available is True
        current = teacher.teaching_slice()
        assert current is not None
        assert current.where == "s0ma/_teaching/slice.json"

    def test_the_checkout_fallback_finds_the_generated_artifact(self) -> None:
        """The recovery path, for a tree whose mirror somebody deleted.

        Bounded on purpose: it walks a fixed number of directories above
        this file rather than searching upward forever, so a package
        installed somewhere deep cannot adopt an unrelated ``docs/``.
        """
        artifact = checkout_artifact()
        found = resolve_slice_path()
        if artifact is None:  # pragma: no cover - wheel-install context
            assert found is None
            return
        assert found == artifact


# ---------------------------------------------------------------------------
# Every answer says which build it is from
# ---------------------------------------------------------------------------


def _slice_with(**source_fields: str) -> TeachingSlice:
    """The packaged slice, re-read with its ``source`` block edited."""
    document = json.loads(MIRROR.read_text(encoding="utf-8"))
    document["source"].update(source_fields)
    return TeachingSlice.load("fixture", json.dumps(document))


class TestTheAnswerSaysWhichBuild:
    """The labelling rule, and the default that keeps it honest (H2).

    The rule is stated twice in this repository — here in core and in
    ``BuildStamp.version_line`` on the documentation side — because D-9
    forbids core the import that would let it share one. The two cannot
    drift silently: ``scripts/wheel_smoke.py`` renders this line out of a
    built wheel and compares it with the release manifest's own channel
    before a release is served.
    """

    def test_a_preview_build_is_labelled(self) -> None:
        current = _slice_with(build_channel="preview", release_version="0.18.1")
        assert current.version_line() == "0.18.1 (preview)"
        assert "s0ma 0.18.1 (preview)," in current.identity_line("concept:nerve")

    def test_a_release_build_says_the_bare_version(self) -> None:
        current = _slice_with(build_channel="release", release_version="0.18.1")
        assert current.version_line() == "0.18.1"
        assert "s0ma 0.18.1," in current.identity_line("concept:nerve")

    def test_a_slice_that_does_not_say_is_not_a_release(self) -> None:
        """The additive-field rule, and the cautious side of it.

        A slice written before H2 has no channel. Reading that as
        "released" would make every older wheel claim to teach a release it
        was never cut from, which is the failure the field exists to
        prevent — so the absence reads as preview and is *shown*.
        """
        document = json.loads(MIRROR.read_text(encoding="utf-8"))
        del document["source"]["build_channel"]
        current = TeachingSlice.load("fixture", json.dumps(document))
        assert current.build_channel == "preview"
        assert current.version_line().endswith(" (preview)")

    def test_the_version_stays_a_version(self) -> None:
        """The field a caller compares is not a sentence."""
        current = TeachingSlice.load(*_packaged())
        assert "(" not in current.release_version, current.release_version

    def test_every_served_answer_carries_the_line(
        self, teacher: TeachingProvider
    ) -> None:
        """Not the topic pages only: the map and the miss say it too."""
        current = teacher.teaching_slice()
        assert current is not None
        expected = current.version_line()
        for question in ("nerve", "concept:drift", "xyzzy plugh nothing"):
            answer = teacher.learn_topic(question)
            assert f"came from s0ma {expected}," in answer, question


# ---------------------------------------------------------------------------
# The mirror is the same file
# ---------------------------------------------------------------------------


class TestMirrorDrift:
    """The packaged copy and the generated artifact are one file, twice.

    If the comparison fails, the documentation application has written a
    new slice and the mirror was not refreshed. Copy it over and commit the
    result::

        uv run s0ma --project-root docs docs compose --output-dir docs
        cp docs/_generated/core-teaching-slice.json \\
           packages/s0ma-core/src/s0ma/_teaching/slice.json

    The order matters and is written down in ``docs/RELEASING.md``.
    """

    def test_the_packaged_file_is_there_and_parses(self) -> None:
        """Runs everywhere, including where the comparison below cannot.

        The companion that keeps a skip honest: outside a checkout there is
        no artifact to compare against, and a class whose only test skips
        reports nothing at all. This one asserts what can still be
        asserted — the file ships, it parses, and it has something in it.
        """
        current = TeachingSlice.load(*_packaged())
        assert current.topics
        assert current.indexes
        assert current.keywords
        assert current.snapshot_hash

    def test_the_mirror_matches_the_generated_artifact(self) -> None:
        artifact = checkout_artifact()
        if artifact is None:  # pragma: no cover - wheel-install context
            pytest.skip("not a repository checkout: no generated slice to compare")
        assert MIRROR.read_bytes() == artifact.read_bytes(), (
            "s0ma/_teaching/slice.json has drifted from "
            "docs/_generated/core-teaching-slice.json — refresh the mirror "
            "(see this class's docstring and docs/RELEASING.md)"
        )

    def test_the_mirror_is_what_the_reader_reads(self) -> None:
        """No third copy: the file compared above is the file served."""
        _, text = _packaged()
        assert text == MIRROR.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# Every question still answers
# ---------------------------------------------------------------------------


class TestLegacyVocabulary:
    """Every keyword this package used to answer on still answers.

    One case per keyword rather than one per group, because the promise is
    per word: somebody's agent has "checklist" written into a prompt
    somewhere, and "the group still resolves" is not the same claim.
    """

    @pytest.mark.parametrize("keyword", LEGACY_KEYWORDS)
    def test_the_keyword_resolves(
        self, teacher: TeachingProvider, keyword: str
    ) -> None:
        current = teacher.teaching_slice()
        assert current is not None
        assert current.resolve(keyword) is not None, (
            f"{keyword!r} answered before the teaching slice and answers "
            f"nothing now. Repoint it in LEGACY_KEYWORDS, in the generator."
        )

    @pytest.mark.parametrize("keyword", LEGACY_KEYWORDS)
    def test_the_keyword_returns_real_content(
        self, teacher: TeachingProvider, keyword: str
    ) -> None:
        current = teacher.teaching_slice()
        assert current is not None
        answer = teacher.learn_topic(keyword)
        assert "not available" not in answer.lower()
        assert "Available topics for learn_about_s0ma" not in answer
        assert len(answer) > 200
        assert current.release_version in answer
        assert current.snapshot_hash in answer

    @pytest.mark.parametrize("keyword", LEGACY_KEYWORDS)
    def test_the_keyword_reaches_the_topic_the_slice_declares_for_it(
        self, teacher: TeachingProvider, keyword: str
    ) -> None:
        """The readings above the keyword table do not quietly hijack one.

        Four readings run before the vocabulary — id, alternate name, the
        topic's own name, and a name the question says. Any of them could
        catch a keyword on the way past and answer with something else, and
        the whole answer would still look reasonable. This pins each
        keyword to the topic the generator declared for it.
        """
        current = teacher.teaching_slice()
        assert current is not None
        assert current.resolve(keyword) == current.keywords[keyword]

    def test_a_question_about_an_idea_reaches_that_idea(
        self, teacher: TeachingProvider
    ) -> None:
        """The reading the old table could not do at all."""
        current = teacher.teaching_slice()
        assert current is not None
        assert current.resolve("nerve") == "concept:nerve"
        assert current.resolve("what is drift") == "concept:drift"
        assert current.resolve("concept:ganglion") == "concept:ganglion"

    def test_resolution_is_deterministic(self, teacher: TeachingProvider) -> None:
        """The same question, twice, is the same answer.

        An agent that gets two different lessons from one question has no
        way to tell which was the product and which was the ordering of a
        dictionary.
        """
        current = teacher.teaching_slice()
        assert current is not None
        for question in ("compliance rules", "how do I fix errors", "nerve", "setup"):
            assert current.resolve(question) == current.resolve(question)

    def test_a_question_nothing_answers_gets_the_map(
        self, teacher: TeachingProvider
    ) -> None:
        current = teacher.teaching_slice()
        assert current is not None
        assert current.resolve("xyzzy plugh nothing") is None
        answer = teacher.learn_topic("xyzzy plugh nothing")
        assert "index:all" in answer


# ---------------------------------------------------------------------------
# It cost no dependency
# ---------------------------------------------------------------------------

#: The three distributions core must never import (D-9's "no upward
#: dependency"). Named rather than pattern-matched, so adding a fourth
#: package to the workspace is a decision somebody takes here.
FORBIDDEN_IMPORTS = ("s0ma_dsl", "s0ma_mcp", "s0ma_studi0")

_ISOLATION_PROBE = """
import sys

from s0ma._bootstrap import bootstrap_register
from s0ma.api.teaching import TeachingProvider
from s0ma.registry import ComponentRegistry

registry = ComponentRegistry(persist=False)
bootstrap_register(registry)
teacher = TeachingProvider(registry)
assert teacher.slice_available, "no packaged teaching slice"
answer = teacher.learn_topic("nerve")
assert "concept:nerve" in answer, answer[:200]
leaked = sorted(
    name
    for name in sys.modules
    if name.split(".")[0] in ("s0ma_dsl", "s0ma_mcp", "s0ma_studi0")
)
assert not leaked, f"teaching imported {leaked}"
print("ISOLATED")
"""


class TestNoUpwardDependency:
    """Core teaches from the slice without reaching for the toolchain."""

    def test_the_module_imports_nothing_from_the_toolchain(self) -> None:
        source = Path(__file__).resolve().parents[1] / "src/s0ma/api/teaching.py"
        tree = ast.parse(source.read_text(encoding="utf-8"))
        imported: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.update(alias.name.split(".")[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported.add(node.module.split(".")[0])
        assert not imported & set(FORBIDDEN_IMPORTS)

    def test_it_reads_the_slice_with_the_standard_library(self) -> None:
        """No third-party import either — json and importlib, nothing else."""
        source = Path(__file__).resolve().parents[1] / "src/s0ma/api/teaching.py"
        tree = ast.parse(source.read_text(encoding="utf-8"))
        roots: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                roots.update(alias.name.split(".")[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                roots.add(node.module.split(".")[0])
        assert roots <= {
            "__future__",
            "collections",  # collections.abc, under TYPE_CHECKING
            "dataclasses",
            "importlib",
            "json",
            "pathlib",
            "re",
            "s0ma",
            "typing",
        }, sorted(roots)

    def test_nothing_from_the_toolchain_is_imported_at_runtime(self) -> None:
        """The claim the source can only suggest, proved in a fresh process.

        Read in this one it would be worth little: the suite may have
        imported anything by now. A new interpreter that answers a teaching
        question and then looks at ``sys.modules`` is the honest form of
        the question.
        """
        result = subprocess.run(  # noqa: S603 - fixed argv, no shell
            [sys.executable, "-I", "-c", _ISOLATION_PROBE],
            capture_output=True,
            text=True,
            check=False,
        )
        assert result.returncode == 0, result.stderr
        assert "ISOLATED" in result.stdout


# ---------------------------------------------------------------------------
# A real wheel, installed into an empty environment
# ---------------------------------------------------------------------------

_WHEEL_PROBE = """
import importlib.util
import sys

EXPECTED_VERSION = ""  # WHEEL_PROBE_EXPECTED_VERSION
EXPECTED_SNAPSHOT = ""  # WHEEL_PROBE_EXPECTED_SNAPSHOT
EXPECTED_CHANNEL = ""  # WHEEL_PROBE_EXPECTED_CHANNEL
KEYWORDS = []  # WHEEL_PROBE_KEYWORDS

for name in ("s0ma_dsl", "s0ma_mcp", "s0ma_studi0"):
    assert importlib.util.find_spec(name) is None, f"{name} is installed"

from s0ma._bootstrap import bootstrap_register
from s0ma.api.teaching import TeachingProvider
from s0ma.registry import ComponentRegistry

registry = ComponentRegistry(persist=False)
bootstrap_register(registry)
teacher = TeachingProvider(registry)

assert teacher.slice_available, "the installed wheel carries no teaching slice"
assert not teacher.docs_available, "a wheel install should have no checkout guide"
current = teacher.teaching_slice()
assert current.where == "s0ma/_teaching/slice.json", current.where
assert current.release_version == EXPECTED_VERSION, current.release_version
assert current.snapshot_hash == EXPECTED_SNAPSHOT, current.snapshot_hash
assert current.build_channel == EXPECTED_CHANNEL, current.build_channel

answer = teacher.learn_topic("nerve")
assert "concept:nerve" in answer, answer[:300]
assert "not available" not in answer.lower(), answer[:300]
assert EXPECTED_VERSION in answer and EXPECTED_SNAPSHOT in answer
# The whole written line, not its parts: the bare version is a substring
# of the labelled one, so asserting it alone would pass on a wheel that
# had quietly dropped the channel (H2).
assert f"came from s0ma {current.version_line()}," in answer, answer[-300:]

for word in KEYWORDS:
    lesson = teacher.learn_topic(word)
    assert "not available" not in lesson.lower(), (word, lesson[:200])
    assert len(lesson) > 200, (word, len(lesson))

guide = teacher.get_user_guide()
assert "not available" not in guide.lower(), guide[:300]

print("COLD OK", current.release_version, current.snapshot_hash, len(current.topics))
"""


def _wheel_probe_source() -> str:
    """The probe, with this build's identity written into it.

    The expected version and snapshot are read from the mirror in *this*
    process and injected, so the installed wheel is checked against the
    tree it was built from rather than against whatever it happens to say.
    """
    document = json.loads(MIRROR.read_text(encoding="utf-8"))
    source = _WHEEL_PROBE
    for marker, value in (
        ("WHEEL_PROBE_EXPECTED_VERSION", document["source"]["release_version"]),
        ("WHEEL_PROBE_EXPECTED_SNAPSHOT", document["source"]["snapshot_hash"]),
        ("WHEEL_PROBE_EXPECTED_CHANNEL", document["source"]["build_channel"]),
        ("WHEEL_PROBE_KEYWORDS", LEGACY_KEYWORDS),
    ):
        line = next(
            candidate
            for candidate in source.splitlines()
            if candidate.endswith(f"# {marker}")
        )
        name = line.split("=", 1)[0].strip()
        source = source.replace(line, f"{name} = {value!r}", 1)
    return source


def _run(argv: list[Any], cwd: Path) -> None:
    rendered = [str(item) for item in argv]
    print(f"$ {' '.join(rendered)}", flush=True)
    subprocess.run(rendered, cwd=cwd, check=True)  # noqa: S603 - fixed argv


class TestWheelCarriesTheSlice:
    """The proof, end to end: build the wheel, install it alone, ask it.

    This is the test the F8 defect would have failed and nothing else in
    this suite would. Everything above runs against the source tree, where
    the slice is present because it is a file in the directory; the only
    way to know a *wheel* carries it is to build one and look — the same
    reasoning ``scripts/wheel_smoke.py`` applies to the other three
    distributions.

    It installs s0ma-core and nothing else, which also settles D-9's other
    half: the answer comes back with no s0ma-dsl, no s0ma-mcp and no
    s0ma-studi0 anywhere on the path.
    """

    def test_a_cold_install_answers_a_teaching_question(self) -> None:
        root = checkout_artifact()
        if root is None or shutil.which("uv") is None:  # pragma: no cover
            pytest.skip("needs a repository checkout and uv on PATH")
        workspace = root.parents[2]
        with tempfile.TemporaryDirectory(prefix="s0ma-f8-wheel-") as raw:
            temporary = Path(raw)
            dist = temporary / "dist"
            _run(
                ["uv", "build", "--package", "s0ma-core", "--wheel", "--out-dir", dist],
                cwd=workspace,
            )
            wheels = sorted(dist.glob("s0ma_core-*.whl"))
            assert len(wheels) == 1, wheels
            self._assert_wheel_payload(wheels[0])

            environment = temporary / "venv"
            _run(["uv", "venv", "--python", sys.executable, environment], cwd=temporary)
            python = environment / (
                "Scripts/python.exe" if sys.platform == "win32" else "bin/python"
            )
            _run(["uv", "pip", "install", "--python", python, wheels[0]], cwd=temporary)

            probe = temporary / "cold_teaching_probe.py"
            probe.write_text(_wheel_probe_source(), encoding="utf-8", newline="\n")
            result = subprocess.run(  # noqa: S603 - fixed argv, no shell
                [str(python), "-I", str(probe)],
                cwd=temporary,
                capture_output=True,
                text=True,
                check=False,
            )
            print(result.stdout)
            assert result.returncode == 0, result.stderr
            assert "COLD OK" in result.stdout

    def _assert_wheel_payload(self, wheel: Path) -> None:
        """The slice is in the archive, byte for byte as committed."""
        import zipfile

        with zipfile.ZipFile(wheel) as archive:
            names = archive.namelist()
            assert "s0ma/_teaching/slice.json" in names, (
                "the s0ma-core wheel does not carry the teaching slice; check "
                "[tool.hatch.build.targets.wheel] in packages/s0ma-core/pyproject.toml"
            )
            assert archive.read("s0ma/_teaching/slice.json") == MIRROR.read_bytes()


# ---------------------------------------------------------------------------
# The served resources keep their addresses and gain current content
# ---------------------------------------------------------------------------

try:
    import mcp  # noqa: F401

    _HAS_MCP = True
except ImportError:  # pragma: no cover - the mcp extra is optional
    _HAS_MCP = False

#: Core's three teaching resources. Their addresses are a published
#: contract — a client that reads ``s0ma://docs/user-guide`` today must
#: keep reading it — so the URIs are pinned by name and only what they
#: *serve* changes.
DOC_RESOURCES = (
    "s0ma://docs/user-guide",
    "s0ma://docs/compliance-rules",
    "s0ma://docs/architecture",
)


@pytest.mark.skipif(not _HAS_MCP, reason="MCP SDK not installed")
class TestServedDocResources:
    """``s0ma://docs/*`` on an installation with no repository beside it.

    The resources that used to answer "documentation files are not
    available in this installation" whenever the user guide was not on
    disk — which, on a wheel, was always. Their addresses do not move; what
    comes back is now current teaching content or an answer that names
    what is here, and in neither case the degradation message.
    """

    @pytest.fixture()
    def server(self) -> Any:
        from s0ma.api.mcp_server import create_mcp_server

        registry = ComponentRegistry(persist=False)
        bootstrap_register(registry)
        # No checkout guide: the wheel condition, in process.
        return create_mcp_server(registry, docs_dir="/nonexistent_dir")

    def _read(self, server: Any, uri: str) -> str:
        import asyncio

        contents = list(asyncio.run(server.read_resource(uri)))
        assert len(contents) == 1
        text = contents[0].content
        assert isinstance(text, str)
        return text

    @pytest.mark.parametrize("uri", DOC_RESOURCES)
    def test_the_address_is_still_served(self, server: Any, uri: str) -> None:
        import asyncio

        listed = {str(resource.uri) for resource in asyncio.run(server.list_resources())}
        assert uri in listed

    @pytest.mark.parametrize("uri", DOC_RESOURCES)
    def test_it_no_longer_degrades(self, server: Any, uri: str) -> None:
        text = self._read(server, uri)
        assert "Documentation files are not available" not in text
        assert len(text) > 200

    def test_the_user_guide_address_serves_the_teaching_map(
        self, server: Any
    ) -> None:
        text = self._read(server, "s0ma://docs/user-guide")
        assert "concept:nerve" in text
        assert "teaching snapshot" in text

    @pytest.mark.parametrize(
        ("uri", "expected"),
        [
            ("s0ma://docs/compliance-rules", "concept:strictness-mode"),
            ("s0ma://docs/architecture", "concept:self-model"),
        ],
    )
    def test_a_guide_only_document_names_what_is_here(
        self, server: Any, uri: str, expected: str
    ) -> None:
        """Not the guide, and not a dead end: the topics that answer it."""
        text = self._read(server, uri)
        assert expected in text
        assert "teaching snapshot" in text

    def test_the_degradation_message_is_unreachable_with_a_slice(
        self, registry_with_framework: ComponentRegistry
    ) -> None:
        """Every served answer, on a wheel, is something other than the apology.

        The claim F8 is for. ``_docs_unavailable_message`` is still in the
        module — a tree with neither slice nor guide has to say *something*
        — but no path a wheel can take reaches it, including the one that
        asks for a guide section by heading and honestly has none.
        """
        teacher = TeachingProvider(
            registry_with_framework, docs_dir=Path("/nonexistent_dir")
        )
        answers = [
            teacher.get_user_guide(),
            teacher.get_compliance_rules(),
            teacher.get_compliance_checklist(),
            teacher.get_architecture(),
            teacher.get_section("Section 2: Creating Components"),
            teacher.learn_topic("nerve"),
            teacher.learn_topic("banana pancake recipe"),
        ]
        for answer in answers:
            assert "Documentation files are not available" not in answer
            assert "teaching snapshot" in answer

    def test_the_teaching_tool_answers_without_a_checkout(
        self, server: Any
    ) -> None:
        import asyncio

        content, _structured = asyncio.run(
            server.call_tool("learn_about_s0ma", {"topic": "nerve"})
        )
        answer = content[0].text
        assert "concept:nerve" in answer
        assert "not available" not in answer.lower()


def _packaged() -> tuple[str, str]:
    """The packaged slice, refusing the absence rather than skipping it."""
    found = packaged_slice()
    assert found is not None, "no packaged teaching slice in this installation"
    return found
