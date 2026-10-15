#!/usr/bin/env python3
"""Build the public marketplace repository's tree, in a directory you name.

The monorepo is private. A private Claude Code marketplace is fragile - the
background refresh that keeps a plugin current runs without git credential
helpers, so a private catalog goes stale for exactly the users who most want it
current (research section 2.4). So the catalog and the plugin are published
from a small PUBLIC repository, ``kn0w-thyself/claude-plugins``, and this
script is what builds that repository's contents out of ``integrations/claude/``.

    uv run python scripts/export_claude_marketplace.py --out ../claude-plugins

What lands in that directory::

    .claude-plugin/marketplace.json   the catalog, with the plugin entry's
                                      source rewritten from "./plugin" (where
                                      the plugin sits next to the catalog in
                                      the monorepo) to "./plugins/s0ma"
    plugins/s0ma/**                   the plugin, byte for byte, with the two
                                      shell shims still executable
    LICENSE                           the same Apache-2.0 text the plugin carries
    README.md                         for somebody who has never heard of s0ma
    PRIVACY.md                        what the launcher does on the network
    EXPORT-MANIFEST.json              the source commit, the plugin version, and
                                      every file above with its sha256 and mode

**This script publishes nothing.** It never runs ``git push``, never creates a
repository, never calls ``gh``. It prints the commands the owner runs, and
creating that repository is the owner's act, not this script's.

Two refusals stand between a mistake and the public internet:

* the source tree must have no uncommitted changes under ``integrations/``, so
  what is published is what is committed and reviewed;
* ``scripts/sync_integrations.py --check`` must pass, so a stale launcher copy
  or a version left behind by a release cut can never be exported.

``--allow-dirty`` lifts the first one and exists for the tests only.

The output is deterministic: the same commit produces a byte-identical tree.
Nothing carries a timestamp, nothing carries a path from the machine that built
it, the traversal is sorted, and both JSON files are written in the canonical
form the monorepo's manifests already use.

Exit codes: 0 exported; 1 refused, with nothing written; 2 a usage mistake;
3 exported, but ``claude plugin validate`` rejected the result.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import shutil
import stat
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType
from typing import Any

PROG = "export_claude_marketplace.py"

SCRIPTS_DIR = Path(__file__).resolve().parent
#: The repository this script lives in; ``--root`` defaults to it.
DEFAULT_ROOT = SCRIPTS_DIR.parent

# ---------------------------------------------------------------------------
# Where things are, here and there.
# ---------------------------------------------------------------------------

#: In the monorepo. The marketplace root is ``integrations/claude/`` itself,
#: wrapped AROUND the plugin, because both `claude` CLI builds refuse a plugin
#: source that climbs out of the marketplace root with "..".
MARKETPLACE_MANIFEST = "integrations/claude/.claude-plugin/marketplace.json"
PLUGIN_DIR = "integrations/claude/plugin"
PLUGIN_MANIFEST = "integrations/claude/plugin/.claude-plugin/plugin.json"

#: In the export.
EXPORT_MARKETPLACE_MANIFEST = ".claude-plugin/marketplace.json"
EXPORT_PLUGIN_DIR = "plugins/s0ma"
EXPORT_MANIFEST = "EXPORT-MANIFEST.json"

#: The plugin entry's source, before and after.
SOURCE_IN_MONOREPO = "./plugin"
SOURCE_IN_EXPORT = "./plugins/s0ma"

#: The public repository this export becomes, and the name users install from.
PUBLIC_REPO = "kn0w-thyself/claude-plugins"
MARKETPLACE_NAME = "kn0wthyself"

#: The only two files in the plugin that have to be executable. Named here
#: rather than read from the filesystem, so that an export built on Windows -
#: where there is no executable bit to read - records the same modes as one
#: built on macOS, and the manifest stays byte-identical across platforms.
EXECUTABLE_FILES = ("bin/s0ma", "bin/s0ma-launch")

#: Never copied: build litter that is not part of the plugin.
SKIPPED_NAMES = frozenset({"__pycache__", ".DS_Store"})
SKIPPED_SUFFIXES = (".pyc", ".pyo")

EXIT_OK = 0
EXIT_REFUSED = 1
EXIT_INVALID = 3

#: Passed to every `claude` subprocess, so validating an export never turns
#: into a background update check nobody asked for.
OFFLINE_ENV = {
    "DISABLE_AUTOUPDATER": "1",
    "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC": "1",
}


class Refusal(Exception):
    """A reason not to export, in words a reader can act on."""


# ---------------------------------------------------------------------------
# Small helpers.
# ---------------------------------------------------------------------------


def fwd(path: Path | str) -> str:
    """A path with forward slashes, so one machine's output reads like another's."""
    return str(path).replace("\\", "/")


def canonical_json(data: Any) -> str:
    """The form both manifests are written in: 2-space, sorted, one newline.

    The same form ``scripts/sync_integrations.py`` writes, so the exported
    catalog differs from the committed one in the source string and nothing
    else, and so two exports of one commit are byte-identical.
    """
    return json.dumps(data, indent=2, sort_keys=True) + "\n"


def write_text(path: Path, text: str) -> bytes:
    """Write *text* as UTF-8 with LF endings on every platform; return the bytes."""
    data = text.encode("utf-8")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return data


def read_json(path: Path, what: str) -> dict[str, Any]:
    """Load one of the manifests, or refuse with the reason."""
    try:
        data = json.loads(path.read_bytes().decode("utf-8"))
    except OSError as exc:
        raise Refusal(f"{what} ({fwd(path.name)}) cannot be read: {exc.strerror}.") from exc
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise Refusal(f"{what} ({fwd(path.name)}) is not valid UTF-8 JSON: {exc}.") from exc
    if not isinstance(data, dict):
        raise Refusal(f"{what} ({fwd(path.name)}) does not hold a JSON object.")
    return data


def git_output(root: Path, *args: str) -> str | None:
    """What ``git`` printed, or ``None`` if it could not answer at all."""
    try:
        result = subprocess.run(  # noqa: S603 - a fixed, local command
            ["git", "-C", str(root), *args],
            capture_output=True,
            text=True,
            timeout=120,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if result.returncode != 0:
        return None
    return result.stdout


# ---------------------------------------------------------------------------
# The two refusals.
# ---------------------------------------------------------------------------


def check_out_directory(out: Path, root: Path) -> Path:
    """The export directory, resolved - or a refusal. Creates nothing."""
    resolved = out.expanduser().resolve()
    inside = (
        (root, "the repository being exported"),
        (DEFAULT_ROOT, "this repository"),
    )
    for repo, described in inside:
        if resolved == repo or repo in resolved.parents:
            raise Refusal(
                f"{fwd(resolved)} is inside {described} ({fwd(repo)}). The export "
                f"becomes its own git repository, so it has to live outside this "
                f"one. Name a directory somewhere else, next to it for instance."
            )
    if resolved.exists():
        if not resolved.is_dir():
            raise Refusal(f"{fwd(resolved)} is a file, not a directory.")
        existing = sorted(entry.name for entry in resolved.iterdir())
        shown = ", ".join(existing[:5]) + (", ..." if len(existing) > 5 else "")
        raise Refusal(
            f"{fwd(resolved)} already has something in it ({shown}). Export into "
            f"an empty or a new directory, so that what lands there is only what "
            f"this run put there."
        )
    return resolved


def check_source_is_committed(root: Path) -> None:
    """Refuse unless everything under ``integrations/`` is committed."""
    output = git_output(root, "status", "--porcelain", "--", "integrations/")
    if output is None:
        raise Refusal(
            f"git could not say whether {fwd(root)} is clean, so there is no "
            f"telling whether the plugin about to be published is the plugin "
            f"that was reviewed. Export from a git checkout of the monorepo."
        )
    changes = [line.rstrip() for line in output.splitlines() if line.strip()]
    if changes:
        listed = "\n".join(f"  {line}" for line in changes[:20])
        more = f"\n  ... and {len(changes) - 20} more" if len(changes) > 20 else ""
        raise Refusal(
            f"integrations/ has uncommitted changes, and an export publishes "
            f"whatever is on disk. Commit or put them back first:\n{listed}{more}"
        )


def load_sync_module() -> ModuleType | None:
    """``scripts/sync_integrations.py``, imported from its path beside this one."""
    script = SCRIPTS_DIR / "sync_integrations.py"
    spec = importlib.util.spec_from_file_location("s0ma_sync_integrations", script)
    if spec is None or spec.loader is None:
        return None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    try:
        spec.loader.exec_module(module)
    except Exception:  # pragma: no cover - a broken checkout; fall back below
        return None
    return module


def check_copies_are_in_step(root: Path) -> None:
    """Refuse unless ``sync_integrations.py --check`` passes on *root*.

    Imported rather than run, so its findings arrive as objects and are printed
    once, in its words. If the script cannot be imported at all it is run as a
    subprocess instead - the check is not optional either way.
    """
    module = load_sync_module()
    if module is None:  # pragma: no cover - a broken checkout
        script = SCRIPTS_DIR / "sync_integrations.py"
        result = subprocess.run(  # noqa: S603 - a fixed, local command
            [sys.executable, str(script), "--check", "--root", str(root)],
            capture_output=True,
            text=True,
            timeout=300,
        )
        if result.returncode != 0:
            raise Refusal(
                "the Claude integration is out of step with the monorepo, so an "
                "export would ship a stale copy:\n"
                + (result.stdout + result.stderr).rstrip()
            )
        return
    findings = module.collect(root)
    if findings:
        listed = "\n".join(f"  {finding.message()}" for finding in findings)
        raise Refusal(
            "the Claude integration is out of step with the monorepo, so an "
            "export would ship a stale copy of the launcher or a wrong version "
            f"number:\n{listed}"
        )


# ---------------------------------------------------------------------------
# Building the tree.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ExportedFile:
    """One file in the export: where it landed, how it is read, what it is."""

    path: str
    mode: int
    sha256: str

    def entry(self) -> dict[str, str]:
        """This file's row in ``EXPORT-MANIFEST.json``."""
        return {"mode": f"{self.mode:04o}", "path": self.path, "sha256": self.sha256}


def plugin_sources(plugin_dir: Path) -> list[tuple[str, Path]]:
    """Every plugin file to copy, as ``(plugin-relative path, source)``, sorted."""
    found: list[tuple[str, Path]] = []
    for source in plugin_dir.rglob("*"):
        if any(part in SKIPPED_NAMES for part in source.relative_to(plugin_dir).parts):
            continue
        if source.is_symlink():
            raise Refusal(
                f"{fwd(source.relative_to(plugin_dir))} in the plugin is a symbolic "
                f"link. A published plugin has to be plain files, so that what a "
                f"user installs does not depend on where it was built."
            )
        if not source.is_file() or source.suffix in SKIPPED_SUFFIXES:
            continue
        found.append((fwd(source.relative_to(plugin_dir)), source))
    return sorted(found)


def record_file(out: Path, target: Path, data: bytes, mode: int = 0o644) -> ExportedFile:
    """Record one written file, by its path relative to the export root."""
    if os.name == "posix":
        os.chmod(target, mode)  # noqa: S103 - 0755 on two shims, 0644 on the rest
    return ExportedFile(
        path=fwd(target.relative_to(out)),
        mode=mode,
        sha256=hashlib.sha256(data).hexdigest(),
    )


def rewritten_marketplace(root: Path) -> str:
    """The catalog, with the plugin entry pointing at its home in the export."""
    manifest = read_json(root / MARKETPLACE_MANIFEST, "the marketplace manifest")
    plugins = manifest.get("plugins")
    if not isinstance(plugins, list) or not plugins:
        raise Refusal("the marketplace manifest lists no plugins.")
    rewrites = 0
    for plugin in plugins:
        if isinstance(plugin, dict) and plugin.get("source") == SOURCE_IN_MONOREPO:
            plugin["source"] = SOURCE_IN_EXPORT
            rewrites += 1
    if rewrites != 1:
        raise Refusal(
            f"the marketplace manifest has {rewrites} plugin entries whose source "
            f'is "{SOURCE_IN_MONOREPO}"; exactly one is expected, and this script '
            f"rewrites that one. Look at {MARKETPLACE_MANIFEST}."
        )
    return canonical_json(manifest)


def plugin_version(root: Path) -> str:
    """The version the plugin manifest states, which the suggested tag uses."""
    manifest = read_json(root / PLUGIN_MANIFEST, "the plugin manifest")
    version = manifest.get("version")
    if not isinstance(version, str) or not version:
        raise Refusal(f"{PLUGIN_MANIFEST} states no version.")
    return version


def build(root: Path, out: Path) -> tuple[list[ExportedFile], str, str]:
    """Write the whole tree. Returns the files, the version and the commit."""
    plugin_dir = root / PLUGIN_DIR
    if not plugin_dir.is_dir():
        raise Refusal(f"{PLUGIN_DIR} is not in {fwd(root)}, so there is nothing to export.")
    sources = plugin_sources(plugin_dir)
    if os.name == "posix":
        stray = [
            relative
            for relative, source in sources
            if relative not in EXECUTABLE_FILES and source.stat().st_mode & stat.S_IXUSR
        ]
        if stray:
            raise Refusal(
                "these plugin files are executable but are not one of the two "
                "shims, so the export cannot tell what mode they should have in "
                "the public repository: " + ", ".join(stray)
            )

    license_text = plugin_dir / "LICENSE"
    if not license_text.is_file():
        raise Refusal(
            f"{PLUGIN_DIR}/LICENSE is missing, and a public repository states its "
            f"licence at the root or it has none."
        )

    # Everything that can refuse has now refused, so the directory can be made.
    version = plugin_version(root)
    catalog = rewritten_marketplace(root)
    commit = (git_output(root, "rev-parse", "HEAD") or "unknown").strip() or "unknown"

    out.mkdir(parents=True, exist_ok=True)
    files: list[ExportedFile] = []

    target = out / EXPORT_MARKETPLACE_MANIFEST
    files.append(record_file(out, target, write_text(target, catalog)))

    for relative, source in sources:
        mode = 0o755 if relative in EXECUTABLE_FILES else 0o644
        target = out / EXPORT_PLUGIN_DIR / relative
        data = source.read_bytes()
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        files.append(record_file(out, target, data, mode))

    target = out / "LICENSE"
    files.append(record_file(out, target, copy_bytes(license_text, target)))

    target = out / "README.md"
    files.append(record_file(out, target, write_text(target, README_MD)))

    target = out / "PRIVACY.md"
    files.append(record_file(out, target, write_text(target, PRIVACY_MD)))

    files.sort(key=lambda item: item.path)
    manifest = {
        "files": [item.entry() for item in files],
        "note": (
            "Built by scripts/export_claude_marketplace.py in the s0ma monorepo. "
            "Every file in this repository is listed above except this manifest, "
            "which cannot state its own hash. Nothing here is edited by hand."
        ),
        "plugin_version": version,
        "source_commit": commit,
        "source_path": "integrations/claude",
    }
    target = out / EXPORT_MANIFEST
    write_text(target, canonical_json(manifest))
    if os.name == "posix":
        os.chmod(target, 0o644)  # noqa: S103 - an ordinary readable file
    return files, version, commit


def copy_bytes(source: Path, target: Path) -> bytes:
    """Copy one file byte for byte and hand back what was written."""
    data = source.read_bytes()
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(data)
    return data


# ---------------------------------------------------------------------------
# Checking the result with the CLI that will load it.
# ---------------------------------------------------------------------------


def find_claude() -> str | None:
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
    """Run `claude plugin validate` on *target*, strictly where that is supported."""
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


def validate(out: Path) -> bool | None:
    """Validate the export. ``True`` pass, ``False`` fail, ``None`` not checked."""
    binary = find_claude()
    print("")
    print("==> Does the `claude` CLI accept it?")
    if binary is None:
        print("  Not checked: there is no `claude` on this PATH. On a machine that")
        print("  has one, these two commands are the check, and they install nothing:")
        print(f"    claude plugin validate {fwd(out)}")
        print(f"    claude plugin validate {fwd(out / EXPORT_PLUGIN_DIR)}")
        return None
    ok = True
    for what, target in (("the marketplace", out), ("the plugin", out / EXPORT_PLUGIN_DIR)):
        result = run_validate(binary, target)
        if result.returncode == 0:
            print(f"  {what}: accepted.")
            continue
        ok = False
        print(f"  {what}: REJECTED.")
        for line in (result.stdout + result.stderr).splitlines():
            print(f"    {line}")
    return ok


# ---------------------------------------------------------------------------
# What the owner does next. Printed, never run.
# ---------------------------------------------------------------------------


def print_owner_commands(out: Path, version: str, commit: str) -> None:
    """The publishing steps, in order, for the owner to run by hand."""
    short = commit[:12] if commit != "unknown" else commit
    shims = " ".join(f"{EXPORT_PLUGIN_DIR}/{name}" for name in EXECUTABLE_FILES)
    print("")
    print("==> Next, by hand (this script runs NONE of these):")
    print("")
    print(f"  cd {fwd(out)}")
    print("  git init -b main")
    print("  git add -A")
    if os.name != "posix":
        print("  # This export was built on Windows, which has no executable bit, so")
        print("  # git has just recorded both shims as ordinary files. This line puts")
        print("  # the bit into the index, where it is what actually gets published:")
        print(f"  git update-index --chmod=+x {shims}")
    print(
        f'  git commit -m "s0ma Claude plugin {version} '
        f'(exported from the monorepo at {short})"'
    )
    print("")
    print("  # Creating the repository PUBLISHES it. That is your act, not this")
    print("  # script's, and it cannot be quietly undone: assume anything pushed")
    print("  # to a public repository has been seen.")
    print(f"  gh repo create {PUBLIC_REPO} --public --source . --push")
    print("")
    print("  # or, without the gh CLI - create the repository on github.com first,")
    print("  # then:")
    print(f"  git remote add origin https://github.com/{PUBLIC_REPO}.git")
    print("  git push -u origin main")
    print("")
    print("  # a tag, so the catalog's history has a name for this release:")
    print(f'  git tag -a v{version} -m "s0ma Claude plugin {version}"')
    print(f"  git push origin v{version}")
    print("")
    print("==> Executable bits")
    if os.name == "posix":
        print("  Set here: both shims are 0755 and every other file is 0644. git")
        print("  reads the bit off the filesystem, so it survives into the public")
        print("  repository - `git ls-files -s` after `git add` shows 100755 on")
        for name in EXECUTABLE_FILES:
            print(f"    {EXPORT_PLUGIN_DIR}/{name}")
    else:
        print("  NOT set here: Windows has no executable bit to set, so run the")
        print("  `git update-index --chmod=+x` line above after `git add` and before")
        print("  committing - or build the export on macOS or Linux instead.")
    print(f"  {EXPORT_MANIFEST} records the mode every file is meant to have.")
    print("")
    print("==> Next time")
    print("  Export again into a fresh empty directory, copy the result over your")
    print("  clone of the public repository, then commit, tag and push from there.")
    print("  Nothing in the public repository is ever edited by hand, so a fresh")
    print("  export is always the whole answer.")


# ---------------------------------------------------------------------------
# The two files written for people, rather than for Claude.
# ---------------------------------------------------------------------------

README_MD = """\
# s0ma for Claude

s0ma gives Claude a living model of the software you are building: what each
part is for, what it depends on, and why it is there. Answers about your
project then come from the project itself, rather than from a guess made while
reading its files. This repository is the marketplace that Claude installs the
s0ma plugin from, and nothing else.

## Install

In Claude Code, two lines:

```
/plugin marketplace add kn0w-thyself/claude-plugins
/plugin install s0ma@kn0wthyself
```

Claude asks for a few settings when the plugin is switched on. You can leave
every one of them empty and come back to them. Then run `/s0ma:setup`, which
checks what this computer already has and installs what it does not.

## Where your key goes

Put the key from your account at account.kn0wthyself.ai into the plugin's
**s0ma license key** field. Claude masks it as you type, keeps it in this
computer's own secure storage, and never writes it into a settings file.

Never type a key into a conversation, and never ask Claude to read one back to
you. If a key has been in a chat, treat it as spent and get a new one. If you
would rather use a terminal, `s0ma-launch activate` asks for the key without
showing it and saves it for you.

The key is only used to download s0ma from the subscriber channel. If you run
s0ma from a source checkout you need no key at all, and everything in this
plugin still works.

## Keeping it current

Two different things update here, and only one of them is ours.

**The s0ma toolchain** looks after itself. It starts the version you have,
fetches a newer one quietly in the background, and uses it the next time a
session starts - never in the middle of your work. `/s0ma:update` checks by
hand, and a project can hold itself on one version when a change would be
unwelcome.

**The plugin** is Claude's business, and Claude only updates marketplaces
automatically when they are Anthropic's own. To switch it on for this one:
`/plugin`, then Marketplaces, then kn0wthyself, then **Enable auto-update**.
The plugin is deliberately thin and changes rarely, so little is lost if you
leave it off.

## What this sends over the network

When it looks for a newer s0ma - by itself at most once a day, and only while
its update setting is `auto` or `notify` - the plugin's launcher asks
account.kn0wthyself.ai which release exists and where its files are, with your
key in the request's authorization header rather than in the web address, and
downloads the files that answer names. It sends nothing else: no analytics, no
usage counts, and nothing about your project, your files or your conversation.
While a version is being installed, uv also fetches the open-source Python
packages s0ma depends on from the Python package index your machine uses; your
key is never given to it.

`PRIVACY.md` in this repository sets that out in full, including how to switch
it off. The policy it all sits under is at kn0wthyself.ai/legal/privacy.

## Help

- `/s0ma:setup` in Claude, to install s0ma or repair an install
- `/s0ma:doctor` in Claude, when something is not behaving
- `/s0ma:feedback` in Claude, to tell us about it - you see and approve the
  report before any of it is sent
- account.kn0wthyself.ai for your subscription and your key
- kn0wthyself.ai for everything else

## About this repository

Nothing here is written by hand. The plugin is generated from the s0ma
monorepo, where it is built, tested and released with the rest of s0ma;
`EXPORT-MANIFEST.json` records the commit each export came from and the
checksum of every file. If something here should change, propose it in the
monorepo and it will arrive in the next export. Questions and bug reports about
the plugin are welcome here.

Apache License 2.0. See `LICENSE`.
"""

PRIVACY_MD = """\
# What this plugin sends, and when

This is not the privacy policy; the policy is at kn0wthyself.ai/legal/privacy
and governs everything. This is the short, specific version for the one program
this plugin carries: the s0ma launcher, which finds the copy of s0ma your
computer should run, starts it, and fetches newer ones.

## The only conversation the launcher has

The launcher itself talks to one place, account.kn0wthyself.ai, and only to find
out which release of s0ma exists and to fetch it. Two requests, no more:

1. It asks which release is current and what files it is made of. Your license
   key travels in that request's authorization header - never in the web
   address, never on a command line, never in a log file, and never in anything
   you or Claude can read back.
2. If that answer names a release worth having, it downloads those files from
   the same place and checks each one against the checksum the first answer
   gave.

## The one other place an install reaches

s0ma is built on a handful of open-source Python packages. While a version is
being installed, uv - the program that builds s0ma's environment - fetches
those from the Python package index (pypi.org, or whichever index your machine
is set up to use), exactly as it would for any other Python program. That
request is uv's own: it carries nothing about you or your project, and the
launcher removes your license key from uv's environment before it starts it.
It happens once per installed version, and never when nothing is being
installed.

## When

- By itself: at most once a day, and only while the update setting is `auto` or
  `notify`. Set it to `off` in the plugin's settings, or set the environment
  variable `S0MA_UPDATE=off`, and the launcher never opens a connection on its
  own.
- Never in the middle of a session's work. A newer version is fetched in the
  background and is used the next time a session starts.
- When you ask: `s0ma-launch install`, `s0ma-launch update` and
  `s0ma-launch activate` talk to the same place at the moment you run them.
  `activate` makes one extra request, to tell you straight away whether the key
  you just typed is good. `s0ma-launch pin` asks once whether the version you
  named exists, so a typing mistake is caught before it is written down; add
  `--offline` and it asks nothing.

## What it never sends

No analytics. No usage counts. No error reports. Nothing about your project,
your files, your prompts or your conversation - not to us, not to anyone. The
launcher's other commands (`status`, `session-hint`, `unpin`, `run`) read local
files and open no connection at all, which is why they still work with the
network unplugged.

## The one thing you can send on purpose

`/s0ma:feedback` sends a report about s0ma to us, and only because you asked
for it. You see the exact report first and approve it. Say no and nothing
leaves the machine.

## Where your key is kept

In this computer's own secure storage, put there by Claude when you type it
into the plugin's masked field. If you used `s0ma-launch activate` instead, it
is in a file in your s0ma home directory. On macOS and Linux the launcher makes
that file readable by your account and nobody else; on Windows it cannot, says
so, and asks you to check who can read the folder. Either way it is never
written into a settings file, never printed, and never shown in a conversation.

## Questions

kn0wthyself.ai/legal/privacy, or `/s0ma:feedback` in Claude.
"""


# ---------------------------------------------------------------------------
# Running.
# ---------------------------------------------------------------------------


def export(root: Path, out: Path, *, allow_dirty: bool) -> tuple[Path, str, str]:
    """Refuse, or build. Returns the export directory, version and commit."""
    resolved_out = check_out_directory(out, root)
    if not allow_dirty:
        check_source_is_committed(root)
    check_copies_are_in_step(root)
    files, version, commit = build(root, resolved_out)

    print(f"==> Exported the {MARKETPLACE_NAME} marketplace to {fwd(resolved_out)}")
    print(f"  from {fwd(root)} at commit {commit}, plugin version {version}")
    print("")
    listing = sorted([(item.path, item.mode) for item in files] + [(EXPORT_MANIFEST, 0o644)])
    for path, mode in listing:
        print(f"  {mode:04o}  {path}")
    print(f"  {len(listing)} files. Nothing has been published.")
    return resolved_out, version, commit


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog=PROG,
        description=(
            "Build the tree of the public Claude Code marketplace repository "
            f"({PUBLIC_REPO}) from this monorepo's integrations/claude/. "
            "Nothing is published: the commands for that are printed, not run."
        ),
        epilog=(
            "Exit codes: 0 exported; 1 refused, with nothing written; "
            "2 a usage mistake; 3 exported, but `claude plugin validate` "
            "rejected the result."
        ),
    )
    parser.add_argument(
        "--out",
        type=Path,
        required=True,
        help=(
            "the directory to build the public repository in; it must be empty "
            "or not yet exist, and must be outside this repository"
        ),
    )
    parser.add_argument(
        "--root",
        type=Path,
        default=DEFAULT_ROOT,
        help="the monorepo to export from (default: the one this script lives in)",
    )
    parser.add_argument(
        "--allow-dirty",
        action="store_true",
        help=(
            "for the tests only: export even though integrations/ has "
            "uncommitted changes. Never use this for a real export - it "
            "publishes bytes nobody has reviewed"
        ),
    )
    opts = parser.parse_args(argv)

    root = opts.root.expanduser().resolve()
    try:
        out, version, commit = export(root, opts.out, allow_dirty=bool(opts.allow_dirty))
    except Refusal as refusal:
        print(f"{PROG}: refused: {refusal}", file=sys.stderr)
        print("Nothing was written.", file=sys.stderr)
        return EXIT_REFUSED

    verdict = validate(out)
    print_owner_commands(out, version, commit)
    return EXIT_INVALID if verdict is False else EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main())
