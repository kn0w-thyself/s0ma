"""A body Python cannot compile fails ``s0ma check`` and ``s0ma build``.

Each body is read with ``ast.parse``, which accepts some code that Python
then refuses to compile: a ``nonlocal`` declared after the name is
assigned, a ``return`` with a value inside an async generator. Before
``GENERATED_FILE_COMPILE_ERROR`` such a module checked clean in strict mode,
built with exit 0, and failed only when something imported it. Now check
and build compile each emitted module (``compile()``, nothing executed) and
report a failure as an error at the ``.s0ma`` line of the body it came
from, in every mode. A module that compiles sees no change.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

import pytest

from s0ma_dsl.cli.main import S0maCLI
from s0ma_dsl.config import (
    ERROR_CODE_DESCRIPTIONS,
    SEVERITY_MATRIX,
    StrictnessMode,
)

if TYPE_CHECKING:
    from pathlib import Path

CODE = "GENERATED_FILE_COMPILE_ERROR"

_HEADER = """\
module probe_domain
    layer: DOMAIN
    version: 0.1.0
    intent: "Probe a body that parses and does not compile."
    exports: [{name}]
    requires: []
    uses: []

    soft_requires: none
    runtime_only_requires: none
    deferred_requires: none
    exports_helpers: none
nerve {name} :: DOMAIN
    kind: FUNCTION
    visibility: PUBLIC
    intent: "Probe one body that Python cannot compile."
    expects: "Whatever the body takes."
    guarantees: "Nothing: the body does not compile."
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
"""

#: The reproduced case: ``total`` is assigned, then declared ``nonlocal``.
NONLOCAL_BODY = """\
    def tally(values: list[int]) -> int:
        total = 0

        def add(value: int) -> None:
            total = value
            nonlocal total
            total += value

        for value in values:
            add(value)
        return total
"""

#: A second shape ``ast.parse`` accepts: ``return 2`` in an async generator.
ASYNC_GENERATOR_BODY = """\
    async def stream() -> object:
        yield 1
        return 2
"""

CASES = {
    "nonlocal": ("tally", NONLOCAL_BODY, "nonlocal total", "nonlocal declaration"),
    "async-generator": (
        "stream", ASYNC_GENERATOR_BODY, "return 2", "async generator",
    ),
}


def _scaffold(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> Path:
    project = tmp_path / "probe"
    assert S0maCLI().run(["new", "project", str(project), "--quiet"]) == 0
    capsys.readouterr()
    return project


def _add_probe(project: Path, case: str) -> tuple[Path, int]:
    """Write the probe module; return its path and the failing line."""
    name, body, marker, _ = CASES[case]
    text = _HEADER.format(name=name) + body
    path = project / "src" / "core" / "probe_domain.s0ma"
    path.write_text(text, encoding="utf-8", newline="\n")
    (line,) = [
        number
        for number, content in enumerate(text.splitlines(), start=1)
        if content.strip() == marker
    ]
    return path, line


def _check(project: Path, mode: str, capsys: pytest.CaptureFixture[str]):
    rc = S0maCLI().run([
        "--project-root", str(project), "check", "--mode", mode,
        "--format", "json",
    ])
    return rc, json.loads(capsys.readouterr().out)


def _build(
    project: Path, capsys: pytest.CaptureFixture[str], *extra: str,
):
    rc = S0maCLI().run([
        "--project-root", str(project), "build", str(project),
        "--mode", "dev", "--format", "json", *extra,
    ])
    return rc, json.loads(capsys.readouterr().out)


def _compile_findings(report: dict) -> list[dict]:
    return [f for f in report["errors"] if f["code"] == CODE]


class TestRegistry:
    def test_the_code_is_an_error_in_every_mode(self) -> None:
        assert SEVERITY_MATRIX[CODE] == dict.fromkeys(StrictnessMode, "error")

    def test_the_code_is_described(self) -> None:
        assert ERROR_CODE_DESCRIPTIONS[CODE]


@pytest.mark.parametrize("case", sorted(CASES))
class TestUncompilableBody:
    def test_check_fails_at_the_body_line(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str], case: str,
    ) -> None:
        project = _scaffold(tmp_path, capsys)
        source, line = _add_probe(project, case)

        rc, report = _check(project, "strict", capsys)

        assert rc == 1
        (finding,) = _compile_findings(report)
        assert finding["severity"] == "error"
        assert finding["file"].endswith("probe_domain.s0ma")
        assert finding["line"] == line
        assert CASES[case][3] in finding["message"]
        assert finding["remediation"]
        assert source.read_text(encoding="utf-8")  # untouched

    def test_build_fails_at_the_body_line_and_writes_no_module(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str], case: str,
    ) -> None:
        project = _scaffold(tmp_path, capsys)
        _, line = _add_probe(project, case)

        rc, report = _build(project, capsys, "--no-cache")

        assert rc == 1
        (finding,) = _compile_findings(report)
        assert finding["file"].endswith("probe_domain.s0ma")
        assert finding["line"] == line
        assert not (project / "build" / "probe_domain.py").exists()


@pytest.mark.parametrize("mode", [m.value for m in StrictnessMode])
def test_check_reports_it_as_an_error_in_every_mode(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], mode: str,
) -> None:
    project = _scaffold(tmp_path, capsys)
    _, line = _add_probe(project, "nonlocal")

    rc, report = _check(project, mode, capsys)

    assert rc == 1
    (finding,) = _compile_findings(report)
    assert finding["line"] == line


def test_a_clean_scaffold_checks_and_builds_as_before(
    tmp_path: Path, capsys: pytest.CaptureFixture[str],
) -> None:
    project = _scaffold(tmp_path, capsys)
    build_dir = project / "build"
    before = {
        p.relative_to(build_dir): p.read_bytes()
        for p in sorted(build_dir.rglob("*")) if p.is_file()
    }

    rc, report = _check(project, "strict", capsys)
    assert rc == 0
    assert report["errors"] == []
    assert report["warnings"] == []

    rc, report = _build(project, capsys, "--no-cache")
    assert rc == 0
    assert _compile_findings(report) == []
    after = {
        p.relative_to(build_dir): p.read_bytes()
        for p in sorted(build_dir.rglob("*")) if p.is_file()
    }
    assert after == before
