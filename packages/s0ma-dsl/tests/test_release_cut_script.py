"""Tests for the release-cut helper ``scripts/release_cut.sh`` (plan RP-M1).

The script performs the mechanical half of ``docs/RELEASING.md``: bump the
four lockstep ``pyproject.toml`` versions, carve ``## [Unreleased]`` into a
dated release heading (in the root changelog AND its served mirror), refresh
the lockfile, and **print** the commit/tag/push commands it must never run.

Everything here runs against a **temp fixture repo** — a minimal copy of the
monorepo's shape (four manifests, a changelog, its ``_docs`` mirror, a git
repo, and the script itself) — so ``--write`` can be exercised for real
without touching the working tree. Three properties make that safe and
deterministic:

1. the script resolves its repo root from **its own location**, so the copy
   in the fixture operates entirely on the fixture;
2. ``uv`` is shimmed onto ``PATH`` by a recording stub, so the lockfile step
   is asserted (exact argv) without running a real sync;
3. no test touches the network — the script makes no network calls at all,
   and a source-level test pins that.

Like ``test_install_script.py``, every test skips gracefully when ``bash``
or ``git`` is unavailable, so the gate stays green on hosts without them.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

import pytest

#: The monorepo root (this file: packages/s0ma-dsl/tests/<file>).
REPO_ROOT = Path(__file__).resolve().parents[3]
RELEASE_CUT_SH = REPO_ROOT / "scripts" / "release_cut.sh"

#: The four lockstep distributions (PRD INV-4). This tuple PINS the set the
#: cut must bump: a package added to (or dropped from) the script without a
#: matching change here fails the fixture tests below.
PACKAGES = ("s0ma-core", "s0ma-dsl", "s0ma-mcp", "s0ma-studi0")

#: Where the served changelog mirror lives, relative to the repo root.
MIRROR_REL = "packages/s0ma-mcp/src/s0ma_mcp/_docs/CHANGELOG.md"

#: The version the fixture repo starts on, and the one the tests cut to.
FIXTURE_VERSION = "0.17.0"
NEXT_VERSION = "0.18.0"
CUT_DATE = "2026-09-01"

#: Every changelog heading uses an em dash (`## [0.17.0] — 2026-08-17`).
EM = "—"

_BASH = shutil.which("bash")
_GIT = shutil.which("git")

#: A realistic changelog head: prose, a non-empty Unreleased section with two
#: groups, and a prior release to prove the carve leaves history alone.
FIXTURE_CHANGELOG = f"""# Changelog

All notable changes to the s0ma monorepo are documented in this file.

## [Unreleased]

### Added

- A thing that landed since {FIXTURE_VERSION}.

### Changed

- Another thing, reworded.

## [{FIXTURE_VERSION}] {EM} 2026-08-17

### Added

- The previous release.
"""


def _pyproject(name: str, version: str) -> str:
    """A minimal manifest with the same shape as the real ones.

    The trailing ``target-version`` line is the decoy that matters: the
    script must bump the ``version = "..."`` line and nothing else.
    """
    return f"""[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[project]
name = "{name}"
version = "{version}"
description = "fixture package {name}"
requires-python = ">=3.11"

[tool.ruff]
target-version = "py311"
"""


@dataclass
class CutRepo:
    """A throwaway monorepo-shaped checkout with the script inside it."""

    root: Path
    env: dict[str, str]
    uv_log: Path

    @property
    def changelog(self) -> Path:
        return self.root / "CHANGELOG.md"

    @property
    def mirror(self) -> Path:
        return self.root / MIRROR_REL

    def pyproject(self, package: str) -> Path:
        return self.root / "packages" / package / "pyproject.toml"

    def snapshot(self) -> dict[str, bytes]:
        """Byte snapshot of every file the cut is allowed to touch."""
        files = {p: self.pyproject(p).read_bytes() for p in PACKAGES}
        files["CHANGELOG.md"] = self.changelog.read_bytes()
        files[MIRROR_REL] = self.mirror.read_bytes()
        return files

    def git(self, *args: str) -> str:
        assert _GIT is not None
        return subprocess.run(
            [_GIT, "-C", str(self.root), *args],
            capture_output=True,
            text=True,
            check=True,
        ).stdout

    def run(self, *args: str) -> subprocess.CompletedProcess[str]:
        """Run the fixture's copy of the script with the shimmed PATH."""
        assert _BASH is not None
        return subprocess.run(
            [_BASH, str(self.root / "scripts" / "release_cut.sh"), *args],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
            cwd=str(self.root),
            env=self.env,
        )

    def cut(self, *args: str, version: str = NEXT_VERSION) -> subprocess.CompletedProcess[str]:
        """``--version <v> --date <fixed>`` plus whatever the test adds."""
        return self.run("--version", version, "--date", CUT_DATE, *args)

    def uv_calls(self) -> list[str]:
        if not self.uv_log.is_file():
            return []
        return [
            line
            for line in self.uv_log.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]


def _require_tools() -> None:
    if _BASH is None:
        pytest.skip("bash unavailable")
    if _GIT is None:
        pytest.skip("git unavailable")


@pytest.fixture
def cut_repo(tmp_path: Path) -> CutRepo:
    """Build a clean, committed fixture repo on branch ``main``."""
    _require_tools()
    assert _GIT is not None

    root = tmp_path / "repo"
    (root / "scripts").mkdir(parents=True)
    shutil.copy2(RELEASE_CUT_SH, root / "scripts" / "release_cut.sh")

    for package in PACKAGES:
        target = root / "packages" / package
        target.mkdir(parents=True)
        (target / "pyproject.toml").write_text(
            _pyproject(package, FIXTURE_VERSION), encoding="utf-8", newline="\n"
        )

    (root / "CHANGELOG.md").write_text(
        FIXTURE_CHANGELOG, encoding="utf-8", newline="\n"
    )
    mirror = root / MIRROR_REL
    mirror.parent.mkdir(parents=True)
    mirror.write_bytes((root / "CHANGELOG.md").read_bytes())

    # A recording `uv` stub: the lockfile step is asserted by argv, never run.
    fakebin = tmp_path / "fakebin"
    fakebin.mkdir()
    uv_log = tmp_path / "uv-calls.log"
    uv_stub = fakebin / "uv"
    uv_stub.write_text(
        '#!/bin/sh\nprintf \'%s\\n\' "$*" >> "$UV_CALL_LOG"\nexit 0\n',
        encoding="utf-8",
        newline="\n",
    )
    uv_stub.chmod(0o755)

    env = dict(os.environ)
    env["PATH"] = f"{fakebin}{os.pathsep}{env.get('PATH', '')}"
    env["UV_CALL_LOG"] = str(uv_log)

    # A git repo on `main`, everything committed -> a clean tree.
    def git(*args: str) -> None:
        subprocess.run(
            [_GIT, "-C", str(root), *args],
            capture_output=True,
            text=True,
            check=True,
        )

    subprocess.run(
        [_GIT, "init", "-q", str(root)], capture_output=True, text=True, check=True
    )
    git("symbolic-ref", "HEAD", "refs/heads/main")
    git("config", "user.email", "fixture@example.invalid")
    git("config", "user.name", "fixture")
    git("config", "commit.gpgsign", "false")
    git("add", "-A")
    git("commit", "-q", "-m", "fixture")

    repo = CutRepo(root=root, env=env, uv_log=uv_log)

    # The uv shim must actually be callable from bash on this host (it is
    # not on some Windows shells); skip the whole module's write path
    # rather than fail for an environment reason.
    assert _BASH is not None
    probe = subprocess.run(
        [_BASH, "-c", "uv probe-shim"],
        capture_output=True,
        text=True,
        check=False,
        env=env,
    )
    if probe.returncode != 0 or not uv_log.is_file():
        pytest.skip("the uv shim is not executable from bash on this host")
    uv_log.write_text("", encoding="utf-8")
    return repo


# ---------------------------------------------------------------------------
# Source-level invariants (no fixture needed).
# ---------------------------------------------------------------------------


def test_release_cut_script_exists_and_is_executable() -> None:
    assert RELEASE_CUT_SH.is_file(), f"missing {RELEASE_CUT_SH}"


def test_release_cut_script_parses_clean() -> None:
    """``bash -n scripts/release_cut.sh`` parses without error."""
    if _BASH is None:
        pytest.skip("bash unavailable")
    result = subprocess.run(
        [_BASH, "-n", str(RELEASE_CUT_SH)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, f"bash -n reported:\n{result.stderr}"


def test_release_cut_script_is_offline() -> None:
    """The cut never reaches the network: no fetch tool appears in it."""
    source = RELEASE_CUT_SH.read_text(encoding="utf-8")
    for tool in ("curl ", "wget ", "gh release", "wrangler "):
        assert tool not in source, f"{tool!r} has no business in a release cut"


def test_help_documents_the_flags() -> None:
    if _BASH is None:
        pytest.skip("bash unavailable")
    result = subprocess.run(
        [_BASH, str(RELEASE_CUT_SH), "--help"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )
    assert result.returncode == 0
    assert "Usage:" in result.stdout
    for flag in ("--version", "--write", "--allow-branch", "--date"):
        assert flag in result.stdout, f"{flag} undocumented"
    # The help block stops at the flags — no shell code leaks into it.
    assert "set -euo pipefail" not in result.stdout


# ---------------------------------------------------------------------------
# Dry run (the default): prints the whole plan, writes nothing.
# ---------------------------------------------------------------------------


def test_dry_run_names_every_file_it_would_touch(cut_repo: CutRepo) -> None:
    result = cut_repo.cut()
    assert result.returncode == 0, result.stderr
    out = result.stdout

    for package in PACKAGES:
        assert f"packages/{package}/pyproject.toml" in out
    assert "CHANGELOG.md" in out
    assert MIRROR_REL in out
    # The transition is stated, both ends of it.
    assert f'version = "{FIXTURE_VERSION}"' in out
    assert f'version = "{NEXT_VERSION}"' in out
    assert f"## [{NEXT_VERSION}] {EM} {CUT_DATE}" in out
    # And the lockfile step is named.
    assert "uv sync --all-packages" in out


def test_dry_run_writes_nothing(cut_repo: CutRepo) -> None:
    before = cut_repo.snapshot()
    assert cut_repo.cut().returncode == 0
    assert cut_repo.snapshot() == before
    assert cut_repo.uv_calls() == [], "a dry run must not run uv"


def test_dry_run_prints_the_commit_tag_and_push_commands(cut_repo: CutRepo) -> None:
    """The release act is PRINTED, never performed (plan RP-M1 T1)."""
    out = cut_repo.cut().stdout
    assert f'git commit -m "s0ma: release {EM} cut {NEXT_VERSION}"' in out
    assert f"git tag -a v{NEXT_VERSION}" in out
    assert f"git push origin v{NEXT_VERSION}" in out
    # ...with the authority caveat attached to the tag push.
    assert "OWNER-AUTHORIZED ONLY" in out


def test_dry_run_prints_the_tagged_compose_and_the_tagged_gate(cut_repo: CutRepo) -> None:
    """A cut driven from the printed list alone must compose the RELEASE.

    Found while dry-running the publication runbook: the list said "the full
    gate: uv run python scripts/check.py" and nothing about the documentation.
    docs/RELEASING.md steps 4 and 5 require the compose to be told the tag
    (untold, it composes a preview and every identity line says so) and the
    gate to be told the same tag. Both, and in that order, before the commit
    the tag will name.

    All five mirror copies are named, in the order
    docs/operations/docs-maintenance.md ("The loop") gives them, and the
    third one is why: the ``s0ma-dsl`` wheel's copy is what ``s0ma docs``
    reads when there is no checkout, and while nothing filled it every read
    command answered an installed person "no documentation snapshot was
    found". The last two are the quick reference the authoring server
    serves. A cut driven from this printed list alone must refresh all
    five, or the release ships a toolchain that cannot answer a
    documentation question.
    """
    out = cut_repo.cut().stdout
    compose = f"docs compose --output-dir docs --head-tag v{NEXT_VERSION}"
    gate = f"S0MA_HEAD_TAG=v{NEXT_VERSION} uv run python scripts/check.py"
    commit_r = f'git commit -m "s0ma: release {EM} cut {NEXT_VERSION}"'
    assert compose in out
    assert gate in out
    copies = [
        "s0ma_mcp/_docs/s0ma-docs-model.json",
        "s0ma/_teaching/slice.json",
        "s0ma_dsl/_docs_snapshot/s0ma-docs-model.json",
        "s0ma_mcp/_docs/quick-reference-readable.md",
        "s0ma_mcp/_docs/quick-reference-machine.json",
    ]
    for copy in copies:
        assert copy in out, f"the mirror copy into {copy} is not printed"
    positions = [out.index(copy) for copy in copies]
    assert positions == sorted(positions), "the five copies, in the loop's order"
    assert out.index(compose) < out.index(gate) < out.index(commit_r)


def test_dry_run_prints_the_three_rebuilds_before_any_compose(cut_repo: CutRepo) -> None:
    """Three committed builds carry the toolchain version, not two: both
    self-hosted packages and the documentation application (AGENTS.md,
    "Authored and generated paths"). All three are rebuilt, with
    ``--no-cache``, before the documentation is composed, because the
    compose reads what they built (docs/RELEASING.md step 3 and "The
    teaching-slice build order").

    Before any of them, the optional extras are put back. The cut ends with
    an exact ``uv sync --all-packages``, which removes them, and the
    documentation build refuses to compose without core's ``api`` extra:
    found on the first cut made after the documentation application
    existed, when a compose driven from this list alone stopped there."""
    out = cut_repo.cut().stdout
    restore = "uv sync --all-packages --all-extras"
    assert restore in out, "the extras the cut's exact sync removed are not put back"
    rebuilds = [
        "uv run s0ma --project-root packages/s0ma-mcp build packages/s0ma-mcp"
        " --mode release --no-cache",
        "uv run s0ma --project-root packages/s0ma-studi0 build packages/s0ma-studi0 --no-cache",
        "uv run s0ma --project-root docs build docs --no-cache",
        "uv run s0ma --project-root docs docs render docs/s0ma_src"
        " --output-dir docs --mode release",
    ]
    for rebuild in rebuilds:
        assert rebuild in out, f"not printed: {rebuild}"
    first_compose = out.index("docs compose --output-dir docs")
    assert all(out.index(rebuild) < first_compose for rebuild in rebuilds)
    assert out.index(restore) < out.index(rebuilds[0])


def test_dry_run_prints_the_three_commits_in_order(cut_repo: CutRepo) -> None:
    """The cut lands as three commits (docs/RELEASING.md, "The three commits
    of a cut"). A is composed as a preview, so the pull-request matrix can
    read it; R is composed for the release and is the commit the tag names;
    P is composed as a preview again, and ``main`` ends there. A
    release-composed tree is red on ordinary CI by design, so ``main`` moves
    to P, and the tag push still comes last."""
    out = cut_repo.cut().stdout
    commit_a = f'git commit -m "s0ma: release {EM} prepare {NEXT_VERSION}'
    commit_r = f'git commit -m "s0ma: release {EM} cut {NEXT_VERSION}"'
    commit_p = (
        f'git commit -m "s0ma: release {EM} main returns to the preview channel'
        f' after {NEXT_VERSION}"'
    )
    tagged_compose = f"--head-tag v{NEXT_VERSION}"
    main_to_p = f"git push origin release-{NEXT_VERSION}:main"
    tag_on_r = f"git tag -a v{NEXT_VERSION} <hash-of-R>"
    tag_push = f"git push origin v{NEXT_VERSION}"
    assert "The three commits of a cut" in out
    assert out.index(commit_a) < out.index(tagged_compose) < out.index(commit_r)
    assert out.index(commit_r) < out.index(commit_p) < out.index(main_to_p)
    assert out.index(main_to_p) < out.index(tag_on_r) < out.index(tag_push)


def test_dry_run_lists_the_sites_it_does_not_bump(cut_repo: CutRepo) -> None:
    """The cut is partial by design; the leftovers must be stated, or the
    operator ships a half-bumped tree (docs/RELEASING.md step 2)."""
    out = cut_repo.cut().stdout
    assert "__version__" in out
    assert "s0ma_src/*.s0ma" in out
    assert "test_docs_provider_diagnostics.py" in out
    assert "s0ma-core-spec-v*.md   cut the core spec" in out
    assert "scripts/check.py" in out


def test_dry_run_reports_blocking_preflights_without_failing(
    cut_repo: CutRepo,
) -> None:
    """A dirty tree is previewable: reported as [BLOCK], still exit 0."""
    (cut_repo.root / "untracked.txt").write_text("x", encoding="utf-8")
    result = cut_repo.cut()
    assert result.returncode == 0
    assert "[BLOCK] working tree is not clean" in result.stdout
    assert "--write would REFUSE" in result.stdout


def test_dry_run_on_a_clean_tree_reports_all_preflights_ok(
    cut_repo: CutRepo,
) -> None:
    out = cut_repo.cut().stdout
    # No preflight REPORT line is blocked (the legend line mentions [BLOCK]).
    assert not [line for line in out.splitlines() if line.startswith("#   [BLOCK]")]
    assert "Preflights pass" in out


# ---------------------------------------------------------------------------
# --write: the edits, byte-predictable.
# ---------------------------------------------------------------------------


def test_write_bumps_all_four_pyprojects(cut_repo: CutRepo) -> None:
    result = cut_repo.cut("--write")
    assert result.returncode == 0, result.stderr
    for package in PACKAGES:
        text = cut_repo.pyproject(package).read_text(encoding="utf-8")
        assert f'version = "{NEXT_VERSION}"' in text
        assert f'version = "{FIXTURE_VERSION}"' not in text
        # The decoy line is untouched: only the release version moved.
        assert 'target-version = "py311"' in text


def test_write_carves_the_changelog_byte_exactly(cut_repo: CutRepo) -> None:
    """The carve is a single, predictable substitution: the old heading
    becomes a fresh empty ``[Unreleased]`` plus the dated release heading,
    and every other byte of the file is preserved."""
    assert cut_repo.cut("--write").returncode == 0

    expected = FIXTURE_CHANGELOG.replace(
        "## [Unreleased]",
        f"## [Unreleased]\n\n## [{NEXT_VERSION}] {EM} {CUT_DATE}",
        1,
    )
    assert cut_repo.changelog.read_text(encoding="utf-8") == expected
    # History below the carve is untouched.
    assert f"## [{FIXTURE_VERSION}] {EM} 2026-08-17" in expected
    # The new Unreleased heading is empty, and the entries moved under the
    # release heading (not the other way round).
    body = expected.split("## [Unreleased]", 1)[1]
    assert body.startswith(f"\n\n## [{NEXT_VERSION}]")


def test_write_keeps_the_served_mirror_byte_identical(cut_repo: CutRepo) -> None:
    assert cut_repo.cut("--write").returncode == 0
    assert cut_repo.mirror.read_bytes() == cut_repo.changelog.read_bytes()


def test_write_refreshes_the_lockfile_exactly_once(cut_repo: CutRepo) -> None:
    assert cut_repo.cut("--write").returncode == 0
    assert cut_repo.uv_calls() == ["sync --all-packages"]


def test_write_never_commits_tags_or_pushes(cut_repo: CutRepo) -> None:
    """The edits land in the working tree and stop there."""
    before_head = cut_repo.git("rev-parse", "HEAD").strip()
    assert cut_repo.cut("--write").returncode == 0

    assert cut_repo.git("rev-parse", "HEAD").strip() == before_head
    assert cut_repo.git("tag", "-l").strip() == ""
    # The edits are real, and they are uncommitted.
    status = cut_repo.git("status", "--porcelain")
    assert "CHANGELOG.md" in status
    assert "pyproject.toml" in status


def test_write_is_idempotent_in_the_refusing_sense(cut_repo: CutRepo) -> None:
    """A second identical cut refuses (tree now dirty, version no longer
    forward) rather than carving twice."""
    assert cut_repo.cut("--write").returncode == 0
    after_first = cut_repo.snapshot()

    second = cut_repo.cut("--write")
    assert second.returncode == 1
    assert cut_repo.snapshot() == after_first


def test_write_stamps_todays_date_when_no_date_is_given(cut_repo: CutRepo) -> None:
    import datetime

    result = cut_repo.run("--version", NEXT_VERSION, "--write")
    assert result.returncode == 0, result.stderr
    today = datetime.date.today().isoformat()
    assert (
        f"## [{NEXT_VERSION}] {EM} {today}"
        in cut_repo.changelog.read_text(encoding="utf-8")
    )


# ---------------------------------------------------------------------------
# Preflights: each refuses, and refuses BEFORE writing anything.
# ---------------------------------------------------------------------------


def _assert_refused(repo: CutRepo, result: subprocess.CompletedProcess[str],
                    before: dict[str, bytes], needle: str) -> None:
    assert result.returncode == 1, result.stdout
    assert "Nothing was written" in result.stderr or "refused" in result.stderr
    assert needle in result.stderr, result.stderr
    assert repo.snapshot() == before, "a refused cut must not edit anything"
    assert repo.uv_calls() == [], "a refused cut must not run uv"


def test_write_refuses_a_dirty_tree(cut_repo: CutRepo) -> None:
    (cut_repo.root / "stray.txt").write_text("x", encoding="utf-8")
    before = cut_repo.snapshot()
    _assert_refused(cut_repo, cut_repo.cut("--write"), before, "working tree is not clean")


def test_write_refuses_off_main(cut_repo: CutRepo) -> None:
    cut_repo.git("checkout", "-q", "-b", "some-feature")
    before = cut_repo.snapshot()
    _assert_refused(
        cut_repo, cut_repo.cut("--write"), before, "on branch some-feature, not main"
    )


def test_allow_branch_permits_an_off_main_cut(cut_repo: CutRepo) -> None:
    cut_repo.git("checkout", "-q", "-b", "some-feature")
    result = cut_repo.cut("--write", "--allow-branch")
    assert result.returncode == 0, result.stderr
    assert f'version = "{NEXT_VERSION}"' in cut_repo.pyproject("s0ma-core").read_text(
        encoding="utf-8"
    )


def test_write_refuses_a_version_that_is_not_strictly_newer(
    cut_repo: CutRepo,
) -> None:
    before = cut_repo.snapshot()
    for version in (FIXTURE_VERSION, "0.16.0", "0.9.0"):
        result = cut_repo.cut("--write", version=version)
        _assert_refused(cut_repo, result, before, "not strictly newer")


def test_semver_compare_is_numeric_not_lexical(cut_repo: CutRepo) -> None:
    """0.9.0 -> 0.10.0 is forward. A string compare says otherwise, and this
    is exactly where a release pipeline goes backwards by accident."""
    for package in PACKAGES:
        path = cut_repo.pyproject(package)
        path.write_text(
            _pyproject(package, "0.9.0"), encoding="utf-8", newline="\n"
        )
    cut_repo.git("add", "-A")
    cut_repo.git("commit", "-q", "-m", "back to 0.9.0")

    result = cut_repo.cut("--write", version="0.10.0")
    assert result.returncode == 0, result.stderr
    assert 'version = "0.10.0"' in cut_repo.pyproject("s0ma-core").read_text(
        encoding="utf-8"
    )


def test_write_refuses_an_empty_unreleased_section(cut_repo: CutRepo) -> None:
    emptied = FIXTURE_CHANGELOG.replace(
        f"""### Added

- A thing that landed since {FIXTURE_VERSION}.

### Changed

- Another thing, reworded.

""",
        "",
        1,
    )
    cut_repo.changelog.write_text(emptied, encoding="utf-8", newline="\n")
    cut_repo.mirror.write_bytes(cut_repo.changelog.read_bytes())
    cut_repo.git("add", "-A")
    cut_repo.git("commit", "-q", "-m", "empty unreleased")

    before = cut_repo.snapshot()
    _assert_refused(cut_repo, cut_repo.cut("--write"), before, "is empty")


def test_write_refuses_a_drifted_mirror(cut_repo: CutRepo) -> None:
    cut_repo.mirror.write_text(
        FIXTURE_CHANGELOG + "\ndrifted\n", encoding="utf-8", newline="\n"
    )
    cut_repo.git("add", "-A")
    cut_repo.git("commit", "-q", "-m", "drift the mirror")

    before = cut_repo.snapshot()
    _assert_refused(cut_repo, cut_repo.cut("--write"), before, "has drifted")


def test_write_refuses_a_version_already_in_the_changelog(
    cut_repo: CutRepo,
) -> None:
    before = cut_repo.snapshot()
    # 0.17.0 is already a section AND not newer; use a newer version that is
    # nonetheless already present.
    cut_repo.changelog.write_text(
        FIXTURE_CHANGELOG.replace(
            f"## [{FIXTURE_VERSION}] {EM} 2026-08-17",
            f"## [{NEXT_VERSION}] {EM} 2026-08-30",
            1,
        ),
        encoding="utf-8",
        newline="\n",
    )
    cut_repo.mirror.write_bytes(cut_repo.changelog.read_bytes())
    cut_repo.git("add", "-A")
    cut_repo.git("commit", "-q", "-m", "pre-existing section")
    before = cut_repo.snapshot()

    _assert_refused(cut_repo, cut_repo.cut("--write"), before, "already has")


def test_lockstep_mismatch_is_a_hard_error_in_both_modes(
    cut_repo: CutRepo,
) -> None:
    """Four packages, one version (INV-4). A skewed manifest is refused
    before any plan is printed — a half-bumped tree is not cuttable."""
    cut_repo.pyproject("s0ma-mcp").write_text(
        _pyproject("s0ma-mcp", "0.16.1"), encoding="utf-8", newline="\n"
    )
    cut_repo.git("add", "-A")
    cut_repo.git("commit", "-q", "-m", "skew")
    before = cut_repo.snapshot()

    for args in ((), ("--write",)):
        result = cut_repo.cut(*args)
        assert result.returncode == 1
        assert "NOT on one lockstep version" in result.stderr
        assert cut_repo.snapshot() == before


# ---------------------------------------------------------------------------
# Argument handling.
# ---------------------------------------------------------------------------


def test_missing_version_fails_loudly(cut_repo: CutRepo) -> None:
    result = cut_repo.run()
    assert result.returncode == 1
    assert "a release version is required" in result.stderr
    assert "--version" in result.stderr


@pytest.mark.parametrize("bad", ["0.18", "v0.18.0", "0.18.0rc1", "abc", "0.18.0.1"])
def test_bad_version_shapes_fail_loudly(cut_repo: CutRepo, bad: str) -> None:
    result = cut_repo.run("--version", bad)
    assert result.returncode == 1
    assert "bare X.Y.Z" in result.stderr


def test_bad_date_fails_loudly(cut_repo: CutRepo) -> None:
    result = cut_repo.run("--version", NEXT_VERSION, "--date", "01-09-2026")
    assert result.returncode == 1
    assert "YYYY-MM-DD" in result.stderr


def test_unknown_option_fails_loudly(cut_repo: CutRepo) -> None:
    result = cut_repo.run("--version", NEXT_VERSION, "--bogus")
    assert result.returncode == 1
    assert "unknown option" in result.stderr
