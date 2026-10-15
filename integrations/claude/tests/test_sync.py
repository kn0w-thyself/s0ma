"""What ``scripts/sync_integrations.py`` promises, held to it.

Three things under ``integrations/`` are copies of something the monorepo
owns: the launcher (copied into the plugin and into the Desktop extension),
the version (stated in the plugin manifest, the extension manifest and the
extension's ``pyproject.toml``), and the feedback skill's body (written by
``s0ma new project``). The sync script is the only thing allowed to change
any of them, and the ``integrations`` stage of ``scripts/check.py`` runs its
``--check``.

A gate is only worth its runtime if it fails when it should, so most of this
file is failure: the committed tree is checked once, and then a COPY of it in
a temporary directory is broken in each of the ways it can really break -
a stale launcher copy, a version left behind by a release cut, an edited
skill body - and the script has to name the file, name the fix, repair it,
and change nothing on a second run. Nothing here touches the checkout: every
mutation happens under ``tmp_path``, which is what the script's ``--root``
argument exists for.

The suite is offline, spawns only this interpreter, and makes no assumption
about path separators or line endings, so it behaves on Windows as it does
here.
"""

from __future__ import annotations

import hashlib
import importlib
import importlib.util
import json
import shutil
import subprocess
import sys
from pathlib import Path
from types import ModuleType

import pytest

#: The repository, from ``integrations/claude/tests/test_sync.py``.
REPO_ROOT = Path(__file__).resolve().parents[3]

SCRIPT = REPO_ROOT / "scripts" / "sync_integrations.py"


# ---------------------------------------------------------------------------
# The script, as a module and as a command
# ---------------------------------------------------------------------------


@pytest.fixture(scope="session")
def sync() -> ModuleType:
    """``sync_integrations.py``, imported from its path.

    It is a standalone script in ``scripts/``, not an installed module, so it
    is loaded the way it is run. Importing it gives the tests the one list of
    files it keeps in step - so a site added to the script is copied and
    checked here without anybody remembering to update a second list.
    """
    spec = importlib.util.spec_from_file_location("s0ma_sync_integrations_for_tests", SCRIPT)
    if spec is None or spec.loader is None:  # pragma: no cover - broken checkout
        raise RuntimeError(f"could not load the sync script from {SCRIPT}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="session")
def tracked_files(sync: ModuleType) -> tuple[str, ...]:
    """Every repo-relative path the script reads or writes."""
    return (
        sync.VERSION_SOURCE,
        sync.LAUNCHER_SOURCE,
        *sync.LAUNCHER_COPIES,
        *sync.JSON_VERSION_SITES,
        sync.TOML_VERSION_SITE,
        sync.FEEDBACK_SKILL,
    )


def run_script(*args: str, root: Path | None = None) -> subprocess.CompletedProcess[str]:
    """Run the script the way the gate stage runs it, and capture what it said."""
    command = [sys.executable, str(SCRIPT), *args]
    if root is not None:
        command += ["--root", str(root)]
    return subprocess.run(
        command,
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )


@pytest.fixture
def tree(tmp_path: Path, tracked_files: tuple[str, ...]) -> Path:
    """A copy of just the files the script cares about, under ``tmp_path``.

    A copy, because every test below breaks something on purpose; only the
    named files, because copying a monorepo to prove a version string is
    wasteful and slow.
    """
    root = tmp_path / "tree"
    for relative in tracked_files:
        source = REPO_ROOT / relative
        target = root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
    return root


def digest(root: Path) -> dict[str, str]:
    """Every file under *root* as relative-POSIX path -> sha256."""
    return {
        path.relative_to(root).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


# ---------------------------------------------------------------------------
# The ways the integration really drifts
# ---------------------------------------------------------------------------


def stale_launcher_copy(sync: ModuleType, root: Path) -> str:
    """The plugin ships last week's launcher."""
    relative = sync.LAUNCHER_COPIES[0]
    path = root / relative
    path.write_bytes(path.read_bytes() + b"\n# an edit nobody synced\n")
    return relative


def stale_desktop_launcher_copy(sync: ModuleType, root: Path) -> str:
    """The extension ships last week's launcher."""
    relative = sync.LAUNCHER_COPIES[1]
    path = root / relative
    path.write_bytes(path.read_bytes().replace(b"serve", b"serv3", 1))
    return relative


def stale_manifest_version(sync: ModuleType, root: Path, which: int) -> str:
    """A release cut bumped the packages and forgot one of the manifests."""
    relative = sync.JSON_VERSION_SITES[which]
    path = root / relative
    data = json.loads(path.read_text(encoding="utf-8"))
    data["version"] = "0.1.0"
    path.write_text(
        json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n"
    )
    return relative


def stale_extension_pyproject(sync: ModuleType, root: Path) -> str:
    """The extension's own project file states a version nobody bumped."""
    relative = sync.TOML_VERSION_SITE
    path = root / relative
    text = path.read_text(encoding="utf-8")
    stated = sync.TOML_VERSION_RE.findall(text)[0]
    path.write_text(
        text.replace(f'version = "{stated}"', 'version = "0.1.0"', 1),
        encoding="utf-8",
        newline="\n",
    )
    return relative


def edited_skill_body(sync: ModuleType, root: Path) -> str:
    """Somebody improved the plugin's feedback skill and not the scaffolded one."""
    relative = sync.FEEDBACK_SKILL
    path = root / relative
    path.write_text(
        path.read_text(encoding="utf-8") + "\nOne more sentence, in one copy only.\n",
        encoding="utf-8",
        newline="\n",
    )
    return relative


#: The drifts, each a callable that breaks one thing and names the file.
DRIFTS = {
    "stale launcher copy (plugin)": stale_launcher_copy,
    "stale launcher copy (desktop)": stale_desktop_launcher_copy,
    "wrong version (plugin manifest)": lambda sync, root: stale_manifest_version(sync, root, 0),
    "wrong version (desktop manifest)": lambda sync, root: stale_manifest_version(sync, root, 1),
    "wrong version (desktop pyproject)": stale_extension_pyproject,
    "edited feedback skill body": edited_skill_body,
}


# ---------------------------------------------------------------------------
# The committed tree
# ---------------------------------------------------------------------------


class TestTheCommittedTree:
    """What the gate stage asserts, asserted here too."""

    def test_check_passes_on_this_checkout(self) -> None:
        """The same command ``scripts/check.py --only integrations`` runs."""
        result = run_script("--check")
        assert result.returncode == 0, result.stdout + result.stderr
        assert result.stdout.startswith("in step:"), result.stdout

    def test_the_copy_the_tests_work_on_is_faithful(self, tree: Path) -> None:
        """Otherwise every failure below would prove only that the copy is wrong."""
        result = run_script("--check", root=tree)
        assert result.returncode == 0, result.stdout + result.stderr

    def test_a_clean_run_says_what_it_looked_at(self, tree: Path) -> None:
        """Anti-vacuity: a green line that names nothing can hide a no-op."""
        stdout = run_script("--check", root=tree).stdout
        assert "2 launcher copies" in stdout
        assert "3 version sites" in stdout
        assert "1 skill body" in stdout


# ---------------------------------------------------------------------------
# Every drift is found, named, and repaired
# ---------------------------------------------------------------------------


class TestEveryDriftIsFoundAndRepaired:
    """One test body, six real ways the integration goes out of step."""

    @pytest.mark.parametrize("name", sorted(DRIFTS))
    def test_check_names_the_file_and_the_command_that_fixes_it(
        self, name: str, sync: ModuleType, tree: Path
    ) -> None:
        relative = DRIFTS[name](sync, tree)
        result = run_script("--check", root=tree)
        assert result.returncode == 1, result.stdout + result.stderr
        lines = result.stdout.splitlines()
        assert len(lines) == 1, f"one difference, one line: {lines}"
        assert relative in lines[0], lines[0]
        assert sync.FIX_COMMAND in lines[0], lines[0]

    @pytest.mark.parametrize("name", sorted(DRIFTS))
    def test_check_changes_nothing(self, name: str, sync: ModuleType, tree: Path) -> None:
        """``--check`` is a question, so asking it twice reads the same tree."""
        DRIFTS[name](sync, tree)
        before = digest(tree)
        run_script("--check", root=tree)
        assert digest(tree) == before

    @pytest.mark.parametrize("name", sorted(DRIFTS))
    def test_write_repairs_it_and_says_so(
        self, name: str, sync: ModuleType, tree: Path
    ) -> None:
        relative = DRIFTS[name](sync, tree)
        written = run_script("--write", root=tree)
        assert written.returncode == 0, written.stdout + written.stderr
        assert written.stdout.startswith(f"wrote: {relative} "), written.stdout
        assert run_script("--check", root=tree).returncode == 0

    @pytest.mark.parametrize("name", sorted(DRIFTS))
    def test_the_repaired_file_is_the_committed_one(
        self, name: str, sync: ModuleType, tree: Path
    ) -> None:
        """Repair means repair: the bytes come back, not something like them."""
        relative = DRIFTS[name](sync, tree)
        run_script("--write", root=tree)
        assert (tree / relative).read_bytes() == (REPO_ROOT / relative).read_bytes()

    def test_all_six_at_once(self, sync: ModuleType, tree: Path) -> None:
        """A real drift is rarely alone; every line is printed, not the first."""
        relatives = {drift(sync, tree) for drift in DRIFTS.values()}
        result = run_script("--check", root=tree)
        assert result.returncode == 1
        assert len(result.stdout.splitlines()) == len(relatives)
        for relative in relatives:
            assert relative in result.stdout
        assert run_script("--write", root=tree).returncode == 0
        assert run_script("--check", root=tree).returncode == 0


# ---------------------------------------------------------------------------
# ``--write`` twice
# ---------------------------------------------------------------------------


class TestWriteIsIdempotent:
    """The second run has nothing to do, and does nothing."""

    def test_a_second_write_changes_no_byte(self, sync: ModuleType, tree: Path) -> None:
        for drift in DRIFTS.values():
            drift(sync, tree)
        run_script("--write", root=tree)
        after_first = digest(tree)

        second = run_script("--write", root=tree)
        assert second.returncode == 0
        assert "wrote:" not in second.stdout, second.stdout
        assert second.stdout.startswith("nothing to change:"), second.stdout
        assert digest(tree) == after_first

    def test_write_on_a_clean_tree_is_a_no_op(self, tree: Path) -> None:
        before = digest(tree)
        result = run_script("--write", root=tree)
        assert result.returncode == 0
        assert digest(tree) == before


# ---------------------------------------------------------------------------
# The manifests keep their shape
# ---------------------------------------------------------------------------


class TestTheManifestsKeepTheirFormatting:
    """A sync script that reformats a file makes every later diff unreadable."""

    def test_only_the_version_line_moves(self, sync: ModuleType, tree: Path) -> None:
        """Bump the monorepo in the copy; the three sites follow, alone.

        The version the sites are compared against is moved rather than the
        sites themselves, so the repaired files cannot simply be the
        committed bytes - the one line that is allowed to change has to be
        the only line that changed.
        """
        source = tree / sync.VERSION_SOURCE
        source.write_text(
            sync.TOML_VERSION_RE.sub('version = "9.9.9"', source.read_text(encoding="utf-8"), count=1),
            encoding="utf-8",
            newline="\n",
        )
        assert run_script("--check", root=tree).returncode == 1
        assert run_script("--write", root=tree).returncode == 0

        for relative in (*sync.JSON_VERSION_SITES, sync.TOML_VERSION_SITE):
            before = (REPO_ROOT / relative).read_text(encoding="utf-8").splitlines()
            after = (tree / relative).read_text(encoding="utf-8").splitlines()
            differing = [
                (old, new) for old, new in zip(before, after, strict=True) if old != new
            ]
            assert len(differing) == 1, f"{relative}: {differing}"
            assert "9.9.9" in differing[0][1], differing[0]

    @pytest.mark.parametrize("which", (0, 1))
    def test_a_rewritten_manifest_is_still_canonical_json(
        self, which: int, sync: ModuleType, tree: Path
    ) -> None:
        """Two-space indent, sorted keys, ASCII, LF, one trailing newline.

        Their own suites pin exactly this, and the extension's pack script
        reads the version back out with ``sed``.
        """
        relative = stale_manifest_version(sync, tree, which)
        run_script("--write", root=tree)
        raw = (tree / relative).read_bytes()
        assert b"\r\n" not in raw
        text = raw.decode("utf-8")
        assert text.isascii()
        assert text == json.dumps(json.loads(text), indent=2, sort_keys=True) + "\n"

    def test_the_extension_pyproject_is_not_reformatted(
        self, sync: ModuleType, tree: Path
    ) -> None:
        """It is edited with a substitution, so its comments survive."""
        relative = stale_extension_pyproject(sync, tree)
        run_script("--write", root=tree)
        text = (tree / relative).read_text(encoding="utf-8")
        assert text.startswith("# The Claude Desktop extension's project file.")
        assert "[project]" in text


# ---------------------------------------------------------------------------
# One definition of the feedback skill's body
# ---------------------------------------------------------------------------


class TestOneDefinitionOfTheScaffoldedBody:
    """The script and the skill suite must mean the same text by "the body"."""

    def test_both_read_the_same_renderer_the_same_way(self, sync: ModuleType) -> None:
        import test_skills  # the sibling suite, same directory

        new_project = importlib.import_module("s0ma_dsl.cli.new_project")
        _, scaffolded = test_skills.split_front_matter(new_project._feedback_skill_md())
        assert sync.scaffolded_feedback_body() == scaffolded
        assert scaffolded.strip(), "an empty body would make the gate vacuous"

    def test_the_plugin_skill_keeps_its_own_invocation_name(
        self, sync: ModuleType, tree: Path
    ) -> None:
        """Repairing the body must never rename the skill to the project one."""
        edited_skill_body(sync, tree)
        run_script("--write", root=tree)
        front, _ = sync.split_front_matter(
            (tree / sync.FEEDBACK_SKILL).read_text(encoding="utf-8")
        )
        assert "name: feedback\n" in front
        assert "s0ma-feedback" not in front


# ---------------------------------------------------------------------------
# The command line
# ---------------------------------------------------------------------------


class TestTheCommandLine:
    """Two modes, exactly one of them, and nothing clever."""

    @pytest.mark.parametrize("args", ([], ["--check", "--write"]))
    def test_a_mode_is_required_and_only_one(self, args: list[str]) -> None:
        assert run_script(*args).returncode == 2

    def test_an_empty_root_is_reported_not_crashed(
        self, sync: ModuleType, tmp_path: Path
    ) -> None:
        """A tree with none of the files is out of step, loudly and calmly.

        Nothing a rewrite can repair, so every line has to say so rather
        than promise a fix that would not arrive.
        """
        empty = tmp_path / "nothing"
        empty.mkdir()
        result = run_script("--check", root=empty)
        assert result.returncode == 1
        assert "Traceback" not in result.stderr, result.stderr
        lines = result.stdout.splitlines()
        assert lines, "a failure that prints nothing explains nothing"
        assert any(sync.LAUNCHER_SOURCE in line for line in lines), lines
        for line in lines:
            assert "cannot fix this one" in line, line
            assert "\\" not in line, f"paths are forward-slashed everywhere: {line}"

    def test_write_on_a_root_it_cannot_repair_exits_nonzero(
        self, tmp_path: Path
    ) -> None:
        """``--write`` must not claim success it did not have."""
        empty = tmp_path / "nothing"
        empty.mkdir()
        assert run_script("--write", root=empty).returncode == 1
