#!/usr/bin/env python3
"""Keep the Claude integration in step with the monorepo it ships from.

Three things under ``integrations/`` are copies of something else, and a copy
that drifts is a defect nobody sees until a user has it installed:

1. **The launcher, twice.** ``integrations/launcher/s0ma_launch.py`` is the
   launcher; the Claude Code plugin and the Claude Desktop extension each
   carry a byte-for-byte copy of it, because each is packaged and shipped on
   its own. A stale copy means the plugin runs last week's launcher.
2. **The version, three times.** The plugin manifest, the extension manifest
   and the extension's ``pyproject.toml`` each state a version, and Claude
   Code treats the plugin's as a pin. They must equal the monorepo's lockstep
   version (PRD INV-4), so a release cut that bumps the four packages and
   forgets these ships a plugin claiming the old release.
3. **The feedback skill's body.** ``s0ma new project`` scaffolds a
   ``/s0ma-feedback`` skill into every project; the plugin ships the same
   text under its own invocation name. Two copies of one journey inside one
   release is two journeys. Only the front matter's ``name`` differs - the
   body is identical, byte for byte.

This script is the only thing that changes any of them:

    uv run python scripts/sync_integrations.py --check    # say what drifted
    uv run python scripts/sync_integrations.py --write    # put it back in step

``--check`` exits 0 when everything is in step and 1 otherwise, printing one
line per difference that names the file, what it is out of step with, and the
command that fixes it. ``--write`` fixes what it can and prints what it
changed; run twice, the second run changes nothing. It is the ``integrations``
stage of ``scripts/check.py``, so CI runs ``--check`` on Linux and Windows.

Standard library only, apart from one import of the monorepo's own
``s0ma_dsl`` - which is where the scaffolded feedback skill's text is
written, and reading it from there is what keeps ONE definition of that text
(``integrations/claude/tests/test_skills.py`` reads it the same way). Every
text write is UTF-8 with LF endings, both manifests are rewritten in the
canonical form their tests pin (two-space indent, sorted keys, trailing
newline), the launcher copies are byte copies, and the extension's TOML
version is a single-line substitution - no TOML writer, and no reformatting
of a file this script has no business reformatting.

``--root`` points the whole thing at another tree (the tests use a copy in a
temporary directory, so they never touch this one). It governs the files that
are read and written; the scaffolded skill's text always comes from the
``s0ma_dsl`` on the interpreter's path, because that is the package whose
behaviour the plugin has to match.
"""

from __future__ import annotations

import argparse
import importlib
import json
import re
import tomllib
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent

#: What a reader is told to run. Named once so every message says the same.
FIX_COMMAND = "uv run python scripts/sync_integrations.py --write"

#: The launcher, and the two copies of it that are shipped.
LAUNCHER_SOURCE = "integrations/launcher/s0ma_launch.py"
LAUNCHER_COPIES: tuple[str, ...] = (
    "integrations/claude/plugin/launcher/s0ma_launch.py",
    "integrations/claude/desktop/server/s0ma_launch.py",
)

#: The monorepo's lockstep version, read from one manifest. s0ma-mcp is the
#: one the integration ships (``s0ma-mcp`` is the server the launcher starts);
#: all four packages carry the same string by INV-4, and the
#: ``docs-version-currency`` stage is what proves that.
VERSION_SOURCE = "packages/s0ma-mcp/pyproject.toml"

#: Version sites inside the integration. JSON first, then the one TOML.
JSON_VERSION_SITES: tuple[str, ...] = (
    "integrations/claude/plugin/.claude-plugin/plugin.json",
    "integrations/claude/desktop/manifest.json",
)
TOML_VERSION_SITE = "integrations/claude/desktop/pyproject.toml"

#: The plugin's copy of the scaffolded feedback skill.
FEEDBACK_SKILL = "integrations/claude/plugin/skills/feedback/SKILL.md"

#: Where the scaffolded text is written, quoted in messages so a reader knows
#: which file to edit when the two are meant to diverge (they are not).
FEEDBACK_SOURCE = "packages/s0ma-dsl/src/s0ma_dsl/cli/new_project.py"

#: A top-level ``version = "..."`` line in a pyproject. The same shape
#: ``scripts/release_cut.sh`` reads and rewrites; exactly one is required, so
#: a manifest that grew a second one is reported rather than half-edited.
TOML_VERSION_RE = re.compile(r'(?m)^version = "([^"]*)"$')


class SyncError(Exception):
    """Something this script cannot read, and so cannot keep in step."""


# ---------------------------------------------------------------------------
# What one difference is
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Finding:
    """One file that is out of step, and how (or whether) it can be fixed.

    ``fix`` is ``None`` for a difference no rewrite can repair - a missing
    manifest, an unreadable one, a scaffolder that will not import. Those are
    reported as something to fix by hand rather than silently skipped.
    """

    path: str
    problem: str
    fix: Callable[[], None] | None
    change: str

    def message(self) -> str:
        """The single line ``--check`` prints for this difference."""
        if self.fix is None:
            return (
                f"out of step: {self.path} {self.problem} Put it right by hand: "
                f"`{FIX_COMMAND}` cannot fix this one."
            )
        return f"out of step: {self.path} {self.problem} Run: {FIX_COMMAND}"


# ---------------------------------------------------------------------------
# Reading things
# ---------------------------------------------------------------------------


def _write_text(path: Path, text: str) -> None:
    """Write *text* as UTF-8 with LF endings, on every platform."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8", newline="\n")


def _canonical_json(data: Any) -> str:
    """The committed form of both manifests: 2-space, sorted, one newline.

    Their tests pin exactly this, and the extension's pack script reads the
    version back out with ``sed``, which leans on the two-space indent.
    """
    return json.dumps(data, indent=2, sort_keys=True) + "\n"


def read_lockstep_version(root: Path) -> str:
    """The version every site here must state, read with tomllib.

    The message a failure carries is a phrase, not a sentence, and names no
    absolute path: the caller prints it after the repo-relative path, which
    is forward-slashed on every platform.
    """
    path = root / VERSION_SOURCE
    unchecked = "so no version site in the integration can be checked."
    try:
        with path.open("rb") as handle:
            data = tomllib.load(handle)
    except OSError as exc:
        raise SyncError(f"cannot be read ({exc.strerror}), {unchecked}") from exc
    except tomllib.TOMLDecodeError as exc:
        raise SyncError(f"cannot be parsed ({exc}), {unchecked}") from exc
    project = data.get("project")
    version = project.get("version") if isinstance(project, dict) else None
    if not isinstance(version, str) or not version:
        raise SyncError(f'states no [project] version = "...", {unchecked}')
    return version


def split_front_matter(text: str) -> tuple[str, str]:
    """``(front matter, body)`` for a skill file.

    The body is everything after the closing fence, its first character
    included, so two files with the same body compare equal whatever their
    front matter says. This is the same split
    ``integrations/claude/tests/test_skills.py`` makes, and the reason the
    plugin's skill can carry its own ``name`` and still be one text.
    """
    parts = text.split("---\n", 2)
    if len(parts) != 3 or parts[0] != "":
        raise SyncError(
            "is not a skill file: it must start with a '---' line, then its "
            "front matter, then a second '---' line."
        )
    return parts[1], parts[2]


def scaffolded_feedback_body() -> str:
    """The body of the feedback skill ``s0ma new project`` writes.

    Read from the renderer itself, never from a second copy of the words:
    the plugin's skill and the scaffolded one are one text with one author.
    """
    try:
        new_project = importlib.import_module("s0ma_dsl.cli.new_project")
    except ImportError as exc:  # pragma: no cover - a workspace without s0ma-dsl
        raise SyncError(
            f"cannot import s0ma_dsl.cli.new_project ({exc}); run this through "
            f"the workspace, with `uv run python scripts/sync_integrations.py`."
        ) from exc
    _, body = split_front_matter(new_project._feedback_skill_md())
    return body


# ---------------------------------------------------------------------------
# The three things kept in step
# ---------------------------------------------------------------------------


def launcher_findings(root: Path) -> list[Finding]:
    """The two shipped copies of the launcher, byte for byte."""
    source = root / LAUNCHER_SOURCE
    if not source.is_file():
        return [
            Finding(
                LAUNCHER_SOURCE,
                "is missing, so the copies inside the plugin and the extension "
                "have nothing to be copies of.",
                None,
                "",
            )
        ]
    original = source.read_bytes()
    findings: list[Finding] = []
    for relative in LAUNCHER_COPIES:
        target = root / relative
        if target.is_file() and target.read_bytes() == original:
            continue
        problem = (
            f"is missing; it is a byte-for-byte copy of {LAUNCHER_SOURCE}."
            if not target.is_file()
            else f"is not a byte-for-byte copy of {LAUNCHER_SOURCE}."
        )
        findings.append(
            Finding(
                relative,
                problem,
                _copy_bytes(target, original),
                f"copied from {LAUNCHER_SOURCE}",
            )
        )
    return findings


def _copy_bytes(target: Path, data: bytes) -> Callable[[], None]:
    """Bind one byte-mode copy into the callable ``--write`` runs."""

    def write() -> None:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)

    return write


def json_version_findings(root: Path, version: str) -> list[Finding]:
    """The two manifests state the lockstep version."""
    findings: list[Finding] = []
    for relative in JSON_VERSION_SITES:
        path = root / relative
        if not path.is_file():
            findings.append(Finding(relative, "is missing.", None, ""))
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            findings.append(Finding(relative, f"cannot be read ({exc}).", None, ""))
            continue
        if not isinstance(data, dict):
            findings.append(
                Finding(relative, "does not hold a JSON object.", None, "")
            )
            continue
        stated = data.get("version")
        if stated == version:
            continue
        said = f"states version {stated}" if isinstance(stated, str) else "states no version"
        was = stated if isinstance(stated, str) else "nothing"
        findings.append(
            Finding(
                relative,
                f"{said}; the monorepo is at {version} ({VERSION_SOURCE}).",
                _write_json_version(path, data, version),
                f"version {was} -> {version}",
            )
        )
    return findings


def _write_json_version(path: Path, data: dict[str, Any], version: str) -> Callable[[], None]:
    """Bind one manifest rewrite, in the formatting the file already has."""

    def write() -> None:
        _write_text(path, _canonical_json({**data, "version": version}))

    return write


def toml_version_findings(root: Path, version: str) -> list[Finding]:
    """The extension's ``pyproject.toml`` states the lockstep version."""
    relative = TOML_VERSION_SITE
    path = root / relative
    if not path.is_file():
        return [Finding(relative, "is missing.", None, "")]
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:  # pragma: no cover - unreadable file
        return [Finding(relative, f"cannot be read ({exc}).", None, "")]
    matches = TOML_VERSION_RE.findall(text)
    if len(matches) != 1:
        return [
            Finding(
                relative,
                f"has {len(matches)} top-level `version = \"...\"` line(s); "
                f"exactly one is expected, and this script edits that line only.",
                None,
                "",
            )
        ]
    stated = matches[0]
    if stated == version:
        return []
    return [
        Finding(
            relative,
            f"states version {stated}; the monorepo is at {version} ({VERSION_SOURCE}).",
            _write_toml_version(path, text, stated, version),
            f"version {stated} -> {version}",
        )
    ]


def _write_toml_version(
    path: Path, text: str, stated: str, version: str
) -> Callable[[], None]:
    """Bind the one-line substitution ``--write`` runs. Nothing else moves."""

    def write() -> None:
        _write_text(path, TOML_VERSION_RE.sub(f'version = "{version}"', text, count=1))

    return write


def feedback_findings(root: Path) -> list[Finding]:
    """The plugin's feedback skill has the scaffolded body."""
    relative = FEEDBACK_SKILL
    path = root / relative
    if not path.is_file():
        return [Finding(relative, "is missing.", None, "")]
    try:
        expected = scaffolded_feedback_body()
    except SyncError as exc:
        return [Finding(relative, f"cannot be checked: {exc}", None, "")]
    try:
        front, body = split_front_matter(path.read_bytes().decode("utf-8"))
    except (UnicodeDecodeError, SyncError) as exc:
        return [Finding(relative, f"{exc}", None, "")]
    if body == expected:
        return []
    return [
        Finding(
            relative,
            f"has a different body from the feedback skill `s0ma new project` "
            f"scaffolds ({FEEDBACK_SOURCE}); only the front matter's name may differ.",
            _write_skill_body(path, front, expected),
            f"body taken from {FEEDBACK_SOURCE}",
        )
    ]


def _write_skill_body(path: Path, front: str, body: str) -> Callable[[], None]:
    """Bind the skill rewrite: the plugin's front matter, the one body."""

    def write() -> None:
        _write_text(path, f"---\n{front}---\n{body}")

    return write


# ---------------------------------------------------------------------------
# Running
# ---------------------------------------------------------------------------


def collect(root: Path) -> list[Finding]:
    """Every difference in the tree at *root*, in a fixed order."""
    findings = launcher_findings(root)
    try:
        version = read_lockstep_version(root)
    except SyncError as exc:
        findings.append(Finding(VERSION_SOURCE, str(exc), None, ""))
    else:
        findings.extend(json_version_findings(root, version))
        findings.extend(toml_version_findings(root, version))
    findings.extend(feedback_findings(root))
    return findings


def _summary(root: Path) -> str:
    """What a clean run says it looked at, so a green line means something."""
    sites = len(JSON_VERSION_SITES) + 1
    try:
        version = read_lockstep_version(root)
    except SyncError:  # pragma: no cover - collect() already reported it
        return "the Claude integration is in step."
    return (
        f"the Claude integration is in step with the monorepo at {version}: "
        f"{len(LAUNCHER_COPIES)} launcher copies, {sites} version sites, 1 skill body."
    )


def run(root: Path, *, write: bool) -> int:
    """``--check`` or ``--write`` over the tree at *root*. 0 = in step."""
    findings = collect(root)
    if not findings:
        print(f"{'nothing to change: ' if write else 'in step: '}{_summary(root)}")
        return 0
    if not write:
        for finding in findings:
            print(finding.message())
        return 1

    unfixable = [finding for finding in findings if finding.fix is None]
    for finding in findings:
        if finding.fix is None:
            continue
        finding.fix()
        print(f"wrote: {finding.path} ({finding.change})")
    for finding in unfixable:
        print(finding.message())
    return 1 if unfixable else 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Keep the Claude plugin and Desktop extension in step with the "
            "monorepo: the two launcher copies, the three version sites and "
            "the feedback skill's body."
        )
    )
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument(
        "--check",
        action="store_true",
        help="report what is out of step and exit 1; change nothing",
    )
    mode.add_argument(
        "--write",
        action="store_true",
        help="put everything back in step and say what changed",
    )
    parser.add_argument(
        "--root",
        type=Path,
        default=ROOT,
        help="the repository to work on (default: the one this script lives in)",
    )
    opts = parser.parse_args(argv)
    return run(opts.root.resolve(), write=bool(opts.write))


if __name__ == "__main__":
    raise SystemExit(main())
