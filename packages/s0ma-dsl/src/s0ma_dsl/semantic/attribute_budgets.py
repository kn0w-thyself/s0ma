"""Project-level enforcement of ``[tool.s0ma.attribute_budgets]`` (M18 + F3).

A nerve's optional ``declares_attributes:`` field carries a list of
``<namespace>:<attribute>`` strings — structural claims a nerve makes
about its output (HTML landmarks, HTTP routes, CSS classes, RPC method
names, …). When a project configures budgets for one or more
namespaces under ``[tool.s0ma.attribute_budgets]``, this module
enforces those budgets across the project and surfaces
``ATTRIBUTE_BUDGET_VIOLATION`` diagnostics.

Three budget shapes are supported (see
:data:`s0ma_dsl.project.SUPPORTED_ATTRIBUTE_BUDGETS`):

- ``exactly_one_per_page`` — exactly one nerve in the reachable nerve
  set of each "page" must declare a given ``<namespace>:<attribute>``
  string. Zero or more-than-one fires the violation.
- ``unique_in_project`` — the ``<namespace>:<attribute>`` string may
  appear at most once across every nerve in the project.
- ``warn_on_duplicate`` — same shape as ``unique_in_project`` but
  surfaced as warnings.

"Page" interpretation (F3, replaces M18's heuristic): a *page* is any
nerve marked ``is_page_composer: true``. The validator walks the
``uses:`` graph from each marked nerve's owning module to compute the
reachable module set, then counts ``declares_attributes:`` entries
across every nerve in those modules. Marking is **explicit**: the
project author opts a nerve in, and the validator only walks budget
rules from explicitly-marked nerves. If a project configures an
``exactly_one_per_page`` budget but no nerve carries the marker, the
resolver emits ``NO_PAGE_COMPOSER_DECLARED`` (error in every mode).
Silent no-op was the documented failure mode of M18's heuristic
("top-level module in the uses graph") — replaced in F3 to satisfy
the principle "no silent failures."

PRD references: feedback-5.5 lines 1023–1061 (the original
``declares_landmarks:`` request, generalised here);
the 5-6 plan (internal) Milestone F3.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from s0ma.decorators import component
from s0ma.types import ComponentKind, Layer

from s0ma_dsl.config import StrictnessMode, get_severity
from s0ma_dsl.errors import S0maResolutionError
from s0ma_dsl.project import SUPPORTED_ATTRIBUTE_BUDGETS

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping

    from s0ma_dsl.ast_nodes.nodes import NerveDecl, S0maModule

__all__ = ["check_attribute_budgets"]


def _module_from_qualified(qualified_name: str) -> str:
    """Return the module name from a ``module.component`` qualified name."""
    return qualified_name.split(".", 1)[0]


def _reachable_modules(
    root: str, modules: Mapping[str, S0maModule]
) -> list[str]:
    """Return the transitive closure of ``root`` over the ``uses:`` graph.

    Includes ``root`` itself. The traversal is deterministic
    (sorted-by-name BFS) so diagnostics are stable across runs and
    cycles in the graph terminate naturally — the ``seen`` set guards
    re-entry, so an A → B → C → A cycle visits each node exactly once.
    """
    seen: set[str] = {root}
    order: list[str] = [root]
    queue: list[str] = [root]
    while queue:
        current = queue.pop(0)
        mod = modules.get(current)
        if mod is None:
            continue
        next_targets: list[str] = []
        for use in mod.module.uses:
            target = _module_from_qualified(use.qualified_name)
            if target in modules and target not in seen:
                next_targets.append(target)
        for target in sorted(next_targets):
            seen.add(target)
            order.append(target)
            queue.append(target)
    return order


def _collect_nerves_with_attributes(
    module_names: Iterable[str], modules: Mapping[str, S0maModule]
) -> list[tuple[str, NerveDecl]]:
    """Return ``(module_name, nerve)`` for every nerve declaring attributes.

    Order is stable: module-name then nerve source line, matching the
    surrounding diagnostic ordering used by the resolver.
    """
    out: list[tuple[str, NerveDecl]] = []
    for mod_name in module_names:
        mod = modules.get(mod_name)
        if mod is None:
            continue
        for nerve in mod.nerves:
            if nerve.declares_attributes:
                out.append((mod_name, nerve))
    return out


def _attribute_namespace(attribute: str) -> str:
    """Return the namespace half of a ``<namespace>:<attribute>`` entry."""
    return attribute.split(":", 1)[0]


def _page_composer_nerves(
    modules: Mapping[str, S0maModule],
) -> list[tuple[str, NerveDecl]]:
    """Return ``(module_name, nerve)`` for every explicitly-marked composer.

    F3 replaces M18's heuristic ("top-level module in the uses graph")
    with explicit declaration: a nerve scopes a page only when its
    author writes ``is_page_composer: true``. The walker emits results
    in module-name → source-line order so per-page diagnostics are
    deterministic.
    """
    out: list[tuple[str, NerveDecl]] = []
    for mod_name in sorted(modules.keys()):
        mod = modules[mod_name]
        for nerve in mod.nerves:
            if nerve.is_page_composer:
                out.append((mod_name, nerve))
    return out


@component(
    name="S0maDSL_check_attribute_budgets",
    kind=ComponentKind.FUNCTION,
    layer=Layer.FRAMEWORK,
    intent=(
        "Enforce [tool.s0ma.attribute_budgets] across all nerves in the project; emits "
        "ATTRIBUTE_BUDGET_VIOLATION and NO_PAGE_COMPOSER_DECLARED diagnostics."
    ),
    idempotent=True,
    is_framework=True,
)
def check_attribute_budgets(
    modules: Mapping[str, S0maModule],
    *,
    attribute_budgets: Mapping[str, str],
    mode: StrictnessMode,
    filenames: Mapping[str, str] | None = None,
) -> list[S0maResolutionError]:
    """Run every configured budget check and return the diagnostics.

    Parameters
    ----------
    modules:
        Project view: ``module_name → parsed S0maModule``.
    attribute_budgets:
        ``namespace → shape`` from ``[tool.s0ma.attribute_budgets]``.
        An empty mapping short-circuits (no checks run).
    mode:
        Active strictness mode — used to resolve severities for the
        non-warn shapes.
    filenames:
        Optional ``module_name → source file path`` map for richer
        diagnostics. Falls back to ``f"{name}.s0ma"`` when missing.

    Returns
    -------
    list[S0maResolutionError]
        ``ATTRIBUTE_BUDGET_VIOLATION`` and (F3) ``NO_PAGE_COMPOSER_DECLARED``
        diagnostics; empty when every budget is satisfied or no budgets
        are configured.
    """
    if not attribute_budgets:
        return []
    filenames_map = dict(filenames) if filenames is not None else {}
    diagnostics: list[S0maResolutionError] = []

    # Validate the budget shapes once. The project parser already
    # rejects unknown shapes, but a unit-test caller may construct the
    # dict directly — keep the resolver self-defending.
    for namespace, shape in attribute_budgets.items():
        if shape not in SUPPORTED_ATTRIBUTE_BUDGETS:
            raise ValueError(
                f"Unknown attribute_budgets shape for namespace "
                f"{namespace!r}: {shape!r}. Supported shapes: "
                f"{sorted(SUPPORTED_ATTRIBUTE_BUDGETS)!r}."
            )

    # Build a per-namespace severity map. ``warn_on_duplicate`` is
    # always a warning; the other shapes ladder via the severity matrix
    # entry for ``ATTRIBUTE_BUDGET_VIOLATION`` (warning in migration,
    # error otherwise).
    matrix_severity = get_severity("ATTRIBUTE_BUDGET_VIOLATION", mode)

    nerves_with_attrs = _collect_nerves_with_attributes(
        sorted(modules.keys()), modules
    )

    # ---------------------------------------------------------------
    # ``unique_in_project`` and ``warn_on_duplicate``: both flag any
    # ``<namespace>:<attribute>`` string that appears more than once.
    # ---------------------------------------------------------------
    project_index: dict[str, list[tuple[str, NerveDecl]]] = {}
    for mod_name, nerve in nerves_with_attrs:
        for attr in nerve.declares_attributes:
            project_index.setdefault(attr, []).append((mod_name, nerve))

    for attr, occurrences in sorted(project_index.items()):
        if len(occurrences) <= 1:
            continue
        namespace = _attribute_namespace(attr)
        budget_shape = attribute_budgets.get(namespace)
        if budget_shape not in ("unique_in_project", "warn_on_duplicate"):
            continue
        severity = "warning" if budget_shape == "warn_on_duplicate" else matrix_severity
        if severity is None:
            continue
        first_mod, first_nerve = occurrences[0]
        line = (
            first_nerve.location.start_line
            if first_nerve.location is not None
            else 0
        )
        filename = filenames_map.get(
            first_mod, f"{first_mod}.s0ma"
        )
        offending = [
            f"{m}.{n.name}" for m, n in occurrences
        ]
        diagnostics.append(S0maResolutionError(
            code="ATTRIBUTE_BUDGET_VIOLATION",
            message=(
                f"Attribute {attr!r} declared by {len(occurrences)} "
                f"nerves but namespace {namespace!r} has budget "
                f"{shape!r}: only one occurrence is allowed across "
                f"the project. Nerves: {', '.join(offending)}."
            ),
            file=filename,
            line=line,
            column=0,
            severity=severity,
            remediation=(
                f"Pick one nerve to own {attr!r} (typically the page "
                f"composer for the namespace), and remove the entry "
                f"from the others' declares_attributes:. If the "
                f"duplication is intentional, change the budget for "
                f"{namespace!r} to 'warn_on_duplicate' or remove the "
                f"budget entry altogether."
            ),
            context={
                "namespace": namespace,
                "attribute": attr,
                "budget_shape": shape,
                "nerves": offending,
            },
        ))

    # ---------------------------------------------------------------
    # ``exactly_one_per_page`` (F3): per-page reachable nerve set must
    # contain exactly one declaration of every ``<namespace>:<attribute>``
    # whose namespace is budgeted this way.
    #
    # F3 replaces M18's heuristic ("top-level modules in the uses
    # graph") with explicit declaration: each nerve marked
    # ``is_page_composer: true`` is a scope root; the walker computes
    # the reachable module set from each composer's owning module and
    # counts attribute occurrences across those modules' nerves.
    # ---------------------------------------------------------------
    exactly_one_namespaces = {
        ns for ns, shape in attribute_budgets.items()
        if shape == "exactly_one_per_page"
    }
    if exactly_one_namespaces:
        page_composers = _page_composer_nerves(modules)
        if not page_composers:
            # F3: the project configures ``exactly_one_per_page`` but
            # no nerve is explicitly marked. Fire a single, project-
            # level diagnostic — silent no-op is forbidden by the
            # principle "no silent failures."
            severity = get_severity("NO_PAGE_COMPOSER_DECLARED", mode)
            if severity is not None:
                # Pick a stable file/line: first module by name, line 1.
                # No specific nerve owns this diagnostic — it is a
                # project-level configuration error.
                first_module = sorted(modules.keys())[0] if modules else "<project>"
                filename = filenames_map.get(
                    first_module, f"{first_module}.s0ma"
                )
                budgeted_list = ", ".join(sorted(exactly_one_namespaces))
                diagnostics.append(S0maResolutionError(
                    code="NO_PAGE_COMPOSER_DECLARED",
                    message=(
                        f"Project configures 'exactly_one_per_page' "
                        f"budget for namespace(s) {{{budgeted_list}}} "
                        f"but no nerve is marked "
                        f"'is_page_composer: true'. The "
                        f"'exactly_one_per_page' shape requires at "
                        f"least one explicitly-declared page composer "
                        f"to scope the per-page reachable nerve set."
                    ),
                    file=filename,
                    line=1,
                    column=0,
                    severity=severity,
                    remediation=(
                        "Add 'is_page_composer: true' to the nerve "
                        "that scopes a page (typically the top-level "
                        "page composer that uses: every landmark "
                        "renderer). The validator walks the uses: "
                        "graph from that nerve's module to compute "
                        "the per-page reachable nerve set. If the "
                        "project does not have a page-scoped concept, "
                        "switch the budget shape to 'unique_in_project' "
                        "or 'warn_on_duplicate', or remove the entry "
                        "from [tool.s0ma.attribute_budgets]."
                    ),
                    context={
                        "budgeted_namespaces": sorted(exactly_one_namespaces),
                    },
                ))
        else:
            # One reachable-module set per marked nerve. We key by
            # composer module name so two composers in the same module
            # — an unusual but legal shape — share the page index.
            for composer_mod, composer_nerve in page_composers:
                reachable = _reachable_modules(composer_mod, modules)
                page_index: dict[str, list[tuple[str, NerveDecl]]] = {}
                for mod_name, nerve in _collect_nerves_with_attributes(
                    reachable, modules
                ):
                    for attr in nerve.declares_attributes:
                        if _attribute_namespace(attr) in exactly_one_namespaces:
                            page_index.setdefault(attr, []).append(
                                (mod_name, nerve)
                            )
                # Page label combines module + composer name so two
                # composers in one module produce distinguishable
                # diagnostics.
                page_label = f"{composer_mod}.{composer_nerve.name}"
                for attr, occurrences in sorted(page_index.items()):
                    if len(occurrences) == 1:
                        continue
                    namespace = _attribute_namespace(attr)
                    severity = matrix_severity
                    if severity is None:
                        continue
                    offending = [
                        f"{m}.{n.name}" for m, n in occurrences
                    ]
                    first_mod, first_nerve = occurrences[0]
                    line = (
                        first_nerve.location.start_line
                        if first_nerve.location is not None
                        else 0
                    )
                    filename = filenames_map.get(
                        first_mod, f"{first_mod}.s0ma"
                    )
                    diagnostics.append(S0maResolutionError(
                        code="ATTRIBUTE_BUDGET_VIOLATION",
                        message=(
                            f"Page {page_label!r} reaches "
                            f"{len(occurrences)} nerves declaring "
                            f"attribute {attr!r} but namespace "
                            f"{namespace!r} has budget "
                            f"'exactly_one_per_page': exactly one "
                            f"occurrence is required per page "
                            f"composer's reachable nerve set. Nerves: "
                            f"{', '.join(offending)}."
                        ),
                        file=filename,
                        line=line,
                        column=0,
                        severity=severity,
                        remediation=(
                            f"Keep one nerve declaring {attr!r} "
                            f"(typically the canonical {namespace} "
                            f"owner) and remove the entry from the "
                            f"others' declares_attributes: list. If "
                            f"the duplication is intentional, change "
                            f"the budget for {namespace!r} to "
                            f"'warn_on_duplicate' or "
                            f"'unique_in_project'."
                        ),
                        context={
                            "namespace": namespace,
                            "attribute": attr,
                            "budget_shape": "exactly_one_per_page",
                            "page": page_label,
                            "page_composer": page_label,
                            "nerves": offending,
                        },
                    ))

    return diagnostics
