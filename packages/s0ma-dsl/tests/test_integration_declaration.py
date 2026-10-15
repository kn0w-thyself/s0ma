"""Tests for POST-5 (0.16.0): the first-class ``integration`` declaration kind.

The ``integration`` declaration promotes the D-15 IntegrationManifest
pattern to a first-class declaration. The parser accepts the new
``integration <Name> :: INFRASTRUCTURE`` header with required
``version`` / ``intent`` / ``factory`` / ``smoke_test_primary`` /
``manifest:`` fields. The validator enforces:

- ``layer == INFRASTRUCTURE`` (``LAYER_MISMATCH`` otherwise),
- the ``factory:`` field names a same-module SERVICE nerve
  (``INTEGRATION_FACTORY_NOT_FOUND`` / ``INTEGRATION_FACTORY_NOT_SERVICE``),
- the ``smoke_test_primary:`` field names a same-module nerve or a
  reachable ``uses:`` entry
  (``INTEGRATION_SMOKE_TEST_NOT_FOUND``),
- the ``manifest:`` keys are Python identifiers and values are
  JSON-serialisable primitives
  (``INTEGRATION_INVALID_MANIFEST_KEY``).

The Python emitter auto-emits four module-scoped helper functions for
every integration: ``get_factory``, ``get_manifest``,
``smoke_test_primary``, and ``get_smoke_test``. Each is registered via
``register_integration_helper`` with ``module_scoped=True`` so two
integrations in different modules can share helper names without
collision.

The IR records each integration under ``IRDocument.integrations`` —
a section parallel to ``helpers``. ``s0ma inspect`` renders an
``Integrations`` section.

Critical invariant: the existing IntegrationManifest pattern (Phase 1
Google Calendar / Slack / etc.) continues to work unchanged — the new
``integration`` declaration is opt-in convenience, not a forced
migration.
"""

from __future__ import annotations

import io
import json
from contextlib import redirect_stdout

import pytest

from s0ma_dsl.ast_nodes.nodes import IntegrationDecl
from s0ma_dsl.cli.main import S0maCLI
from s0ma_dsl.codegen.python_emitter import PythonEmitter
from s0ma_dsl.config import StrictnessMode
from s0ma_dsl.errors import S0maParseError
from s0ma_dsl.ir.builder import build_ir
from s0ma_dsl.parser.s0ma_parser import parse_s0ma
from s0ma_dsl.resolver.dependency import resolve_dependencies
from s0ma_dsl.semantic.validator import IntraModuleValidator

# ---------------------------------------------------------------------------
# Test helpers
# ---------------------------------------------------------------------------


def _gcal_module(
    *,
    integration_layer: str = "INFRASTRUCTURE",
    factory_name: str = "GoogleCalendarClient",
    factory_kind: str = "SERVICE",
    smoke_target: str = "smoke_calendar_read",
    extra_integration_fields: str = "",
    extra_top_fields: str = "",
    manifest_block: str = (
        "    manifest:\n"
        "      provides: [list_events, get_event]\n"
        "      required_env: [GOOGLE_CALENDAR_CREDENTIALS]\n"
        "      requires_oauth: true\n"
    ),
    include_smoke_nerve: bool = True,
    include_factory_nerve: bool = True,
    exports: str = "[GoogleCalendarIntegration, GoogleCalendarClient, smoke_calendar_read]",
) -> str:
    """Construct a minimal valid integration-declaration .s0ma module.

    Each kwarg lets a per-test override target one invariant without
    rebuilding the entire module. The default produces a passing
    module: an INFRASTRUCTURE-layered integration declaring a
    same-module SERVICE factory and FUNCTION smoke-test nerve.
    """
    factory_block = (
        f"nerve {factory_name} :: INFRASTRUCTURE\n"
        f"    kind: {factory_kind}\n"
        f"    visibility: PUBLIC\n"
        f"    intent: \"Factory nerve.\"\n"
        f"    expects: \"\"\n"
        f"    guarantees: \"Returns a callable bundle.\"\n"
        f"    forbids: none\n"
        f"    evaluates_at: FUNCTION_BOUNDARY\n"
        f"    returns: none\n"
        f"    raises: none\n"
        f"    interface: none\n"
        f"    latency_ms: none\n"
        f"    depends_on: none\n"
        f"    internal: none\n"
        f"    expected_exceptions: none\n"
        f"    consumes_via_dict: none\n"
        f"    declares_attributes: none\n"
        f"    covered_by: none\n"
        f"    provides: [list_events, get_event]\n"
        f"    ---\n"
        f"    def {factory_name}():\n"
        f"        def list_events(): return []\n"
        f"        def get_event(): return None\n"
        f"        return {{\"list_events\": list_events, \"get_event\": get_event}}\n"
    )
    smoke_block = (
        f"nerve {smoke_target} :: INFRASTRUCTURE\n"
        f"    kind: FUNCTION\n"
        f"    visibility: PUBLIC\n"
        f"    intent: \"Smoke-test nerve.\"\n"
        f"    expects: \"\"\n"
        f"    guarantees: \"Returns status dict.\"\n"
        f"    forbids: none\n"
        f"    evaluates_at: FUNCTION_BOUNDARY\n"
        f"    provides: none\n"
        f"    returns: none\n"
        f"    raises: none\n"
        f"    interface: none\n"
        f"    latency_ms: none\n"
        f"    depends_on: none\n"
        f"    internal: none\n"
        f"    expected_exceptions: none\n"
        f"    consumes_via_dict: none\n"
        f"    declares_attributes: none\n"
        f"    covered_by: none\n"
        f"    ---\n"
        f"    def {smoke_target}():\n"
        f"        return {{\"status\": \"ok\"}}\n"
    )
    bodies = ""
    if include_factory_nerve:
        bodies += factory_block + "\n"
    if include_smoke_nerve:
        bodies += smoke_block + "\n"
    return (
        "module gcal_integration\n"
        "    layer: INFRASTRUCTURE\n"
        "    version: 0.1.0\n"
        "    intent: \"Demo integration module.\"\n"
        f"    exports: {exports}\n"
        f"    requires: none\n"
        f"    uses: none\n"
        f"    soft_requires: none\n"
        f"    runtime_only_requires: none\n"
        f"    deferred_requires: none\n"
        f"    exports_helpers: none\n"
        f"{extra_top_fields}"
        "    ---\n"
        "\n"
        f"{bodies}"
        f"integration GoogleCalendarIntegration :: {integration_layer}\n"
        "    version: 0.1.0\n"
        "    intent: \"Read-only Google Calendar adapter for the daily scheduler.\"\n"
        f"    factory: {factory_name}\n"
        f"    smoke_test_primary: {smoke_target}\n"
        f"{manifest_block}"
        "    requires: none\n"
        "    uses: none\n"
        "    raises: none\n"
        f"{extra_integration_fields}"
    )


def _validate(source: str, filename: str = "gcal_integration.s0ma"):
    """Parse + validate a source. Returns (module, errors)."""
    mod = parse_s0ma(source, filename=filename)
    v = IntraModuleValidator(mode=StrictnessMode.DEV, filename=filename)
    return mod, v.validate(mod)


def _integration_error_codes(errors) -> list[str]:
    """Return error codes whose name begins with INTEGRATION_ or LAYER_MISMATCH."""
    return [
        e.code
        for e in errors
        if e.code.startswith("INTEGRATION_") or e.code == "LAYER_MISMATCH"
    ]


# ---------------------------------------------------------------------------
# Parser — basic shape
# ---------------------------------------------------------------------------


class TestIntegrationParsing:
    """The ``integration`` header + required fields parse to an IntegrationDecl."""

    def test_parses_with_required_fields(self) -> None:
        src = _gcal_module()
        mod = parse_s0ma(src, filename="gcal_integration.s0ma")
        assert len(mod.integrations) == 1
        integ = mod.integrations[0]
        assert isinstance(integ, IntegrationDecl)
        assert integ.name == "GoogleCalendarIntegration"
        assert integ.version == "0.1.0"
        assert (
            integ.intent
            == "Read-only Google Calendar adapter for the daily scheduler."
        )
        assert integ.factory == "GoogleCalendarClient"
        assert integ.smoke_test_primary == "smoke_calendar_read"

    def test_manifest_block_parses_into_dict(self) -> None:
        src = _gcal_module()
        mod = parse_s0ma(src, filename="gcal_integration.s0ma")
        manifest = mod.integrations[0].manifest
        assert manifest == {
            "provides": ["list_events", "get_event"],
            "required_env": ["GOOGLE_CALENDAR_CREDENTIALS"],
            "requires_oauth": True,
        }

    def test_inline_empty_manifest_parses_to_empty_dict(self) -> None:
        """``manifest: {}`` parses to an empty Python dict."""
        src = _gcal_module(manifest_block="    manifest: {}\n")
        mod = parse_s0ma(src, filename="gcal_integration.s0ma")
        assert mod.integrations[0].manifest == {}

    def test_inline_compact_manifest_parses(self) -> None:
        """``manifest: { key: value }`` inline form parses."""
        src = _gcal_module(
            manifest_block="    manifest: { requires_oauth: true }\n",
        )
        mod = parse_s0ma(src, filename="gcal_integration.s0ma")
        assert mod.integrations[0].manifest == {"requires_oauth": True}

    def test_integration_is_in_all_declarations(self) -> None:
        """The integration appears in ``module.all_declarations`` for source-order iteration."""
        src = _gcal_module()
        mod = parse_s0ma(src, filename="gcal_integration.s0ma")
        names = [getattr(d, "name", None) for d in mod.all_declarations]
        assert "GoogleCalendarIntegration" in names


# ---------------------------------------------------------------------------
# Parser — required-field errors
# ---------------------------------------------------------------------------


class TestIntegrationRequiredFields:
    """Every required field raises MISSING_FIELD when omitted."""

    def test_missing_intent_raises_missing_field(self) -> None:
        src = _gcal_module().replace(
            '    intent: "Read-only Google Calendar adapter for the daily scheduler."\n',
            "",
            1,  # only remove the first match (module intent stays)
        )
        # The replacement removed the module intent (also matches "intent:"); restore it.
        # Easier: build manually with missing integration intent.
        src = (
            "module gcal_integration\n"
            "    layer: INFRASTRUCTURE\n"
            "    version: 0.1.0\n"
            '    intent: "Demo."\n'
            "    exports: [GoogleCalendarIntegration]\n"
            "    requires: none\n"
            "    uses: none\n"
            "    soft_requires: none\n"
            "    runtime_only_requires: none\n"
            "    deferred_requires: none\n"
            "    exports_helpers: none\n"
            "    ---\n"
            "\n"
            "integration GoogleCalendarIntegration :: INFRASTRUCTURE\n"
            "    version: 0.1.0\n"
            "    factory: F\n"
            "    smoke_test_primary: S\n"
            "    manifest: {}\n"
            "    requires: none\n"
            "    uses: none\n"
            "    raises: none\n"
        )
        with pytest.raises(S0maParseError) as excinfo:
            parse_s0ma(src, filename="missing_intent.s0ma")
        assert excinfo.value.code == "SEMANTIC_REQUIRED_STATE_OMITTED"
        assert "intent" in excinfo.value.message

    def test_missing_version_raises_missing_field(self) -> None:
        src = (
            "module gcal_integration\n"
            "    layer: INFRASTRUCTURE\n"
            "    version: 0.1.0\n"
            '    intent: "Demo."\n'
            "    exports: [GoogleCalendarIntegration]\n"
            "    requires: none\n"
            "    uses: none\n"
            "    soft_requires: none\n"
            "    runtime_only_requires: none\n"
            "    deferred_requires: none\n"
            "    exports_helpers: none\n"
            "    ---\n"
            "\n"
            "integration GoogleCalendarIntegration :: INFRASTRUCTURE\n"
            '    intent: "Adapter."\n'
            "    factory: F\n"
            "    smoke_test_primary: S\n"
            "    manifest: {}\n"
            "    requires: none\n"
            "    uses: none\n"
            "    raises: none\n"
        )
        with pytest.raises(S0maParseError) as excinfo:
            parse_s0ma(src, filename="missing_version.s0ma")
        assert excinfo.value.code == "SEMANTIC_REQUIRED_STATE_OMITTED"
        assert "version" in excinfo.value.message

    def test_missing_factory_raises_missing_field(self) -> None:
        src = (
            "module gcal_integration\n"
            "    layer: INFRASTRUCTURE\n"
            "    version: 0.1.0\n"
            '    intent: "Demo."\n'
            "    exports: [GoogleCalendarIntegration]\n"
            "    requires: none\n"
            "    uses: none\n"
            "    soft_requires: none\n"
            "    runtime_only_requires: none\n"
            "    deferred_requires: none\n"
            "    exports_helpers: none\n"
            "    ---\n"
            "\n"
            "integration GoogleCalendarIntegration :: INFRASTRUCTURE\n"
            "    version: 0.1.0\n"
            '    intent: "Adapter."\n'
            "    smoke_test_primary: S\n"
            "    manifest: {}\n"
            "    requires: none\n"
            "    uses: none\n"
            "    raises: none\n"
        )
        with pytest.raises(S0maParseError) as excinfo:
            parse_s0ma(src, filename="missing_factory.s0ma")
        assert excinfo.value.code == "SEMANTIC_REQUIRED_STATE_OMITTED"
        assert "factory" in excinfo.value.message

    def test_missing_smoke_test_primary_raises_missing_field(self) -> None:
        src = (
            "module gcal_integration\n"
            "    layer: INFRASTRUCTURE\n"
            "    version: 0.1.0\n"
            '    intent: "Demo."\n'
            "    exports: [GoogleCalendarIntegration]\n"
            "    requires: none\n"
            "    uses: none\n"
            "    soft_requires: none\n"
            "    runtime_only_requires: none\n"
            "    deferred_requires: none\n"
            "    exports_helpers: none\n"
            "    ---\n"
            "\n"
            "integration GoogleCalendarIntegration :: INFRASTRUCTURE\n"
            "    version: 0.1.0\n"
            '    intent: "Adapter."\n'
            "    factory: F\n"
            "    manifest: {}\n"
            "    requires: none\n"
            "    uses: none\n"
            "    raises: none\n"
        )
        with pytest.raises(S0maParseError) as excinfo:
            parse_s0ma(src, filename="missing_smoke.s0ma")
        assert excinfo.value.code == "SEMANTIC_REQUIRED_STATE_OMITTED"
        assert "smoke_test_primary" in excinfo.value.message

    def test_missing_manifest_raises_missing_field(self) -> None:
        src = (
            "module gcal_integration\n"
            "    layer: INFRASTRUCTURE\n"
            "    version: 0.1.0\n"
            '    intent: "Demo."\n'
            "    exports: [GoogleCalendarIntegration]\n"
            "    requires: none\n"
            "    uses: none\n"
            "    soft_requires: none\n"
            "    runtime_only_requires: none\n"
            "    deferred_requires: none\n"
            "    exports_helpers: none\n"
            "    ---\n"
            "\n"
            "integration GoogleCalendarIntegration :: INFRASTRUCTURE\n"
            "    version: 0.1.0\n"
            '    intent: "Adapter."\n'
            "    factory: F\n"
            "    smoke_test_primary: S\n"
        )
        with pytest.raises(S0maParseError) as excinfo:
            parse_s0ma(src, filename="missing_manifest.s0ma")
        assert excinfo.value.code == "SEMANTIC_REQUIRED_STATE_OMITTED"
        assert "manifest" in excinfo.value.message


# ---------------------------------------------------------------------------
# Validator — layer / factory / smoke / manifest cross-checks
# ---------------------------------------------------------------------------


class TestIntegrationLayerMismatch:
    """integration declarations MUST be INFRASTRUCTURE-layered."""

    @pytest.mark.parametrize(
        "layer", ["APPLICATION", "DOMAIN", "FRAMEWORK"],
    )
    def test_non_infrastructure_layer_raises_layer_mismatch(self, layer: str) -> None:
        # Construct a module whose layer matches the integration's layer
        # (avoids the unrelated module-vs-component layer-mismatch check
        # firing before the integration-specific one). The integration
        # itself, however, is still LAYER-mismatched against the
        # invariant that integrations are INFRASTRUCTURE-only.
        src = (
            f"module gcal_integration\n"
            f"    layer: {layer}\n"
            f"    version: 0.1.0\n"
            f'    intent: "Demo."\n'
            f"    exports: [GoogleCalendarIntegration]\n"
            f"    requires: none\n"
            f"    uses: none\n"
            f"    soft_requires: none\n"
            f"    runtime_only_requires: none\n"
            f"    deferred_requires: none\n"
            f"    exports_helpers: none\n"
            f"    ---\n"
            f"\n"
            f"integration GoogleCalendarIntegration :: {layer}\n"
            f"    version: 0.1.0\n"
            f'    intent: "Adapter."\n'
            f"    factory: NotChecked\n"
            f"    smoke_test_primary: NotChecked\n"
            f"    manifest: {{}}\n"
            f"    requires: none\n"
            f"    uses: none\n"
            f"    raises: none\n"
        )
        mod, errors = _validate(src, filename="bad_layer.s0ma")
        codes = [e.code for e in errors]
        assert "LAYER_MISMATCH" in codes


class TestIntegrationFactoryCrossCheck:
    """The factory: field must name a same-module SERVICE nerve."""

    def test_factory_missing_raises_integration_factory_not_found(self) -> None:
        src = _gcal_module(
            extra_integration_fields="",
        ).replace("factory: GoogleCalendarClient", "factory: DoesNotExist")
        mod, errors = _validate(src)
        codes = _integration_error_codes(errors)
        assert "INTEGRATION_FACTORY_NOT_FOUND" in codes

    def test_factory_non_service_raises_factory_not_service(self) -> None:
        src = _gcal_module(factory_kind="FUNCTION")
        mod, errors = _validate(src)
        codes = _integration_error_codes(errors)
        assert "INTEGRATION_FACTORY_NOT_SERVICE" in codes


class TestIntegrationSmokeTestCrossCheck:
    """smoke_test_primary: must name a nerve or a uses: entry."""

    def test_unknown_smoke_test_raises_not_found(self) -> None:
        src = _gcal_module().replace(
            "smoke_test_primary: smoke_calendar_read",
            "smoke_test_primary: DoesNotExistAnywhere",
        )
        mod, errors = _validate(src)
        codes = _integration_error_codes(errors)
        assert "INTEGRATION_SMOKE_TEST_NOT_FOUND" in codes

    def test_uses_entry_qualifies_as_smoke_test(self) -> None:
        """A ``uses:`` import counts as a reachable smoke-test target."""
        # Drop the local smoke nerve and put the target on the
        # module's ``uses:`` list. Even though the resolver hasn't
        # validated the cross-module import, the intra-module
        # validator should accept it as in-scope.
        src = (
            "module gcal_integration\n"
            "    layer: INFRASTRUCTURE\n"
            "    version: 0.1.0\n"
            '    intent: "Demo."\n'
            "    uses: [other_mod.smoke_target]\n"
            "    exports: [GoogleCalendarIntegration, GoogleCalendarClient]\n"
            "    requires: none\n"
            "    soft_requires: none\n"
            "    runtime_only_requires: none\n"
            "    deferred_requires: none\n"
            "    exports_helpers: none\n"
            "    ---\n"
            "\n"
            "nerve GoogleCalendarClient :: INFRASTRUCTURE\n"
            "    kind: SERVICE\n"
            "    visibility: PUBLIC\n"
            '    intent: "Factory."\n'
            '    expects: ""\n'
            '    guarantees: "Returns bundle."\n'
            '    forbids: none\n'
            "    evaluates_at: FUNCTION_BOUNDARY\n"
            "    returns: none\n"
            "    raises: none\n"
            "    interface: none\n"
            "    latency_ms: none\n"
            "    depends_on: none\n"
            "    internal: none\n"
            "    expected_exceptions: none\n"
            "    consumes_via_dict: none\n"
            "    declares_attributes: none\n"
            "    covered_by: none\n"
            "    provides: [list_events]\n"
            "    ---\n"
            "    def GoogleCalendarClient():\n"
            "        def list_events(): return []\n"
            "        return {\"list_events\": list_events}\n"
            "\n"
            "integration GoogleCalendarIntegration :: INFRASTRUCTURE\n"
            "    version: 0.1.0\n"
            '    intent: "Adapter."\n'
            "    factory: GoogleCalendarClient\n"
            "    smoke_test_primary: smoke_target\n"
            "    manifest: {}\n"
            "    requires: none\n"
            "    uses: none\n"
            "    raises: none\n"
        )
        mod, errors = _validate(src)
        codes = _integration_error_codes(errors)
        assert "INTEGRATION_SMOKE_TEST_NOT_FOUND" not in codes


class TestIntegrationManifestShape:
    """Manifest keys must be Python identifiers; values JSON-serialisable."""

    def test_basic_manifest_shape_passes(self) -> None:
        src = _gcal_module()
        mod, errors = _validate(src)
        codes = _integration_error_codes(errors)
        assert "INTEGRATION_INVALID_MANIFEST_KEY" not in codes

    def test_arbitrary_keys_accepted(self) -> None:
        """The check is permissive — any identifier key + primitive value passes."""
        src = _gcal_module(
            manifest_block=(
                "    manifest:\n"
                "      custom_metric: 42\n"
                "      threshold: 0.95\n"
                "      enabled: false\n"
            ),
        )
        mod, errors = _validate(src)
        codes = _integration_error_codes(errors)
        assert "INTEGRATION_INVALID_MANIFEST_KEY" not in codes


class TestIntegrationVersionFormat:
    """The version field follows semver (re-uses INVALID_VERSION)."""

    def test_invalid_semver_raises_invalid_version(self) -> None:
        src = _gcal_module().replace(
            "integration GoogleCalendarIntegration :: INFRASTRUCTURE\n"
            "    version: 0.1.0",
            "integration GoogleCalendarIntegration :: INFRASTRUCTURE\n"
            "    version: not-semver",
            1,
        )
        mod, errors = _validate(src)
        codes = [e.code for e in errors]
        assert "INVALID_VERSION" in codes


# ---------------------------------------------------------------------------
# Validator — passing path
# ---------------------------------------------------------------------------


class TestIntegrationValidatesCleanly:
    """A well-formed integration produces no integration-specific errors."""

    def test_no_integration_errors_for_valid_integration(self) -> None:
        src = _gcal_module()
        mod, errors = _validate(src)
        codes = _integration_error_codes(errors)
        assert codes == []


# ---------------------------------------------------------------------------
# IR — round-trip
# ---------------------------------------------------------------------------


class TestIntegrationIRRoundTrip:
    """The integration rides through the IR builder and to_dict() unchanged."""

    def test_integration_appears_in_ir(self) -> None:
        src = _gcal_module()
        mod = parse_s0ma(src, filename="gcal_integration.s0ma")
        doc = build_ir(mod, source_text=src)
        ir_dict = doc.to_dict()
        assert "integrations" in ir_dict
        assert len(ir_dict["integrations"]) == 1
        ir_integ = ir_dict["integrations"][0]
        assert ir_integ["name"] == "GoogleCalendarIntegration"
        assert (
            ir_integ["canonical_id"]
            == "gcal_integration::GoogleCalendarIntegration"
        )
        assert ir_integ["layer"] == "INFRASTRUCTURE"
        assert ir_integ["factory"] == {
            "state": "value",
            "value": "GoogleCalendarClient",
        }
        assert ir_integ["smoke_test_primary"] == {
            "state": "value",
            "value": "smoke_calendar_read",
        }
        assert ir_integ["manifest"]["state"] == "value"
        manifest = ir_integ["manifest"]["value"]
        assert manifest["requires_oauth"] is True
        assert manifest["provides"] == ["list_events", "get_event"]

    def test_integration_not_in_components(self) -> None:
        """The integration itself is not a component (only its 4 helpers are at runtime)."""
        src = _gcal_module()
        mod = parse_s0ma(src, filename="gcal_integration.s0ma")
        doc = build_ir(mod, source_text=src)
        ir_dict = doc.to_dict()
        comp_ids = [c["canonical_id"] for c in ir_dict["components"]]
        assert "gcal_integration::GoogleCalendarIntegration" not in comp_ids

    def test_schema_version_bumped(self) -> None:
        src = _gcal_module()
        mod = parse_s0ma(src, filename="gcal_integration.s0ma")
        doc = build_ir(mod, source_text=src)
        # DSL-M1 (0.8.0) bumped 2.0.0 -> 2.1.0: additive
        # metadata/serves_as fields (ADR-011 §(g); see ir/schema.py).
        assert doc.schema_version == "3.0.0"

    def test_ir_json_serialisable(self) -> None:
        """The IR dict round-trips through json.dumps / json.loads."""
        src = _gcal_module()
        mod = parse_s0ma(src, filename="gcal_integration.s0ma")
        doc = build_ir(mod, source_text=src)
        rehydrated = json.loads(json.dumps(doc.to_dict()))
        assert (
            rehydrated["integrations"][0]["name"]
            == "GoogleCalendarIntegration"
        )


# ---------------------------------------------------------------------------
# Python emitter — four auto-emitted helpers
# ---------------------------------------------------------------------------


class TestIntegrationCodegen:
    """The emitter produces four module-scoped helper functions."""

    def _emit(self, src: str) -> str:
        mod = parse_s0ma(src, filename="gcal_integration.s0ma")
        emitter = PythonEmitter(module_name="gcal_integration")
        return emitter.emit(mod)

    def test_get_factory_emitted(self) -> None:
        py = self._emit(_gcal_module())
        assert "def get_factory():" in py
        assert "return GoogleCalendarClient()" in py

    def test_get_manifest_emitted(self) -> None:
        py = self._emit(_gcal_module())
        assert "def get_manifest():" in py
        # The manifest dict literal contains every key.
        assert '"provides": ["list_events", "get_event"]' in py
        assert '"required_env": ["GOOGLE_CALENDAR_CREDENTIALS"]' in py
        assert '"requires_oauth": True' in py

    def test_smoke_test_primary_emitted(self) -> None:
        py = self._emit(_gcal_module())
        assert "def smoke_test_primary(*args, **kwargs):" in py
        assert "return smoke_calendar_read(*args, **kwargs)" in py

    def test_get_smoke_test_emitted(self) -> None:
        py = self._emit(_gcal_module())
        assert "def get_smoke_test():" in py
        assert "return smoke_test_primary" in py

    def test_register_integration_helper_called_for_each(self) -> None:
        py = self._emit(_gcal_module())
        assert py.count("register_integration_helper(") == 4
        # Each helper passes its own name + the module path.
        assert 'name="get_factory"' in py
        assert 'name="get_manifest"' in py
        assert 'name="smoke_test_primary"' in py
        assert 'name="get_smoke_test"' in py
        assert 'module_path="gcal_integration"' in py

    def test_emitted_python_compiles(self) -> None:
        """The emitted module compiles and runs end-to-end."""
        from s0ma.registry import (
            ComponentRegistry,
            reset_registry,
            set_registry,
        )

        # Each exec() registers components in the global registry — use a
        # fresh registry per test so a second exec() in the same session
        # doesn't fail with ``RegistrationError`` (the nerve names are
        # bare and registered without ``module_scoped=True``, so
        # re-execution collides).
        registry = ComponentRegistry(persist=False)
        set_registry(registry)
        try:
            py = self._emit(_gcal_module())
            # Replace hash placeholders so the module is valid Python.
            py = py.replace("__S0MA_SOURCE_HASH__", "x").replace(
                "__S0MA_OUTPUT_HASH__", "y"
            )
            ns: dict = {"__name__": "gcal_integration"}
            exec(compile(py, "<emitted>", "exec"), ns)  # noqa: S102
            assert ns["get_manifest"]() == {
                "provides": ["list_events", "get_event"],
                "required_env": ["GOOGLE_CALENDAR_CREDENTIALS"],
                "requires_oauth": True,
            }
            factory_bundle = ns["get_factory"]()
            assert "list_events" in factory_bundle
            assert "get_event" in factory_bundle
            smoke = ns["smoke_test_primary"]()
            assert smoke == {"status": "ok"}
            assert ns["get_smoke_test"]() is ns["smoke_test_primary"]
        finally:
            reset_registry()

    def test_module_scoped_registration_uses_qualified_key(self) -> None:
        """The four helpers register under module-qualified keys (POST-5 / PRE-10)."""
        from s0ma.registry import (
            ComponentRegistry,
            reset_registry,
            set_registry,
        )

        registry = ComponentRegistry(persist=False)
        set_registry(registry)
        try:
            py = self._emit(_gcal_module())
            py = py.replace("__S0MA_SOURCE_HASH__", "x").replace(
                "__S0MA_OUTPUT_HASH__", "y"
            )
            ns: dict = {"__name__": "gcal_integration"}
            exec(compile(py, "<emitted>", "exec"), ns)  # noqa: S102

            # The runtime-bridge `register_integration_helper` builds
            # the ComponentSpec with ``module_scoped=True``. Assert
            # the spec attached to each helper carries the flag.
            for name in (
                "get_factory",
                "get_manifest",
                "smoke_test_primary",
                "get_smoke_test",
            ):
                spec = ns[name].__component__
                assert spec.module_scoped is True, (
                    f"{name} should be module_scoped=True"
                )
                assert spec.module_path == "gcal_integration"
        finally:
            reset_registry()

    def test_integration_marker_symbol_emitted(self) -> None:
        """The integration's name is exposed as a module attribute."""
        from s0ma.registry import (
            ComponentRegistry,
            reset_registry,
            set_registry,
        )

        registry = ComponentRegistry(persist=False)
        set_registry(registry)
        try:
            py = self._emit(_gcal_module())
            py = py.replace("__S0MA_SOURCE_HASH__", "x").replace(
                "__S0MA_OUTPUT_HASH__", "y"
            )
            ns: dict = {"__name__": "gcal_integration"}
            exec(compile(py, "<emitted>", "exec"), ns)  # noqa: S102
            # The marker bundles the four helpers + metadata.
            marker = ns["GoogleCalendarIntegration"]
            assert marker["name"] == "GoogleCalendarIntegration"
            assert marker["version"] == "0.1.0"
            assert marker["get_factory"] is ns["get_factory"]
            assert marker["get_manifest"] is ns["get_manifest"]
            assert (
                marker["smoke_test_primary"] is ns["smoke_test_primary"]
            )
            assert marker["get_smoke_test"] is ns["get_smoke_test"]
        finally:
            reset_registry()


# ---------------------------------------------------------------------------
# Cross-module sibling coexistence
# ---------------------------------------------------------------------------


class TestSiblingIntegrationsCoexist:
    """Two integrations in different modules share helper names cleanly."""

    def _emit_two_modules(self) -> dict[str, dict]:
        """Compile + execute two sibling integration modules and return their namespaces."""
        mod_a_src = (
            "module gcal_integration\n"
            "    layer: INFRASTRUCTURE\n"
            "    version: 0.1.0\n"
            '    intent: "Module A."\n'
            "    exports: [GoogleCalendarIntegration, GoogleCalendarClient, smoke_a]\n"
            "    requires: none\n"
            "    uses: none\n"
            "    soft_requires: none\n"
            "    runtime_only_requires: none\n"
            "    deferred_requires: none\n"
            "    exports_helpers: none\n"
            "    ---\n"
            "\n"
            "nerve GoogleCalendarClient :: INFRASTRUCTURE\n"
            "    kind: SERVICE\n"
            "    visibility: PUBLIC\n"
            '    intent: "Factory for module A integration."\n'
            '    expects: ""\n'
            '    guarantees: "Returns bundle."\n'
            '    forbids: none\n'
            "    evaluates_at: FUNCTION_BOUNDARY\n"
            "    returns: none\n"
            "    raises: none\n"
            "    interface: none\n"
            "    latency_ms: none\n"
            "    depends_on: none\n"
            "    internal: none\n"
            "    expected_exceptions: none\n"
            "    consumes_via_dict: none\n"
            "    declares_attributes: none\n"
            "    covered_by: none\n"
            "    provides: [list_events]\n"
            "    ---\n"
            "    def GoogleCalendarClient():\n"
            "        def list_events(): return 'a'\n"
            "        return {\"list_events\": list_events}\n"
            "\n"
            "nerve smoke_a :: INFRASTRUCTURE\n"
            "    kind: FUNCTION\n"
            "    visibility: PUBLIC\n"
            '    intent: "Smoke test nerve for module A."\n'
            '    expects: ""\n'
            '    guarantees: "Returns ok."\n'
            '    forbids: none\n'
            "    evaluates_at: FUNCTION_BOUNDARY\n"
            "    provides: none\n"
            "    returns: none\n"
            "    raises: none\n"
            "    interface: none\n"
            "    latency_ms: none\n"
            "    depends_on: none\n"
            "    internal: none\n"
            "    expected_exceptions: none\n"
            "    consumes_via_dict: none\n"
            "    declares_attributes: none\n"
            "    covered_by: none\n"
            "    ---\n"
            "    def smoke_a():\n"
            "        return {\"status\": \"ok-a\"}\n"
            "\n"
            "integration GoogleCalendarIntegration :: INFRASTRUCTURE\n"
            "    version: 0.1.0\n"
            '    intent: "Adapter declaration for module A."\n'
            "    factory: GoogleCalendarClient\n"
            "    smoke_test_primary: smoke_a\n"
            "    manifest: {}\n"
            "    requires: none\n"
            "    uses: none\n"
            "    raises: none\n"
        )
        mod_b_src = (
            "module slack_integration\n"
            "    layer: INFRASTRUCTURE\n"
            "    version: 0.1.0\n"
            '    intent: "Module B."\n'
            "    exports: [SlackIntegration, SlackClient, smoke_b]\n"
            "    requires: none\n"
            "    uses: none\n"
            "    soft_requires: none\n"
            "    runtime_only_requires: none\n"
            "    deferred_requires: none\n"
            "    exports_helpers: none\n"
            "    ---\n"
            "\n"
            "nerve SlackClient :: INFRASTRUCTURE\n"
            "    kind: SERVICE\n"
            "    visibility: PUBLIC\n"
            '    intent: "Factory for module B integration."\n'
            '    expects: ""\n'
            '    guarantees: "Returns bundle."\n'
            '    forbids: none\n'
            "    evaluates_at: FUNCTION_BOUNDARY\n"
            "    returns: none\n"
            "    raises: none\n"
            "    interface: none\n"
            "    latency_ms: none\n"
            "    depends_on: none\n"
            "    internal: none\n"
            "    expected_exceptions: none\n"
            "    consumes_via_dict: none\n"
            "    declares_attributes: none\n"
            "    covered_by: none\n"
            "    provides: [post_message]\n"
            "    ---\n"
            "    def SlackClient():\n"
            "        def post_message(): return 'b'\n"
            "        return {\"post_message\": post_message}\n"
            "\n"
            "nerve smoke_b :: INFRASTRUCTURE\n"
            "    kind: FUNCTION\n"
            "    visibility: PUBLIC\n"
            '    intent: "Smoke test nerve for module B."\n'
            '    expects: ""\n'
            '    guarantees: "Returns ok."\n'
            '    forbids: none\n'
            "    evaluates_at: FUNCTION_BOUNDARY\n"
            "    provides: none\n"
            "    returns: none\n"
            "    raises: none\n"
            "    interface: none\n"
            "    latency_ms: none\n"
            "    depends_on: none\n"
            "    internal: none\n"
            "    expected_exceptions: none\n"
            "    consumes_via_dict: none\n"
            "    declares_attributes: none\n"
            "    covered_by: none\n"
            "    ---\n"
            "    def smoke_b():\n"
            "        return {\"status\": \"ok-b\"}\n"
            "\n"
            "integration SlackIntegration :: INFRASTRUCTURE\n"
            "    version: 0.1.0\n"
            '    intent: "Adapter declaration for module B."\n'
            "    factory: SlackClient\n"
            "    smoke_test_primary: smoke_b\n"
            "    manifest: {}\n"
            "    requires: none\n"
            "    uses: none\n"
            "    raises: none\n"
        )
        a_mod = parse_s0ma(mod_a_src, filename="gcal_integration.s0ma")
        b_mod = parse_s0ma(mod_b_src, filename="slack_integration.s0ma")
        a_py = PythonEmitter(module_name="gcal_integration").emit(a_mod)
        b_py = PythonEmitter(module_name="slack_integration").emit(b_mod)
        ns_a: dict = {"__name__": "gcal_integration"}
        ns_b: dict = {"__name__": "slack_integration"}
        for src_str, ns in ((a_py, ns_a), (b_py, ns_b)):
            src_str = src_str.replace(
                "__S0MA_SOURCE_HASH__", "x"
            ).replace("__S0MA_OUTPUT_HASH__", "y")
            exec(compile(src_str, "<emitted>", "exec"), ns)  # noqa: S102
        return {"a": ns_a, "b": ns_b}

    def test_both_modules_load_without_collision(self) -> None:
        """Both modules expose helpers with the same bare names without RegistrationError."""
        from s0ma.registry import (
            ComponentRegistry,
            get_registry,
            reset_registry,
            set_registry,
        )

        registry = ComponentRegistry(persist=False)
        set_registry(registry)
        try:
            nss = self._emit_two_modules()
            reg = get_registry(persist=False)
            all_keys = set(reg.get_all().keys())
            # Both module-qualified entries coexist.
            assert "gcal_integration::get_factory" in all_keys
            assert "slack_integration::get_factory" in all_keys
            # Each spec carries its own module_path.
            assert (
                nss["a"]["get_factory"].__component__.module_path
                == "gcal_integration"
            )
            assert (
                nss["b"]["get_factory"].__component__.module_path
                == "slack_integration"
            )
            # And module_scoped is True on both.
            assert (
                nss["a"]["get_factory"].__component__.module_scoped is True
            )
            assert (
                nss["b"]["get_factory"].__component__.module_scoped is True
            )
        finally:
            reset_registry()


# ---------------------------------------------------------------------------
# Resolver — uses: resolves to integration
# ---------------------------------------------------------------------------


class TestIntegrationUsesResolution:
    """A ``uses:`` entry naming an integration resolves cleanly (no NOT_EXPORTED)."""

    def test_uses_integration_resolves(self) -> None:
        provider_src = _gcal_module()
        consumer_src = (
            "module consumer\n"
            "    layer: INFRASTRUCTURE\n"
            "    version: 0.1.0\n"
            '    intent: "Consumer module."\n'
            "    uses: [gcal_integration.GoogleCalendarIntegration]\n"
            "    exports: [run]\n"
            "    requires: none\n"
            "    soft_requires: none\n"
            "    runtime_only_requires: none\n"
            "    deferred_requires: none\n"
            "    exports_helpers: none\n"
            "    ---\n"
            "\n"
            "nerve run :: INFRASTRUCTURE\n"
            "    kind: FUNCTION\n"
            "    visibility: PUBLIC\n"
            '    intent: "Driver."\n'
            '    expects: ""\n'
            '    guarantees: "Calls integration."\n'
            '    forbids: none\n'
            "    evaluates_at: FUNCTION_BOUNDARY\n"
            "    provides: none\n"
            "    returns: none\n"
            "    raises: none\n"
            "    interface: none\n"
            "    latency_ms: none\n"
            "    depends_on: none\n"
            "    internal: none\n"
            "    expected_exceptions: none\n"
            "    consumes_via_dict: none\n"
            "    declares_attributes: none\n"
            "    covered_by: none\n"
            "    ---\n"
            "    def run():\n"
            "        return GoogleCalendarIntegration\n"
        )
        provider = parse_s0ma(provider_src, filename="gcal_integration.s0ma")
        consumer = parse_s0ma(consumer_src, filename="consumer.s0ma")
        errors = resolve_dependencies(
            {"gcal_integration": provider, "consumer": consumer},
            mode=StrictnessMode.DEV,
            check_imports=False,
        )
        # No NOT_EXPORTED / DOES_NOT_EXIST for the integration target.
        codes = [e.code for e in errors]
        assert "NOT_EXPORTED" not in codes, (
            f"Unexpected NOT_EXPORTED among {codes!r}"
        )
        assert "DOES_NOT_EXIST" not in codes, (
            f"Unexpected DOES_NOT_EXIST among {codes!r}"
        )


# ---------------------------------------------------------------------------
# s0ma inspect — Integrations section appears
# ---------------------------------------------------------------------------


class TestInspectShowsIntegrations:
    """``s0ma inspect`` text output renders an Integrations section."""

    def test_inspect_renders_integrations_section(self) -> None:
        src = _gcal_module()
        mod = parse_s0ma(src, filename="gcal_integration.s0ma")
        doc = build_ir(mod, source_text=src)
        ir_dict = json.loads(json.dumps(doc.to_dict()))

        cli = S0maCLI()
        buf = io.StringIO()
        with redirect_stdout(buf):
            cli._print_inspect_text(ir_dict)
        output = buf.getvalue()

        assert "Integrations (1):" in output
        assert "GoogleCalendarIntegration" in output
        assert "factory: GoogleCalendarClient" in output
        assert "smoke_test_primary: smoke_calendar_read" in output
        assert "manifest keys:" in output
        assert "get_factory, get_manifest" in output


# ---------------------------------------------------------------------------
# Backwards compatibility — IntegrationManifest pattern still works
# ---------------------------------------------------------------------------


class TestIntegrationManifestPatternStillWorks:
    """The pre-POST-5 IntegrationManifest pattern continues to parse and emit cleanly.

    Phase 1 integrations (Google Calendar, Slack, etc.) declare a
    Python ``IntegrationManifest`` dataclass via ``requires:`` and
    construct it from a regular ``get_manifest`` nerve. Adopting the
    new ``integration`` declaration is opt-in; the existing pattern
    MUST keep working unchanged.
    """

    LEGACY_PATTERN_SRC = (
        "module legacy_integration\n"
        "    layer: INFRASTRUCTURE\n"
        "    version: 0.1.0\n"
        '    intent: "Phase 1 pattern — manual IntegrationManifest construction."\n'
        "    exports: [get_manifest]\n"
        "    requires: none\n"
        "    uses: none\n"
        "    soft_requires: none\n"
        "    runtime_only_requires: none\n"
        "    deferred_requires: none\n"
        "    exports_helpers: none\n"
        "    ---\n"
        "\n"
        "nerve get_manifest :: INFRASTRUCTURE\n"
        "    kind: FUNCTION\n"
        "    visibility: PUBLIC\n"
        '    intent: "Hand-rolled manifest factory (pre-POST-5 D-15 pattern)."\n'
        '    expects: ""\n'
        '    guarantees: "Returns a manifest dict."\n'
        '    forbids: none\n'
        "    evaluates_at: FUNCTION_BOUNDARY\n"
        "    provides: none\n"
        "    returns: none\n"
        "    raises: none\n"
        "    interface: none\n"
        "    latency_ms: none\n"
        "    depends_on: none\n"
        "    internal: none\n"
        "    expected_exceptions: none\n"
        "    consumes_via_dict: none\n"
        "    declares_attributes: none\n"
        "    covered_by: none\n"
        "    ---\n"
        "    def get_manifest():\n"
        "        return {\"name\": \"legacy\", \"requires_oauth\": False}\n"
    )

    def test_legacy_pattern_parses(self) -> None:
        mod = parse_s0ma(
            self.LEGACY_PATTERN_SRC, filename="legacy_integration.s0ma",
        )
        assert len(mod.nerves) == 1
        assert mod.nerves[0].name == "get_manifest"
        # No integration declarations in this module — the legacy
        # pattern doesn't use the new kind.
        assert mod.integrations == ()

    def test_legacy_pattern_validates_cleanly(self) -> None:
        mod, errors = _validate(
            self.LEGACY_PATTERN_SRC, filename="legacy_integration.s0ma",
        )
        codes = _integration_error_codes(errors)
        # No integration-specific errors fire on the legacy pattern.
        assert codes == []

    def test_legacy_pattern_emits(self) -> None:
        mod = parse_s0ma(
            self.LEGACY_PATTERN_SRC, filename="legacy_integration.s0ma",
        )
        py = PythonEmitter(module_name="legacy_integration").emit(mod)
        # The hand-rolled get_manifest nerve still emits a regular
        # @component-decorated function — no register_integration_helper
        # call appears.
        assert "@component(" in py
        assert "def get_manifest():" in py
        assert "register_integration_helper" not in py
