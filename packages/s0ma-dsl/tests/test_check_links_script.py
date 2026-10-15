"""Tests for ``scripts/check_links.py`` — the docs link + anchor guard.

The gate answers a question nothing in this repo asked before: *does every
link in the shipped prose still land somewhere?* The August 2026 docs audit
(§6.2 item 4) found no markdown lint, no relative-link validation and no
git hook anywhere in the tree, with dead anchors and orphaned pointers as
the standing proof.

Two halves, tested two ways:

* The **slugger** is the risky half. GitHub's heading-anchor rules are
  unwritten in this repo and easy to get subtly wrong — an em dash leaves
  *two* hyphens behind, ``-`` and ``_`` survive while ``.`` and ``[`` do
  not, and repeated headings take ``-1``/``-2`` suffixes in document order.
  These are exercised as unit cases against the imported module, with the
  real repository anchors (``#6-owner-runbook--provisioning-a-tester``) as
  the calibration.
* The **gate** is exercised end to end, as a subprocess against throwaway
  git repositories built under ``tmp_path``. Fixtures are real repos
  because the checker's universe is ``git ls-files`` on purpose: a file
  present only in the working tree is a file every other clone 404s on.

Every fixture carries enough resolving links to clear the checker's
anti-vacuity floor, because a gate that passes on nothing is the failure
mode the floor exists to catch — and the floor gets its own test with an
empty scan universe.

These tests are network-free by construction (the checker never contacts
anything; one fixture plants an external link at an unroutable host to
prove it is skipped rather than fetched), and skip gracefully where ``git``
is unavailable, following ``test_release_cut_script.py``.
"""

from __future__ import annotations

import importlib.util
import shutil
import subprocess
import sys
from functools import cache
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from types import ModuleType

#: The monorepo root (this file: packages/s0ma-dsl/tests/<file>).
REPO_ROOT = Path(__file__).resolve().parents[3]
CHECK_LINKS = REPO_ROOT / "scripts" / "check_links.py"
CHECK_PY = REPO_ROOT / "scripts" / "check.py"

_GIT = shutil.which("git")

#: Comfortably above the checker's MINIMUM_LINKS floor, so a fixture's
#: verdict is about the link under test and never about vacuity.
FILLER_LINKS = 60


@cache
def _checker() -> ModuleType:
    """Import ``scripts/check_links.py`` for the unit-level assertions.

    Registered in ``sys.modules`` before execution because ``@dataclass``
    resolves a class's module through it; loading a file-path module
    without that registration fails inside the decorator.
    """
    spec = importlib.util.spec_from_file_location("s0ma_check_links", CHECK_LINKS)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _require_git() -> str:
    if _GIT is None:
        pytest.skip("git unavailable")
    return _GIT


def _filler(count: int = FILLER_LINKS) -> str:
    """*count* links that resolve, to clear the anti-vacuity floor."""
    return "\n".join(f"- [entry {index}](notes.md)" for index in range(count))


def _baseline() -> dict[str, str]:
    """A minimal green documentation tree: one target, one linking page."""
    return {
        "docs/notes.md": "# Notes\n\n## Deep section\n\nBody.\n",
        "docs/index.md": f"# Index\n\n{_filler()}\n",
    }


def _make_repo(tmp_path: Path, files: dict[str, str]) -> Path:
    """A throwaway git repository whose index holds exactly *files*."""
    git = _require_git()
    root = tmp_path / "repo"
    root.mkdir()
    for rel, text in files.items():
        target = root / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8", newline="\n")
    subprocess.run([git, "init", "-q"], cwd=root, check=True)
    subprocess.run([git, "add", "-A"], cwd=root, check=True)
    return root


def _run(root: Path) -> subprocess.CompletedProcess[str]:
    """Run the checker against *root* exactly as the stage runs it."""
    return subprocess.run(
        [sys.executable, str(CHECK_LINKS), str(root)],
        cwd=root,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )


# ---------------------------------------------------------------------------
# The slugger: GitHub's heading-anchor rules
# ---------------------------------------------------------------------------


def test_slugify_lowercases_and_hyphenates_spaces() -> None:
    assert _checker().slugify("What You Do") == "what-you-do"


def test_slugify_drops_punctuation_but_keeps_hyphen_and_underscore() -> None:
    """``-`` and ``_`` are legal slug characters; the rest of ASCII punctuation is not."""
    slugify = _checker().slugify
    assert slugify("Action 3 — Rename mismatched-stem modules") == (
        "action-3--rename-mismatched-stem-modules"
    )
    assert slugify("`module_path` on Constant / Type Registration (0.3.0)") == (
        "module_path-on-constant--type-registration-030"
    )
    assert slugify("Why? (really!)") == "why-really"


def test_slugify_em_dash_leaves_a_doubled_hyphen() -> None:
    """The calibration case: a real anchor this repository links to.

    ``docs/RELEASING.md`` points at ``#6-owner-runbook--provisioning-a-tester``.
    The em dash is deleted, its two flanking spaces are not, and the pair
    becomes ``--``. Get this wrong and every dash-bearing heading in the
    tree reports a false miss.
    """
    assert _checker().slugify("6. Owner runbook — provisioning a tester") == (
        "6-owner-runbook--provisioning-a-tester"
    )


def test_slugify_strips_inline_markup_to_rendered_text() -> None:
    """Anchors are built from what a reader sees, not from the markup."""
    slugify = _checker().slugify
    assert slugify("**Bold** heading") == "bold-heading"
    assert slugify("`s0ma build` and friends") == "s0ma-build-and-friends"
    assert slugify("[the walkthrough](../docs/walkthrough.md) explained") == (
        "the-walkthrough-explained"
    )


def test_document_anchors_disambiguates_duplicate_headings() -> None:
    """Repeated titles take ``-1``/``-2`` suffixes in document order."""
    text = "# Notes\n\n## Notes\n\n## Notes\n\n## Other\n"
    assert _checker().document_anchors(text) == ["notes", "notes-1", "notes-2", "other"]


def test_document_anchors_ignores_headings_inside_code_fences() -> None:
    """A shell comment is not a heading — and an invented heading would
    shift every later duplicate suffix, turning correct links red."""
    text = "# Real\n\n```bash\n# not a heading\n## nor this\n```\n\n## Real\n"
    assert _checker().document_anchors(text) == ["real", "real-1"]


def test_document_links_ignores_fences_and_code_spans() -> None:
    """A link that renders as literal text is not a link.

    Both forms occur in the real docs: Python subscript-and-call syntax in
    a fenced sample (``registry["greet"]("Alice")``) parses as markdown
    link syntax, and would be six false misses in the patterns guide alone.
    """
    text = (
        "# Doc\n\n"
        "[live](notes.md)\n\n"
        "```python\n"
        'registry["greet"]("Alice")\n'
        "```\n\n"
        'Inline `registry["get"]("/api/data")` sample.\n'
    )
    links = _checker().document_links("docs/doc.md", text)
    assert [(link.lineno, link.target) for link in links] == [(3, "notes.md")]


# ---------------------------------------------------------------------------
# The gate, end to end
# ---------------------------------------------------------------------------


def test_green_fixture_passes(tmp_path: Path) -> None:
    files = _baseline()
    files["docs/index.md"] += (
        "\n[deep](notes.md#deep-section)\n"
        "[same file](#index)\n"
        "[a package directory](../packages/s0ma-core)\n"
        "[across the tree](../packages/s0ma-core/README.md#core)\n"
    )
    files["packages/s0ma-core/README.md"] = "# Core\n"
    result = _run(_make_repo(tmp_path, files))
    assert result.returncode == 0, result.stdout
    assert "docs-links: PASS" in result.stdout
    assert "VIOLATION" not in result.stdout


def test_broken_relative_link_is_red_with_file_and_line(tmp_path: Path) -> None:
    files = _baseline()
    files["docs/guide.md"] = "# Guide\n\nSee the [old plan](moved-away.md) for context.\n"
    result = _run(_make_repo(tmp_path, files))
    assert result.returncode == 1
    assert "VIOLATION docs/guide.md:3:" in result.stdout
    assert "docs/moved-away.md is not tracked" in result.stdout
    assert "link: moved-away.md" in result.stdout


def test_dead_anchor_is_red_with_file_line_and_nearest_heading(tmp_path: Path) -> None:
    files = _baseline()
    files["docs/guide.md"] = "# Guide\n\nJump to [the section](notes.md#deep-sekshun).\n"
    result = _run(_make_repo(tmp_path, files))
    assert result.returncode == 1
    assert "VIOLATION docs/guide.md:3:" in result.stdout
    assert "anchor #deep-sekshun names no heading in docs/notes.md" in result.stdout
    # The remediation names the real anchor, so the fix needs no hunting.
    assert "#deep-section" in result.stdout


def test_untracked_file_does_not_rescue_a_link(tmp_path: Path) -> None:
    """Present in the working tree, absent from the index: still a 404 for
    everyone else, which is the only reader that matters."""
    root = _make_repo(tmp_path, {**_baseline(), "docs/guide.md": "# G\n\n[x](stray.md)\n"})
    (root / "docs" / "stray.md").write_text("# Stray\n", encoding="utf-8", newline="\n")
    result = _run(root)
    assert result.returncode == 1
    assert "docs/stray.md is not tracked" in result.stdout


def test_parent_traversal_out_of_the_repository_is_red(tmp_path: Path) -> None:
    files = _baseline()
    files["docs/guide.md"] = "# Guide\n\n[outside](../../elsewhere/notes.md)\n"
    result = _run(_make_repo(tmp_path, files))
    assert result.returncode == 1
    assert "escapes the repository root" in result.stdout


def test_root_relative_link_is_read_the_way_github_reads_it(tmp_path: Path) -> None:
    """A leading ``/`` means repo root, not filesystem root — which is how
    an absolute developer-machine path slips into prose and looks fine."""
    files = _baseline()
    files["docs/guide.md"] = "# Guide\n\n[home](/Users/someone/notes.md)\n"
    files["docs/ok.md"] = "# OK\n\n[index](/docs/index.md)\n"
    result = _run(_make_repo(tmp_path, files))
    assert result.returncode == 1
    assert "Users/someone/notes.md is not tracked" in result.stdout
    assert "docs/ok.md" not in result.stdout


def test_external_links_are_skipped_without_contacting_anything(tmp_path: Path) -> None:
    """No network, ever: an unroutable host and a mailto both pass untouched."""
    files = _baseline()
    files["docs/guide.md"] = (
        "# Guide\n\n"
        "[docs](https://192.0.2.1/never-fetched)\n"
        "[mail](mailto:support@kn0wthyself.ai)\n"
        "[served](s0ma://guide/patterns)\n"
    )
    result = _run(_make_repo(tmp_path, files))
    assert result.returncode == 0, result.stdout
    assert "3 external link(s) skipped" in result.stdout


def test_excluded_directories_are_not_scanned(tmp_path: Path) -> None:
    """Mirrors are byte-gated at their source; history and plans are frozen."""
    files = _baseline()
    broken = "# Doc\n\n[gone](nowhere-at-all.md)\n"
    files["plans/notes.md"] = broken
    files["docs/historical/old.md"] = broken
    files["packages/s0ma-mcp/src/s0ma_mcp/_docs/mirror.md"] = broken
    files["packages/s0ma-studi0/docs/_generated/surface.md"] = broken
    files["packages/s0ma-studi0/src/_built/module.md"] = broken
    result = _run(_make_repo(tmp_path, files))
    assert result.returncode == 0, result.stdout


def test_vacuity_floor_fires_on_an_empty_scan_universe(tmp_path: Path) -> None:
    """A scan that checks nothing must not report PASS."""
    result = _run(_make_repo(tmp_path, {"README.txt": "not markdown\n", "src/app.py": "x = 1\n"}))
    assert result.returncode == 1
    assert "VACUOUS SCAN" in result.stdout
    assert "0 intra-repo link(s) found" in result.stdout
    assert "PASS" not in result.stdout


def test_vacuity_floor_fires_on_a_scanned_but_linkless_tree(tmp_path: Path) -> None:
    """Documents present, links absent — still nothing verified."""
    result = _run(_make_repo(tmp_path, {"README.md": "# Nothing here\n"}))
    assert result.returncode == 1
    assert "VACUOUS SCAN" in result.stdout


def test_checker_refuses_outside_a_checkout(tmp_path: Path) -> None:
    """No git index, no universe: fail loudly rather than scan nothing."""
    bare = tmp_path / "plain"
    bare.mkdir()
    result = _run(bare)
    assert result.returncode == 1
    assert "cannot list tracked files" in result.stdout


# ---------------------------------------------------------------------------
# The allowlist
# ---------------------------------------------------------------------------


def test_allowlisted_link_passes(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    checker = _checker()
    files = _baseline()
    files["docs/guide.md"] = "# Guide\n\n[deliberate](never-tracked.md)\n"
    root = _make_repo(tmp_path, files)

    allowed = checker.Allowed(
        path="docs/guide.md",
        link="never-tracked.md",
        why="fixture: exercises the exemption mechanism",
    )
    assert checker.check(root, allowlist=(allowed,)) == 0
    output = capsys.readouterr().out
    assert "docs-links: PASS" in output
    assert "(1 allowlisted)" in output


def test_stale_allowlist_entry_warns(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """An entry that covers nothing cannot outlive its justification."""
    checker = _checker()
    root = _make_repo(tmp_path, _baseline())

    allowed = checker.Allowed(
        path="docs/guide.md",
        link="never-tracked.md",
        why="fixture: the link it covered is gone",
    )
    assert checker.check(root, allowlist=(allowed,)) == 0
    assert "WARNING stale allowlist entry" in capsys.readouterr().out


def test_shipped_allowlist_entries_each_name_a_link_and_a_reason() -> None:
    """Every entry is a link that CANNOT resolve, and says why.

    In the private monorepo this list is empty: every finding the gate has
    produced was a real broken link and was fixed as one. This repository
    is the public export, where a handful of frozen records — a frozen
    contract, four accepted ADRs, two archive tombstones, two reference
    pages — cite documents the export withholds. Repointing those would
    falsify the record, so they are exempted instead, and what is asserted
    here is the property that still holds: each entry names one link and
    carries a written reason. An entry that stops matching is reported by
    the checker itself as a WARNING, so an exemption cannot outlive its
    reason in silence.
    """
    allowlist = _checker().ALLOWLIST
    assert allowlist, "the export fills this in; an empty list means the rule did not run"
    for entry in allowlist:
        assert entry.path and entry.link, entry
        assert len(entry.why.split()) >= 6, entry


# ---------------------------------------------------------------------------
# Wiring
# ---------------------------------------------------------------------------


def test_stage_is_registered_after_the_version_currency_stage() -> None:
    """The gate is only a gate if ``check.py`` runs it."""
    source = CHECK_PY.read_text(encoding="utf-8")
    assert '"docs-links"' in source
    assert "scripts/check_links.py" in source
    assert source.index('"docs-version-currency"') < source.index('"docs-links"')
