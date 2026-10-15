"""The four generated references: MCP, studi0, the distributions, the components.

Milestone F4 of the docs-function plan (internal) §11. Four pages, and the
assertions here are the ones a reference page can actually fail: that it
lists everything the live sources say exists, that its numbers are the
numbers of the rows under them, that every link and every contents entry
resolves, and that it agrees with the *other* renderer of the same MCP
facts.

**Why completeness is asserted as equality.** A subset assertion passes a
page that lost half a server; a superset assertion passes a page that
invented a tool. Every page's claim is that it *is* a family of records,
rendered — so the sets are compared as sets, against the composed bundle
and the component facts rather than against a list written here.

**The parity check, and what a failure of it would mean.**
``scripts/generate_mcp_readme_surfaces.py`` renders the authoring server
into the two READMEs from ``packages/s0ma-mcp/tests/snapshots/mcp_surface.json``.
The documentation build renders it from the live served listing, which
:class:`~s0ma_dsl.docs_model.providers_mcp.McpProvider` cross-checks
against that same snapshot before emitting a record. So the two renderings
agreeing is not a coincidence to be maintained, it is a consequence to be
*verified*: :class:`TestParityWithTheReadmeGenerator` compares the name
sets and the read/write facts in both directions, and a failure is a bug
in the provider's cross-check rather than a page to be edited.

**What is not asserted here.** Whether the four pages are wired into
:data:`~s0ma_dsl.docs_model.application.STATIC_OUTPUTS` is the
orchestrator's step, not this milestone's, and
:class:`TestTheWiring` is written to be true on both sides of it: it
checks the four together, so a half-wired set — two outputs declared and
two forgotten — is red either way.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import subprocess
import sys
from functools import cache
from pathlib import Path
from typing import TYPE_CHECKING, Any

import pytest

from s0ma_dsl.docs_model.application import DOCS_ROOT, STATIC_OUTPUTS, build, registry
from s0ma_dsl.docs_model.inventories import component_facts
from s0ma_dsl.docs_model.providers_catalog import (
    AUDIENCES,
    CATALOG_SCHEMA,
    KINDS,
    STATUS_BY_CATEGORY,
    STATUSES,
    CatalogProvider,
)
from s0ma_dsl.docs_model.providers_concepts import FORBIDDEN_IN_AUTHORED_PROSE
from s0ma_dsl.docs_model.providers_mcp import McpProvider
from s0ma_dsl.docs_model.providers_repo import facts_of, package_facts
from s0ma_dsl.docs_model.reference_pages_surfaces import (
    AUTHORING_ADAPTER,
    COMPONENT_INDEX_TITLE,
    CONTRACT_PREFIX,
    KIND_WORDS,
    LAYER_WORDS,
    MCP_CHANNELS,
    MCP_TITLE,
    PACKAGES_TITLE,
    RUNTIME_ADAPTER,
    SERVERS,
    STUDI0_CHANNEL,
    STUDI0_CONTRACTS,
    STUDI0_TITLE,
    VISIBILITY_ABSENT,
    DocsReferenceError,
    approval_of,
    component_index,
    contracts_of,
    distribution_facts,
    mcp_reference,
    packages_reference,
    studi0_reference,
)

if TYPE_CHECKING:
    from collections.abc import Mapping
    from types import ModuleType

    from s0ma_dsl.docs_model.records import DocsBundle

#: The monorepo root (this file: packages/s0ma-dsl/tests/<file>).
REPO_ROOT = Path(__file__).resolve().parents[3]
SCRIPTS = REPO_ROOT / "scripts"
TESTS_DIR = Path(__file__).resolve().parent

#: The committed MCP surface snapshot the README generator renders from,
#: and which the MCP provider cross-checks its reading against.
MCP_SNAPSHOT = REPO_ROOT / "packages/s0ma-mcp/tests/snapshots/mcp_surface.json"

#: The README generator this milestone must not fork the facts of.
README_GENERATOR = SCRIPTS / "generate_mcp_readme_surfaces.py"

#: The renderer under test, as a file — two assertions below are about
#: what it does *not* read, and only its source can answer those.
RENDERER_SOURCE = (
    REPO_ROOT
    / "packages/s0ma-dsl/src/s0ma_dsl/docs_model/reference_pages_surfaces.py"
)

# ---------------------------------------------------------------------------
# The four pages, and where the wiring note says each one goes
# ---------------------------------------------------------------------------

MCP_OUTPUT = "reference/mcp.md"
STUDI0_OUTPUT = "reference/studi0.md"
PACKAGES_OUTPUT = "reference/packages.md"
COMPONENT_INDEX_OUTPUT = "architecture/component-index.md"

F4_OUTPUTS: tuple[str, ...] = (
    MCP_OUTPUT,
    STUDI0_OUTPUT,
    PACKAGES_OUTPUT,
    COMPONENT_INDEX_OUTPUT,
)

#: The catalog rows the wiring note asks the orchestrator to add, exactly
#: as they would appear in ``docs/s0ma_src/catalog.json``. Held here so the
#: shapes are validated by the real catalog reader rather than by review,
#: and so a change to either side is a change somebody has to make twice
#: on purpose.
F4_CATALOG_ROWS: tuple[Mapping[str, Any], ...] = (
    {
        "audiences": ["agent", "contributor", "user"],
        "authority": "",
        "canonical_source": f"{DOCS_ROOT}/{COMPONENT_INDEX_OUTPUT}",
        "covers": [],
        "governed_by": [],
        "id": "doc:generated/component-index",
        "kind": "reference",
        "prose_locator": f"{DOCS_ROOT}/{COMPONENT_INDEX_OUTPUT}",
        "status": "generated",
        "title": COMPONENT_INDEX_TITLE,
    },
    {
        "audiences": ["agent", "user"],
        "authority": "",
        "canonical_source": f"{DOCS_ROOT}/{MCP_OUTPUT}",
        "covers": [],
        "governed_by": [],
        "id": "doc:generated/mcp-reference",
        "kind": "reference",
        "prose_locator": f"{DOCS_ROOT}/{MCP_OUTPUT}",
        "status": "generated",
        "title": MCP_TITLE,
    },
    {
        "audiences": ["contributor", "user"],
        "authority": "",
        "canonical_source": f"{DOCS_ROOT}/{PACKAGES_OUTPUT}",
        "covers": [],
        "governed_by": [],
        "id": "doc:generated/packages-reference",
        "kind": "reference",
        "prose_locator": f"{DOCS_ROOT}/{PACKAGES_OUTPUT}",
        "status": "generated",
        "title": PACKAGES_TITLE,
    },
    {
        "audiences": ["agent", "user"],
        "authority": "",
        "canonical_source": f"{DOCS_ROOT}/{STUDI0_OUTPUT}",
        "covers": [],
        "governed_by": [],
        "id": "doc:generated/studi0-reference",
        "kind": "reference",
        "prose_locator": f"{DOCS_ROOT}/{STUDI0_OUTPUT}",
        "status": "generated",
        "title": STUDI0_TITLE,
    },
)


def _is_checkout() -> bool:
    return (REPO_ROOT / ".git").exists()


requires_checkout = pytest.mark.skipif(
    not _is_checkout(), reason="not a git checkout (wheel-install context)"
)


@cache
def _script(name: str) -> ModuleType:
    """Import a ``scripts/`` guard, so a pin is against the real rule.

    Registered in ``sys.modules`` before execution for the reason
    ``test_check_links_script.py`` gives: ``@dataclass`` resolves a class's
    module through it.
    """
    spec = importlib.util.spec_from_file_location(f"s0ma_{name}", SCRIPTS / f"{name}.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


# ---------------------------------------------------------------------------
# One reading of this checkout, shared by every assertion below
# ---------------------------------------------------------------------------


def render_pages(root: Path) -> dict[str, str]:
    """The four pages, rendered from ``root``, keyed by where each goes.

    The wiring the orchestrator will write into
    :func:`~s0ma_dsl.docs_model.application._artifacts`, written here first
    so the renderers are proved from outside before anything declares them
    — and so the subprocess determinism check has one function to call
    rather than four calls to keep in step with these.
    """
    known = registry(root)
    result = build(root, providers=known)
    mirrors = [
        item
        for provider in known.providers()
        if isinstance(provider, McpProvider)
        for item in provider.mirrored_documents()
    ]
    external = sorted(
        {
            identifier
            for provider in known.providers()
            for identifier in getattr(provider, "external_ids", tuple)()
        }
    )
    facts, _ = component_facts(root, external)
    return {
        MCP_OUTPUT: mcp_reference(
            result.bundle, mirrors=mirrors, page=MCP_OUTPUT, docs_root=DOCS_ROOT
        ),
        STUDI0_OUTPUT: studi0_reference(
            result.bundle, page=STUDI0_OUTPUT, docs_root=DOCS_ROOT
        ),
        PACKAGES_OUTPUT: packages_reference(
            result.bundle,
            distributions=distribution_facts(root),
            components=facts,
            page=PACKAGES_OUTPUT,
            docs_root=DOCS_ROOT,
        ),
        COMPONENT_INDEX_OUTPUT: component_index(
            result.bundle,
            components=facts,
            page=COMPONENT_INDEX_OUTPUT,
            docs_root=DOCS_ROOT,
        ),
    }


def digest_of_pages(root: str) -> str:
    """One digest over all four pages. Called by this module's own subprocess."""
    rendered = render_pages(Path(root))
    joined = "\0".join(f"{key}\0{rendered[key]}" for key in sorted(rendered))
    return hashlib.sha256(joined.encode("utf-8")).hexdigest()


@pytest.fixture(scope="module")
def composed() -> DocsBundle:
    """One composition of this checkout."""
    return build(REPO_ROOT).bundle


@pytest.fixture(scope="module")
def facts() -> tuple[Any, ...]:
    """The component facts of this checkout, read once."""
    known = registry(REPO_ROOT)
    external = sorted(
        {
            identifier
            for provider in known.providers()
            for identifier in getattr(provider, "external_ids", tuple)()
        }
    )
    found, _ = component_facts(REPO_ROOT, external)
    return found


@pytest.fixture(scope="module")
def pages() -> dict[str, str]:
    """The four pages as this checkout renders them."""
    return render_pages(REPO_ROOT)


@pytest.fixture(scope="module")
def snapshot() -> dict[str, list[dict[str, Any]]]:
    """The committed MCP surface snapshot the README generator reads."""
    document: dict[str, list[dict[str, Any]]] = json.loads(
        MCP_SNAPSHOT.read_text(encoding="utf-8")
    )
    return document


def _code_spans(page: str) -> set[str]:
    """Every backticked run on a page — where this renderer puts ids."""
    found: set[str] = set()
    for line in page.splitlines():
        parts = line.split("`")
        found.update(parts[index] for index in range(1, len(parts), 2))
    return found


def _links(page: str) -> list[str]:
    """Every intra-repository link target on a page, by the A5 gate's rules."""
    module = _script("check_links")
    return [
        match.group("target")
        for match in module._LINK_RE.finditer(page)
        if match.group("target")
        and not match.group("target").startswith("#")
        and not module._EXTERNAL_RE.match(match.group("target"))
    ]


# ---------------------------------------------------------------------------
# T1 — the MCP page carries both servers, completely
# ---------------------------------------------------------------------------


@requires_checkout
class TestTheMcpPage:
    """Every capability either server serves, sectioned by which one serves it."""

    def test_every_mcp_surface_is_on_the_page(
        self, pages: dict[str, str], composed: DocsBundle
    ) -> None:
        """Equality against the composed bundle, not containment."""
        channels = {channel for channel, _ in MCP_CHANNELS}
        served = {
            record.id for record in composed.surfaces if record.channel in channels
        }
        assert served, "this checkout composed no MCP surface at all"
        assert served <= _code_spans(pages[MCP_OUTPUT])
        listed = {
            span for span in _code_spans(pages[MCP_OUTPUT]) if span.startswith("mcp:")
        }
        assert listed == served

    def test_each_surface_has_exactly_one_row(
        self, pages: dict[str, str], composed: DocsBundle
    ) -> None:
        """A capability listed under both servers would double every count.

        Counted as *rows* rather than as occurrences: nine of the
        resources are named a second time in the mirrors table, which is
        the point of that table, and a naive occurrence count would call
        the page's most useful cross-reference a duplicate.
        """
        lines = pages[MCP_OUTPUT].splitlines()
        channels = {channel for channel, _ in MCP_CHANNELS}
        for record in composed.surfaces:
            if record.channel not in channels:
                continue
            opening = f"| `{record.public_name}` | `{record.id}` |"
            assert sum(1 for line in lines if line.startswith(opening)) == 1, record.id

    def test_the_two_servers_are_sectioned_and_counted(
        self, pages: dict[str, str], composed: DocsBundle
    ) -> None:
        """Section headings, and the count under each equal to its records."""
        page = pages[MCP_OUTPUT]
        channels = {channel for channel, _ in MCP_CHANNELS}
        total = sum(1 for item in composed.surfaces if item.channel in channels)
        for server in SERVERS:
            held = [
                item
                for item in composed.surfaces
                if item.channel in channels
                and item.provenance.adapter_id == server.adapter
            ]
            assert held, server.adapter
            assert f"\n## {server.title}\n" in page
            assert (
                f"{len(held)} of the {total} capabilities, shipped in "
                f"`{server.distribution}`."
            ) in page
            for channel, heading in MCP_CHANNELS:
                per_channel = [item for item in held if item.channel == channel]
                if per_channel:
                    assert f"### {heading}\n" in page, (server.adapter, heading)
                    assert f"{len(per_channel)} of this server's {len(held)}." in page

    def test_the_runtime_server_is_named_as_unbound_because_it_is(
        self, pages: dict[str, str], composed: DocsBundle
    ) -> None:
        """The honest sentence, and the fact that makes it honest.

        Core's server is listed through the protocol's public surface,
        which carries no callable — so no row of it reaches a registered
        component, and the page says so instead of leaving a blank column
        where a binding would be.
        """
        channels = {channel for channel, _ in MCP_CHANNELS}
        runtime = [
            item
            for item in composed.surfaces
            if item.channel in channels
            and item.provenance.adapter_id == RUNTIME_ADAPTER
        ]
        assert runtime
        assert not any(item.component_refs for item in runtime)
        assert all(item.manual_exception for item in runtime)
        assert "None of them reaches a registered component" in pages[MCP_OUTPUT]

    def test_the_approval_column_is_the_declared_effect(
        self, pages: dict[str, str], composed: DocsBundle
    ) -> None:
        """Three answers, and the third one is the honest one."""
        channels = {channel for channel, _ in MCP_CHANNELS}
        answers = {
            approval_of(item)
            for item in composed.surfaces
            if item.channel in channels
        }
        assert answers == {"yes", "no", "not declared"}
        asking = sorted(
            item.id
            for item in composed.surfaces
            if item.channel in channels and approval_of(item) == "yes"
        )
        assert asking == ["mcp:tool/submit_feedback", "mcp:tool/verify_host"]
        for identifier in asking:
            row = next(
                line
                for line in pages[MCP_OUTPUT].splitlines()
                if f"`{identifier}`" in line
            )
            assert row.rstrip().endswith("| yes |"), identifier

    def test_every_mirror_is_listed_with_its_canonical_source(
        self, pages: dict[str, str]
    ) -> None:
        """Every packaged guide, each pointing at its original."""
        mirrors = McpProvider(root=REPO_ROOT).mirrored_documents()
        assert mirrors
        page = pages[MCP_OUTPUT]
        assert (
            f"The authoring server answers {len(mirrors)} of its resources"
        ) in page
        for item in mirrors:
            assert f"`{item.resource}`" in page, item.resource
            assert f"`{item.mirror}`" in page, item.mirror
            assert f"`{item.canonical}`" in page, item.canonical

    def test_a_mirror_naming_an_unserved_resource_is_refused(
        self, composed: DocsBundle
    ) -> None:
        """A row pointing at a URI no section lists is a dead pointer."""
        from s0ma_dsl.docs_model.providers_mcp import MirrorDocument

        with pytest.raises(DocsReferenceError, match="does not list"):
            mcp_reference(
                composed,
                mirrors=[
                    MirrorDocument(
                        resource="mcp:resource/s0ma://guide/nothing",
                        mirror="packages/s0ma-mcp/src/s0ma_mcp/_docs/nothing.md",
                        canonical="docs/nothing.md",
                    )
                ],
                page=MCP_OUTPUT,
                docs_root=DOCS_ROOT,
            )


# ---------------------------------------------------------------------------
# T3 — parity with the README generator
# ---------------------------------------------------------------------------


@requires_checkout
class TestParityWithTheReadmeGenerator:
    """Two renderings of one served surface, held against each other.

    Both derive from the same truth — that is the design — so this is a
    verification rather than a synchronization. A failure here is a
    provider bug, and the milestone brief is explicit that it is reported
    rather than papered over.
    """

    def test_the_generator_still_reads_the_snapshot_this_pins(self) -> None:
        """The pin's own premise: the generator has not moved its source."""
        source = README_GENERATOR.read_text(encoding="utf-8")
        assert 'SNAPSHOT = ROOT / "packages/s0ma-mcp/tests/snapshots/mcp_surface.json"' in source
        assert MCP_SNAPSHOT.is_file()

    def test_the_authoring_surface_names_are_the_same_set(
        self, composed: DocsBundle, snapshot: dict[str, list[dict[str, Any]]]
    ) -> None:
        """Set equality per family, in both directions."""
        served = {
            channel: {
                record.public_name
                for record in composed.surfaces
                if record.channel == channel
                and record.provenance.adapter_id == AUTHORING_ADAPTER
            }
            for channel, _ in MCP_CHANNELS
        }
        assert served["mcp_tool"] == {item["name"] for item in snapshot["tools"]}
        assert served["mcp_resource"] == {item["uri"] for item in snapshot["resources"]}
        assert served["mcp_prompt"] == {item["name"] for item in snapshot["prompts"]}

    def test_every_name_the_generator_would_render_is_on_the_page(
        self, pages: dict[str, str], snapshot: dict[str, list[dict[str, Any]]]
    ) -> None:
        """The claim as a reader meets it: same names, same page."""
        spans = _code_spans(pages[MCP_OUTPUT])
        for item in snapshot["tools"]:
            assert item["name"] in spans, item["name"]
        for item in snapshot["resources"]:
            assert item["uri"] in spans, item["uri"]
        for item in snapshot["prompts"]:
            assert item["name"] in spans, item["name"]

    def test_the_read_write_fact_agrees_with_the_annotation(
        self, composed: DocsBundle, snapshot: dict[str, list[dict[str, Any]]]
    ) -> None:
        """``readOnlyHint`` is the protocol's promise; the row must keep it.

        The generator renders the hint into its annotations table and this
        page renders the effect derived from it. If they can disagree, one
        of the two is telling a reader that a mutating tool is safe.
        """
        effects = {
            record.public_name: record.side_effects
            for record in composed.surfaces
            if record.channel == "mcp_tool"
            and record.provenance.adapter_id == AUTHORING_ADAPTER
        }
        for tool in snapshot["tools"]:
            annotations = tool["annotations"] or {}
            read_only = annotations.get("readOnlyHint")
            assert isinstance(read_only, bool), tool["name"]
            declared = effects[tool["name"]]
            if read_only:
                assert "read" in declared, tool["name"]
                assert "write" not in declared, tool["name"]
            else:
                assert "write" in declared, tool["name"]
                assert "read" not in declared, tool["name"]

    def test_the_page_does_not_read_the_snapshot(self) -> None:
        """A second opinion about a settled fact is how two pages diverge.

        The renderer reaches the snapshot through the provider's
        cross-check and never by opening the file, which is what makes
        the parity above a consequence rather than a habit somebody has
        to keep. The one file this module opens at all is the
        ``pyproject.toml`` a distribution's license is declared in.
        """
        source = RENDERER_SOURCE.read_text(encoding="utf-8")
        body = source.split('"""', 2)[2]
        assert "mcp_surface.json" in source, "the parity claim should be documented"
        assert "mcp_surface.json" not in body, "the renderer must not name the snapshot"
        assert "json" not in body.split("\n__all__", 1)[0], (
            "the renderer imports no JSON reader; the snapshot is a JSON file"
        )
        assert body.count("read_text") == 1, (
            "the only file this module reads is a distribution's pyproject.toml"
        )


# ---------------------------------------------------------------------------
# T1 — the studi0 page carries the routes and the contracts
# ---------------------------------------------------------------------------


@requires_checkout
class TestTheStudi0Page:
    """Five routes, six contracts, and every declared fact of each."""

    def test_every_route_is_on_the_page(
        self, pages: dict[str, str], composed: DocsBundle
    ) -> None:
        routes = {
            record.id
            for record in composed.surfaces
            if record.channel == STUDI0_CHANNEL
        }
        assert routes
        listed = {
            span
            for span in _code_spans(pages[STUDI0_OUTPUT])
            if span.startswith("studi0:")
        }
        assert listed == routes

    def test_each_route_carries_its_method_purpose_and_effects(
        self, pages: dict[str, str], composed: DocsBundle
    ) -> None:
        """The three facts the milestone asks the table for, per row."""
        page = pages[STUDI0_OUTPUT]
        serving = next(
            item
            for item in contracts_of(composed)
            if item.id == f"{CONTRACT_PREFIX}serving-contract"
        )
        method = facts_of(serving.status)["methods"]
        for record in composed.surfaces:
            if record.channel != STUDI0_CHANNEL:
                continue
            row = next(line for line in page.splitlines() if f"`{record.id}`" in line)
            assert f"`{record.public_name}`" in row, record.id
            assert f"`{method}`" in row, record.id
            assert record.intent in row, record.id
            for effect in record.side_effects:
                assert effect in row, (record.id, effect)

    def test_the_route_count_and_the_serving_contract_agree(
        self, composed: DocsBundle
    ) -> None:
        """The contract says how many routes there are; so does the bundle.

        Not a page assertion — a truth assertion. The page renders both
        numbers, and if the source of one ever stopped matching the source
        of the other the page would be the last place anybody noticed.
        """
        serving = next(
            item
            for item in contracts_of(composed)
            if item.id == f"{CONTRACT_PREFIX}serving-contract"
        )
        declared = facts_of(serving.status)["routes"]
        actual = sum(
            1 for item in composed.surfaces if item.channel == STUDI0_CHANNEL
        )
        assert declared == str(actual)

    def test_every_declared_contract_has_a_section_and_all_its_facts(
        self, pages: dict[str, str], composed: DocsBundle
    ) -> None:
        page = pages[STUDI0_OUTPUT]
        declared = contracts_of(composed)
        assert declared
        assert f"{len(declared)} of them." in page
        for record in declared:
            assert f"`{record.id}`" in page, record.id
            assert f"`{record.section}`" in page, record.id
            for key, value in facts_of(record.status).items():
                assert f"| `{key}` | `{value}` |" in page, (record.id, key)

    def test_this_modules_contract_table_is_the_builds_contract_set(
        self, composed: DocsBundle
    ) -> None:
        """A contract with no authored sentence renders, and is a finding.

        The renderer never drops one — it falls back to the key — so this
        assertion is what turns "a contract nobody described" into a red
        test rather than a paragraph a reader never gets.
        """
        declared = {
            record.id.removeprefix(CONTRACT_PREFIX) for record in contracts_of(composed)
        }
        assert {item.key for item in STUDI0_CONTRACTS} == declared

    def test_a_build_with_no_studi0_route_is_refused(
        self, composed: DocsBundle
    ) -> None:
        import dataclasses

        stripped = dataclasses.replace(
            composed,
            surfaces=tuple(
                item for item in composed.surfaces if item.channel != STUDI0_CHANNEL
            ),
        )
        with pytest.raises(DocsReferenceError, match="0 studi0 routes"):
            studi0_reference(stripped, page=STUDI0_OUTPUT, docs_root=DOCS_ROOT)


# ---------------------------------------------------------------------------
# T1 — the distributions page
# ---------------------------------------------------------------------------


@requires_checkout
class TestThePackagesPage:
    """Four distributions: version, license, direction, and what each is."""

    def test_the_reading_is_the_shared_one_plus_the_license(self) -> None:
        """Version and direction come from ``package_facts``, unchanged.

        The whole point of :func:`distribution_facts` is that it does not
        take a second opinion about a fact that already has one, and this
        is that claim as an assertion rather than as a docstring.
        """
        shared = {item.distribution: item for item in package_facts(REPO_ROOT)}
        read = {item.distribution: item for item in distribution_facts(REPO_ROOT)}
        assert set(shared) == set(read)
        for name, item in read.items():
            assert item.version == shared[name].version
            assert item.depends_on == shared[name].depends_on
            assert item.source == shared[name].source
            assert item.license

    def test_every_distribution_is_on_the_page_with_its_facts(
        self, pages: dict[str, str]
    ) -> None:
        page = pages[PACKAGES_OUTPUT]
        found = distribution_facts(REPO_ROOT)
        assert found
        for item in found:
            assert f"\n## {item.distribution}\n" in page, item.distribution
            row = next(
                line
                for line in page.splitlines()
                if line.startswith(f"| `{item.distribution}` |")
            )
            assert f"`{item.version}`" in row
            assert f"`{item.license}`" in row
            for name in item.depends_on:
                assert f"`{name}`" in row
            if not item.depends_on:
                assert "| nothing |" in row

    def test_the_license_split_is_stated_and_counted(
        self, pages: dict[str, str]
    ) -> None:
        """The one question this page exists to answer, answered by counting."""
        found = distribution_facts(REPO_ROOT)
        tally: dict[str, int] = {}
        for item in found:
            tally[item.license] = tally.get(item.license, 0) + 1
        page = pages[PACKAGES_OUTPUT]
        if len(tally) == 1:
            # One license across every distribution is not a split, and the
            # page says so in a sentence rather than counting a split of one.
            assert f"They are all under the same license, `{sorted(tally)[0]}`." in page
        else:
            for name, count in tally.items():
                assert f"{count} under `{name}`" in page, name

    def test_the_component_counts_match_the_inventory(
        self, pages: dict[str, str], facts: tuple[Any, ...]
    ) -> None:
        page = pages[PACKAGES_OUTPUT]
        tally: dict[str, int] = {}
        for item in facts:
            tally[item.distribution] = tally.get(item.distribution, 0) + 1
        for name, count in tally.items():
            assert f"It registers {count} components" in page, name

    def test_a_distribution_with_no_license_is_refused(self, tmp_path: Path) -> None:
        """An empty license cell is the one blank this page may not have."""
        package = tmp_path / "packages" / "thing"
        package.mkdir(parents=True)
        (package / "pyproject.toml").write_text(
            '[project]\nname = "thing"\nversion = "1.0.0"\n',
            encoding="utf-8",
            newline="\n",
        )
        with pytest.raises(DocsReferenceError, match="declares no `license`"):
            distribution_facts(tmp_path)

    def test_an_empty_workspace_refuses_rather_than_claims_nothing_ships(
        self, composed: DocsBundle, facts: tuple[Any, ...]
    ) -> None:
        with pytest.raises(DocsReferenceError, match="ships nothing"):
            packages_reference(
                composed,
                distributions=(),
                components=facts,
                page=PACKAGES_OUTPUT,
                docs_root=DOCS_ROOT,
            )


# ---------------------------------------------------------------------------
# T1 — the component index
# ---------------------------------------------------------------------------


@requires_checkout
class TestTheComponentIndex:
    """Every registered component this build can address, grouped and counted."""

    def test_every_component_is_on_the_page_exactly_once(
        self, pages: dict[str, str], facts: tuple[Any, ...]
    ) -> None:
        page = pages[COMPONENT_INDEX_OUTPUT]
        listed = {
            span for span in _code_spans(page) if span.startswith("component:")
        }
        assert listed == {item.id for item in facts}
        for item in facts:
            assert page.count(f"`{item.id}`") == 1, item.id

    def test_the_page_agrees_with_the_committed_inventory(
        self, pages: dict[str, str]
    ) -> None:
        """D6's machine-readable inventory and this page are one reading.

        The inventory is a committed, byte-gated artifact; if the page
        listed a different set, one of the two would be describing a
        registry the other has never seen.
        """
        target = REPO_ROOT / DOCS_ROOT / "_generated/inventory-components.json"
        if not target.is_file():  # pragma: no cover - guarded by the marker
            pytest.skip("the components inventory has never been written")
        document = json.loads(target.read_text(encoding="utf-8"))
        listed = {
            span
            for span in _code_spans(pages[COMPONENT_INDEX_OUTPUT])
            if span.startswith("component:")
        }
        assert listed == {entry["id"] for entry in document["entries"]}
        assert f"{document['counts']['components']} of them" in pages[
            COMPONENT_INDEX_OUTPUT
        ]

    def test_every_distribution_is_a_section_with_its_own_count(
        self, pages: dict[str, str], facts: tuple[Any, ...]
    ) -> None:
        page = pages[COMPONENT_INDEX_OUTPUT]
        tally: dict[str, int] = {}
        for item in facts:
            tally[item.distribution] = tally.get(item.distribution, 0) + 1
        assert tally
        for name, count in sorted(tally.items()):
            assert f"\n## {name}\n" in page, name
            assert f"{count} of the {len(facts)} components" in page, name
        assert sum(tally.values()) == len(facts)

    def test_every_kind_and_layer_has_a_reader_word(
        self, facts: tuple[Any, ...]
    ) -> None:
        """A vocabulary this module has not heard of renders under its own
        name rather than vanishing; this is what makes the arrival of a
        new one a decision somebody takes here."""
        assert {item.kind for item in facts} <= set(KIND_WORDS)
        assert {item.layer for item in facts} <= set(LAYER_WORDS)

    def test_an_undeclared_visibility_says_so(
        self, pages: dict[str, str], facts: tuple[Any, ...]
    ) -> None:
        """Absent is not internal and it is not public."""
        undeclared = [item for item in facts if not item.visibility]
        assert undeclared, "this checkout has no undeclared visibility to render"
        assert VISIBILITY_ABSENT in pages[COMPONENT_INDEX_OUTPUT]
        assert f"{len(undeclared)} declare no visibility at all" in pages[
            COMPONENT_INDEX_OUTPUT
        ]

    def test_an_empty_reading_is_refused(self, composed: DocsBundle) -> None:
        with pytest.raises(DocsReferenceError, match="no component"):
            component_index(
                composed,
                components=(),
                page=COMPONENT_INDEX_OUTPUT,
                docs_root=DOCS_ROOT,
            )


# ---------------------------------------------------------------------------
# The renderers' "never drop a family" claims, exercised
# ---------------------------------------------------------------------------


@requires_checkout
class TestNothingIsQuietlyDropped:
    """A family nobody described is rendered ugly, never rendered away.

    Both renderers fall back rather than filter, and both fallbacks say in
    the page that nobody has written the sentence. That is the behaviour
    ``DOC_SURFACE_UNCOVERED`` exists to protect, and a renderer that
    silently dropped the unknown case would make that gate a test of
    itself — so the unknown case is planted here and the output checked.
    """

    def test_a_server_this_module_has_never_heard_of_is_still_listed(
        self, composed: DocsBundle
    ) -> None:
        import dataclasses

        channels = {channel for channel, _ in MCP_CHANNELS}
        moved = next(
            item
            for item in composed.surfaces
            if item.channel in channels
            and item.provenance.adapter_id == RUNTIME_ADAPTER
        )
        planted = dataclasses.replace(
            composed,
            surfaces=tuple(
                dataclasses.replace(
                    item,
                    provenance=dataclasses.replace(
                        item.provenance, adapter_id="a-server-nobody-described"
                    ),
                )
                if item.id == moved.id
                else item
                for item in composed.surfaces
            ),
        )
        page = mcp_reference(
            planted, mirrors=(), page=MCP_OUTPUT, docs_root=DOCS_ROOT
        )
        assert "## Served by the a-server-nobody-described reading" in page
        assert f"`{moved.id}`" in page
        assert "Nothing on this page says what this server is for" in page
        assert "shipped in ``" not in page, "an adapter id is not a distribution"

    def test_a_contract_this_module_has_never_heard_of_is_still_listed(
        self, composed: DocsBundle
    ) -> None:
        import dataclasses

        from s0ma_dsl.docs_model.records import AuthorityRef

        planted = dataclasses.replace(
            composed,
            authorities=(
                *composed.authorities,
                AuthorityRef(
                    id=f"{CONTRACT_PREFIX}late-arrival",
                    authority_class="declared",
                    source="packages/s0ma-studi0/src/s0ma_studi0/_built/studi0_server.py",
                    section="LATE_ARRIVAL",
                    content_sha256="0" * 64,
                    status="Declared; shape=unreviewed",
                    delegates=(),
                ),
            ),
        )
        page = studi0_reference(planted, page=STUDI0_OUTPUT, docs_root=DOCS_ROOT)
        assert "### The late arrival contract" in page
        assert "| `shape` | `unreviewed` |" in page
        assert "Nothing on this page says what this contract is for" in page
        assert f"{len(contracts_of(planted))} of them." in page


# ---------------------------------------------------------------------------
# T2/T3 — anchors, links, voice, canonical bytes, determinism
# ---------------------------------------------------------------------------


@requires_checkout
@pytest.mark.parametrize("relative", F4_OUTPUTS)
class TestEveryPage:
    """What all four owe a reader and the gates that will hold them."""

    def test_every_contents_entry_names_a_heading(
        self, pages: dict[str, str], relative: str
    ) -> None:
        """The page's own anchors, slugged by the gate's real slugger."""
        page = pages[relative]
        module = _script("check_links")
        anchors = set(module.document_anchors(page))
        fragments = [
            match.group("target")[1:]
            for match in module._LINK_RE.finditer(page)
            if match.group("target").startswith("#")
        ]
        assert fragments, relative
        for fragment in fragments:
            assert fragment in anchors, (relative, fragment)

    def test_every_link_names_a_tracked_path(
        self, pages: dict[str, str], relative: str
    ) -> None:
        """The unit form of the A5 gate, so a failure names the link.

        The four pages this milestone renders count as resolvable even
        before they are committed: two of them link to each other, and
        the orchestrator commits all four in the same step. Everything
        else has to be tracked today, which is the rule the A5 gate will
        apply once these pages are in its scanned set.
        """
        module = _script("check_links")
        tracked = module.tracked_files(REPO_ROOT)
        directories = module.tracked_directories(tracked)
        landing = {f"{DOCS_ROOT}/{item}" for item in F4_OUTPUTS}
        source = f"{DOCS_ROOT}/{relative}"
        targets = _links(pages[relative])
        assert targets, relative
        for target in targets:
            resolved = module._resolve(source, target.partition("#")[0])
            assert resolved is not None, (relative, target)
            assert resolved in tracked or resolved in directories or resolved in landing, (
                relative,
                target,
            )

    def test_the_authored_framing_is_in_the_products_voice(
        self, pages: dict[str, str], relative: str
    ) -> None:
        """Rule 10, over the half of each page a person wrote.

        The tables are quotations — a tool's own description, a
        component's own intent — and the voice rule deliberately does not
        reach a quotation (B4 finding 4). What it reaches is the framing:
        the headings, the sentences under them, and the legends.
        """
        authored = "\n".join(
            line
            for line in pages[relative].splitlines()
            if not line.startswith("| ") and not line.startswith("|-")
        )
        for label, pattern in FORBIDDEN_IN_AUTHORED_PROSE:
            found = pattern.search(authored)
            assert found is None, f"{relative} — {label}: {found.group(0)!r}"

    def test_the_page_is_canonical_text(
        self, pages: dict[str, str], relative: str
    ) -> None:
        content = pages[relative]
        assert "\r" not in content
        assert content.endswith("\n")
        assert not content.endswith("\n\n")
        assert str(REPO_ROOT) not in content

    def test_the_generated_note_is_on_it(
        self, pages: dict[str, str], relative: str
    ) -> None:
        """A reader who arrives at a generated page is told it is one."""
        from s0ma_dsl.docs_model.inventories import GENERATED_NOTE

        assert GENERATED_NOTE in pages[relative]


@requires_checkout
class TestDeterminism:
    """The same tree renders the same bytes, twice and across hash seeds."""

    def test_rendering_twice_produces_the_same_bytes(
        self, pages: dict[str, str]
    ) -> None:
        again = render_pages(REPO_ROOT)
        assert again == pages

    @pytest.mark.parametrize("seeds", [("0", "1")])
    def test_the_bytes_do_not_depend_on_the_hash_seed(
        self, pages: dict[str, str], seeds: tuple[str, str]
    ) -> None:
        """Set iteration order is the classic way a rendering drifts.

        Two real subprocesses with different ``PYTHONHASHSEED`` values,
        because a same-process check cannot vary the seed and the gate
        that will compare these bytes runs in a process nobody chose the
        seed for.
        """
        program = (
            "import sys;"
            f"sys.path.insert(0, {str(TESTS_DIR)!r});"
            "import test_docs_reference_surfaces as suite;"
            f"print(suite.digest_of_pages({str(REPO_ROOT)!r}))"
        )
        digests = []
        for seed in seeds:
            result = subprocess.run(  # noqa: S603 - fixed argv, no shell
                [sys.executable, "-c", program],
                cwd=REPO_ROOT,
                capture_output=True,
                text=True,
                encoding="utf-8",
                env={**_env(), "PYTHONHASHSEED": seed},
                check=False,
            )
            assert result.returncode == 0, result.stdout + result.stderr
            digests.append(result.stdout.strip().splitlines()[-1])
        assert digests[0] == digests[1]
        assert digests[0] == digest_of_pages(str(REPO_ROOT))


def _env() -> dict[str, str]:
    """The current environment, for a subprocess that must import s0ma_dsl."""
    import os

    return dict(os.environ)


# ---------------------------------------------------------------------------
# T3 — the wiring note, validated rather than reviewed
# ---------------------------------------------------------------------------


class TestTheWiringNote:
    """The catalog rows F4 hands the orchestrator, read by the real reader."""

    def test_the_rows_load_as_catalog_documents(self, tmp_path: Path) -> None:
        """Not a shape restated — the shape applied, by the catalog itself."""
        for relative in F4_OUTPUTS:
            target = tmp_path / DOCS_ROOT / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text("# placeholder\n", encoding="utf-8", newline="\n")
        catalog = tmp_path / DOCS_ROOT / "s0ma_src" / "catalog.json"
        catalog.parent.mkdir(parents=True, exist_ok=True)
        catalog.write_text(
            json.dumps(
                {
                    "documents": list(F4_CATALOG_ROWS),
                    "excluded": [],
                    "schema": CATALOG_SCHEMA,
                    "self": {
                        "audiences": ["contributor"],
                        "id": "doc:catalog/document-catalog",
                        "kind": "reference",
                        "status": "living",
                        "title": "The document catalog",
                    },
                },
                indent=2,
            )
            + "\n",
            encoding="utf-8",
            newline="\n",
        )
        provider = CatalogProvider(root=tmp_path)
        sources = {item.canonical_source for item in provider.documents()}
        # The catalog carries a row for itself, which is not F4's to write.
        assert sources - {f"{DOCS_ROOT}/s0ma_src/catalog.json"} == {
            f"{DOCS_ROOT}/{relative}" for relative in F4_OUTPUTS
        }
        rows = {row.id: row for row in provider.rows()}
        for row in F4_CATALOG_ROWS:
            loaded = rows[str(row["id"])]
            assert loaded.kind == row["kind"]
            assert loaded.status == row["status"]
            assert loaded.audiences == tuple(row["audiences"])

    def test_the_rows_stay_inside_the_closed_vocabularies(self) -> None:
        """The three enums, and the id-to-status claim the catalog enforces."""
        for row in F4_CATALOG_ROWS:
            assert row["kind"] in KINDS
            assert row["status"] in STATUSES
            assert set(row["audiences"]) <= set(AUDIENCES)
            assert row["audiences"] == sorted(row["audiences"])
            category = str(row["id"]).partition(":")[2].partition("/")[0]
            assert STATUS_BY_CATEGORY[category] == row["status"]

    def test_the_rows_are_unique_sorted_and_name_the_four_pages(self) -> None:
        identifiers = [str(row["id"]) for row in F4_CATALOG_ROWS]
        assert identifiers == sorted(identifiers)
        assert len(set(identifiers)) == len(identifiers)
        assert {str(row["canonical_source"]) for row in F4_CATALOG_ROWS} == {
            f"{DOCS_ROOT}/{relative}" for relative in F4_OUTPUTS
        }

    def test_the_titles_are_the_renderers_own_headings(self) -> None:
        """A catalog title that drifts from the H1 is two names for one page."""
        by_source = {
            str(row["canonical_source"]): str(row["title"]) for row in F4_CATALOG_ROWS
        }
        assert by_source[f"{DOCS_ROOT}/{MCP_OUTPUT}"] == MCP_TITLE
        assert by_source[f"{DOCS_ROOT}/{STUDI0_OUTPUT}"] == STUDI0_TITLE
        assert by_source[f"{DOCS_ROOT}/{PACKAGES_OUTPUT}"] == PACKAGES_TITLE
        assert (
            by_source[f"{DOCS_ROOT}/{COMPONENT_INDEX_OUTPUT}"]
            == COMPONENT_INDEX_TITLE
        )


@requires_checkout
class TestTheWiring:
    """Four outputs, wired or not wired — never half of each.

    F4 delivers the renderers and the wiring note; declaring the outputs
    is the orchestrator's step at the gate. This class is written to be
    meaningful on both sides of that step, and to be red in the one state
    that is a mistake rather than a stage: some declared and some not.
    """

    def test_the_four_are_declared_together_or_not_at_all(self) -> None:
        declared = [item for item in F4_OUTPUTS if item in STATIC_OUTPUTS]
        assert declared in ([], list(F4_OUTPUTS)), (
            f"{len(declared)} of F4's {len(F4_OUTPUTS)} outputs are declared; "
            f"a half-wired set renders pages nothing compares, or compares "
            f"pages nothing renders."
        )

    def test_a_declared_page_is_what_this_build_renders(
        self, pages: dict[str, str]
    ) -> None:
        """Once wired, the committed bytes are the rendered bytes."""
        if not all(item in STATIC_OUTPUTS for item in F4_OUTPUTS):
            pytest.skip("F4's outputs are not declared yet (orchestrator wires them)")
        for relative in F4_OUTPUTS:
            committed = REPO_ROOT / DOCS_ROOT / relative
            assert committed.is_file(), relative
            assert committed.read_text(encoding="utf-8") == pages[relative], relative
