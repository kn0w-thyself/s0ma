"""I2's completeness audit: every shipped diagnostic has a failing fixture.

Milestone I2 of the docs-function plan (internal) §14, enforcing architecture
plan §16.3 — *"every gate needs a deliberately failing fixture"* — as a
property of the repository rather than as a habit each phase remembered to
keep.

**What this module adds that the two batteries do not.** C9
(``test_docs_model_negative.py``) audits its table against the ``docs_model``
source tree; D8 (``test_docs_surfaces_negative.py``) audits its own and shakes
hands with C9's. Between them they are complete *on the tree they read* — and
that tree is not the product. Three blind spots follow, and they are this
module's whole subject:

1. **The universe is two directories.** C9 greps ``docs_model/*.py``; D8 adds
   one file. A diagnostic minted anywhere else in any shipped package — the
   emitter, the CLI, another distribution — is outside both universes and would
   be claimed by neither battery while failing no audit. Here the universe is
   every shipped source tree, plus the DSL severity registry, which is where a
   code can be armed without ever being written as a constant.
2. **Nothing checks the architecture's own table.** §11 names twenty failure
   classes and says the names are proposed. Sixteen shipped under their
   proposed name; four did not, and each of those four had a real reason —
   which is exactly the shape of decision that becomes a silently dropped
   requirement if nobody writes it down. :data:`OUT_OF_MODEL` is where they are
   written down, and every entry is held against the thing it claims exists.
3. **The two discovery contracts never met.** §9.3's seven human routes are
   registered in this package's F9 suite and §9.6's seven agent routes in
   s0ma-mcp's; each suite asserts its own seven and neither can see the other,
   so nothing held the fourteen together or against the application's own
   ledger. This module is where all three readings meet.

**Everything is derived, in both directions.** The code universe is walked out
of the source with :mod:`ast` (a self-naming ``DOC_X = "DOC_X"`` assignment is
what a diagnostic *is* here, which is what keeps the AST enum members and the
import-hook marker attributes out without a list of exclusions to maintain).
The fixture universe is read out of the two batteries' ``FIXTURES`` tables the
way D8 reads C9's — parsed, never imported, so the two readings stay
independent. The architecture table is parsed from the plan. A code minted
without a fixture, a fixture for a code that has been retired, a §11 row
nobody dispositioned, or a route added to either discovery contract all turn
this module red with the name in the message.

**What it deliberately does not do.** It does not re-prove any fixture. C9 and
D8 fire their gates and assert their findings; re-firing them here would be a
third copy of the same proof and a second place to update. This module asserts
only the *bijection* — which is the property neither battery can assert about
itself.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

from s0ma_dsl.config import SEVERITY_MATRIX
from s0ma_dsl.docs_model.application import DISCOVERY_CONTRACT
from s0ma_dsl.docs_model.validate import DEFERRED_GATES
from tests import _internal_corpus

# ---------------------------------------------------------------------------
# Where everything is read from
# ---------------------------------------------------------------------------

REPO_ROOT = Path(__file__).resolve().parents[3]

#: Every shipped source tree in this repository, found rather than listed:
#: a fifth distribution arrives in this universe by existing.
SOURCE_ROOTS: tuple[Path, ...] = tuple(
    sorted(path for path in REPO_ROOT.glob("packages/*/src") if path.is_dir())
)

#: The two negative batteries, by the table each publishes.
C_PHASE_BATTERY = Path(__file__).resolve().parent / "test_docs_model_negative.py"
D_PHASE_BATTERY = Path(__file__).resolve().parent / "test_docs_surfaces_negative.py"

#: The two discovery registries, one per package, and the constant each
#: publishes. They are in different distributions on purpose — a contract
#: about the MCP server is proven from the MCP server's own suite — which
#: is also why neither can check the other and why this module must.
HUMAN_REGISTRY = (
    Path(__file__).resolve().parent / "test_docs_discovery_contract.py",
    "HUMAN_ENTRY_POINTS",
)
AGENT_REGISTRY = (
    REPO_ROOT / "packages/s0ma-mcp/tests/test_docs_discovery_mcp.py",
    "AGENT_ENTRY_POINTS",
)

#: The architecture plan, wherever it currently lives. Plans move to
#: ``plans/complete/`` when their initiative closes, and an audit that
#: could be silenced by a file move is an audit with an expiry date.
ARCHITECTURE_PLAN_NAME = "s0ma-self-documenting-application-1.md"

#: A ``DOC_*`` name, with C9's lookbehind so a code embedded in a longer
#: identifier does not contribute a phantom.
_CODE_NAME = re.compile(r"(?<![A-Z0-9_])DOC_[A-Z][A-Z0-9_]*")


#: Where the plan may live, in the order it is looked for.
ARCHITECTURE_PLAN_PATHS = (
    f"plans/{ARCHITECTURE_PLAN_NAME}",
    f"plans/complete/{ARCHITECTURE_PLAN_NAME}",
)

#: What this audit calls it when it has to say the file is missing.
ARCHITECTURE_PLAN_WHAT = (
    "the self-documenting-application architecture plan, the authority this "
    "audit reads \u00a711 and \u00a79.3/\u00a79.6 out of"
)

requires_architecture_plan = _internal_corpus.requires_internal(
    *ARCHITECTURE_PLAN_PATHS, what=ARCHITECTURE_PLAN_WHAT
)


def architecture_plan() -> Path:
    """The architecture plan, searched for rather than pinned to one path.

    Skips the calling test when the plan is in neither place. That is not
    the same as tolerating a missing authority: a checkout that HAS the
    plan reads it and every assertion below runs at full strength. It is
    the public export, which withholds the working-note corpus, that has
    neither copy — and a skip that names the document is the honest
    answer there.
    """
    return _internal_corpus.internal_document(
        *ARCHITECTURE_PLAN_PATHS, what=ARCHITECTURE_PLAN_WHAT
    )


def arch_table_at_collection() -> tuple[str, ...]:
    """The \u00a711 table for ``parametrize``, or empty when the plan is absent.

    Parametrize arguments are evaluated at COLLECTION time, before any
    skip can fire, so this one cannot raise. Its class carries
    ``requires_architecture_plan``, so an empty tuple is only ever
    reported as a skipped class, never as a silent zero-case pass.
    """
    if not _internal_corpus.present(*ARCHITECTURE_PLAN_PATHS):
        return ()
    return arch_table()


# ---------------------------------------------------------------------------
# The code universe, derived
# ---------------------------------------------------------------------------


def shipped_codes() -> dict[str, str]:
    """Every self-naming ``DOC_*`` constant in a shipped source tree.

    Keyed by code, valued by the repository-relative module that defines
    it, so a failure can say *where* rather than only *what*.

    **Self-naming is the definition, not a heuristic.** A diagnostic in
    this repository is written ``DOC_GATE_VACUOUS = "DOC_GATE_VACUOUS"``
    and used as ``Finding(code=...)``. Reading the form rather than the
    prefix is what keeps ``DOC_REF`` and ``DOC_GUIDE`` (grammar
    declaration kinds, whose values are lowercase tokens) and
    ``DOC_REF_MARKER_ATTR`` (a dunder attribute name) out of the universe
    without an exclusion list somebody would have to maintain — and it is
    also why renaming a real code cannot hide it here.
    """
    found: dict[str, str] = {}
    for root in SOURCE_ROOTS:
        for module in sorted(root.rglob("*.py")):
            tree = ast.parse(module.read_text(encoding="utf-8"), filename=str(module))
            for node in ast.walk(tree):
                if not isinstance(node, ast.Assign | ast.AnnAssign):
                    continue
                targets = (
                    [node.target] if isinstance(node, ast.AnnAssign) else node.targets
                )
                value = node.value
                if not isinstance(value, ast.Constant) or not isinstance(
                    value.value, str
                ):
                    continue
                for target in targets:
                    if not isinstance(target, ast.Name):
                        continue
                    if not _CODE_NAME.fullmatch(target.id):
                        continue
                    if value.value != target.id:
                        continue
                    found.setdefault(
                        target.id, str(module.relative_to(REPO_ROOT))
                    )
    return found


def registered_codes() -> frozenset[str]:
    """Every ``DOC_*`` the DSL severity registry arms.

    The second half of the universe, and not a redundant one:
    ``DOC_RENDER_ERROR`` is a default argument rather than a constant, so
    it is armed, reportable and invisible to a walk that only looks for
    assignments. A registry entry that never appears as a reported code is
    the dead-registry shape ADR-013 exists to end; a reported code with no
    registry entry is the same defect from the other side.
    """
    return frozenset(name for name in SEVERITY_MATRIX if _CODE_NAME.fullmatch(name))


#: Every diagnostic this repository ships, however it is spelled.
SHIPPED = shipped_codes()
CODE_UNIVERSE = frozenset(SHIPPED) | registered_codes()


# ---------------------------------------------------------------------------
# The fixture universe, read out of the batteries
# ---------------------------------------------------------------------------


def _module_constant(path: Path, name: str) -> ast.expr:
    """One module-level assignment's value, parsed and never imported."""
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    for node in tree.body:
        if not isinstance(node, ast.Assign | ast.AnnAssign):
            continue
        targets = [node.target] if isinstance(node, ast.AnnAssign) else node.targets
        if any(
            isinstance(target, ast.Name) and target.id == name for target in targets
        ) and node.value is not None:
            return node.value
    raise AssertionError(
        f"{path.name} no longer defines a module-level {name}. This audit "
        f"reads it there; if it has moved, the audit moves with it rather "
        f"than quietly finding nothing."
    )


def fixture_claims(path: Path) -> frozenset[str]:
    """The codes one battery's ``FIXTURES`` table claims.

    Parsed the way D8 parses C9's, and for D8's reason: the keys are the
    imported ``DOC_*`` constants written as names, every such constant is
    its own spelling, and two independent readings of one tree can be
    compared where one shared reading cannot.
    """
    value = _module_constant(path, "FIXTURES")
    if not isinstance(value, ast.Dict):
        raise AssertionError(f"{path.name}'s FIXTURES is no longer a dict literal")
    return frozenset(key.id for key in value.keys if isinstance(key, ast.Name))


def fixture_tests(path: Path) -> dict[str, tuple[str, ...]]:
    """One battery's table as code to test names, for the tally."""
    value = _module_constant(path, "FIXTURES")
    assert isinstance(value, ast.Dict)
    claims: dict[str, tuple[str, ...]] = {}
    for key, entry in zip(value.keys, value.values, strict=True):
        if not isinstance(key, ast.Name):
            continue
        names = tuple(
            item.value
            for item in getattr(entry, "elts", [])
            if isinstance(item, ast.Constant) and isinstance(item.value, str)
        )
        claims[key.id] = names
    return claims


FIXTURED = fixture_claims(C_PHASE_BATTERY) | fixture_claims(D_PHASE_BATTERY)


# ---------------------------------------------------------------------------
# The architecture's own table
# ---------------------------------------------------------------------------


def arch_table() -> tuple[str, ...]:
    """The codes architecture §11's table names, in its order.

    Read from the plan rather than copied here, so a row added to the
    contract arrives as a red test naming the code instead of as a
    requirement nobody implemented.
    """
    text = architecture_plan().read_text(encoding="utf-8")
    section = text.split("## 11. Required validation rules", 1)
    if len(section) != 2:
        raise AssertionError(
            "architecture §11's heading has changed. That section is the "
            "checklist this audit walks; renaming it silently empties the "
            "checklist, which is why this raises instead."
        )
    body = section[1].split("### 11.1", 1)[0]
    found = [
        match.group(0)
        for line in body.splitlines()
        if line.startswith("| `DOC_")
        for match in [_CODE_NAME.search(line)]
        if match
    ]
    return tuple(found)


def arch_routes(heading: str) -> tuple[str, ...]:
    """One discovery contract's numbered clauses, as written.

    §9.3 and §9.6 are ordinary numbered lists in the plan; what this needs
    from them is how many there are and that they are numbered from one,
    because the ledger's clause ids are built that way.
    """
    text = architecture_plan().read_text(encoding="utf-8")
    body = text.split(heading, 1)[1].split("\n### ", 1)[0]
    return tuple(
        line.split(". ", 1)[1].strip()
        for line in body.splitlines()
        if re.match(r"^\d+\. ", line)
    )


# ---------------------------------------------------------------------------
# The four §11 names that ship as something else
# ---------------------------------------------------------------------------

#: Architecture §11's rows whose failure class ships, but not as a
#: ``DOC_*`` constant in a source tree. §11 says the names are proposed
#: and that final codes follow existing conventions; these four are where
#: that clause was actually exercised, and each entry records what the
#: class became, where its enforcement lives and what proves it.
#:
#: This is a ledger of rulings in exactly the sense
#: ``application.UNREGISTERED_HANDLERS`` is: hand-written because each row
#: is a decision somebody took, and then held against reality — every
#: ``enforcement`` path must exist, every ``proof`` symbol must be in the
#: file it names, and no entry may name a code that has since shipped as a
#: constant. An entry that stops being true fails rather than lingers.
OUT_OF_MODEL: dict[str, dict[str, str]] = {
    "DOC_MIRROR_DRIFT": {
        "disposition": "shipped as check stages, no code name",
        "enforcement": "scripts/check.py",
        "proof": "packages/s0ma-mcp/tests/test_resources.py::TestDocDrift",
        "why": (
            "Mirror drift is byte-equality between a committed copy and its "
            "canonical source, which is a question about two files rather "
            "than about a record. The model carries the correspondence as a "
            "fact (McpProvider.mirrored_documents) and the comparison runs "
            "in the pytest-mcp and selfhost-build stages of the canonical "
            "gate, where both files are in hand."
        ),
    },
    "DOC_LINK_BROKEN": {
        "disposition": "shipped as a check stage, no code name",
        "enforcement": "scripts/check_links.py",
        "proof": (
            "packages/s0ma-dsl/tests/test_check_links_script.py"
            "::test_broken_relative_link_is_red_with_file_and_line"
        ),
        "why": (
            "Phase A5 armed this over the whole repository — every tracked "
            "Markdown file, not only the documentation model's corpus — so "
            "it runs as the docs-links stage over a checkout rather than as "
            "a gate over a composed bundle. It reports VIOLATION with file "
            "and line, and its allowlist ships empty."
        ),
    },
    "DOC_DISCOVERY_BROKEN": {
        "disposition": "test-utility code, by written decision",
        "enforcement": "packages/s0ma-dsl/tests/test_docs_discovery_contract.py",
        "proof": (
            "packages/s0ma-dsl/tests/test_docs_discovery_contract.py"
            "::TestRootReadmeRoute"
        ),
        "why": (
            "The routes are properties of the running product's output — a "
            "help text, a server's instructions, a scaffolded file — which "
            "no build-time validator has in front of it. F9 wrote the "
            "reasoning down where the code is defined rather than leaving "
            "the absence to be noticed."
        ),
    },
    "DOC_CHANNEL_DIVERGENCE": {
        "disposition": "test-utility code, by written decision",
        "enforcement": "packages/s0ma-dsl/tests/test_docs_resolve_render.py",
        "proof": (
            "packages/s0ma-dsl/tests/test_docs_resolve_render.py"
            "::TestFactualMutationsGoRed"
        ),
        "why": (
            "The comparison is between renderings, not within a record: "
            "three channels' artifacts held against one topic view. The "
            "product side ships the machinery the comparison needs — the "
            "identity core, the snapshot hash on every stamp, each "
            "renderer's declared extract — and the comparator lives in the "
            "suite that mutates one channel to prove the others notice."
        ),
    },
}


#: Codes that *are* fixtured, deliberately and through a real gate, but by
#: a suite that publishes no ``FIXTURES`` table — so no completeness audit
#: reaches them.
#:
#: This is the "explained" half of bijection-or-explained, and it is a
#: third state rather than a loophole: an entry here asserts that named
#: tests in a named file fire the code, and those assertions run below. A
#: code parked here without real fixtures fails as loudly as one with none
#: at all.
#:
#: **One entry, and it is a finding as much as a disposition.**
#: ``DOC_RENDER_ERROR`` pre-dates the documentation application entirely:
#: it is the doc emitter's own diagnostic, armed in the DSL severity matrix
#: at ``error`` in every strictness mode, raised from seven sites, and
#: fired by four tests in the emitter's suite. What it has never had is a
#: row in any registry — C9's universe is ``docs_model`` and D8's adds one
#: file, so neither battery could see it and neither was wrong not to
#: claim it. The practical consequence, until this module: deleting every
#: one of those four fixtures would have left an armed, reportable
#: diagnostic with no negative proof and turned nothing red.
FIXTURED_ELSEWHERE: dict[str, dict[str, object]] = {
    "DOC_RENDER_ERROR": {
        "suite": "packages/s0ma-dsl/tests/test_derived_sources_registry.py",
        "fires": (
            "test_empty_records_are_a_failure_not_a_result",
            "test_unsorted_records_are_refused",
            "test_undeclared_format_fails_with_the_named_diagnostic",
            "test_doc_render_error_still_defaults_to_its_own_code",
        ),
        "why": (
            "The doc emitter's diagnostic, not the documentation "
            "application's: it pre-dates ADR-012, is registered in the DSL "
            "severity matrix rather than raised as a Finding, and its "
            "fixtures live beside the renderer they exercise. Moving them "
            "into a docs-model battery would separate a fixture from the "
            "subsystem it is about; recording them here keeps the audit "
            "complete without that. Whether the emitter's codes should "
            "publish a table of their own is an open question for I3."
        ),
    },
}


# ---------------------------------------------------------------------------
# The audit
# ---------------------------------------------------------------------------


class TestTheUniverseIsReal:
    """This audit's own preconditions, asserted before anything rests on them."""

    def test_it_found_the_shipped_source_trees(self) -> None:
        assert len(SOURCE_ROOTS) >= 4, [str(path) for path in SOURCE_ROOTS]
        for root in SOURCE_ROOTS:
            assert list(root.rglob("*.py")), root

    def test_the_universe_is_not_empty_and_not_everything(self) -> None:
        """A grep that matched nothing and a grep that matched all of it
        both produce an audit that cannot fail."""
        assert len(CODE_UNIVERSE) >= 20, sorted(CODE_UNIVERSE)
        assert len(CODE_UNIVERSE) < 100, sorted(CODE_UNIVERSE)

    def test_both_batteries_still_publish_a_table(self) -> None:
        assert C_PHASE_BATTERY.is_file()
        assert D_PHASE_BATTERY.is_file()
        assert len(fixture_claims(C_PHASE_BATTERY)) >= 15
        assert len(fixture_claims(D_PHASE_BATTERY)) >= 5

    def test_every_claimed_code_is_a_diagnostic_name(self) -> None:
        for code in sorted(FIXTURED | CODE_UNIVERSE):
            assert _CODE_NAME.fullmatch(code), code

    def test_the_declaration_kinds_are_not_in_the_universe(self) -> None:
        """The self-naming rule doing its job, asserted rather than assumed.

        ``DOC_REF`` and ``DOC_GUIDE`` are grammar declaration kinds and
        ``DOC_REF_MARKER_ATTR`` is an import-hook attribute name; all three
        start with the prefix and none is a diagnostic. If the rule ever
        stopped excluding them the audit would demand fixtures for things
        that cannot fail, and somebody would write them.
        """
        for name in ("DOC_REF", "DOC_GUIDE", "DOC_REF_MARKER_ATTR"):
            assert name not in CODE_UNIVERSE, name


class TestEveryShippedCodeIsFixturedOrDeferred:
    """§16.3's contract, over the whole repository at once."""

    def test_no_shipped_code_is_unaccounted_for(self) -> None:
        unclaimed = sorted(
            CODE_UNIVERSE - FIXTURED - set(DEFERRED_GATES) - set(FIXTURED_ELSEWHERE)
        )
        assert unclaimed == [], (
            f"{unclaimed} ship in this repository and neither negative "
            f"battery fires them nor does validate.DEFERRED_GATES record "
            f"them as waiting. Every gate needs a deliberately failing "
            f"fixture (architecture §16.3): add one to whichever battery "
            f"owns the phase that minted the code, and a row to its table. "
            f"Defined at: "
            f"{ {code: SHIPPED.get(code, 'severity registry') for code in unclaimed} }"
        )

    @pytest.mark.parametrize("code", sorted(FIXTURED_ELSEWHERE))
    def test_a_code_fixtured_elsewhere_really_is_fixtured_there(
        self, code: str
    ) -> None:
        """The third state carries its weight or it is not a state.

        The named suite must exist, must name every test the ledger
        claims, and must actually raise — an entry that had drifted into a
        note about a file with no fixtures left in it would be exactly the
        silence this module exists to end.
        """
        entry = FIXTURED_ELSEWHERE[code]
        suite = REPO_ROOT / str(entry["suite"])
        assert suite.is_file(), (code, entry["suite"])
        text = suite.read_text(encoding="utf-8")
        fires = entry["fires"]
        assert isinstance(fires, tuple) and fires, code
        for name in fires:
            assert f"def {name}(" in text, (code, name)
        assert "pytest.raises" in text, code
        assert code in text, (
            f"{code} is recorded as fixtured in {entry['suite']}, which "
            f"never names it. A disposition that points at a file not "
            f"about the code is a gap wearing a note."
        )
        assert len(str(entry["why"])) > 100, code
        assert code not in FIXTURED, (
            f"{code} is now claimed by a negative battery's table. Drop the "
            f"FIXTURED_ELSEWHERE entry: the third state is for codes no "
            f"table reaches, and this one is reached."
        )

    def test_no_battery_claims_a_code_that_has_been_retired(self) -> None:
        stale = sorted(FIXTURED - CODE_UNIVERSE)
        assert stale == [], (
            f"{stale} are claimed by a negative battery and ship nowhere in "
            f"this repository. Either the code was renamed — move the row — "
            f"or it was retired, and the fixture goes with it."
        )

    def test_no_code_is_both_fired_and_deferred(self) -> None:
        overlap = sorted(FIXTURED & set(DEFERRED_GATES))
        assert overlap == [], (
            f"{overlap} are fired by a battery and recorded as deferred. A "
            f"gate that has armed drops its deferral; one that has not "
            f"drops its fixture claim."
        )

    def test_every_deferred_code_says_what_it_waits_for(self) -> None:
        for code, reason in sorted(DEFERRED_GATES.items()):
            assert _CODE_NAME.fullmatch(code), code
            assert len(reason) > 40, (code, reason)

    def test_the_severity_registry_and_the_batteries_agree(self) -> None:
        """A DSL-layer code armed in the matrix has a fixture too.

        The matrix is where a code becomes reportable at a strictness
        level, so an entry there with no negative fixture is a diagnostic
        the product can emit and no test has ever seen emitted.
        """
        armed = registered_codes()
        assert armed, "the severity registry names no DOC_* code at all"
        missing = sorted(
            armed - FIXTURED - set(DEFERRED_GATES) - set(FIXTURED_ELSEWHERE)
        )
        assert missing == [], missing


@requires_architecture_plan
class TestTheArchitectureTableIsWalkedRowByRow:
    """§11's twenty rows, each dispositioned or the audit fails."""

    def test_the_table_was_actually_read(self) -> None:
        table = arch_table()
        assert len(table) == 20, table
        assert len(set(table)) == len(table), "§11 names a code twice"

    @pytest.mark.parametrize("code", arch_table_at_collection())
    def test_every_row_ships_and_is_fixtured_or_is_dispositioned(
        self, code: str
    ) -> None:
        """The checklist, one row at a time so a failure names the row."""
        if code in CODE_UNIVERSE:
            assert code in FIXTURED or code in DEFERRED_GATES, (
                f"{code} ships at {SHIPPED.get(code)} and no battery fires "
                f"it. Architecture §16.3 requires a deliberately failing "
                f"fixture for every gate."
            )
            assert code not in OUT_OF_MODEL, (
                f"{code} now ships as a constant at {SHIPPED.get(code)} and "
                f"is still recorded in OUT_OF_MODEL as shipping some other "
                f"way. Drop the entry: the ledger is for classes that did "
                f"not become codes."
            )
            return
        assert code in OUT_OF_MODEL, (
            f"architecture §11 requires {code} and this repository ships no "
            f"such diagnostic. If the class is covered under another name "
            f"or by another mechanism, record it in OUT_OF_MODEL with what "
            f"enforces it and what proves it; if it is genuinely missing, "
            f"that is a finding and not a naming question."
        )

    def test_no_disposition_names_a_row_the_table_does_not_have(self) -> None:
        surplus = sorted(set(OUT_OF_MODEL) - set(arch_table()))
        assert surplus == [], (
            f"{surplus} are dispositioned here and architecture §11 does "
            f"not ask for them. A disposition for a requirement nobody made "
            f"is a permission nobody needed."
        )

    @pytest.mark.parametrize("code", sorted(OUT_OF_MODEL))
    def test_each_disposition_points_at_something_that_exists(
        self, code: str
    ) -> None:
        entry = OUT_OF_MODEL[code]
        enforcement = REPO_ROOT / entry["enforcement"]
        assert enforcement.is_file(), (
            f"{code} is dispositioned to {entry['enforcement']}, which is "
            f"not there. A ruling that points at a deleted file is a gap "
            f"wearing a note."
        )
        path, _, symbol = entry["proof"].partition("::")
        proving = REPO_ROOT / path
        assert proving.is_file(), (code, path)
        assert symbol, f"{code}'s proof names no symbol"
        assert symbol in proving.read_text(encoding="utf-8"), (
            f"{code}'s proof names {symbol}, which {path} does not define. "
            f"Renaming a proving class without moving the ledger is how a "
            f"disposition stops meaning anything."
        )
        assert len(entry["why"]) > 100, f"{code}'s reason is too thin to review"

    def test_the_dispositioned_four_are_the_only_ones(self) -> None:
        """The count is derived from the table, not written down.

        Sixteen of §11's twenty ship as constants and four do not. Stated
        as a computation so that arming one of the four moves this
        assertion instead of leaving a sentence somebody has to notice.
        """
        table = arch_table()
        shipped = [code for code in table if code in CODE_UNIVERSE]
        elsewhere = [code for code in table if code not in CODE_UNIVERSE]
        assert sorted(elsewhere) == sorted(OUT_OF_MODEL)
        assert len(shipped) + len(elsewhere) == len(table)


@requires_architecture_plan
class TestTheTwoDiscoveryContractsAreOneLedger:
    """§9.3's seven and §9.6's seven, held together for the first time.

    Each suite asserts its own registry has seven entries and that each
    names a class it holds. Neither can see the other, and until I2
    nothing held either against the architecture's numbered lists or
    against the application's own ledger — so a route could have been
    dropped from a contract and added to no other place, and every
    existing test would still have passed.
    """

    def test_the_architecture_still_asks_for_seven_and_seven(self) -> None:
        assert len(arch_routes("### 9.3 Human discovery contract")) == 7
        assert len(arch_routes("### 9.6 Agent discovery contract")) == 7

    def test_the_application_ledger_is_fourteen_split_seven_seven(self) -> None:
        assert len(DISCOVERY_CONTRACT) == 14
        by_audience = {"human": 0, "agent": 0}
        for edge in DISCOVERY_CONTRACT:
            by_audience[edge.audience] += 1
        assert by_audience == {"human": 7, "agent": 7}

    def test_every_ledger_clause_is_a_clause_the_plan_numbers(self) -> None:
        counts = {
            "human": len(arch_routes("### 9.3 Human discovery contract")),
            "agent": len(arch_routes("### 9.6 Agent discovery contract")),
        }
        sections = {"human": "9.3", "agent": "9.6"}
        for edge in DISCOVERY_CONTRACT:
            index = int(edge.id.rsplit("-", 1)[1])
            assert 1 <= index <= counts[edge.audience], edge
            assert edge.clause == f"architecture §{sections[edge.audience]}.{index}"

    @pytest.mark.parametrize(
        ("registry", "audience"),
        [(HUMAN_REGISTRY, "human"), (AGENT_REGISTRY, "agent")],
        ids=["human", "agent"],
    )
    def test_the_ledger_names_the_classes_the_suite_registers(
        self, registry: tuple[Path, str], audience: str
    ) -> None:
        """The join nobody had made: ledger against registry, both ways."""
        path, name = registry
        assert path.is_file(), path
        value = _module_constant(path, name)
        assert isinstance(value, ast.Dict), f"{name} is no longer a dict literal"
        registered = [
            item.value
            for item in value.values
            if isinstance(item, ast.Constant) and isinstance(item.value, str)
        ]
        claimed = [
            edge.proof.rsplit("::", 1)[1]
            for edge in DISCOVERY_CONTRACT
            if edge.audience == audience
        ]
        assert sorted(claimed) == sorted(registered), (
            f"the application's discovery ledger names {sorted(claimed)} for "
            f"the {audience} contract and {path.name}'s {name} registers "
            f"{sorted(registered)}. One of them has moved; a route proven by "
            f"a class nobody runs, or run by a class nothing records, is the "
            f"failure this join exists to catch."
        )

    def test_every_proof_names_a_class_its_file_defines(self) -> None:
        for edge in DISCOVERY_CONTRACT:
            path, _, symbol = edge.proof.partition("::")
            target = REPO_ROOT / "packages" / path.replace(" ", "/")
            assert target.is_file(), (edge.id, str(target))
            assert f"class {symbol}" in target.read_text(encoding="utf-8"), edge


class TestTheTallyIsDerived:
    """The numbers I2 reports, computed here so they cannot be typed wrong."""

    def test_the_shipped_and_fixtured_counts_add_up(self) -> None:
        """Every shipped code lands in exactly one of the three states."""
        fixtured = CODE_UNIVERSE & FIXTURED
        deferred = CODE_UNIVERSE & set(DEFERRED_GATES)
        elsewhere = CODE_UNIVERSE & set(FIXTURED_ELSEWHERE)
        assert len(fixtured) + len(deferred) + len(elsewhere) == len(
            CODE_UNIVERSE
        ), sorted(CODE_UNIVERSE - fixtured - deferred - elsewhere)
        assert not fixtured & elsewhere, sorted(fixtured & elsewhere)
        assert not deferred & elsewhere, sorted(deferred & elsewhere)

    def test_exactly_one_gate_remains_deferred(self) -> None:
        """Read off the map, so arming it moves the audit and not a sentence."""
        assert sorted(DEFERRED_GATES) == ["DOC_COVERAGE_UNMENTIONED"]

    def test_every_fixtured_code_names_at_least_one_test(self) -> None:
        for battery in (C_PHASE_BATTERY, D_PHASE_BATTERY):
            for code, names in sorted(fixture_tests(battery).items()):
                assert names, f"{battery.name}: {code} maps to no test at all"
