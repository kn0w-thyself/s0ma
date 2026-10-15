"""Component decorators — the primary developer-facing API.

The @component decorator is how developers register code in the self-model.
It simultaneously registers the entity, validates required metadata, and
attaches introspectable metadata — without wrapping or proxying the original.

The @internal decorator marks private helpers as intentionally unregistered,
telling the import hook to exempt them from enforcement.

Key functions:
    - component(): decorator factory for registering components
    - internal(): lightweight marker for private helpers
    - is_component(): introspection check for decorated entities
    - is_internal(): introspection check for internal entities
    - get_component_spec(): retrieve the ComponentSpec from a decorated entity
    - get_all_components_in_module(): scan a module for all registered components
"""

from __future__ import annotations

import contextlib
import inspect
import logging
from typing import TYPE_CHECKING, Any, TypeVar, overload

from s0ma.exceptions import RegistrationError
from s0ma.models import ComponentSpec, Contract, ResourceProfile
from s0ma.registry import get_registry

if TYPE_CHECKING:
    from collections.abc import Callable
    from types import ModuleType

    from s0ma.types import ComponentKind, Layer

__all__ = [
    "component",
    "internal",
    "is_component",
    "is_internal",
    "get_component_spec",
    "get_all_components_in_module",
]

logger = logging.getLogger("s0ma")

# TypeVar for preserving the decorated entity's type
_T = TypeVar("_T")


def component(
    name: str,
    kind: ComponentKind,
    layer: Layer,
    intent: str,
    *,
    contracts: Contract | None = None,
    dependencies: list[str] | None = None,
    resource_profile: ResourceProfile | None = None,
    version: str = "0.1.0",
    metadata: dict[str, Any] | None = None,
    is_framework: bool = False,
    idempotent: bool = False,
) -> Callable[[_T], _T]:
    """Decorator factory that registers a class or function as a component.

    Constructs a ComponentSpec from the provided metadata and auto-derived
    fields (module_path, qualified_name, source_file), registers it in the
    global registry, and attaches the spec to the entity as ``__component__``.

    The decorated entity is returned **unmodified** — this decorator does not
    wrap or proxy. Zero runtime overhead on calls.

    Args:
        name: Unique component identifier.
        kind: The component archetype (SERVICE, FUNCTION, MODEL, etc.).
        layer: The architectural layer (DOMAIN, APPLICATION, etc.).
        intent: Natural language description of purpose (min 10 chars).
        contracts: Behavioral contracts (pre/postconditions, invariants,
            forbids). ``forbids`` lists what the component must never
            do, however it is called and whatever happens while it
            runs; s0ma keeps it with the component and shows it, and
            nothing executes it.
        dependencies: Names of components this one depends on.
        resource_profile: Expected resource usage for interoception.
        version: Semantic version string.
        metadata: Extensible key-value store.
        is_framework: True if this is a s0ma internal component.
        idempotent: If True, silently succeed when re-registering the same
            component from the same source file. Useful for hot-reload and
            dynamic code loading scenarios. Default is False.

    Returns:
        A decorator that annotates and registers the target entity.

    Raises:
        RegistrationError: If required fields are missing or invalid,
            if the name is already registered, if the target is not
            a class or function, or if the entity is already decorated.

    Example::

        @component(
            name="PaymentProcessor",
            kind=ComponentKind.SERVICE,
            layer=Layer.DOMAIN,
            intent="Processes customer payments through payment gateways",
        )
        class PaymentProcessor:
            ...
    """

    def decorator(entity: _T) -> _T:
        # Validate the target is a class or function
        if not (isinstance(entity, type) or callable(entity)):
            raise RegistrationError(
                f"@component can only decorate classes and functions, "
                f"got {type(entity).__name__}: {entity!r}"
            )

        # Reject double-decoration — check __dict__ directly to distinguish a
        # directly-attached __component__ from one inherited via a parent class.
        # Subclasses of @component-decorated classes are allowed to establish
        # their own independent registration.
        entity_dict = getattr(entity, "__dict__", {})
        if "__component__" in entity_dict:
            existing = entity_dict["__component__"]
            raise RegistrationError(
                f"Entity '{_get_qualname(entity)}' already has a @component decorator "
                f"(registered as '{existing.name}'). If this was inherited from a parent "
                f"class, use @internal on the abstract base class and @component only on "
                f"concrete implementations."
            )

        # Derive module path, qualified name, and source file
        module_path = getattr(entity, "__module__", "") or ""
        entity_qualname = _get_qualname(entity)
        qualified_name = (
            f"{module_path}.{entity_qualname}" if module_path else entity_qualname
        )

        source_file: str | None = None
        with contextlib.suppress(TypeError, OSError):
            source_file = inspect.getfile(entity)

        # Build the ComponentSpec
        spec = ComponentSpec(
            name=name,
            kind=kind,
            layer=layer,
            intent=intent,
            contracts=contracts if contracts is not None else Contract(),
            dependencies=dependencies if dependencies is not None else [],
            resource_profile=resource_profile,
            version=version,
            metadata=metadata if metadata is not None else {},
            module_path=module_path,
            qualified_name=qualified_name,
            source_file=source_file,
            is_framework=is_framework,
        )

        # Register in the global registry
        registry = get_registry(persist=False)
        registry.register(spec, idempotent=idempotent)

        # Attach the spec to the entity for introspection.
        # Uses setattr to avoid mypy union-attr narrowing issues
        # with TypeVar after isinstance checks.
        setattr(entity, "__component__", spec)  # noqa: B010

        logger.debug(
            "Decorated and registered component '%s' from %s",
            name,
            module_path,
        )

        # Return the entity unmodified — no wrapping, no proxying.
        return entity

    return decorator


@overload
def internal(entity: _T) -> _T: ...


@overload
def internal(*, reason: str) -> Callable[[_T], _T]: ...


def internal(
    entity: _T | None = None, *, reason: str = ""
) -> _T | Callable[[_T], _T]:
    """Mark a helper as intentionally unregistered.

    Attaches ``__s0ma_internal__ = True`` to the entity, telling the
    import hook to exempt it from registration enforcement. Does NOT
    register the entity in the registry.

    Can be used bare or with a reason keyword argument::

        @internal
        def _parse_config(raw: str) -> dict:
            ...

        @internal(reason="Legacy helper, will be removed in v2")
        def _old_parser(raw: str) -> dict:
            ...

    Args:
        entity: The class or function to mark (when used as bare decorator).
        reason: Optional explanation of why this is internal.

    Returns:
        The entity with ``__s0ma_internal__`` set to True.
    """
    if entity is not None:
        # Used as bare decorator: @internal
        entity.__s0ma_internal__ = True  # type: ignore[attr-defined]
        if reason:
            entity.__s0ma_internal_reason__ = reason  # type: ignore[attr-defined]
        return entity

    # Used with arguments: @internal(reason="...")
    def decorator(ent: _T) -> _T:
        ent.__s0ma_internal__ = True  # type: ignore[attr-defined]
        if reason:
            ent.__s0ma_internal_reason__ = reason  # type: ignore[attr-defined]
        return ent

    return decorator


def is_component(obj: object) -> bool:
    """Check whether an object has been decorated with @component.

    Args:
        obj: Any Python object.

    Returns:
        True if the object has a ``__component__`` attribute containing
        a ComponentSpec.
    """
    return hasattr(obj, "__component__") and isinstance(
        obj.__component__, ComponentSpec
    )


def is_internal(obj: object) -> bool:
    """Check whether an object has been decorated with @internal.

    Args:
        obj: Any Python object.

    Returns:
        True if the object has ``__s0ma_internal__`` set to True.
    """
    return getattr(obj, "__s0ma_internal__", False) is True


def get_component_spec(obj: object) -> ComponentSpec | None:
    """Retrieve the ComponentSpec from a @component-decorated entity.

    Args:
        obj: Any Python object.

    Returns:
        The ComponentSpec if the object is a registered component,
        None otherwise.
    """
    if is_component(obj):
        spec: ComponentSpec = obj.__component__  # type: ignore[attr-defined]
        return spec
    return None


def get_all_components_in_module(module: ModuleType) -> list[ComponentSpec]:
    """Scan a module for all @component-decorated entities.

    Iterates over all public names in the module's namespace and collects
    the ComponentSpec from each decorated entity.

    Args:
        module: A Python module object.

    Returns:
        List of ComponentSpecs found in the module, sorted by name.
    """
    specs: list[ComponentSpec] = []
    for attr_name in dir(module):
        obj = getattr(module, attr_name, None)
        if obj is not None and is_component(obj):
            spec = get_component_spec(obj)
            if spec is not None:
                specs.append(spec)
    return sorted(specs, key=lambda s: s.name)


def _get_qualname(entity: object) -> str:
    """Get the qualified name of an entity, falling back to __name__."""
    qualname = getattr(entity, "__qualname__", None)
    if qualname is not None:
        return str(qualname)
    name = getattr(entity, "__name__", None)
    if name is not None:
        return str(name)
    return repr(entity)
