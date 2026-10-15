"""Tests for qualified→bare identifier resolution in the registry.

The DSL emitter (DSL-M2, ADR-011 §(d)) writes cross-module dependency
claims in the canonical ``"module::Name"`` form while registering every
generated component under its bare name (``module_scoped`` stays False).
``_resolve_key`` therefore has to land a qualified identifier on a
bare-keyed spec whenever the spec's recorded ``module_path`` is
consistent with the claimed module. Before this fallback existed,
``register()`` warned "declares dependency '<module>::<Name>' which is
not yet registered" for every cross-module edge of every generated
project even though the target was registered — the 0.15.1 regression
observed in the s0ma-cpx pilot.

Scoped-storage behaviour itself is pinned by
``test_registry_module_scoped.py``; the legacy bare-name regressions by
``test_registry.py``. This file pins qualified-identifier resolution
against bare and scoped stores.
"""

from __future__ import annotations

import logging

import pytest

from s0ma.exceptions import RegistrationError
from s0ma.models import ComponentSpec
from s0ma.registry import ComponentRegistry
from s0ma.types import ComponentKind, Layer


def _make_spec(
    name: str,
    *,
    module_path: str = "",
    module_scoped: bool = False,
    dependencies: list[str] | None = None,
) -> ComponentSpec:
    """Construct a valid ComponentSpec for qualified-resolution tests."""
    return ComponentSpec(
        name=name,
        kind=ComponentKind.MODEL,
        layer=Layer.DOMAIN,
        intent=f"A test component named {name} for qualified resolution tests",
        module_path=module_path,
        qualified_name=f"{module_path}.{name}" if module_path else name,
        module_scoped=module_scoped,
        dependencies=dependencies or [],
    )


def _dependency_warnings(caplog: pytest.LogCaptureFixture) -> list[str]:
    """The dependency-validation warnings captured from the s0ma logger."""
    return [
        record.getMessage()
        for record in caplog.records
        if "declares dependency" in record.getMessage()
    ]


class TestQualifiedClaimAgainstBareStore:
    """``register()`` dependency validation accepts true qualified claims."""

    def test_matching_module_path_does_not_warn(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """The generated shape: bare-keyed target, qualified claim, no warning."""
        registry = ComponentRegistry(persist=False)
        registry.register(
            _make_spec("LightReading", module_path="reading_models")
        )
        with caplog.at_level(logging.WARNING, logger="s0ma"):
            registry.register(
                _make_spec(
                    "read_light",
                    module_path="senses",
                    dependencies=["reading_models::LightReading"],
                )
            )
        assert _dependency_warnings(caplog) == []
        assert registry.count() == 2

    def test_package_prefixed_module_path_matches(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """``module_path`` is a Python import path; a package prefix is fine."""
        registry = ComponentRegistry(persist=False)
        registry.register(
            _make_spec("LightReading", module_path="build.reading_models")
        )
        with caplog.at_level(logging.WARNING, logger="s0ma"):
            registry.register(
                _make_spec(
                    "read_light",
                    module_path="build.senses",
                    dependencies=["reading_models::LightReading"],
                )
            )
        assert _dependency_warnings(caplog) == []

    def test_wrong_module_still_warns(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """A claim naming the wrong module is genuinely suspect — keep warning."""
        registry = ComponentRegistry(persist=False)
        registry.register(_make_spec("LightReading", module_path="motors"))
        with caplog.at_level(logging.WARNING, logger="s0ma"):
            registry.register(
                _make_spec(
                    "read_light",
                    module_path="senses",
                    dependencies=["reading_models::LightReading"],
                )
            )
        assert len(_dependency_warnings(caplog)) == 1

    def test_similar_module_name_is_not_a_match(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Suffix matching is segment-aware — no substring false positives."""
        registry = ComponentRegistry(persist=False)
        registry.register(
            _make_spec("LightReading", module_path="not_reading_models")
        )
        with caplog.at_level(logging.WARNING, logger="s0ma"):
            registry.register(
                _make_spec(
                    "read_light",
                    module_path="senses",
                    dependencies=["reading_models::LightReading"],
                )
            )
        assert len(_dependency_warnings(caplog)) == 1

    def test_unregistered_target_still_warns(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """A qualified claim on a genuinely absent component keeps warning."""
        registry = ComponentRegistry(persist=False)
        registry.register(
            _make_spec("LightReading", module_path="reading_models")
        )
        with caplog.at_level(logging.WARNING, logger="s0ma"):
            registry.register(
                _make_spec(
                    "read_light",
                    module_path="senses",
                    dependencies=["reading_models::Ghost"],
                )
            )
        assert len(_dependency_warnings(caplog)) == 1

    def test_empty_module_path_does_not_refute_the_claim(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """A target that recorded no module_path can't contradict the claim."""
        registry = ComponentRegistry(persist=False)
        registry.register(_make_spec("LightReading", module_path=""))
        with caplog.at_level(logging.WARNING, logger="s0ma"):
            registry.register(
                _make_spec(
                    "read_light",
                    module_path="senses",
                    dependencies=["reading_models::LightReading"],
                )
            )
        assert _dependency_warnings(caplog) == []

    def test_strict_mode_accepts_registered_qualified_claim(self) -> None:
        registry = ComponentRegistry(persist=False, strict_dependencies=True)
        registry.register(
            _make_spec("LightReading", module_path="reading_models")
        )
        registry.register(
            _make_spec(
                "read_light",
                module_path="senses",
                dependencies=["reading_models::LightReading"],
            )
        )
        assert registry.count() == 2

    def test_strict_mode_still_raises_on_wrong_module(self) -> None:
        registry = ComponentRegistry(persist=False, strict_dependencies=True)
        registry.register(_make_spec("LightReading", module_path="motors"))
        with pytest.raises(RegistrationError, match="not yet registered"):
            registry.register(
                _make_spec(
                    "read_light",
                    module_path="senses",
                    dependencies=["reading_models::LightReading"],
                )
            )


class TestQualifiedLookupSurface:
    """``get`` / ``contains`` / ``get_dependencies`` accept qualified IDs."""

    def test_get_by_qualified_name_of_bare_spec(self) -> None:
        registry = ComponentRegistry(persist=False)
        registry.register(
            _make_spec("LightReading", module_path="reading_models")
        )
        spec = registry.get("reading_models::LightReading")
        assert spec is not None
        assert spec.name == "LightReading"
        assert registry.contains("reading_models::LightReading") is True
        assert "reading_models::LightReading" in registry
        # A wrong-module qualified lookup stays a miss.
        assert registry.get("motors::LightReading") is None

    def test_get_dependencies_resolves_qualified_claims(self) -> None:
        registry = ComponentRegistry(persist=False)
        registry.register(
            _make_spec("LightReading", module_path="reading_models")
        )
        registry.register(
            _make_spec(
                "read_light",
                module_path="senses",
                dependencies=["reading_models::LightReading"],
            )
        )
        deps = registry.get_dependencies("read_light")
        assert [d.name for d in deps] == ["LightReading"]

    def test_qualified_lookup_reaches_scoped_key_via_module_suffix(self) -> None:
        """A scoped spec stored under a package-prefixed key is reachable
        through the DSL-module canonical ID."""
        registry = ComponentRegistry(persist=False)
        registry.register(
            _make_spec(
                "Foo", module_path="build.mod_a", module_scoped=True
            )
        )
        spec = registry.get("mod_a::Foo")
        assert spec is not None
        assert spec.module_path == "build.mod_a"

    def test_ambiguous_qualified_lookup_returns_none(self) -> None:
        """Two scoped specs both consistent with the claim — refuse to guess."""
        registry = ComponentRegistry(persist=False)
        registry.register(
            _make_spec("Foo", module_path="build_a.mod", module_scoped=True)
        )
        registry.register(
            _make_spec("Foo", module_path="build_b.mod", module_scoped=True)
        )
        assert registry.get("mod::Foo") is None
        # Fully-qualified direct keys keep working.
        assert registry.get("build_a.mod::Foo") is not None
        assert registry.get("build_b.mod::Foo") is not None

    def test_malformed_qualified_names_stay_misses(self) -> None:
        registry = ComponentRegistry(persist=False)
        registry.register(
            _make_spec("LightReading", module_path="reading_models")
        )
        assert registry.get("::LightReading") is None
        assert registry.get("reading_models::") is None
