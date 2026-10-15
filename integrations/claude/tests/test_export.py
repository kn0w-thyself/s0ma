"""What ``scripts/export_claude_marketplace.py`` promises, held to it.

The export script builds the tree of a PUBLIC repository. That is the whole
reason this file is careful: everything it writes is about to be readable by
anyone, and a mistake there cannot be taken back. So the tests ask three kinds
of question.

*Is the tree right?* Every expected file is present, the catalog's plugin entry
points at the plugin's new home, the plugin's own files arrive byte for byte
with the two shims still executable, and the export manifest states the hash
and the mode of every one of them.

*Is it safe to publish?* Nothing in the output names the machine that built it.
The two files written for readers carry no key-shaped string, no version number
that could go stale, and spell the product's name with the digit zero. The
script refuses to write at all when the export directory is inside this
repository, when it already holds something, when the launcher copies are out
of step with the monorepo, or when git cannot vouch that the source is
committed.

*Does it publish anything itself?* No: the owner's commands are printed, and
the one test that watches every subprocess proves that no ``git push``, no
``gh``, and no ``claude plugin install`` was ever run.

Nothing here opens a socket, nothing reads or writes anything under
``~/.claude`` or ``~/.s0ma``, and every byte written lands under ``tmp_path``.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

#: The repository, from ``integrations/claude/tests/test_export.py``.
REPO_ROOT = Path(__file__).resolve().parents[3]

SCRIPT = REPO_ROOT / "scripts" / "export_claude_marketplace.py"

WINDOWS = sys.platform.startswith("win")

#: The files the export writes itself, as opposed to the ones it copies. Only
#: these are held to "no dates, no version numbers": the copied ones are the
#: committed bytes of the plugin, and keeping those honest is the plugin's own
#: test suite's job.
GENERATED = (
    ".claude-plugin/marketplace.json",
    "EXPORT-MANIFEST.json",
    "PRIVACY.md",
    "README.md",
)

#: The secret-hygiene grep the gate runs over every diff, applied here to the
#: two files a stranger reads first.
KEY_SHAPED = re.compile(r"s0ma_[A-Za-z0-9]{8,}")

#: House spelling: the digit zero, always (plan section 3.1 rule 11). The
#: letter-o forms are spelled with a character class so this file does not
#: itself trip the repository's spelling guard.
MISSPELLED = (re.compile(r"(?i)\bs[o]ma\b"), re.compile(r"(?i)kn[o]w[\s-]?thyself"))

#: A version number in prose goes stale the day after it is written.
VERSION_SHAPED = re.compile(r"\b\d+\.\d+\.\d+\b")

#: Anything that would make two exports of one commit differ.
TIMESTAMP_SHAPED = (
    re.compile(r"\b\d{4}-\d{2}-\d{2}\b"),
    re.compile(r"\b\d{2}:\d{2}:\d{2}\b"),
    re.compile(
        r"(?i)\b(january|february|march|april|june|july|august|september"
        r"|october|november|december)\b"
    ),
)


# ---------------------------------------------------------------------------
# The script, as a module and as a command.
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def script() -> ModuleType:
    """``export_claude_marketplace.py``, imported from its path.

    It is a standalone script in ``scripts/``, not an installed module, so it
    is loaded the way it is run. Importing it gives the tests its own idea of
    what belongs in the export - so a file added to the script is checked here
    without anybody remembering to update a second list.
    """
    spec = importlib.util.spec_from_file_location("s0ma_export_marketplace_for_tests", SCRIPT)
    if spec is None or spec.loader is None:  # pragma: no cover - broken checkout
        raise RuntimeError(f"could not load the export script from {SCRIPT}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@dataclass(frozen=True)
class Export:
    """One finished export: where it landed and what the script said."""

    out: Path
    result: subprocess.CompletedProcess[str]

    def read(self, relative: str) -> bytes:
        return (self.out / relative).read_bytes()

    def text(self, relative: str) -> str:
        return self.read(relative).decode("utf-8")

    def json(self, relative: str) -> dict[str, Any]:
        loaded = json.loads(self.text(relative))
        assert isinstance(loaded, dict), f"{relative} must hold a JSON object"
        return loaded

    def paths(self) -> list[str]:
        """Every file in the export, forward-slashed and sorted."""
        return sorted(
            str(path.relative_to(self.out)).replace("\\", "/")
            for path in self.out.rglob("*")
            if path.is_file()
        )


def run_export(*args: str) -> subprocess.CompletedProcess[str]:
    """Run the script the way a person runs it, and capture what it said."""
    return subprocess.run(  # noqa: S603 - this interpreter, a fixed script
        [sys.executable, str(SCRIPT), *args],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=600,
    )


@pytest.fixture(scope="module")
def export(tmp_path_factory: pytest.TempPathFactory) -> Export:
    """One real export of this checkout, shared by every test that reads it.

    ``--allow-dirty`` because the milestone this file belongs to is written
    before its own commit exists: the tests are themselves an uncommitted
    change under ``integrations/``, which is precisely what the check the flag
    lifts is there to catch. The refusal itself is tested below.
    """
    out = tmp_path_factory.mktemp("marketplace") / "export"
    result = run_export("--allow-dirty", "--root", str(REPO_ROOT), "--out", str(out))
    assert result.returncode == 0, (
        f"the export failed:\n{result.stdout}\n{result.stderr}"
    )
    return Export(out=out, result=result)


# ---------------------------------------------------------------------------
# Is the tree right?
# ---------------------------------------------------------------------------


def test_the_expected_files_are_there(export: Export, script: ModuleType) -> None:
    """A marketplace, a plugin under it, and the three files a reader needs."""
    present = export.paths()
    for expected in (
        ".claude-plugin/marketplace.json",
        "EXPORT-MANIFEST.json",
        "LICENSE",
        "PRIVACY.md",
        "README.md",
        f"{script.EXPORT_PLUGIN_DIR}/.claude-plugin/plugin.json",
        f"{script.EXPORT_PLUGIN_DIR}/.mcp.json",
        f"{script.EXPORT_PLUGIN_DIR}/hooks/hooks.json",
        f"{script.EXPORT_PLUGIN_DIR}/launcher/s0ma_launch.py",
    ):
        assert expected in present, f"{expected} is missing from the export"
    skills = [path for path in present if "/skills/" in path]
    assert len(skills) == 6, f"six skills are expected, found {skills}"


def test_the_marketplace_points_at_the_plugin_in_the_export(
    export: Export, script: ModuleType
) -> None:
    """The source is rewritten from where the plugin sits in the monorepo."""
    catalog = export.json(".claude-plugin/marketplace.json")
    assert catalog["name"] == script.MARKETPLACE_NAME
    entries = catalog["plugins"]
    assert len(entries) == 1, "one plugin entry is expected"
    source = entries[0]["source"]
    assert source == script.SOURCE_IN_EXPORT, f"the entry still points at {source}"
    assert source != script.SOURCE_IN_MONOREPO
    assert ".." not in source, "a source that climbs out of the root is refused by the CLI"
    named = export.out / source
    assert (named / ".claude-plugin" / "plugin.json").is_file(), (
        f"the entry names {source}, where there is no plugin"
    )


def test_the_plugin_arrives_byte_for_byte(export: Export, script: ModuleType) -> None:
    """Every file of the plugin, unchanged, and nothing extra."""
    plugin_dir = REPO_ROOT / script.PLUGIN_DIR
    expected = script.plugin_sources(plugin_dir)
    for relative, source in expected:
        landed = export.out / script.EXPORT_PLUGIN_DIR / relative
        assert landed.is_file(), f"{relative} did not arrive"
        assert landed.read_bytes() == source.read_bytes(), f"{relative} was altered"
    exported_plugin = [
        path[len(script.EXPORT_PLUGIN_DIR) + 1 :]
        for path in export.paths()
        if path.startswith(script.EXPORT_PLUGIN_DIR + "/")
    ]
    assert sorted(exported_plugin) == sorted(relative for relative, _ in expected)


def test_the_root_license_is_the_plugins(export: Export, script: ModuleType) -> None:
    """One Apache-2.0 text, stated twice, identical both times."""
    plugin_license = (REPO_ROOT / script.PLUGIN_DIR / "LICENSE").read_bytes()
    assert export.read("LICENSE") == plugin_license
    assert export.read(f"{script.EXPORT_PLUGIN_DIR}/LICENSE") == plugin_license
    assert b"Apache License" in plugin_license


@pytest.mark.skipif(
    WINDOWS,
    reason=(
        "Windows has no executable bit to read: the export records the modes in "
        "EXPORT-MANIFEST.json instead, and the printed instructions tell the "
        "owner to run `git update-index --chmod=+x` on the two shims"
    ),
)
def test_the_shims_are_executable(export: Export, script: ModuleType) -> None:
    """The two programs the Bash tool runs keep their bit through the copy."""
    for name in script.EXECUTABLE_FILES:
        landed = export.out / script.EXPORT_PLUGIN_DIR / name
        assert landed.stat().st_mode & 0o777 == 0o755, f"{name} is not 0755"
    for path in export.paths():
        if path.endswith(tuple(script.EXECUTABLE_FILES)):
            continue
        mode = (export.out / path).stat().st_mode & 0o777
        assert mode == 0o644, f"{path} should be 0644, it is {mode:04o}"


def test_the_manifest_records_every_file(export: Export, script: ModuleType) -> None:
    """Hash and mode for everything, plus where the export came from."""
    manifest = export.json("EXPORT-MANIFEST.json")
    recorded = {entry["path"]: entry for entry in manifest["files"]}
    on_disk = [path for path in export.paths() if path != "EXPORT-MANIFEST.json"]
    assert sorted(recorded) == on_disk, "the manifest and the tree disagree"

    for path, entry in recorded.items():
        data = export.read(path)
        assert entry["sha256"] == hashlib.sha256(data).hexdigest(), f"{path} hash"
        assert entry["mode"] in {"0644", "0755"}, f"{path} mode {entry['mode']}"
        assert not path.startswith("/") and ":" not in path, f"{path} is not relative"

    plugin_manifest = json.loads((REPO_ROOT / script.PLUGIN_MANIFEST).read_text("utf-8"))
    assert manifest["plugin_version"] == plugin_manifest["version"]
    assert re.fullmatch(r"[0-9a-f]{40}|unknown", manifest["source_commit"]), (
        "the source commit should be a git object name"
    )
    assert manifest["source_path"] == "integrations/claude"


def test_both_json_files_are_canonical(export: Export) -> None:
    """Sorted keys, two-space indent, one trailing newline - so diffs are real."""
    for relative in (".claude-plugin/marketplace.json", "EXPORT-MANIFEST.json"):
        text = export.text(relative)
        rewritten = json.dumps(json.loads(text), indent=2, sort_keys=True) + "\n"
        assert text == rewritten, f"{relative} is not in the canonical form"


# ---------------------------------------------------------------------------
# Is it safe to publish?
# ---------------------------------------------------------------------------


def test_nothing_in_the_export_names_this_machine(export: Export) -> None:
    """No path from the machine that built it, anywhere in the tree."""
    forbidden = {
        str(REPO_ROOT),
        str(REPO_ROOT).replace("\\", "/"),
        str(export.out),
        str(export.out).replace("\\", "/"),
        str(Path.home()),
        str(Path.home()).replace("\\", "/"),
    }
    for path in export.paths():
        text = export.read(path).decode("utf-8", errors="replace")
        for needle in forbidden:
            assert needle not in text, f"{path} names {needle}"


def test_the_generated_files_carry_no_timestamp(export: Export) -> None:
    """Nothing dated: the same commit has to produce the same bytes."""
    for relative in GENERATED:
        text = export.text(relative)
        for pattern in TIMESTAMP_SHAPED:
            found = pattern.search(text)
            assert found is None, f"{relative} carries a timestamp: {found!r}"


def test_two_exports_are_byte_identical(
    script: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Determinism, the property that makes a re-export reviewable as a diff.

    ``find_claude`` is stubbed away because validating twice would only prove
    something another test already proves, and the CLI is slow.
    """
    monkeypatch.setattr(script, "find_claude", lambda: None)
    outs = []
    for name in ("first", "second"):
        out = tmp_path / name
        code = script.main(["--allow-dirty", "--root", str(REPO_ROOT), "--out", str(out)])
        assert code == 0
        outs.append(out)
    first, second = outs
    listed = sorted(str(p.relative_to(first)) for p in first.rglob("*") if p.is_file())
    assert listed == sorted(str(p.relative_to(second)) for p in second.rglob("*") if p.is_file())
    for relative in listed:
        assert (first / relative).read_bytes() == (second / relative).read_bytes(), (
            f"{relative} differs between two exports of one commit"
        )


def test_the_readme_and_privacy_are_fit_to_publish(export: Export) -> None:
    """The two files a stranger reads first, held to the house rules."""
    for relative in ("README.md", "PRIVACY.md"):
        text = export.text(relative)
        assert not KEY_SHAPED.search(text), f"{relative} contains a key-shaped string"
        assert "payload" not in text.lower(), f"{relative} says 'payload'"
        for pattern in MISSPELLED:
            found = pattern.search(text)
            assert found is None, f"{relative} misspells the name: {found!r}"
        found = VERSION_SHAPED.search(text)
        assert found is None, f"{relative} names a version that will go stale: {found!r}"
        assert "kn0wthyself.ai/legal/privacy" in text, f"{relative} omits the policy link"
        assert text.endswith("\n") and "\r" not in text, f"{relative} endings"


def test_the_readme_says_how_to_install_and_where_the_key_goes(export: Export) -> None:
    """The four things somebody who has never heard of s0ma needs from it."""
    readme = export.text("README.md")
    assert "/plugin marketplace add kn0w-thyself/claude-plugins" in readme
    assert "/plugin install s0ma@kn0wthyself" in readme
    assert "Enable auto-update" in readme, "the marketplace toggle is not explained"
    assert "account.kn0wthyself.ai" in readme, "where the key comes from"
    lowered = readme.lower()
    assert "never type a key into a conversation" in lowered
    assert "source checkout you need no key" in lowered, "the open-source route"
    assert "monorepo" in lowered, "where changes should be proposed"


def test_privacy_says_what_the_launcher_does_on_the_network(export: Export) -> None:
    """Specific, not a restated policy: one host, one header, one cadence."""
    privacy = export.text("PRIVACY.md")
    lowered = privacy.lower()
    assert "account.kn0wthyself.ai" in privacy, "the one host it talks to"
    assert "authorization header" in lowered, "where the key travels"
    assert "at most once a day" in lowered, "how often"
    assert "s0ma_update=off" in lowered, "how to switch it off"
    assert "no analytics" in lowered, "what it never sends"
    assert "this is not the privacy policy" in lowered, "it must not restate one"
    # Found at the D1 gate by tracing every request the launcher makes: an
    # install also has uv fetch s0ma's third-party dependencies from a package
    # index, and `pin` asks once whether the version exists. A note that said
    # "one place" and listed `pin` among the commands that open no connection
    # was not true, and this is the one page where that matters most.
    assert "python package index" in lowered, "uv's own fetch during an install"
    assert "removes your license key from uv's environment" in lowered
    assert "`s0ma-launch pin` asks once" in privacy, "pin's existence check"
    assert "`--offline`" in privacy, "and how to skip it"
    silent = privacy.split("launcher's other commands (", 1)[1].split(")", 1)[0]
    assert "`pin`" not in silent, "pin is not one of the commands that open no connection"
    assert "on windows it cannot" in lowered, "the key file's protection, per platform"


# ---------------------------------------------------------------------------
# The refusals. Nothing is written by any of these.
# ---------------------------------------------------------------------------


def test_refuses_an_out_directory_inside_the_repository() -> None:
    """The export becomes its own git repository; it cannot live in this one."""
    inside = REPO_ROOT / "build-export-that-should-never-exist"
    result = run_export("--allow-dirty", "--out", str(inside))
    assert result.returncode == 1
    assert "inside" in result.stderr and "Nothing was written." in result.stderr
    assert not inside.exists(), "a refused export created a directory anyway"


def test_refuses_a_directory_that_already_holds_something(tmp_path: Path) -> None:
    """Only what this run put there should end up published."""
    out = tmp_path / "not-empty"
    out.mkdir()
    (out / "notes.txt").write_text("mine\n", encoding="utf-8")
    result = run_export("--allow-dirty", "--out", str(out))
    assert result.returncode == 1
    assert "already has something in it" in result.stderr
    assert sorted(p.name for p in out.iterdir()) == ["notes.txt"], "it wrote anyway"


@pytest.fixture
def copied_tree(tmp_path: Path) -> Path:
    """A copy of the parts of the monorepo the export and the sync check read.

    It is deliberately not a git repository, so the git-cannot-vouch refusal
    can be provoked here too, and nothing any test does to it can reach the
    checkout.
    """
    root = tmp_path / "monorepo"
    (root / "packages" / "s0ma-mcp").mkdir(parents=True)
    shutil.copytree(
        REPO_ROOT / "integrations",
        root / "integrations",
        ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
    )
    shutil.copy2(
        REPO_ROOT / "packages" / "s0ma-mcp" / "pyproject.toml",
        root / "packages" / "s0ma-mcp" / "pyproject.toml",
    )
    return root


def test_refuses_when_a_shipped_copy_is_out_of_step(
    script: ModuleType,
    copied_tree: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """A stale launcher inside the plugin must never reach the public repository.

    The copy is exported once to prove it is sound, then the plugin's launcher
    is changed behind the sync script's back and the same export is refused -
    so the refusal is provably caused by the drift and not by the copy.
    """
    monkeypatch.setattr(script, "find_claude", lambda: None)
    sound = ["--allow-dirty", "--root", str(copied_tree), "--out", str(tmp_path / "before")]
    assert script.main(sound) == 0, "the copy should export cleanly before it is broken"

    stale = copied_tree / "integrations" / "claude" / "plugin" / "launcher" / "s0ma_launch.py"
    stale.write_bytes(stale.read_bytes() + b"\n# left behind by an old release\n")

    out = tmp_path / "after"
    code = script.main(["--allow-dirty", "--root", str(copied_tree), "--out", str(out)])
    assert code == 1
    message = capsys.readouterr().err
    assert "out of step" in message, message
    assert "launcher/s0ma_launch.py" in message, "the refusal must name the stale file"
    assert not out.exists(), "a refused export created a directory anyway"


def test_refuses_when_git_cannot_vouch_for_the_source(copied_tree: Path, tmp_path: Path) -> None:
    """Without ``--allow-dirty``, an unverifiable source tree is not exported."""
    out = tmp_path / "unverifiable"
    result = run_export("--root", str(copied_tree), "--out", str(out))
    assert result.returncode == 1
    assert "git could not say" in result.stderr
    assert not out.exists()


# ---------------------------------------------------------------------------
# It publishes nothing.
# ---------------------------------------------------------------------------


def test_prints_the_owner_commands_and_runs_none_of_them(
    export: Export, script: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The commands that publish are text on the screen, never a subprocess.

    Every ``subprocess.run`` the script makes is recorded and inspected: the
    only programs it may start are ``git``, to read the commit and the working
    tree, and ``claude``, to validate what was just written. Anything that
    creates a repository, pushes to one, or changes the reader's Claude is a
    failure here.
    """
    printed = export.result.stdout
    assert "gh repo create kn0w-thyself/claude-plugins --public" in printed
    assert "git init" in printed and "git add -A" in printed
    assert "git push" in printed, "the owner is told how to push"
    assert "git tag -a v" in printed, "a tag is suggested"
    assert "runs NONE of these" in printed
    assert "PUBLISHES it" in printed and "your act" in printed
    assert "Export again into a fresh empty directory" in printed

    calls: list[list[str]] = []
    real_run = subprocess.run

    def recorder(argv: Any, *args: Any, **kwargs: Any) -> Any:
        calls.append([str(part) for part in argv])
        return real_run(argv, *args, **kwargs)

    monkeypatch.setattr(script.subprocess, "run", recorder)
    again = ["--allow-dirty", "--root", str(REPO_ROOT), "--out", str(tmp_path / "watched")]
    assert script.main(again) == 0

    assert calls, "the script should at least have asked git for the commit"
    for argv in calls:
        # Windows spells these `git.exe` and `claude.cmd`, so match the stem.
        program = Path(argv[0]).name.lower()
        assert program.startswith(("git", "claude")), f"it ran {argv[0]}"
        assert "push" not in argv, f"it ran a push: {argv}"
        if program.startswith("git"):
            assert argv[3] in {"rev-parse", "status"}, f"git was asked to {argv[3]}"
        else:
            assert argv[1:3] == ["plugin", "validate"], f"claude was asked to {argv[1:3]}"
            assert "install" not in argv and "marketplace" not in argv


@pytest.mark.skipif(
    shutil.which("claude") is None,
    reason="no `claude` on PATH, so the CLI's own verdict on the export cannot be taken",
)
def test_the_claude_cli_accepts_the_export(export: Export) -> None:
    """Both halves validate: the marketplace, and the plugin inside it."""
    printed = export.result.stdout
    assert "the marketplace: accepted." in printed, printed
    assert "the plugin: accepted." in printed, printed
