"""The runtime bridge registers against a registry that already knows s0ma.

The bridge's helpers are decorated at import time and declare dependencies
on s0ma-core components. The core singleton now registers the framework as
it is created, so importing the bridge before ``s0ma.initialize()`` — as
every toolchain process does — logs nothing and leaves every declared
dependency resolvable.

Run in a subprocess so the import really is the first thing the process
does with the registry.
"""

from __future__ import annotations

import subprocess
import sys
import textwrap

_CODE = textwrap.dedent("""
    import logging
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(message)s")
    import s0ma_dsl.runtime_bridge.registration as bridge
    from s0ma.registry import get_registry

    registry = get_registry()
    for name in (
        "S0maDSL_register_module", "S0maDSL_register_relationship",
        "S0maDSL_register_test", "S0maDSL_register_doc_ref",
        "S0maDSL_register_doc_guide", "S0maDSL_register_example",
        "S0maDSL_register_integration_helper",
    ):
        spec = registry.get(name)
        assert spec is not None, name
        assert spec.dependencies, name
        for dep in spec.dependencies:
            assert registry.contains(dep), (name, dep)
    print("OK")
""")


def test_importing_the_bridge_first_is_quiet_and_resolvable() -> None:
    proc = subprocess.run(
        [sys.executable, "-c", _CODE],
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr
    assert "OK" in proc.stdout
    assert "not yet registered" not in proc.stderr, proc.stderr
    assert "WARNING" not in proc.stderr, proc.stderr
