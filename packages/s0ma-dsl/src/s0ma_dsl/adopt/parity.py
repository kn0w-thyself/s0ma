"""Parity — what a module promised before it was converted, kept on disk.

The retrofit ladder's hardest question is "did the conversion change
anything?". Answering it needs a record of the *original* module's
public surface, taken while the original Python file is still there, and
that record has to survive the file it describes. This module is that
store; :mod:`s0ma_dsl.adopt.surface` is the reader it stores, and the
comparer that reads both back (``compare_surfaces``, E2) lands here too.

The record — the design decision, spelled out
---------------------------------------------

One committed JSON file at the project root: ``adopt-baseline.s0ma.json``,
schema ``s0ma-adopt-baseline@1`` (retrofit rule R-3). It joins
``build.s0ma.json`` and ``adopted.s0ma.json`` in the established
``<name>.s0ma.json`` family, and it is committed for a reason the other
two do not share: **a baseline cannot be re-captured.** Once the
original ``.py`` is gone, the only surviving statement of what it
promised is this file. So it is plain text, it diffs cleanly, and every
refusal below tells the reader to restore it rather than delete it.

Deterministic bytes, because a record that churns is a record nobody
reviews: keys sorted, two-space indent, one trailing newline, LF endings,
UTF-8, paths project-relative and forward-slashed, no timestamps and no
tool version. Capturing an unchanged module again rewrites the same
bytes.

Shape::

    {
      "schema": "s0ma-adopt-baseline@1",
      "modules": {
        "bookshelf.errors": {
          "source_path": "src/bookshelf/errors.py",
          "source_hash": "sha256:...",
          "captured_surface": { "module": ..., "entries": [...], "dunder_all": [...] }
        }
      }
    }

The dotted module name is the key, so it is not repeated inside the
entry. ``source_hash`` uses the toolchain's one hashing convention
(:func:`s0ma_dsl.adoption.compute_adopted_hash`, ``sha256:`` over the
file's text) so a baseline's hash and an adopted file's hash mean the
same thing and can be compared with each other.

Additive fields ride ``@1`` — a reader that meets a field it does not
know ignores it — and an unknown schema is refused rather than guessed
at. It works in the other direction too: a field added to an entry
since a record was written reads back as ``None`` rather than refusing,
so a baseline captured by an older s0ma still loads. That is the point
of a record that cannot be recaptured. ``annotation``, the declared type
of a constant or attribute, is the first field to arrive this way.
"""

from __future__ import annotations

import json
import textwrap
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

from s0ma_dsl.adopt.model import (
    BASELINE_FILENAME,
    BASELINE_SCHEMA,
    ModuleSurface,
    ParityFinding,
    ParityResult,
    SurfaceEntry,
    dump_json,
)
from s0ma_dsl.adopt.surface import SurfaceReadError, surface_from_source
from s0ma_dsl.adoption import compute_adopted_hash

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

__all__ = [
    "BASELINE_MODULES_KEY",
    "EMITTER_ADDITIONS",
    "FINDING_PHRASES",
    "IGNORED_DECORATORS",
    "PARITY_SCHEMA",
    "BaselineEntry",
    "BaselineRecordError",
    "EmitterAddition",
    "baseline_record_path",
    "capture_baseline",
    "compare_surfaces",
    "load_baselines",
    "parity_document",
    "render_parity_text",
    "save_baselines",
    "surface_from_dict",
]


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

BASELINE_MODULES_KEY = "modules"
"""Top-level key holding the captured modules, keyed by dotted name.

Named rather than spelled out at each use, because the reader and the
writer have to agree and both are read by people checking the format.
"""


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class BaselineRecordError(Exception):
    """Raised when a baseline cannot be captured, read or written.

    A *missing* ``adopt-baseline.s0ma.json`` is not an error — it means
    no baseline has been captured yet, and :func:`load_baselines`
    returns an empty mapping.

    Every message says what happened and what to do next, so a command
    can print one without translating it.
    """


# ---------------------------------------------------------------------------
# The stored record
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class BaselineEntry:
    """One module's captured baseline: where it came from, and what it promised.

    A store-level record, not part of the shared vocabulary in
    :mod:`s0ma_dsl.adopt.model`: it exists to carry a
    :class:`~s0ma_dsl.adopt.model.ModuleSurface` together with the
    provenance that makes it trustworthy.

    * ``module`` — the dotted module the baseline is for. It is the
      record's key on disk, so :meth:`to_dict` does not repeat it.
    * ``source_path`` — project-relative POSIX path of the Python file
      the surface was read from, as it was when captured. The file may
      well be gone by the time anyone reads this.
    * ``source_hash`` — ``sha256:<hex>`` over that file's text, the same
      convention as adopted-file records, so "is this still the file I
      measured?" has an answer.
    * ``surface`` — what the module promised: the captured
      :class:`~s0ma_dsl.adopt.model.ModuleSurface`, ready to compare.
    """

    module: str
    source_path: str
    source_hash: str
    surface: ModuleSurface

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_path": self.source_path,
            "source_hash": self.source_hash,
            "captured_surface": self.surface.to_dict(),
        }


# ---------------------------------------------------------------------------
# Where the record lives
# ---------------------------------------------------------------------------


def baseline_record_path(root: Path) -> Path:
    """The parity-baselines file for a project rooted at *root*."""
    return root / BASELINE_FILENAME


# ---------------------------------------------------------------------------
# Capture
# ---------------------------------------------------------------------------


def capture_baseline(root: Path, module: str, source_path: str | Path) -> BaselineEntry:
    """Read *module*'s public surface from its Python file and return the record.

    *source_path* is the module's file, project-relative (absolute is
    accepted and recorded relative). The file is read and parsed; it is
    never imported (retrofit rule R-1).

    Capturing is a pure read: nothing is written. The caller merges the
    returned entry into what :func:`load_baselines` gave it and writes
    once with :func:`save_baselines`, so capturing many modules still
    touches the file exactly once.

    Raises :class:`BaselineRecordError` — and only that — when the
    capture is refused: the path is outside the project, is not a Python
    file, is no longer there, or cannot be read as Python.
    """
    relative = _project_relative(root, source_path)
    target = root / relative

    if target.suffix != ".py":
        raise BaselineRecordError(
            f"No baseline was captured for {module}: {relative} is not a Python file. "
            f"A baseline records what a module's Python promised before it was "
            f"converted, so it is captured from the module's .py file."
        )
    if not target.is_file():
        raise BaselineRecordError(
            f"No baseline was captured for {module}: there is no file at {relative} "
            f"any more. A baseline is the record of what the original Python "
            f"promised, so it has to be captured before that file is deleted or "
            f"replaced. Bring the file back from version control (for example "
            f"`git restore {relative}`), run `s0ma adopt baseline {module}` again, "
            f"and convert it after that."
        )

    try:
        # Read through the text entry point rather than the path one: a
        # refusal from here is printed to somebody, and it must name the
        # module and the project-relative path, never this machine's
        # absolute one.
        surface = surface_from_source(target.read_text(encoding="utf-8"), module)
        source_hash = compute_adopted_hash(target)
    except SurfaceReadError as exc:
        raise BaselineRecordError(f"No baseline was captured for {module}. {exc}") from exc
    except (OSError, UnicodeDecodeError) as exc:
        raise BaselineRecordError(
            f"No baseline was captured for {module}: {relative} could not be read "
            f"({exc}). Check the file, then try again."
        ) from exc

    return BaselineEntry(
        module=module,
        source_path=relative,
        source_hash=source_hash,
        surface=surface,
    )


def _project_relative(root: Path, source_path: str | Path) -> str:
    """*source_path* as a project-relative POSIX path, or a refusal.

    Records never hold an absolute machine path: they are committed and
    read on other people's machines. Anything that resolves outside the
    project is refused rather than quietly rewritten.
    """
    candidate = Path(source_path)
    base = root.resolve()
    absolute = candidate.resolve() if candidate.is_absolute() else (base / candidate).resolve()
    try:
        return absolute.relative_to(base).as_posix()
    except ValueError as exc:
        raise BaselineRecordError(
            f"{candidate.as_posix()} is outside this project, so no baseline can be "
            f"captured for it. A baseline belongs to the project whose file it "
            f"describes; give a path inside the project and try again."
        ) from exc


# ---------------------------------------------------------------------------
# Load
# ---------------------------------------------------------------------------


def load_baselines(root: Path) -> dict[str, BaselineEntry]:
    """Read the project's captured baselines, keyed by dotted module name.

    Returns an empty dict when there is no ``adopt-baseline.s0ma.json``
    — nothing captured yet, the state every project starts in. Keys come
    back sorted, so a caller that iterates prints modules in a stable
    order.

    Raises :class:`BaselineRecordError` when the file is there but
    cannot be trusted: unreadable, not the shape s0ma writes, or written
    to a schema this version does not know.
    """
    record_path = baseline_record_path(root)
    if not record_path.is_file():
        return {}

    try:
        raw = json.loads(record_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise BaselineRecordError(_malformed(f"it is not readable JSON — {exc}")) from exc
    except (OSError, UnicodeDecodeError) as exc:
        raise BaselineRecordError(
            f"The parity baselines file {BASELINE_FILENAME} could not be read "
            f"({exc}). Check the file's permissions, then try again."
        ) from exc

    document = _as_mapping(raw, where="the file")
    schema = document.get("schema")
    if schema != BASELINE_SCHEMA:
        raise BaselineRecordError(
            f"The parity baselines file {BASELINE_FILENAME} is written in the format "
            f"{schema!r}, and this version of s0ma reads {BASELINE_SCHEMA!r}. Use the "
            f"version of s0ma that wrote it, or capture the baselines again with "
            f"`s0ma adopt baseline --all` while the original Python files are still "
            f"there. Do not delete the file: it may be the only surviving record of "
            f"what those modules promised."
        )

    modules = _as_mapping(
        document.get(BASELINE_MODULES_KEY, {}), where=f"its '{BASELINE_MODULES_KEY}' entry",
    )
    entries: dict[str, BaselineEntry] = {}
    for module in sorted(modules):
        entries[module] = _entry_from_dict(module, modules[module])
    return entries


def _entry_from_dict(module: str, data: object) -> BaselineEntry:
    """One stored entry, checked field by field."""
    where = f"the entry for {module!r}"
    body = _as_mapping(data, where=where)
    return BaselineEntry(
        module=module,
        source_path=_as_str(body.get("source_path"), where=f"'source_path' in {where}"),
        source_hash=_as_str(body.get("source_hash"), where=f"'source_hash' in {where}"),
        surface=_surface_from_dict(
            body.get("captured_surface"), where=f"the captured surface in {where}",
        ),
    )


def surface_from_dict(data: Mapping[str, Any]) -> ModuleSurface:
    """Turn a stored ``captured_surface`` dict back into a :class:`ModuleSurface`.

    The exact inverse of :meth:`ModuleSurface.to_dict`, and the way a
    comparer reads a baseline back. Fields it does not recognise are
    ignored, which is what lets an additive change ride the ``@1``
    schema. Entries come back sorted by name, so a hand-edited file
    still yields a surface with the ordering the rest of the tool
    assumes.

    Raises :class:`BaselineRecordError` when the shape is wrong.
    """
    return _surface_from_dict(data, where="the captured surface")


def _surface_from_dict(data: object, *, where: str) -> ModuleSurface:
    body = _as_mapping(data, where=where)
    raw_entries = body.get("entries")
    if not isinstance(raw_entries, list):
        raise BaselineRecordError(_malformed(f"'entries' in {where} should be a list"))
    entries = tuple(
        sorted(
            (
                _entry_surface_from_dict(item, where=where)
                for item in raw_entries
            ),
            key=lambda entry: entry.name,
        )
    )
    dunder_all_raw = body.get("dunder_all")
    dunder_all = (
        None
        if dunder_all_raw is None
        else _as_str_tuple(dunder_all_raw, where=f"'dunder_all' in {where}")
    )
    return ModuleSurface(
        module=_as_str(body.get("module"), where=f"'module' in {where}"),
        entries=entries,
        dunder_all=dunder_all,
    )


def _entry_surface_from_dict(data: object, *, where: str) -> SurfaceEntry:
    body = _as_mapping(data, where=f"an entry in {where}")
    name = _as_str(body.get("name"), where=f"'name' on an entry in {where}")
    place = f"{name!r} in {where}"
    return SurfaceEntry(
        name=name,
        category=_as_str(body.get("category"), where=f"'category' on {place}"),
        signature=_as_optional_str(body.get("signature"), where=f"'signature' on {place}"),
        # Absent in every record written before declared types joined the
        # surface. Missing reads as None — the same value the reader
        # gives a name that never declared one — so an older baseline
        # loads and compares without being recaptured, which matters
        # because the Python it describes may be gone.
        annotation=_as_optional_str(body.get("annotation"), where=f"'annotation' on {place}"),
        decorators=_as_str_tuple(body.get("decorators"), where=f"'decorators' on {place}"),
        bases=_as_str_tuple(body.get("bases"), where=f"'bases' on {place}"),
        docstring=_as_optional_str(body.get("docstring"), where=f"'docstring' on {place}"),
        value=_as_optional_str(body.get("value"), where=f"'value' on {place}"),
    )


# ---------------------------------------------------------------------------
# Save
# ---------------------------------------------------------------------------


def save_baselines(root: Path, entries: Mapping[str, BaselineEntry]) -> Path:
    """Write *entries* to the project's ``adopt-baseline.s0ma.json``; return its path.

    One file, at the project root, and nothing else. The bytes are
    deterministic — sorted keys, two-space indent, one trailing newline,
    LF endings, UTF-8 — so writing the same baselines twice produces a
    byte-identical file and an unchanged capture diffs empty on every
    platform.

    An empty mapping still writes a valid record: "no baselines yet" is
    a reviewable state, and deleting the file is the author's call, not
    the tool's.
    """
    for module, entry in entries.items():
        if entry.module != module:
            raise BaselineRecordError(
                f"The baseline filed under {module!r} says it is for "
                f"{entry.module!r}. Each baseline is filed under the module it was "
                f"captured from; this one cannot be written until that is sorted out."
            )

    record_path = baseline_record_path(root)
    document = {
        "schema": BASELINE_SCHEMA,
        BASELINE_MODULES_KEY: {
            module: entries[module].to_dict() for module in sorted(entries)
        },
    }
    try:
        record_path.write_text(dump_json(document), encoding="utf-8", newline="\n")
    except OSError as exc:
        raise BaselineRecordError(
            f"The parity baselines could not be written to {BASELINE_FILENAME} "
            f"({exc.strerror or exc}). Check that the project folder is writable, "
            f"then try again."
        ) from exc
    return record_path


# ---------------------------------------------------------------------------
# Reading a record defensively
#
# The file is committed, hand-editable and irreplaceable, so every check
# below refuses with one sentence about what is wrong and one about what
# to do — never a traceback, and never advice to delete it.
# ---------------------------------------------------------------------------


def _malformed(detail: str) -> str:
    """The standard refusal for a record that is not the shape s0ma writes."""
    return (
        f"The parity baselines file {BASELINE_FILENAME} is not in the shape s0ma "
        f"writes: {detail}. Restore it from version control rather than deleting it — "
        f"a baseline records what a module promised before it was converted, and it "
        f"cannot be captured again once the original Python file is gone."
    )


def _as_mapping(value: object, *, where: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise BaselineRecordError(_malformed(f"{where} should be a JSON object"))
    return value


def _as_str(value: object, *, where: str) -> str:
    if not isinstance(value, str):
        raise BaselineRecordError(_malformed(f"{where} should be text"))
    return value


def _as_optional_str(value: object, *, where: str) -> str | None:
    if value is None or isinstance(value, str):
        return value
    raise BaselineRecordError(_malformed(f"{where} should be text or null"))


def _as_str_tuple(value: object, *, where: str) -> tuple[str, ...]:
    if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
        raise BaselineRecordError(_malformed(f"{where} should be a list of text"))
    return tuple(value)


# ---------------------------------------------------------------------------
# Compare (E2)
#
# ``compare_surfaces(baseline, built) -> ParityResult`` lands here, with
# the ignore list for what the emitter adds around an authored body.
# Everything above is the store it reads from.
# ---------------------------------------------------------------------------


PARITY_SCHEMA = "s0ma-adopt-parity@1"
"""Schema string of the machine-readable parity verdict.

``s0ma adopt verify-parity --format json`` prints a document carrying
this string, in the same ``<family>@<major>`` style as
:data:`~s0ma_dsl.adopt.model.SCAN_SCHEMA` and
:data:`~s0ma_dsl.adopt.model.BASELINE_SCHEMA`. A field added later rides
``@1``; ``@2`` is reserved for a change that breaks a reader.
"""


@dataclass(frozen=True, slots=True)
class EmitterAddition:
    """One thing ``s0ma build`` writes around an authored body, and what parity does about it.

    The comparer's promise is narrow and has to stay narrow: *ignore what
    the emitter adds, and only that*. Everything in
    :data:`EMITTER_ADDITIONS` was read out of really emitted modules —
    the s0ma authoring server's own ``_built/`` tree, and conversions of
    the brownfield fixture — rather than guessed at from the emitter's
    source, so the list describes what a user's build actually produces.

    * ``construct`` — the emitted thing, named the way it appears in a
      generated file.
    * ``decorator`` — the decorator name to drop from a captured entry
      when this addition is a decorator, else ``None``. It is the
      operative field: :func:`compare_surfaces` reads the set of names
      off this tuple rather than repeating them, so the list and the
      behaviour cannot drift apart.
    * ``why`` — one sentence saying why ignoring it is honest: an
      addition is only safe to ignore when no caller of the module could
      have depended on its absence.
    """

    construct: str
    decorator: str | None
    why: str


EMITTER_ADDITIONS: tuple[EmitterAddition, ...] = (
    EmitterAddition(
        construct="@component(...)",
        decorator="component",
        why=(
            "The registration decorator the emitter writes above every nerve and "
            "every cell it emits, carrying the declaration's authored name, kind, "
            "layer, intent and metadata. It is how the module tells the running "
            "self-model what is in it; it does not change how the thing it sits on "
            "is called, so it is not part of the surface a caller depends on. Every "
            "other decorator — including one a person wrote that happens to be a "
            "call — is compared."
        ),
    ),
    EmitterAddition(
        construct="the generated __all__ and its ordering",
        decorator=None,
        why=(
            "The emitter writes __all__ itself, in the order of the module header's "
            "`exports:` list, which is the order the declarations were drafted in "
            "rather than the order the Python file happened to use. Order is not a "
            "promise to anybody, so it is ignored; membership is, so a name that "
            "joins or leaves the exported set is reported like any other difference."
        ),
    ),
    EmitterAddition(
        construct="the generated module docstring, hash headers and source-reference comments",
        decorator=None,
        why=(
            "A generated module opens with a docstring built from the module's "
            "intent and a 'do not edit' notice, then the transpiler's "
            "s0ma-source-hash / s0ma-output-hash lines, and each declaration is "
            "preceded by a comment naming the .s0ma line it came from. None of "
            "them reaches the surface: a module docstring is not an entry, and a "
            "comment is not syntax. The docstring of a class or a function is "
            "compared, because that one is authored."
        ),
    ),
    EmitterAddition(
        construct="the runtime import block and its register_* calls",
        decorator=None,
        why=(
            "A generated module imports `component`, `ComponentKind`, `Layer`, "
            "`Contract` and the runtime bridge's `register_module` / "
            "`register_constant` / `register_test`, and calls the register_* ones "
            "at the top level beside each constant. An imported name is never an "
            "entry — an entry describes something the module defines — and a bare "
            "call statement binds no name, so neither reaches the surface. A "
            "top-level assignment the conversion dropped still reads as a missing "
            "name."
        ),
    ),
)
"""What ``s0ma build`` adds around an authored body, and nothing else.

One entry per emitted construct, each saying which real thing it covers
and why ignoring it is honest. Two of the four are ignored by
construction — the surface reader never saw them in the first place —
and they are listed anyway, because "we checked and it cannot reach the
comparison" is the claim this list is making, and an undocumented
absence is indistinguishable from an oversight.
"""


#: The decorator names :func:`compare_surfaces` drops, derived from
#: :data:`EMITTER_ADDITIONS` so the documented list is the operative one.
IGNORED_DECORATORS: frozenset[str] = frozenset(
    addition.decorator
    for addition in EMITTER_ADDITIONS
    if addition.decorator is not None
)


#: Plain-language name for each finding kind, for the line a person
#: reads. The keys are the kinds
#: :class:`~s0ma_dsl.adopt.model.ParityFinding` documents; nothing else
#: is ever constructed, and ``test_adopt_parity`` checks the two lists
#: against each other so a kind cannot be added here without being
#: documented there.
FINDING_PHRASES: Mapping[str, str] = {
    "missing": "gone",
    "extra": "new",
    "signature_changed": "signature changed",
    "annotation_changed": "declared type changed",
    "doc_changed": "documentation changed",
    "bases_changed": "base classes changed",
    "decorators_changed": "decorators changed",
    "value_changed": "value changed",
}


def compare_surfaces(
    baseline: ModuleSurface, built: ModuleSurface, *, built_path: str = "",
) -> ParityResult:
    """Compare what a module promised with what the build emitted.

    *baseline* is the surface captured from the original Python file
    before it was converted; *built* is the surface read back from the
    ``.py`` the build wrote. *built_path* is the project-relative POSIX
    path the built surface was read from, recorded on the verdict so it
    says what it actually compared.

    Every difference becomes one
    :class:`~s0ma_dsl.adopt.model.ParityFinding` naming the symbol —
    dotted for a class member — and carrying the text before and after.
    Findings come back sorted by ``(symbol, kind)``, so two runs of the
    same comparison read identically and a reader works down the module
    one name at a time.

    What the build adds around an authored body is ignored, and only
    that: see :data:`EMITTER_ADDITIONS` for the list and the reason
    behind each entry.

    **Documentation that arrives is not a finding; documentation that
    changes or disappears is.** A class or a function that had no
    docstring and now has one has broken nothing — nobody could have
    depended on its absence — and a conversion is meant to add meaning,
    which is the whole point of the authoring step. A docstring that was
    there and is now different, or gone, is exactly the drift parity
    exists to catch, so that direction is reported.
    """
    before = {entry.name: _without_emitter_decorators(entry) for entry in baseline.entries}
    after = {entry.name: _without_emitter_decorators(entry) for entry in built.entries}

    findings: list[ParityFinding] = []
    for name in sorted(set(before) - set(after)):
        findings.append(_gone(before[name]))
    for name in sorted(set(after) - set(before)):
        findings.append(_new(after[name]))
    for name in sorted(set(before) & set(after)):
        findings.extend(_changes(before[name], after[name]))
    findings.extend(_export_findings(baseline, built, compared=set(before) | set(after)))

    return ParityResult(
        module=baseline.module,
        built_path=built_path,
        findings=tuple(sorted(findings, key=lambda finding: (finding.symbol, finding.kind))),
    )


def _without_emitter_decorators(entry: SurfaceEntry) -> SurfaceEntry:
    """*entry* with the build's own registration decorators dropped.

    Applied to both sides rather than only to the built one. A codebase
    part way through a retrofit may already carry ``@component(...)`` on
    a name that was registered in place (the way-station the guide calls
    Track A), and the baseline captured from it would hold that
    decorator too. Dropping it from both means the conversion neither
    gains a finding for a decorator the build re-writes nor loses one
    for a decorator a person removed.
    """
    kept = tuple(
        decorator
        for decorator in entry.decorators
        if _decorator_name(decorator) not in IGNORED_DECORATORS
    )
    if kept == entry.decorators:
        return entry
    return SurfaceEntry(
        name=entry.name,
        category=entry.category,
        signature=entry.signature,
        annotation=entry.annotation,
        decorators=kept,
        bases=entry.bases,
        docstring=entry.docstring,
        value=entry.value,
    )


def _decorator_name(decorator: str) -> str:
    """The bare name a decorator expression applies, for the ignore test.

    ``component(name='X', ...)`` is ``component``; ``functools.lru_cache``
    is ``functools.lru_cache`` and never matches, which is the point —
    the ignore list holds the emitter's own unqualified name and nothing
    a person is likely to have written.
    """
    head = decorator.split("(", 1)[0]
    return head.strip()


def _changes(before: SurfaceEntry, after: SurfaceEntry) -> list[ParityFinding]:
    """Every difference between two entries for the same name."""
    if before.category != after.category:
        # What something *is* has changed, so comparing the rest of it
        # would report the same break several times over in different
        # words. One finding, naming both shapes.
        return [
            ParityFinding(
                kind="signature_changed",
                symbol=before.name,
                before=_shape(before),
                after=_shape(after),
                detail=(
                    f"{before.name} was {_shape(before)} and is now {_shape(after)}. "
                    f"Callers written against the old shape will not work against "
                    f"the new one; change the declaration back, or accept the break "
                    f"deliberately and tell the people who call it."
                ),
            )
        ]

    findings: list[ParityFinding] = []
    if before.signature != after.signature:
        findings.append(
            ParityFinding(
                kind="signature_changed",
                symbol=before.name,
                before=before.signature,
                after=after.signature,
                detail=(
                    f"{before.name} is called differently than it was. Put the "
                    f"parameters, their defaults and the return type back as they "
                    f"were, or accept the change knowing every caller has to follow."
                ),
            )
        )
    if before.annotation != after.annotation:
        findings.append(
            ParityFinding(
                kind="annotation_changed",
                symbol=before.name,
                before=before.annotation,
                after=after.annotation,
                detail=(
                    f"The declared type of {before.name} changed. A field that "
                    f"quietly changes type is the commonest way a conversion breaks "
                    f"something without breaking a test; check the declaration "
                    f"against the Python it came from."
                ),
            )
        )
    if before.bases != after.bases:
        findings.append(
            ParityFinding(
                kind="bases_changed",
                symbol=before.name,
                before=_listed(before.bases),
                after=_listed(after.bases),
                detail=(
                    f"{before.name} no longer has the same base classes. Anything "
                    f"that catches it, subclasses it or checks its type with "
                    f"isinstance depends on this; put the bases back unless you "
                    f"meant to change what it is."
                ),
            )
        )
    if before.decorators != after.decorators:
        findings.append(
            ParityFinding(
                kind="decorators_changed",
                symbol=before.name,
                before=_listed(before.decorators),
                after=_listed(after.decorators),
                detail=(
                    f"The decorators on {before.name} are not what they were. A "
                    f"decorator is behaviour — caching, a property, a class or "
                    f"static method — so one that was dropped in the conversion "
                    f"changes what callers get. Carry it across in the "
                    f"declaration's body."
                ),
            )
        )
    if before.value is not None and before.value != after.value:
        findings.append(
            ParityFinding(
                kind="value_changed",
                symbol=before.name,
                before=before.value,
                after=after.value,
                detail=(
                    f"{before.name} does not hold what it held. Constants are read "
                    f"by other people's code; change it back, or change it on "
                    f"purpose and say so."
                ),
            )
        )
    elif before.value is None and after.value is not None:
        findings.append(
            ParityFinding(
                kind="value_changed",
                symbol=before.name,
                before=None,
                after=after.value,
                detail=(
                    f"{before.name} was declared without a value and now has one. "
                    f"That is a real difference for anything that reads it before "
                    f"it is set; check that it is what you meant."
                ),
            )
        )
    if before.docstring is not None and before.docstring != after.docstring:
        findings.append(
            ParityFinding(
                kind="doc_changed",
                symbol=before.name,
                before=before.docstring,
                after=after.docstring,
                detail=(
                    f"The documentation on {before.name} is not the documentation "
                    f"it had. Rewriting it on purpose is fine and common in a "
                    f"conversion; losing it by accident is not, which is why this "
                    f"is reported rather than assumed."
                ),
            )
        )
    return findings


def _gone(entry: SurfaceEntry) -> ParityFinding:
    """A name the module promised and the build does not offer."""
    return ParityFinding(
        kind="missing",
        symbol=entry.name,
        before=_shape(entry),
        after=None,
        detail=(
            f"{entry.name} was part of this module's public surface and the built "
            f"module does not have it. Either a declaration for it is missing from "
            f"the .s0ma source, or it is there under another name, or it is no "
            f"longer exported."
        ),
    )


def _new(entry: SurfaceEntry) -> ParityFinding:
    """A name the build offers that the module never promised."""
    return ParityFinding(
        kind="extra",
        symbol=entry.name,
        before=None,
        after=_shape(entry),
        detail=(
            f"{entry.name} is public in the built module and was not public before. "
            f"A conversion that widens the surface commits you to keeping the new "
            f"name; make it internal if it was not meant to be part of the promise."
        ),
    )


def _export_findings(
    baseline: ModuleSurface, built: ModuleSurface, *, compared: set[str]
) -> list[ParityFinding]:
    """Names that joined or left ``__all__`` without being entries either side.

    Almost every export difference is already a ``missing`` or an
    ``extra`` above, because the surface reader intersects public names
    with a literal ``__all__`` — so a name dropped from the list is a
    name dropped from the surface. What this catches is the remainder: a
    **re-exported** name, imported from elsewhere and listed in
    ``__all__``, which is nobody's entry and would otherwise vanish in
    silence. Order is never a finding (:data:`EMITTER_ADDITIONS`).
    """
    before = _exported_names(baseline)
    after = _exported_names(built)
    findings: list[ParityFinding] = []
    for name in sorted(before - after - compared):
        findings.append(
            ParityFinding(
                kind="missing",
                symbol=name,
                before="an exported name",
                after=None,
                detail=(
                    f"{name} was listed in this module's __all__ and the built "
                    f"module does not export it. It is not defined here, so it was "
                    f"passed through from somewhere else; re-export it from the "
                    f"converted module, or tell the people importing it from here."
                ),
            )
        )
    for name in sorted(after - before - compared):
        findings.append(
            ParityFinding(
                kind="extra",
                symbol=name,
                before=None,
                after="an exported name",
                detail=(
                    f"{name} is exported by the built module and was not exported "
                    f"before. It is not defined here either, so the conversion has "
                    f"added a pass-through; keep it only if you meant to."
                ),
            )
        )
    return findings


def _exported_names(surface: ModuleSurface) -> set[str]:
    """What the module offers by name: its ``__all__``, or its public top-level names.

    A module with no ``__all__`` promises every public name it defines,
    which is exactly what the surface's top-level entries are — so the
    two shapes compare against each other rather than one of them being
    read as "promises nothing".
    """
    if surface.dunder_all is not None:
        return set(surface.dunder_all)
    return {entry.name for entry in surface.entries if "." not in entry.name}


def _shape(entry: SurfaceEntry) -> str:
    """What an entry *is*, in the fewest plain words that still identify it."""
    words = {
        "function": "a function",
        "async_function": "an async function",
        "class": "a class",
        "constant": "a constant",
        "method": "a method",
        "async_method": "an async method",
        "attribute": "a class attribute",
    }.get(entry.category, f"a {entry.category}")
    if entry.signature is not None:
        return f"{words} {entry.signature}"
    if entry.value is not None:
        return f"{words} = {entry.value}"
    return words


def _listed(items: tuple[str, ...]) -> str:
    """A decorator or base-class list as one comparable piece of text."""
    return ", ".join(items) if items else "none"


# ---------------------------------------------------------------------------
# Saying what was found
# ---------------------------------------------------------------------------


def render_parity_text(
    results: Sequence[ParityResult], *, waiting: Sequence[str] = ()
) -> str:
    """The verdict as somebody reading a terminal wants it.

    One heading per module saying whether its surface is the same and
    what it was compared against, every difference on a line of its own
    — the symbol, what changed in plain words, and the before and after
    — and one closing line totalling the lot. Ends with a newline;
    contains no absolute path, no timestamp and nothing that differs
    between two machines.

    *waiting* names modules that have a baseline and were not compared
    because nothing of that name has been built yet. They are said out
    loud rather than left out: a report that quietly skips half a
    project reads as a clean bill of health for all of it.
    """
    lines: list[str] = []
    for index, result in enumerate(results):
        if index:
            lines.append("")
        lines.append(_verdict_line(result))
        width = max((len(finding.symbol) for finding in result.findings), default=0)
        phrase_width = max(
            (len(FINDING_PHRASES[finding.kind]) for finding in result.findings), default=0
        )
        for finding in result.findings:
            phrase = FINDING_PHRASES[finding.kind]
            lines.append(
                f"  {finding.symbol:<{width}}  {phrase:<{phrase_width}}  "
                f"{_side(finding.before)} → {_side(finding.after)}"
            )
    lines.append("")
    lines.extend(_wrap(_total_line(results)))
    if waiting:
        count = len(waiting)
        lines.append("")
        lines.extend(
            _wrap(
                f"{count} other {'module has' if count == 1 else 'modules have'} a "
                f"baseline and nothing built to compare it with yet: "
                f"{', '.join(waiting)}. Convert and build each one, then run this "
                f"again."
            )
        )
    return "\n".join(lines) + "\n"


#: The column this family's prose folds at — the width `adopt scan`
#: reports at and `adopt draft` closes at, so somebody walking the ladder
#: reads one thing rather than five.
_WRAP = 88


def _wrap(text: str) -> list[str]:
    """One closing sentence folded to :data:`_WRAP` columns."""
    return textwrap.wrap(
        text,
        width=_WRAP,
        subsequent_indent="  ",
        break_long_words=False,
        break_on_hyphens=False,
    ) or [text]


def _verdict_line(result: ParityResult) -> str:
    """One module's headline: clean, or how many differences."""
    where = f" (compared with {result.built_path})" if result.built_path else ""
    if result.clean:
        return f"{result.module} — same surface{where}"
    count = len(result.findings)
    word = "difference" if count == 1 else "differences"
    return f"{result.module} — {count} {word}{where}"


def _total_line(results: Sequence[ParityResult]) -> str:
    """The closing line: how many modules, how many of them moved."""
    modules = len(results)
    noun = "module" if modules == 1 else "modules"
    moved = [result for result in results if not result.clean]
    if not moved:
        kept = (
            "and its surface is what it was"
            if modules == 1
            else "and every surface is what it was"
        )
        return (
            f"{modules} {noun} compared, {kept}. Run the project's own tests next: "
            f"parity says the shape survived, and only your tests can say the "
            f"behaviour did."
        )
    findings = sum(len(result.findings) for result in moved)
    return (
        f"{modules} {noun} compared, {len(moved)} with differences, "
        f"{findings} {'difference' if findings == 1 else 'differences'} in all. "
        f"Each line above says what moved; put it back in the .s0ma source and "
        f"build again, or accept the change knowing what it costs the callers."
    )


def _side(value: str | None) -> str:
    """One side of a before/after pair, on one line, never empty.

    A docstring is the only value that can carry newlines, and a finding
    is one line by contract, so it is folded here rather than allowed to
    break the shape of the report.
    """
    if value is None:
        return "(nothing)"
    folded = " ".join(value.split())
    return folded or "(empty)"


def parity_document(
    results: Sequence[ParityResult], *, waiting: Sequence[str] = ()
) -> dict[str, Any]:
    """The same verdict for an agent, as the ``s0ma-adopt-parity@1`` document.

    Modules in the order they were asked for; ``clean`` at the top is
    true only when every one of them is. ``not_compared`` names the
    modules that have a baseline and nothing built to compare it with —
    the same honesty the text report keeps, so a reader of either cannot
    mistake "not checked" for "checked and fine". Deterministic: the
    findings inside each result are already sorted, and nothing here
    reads a clock, an environment or an absolute path.
    """
    return {
        "schema": PARITY_SCHEMA,
        "clean": all(result.clean for result in results),
        "modules": [result.to_dict() for result in results],
        "not_compared": [
            {"module": module, "reason": "nothing of that name has been built yet"}
            for module in waiting
        ],
    }
