"""The ``[tool.s0ma]`` schema, read out of the loader that enforces it.

Milestone D2 of the docs-function plan (internal) §9, implementing the
architecture plan's §7.3 line "project-configuration schema and defaults".
One record per key an author may write in ``[tool.s0ma]``, carrying the
authored type, the default, the closed value set where there is one, and
the structural rule where there is one.

**One source, read structurally.** Everything comes out of
``packages/s0ma-dsl/src/s0ma_dsl/project.py``, parsed with :mod:`ast`.
The key set is the set of keys ``S0maProject._from_tool_s0ma`` actually
reads — not a list kept beside it — so a key added to the loader appears
here without an edit, and a key removed disappears. Three call shapes are
read, and they are the three the loader uses: ``table.get("<key>", …)``,
``"<key>" in table``, and ``_parse_optional_str(table, "<key>")``.

Reading the file rather than importing the module is the same choice
:mod:`s0ma_dsl.docs_model.providers_diagnostics` makes and for the same
reason: point this provider at a copy of the tree with a key removed and
the records change with it, which is what makes "derived" a claim a proof
can settle rather than a word in a docstring.

**What each fact is derived from.**

``type``
    The authored TOML type, taken from the loader's own words. Every key
    the loader type-checks names its expected type in the error it would
    raise — ``_ensure_list_of_str`` says "list of strings",
    ``_toml_type_error(key, "table (mapping)", …)`` says so directly, and
    ``_parse_optional_str`` accepts a string. Three keys are validated
    through helpers that name no type; they carry :data:`UNSTATED` rather
    than a type transcribed by hand. The resolved *Python* type on
    :class:`~s0ma_dsl.project.S0maProject` is deliberately not used: an
    author writes ``["src"]`` in TOML and the field holds
    ``tuple[Path, ...]``, and recording the second as the key's type would
    document the loader's output as though it were its input.
``default``
    The loader's default argument where it supplies one, resolved through
    ``project.py``'s own module constants; otherwise the dataclass field's
    default. ``build_dir`` has neither and says :data:`COMPUTED`, because
    its default is derived from the project name — the rule §1.2 fact 5
    names, written out in the record's exception note.
``values``
    The closed set the loader validates against, read out of the constant
    it names. The key-to-constant citation is the one hand-written table
    here (:data:`VALUE_SETS`), and it is guarded in both directions: a
    citation whose constant has left ``project.py`` refuses the build, and
    so does a ``SUPPORTED_*`` constant that no key cites — a new closed
    set cannot arrive without this module noticing.
``rule``
    The name of the structural rule that governs the key, where one
    exists, again cited rather than inferred (:data:`RULES`) and again
    guarded: the anchor has to still be in ``project.py``.

``intent`` is the first sentence of the field's own documentation in
``project.py``, collapsed to one line. Quoting rather than rewriting is
what ``SurfaceRecord.intent``'s ``SOURCED`` classification means.

**Two things this module does not do.** It does not claim which
diagnostics a key can fire. Several of them are raised through helpers
that name no key — ``OVERLAPPING_DISCOVERY_ROOTS`` is built inside
``_format_overlapping_roots_error`` — so attributing a code to a key would
be a guess dressed as a derivation, and ``errors`` carries schema facts
instead. And it does not read ``[project]`` keys: ``requires-python`` is
a PEP 621 field the loader forwards, not something an author writes under
``[tool.s0ma]``.

**The id form was an escalation, and D5a answered it.** ``config:<key>``
is not in plan §5's frozen set: none of the forms it froze addresses a
configuration key, so D2 matched the form with a local regular
expression, said so out loud, and pinned the gap with a proof that would
fail the moment the form landed. It landed. ``config:`` is now in
:data:`~s0ma_dsl.docs_model.ids.ID_FORMS` beside ``sequence:`` — the
form C1 completed for the same reason — and this module has no matcher
of its own: :func:`config_id` calls
:func:`~s0ma_dsl.docs_model.ids.validate_id` like every other provider,
so there is exactly one account of what a configuration key id looks
like and the refusal a person meets is the model's rather than this
adapter's.

**Where the schema facts ride.** In ``SurfaceRecord.errors``, under the
grammar :mod:`s0ma_dsl.docs_model.providers_diagnostics` defines and this
module imports rather than spelling twice. That module's docstring carries
the reasoning and the model question it raises for D8; the short version
is that ``@1`` has no field for a schema fact, this milestone does not own
``records.py``, and inventing a field is a schema decision rather than a
provider's.
"""

from __future__ import annotations

import ast
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
from s0ma_dsl.docs_model.providers_diagnostics import digest_of, fact_entries, summary_line
from s0ma_dsl.docs_model.records import SCHEMA, Provenance, SurfaceRecord

if TYPE_CHECKING:
    from collections.abc import Mapping
    from pathlib import Path

__all__ = [
    "CHANNEL",
    "COMPUTED",
    "CONFIG_FLOORS",
    "LOADER",
    "MODEL_CLASS",
    "PROJECT_SOURCE",
    "PROVIDER_ID",
    "RULES",
    "TABLE",
    "UNBOUND_EXCEPTION",
    "UNSTATED",
    "VALUE_SETS",
    "ConfigProvider",
    "config_id",
    "read_keys",
]

#: This adapter's id, and the ``adapter_id`` it stamps on every record.
PROVIDER_ID = "config"

#: The one file this provider reads, repository-relative in POSIX form.
PROJECT_SOURCE = "packages/s0ma-dsl/src/s0ma_dsl/project.py"

#: The loader whose reads define the key set, and the dataclass whose
#: fields carry the documentation and the fallback defaults. Named so a
#: rename produces a refusal that says which one went missing.
LOADER = "_from_tool_s0ma"
MODEL_CLASS = "S0maProject"

#: The table an author writes these keys in, and the parameter name the
#: loader reads it through. Both appear in served names and in refusals.
TABLE = "[tool.s0ma]"
_TABLE_PARAM = "table"

#: The channel word every record here is served on. A configuration key is
#: not served over a transport; the channel says what the record is. Same
#: reading as the diagnostics provider's, and recorded for D8 with it.
CHANNEL = "config"

#: What a fact says when the loader states no type for a key, and what
#: ``default`` says for the one key whose default is computed rather than
#: written. Both are words rather than silence: an absent fact reads as an
#: oversight, and neither of these is one.
UNSTATED = "unstated"
COMPUTED = "computed"

#: The helpers the loader validates through, and the authored TOML type
#: each one asserts. Read out of the loader's own error text where the
#: helper takes it as an argument, and written here where the helper hard-
#: codes it — ``_ensure_list_of_str`` raises ``_toml_type_error(key, "list
#: of strings", value)`` in its own body, which is one indirection further
#: than this module follows.
_LIST_OF_STR = "_ensure_list_of_str"
_TYPE_ERROR = "_toml_type_error"
_OPTIONAL_STR = "_parse_optional_str"
_HELPER_TYPES: Mapping[str, str] = {
    _LIST_OF_STR: "list of strings",
    _OPTIONAL_STR: "string",
}

#: Which module constant holds each key's closed value set. A citation,
#: not a copy: the values themselves are read out of ``project.py``, and
#: :meth:`ConfigProvider.provide` refuses to run if a cited constant has
#: left the file or if the file has grown a ``SUPPORTED_`` constant no key
#: cites. The ``PRD_DELEGATIONS`` idiom, for the same reason.
VALUE_SETS: Mapping[str, str] = {
    "attribute_budgets": "SUPPORTED_ATTRIBUTE_BUDGETS",
    "authoring": "SUPPORTED_AUTHORING",
    "fixtures_format": "SUPPORTED_FIXTURE_FORMATS",
    "mode": "SUPPORTED_PROJECT_MODES",
    "test_layering": "SUPPORTED_TEST_LAYERINGS",
    "test_runner": "SUPPORTED_TEST_RUNNERS",
}

#: The prefix every closed-set constant in ``project.py`` shares. The
#: completeness guard reads it: a new ``SUPPORTED_`` constant that no key
#: cites means a key gained a closed set and this module did not notice.
_VALUE_SET_PREFIX = "SUPPORTED_"


@dataclass(frozen=True)
class _Rule:
    """One structural rule over a key: what to look for, and what it says.

    ``anchor`` is a name that must still be in ``project.py`` for the note
    to be worth reading. ``note`` is authored prose, written once here and
    carried on the record, because the rule is a sentence about the code
    and not something the code states in a form this module could quote.
    """

    anchor: str
    note: str


#: The rules worth telling an author about, each cited by an anchor the
#: provider checks. Hand-authored and guarded: a rule whose anchor has
#: left ``project.py`` stops the build rather than describing behaviour
#: the product no longer has.
RULES: Mapping[str, _Rule] = {
    "build_dir": _Rule(
        anchor="INVALID_PROJECT_NAME_FOR_BUILD_DIR",
        note=(
            "The last path component has to be a valid Python identifier. "
            "It is the import token the built modules are reached through, "
            "so a hyphen or a leading digit there produces code that "
            "transpiles cleanly and cannot be imported. Left unset, the "
            "default is the project name with every non-word character "
            "turned into an underscore and _build appended; a name that "
            "cannot be repaired that way is refused by name."
        ),
    ),
    "bootstrap_files": _Rule(
        anchor="CONFLICTING_PACKAGE_DECLARATION",
        note=(
            "A file listed here and under package_markers is refused at "
            "load time. The two lists answer different questions and one "
            "file cannot answer both."
        ),
    ),
    "package_markers": _Rule(
        anchor="CONFLICTING_PACKAGE_DECLARATION",
        note=(
            "A file listed here and under bootstrap_files is refused at "
            "load time. The two lists answer different questions and one "
            "file cannot answer both."
        ),
    ),
    "source_roots": _Rule(
        anchor="_detect_overlapping_roots",
        note=(
            "No declared root may contain another, and no two may resolve "
            "to one path. Overlapping roots make the same file discovered "
            "twice, which surfaces much later as a module colliding with "
            "itself."
        ),
    ),
    "test_roots": _Rule(
        anchor="_detect_overlapping_roots",
        note=(
            "No declared root may contain another, and no two may resolve "
            "to one path. Overlapping roots make the same file discovered "
            "twice, which surfaces much later as a module colliding with "
            "itself."
        ),
    ),
    "env": _Rule(
        anchor="_RUNBOOK_ENV_FIELDS",
        note=(
            "Each variable is its own subtable and may declare only the "
            "sub-keys the loader recognises; an unrecognised one is "
            "refused so a typo cannot silently drop the contract. The "
            "table carries contracts, never live values."
        ),
    ),
}

#: Written by hand, and every record carries it. The schema is enforced by
#: a classmethod and a handful of module helpers, none of which the
#: component registry carries, so there is no registered component for a
#: configuration record to name.
UNBOUND_EXCEPTION = (
    "No registered component implements a configuration key. The schema is "
    "enforced by the project loader and its helpers, which the component "
    "registry does not carry, so this record names the file it was read "
    "from rather than a component that would have to be invented. The "
    "binding is left to the milestone that completes every surface's "
    "binding."
)

#: What a configuration key changes on its own: nothing. It is read at
#: project load and every effect belongs to the command that acts on it.
_SIDE_EFFECTS: tuple[str, ...] = ("none",)

#: An anti-vacuity floor for this repository. Under the live count so
#: ordinary authoring never trips it, and far above what a provider that
#: has stopped seeing the loader produces.
CONFIG_FLOORS: Mapping[tuple[str, str], int] = {(PROVIDER_ID, "surfaces"): 15}

#: A sentence ends at a full stop, question or exclamation mark followed by
#: whitespace. Applied to one paragraph of authored documentation, which is
#: what the field docstrings in ``project.py`` are. Not every match is a
#: sentence end — see :data:`_ABBREVIATIONS`.
_SENTENCE = re.compile(r"(?<=[.!?])\s")

#: The abbreviations whose full stop does not end a sentence, lowercased.
#: A field docstring reaches for ``e.g.`` mid-sentence to show what a value
#: looks like — ``health_command`` and ``run_command`` both do — and a
#: splitter that stopped at the first full stop recorded half a sentence
#: ending in ``(e.g.`` as the key's whole intent. That is worse than a long
#: intent: it reads as a truncated file rather than as a short summary, and
#: it is the summary an agent channel and a generated reference page both
#: quote verbatim.
#:
#: The list is the abbreviations that occur in ordinary technical prose, not
#: the ones this repository happens to use today: a rule tuned to the
#: current contents of ``project.py`` would go wrong the first time somebody
#: wrote ``i.e.``. A genuine sentence really ending in one of these joins
#: the next sentence, which is a longer intent rather than a wrong one.
_ABBREVIATIONS: tuple[str, ...] = ("cf.", "e.g.", "etc.", "i.e.", "vs.")


class ConfigProviderError(DocsProviderError):
    """The configuration provider cannot read what it was asked to read.

    A provider-contract failure rather than a documentation finding: a
    renamed loader, a citation whose anchor has gone, or a closed value set
    nobody cites are all things no author of documentation can fix, and
    continuing would produce a build that describes a schema the product
    does not enforce.
    """


def config_id(key: str) -> str:
    """The id of a configuration key, from the key as an author writes it.

    The form is checked by :func:`~s0ma_dsl.docs_model.ids.validate_id`,
    not here: D5a added ``config:`` to the model's own table, so a key
    the form refuses raises the model's
    :class:`~s0ma_dsl.docs_model.ids.DocsIdError` with the model's own
    account of what a key looks like. Wrapping that in a provider error
    would put a second, driftable explanation of one form in the tree,
    which is the thing this milestone just removed.
    """
    identifier = f"config:{key}"
    validate_id(identifier)
    return identifier


# ---------------------------------------------------------------------------
# Reading the file
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _Key:
    """One ``[tool.s0ma]`` key as the loader reads it.

    ``default_expr`` is the loader's own default argument where it supplies
    one; ``None`` means the loader supplies none and the dataclass field's
    default is the answer.
    """

    name: str
    default_expr: ast.expr | None
    stated_type: str


def _loader(tree: ast.Module) -> ast.FunctionDef:
    """The classmethod that reads the table, refusing its absence by name."""
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == LOADER:
            return node
    raise ConfigProviderError(
        f"{PROJECT_SOURCE} declares no {LOADER}. The key set is the set of "
        f"keys that function reads; without it this provider would describe "
        f"a configuration table with no keys in it."
    )


def _model(tree: ast.Module) -> ast.ClassDef:
    """The resolved-project dataclass, refusing its absence by name."""
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and node.name == MODEL_CLASS:
            return node
    raise ConfigProviderError(
        f"{PROJECT_SOURCE} declares no {MODEL_CLASS}. Each key's "
        f"documentation and fallback default are read from its field."
    )


def _literal_key(node: ast.expr) -> str | None:
    """The value of a string-literal argument, or ``None`` for anything else."""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    return None


def read_keys(tree: ast.Module) -> dict[str, _Key]:
    """Every key the loader reads from the table, with what it says about it.

    Three call shapes, which are the three the loader uses. A key read
    twice — ``build_dir`` is read once for presence and once for its value
    — is one key: the readings are merged, the loader's default argument
    wins where any reading has one, and a stated type wins over silence.
    """
    loader = _loader(tree)
    found: dict[str, _Key] = {}

    def remember(name: str, default: ast.expr | None, stated: str) -> None:
        held = found.get(name)
        if held is None:
            found[name] = _Key(name=name, default_expr=default, stated_type=stated)
            return
        found[name] = _Key(
            name=name,
            default_expr=held.default_expr if held.default_expr is not None else default,
            stated_type=held.stated_type if held.stated_type != UNSTATED else stated,
        )

    for node in ast.walk(loader):
        if isinstance(node, ast.Compare):
            for operator, comparator in zip(node.ops, node.comparators, strict=True):
                if not isinstance(operator, ast.In):
                    continue
                if not (
                    isinstance(comparator, ast.Name) and comparator.id == _TABLE_PARAM
                ):
                    continue
                name = _literal_key(node.left)
                if name is not None:
                    remember(name, None, UNSTATED)
            continue
        if not isinstance(node, ast.Call):
            continue
        function = node.func
        if (
            isinstance(function, ast.Attribute)
            and function.attr == "get"
            and isinstance(function.value, ast.Name)
            and function.value.id == _TABLE_PARAM
            and node.args
        ):
            name = _literal_key(node.args[0])
            if name is not None:
                default = node.args[1] if len(node.args) > 1 else None
                remember(name, default, UNSTATED)
            continue
        if not isinstance(function, ast.Name):
            continue
        if (
            function.id in _HELPER_TYPES
            and len(node.args) == 2
            and function.id == _OPTIONAL_STR
            and isinstance(node.args[0], ast.Name)
            and node.args[0].id == _TABLE_PARAM
        ):
            name = _literal_key(node.args[1])
            if name is not None:
                remember(name, None, _HELPER_TYPES[function.id])
            continue
        if function.id == _LIST_OF_STR and node.args:
            name = _literal_key(node.args[0])
            if name is not None:
                remember(name, None, _HELPER_TYPES[_LIST_OF_STR])
            continue
        if function.id == _TYPE_ERROR and len(node.args) >= 2:
            name = _literal_key(node.args[0])
            stated = _literal_key(node.args[1])
            if name is not None and stated is not None:
                remember(name, None, stated)

    if not found:
        raise ConfigProviderError(
            f"{LOADER} in {PROJECT_SOURCE} reads no keys from {TABLE}. A "
            f"schema that reads empty passes every count downstream of it; "
            f"either the loader changed shape or this provider stopped "
            f"recognising how it reads."
        )
    return found


def _module_constants(tree: ast.Module) -> dict[str, ast.expr]:
    """Every module-level ``NAME = <value>`` in the file, by name."""
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


_EMPTY_FACTORIES: Mapping[str, str] = {
    "dict": "{}",
    "list": "[]",
    "set": "set()",
    "tuple": "()",
}


def _render(node: ast.expr, constants: Mapping[str, ast.expr], depth: int = 0) -> str:
    """A default expression as the value an author would meet.

    Resolved through the file's own constants where it names one, so
    ``list(DEFAULT_SOURCE_ROOTS)`` reads as ``['src']`` rather than as the
    name of something the reader would then have to go and look up. An
    expression this cannot resolve is written out as it appears in the
    source, which is still true and still traceable.
    """
    if depth > 4:  # pragma: no cover - the file nests two deep at most
        return ast.unparse(node)
    try:
        return repr(ast.literal_eval(node))
    except (ValueError, TypeError, SyntaxError, MemoryError, RecursionError):
        pass
    if isinstance(node, ast.Name) and node.id in constants:
        return _render(constants[node.id], constants, depth + 1)
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
        name = node.func.id
        if name in {"list", "tuple", "set", "frozenset"} and len(node.args) == 1:
            inner = _render(node.args[0], constants, depth + 1)
            try:
                return repr(list(ast.literal_eval(inner)))
            except (ValueError, TypeError, SyntaxError):
                return f"{name}({inner})"
        if name == "field":
            for keyword in node.keywords:
                if keyword.arg != "default_factory":
                    continue
                if isinstance(keyword.value, ast.Name):
                    written = _EMPTY_FACTORIES.get(keyword.value.id)
                    if written is not None:
                        return written
    return ast.unparse(node)


def _values(node: ast.expr, constants: Mapping[str, ast.expr], name: str) -> str:
    """A closed value set as one sorted, comma-joined fact value."""
    resolved: ast.expr = node
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.args:
        resolved = node.args[0]
    try:
        literal = ast.literal_eval(resolved)
    except (ValueError, TypeError, SyntaxError) as error:
        raise ConfigProviderError(
            f"{name} in {PROJECT_SOURCE} is not a written-out collection of "
            f"values, so this provider cannot say what a key validated "
            f"against it accepts: {error}"
        ) from error
    if not isinstance(literal, list | tuple | set | frozenset) or not all(
        isinstance(item, str) for item in literal
    ):
        raise ConfigProviderError(
            f"{name} in {PROJECT_SOURCE} does not hold a collection of "
            f"strings; a closed value set is the set of words an author may "
            f"write, and nothing else can be rendered as one."
        )
    return ",".join(sorted(str(item) for item in literal))


@dataclass(frozen=True)
class _Field:
    """One resolved-project field: its default, and its own documentation."""

    default_expr: ast.expr | None
    documentation: str


def _fields(model: ast.ClassDef) -> dict[str, _Field]:
    """Every annotated field of the dataclass, with its attribute docstring.

    An attribute docstring is the string expression immediately after the
    annotation — the convention ``project.py`` writes every field in, and
    the only documentation of a key that lives beside the key.
    """
    found: dict[str, _Field] = {}
    body = model.body
    for index, statement in enumerate(body):
        if not isinstance(statement, ast.AnnAssign):
            continue
        if not isinstance(statement.target, ast.Name):
            continue
        documentation = ""
        if index + 1 < len(body):
            following = body[index + 1]
            if (
                isinstance(following, ast.Expr)
                and isinstance(following.value, ast.Constant)
                and isinstance(following.value.value, str)
            ):
                documentation = following.value.value
        found[statement.target.id] = _Field(
            default_expr=statement.value, documentation=documentation
        )
    return found


def _first_sentence(documentation: str) -> str:
    """The first sentence of ``documentation``, collapsed to one line.

    A field's documentation runs to paragraphs of history and rationale;
    the record carries its first sentence because the whole of it stays
    reachable through the source the provenance names, and because the
    agent channel writes this fact under a byte budget.

    A full stop that belongs to an abbreviation is not a sentence end
    (:data:`_ABBREVIATIONS`). This walks the candidate boundaries in order
    and takes the first one that is really one, so ``e.g.`` in the middle
    of a sentence is passed over rather than stopped at. A paragraph with
    no sentence end at all is its own first sentence — quoting all of one
    line is the ``SOURCED`` answer; quoting the empty string is not.
    """
    paragraph = documentation.strip().split("\n\n", 1)[0]
    collapsed = summary_line(paragraph)
    if not collapsed:
        return ""
    for boundary in _SENTENCE.finditer(collapsed):
        head = collapsed[: boundary.start()]
        if head.lower().endswith(_ABBREVIATIONS):
            continue
        return head
    return collapsed


# ---------------------------------------------------------------------------
# The provider
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ConfigProvider:
    """The ``[tool.s0ma]`` schema of one checkout, indexed.

    ``root`` is the immutable input the provider contract asks for: the
    repository whose loader the records describe, fixed when the provider
    is built. Point it at a copy with a key removed and the records
    describe the copy.

    Nothing here writes, and nothing here opens a socket. The one path it
    touches is recorded repository-relative in POSIX form (INV-5).
    """

    root: Path
    _cache: dict[str, tuple[ast.Module, str, str]] = field(
        default_factory=dict, compare=False, repr=False
    )

    @property
    def provider_id(self) -> str:
        """This adapter's stable id."""
        return PROVIDER_ID

    def _source(self) -> tuple[ast.Module, str, str]:
        """``project.py`` read once: its tree, its digest, and its text.

        The text is kept rather than re-read because the anchor check runs
        over it and a second read could see different bytes from the ones
        the records were derived from — two readings of one file that can
        disagree is exactly what the digest exists to make impossible.
        """
        held = self._cache.get(PROJECT_SOURCE)
        if held is not None:
            return held
        path = self.root / PROJECT_SOURCE
        if not path.is_file():
            raise ConfigProviderError(
                f"{PROJECT_SOURCE} is not in this tree. The {TABLE} schema is "
                f"read from that file; a build that skipped it would "
                f"describe a product with nothing to configure."
            )
        text = path.read_text(encoding="utf-8")
        try:
            tree = ast.parse(text)
        except SyntaxError as error:
            raise ConfigProviderError(
                f"{PROJECT_SOURCE} does not parse as Python: {error}"
            ) from error
        read = (tree, digest_of(text), text)
        self._cache[PROJECT_SOURCE] = read
        return read

    def keys(self) -> tuple[str, ...]:
        """Every key an author may write under ``[tool.s0ma]``, sorted."""
        return tuple(sorted(read_keys(self._source()[0])))

    def _check_citations(
        self, keys: Mapping[str, _Key], constants: Mapping[str, ast.expr]
    ) -> None:
        """Both hand-written tables still point at things that are there.

        Four ways a citation goes stale, and all four stop the build rather
        than quietly describing a schema the loader no longer enforces: a
        cited key the loader no longer reads, a cited constant the file no
        longer declares, a closed value set nobody cites, and a rule whose
        anchor has left the file.
        """
        stale_keys = sorted(
            {name for name in VALUE_SETS if name not in keys}
            | {name for name in RULES if name not in keys}
        )
        if stale_keys:
            raise ConfigProviderError(
                f"{', '.join(stale_keys)} are cited here and {LOADER} no "
                f"longer reads them. A note about a key nobody can write is "
                f"documentation of something that does not exist — re-point "
                f"it at the key that carries the rule now, or drop it."
            )
        absent = sorted(
            {constant for constant in VALUE_SETS.values() if constant not in constants}
        )
        if absent:
            raise ConfigProviderError(
                f"{PROJECT_SOURCE} no longer declares {', '.join(absent)}, "
                f"and a key here cites it for its accepted values. Point the "
                f"citation at the constant that holds them now."
            )
        uncited = sorted(
            name
            for name in constants
            if name.startswith(_VALUE_SET_PREFIX) and name not in set(VALUE_SETS.values())
        )
        if uncited:
            raise ConfigProviderError(
                f"{PROJECT_SOURCE} declares {', '.join(uncited)} and no key "
                f"here cites it. A closed value set nobody documents is a "
                f"rule an author meets only by breaking it — add the key it "
                f"belongs to."
            )

    def _check_anchors(self, text: str) -> None:
        """Every rule's anchor is still written somewhere in the file."""
        missing = sorted({rule.anchor for rule in RULES.values() if rule.anchor not in text})
        if missing:
            raise ConfigProviderError(
                f"{PROJECT_SOURCE} no longer mentions {', '.join(missing)}, "
                f"and a rule recorded here cites it. A rule whose citation "
                f"has gone is a claim about behaviour the product may no "
                f"longer have."
            )

    def provide(self) -> ProviderResult:
        """Read the loader and return one record per key, sorted."""
        tree, digest, text = self._source()
        keys = read_keys(tree)
        constants = _module_constants(tree)
        fields = _fields(_model(tree))

        self._check_citations(keys, constants)
        self._check_anchors(text)

        provenance = Provenance(
            adapter_id=PROVIDER_ID,
            schema_version=SCHEMA,
            source=PROJECT_SOURCE,
            source_sha256=digest,
        )
        records: list[SourcedRecord] = []
        for name in sorted(keys):
            key = keys[name]
            held = fields.get(name)
            facts: dict[str, str] = {"type": key.stated_type}
            if key.default_expr is not None:
                facts["default"] = _render(key.default_expr, constants)
            elif held is not None and held.default_expr is not None:
                facts["default"] = _render(held.default_expr, constants)
            else:
                facts["default"] = COMPUTED
            cited = VALUE_SETS.get(name)
            if cited is not None:
                facts["values"] = _values(constants[cited], constants, cited)
            rule = RULES.get(name)
            if rule is not None:
                facts["rule"] = rule.anchor
            exception = UNBOUND_EXCEPTION if rule is None else f"{UNBOUND_EXCEPTION} {rule.note}"
            records.append(
                SourcedRecord.of(
                    SurfaceRecord(
                        id=config_id(name),
                        channel=CHANNEL,
                        public_name=f"{TABLE}.{name}",
                        intent=_first_sentence(held.documentation if held else ""),
                        component_refs=(),
                        manual_exception=summary_line(exception),
                        governed_by=(),
                        side_effects=_SIDE_EFFECTS,
                        errors=fact_entries(facts),
                        provenance=provenance,
                    )
                )
            )
        return ProviderResult(provider_id=PROVIDER_ID, records=sort_records(records))
