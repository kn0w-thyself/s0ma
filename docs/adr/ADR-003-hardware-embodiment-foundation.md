# ADR-003: Hardware embodiment foundation — physical-facts vocabulary and runtime surfaces

**Status:** Accepted — owner-ratified 2026-08-09 (HW-D-1; HW-D-2 keeps
`NOCICEPTION`)
**Date:** 2026-08-09
**Governing input:** owner direction of 2026-08-09 (hardware-readiness
feedback: project-agnostic, universal-first, extend by necessity, keep
s0ma intuitive and efficient)

## Context

Two independent embodied PoC designs (the sensing-first board pilot and the
`limb0` delivery cart) both need s0ma applications to state physical facts
about components — dimensions, composition, power draw, articulation — and
both need the runtime half of the product to notice physical reality
disagreeing with declarations *the moment it happens*. Today the schema has
no physical vocabulary at all, so each project would invent its own metadata
dialect, and runtime anomalies are poll-only. Both designs also
independently requested the same three runtime gaps (validator access to
call arguments, an anomaly push surface, physical resource expectations) —
convergence that motivates fixing them once, project-agnostically.

## Decision

### 1. No new declaration type

Hardware is not modeled from outside — it is **embodied**: brought inside the
self-knowing boundary as ordinary components, at the same lowest sensible
level of abstraction as everything else. Hardware does not get a new grammar
object. The existing organs suffice:

- a physical **device** attached to the system is an `integration`
  (factory + startup smoke probe + manifest);
- reading a sensor or driving an actuator is behavior — a `nerve`;
- reading models and physical value types are `cell`s
  (`dataclass_invariants:` carry physical ranges);
- baselines and envelopes watched over time are `ganglion`s;
- physical facts are `metadata:` entries under the vocabulary below.

A dedicated `hardware`/`sensor` declaration would fork the grammar for zero
verification gain. Revisit only if a verifier ever needs hardware-specific
*semantics* the opaque map cannot carry (necessity rule).

### 2. Universal physical-facts vocabulary (`hw_*` metadata keys)

Standardized names for facts that apply to essentially all hardware. Every
key is optional — **author what you know; omit what you don't; never
invent**. Keys embed their unit (house precedent: `latency_ms`). The `hw_`
prefix marks a key as ADR-003 vocabulary so tooling can collect physical
facts without a schema.

| Key | Type | Meaning |
|---|---|---|
| `hw_part` | str | Canonical part/model identity (e.g. "LIS3DH", "MG996R") |
| `hw_mounted` | str | Where on the body, free prose (e.g. "rear, transverse, full width") |
| `hw_length_mm` / `hw_width_mm` / `hw_height_mm` | float | Rough physical envelope |
| `hw_mass_g` | float | Mass |
| `hw_material` | str | Composition (e.g. "3 mm plywood, PTFE glide tip") |
| `hw_range_of_motion_deg` | float | Articulated parts only: usable sweep |
| `hw_supply_voltage_v` | float | Nominal supply rail |
| `hw_current_ma_typical` | float | Typical current draw |
| `hw_current_ma_max` | float | Worst-case current draw (stall/peak) |

Extending the vocabulary requires a second project that needs the key and an
amendment to this ADR — universal-first, growth by demonstrated necessity.

### 3. Sense/actuator attribute namespaces

Physical roles are declared with the existing structural-attribute
mechanism: `declares_attributes: [sense:<modality>]` and
`[actuator:<modality>]` (e.g. `sense:light`, `actuator:servo`). Uniqueness
budgets, where wanted, use the existing `[tool.s0ma.attribute_budgets]`
table. No new mechanism.

### 4. Physical ResourceProfile bounds

`ResourceProfile` gains three optional physical expectations beside the
existing latency/error/memory ones:

- `expected_max_current_ma` — upper bound on current draw;
- `expected_max_temperature_c` — upper bound on temperature;
- `expected_min_voltage_v` — lower bound on supply voltage (sag detection).

Breaches are `INFLAMMATION`, exactly like every other resource-profile
deviation. Ingestion is application-driven: the app samples its own
instruments and reports via `MetricsCollector.record_physical(...)`; s0ma
never reads hardware itself. Readings live in the metrics layer only — they
are never written into deterministic build artifacts.

### 5. NOCICEPTION and the runtime anomaly stream

A live call that violates an executable contract is *pain*, and the
taxonomy names it: `AnomalyKind.NOCICEPTION`. The `precondition` /
`postcondition` decorators publish a NOCICEPTION anomaly on the new
**runtime anomaly stream** (`s0ma.anomaly_stream`) immediately before
raising `ContractViolationError`; `record_physical` publishes its
INFLAMMATION crossings on the same stream. The stream is a process-wide
subscription channel mirroring
`ComponentRegistry.subscribe_import_hook_anomalies`: synchronous dispatch in
registration order, subscriber exceptions logged and swallowed, dispatch on
the detecting call's thread. This replaces health-poll timers in embodied
hosts without adding any framework thread or queue.

### 6. Trust boundary for live readings

Live sensor/telemetry values placed before an agent are **observational
runtime data**, a channel of their own beside the authored self-model. The
host labels them as untrusted observations, parallel to the `AUTHORED_DATA`
rule of ADR-002, and never merges them into build artifacts. Learned
baselines (calibration results) reach the self-model only by explicit
re-authoring and rebuild — experience updates the model through the front
door, preserving build determinism.

## Consequences

- Cost to the core is one enum member, three optional dataclass fields, and
  one dependency-free module; everything else is convention.
- Both PoC projects author against one vocabulary from day one; a future
  lint over `hw_*` keys becomes possible without migration.
- The self-model can render a physical profile for any component
  (`format_component_detail` includes the physical bounds).
- Guides and the patterns reference document the conventions in the plan's
  M2, after ratification of this ADR.
