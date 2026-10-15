"""Guards for the brownfield fixture applications (plan beta-prep-1, A2).

``tests/fixtures/brownfield/`` holds two complete plain-Python applications
that the ``s0ma adopt`` family is proved against. Later milestones commit
golden scan reports, drafts and parity baselines taken from them, so the
fixtures have to be three things at once, and every one of them is a thing
that quietly stops being true:

* **invisible to this suite.** They ship ``test_*.py`` of their own, and
  ``pytest packages/s0ma-dsl/tests`` passes an explicit path, which turns
  ``testpaths`` off and walks the whole tree. Without the ``collect_ignore``
  in ``fixtures/brownfield/conftest.py`` their assertions would be reported
  as DSL results.
* **byte-stable.** A golden taken from a fixture is only evidence while the
  fixture's bytes are the bytes the golden was taken from. The manifest
  below is the pin: an edit to a fixture must be a deliberate edit here too.
* **runnable on their own.** "The project's own tests are still green" is
  the headline proof of the conversion journey (E2.T4), so the fixture's
  suite has to keep passing from inside the fixture directory.

The remaining tests state the promises the fixtures make to the milestones
that consume them: plain Python, standard library only, no s0ma anywhere,
and no Markdown (every tracked Markdown file in this repository needs a
catalog row and a ledger row).
"""

from __future__ import annotations

import ast
import hashlib
import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
BROWNFIELD_DIR = Path(__file__).resolve().parent / "fixtures" / "brownfield"
LAYERED_APP_DIR = BROWNFIELD_DIR / "layered_app"
MULTI_PKG_APP_DIR = BROWNFIELD_DIR / "multi_pkg_app"

# Directories a walk must not descend into: every one is regenerable, is
# ignored by git, and would otherwise show up as an unexpected fixture file.
IGNORABLE_DIRS = frozenset({"__pycache__", ".pytest_cache", ".ruff_cache", ".venv"})

# Every file of both fixture applications, project-relative POSIX path to the
# sha256 of its bytes, sorted by path. Regenerate deliberately when a fixture
# is meant to change; a surprise failure here means a fixture moved under a
# golden that was taken from it (or that a tool wrote into the tree).
FIXTURE_MANIFEST = {
    "packages/s0ma-dsl/tests/fixtures/brownfield/layered_app/pyproject.toml":
        "1efb9e3c8f49b186a859fa611accab2d13a8232e4bfc63d9fb9c5eb86bdedc09",
    "packages/s0ma-dsl/tests/fixtures/brownfield/layered_app/src/bookshelf/__init__.py":
        "b9abc279c1563feee37b24b63479afaa716caaf7e2c30445d5d4071e83ec4f7b",
    "packages/s0ma-dsl/tests/fixtures/brownfield/layered_app/src/bookshelf/__main__.py":
        "50fd328dfe5b5339a9958444940e9ce45b9764dbb7b130cc25f3a966ccb706a8",
    "packages/s0ma-dsl/tests/fixtures/brownfield/layered_app/src/bookshelf/api.py":
        "fc00ffbb7aa13c96040a7d47faa5fe8ead1e7ef36d047d0f2beec309c3da5ff4",
    "packages/s0ma-dsl/tests/fixtures/brownfield/layered_app/src/bookshelf/catalog.py":
        "2139da5be6a1c887ca11bc971633cc006a67086ebe7de3c970d367dd1d918aa8",
    "packages/s0ma-dsl/tests/fixtures/brownfield/layered_app/src/bookshelf/cli.py":
        "7b088d5511f405836763126eccfcbbea5f8fcf969534ecc6f55900b4f1940868",
    "packages/s0ma-dsl/tests/fixtures/brownfield/layered_app/src/bookshelf/config.py":
        "24ca5b194b2b3cfed1bb51c3aa098b5fa5ff12e145f27659119e3413e0f751fc",
    "packages/s0ma-dsl/tests/fixtures/brownfield/layered_app/src/bookshelf/errors.py":
        "671053c4b0840a801925b88a7882c8587c06f291a3b172e7cdc0b33369f8851e",
    "packages/s0ma-dsl/tests/fixtures/brownfield/layered_app/src/bookshelf/lending.py":
        "3eac1063f79df154f51df5518d7c8d338100a8c9b927c6cc4431899a2895be63",
    "packages/s0ma-dsl/tests/fixtures/brownfield/layered_app/src/bookshelf/models.py":
        "8dd709a199153e10f09f13b5e461b7af280aa91d88627dd70acc63792c2b5a17",
    "packages/s0ma-dsl/tests/fixtures/brownfield/layered_app/src/bookshelf/notifications.py":
        "5b5d60573d36a1fccf510bf17d462b5069db198521a8ad1c6166c08dd049d0e1",
    "packages/s0ma-dsl/tests/fixtures/brownfield/layered_app/src/bookshelf/storage.py":
        "784338970fae8ff9192008bf2f3dbd3a4f042019b710d875ee61d56668a9ac93",
    "packages/s0ma-dsl/tests/fixtures/brownfield/layered_app/tests/conftest.py":
        "b00aa4774b8538c8e09e60fd8dd9a52c83b750d6cc7bd9182159d9a9443b14f0",
    "packages/s0ma-dsl/tests/fixtures/brownfield/layered_app/tests/test_api.py":
        "895b65e63da568692ff44d3f97c3c6968a2bcc648e8d5258210008df426c9e37",
    "packages/s0ma-dsl/tests/fixtures/brownfield/layered_app/tests/test_catalog.py":
        "e0a971b4fb48a3b78699780785cb6997d4a93569c5c141f74a03db12a5da4a94",
    "packages/s0ma-dsl/tests/fixtures/brownfield/layered_app/tests/test_lending.py":
        "23391b2a21a2ba6121d44a7682314e63d1e225b180e00d5a77ddbe49ddc39468",
    "packages/s0ma-dsl/tests/fixtures/brownfield/layered_app/tests/test_notifications.py":
        "3c16187e65d20138e1b53831008a669fa7a05761fa92c7157262abb5da1426ad",
    "packages/s0ma-dsl/tests/fixtures/brownfield/multi_pkg_app/evallib/__init__.py":
        "07da7a8de8fe21c78aa2f9ca53fda3266b942652d957066516621a7d647faa6d",
    "packages/s0ma-dsl/tests/fixtures/brownfield/multi_pkg_app/evallib/scoring.py":
        "eaa97b00ba96340742374709c027950a883fa300fc67c756081b20943365a76d",
    "packages/s0ma-dsl/tests/fixtures/brownfield/multi_pkg_app/harnesslib/__init__.py":
        "a6c168bcada99a74aa3757b3fa15f685a7582f37fbefd8259f455e5c483ae6ce",
    "packages/s0ma-dsl/tests/fixtures/brownfield/multi_pkg_app/harnesslib/__main__.py":
        "dcb7765737f92cfacf08958f5e30518c67b5814305ff9b7f77f8932e00af97e5",
    "packages/s0ma-dsl/tests/fixtures/brownfield/multi_pkg_app/harnesslib/runner.py":
        "c4115ac7fb0c920e377924514694fcd8b3ea64b2936e83b68319127c0ac69154",
    "packages/s0ma-dsl/tests/fixtures/brownfield/multi_pkg_app/metrics/__init__.py":
        "71fb634b6184fc3094f0187de46c98a97dbffdc768f229d6ffa0f1db573d30d0",
    "packages/s0ma-dsl/tests/fixtures/brownfield/multi_pkg_app/metrics/counters.py":
        "9711394b686abe0a051e0739c2fe6f25c107379fb16b5c6b2235c7371582fe27",
    "packages/s0ma-dsl/tests/fixtures/brownfield/multi_pkg_app/pyproject.toml":
        "43acb623ecd1c71b6613e075eeea2526bc47a7bb3c723d862bdeeb85b02224f1",
    "packages/s0ma-dsl/tests/fixtures/brownfield/multi_pkg_app/samples/demo_one/app.py":
        "12ce46eaf45bbb8f55ba6ed0ebaeec5d14445b458acdede8bd43e99985508d53",
    "packages/s0ma-dsl/tests/fixtures/brownfield/multi_pkg_app/samples/demo_one/support.py":
        "79ba4dcfc7d729a4333c5a92ebfe8a69ecd3f537fd44d4324f59a9bf9f51a9e6",
    "packages/s0ma-dsl/tests/fixtures/brownfield/multi_pkg_app/samples/demo_two/main.py":
        "8c26fc954184a9e11f643b801a5ac32abe46948a2b1518bc01599fa82893d576",
    "packages/s0ma-dsl/tests/fixtures/brownfield/multi_pkg_app/tests_suite/test_counters.py":
        "4cf804a15a4b3c5eb7df8ca5d845345eac0975fe923a4e56e474b10380a3a9c4",
    "packages/s0ma-dsl/tests/fixtures/brownfield/multi_pkg_app/tests_suite/test_runner.py":
        "2df4092f2e2fe59c5fe2a82c877ea1965b35c0155268d3eabfa943bf63ab19dc",
    "packages/s0ma-dsl/tests/fixtures/brownfield/multi_pkg_app/tests_suite/test_scoring.py":
        "1703936ce51a2d111b1f4f3629c02071afd95ced7bbe42b74ece112212eeab37",
    "packages/s0ma-dsl/tests/fixtures/brownfield/tiny_app/inventory.py":
        "c82b750f9db1c70928d1243b6f6d30556b41b8ec98e84b1b3ab4620b2ce7485c",
    "packages/s0ma-dsl/tests/fixtures/brownfield/tiny_app/report.py":
        "3ced8a2e96ba3fa07b441810062a9acfb0f4f8a4643094a78cbf1313526825bf",
    "packages/s0ma-dsl/tests/fixtures/brownfield/tiny_app/run.py":
        "a5ac6d4042a9dae62c2fc6453e67777a508c6386e4357a9183eb222e4d51cb15",
}

# The number of tests each fixture's own suite reports. Pinned so that a
# fixture test silently disappearing cannot pass as "still green".
LAYERED_APP_TEST_COUNT = 15
MULTI_PKG_APP_TEST_COUNT = 13


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _walk(directory: Path) -> list[Path]:
    """Every file under ``directory``, caches excluded, sorted by path."""
    found = [
        path
        for path in directory.rglob("*")
        if path.is_file()
        and not IGNORABLE_DIRS.intersection(path.relative_to(directory).parts)
    ]
    return sorted(found)


def _project_relative(path: Path) -> str:
    """The path as the repository records paths: relative, forward-slashed."""
    return path.relative_to(REPO_ROOT).as_posix()


def _application_dirs() -> list[Path]:
    """The fixture application trees: every child not named with a leading _."""
    return sorted(
        child
        for child in BROWNFIELD_DIR.iterdir()
        if child.is_dir() and not child.name.startswith((".", "_"))
    )


def _collect_ignore_entries() -> list[str]:
    """``collect_ignore`` as the brownfield conftest declares it.

    Read out of the source with ``ast`` rather than imported: importing a
    conftest by hand is the very thing this file asserts does not happen.
    """
    source = (BROWNFIELD_DIR / "conftest.py").read_text(encoding="utf-8")
    for node in ast.parse(source).body:
        targets = node.targets if isinstance(node, ast.Assign) else []
        if any(isinstance(t, ast.Name) and t.id == "collect_ignore" for t in targets):
            return [str(entry) for entry in ast.literal_eval(node.value)]
    pytest.fail("fixtures/brownfield/conftest.py no longer defines collect_ignore")


# ---------------------------------------------------------------------------
# Byte stability
# ---------------------------------------------------------------------------

def test_the_manifest_lists_exactly_the_files_that_are_there() -> None:
    on_disk = {
        _project_relative(path)
        for app_dir in _application_dirs()
        for path in _walk(app_dir)
    }
    unexpected = sorted(on_disk - set(FIXTURE_MANIFEST))
    missing = sorted(set(FIXTURE_MANIFEST) - on_disk)
    assert not unexpected, (
        "files under the fixture applications that the manifest does not list: "
        f"{unexpected}. If a tool wrote them, remove them (running `uv run` inside "
        "layered_app leaves a .venv/ and a uv.lock behind); if they are new fixture "
        "files, add them to FIXTURE_MANIFEST on purpose."
    )
    assert not missing, f"manifest lists files that are gone: {missing}"


def test_every_fixture_file_still_has_the_bytes_the_manifest_pins() -> None:
    drifted = []
    for relative, expected in sorted(FIXTURE_MANIFEST.items()):
        actual = hashlib.sha256((REPO_ROOT / relative).read_bytes()).hexdigest()
        if actual != expected:
            drifted.append(f"{relative}: {expected} -> {actual}")
    assert not drifted, (
        "fixture bytes changed; goldens taken from them are now evidence for a "
        "different tree. Update the golden and then the manifest, in that order:\n"
        + "\n".join(drifted)
    )


def test_the_manifest_is_sorted_so_its_diffs_stay_readable() -> None:
    keys = list(FIXTURE_MANIFEST)
    assert keys == sorted(keys)


# ---------------------------------------------------------------------------
# Isolation from this suite's collection
# ---------------------------------------------------------------------------

def test_every_application_tree_is_named_in_collect_ignore() -> None:
    ignored = set(_collect_ignore_entries())
    unlisted = sorted(d.name for d in _application_dirs() if d.name not in ignored)
    assert not unlisted, (
        f"fixture applications missing from brownfield/conftest.py collect_ignore: "
        f"{unlisted}. Add them, or this suite will collect their tests as its own."
    )


def test_pytest_collects_nothing_from_the_brownfield_tree() -> None:
    result = subprocess.run(
        [
            sys.executable, "-m", "pytest", str(BROWNFIELD_DIR),
            "--collect-only", "-q", "-p", "no:cacheprovider",
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    # 5 is pytest's "no tests were collected", which is the whole point.
    assert result.returncode == 5, (
        "pytest collected something from the brownfield fixtures "
        f"(exit {result.returncode}):\n{result.stdout}\n{result.stderr}"
    )


# ---------------------------------------------------------------------------
# The applications still work on their own
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    ("directory", "expected"),
    [
        (LAYERED_APP_DIR, LAYERED_APP_TEST_COUNT),
        (MULTI_PKG_APP_DIR, MULTI_PKG_APP_TEST_COUNT),
    ],
    ids=["layered_app", "multi_pkg_app"],
)
def test_each_fixture_suite_passes_from_inside_the_fixture(
    directory: Path, expected: int
) -> None:
    # `python -m pytest`, never `uv run`: uv would write a lockfile into the
    # fixture tree and the manifest above pins every byte of it.
    result = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider"],
        cwd=directory,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, (
        "the fixture's own suite failed; the conversion journey's headline proof "
        f"is that it stays green:\n{result.stdout}\n{result.stderr}"
    )
    assert f"{expected} passed" in result.stdout, (
        f"expected {expected} fixture tests in {directory.name}:\n{result.stdout}"
    )


# ---------------------------------------------------------------------------
# Lint
# ---------------------------------------------------------------------------

def test_the_fixtures_are_clean_under_the_repository_ruff_settings() -> None:
    # There is no ruff exclusion for tests/fixtures/ and this milestone did not
    # add one: the fixtures simply lint clean under the s0ma-dsl package's own
    # [tool.ruff] settings, which is what `ruff check packages/` enforces at
    # every gate. This test says so where a fixture author will read it.
    if importlib.util.find_spec("ruff") is None:  # pragma: no cover - env-dependent
        pytest.skip("ruff is not installed in this environment")
    result = subprocess.run(
        [sys.executable, "-m", "ruff", "check", "--no-cache", str(BROWNFIELD_DIR)],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, (
        f"the brownfield fixtures no longer lint clean:\n{result.stdout}\n{result.stderr}"
    )


# ---------------------------------------------------------------------------
# What the fixtures promise the milestones that consume them
# ---------------------------------------------------------------------------

def test_the_fixtures_are_utf8_with_unix_endings_and_no_trailing_space() -> None:
    faults = []
    for relative in sorted(FIXTURE_MANIFEST):
        path = REPO_ROOT / relative
        raw = path.read_bytes()
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError as exc:
            faults.append(f"{relative}: not UTF-8 ({exc})")
            continue
        if b"\r" in raw:
            faults.append(f"{relative}: carriage return in the file")
        if raw and not raw.endswith(b"\n"):
            faults.append(f"{relative}: no newline at end of file")
        for number, line in enumerate(text.split("\n"), start=1):
            if line != line.rstrip():
                faults.append(f"{relative}:{number}: trailing whitespace")
    assert not faults, "\n".join(faults)


def test_there_is_no_markdown_under_the_fixture_trees() -> None:
    # Every tracked Markdown file needs a catalog row and a ledger row; a
    # fixture has no business in the documentation corpus. NOTES.txt instead.
    markdown = [
        _project_relative(path)
        for app_dir in _application_dirs()
        for path in _walk(app_dir)
        if path.suffix.lower() in {".md", ".markdown"}
    ]
    assert not markdown, f"use NOTES.txt beside the fixtures, not Markdown: {markdown}"


def test_there_is_no_s0ma_in_the_fixtures() -> None:
    # The fixtures are the "before" picture. Anything s0ma inside them would
    # make the retrofit journey prove less than it claims to.
    faults = []
    for relative in sorted(FIXTURE_MANIFEST):
        path = REPO_ROOT / relative
        if path.suffix == ".s0ma":
            faults.append(f"{relative}: a .s0ma source inside a fixture")
            continue
        text = path.read_text(encoding="utf-8")
        if "[tool.s0ma]" in text:
            faults.append(f"{relative}: carries a [tool.s0ma] table")
        for marker in ("import s0ma", "from s0ma", "s0ma_dsl"):
            if marker in text:
                faults.append(f"{relative}: mentions {marker!r}")
    assert not faults, "\n".join(faults)


def test_the_applications_import_nothing_but_the_standard_library() -> None:
    # The fixtures have to run anywhere, and a scan must not have to resolve a
    # package that is not installed. pytest is allowed in the fixture's own
    # tests: it is the runner, not a dependency of the service.
    first_party = {
        "bookshelf", "inventory", "report", "run", "conftest",
        # multi_pkg_app: three sibling packages, plus the name one sample
        # application imports from its own directory.
        "harnesslib", "evallib", "metrics", "support",
    }
    allowed = set(sys.stdlib_module_names) | first_party
    faults = []
    for relative in sorted(FIXTURE_MANIFEST):
        if not relative.endswith(".py"):
            continue
        path = REPO_ROOT / relative
        in_tests = "/tests/" in relative
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=relative)
        for node in ast.walk(tree):
            roots: list[str] = []
            if isinstance(node, ast.Import):
                roots = [alias.name.split(".")[0] for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                roots = [node.module.split(".")[0]]
            for root in roots:
                if root in allowed or (in_tests and root == "pytest"):
                    continue
                faults.append(f"{relative}:{node.lineno}: third-party import {root!r}")
    assert not faults, "\n".join(faults)


def test_the_notes_file_is_there_and_is_not_markdown() -> None:
    notes = BROWNFIELD_DIR / "NOTES.txt"
    assert notes.is_file(), "NOTES.txt maps the deliberate cases; later milestones read it"
    body = notes.read_text(encoding="utf-8")
    for name in ("layered_app", "tiny_app", "multi_pkg_app", "TYPE_CHECKING", "async def"):
        assert name in body, f"NOTES.txt no longer mentions {name}"


@pytest.mark.parametrize("app", ["layered_app", "multi_pkg_app", "tiny_app"])
def test_each_fixture_application_is_present(app: str) -> None:
    assert (BROWNFIELD_DIR / app).is_dir()
