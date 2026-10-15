"""``example.runs_in`` value validation (A8 T2).

``runs_in:`` selects a dispatcher arm in s0ma-core's
``ExampleDispatcher.dispatch``. Only three arms exist —
``standalone``, ``pytest``, ``integration`` — and the DSL spec §4.12.3
declares the field as ``runs_in: <standalone | pytest | integration>``.

Before A8 the value was parsed free-form: a typo such as ``pytests``
parsed clean, transpiled clean, and only surfaced at run time (the
dispatcher's ``ValueError``, or the doc-emitter's silent coercion back
to ``standalone``). An unknown mode can never execute, so it is now a
layer-1 ``PARSE_ERROR`` — an error in every strictness mode, like the
sibling ``category:`` and ``covers: {source:}`` value checks.
"""

from __future__ import annotations

from textwrap import dedent
from typing import TYPE_CHECKING

import pytest

from s0ma_dsl.cli.main import S0maCLI
from s0ma_dsl.errors import S0maParseError
from s0ma_dsl.parser.s0ma_parser import (
    VALID_EXAMPLE_RUNS_IN,
    parse_s0ma,
    parse_s0ma_with_warnings,
)

if TYPE_CHECKING:
    from pathlib import Path

MODULE_NAME = "runs_in_fixture"

# The three modes, quoted from spec §4.12.3's declared order.
SPEC_MODES = ("standalone", "pytest", "integration")


def _source(runs_in: str) -> str:
    """A minimal, otherwise-clean module whose example declares *runs_in*.

    The ``greet`` nerve is present so a valid ``runs_in`` reaches exit 0
    at check time — an unresolved ``demonstrates:`` target would mask the
    thing under test.
    """
    return dedent(f"""
        module {MODULE_NAME}
            layer: DOMAIN
            version: 1.0.0
            intent: "Fixture module for runs_in value validation."
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
            intent: "Returns a greeting for the given username."
            expects: "username is a non-empty string"
            guarantees: "returns a non-empty greeting string"
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
            def greet(username):
                return f"Hello, {{username}}!"
        example greet_example
            intent: "Demonstrates calling the greet nerve."
            demonstrates: [nerve::greet]
            runs_in: {runs_in}
            ---
            print("hello")
    """).lstrip()


def _write(tmp_path: Path, runs_in: str) -> Path:
    path = tmp_path / f"{MODULE_NAME}.s0ma"
    path.write_text(_source(runs_in), encoding="utf-8")
    return path


# ---------------------------------------------------------------------------
# The valid set
# ---------------------------------------------------------------------------


class TestValidModesParse:
    def test_constant_is_exactly_the_spec_set(self) -> None:
        # Guards the constant against drifting from spec §4.12.3 and from
        # ExampleDispatcher.dispatch's three arms.
        assert VALID_EXAMPLE_RUNS_IN == SPEC_MODES

    @pytest.mark.parametrize("mode", SPEC_MODES)
    def test_each_mode_parses_and_round_trips(self, mode: str) -> None:
        result = parse_s0ma(_source(mode), f"{MODULE_NAME}.s0ma")
        assert len(result.examples) == 1
        assert result.examples[0].runs_in == mode

    @pytest.mark.parametrize("mode", SPEC_MODES)
    def test_each_mode_parses_on_the_warnings_path(self, mode: str) -> None:
        # ``_build_example`` has two call sites (parse_s0ma and
        # parse_s0ma_with_warnings); both must agree.
        result, _warnings = parse_s0ma_with_warnings(
            _source(mode), f"{MODULE_NAME}.s0ma",
        )
        assert result.examples[0].runs_in == mode

    @pytest.mark.parametrize("mode", SPEC_MODES)
    def test_each_mode_passes_check(self, tmp_path: Path, mode: str) -> None:
        path = _write(tmp_path, mode)
        rc = S0maCLI().run([
            "--project-root", str(tmp_path), "check", str(path), "--mode", "strict",
        ])
        # A clean parse; any remaining exit code would be a different
        # diagnostic, not the runs_in one.
        assert rc == 0


# ---------------------------------------------------------------------------
# The rejected set
# ---------------------------------------------------------------------------


class TestUnknownModeRejected:
    @pytest.mark.parametrize(
        "bad",
        [
            "pytests",        # plausible typo
            "unit",           # a mode that sounds real but has no arm
            "Standalone",     # case matters — no silent normalisation
            "INTEGRATION",
            "standalone2",
        ],
    )
    def test_unknown_value_raises_parse_error(self, bad: str) -> None:
        with pytest.raises(S0maParseError) as excinfo:
            parse_s0ma(_source(bad), f"{MODULE_NAME}.s0ma")
        err = excinfo.value
        assert err.code == "PARSE_ERROR"
        assert err.severity == "error"
        # Names the offending value...
        assert repr(bad) in err.message
        # ...and all three valid modes, in both message and remediation.
        for mode in SPEC_MODES:
            assert mode in err.message
            assert mode in err.remediation

    def test_diagnostic_is_source_located(self) -> None:
        with pytest.raises(S0maParseError) as excinfo:
            parse_s0ma(_source("pytests"), f"{MODULE_NAME}.s0ma")
        err = excinfo.value
        assert err.file == f"{MODULE_NAME}.s0ma"
        # Points at the example declaration's header line, not line 0/1.
        expected_line = _source("pytests").splitlines().index(
            "example greet_example",
        ) + 1
        assert err.line == expected_line
        assert err.context.get("declaration_name") == "greet_example"
        assert err.context.get("runs_in") == "pytests"
        assert err.context.get("valid") == list(SPEC_MODES)

    def test_unknown_value_raises_on_the_warnings_path(self) -> None:
        with pytest.raises(S0maParseError):
            parse_s0ma_with_warnings(
                _source("pytests"), f"{MODULE_NAME}.s0ma",
            )


class TestCheckTimeFailure:
    @pytest.mark.parametrize(
        "strictness", ["migration", "dev", "strict", "release"],
    )
    def test_fails_in_every_strictness_mode(
        self, tmp_path: Path, strictness: str, capsys,
    ) -> None:
        """An unknown mode can never execute — no mode tolerates it."""
        path = _write(tmp_path, "pytests")
        rc = S0maCLI().run([
            "--project-root", str(tmp_path),
            "check", str(path), "--mode", strictness,
        ])
        assert rc == 1
        out = capsys.readouterr().out
        assert "PARSE_ERROR" in out
        assert "runs_in" in out

    def test_message_names_the_three_modes_at_check_time(
        self, tmp_path: Path, capsys,
    ) -> None:
        path = _write(tmp_path, "pytests")
        S0maCLI().run([
            "--project-root", str(tmp_path), "check", str(path), "--mode", "strict",
        ])
        out = capsys.readouterr().out
        for mode in SPEC_MODES:
            assert mode in out
        assert "'pytests'" in out
