"""Tests for ``module_path`` propagation through ``register_constant`` /
``register_type``.

The DSL emitter calls these helpers with the owning module name so the
registry can attribute the constant / type to its module the same way
``register_module`` and ``@component`` registrations do. Without
``module_path`` populated, downstream tooling (e.g. fr3d's
``WebViewRegistry`` walker) has to derive the path from the source-file
path with a fragile fallback.

These tests pin:
- the new ``module_path`` keyword argument is accepted,
- the value is round-tripped onto ``ComponentSpec.module_path``,
- the parameter is optional (omitted → empty string default),
- ``qualified_name`` is derived from it as ``"<module_path>.<name>"``
  (empty when ``module_path`` is), and a registry persisted with the
  empty name is repaired on the next idempotent registration.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from s0ma.registry import ComponentRegistry

if TYPE_CHECKING:
    from pathlib import Path


class TestRegisterConstantModulePath:
    """``register_constant`` carries ``module_path`` onto the spec."""

    def test_module_path_round_trip(self) -> None:
        registry = ComponentRegistry(persist=False)
        spec = registry.register_constant(
            name="SAMPLE_CONST",
            layer="APPLICATION",
            intent="A sample constant for module-path round-trip testing",
            module_path="presentation.web.shell_view",
        )
        assert spec.module_path == "presentation.web.shell_view"

        # And the registry's view of the spec round-trips the same.
        retrieved = registry.get("SAMPLE_CONST")
        assert retrieved is not None
        assert retrieved.module_path == "presentation.web.shell_view"

    def test_module_path_default_is_empty_string(self) -> None:
        """Existing call sites that don't pass ``module_path`` keep working."""
        registry = ComponentRegistry(persist=False)
        spec = registry.register_constant(
            name="LEGACY_CONST",
            layer="APPLICATION",
            intent="A legacy constant registered without module_path",
        )
        assert spec.module_path == ""

    def test_module_path_appears_in_snapshot(self) -> None:
        registry = ComponentRegistry(persist=False)
        registry.register_constant(
            name="SNAPSHOT_CONST",
            layer="DOMAIN",
            intent="A constant whose module_path must survive snapshot",
            module_path="domain.fixtures.canonical",
        )
        snap = registry.snapshot()
        assert "SNAPSHOT_CONST" in snap.components
        assert snap.components["SNAPSHOT_CONST"].module_path == "domain.fixtures.canonical"


class TestRegisterTypeModulePath:
    """``register_type`` carries ``module_path`` onto the spec."""

    def test_module_path_round_trip(self) -> None:
        registry = ComponentRegistry(persist=False)
        spec = registry.register_type(
            name="UserId",
            layer="DOMAIN",
            intent="Type alias for user identifier in domain layer",
            module_path="domain.identifiers",
        )
        assert spec.module_path == "domain.identifiers"

    def test_module_path_default_is_empty_string(self) -> None:
        registry = ComponentRegistry(persist=False)
        spec = registry.register_type(
            name="LegacyId",
            layer="DOMAIN",
            intent="Type alias registered without module_path",
        )
        assert spec.module_path == ""


# ---------------------------------------------------------------------------
# qualified_name is derived from module_path
# ---------------------------------------------------------------------------
#
# ``ComponentSpec`` documents ``qualified_name`` as auto-derived at
# registration, and ``@component`` derives it as ``"<module_path>.<name>"``.
# Without it, the phantom-limb check (run by the Structural Verifier and
# the Coverage Auditor alike) rejects the empty name as an ERROR, so an
# application that registers one CONSTANT or TYPE cell reports UNHEALTHY.


class TestRegisterConstantQualifiedName:
    """``register_constant`` derives ``qualified_name`` from ``module_path``."""

    def test_qualified_name_derived_from_module_path(self) -> None:
        registry = ComponentRegistry(persist=False)
        spec = registry.register_constant(
            name="SAMPLE_CONST",
            layer="APPLICATION",
            intent="A sample constant whose qualified name is derived",
            module_path="presentation.web.shell_view",
        )
        assert spec.qualified_name == "presentation.web.shell_view.SAMPLE_CONST"
        retrieved = registry.get("SAMPLE_CONST")
        assert retrieved is not None
        assert retrieved.qualified_name == "presentation.web.shell_view.SAMPLE_CONST"

    def test_qualified_name_empty_without_module_path(self) -> None:
        registry = ComponentRegistry(persist=False)
        spec = registry.register_constant(
            name="LEGACY_CONST",
            layer="APPLICATION",
            intent="A legacy constant registered without module_path",
        )
        assert spec.qualified_name == ""


class TestRegisterTypeQualifiedName:
    """``register_type`` derives ``qualified_name`` from ``module_path``."""

    def test_qualified_name_derived_from_module_path(self) -> None:
        registry = ComponentRegistry(persist=False)
        spec = registry.register_type(
            name="UserId",
            layer="DOMAIN",
            intent="Type alias for user identifier in domain layer",
            module_path="domain.identifiers",
        )
        assert spec.qualified_name == "domain.identifiers.UserId"

    def test_qualified_name_empty_without_module_path(self) -> None:
        registry = ComponentRegistry(persist=False)
        spec = registry.register_type(
            name="LegacyId",
            layer="DOMAIN",
            intent="Type alias registered without module_path",
        )
        assert spec.qualified_name == ""


class TestPersistedRegistryRefreshesEmptyQualifiedName:
    """A registry persisted before the name was derived is repaired in place.

    ``register(..., idempotent=True)`` returns early for a stored spec from
    the same source file, so a constant stored with ``qualified_name == ""``
    would otherwise keep the empty name for every later run.
    """

    def test_stored_empty_qualified_name_is_refreshed_and_persisted(
        self, tmp_path: Path,
    ) -> None:
        db_path = tmp_path / "registry.db"

        # A store written by the older code: the same constant, empty name.
        first = ComponentRegistry(persist=True, db_path=db_path)
        first.register_constant(
            name="STORED_CONST",
            layer="APPLICATION",
            intent="A constant stored before qualified_name was derived",
            module_path="legacy.module",
        )
        assert first._connection is not None
        first._connection.execute(
            "UPDATE components SET qualified_name = '' WHERE name = 'STORED_CONST'"
        )
        first._connection.commit()
        first.close()

        reloaded = ComponentRegistry(persist=True, db_path=db_path)
        stored = reloaded.get("STORED_CONST")
        assert stored is not None
        assert stored.qualified_name == ""

        # The module registers its constant again on the next load.
        spec = reloaded.register_constant(
            name="STORED_CONST",
            layer="APPLICATION",
            intent="A constant stored before qualified_name was derived",
            module_path="legacy.module",
        )
        assert spec.qualified_name == "legacy.module.STORED_CONST"
        refreshed = reloaded.get("STORED_CONST")
        assert refreshed is not None
        assert refreshed.qualified_name == "legacy.module.STORED_CONST"
        reloaded.close()

        # And the repair reached the store.
        third = ComponentRegistry(persist=True, db_path=db_path)
        persisted = third.get("STORED_CONST")
        assert persisted is not None
        assert persisted.qualified_name == "legacy.module.STORED_CONST"
        third.close()


class TestRegisterConstantValue:
    """``register_constant`` carries the constant's literal when it is given."""

    def test_value_is_stored_in_metadata_and_the_snapshot(self) -> None:
        registry = ComponentRegistry(persist=False)
        spec = registry.register_constant(
            name="MIN_INTERVAL_SECONDS",
            layer="APPLICATION",
            intent="Hard floor for interval triggers, in seconds",
            module_path="scheduler_service",
            value=60,
        )
        assert spec.metadata["value"] == 60
        assert spec.metadata["kind_detail"] == "CONSTANT"
        snapshot = registry.snapshot().to_dict()
        assert snapshot["components"]["MIN_INTERVAL_SECONDS"]["metadata"]["value"] == 60

    def test_none_is_a_value_and_absence_is_not(self) -> None:
        registry = ComponentRegistry(persist=False)
        with_none = registry.register_constant(
            name="OPTIONAL_LIMIT",
            layer="APPLICATION",
            intent="A limit that is unset by default",
            value=None,
        )
        assert "value" in with_none.metadata and with_none.metadata["value"] is None
        without = registry.register_constant(
            name="COMPUTED_LIMIT",
            layer="APPLICATION",
            intent="A limit computed at import time",
        )
        assert "value" not in without.metadata

    def test_value_survives_persistence(self, tmp_path: Path) -> None:
        db = tmp_path / "registry.db"
        registry = ComponentRegistry(persist=True, db_path=db)
        try:
            registry.register_constant(
                name="SUFFIXES",
                layer="APPLICATION",
                intent="Artifact suffixes a build emits per source",
                value=[".py", ".s0ma.json"],
            )
        finally:
            registry.close()
        reopened = ComponentRegistry(persist=True, db_path=db)
        try:
            spec = reopened.get("SUFFIXES")
            assert spec is not None
            assert spec.metadata["value"] == [".py", ".s0ma.json"]
        finally:
            reopened.close()
