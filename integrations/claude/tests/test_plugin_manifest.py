"""What the Claude Code plugin and the kn0wthyself marketplace must look like.

These tests pin the three JSON files, the two shell shims and the licence copy
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

import json
import os
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
PLUGIN_LAUNCHER = PLUGIN_DIR / "launcher" / "s0ma_launch.py"

SHIMS = (PLUGIN_DIR / "bin" / "s0ma", PLUGIN_DIR / "bin" / "s0ma-launch")

#: Where the one version number every s0ma package shares is written down.
LOCKSTEP_PYPROJECT = REPO_ROOT / "packages" / "s0ma-mcp" / "pyproject.toml"

#: The licence the plugin ships is the same file s0ma-core ships.
CANONICAL_LICENSE = REPO_ROOT / "packages" / "s0ma-core" / "LICENSE"

#: Manifest features the `claude` CLI on this machine's PATH (2.1.153) either
#: rejects outright or reports as an unknown field, which `--strict` turns into
#: a failure. Newer builds accept all three. Until the oldest supported CLI is
#: raised, the manifest may not use any of them (plan section 4.5).
FORBIDDEN_MANIFEST_KEYS = ("metadata", "defaultEnabled", "options")

WINDOWS = sys.platform.startswith("win")

#: Passed to every `claude` subprocess so a test run never reaches the network
#: for an update check it did not ask for.
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


def claude_cli() -> str | None:
    """The `claude` executable, if this machine has one on its PATH."""
    return shutil.which("claude")


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


def test_license_key_is_sensitive_and_optional() -> None:
    """A key is masked and kept in secure storage - and nobody is forced to have one.

    Somebody running s0ma from its source code, with ``S0MA_TOOLCHAIN`` pointing
    at their own checkout, has no key and must still be able to enable the
    plugin.
    """
    option = read_json(PLUGIN_MANIFEST)["userConfig"]["license_key"]
    assert option["type"] == "string"
    assert option["sensitive"] is True
    assert option.get("required", False) is False
    assert option["title"].strip()
    assert option["description"].strip()
    assert "default" not in option, "a licence key must never have a default value"


def test_update_and_uv_path_options() -> None:
    """The two plain settings, and the defaults the .mcp.json leans on.

    ``uv_path`` defaulting to ``uv`` is what makes ``${user_config.uv_path}`` in
    the server's ``command`` substitute to a bare ``uv`` when the user has
    stored nothing - proven in the P0 spike.
    """
    user_config = read_json(PLUGIN_MANIFEST)["userConfig"]

    update = user_config["update"]
    assert update["type"] == "string"
    assert update["default"] == "auto"
    assert not update.get("sensitive", False)

    uv_path = user_config["uv_path"]
    assert uv_path["type"] == "string"
    assert uv_path["default"] == "uv"
    assert not uv_path.get("sensitive", False)


def test_every_user_config_option_is_labelled() -> None:
    """`type`, `title` and `description` are required on every option."""
    for name, option in read_json(PLUGIN_MANIFEST)["userConfig"].items():
        for field in ("type", "title", "description"):
            assert option.get(field), f"userConfig.{name} is missing `{field}`"


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


def test_mcp_command_and_args() -> None:
    """The command the P0 spike proved, pointing at the launcher inside the plugin."""
    server = read_json(MCP_CONFIG)["mcpServers"]["s0ma"]
    assert server["command"] == "${user_config.uv_path}"
    assert server["args"] == [
        "run",
        "--script",
        "${CLAUDE_PLUGIN_ROOT}/launcher/s0ma_launch.py",
        "serve",
    ]


def test_mcp_env_carries_the_three_values_and_nothing_else() -> None:
    server = read_json(MCP_CONFIG)["mcpServers"]["s0ma"]
    assert sorted(server["env"]) == ["PATH", "S0MA_LICENSE_KEY", "S0MA_UPDATE"]
    assert server["env"]["S0MA_LICENSE_KEY"] == "${user_config.license_key}"
    assert server["env"]["S0MA_UPDATE"] == "${user_config.update}"


def test_mcp_path_is_widened_at_both_ends() -> None:
    """``${PATH}`` appears first and last, and the probe directories sit between.

    Windows joins its ``PATH`` with ``;``, so the colon-joined probe directories
    glue themselves onto whichever real entry they touch. Writing the real
    ``PATH`` at both ends means the first copy loses only its last entry to that
    glue and the second only its first, so every directory the user really has
    is searched in at least one of them (P0 spike, "Recommendation for P1").
    """
    path_value = read_json(MCP_CONFIG)["mcpServers"]["s0ma"]["env"]["PATH"]
    assert path_value.startswith("${PATH}"), "PATH must begin with the user's own PATH"
    assert path_value.endswith("${PATH}"), "PATH must end with the user's own PATH"
    assert path_value.count("${PATH}") == 2

    for probe in (
        "${HOME:-/nonexistent}/.local/bin",
        "${HOME:-/nonexistent}/.cargo/bin",
        "/opt/homebrew/bin",
        "/usr/local/bin",
    ):
        assert probe in path_value, f"the PATH widening is missing {probe}"

    # HOME carries a default because an unset variable with no default draws a
    # missing-variable warning, and HOME is usually unset on Windows.
    assert "${HOME}" not in path_value


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


@pytest.mark.parametrize("shim", SHIMS, ids=lambda path: path.name)
def test_shim_is_posix_sh(shim: Path) -> None:
    """A ``/bin/sh`` shebang, LF endings, plain ASCII, and no bash-only syntax."""
    raw = shim.read_bytes()
    assert raw.startswith(b"#!/bin/sh\n"), f"{shim.name} must start with #!/bin/sh"
    assert b"\r\n" not in raw, f"{shim.name} must use LF line endings"
    text = raw.decode("utf-8")
    assert text.isascii(), f"{shim.name} must be plain ASCII"
    for bashism in ("[[", "function ", "$(( ", "local ", "echo -e", "source "):
        assert bashism not in text, f"{shim.name} uses a bash-only form: {bashism}"


@pytest.mark.parametrize("shim", SHIMS, ids=lambda path: path.name)
def test_shim_finds_uv_the_same_way_the_server_does(shim: Path) -> None:
    """The shim's fallbacks match the ``PATH`` the ``.mcp.json`` hands the server.

    If the two lists ever diverge, ``s0ma doctor`` in a conversation and the MCP
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
    assert 'exec "$uv" run --script "$launcher" run -- s0ma "$@"' in s0ma.read_text(
        encoding="utf-8"
    )
    assert 'exec "$uv" run --script "$launcher" "$@"' in s0ma_launch.read_text(
        encoding="utf-8"
    )


@pytest.mark.skipif(
    WINDOWS, reason="Windows checkouts have no executable bit; the shims are POSIX-only"
)
@pytest.mark.parametrize("shim", SHIMS, ids=lambda path: path.name)
def test_shim_is_executable(shim: Path) -> None:
    """The exec bit is load-bearing: without it the spawn fails with EACCES (P0)."""
    mode = shim.stat().st_mode
    assert mode & 0o111 == 0o111, (
        f"{shim.name} is mode {mode & 0o777:o}; it needs to be 755"
    )


@pytest.mark.skipif(
    WINDOWS, reason="no POSIX shell to parse the shims with on Windows"
)
@pytest.mark.parametrize("shim", SHIMS, ids=lambda path: path.name)
def test_shim_parses_as_posix_sh(shim: Path) -> None:
    """``sh -n`` reads the whole file without running any of it."""
    result = subprocess.run(  # noqa: S603 - a fixed, local command
        ["/bin/sh", "-n", str(shim)], capture_output=True, text=True, timeout=60
    )
    assert result.returncode == 0, f"{shim.name} is not valid POSIX sh:\n{result.stderr}"


@pytest.mark.skipif(WINDOWS, reason="shellcheck is not run on Windows here")
@pytest.mark.parametrize("shim", SHIMS, ids=lambda path: path.name)
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


# ---------------------------------------------------------------------------
# The CLI's own verdict.
# ---------------------------------------------------------------------------


def test_plugin_manifest_validates() -> None:
    """`claude plugin validate` accepts the plugin, strictly where it can."""
    binary = claude_cli()
    if binary is None:
        pytest.skip("no `claude` on PATH, so the CLI's own verdict cannot be taken")
    result = run_validate(binary, PLUGIN_DIR)
    assert result.returncode == 0, (
        f"claude plugin validate rejected the plugin:\n{result.stdout}{result.stderr}"
    )


def test_marketplace_manifest_validates() -> None:
    """`claude plugin validate` accepts the marketplace, strictly where it can."""
    binary = claude_cli()
    if binary is None:
        pytest.skip("no `claude` on PATH, so the CLI's own verdict cannot be taken")
    result = run_validate(binary, MARKETPLACE_DIR)
    assert result.returncode == 0, (
        f"claude plugin validate rejected the marketplace:\n"
        f"{result.stdout}{result.stderr}"
    )
