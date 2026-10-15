"""What the Claude Desktop extension must look like, and what packing it must do.

The extension is the second of the two wrappers around one launcher (plan
``beta-prep-2-claude``, decision CD-6). Claude Code gets a plugin; Claude
Desktop gets an ``.mcpb`` bundle. Both start the same file the same way, so the
things these tests hold still are the things a person would notice if they
drifted: which key reaches the launcher, which platforms the bundle claims,
which version it says it is, and the promise that a privacy policy exists.

The manifest follows **MCPB manifest spec 0.4**, read from
``modelcontextprotocol/mcpb`` on 2026-09-17: ``src/schemas/0.4.ts`` for the
schema (it is the authority - ``MANIFEST.md``'s own header is stale) and
``examples/hello-world-uv/`` for the shape of a ``uv`` extension.

Three things this file deliberately does **not** do:

* **Byte-identity of the launcher copy.** ``desktop/server/s0ma_launch.py`` is a
  copy of ``integrations/launcher/s0ma_launch.py``; keeping the two in step is
  the sync script's job (plan section 4.6, milestone Q1). All that is asserted
  here is that the file the manifest points at exists and really is the launcher.
* **Anything over the network.** No URL in the manifest is fetched. The
  privacy-policy test below is a reminder, not a liveness check.
* **Anything that installs software.** ``mcpb`` is used only if this machine
  already has it; nothing here runs ``npx`` or ``npm install``.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import sys
import tomllib
from pathlib import Path
from typing import Any

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
CLAUDE_DIR = REPO_ROOT / "integrations" / "claude"
DESKTOP_DIR = CLAUDE_DIR / "desktop"

MANIFEST = DESKTOP_DIR / "manifest.json"
DESKTOP_PYPROJECT = DESKTOP_DIR / "pyproject.toml"
DESKTOP_LAUNCHER = DESKTOP_DIR / "server" / "s0ma_launch.py"
PACK_SCRIPT = REPO_ROOT / "scripts" / "pack_desktop_extension.sh"

#: Where the one version number every s0ma package shares is written down.
LOCKSTEP_PYPROJECT = REPO_ROOT / "packages" / "s0ma-mcp" / "pyproject.toml"

#: The real server's surface, recorded by its own test suite. The extension's
#: tool list is checked against this rather than against a second hand-kept copy.
MCP_SURFACE = (
    REPO_ROOT / "packages" / "s0ma-mcp" / "tests" / "snapshots" / "mcp_surface.json"
)

#: The one tool the launcher's built-in stub offers when s0ma is not installed
#: yet. It is in the manifest because it is the first tool many people will meet.
STUB_TOOL = "s0ma_setup_status"

#: The policy plan 5 will publish. Nothing may be submitted to Anthropic's
#: directory until this URL answers: "Missing or incomplete privacy policies
#: result in immediate rejection" (research note section 4.4).
PRIVACY_POLICY_URL = "https://kn0wthyself.ai/legal/privacy"

#: Spec 0.4, `src/schemas/0.4.ts`: everything else in the manifest is optional.
REQUIRED_MANIFEST_FIELDS = ("name", "version", "description", "author", "server")

WINDOWS = sys.platform.startswith("win")


# ---------------------------------------------------------------------------
# Helpers.
# ---------------------------------------------------------------------------


def read_json(path: Path) -> dict[str, Any]:
    """Load a manifest, failing with a readable message if it is not JSON."""
    raw = path.read_bytes()
    try:
        data = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:  # pragma: no cover
        raise AssertionError(f"{path.name} is not valid UTF-8 JSON: {exc}") from exc
    assert isinstance(data, dict), f"{path.name} must hold a JSON object"
    return data


def manifest() -> dict[str, Any]:
    return read_json(MANIFEST)


def lockstep_version() -> str:
    """The one version string the whole monorepo moves together."""
    with LOCKSTEP_PYPROJECT.open("rb") as handle:
        data = tomllib.load(handle)
    version = data["project"]["version"]
    assert isinstance(version, str) and version, "the lockstep version must be a string"
    return version


def real_server_tools() -> list[str]:
    """Every tool the real ``s0ma-mcp`` offers, by name."""
    surface = json.loads(MCP_SURFACE.read_text(encoding="utf-8"))
    return sorted(tool["name"] for tool in surface["tools"])


def real_server_tool_records() -> list[dict[str, Any]]:
    surface = json.loads(MCP_SURFACE.read_text(encoding="utf-8"))
    tools = surface["tools"]
    assert isinstance(tools, list) and tools
    return tools


def tree_digest(root: Path) -> dict[str, str]:
    """Path-to-hash for every file under *root*, ignoring Python's own caches."""
    digest: dict[str, str] = {}
    for path in sorted(root.rglob("*")):
        if not path.is_file() or "__pycache__" in path.parts:
            continue
        key = path.relative_to(root).as_posix()
        digest[key] = hashlib.sha256(path.read_bytes()).hexdigest()
    return digest


# ---------------------------------------------------------------------------
# The committed files are canonical.
# ---------------------------------------------------------------------------


def test_manifest_is_canonical_json() -> None:
    """Two-space indent, sorted keys, plain ASCII, LF endings, one trailing newline.

    Sorted keys are the house rule for anything committed (plan section 3.1,
    rule 9): the same content always produces the same bytes, so a diff only
    ever shows a real change. The pack script also leans on the two-space indent
    when it reads the version out with ``sed``.
    """
    raw = MANIFEST.read_bytes()
    assert b"\r\n" not in raw, "manifest.json must use LF line endings"
    text = raw.decode("utf-8")
    assert text.isascii(), "manifest.json must be plain ASCII"
    canonical = json.dumps(json.loads(text), indent=2, sort_keys=True) + "\n"
    assert text == canonical, (
        "manifest.json is not in canonical form. Rewrite it with "
        "json.dumps(data, indent=2, sort_keys=True) and a trailing newline."
    )


# ---------------------------------------------------------------------------
# Spec 0.4: the fields the schema demands.
# ---------------------------------------------------------------------------


def test_manifest_version_is_the_spec_this_was_written_against() -> None:
    """0.4 is what adds ``server.type: "uv"`` - the whole reason this bundle is thin."""
    data = manifest()
    assert data["manifest_version"] == "0.4"
    assert "dxt_version" not in data, (
        "dxt_version is the deprecated spelling; exactly one of the two may appear"
    )


@pytest.mark.parametrize("field", REQUIRED_MANIFEST_FIELDS)
def test_required_field_is_present(field: str) -> None:
    value = manifest().get(field)
    assert value, f"manifest.json is missing the required field `{field}`"


def test_identity_and_who_stands_behind_it() -> None:
    """The fields a person reads on the install screen before trusting anything."""
    data = manifest()
    assert data["name"] == "s0ma"
    assert data["display_name"] == "s0ma"
    assert data["license"] == "Apache-2.0"
    assert data["homepage"] == "https://kn0wthyself.ai"
    assert data["support"] == "https://github.com/kn0w-thyself/claude-plugins"
    assert data["author"] == {"name": "kn0wthyself", "url": "https://kn0wthyself.ai"}
    # Spec 0.4 makes `repository` an object, unlike the Claude Code plugin
    # manifest where the same idea is a bare string.
    assert data["repository"] == {
        "type": "git",
        "url": "https://github.com/kn0w-thyself/claude-plugins",
    }
    assert "s0ma" in data["keywords"]


def test_version_is_the_lockstep_version() -> None:
    """The extension moves with the rest of s0ma, not on a schedule of its own.

    The literal is written in the file so the bundle is readable on its own; this
    test is what keeps it honest, and the sync script (milestone Q1) is what
    moves it.
    """
    assert manifest()["version"] == lockstep_version()


def test_no_icon_is_promised_that_is_not_there() -> None:
    """A manifest naming a missing file packs into a broken bundle."""
    data = manifest()
    for field in ("icon",):
        named = data.get(field)
        if named:
            assert (DESKTOP_DIR / named).is_file(), (
                f"manifest.json names {field} {named!r}, which is not in the bundle"
            )
    assert "icons" not in data or data["icons"], "an empty icons list says nothing"


# ---------------------------------------------------------------------------
# The server block.
# ---------------------------------------------------------------------------


def test_server_is_a_uv_extension_pointing_at_the_launcher() -> None:
    """``uv`` is the type that needs neither a bundled Python nor bundled packages.

    ``mcp_config`` is present although ``MANIFEST.md`` calls it optional for this
    type: ``src/schemas/0.4.ts`` declares the server object with
    ``z.strictObject`` and does **not** mark ``mcp_config`` optional, and the
    project's own ``examples/hello-world-uv`` ships one. The schema is what
    ``mcpb validate`` runs, so the schema wins.
    """
    server = manifest()["server"]
    assert sorted(server) == ["entry_point", "mcp_config", "type"]
    assert server["type"] == "uv"
    assert server["entry_point"] == "server/s0ma_launch.py"
    assert server["mcp_config"]["command"] == "uv"
    assert server["mcp_config"]["args"] == [
        "run",
        "--directory",
        "${__dirname}",
        "server/s0ma_launch.py",
        "serve",
    ]


def test_entry_point_is_there_and_is_the_launcher() -> None:
    """The file the manifest names exists and really is the launcher.

    This is not the byte-identity gate - that belongs to the sync script (Q1).
    It only catches a bundle that would ship with nothing to run.
    """
    entry = manifest()["server"]["entry_point"]
    target = DESKTOP_DIR / entry
    assert target == DESKTOP_LAUNCHER
    assert target.is_file(), f"{target} is missing"
    head = target.read_bytes()[:200].decode("utf-8")
    assert head.startswith("# /// script"), "the launcher copy needs its PEP 723 header"
    assert "dependencies = []" in head


def test_the_key_and_the_update_setting_reach_the_launcher() -> None:
    """Exactly the two environment variables the launcher reads, spelled exactly right.

    A typo here is silent: the launcher would simply see no key and start the
    stub, and the person would be told s0ma is not installed when in fact their
    key never arrived.
    """
    env = manifest()["server"]["mcp_config"]["env"]
    assert sorted(env) == ["S0MA_LICENSE_KEY", "S0MA_UPDATE"]
    assert env["S0MA_LICENSE_KEY"] == "${user_config.license_key}"
    assert env["S0MA_UPDATE"] == "${user_config.update}"


def test_no_platform_overrides_are_needed() -> None:
    """One command line works on both platforms, so there is nothing to override."""
    assert "platform_overrides" not in manifest()["server"]["mcp_config"]


# ---------------------------------------------------------------------------
# user_config - the settings screen Claude Desktop generates.
# ---------------------------------------------------------------------------


def test_license_key_is_sensitive_and_optional() -> None:
    """A key is masked and kept in the operating system's secure storage.

    ``required`` stays false on purpose: somebody running s0ma from its source
    code, with ``S0MA_TOOLCHAIN`` pointing at their own checkout, has no key and
    must still be able to install the extension.
    """
    option = manifest()["user_config"]["license_key"]
    assert option["type"] == "string"
    assert option["sensitive"] is True
    assert option.get("required", False) is False
    assert option["title"].strip()
    assert option["description"].strip()
    assert "default" not in option, "a license key must never have a default value"


def test_update_setting_defaults_to_auto() -> None:
    """The launcher checks ``auto``/``notify``/``off``, so this stays a plain string."""
    option = manifest()["user_config"]["update"]
    assert option["type"] == "string"
    assert option["default"] == "auto"
    assert not option.get("sensitive", False)


def test_there_is_no_uv_path_setting() -> None:
    """The Desktop extension does not ask a person where ``uv`` lives.

    The Claude Code plugin has a ``uv_path`` setting because a GUI-launched
    Claude may not see the shell's PATH (the P0 spike). The MCPB ``uv`` server
    type exists precisely to take that problem away - the host application
    installs the dependencies with uv and no user Python is required - so asking
    a Claude Desktop user for a path would be asking a programmer's question of
    somebody who has no terminal open. If this ever has to come back, it is a
    decision, not a patch.
    """
    assert "uv_path" not in manifest()["user_config"]


def test_every_setting_is_labelled() -> None:
    """`type`, `title` and `description` are required on every option in spec 0.4."""
    for name, option in manifest()["user_config"].items():
        for field in ("type", "title", "description"):
            assert option.get(field), f"user_config.{name} is missing `{field}`"


# ---------------------------------------------------------------------------
# Platforms.
# ---------------------------------------------------------------------------


def test_platforms_are_the_two_claude_desktop_runs_on() -> None:
    """There is no Claude Desktop for Linux, so claiming it would be a lie."""
    compatibility = manifest()["compatibility"]
    assert compatibility["platforms"] == ["darwin", "win32"]


def test_no_user_python_is_demanded() -> None:
    """``compatibility.runtimes`` is left out on purpose.

    The ``uv`` server type's whole promise is "no user Python installation
    required"; the version the launcher needs is declared in the bundle's
    ``pyproject.toml``, where uv reads it. Declaring a runtime here could gate
    installation on a Python the person is not supposed to need.
    """
    assert "runtimes" not in manifest()["compatibility"]


# ---------------------------------------------------------------------------
# The privacy policy. This one is a reminder with teeth.
# ---------------------------------------------------------------------------


def test_privacy_policy_url_must_be_live_before_submission() -> None:
    """The policy at this URL does not exist yet. It must, before any submission.

    Anthropic's directory requirements for local connectors: a ``privacy_policies``
    array in the manifest, HTTPS, covering collection, usage, storage, third-party
    sharing, retention and contact - and "missing or incomplete privacy policies
    result in immediate rejection" (research note section 4.4).

    Plan 5 publishes the page. Until it does, this test stands here so that
    nobody can quietly delete the promise: if the URL below disappears from the
    manifest, this test fails and says why.

    This test does NOT fetch the URL - no test here touches the network. Somebody
    has to open it once before the extension is submitted anywhere.
    """
    policies = manifest()["privacy_policies"]
    assert policies == [PRIVACY_POLICY_URL], (
        "The privacy policy URL is what Anthropic's directory rejects an "
        "extension for missing. It must stay exactly "
        f"{PRIVACY_POLICY_URL!r} until plan 5 publishes a different one - and it "
        "must be live before the extension is submitted to any directory."
    )
    assert all(url.startswith("https://") for url in policies), (
        "a privacy policy link must be HTTPS"
    )


# ---------------------------------------------------------------------------
# The tool list.
# ---------------------------------------------------------------------------


def test_tools_listed_are_the_tools_that_exist() -> None:
    """Every real tool, plus the one the stub offers before s0ma is installed.

    The names come from the server's own recorded surface, so a tool added or
    removed there shows up here as a failure rather than as a bundle that
    promises something that is not real.
    """
    listed = sorted(tool["name"] for tool in manifest()["tools"])
    expected = sorted([*real_server_tools(), STUB_TOOL])
    assert listed == expected


def test_tools_are_generated_at_run_time_too() -> None:
    """The list is what people usually get, not a guarantee - and it says so.

    The launcher starts whichever copy of s0ma this computer has, and before
    anything is installed it starts its own stub, which offers one tool. So the
    set of tools really does change at run time, and ``tools_generated`` is the
    field the format has for saying that.
    """
    assert manifest()["tools_generated"] is True


def test_every_listed_tool_has_a_plain_description() -> None:
    """One sentence a non-programmer can read, in ASCII, with no jargon of ours."""
    for tool in manifest()["tools"]:
        name = tool["name"]
        description = tool.get("description", "")
        assert description.strip(), f"tool {name} has no description"
        assert description.isascii(), f"tool {name} has a non-ASCII description"
        assert "\n" not in description, f"tool {name} needs a one-line description"
        assert len(description) <= 200, f"tool {name}'s description is too long"
        assert "payload" not in description.lower(), (
            f"tool {name} uses the word 'payload'; say what it is instead"
        )
        assert sorted(tool) == ["description", "name"], (
            f"tool {name} carries a field spec 0.4 does not define"
        )


def test_no_user_facing_text_says_payload() -> None:
    """House rule: the word is never used where a person can read it."""
    text = MANIFEST.read_text(encoding="utf-8").lower()
    assert "payload" not in text


# ---------------------------------------------------------------------------
# Findings for the directory submission. The server is NOT changed here.
# ---------------------------------------------------------------------------

#: Anthropic's directory requires a `title` on every tool. Until 2026-09-18 no
#: tool in `s0ma-mcp` had one, and this module carried the list of the fifteen
#: that lacked it (X1.T3's finding) so the gap could not go stale unnoticed. The
#: owner approved fifteen titles that day (surface contract revision R3), the
#: list emptied, and - as its own docstring asked - it was deleted. What stands
#: in its place is the requirement itself.


def test_every_real_tool_carries_a_title() -> None:
    """The directory requirement s0ma now meets - and must keep.

    Anthropic's directory requirement for every connector: "all tools must
    include a `title` and the applicable `readOnlyHint` or `destructiveHint`"
    (research note section 4.4). The server serves each title in both places a
    client may read it, from one authored value, so the two must also agree.
    A new tool that arrives without a title fails here, before a reviewer
    finds it.
    """
    records = real_server_tool_records()
    untitled = sorted(
        tool["name"]
        for tool in records
        if not (tool.get("title") and (tool.get("annotations") or {}).get("title"))
    )
    assert untitled == [], (
        "These s0ma tools have no `title` in one or both of the places a client "
        "reads it. Anthropic's directory needs a title on every tool before the "
        f"extension can be submitted: {untitled}"
    )
    disagreeing = sorted(
        tool["name"]
        for tool in records
        if tool.get("title") != (tool.get("annotations") or {}).get("title")
    )
    assert disagreeing == [], disagreeing


def test_every_real_tool_carries_a_read_only_or_destructive_hint() -> None:
    """The half of the directory requirement s0ma already meets - and must keep.

    A tool with neither hint tells a reviewer, and a person approving a call,
    nothing about whether it can damage anything.
    """
    unhinted = sorted(
        tool["name"]
        for tool in real_server_tool_records()
        if (tool.get("annotations") or {}).get("readOnlyHint") is None
        and (tool.get("annotations") or {}).get("destructiveHint") is None
    )
    assert unhinted == [], (
        "These tools declare neither readOnlyHint nor destructiveHint, which "
        f"Anthropic's directory requires: {unhinted}"
    )


# ---------------------------------------------------------------------------
# pyproject.toml - required by the `uv` server type.
# ---------------------------------------------------------------------------


def test_bundle_has_the_pyproject_the_uv_type_requires() -> None:
    """``uv`` extensions declare their dependencies in a ``pyproject.toml``.

    s0ma's launcher has none and never will (plan section 3.1, rule 7), so the
    list is empty - but the file still has to be there, because that is how the
    host application knows what environment to build.
    """
    assert DESKTOP_PYPROJECT.is_file()
    with DESKTOP_PYPROJECT.open("rb") as handle:
        data = tomllib.load(handle)
    project = data["project"]
    assert project["dependencies"] == [], (
        "the launcher is standard library only; this list stays empty"
    )
    assert project["requires-python"] == ">=3.11"
    assert project["version"] == lockstep_version()
    assert "build-system" not in data, (
        "without a [build-system] table uv runs in the project instead of "
        "building a package out of the launcher, which is what we want"
    )


def test_bundle_carries_nothing_the_uv_type_forbids() -> None:
    """``server/lib`` and ``server/venv`` are exactly what this type replaces."""
    for forbidden in ("server/lib", "server/venv", ".venv"):
        assert not (DESKTOP_DIR / forbidden).exists(), (
            f"a `uv` extension must not contain {forbidden}"
        )


def test_the_bundle_is_only_the_three_files() -> None:
    """Small is the point: a manifest, a project file and one program.

    The format's own note on the ``uv`` type puts the win at roughly 100 KB
    against 5-10 MB for a bundle that carries its dependencies. Anything new
    appearing here should be a decision somebody took on purpose.
    """
    assert sorted(tree_digest(DESKTOP_DIR)) == [
        "manifest.json",
        "pyproject.toml",
        "server/s0ma_launch.py",
    ]


# ---------------------------------------------------------------------------
# The pack script.
# ---------------------------------------------------------------------------


def test_pack_script_is_posix_sh() -> None:
    """A ``/bin/sh`` shebang, LF endings and plain ASCII - no bash needed.

    Nothing the script does asks for more than POSIX sh, so it does not ask for
    bash: the same file then runs under dash, busybox ash and macOS's sh alike.
    """
    raw = PACK_SCRIPT.read_bytes()
    assert raw.startswith(b"#!/bin/sh\n"), "the pack script must start with #!/bin/sh"
    assert b"\r\n" not in raw, "the pack script must use LF line endings"
    text = raw.decode("utf-8")
    assert text.isascii(), "the pack script must be plain ASCII"
    for line in text.splitlines():
        code = line.strip()
        if not code or code.startswith("#"):
            continue
        for bashism in ("[[", "function ", "$(( ", "echo -e"):
            assert bashism not in code, f"bash-only form {bashism!r} in: {code}"
        for opener in ("local ", "source "):
            assert not code.startswith(opener), f"bash-only form {opener!r} in: {code}"


def test_pack_script_never_downloads_anything() -> None:
    """It may print an install command. It may not run one.

    ``npx --yes @anthropic-ai/mcpb`` fetches a package from the network; a build
    script that silently does that is a build script nobody can audit.
    """
    text = PACK_SCRIPT.read_text(encoding="utf-8")
    assert "npx" not in text
    assert "command -v mcpb" in text, "the packer is used only if it is already here"
    for line in text.splitlines():
        stripped = line.strip()
        if "npm install" in stripped:
            assert stripped.startswith("echo "), (
                "an install command may only ever be printed, never run: " + stripped
            )


@pytest.mark.skipif(
    WINDOWS, reason="Windows checkouts have no executable bit; the script is POSIX-only"
)
def test_pack_script_is_executable() -> None:
    mode = PACK_SCRIPT.stat().st_mode
    assert mode & 0o111 == 0o111, (
        f"the pack script is mode {mode & 0o777:o}; it needs to be 755"
    )


@pytest.mark.skipif(
    WINDOWS, reason="no POSIX shell to parse the script with on Windows"
)
def test_pack_script_parses_as_posix_sh() -> None:
    """``sh -n`` reads the whole file without running any of it."""
    result = subprocess.run(  # noqa: S603 - a fixed, local command
        ["/bin/sh", "-n", str(PACK_SCRIPT)], capture_output=True, text=True, timeout=60
    )
    assert result.returncode == 0, f"not valid POSIX sh:\n{result.stderr}"


@pytest.mark.skipif(WINDOWS, reason="the pack script is POSIX-only")
def test_pack_script_without_the_packer_stages_and_explains(tmp_path: Path) -> None:
    """With no ``mcpb`` on the PATH: stage the bundle, print the commands, exit 0.

    This is the case every contributor is in, so it has to end somewhere useful
    rather than in an error. The bundle is staged either way, so the printed
    commands are ones that will actually work when they are pasted.
    """
    empty_bin = tmp_path / "bin"
    empty_bin.mkdir()
    search_path = f"{empty_bin}:/usr/bin:/bin:/usr/sbin:/sbin"
    if shutil.which("mcpb", path=search_path) is not None:  # pragma: no cover
        pytest.skip("this machine has mcpb where the test cannot hide it")

    out_dir = tmp_path / "out"
    before = tree_digest(DESKTOP_DIR)

    result = subprocess.run(  # noqa: S603 - a fixed, local command
        ["/bin/sh", str(PACK_SCRIPT), str(out_dir)],
        capture_output=True,
        text=True,
        timeout=120,
        cwd=str(tmp_path),
        env={"PATH": search_path, "HOME": str(tmp_path)},
    )

    assert result.returncode == 0, f"the script failed:\n{result.stdout}{result.stderr}"
    assert "mcpb validate" in result.stdout
    assert "mcpb pack" in result.stdout
    assert "npm install -g @anthropic-ai/mcpb" in result.stdout

    version = lockstep_version()
    staged = out_dir / f"s0ma-{version}"
    assert (staged / "manifest.json").is_file()
    assert (staged / "pyproject.toml").is_file()
    assert (staged / "server" / "s0ma_launch.py").is_file()
    assert staged.name in result.stdout, "the script must say where it put the bundle"

    assert not list(out_dir.glob("*.mcpb")), "nothing may be packed without the packer"
    assert tree_digest(DESKTOP_DIR) == before, (
        "packing must not change anything inside the repository"
    )


@pytest.mark.skipif(WINDOWS, reason="the pack script is POSIX-only")
def test_pack_script_refuses_to_write_inside_the_repository(tmp_path: Path) -> None:
    """The ``.mcpb`` is a build product; the repository is not where it goes.

    The refusal happens before anything is created, so a mistyped command leaves
    no directory behind to clean up.
    """
    inside = DESKTOP_DIR / "would-be-build-output"
    result = subprocess.run(  # noqa: S603 - a fixed, local command
        ["/bin/sh", str(PACK_SCRIPT), str(inside)],
        capture_output=True,
        text=True,
        timeout=120,
        cwd=str(tmp_path),
        env={"PATH": "/usr/bin:/bin:/usr/sbin:/sbin", "HOME": str(tmp_path)},
    )
    assert result.returncode == 2
    assert "build product" in result.stderr
    assert not inside.exists(), "a refused path must leave nothing behind"


@pytest.mark.skipif(WINDOWS, reason="the pack script is POSIX-only")
def test_pack_script_reads_the_version_the_same_way_the_manifest_writes_it(
    tmp_path: Path,
) -> None:
    """``sed`` must find ``version``, not ``manifest_version``.

    The two keys sit one line apart in the sorted manifest, and a pattern loose
    enough to match both would name the bundle ``s0ma-0.4.mcpb``.
    """
    empty_bin = tmp_path / "bin"
    empty_bin.mkdir()
    search_path = f"{empty_bin}:/usr/bin:/bin:/usr/sbin:/sbin"
    if shutil.which("mcpb", path=search_path) is not None:  # pragma: no cover
        pytest.skip("this machine has mcpb where the test cannot hide it")

    out_dir = tmp_path / "out"
    subprocess.run(  # noqa: S603 - a fixed, local command
        ["/bin/sh", str(PACK_SCRIPT), str(out_dir)],
        capture_output=True,
        text=True,
        timeout=120,
        check=True,
        cwd=str(tmp_path),
        env={"PATH": search_path, "HOME": str(tmp_path)},
    )
    staged = [child.name for child in out_dir.iterdir()]
    assert staged == [f"s0ma-{lockstep_version()}"]


@pytest.mark.skipif(WINDOWS, reason="the pack script is POSIX-only")
def test_the_packer_accepts_the_manifest_when_this_machine_has_it(
    tmp_path: Path,
) -> None:
    """``mcpb validate``'s own verdict, taken only if the packer is already here.

    Nothing is installed to make this run. On a machine without ``mcpb`` the test
    skips and says so, and the pack script's printed command is how somebody
    takes the verdict by hand.
    """
    if shutil.which("mcpb") is None:
        pytest.skip("mcpb is not installed on this machine; no verdict can be taken")
    out_dir = tmp_path / "out"
    result = subprocess.run(  # noqa: S603 - a fixed, local command
        ["/bin/sh", str(PACK_SCRIPT), str(out_dir)],
        capture_output=True,
        text=True,
        timeout=300,
        cwd=str(tmp_path),
    )
    assert result.returncode == 0, (
        f"mcpb rejected the extension:\n{result.stdout}{result.stderr}"
    )
    assert list(out_dir.glob("*.mcpb")), "the packer should have produced a bundle"
