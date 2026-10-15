"""Every diagnostic the DSL can emit, read out of its severity registries.

Milestone D2 of the docs-function plan (internal) §9, implementing the
architecture plan's §7.3 line "diagnostic registries and remediation
descriptions". These are the records a ``diagnostic:<CODE>`` topic resolves
to and the targets the F-phase deep links point at, so a build that failed
on ``BARE_IMPORT`` can hand a reader the page about ``BARE_IMPORT``.

**One source, read structurally.** Everything here comes out of
``packages/s0ma-dsl/src/s0ma_dsl/config.py``, parsed with :mod:`ast` and
read at three anchored places: the ``SEVERITY_MATRIX`` table, the
``OUT_OF_MATRIX_CODES_THAT_MUST_STILL_BE_TRACEABLE`` tuple, and the
``ERROR_CODE_DESCRIPTIONS`` map. The mode vocabulary is read from the
``StrictnessMode`` enum in the same file rather than spelled again here, so
a fifth mode arrives in the records without an edit.

Reading the *file* rather than importing the *module* is the load-bearing
choice, and it is what "derived, not copied" means in practice: point the
provider at a copy of the tree with one severity changed and the records
change with it. An import would answer from this process's own
``s0ma_dsl.config`` no matter which tree it was asked about, and the
parity proof would be a tautology. The suite still cross-checks the live
module against the live tree, which is the direction that is worth
checking: the structural reading and the running product must agree.

**Two value shapes, and nothing else.** A matrix entry is either
``dict.fromkeys(StrictnessMode, "<severity>")`` — one severity in every
mode — or a dict literal keyed by ``StrictnessMode.<MODE>``. A third shape
is refused by name rather than skipped: a diagnostic that quietly failed
to appear would be a deep link that quietly stopped resolving.

**Where the severity ladder rides, and why that is a stopgap.**
``s0ma-docs-model@1`` has no field for a per-mode severity, and this
milestone does not own ``records.py``. Rather than invent a field, the
ladder rides in ``SurfaceRecord.errors`` under one documented grammar —
the same stopgap :mod:`s0ma_dsl.docs_model.providers_repo` uses for a
package's version, and the same rule applies: :func:`fact_entries` and
:func:`fact_map` are the only supported way to write and read it, so no
consumer string-splits by hand. Architecture §6.3 defines ``errors`` as
"diagnostic/error ids or declared exception surface", and the ``diagnostic``
channel is the one channel where the first reading has no content — a
diagnostic does not cite itself — so the second reading is what the field
carries here. The cost is honest and worth writing down: the human page
labels the fact "What can go wrong", which reads as a stretch over a
severity ladder. **The model question for D8**: a diagnostic wants either a
``severity`` field inside ``@1`` or a group of its own, and until it has
one this is where the ladder lives.

**Why these are surfaces at all.**
:func:`~s0ma_dsl.docs_model.providers.group_of` classifies by record type,
not by id prefix, and the six types are the whole vocabulary — a seventh is
a schema change. Of the six, only :class:`SurfaceRecord` fits: its
``intent`` is classified ``SOURCED``, which is exactly what a quoted
description is, while every teaching field of a :class:`ConceptRecord` is
``AUTHORED_PROSE`` and a voice rule applied to a quotation makes either a
false quotation or a permanently failing gate (C1's own reason for the
distinction). So a diagnostic is a served capability on the ``diagnostic``
channel, it resolves through the ordinary topic index, and both renderers
show it without knowing this module exists.

**What is not here, and why.** No remediation text. ``config.py`` carries
one *description* per code and says so in its own words — "intentionally
one-sentence triggers (not full remediation prose)" — and the real
remediation prose lives at four hundred-odd raise sites as a
``remediation=`` argument, keyed by call site rather than by code. There is
no structural code-to-remediation registry to read, so this module emits
the description as ``intent`` and does not manufacture the rest. Recovery
prose is authored against journeys at E5/F5, where a person writes it once
and a gate resolves it.

No authority is cited. ``config.py`` is itself the authority for the
per-code severities: the numbered PRD section it used to name for them
belonged to the retired pre-monorepo s0ma-dsl PRD, and the current PRD
requires the four modes (FR-DSL-6) without enumerating what each code does
in each one. A section would not be an addressable authority id here in any
case — the repository provider indexes requirement ids, not sections — and
citing ``authority:prd/document`` for every code would be a citation nobody
could follow to the paragraph that decides. ``governed_by`` is therefore
empty, which is the honest answer until a section-addressable form exists.
"""

from __future__ import annotations

import ast
import hashlib
import re
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from s0ma_dsl.docs_model.ids import validate_id
from s0ma_dsl.docs_model.providers import (
    DocsProviderError,
    ProviderResult,
    SourcedRecord,
    sort_records,
)
from s0ma_dsl.docs_model.records import SCHEMA, Provenance, SurfaceRecord

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence
    from pathlib import Path

__all__ = [
    "CHANNEL",
    "CONFIG_SOURCE",
    "DESCRIPTIONS_NAME",
    "DIAGNOSTIC_FLOORS",
    "MATRIX_NAME",
    "MATRIX_REGISTRY",
    "MODE_ENUM",
    "NOT_APPLICABLE",
    "OUT_OF_MATRIX_NAME",
    "OUT_OF_MATRIX_REGISTRY",
    "PROVIDER_ID",
    "REGISTRY_KEY",
    "UNBOUND_EXCEPTION",
    "DiagnosticsProvider",
    "diagnostic_id",
    "digest_of",
    "fact_entries",
    "fact_map",
    "module_assignments",
    "severity_of",
    "summary_line",
]

#: This adapter's id, and the ``adapter_id`` it stamps on every record.
PROVIDER_ID = "diagnostics"

#: The one file this provider reads, repository-relative in POSIX form.
CONFIG_SOURCE = "packages/s0ma-dsl/src/s0ma_dsl/config.py"

#: The channel word every record here is served on. Not one of the
#: architecture plan's §6.3 words, which name serving mechanisms — a
#: diagnostic is not served over a mechanism, it is emitted by all of them
#: — so the channel says what the record is instead of pretending it is a
#: transport. Recorded for D8 alongside the group question above.
CHANNEL = "diagnostic"

#: The three anchored names read out of ``config.py``, and the enum the
#: mode vocabulary comes from. Named here so a rename in ``config.py``
#: produces a refusal that says which name went missing.
MATRIX_NAME = "SEVERITY_MATRIX"
OUT_OF_MATRIX_NAME = "OUT_OF_MATRIX_CODES_THAT_MUST_STILL_BE_TRACEABLE"
DESCRIPTIONS_NAME = "ERROR_CODE_DESCRIPTIONS"
MODE_ENUM = "StrictnessMode"

#: The fact key that says which registry a code was read from, and its two
#: values. A reader that meets a record with no mode facts learns why from
#: this rather than by guessing that the ladder went missing.
REGISTRY_KEY = "registry"
MATRIX_REGISTRY = "severity_matrix"
OUT_OF_MATRIX_REGISTRY = "out_of_matrix"

#: What ``None`` in the matrix is written as. The matrix uses ``None`` for
#: "this check does not run in this mode", which is a different fact from
#: "it runs and warns"; spelling it out keeps the release-only codes
#: readable — the two documentation-coverage checks are not applicable in
#: three modes and errors in the fourth, and that shape is the point of
#: them. (Their names are spelled in this module's suite rather than here:
#: C9's completeness audit greps this tree for ``DOC_``-shaped names and
#: reads one out of the middle of a longer code. See the D8 note in the
#: milestone report.)
NOT_APPLICABLE = "not_applicable"

#: Written by hand, and every record carries it. The emit sites are module
#: functions and methods inside ``s0ma_dsl`` — validator passes, parser
#: helpers, CLI pre-flight checks — and the component registry carries
#: none of them, so there is no registered component for a diagnostic
#: record to name. Binding completion is D5's milestone; until it runs,
#: this is the written reason the architecture plan's §6.3 asks for.
UNBOUND_EXCEPTION = (
    "No registered component implements a diagnostic. A code is raised "
    "from validator passes, parser helpers and command pre-flight checks "
    "that the component registry does not carry, so this record names the "
    "registry it was read from rather than a component that would have to "
    "be invented. The binding is left to the milestone that completes "
    "every surface's binding."
)

#: What a diagnostic changes: nothing. Derived rather than guessed — a
#: registry entry is a label on a report, and neither registry performs any
#: input or output — so unlike core's MCP tools, which declare no
#: annotations and therefore carry no side-effect fact at all, this one can
#: answer the question D5's ``DOC_SIDE_EFFECT_UNDECLARED`` will ask. The
#: word is the architecture plan's §6.3 vocabulary.
_SIDE_EFFECTS: tuple[str, ...] = ("none",)

#: An anti-vacuity floor for this repository. Well under the live count so
#: ordinary authoring never trips it, and far above what a provider that
#: has stopped seeing ``config.py`` produces.
DIAGNOSTIC_FLOORS: Mapping[tuple[str, str], int] = {(PROVIDER_ID, "surfaces"): 90}

#: A diagnostic code as ``config.py`` registers it. The same shape the id
#: form requires, checked here so a malformed key in the table is refused
#: where it is read rather than three functions later.
_CODE = re.compile(r"^[A-Z][A-Z0-9]*(?:_[A-Z0-9]+)*$")

#: ``<key>=<value>``, the one grammar the fact list is written in.
_FACT = re.compile(r"^(?P<key>[a-z][a-z0-9_]*)=(?P<value>.*)$")


class DiagnosticsProviderError(DocsProviderError):
    """The diagnostics provider cannot read what it was asked to read.

    A provider-contract failure rather than a documentation finding: a
    renamed registry, an unrecognized value shape or a code with no
    description are all things no author of documentation can fix, and
    continuing would produce a build that describes fewer diagnostics than
    the product emits.
    """


# ---------------------------------------------------------------------------
# The fact grammar
#
# ``<key>=<value>`` entries, sorted, one per list element. Written and read
# only through the two functions below, so the grammar has one definition —
# the rule ``providers_repo.status_line`` established for the same problem.
# ``providers_config`` writes its schema facts in this grammar too, and
# imports these rather than spelling a second copy of it.
# ---------------------------------------------------------------------------


def fact_entries(facts: Mapping[str, str]) -> tuple[str, ...]:
    """``facts`` as sorted ``<key>=<value>`` entries.

    Sorted at the source rather than at comparison time: the residue rule
    compares a list fact element by element, so two equal fact sets have to
    be one tuple or a channel that wrote them in another order would read
    as divergence.
    """
    written: list[str] = []
    for key in sorted(facts):
        value = facts[key]
        if "\n" in value or "\r" in value:
            raise DiagnosticsProviderError(
                f"the value of {key!r} spans lines; a fact is one line so a "
                f"channel can write it beside its neighbours"
            )
        if _FACT.fullmatch(f"{key}={value}") is None:
            raise DiagnosticsProviderError(
                f"{key!r} is not a fact key; a key is lowercase with "
                f"underscores and the value follows one equals sign"
            )
        written.append(f"{key}={value}")
    return tuple(written)


def fact_map(entries: Sequence[str]) -> Mapping[str, str]:
    """The facts of a record's ``errors`` list, keyed by name.

    The only supported way to read the list back. An entry that is not in
    the grammar is refused rather than skipped: a fact list holding
    something else means a second writer has appeared, and quietly dropping
    it would hide that.
    """
    found: dict[str, str] = {}
    for entry in entries:
        matched = _FACT.fullmatch(entry)
        if matched is None:
            raise DiagnosticsProviderError(
                f"{entry!r} is not a <key>=<value> fact. Every entry of this "
                f"list is written by fact_entries() and read by fact_map()."
            )
        found[matched.group("key")] = matched.group("value")
    return found


def severity_of(record: SurfaceRecord, mode: str) -> str | None:
    """The severity ``record`` carries for ``mode``, or ``None`` for none.

    ``None`` says the record records no severity for that mode, which is
    what every out-of-matrix code answers for every mode. It is not the
    same as :data:`NOT_APPLICABLE`, which is a severity the matrix states.
    """
    return fact_map(record.errors).get(mode)


def diagnostic_id(code: str) -> str:
    """The id of a diagnostic, from its code as the registry spells it."""
    if not _CODE.match(code):
        raise DiagnosticsProviderError(
            f"{code!r} is not a diagnostic code. A code is capitals, digits "
            f"and underscores, starting with a letter, exactly as it is "
            f"registered — PARSE_ERROR, MODULE_NAME_COLLISION."
        )
    identifier = f"diagnostic:{code}"
    validate_id(identifier)
    return identifier


# ---------------------------------------------------------------------------
# Reading the file
# ---------------------------------------------------------------------------


def digest_of(text: str) -> str:
    """The sha256 of ``text`` as LF-normalized UTF-8 bytes.

    The same reading ``providers_repo`` uses, for the same reason: it
    equals ``sha256sum`` of the tracked file and stays equal in a checkout
    that lost the line-feed attribute.
    """
    normalized = text.replace("\r\n", "\n").replace("\r", "\n")
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def summary_line(text: str) -> str:
    """``text`` with every run of whitespace reduced to one space.

    A description in ``config.py`` is written as adjacent string literals
    across several source lines; the value is one sentence and the line
    breaks are the file's layout, not the sentence's. Collapsing them is
    the same transformation ``resolve.collapse`` applies before comparing
    channels, so the record and the page agree by construction.
    """
    return " ".join(text.split())


def module_assignments(tree: ast.Module) -> dict[str, ast.expr]:
    """Every module-level ``NAME = <value>``, by name.

    Annotated and plain assignments both, because ``config.py`` writes the
    matrix annotated and the tuple annotated but a future registry might
    not, and a reader that saw only one form would silently miss the other.
    """
    found: dict[str, ast.expr] = {}
    for node in tree.body:
        if isinstance(node, ast.AnnAssign):
            if isinstance(node.target, ast.Name) and node.value is not None:
                found[node.target.id] = node.value
        elif isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    found[target.id] = node.value
    return found


def _named(assignments: Mapping[str, ast.expr], name: str) -> ast.expr:
    """One module-level name, refusing its absence by name."""
    try:
        return assignments[name]
    except KeyError:
        raise DiagnosticsProviderError(
            f"{CONFIG_SOURCE} declares no {name!r} at module level. This "
            f"provider reads the severity registries by name; a rename here "
            f"has to be made here too, because the alternative is a "
            f"documentation build that describes no diagnostics at all."
        ) from None


def _string(node: ast.expr, what: str) -> str:
    """The value of a string literal, refusing anything computed."""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    raise DiagnosticsProviderError(
        f"{what} in {CONFIG_SOURCE} is written as {ast.unparse(node)!r}, "
        f"which is not a plain string. This provider reads literals; a "
        f"computed registry entry would have to be read by running the "
        f"module, and a documentation build does not run the product to "
        f"find out what it says."
    )


def _enum_members(tree: ast.Module) -> dict[str, str]:
    """The mode enum's member names mapped to their values, in order.

    The one place the enum is walked. Both readings below need it: the
    ladder's mode names come from the values, and a dict-literal entry keys
    its severities on the member names.
    """
    for node in tree.body:
        if not isinstance(node, ast.ClassDef) or node.name != MODE_ENUM:
            continue
        found: dict[str, str] = {}
        for statement in node.body:
            if not isinstance(statement, ast.Assign) or len(statement.targets) != 1:
                continue
            target = statement.targets[0]
            if not isinstance(target, ast.Name):
                continue
            found[target.id] = _string(statement.value, f"{MODE_ENUM}.{target.id}")
        if not found:
            raise DiagnosticsProviderError(
                f"{MODE_ENUM} in {CONFIG_SOURCE} declares no members. The "
                f"severity ladder is read from it, and a ladder with no "
                f"rungs would make every diagnostic record say nothing."
            )
        return found
    raise DiagnosticsProviderError(
        f"{CONFIG_SOURCE} declares no {MODE_ENUM} class. The mode "
        f"vocabulary is read from it rather than repeated in the "
        f"documentation model, so a rename has to be made here too."
    )


def read_modes(tree: ast.Module) -> tuple[str, ...]:
    """The strictness modes, in the order the enum declares them.

    Read from the enum rather than spelled here, so the mode vocabulary has
    one definition. Declaration order is kept because it is the ladder's
    order — migration to release — and a reader meeting the four should
    meet them in the order the product ramps through them.
    """
    return tuple(_enum_members(tree).values())


def _member_mode(node: ast.expr, code: str, members: Mapping[str, str]) -> str:
    """The mode a ``StrictnessMode.<MODE>`` key names, refusing anything else."""
    if (
        isinstance(node, ast.Attribute)
        and isinstance(node.value, ast.Name)
        and node.value.id == MODE_ENUM
        and node.attr in members
    ):
        return members[node.attr]
    raise DiagnosticsProviderError(
        f"{code} keys its severities on {ast.unparse(node)}, which is not a "
        f"{MODE_ENUM} member this provider knows. A mode outside the enum "
        f"cannot be laddered, and guessing which one was meant would put a "
        f"severity on the wrong rung."
    )


def _severity(node: ast.expr, code: str) -> str:
    """One severity value: a string, or ``None`` written as not applicable."""
    if isinstance(node, ast.Constant) and node.value is None:
        return NOT_APPLICABLE
    return _string(node, f"the severity of {code}")


def read_matrix(tree: ast.Module) -> dict[str, dict[str, str]]:
    """``SEVERITY_MATRIX`` as ``{code: {mode: severity}}``.

    Two entry shapes are understood and a third is refused by name. The
    refusal is the point: a shape this reader does not know produces a code
    the documentation would silently stop addressing, and a deep link that
    stops resolving is worse than a build that stops.
    """
    members = _enum_members(tree)
    modes = tuple(members.values())
    node = _named(module_assignments(tree), MATRIX_NAME)
    if not isinstance(node, ast.Dict):
        raise DiagnosticsProviderError(
            f"{MATRIX_NAME} in {CONFIG_SOURCE} is not a dict literal; this "
            f"provider reads the table structurally and cannot read a "
            f"computed one."
        )
    matrix: dict[str, dict[str, str]] = {}
    for key, value in zip(node.keys, node.values, strict=True):
        if key is None:
            raise DiagnosticsProviderError(
                f"{MATRIX_NAME} in {CONFIG_SOURCE} unpacks another mapping "
                f"into itself. Every code is written out, so every code can "
                f"be found by reading the file."
            )
        code = _string(key, f"a key of {MATRIX_NAME}")
        if code in matrix:
            raise DiagnosticsProviderError(
                f"{MATRIX_NAME} registers {code} twice. One code has one "
                f"severity ladder; the later entry silently wins at import "
                f"and nothing says which one the product uses."
            )
        matrix[code] = _ladder(value, code, modes, members)
    if not matrix:
        raise DiagnosticsProviderError(
            f"{MATRIX_NAME} in {CONFIG_SOURCE} is empty. A registry that "
            f"reads empty passes every count downstream of it."
        )
    return matrix


def _ladder(
    value: ast.expr, code: str, modes: Sequence[str], members: Mapping[str, str]
) -> dict[str, str]:
    """One code's severity in every mode, from either registered shape."""
    if isinstance(value, ast.Call):
        target = ast.unparse(value.func)
        if target != "dict.fromkeys" or len(value.args) != 2:
            raise DiagnosticsProviderError(
                f"{code} is registered as {ast.unparse(value)}, which this "
                f"provider does not read. The two shapes it reads are "
                f"dict.fromkeys({MODE_ENUM}, \"<severity>\") and a dict "
                f"literal keyed by {MODE_ENUM} members."
            )
        if ast.unparse(value.args[0]) != MODE_ENUM:
            raise DiagnosticsProviderError(
                f"{code} fills its ladder from {ast.unparse(value.args[0])} "
                f"rather than from {MODE_ENUM}. A ladder over some other "
                f"set is not a severity ladder."
            )
        severity = _severity(value.args[1], code)
        return dict.fromkeys(modes, severity)
    if isinstance(value, ast.Dict):
        ladder: dict[str, str] = {}
        for key, entry in zip(value.keys, value.values, strict=True):
            if key is None:
                raise DiagnosticsProviderError(
                    f"{code} unpacks another mapping into its ladder; every "
                    f"mode is written out so every mode can be read."
                )
            ladder[_member_mode(key, code, members)] = _severity(entry, code)
        absent = sorted(set(modes) - set(ladder))
        if absent:
            raise DiagnosticsProviderError(
                f"{code} names no severity for {', '.join(absent)}. Every "
                f"mode gets an answer — a severity, or None for a check that "
                f"does not run in that mode — because a silent gap reads as "
                f"'never fires' to everything downstream."
            )
        return ladder
    raise DiagnosticsProviderError(
        f"{code} is registered as {ast.unparse(value)}, which is neither of "
        f"the two shapes this provider reads. Register it as "
        f"dict.fromkeys({MODE_ENUM}, \"<severity>\") or as a dict literal "
        f"keyed by {MODE_ENUM} members."
    )


def read_out_of_matrix(tree: ast.Module) -> tuple[str, ...]:
    """The codes that never pass through the ladder, in declaration order."""
    node = _named(module_assignments(tree), OUT_OF_MATRIX_NAME)
    if not isinstance(node, ast.Tuple | ast.List):
        raise DiagnosticsProviderError(
            f"{OUT_OF_MATRIX_NAME} in {CONFIG_SOURCE} is not a written-out "
            f"sequence; this provider reads it structurally."
        )
    return tuple(
        _string(element, f"an entry of {OUT_OF_MATRIX_NAME}") for element in node.elts
    )


def read_descriptions(tree: ast.Module) -> dict[str, str]:
    """``ERROR_CODE_DESCRIPTIONS`` as ``{code: one collapsed sentence}``."""
    node = _named(module_assignments(tree), DESCRIPTIONS_NAME)
    if not isinstance(node, ast.Dict):
        raise DiagnosticsProviderError(
            f"{DESCRIPTIONS_NAME} in {CONFIG_SOURCE} is not a dict literal; "
            f"this provider reads the table structurally."
        )
    found: dict[str, str] = {}
    for key, value in zip(node.keys, node.values, strict=True):
        if key is None:
            raise DiagnosticsProviderError(
                f"{DESCRIPTIONS_NAME} in {CONFIG_SOURCE} unpacks another "
                f"mapping into itself; every description is written out."
            )
        code = _string(key, f"a key of {DESCRIPTIONS_NAME}")
        found[code] = summary_line(_string(value, f"the description of {code}"))
    return found


# ---------------------------------------------------------------------------
# The provider
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class DiagnosticsProvider:
    """The DSL's diagnostic registries, indexed as served capabilities.

    ``root`` is the immutable input the provider contract asks for: the
    repository whose ``config.py`` the records describe, fixed when the
    provider is built. Point it at a copy with an edited matrix and the
    records describe the copy — which is how the derived-not-copied claim
    is proved rather than asserted.

    Nothing here writes, and nothing here opens a socket. The one path it
    touches is recorded repository-relative in POSIX form, so a record
    carries no trace of the machine that built it (INV-5).
    """

    root: Path
    _cache: dict[str, tuple[ast.Module, str] | None] = field(
        default_factory=dict, compare=False, repr=False
    )

    @property
    def provider_id(self) -> str:
        """This adapter's stable id."""
        return PROVIDER_ID

    def _source(self) -> tuple[ast.Module, str]:
        """``config.py`` parsed once, with the digest of the bytes read.

        Parsed once per provider so every record derived from the file
        carries the same digest by construction rather than by two readings
        agreeing. A file this provider cannot find or cannot parse is a
        refusal, not an empty result: absence is only ever "empty" for a
        source a repository may legitimately not have, and a checkout of
        this package without its own configuration module is not one.
        """
        held = self._cache.get(CONFIG_SOURCE)
        if held is not None:
            return held
        path = self.root / CONFIG_SOURCE
        if not path.is_file():
            raise DiagnosticsProviderError(
                f"{CONFIG_SOURCE} is not in this tree. The diagnostic "
                f"registries are read from that file; a build that skipped "
                f"it would describe a product that emits no diagnostics."
            )
        text = path.read_text(encoding="utf-8")
        try:
            tree = ast.parse(text)
        except SyntaxError as error:
            raise DiagnosticsProviderError(
                f"{CONFIG_SOURCE} does not parse as Python: {error}"
            ) from error
        read = (tree, digest_of(text))
        self._cache[CONFIG_SOURCE] = read
        return read

    def modes(self) -> tuple[str, ...]:
        """The strictness modes this tree declares, in ladder order."""
        return read_modes(self._source()[0])

    def codes(self) -> tuple[str, ...]:
        """Every registered code, sorted, from both registries."""
        tree = self._source()[0]
        return tuple(sorted(set(read_matrix(tree)) | set(read_out_of_matrix(tree))))

    def provide(self) -> ProviderResult:
        """Read the registries and return one record per code, sorted.

        A code registered in both places is refused here rather than left
        to the composition. Two registries claiming one code is a bug in
        ``config.py`` — the two are meant to partition the codes, and the
        meta-test in ``tests/test_doc_consistency.py`` exists to keep them
        partitioned — and reporting it as though two sources disagreed
        would point a reader at the documentation model instead.
        """
        tree, digest = self._source()
        matrix = read_matrix(tree)
        out_of_matrix = read_out_of_matrix(tree)
        descriptions = read_descriptions(tree)

        both = sorted(set(matrix) & set(out_of_matrix))
        if both:
            raise DiagnosticsProviderError(
                f"{', '.join(both)} appear in both {MATRIX_NAME} and "
                f"{OUT_OF_MATRIX_NAME}. The two registries partition the "
                f"codes: one says how a code ladders with strictness, the "
                f"other says why it cannot. A code in both has two answers."
            )
        undescribed = sorted((set(matrix) | set(out_of_matrix)) - set(descriptions))
        if undescribed:
            raise DiagnosticsProviderError(
                f"{', '.join(undescribed)} carry no entry in "
                f"{DESCRIPTIONS_NAME}. Adding a code takes three coordinated "
                f"edits and the description is the second; a record with no "
                f"description would be a topic that resolves and says "
                f"nothing."
            )

        provenance = Provenance(
            adapter_id=PROVIDER_ID,
            schema_version=SCHEMA,
            source=CONFIG_SOURCE,
            source_sha256=digest,
        )
        records: list[SourcedRecord] = []
        for code in sorted(set(matrix) | set(out_of_matrix)):
            if code in matrix:
                facts = dict(matrix[code])
                facts[REGISTRY_KEY] = MATRIX_REGISTRY
            else:
                facts = {REGISTRY_KEY: OUT_OF_MATRIX_REGISTRY}
            records.append(
                SourcedRecord.of(
                    SurfaceRecord(
                        id=diagnostic_id(code),
                        channel=CHANNEL,
                        public_name=code,
                        intent=descriptions[code],
                        component_refs=(),
                        manual_exception=UNBOUND_EXCEPTION,
                        governed_by=(),
                        side_effects=_SIDE_EFFECTS,
                        errors=fact_entries(facts),
                        provenance=provenance,
                    )
                )
            )
        return ProviderResult(provider_id=PROVIDER_ID, records=sort_records(records))
