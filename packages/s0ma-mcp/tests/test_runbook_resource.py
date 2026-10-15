"""The O1 ops-story surface: the runbook resource + project_status runtime.

M4 (0.11.0, batch-01a): the bench's git-revert-of-live-DB failure (agents
reverting live runtime state because they treated committed state as the
deliverable) is answered by an ops story taught in-band. Two surfaces:

* ``s0ma://project/runbook`` — ``runbook_resource`` renders the project's
  declared run/health commands, env contracts, runtime ``state_paths``
  that must never be reverted, the module inventory, and the ops rules;
  when no project (or no runbook keys) is found it still serves, teaching
  what to declare. Rendered from the project discovered by walking up
  from the server's working directory; ``_render_runbook(start)`` is the
  testable core.
* ``project_status`` gains a ``runtime`` section carrying the same facts
  for an explicit project_root, plus a live-env summary (names only).

Exercised against the BUILT modules (``s0ma_mcp.resources`` /
``s0ma_mcp.tools``) — the same artifacts the wheel ships.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from s0ma_mcp.resources import _render_runbook, runbook_resource
from s0ma_mcp.tools import project_status_tool

if TYPE_CHECKING:
    from pathlib import Path

_DECLARED_PYPROJECT = """\
[project]
name = "opsdemo"
version = "0.1.0"

[tool.s0ma]
source_roots = ["src"]
run_command = "uv run opsdemo"
health_command = "curl -fsS localhost:8080/health"
state_paths = ["var/app.db", "var/uploads"]
runbook_notes = ["restart is safe", "back up var/ nightly"]

[tool.s0ma.env.DATABASE_URL]
required = true
fail_fast = true
default = "sqlite:///dev.db"

[tool.s0ma.env.PORT]
default = "8080"
"""

_BARE_PYPROJECT = """\
[project]
name = "bare"
version = "0.1.0"

[tool.s0ma]
source_roots = ["src"]
"""

#: Only one runbook field declared — a PARTIAL runbook (batch-01c M1).
_PARTIAL_PYPROJECT = """\
[project]
name = "partialops"
version = "0.1.0"

[tool.s0ma]
source_roots = ["src"]
run_command = "uv run partialops"
"""

#: batch-01c M1: the not-a-fault disclaimer phrases shared across the
#: runbook resource (undeclared/partial states) and the project_status
#: runtime hint. Their whole job is to stop a mid-diagnosis agent reading
#: an undeclared runbook as the root cause of a live service fault (bench
#: P2 r02, warm O3 — the one incorrect detection verdict in its cell).
_NOT_A_FAULT = "documentation gap, never a service fault"
_DIAGNOSE_FROM = "observed behavior, configuration, and environment"


def _mk_project(root: Path, pyproject: str) -> Path:
    (root / "pyproject.toml").write_text(pyproject, encoding="utf-8")
    (root / "src").mkdir(exist_ok=True)
    return root


# ---------------------------------------------------------------------------
# runbook_resource / _render_runbook
# ---------------------------------------------------------------------------


class TestRunbookResourceDeclared:
    def test_declared_fields_render(self, tmp_path: Path) -> None:
        _mk_project(tmp_path, _DECLARED_PYPROJECT)
        # A real module so the inventory section is non-empty.
        (tmp_path / "src" / "core_domain.s0ma").write_text(
            "module core_domain\n", encoding="utf-8"
        )
        runbook = _render_runbook(tmp_path)

        assert runbook.startswith("# Operational runbook — opsdemo")
        assert "run command: `uv run opsdemo`" in runbook
        assert "health command: `curl -fsS localhost:8080/health`" in runbook
        assert "`DATABASE_URL`: required=true, fail_fast=true" in runbook
        assert "`PORT`: required=false, fail_fast=false" in runbook
        assert "`var/app.db`" in runbook and "`var/uploads`" in runbook
        assert "restart is safe" in runbook
        assert "core_domain" in runbook

    def test_declared_runbook_still_carries_ops_rules(self, tmp_path: Path) -> None:
        _mk_project(tmp_path, _DECLARED_PYPROJECT)
        runbook = _render_runbook(tmp_path)
        # The O2 rule + the state_paths semantics — the whole point.
        assert "never restore committed versions of runtime data" in runbook
        assert "NEVER revert, restore, or regenerate" in runbook

    def test_fully_declared_runbook_has_no_disclaimer(
        self, tmp_path: Path
    ) -> None:
        # batch-01c M1: a runbook declaring every field is neither
        # undeclared nor partial — nothing is absent to mistake for a
        # fault, so it carries no not-a-fault disclaimer.
        _mk_project(tmp_path, _DECLARED_PYPROJECT)
        runbook = _render_runbook(tmp_path)
        assert _NOT_A_FAULT not in runbook
        assert "No runbook fields are declared" not in runbook
        assert "Some runbook fields are undeclared" not in runbook


class TestRunbookResourceTeaching:
    def test_bare_project_teaches_what_to_declare(self, tmp_path: Path) -> None:
        _mk_project(tmp_path, _BARE_PYPROJECT)
        runbook = _render_runbook(tmp_path)
        assert "not declared" in runbook
        assert "no environment variables declared" in runbook
        assert "no state_paths declared" in runbook
        assert "Declaring the runbook" in runbook
        # Even with nothing declared, the ops rules still teach.
        assert "never restore committed versions of runtime data" in runbook

    def test_undeclared_runbook_leads_with_not_a_fault_disclaimer(
        self, tmp_path: Path
    ) -> None:
        # batch-01c M1: a fully-undeclared runbook LEADS with the
        # not-a-fault disclaimer so runbook_declared: false cannot read
        # as a service defect.
        _mk_project(tmp_path, _BARE_PYPROJECT)
        runbook = _render_runbook(tmp_path)
        assert "No runbook fields are declared" in runbook
        assert _NOT_A_FAULT in runbook
        assert _DIAGNOSE_FROM in runbook
        # It LEADS — the disclaimer precedes the first field section.
        assert runbook.index(_NOT_A_FAULT) < runbook.index("## Run & health")

    def test_partial_runbook_leads_with_not_a_fault_disclaimer(
        self, tmp_path: Path
    ) -> None:
        # batch-01c M1: a PARTIAL runbook (some fields declared, some
        # not) leads with the partial-variant disclaimer — the
        # fully-undeclared wording does not apply, but the missing fields
        # still must not read as a fault.
        _mk_project(tmp_path, _PARTIAL_PYPROJECT)
        runbook = _render_runbook(tmp_path)
        assert "Some runbook fields are undeclared" in runbook
        assert "No runbook fields are declared" not in runbook
        assert _NOT_A_FAULT in runbook
        assert _DIAGNOSE_FROM in runbook
        # the one declared field still renders under its section
        assert "run command: `uv run partialops`" in runbook
        # the disclaimer LEADS the partial rendering
        assert runbook.index(_NOT_A_FAULT) < runbook.index("## Run & health")

    def test_non_project_directory_still_serves(self, tmp_path: Path) -> None:
        # No pyproject at all — discovery fails, teaching variant serves,
        # never an error, never empty.
        runbook = _render_runbook(tmp_path)
        assert runbook.startswith("# Operational runbook")
        assert "No s0ma project was resolved" in runbook
        assert "Declaring the runbook" in runbook
        assert "never restore committed versions of runtime data" in runbook
        # batch-01c M1: the not-a-fault disclaimer leads here too.
        assert _NOT_A_FAULT in runbook
        assert runbook.index(_NOT_A_FAULT) < runbook.index(
            "No s0ma project was resolved"
        )

    def test_zero_arg_resource_serves_from_cwd(self) -> None:
        # The public resource renders against the server cwd; whatever
        # variant results, it is non-empty markdown with the ops rule.
        served = runbook_resource()
        assert served.startswith("# Operational runbook")
        assert "never restore committed versions of runtime data" in served


# ---------------------------------------------------------------------------
# project_status runtime section
# ---------------------------------------------------------------------------


class TestProjectStatusRuntime:
    def test_declared_runtime_summary(self, tmp_path: Path, monkeypatch) -> None:
        _mk_project(tmp_path, _DECLARED_PYPROJECT)
        monkeypatch.delenv("DATABASE_URL", raising=False)
        monkeypatch.setenv("PORT", "9999")

        runtime = project_status_tool(str(tmp_path))["runtime"]
        assert runtime["runbook_declared"] is True
        assert runtime["run_command"] == "uv run opsdemo"
        assert runtime["health_command"] == "curl -fsS localhost:8080/health"
        assert runtime["state_paths"] == ["var/app.db", "var/uploads"]
        assert runtime["runbook_notes"] == ["restart is safe", "back up var/ nightly"]
        assert runtime["runbook_resource"] == "s0ma://project/runbook"
        env_by_name = {e["name"]: e for e in runtime["env"]}
        assert env_by_name["DATABASE_URL"] == {
            "name": "DATABASE_URL",
            "required": True,
            "fail_fast": True,
            "has_default": True,
        }
        # DATABASE_URL is required and unset -> missing; PORT is not
        # required -> never in the missing list even when it happens to be
        # set.
        assert runtime["missing_required_env"] == ["DATABASE_URL"]

    def test_runtime_never_leaks_values(self, tmp_path: Path, monkeypatch) -> None:
        _mk_project(tmp_path, _DECLARED_PYPROJECT)
        monkeypatch.setenv("DATABASE_URL", "postgres://user:secret@host/db")
        runtime = project_status_tool(str(tmp_path))["runtime"]
        blob = json.dumps(runtime)
        # Neither the declared default nor the live value ever appears —
        # names and contracts only.
        assert "sqlite" not in blob
        assert "secret" not in blob
        assert runtime["missing_required_env"] == []

    def test_absent_runbook_teaches(self, tmp_path: Path) -> None:
        _mk_project(tmp_path, _BARE_PYPROJECT)
        runtime = project_status_tool(str(tmp_path))["runtime"]
        assert runtime["runbook_declared"] is False
        assert runtime["run_command"] is None
        assert runtime["env"] == []
        assert runtime["state_paths"] == []
        assert "hint" in runtime
        assert "s0ma://project/runbook" in runtime["hint"]
        # batch-01c M1: the hint beside runbook_declared: false LEADS with
        # the not-a-fault disclaimer so the absence cannot read as a fault.
        assert _NOT_A_FAULT in runtime["hint"]
        assert _DIAGNOSE_FROM in runtime["hint"]


class TestNotAFaultRegression:
    """batch-01c M1 regression (bench P2 r02, warm O3).

    An env-var fault was injected and the service was misbehaving; the
    agent read ``s0ma://project/runbook``, saw ``runbook_declared:
    false``, and concluded the *absence of a declared runbook* was the
    root cause — the one ``incorrect`` detection verdict in its cell.
    Both surfaces an agent consults mid-diagnosis (the runbook resource
    and the ``project_status`` runtime hint) must now LEAD with the
    not-a-fault disclaimer, so an undeclared runbook can never read as a
    live service defect.
    """

    def test_undeclared_runbook_read_during_live_fault_disclaims(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        # The O3 shape: a real project whose runbook is undeclared.
        _mk_project(tmp_path, _BARE_PYPROJECT)
        # The injected live fault — a misconfigured env var, the service
        # misbehaving. The disclaimer is unconditional on the undeclared
        # state; the env var mirrors the scenario faithfully.
        monkeypatch.setenv("DATABASE_URL", "postgres://broken-host/db")

        # (1) the agent reads the runbook resource
        runbook = _render_runbook(tmp_path)
        assert _NOT_A_FAULT in runbook
        assert _DIAGNOSE_FROM in runbook
        assert runbook.index(_NOT_A_FAULT) < runbook.index("## Run & health")

        # (2) the agent reads project_status; runbook_declared is false,
        # but the hint disclaims the absence as a fault
        runtime = project_status_tool(str(tmp_path))["runtime"]
        assert runtime["runbook_declared"] is False
        assert _NOT_A_FAULT in runtime["hint"]
        assert _DIAGNOSE_FROM in runtime["hint"]
