"""What the Claude Code plugin and the kn0wthyself marketplace must look like.

These tests pin the three JSON files, the shell scripts and the licence copy
that make up the plugin, so that none of them can drift without somebody
noticing. They are deliberately cheap: nothing here opens a socket, nothing
writes to disk, and the only subprocess is the ``claude`` CLI's own offline
``plugin validate``.

Two things this file deliberately does **not** test:

* **Byte-identity of the launcher copy.** ``plugin/launcher/s0ma_launch.py`` is
  a copy of ``integrations/launcher/s0ma_launch.py``, and keeping the two in
  step is the sync script's job (plan section 4.6, milestone Q1). While the
  launcher is still being written the copy is expected to be behind, so a
  byte-identity test here would only produce noise. All that is asserted below
  is that the file the plugin's ``.mcp.json`` points at exists and is the
  launcher.
* **Anything that would change the reader's Claude configuration.** No plugin
  is installed, no marketplace is added, and nothing under ``~/.claude`` is
  read or written.

The marketplace manifest lives at ``integrations/claude/.claude-plugin/`` so
that its relative source (``./plugin``) stays inside the marketplace root -
both CLI builds refuse a source that climbs out with ``..``.
"""

from __future__ import annotations

import importlib
import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
import tomllib
from pathlib import Path
from typing import Any

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
CLAUDE_DIR = REPO_ROOT / "integrations" / "claude"
PLUGIN_DIR = CLAUDE_DIR / "plugin"
#: The marketplace root is the directory that CONTAINS ``.claude-plugin/``. It
#: sits AROUND the plugin, not beside it: the CLI resolves a plugin source
#: against the marketplace root and refuses any source containing "..", so a
#: sibling layout cannot carry a relative source (found by P1, ruled at its gate).
MARKETPLACE_DIR = CLAUDE_DIR

PLUGIN_MANIFEST = PLUGIN_DIR / ".claude-plugin" / "plugin.json"
MCP_CONFIG = PLUGIN_DIR / ".mcp.json"
MARKETPLACE_MANIFEST = MARKETPLACE_DIR / ".claude-plugin" / "marketplace.json"
PLUGIN_LICENSE = PLUGIN_DIR / "LICENSE"
PLUGIN_README = PLUGIN_DIR / "README.md"
PLUGIN_LAUNCHER = PLUGIN_DIR / "launcher" / "s0ma_launch.py"

SHIMS = (PLUGIN_DIR / "bin" / "s0ma", PLUGIN_DIR / "bin" / "s0ma-launch")

#: The two other POSIX scripts: the session-start hook and the server script.
HOOK_SCRIPT = PLUGIN_DIR / "hooks" / "session-start.sh"
SERVER_SCRIPT = PLUGIN_DIR / "scripts" / "s0ma-serve"

#: Every POSIX sh file in the plugin, held to the same house rules.
SH_SCRIPTS = (*SHIMS, HOOK_SCRIPT, SERVER_SCRIPT)

#: The ones that are run by their own path, so their executable bit matters.
#: The hook script is run as `sh <path>` and needs none.
EXECUTABLE_SCRIPTS = (*SHIMS, SERVER_SCRIPT)

#: Where the one version number every s0ma package shares is written down.
LOCKSTEP_PYPROJECT = REPO_ROOT / "packages" / "s0ma-mcp" / "pyproject.toml"

#: The licence the plugin ships is the same file s0ma-lang-core ships.
CANONICAL_LICENSE = REPO_ROOT / "packages" / "s0ma-core" / "LICENSE"

#: Manifest features the `claude` CLI on this machine's PATH (2.1.153) either
#: rejects outright or reports as an unknown field, which `--strict` turns into
#: a failure. Newer builds accept all three. Until the oldest supported CLI is
#: raised, the manifest may not use any of them (plan section 4.5). `network`
#: is the one key above that floor: it is kept because the runtime tolerates a
#: field it does not know, and only strict validation needs the newer CLI
#: (CLAUDE_FLOOR below).
FORBIDDEN_MANIFEST_KEYS = ("metadata", "defaultEnabled", "options")

WINDOWS = sys.platform.startswith("win")

#: Passed to every `claude` subprocess so a test run never reaches the network
#: for an update check it did not ask for.
#: The oldest `claude` whose strict validation knows every manifest field the
#: plugin uses: ``network`` arrived in Claude Code 2.1.328. Below it the
#: verdict tests skip, since the runtime tolerates a field it does not know.
CLAUDE_FLOOR = (2, 1, 328)

OFFLINE_ENV = {
    "DISABLE_AUTOUPDATER": "1",
    "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC": "1",
}


# ---------------------------------------------------------------------------
# Helpers.
# ---------------------------------------------------------------------------


def read_json(path: Path) -> dict[str, Any]:
    """Load one of the manifests, failing with a readable message if it is not JSON."""
    raw = path.read_bytes()
    try:
        data = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:  # pragma: no cover
        raise AssertionError(f"{path.name} is not valid UTF-8 JSON: {exc}") from exc
    assert isinstance(data, dict), f"{path.name} must hold a JSON object"
    return data


def find_keys(node: Any, wanted: str) -> list[str]:
    """Every path inside *node* at which a mapping has the key *wanted*."""
    found: list[str] = []

    def walk(value: Any, where: str) -> None:
        if isinstance(value, dict):
            for key, child in value.items():
                spot = f"{where}.{key}" if where else key
                if key == wanted:
                    found.append(spot)
                walk(child, spot)
        elif isinstance(value, list):
            for index, child in enumerate(value):
                walk(child, f"{where}[{index}]")

    walk(node, "")
    return found


def lockstep_version() -> str:
    """The one version string the whole monorepo moves together."""
    with LOCKSTEP_PYPROJECT.open("rb") as handle:
        data = tomllib.load(handle)
    version = data["project"]["version"]
    assert isinstance(version, str) and version, "the lockstep version must be a string"
    return version


def claude_version(binary: str) -> tuple[int, int, int] | None:
    """The version `claude --version` reports, or ``None`` if it cannot be read."""
    try:
        result = subprocess.run(  # noqa: S603 - a fixed, local command
            [binary, "--version"],
            capture_output=True,
            text=True,
            timeout=120,
            env={**os.environ, **OFFLINE_ENV},
        )
    except (OSError, subprocess.SubprocessError):
        return None
    found = re.search(r"\b(\d+)\.(\d+)\.(\d+)\b", result.stdout)
    if result.returncode != 0 or found is None:
        return None
    major, minor, patch = (int(part) for part in found.groups())
    return (major, minor, patch)


def too_old_to_validate(binary: str) -> str | None:
    """Why this `claude` cannot give a strict verdict on the plugin, or ``None``."""
    version = claude_version(binary)
    needed = ".".join(str(part) for part in CLAUDE_FLOOR)
    if version is None:
        return (
            f"`claude --version` printed nothing this suite can read, so it is taken "
            f"as older than {needed}, which strict validation of `network` needs"
        )
    if version < CLAUDE_FLOOR:
        found = ".".join(str(part) for part in version)
        return f"`claude` is {found}; strict validation of `network` needs {needed} or newer"
    return None


def claude_for_validation() -> str:
    """The `claude` to take a strict verdict from, or a skip that says why not."""
    binary = shutil.which("claude")
    if binary is None:
        pytest.skip("no `claude` on PATH, so the CLI's own verdict cannot be taken")
    reason = too_old_to_validate(binary)
    if reason is not None:
        pytest.skip(reason)
    return binary


def validate_supports_strict(binary: str) -> bool:
    """Whether this build of `claude plugin validate` understands ``--strict``."""
    result = subprocess.run(  # noqa: S603 - a fixed, local command
        [binary, "plugin", "validate", "--help"],
        capture_output=True,
        text=True,
        timeout=120,
        env={**os.environ, **OFFLINE_ENV},
    )
    return "--strict" in (result.stdout + result.stderr)


def run_validate(binary: str, target: Path) -> subprocess.CompletedProcess[str]:
    """Run `claude plugin validate` on *target*, strictly where that is supported.

    ``--json`` is never passed: the CLI on this machine's PATH does not have it,
    and the exit code carries everything these tests need.
    """
    argv = [binary, "plugin", "validate", str(target)]
    if validate_supports_strict(binary):
        argv.append("--strict")
    return subprocess.run(  # noqa: S603 - a fixed, local command
        argv,
        capture_output=True,
        text=True,
        timeout=300,
        env={**os.environ, **OFFLINE_ENV},
    )


# ---------------------------------------------------------------------------
# Every committed JSON file is canonical.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "path",
    [PLUGIN_MANIFEST, MCP_CONFIG, MARKETPLACE_MANIFEST],
    ids=lambda path: path.name,
)
def test_json_is_canonical(path: Path) -> None:
    """Two-space indent, sorted keys, plain ASCII, LF endings, one trailing newline.

    Sorted keys are the house rule for anything committed (plan section 3.1
    rule 9): the same content always produces the same bytes, so a diff only
    ever shows a real change.
    """
    raw = path.read_bytes()
    assert b"\r\n" not in raw, f"{path.name} must use LF line endings"
    text = raw.decode("utf-8")
    assert text.isascii(), f"{path.name} must be plain ASCII"
    canonical = json.dumps(json.loads(text), indent=2, sort_keys=True) + "\n"
    assert text == canonical, (
        f"{path.name} is not in canonical form. Rewrite it with "
        "json.dumps(data, indent=2, sort_keys=True) and a trailing newline."
    )


# ---------------------------------------------------------------------------
# plugin.json.
# ---------------------------------------------------------------------------


def test_plugin_manifest_identity() -> None:
    """The fields that say what this plugin is and who stands behind it."""
    manifest = read_json(PLUGIN_MANIFEST)
    assert manifest["name"] == "s0ma"
    assert manifest["license"] == "Apache-2.0"
    assert manifest["homepage"] == "https://kn0wthyself.ai"
    assert manifest["repository"] == "https://github.com/kn0w-thyself/claude-plugins"
    assert manifest["author"]["name"] == "kn0wthyself"
    assert manifest["description"].strip()
    assert isinstance(manifest["keywords"], list) and manifest["keywords"]
    assert "s0ma" in manifest["keywords"]


def test_plugin_version_is_the_lockstep_version() -> None:
    """The plugin moves with the rest of s0ma, not on a schedule of its own.

    Claude Code treats ``version`` in ``plugin.json`` as a pin: users receive an
    update only when this string changes. Reading the number the packages
    already agree on is what keeps that promise honest.
    """
    manifest = read_json(PLUGIN_MANIFEST)
    assert manifest["version"] == lockstep_version()


def test_the_plugin_asks_nothing_at_install() -> None:
    """No ``userConfig``, so Claude Code opens no settings dialog at install.

    A key is saved with ``s0ma-launch activate``, the update preference with
    ``s0ma-launch set update``, and uv is found by the scripts themselves.
    """
    manifest = read_json(PLUGIN_MANIFEST)
    assert "userConfig" not in manifest
    assert find_keys(manifest, "userConfig") == []


def declared_hosts() -> list[str]:
    """What ``network.hosts`` in the plugin manifest lists."""
    network = read_json(PLUGIN_MANIFEST).get("network")
    assert isinstance(network, dict), "plugin.json declares no `network` block"
    hosts = network.get("hosts")
    assert isinstance(hosts, list) and hosts, "plugin.json declares no hosts"
    assert all(isinstance(host, str) for host in hosts)
    return hosts


#: A bare hostname or a ``*.`` wildcard: no scheme, no path, no port.
HOST_SHAPED = re.compile(r"(\*\.)?[a-z0-9]([a-z0-9-]*[a-z0-9])?(\.[a-z0-9]([a-z0-9-]*[a-z0-9])?)*")


def test_the_declared_hosts_are_bare_hostnames() -> None:
    """``network.hosts`` is written in the sandbox's domain syntax, not as URLs."""
    hosts = declared_hosts()
    assert hosts == sorted(set(hosts)), "list each host once, sorted"
    for host in hosts:
        assert HOST_SHAPED.fullmatch(host), f"{host!r} is not a bare hostname"


def test_the_control_plane_host_is_the_launchers_own() -> None:
    """The host the manifest declares is the one the launcher's constant names."""
    spec = importlib.util.spec_from_file_location(
        "s0ma_launch_for_manifest_tests", PLUGIN_LAUNCHER
    )
    assert spec is not None and spec.loader is not None
    launcher = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = launcher
    spec.loader.exec_module(launcher)
    assert launcher.DEFAULT_CP_HOST in declared_hosts()


def test_the_readme_names_every_declared_host() -> None:
    """Whatever the manifest says the plugin can reach, its README says too.

    A wildcard entry such as ``*.example.com`` is named by the domain it
    covers, ``example.com``: a README speaks of a host family by its domain.
    """
    readme = PLUGIN_README.read_text(encoding="utf-8")
    fetches = readme.split("## What it fetches, and when", 1)
    assert len(fetches) == 2, "the README has no 'What it fetches, and when' section"
    section = fetches[1].split("\n## ", 1)[0]
    missing = [
        host for host in declared_hosts() if host.removeprefix("*.") not in section
    ]
    assert missing == [], f"the README's fetch section does not name {missing}"


@pytest.mark.parametrize("key", FORBIDDEN_MANIFEST_KEYS)
def test_manifest_avoids_keys_the_oldest_cli_refuses(key: str) -> None:
    """Nothing in the manifest may depend on a CLI newer than the floor.

    ``options`` is rejected outright by 2.1.153; ``metadata`` and
    ``defaultEnabled`` are reported as unknown fields, which ``--strict`` turns
    into a failure. Raising the floor is a decision, not an accident, so the
    three are pinned out until somebody takes it.
    """
    hits = find_keys(read_json(PLUGIN_MANIFEST), key)
    assert hits == [], f"plugin.json uses `{key}` at: {', '.join(hits)}"


# ---------------------------------------------------------------------------
# .mcp.json - the block the P0 spike froze.
# ---------------------------------------------------------------------------


def test_mcp_config_declares_exactly_one_server() -> None:
    config = read_json(MCP_CONFIG)
    assert list(config) == ["mcpServers"]
    assert list(config["mcpServers"]) == ["s0ma"]


def test_mcp_command_is_the_server_script() -> None:
    """The script pair under the plugin root: ``s0ma-serve``, and on Windows the
    ``s0ma-serve.cmd`` beside it. It finds uv itself, so the server needs no
    arguments and no environment of its own."""
    server = read_json(MCP_CONFIG)["mcpServers"]["s0ma"]
    assert server == {"command": "${CLAUDE_PLUGIN_ROOT}/scripts/s0ma-serve"}
    script = PLUGIN_DIR / "scripts" / "s0ma-serve"
    assert script.is_file(), f"{script} is missing"
    assert (PLUGIN_DIR / "scripts" / "s0ma-serve.cmd").is_file()


def test_mcp_config_points_at_a_launcher_that_is_there() -> None:
    """The file ``.mcp.json`` names exists and really is the launcher.

    This is not the byte-identity gate - that belongs to the sync script (Q1).
    It only catches a plugin that would ship with nothing to run.
    """
    assert PLUGIN_LAUNCHER.is_file(), f"{PLUGIN_LAUNCHER} is missing"
    head = PLUGIN_LAUNCHER.read_bytes()[:200].decode("utf-8")
    assert head.startswith("# /// script"), "the launcher copy needs its PEP 723 header"
    assert "dependencies = []" in head


# ---------------------------------------------------------------------------
# The licence.
# ---------------------------------------------------------------------------


def test_license_is_the_same_file_s0ma_core_ships() -> None:
    """Byte-for-byte, so the plugin's licence can never quietly become a variant."""
    assert PLUGIN_LICENSE.read_bytes() == CANONICAL_LICENSE.read_bytes()


# ---------------------------------------------------------------------------
# The shims.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("shim", SH_SCRIPTS, ids=lambda path: path.name)
def test_shim_is_posix_sh(shim: Path) -> None:
    """A ``/bin/sh`` shebang, LF endings, plain ASCII, and no bash-only syntax."""
    raw = shim.read_bytes()
    assert raw.startswith(b"#!/bin/sh\n"), f"{shim.name} must start with #!/bin/sh"
    assert b"\r\n" not in raw, f"{shim.name} must use LF line endings"
    text = raw.decode("utf-8")
    assert text.isascii(), f"{shim.name} must be plain ASCII"
    # A POSIX character class such as ``[[:space:]]`` inside a sed pattern is
    # not bash's ``[[`` test, so it is taken out before looking.
    text = re.sub(r"\[\[:[a-z]+:\]", "", text)
    for bashism in ("[[", "function ", "$(( ", "local ", "echo -e", "source "):
        assert bashism not in text, f"{shim.name} uses a bash-only form: {bashism}"


@pytest.mark.parametrize("shim", SHIMS, ids=lambda path: path.name)
def test_shim_finds_uv_the_same_way_the_server_does(shim: Path) -> None:
    """The shim looks where the server script does.

    The full list is held equal to the launcher's own by
    ``test_plugin_rules.py``; this is the quick read of it. If the lists ever
    diverge, ``s0ma doctor`` in a conversation and the MCP
    server itself would disagree about whether uv exists - the most confusing
    failure this design can produce.
    """
    text = shim.read_text(encoding="utf-8")
    for probe in (
        "${HOME:-/nonexistent}/.local/bin",
        "${HOME:-/nonexistent}/.cargo/bin",
        "/opt/homebrew/bin",
        "/usr/local/bin",
    ):
        assert probe in text, f"{shim.name} does not look in {probe}"
    assert "command -v uv" in text, f"{shim.name} must try the PATH first"
    assert "https://astral.sh/uv/install.sh" in text, (
        f"{shim.name} must tell the reader how to install uv"
    )


def test_shims_call_the_launcher_correctly() -> None:
    """``s0ma`` runs a toolchain program; ``s0ma-launch`` is the launcher itself."""
    s0ma, s0ma_launch = SHIMS
    assert 'exec "$uv" run --frozen --script "$launcher" run -- s0ma "$@"' in s0ma.read_text(
        encoding="utf-8"
    )
    assert 'exec "$uv" run --frozen --script "$launcher" "$@"' in s0ma_launch.read_text(
        encoding="utf-8"
    )


@pytest.mark.skipif(
    WINDOWS, reason="Windows checkouts have no executable bit; the shims are POSIX-only"
)
@pytest.mark.parametrize("shim", EXECUTABLE_SCRIPTS, ids=lambda path: path.name)
def test_shim_is_executable(shim: Path) -> None:
    """The exec bit is load-bearing: without it the spawn fails with EACCES (P0)."""
    mode = shim.stat().st_mode
    assert mode & 0o111 == 0o111, (
        f"{shim.name} is mode {mode & 0o777:o}; it needs to be 755"
    )


@pytest.mark.skipif(
    WINDOWS, reason="no POSIX shell to parse the shims with on Windows"
)
@pytest.mark.parametrize("shim", SH_SCRIPTS, ids=lambda path: path.name)
def test_shim_parses_as_posix_sh(shim: Path) -> None:
    """``sh -n`` reads the whole file without running any of it."""
    result = subprocess.run(  # noqa: S603 - a fixed, local command
        ["/bin/sh", "-n", str(shim)], capture_output=True, text=True, timeout=60
    )
    assert result.returncode == 0, f"{shim.name} is not valid POSIX sh:\n{result.stderr}"


@pytest.mark.skipif(WINDOWS, reason="shellcheck is not run on Windows here")
@pytest.mark.parametrize("shim", SH_SCRIPTS, ids=lambda path: path.name)
def test_shim_passes_shellcheck(shim: Path) -> None:
    """Run shellcheck when the machine has it, and say so plainly when it does not."""
    shellcheck = shutil.which("shellcheck")
    if shellcheck is None:
        pytest.skip("shellcheck is not installed on this machine")
    result = subprocess.run(  # noqa: S603 - a fixed, local command
        [shellcheck, "--shell=sh", str(shim)],
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert result.returncode == 0, f"shellcheck on {shim.name}:\n{result.stdout}"


# ---------------------------------------------------------------------------
# marketplace.json.
# ---------------------------------------------------------------------------


def test_marketplace_identity() -> None:
    """``/plugin install s0ma@kn0wthyself`` is the line this makes true."""
    manifest = read_json(MARKETPLACE_MANIFEST)
    assert manifest["name"] == "kn0wthyself"
    assert manifest["owner"]["name"] == "kn0wthyself"
    assert manifest["owner"]["url"] == "https://kn0wthyself.ai"
    assert len(manifest["plugins"]) == 1
    assert manifest["plugins"][0]["name"] == "s0ma"


def test_marketplace_source_resolves_to_the_plugin_directory() -> None:
    """The entry's relative source reaches the plugin in this repository.

    The CLI resolves a relative source against the marketplace root - the
    directory that holds ``.claude-plugin/`` - not against the manifest file.
    """
    source = read_json(MARKETPLACE_MANIFEST)["plugins"][0]["source"]
    assert isinstance(source, str), "the local-development source is a relative path"
    assert not Path(source).is_absolute(), "the source must be relative, not absolute"
    resolved = (MARKETPLACE_DIR / source).resolve()
    assert resolved == PLUGIN_DIR.resolve(), (
        f"the source {source!r} resolves to {resolved}, not to the plugin directory"
    )
    assert (resolved / ".claude-plugin" / "plugin.json").is_file()


def test_marketplace_and_plugin_describe_the_plugin_the_same_way() -> None:
    """One sentence, written once - so the catalog and the plugin cannot disagree."""
    entry = read_json(MARKETPLACE_MANIFEST)["plugins"][0]
    assert entry["description"] == read_json(PLUGIN_MANIFEST)["description"]


def test_marketplace_entry_does_not_restate_the_version() -> None:
    """``plugin.json`` wins over the marketplace entry, so only one file carries it."""
    entry = read_json(MARKETPLACE_MANIFEST)["plugins"][0]
    assert "version" not in entry


def test_a_new_project_names_this_catalog_and_this_plugin() -> None:
    """``s0ma new project`` writes ``.claude/settings.json`` naming the catalog
    and the plugin, so its names are these manifests' names and its catalog
    repository is the one the plugin says it is published from. The
    comparison sits here because this suite may read the language package
    and the language package reads nothing under ``integrations/``."""
    new_project = importlib.import_module("s0ma_dsl.cli.new_project")
    marketplace = read_json(MARKETPLACE_MANIFEST)
    plugin = read_json(PLUGIN_MANIFEST)
    assert new_project.PLUGIN_MARKETPLACE_NAME == marketplace["name"]
    assert new_project.PLUGIN_NAME == plugin["name"]
    assert new_project.PLUGIN_NAME == marketplace["plugins"][0]["name"]
    assert plugin["repository"] == (
        f"https://github.com/{new_project.PLUGIN_MARKETPLACE_REPO}"
    )
    settings = json.loads(new_project._project_settings_json())
    assert settings["enabledPlugins"] == {
        f"{plugin['name']}@{marketplace['name']}": True
    }
    assert list(settings["extraKnownMarketplaces"]) == [marketplace["name"]]


# ---------------------------------------------------------------------------
# The CLI's own verdict.
# ---------------------------------------------------------------------------


def test_plugin_manifest_validates() -> None:
    """`claude plugin validate` accepts the plugin, strictly where it can."""
    binary = claude_for_validation()
    result = run_validate(binary, PLUGIN_DIR)
    assert result.returncode == 0, (
        f"claude plugin validate rejected the plugin:\n{result.stdout}{result.stderr}"
    )


def test_marketplace_manifest_validates() -> None:
    """`claude plugin validate` accepts the marketplace, strictly where it can."""
    binary = claude_for_validation()
    result = run_validate(binary, MARKETPLACE_DIR)
    assert result.returncode == 0, (
        f"claude plugin validate rejected the marketplace:\n"
        f"{result.stdout}{result.stderr}"
    )


# ---------------------------------------------------------------------------
# Which `claude` a verdict is taken from. No real Claude runs here.
# ---------------------------------------------------------------------------

STAND_IN_CLI = """\
#!/bin/sh
# Prints what a `claude --version` of some build would.
case "$1" in
    --version) printf '%s\\n' "{printed}" ;;
    *) echo "this stand-in only knows --version" >&2; exit 2 ;;
esac
"""


def stand_in_cli(where: Path, printed: str) -> str:
    fake = where / "stand-in-cli"
    fake.write_text(STAND_IN_CLI.replace("{printed}", printed), encoding="utf-8")
    fake.chmod(0o755)
    return str(fake)


@pytest.mark.skipif(WINDOWS, reason="the stand-in CLI is a sh script")
@pytest.mark.parametrize(
    ("printed", "skipped", "named"),
    [
        ("2.1.311 (Claude Code)", True, ("2.1.311", "2.1.328")),
        ("2.1.330 (Claude Code)", False, ()),
        ("Claude Code, some build", True, ("nothing this suite can read", "2.1.328")),
    ],
)
def test_a_claude_below_the_floor_is_skipped_and_says_why(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    printed: str,
    skipped: bool,
    named: tuple[str, ...],
) -> None:
    fake = stand_in_cli(tmp_path, printed)
    monkeypatch.setattr(shutil, "which", lambda name, *a, **k: fake if name == "claude" else None)
    if skipped:
        with pytest.raises(pytest.skip.Exception) as raised:
            claude_for_validation()
        for words in named:
            assert words in str(raised.value), str(raised.value)
    else:
        assert claude_for_validation() == fake
