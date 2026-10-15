"""B2 (s0ma 0.11.0, batch-01a) — the build refuses to overwrite hand edits.

A generated ``.py`` carries ``# s0ma-output-hash: sha256:<h>``. If the
file is edited by hand the recomputed hash no longer matches, and the
next ``s0ma build`` would silently revert the edit — the failure that
detonated bench run ``P1_P_r02`` (acceptance 1/24; a hand-fixed
generated file clobbered on the next build). The write path now refuses
with a teaching message unless ``--force``; ``s0ma verify`` classifies
the file ``EDITED`` and ``s0ma check`` reports ``GENERATED_FILE_DRIFT``.
The emitter helpers (``is_hand_edited`` / ``recompute_output_hash``) are
the single source of truth all three paths share.

The refusal holds on every path a build can take: a warm cache is no
exception (a hit needs the published files to be the ones the build
wrote), and it gives way only when overwriting would lose nothing — the
edit was moved into the source — or when ``--force`` discards the edit.
"""

from __future__ import annotations

import json
import shutil
import textwrap
from typing import TYPE_CHECKING

from s0ma_dsl.cli.main import S0maCLI
from s0ma_dsl.codegen.python_emitter import (
    embedded_output_hash,
    inject_hashes,
    is_hand_edited,
    overwrite_loses_hand_edit,
    recompute_output_hash,
)
from s0ma_dsl.config import ERROR_CODE_DESCRIPTIONS

if TYPE_CHECKING:
    from pathlib import Path

    import pytest

_GREETING = """\
module greeting
    layer: DOMAIN
    version: {version}
    intent: "Greeting module {tag}."
    exports: [greet]
    requires: []
    uses: []

    soft_requires: none
    runtime_only_requires: none
    deferred_requires: none
    exports_helpers: none
nerve greet :: DOMAIN
    kind: FUNCTION
    visibility: PUBLIC
    intent: "Greet"
    expects: "name"
    guarantees: "Returns a greeting"
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
    def greet(name):
        return "hello " + name
"""


def _make_project(tmp_path: Path) -> Path:
    (tmp_path / "pyproject.toml").write_text(textwrap.dedent("""\
        [project]
        name = "b2demo"
        version = "0.0.1"

        [tool.s0ma]
        source_roots = ["src"]
        test_roots = ["tests"]
        build_dir = "build"
        """))
    src = tmp_path / "src"
    src.mkdir()
    (src / "greeting.s0ma").write_text(
        _GREETING.format(version="0.1.0", tag="v1")
    )
    return tmp_path


def _bump_source(project: Path, *, version: str, tag: str) -> None:
    (project / "src" / "greeting.s0ma").write_text(
        _GREETING.format(version=version, tag=tag)
    )


def _build(project: Path, *extra: str) -> int:
    return S0maCLI().run([
        "--project-root", str(project),
        "build", str(project), "--mode", "strict", *extra,
    ])


def _edit_generated(project: Path, old: str, new: str) -> Path:
    """Replace *old* with *new* in the generated ``build/greeting.py``."""
    gpy = project / "build" / "greeting.py"
    text = gpy.read_text(encoding="utf-8")
    assert old in text
    gpy.write_text(text.replace(old, new), encoding="utf-8", newline="\n")
    return gpy


def _edit_source(project: Path, old: str, new: str) -> None:
    """Replace *old* with *new* in the authored ``src/greeting.s0ma``."""
    src = project / "src" / "greeting.s0ma"
    text = src.read_text(encoding="utf-8")
    assert old in text
    src.write_text(text.replace(old, new), encoding="utf-8", newline="\n")


# ---------------------------------------------------------------------------
# The emitter helpers — the single source of truth for hand-edit detection
# ---------------------------------------------------------------------------


class TestHashHelpers:
    def test_freshly_injected_output_is_not_hand_edited(self) -> None:
        src = "def f():\n    return 1\n# s0ma-output-hash: __S0MA_OUTPUT_HASH__\n"
        injected = inject_hashes(
            "# s0ma-source-hash: __S0MA_SOURCE_HASH__\n" + src, "SOURCE"
        )
        assert embedded_output_hash(injected) is not None
        assert not is_hand_edited(injected)
        assert recompute_output_hash(injected) == embedded_output_hash(injected)

    def test_editing_the_body_makes_it_hand_edited(self) -> None:
        injected = inject_hashes(
            "# s0ma-source-hash: __S0MA_SOURCE_HASH__\n"
            "def f():\n    return 1\n"
            "# s0ma-output-hash: __S0MA_OUTPUT_HASH__\n",
            "SOURCE",
        )
        tampered = injected.replace("return 1", "return 999")
        assert is_hand_edited(tampered)

    def test_file_without_output_hash_is_never_hand_edited(self) -> None:
        # A bootstrap / hand-written file carries no output-hash header.
        assert not is_hand_edited("import os\n\n\ndef main():\n    pass\n")
        assert embedded_output_hash("print('hi')\n") is None


class TestOverwriteLosesHandEdit:
    """When overwriting a generated file would throw a hand edit away."""

    _TEMPLATE = (
        "# s0ma-source-hash: __S0MA_SOURCE_HASH__\n"
        "def f():\n    return {value}\n"
        "# s0ma-output-hash: __S0MA_OUTPUT_HASH__\n"
    )

    def _generated(self, value: int, source: str) -> str:
        return inject_hashes(self._TEMPLATE.format(value=value), source)

    def test_an_edit_the_new_output_lacks_is_lost(self) -> None:
        before = self._generated(1, "SOURCE v1")
        tampered = before.replace("return 1", "return 999")
        assert overwrite_loses_hand_edit(tampered, before)

    def test_an_edit_the_new_output_carries_is_not_lost(self) -> None:
        tampered = self._generated(1, "SOURCE v1").replace("return 1", "return 999")
        # The edit was moved into the source: the regenerated body is the
        # edited body, and only the two hash lines differ.
        regenerated = self._generated(999, "SOURCE v2")
        assert is_hand_edited(tampered)
        assert tampered != regenerated
        assert not overwrite_loses_hand_edit(tampered, regenerated)

    def test_an_untouched_file_has_nothing_to_lose(self) -> None:
        untouched = self._generated(1, "SOURCE v1")
        assert not overwrite_loses_hand_edit(untouched, self._generated(2, "SOURCE v2"))

    def test_a_file_without_output_hash_has_nothing_to_lose(self) -> None:
        # Never generated, so never guarded: the same rule as is_hand_edited.
        assert not overwrite_loses_hand_edit(
            "import os\n", self._generated(1, "SOURCE v1")
        )


# ---------------------------------------------------------------------------
# The build write-guard
# ---------------------------------------------------------------------------


class TestBuildRefusesHandEdit:
    """The write-guard, driven through a real build.

    Every read/write of the generated ``.py`` names ``encoding="utf-8"``
    (and LF) explicitly. The emitter writes UTF-8 and the output hash is
    taken over UTF-8 bytes, but an encoding-less ``read_text()`` decodes
    with the ANSI code page on Windows: the emitted header's em-dashes
    came back as mojibake, whose recomputed hash no longer matched the
    embedded one, and a freshly regenerated file read as hand-edited.
    """

    def test_build_refuses_to_overwrite_a_hand_edited_py(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str],
    ) -> None:
        project = _make_project(tmp_path)
        assert _build(project) == 0
        capsys.readouterr()

        gpy = project / "build" / "greeting.py"
        edited = gpy.read_text(encoding="utf-8").replace(
            'return "hello " + name', 'return "HAND EDIT " + name'
        )
        gpy.write_text(edited, encoding="utf-8", newline="\n")

        # Bump the source so the rebuild is a cache MISS and reaches the
        # overwrite path (the silent-revert scenario).
        _bump_source(project, version="0.2.0", tag="v2")
        rc = _build(project)
        out = capsys.readouterr().out

        assert rc != 0, "build must fail when it would clobber a hand edit"
        assert "GENERATED_FILE_DRIFT" in out
        assert "greeting.py" in out
        assert "--force" in out
        # The hand edit is preserved — the build refused to write.
        assert "HAND EDIT" in gpy.read_text(encoding="utf-8")

    def test_force_overwrites_the_hand_edited_py(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str],
    ) -> None:
        project = _make_project(tmp_path)
        assert _build(project) == 0
        capsys.readouterr()

        gpy = project / "build" / "greeting.py"
        gpy.write_text(
            gpy.read_text(encoding="utf-8").replace(
                'return "hello " + name', 'return "HAND EDIT " + name'
            ),
            encoding="utf-8",
            newline="\n",
        )
        _bump_source(project, version="0.2.0", tag="v2")

        rc = _build(project, "--force")
        assert rc == 0
        regenerated = gpy.read_text(encoding="utf-8")
        assert "HAND EDIT" not in regenerated
        assert 'return "hello " + name' in regenerated
        # --force regenerated from the bumped source, not a stale cache.
        assert "v2" in regenerated
        assert not is_hand_edited(regenerated)

    def test_clean_rebuild_is_not_refused(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str],
    ) -> None:
        """A byte-clean generated file is overwritten without any refusal."""
        project = _make_project(tmp_path)
        assert _build(project) == 0
        capsys.readouterr()

        # Change the source but leave the generated .py untouched (clean).
        _bump_source(project, version="0.2.0", tag="v2")
        rc = _build(project)
        out = capsys.readouterr().out
        assert rc == 0
        assert "GENERATED_FILE_DRIFT" not in out

    def test_generated_file_drift_is_cataloged(self) -> None:
        assert "GENERATED_FILE_DRIFT" in ERROR_CODE_DESCRIPTIONS


class TestAWarmCacheDoesNotKeepAHandEdit:
    """The write-guard, reached through a warm cache.

    A rebuild of an unchanged source used to be a cache hit that kept
    whatever the build directory held: the hand edit survived, the build
    exited 0 calling the module "kept from the last build", and only
    ``--no-cache`` or an edited source reached the refusal. The answer
    depended on whether ``.s0ma.cache/`` existed, which the spec says it
    never may. A hit now needs the published files to be the ones the
    build wrote, so a hand-edited one is a miss and the guard decides.
    """

    _EDIT = ('return "hello " + name', 'return "HAND EDIT " + name')

    def test_rebuilding_an_unchanged_source_refuses(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str],
    ) -> None:
        project = _make_project(tmp_path)
        assert _build(project) == 0
        capsys.readouterr()
        gpy = _edit_generated(project, *self._EDIT)

        rc = _build(project)  # the source is untouched: the cache is warm
        out = capsys.readouterr().out

        assert rc != 0, "a warm cache must not wave a hand edit through"
        assert "GENERATED_FILE_DRIFT" in out
        assert "kept from the last build" not in out
        assert "HAND EDIT" in gpy.read_text(encoding="utf-8")

    def test_the_answer_does_not_depend_on_the_cache(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str],
    ) -> None:
        project = _make_project(tmp_path)
        assert _build(project) == 0
        capsys.readouterr()
        _edit_generated(project, *self._EDIT)

        warm_rc = _build(project)
        warm = capsys.readouterr().out
        bypassed_rc = _build(project, "--no-cache")
        bypassed = capsys.readouterr().out
        cache_dir = project / "build" / ".s0ma.cache"
        assert cache_dir.is_dir(), "the first two runs must have had a cache"
        shutil.rmtree(cache_dir)
        deleted_rc = _build(project)
        deleted = capsys.readouterr().out

        assert warm_rc == bypassed_rc == deleted_rc != 0
        assert warm == bypassed == deleted

    def test_force_discards_the_edit_without_a_source_change(
        self, tmp_path: Path,
    ) -> None:
        project = _make_project(tmp_path)
        assert _build(project) == 0
        gpy = _edit_generated(project, *self._EDIT)

        assert _build(project, "--force") == 0
        regenerated = gpy.read_text(encoding="utf-8")
        assert "HAND EDIT" not in regenerated
        assert not is_hand_edited(regenerated)

    def test_an_untouched_rebuild_is_still_kept(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str],
    ) -> None:
        """The cache still does its job when the build directory is intact."""
        project = _make_project(tmp_path)
        assert _build(project) == 0
        capsys.readouterr()

        assert _build(project) == 0
        assert "1 module unchanged — kept from the last build" in (
            capsys.readouterr().out
        )


class TestMovingTheEditIntoTheSource:
    """The refusal's first way out, taken at its word: no ``--force``.

    The guard used to refuse any hand-edited file, so moving the change
    into the ``.s0ma`` source and building again was refused too — even
    though the regenerated file carried exactly the edit and differed
    only in its two hash lines. It now refuses only when overwriting the
    file would lose something.
    """

    def test_an_exact_move_builds_without_force(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str],
    ) -> None:
        project = _make_project(tmp_path)
        assert _build(project) == 0
        capsys.readouterr()
        gpy = _edit_generated(project, '"hello "', '"hi "')
        _edit_source(project, '"hello "', '"hi "')

        rc = _build(project)
        out = capsys.readouterr().out

        assert rc == 0
        assert "GENERATED_FILE_DRIFT" not in out
        rebuilt = gpy.read_text(encoding="utf-8")
        assert 'return "hi " + name' in rebuilt
        assert not is_hand_edited(rebuilt)

    def test_a_partial_move_still_refuses(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str],
    ) -> None:
        project = _make_project(tmp_path)
        assert _build(project) == 0
        capsys.readouterr()
        _edit_generated(project, '"hello "', '"hi "')
        gpy = _edit_generated(
            project, 'return "hi " + name', 'return "hi " + name  # only here'
        )
        _edit_source(project, '"hello "', '"hi "')

        rc = _build(project)
        out = capsys.readouterr().out

        assert rc != 0
        assert "GENERATED_FILE_DRIFT" in out
        assert "# only here" in gpy.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# `s0ma check`'s drift pass — surfaces the same hand-edit as a warning,
# before the next build would clobber it. (The `docs check-drift` /
# DRIFT_DETECTED mechanism is a separate concept covered by
# test_check_drift.py; this is the generated-.py hand-edit drift.)
# ---------------------------------------------------------------------------


class TestCheckReportsGeneratedFileDrift:
    def test_check_warns_on_hand_edited_generated_py(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str],
    ) -> None:
        project = _make_project(tmp_path)
        assert _build(project) == 0
        capsys.readouterr()

        gpy = project / "build" / "greeting.py"
        gpy.write_text(gpy.read_text().replace(
            'return "hello " + name', 'return "HAND EDIT " + name'
        ))

        rc = S0maCLI().run([
            "--project-root", str(project), "check", "--mode", "strict",
        ])
        out = capsys.readouterr().out
        # Warning-only: check does not fail on drift (the hard refusal is
        # in build), but the drift is visible.
        assert rc == 0
        assert "GENERATED_FILE_DRIFT" in out
        assert "greeting.py" in out

    def test_check_is_clean_when_generated_py_is_untouched(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str],
    ) -> None:
        project = _make_project(tmp_path)
        assert _build(project) == 0
        capsys.readouterr()

        rc = S0maCLI().run([
            "--project-root", str(project), "check", "--mode", "strict",
        ])
        out = capsys.readouterr().out
        assert rc == 0
        assert "GENERATED_FILE_DRIFT" not in out

    def test_check_says_what_the_build_does(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str],
    ) -> None:
        """One sentence for both commands, and no promise the build breaks.

        The warning used to promise that "the next `s0ma build` overwrites
        this file". Without ``--force`` no build did: it refused, or on a
        cache hit kept the edit. Check now says the sentence the build's
        refusal says, and its remediation names the two real ways out.
        """
        project = _make_project(tmp_path)
        assert _build(project) == 0
        capsys.readouterr()
        _edit_generated(
            project, 'return "hello " + name', 'return "HAND EDIT " + name'
        )

        assert S0maCLI().run([
            "--project-root", str(project), "check", "--mode", "strict",
            "--format", "json",
        ]) == 0
        (warning,) = [
            finding
            for finding in json.loads(capsys.readouterr().out)["warnings"]
            if finding["code"] == "GENERATED_FILE_DRIFT"
        ]
        assert _build(project, "--format", "json") != 0
        (error,) = [
            finding
            for finding in json.loads(capsys.readouterr().out)["errors"]
            if finding["code"] == "GENERATED_FILE_DRIFT"
        ]

        assert warning["message"] == error["message"]
        assert "will not overwrite it" in warning["message"]
        assert "overwritten on every build" not in warning["message"]
        assert "s0ma build --force" in warning["remediation"]
        assert "overwrites this file" not in warning["remediation"]
