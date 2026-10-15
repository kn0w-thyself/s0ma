#!/usr/bin/env python3
"""Generate onboarding and MCP inventories from their canonical artifacts.

Default mode is a read-only gate. Pass ``--write`` after a deliberate served
surface or onboarding change, review the marker-only diff, then run the default
mode again. The live MCP-vs-snapshot equality remains owned by
``test_mcp_surface_snapshot.py``; this script binds the snapshot to the two
README inventories and the canonical getting-started document.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
SNAPSHOT = ROOT / "packages/s0ma-mcp/tests/snapshots/mcp_surface.json"
ROOT_README = ROOT / "README.md"
MCP_README = ROOT / "packages/s0ma-mcp/README.md"
GETTING_STARTED = ROOT / "docs/getting-started.md"
PACKAGED_GETTING_STARTED = (
    ROOT / "packages/s0ma-mcp/src/s0ma_mcp/_docs/getting-started.md"
)

SURFACE_START = "<!-- BEGIN GENERATED MCP SURFACE -->"
SURFACE_END = "<!-- END GENERATED MCP SURFACE -->"
JOURNEY_START = "<!-- BEGIN GENERATED GETTING STARTED -->"
JOURNEY_END = "<!-- END GENERATED GETTING STARTED -->"


class GenerationError(RuntimeError):
    """The canonical source or a marker contract is malformed."""


def _snapshot() -> dict[str, list[dict[str, Any]]]:
    document = json.loads(SNAPSHOT.read_text(encoding="utf-8"))
    if set(document) != {"tools", "resources", "prompts"}:
        raise GenerationError("surface snapshot must contain tools/resources/prompts")
    for tool in document["tools"]:
        required = {"name", "description", "annotations", "inputSchema", "outputSchema"}
        if not required <= set(tool):
            raise GenerationError(f"tool snapshot is incomplete: {tool.get('name')!r}")
    return document


def _cell(value: object) -> str:
    return str(value).replace("|", "\\|").replace("\n", " ").strip()


def _summary(description: object) -> str:
    text = _cell(description)
    return text.split(".", 1)[0] + "." if "." in text else text


def _tool_inputs(tool: dict[str, Any]) -> str:
    schema = tool["inputSchema"]
    properties = schema.get("properties", {})
    required = set(schema.get("required", []))
    items = [
        f"`{name}`{' (required)' if name in required else ''}"
        for name in properties
    ]
    return ", ".join(items) if items else "None"


def _annotation_value(value: object) -> str:
    if value is None:
        return "—"
    return "true" if value is True else "false" if value is False else _cell(value)


def _render_root_surface(document: dict[str, list[dict[str, Any]]]) -> str:
    tools = ", ".join(f"`{item['name']}`" for item in document["tools"])
    resources = ", ".join(f"`{item['uri']}`" for item in document["resources"])
    prompts = ", ".join(f"`{item['name']}`" for item in document["prompts"])
    return (
        "The served surface is generated from the committed MCP snapshot; its live "
        "names, annotations, and input/output schemas are checked in CI.\n\n"
        f"- **Tools:** {tools}.\n"
        f"- **Resources:** {resources}.\n"
        f"- **Prompts:** {prompts}."
    )


def _render_mcp_surface(document: dict[str, list[dict[str, Any]]]) -> str:
    lines = [
        "The tables below are generated from the served-surface snapshot. Do not edit them by hand.",
        "",
        "### Tools",
        "",
        "| Tool | Inputs | Job to be done |",
        "|---|---|---|",
    ]
    for tool in document["tools"]:
        lines.append(
            f"| `{tool['name']}` | {_tool_inputs(tool)} | {_summary(tool['description'])} |"
        )
    lines += [
        "",
        "### Tool annotations",
        "",
        "| Tool | `readOnlyHint` | `destructiveHint` | `idempotentHint` | `openWorldHint` |",
        "|---|---:|---:|---:|---:|",
    ]
    for tool in document["tools"]:
        annotations = tool["annotations"] or {}
        values = [
            _annotation_value(annotations.get(key))
            for key in (
                "readOnlyHint",
                "destructiveHint",
                "idempotentHint",
                "openWorldHint",
            )
        ]
        lines.append(f"| `{tool['name']}` | {' | '.join(values)} |")
    lines += [
        "",
        "### Resources",
        "",
        "| URI | MIME type | Content |",
        "|---|---|---|",
    ]
    for resource in document["resources"]:
        lines.append(
            f"| `{resource['uri']}` | `{resource['mimeType']}` | "
            f"{_summary(resource['description'])} |"
        )
    lines += [
        "",
        "### Prompts",
        "",
        "| Prompt | Arguments | Journey |",
        "|---|---|---|",
    ]
    for prompt in document["prompts"]:
        arguments = ", ".join(
            f"`{arg['name']}`{' (required)' if arg.get('required') else ''}"
            for arg in prompt.get("arguments") or []
        ) or "None"
        lines.append(
            f"| `{prompt['name']}` | {arguments} | {_summary(prompt['description'])} |"
        )
    return "\n".join(lines)


def _replace_marker(text: str, start: str, end: str, body: str) -> str:
    if text.count(start) != 1 or text.count(end) != 1:
        raise GenerationError(f"expected exactly one {start!r}/{end!r} marker pair")
    before, rest = text.split(start, 1)
    _old, after = rest.split(end, 1)
    return f"{before}{start}\n{body.rstrip()}\n{end}{after}"


def _expected_files() -> dict[Path, str]:
    document = _snapshot()
    journey = GETTING_STARTED.read_text(encoding="utf-8").rstrip()
    root = ROOT_README.read_text(encoding="utf-8")
    root = _replace_marker(root, JOURNEY_START, JOURNEY_END, journey)
    root = _replace_marker(
        root, SURFACE_START, SURFACE_END, _render_root_surface(document)
    )
    mcp = _replace_marker(
        MCP_README.read_text(encoding="utf-8"),
        SURFACE_START,
        SURFACE_END,
        _render_mcp_surface(document),
    )
    return {
        ROOT_README: root,
        MCP_README: mcp,
        PACKAGED_GETTING_STARTED: journey + "\n",
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--write", action="store_true", help="replace marker blocks and packaged copy"
    )
    options = parser.parse_args(argv)
    try:
        expected = _expected_files()
    except (GenerationError, OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"MCP README generation error: {exc}")
        return 1

    stale: list[Path] = []
    for path, content in expected.items():
        if options.write:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8", newline="\n")
        elif not path.is_file() or path.read_text(encoding="utf-8") != content:
            stale.append(path)
    if stale:
        for path in stale:
            print(f"STALE {path.relative_to(ROOT).as_posix()}")
        print("Run `python scripts/generate_mcp_readme_surfaces.py --write` and review.")
        return 1
    print(
        "MCP README surfaces: "
        f"{'updated' if options.write else 'current'} "
        f"({len(_snapshot()['tools'])} tools, "
        f"{len(_snapshot()['resources'])} resources, "
        f"{len(_snapshot()['prompts'])} prompts)"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
