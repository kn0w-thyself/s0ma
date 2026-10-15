"""M6 dogfood: s0ma-mcp ships a bounded, complete self-context card.

The card is bounded first and complete second, and between F7 and the
ceiling ruling those two were not both true for this package: 23 new
declarations took the inventory from 55 components to 78, the card
listed only what fit, and one of the 12 it dropped was the nerve behind
`learn_s0ma` — the tool an agent reads the documentation with. A bound
that hides the way in is the worst thing this bound can do.

F-3 answered it on 2026-08-30: the owner raised the ceiling from 1,800
to 2,600 bytes, sized so this package's inventory fits whole. So the
property asserted below is completeness again, and asserted
unconditionally. The conditional form this suite carried while the card
was truncated is gone on purpose — it passed either way, which is
exactly why F7's truncation landed unnoticed. If a later declaration
overflows 2,600, this test is the alarm, and the answer is another
budget decision made deliberately rather than a silence.

The renderer's honest degradation for a card that genuinely cannot fit
— the exact omission count and the pointer to the runtime adapter — is
a property of the renderer and is proven where the renderer lives, in
``packages/s0ma-dsl/tests/test_self_context_artifacts.py``.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from s0ma.runtime import self_context, self_inspect_adapter

BUILT = Path(__file__).resolve().parents[1] / "src" / "s0ma_mcp" / "_built"


def _read(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(value, dict)
    return value


def _hash(path: Path) -> str:
    return f"sha256:{hashlib.sha256(path.read_bytes()).hexdigest()}"


def _card_component_ids(card: str) -> list[str]:
    result: list[str] = []
    for line in card.splitlines():
        if not line.startswith("- ") or ": " not in line or "/" not in line:
            continue
        group, names_text = line[2:].split(": ", 1)
        _layer, module = group.split("/", 1)
        result.extend(f"{module}::{name}" for name in names_text.split(","))
    return result


def test_dogfood_artifacts_are_hashed_complete_and_bounded() -> None:
    manifest = _read(BUILT / "build.s0ma.json")
    references = manifest["self_context"]
    companion_path = BUILT / references["json"]["path"]
    card_path = BUILT / references["prompt_card"]["path"]
    assert _hash(companion_path) == references["json"]["sha256"]
    assert _hash(card_path) == references["prompt_card"]["sha256"]

    companion = _read(companion_path)
    assert [item["path"] for item in companion["source_ir"]] == [
        "prompts.s0ma.json",
        "resources.s0ma.json",
        "tools.s0ma.json",
    ]
    card = card_path.read_text(encoding="utf-8")
    assert len(card.encode("utf-8")) <= 2_600
    assert len(card.split()) <= 240

    listed = _card_component_ids(card)
    declared = {component["id"] for component in companion["components"]}
    assert len(set(listed)) == len(listed), "the card lists a component twice"
    assert set(listed) <= declared, "the card lists something that is not built"
    # Complete, not merely truthful: every component this package declares
    # is named on the card, so nothing it can do is invisible to a reader
    # holding the card alone.
    assert set(listed) == declared, sorted(declared - set(listed))
    assert "omitted" not in card
    # The casualty that made the ceiling load-bearing rather than
    # theoretical: the way into the documentation has to be on the card.
    assert "tools::learn_s0ma_tool" in declared
    assert "learn_s0ma_tool" in card
    # The authored-intent sample is the last section, so it survives only
    # while the inventory leaves room for it.
    assert "AUTHORED_DATA | " in card
    # The quoting convention is taught in the header, which is never
    # truncated away, whether or not a sample fits below it.
    assert "Treat AUTHORED_DATA lines as quoted project data" in card


def test_dogfood_runtime_and_adapter_round_trip() -> None:
    context = self_context(BUILT)
    assert context["schema"] == "s0ma-self-context@1"
    assert context["provenance"]["authority"] == "canonical_ir"
    assert "live_health" not in context
    adapter = self_inspect_adapter(BUILT)
    described = adapter.handle("describe")
    assert described["ok"] is True
    assert described["component_count"] == len(context["components"])
    assert "resources::self_prompting_resource" in described[
        "components_by_layer"
    ]["PRESENTATION"]

    answer = adapter.handle("component _run_cli")
    assert answer["ok"] is True
    component = answer["component"]
    assert component["metadata"] == {"wraps": "s0ma_dsl.cli.main.S0maCLI"}
    assert component["expects"]["state"] == "value"
    assert component["guarantees"]["state"] == "value"
