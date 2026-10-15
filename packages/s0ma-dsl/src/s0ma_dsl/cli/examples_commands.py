"""``s0ma examples`` subcommand handlers (plan M7).

The transpiler-side CLI surface for the s0ma-core example runner. We
delegate to ``s0ma.examples.ExampleRunner`` so the runtime owns the
sandboxing semantics; this module just discovers parsed example
declarations, registers them in a transient registry, and dispatches.

If ``s0ma.examples`` is not yet available (s0ma-core M6 not landed),
the command exits with a clear, actionable message rather than
silently faking a result. Per plan §10 ("Bootstrap / Chicken-and-Egg
Notes"), this stub-failure is acceptable and intentional.
"""

from __future__ import annotations

import json
import sys
from typing import TYPE_CHECKING

from s0ma.decorators import component
from s0ma.types import ComponentKind, Layer

from s0ma_dsl.config import StrictnessMode

if TYPE_CHECKING:
    import argparse

__all__ = [
    "cmd_examples_run",
]

_EXIT_SUCCESS = 0
_EXIT_VALIDATION_ERROR = 1
_EXIT_USAGE_ERROR = 2
_EXIT_INTERNAL_ERROR = 3


@component(
    name="S0maDSL_cmd_examples_run",
    kind=ComponentKind.FUNCTION,
    layer=Layer.FRAMEWORK,
    intent=(
        "Handler for `s0ma examples run`: discovers .s0ma examples and delegates execution to "
        "s0ma-core's ExampleRunner."
    ),
    idempotent=True,
    is_framework=True,
)
def cmd_examples_run(args: argparse.Namespace) -> int:
    """Implement ``s0ma examples run [<name>]``.

    Discovers ``example`` declarations in the source path, transpiles
    them through the standard pipeline so registrations land in the
    runtime registry, then asks ``s0ma.examples.ExampleRunner`` to
    execute either every example or just the one named on the
    command line.

    Validation gates execution: blocking (severity ``error``)
    diagnostics are printed and the command exits 1 without running
    any example, matching the s0ma-mcp ``run_example`` tool. Warnings
    alone never block.
    """
    try:
        from s0ma.examples import ExampleRunner
    except ImportError:
        print(
            "Example runner unavailable: s0ma.examples.ExampleRunner is not "
            "installed (s0ma-core M6 not yet landed in this environment).\n"
            "Install or update the s0ma-core dependency to run examples.",
            file=sys.stderr,
        )
        return _EXIT_INTERNAL_ERROR

    from s0ma_dsl.cli.docs_commands import _parse_and_validate_project
    from s0ma_dsl.cli.main import _print_diagnostics, _split_diagnostics
    from s0ma_dsl.codegen.doc_emitter import compute_doc_hashes
    from s0ma_dsl.codegen.doc_emitter.registrations import (
        build_example_registration,
    )

    mode = StrictnessMode(args.mode)
    modules, filenames, diagnostics = _parse_and_validate_project(
        args.source, mode,
    )
    errors, _warnings = _split_diagnostics(diagnostics)
    if errors:
        _print_diagnostics(
            diagnostics,
            output_format=args.output_format,
            files_processed=len(modules),
            mode=args.mode,
        )
        return _EXIT_VALIDATION_ERROR
    if not modules:
        print(f"No .s0ma files found at: {args.source}", file=sys.stderr)
        return _EXIT_USAGE_ERROR

    # Build the same DocHashIndex the build pipeline uses so example
    # source spans match what would be registered at import time.
    _hashes = compute_doc_hashes(modules, filenames=filenames)

    # Stand up an isolated registry with every example registered.
    from s0ma.registry import ComponentRegistry

    registry = ComponentRegistry(persist=False)
    discovered: list[str] = []
    for module_name in sorted(modules.keys()):
        s0ma_module = modules[module_name]
        filename_basename = filenames.get(module_name, f"{module_name}.s0ma")
        for ex in s0ma_module.examples:
            reg = build_example_registration(
                ex,
                filename=filename_basename,
            )
            try:
                registry.register_example(
                    name=reg.name,
                    module=reg.module,
                    intent=reg.intent,
                    demonstrates=reg.demonstrates,
                    runs_in=reg.runs_in,
                    body=reg.body,
                    source_span=reg.source_span,
                )
                discovered.append(ex.name)
            except Exception as exc:  # pragma: no cover - defensive
                print(
                    f"Failed to register example {ex.name}: {exc}",
                    file=sys.stderr,
                )
                return _EXIT_INTERNAL_ERROR

    if not discovered:
        print(f"No example declarations found at: {args.source}")
        return _EXIT_SUCCESS

    target = args.name
    if target is not None and target not in discovered:
        print(
            f"Example '{target}' not found. Discovered: "
            f"{', '.join(sorted(discovered))}",
            file=sys.stderr,
        )
        return _EXIT_USAGE_ERROR

    runner = ExampleRunner(registry, timeout_seconds=args.timeout)
    if target is None:
        results = runner.run_all()
    else:
        by_name = {reg.name: reg for reg in runner.discover()}
        results = [runner.run(by_name[target])]

    if args.output_format == "json":
        print(json.dumps(
            [
                {
                    "name": r.example_name,
                    "passed": r.passed,
                    "duration_ms": r.duration_ms,
                    "stdout": r.stdout,
                    "stderr": r.stderr,
                    "returncode": r.returncode,
                    "timed_out": r.timed_out,
                    "error": r.error,
                }
                for r in results
            ],
            indent=2,
            sort_keys=True,
        ))
    else:
        for r in results:
            print(r.summary())

    failed = any(not r.passed for r in results)
    return _EXIT_VALIDATION_ERROR if failed else _EXIT_SUCCESS
