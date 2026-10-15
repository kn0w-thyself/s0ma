"""M2 (s0ma 0.13.0, batch-01c) — the build refuses NEW check errors.

``build_project`` failed 0/84 times in batch-01c cold sessions while
18/36 ended check-red; the CM6 crater (``P2_P_haiku45_r03``) shipped
through exactly that gap — the agent read its own check failures, called
them "pre-existing and not related to my changes" (it was wrong), built
green (``build`` runs dev, ``check`` runs strict), and never ran the
service. 0.12.0 M2 made NEW-vs-PRE-EXISTING computable; this milestone
makes it BINDING on the build.

The load-bearing shape: ``PROVIDES_KEY_MISMATCH`` is a *warning* in dev
(so a dev build's own error gate stays green) but an *error* in strict
(so ``check`` goes red) — the exact check-red / build-green class. The
factory below defines every ``provides:`` name (so no always-error
``MISSING_PROVIDED_FUNCTION`` fires) and returns a dict whose literal
keys differ, so the tree's ONLY finding is ``PROVIDES_KEY_MISMATCH``.

Coverage maps to the M2 done-when clauses:

* refuse          — green baseline, an edit introduces a NEW check error
* allow           — ``--allow-new-errors`` builds + stamps the manifest
* pre-existing    — a check-recorded error alone never blocks (brownfield)
* no-baseline     — a missing baseline degrades to today's warn-and-build
* CM6 e2e         — the whole refuse -> allow arc driven end to end
* exemptions      — ``--check`` dry-run and synthetic projects are not gated
* manifest        — the override key round-trips through ``load_manifest``
"""

from __future__ import annotations

import io
import json
from contextlib import redirect_stdout
from typing import TYPE_CHECKING

from s0ma_dsl.check_baseline import baseline_path
from s0ma_dsl.cli.main import S0maCLI
from s0ma_dsl.codegen.build_manifest import MANIFEST_FILENAME, load_manifest

if TYPE_CHECKING:
    from pathlib import Path

    import pytest

_PYPROJECT = """\
[project]
name = "gate_app"
version = "0.1.0"

[tool.s0ma]
source_roots = ["src"]
build_dir = "build"
"""

# A SERVICE factory that DEFINES every provides: name (so no always-error
# MISSING_PROVIDED_FUNCTION) — only the terminal return dict's literal
# keys are varied, so PROVIDES_KEY_MISMATCH (warning in dev, error in
# strict) is the sole finding.
_HEAD = """\
module provides_demo
    layer: APPLICATION
    version: 0.1.0
    intent: "A service module exercising the NEW check-error build gate."
    exports: [assembler]

    requires: none
    uses: none
    soft_requires: none
    runtime_only_requires: none
    deferred_requires: none
    exports_helpers: none
nerve assembler :: APPLICATION
    kind: SERVICE
    visibility: PUBLIC
    intent: "Return a dict of ops for the build-gate tests."
    expects: "no arguments"
    guarantees: "returns a dict of ops"
    forbids: none
    provides: [assemble, validate]
    evaluates_at: FUNCTION_BOUNDARY
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
    def assembler():
        def assemble():
            return 1
        def validate():
            return 1
"""

_GREEN = _HEAD + "        return {'assemble': assemble, 'validate': validate}\n"
# 'validate' -> 'validat' in the return dict: PROVIDES_KEY_MISMATCH only.
_BROKEN = _HEAD + "        return {'assemble': assemble, 'validat': validate}\n"


def _make_project(root: Path, source: str) -> Path:
    src = root / "src"
    src.mkdir(parents=True)
    (root / "pyproject.toml").write_text(_PYPROJECT, encoding="utf-8")
    (src / "provides_demo.s0ma").write_text(source, encoding="utf-8")
    return root


def _write(root: Path, source: str) -> None:
    (root / "src" / "provides_demo.s0ma").write_text(source, encoding="utf-8")


def _run(root: Path, *argv: str) -> int:
    return S0maCLI().run(["--project-root", str(root), *argv])


def _build(root: Path, *extra: str, mode: str = "dev") -> int:
    return _run(root, "build", str(root), "--mode", mode, *extra)


def _build_json(root: Path, *extra: str, mode: str = "dev") -> tuple[int, dict]:
    buf = io.StringIO()
    with redirect_stdout(buf):
        rc = _build(root, "--format", "json", *extra, mode=mode)
    return rc, json.loads(buf.getvalue())


def _manifest_path(root: Path) -> Path:
    return root / "build" / MANIFEST_FILENAME


# ---------------------------------------------------------------------------
# refuse
# ---------------------------------------------------------------------------


class TestRefuse:
    def test_new_check_error_refuses_build_text(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str],
    ) -> None:
        root = _make_project(tmp_path / "p", _GREEN)
        assert _build(root, "--quiet") == 0  # green build -> green baseline
        capsys.readouterr()

        _write(root, _BROKEN)
        rc = _build(root)
        out = capsys.readouterr().out
        assert rc != 0
        # leads with the rule; the NEW error is labelled and carries M1's
        # ready-to-paste suggested block; the escape hatch is named.
        assert "BUILD REFUSED" in out
        assert "new check errors block builds" in out
        assert "[NEW]" in out
        assert "PROVIDES_KEY_MISMATCH" in out
        assert "Suggested fix" in out
        assert "--allow-new-errors" in out

    def test_refusal_writes_no_new_artifacts_and_leaves_baseline(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str],
    ) -> None:
        root = _make_project(tmp_path / "p", _GREEN)
        assert _build(root, "--quiet") == 0
        capsys.readouterr()
        # The green baseline is empty; the refusal must not overwrite it,
        # so a re-run refuses again (the override is a one-shot, not a
        # laundering of NEW -> PRE-EXISTING).
        green_baseline = baseline_path(root).read_bytes()

        _write(root, _BROKEN)
        assert _build(root) != 0
        capsys.readouterr()
        assert baseline_path(root).read_bytes() == green_baseline
        # a SECOND build still refuses — NEW-ness did not erode
        assert _build(root) != 0

    def test_refusal_json_is_first_class(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str],
    ) -> None:
        root = _make_project(tmp_path / "p", _GREEN)
        assert _build(root, "--quiet") == 0
        capsys.readouterr()

        _write(root, _BROKEN)
        rc, doc = _build_json(root)
        assert rc != 0
        assert doc["build_refused"]["reason"] == "NEW_CHECK_ERRORS"
        assert doc["build_refused"]["new_error_count"] == 1
        assert "new check errors block builds" in doc["build_refused"]["rule"]
        err = doc["errors"][0]
        assert err["code"] == "PROVIDES_KEY_MISMATCH"
        assert err["delta_label"] == "NEW"
        assert err["suggested_declaration"].startswith("provides: [")


# ---------------------------------------------------------------------------
# allow
# ---------------------------------------------------------------------------


class TestAllow:
    def test_allow_new_errors_builds_and_stamps_manifest(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str],
    ) -> None:
        root = _make_project(tmp_path / "p", _GREEN)
        assert _build(root, "--quiet") == 0
        capsys.readouterr()

        _write(root, _BROKEN)
        rc, doc = _build_json(root, "--allow-new-errors")
        assert rc == 0  # the override built (PKM is a dev-warning)
        assert doc["build_override"]["allow_new_errors"] is True
        assert doc["build_override"]["new_error_count"] == 1
        # the manifest logs the override so the bench can count it
        manifest = load_manifest(root / "build")
        assert manifest.overridden_new_errors == (
            "PROVIDES_KEY_MISMATCH@src/provides_demo.s0ma",
        )

    def test_override_text_note_leads(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str],
    ) -> None:
        root = _make_project(tmp_path / "p", _GREEN)
        assert _build(root, "--quiet") == 0
        capsys.readouterr()
        _write(root, _BROKEN)
        rc = _build(root, "--allow-new-errors")
        out = capsys.readouterr().out
        assert rc == 0
        assert "built with --allow-new-errors" in out


# ---------------------------------------------------------------------------
# pre-existing alone never blocks (brownfield)
# ---------------------------------------------------------------------------


class TestPreExistingOnly:
    def test_pre_existing_check_error_builds(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str],
    ) -> None:
        root = _make_project(tmp_path / "p", _BROKEN)
        # A prior strict check records the failure into the baseline, so
        # the build classifies it PRE-EXISTING — brownfield stays viable.
        assert _run(root, "check", "--mode", "strict") != 0
        capsys.readouterr()

        rc, doc = _build_json(root)
        assert rc == 0
        assert "build_refused" not in doc
        assert "build_override" not in doc
        assert _manifest_path(root).is_file()


# ---------------------------------------------------------------------------
# no baseline -> today's behaviour (warn, build)
# ---------------------------------------------------------------------------


class TestNoBaseline:
    def test_missing_baseline_degrades_to_warn_and_build(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str],
    ) -> None:
        root = _make_project(tmp_path / "p", _BROKEN)
        # No prior check/build -> no baseline -> nothing attributable.
        assert not baseline_path(root).exists()
        rc, doc = _build_json(root)
        assert rc == 0
        assert "build_refused" not in doc
        # PROVIDES_KEY_MISMATCH surfaced as a dev warning, not a block.
        codes = {w["code"] for w in doc["warnings"]}
        assert "PROVIDES_KEY_MISMATCH" in codes
        assert _manifest_path(root).is_file()


# ---------------------------------------------------------------------------
# CM6 shape, end to end
# ---------------------------------------------------------------------------


class TestCM6EndToEnd:
    def test_green_then_new_error_refuses_then_allow_builds(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str],
    ) -> None:
        """The exact evidence the r03 agent's build never surfaced.

        Green baseline -> an edit introduces a NEW check error -> the
        build REFUSES with the labelled list -> allow_new_errors builds
        and stamps the manifest + the override marker.
        """
        root = _make_project(tmp_path / "p", _GREEN)
        assert _build(root, "--quiet") == 0
        capsys.readouterr()

        # edit introduces the NEW error
        _write(root, _BROKEN)
        rc, doc = _build_json(root)
        assert rc != 0
        assert doc["build_refused"]["new_error_count"] == 1
        assert doc["errors"][0]["delta_label"] == "NEW"

        # allow_new_errors builds and records the override
        rc, doc = _build_json(root, "--allow-new-errors")
        assert rc == 0
        assert doc["build_override"]["new_error_count"] == 1
        manifest = load_manifest(root / "build")
        assert manifest.overridden_new_errors == (
            "PROVIDES_KEY_MISMATCH@src/provides_demo.s0ma",
        )

    def test_honest_cm6_shape_intervening_check_cannot_launder(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str],
    ) -> None:
        """The HONEST CM6 sequence — the crater agent RAN check first.

        Green baseline -> edit introduces a NEW check error -> ``check``
        runs RED (labelled NEW, and its recording must not launder the
        attribution) -> the build STILL refuses -> fix -> green build.
        Under 0.12.0 last-run semantics the intervening check overwrote
        the baseline with the failure set and the build called it
        PRE-EXISTING; the anchor (seeded empty by the green build, and
        only ever shrinking) closes that structurally.
        """
        root = _make_project(tmp_path / "p", _GREEN)
        assert _build(root, "--quiet") == 0  # green baseline, empty anchor
        capsys.readouterr()

        _write(root, _BROKEN)
        # the intervening full-scope red check — the laundering attempt
        rc = _run(root, "check", "--mode", "strict")
        out = capsys.readouterr().out
        assert rc != 0
        assert "[NEW]" in out and "[PRE-EXISTING]" not in out

        # the build STILL refuses — check's recording did not launder
        rc, doc = _build_json(root)
        assert rc != 0
        assert doc["build_refused"]["reason"] == "NEW_CHECK_ERRORS"
        assert doc["errors"][0]["delta_label"] == "NEW"

        # fix -> green build
        _write(root, _GREEN)
        assert _build(root, "--quiet") == 0

    def test_inherited_error_survives_a_parse_error_detour(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str],
    ) -> None:
        """Attribution safety at the gate: preemption never resurrects debt.

        Brownfield inherited error (anchored) -> the agent introduces a
        transient parse error (the module's analysis is cut short, the
        inherited error unobservable) -> the parse error is fixed -> the
        inherited error must still classify PRE-EXISTING and the build
        must still be allowed.
        """
        root = _make_project(tmp_path / "p", _BROKEN)
        # first contact: the mismatch is inherited debt
        assert _run(root, "check", "--mode", "strict") != 0
        capsys.readouterr()
        assert _build(root, "--quiet") == 0  # PRE-EXISTING alone: allowed
        capsys.readouterr()

        # transient parse error preempts the module's analysis (a body
        # with an import and no def cannot parse into a nerve)
        parse_broken = _HEAD.split("    ---\n")[0] + "    ---\n    import os\n"
        _write(root, parse_broken)
        assert _run(root, "check", "--mode", "strict") != 0
        capsys.readouterr()

        # parse error fixed; the inherited mismatch is back in view
        _write(root, _BROKEN)
        rc, doc = _build_json(root)
        assert rc == 0, "inherited debt must not resurface as NEW"
        assert "build_refused" not in doc


# ---------------------------------------------------------------------------
# exemptions: the gate only fires where an artifact would be emitted
# ---------------------------------------------------------------------------


class TestGateExemptions:
    def test_check_dry_run_is_not_gated(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str],
    ) -> None:
        """``build --check`` writes no real artifacts, so it never refuses.

        It compares transpiled output against the build dir (drift). With
        a green baseline and a NEW-error edit it would trip the gate — but
        the gate is exempt for the dry-run, so it reaches the drift
        comparison instead of the refusal.
        """
        root = _make_project(tmp_path / "p", _GREEN)
        assert _build(root, "--quiet") == 0
        capsys.readouterr()
        _write(root, _BROKEN)
        rc = _build(root, "--check")
        out = capsys.readouterr().out
        assert "BUILD REFUSED" not in out
        # (rc reflects the drift comparison, not the NEW-error gate.)
        assert rc != 0 or "BUILD REFUSED" not in out

    def test_synthetic_project_is_not_gated(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str],
    ) -> None:
        """No ``[tool.s0ma]`` table -> synthetic fallback -> no baseline
        anchor -> the gate cannot attribute, so the build is not gated."""
        src = tmp_path / "loose"
        src.mkdir()
        (src / "provides_demo.s0ma").write_text(_BROKEN, encoding="utf-8")
        rc = S0maCLI().run(
            ["build", str(src), "--mode", "dev", "--output-dir", str(src)]
        )
        out = capsys.readouterr().out
        assert "BUILD REFUSED" not in out
        # a synthetic build never wrote a baseline
        assert not (src / ".s0ma").exists()
        assert rc == 0


# ---------------------------------------------------------------------------
# manifest field round-trip / back-compat
# ---------------------------------------------------------------------------


class TestManifestOverrideField:
    def test_normal_build_manifest_omits_the_key(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str],
    ) -> None:
        root = _make_project(tmp_path / "p", _GREEN)
        assert _build(root, "--quiet") == 0
        raw = json.loads(_manifest_path(root).read_text(encoding="utf-8"))
        # additive: a clean build's manifest carries no override key,
        # staying byte-identical to its pre-M2 shape.
        assert "overridden_new_errors" not in raw
        # and it still loads clean (empty default)
        assert load_manifest(root / "build").overridden_new_errors == ()
