"""Shared fixtures for the s0ma-mcp test suite.

Round-trip tests run against *real* temporary projects assembled from
s0ma-dsl's own valid fixtures (the consolidation plan's M5 step 5), so
the tools are exercised end to end through the actual toolchain — no
mocks.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

#: Monorepo paths (repo-checkout only; the suite does not ship in wheels).
REPO_ROOT = Path(__file__).resolve().parents[3]
DSL_DOCS = REPO_ROOT / "packages" / "s0ma-dsl" / "docs"
DSL_FIXTURES = REPO_ROOT / "packages" / "s0ma-dsl" / "tests" / "fixtures"

#: A known-good multi-module fixture (valid in dev mode).
VALID_MULTI_MODULE = DSL_FIXTURES / "valid" / "multi_module"

PYPROJECT_TEMPLATE = """\
[project]
name = "agent_app"
version = "0.1.0"

[tool.s0ma]
source_roots = ["src"]
build_dir = "build"
"""

#: A self-contained module + example pair used by the run_example tests.
GREETINGS_S0MA = """\
module greetings
    layer: DOMAIN
    version: 1.0.0
    intent: "Greeting helpers demonstrating the example runner."
    exports: [greet]
    requires: none
    uses: none
    soft_requires: none
    runtime_only_requires: none
    deferred_requires: none
    exports_helpers: none

nerve greet :: DOMAIN
    kind: FUNCTION
    visibility: PUBLIC
    intent: "Build a friendly greeting string for a username."
    expects: "name is a non-empty string"
    guarantees: "returns a greeting containing the name"
    forbids: none
    evaluates_at: FUNCTION_BOUNDARY
    provides: none
    returns: none
    raises: none
    interface: none
    latency_ms: none
    depends_on: none
    internal: none
    expected_exceptions: none
    consumes_via_dict: none
    declares_attributes: none
    covered_by: none
    ---
    def greet(name):
        return f"Hello, {name}!"

example greet_example
    intent: "Demonstrates greeting a sample user by printing the result."
    demonstrates: [nerve::greet]
    runs_in: standalone
    ---
    print("Hello, Ada!")
"""

#: An intentionally invalid module: the nerve is missing its mandatory
#: contract fields, and an undeclared export rounds it out.
BROKEN_S0MA = """\
module broken
    layer: DOMAIN
    version: 1.0.0
    intent: "Deliberately invalid module for diagnostics tests."
    exports: [missing_component]

nerve incomplete :: DOMAIN
    kind: FUNCTION
    visibility: INTERNAL
    intent: "too short"
    ---
    def incomplete():
        pass
"""


def mainline_rules() -> list[str]:
    """The rules a tool result carries when NO condition applies.

    The canonical ``_SURVIVAL_RULES`` plus the one unconditional line F7
    appends — the pointer at ``learn_s0ma`` and ``s0ma://docs/index``.
    Written as a derivation, and in exactly one place, so the several
    suites that assert "nothing conditional fired" keep asserting that
    and never quietly become a second copy of the rules themselves.

    The conditional lines sit around it in a fixed order: the
    feedback-offer line above it (it is about the project the call
    names), and the frozen narration line below it (the M8 bench
    measured that line LAST and a moved line is an unmeasured line).
    """
    from s0ma_mcp import tools

    return [*tools._SURVIVAL_RULES, tools._DOCS_RULE]


def make_project(root: Path, *, sources: dict[str, str] | None = None) -> Path:
    """Create a minimal real s0ma project under ``root`` and return it.

    With ``sources=None`` the project's ``src/`` is populated from the
    dsl's ``valid/multi_module`` fixture; otherwise ``sources`` maps
    filename → ``.s0ma`` content.
    """
    src = root / "src"
    src.mkdir(parents=True)
    (root / "pyproject.toml").write_text(PYPROJECT_TEMPLATE, encoding="utf-8")
    if sources is None:
        for fixture in sorted(VALID_MULTI_MODULE.glob("*.s0ma")):
            shutil.copy(fixture, src / fixture.name)
    else:
        for filename, content in sources.items():
            (src / filename).write_text(content, encoding="utf-8")
    return root


@pytest.fixture()
def project(tmp_path: Path) -> Path:
    """A real temp project built from the dsl's valid multi_module fixture."""
    if not VALID_MULTI_MODULE.is_dir():  # pragma: no cover - repo layout guard
        pytest.skip("s0ma-dsl fixtures not available (not a repo checkout)")
    return make_project(tmp_path / "proj")


@pytest.fixture()
def greetings_project(tmp_path: Path) -> Path:
    """A temp project with one module + one runnable example declaration."""
    return make_project(
        tmp_path / "proj", sources={"greetings.s0ma": GREETINGS_S0MA}
    )
