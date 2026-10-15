"""The batch-01a P2 telemetry counters derive from the served-call triple.

M4 (0.11.0, batch-01a): the telemetry wrapper appends one JSONL record
per served call. Each record carries a derived ``counters`` list —
``s0ma_mcp._telemetry_counters(surface, name, result)`` — computed purely
from the ``(surface, name, result)`` the wrapper already sees, so the
tags exist ONLY in the JSONL and only when the hook is enabled (the
record itself only exists then; see ``test_telemetry_invisibility.py``
for the byte-identity / sink-only-when-on proof over real stdio).

This module is the definitive per-tag coverage: the four counters the
batch-01a verification plan watches — ``runbook_read`` (the new
``s0ma://project/runbook`` resource), ``inline_rule_impression`` (a tool
result carrying the inline survival ``rules``), ``refused_overwrite``
(``build_project`` surfacing ``GENERATED_FILE_DRIFT``), and
``drift_shown`` (``check`` surfacing it) — plus the negative cases that
keep the tags specific rather than blanket-on-every-call.
"""

from __future__ import annotations

from typing import Any

from s0ma_mcp import (
    _TELEMETRY_SCHEMA,
    _telemetry_counters,
    _telemetry_result_has_declaration_suggestion,
    _telemetry_result_has_drift,
    _telemetry_result_has_new_error_override,
)

# ---------------------------------------------------------------------------
# Sample result shapes (the exact dict shapes the tools return)
# ---------------------------------------------------------------------------

_DRIFT_ERROR: dict[str, Any] = {
    "ok": False,
    "exit_code": 1,
    "diagnostics": {
        "errors": [{"code": "GENERATED_FILE_DRIFT", "severity": "error"}],
        "warnings": [],
    },
}

_DRIFT_WARNING: dict[str, Any] = {
    "ok": True,
    "exit_code": 0,
    "diagnostics": {
        "errors": [],
        "warnings": [{"code": "GENERATED_FILE_DRIFT", "severity": "warning"}],
    },
}

_CLEAN_CHECK: dict[str, Any] = {
    "ok": True,
    "exit_code": 0,
    "diagnostics": {"errors": [], "warnings": []},
}

_RULES_RESULT: dict[str, Any] = {
    "ok": True,
    "rules": ["only edit .s0ma", "one def per body"],
}

# M1 (0.13.0): a check result whose diagnostics carry a corrected
# declaration block on a self-healing contract finding.
_SUGGESTION_RESULT: dict[str, Any] = {
    "ok": False,
    "exit_code": 1,
    "diagnostics": {
        "errors": [
            {
                "code": "PROVIDES_KEY_MISMATCH",
                "severity": "error",
                "suggested_declaration": "provides: [store.open, store.migrate]",
            }
        ],
        "warnings": [],
    },
}

# A MISSING_PACKAGE that hit the ambiguity guard — no block emitted.
_GUARDED_RESULT: dict[str, Any] = {
    "ok": False,
    "exit_code": 1,
    "diagnostics": {
        "errors": [{"code": "MISSING_PACKAGE", "severity": "error"}],
        "warnings": [],
    },
}

# M2 (0.13.0): a build_project result whose diagnostics carry a
# build_override block — allow_new_errors=true waved NEW check errors
# past the build gate (the DSL stamps `build_override` into the JSON doc,
# which rides through under result["diagnostics"]).
_OVERRIDE_RESULT: dict[str, Any] = {
    "ok": True,
    "exit_code": 0,
    "diagnostics": {
        "errors": [],
        "warnings": [
            {
                "code": "PROVIDES_KEY_MISMATCH",
                "severity": "warning",
                "suggested_declaration": "provides: [connect, flush]",
            }
        ],
        "build_override": {
            "allow_new_errors": True,
            "new_error_count": 1,
            "new_errors": [{"code": "PROVIDES_KEY_MISMATCH"}],
        },
    },
}


class TestRunbookReadCounter:
    def test_runbook_uri_counts(self) -> None:
        assert _telemetry_counters(
            "resource", "s0ma://project/runbook", "any markdown"
        ) == ["runbook_read"]

    def test_runbook_counts_regardless_of_result_shape(self) -> None:
        # The read is surface/name-based — a str body, a None (failed
        # read), or a dict all still register the read.
        for result in ("md", None, {"ok": True}):
            assert "runbook_read" in _telemetry_counters(
                "resource", "s0ma://project/runbook", result
            )

    def test_other_resources_do_not_count(self) -> None:
        assert _telemetry_counters(
            "resource", "s0ma://guide/survival-card", "x"
        ) == []
        assert _telemetry_counters("resource", "s0ma://meta/version", "x") == []


class TestInlineRuleImpressionCounter:
    def test_result_with_rules_counts(self) -> None:
        assert _telemetry_counters("tool", "init_project", _RULES_RESULT) == [
            "inline_rule_impression"
        ]

    def test_any_tool_name_carrying_rules_counts(self) -> None:
        # The tag is result-driven (the `rules` key), not name-gated:
        # init_project / scaffold_module / describe_server all carry it.
        for name in ("scaffold_module", "describe_server"):
            assert _telemetry_counters("tool", name, _RULES_RESULT) == [
                "inline_rule_impression"
            ]

    def test_empty_rules_does_not_count(self) -> None:
        assert _telemetry_counters("tool", "init_project", {"rules": []}) == []
        assert _telemetry_counters("tool", "init_project", {"ok": True}) == []


class TestDriftCounters:
    def test_build_project_drift_is_refused_overwrite(self) -> None:
        assert _telemetry_counters("tool", "build_project", _DRIFT_ERROR) == [
            "refused_overwrite"
        ]

    def test_check_drift_is_drift_shown(self) -> None:
        assert _telemetry_counters("tool", "check", _DRIFT_WARNING) == [
            "drift_shown"
        ]

    def test_clean_check_has_no_drift_counter(self) -> None:
        assert _telemetry_counters("tool", "check", _CLEAN_CHECK) == []

    def test_drift_helper_scans_errors_and_warnings(self) -> None:
        assert _telemetry_result_has_drift(_DRIFT_ERROR) is True
        assert _telemetry_result_has_drift(_DRIFT_WARNING) is True
        assert _telemetry_result_has_drift(_CLEAN_CHECK) is False
        assert _telemetry_result_has_drift(None) is False
        assert _telemetry_result_has_drift("not a dict") is False
        assert _telemetry_result_has_drift({"diagnostics": None}) is False

    def test_drift_only_split_by_tool_name(self) -> None:
        # A drift finding on a name other than build_project/check yields
        # no drift counter (transpile would refuse via its own path, but
        # the two named tools are the batch-01a signals).
        assert _telemetry_counters("tool", "transpile", _DRIFT_ERROR) == []


class TestDeclarationSuggestionCounter:
    """M1 (0.13.0): a surfaced ``suggested_declaration`` block registers
    the teaching exposure — result-driven, not name-gated."""

    def test_check_suggestion_counts(self) -> None:
        assert _telemetry_counters("tool", "check", _SUGGESTION_RESULT) == [
            "declaration_suggestion_shown"
        ]

    def test_any_tool_surfacing_a_suggestion_counts(self) -> None:
        # The tag is result-driven: build_project / transpile surface the
        # same DSL diagnostics, so they register it too.
        for name in ("build_project", "transpile"):
            assert _telemetry_counters("tool", name, _SUGGESTION_RESULT) == [
                "declaration_suggestion_shown"
            ]

    def test_guarded_finding_has_no_suggestion_counter(self) -> None:
        # A MISSING_PACKAGE that declined to suggest (ambiguity guard)
        # carries no block, so no teaching-exposure tag.
        assert _telemetry_counters("tool", "check", _GUARDED_RESULT) == []

    def test_clean_check_has_no_suggestion_counter(self) -> None:
        assert _telemetry_counters("tool", "check", _CLEAN_CHECK) == []

    def test_resource_surface_never_counts(self) -> None:
        # The tag is tool-surface only (resources do not carry diagnostics).
        assert _telemetry_counters("resource", "check", _SUGGESTION_RESULT) == []

    def test_suggestion_helper_scans_errors_and_warnings(self) -> None:
        assert _telemetry_result_has_declaration_suggestion(_SUGGESTION_RESULT) is True
        assert _telemetry_result_has_declaration_suggestion(_GUARDED_RESULT) is False
        assert _telemetry_result_has_declaration_suggestion(_CLEAN_CHECK) is False
        assert _telemetry_result_has_declaration_suggestion(None) is False
        assert _telemetry_result_has_declaration_suggestion("not a dict") is False
        assert _telemetry_result_has_declaration_suggestion({"diagnostics": None}) is False
        # A warning-severity finding carrying a block also counts (dev-mode
        # PROVIDES_KEY_MISMATCH is a warning, not an error).
        warn_block = {
            "diagnostics": {
                "errors": [],
                "warnings": [
                    {"code": "MISSING_PACKAGE", "suggested_declaration": "requires: []"}
                ],
            }
        }
        assert _telemetry_result_has_declaration_suggestion(warn_block) is True

    def test_suggestion_and_drift_can_coexist(self) -> None:
        # A check that surfaces BOTH a drift warning and a suggestion emits
        # both tags, drift first (stable order).
        combined: dict[str, Any] = {
            "diagnostics": {
                "errors": [
                    {
                        "code": "PROVIDES_KEY_MISMATCH",
                        "suggested_declaration": "provides: [a]",
                    }
                ],
                "warnings": [
                    {"code": "GENERATED_FILE_DRIFT", "severity": "warning"}
                ],
            }
        }
        assert _telemetry_counters("tool", "check", combined) == [
            "drift_shown",
            "declaration_suggestion_shown",
        ]


class TestBuildOverrideCounter:
    """M2 (0.13.0): a ``build_override`` block registers the escape-hatch
    use — ``build_project``-only, so the bench can count how often agents
    waved NEW check errors through instead of fixing them."""

    def test_build_override_counts(self) -> None:
        assert _telemetry_counters(
            "tool", "build_project", _OVERRIDE_RESULT
        ) == [
            # the suggestion (dev-warning PKM still carries a block) fires
            # first (stable order), then the override tag.
            "declaration_suggestion_shown",
            "build_override_new_errors",
        ]

    def test_override_is_build_project_only(self) -> None:
        # The gate lives on build_project; check never emits build_override.
        assert "build_override_new_errors" not in _telemetry_counters(
            "tool", "check", _OVERRIDE_RESULT
        )
        assert "build_override_new_errors" not in _telemetry_counters(
            "tool", "transpile", _OVERRIDE_RESULT
        )

    def test_normal_build_has_no_override_counter(self) -> None:
        assert _telemetry_counters("tool", "build_project", _CLEAN_CHECK) == []

    def test_refusal_result_has_no_override_counter(self) -> None:
        # A refused build (allow_new_errors NOT passed) carries build_refused,
        # not build_override — the override tag counts only actual overrides.
        refused: dict[str, Any] = {
            "ok": False,
            "exit_code": 1,
            "diagnostics": {
                "errors": [{"code": "PROVIDES_KEY_MISMATCH"}],
                "warnings": [],
                "build_refused": {"reason": "NEW_CHECK_ERRORS"},
            },
        }
        assert "build_override_new_errors" not in _telemetry_counters(
            "tool", "build_project", refused
        )

    def test_override_helper_reads_the_diagnostics_block(self) -> None:
        assert _telemetry_result_has_new_error_override(_OVERRIDE_RESULT) is True
        assert _telemetry_result_has_new_error_override(_CLEAN_CHECK) is False
        assert _telemetry_result_has_new_error_override(None) is False
        assert _telemetry_result_has_new_error_override("not a dict") is False
        assert _telemetry_result_has_new_error_override({"diagnostics": None}) is False
        # an empty block is falsy — no override actually recorded
        assert _telemetry_result_has_new_error_override(
            {"diagnostics": {"build_override": {}}}
        ) is False


class TestCounterCombinationsAndNegatives:
    def test_rules_and_drift_both_fire(self) -> None:
        combined = {**_DRIFT_ERROR, "rules": ["r"]}
        assert _telemetry_counters("tool", "build_project", combined) == [
            "inline_rule_impression",
            "refused_overwrite",
        ]

    def test_non_dict_result_yields_no_result_counters(self) -> None:
        assert _telemetry_counters("tool", "check", None) == []
        assert _telemetry_counters("tool", "build_project", "oops") == []

    def test_ordinary_call_has_no_counters(self) -> None:
        assert _telemetry_counters("tool", "project_status", {"ok": True}) == []
        assert _telemetry_counters("prompt", "author_module", "text") == []


class TestSchemaMarker:
    """The self-describing schema tag every JSONL record carries (M3).

    0.11.0's records carried the derived ``counters`` list but no
    version/schema marker, forcing a consumer to shape-sniff. M3 stamps
    one ``telemetry_schema`` marker on every record so consumers key on
    the tag; ``counters``-presence stays the documented 0.11.0 fallback
    for pre-marker records. This pins the exact contract value — the
    per-record wiring (marker on every record, incl. zero-counter events)
    is proven over real stdio in test_telemetry_invisibility.py.
    """

    def test_marker_is_the_v2_tag(self) -> None:
        # @2 is the first MARKED shape; 0.11.0's unmarked, counters-bearing
        # shape is the implicit @1.
        assert _TELEMETRY_SCHEMA == "s0ma-telemetry@2"

    def test_marker_is_a_well_formed_family_at_version_tag(self) -> None:
        family, separator, version = _TELEMETRY_SCHEMA.partition("@")
        assert family == "s0ma-telemetry"
        assert separator == "@"
        assert version.isdigit() and int(version) >= 2
