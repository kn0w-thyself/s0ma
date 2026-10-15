"""Tests for ``scripts/check_version_refs.py`` — the ``docs-version-currency`` gate.

The stage shipped in the release-pipeline initiative and was extended twice
since, and until milestone I3 nothing had ever called either of its entry
points. ``LIVING_DOCS`` was read as a constant by
``test_docs_map_of_record.py``; ``check()`` and ``check_package_maps()``
themselves were exercised only by CI running the whole script against a
tree that happened to be green. Milestone A4 named a conditional test file
as its own acceptance criterion and it never landed. I2's negative-fixture
audit found the hole and filed it as I2-F5; this module closes it.

**Why the hole mattered more here than elsewhere.** Every invariant this
gate enforces is enforced by *finding* something. A stale version is only
reported once ``VERSION_RE`` has matched it, so a matcher narrowed to
nothing — by a regex edit, a truncated ``LIVING_DOCS``, or a run rooted in
the wrong directory — reports ``0 version reference(s)`` and passes
forever. That is not a gate that fails open under load; it is a gate that
becomes decoration silently, and the only observable symptom is a number
in a PASS line nobody reads. So the headline proof below breaks the
matcher on the real repository and requires a refusal.

Two fixture styles, for two different jobs:

* **A scratch tree** under ``tmp_path``, built from the checker's own
  ``LOCKSTEP_SITES`` and ``LIVING_DOCS`` so it cannot drift out of step
  with them, is where the red proofs live: a stale version in prose, a
  package out of lockstep, a package map missing a distribution. Faults
  are planted in the copy, never in the checkout — the same posture
  ``test_docs_application_gate.py`` takes, and for the same reason.
* **The real tree**, read-only, is where the floor and the allowlist are
  proved live: the shipped scan clears its own anti-vacuity floor with
  headroom, and every shipped ALLOWLIST entry still matches the sentence
  that justifies it.

No git, no network, no writes outside ``tmp_path``: unlike the link
checker, this gate's universe is a list of paths rather than ``git
ls-files``, so a plain directory is a complete fixture.
"""

from __future__ import annotations

import importlib.util
import re
import subprocess
import sys
from functools import cache
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from types import ModuleType

#: The monorepo root (this file: packages/s0ma-dsl/tests/<file>).
REPO_ROOT = Path(__file__).resolve().parents[3]
SCRIPT = REPO_ROOT / "scripts" / "check_version_refs.py"
CHECK_PY = REPO_ROOT / "scripts" / "check.py"

requires_checkout = pytest.mark.skipif(
    not (REPO_ROOT / "packages" / "s0ma-core" / "pyproject.toml").is_file(),
    reason="not a monorepo checkout (wheel-install context)",
)

#: The scratch tree's own lockstep version. Deliberately not the
#: repository's: a fixture that borrowed the real version would start
#: passing or failing for reasons that have nothing to do with the case
#: under test the next time somebody cuts a release.
SCRATCH_VERSION = "0.7.3"

#: A version that is not SCRATCH_VERSION, for the faults to carry.
STALE_VERSION = "0.4.0"


@cache
def _checker() -> ModuleType:
    """Import ``scripts/check_version_refs.py`` for direct calls.

    Registered in ``sys.modules`` before execution for the reason
    ``test_check_links_script.py`` gives: ``@dataclass`` resolves a
    class's module through it, and a file-path module loaded without that
    registration fails inside the decorator.
    """
    spec = importlib.util.spec_from_file_location("s0ma_check_version_refs", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _filler(version: str, count: int) -> str:
    """*count* current-version references, to clear the anti-vacuity floor."""
    return "\n".join(
        f"- wheel {index}: `s0ma_core-{version}-py3-none-any.whl`" for index in range(count)
    )


def _map_block(heading: str, names: tuple[str, ...]) -> str:
    """A package map in the shape the checker reads: a fenced block under *heading*."""
    listed = "\n".join(f"  {name}/" for name in names)
    return f"\n{heading}\n\nThe workspace ships:\n\n```\npackages/\n{listed}\n```\n"


def _tree(
    *,
    version: str = SCRATCH_VERSION,
    references: int | None = None,
    packages: tuple[str, ...] = ("s0ma-core", "s0ma-dsl", "s0ma-mcp", "s0ma-studi0"),
) -> dict[str, str]:
    """A green scratch tree: every file both entry points require.

    Built from the checker's own constants rather than a hand-written
    list, so adding a lockstep site or a living doc cannot leave this
    fixture quietly incomplete. ``references`` defaults to the floor plus
    five — comfortably above it, the way ``test_check_links_script.py``
    sizes its filler — and ``0`` produces a version-free corpus for the
    vacuity proof.
    """
    checker = _checker()
    if references is None:
        references = checker.MINIMUM_REFERENCES + 5

    files: dict[str, str] = {}
    for site in checker.LOCKSTEP_SITES:
        if site.kind == "pyproject":
            name = PurePosixPath(site.path).parent.name
            files[site.path] = f'[project]\nname = "{name}"\nversion = "{version}"\n'
        else:
            files[site.path] = f'"""Scratch package."""\n\n__version__ = "{version}"\n'

    # Every living doc exists and is version-free; the references all sit in
    # one page, so a case that changes the count changes it in one place.
    for rel in checker.LIVING_DOCS:
        files[rel] = f"# {PurePosixPath(rel).name}\n\nProse with no version in it.\n"
    if references:
        files["README.md"] += f"\n## Downloads\n\n{_filler(version, references)}\n"

    for name in packages:
        manifest = f"packages/{name}/pyproject.toml"
        files.setdefault(manifest, f'[project]\nname = "{name}"\nversion = "{version}"\n')
    for spec in checker.PACKAGE_MAPS:
        files[spec.path] += _map_block(spec.heading, packages)
    return files


def _write(tmp_path: Path, files: dict[str, str]) -> Path:
    """Materialise *files* under a fresh directory and return its root."""
    root = tmp_path / "tree"
    for rel, text in files.items():
        target = root / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8", newline="\n")
    return root


def _scratch(tmp_path: Path, **kwargs: object) -> Path:
    """The green tree, ready to have one fault planted in it."""
    return _write(tmp_path, _tree(**kwargs))  # type: ignore[arg-type]


def _check(root: Path) -> int:
    """Run the doc/lockstep half against *root* with no exemptions.

    The shipped ALLOWLIST pins sentences in the real repository, so on a
    scratch tree every entry would report itself stale — noise that would
    bury the warning the allowlist tests are actually about.
    """
    return _checker().check(root, allowlist=())


# ---------------------------------------------------------------------------
# The green baseline
# ---------------------------------------------------------------------------


def test_green_scratch_tree_passes(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """The fixture itself is sound, so every red case below means what it says."""
    root = _scratch(tmp_path)
    assert _check(root) == 0
    assert _checker().check_package_maps(root) == 0
    output = capsys.readouterr().out
    assert "version-currency: PASS" in output
    assert "package-maps: PASS" in output
    assert "VIOLATION" not in output


# ---------------------------------------------------------------------------
# Living-docs currency — the red half
# ---------------------------------------------------------------------------


def test_stale_version_in_a_living_doc_is_red_with_file_and_line(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """The gate's whole purpose, proved failing.

    A wheel filename left behind by a release is the canonical shape of
    this defect, and the report has to name the page and the line — "the
    version check failed" is a result somebody then has to reproduce by
    hand across every living document.
    """
    files = _tree()
    files["docs/getting-started.md"] += (
        f"\nInstall it with `pip install s0ma_core-{STALE_VERSION}-py3-none-any.whl`.\n"
    )
    root = _write(tmp_path, files)

    assert _check(root) == 1
    output = capsys.readouterr().out
    assert f"VIOLATION docs/getting-started.md:5: stale version {STALE_VERSION}" in output
    assert f"(current is {SCRATCH_VERSION})" in output
    # The remediation teaches all three legitimate answers, so a contributor
    # meeting this for the first time needs no other page.
    assert "reword it version-agnostically" in output
    assert "add it to ALLOWLIST" in output


def test_a_pinned_third_party_version_is_not_a_s0ma_version(tmp_path: Path) -> None:
    """``uv 0.9.21`` in an install instruction is not stale s0ma prose."""
    files = _tree()
    files["docs/getting-started.md"] += "\nRequires `uv 0.4.0` or newer.\n"
    assert _check(_write(tmp_path, files)) == 0


def test_a_missing_living_doc_is_an_error_not_a_silent_skip(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """A page that moved must fail loudly; scanning all but one proves less."""
    root = _scratch(tmp_path)
    (root / "docs" / "walkthrough.md").unlink()
    assert _check(root) == 1
    assert "ERROR living doc missing: docs/walkthrough.md" in capsys.readouterr().out


# ---------------------------------------------------------------------------
# The anti-vacuity floor (I2-F5)
# ---------------------------------------------------------------------------


def test_vacuity_floor_refuses_a_scan_that_matched_nothing(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Living docs present, version references absent: nothing was verified."""
    root = _scratch(tmp_path, references=0)
    assert _check(root) != 0
    output = capsys.readouterr().out
    assert "VACUOUS SCAN" in output
    assert "0 version reference(s)" in output
    assert "PASS" not in output


def test_vacuity_floor_refuses_a_scan_just_below_the_floor(tmp_path: Path) -> None:
    """The boundary is where an off-by-one would hide."""
    checker = _checker()
    assert _check(_scratch(tmp_path / "under", references=checker.MINIMUM_REFERENCES - 1)) != 0
    assert _check(_scratch(tmp_path / "at", references=checker.MINIMUM_REFERENCES)) == 0


@requires_checkout
def test_a_broken_matcher_cannot_pass_on_the_real_tree(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """I2-F5's exact scenario, on the real corpus.

    Before the floor, narrowing ``VERSION_RE`` to something that matches
    no living-doc prose left the whole stage green — every living
    document scanned, nothing checked, PASS printed. The gate now refuses,
    and the message names the constants a contributor should suspect.
    """
    checker = _checker()
    monkeypatch.setattr(checker, "VERSION_RE", re.compile(r"(?!x)x"))
    assert checker.check(REPO_ROOT) != 0
    output = capsys.readouterr().out
    assert "VACUOUS SCAN" in output
    assert "version-currency: PASS" not in output
    assert "VERSION_RE" in output


@requires_checkout
def test_the_real_tree_clears_the_floor_with_headroom(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """The floor is a live measurement, not an aspiration.

    Pinned the way the application floors are: the number the shipped
    corpus actually yields must sit above the constant, so the constant
    is known to be reachable and known not to be sitting on top of the
    real value where ordinary rewording would trip it.
    """
    checker = _checker()
    assert checker.check(REPO_ROOT) == 0
    found = re.search(r"(\d+) version reference\(s\)", capsys.readouterr().out)
    assert found is not None
    assert int(found.group(1)) >= checker.MINIMUM_REFERENCES


# ---------------------------------------------------------------------------
# Lockstep integrity (PRD INV-4)
# ---------------------------------------------------------------------------


def test_a_site_out_of_lockstep_is_red_and_names_the_site(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """The eight-site invariant, proved by breaking one of them."""
    files = _tree()
    files["packages/s0ma-mcp/src/s0ma_mcp/__init__.py"] = (
        f'"""Scratch package."""\n\n__version__ = "{STALE_VERSION}"\n'
    )
    root = _write(tmp_path, files)

    assert _check(root) == 1
    output = capsys.readouterr().out
    assert "VIOLATION packages/s0ma-mcp/src/s0ma_mcp/__init__.py" in output
    assert f"version {STALE_VERSION} does not match the lockstep anchor {SCRATCH_VERSION}" in output
    assert "INV-4" in output


def test_a_missing_lockstep_site_is_counted_not_skipped(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """An unreadable site is a failure; a gate that shrugs at absence proves nothing."""
    root = _scratch(tmp_path)
    (root / "packages" / "s0ma-studi0" / "pyproject.toml").unlink()
    assert _check(root) == 1
    assert "lockstep site missing (INV-4)" in capsys.readouterr().out


# ---------------------------------------------------------------------------
# The allowlist
# ---------------------------------------------------------------------------


def test_an_allowlisted_reference_is_counted_historical(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """The exemption mechanism, exercised rather than described."""
    checker = _checker()
    files = _tree()
    files["docs/walkthrough.md"] += f"\nSince {STALE_VERSION} the table is load-bearing.\n"
    root = _write(tmp_path, files)

    entry = checker.Historical(
        path="docs/walkthrough.md",
        version=STALE_VERSION,
        on_line_containing="the table is load-bearing",
        why="fixture: exercises the exemption mechanism",
    )
    assert checker.check(root, allowlist=(entry,)) == 0
    assert "1 deliberately historical" in capsys.readouterr().out


def test_an_allowlist_entry_pinned_to_a_reworded_sentence_warns(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """``on_line_containing`` is what stops an exemption outliving its reason."""
    checker = _checker()
    entry = checker.Historical(
        path="docs/walkthrough.md",
        version=STALE_VERSION,
        on_line_containing="a sentence that is no longer there",
        why="fixture: the sentence it covered was reworded",
    )
    assert checker.check(_scratch(tmp_path), allowlist=(entry,)) == 0
    assert "WARNING stale allowlist entry" in capsys.readouterr().out


@requires_checkout
def test_every_shipped_allowlist_entry_still_matches_its_sentence(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Liveness, not merely syntax.

    Milestone G2/G4 retired eighteen entries whose sentences had been
    rewritten out from under them and left the stage warning-free. Nothing
    held that state: warnings do not change the exit code, so the next
    rewording could re-accumulate them unnoticed.
    """
    assert _checker().check(REPO_ROOT) == 0
    assert "WARNING stale allowlist entry" not in capsys.readouterr().out


def test_every_shipped_allowlist_entry_names_a_living_doc() -> None:
    """An entry naming an unscanned page could never apply to anything."""
    checker = _checker()
    living = set(checker.LIVING_DOCS)
    assert [entry.path for entry in checker.ALLOWLIST if entry.path not in living] == []


# ---------------------------------------------------------------------------
# Package maps
# ---------------------------------------------------------------------------


def test_a_package_missing_from_the_maps_is_red_in_both(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """The defect this half was written for: a package the maps never learned about."""
    checker = _checker()
    files = _tree()
    files["packages/s0ma-extra/pyproject.toml"] = (
        f'[project]\nname = "s0ma-extra"\nversion = "{SCRATCH_VERSION}"\n'
    )
    root = _write(tmp_path, files)

    assert checker.check_package_maps(root) == len(checker.PACKAGE_MAPS)
    output = capsys.readouterr().out
    assert "does not name s0ma-extra" in output
    for spec in checker.PACKAGE_MAPS:
        assert f"VIOLATION {spec.path}:" in output


def test_a_map_whose_fenced_block_vanished_is_red(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """The block is read structurally; prose naming the packages is not the map."""
    files = _tree()
    files["AGENTS.md"] = (
        "# Agents\n\n## Package and dependency map\n\n"
        "We ship s0ma-core, s0ma-dsl, s0ma-mcp and s0ma-studi0.\n"
    )
    assert _checker().check_package_maps(_write(tmp_path, files)) == 1
    assert "no fenced block under '## Package and dependency map'" in capsys.readouterr().out


def test_the_package_floor_refuses_a_thin_scan(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Two packages where four are expected is a lost scan, not a verdict."""
    checker = _checker()
    files = {
        rel: text
        for rel, text in _tree(packages=("s0ma-core", "s0ma-dsl")).items()
        if not rel.startswith(("packages/s0ma-mcp/", "packages/s0ma-studi0/"))
    }
    assert checker.check_package_maps(_write(tmp_path, files)) == 1
    output = capsys.readouterr().out
    assert "found 2 distribution(s)" in output
    assert f"at least {checker.MIN_PACKAGES} expected" in output


# ---------------------------------------------------------------------------
# Wiring
# ---------------------------------------------------------------------------


@requires_checkout
def test_the_script_runs_green_end_to_end() -> None:
    """Both halves, one process, the real exit code the stage consumes."""
    result = subprocess.run(  # noqa: S603 - fixed argv, no shell
        [sys.executable, str(SCRIPT)],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "version-currency: PASS" in result.stdout
    assert "package-maps: PASS" in result.stdout


def test_the_stage_is_registered_in_the_canonical_gate() -> None:
    """The script is only a gate if ``check.py`` runs it."""
    source = CHECK_PY.read_text(encoding="utf-8")
    assert '"docs-version-currency"' in source
    assert "scripts/check_version_refs.py" in source
