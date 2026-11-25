"""``s0ma new project --template <service|library|cli|pipeline|agent>`` archetypes (STD-M7).

Each archetype is a **complete, compiling mini-app** — the archetype *is*
the design-pattern documentation. ``s0ma new project`` without ``--template``
scaffolds M6's minimal single-feature starter; the four archetypes here are
**additive**, each a larger worked example a reader can build, ``check``
(including ``--mode release``), ``test``, and run out of the box.

The four archetypes and what each teaches
-----------------------------------------
- **service** — a three-feature, three-layer service (DOMAIN catalog →
  APPLICATION ordering → PRESENTATION api). Teaches **cross-feature
  ``depends_on:`` edges** in the qualified ``module.declaration`` form and
  the **layer reachability matrix** (PRESENTATION → APPLICATION → DOMAIN,
  never upward), in a project that passes ``check --mode release``. Ships the
  single sanctioned plain-Python **bootstrap** (``bootstrap/main.py``,
  declared in ``[tool.s0ma].bootstrap_files``) that wires the built modules.
- **library** — a layer-light, export-focused package (one DOMAIN feature: a
  slug core + a thin public facade). Teaches **``exports:``** and
  **``covered_by:``** (external-pytest-suite test credit for the release
  gate, on the thin facade that has no in-language test) and notes that
  **layer-first is acceptable for small libraries**.
- **cli** — a thin-Python bootstrap shim dispatching to a PRESENTATION nerve
  via the **``argparse.REMAINDER``** handoff (the quick-reference pattern,
  including the leading-``--`` strip), over a DOMAIN/APPLICATION core.
- **pipeline**: one module per layer (INFRASTRUCTURE ``player`` → DOMAIN
  ``music`` → APPLICATION ``coach`` → PRESENTATION ``page``): it reads what
  is playing from built-in samples, measures the song, settles on a mood,
  chooses a nudge, and shows it as page text. Its declared text is written
  for a reader who does not program, and a ganglion watches the mood nerve.
  The bootstrap hands the INFRASTRUCTURE source to the PRESENTATION page,
  since neither boundary layer may reach the other.
- **agent**: a small support-inbox agent declared as five ordered steps
  (:class:`ArchetypeStep`). It reads a customer message, then answers from a
  short list of common answers, looks up an order with a tool, or hands off
  to a person, and it never promises a refund. Its model sits behind an
  abstract ADAPTER port with a scripted stand-in, so it checks, builds,
  tests, and runs with no account, no key, and no network. Each prefix of
  its steps is itself a clean project (:meth:`Archetype.files_through`).

Every archetype ships the feature-first layout, **AGENTS.md** + a thin
**CLAUDE.md** (reusing :func:`s0ma_dsl.cli.new_project.scaffold_agent_files`),
the load-bearing **app map**, and starter ``test``/``covered_by:`` coverage
so ``s0ma check`` (and ``--mode release``) and ``s0ma test`` pass immediately.

This module is pure content + a thin planner: it returns the file set an
archetype lays down; the orchestration (refusal scan, pyproject write, first
build, summary) stays in :mod:`s0ma_dsl.cli.new_project`.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, replace
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Callable

#: The archetype names ``--template`` accepts (the default — no template — is
#: M6's minimal starter, handled in ``new_project``). Decision 4 shipped
#: service + library first, then cli; pipeline and agent came after. The
#: CLI's ``--template`` choices are read from here.
TEMPLATE_CHOICES: tuple[str, ...] = (
    "service",
    "library",
    "cli",
    "pipeline",
    "agent",
)


@dataclass(frozen=True)
class ArchetypeFile:
    """One file an archetype writes, by project-root-relative POSIX path."""

    #: Path relative to the project root, POSIX (e.g. ``src/catalog/x.s0ma``).
    relpath: str
    #: Full file content (always written LF, UTF-8).
    content: str


@dataclass(frozen=True)
class ArchetypeStep:
    """One ordered step of an archetype declared as steps.

    A step writes its files on top of every earlier step's; a file it names
    that an earlier step already wrote is replaced. The files of steps 1 to
    N, for any N, make a project that checks, builds, tests, and runs.
    """

    #: The step's short name, as a person reads it (e.g. ``Its tools``).
    name: str
    #: One sentence on what the step adds.
    intent: str
    #: The files the step writes or replaces.
    files: tuple[ArchetypeFile, ...]


def _apply_steps(
    steps: tuple[ArchetypeStep, ...], count: int
) -> tuple[ArchetypeFile, ...]:
    """The file set of steps 1 to *count*, applied in order.

    A later step's file replaces an earlier one at the same path and keeps
    the place the path first took, so the order is stable across prefixes.
    """
    if not 1 <= count <= len(steps):
        raise ValueError(
            f"step count must be between 1 and {len(steps)}, not {count}"
        )
    applied: dict[str, ArchetypeFile] = {}
    for step in steps[:count]:
        for file in step.files:
            applied[file.relpath] = file
    return tuple(applied.values())


def _features_of(files: tuple[ArchetypeFile, ...]) -> tuple[str, ...]:
    """The feature directories under ``src/`` that *files* write, in order."""
    features: list[str] = []
    for file in files:
        parts = file.relpath.split("/")
        if len(parts) > 2 and parts[0] == "src" and parts[1] not in features:
            features.append(parts[1])
    return tuple(features)


#: A top-level declaration that counts as one working part of a sample.
_PART_LINE = re.compile(r"^(?:cell|nerve|ganglion) \w+ ::", re.MULTILINE)


def count_parts(files: tuple[ArchetypeFile, ...]) -> int:
    """The working parts *files* declare: cells, nerves, and ganglia under ``src/``.

    Tests and the app map's doc declarations are not counted.
    """
    return sum(
        len(_PART_LINE.findall(file.content))
        for file in files
        if file.relpath.startswith("src/") and file.relpath.endswith(".s0ma")
    )


@dataclass(frozen=True)
class Archetype:
    """A complete archetype: the files it writes plus its summary facts.

    An archetype either lists its ``files`` directly or declares ordered
    ``steps``. For one with steps, ``files`` is derived (every step applied
    in order) and so is ``features`` when it is left empty.
    """

    #: The ``--template`` name.
    name: str
    #: One-line description for the printed/JSON summary.
    summary: str
    #: Feature directories the archetype creates under ``src/``.
    features: tuple[str, ...] = ()
    #: The ``.s0ma`` source + test + app-map + bootstrap files (everything
    #: except AGENTS.md/CLAUDE.md and pyproject, which the orchestrator owns).
    files: tuple[ArchetypeFile, ...] = ()
    #: ``[tool.s0ma].bootstrap_files`` entries (POSIX, project-root-relative);
    #: empty for archetypes with no plain-Python bootstrap (library).
    bootstrap_files: tuple[str, ...] = ()
    #: The DSL concept this archetype is the worked example for (summary copy).
    teaches: str = ""
    #: Extra notes for the printed next-steps (e.g. how to run the bootstrap).
    run_hint: str = ""
    #: The ordered steps, for an archetype declared as steps; empty otherwise.
    steps: tuple[ArchetypeStep, ...] = ()
    #: What the sample calls itself in a sentence (e.g. ``a small agent``).
    called: str = ""
    #: A question a person can ask the sample about itself.
    example_question: str = ""
    #: ``[tool.s0ma].health_command`` to declare; empty declares none.
    health_command: str = ""

    def __post_init__(self) -> None:
        if not self.steps:
            return
        if self.files:
            raise ValueError(
                f"archetype {self.name!r} declares steps, so its files are "
                f"derived and must not be given"
            )
        files = _apply_steps(self.steps, len(self.steps))
        object.__setattr__(self, "files", files)
        if not self.features:
            object.__setattr__(self, "features", _features_of(files))

    def files_through(self, count: int) -> tuple[ArchetypeFile, ...]:
        """The files of steps 1 to *count*, a later step replacing an earlier file.

        Raises :class:`ValueError` for an archetype with no steps or a count
        outside 1 to the number of steps.
        """
        if not self.steps:
            raise ValueError(f"archetype {self.name!r} is not declared as steps")
        return _apply_steps(self.steps, count)

    def through_step(self, count: int) -> Archetype:
        """This archetype cut to steps 1 to *count*, its files and features derived.

        The result scaffolds like any archetype, so steps 1 to N can be laid
        down with the same machinery as the whole sample.
        """
        self.files_through(count)  # the same checks on *count*
        return replace(
            self, steps=self.steps[:count], files=(), features=()
        )


# ---------------------------------------------------------------------------
# service — DOMAIN catalog → APPLICATION ordering → PRESENTATION api
# ---------------------------------------------------------------------------

_SERVICE_CATALOG_DOMAIN = """\
module catalog_domain
    layer: DOMAIN
    version: 0.1.0
    intent: "Catalog domain: the Product model and the pure pricing rule the rest of the service builds on."
    requires: [dataclasses:dataclass]
    exports: [Product, price_of]

cell Product :: DOMAIN
    kind: MODEL
    visibility: PUBLIC
    intent: "An item the service can sell: a stable SKU, a display name, and a unit price in whole cents."
    schema: "sku: str, name: str, unit_price_cents: int"
    ---
    @dataclass(frozen=True)
    class Product:
        sku: str
        name: str
        unit_price_cents: int

nerve price_of :: DOMAIN
    kind: FUNCTION
    visibility: PUBLIC
    intent: "Compute the line price for a quantity of a product, in whole cents."
    expects: "A Product and a positive integer quantity."
    guarantees: "Returns quantity * unit_price_cents; raises ValueError when quantity < 1."
    forbids: "Never price a quantity below 1; price_of raises ValueError instead."
    evaluates_at: FUNCTION_BOUNDARY
    ---
    def price_of(product: Product, quantity: int) -> int:
        \"\"\"Return the line price (cents) for *quantity* units of *product*.\"\"\"
        if quantity < 1:
            raise ValueError("quantity must be at least 1")
        return product.unit_price_cents * quantity
"""

_SERVICE_ORDERING_APPLICATION = """\
module ordering_application
    layer: APPLICATION
    version: 0.1.0
    intent: "Ordering application service: turns a product and a quantity into a priced order, orchestrating the catalog domain."
    uses: [catalog_domain.Product, catalog_domain.price_of]
    exports: [submit_order]

nerve submit_order :: APPLICATION
    kind: SERVICE
    visibility: PUBLIC
    intent: "Place an order for a quantity of a product and return the priced result."
    expects: "A Product and a positive integer quantity."
    guarantees: "Returns a dict with the sku, quantity, and total_cents; propagates ValueError for a non-positive quantity."
    forbids: none
    evaluates_at: FUNCTION_BOUNDARY
    depends_on:
        catalog_domain.price_of: {relation: CALLS, carries: "product + quantity to price", coupling: LOOSE}
    ---
    def submit_order(product: Product, quantity: int) -> dict[str, object]:
        \"\"\"Price *quantity* units of *product* and return the order line.\"\"\"
        total = price_of(product, quantity)
        return {"sku": product.sku, "quantity": quantity, "total_cents": total}
"""

_SERVICE_API_PRESENTATION = """\
module api_presentation
    layer: PRESENTATION
    version: 0.1.0
    intent: "The service's request boundary: validate an inbound order request and hand it to the ordering application service."
    uses: [catalog_domain.Product, ordering_application.submit_order]
    exports: [handle_order_request]

nerve handle_order_request :: PRESENTATION
    kind: ADAPTER
    visibility: PUBLIC
    intent: "Translate an inbound (product, quantity) request into a priced order response at the service boundary."
    expects: "A Product and a quantity that may have come from an untrusted caller."
    guarantees: "Returns the priced order dict on success, or an {error: ...} dict when the request is invalid."
    forbids: "Never let a ValueError reach its caller; an invalid request comes back as an error dict instead."
    evaluates_at: SUBSYSTEM
    depends_on:
        ordering_application.submit_order: {relation: CALLS, carries: "validated product + quantity", coupling: LOOSE}
    ---
    def handle_order_request(product: Product, quantity: int) -> dict[str, object]:
        \"\"\"Boundary handler: price the order, or report why the request was rejected.\"\"\"
        try:
            return submit_order(product, quantity)
        except ValueError as exc:
            return {"error": str(exc)}
"""

_SERVICE_CATALOG_TESTS = """\
module catalog_domain_tests
    layer: DOMAIN
    version: 0.1.0
    intent: "Tests for the catalog domain pricing rule."
    uses: [catalog_domain.Product, catalog_domain.price_of]
    exports: []

test test_price_of_multiplies_quantity :: DOMAIN
    intent: "price_of returns unit_price_cents * quantity for a valid quantity."
    tests: [catalog_domain.price_of]
    ---
    def test_price_of_multiplies_quantity() -> None:
        widget = Product(sku="W1", name="Widget", unit_price_cents=250)
        assert price_of(widget, 3) == 750
"""

_SERVICE_ORDERING_TESTS = """\
module ordering_application_tests
    layer: APPLICATION
    version: 0.1.0
    intent: "Tests for the ordering application service."
    uses: [catalog_domain.Product, ordering_application.submit_order]
    exports: []

test test_submit_order_prices_the_line :: APPLICATION
    intent: "submit_order returns the sku, quantity, and total_cents for a valid order."
    tests: [ordering_application.submit_order]
    ---
    def test_submit_order_prices_the_line() -> None:
        widget = Product(sku="W1", name="Widget", unit_price_cents=250)
        order = submit_order(widget, 2)
        assert order == {"sku": "W1", "quantity": 2, "total_cents": 500}
"""

_SERVICE_API_TESTS = """\
module api_presentation_tests
    layer: PRESENTATION
    version: 0.1.0
    intent: "Tests for the service's request boundary handler."
    uses: [catalog_domain.Product, api_presentation.handle_order_request]
    exports: []

test test_handle_order_request_prices_and_reports :: PRESENTATION
    intent: "handle_order_request prices a valid order and returns an error dict for an invalid quantity."
    tests: [api_presentation.handle_order_request]
    ---
    def test_handle_order_request_prices_and_reports() -> None:
        widget = Product(sku="W1", name="Widget", unit_price_cents=250)
        assert handle_order_request(widget, 1) == {
            "sku": "W1",
            "quantity": 1,
            "total_cents": 250,
        }
        assert "error" in handle_order_request(widget, 0)
"""

_SERVICE_APP_MAP = """\
module app_map
    layer: PRESENTATION
    version: 0.1.0
    intent: "The service's load-bearing app map: a generated public-API reference plus a three-faculty architecture guide, both drift-gated."
    exports: []

doc-ref public_api_reference
    intent: "Generated reference of every PUBLIC nerve in the service, rendered from the registry so it cannot drift from the served surface."
    format: markdown
    output: docs/public_api_reference.md
    covers: [nerve where visibility == PUBLIC]
    sections: [intent, expects, guarantees, forbids]

doc-guide architecture_map
    intent: "How this service is built, narrated around the three faculties of self-knowledge: structure, runtime state, and reasoning over the model."
    format: markdown
    output: docs/architecture_map.md
    covers: [nerve::submit_order]
    asserts: [nerve::submit_order.visibility == PUBLIC, nerve::submit_order.layer == APPLICATION]
    examples: []
    ---
    # Architecture map

    This service keeps an accurate, queryable, machine-readable model of itself. Read it through the three faculties of self-knowledge.

    ## Structure (proprioception)

    What the system is made of and how it is wired. This is a three-feature, three-layer service:

    - The catalog feature (DOMAIN) owns the product model and the pure pricing rule.
    - The ordering feature (APPLICATION) is the {{nerve::submit_order}} service; it prices an order through the catalog domain.
    - The api feature (PRESENTATION) is the request boundary; it hands a validated request to the ordering service and shapes the response.

    The dependency edges only ever point downward — PRESENTATION to APPLICATION to DOMAIN — and the layer reachability matrix enforces it: a higher layer may reach a lower one, never the reverse. The cross-feature edges are declared as qualified depends_on (CALLS) targets, so the wiring is in the IR, not just in the code.

    ## Runtime state (interoception)

    How the system behaves versus how it declared it would: declared resource profiles checked against runtime metrics. Declare resource profiles on the boundary and service nerves and this section grows teeth; until then it states the contract the service intends to hold.

    ## Reasoning over the model (metacognition)

    Reasoning about the service's own model: impact analysis, extension-point guidance, and the drift check that keeps every reference in this map true. Because this guide is registry-bound and drift-gated, a change to a covered component that is not reflected here fails the build.
"""

_SERVICE_BOOTSTRAP = '''\
"""Service bootstrap — the single handwritten entry point.

This is the one sanctioned plain-Python module in the service (the
boundary-doctrine "single handwritten bootstrap module", declared in
``[tool.s0ma].bootstrap_files``). Everything else is authored as ``.s0ma``
and emitted into the build directory; this file only *wires* the built
modules together at runtime and exposes a process entry point.

Run it after a build (``s0ma build .``)::

    python bootstrap/main.py
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from s0ma.bootstrap import bootstrap_imports


def main() -> dict[str, Any]:
    """Wire the built modules and place one demo order through the boundary."""
    build_dir = Path(__file__).resolve().parent.parent / "build"
    modules = bootstrap_imports(build_dir.as_posix())

    catalog = modules["catalog_domain"]
    api = modules["api_presentation"]

    widget = catalog.Product(sku="W1", name="Widget", unit_price_cents=250)
    response: dict[str, Any] = api.handle_order_request(widget, 3)
    print(f"order response: {response}")
    return response


if __name__ == "__main__":
    main()
'''


def _service() -> Archetype:
    return Archetype(
        name="service",
        summary=(
            "multi-feature service (DOMAIN catalog → APPLICATION ordering "
            "→ PRESENTATION api) with cross-feature depends_on edges"
        ),
        features=("catalog", "ordering", "api"),
        teaches=(
            "cross-feature depends_on edges (qualified module.declaration) "
            "and the layer reachability matrix"
        ),
        bootstrap_files=("bootstrap/main.py",),
        run_hint="Run the wired service:           python bootstrap/main.py",
        files=(
            ArchetypeFile("src/catalog/catalog_domain.s0ma", _SERVICE_CATALOG_DOMAIN),
            ArchetypeFile(
                "src/ordering/ordering_application.s0ma",
                _SERVICE_ORDERING_APPLICATION,
            ),
            ArchetypeFile(
                "src/api/api_presentation.s0ma", _SERVICE_API_PRESENTATION
            ),
            ArchetypeFile("src/app_map.s0ma", _SERVICE_APP_MAP),
            ArchetypeFile(
                "tests/catalog/catalog_domain_tests.s0ma", _SERVICE_CATALOG_TESTS
            ),
            ArchetypeFile(
                "tests/ordering/ordering_application_tests.s0ma",
                _SERVICE_ORDERING_TESTS,
            ),
            ArchetypeFile(
                "tests/api/api_presentation_tests.s0ma", _SERVICE_API_TESTS
            ),
            ArchetypeFile("bootstrap/main.py", _SERVICE_BOOTSTRAP),
        ),
    )


# ---------------------------------------------------------------------------
# library — one DOMAIN feature: slug core + thin public facade
# ---------------------------------------------------------------------------

_LIBRARY_DOMAIN = """\
module toolkit_domain
    layer: DOMAIN
    version: 0.1.0
    intent: "The library's core: pure, dependency-free slug helpers other code composes."
    requires: [re]
    exports: [slugify, is_slug]

nerve slugify :: DOMAIN
    kind: FUNCTION
    visibility: PUBLIC
    intent: "Turn an arbitrary title into a lowercase, hyphen-separated URL slug."
    expects: "Any string (may contain spaces, punctuation, or mixed case)."
    guarantees: "Returns a lowercase string of [a-z0-9-] with no leading, trailing, or repeated hyphens."
    forbids: "Never return anything but the letters a-z, the digits 0-9 and single hyphens between them."
    evaluates_at: FUNCTION_BOUNDARY
    ---
    def slugify(title: str) -> str:
        \"\"\"Return a URL-safe slug for *title*.\"\"\"
        lowered = title.strip().lower()
        collapsed = re.sub(r"[^a-z0-9]+", "-", lowered)
        return collapsed.strip("-")

nerve is_slug :: DOMAIN
    kind: FUNCTION
    visibility: PUBLIC
    intent: "Report whether a string is already a well-formed slug."
    expects: "Any string."
    guarantees: "Returns True only when the string equals its own slugify() output and is non-empty."
    forbids: "Never answer True for an empty string, or for one that slugify would change."
    evaluates_at: FUNCTION_BOUNDARY
    depends_on:
        slugify: {relation: CALLS, carries: "candidate slug to normalize", coupling: TIGHT}
    ---
    def is_slug(candidate: str) -> bool:
        \"\"\"True when *candidate* is already a normalized, non-empty slug.\"\"\"
        return bool(candidate) and slugify(candidate) == candidate
"""

_LIBRARY_API = """\
module toolkit_api
    layer: DOMAIN
    version: 0.1.0
    intent: "The library's thin public surface: the one entry point downstream callers import, composed from the domain core."
    uses: [toolkit_domain.slugify, toolkit_domain.is_slug]
    exports: [normalize_title]

nerve normalize_title :: DOMAIN
    kind: FUNCTION
    visibility: PUBLIC
    intent: "Public facade: return a clean slug for a title, leaving an already-valid slug untouched."
    expects: "Any string title."
    guarantees: "Returns the input unchanged when it is already a slug, otherwise its slugify() form."
    forbids: "Never change a title that is already a slug; it comes back exactly as given."
    evaluates_at: FUNCTION_BOUNDARY
    covered_by: ["tests/external/test_public_api.py — downstream contract suite"]
    depends_on:
        toolkit_domain.is_slug: {relation: CALLS, carries: "title to test for slug-shape", coupling: LOOSE}
        toolkit_domain.slugify: {relation: CALLS, carries: "title to normalize", coupling: LOOSE}
    ---
    def normalize_title(title: str) -> str:
        \"\"\"Return a normalized slug for *title* (idempotent on valid slugs).\"\"\"
        if is_slug(title):
            return title
        return slugify(title)
"""

_LIBRARY_TESTS = """\
module toolkit_domain_tests
    layer: DOMAIN
    version: 0.1.0
    intent: "Tests for the library's slug core."
    uses: [toolkit_domain.slugify, toolkit_domain.is_slug]
    exports: []

test test_slugify_normalizes_titles :: DOMAIN
    intent: "slugify lowercases, replaces runs of non-alphanumerics with single hyphens, and trims."
    tests: [toolkit_domain.slugify]
    ---
    def test_slugify_normalizes_titles() -> None:
        assert slugify("  Hello, World!  ") == "hello-world"
        assert slugify("Already-A-Slug") == "already-a-slug"

test test_is_slug_recognizes_normalized_input :: DOMAIN
    intent: "is_slug is True for a normalized slug and False for raw input."
    tests: [toolkit_domain.is_slug]
    ---
    def test_is_slug_recognizes_normalized_input() -> None:
        assert is_slug("hello-world") is True
        assert is_slug("Hello World") is False
        assert is_slug("") is False
"""

_LIBRARY_APP_MAP = """\
module app_map
    layer: PRESENTATION
    version: 0.1.0
    intent: "The library's load-bearing app map: a generated public-API reference plus a three-faculty architecture guide, both drift-gated."
    exports: []

doc-ref public_api_reference
    intent: "Generated reference of every PUBLIC nerve in the library, rendered from the registry so it cannot drift from the served surface."
    format: markdown
    output: docs/public_api_reference.md
    covers: [nerve where visibility == PUBLIC]
    sections: [intent, expects, guarantees, forbids]

doc-guide architecture_map
    intent: "How this library is built, narrated around the three faculties of self-knowledge: structure, runtime state, and reasoning over the model."
    format: markdown
    output: docs/architecture_map.md
    covers: [nerve::normalize_title]
    asserts: [nerve::normalize_title.visibility == PUBLIC, nerve::normalize_title.layer == DOMAIN]
    examples: []
    ---
    # Architecture map

    This library keeps an accurate, queryable, machine-readable model of itself. Read it through the three faculties of self-knowledge.

    ## Structure (proprioception)

    This is a small, export-focused library, so it is deliberately layer-light: everything lives in the DOMAIN layer (layer-first is acceptable for small libraries — promote a feature to its own directory only when it earns the separation). One feature, two modules: a slug core and a thin public surface.

    The {{nerve::normalize_title}} facade is the single entry point downstream callers import; it composes the core slug helpers. Because the public surface is intentionally thin, its release-mode test credit comes from an external downstream contract suite declared via covered_by, while the core is exercised by in-language tests.

    ## Runtime state (interoception)

    How the system behaves versus how it declared it would: declared resource profiles checked against runtime metrics. A pure library typically declares none; this section states the contract honestly rather than inventing a signal.

    ## Reasoning over the model (metacognition)

    Reasoning about the library's own model: impact analysis, extension-point guidance, and the drift check that keeps every reference in this map true. Because this guide is registry-bound and drift-gated, a change to a covered component that is not reflected here fails the build.
"""


def _library() -> Archetype:
    return Archetype(
        name="library",
        summary=(
            "layer-light export-focused package (DOMAIN slug core + thin "
            "public facade) showing exports + covered_by"
        ),
        features=("toolkit",),
        teaches="exports: and covered_by: (external pytest-suite test credit)",
        bootstrap_files=(),
        run_hint=(
            "Import the facade:               "
            'from build.toolkit_api import normalize_title'
        ),
        files=(
            ArchetypeFile("src/toolkit/toolkit_domain.s0ma", _LIBRARY_DOMAIN),
            ArchetypeFile("src/toolkit/toolkit_api.s0ma", _LIBRARY_API),
            ArchetypeFile("src/app_map.s0ma", _LIBRARY_APP_MAP),
            ArchetypeFile(
                "tests/toolkit/toolkit_domain_tests.s0ma", _LIBRARY_TESTS
            ),
        ),
    )


# ---------------------------------------------------------------------------
# cli — argparse.REMAINDER shim → PRESENTATION router → APPLICATION → DOMAIN
# ---------------------------------------------------------------------------

_CLI_GREETING_DOMAIN = """\
module greeting_domain
    layer: DOMAIN
    version: 0.1.0
    intent: "Greeting domain: the pure rule that turns a name into a greeting line."
    exports: [compose_greeting]

nerve compose_greeting :: DOMAIN
    kind: FUNCTION
    visibility: PUBLIC
    intent: "Compose a friendly greeting line for a name."
    expects: "A name string; an empty or whitespace name falls back to 'world'."
    guarantees: "Returns a non-empty 'Hello, <name>!' line."
    forbids: none
    evaluates_at: FUNCTION_BOUNDARY
    ---
    def compose_greeting(name: str) -> str:
        \"\"\"Return a greeting line for *name* (defaulting to 'world').\"\"\"
        who = name.strip() or "world"
        return f"Hello, {who}!"
"""

_CLI_GREETING_APPLICATION = """\
module greeting_application
    layer: APPLICATION
    version: 0.1.0
    intent: "Greeting application service: orchestrates the domain rule into the result the CLI prints."
    uses: [greeting_domain.compose_greeting]
    exports: [greet]

nerve greet :: APPLICATION
    kind: SERVICE
    visibility: PUBLIC
    intent: "Produce the greeting output for a name argument coming from the CLI."
    expects: "A name string (possibly empty)."
    guarantees: "Returns the greeting line the CLI should print."
    forbids: none
    evaluates_at: FUNCTION_BOUNDARY
    depends_on:
        greeting_domain.compose_greeting: {relation: CALLS, carries: "name to greet", coupling: LOOSE}
    ---
    def greet(name: str) -> str:
        \"\"\"Return the greeting line for *name*.\"\"\"
        return compose_greeting(name)
"""

_CLI_CONSOLE_PRESENTATION = """\
module console_presentation
    layer: PRESENTATION
    version: 0.1.0
    intent: "The CLI router: the presentation nerve the thin Python bootstrap shim dispatches every subcommand to."
    uses: [greeting_application.greet]
    exports: [dispatch]

nerve dispatch :: PRESENTATION
    kind: ADAPTER
    visibility: PUBLIC
    intent: "Route a parsed (subcommand, remaining-args) pair to the right application service and return the line to print."
    expects: "A subcommand string and the list of remaining CLI args (argparse.REMAINDER), already stripped of a leading '--'."
    guarantees: "Returns the output line for a known subcommand; returns a usage line for an unknown one."
    forbids: "Never raise an error for an unknown subcommand; it returns a usage line instead."
    evaluates_at: SUBSYSTEM
    depends_on:
        greeting_application.greet: {relation: CALLS, carries: "name argument from the CLI tail", coupling: LOOSE}
    ---
    def dispatch(subcommand: str, rest: list[str]) -> str:
        \"\"\"Dispatch *subcommand* with *rest* to an application service.\"\"\"
        if subcommand == "greet":
            name = rest[0] if rest else ""
            return greet(name)
        return f"unknown subcommand: {subcommand!r} (try: greet)"
"""

_CLI_GREETING_DOMAIN_TESTS = """\
module greeting_domain_tests
    layer: DOMAIN
    version: 0.1.0
    intent: "Tests for the greeting domain rule."
    uses: [greeting_domain.compose_greeting]
    exports: []

test test_compose_greeting_uses_name_or_world :: DOMAIN
    intent: "compose_greeting greets the given name, falling back to 'world' when empty."
    tests: [greeting_domain.compose_greeting]
    ---
    def test_compose_greeting_uses_name_or_world() -> None:
        assert compose_greeting("Ada") == "Hello, Ada!"
        assert compose_greeting("   ") == "Hello, world!"
"""

_CLI_GREETING_APPLICATION_TESTS = """\
module greeting_application_tests
    layer: APPLICATION
    version: 0.1.0
    intent: "Tests for the greeting application service."
    uses: [greeting_application.greet]
    exports: []

test test_greet_returns_the_greeting_line :: APPLICATION
    intent: "greet returns the composed greeting line for a name."
    tests: [greeting_application.greet]
    ---
    def test_greet_returns_the_greeting_line() -> None:
        assert greet("Ada") == "Hello, Ada!"
"""

_CLI_CONSOLE_TESTS = """\
module console_presentation_tests
    layer: PRESENTATION
    version: 0.1.0
    intent: "Tests for the CLI router."
    uses: [console_presentation.dispatch]
    exports: []

test test_dispatch_routes_greet_and_reports_unknown :: PRESENTATION
    intent: "dispatch routes the greet subcommand and reports unknown subcommands."
    tests: [console_presentation.dispatch]
    ---
    def test_dispatch_routes_greet_and_reports_unknown() -> None:
        assert dispatch("greet", ["Ada"]) == "Hello, Ada!"
        assert dispatch("greet", []) == "Hello, world!"
        assert "unknown subcommand" in dispatch("nope", [])
"""

_CLI_APP_MAP = """\
module app_map
    layer: PRESENTATION
    version: 0.1.0
    intent: "The CLI's load-bearing app map: a generated public-API reference plus a three-faculty architecture guide, both drift-gated."
    exports: []

doc-ref public_api_reference
    intent: "Generated reference of every PUBLIC nerve in the CLI, rendered from the registry so it cannot drift from the served surface."
    format: markdown
    output: docs/public_api_reference.md
    covers: [nerve where visibility == PUBLIC]
    sections: [intent, expects, guarantees, forbids]

doc-guide architecture_map
    intent: "How this CLI is built, narrated around the three faculties of self-knowledge: structure, runtime state, and reasoning over the model."
    format: markdown
    output: docs/architecture_map.md
    covers: [nerve::dispatch]
    asserts: [nerve::dispatch.visibility == PUBLIC, nerve::dispatch.layer == PRESENTATION]
    examples: []
    ---
    # Architecture map

    This CLI keeps an accurate, queryable, machine-readable model of itself. Read it through the three faculties of self-knowledge.

    ## Structure (proprioception)

    What the system is made of and how it is wired. A thin Python bootstrap shim (bootstrap/cli.py — the one sanctioned handwritten file, declared in tool.s0ma.bootstrap_files) parses argv with argparse.REMAINDER and hands the subcommand to the {{nerve::dispatch}} router. The router (PRESENTATION) calls the greeting application service, which calls the greeting domain rule.

    The layers point only downward — PRESENTATION to APPLICATION to DOMAIN — and the layer reachability matrix enforces it. The bootstrap shim is the boundary: it is the single place plain Python is allowed, and it does nothing but parse and dispatch.

    ## Runtime state (interoception)

    How the system behaves versus how it declared it would: declared resource profiles checked against runtime metrics. Declare resource profiles on the router and services and this section grows teeth; until then it states the contract the CLI intends to hold.

    ## Reasoning over the model (metacognition)

    Reasoning about the CLI's own model: impact analysis, extension-point guidance, and the drift check that keeps every reference in this map true. Because this guide is registry-bound and drift-gated, a change to a covered component that is not reflected here fails the build.
"""

_CLI_BOOTSTRAP = '''\
"""CLI bootstrap shim — the single handwritten entry point.

This is the one sanctioned plain-Python module in the project (the
boundary-doctrine "single handwritten bootstrap module", declared in
``[tool.s0ma].bootstrap_files``). It does the *only* thing a bootstrap is
allowed to do: parse the process argv and hand off to a PRESENTATION nerve.
All behaviour lives in ``.s0ma`` modules under ``src/``.

The handoff uses the canonical ``argparse.REMAINDER`` pattern (patterns
guide / quick reference): one positional ``subcommand`` plus a REMAINDER
list that captures every following token verbatim — including a literal
``--`` separator, which ``REMAINDER`` does *not* strip, so the shim strips
it before passing ``rest`` to the router.

Run it after a build (``s0ma build .``)::

    python bootstrap/cli.py greet Ada
    python bootstrap/cli.py greet -- Ada
"""

from __future__ import annotations

import argparse
from pathlib import Path

from s0ma.bootstrap import bootstrap_imports


def main() -> str:
    """Parse argv and dispatch the subcommand to the presentation router."""
    parser = argparse.ArgumentParser(prog="cli")
    parser.add_argument("subcommand", help="the subcommand to run (e.g. greet)")
    parser.add_argument(
        "rest",
        nargs=argparse.REMAINDER,
        help="arguments forwarded verbatim to the subcommand",
    )
    args = parser.parse_args()

    # REMAINDER captures a literal '--' too; strip a single leading one so
    # the downstream router sees only real arguments.
    rest = args.rest
    if rest and rest[0] == "--":
        rest = rest[1:]

    build_dir = Path(__file__).resolve().parent.parent / "build"
    modules = bootstrap_imports(build_dir.as_posix())

    line: str = modules["console_presentation"].dispatch(args.subcommand, rest)
    print(line)
    return line


if __name__ == "__main__":
    main()
'''


def _cli() -> Archetype:
    return Archetype(
        name="cli",
        summary=(
            "thin argparse.REMAINDER bootstrap shim → PRESENTATION router "
            "→ APPLICATION → DOMAIN core"
        ),
        features=("greeting", "console"),
        teaches=(
            "the argparse.REMAINDER thin-Python bootstrap → PRESENTATION "
            "nerve handoff"
        ),
        bootstrap_files=("bootstrap/cli.py",),
        run_hint="Run the CLI:                     python bootstrap/cli.py greet Ada",
        files=(
            ArchetypeFile(
                "src/greeting/greeting_domain.s0ma", _CLI_GREETING_DOMAIN
            ),
            ArchetypeFile(
                "src/greeting/greeting_application.s0ma",
                _CLI_GREETING_APPLICATION,
            ),
            ArchetypeFile(
                "src/console/console_presentation.s0ma",
                _CLI_CONSOLE_PRESENTATION,
            ),
            ArchetypeFile("src/app_map.s0ma", _CLI_APP_MAP),
            ArchetypeFile(
                "tests/greeting/greeting_domain_tests.s0ma",
                _CLI_GREETING_DOMAIN_TESTS,
            ),
            ArchetypeFile(
                "tests/greeting/greeting_application_tests.s0ma",
                _CLI_GREETING_APPLICATION_TESTS,
            ),
            ArchetypeFile(
                "tests/console/console_presentation_tests.s0ma",
                _CLI_CONSOLE_TESTS,
            ),
            ArchetypeFile("bootstrap/cli.py", _CLI_BOOTSTRAP),
        ),
    )


# ---------------------------------------------------------------------------
# pipeline — INFRASTRUCTURE player → DOMAIN music → APPLICATION coach
# → PRESENTATION page, one module per layer, written for a first-time reader
# ---------------------------------------------------------------------------

_PIPELINE_PLAYER = """\
module player
    layer: INFRASTRUCTURE
    version: 0.1.0
    intent: "This file finds out what is playing right now."
    uses: [music.Track]
    exports: [read_now_playing]

nerve read_now_playing :: INFRASTRUCTURE
    kind: ADAPTER
    visibility: PUBLIC
    intent: "Tells the app which song is playing right now."
    expects: "A turn number, which picks one of the built-in sample songs."
    guarantees: "Gives back one of four built-in sample songs, and the same turn number always gives the same song."
    forbids: "Never contacts a music player or a music service; the four sample songs are built into this file."
    evaluates_at: FUNCTION_BOUNDARY
    ---
    def read_now_playing(turn: int = 0) -> Track:
        \"\"\"Return the built-in sample song for *turn*.\"\"\"
        samples = (
            Track(title="Morning Walk", artist="The Example Quartet",
                  beats_per_minute=76, loudness=0.3, major_key=True),
            Track(title="Night Drive", artist="Practice Room",
                  beats_per_minute=128, loudness=0.8, major_key=False),
            Track(title="Market Day", artist="Demo Brass Band",
                  beats_per_minute=118, loudness=0.7, major_key=True),
            Track(title="Rain on Glass", artist="Test Pattern",
                  beats_per_minute=64, loudness=0.2, major_key=False),
        )
        return samples[turn % len(samples)]
"""

_PIPELINE_MUSIC = """\
module music
    layer: DOMAIN
    version: 0.1.0
    intent: "This file holds what the app knows about music: a song, how it sounds, and the mood it settles on."
    requires: [dataclasses:dataclass]
    exports: [Track, Features, Mood, measure_features, settle_mood]

cell Track :: DOMAIN
    kind: MODEL
    visibility: PUBLIC
    intent: "A song that is playing: its title, who made it, how fast and how loud it is, and whether it is in a major key."
    schema: "title: str, artist: str, beats_per_minute: int, loudness: float, major_key: bool"
    invariants: "Loudness runs from 0, silent, to 1, as loud as the song gets."
    ---
    @dataclass(frozen=True)
    class Track:
        title: str
        artist: str
        beats_per_minute: int
        loudness: float
        major_key: bool

cell Features :: DOMAIN
    kind: MODEL
    visibility: PUBLIC
    intent: "How a song sounds, as three scores: how fast it feels, how much energy it has, and how bright it sounds."
    schema: "pace: float, energy: float, brightness: float"
    invariants: "Each score runs from 0 to 1."
    ---
    @dataclass(frozen=True)
    class Features:
        pace: float
        energy: float
        brightness: float

cell Mood :: DOMAIN
    kind: MODEL
    visibility: PUBLIC
    intent: "The mood a song puts across, as one word and a short plain description."
    schema: "name: str, description: str"
    invariants: "The name is one of lively, tense, calm, or low."
    ---
    @dataclass(frozen=True)
    class Mood:
        name: str
        description: str

nerve measure_features :: DOMAIN
    kind: FUNCTION
    visibility: PUBLIC
    intent: "Reads the facts about a song and scores how it sounds."
    expects: "A song."
    guarantees: "Gives back a pace, an energy, and a brightness score, each from 0 to 1."
    forbids: "Never changes the song it is given; it only reads it."
    evaluates_at: FUNCTION_BOUNDARY
    ---
    def measure_features(track: Track) -> Features:
        \"\"\"Score how *track* sounds, each score from 0 to 1.\"\"\"
        pace = min(1.0, max(0.0, (track.beats_per_minute - 60) / 80))
        energy = (pace + track.loudness) / 2
        brightness = 0.8 if track.major_key else 0.2
        return Features(pace=pace, energy=energy, brightness=brightness)

nerve settle_mood :: DOMAIN
    kind: FUNCTION
    visibility: PUBLIC
    intent: "Decides which mood a song puts across, from how it sounds."
    expects: "The scores for how a song sounds."
    guarantees: "Gives back exactly one of four moods: lively, tense, calm, or low."
    forbids: "Never picks a mood outside those four."
    evaluates_at: FUNCTION_BOUNDARY
    ---
    def settle_mood(features: Features) -> Mood:
        \"\"\"Settle on one of four moods from *features*.\"\"\"
        energetic = features.energy >= 0.5
        bright = features.brightness >= 0.5
        if energetic and bright:
            return Mood(name="lively", description="full of energy and bright")
        if energetic:
            return Mood(name="tense", description="full of energy and dark")
        if bright:
            return Mood(name="calm", description="quiet and bright")
        return Mood(name="low", description="quiet and dark")
"""

_PIPELINE_COACH = """\
module coach
    layer: APPLICATION
    version: 0.1.0
    intent: "This file turns a mood into a small suggestion and keeps an eye on how steady the mood is."
    uses: [music.Mood]
    requires: [dataclasses:dataclass]
    exports: [Nudge, choose_nudge, watch_swings]

cell Nudge :: APPLICATION
    kind: MODEL
    visibility: PUBLIC
    intent: "A small suggestion for the listener, and the mood it was chosen for."
    schema: "mood: str, message: str"
    invariants: "The message is one short sentence."
    ---
    @dataclass(frozen=True)
    class Nudge:
        mood: str
        message: str

nerve choose_nudge :: APPLICATION
    kind: FUNCTION
    visibility: PUBLIC
    intent: "Picks a small suggestion that fits the mood."
    expects: "A mood."
    guarantees: "Gives back one suggestion from a short written list, one for each of the four moods."
    forbids: "Never makes up a suggestion; every message comes from the written list in this file."
    evaluates_at: FUNCTION_BOUNDARY
    ---
    def choose_nudge(mood: Mood) -> Nudge:
        \"\"\"Pick the suggestion written for *mood*.\"\"\"
        messages = {
            "lively": "Good moment to start the hardest thing on your list.",
            "tense": "Take three slow breaths before the next thing.",
            "calm": "Pick one thing and give it your full attention.",
            "low": "Stand up and stretch for a minute.",
        }
        message = messages.get(mood.name, messages["calm"])
        return Nudge(mood=mood.name, message=message)

ganglion watch_swings :: APPLICATION
    visibility: PUBLIC
    intent: "Watches the moods the app settles on and notices when they keep flipping back and forth."
    observes: [settle_mood]
    scope: SUBSYSTEM
    priors: "The mood should stay put or move on, not flip back to the mood it just left."
    on_anomaly: "Reports how many times the mood flipped back, so a person can look at the songs."
    forbids: "Never changes a mood; it only counts what it sees."
    ---
    def watch_swings(signals: list[Mood]) -> dict[str, object]:
        \"\"\"Count how often the mood flips back to the one before it.\"\"\"
        names = [mood.name for mood in signals]
        flips = sum(
            1
            for before, now, after in zip(names, names[1:], names[2:])
            if before == after and before != now
        )
        return {"flips": flips, "steady": flips == 0}
"""

_PIPELINE_PAGE = """\
module page
    layer: PRESENTATION
    version: 0.1.0
    intent: "This file shows the suggestion to the listener as a small web page."
    uses: [music.Track, music.measure_features, music.settle_mood, coach.choose_nudge, coach.Nudge]
    requires: [html]
    exports: [PAGE_HTML, show_page, song_to_page]

cell PAGE_HTML :: PRESENTATION
    kind: CONSTANT
    visibility: PUBLIC
    intent: "The outline of the page, with gaps where the mood and the suggestion go."
    schema: "The text of a web page with two gaps, {mood} and {message}."
    ---
    PAGE_HTML = (
        "<!doctype html>\\n"
        "<html><head><meta charset=\\"utf-8\\"><title>Now playing</title></head>\\n"
        "<body>\\n"
        "<h1>The mood is {mood}</h1>\\n"
        "<p>{message}</p>\\n"
        "</body></html>\\n"
    )

nerve show_page :: PRESENTATION
    kind: FUNCTION
    visibility: PUBLIC
    intent: "Fills the page outline with the mood and the suggestion."
    expects: "A suggestion and the mood it was chosen for."
    guarantees: "Gives back the full text of the page, with the mood and the suggestion in it."
    forbids: "Never puts text on the page unescaped, so a song title or message cannot break the page."
    evaluates_at: FUNCTION_BOUNDARY
    ---
    def show_page(nudge: Nudge) -> str:
        \"\"\"Return the page text for *nudge*.\"\"\"
        return PAGE_HTML.format(
            mood=html.escape(nudge.mood),
            message=html.escape(nudge.message),
        )

nerve song_to_page :: PRESENTATION
    kind: ORCHESTRATOR
    visibility: PUBLIC
    intent: "Takes a song all the way to a finished page: measure it, settle the mood, choose a suggestion, and show it."
    expects: "The song that is playing."
    guarantees: "Gives back the full text of the page for that song."
    forbids: "Never opens a network connection or starts a web server; it hands back the page as text."
    evaluates_at: SUBSYSTEM
    depends_on:
        music.measure_features: {relation: CALLS, carries: "the song, to score how it sounds", coupling: LOOSE}
        music.settle_mood: {relation: CALLS, carries: "the scores, to settle on a mood", coupling: LOOSE}
        coach.choose_nudge: {relation: CALLS, carries: "the mood, to pick a suggestion", coupling: LOOSE}
        show_page: {relation: CALLS, carries: "the suggestion, to fill in the page", coupling: TIGHT}
    ---
    def song_to_page(track: Track) -> str:
        \"\"\"Return the finished page for *track*.\"\"\"
        mood = settle_mood(measure_features(track))
        return show_page(choose_nudge(mood))
"""

_PIPELINE_PLAYER_TESTS = """\
module player_tests
    layer: INFRASTRUCTURE
    version: 0.1.0
    intent: "Tests for finding out what is playing."
    uses: [player.read_now_playing]
    exports: []

test test_read_now_playing_is_repeatable :: INFRASTRUCTURE
    intent: "The same turn number always gives the same built-in song, and the songs take turns."
    tests: [player.read_now_playing]
    ---
    def test_read_now_playing_is_repeatable() -> None:
        assert read_now_playing(0) == read_now_playing(0)
        assert read_now_playing(0) == read_now_playing(4)
        assert read_now_playing(0).title == "Morning Walk"
        assert read_now_playing(1).title == "Night Drive"
"""

_PIPELINE_MUSIC_TESTS = """\
module music_tests
    layer: DOMAIN
    version: 0.1.0
    intent: "Tests for scoring a song and settling on its mood."
    uses: [music.Track, music.Features, music.measure_features, music.settle_mood]
    exports: []

test test_measure_features_scores_a_song :: DOMAIN
    intent: "A fast, loud song in a major key scores high on every count."
    tests: [music.measure_features]
    ---
    def test_measure_features_scores_a_song() -> None:
        song = Track(title="t", artist="a", beats_per_minute=140,
                     loudness=1.0, major_key=True)
        assert measure_features(song) == Features(
            pace=1.0, energy=1.0, brightness=0.8
        )

test test_settle_mood_picks_one_of_four :: DOMAIN
    intent: "Energy and brightness together decide which of the four moods a song gets."
    tests: [music.settle_mood]
    ---
    def test_settle_mood_picks_one_of_four() -> None:
        assert settle_mood(Features(pace=1.0, energy=0.9, brightness=0.8)).name == "lively"
        assert settle_mood(Features(pace=1.0, energy=0.9, brightness=0.2)).name == "tense"
        assert settle_mood(Features(pace=0.1, energy=0.2, brightness=0.8)).name == "calm"
        assert settle_mood(Features(pace=0.1, energy=0.2, brightness=0.2)).name == "low"
"""

_PIPELINE_COACH_TESTS = """\
module coach_tests
    layer: APPLICATION
    version: 0.1.0
    intent: "Tests for choosing a suggestion and for watching the mood."
    uses: [music.Mood, coach.choose_nudge, coach.watch_swings]
    exports: []

test test_choose_nudge_fits_the_mood :: APPLICATION
    intent: "Each mood gets its own suggestion from the written list."
    tests: [coach.choose_nudge]
    ---
    def test_choose_nudge_fits_the_mood() -> None:
        nudge = choose_nudge(Mood(name="low", description="quiet and dark"))
        assert nudge.mood == "low"
        assert nudge.message == "Stand up and stretch for a minute."

test test_watch_swings_counts_flips :: APPLICATION
    intent: "The watcher counts a mood that flips back to the one it just left, and stays quiet when the mood moves on."
    tests: [coach.watch_swings]
    ---
    def test_watch_swings_counts_flips() -> None:
        calm = Mood(name="calm", description="quiet and bright")
        tense = Mood(name="tense", description="full of energy and dark")
        low = Mood(name="low", description="quiet and dark")
        assert watch_swings([calm, tense, calm, tense]) == {"flips": 2, "steady": False}
        assert watch_swings([calm, calm, tense, low]) == {"flips": 0, "steady": True}
"""

_PIPELINE_PAGE_TESTS = """\
module page_tests
    layer: PRESENTATION
    version: 0.1.0
    intent: "Tests for showing the page."
    uses: [music.Track, coach.Nudge, page.show_page, page.song_to_page]
    exports: []

test test_show_page_escapes_text :: PRESENTATION
    intent: "The page shows the mood and the suggestion, with any markup in them made harmless."
    tests: [page.show_page]
    ---
    def test_show_page_escapes_text() -> None:
        text = show_page(Nudge(mood="calm", message="Rest <now>."))
        assert "The mood is calm" in text
        assert "Rest &lt;now&gt;." in text

test test_song_to_page_runs_the_whole_way :: PRESENTATION
    intent: "A quiet, bright song comes out as a calm page with the calm suggestion."
    tests: [page.song_to_page]
    ---
    def test_song_to_page_runs_the_whole_way() -> None:
        song = Track(title="t", artist="a", beats_per_minute=70,
                     loudness=0.2, major_key=True)
        text = song_to_page(song)
        assert "The mood is calm" in text
        assert "Pick one thing and give it your full attention." in text
"""

_PIPELINE_APP_MAP = """\
module app_map
    layer: PRESENTATION
    version: 0.1.0
    intent: "This file is the map of the app: a list of its public parts and a short tour of how they fit together."
    exports: []

doc-ref public_api_reference
    intent: "A list of every public working part of the app, written from the app itself so it always matches."
    format: markdown
    output: docs/public_api_reference.md
    covers: [nerve where visibility == PUBLIC]
    sections: [intent, expects, guarantees, forbids]

doc-guide architecture_map
    intent: "A short tour of the app: what it is made of, how it behaves, and how it checks itself."
    format: markdown
    output: docs/architecture_map.md
    covers: [nerve::song_to_page]
    asserts: [nerve::song_to_page.visibility == PUBLIC, nerve::song_to_page.layer == PRESENTATION]
    examples: []
    ---
    # Architecture map

    This app reads what is playing, measures the song, settles on a mood, chooses a nudge, and shows it. It keeps an accurate model of itself, and this map is read from that model.

    ## Structure

    The app is four files, one for each layer:

    - The player file (INFRASTRUCTURE) finds out what is playing. It uses four built-in sample songs and contacts nothing outside the app.
    - The music file (DOMAIN) scores how a song sounds and settles on one of four moods.
    - The coach file (APPLICATION) picks a small suggestion for the mood and watches whether the mood keeps flipping back and forth.
    - The page file (PRESENTATION) fills a small web page with the mood and the suggestion. {{nerve::song_to_page}} runs the whole way from a song to the finished page.

    A file may only reach toward the middle of the app. The music file is the middle and uses no other file. The coach file uses the music file. The player file and the page file are the two edges: the player uses the music file, the page uses the coach and music files, and the two edges never use each other. The build refuses anything else. The bootstrap file, the one plain Python file in the project, hands the song from the player to the page.

    ## Runtime state

    How the app behaves compared with what it said it would do. The coach file's watcher counts how often the mood flips back to the mood it just left.

    ## Reasoning over the model

    The app can answer questions about its own parts: what each one is for, what it promises, and what depends on it. This map is checked on every build, so a change to a part it names that is not reflected here fails the build.
"""

_PIPELINE_BOOTSTRAP = '''\
"""Pipeline bootstrap: the single handwritten entry point.

This is the one sanctioned plain-Python module in the project (declared in
``[tool.s0ma].bootstrap_files``). Everything else is authored as ``.s0ma``
and emitted into the build directory; this file only hands the song the
player reads to the page, and prints the page.

Run it after a build (``s0ma build .``)::

    python bootstrap/main.py        # the first built-in song
    python bootstrap/main.py 1      # the second one
"""

from __future__ import annotations

import sys
from pathlib import Path

from s0ma.bootstrap import bootstrap_imports


def main(turn: int = 0) -> str:
    """Read the song for *turn*, build its page, and print it."""
    build_dir = Path(__file__).resolve().parent.parent / "build"
    modules = bootstrap_imports(build_dir.as_posix())

    track = modules["player"].read_now_playing(turn)
    text: str = modules["page"].song_to_page(track)
    print(f"now playing: {track.title} by {track.artist}")
    print(text, end="")
    return text


if __name__ == "__main__":
    main(int(sys.argv[1]) if len(sys.argv) > 1 else 0)
'''


def _pipeline() -> Archetype:
    return Archetype(
        name="pipeline",
        summary=(
            "four-layer pipeline, one module per layer (INFRASTRUCTURE player "
            "→ DOMAIN music → APPLICATION coach → PRESENTATION page) with "
            "declared text written for a first-time reader"
        ),
        features=("player", "music", "coach", "page"),
        teaches=(
            "one module per layer, an INFRASTRUCTURE source handed to a "
            "PRESENTATION page by the bootstrap, and a ganglion watching a nerve"
        ),
        bootstrap_files=("bootstrap/main.py",),
        run_hint="Show the page for a song:        python bootstrap/main.py 1",
        files=(
            ArchetypeFile("src/player/player.s0ma", _PIPELINE_PLAYER),
            ArchetypeFile("src/music/music.s0ma", _PIPELINE_MUSIC),
            ArchetypeFile("src/coach/coach.s0ma", _PIPELINE_COACH),
            ArchetypeFile("src/page/page.s0ma", _PIPELINE_PAGE),
            ArchetypeFile("src/app_map.s0ma", _PIPELINE_APP_MAP),
            ArchetypeFile("tests/player/player_tests.s0ma", _PIPELINE_PLAYER_TESTS),
            ArchetypeFile("tests/music/music_tests.s0ma", _PIPELINE_MUSIC_TESTS),
            ArchetypeFile("tests/coach/coach_tests.s0ma", _PIPELINE_COACH_TESTS),
            ArchetypeFile("tests/page/page_tests.s0ma", _PIPELINE_PAGE_TESTS),
            ArchetypeFile("bootstrap/main.py", _PIPELINE_BOOTSTRAP),
        ),
    )


# ---------------------------------------------------------------------------
# agent: a small support-inbox agent, declared as five ordered steps
# ---------------------------------------------------------------------------
#
# Each step's files go on top of the steps before it, and every prefix is a
# clean project. Step 4 replaces the bootstrap step 1 wrote. The model is an
# abstract ADAPTER port (model.ReplyModel) with a scripted stand-in, so the
# project runs with no account, no key, and no network. A class-bodied
# ADAPTER builds to a factory that returns a dict, which is why the decider
# calls model["choose"]; the decider's parameter is typed with the port so
# the port's uses: line is a real use.

_AGENT_INBOX = '''\
module inbox
    layer: DOMAIN
    version: 0.1.0
    intent: "This file is what the agent hears: a customer message, and the order number in it if there is one."
    requires: [dataclasses:dataclass, re]
    exports: [Message, read_message]

cell Message :: DOMAIN
    kind: MODEL
    visibility: PUBLIC
    intent: "One message from a customer: the words they wrote and the order number they gave, if any."
    schema: "text: str, order_number: str | None"
    invariants: "The text is never empty."
    ---
    @dataclass(frozen=True)
    class Message:
        text: str
        order_number: str | None

nerve read_message :: DOMAIN
    kind: FUNCTION
    visibility: PUBLIC
    intent: "Reads what a customer wrote and picks out the order number."
    expects: "The words a customer wrote."
    guarantees: "Gives back the message with extra spaces removed, and the order number when it has the form A followed by four digits."
    forbids: "Never changes what the customer said; it only tidies the spaces."
    evaluates_at: FUNCTION_BOUNDARY
    ---
    def read_message(text: str) -> Message:
        """Tidy *text* and pick out an order number like A1234."""
        tidy = " ".join(text.split()) or "(empty)"
        found = re.search(r"\\bA\\d{4}\\b", tidy)
        return Message(text=tidy, order_number=found.group(0) if found else None)
'''

_AGENT_INBOX_TESTS = """\
module inbox_tests
    layer: DOMAIN
    version: 0.1.0
    intent: "Tests for reading a customer message."
    uses: [inbox.read_message]
    exports: []

test test_read_message_finds_the_order :: DOMAIN
    intent: "A message with an order number gives that number back, and one without gives none."
    tests: [inbox.read_message]
    ---
    def test_read_message_finds_the_order() -> None:
        assert read_message("Where is  A1234?").order_number == "A1234"
        assert read_message("Hello").order_number is None
"""

_AGENT_APP_MAP = """\
module app_map
    layer: PRESENTATION
    version: 0.1.0
    intent: "This file is the map of the agent: a list of its public parts, written from the agent itself."
    exports: []

doc-ref public_api_reference
    intent: "A list of every public working part of the agent, written from the agent itself so it always matches."
    format: markdown
    output: docs/public_api_reference.md
    covers: [nerve where visibility == PUBLIC]
    sections: [intent, expects, guarantees, forbids]
"""

_AGENT_BOOTSTRAP_HEARS = '''\
"""Support inbox bootstrap: the one handwritten entry point."""

from __future__ import annotations

import sys
from pathlib import Path

from s0ma.bootstrap import bootstrap_imports


def main(text: str = "Where is my order A1234?") -> str:
    build_dir = Path(__file__).resolve().parent.parent / "build"
    modules = bootstrap_imports(build_dir.as_posix())
    message = modules["inbox"].read_message(text)
    order = message.order_number or "none"
    line = f"heard: {message.text} (order number: {order})"
    print(line)
    return line


if __name__ == "__main__":
    main(" ".join(sys.argv[1:]) or "Where is my order A1234?")
'''

_AGENT_RULES = '''\
module rules
    layer: DOMAIN
    version: 0.1.0
    intent: "This file holds what the agent must do and what it must never do."
    requires: [dataclasses:dataclass]
    exports: [Reply, keep_the_rules]

cell Reply :: DOMAIN
    kind: MODEL
    visibility: PUBLIC
    intent: "What the agent does with one message: answer it, or hand it to a person, and the words it sends."
    schema: "action: str, text: str"
    invariants: "The action is answer or hand_off."
    ---
    @dataclass(frozen=True)
    class Reply:
        action: str
        text: str

nerve keep_the_rules :: DOMAIN
    kind: FUNCTION
    visibility: PUBLIC
    intent: "Checks a reply against the rules before it goes out."
    expects: "A reply the agent wants to send."
    guarantees: "Gives back the reply unchanged when it keeps the rules, and a hand-off to a person when it does not."
    forbids: "Never lets out a reply that promises a refund."
    evaluates_at: FUNCTION_BOUNDARY
    ---
    def keep_the_rules(reply: Reply) -> Reply:
        """Hand off any reply that promises a refund."""
        if "refund" in reply.text.lower():
            return Reply(action="hand_off", text="A person will look at this and write back.")
        return reply
'''

_AGENT_RULES_TESTS = """\
module rules_tests
    layer: DOMAIN
    version: 0.1.0
    intent: "Tests for the rules the agent keeps."
    uses: [rules.Reply, rules.keep_the_rules]
    exports: []

test test_keep_the_rules_stops_a_refund_promise :: DOMAIN
    intent: "A reply that promises a refund becomes a hand-off, and any other reply goes out as it was."
    tests: [rules.keep_the_rules]
    ---
    def test_keep_the_rules_stops_a_refund_promise() -> None:
        assert keep_the_rules(Reply(action="answer", text="You will get a refund.")).action == "hand_off"
        ok = Reply(action="answer", text="It ships today.")
        assert keep_the_rules(ok) == ok
"""

_AGENT_TOOLS = '''\
module tools
    layer: INFRASTRUCTURE
    version: 0.1.0
    intent: "This file holds the agent's two tools: a short list of common answers, and a way to look up an order."
    exports: [answer_from_faq, look_up_order]

nerve answer_from_faq :: INFRASTRUCTURE
    kind: ADAPTER
    visibility: PUBLIC
    intent: "Finds the written answer to a common question."
    expects: "The words of a customer message."
    guarantees: "Gives back the written answer whose topic word is in the message, or nothing when none is."
    forbids: "Never makes up an answer; every answer comes from the list in this file."
    evaluates_at: FUNCTION_BOUNDARY
    ---
    def answer_from_faq(text: str) -> str | None:
        """Return the written answer for the first topic word found in *text*."""
        answers = {
            "hours": "We answer messages from 9 to 5, Monday to Friday.",
            "shipping": "Orders ship within two working days.",
            "address": "You can change the address until the order ships.",
        }
        lowered = text.lower()
        for topic, answer in answers.items():
            if topic in lowered:
                return answer
        return None

nerve look_up_order :: INFRASTRUCTURE
    kind: ADAPTER
    visibility: PUBLIC
    intent: "Looks up where an order is."
    expects: "An order number."
    guarantees: "Gives back the order's status from a short built-in list, or nothing for a number it does not know."
    forbids: "Never contacts a shop or a database; the orders are built into this file."
    evaluates_at: FUNCTION_BOUNDARY
    ---
    def look_up_order(order_number: str) -> str | None:
        """Return the built-in status for *order_number*."""
        orders = {"A1234": "shipped on Monday", "A5678": "waiting to ship"}
        return orders.get(order_number)
'''

_AGENT_TOOLS_TESTS = """\
module tools_tests
    layer: INFRASTRUCTURE
    version: 0.1.0
    intent: "Tests for the agent's tools."
    uses: [tools.answer_from_faq, tools.look_up_order]
    exports: []

test test_tools_answer_from_their_lists :: INFRASTRUCTURE
    intent: "Each tool answers from its own list and gives back nothing for what it does not know."
    tests: [tools.answer_from_faq, tools.look_up_order]
    ---
    def test_tools_answer_from_their_lists() -> None:
        assert answer_from_faq("What are your hours?") is not None
        assert answer_from_faq("Hello") is None
        assert look_up_order("A1234") == "shipped on Monday"
        assert look_up_order("A0000") is None
"""

_AGENT_MODEL = """\
module model
    layer: DOMAIN
    version: 0.1.0
    intent: "This file is the port the agent's model plugs into, so a real model can replace the stand-in."
    exports: [ReplyModel]

nerve ReplyModel :: DOMAIN
    kind: ADAPTER
    visibility: PUBLIC
    intent: "The port for the model that picks what to do with a message."
    expects: "A model that has a choose method."
    guarantees: "A call to choose goes to whichever model the bootstrap plugged in."
    forbids: none
    evaluates_at: FUNCTION_BOUNDARY
    abstract: true
    interface: [choose]
    ---
"""

_AGENT_SCRIPTED_MODEL = """\
module scripted_model
    layer: INFRASTRUCTURE
    version: 0.1.0
    intent: "This file is a scripted stand-in for the model, so the agent runs with no account, no key, and no network."
    uses: [model.ReplyModel, inbox.Message]
    exports: [ScriptedModel]

nerve ScriptedModel :: INFRASTRUCTURE
    kind: ADAPTER
    visibility: PUBLIC
    intent: "Picks what to do with a message by fixed rules, standing in for a real model."
    expects: "A customer message."
    guarantees: "Picks order when the message has an order number, faq when it asks a common question, and person otherwise. The same message always gets the same pick."
    forbids: "Never contacts a model service; the rules are written in this file."
    evaluates_at: SUBSYSTEM
    abstract: false
    interface: none
    depends_on:
        ReplyModel: {relation: CONSTRUCTS, carries: "a scripted model behind the port", coupling: TIGHT}
    ---
    class ScriptedModel:
        def choose(self, message: Message) -> str:
            if message.order_number:
                return "order"
            if any(word in message.text.lower() for word in ("hours", "shipping", "address")):
                return "faq"
            return "person"
"""

_AGENT_TRIAGE = '''\
module triage
    layer: APPLICATION
    version: 0.1.0
    intent: "This file is how the agent decides: answer from the list, look up the order, or hand off to a person."
    uses: [inbox.Message, rules.Reply, rules.keep_the_rules, model.ReplyModel]
    requires: [collections.abc:Callable]
    exports: [decide]

nerve decide :: APPLICATION
    kind: ORCHESTRATOR
    visibility: PUBLIC
    intent: "Decides what to do with one message and writes the reply, then checks it against the rules."
    expects: "A message, the model plugged into the port, and the two tools."
    guarantees: "Gives back one reply that has passed the rules: an answer from the list, the order's status, or a hand-off to a person."
    forbids: "Never sends a reply the rules have not checked."
    evaluates_at: SUBSYSTEM
    depends_on:
        rules.keep_the_rules: {relation: CALLS, carries: "the reply, to check it against the rules", coupling: TIGHT}
    ---
    def decide(
        message: Message,
        model: ReplyModel,
        faq: Callable[[str], str | None],
        orders: Callable[[str], str | None],
    ) -> Reply:
        """Pick an action with *model*, use a tool, and check the reply."""
        choice = model["choose"](message)
        text = None
        if choice == "faq":
            text = faq(message.text)
        elif choice == "order" and message.order_number:
            status = orders(message.order_number)
            if status:
                text = f"Order {message.order_number} is {status}."
        if text is None:
            return keep_the_rules(Reply(action="hand_off", text="A person will look at this and write back."))
        return keep_the_rules(Reply(action="answer", text=text))
'''

_AGENT_SCRIPTED_MODEL_TESTS = """\
module scripted_model_tests
    layer: INFRASTRUCTURE
    version: 0.1.0
    intent: "Tests for the scripted stand-in model."
    uses: [inbox.read_message, scripted_model.ScriptedModel]
    exports: []

test test_scripted_model_picks_by_its_rules :: INFRASTRUCTURE
    intent: "The stand-in picks order, faq, or person by its written rules, and every pick is one the port allows."
    tests: [model.ReplyModel, scripted_model.ScriptedModel]
    ---
    def test_scripted_model_picks_by_its_rules() -> None:
        model = ScriptedModel()
        assert model["choose"](read_message("Where is A1234?")) == "order"
        assert model["choose"](read_message("What are your hours?")) == "faq"
        assert model["choose"](read_message("I am upset")) == "person"
"""

_AGENT_TRIAGE_TESTS = """\
module triage_tests
    layer: APPLICATION
    version: 0.1.0
    intent: "Tests for how the agent decides."
    uses: [inbox.read_message, triage.decide]
    exports: []

test test_decide_picks_the_right_path :: APPLICATION
    intent: "An order question gets the order's status, a common question gets the written answer, and anything else goes to a person."
    tests: [triage.decide]
    ---
    def test_decide_picks_the_right_path() -> None:
        def picks(pick: str) -> dict[str, object]:
            return {"choose": lambda message: pick}

        def faq(text: str) -> str | None:
            return "We are open 9 to 5."

        def orders(number: str) -> str | None:
            return "shipped"

        message = read_message("Where is A1234?")
        assert decide(message, picks("order"), faq, orders).text == "Order A1234 is shipped."
        assert decide(message, picks("faq"), faq, orders).text == "We are open 9 to 5."
        assert decide(message, picks("person"), faq, orders).action == "hand_off"
"""

_AGENT_BOOTSTRAP_DECIDES = '''\
"""Support inbox bootstrap: the one handwritten entry point.

It plugs the scripted stand-in model and the two tools into the agent.
A real model replaces the stand-in here and nowhere else.
"""

from __future__ import annotations

import sys
from pathlib import Path

from s0ma.bootstrap import bootstrap_imports


def main(text: str = "Where is my order A1234?") -> str:
    build_dir = Path(__file__).resolve().parent.parent / "build"
    modules = bootstrap_imports(build_dir.as_posix())
    message = modules["inbox"].read_message(text)
    reply = modules["triage"].decide(
        message,
        modules["scripted_model"].ScriptedModel(),
        modules["tools"].answer_from_faq,
        modules["tools"].look_up_order,
    )
    line = f"{reply.action}: {reply.text}"
    print(line)
    return line


if __name__ == "__main__":
    main(" ".join(sys.argv[1:]) or "Where is my order A1234?")
'''

_AGENT_WATCH = '''\
module watch
    layer: APPLICATION
    version: 0.1.0
    intent: "This file is the check that watches the agent's replies as it runs."
    uses: [rules.Reply]
    exports: [watch_replies]

ganglion watch_replies :: APPLICATION
    visibility: PUBLIC
    intent: "Watches the replies the agent decides on and counts how many it hands to a person."
    observes: [decide]
    scope: SUBSYSTEM
    priors: "Most messages get an answer; a few go to a person."
    on_anomaly: "Reports when more than half the replies go to a person, so someone can look at the list of answers."
    forbids: "Never changes a reply; it only counts what it sees."
    ---
    def watch_replies(signals: list[Reply]) -> dict[str, object]:
        """Count hand-offs among *signals*."""
        handed = sum(1 for reply in signals if reply.action == "hand_off")
        return {"hand_offs": handed, "steady": handed * 2 <= len(signals)}
'''

_AGENT_WATCH_TESTS = """\
module watch_tests
    layer: APPLICATION
    version: 0.1.0
    intent: "Tests for the check that watches the agent."
    uses: [rules.Reply, watch.watch_replies]
    exports: []

test test_watch_replies_counts_hand_offs :: APPLICATION
    intent: "The watcher counts hand-offs and says the agent is steady while they are half or fewer."
    tests: [watch.watch_replies]
    ---
    def test_watch_replies_counts_hand_offs() -> None:
        answer = Reply(action="answer", text="ok")
        hand = Reply(action="hand_off", text="a person")
        assert watch_replies([answer, hand]) == {"hand_offs": 1, "steady": True}
        assert watch_replies([hand, hand, answer]) == {"hand_offs": 2, "steady": False}
"""


def _agent() -> Archetype:
    return Archetype(
        name="agent",
        summary=(
            "a small support-inbox agent in five steps: it answers from a "
            "list, looks up an order, or hands off to a person"
        ),
        teaches=(
            "ordered steps that each leave a clean project, a model behind "
            "an ADAPTER port with a scripted stand-in, and a ganglion "
            "watching a decision"
        ),
        called="a small agent",
        example_question="what is this agent never allowed to do?",
        bootstrap_files=("bootstrap/main.py",),
        health_command="python bootstrap/main.py",
        run_hint=(
            'Ask the agent something:        python bootstrap/main.py '
            '"What are your hours?"'
        ),
        steps=(
            ArchetypeStep(
                name="What it hears",
                intent=(
                    "A customer's message, and the order number in it if "
                    "there is one."
                ),
                files=(
                    ArchetypeFile("src/inbox/inbox.s0ma", _AGENT_INBOX),
                    ArchetypeFile("src/app_map.s0ma", _AGENT_APP_MAP),
                    ArchetypeFile(
                        "tests/inbox/inbox_tests.s0ma", _AGENT_INBOX_TESTS
                    ),
                    ArchetypeFile("bootstrap/main.py", _AGENT_BOOTSTRAP_HEARS),
                ),
            ),
            ArchetypeStep(
                name="What it must and must never do",
                intent=(
                    "It answers or hands off to a person, and it never "
                    "promises a refund."
                ),
                files=(
                    ArchetypeFile("src/rules/rules.s0ma", _AGENT_RULES),
                    ArchetypeFile(
                        "tests/rules/rules_tests.s0ma", _AGENT_RULES_TESTS
                    ),
                ),
            ),
            ArchetypeStep(
                name="Its tools",
                intent=(
                    "A short list of common answers, and a way to look up "
                    "an order."
                ),
                files=(
                    ArchetypeFile("src/tools/tools.s0ma", _AGENT_TOOLS),
                    ArchetypeFile(
                        "tests/tools/tools_tests.s0ma", _AGENT_TOOLS_TESTS
                    ),
                ),
            ),
            ArchetypeStep(
                name="How it decides",
                intent=(
                    "It picks one of three: answer from the list, look up "
                    "the order, or hand off to a person. A scripted "
                    "stand-in plays the model, so it runs with no account."
                ),
                files=(
                    ArchetypeFile("src/model/model.s0ma", _AGENT_MODEL),
                    ArchetypeFile(
                        "src/stand_in/scripted_model.s0ma",
                        _AGENT_SCRIPTED_MODEL,
                    ),
                    ArchetypeFile("src/triage/triage.s0ma", _AGENT_TRIAGE),
                    ArchetypeFile(
                        "tests/stand_in/scripted_model_tests.s0ma",
                        _AGENT_SCRIPTED_MODEL_TESTS,
                    ),
                    ArchetypeFile(
                        "tests/triage/triage_tests.s0ma", _AGENT_TRIAGE_TESTS
                    ),
                    ArchetypeFile(
                        "bootstrap/main.py", _AGENT_BOOTSTRAP_DECIDES
                    ),
                ),
            ),
            ArchetypeStep(
                name="The check that watches it",
                intent="It counts how many messages get handed to a person.",
                files=(
                    ArchetypeFile("src/watch/watch.s0ma", _AGENT_WATCH),
                    ArchetypeFile(
                        "tests/watch/watch_tests.s0ma", _AGENT_WATCH_TESTS
                    ),
                ),
            ),
        ),
    )


_ARCHETYPES: dict[str, Callable[[], Archetype]] = {
    "service": _service,
    "library": _library,
    "cli": _cli,
    "pipeline": _pipeline,
    "agent": _agent,
}


def get_archetype(name: str) -> Archetype:
    """Return the :class:`Archetype` for *name* (must be in ``TEMPLATE_CHOICES``)."""
    return _ARCHETYPES[name]()
