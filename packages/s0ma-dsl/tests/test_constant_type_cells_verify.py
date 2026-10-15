"""A transpiled module with a CONSTANT cell and a TYPE cell verifies clean.

The emitter registers those cells through ``register_constant`` and
``register_type`` with the owning ``module_path``; s0ma-core derives
``qualified_name`` from it. Without that derivation the phantom-limb
check rejected the empty name as an ERROR in both the Structural
Verifier and the Coverage Auditor, so any application with one such
cell reported UNHEALTHY. No other test in any package ran the verifiers
over a registry holding a registered constant or type.

The verification runs in a subprocess: the transpiled module writes to
the module-global registry, and ``bootstrap_imports`` must see a fresh
one.
"""

from __future__ import annotations

import subprocess
import sys
import textwrap
from typing import TYPE_CHECKING

from s0ma_dsl.cli.main import EXIT_SUCCESS, S0maCLI

if TYPE_CHECKING:
    from pathlib import Path

_MODULE = """\
module cell_shapes
    layer: DOMAIN
    version: 0.1.0
    intent: "A module whose only declarations are a constant and a type alias."
    exports: [MAX_ITEMS, ItemId]
    requires: none
    uses: none
    soft_requires: none
    runtime_only_requires: none
    deferred_requires: none
    exports_helpers: none
cell MAX_ITEMS :: DOMAIN
    kind: CONSTANT
    visibility: PUBLIC
    intent: "Upper bound on the items one request may carry."
    schema: "int constant = 3"
    invariants: none
    covered_by: none
    ---
    MAX_ITEMS = 3

cell ItemId :: DOMAIN
    kind: TYPE
    visibility: PUBLIC
    intent: "Identifier of one item, a plain string alias."
    schema: "type alias for str"
    invariants: none
    covered_by: none
    ---
    ItemId = str
"""


def test_constant_and_type_cells_verify_healthy(tmp_path: Path) -> None:
    source_dir = tmp_path / "src"
    source_dir.mkdir()
    (source_dir / "cell_shapes.s0ma").write_text(_MODULE, encoding="utf-8")
    build_dir = tmp_path / "build"
    rc = S0maCLI().run([
        "build", str(source_dir),
        "--output-dir", str(build_dir),
        "--mode", "dev",
        "--no-cache",
    ])
    assert rc == EXIT_SUCCESS, "fixture build failed"

    code = textwrap.dedent(f"""
        from pathlib import Path
        import s0ma
        from s0ma.bootstrap import bootstrap_imports
        from s0ma.verifiers import verify_all

        registry = s0ma.initialize(persist=False)
        modules = bootstrap_imports(Path({str(build_dir)!r}))
        assert set(modules) == {{"cell_shapes"}}, sorted(modules)

        constant = registry.get("MAX_ITEMS")
        alias = registry.get("ItemId")
        assert constant is not None and alias is not None
        assert constant.qualified_name == "cell_shapes.MAX_ITEMS", constant
        assert alias.qualified_name == "cell_shapes.ItemId", alias
        assert constant.metadata["kind_detail"] == "CONSTANT"
        assert alias.metadata["kind_detail"] == "TYPE"

        report = verify_all(registry)
        assert report.passed, report.describe()
        own = [
            a for r in report.results for a in r.anomalies
            if a.component_name in ("MAX_ITEMS", "ItemId")
            and a.severity.name == "ERROR"
        ]
        assert own == [], own
        print("OK")
    """)
    proc = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, (
        f"verification failed:\nstdout={proc.stdout!r}\nstderr={proc.stderr!r}"
    )
    assert "OK" in proc.stdout
