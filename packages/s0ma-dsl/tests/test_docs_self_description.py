"""Gates for I1 — the page that describes the documentation application.

Milestone I1 of the docs-function plan (internal) §14, which is architecture
plan §15's M7 acceptance: *the application can describe its own adapters,
validators, and outputs*. A generated page is only that proof if every fact on
it is derived; a page that happened to be right today, written by hand, is the
thing this whole initiative exists to abolish. So the claims this suite makes
are all of one shape — **the page says exactly what the live build says, and
nothing that a person typed**.

Four derivations, asked four ways:

* the readings on the page are :func:`~s0ma_dsl.docs_model.application.
  registry`'s provider ids, exactly, in both directions;
* the gates on the page are the callables
  :func:`~s0ma_dsl.docs_model.application.gate_modules` holds, and that tuple
  is complete — every module of the package is walked and a gate outside it
  is a failure. That last check is the one that matters: the module tuple is
  the only hand-written thing in the derivation, so it is the only thing that
  can go stale, and it is checked against the package rather than against
  itself;
* the registrations on the page are the documentation application's own
  committed canonical IR, which is also the file its own build emits;
* the outputs on the page are :func:`~s0ma_dsl.docs_model.application.
  generated_outputs`, which is the set ``write`` writes and ``check``
  compares.

Plus the negative half, because a derivation that cannot fail is not a
derivation: :class:`TestTheRenderersRefuse` proves each reading coming back
empty produces a stated refusal rather than a page of empty tables, and
:class:`TestTheDerivationCanFail` proves the completeness walk would actually
catch a gate the application had not heard of.

**Cost.** The documentation build is composed once for the module.
"""

from __future__ import annotations

import importlib
import inspect
import json
import pkgutil
from pathlib import Path
from typing import TYPE_CHECKING, Any

import pytest

from s0ma_dsl.docs_model import application as api
from s0ma_dsl.docs_model.application import (
    APPLICATION_IR,
    DOCS_APPLICATION_OUTPUT,
    DOCS_ROOT,
    STATIC_OUTPUTS,
    gate_modules,
    generated_outputs,
    registry,
)
from s0ma_dsl.docs_model.application import (
    build as build_documentation,
)
from s0ma_dsl.docs_model.coverage_report import CoverageSet
from s0ma_dsl.docs_model.self_description import (
    GATE_PREFIX,
    ApplicationModule,
    DocsSelfDescriptionError,
    application_module,
    docs_application,
    gate_facts,
)
from tests._committed_claim import claimed_head_tag

if TYPE_CHECKING:
    from s0ma_dsl.docs_model.application import Build

REPO_ROOT = Path(__file__).resolve().parents[3]

#: The page, relative to the checkout.
PAGE = f"{DOCS_ROOT}/{DOCS_APPLICATION_OUTPUT}"


def _is_checkout() -> bool:
    return (REPO_ROOT / ".git").exists()


requires_checkout = pytest.mark.skipif(
    not _is_checkout(), reason="not a git checkout (wheel-install context)"
)


# ---------------------------------------------------------------------------
# What every test reads, read once
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def live() -> Build:
    """The whole documentation build, composed once for this module.

    Composed in the channel the committed tree claims, so it is the build
    the committed page came from.
    """
    return build_documentation(REPO_ROOT, head_tag=claimed_head_tag())


@pytest.fixture(scope="module")
def page(live: Build) -> str:
    """The rendered self-description, as this build renders it."""
    found = next(
        (
            item.content
            for item in live.artifacts
            if item.relative == DOCS_APPLICATION_OUTPUT
        ),
        None,
    )
    assert found is not None, "the build rendered no self-description"
    return found


@pytest.fixture(scope="module")
def committed() -> str:
    """The self-description as it is committed."""
    return (REPO_ROOT / PAGE).read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def results() -> tuple[Any, ...]:
    """Every provider's own result, read independently of the build.

    Each registered provider is asked directly rather than the build's
    composition being reached into. That is deliberate: this suite is
    checking that the page's numbers are the readings' numbers, and asking
    the same object the renderer was handed would prove only that a value
    survived being passed along.
    """
    return tuple(
        provider.provide() for provider in registry(REPO_ROOT).providers()
    )


# ---------------------------------------------------------------------------
# It is an artifact like any other
# ---------------------------------------------------------------------------


@requires_checkout
class TestThePageIsGatedLikeEverythingElse:
    """M7's proof is worth nothing if the page is not held to the byte gate."""

    def test_it_is_a_declared_output(self, live: Build) -> None:
        assert DOCS_APPLICATION_OUTPUT in STATIC_OUTPUTS
        assert DOCS_APPLICATION_OUTPUT in generated_outputs(live.bundle)

    def test_it_is_rendered_and_matches_what_is_committed(
        self, page: str, committed: str
    ) -> None:
        """The byte gate, asked here as well as by the docs-application stage."""
        assert page == committed

    def test_it_is_in_the_manifest_with_its_catalog_row(self, live: Build) -> None:
        """A reader-facing page outside ``_generated/`` carries a row (B-2)."""
        document = json.loads(
            next(
                item.content
                for item in live.artifacts
                if item.relative == "_generated/docs-manifest.json"
            )
        )
        rows = {row["path_or_uri"]: row for row in document["artifacts"]}
        assert PAGE in rows
        assert rows[PAGE]["source_document"] == "doc:generated/docs-application"
        assert rows[PAGE]["format"] == "markdown"

    def test_it_renders_deterministically(self, live: Build, page: str) -> None:
        """Same tree, same bytes — the property every other artifact has."""
        again = build_documentation(REPO_ROOT, head_tag=claimed_head_tag())
        second = next(
            item.content
            for item in again.artifacts
            if item.relative == DOCS_APPLICATION_OUTPUT
        )
        assert second == page

    def test_it_is_utf8_lf_and_ends_with_one_newline(self, page: str) -> None:
        assert "\r" not in page
        assert page.endswith("\n")
        assert not page.endswith("\n\n")
        page.encode("utf-8")

    def test_it_carries_the_build_identity_with_its_channel(
        self, live: Build, page: str
    ) -> None:
        """H1's convention: the label rides on the version, on every channel."""
        assert live.bundle.stamp.version_line() in page
        assert live.bundle.stamp.snapshot_hash in page


# ---------------------------------------------------------------------------
# Derivation 1 — the readings
# ---------------------------------------------------------------------------


@requires_checkout
class TestTheReadingsAreTheRegistry:
    """The page's adapters are ``registry()``'s, in both directions."""

    def test_every_registered_provider_is_on_the_page(self, page: str) -> None:
        registered = [
            provider.provider_id for provider in registry(REPO_ROOT).providers()
        ]
        assert len(registered) >= 11, "the registry has collapsed"
        for provider_id in registered:
            assert f"| `{provider_id}` " in page, provider_id

    def test_the_page_names_no_reading_the_registry_does_not_have(
        self, page: str
    ) -> None:
        """The half that catches an invented row.

        Asserted as an equality rather than a subset: a page listing a
        reading nobody registered is exactly the failure a subset test
        would let through. The rows are read back out of the rendered
        table between the two adapter headings, so the comparison is
        against what a reader sees.
        """
        section = page.partition("## The readings")[2].partition("## The gates")[0]
        listed = {
            line.split("`")[1]
            for line in section.splitlines()
            if line.startswith("| `")
        }
        registered = {
            provider.provider_id for provider in registry(REPO_ROOT).providers()
        }
        assert listed == registered

    def test_the_counts_are_the_readings_own(
        self, page: str, results: tuple[Any, ...]
    ) -> None:
        """Not a tally taken here: the counts each provider reported."""
        for result in results:
            row = next(
                line
                for line in page.splitlines()
                if line.startswith(f"| `{result.provider_id}` ")
            )
            cells = [cell.strip() for cell in row.split("|")]
            assert cells[2] == str(len(result.sources())), result.provider_id
            assert cells[3] == str(len(result.records)), result.provider_id


# ---------------------------------------------------------------------------
# Derivation 2 — the gates
# ---------------------------------------------------------------------------


def _package_gate_modules() -> list[Any]:
    """Every module of the docs model, imported from the package's own list.

    ``pkgutil`` over the package's ``__path__`` rather than a written list:
    this is the completeness check, and a completeness check that read the
    same tuple it is checking would pass by construction.
    """
    import s0ma_dsl.docs_model as package

    found = []
    for info in sorted(pkgutil.iter_modules(package.__path__), key=lambda i: i.name):
        found.append(importlib.import_module(f"{package.__name__}.{info.name}"))
    return found


@requires_checkout
class TestTheGatesAreTheLiveCallables:
    """The page's gate battery is read off the functions, and it is complete."""

    def test_the_module_tuple_holds_every_gate_in_the_package(self) -> None:
        """The one hand-written thing in the derivation, checked from outside.

        A gate defined in a module the application did not name is a gate
        that runs and is not described, which is the exact shape of the
        failure this page exists to make impossible.
        """
        declared = {module.__name__ for module in gate_modules()}
        for module in _package_gate_modules():
            gates = [
                name
                for name, value in vars(module).items()
                if name.startswith(GATE_PREFIX)
                and inspect.isfunction(value)
                and value.__module__ == module.__name__
            ]
            if gates:
                assert module.__name__ in declared, (module.__name__, gates)

    def test_every_gate_is_on_the_page_with_its_codes(self, page: str) -> None:
        facts = gate_facts(gate_modules())
        assert len(facts) >= 20, "the gate battery has collapsed"
        for gate in facts:
            assert f"`{gate.name}`" in page, gate.name
            for code in gate.reports:
                assert f"`{code}`" in page, (gate.name, code)

    def test_every_gate_states_a_code_that_the_model_mints(self) -> None:
        """A gate may not name a report nothing in the model defines.

        The known set is every ``DOC_*`` constant the gate-holding modules
        declare, which is where the codes are minted. A docstring naming a
        code that exists nowhere would put a lookup on the page that leads
        a reader to no page at all.
        """
        minted = {
            name
            for module in gate_modules()
            for name, value in vars(module).items()
            if name.startswith("DOC_") and isinstance(value, str) and value == name
        }
        assert len(minted) >= 15, "the diagnostic vocabulary has collapsed"
        for gate in gate_facts(gate_modules()):
            for code in gate.reports:
                assert code in minted, (gate.name, code)

    def test_the_page_quotes_the_gate_rather_than_describing_it(
        self, page: str
    ) -> None:
        """What it checks is the gate's own first line, markup normalized."""
        for gate in gate_facts(gate_modules()):
            assert gate.checks in page, gate.name
            assert "``" not in gate.checks, gate.name


# ---------------------------------------------------------------------------
# Derivation 3 — the application's own registrations
# ---------------------------------------------------------------------------


@requires_checkout
class TestTheRegistrationsAreTheApplicationsOwn:
    """What the page says the application registers is what it registers."""

    def test_the_ir_it_reads_is_the_one_its_own_build_emits(self) -> None:
        assert (REPO_ROOT / APPLICATION_IR).is_file()
        assert APPLICATION_IR.startswith(f"{DOCS_ROOT}/_built/")

    def test_every_registered_declaration_is_on_the_page(self, page: str) -> None:
        module = application_module(REPO_ROOT, relative=APPLICATION_IR)
        assert module.components, "the application registers nothing"
        assert f"`{module.name}`" in page
        assert f"`{module.version}`" in page
        for component in module.components:
            assert f"`{component.id}`" in page, component.id

    def test_the_page_names_no_declaration_the_ir_does_not_have(
        self, page: str
    ) -> None:
        document = json.loads(
            (REPO_ROOT / APPLICATION_IR).read_text(encoding="utf-8")
        )
        canonical = {
            entry["canonical_id"]
            for entry in document["components"]
            if isinstance(entry, dict) and isinstance(entry.get("canonical_id"), str)
        }
        listed = {
            line.split("`")[1]
            for line in page.splitlines()
            if line.startswith("| `application::")
        }
        assert listed == canonical

    def test_no_machine_path_reaches_the_page(self, page: str) -> None:
        """INV-5. The IR records an absolute source path; the page must not."""
        assert str(REPO_ROOT) not in page
        assert "source_file" not in page


# ---------------------------------------------------------------------------
# Derivation 4 — the outputs
# ---------------------------------------------------------------------------


@requires_checkout
class TestTheOutputsAreTheDeclaredSet:
    """The page's outputs are what ``write`` writes and ``check`` compares."""

    def test_every_declared_output_is_on_the_page(
        self, page: str, live: Build
    ) -> None:
        declared = generated_outputs(live.bundle)
        assert len(declared) >= 61
        for relative in declared:
            assert f"`{relative}`" in page, relative

    def test_the_split_is_the_applications_own(self, page: str, live: Build) -> None:
        """Decided against computed, taken from ``STATIC_OUTPUTS``."""
        declared = generated_outputs(live.bundle)
        decided, _, computed = page.partition("### Computed")
        for relative in STATIC_OUTPUTS:
            assert f"`{relative}`" in decided, relative
            assert f"`{relative}`" not in computed, relative
        for relative in declared:
            if relative not in STATIC_OUTPUTS:
                assert f"`{relative}`" in computed, relative

    def test_a_page_with_a_catalog_row_names_its_document(
        self, page: str, live: Build
    ) -> None:
        """The join is onto the row, never onto a description written here."""
        prefix = f"{DOCS_ROOT}/"
        titles = {
            record.canonical_source[len(prefix) :]: record.title
            for record in live.bundle.documents
            if record.canonical_source.startswith(prefix)
        }
        for relative in generated_outputs(live.bundle):
            row = next(
                line for line in page.splitlines() if line.startswith(f"| `{relative}`")
            )
            if relative in titles:
                assert titles[relative] in row, relative
            else:
                assert "no catalog row" in row, relative

    def test_it_lists_itself(self, page: str) -> None:
        """The self-reference M7 actually asks for."""
        assert f"`{DOCS_APPLICATION_OUTPUT}`" in page


# ---------------------------------------------------------------------------
# The negative half
# ---------------------------------------------------------------------------


@requires_checkout
class TestTheRenderersRefuse:
    """A reading that came back empty is a refusal, never an empty table."""

    def _module(self) -> ApplicationModule:
        return application_module(REPO_ROOT, relative=APPLICATION_IR)

    def _coverage(self) -> tuple[CoverageSet, ...]:
        """A measured set, so the other refusals are about their own input.

        Built here rather than measured off the live build: each test in
        this class holds four inputs healthy and empties the fifth, and a
        helper that composed a real measurement would make three of them
        also a test of I2's deriver.
        """
        return (
            CoverageSet(
                name="concepts",
                question="a set, so this input is not the empty one",
                measured_by="a fixture",
                enforced_by=("resolve.check_coverage",),
                reports=("DOC_CONCEPT_UNCOVERED",),
                required=1,
                covered=1,
                exceptions=(),
                uncovered=(),
                ceilings={},
            ),
        )

    def test_no_reading_is_refused(self, live: Build) -> None:
        with pytest.raises(DocsSelfDescriptionError, match="no provider result"):
            docs_application(
                live.bundle,
                results=(),
                gates=gate_facts(gate_modules()),
                module=self._module(),
                outputs=generated_outputs(live.bundle),
                decided=STATIC_OUTPUTS,
                packaged=frozenset(),
                media=frozenset(),
                coverage=self._coverage(),
                page=DOCS_APPLICATION_OUTPUT,
                docs_root=DOCS_ROOT,
            )

    def test_no_gate_is_refused(self, live: Build, results: tuple[Any, ...]) -> None:
        with pytest.raises(DocsSelfDescriptionError, match="no gate"):
            docs_application(
                live.bundle,
                results=results,
                gates=(),
                module=self._module(),
                outputs=generated_outputs(live.bundle),
                decided=STATIC_OUTPUTS,
                packaged=frozenset(),
                media=frozenset(),
                coverage=self._coverage(),
                page=DOCS_APPLICATION_OUTPUT,
                docs_root=DOCS_ROOT,
            )

    def test_no_output_is_refused(self, live: Build, results: tuple[Any, ...]) -> None:
        with pytest.raises(DocsSelfDescriptionError, match="no declared output"):
            docs_application(
                live.bundle,
                results=results,
                gates=gate_facts(gate_modules()),
                module=self._module(),
                outputs=(),
                decided=STATIC_OUTPUTS,
                packaged=frozenset(),
                media=frozenset(),
                coverage=self._coverage(),
                page=DOCS_APPLICATION_OUTPUT,
                docs_root=DOCS_ROOT,
            )

    def test_no_coverage_is_refused(self, live: Build, results: tuple[Any, ...]) -> None:
        """The fifth input, and the one whose empty form looks like success.

        Every other refusal here would render a visibly empty table. An
        empty coverage section renders a heading saying what this build
        covers over nothing at all, which reads exactly like full marks —
        so it is refused rather than rendered honestly-but-uselessly.
        """
        with pytest.raises(DocsSelfDescriptionError, match="coverage"):
            docs_application(
                live.bundle,
                results=results,
                gates=gate_facts(gate_modules()),
                module=self._module(),
                outputs=generated_outputs(live.bundle),
                decided=STATIC_OUTPUTS,
                packaged=frozenset(),
                media=frozenset(),
                coverage=(),
                page=DOCS_APPLICATION_OUTPUT,
                docs_root=DOCS_ROOT,
            )

    def test_a_missing_ir_is_refused_by_name(self, tmp_path: Path) -> None:
        with pytest.raises(DocsSelfDescriptionError, match="not in this checkout"):
            application_module(tmp_path, relative=APPLICATION_IR)

    def test_an_ir_that_registers_nothing_is_refused(self, tmp_path: Path) -> None:
        target = tmp_path / APPLICATION_IR
        target.parent.mkdir(parents=True)
        target.write_text(json.dumps({"module": {}, "components": []}), encoding="utf-8")
        with pytest.raises(DocsSelfDescriptionError, match="registers nothing"):
            application_module(tmp_path, relative=APPLICATION_IR)


@requires_checkout
class TestTheDerivationCanFail:
    """A check that says yes to everything would pass every test above."""

    def test_a_gate_outside_the_named_modules_would_be_caught(self) -> None:
        """The completeness walk, run against a module the tuple omits.

        ``inventories`` holds no gate today, which is why it is not in
        ``gate_modules()``. Giving it one and re-running the walk's own
        rule is the proof that the rule notices — without which
        ``test_the_module_tuple_holds_every_gate_in_the_package`` could be
        passing because it looks at nothing.
        """
        from s0ma_dsl.docs_model import inventories

        assert inventories not in gate_modules()

        def check_planted() -> list[Any]:  # pragma: no cover - never called
            """A planted gate. ``DOC_GATE_VACUOUS``."""
            return []

        check_planted.__module__ = inventories.__name__
        inventories.check_planted = check_planted
        try:
            found = [
                name
                for name, value in vars(inventories).items()
                if name.startswith(GATE_PREFIX)
                and inspect.isfunction(value)
                and value.__module__ == inventories.__name__
            ]
            assert found == ["check_planted"]
            assert inventories.__name__ not in {
                module.__name__ for module in gate_modules()
            }
        finally:
            delattr(inventories, "check_planted")

    def test_a_gate_with_no_stated_code_is_refused(self) -> None:
        """The rule that made seven docstrings name their reports at I1."""
        from types import ModuleType

        silent = ModuleType("silent")

        def check_silent() -> list[Any]:  # pragma: no cover - never called
            """Checks something and says nothing about what it reports."""
            return []

        check_silent.__module__ = "silent"
        silent.check_silent = check_silent  # type: ignore[attr-defined]
        with pytest.raises(DocsSelfDescriptionError, match="names no diagnostic code"):
            gate_facts([silent])

    def test_a_gate_with_no_docstring_is_refused(self) -> None:
        """The other half: a battery of bare function names is not a battery."""
        from types import ModuleType

        mute = ModuleType("mute")

        def check_mute() -> list[Any]:  # pragma: no cover - never called
            return []

        check_mute.__module__ = "mute"
        mute.check_mute = check_mute  # type: ignore[attr-defined]
        with pytest.raises(DocsSelfDescriptionError, match="says nothing about itself"):
            gate_facts([mute])

    def test_the_application_module_is_reachable_through_the_public_api(self) -> None:
        """``gate_modules`` reaches this module without importing itself."""
        assert api in gate_modules()
        assert api.check_surface_index.__module__ == api.__name__
