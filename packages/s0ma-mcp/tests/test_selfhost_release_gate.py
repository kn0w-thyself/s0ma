"""The release-mode gate's own test declarations, executed for real.

Since SH-M5 the package's ``[tool.s0ma]`` mode is ``release``, whose
FR-DSL-6 coverage gate requires every PUBLIC nerve to be referenced by a
``test`` declaration (MISSING_TEST_COVERAGE) and every registered
``example`` to be embedded in a ``doc-guide`` (MISSING_EMBEDDED_EXAMPLE).
Those declarations live in the ``.s0ma`` sources next to the nerves they
verify and are emitted into the committed built modules as plain pytest
functions — but pytest's collection scope is ``tests/`` (``testpaths``),
so this module imports them into a collected namespace: the DSL-authored
tests run in this same suite, on every CI OS, against the same built
modules the server serves from. D-2's "tests stay plain pytest" holds —
collection and execution are pytest; only the authoring moved into the
``.s0ma`` sources, which is exactly the point of the release gate.

The ``example`` declaration is additionally exercised the most
self-hosted way available: through the server's own ``run_example`` tool,
against this very package — the doc-guide that embeds it shows code that
provably runs.
"""

from __future__ import annotations

from pathlib import Path

from s0ma_mcp.prompts import (  # noqa: F401 — pytest collects the import
    test_prompts_render_with_arguments_substituted,
)
from s0ma_mcp.resources import (  # noqa: F401 — pytest collects the imports
    test_guide_resources_serve_packaged_documents,
    test_meta_resources_render_live_documents,
)
from s0ma_mcp.tools import (  # noqa: F401 — pytest collects the imports
    test_read_only_tools_answer_structurally,
    test_writing_tools_refuse_invalid_targets,
)

from s0ma_mcp import tools

#: This package's own root (the [tool.s0ma] project the suite tests).
PACKAGE_ROOT = Path(__file__).resolve().parents[1]


def test_packaged_example_runs_through_the_example_tool() -> None:
    """The doc-guide's embedded example provably runs — via the server's own tool.

    ``describe_the_running_server`` is the example the SH-M5 doc-guide
    embeds; running it through ``run_example`` (subprocess-isolated, like
    any client would) proves the documentation's code block is live, not
    prose.
    """
    result = tools.run_example_tool(
        str(PACKAGE_ROOT),
        example_name="describe_the_running_server",
        source_path=str(PACKAGE_ROOT / "s0ma_src"),
    )
    assert result["ok"] is True, result
    (outcome,) = result["results"]
    assert outcome["passed"] is True
    assert "self-model components:" in outcome["stdout"]
