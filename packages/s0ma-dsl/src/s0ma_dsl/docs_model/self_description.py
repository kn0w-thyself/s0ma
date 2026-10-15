"""The one generated page whose subject is the documentation application itself.

Milestone I1 of the docs-function plan (internal) §14, and architecture plan
§15's M7 acceptance in one artifact: *the application can describe its own
adapters, validators, and outputs*. Every other generated page in this
repository describes the product. This one describes the thing that
describes the product, which is the only claim in the initiative that
cannot be met by writing a page — a hand-written account of a build's
adapters is exactly the independently maintained inventory architecture
§8.2 forbids, and it would be wrong on the first day somebody registered a
twelfth reading.

**Four sections, four readings, no fifth opinion.**

*Adapters* come from the ``ProviderResult`` sequence the composition
already produced — the same sequence H1's manifest states its
``provider_schemas`` from. A provider that did not run has no result, so
it cannot appear here; a provider that ran and produced nothing appears
with its zero, which is what :func:`~s0ma_dsl.docs_model.validate.
check_floors` is separately there to refuse.

*Validators* come from the gate callables themselves. Each one states, in
its own first line, what it checks, and names the diagnostic codes it can
report; both are quoted rather than rewritten, exactly as
:func:`~s0ma_dsl.docs_model.reference_pages_surfaces.component_index`
quotes a component's intent. The alternative — a table of gates written
here — would be a second account of a battery that already has one, and
the day a gate was added it would be a battery this page had not heard
of. Which *modules* hold gates is the application's to say and arrives as
a parameter, for the same reason
:func:`~s0ma_dsl.docs_model.application.registry` is the only place that
says which sources: the machinery knows how to read a gate, and the
application says where its gates are.

*Registered components* come from the documentation application's own
committed canonical IR — ``docs/_built/application.s0ma.json``, the file
``s0ma build --project-root docs`` emits from ``s0ma_src/application.s0ma``.
That is the same reading
:func:`~s0ma_dsl.docs_model.inventories.component_facts` makes of the two
transpiled packages, pointed at the third s0ma project in this repository:
the documentation application is written in s0ma, so what it registers
about itself is readable the way anything else written in s0ma is. It is
read rather than imported because importing it would run it, and a page
about a build is not a reason to start one.

*Outputs* come from :func:`~s0ma_dsl.docs_model.application.
generated_outputs`, which is the declared-output set the writer writes and
the checker compares — so an output on this page that no build renders is
impossible, and an output rendered but absent here is the same. What each
one *is* is not stated here either: the join is onto the catalog row whose
canonical source is that path, so a reader-facing page contributes its own
title and a machine artifact contributes the stated absence ADR-012 §2.3
rule B-2 gives it.

**No content hashes.** This page is rendered before H1's manifest, which
is the artifact that hashes every other one, and a page that quoted those
hashes would either have to be rendered after the manifest — which hashes
it — or quote hashes from the previous build. The manifest is where bytes
are accounted for; this page is where the *shape* of the build is, and the
two do not overlap by a single fact.
"""

from __future__ import annotations

import inspect
import json
import re
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from s0ma_dsl.docs_model.inventories import GENERATED_NOTE, cell
from s0ma_dsl.docs_model.manifest import artifact_format
from s0ma_dsl.docs_model.map_of_record import anchor
from s0ma_dsl.docs_model.records import DocsModelError

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping, Sequence
    from pathlib import Path
    from types import ModuleType

    from s0ma_dsl.docs_model.coverage_report import CoverageSet
    from s0ma_dsl.docs_model.providers import ProviderResult
    from s0ma_dsl.docs_model.records import DocsBundle

__all__ = [
    "COVERAGE_TITLE",
    "DOCS_APPLICATION_TITLE",
    "GATE_PREFIX",
    "ApplicationModule",
    "DocsSelfDescriptionError",
    "GateFact",
    "RegisteredComponent",
    "application_module",
    "docs_application",
    "gate_facts",
]


class DocsSelfDescriptionError(DocsModelError):
    """This page had nothing honest to say about the application."""


#: The page's title, and the heading a reader arrives at.
DOCS_APPLICATION_TITLE = "The documentation application"

#: What makes a module-level callable one of this application's gates.
#: Not a list of names: a gate added to a module this application already
#: reaches is a gate this page reports without anybody remembering to add
#: it, which is the whole difference between a derivation and an
#: inventory.
GATE_PREFIX = "check_"

#: A diagnostic code as the model spells one. Used only to read the codes
#: a gate's own docstring names — never to invent one.
_CODE = re.compile(r"\bDOC_[A-Z][A-Z0-9_]*\b")

#: A docstring's inline literal. The gates are documented in the same
#: reStructuredText the rest of this package is, where a literal is written
#: with two backticks; two backticks in Markdown is an empty code span with
#: the text stranded outside it. Quoting a line verbatim therefore means
#: quoting what it *says*, not the markup it happens to say it in — the
#: same argument :func:`~s0ma_dsl.docs_model.inventories.cell` makes about
#: an unescaped column separator.
_LITERAL = re.compile(r"``([^`]+)``")

#: What the language's declaration words are called in a sentence. A
#: declaration absent here renders under its own name, for the reason
#: :data:`~s0ma_dsl.docs_model.reference_pages_surfaces.KIND_WORDS` does:
#: the taxonomy belongs to the language and this table is a courtesy, so a
#: new declaration kind must not be able to drop a component from the page.
DECLARATION_WORDS: Mapping[str, str] = {
    "cell": "cell",
    "doc-guide": "doc-guide",
    "doc-ref": "doc-ref",
    "example": "example",
    "ganglion": "ganglion",
    "nerve": "nerve",
    "test": "test",
}

#: What an output with no catalog row says. Empty is a real answer and not
#: a gap, and which outputs give it is a rule rather than a list: ADR-012
#: §2.3 rule B-2 keeps reader-facing pages out of ``_generated/``, so
#: every output under that directory has no row *by design* and every
#: output outside it has one — the same stated absence, and the same
#: rule-not-enumeration, that H1's ``ArtifactRecord.source_document``
#: carries.
NO_DOCUMENT = "no catalog row — a machine artifact, not a page"


# ---------------------------------------------------------------------------
# The gate battery, read off the callables
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class GateFact:
    """One gate, as the gate describes itself.

    ``checks`` is the first line of its docstring and ``reports`` is every
    diagnostic code that docstring names, both taken verbatim. Neither is
    a summary written here: a gate whose stated purpose and whose real one
    have parted company is a defect in the gate, and a renderer that
    paraphrased would hide it behind a sentence of its own.
    """

    name: str
    module: str
    checks: str
    reports: tuple[str, ...]


def gate_facts(modules: Iterable[ModuleType]) -> tuple[GateFact, ...]:
    """Every gate ``modules`` hold, read off the live callables.

    A gate is a module-level function whose name starts with
    :data:`GATE_PREFIX` and which is *defined* by the module it is found
    in — the ``__module__`` test is what keeps a re-export from being
    counted twice under two names.

    Sorted by owning module and then by name, so the page's order is a
    fact about the code rather than about import order.

    Raises:
        DocsSelfDescriptionError: when a gate carries no docstring, or
            names no diagnostic code in it. Both are refusals rather than
            blank cells: a battery listed without what it reports is a
            list of function names, and this page's whole claim is that
            the application can say what its validators do.
    """
    found: dict[tuple[str, str], GateFact] = {}
    for module in modules:
        for name, value in sorted(vars(module).items()):
            if not name.startswith(GATE_PREFIX) or not inspect.isfunction(value):
                continue
            if value.__module__ != module.__name__:
                continue
            document = inspect.getdoc(value) or ""
            first = document.split("\n", 1)[0].strip()
            if not first:
                raise DocsSelfDescriptionError(
                    f"{module.__name__}.{name} is one of this application's "
                    f"gates and says nothing about itself. This page quotes a "
                    f"gate's own first line rather than describing it, so a "
                    f"gate with no docstring has no honest row here."
                )
            first = _LITERAL.sub(r"`\1`", first)
            reports = tuple(sorted(set(_CODE.findall(document))))
            if not reports:
                raise DocsSelfDescriptionError(
                    f"{module.__name__}.{name} names no diagnostic code in "
                    f"its docstring. A gate that does not say what it reports "
                    f"cannot be looked up from a failing build, which is the "
                    f"one thing a reader arrives at this page holding."
                )
            found[(module.__name__, name)] = GateFact(
                name=name,
                module=module.__name__.rpartition(".")[2],
                checks=first,
                reports=reports,
            )
    if not found:
        raise DocsSelfDescriptionError(
            "no gate was found in the modules this application named as "
            "holding its gates, so the page would report a build that "
            "validates nothing. The module list is what to check."
        )
    return tuple(found[key] for key in sorted(found))


# ---------------------------------------------------------------------------
# The application's own registered components
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class RegisteredComponent:
    """One declaration of the documentation application's own s0ma module."""

    id: str
    declaration: str
    kind: str
    visibility: str
    intent: str


@dataclass(frozen=True)
class ApplicationModule:
    """The documentation application as it registers itself.

    The same four module facts any s0ma module carries, plus what it
    declares. ``source_file`` is deliberately not among them: the IR
    records an absolute path and INV-5 keeps a machine path out of every
    rendered byte.
    """

    name: str
    layer: str
    version: str
    intent: str
    components: tuple[RegisteredComponent, ...]


def _stated(value: Any) -> str:
    """One authored field of the IR as a single line of prose.

    The transpiler wraps a resolved field as ``{"state": ..., "value":
    ...}`` and leaves a plain string where it did not have to. Both shapes
    are read; anything else is nothing this page can quote.
    """
    if isinstance(value, dict):
        inner = value.get("value")
        return " ".join(str(inner).split()) if isinstance(inner, str) else ""
    return " ".join(value.split()) if isinstance(value, str) else ""


def application_module(root: Path, *, relative: str) -> ApplicationModule:
    """The documentation application's own module, from its committed IR.

    ``relative`` is the repository-relative path of the canonical IR that
    ``s0ma build`` emits beside the source. It arrives as a parameter for
    the reason every path in this model does: the machinery knows how to
    read an IR document and the application says which one is its own.

    Raises:
        DocsSelfDescriptionError: when the IR is absent, unreadable, or
            registers nothing. An application that cannot show its own
            registrations has not described itself, and a page that said
            so with an empty table would read as an application that
            registers nothing at all.
    """
    path = root / relative
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except OSError as error:
        raise DocsSelfDescriptionError(
            f"{relative} is not in this checkout, so the documentation "
            f"application cannot read its own registrations. It is emitted by "
            f"`s0ma build --project-root docs` and committed beside the "
            f"source; if it is missing, rebuild the documentation project."
        ) from error
    except ValueError as error:
        raise DocsSelfDescriptionError(
            f"{relative} is not readable as JSON: {error}"
        ) from error
    if not isinstance(document, dict):
        raise DocsSelfDescriptionError(f"{relative} is not an IR document")

    module = document.get("module")
    if not isinstance(module, dict):
        raise DocsSelfDescriptionError(f"{relative} names no module")
    entries = document.get("components")
    if not isinstance(entries, list) or not entries:
        raise DocsSelfDescriptionError(
            f"{relative} registers nothing. The documentation application "
            f"describes itself by what it registers, and an application that "
            f"registers nothing has nothing to describe."
        )

    components: list[RegisteredComponent] = []
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        canonical = entry.get("canonical_id")
        if not isinstance(canonical, str) or "::" not in canonical:
            continue
        declaration = entry.get("declaration_type")
        kind = entry.get("kind")
        visibility = entry.get("visibility")
        components.append(
            RegisteredComponent(
                id=canonical,
                declaration=declaration if isinstance(declaration, str) else "",
                kind=kind if isinstance(kind, str) else "",
                visibility=visibility if isinstance(visibility, str) else "",
                intent=_stated(entry.get("intent")),
            )
        )
    if not components:
        raise DocsSelfDescriptionError(
            f"{relative} holds no readable declaration; every entry was "
            f"refused for want of a canonical id"
        )

    name = module.get("name")
    version = module.get("version")
    layer = module.get("layer")
    return ApplicationModule(
        name=name if isinstance(name, str) else "",
        layer=layer if isinstance(layer, str) else "",
        version=version if isinstance(version, str) else "",
        intent=_stated(module.get("intent")),
        components=tuple(sorted(components, key=lambda item: item.id)),
    )


# ---------------------------------------------------------------------------
# The page
# ---------------------------------------------------------------------------


def _link(target: str, *, page: str, docs_root: str) -> str:
    """``target`` as a link from the page at ``page`` inside ``docs_root``."""
    from posixpath import dirname, relpath

    return relpath(target, dirname(f"{docs_root}/{page}"))


def _page(lines: Sequence[str]) -> str:
    """One page's lines as its final bytes: LF-joined, one trailing newline."""
    return "\n".join(lines).rstrip("\n") + "\n"


def _contents(titles: Sequence[str]) -> list[str]:
    """The page's contents list, slugged the way its headings are."""
    return [
        "## Contents",
        "",
        *[f"- [{title}](#{anchor(title)})" for title in titles],
        "",
    ]


ADAPTERS_TITLE = "The readings"
VALIDATORS_TITLE = "The gates"
COVERAGE_TITLE = "What it covers"
COMPONENTS_TITLE = "What the application registers about itself"
OUTPUTS_TITLE = "What it writes"


def _adapter_rows(results: Sequence[ProviderResult]) -> list[str]:
    """One reading per row: what it read, and how much of the model it is."""
    lines = [
        "| Reading | Sources | Records | Groups it fills |",
        "| --- | --- | --- | --- |",
    ]
    for result in sorted(results, key=lambda item: item.provider_id):
        counts = result.counts()
        groups = ", ".join(
            f"{name} {counts[name]}" for name in sorted(counts) if counts[name]
        )
        lines.append(
            f"| `{cell(result.provider_id)}` "
            f"| {len(result.sources())} "
            f"| {len(result.records)} "
            f"| {cell(groups) if groups else '—'} |"
        )
    lines.append("")
    return lines


def _gate_rows(gates: Sequence[GateFact]) -> list[str]:
    """One gate per row, in its own words."""
    lines = [
        "| Gate | Where it lives | What it checks | What it reports |",
        "| --- | --- | --- | --- |",
    ]
    lines.extend(
        f"| `{cell(gate.name)}` "
        f"| `{cell(gate.module)}` "
        f"| {cell(gate.checks)} "
        f"| {', '.join(f'`{cell(code)}`' for code in gate.reports)} |"
        for gate in gates
    )
    lines.append("")
    return lines


def _coverage_rows(sets: Sequence[CoverageSet]) -> list[str]:
    """One required set per row, with its exceptions counted beside it.

    The exceptions are counted here and named in the report, which is the
    split the two artifacts are for: a person reading this page wants to
    know whether the number moved, and a person who has found that it did
    wants the 199 names — and a page carrying those names would be a page
    nobody reads to find out either.
    """
    lines = [
        "| Set | Required | Covered | By written exception | Not covered |",
        "| --- | --- | --- | --- | --- |",
    ]
    lines.extend(
        f"| {cell(item.name)} "
        f"| {item.required} "
        f"| {item.covered} "
        f"| {len(item.exceptions)} "
        f"| {len(item.uncovered)} |"
        for item in sets
    )
    lines.append("")
    return lines


def _ceiling_rows(sets: Sequence[CoverageSet]) -> list[str]:
    """Every ledger with a ceiling, and how much of it is spent."""
    rows = [
        (item.name, name, used, ceiling)
        for item in sets
        for name, (used, ceiling) in sorted(item.ceilings.items())
    ]
    if not rows:
        return []
    lines = [
        "| Ledger | Set | Entries | Ceiling | Headroom |",
        "| --- | --- | --- | --- | --- |",
    ]
    lines.extend(
        f"| `{cell(ledger)}` | {cell(owner)} | {used} | {ceiling} | {ceiling - used} |"
        for owner, ledger, used, ceiling in rows
    )
    lines.append("")
    return lines


def _component_rows(module: ApplicationModule) -> list[str]:
    """One declaration of the application's own module per row."""
    lines = [
        "| Declaration | Kind | Visible | What it is for |",
        "| --- | --- | --- | --- |",
    ]
    lines.extend(
        f"| `{cell(item.id)}` "
        f"({cell(DECLARATION_WORDS.get(item.declaration, item.declaration))}) "
        f"| {cell(item.kind.lower()) if item.kind else '—'} "
        f"| {cell(item.visibility.lower()) if item.visibility else 'not declared'} "
        f"| {cell(item.intent) if item.intent else '—'} |"
        for item in module.components
    )
    lines.append("")
    return lines


def _output_rows(
    outputs: Sequence[str],
    titles: Mapping[str, str],
    *,
    packaged: frozenset[str],
    media: frozenset[str],
) -> list[str]:
    """One declared output per row, in the order the build renders them."""
    lines = [
        "| Output | Format | The document it is |",
        "| --- | --- | --- |",
    ]
    for relative in outputs:
        title = titles.get(relative, "")
        lines.append(
            f"| `{cell(relative)}` "
            f"| `{cell(artifact_format(relative, packaged=packaged, media=media))}` "
            f"| {cell(title) if title else NO_DOCUMENT} |"
        )
    lines.append("")
    return lines


def docs_application(
    bundle: DocsBundle,
    *,
    results: Sequence[ProviderResult],
    gates: Sequence[GateFact],
    module: ApplicationModule,
    outputs: Sequence[str],
    decided: Sequence[str],
    packaged: frozenset[str],
    media: frozenset[str],
    coverage: Sequence[CoverageSet],
    page: str,
    docs_root: str,
) -> str:
    """The documentation application, described by the documentation application.

    Architecture §15's M7 acceptance rendered rather than asserted. Every
    argument is a reading the build already made — the provider results it
    composed, the gates it ran, the module it registers, the outputs it
    declared — for the reason the four surface references take theirs:
    a renderer that re-derived any of them could describe a build nobody
    ran, and the point of this page is that it cannot.

    ``decided`` is the subset of ``outputs`` the application names one by
    one, as against the two collections it computes. The split is the
    application's own (``STATIC_OUTPUTS`` against
    ``generated_outputs``) and arrives rather than being recomputed here,
    because a second opinion about which outputs are decisions is a second
    place the answer can change.

    Raises:
        DocsSelfDescriptionError: when a reading came back empty. A page
            claiming an application that reads nothing, gates nothing, or
            writes nothing would pass every completeness question asked
            of it, because there would be nothing to ask about.
    """
    if not results:
        raise DocsSelfDescriptionError(
            "no provider result reached this page, so it would describe a "
            "composition with no readings at all. The registry is what to "
            "check."
        )
    if not gates:
        raise DocsSelfDescriptionError(
            "no gate reached this page, so it would describe a build that "
            "validates nothing"
        )
    if not outputs:
        raise DocsSelfDescriptionError(
            "no declared output reached this page, so it would describe a "
            "build that writes nothing — including this page"
        )
    if not coverage:
        raise DocsSelfDescriptionError(
            "no coverage set reached this page, so its coverage section "
            "would be an empty table under a heading claiming completeness "
            "— which reads exactly like full coverage and is the one thing "
            "this page must not be able to say by accident"
        )

    prefix = f"{docs_root}/"
    titles = {
        record.canonical_source[len(prefix) :]: record.title
        for record in bundle.documents
        if record.canonical_source.startswith(prefix)
    }
    decided_set = set(decided)
    computed = [item for item in outputs if item not in decided_set]
    ordered_decided = [item for item in outputs if item in decided_set]
    codes = sorted({code for gate in gates for code in gate.reports})
    readings = sum(len(result.sources()) for result in results)
    records = sum(len(result.records) for result in results)

    required = sum(item.required for item in coverage)
    covered = sum(item.covered for item in coverage)
    excused = sum(len(item.exceptions) for item in coverage)
    shortfall = sum(len(item.uncovered) for item in coverage)

    inventory = f"{docs_root}/_generated/docs-manifest.json"
    to_manifest = _link(inventory, page=page, docs_root=docs_root)
    report = f"{docs_root}/_generated/coverage-report.json"
    to_report = _link(report, page=page, docs_root=docs_root)
    to_components = _link(
        f"{docs_root}/architecture/component-index.md", page=page, docs_root=docs_root
    )
    to_diagnostics = _link(
        f"{docs_root}/reference/diagnostics.md", page=page, docs_root=docs_root
    )

    lines = [
        f"# {DOCS_APPLICATION_TITLE}",
        "",
        GENERATED_NOTE,
        "",
        f"This is the page s0ma writes about the thing that writes its pages. "
        f"Everything below is read out of the build that rendered it: the "
        f"{len(results)} readings it composed the model from, the "
        f"{len(gates)} gates it ran over the result, the "
        f"{len(module.components)} declarations its own s0ma module "
        f"registers, and the {len(outputs)} files it writes — one of which "
        f"is this one.",
        "",
        "That last sentence is the point of the page. A documentation build "
        "that could not describe its own readings would be asking a reader "
        "to take on faith exactly the property the product exists to make "
        "checkable, so the account is generated from the build rather than "
        "written beside it, and it is byte-compared like every other output "
        "here.",
        "",
        f"This page describes the build stamped "
        f"`{cell(bundle.stamp.snapshot_hash)}` at version "
        f"`{cell(bundle.stamp.version_line())}`. What each of those "
        f"{len(outputs)} files came out as, with the digest of its exact "
        f"bytes, is in [`{inventory}`]({to_manifest}).",
        "",
        *_contents(
            [
                ADAPTERS_TITLE,
                VALIDATORS_TITLE,
                COVERAGE_TITLE,
                COMPONENTS_TITLE,
                OUTPUTS_TITLE,
            ]
        ),
        f"## {ADAPTERS_TITLE}",
        "",
        f"{len(results)} readings, {readings} sources between them, "
        f"{records} records composed. A reading is one adapter over one kind "
        f"of source: it is handed a checkout, it produces records that each "
        f"carry the source they came from and the digest of what was read, "
        f"and it never sees another reading's answer. The merge is the only "
        f"place they meet, and it sorts every group before the model is "
        f"built — so the order the readings run in cannot change what the "
        f"build says.",
        "",
        "**Sources** is how many distinct files or in-process readings the "
        "adapter drew on, and **Records** is how many records it "
        "contributed. **Groups it fills** names which parts of the model "
        "those records landed in, with the count in each; an adapter that "
        "fills one group is not a lesser reading than one that fills four, "
        "it is a narrower question asked completely.",
        "",
        *_adapter_rows(results),
        f"## {VALIDATORS_TITLE}",
        "",
        f"{len(gates)} gates run over every composition, and all of them run "
        f"on every build: the report is collected rather than stopped at the "
        f"first finding, so a build tells an author everything that is wrong "
        f"in one pass instead of one thing per run. Between them they can "
        f"report {len(codes)} distinct diagnostics.",
        "",
        f"**What it checks** is the gate's own first line and **What it "
        f"reports** is the codes that gate names, both quoted rather than "
        f"rewritten — a gate whose stated purpose and real one had parted "
        f"company is a defect in the gate, and a description written here "
        f"would hide it. What each code means for a reader, and what to do "
        f"about it, is on the [diagnostics page]({to_diagnostics}).",
        "",
        *_gate_rows(gates),
        f"## {COVERAGE_TITLE}",
        "",
        f"{covered} of the {required} things this build is required to "
        f"cover are covered, {excused} carry a written exception, and "
        f"{shortfall} are neither. That last number is the one to read: a "
        f"gate says nothing when it finds nothing, so a silent build and a "
        f"build whose gates were never armed look identical from outside. "
        f"This is the standing positive answer.",
        "",
        f"**By written exception** counts the members somebody has excused "
        f"in a reviewable ledger, with a reason, one at a time. Every one "
        f"of them is named — with the file its permission is written in — "
        f"in [`{report}`]({to_report}); they are counted here and listed "
        f"there because a page carrying {excused} ids is a page nobody "
        f"reads. **Not covered** is what no ledger excuses and nothing "
        f"covers, and it is the number the gates are armed to keep at "
        f"zero.",
        "",
        *_coverage_rows(coverage),
        "Two of those ledgers are bounded, and the bound is a review "
        "moment rather than a limit anybody expects to reach: an ordinary "
        "addition lands inside the headroom, and a whole new family of "
        "exceptions turns the build red before it arrives — which is when "
        "the conversation about whether it should have been an exception "
        "at all is still worth having.",
        "",
        *_ceiling_rows(coverage),
        "**How each set is measured** is stated per set in the report "
        "rather than assumed to be the same, because it is not. Four of "
        "the five are measured here; discovery is not, and says so. Its "
        "routes are properties of the running product — a help text, a "
        "server's instructions, a scaffolded file — which no build-time "
        "gate has in front of it, so the report names each route, the "
        "contract clause it comes from and the suite that runs it, and "
        "claims nothing about having checked it during the build.",
        "",
        f"## {COMPONENTS_TITLE}",
        "",
        f"The documentation application is itself written in s0ma: "
        f"`{cell(module.name)}` at version `{cell(module.version)}`, in the "
        f"{cell(module.layer.lower())} layer. It is a s0ma project the way "
        f"any application built with s0ma is one, which is why what it "
        f"registers about itself can be read here at all — the same way "
        f"every other registered component in this repository is read for "
        f"the [component index]({to_components}).",
        "",
        "What that module says it is for, in its own words:",
        "",
        f"> {cell(module.intent)}",
        "",
        *_component_rows(module),
        f"## {OUTPUTS_TITLE}",
        "",
        f"{len(outputs)} files, and the build writes exactly these: the "
        f"writer writes this set and the checker compares this set, so "
        f"neither can grow an output the other has not heard of. "
        f"{len(ordered_decided)} of them are decisions — somebody decided "
        f"this repository should commit that file — and the remaining "
        f"{len(computed)} are computed from what the build composed, "
        f"because a page per concept and a package per journey are not "
        f"choices anybody takes one file at a time.",
        "",
        "**The document it is** joins the output onto the catalog row whose "
        "canonical source is that path. An output with no row is not an "
        "uncataloged page: reader-facing pages never live under "
        "`_generated/`, so a file that does live there is a machine "
        "artifact and its stated absence of a row is the honest answer.",
        "",
        "### Decided",
        "",
        *_output_rows(ordered_decided, titles, packaged=packaged, media=media),
        "### Computed",
        "",
        *_output_rows(computed, titles, packaged=packaged, media=media),
    ]
    return _page(lines)
