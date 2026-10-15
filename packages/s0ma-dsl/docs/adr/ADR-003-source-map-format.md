# ADR-003: Custom .s0ma.map Source Map Format

**Status:** Accepted
**Date:** 2026-03-08
**Context:** Milestone 2 — Architecture Decisions & Spec Traceability
**References:** PRD FR-24, §2.6 (source map requirements), DSL Spec §2.1 (build pipeline)

---

## Decision

The transpiler emits a custom JSON-based `.s0ma.map` file per module. The format maps `.s0ma` source ranges to `.py` output ranges at both declaration-level and line-level granularity. We do not use the JavaScript Source Map v3 spec.

## Context

The transpiler needs source maps for:
- Mapping runtime exceptions back to `.s0ma` declarations
- Compiler/emitter debugging
- Supporting future IDE integration
- Correlating emitted decorators/registration blocks with source declarations

The PRD explicitly allows a custom format: "The product does not need JS-style source maps specifically; it needs a documented, reliable line-range mapping format."

## Rationale

### Why custom JSON (not JS Source Map v3)

The JavaScript Source Map v3 format (VLQ-encoded segments) is designed for minified JavaScript where column-level precision in heavily transformed output is essential. Our use case is different:

- `.s0ma` → `.py` is a declaration-level transformation, not a minification
- Line-level granularity is sufficient (declarations map to contiguous line ranges)
- The primary consumers are Python tools and AI agents, not browser devtools
- VLQ encoding adds complexity without benefit for our mapping density

A simple JSON format is:
- Directly readable by AI tools and Python scripts
- Deterministic (required by NFR-01)
- Easy to test with golden test comparisons
- Self-documenting

### Finalized Schema (v1.0.0, Milestone 13)

All line numbers are **1-indexed** and **inclusive**. Line ranges are represented as `{"start_line": int, "end_line": int}`.

```json
{
  "version": "1.0.0",
  "source_file": "signal_processor.s0ma",
  "output_file": "signal_processor.py",
  "mappings": {
    "declarations": [
      {
        "name": "process_signal",
        "type": "nerve",
        "source": {"start_line": 54, "end_line": 71},
        "output": {"start_line": 38, "end_line": 58},
        "body_source": {"start_line": 68, "end_line": 71},
        "body_output": {"start_line": 48, "end_line": 58},
        "decorator_output": {"start_line": 38, "end_line": 47}
      }
    ],
    "module_header": {
      "source": {"start_line": 1, "end_line": 8},
      "output_header": {"start_line": 1, "end_line": 5},
      "output_imports": {"start_line": 7, "end_line": 15},
      "output_all": {"start_line": 17, "end_line": 17},
      "output_registration": {"start_line": 19, "end_line": 25}
    }
  }
}
```

**Declaration mapping fields:**

| Field | Required | Description |
|-------|----------|-------------|
| `name` | Yes | Declaration name (e.g., `"process_signal"`). For standalone axons: `"source -> target"`. |
| `type` | Yes | One of: `"nerve"`, `"cell"`, `"ganglion"`, `"test"`, `"axon"`. |
| `source` | Yes | Line range in the `.s0ma` source file. From AST `SourceLocation`. |
| `output` | Yes | Line range in the generated `.py` file (full declaration extent). |
| `body_source` | Optional | Line range of the body in the `.s0ma` source (after `---`). Absent for standalone axons. |
| `body_output` | Optional | Line range of the body in the generated `.py` file. Absent for standalone axons. |
| `decorator_output` | Optional | Line range of the `@component(...)` decorator in the `.py` file. Only present for `@component`-decorated declarations (nerves, ganglia, class cells). |

**Module header mapping fields:**

| Field | Description |
|-------|-------------|
| `source` | Line range of the `module` declaration in the `.s0ma` source. |
| `output_header` | Line range of the generated docstring and transpiler comment. |
| `output_imports` | Line range of the generated import statements. |
| `output_all` | Line range of the generated `__all__` declaration. |
| `output_registration` | Line range of the generated `register_module()` call. |

This captures:
- Declaration-level ranges (full declaration extent in both source and output)
- Body-specific ranges (for mapping runtime errors to source bodies)
- Generated decorator ranges (for distinguishing authored code from generated metadata)
- Module header mapping (docstring, imports, `__all__`, registration call)

### Determinism

The format uses sorted keys and consistent formatting. Golden tests verify that repeated compilation produces identical `.s0ma.map` output.

## Consequences

- Simple to implement and test
- No external dependencies for source map generation or consumption
- Format is versioned (`version` field) for future evolution
- Not compatible with existing source map tooling (browser devtools, etc.) — acceptable since those tools don't consume Python anyway
- The schema was finalized in Milestone 13 (see schema above)

## Alternatives Considered

1. **JS Source Map v3** — rejected for complexity without corresponding benefit in our use case.
2. **No source maps** — rejected because PRD FR-24 requires them, and they are essential for debugging transpiler output.
3. **Inline source comments in `.py` output** — rejected because it pollutes the readable Python output (PRD P5) and doesn't support structured queries.
