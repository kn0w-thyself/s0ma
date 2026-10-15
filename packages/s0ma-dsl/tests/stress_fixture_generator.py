"""Generate a synthetic project with 50+ .s0ma files for stress testing.

Creates a realistic multi-module project with cross-module dependencies,
multiple declaration types, and varying complexity. Used by test_performance.py.

The generator is deterministic — the same seed produces identical output.
"""

from __future__ import annotations

import random
from pathlib import Path

# Layers cycle for variety
LAYERS = ["DOMAIN", "APPLICATION", "INFRASTRUCTURE", "PRESENTATION"]

# Nerve kinds
NERVE_KINDS = ["SERVICE", "FUNCTION", "ADAPTER", "ORCHESTRATOR"]

# Cell kinds (body-compatible)
CELL_KINDS_CLASS = ["MODEL", "ENUM", "EXCEPTION", "CONFIG"]
CELL_KINDS_ASSIGN = ["CONSTANT"]


def generate_stress_project(output_dir: Path, num_modules: int = 55, seed: int = 42) -> list[Path]:
    """Generate a synthetic multi-module .s0ma project.

    Args:
        output_dir: Directory to write .s0ma files into.
        num_modules: Number of modules to generate (default 55).
        seed: Random seed for deterministic generation.

    Returns:
        List of generated .s0ma file paths.
    """
    rng = random.Random(seed)
    output_dir.mkdir(parents=True, exist_ok=True)

    # Plan module names and their components
    modules = _plan_modules(num_modules, rng)

    # Build dependency graph (each module can depend on earlier modules)
    _assign_dependencies(modules, rng)

    # Generate .s0ma files
    generated: list[Path] = []
    for mod in modules:
        path = output_dir / f"{mod['name']}.s0ma"
        content = _render_module(mod)
        path.write_text(content, encoding="utf-8")
        generated.append(path)

    return generated


def _plan_modules(num_modules: int, rng: random.Random) -> list[dict]:
    """Plan module names, layers, and components."""
    modules = []
    for i in range(num_modules):
        layer = LAYERS[i % len(LAYERS)]
        mod_name = f"mod_{i:03d}"

        # Each module has 3-8 declarations
        num_nerves = rng.randint(1, 4)
        num_cells = rng.randint(1, 3)

        nerves = []
        for n in range(num_nerves):
            name = f"{mod_name}_fn_{n}"
            kind = rng.choice(NERVE_KINDS)
            vis = "PUBLIC" if n == 0 else rng.choice(["PUBLIC", "INTERNAL"])
            nerves.append({"name": name, "kind": kind, "visibility": vis})

        cells = []
        for c in range(num_cells):
            use_class = rng.random() > 0.3
            if use_class:
                kind = rng.choice(CELL_KINDS_CLASS)
                name = f"{mod_name}_Cell_{c}"
            else:
                kind = "CONSTANT"
                name = f"{mod_name}_CONST_{c}"
            vis = "PUBLIC" if c == 0 else rng.choice(["PUBLIC", "INTERNAL"])
            cells.append({"name": name, "kind": kind, "visibility": vis, "is_class": use_class})

        exports = [n["name"] for n in nerves if n["visibility"] == "PUBLIC"]
        exports += [c["name"] for c in cells if c["visibility"] == "PUBLIC"]

        modules.append({
            "name": mod_name,
            "layer": layer,
            "nerves": nerves,
            "cells": cells,
            "exports": exports,
            "uses": [],
            "uses_entries": [],
            "version": f"1.{i % 10}.0",
        })

    return modules


def _assign_dependencies(modules: list[dict], rng: random.Random) -> None:
    """Assign cross-module uses dependencies (only to earlier modules)."""
    for i, mod in enumerate(modules):
        if i == 0:
            continue  # First module has no deps

        # Pick 0-3 modules to depend on (from earlier modules only)
        max_deps = min(3, i)
        num_deps = rng.randint(0, max_deps)
        dep_indices = rng.sample(range(i), num_deps)

        for dep_idx in dep_indices:
            dep_mod = modules[dep_idx]
            if not dep_mod["exports"]:
                continue

            # Pick 1-2 exports to use
            num_imports = min(rng.randint(1, 2), len(dep_mod["exports"]))
            imported = rng.sample(dep_mod["exports"], num_imports)

            for imp_name in imported:
                qualified = f"{dep_mod['name']}.{imp_name}"
                mod["uses_entries"].append(qualified)
                mod["uses"].append((dep_mod["name"], imp_name))


def _render_module(mod: dict) -> str:
    """Render a module dict to .s0ma source text."""
    lines = []

    # Module header
    lines.append(f"module {mod['name']}")
    lines.append(f"    layer: {mod['layer']}")
    lines.append(f"    version: {mod['version']}")
    lines.append(f'    intent: "Synthetic module {mod["name"]} for stress testing"')

    lines.append("    requires: none")

    if mod["uses_entries"]:
        uses_str = ", ".join(mod["uses_entries"])
        lines.append(f"    uses: [{uses_str}]")
    else:
        lines.append("    uses: none")

    if mod["exports"]:
        exports_str = ", ".join(mod["exports"])
        lines.append(f"    exports: [{exports_str}]")
    else:
        lines.append("    exports: []")

    lines.extend([
        "    soft_requires: none",
        "    runtime_only_requires: none",
        "    deferred_requires: none",
        "    exports_helpers: none",
    ])

    lines.append("")

    # Cells
    for cell in mod["cells"]:
        lines.extend(_render_cell(cell, mod["layer"]))
        lines.append("")

    # Nerves
    for nerve in mod["nerves"]:
        lines.extend(_render_nerve(nerve, mod))
        lines.append("")

    return "\n".join(lines)


def _render_cell(cell: dict, layer: str) -> list[str]:
    """Render a cell declaration."""
    lines = []
    lines.append(f"cell {cell['name']} :: {layer}")
    lines.append(f"    kind: {cell['kind']}")
    lines.append(f"    visibility: {cell['visibility']}")
    lines.append(f'    intent: "Synthetic cell {cell["name"]} for testing"')
    lines.append("    invariants: none")
    lines.append("    covered_by: none")

    if cell["is_class"]:
        if cell["kind"] == "EXCEPTION":
            lines.append('    schema: "Exception class"')
            lines.append("    ---")
            lines.append(f"    class {cell['name']}(Exception):")
            lines.append("        pass")
        elif cell["kind"] == "ENUM":
            lines.append('    schema: "Enum class"')
            lines.append("    ---")
            lines.append(f"    class {cell['name']}:")
            lines.append("        VALUE_A = \"a\"")
            lines.append("        VALUE_B = \"b\"")
        else:
            lines.append('    schema: "Data model class"')
            lines.append("    ---")
            lines.append(f"    class {cell['name']}:")
            lines.append("        value: str = \"default\"")
    else:
        lines.append('    schema: "Constant value"')
        lines.append("    ---")
        lines.append(f"    {cell['name']} = 42")

    return lines


def _render_nerve(nerve: dict, mod: dict) -> list[str]:
    """Render a nerve declaration."""
    lines = []
    lines.append(f"nerve {nerve['name']} :: {mod['layer']}")
    lines.append(f"    kind: {nerve['kind']}")
    lines.append(f"    visibility: {nerve['visibility']}")
    lines.append(f'    intent: "Synthetic nerve {nerve["name"]} for testing"')
    lines.append('    expects: "Valid input data"')
    lines.append('    guarantees: "Returns processed result"')
    lines.append("    forbids: none")
    lines.append("    evaluates_at: FUNCTION_BOUNDARY")
    lines.extend([
        "    provides: none",
        "    returns: none",
        "    raises: none",
        "    interface: none",
        "    latency_ms: none",
        "    internal: none",
        "    expected_exceptions: none",
        "    consumes_via_dict: none",
        "    declares_attributes: none",
        "    covered_by: none",
    ])

    # Add intra-module depends_on to first cell if it exists
    if mod["cells"]:
        target_cell = mod["cells"][0]
        lines.append("    depends_on:")
        lines.append(
            f"        {target_cell['name']}: "
            "{relation: READS, carries: \"data\", coupling: LOOSE}"
        )
    else:
        lines.append("    depends_on: none")

    lines.append("    ---")
    lines.append(f"    def {nerve['name']}(data: str) -> dict:")

    # Reference used components in body to satisfy evidence rules
    used_names = [name for _, name in mod["uses"]]
    if used_names:
        for uname in used_names[:2]:
            lines.append(f"        _ = {uname}")

    lines.append("        return {\"result\": data}")

    return lines


if __name__ == "__main__":
    out = Path("tests/fixtures/stress")
    files = generate_stress_project(out)
    print(f"Generated {len(files)} .s0ma files in {out}")
