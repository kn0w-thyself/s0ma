"""Check-failure baseline — NEW vs PRE-EXISTING delta attribution.

Batch-01c M2 (P0). The bench failure this closes: in batch-01c cold CM6
(``P2_P_haiku45_r03``) the agent broke every mutation's ``INSERT`` and
``s0ma check`` FAILED before commit — then the agent *dismissed* the
failure with "These errors are pre-existing and not related to my
changes" (verbatim). The dismissal was factually wrong, but nothing in
the check output made it checkable: diagnostics carried no notion of
"was this failing before your edit?". This module gives ``check`` a
memory of the last run so a fresh failure can be labelled NEW and the
"pre-existing" excuse is only claimable when the output actually says
PRE-EXISTING.

Working state, NOT authored state — the contrast with adoption
--------------------------------------------------------------------

The record is a JSON sidecar, but it is deliberately the *opposite* kind
of file from :mod:`s0ma_dsl.adoption`'s ``adopted.s0ma.json``:

* ``adopted.s0ma.json`` (0.11.0 M3) describes **authored state** — which
  hand-written files the project has decided to own. It is **committed**,
  reviewed, and diffed like source; a human curates it.
* ``.s0ma/check-baseline.json`` (this module) describes **local working
  state** — the diagnostic result of *this checkout's last check on this
  machine*. It is **NOT committed**: it lives under the ``.s0ma/``
  directory that the repo's ``.gitignore`` already excludes as "s0ma
  persistence" (the same home as the gitignored ``.s0ma/registry.db``),
  so it never enters version control and never travels between machines.
  Committing it would be a category error — a green baseline on one
  machine says nothing about another's uncommitted edits.

Because it is throwaway working state, the failure modes are handled the
opposite way too: :func:`load_baseline_record` treats a malformed or
unreadable file as *absent* (returns ``None``) rather than raising the
way :func:`s0ma_dsl.adoption.load_adopted_files` does — a corrupt cache
must never break ``check``, and the next green run regenerates it.

The inherited-debt anchor (0.13.0 M2)
--------------------------------------------------------------------

0.12.0 classified against the *last run's* failure set, which had a
laundering hole the batch-01c CM6 crater walks straight through: green
baseline → edit introduces failure X → ``check`` (X labelled NEW, but the
recording overwrites the baseline with {X}) → the very next run — the
build gate included — finds X in the baseline and calls it PRE-EXISTING.
Running ``check`` on your own breakage laundered NEW into PRE-EXISTING,
which is the literal dismissal the attribution exists to refute.

The record therefore now carries TWO sets (the ``anchor`` field is
additive under ``s0ma-check-baseline@1`` per the schema policy above):

* ``diagnostics`` — the last run's failure set, recorded as before.
* ``anchor`` — the set of **genuinely inherited debt**: failures that
  pre-date this working tree's attribution history. Classification (the
  ``check`` labels AND the ``build`` gate) is PRE-EXISTING iff the key is
  in the anchor, NEW otherwise; RESOLVED is anchor − current.

The anchor is **monotone shrinking** — it is seeded once and only ever
loses keys:

* No baseline file exists → anchor := the current run's failure set
  (brownfield first contact records the inherited debt; a green first
  run seeds an empty anchor).
* Baseline exists → anchor := anchor ∩ current failures. A key leaves
  when its failure is *observed fixed* and can NEVER re-enter — so a
  second red check keeps saying NEW, and re-introducing a failure you
  once fixed is NEW too.
* Legacy record with no ``anchor`` key → anchor := its ``diagnostics``
  set (one-run graceful migration to 0.12.0 behaviour).

Attribution safety — a key may only LEAVE the anchor when the checker
actually re-analysed its module and observed the failure absent:

* **Scope-limited runs never record.** A ``check src/foo.s0ma`` subset
  run (or the internal ``s0ma test`` build helper) analyses part of the
  project; recording it would both corrupt the last-run set and shrink
  the anchor on modules that were never re-analysed. Only full-project
  ``check`` (no positional paths) and full-project-root builds record;
  subset runs still *classify* (read-only) against the stored anchor.
* **Preempted modules keep their keys.** A module whose analysis was cut
  short this run (``PARSE_ERROR`` and the parse-family codes that
  suppress a module's downstream checks) keeps its anchor keys —
  otherwise inherited failure X would vanish behind an agent's transient
  parse error and resurface labelled NEW once the parse error is fixed.

Key severity is **check severity**, not the run's emitted severity: a
code that is a dev-*warning* but a strict-*error* (``check`` runs
strict; ``build`` runs dev — ``PROVIDES_KEY_MISMATCH`` et al.) keys into
the record from every run, so a dev-mode build/check cannot demote an
inherited strict error out of the anchor (see
:func:`is_check_severity_error`).

Design guard (per the M2 plan): the baseline lives **per project root**,
one file, last-writer-wins. Concurrent checks in one root can race on the
write; that is acceptable for the single-agent authoring workflows this
serves (an agent runs one ``check`` at a time), and the atomic
tmp-rename write (:func:`save_baseline_keys`) guarantees a reader never
sees a torn file — only ever the previous or the next complete baseline.

The stable diagnostic key
-------------------------

A diagnostic's identity must survive line churn (an edit above a finding
shifts its line number without changing the finding), so the key is
``(code, module, symbol)`` with **no line numbers and no timestamps**:

* ``code`` — the diagnostic code (``PARSE_ERROR``, ``NOT_EXPORTED``, …).
* ``module`` — the module's ``.s0ma`` source file as a project-root-
  relative POSIX path. In s0ma one file is one module, so the path is the
  always-present, churn-invariant "which module" anchor (it is also
  stable across a re-clone at the same layout — the same reasoning
  :func:`s0ma_dsl.cli.main._recorded_project_path` uses for artifacts).
* ``symbol`` — the in-module locus (a declaration / nerve / component
  name) lifted from the diagnostic's ``context`` when it carries one,
  else ``""``. This is the "symbol" arm of the plan's "symbol-or-path";
  the "path" arm is already carried by ``module``.

Output is deterministic (sorted keys, sorted diagnostic list, stable
indentation, trailing newline) so two green checks produce a
byte-identical baseline (INV-5 discipline, applied to working state).
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

from s0ma_dsl.config import StrictnessMode, get_severity

if TYPE_CHECKING:
    from collections.abc import Collection, Iterable, Mapping, Sequence

    from s0ma_dsl.errors import S0maError

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

BASELINE_SCHEMA = "s0ma-check-baseline@1"
"""Canonical schema string for the check-baseline record.

Additive fields ride the same string; ``@2`` is reserved for a breaking
change — the ``build.s0ma.json`` / ``adopted.s0ma.json`` versioning
policy. The 0.13.0 M2 ``anchor`` list is exactly such an additive field:
a legacy record without it migrates gracefully (anchor := its
``diagnostics`` set). Unlike those committed records this one is NOT
committed (see the module docstring): it is local working state under
gitignored ``.s0ma/``.
"""

BASELINE_DIRNAME = ".s0ma"
"""Working-state directory (already gitignored as "s0ma persistence"),
the same home as ``.s0ma/registry.db``. The baseline is never committed."""

BASELINE_FILENAME = "check-baseline.json"
"""On-disk filename for the check-baseline record, under ``.s0ma/``."""

#: ``context`` keys, in priority order, that carry a stable symbol name
#: for a diagnostic. The first present, non-empty string wins; a
#: diagnostic that carries none keys on its ``(code, module)`` alone.
_SYMBOL_CONTEXT_KEYS: tuple[str, ...] = (
    "declaration",
    "name",
    "component",
    "symbol",
    "module_name",
)

#: Diagnostic codes whose presence means the module's analysis was CUT
#: SHORT this run — the parser produced no module (or a malformed block
#: aborted it), so the module's downstream checks never ran and the
#: absence of its other failures is NOT evidence they were fixed. Anchor
#: keys for such modules survive the intersection (attribution safety —
#: see the module docstring's "Preempted modules keep their keys").
_PREEMPTING_CODES: frozenset[str] = frozenset({
    "PARSE_ERROR",
    "EMPTY_BLOCK_LIST",
    "INCONSISTENT_BLOCK_LIST_INDENT",
    "MIXED_PROVIDES_FORMS",
    "DUPLICATE_PROVIDES_NAME",
})


ENVIRONMENT_CODES: frozenset[str] = frozenset({"MISSING_PACKAGE"})
"""Codes whose truth depends on the environment the check runs in.

Every other check-severity code is a statement about the authored source:
the same ``.s0ma`` text fires it in every environment. ``MISSING_PACKAGE``
is different. It is raised when ``importlib.util.find_spec`` cannot find a
``requires:`` entry in the interpreter running the check, so the same
source is clean where the project's runtime packages are installed and
red where they are not. A PEP 517 build environment is the common case:
it holds the project's ``[build-system].requires`` and nothing else, so
every third-party ``requires:`` entry is missing there, and a baseline
recorded in the developer's environment makes each one look NEW.

The gate cannot tell that case from a misspelled ``requires:`` entry on
its own, so it does not guess: it treats these codes as environment
findings only when the caller states that the environment lacks the
runtime packages (``s0ma build --without-runtime-packages``). Without
that statement they count as NEW check errors like any other.
"""


def is_environment_diagnostic(
    diag: S0maError, project_modules: Collection[str] = (),
) -> bool:
    """Whether *diag* is an environment finding (:data:`ENVIRONMENT_CODES`).

    A ``MISSING_PACKAGE`` whose import path names one of *project_modules*,
    the s0ma modules of the project being built, is not: that entry names
    a s0ma module, which belongs in ``uses:``, so no environment supplies
    it and the source alone settles it.
    """
    if diag.code not in ENVIRONMENT_CODES:
        return False
    return diag.context.get("import_path") not in project_modules


def is_check_severity_error(diag: S0maError) -> bool:
    """Would ``check`` (strict) rank this diagnostic as an *error*?

    Batch-01c 0.13.0 M2. The record and the build gate must see the
    errors ``check`` would report — not just the ones the emitting run's
    (possibly laxer) mode ranked ``error``. The divergence is the whole
    failure: ``check`` defaults to strict, ``build`` to dev, so a code
    that is a *warning* in dev but an *error* in strict
    (``PROVIDES_KEY_MISMATCH``, ``MISSING_PACKAGE``,
    ``CROSS_LAYER_DEPENDENCY``, ``MODULE_SHADOWS_STDLIB`` …) makes
    ``check`` go red while the build stays green — the exact gap the CM6
    crater shipped through. Keying the baseline on this predicate also
    keeps a dev-mode run from demoting an inherited strict error out of
    the anchor (it is *observed* as a warning, not observed fixed).

    A diagnostic already at ``error`` severity is an error in every mode;
    a ``warning`` is a *check error* when the strict-mode severity matrix
    ranks its code an error. Codes outside the matrix keep their emitted
    severity (a warning stays a warning — the gate never invents a block
    for a code the matrix does not govern).
    """
    if diag.severity == "error":
        return True
    try:
        return get_severity(diag.code, StrictnessMode.STRICT) == "error"
    except KeyError:
        return False


# ---------------------------------------------------------------------------
# The stable diagnostic key
# ---------------------------------------------------------------------------


@dataclass(frozen=True, order=True)
class DiagnosticKey:
    """A line-number-free, deterministic identity for one diagnostic.

    ``(code, module, symbol)`` — see the module docstring. ``order=True``
    makes the key sortable so baselines and delta lists are deterministic.
    """

    code: str
    module: str
    symbol: str

    def to_dict(self) -> dict[str, str]:
        """JSON form: a flat object with the three string fields."""
        return {"code": self.code, "module": self.module, "symbol": self.symbol}

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> DiagnosticKey:
        """Rebuild a key from its JSON form, coercing each field to ``str``."""
        return cls(
            code=str(payload.get("code", "")),
            module=str(payload.get("module", "")),
            symbol=str(payload.get("symbol", "")),
        )


def _relative_module(file: str, root: Path | None) -> str:
    """Render *file* as a project-root-relative POSIX path when possible.

    Falls back to the raw string when *file* is empty, *root* is ``None``,
    or the path cannot be expressed under *root* (mirrors
    :func:`s0ma_dsl.cli.main._recorded_project_path`). Keeps the key
    stable across working directories on one machine.
    """
    if not file:
        return ""
    if root is None:
        return file
    try:
        return Path(file).resolve().relative_to(Path(root).resolve()).as_posix()
    except (ValueError, OSError):
        return file


def _symbol_of(context: Mapping[str, Any]) -> str:
    """Return the first recognised, non-empty string symbol in *context*."""
    for key in _SYMBOL_CONTEXT_KEYS:
        value = context.get(key)
        if isinstance(value, str) and value:
            return value
    return ""


def diagnostic_key(diag: S0maError, root: Path | None) -> DiagnosticKey:
    """Compute the stable :class:`DiagnosticKey` for one diagnostic."""
    return DiagnosticKey(
        code=diag.code,
        module=_relative_module(diag.file, root),
        symbol=_symbol_of(diag.context),
    )


def _distinct_error_keys(
    diagnostics: Sequence[S0maError], root: Path | None,
) -> list[DiagnosticKey]:
    """The distinct keys of the *check-severity* errors (order-preserving).

    0.13.0 M2: severity is :func:`is_check_severity_error`, not the
    diagnostic's emitted severity — a dev-warning that ``check`` (strict)
    ranks an error keys into the record from every run, so a dev-mode
    build/check cannot demote an inherited strict error out of the anchor.
    """
    keys: list[DiagnosticKey] = []
    seen: set[DiagnosticKey] = set()
    for diag in diagnostics:
        if not is_check_severity_error(diag):
            continue
        key = diagnostic_key(diag, root)
        if key not in seen:
            seen.add(key)
            keys.append(key)
    return keys


def _preempted_modules(
    diagnostics: Sequence[S0maError], root: Path | None,
) -> frozenset[str]:
    """Modules whose analysis was cut short this run (see the code list).

    Returns their :class:`DiagnosticKey`-style ``module`` strings so
    anchor keys can be matched on module identity.
    """
    return frozenset(
        _relative_module(diag.file, root)
        for diag in diagnostics
        if diag.severity == "error" and diag.code in _PREEMPTING_CODES
    )


# ---------------------------------------------------------------------------
# Load / save
# ---------------------------------------------------------------------------


def baseline_path(root: Path) -> Path:
    """The check-baseline record path for a project rooted at *root*."""
    return root / BASELINE_DIRNAME / BASELINE_FILENAME


@dataclass(frozen=True)
class BaselineRecord:
    """The two key sets one baseline file carries (0.13.0 M2).

    ``last_run`` is the previous run's failure set (the 0.12.0
    ``diagnostics`` list, recorded as before); ``anchor`` is the
    monotone-shrinking inherited-debt set classification keys on (see the
    module docstring). A legacy record without an ``anchor`` field loads
    with ``anchor == last_run`` — the one-run graceful migration that
    degrades to 0.12.0 behaviour.
    """

    last_run: frozenset[DiagnosticKey]
    anchor: frozenset[DiagnosticKey]
    python_file_anchor: frozenset[str] | None


def load_baseline_record(root: Path) -> BaselineRecord | None:
    """Read the recorded baseline, or ``None`` when none is readable.

    ``None`` means "no baseline to diff against" — either nothing has run
    yet, or the file is missing/malformed/schema-mismatched. Unlike
    adoption's committed record this NEVER raises: a corrupt throwaway
    baseline is treated as absent and regenerated by the next recording
    run (see the module docstring's working-state rationale). A present
    but empty record (empty lists) is a *green* baseline and is returned
    with empty sets — distinct from ``None``.
    """
    path = baseline_path(root)
    if not path.is_file():
        return None
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(raw, dict) or raw.get("schema") != BASELINE_SCHEMA:
        return None
    diagnostics = raw.get("diagnostics")
    if not isinstance(diagnostics, list):
        return None
    keys: set[DiagnosticKey] = set()
    for entry in diagnostics:
        if isinstance(entry, dict):
            keys.add(DiagnosticKey.from_dict(entry))
    raw_anchor = raw.get("anchor")
    anchor: set[DiagnosticKey]
    if isinstance(raw_anchor, list):
        anchor = set()
        for entry in raw_anchor:
            if isinstance(entry, dict):
                anchor.add(DiagnosticKey.from_dict(entry))
    else:
        # Legacy 0.12.0 record — no anchor field. Migrate gracefully:
        # treat its last-run set as the anchor for one run (degrades to
        # the old last-run semantics exactly once; the recording run
        # writes an explicit anchor).
        anchor = set(keys)
    raw_python_anchor = raw.get("python_file_anchor")
    python_file_anchor: frozenset[str] | None
    if isinstance(raw_python_anchor, list) and all(
        isinstance(item, str) for item in raw_python_anchor
    ):
        python_file_anchor = frozenset(raw_python_anchor)
    else:
        # Legacy @1 record: the next full-project run seeds first-contact
        # inventory without accusing already-present brownfield files.
        python_file_anchor = None
    return BaselineRecord(
        last_run=frozenset(keys),
        anchor=frozenset(anchor),
        python_file_anchor=python_file_anchor,
    )


def load_baseline_keys(root: Path) -> frozenset[DiagnosticKey] | None:
    """The recorded *last-run* failure set (the 0.12.0 accessor).

    Kept for consumers of the last-run set; classification consumers want
    :func:`load_baseline_record` and its ``anchor``.
    """
    record = load_baseline_record(root)
    return record.last_run if record is not None else None


def save_baseline_keys(
    root: Path,
    keys: Iterable[DiagnosticKey],
    anchor: Iterable[DiagnosticKey] | None = None,
    python_file_anchor: Iterable[str] | None = None,
) -> Path:
    """Atomically write the baseline for *root*; return its path.

    *keys* is the last-run failure set (the ``diagnostics`` list, as in
    0.12.0); *anchor* is the inherited-debt set (0.13.0 M2 — additive
    ``anchor`` list). ``None`` writes ``anchor == keys`` (the seed shape
    a first-contact run records, and what the legacy migration would
    reconstruct anyway).

    Determinism (spec (d)): both lists are sorted and the JSON keys are
    sorted, so a green run (empty sets) — and any two identical runs —
    produce byte-identical bytes. Atomicity: the payload is written to a
    per-process temp file in the same directory, then
    :func:`os.replace`'d over the target, so a concurrent reader sees
    either the old or the new complete file, never a torn one
    (last-writer-wins across racing writers is accepted per the design
    guard).
    """
    path = baseline_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    ordered = sorted(set(keys))
    ordered_anchor = sorted(set(anchor)) if anchor is not None else ordered
    payload: dict[str, Any] = {
        "schema": BASELINE_SCHEMA,
        "diagnostics": [key.to_dict() for key in ordered],
        "anchor": [key.to_dict() for key in ordered_anchor],
    }
    if python_file_anchor is not None:
        payload["python_file_anchor"] = sorted(set(python_file_anchor))
    text = json.dumps(payload, indent=2, sort_keys=True) + "\n"
    tmp = path.with_name(f"{path.name}.tmp.{os.getpid()}")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)
    return path


# ---------------------------------------------------------------------------
# Delta classification + rendering
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class DeltaReport:
    """The NEW / PRE-EXISTING / RESOLVED classification of one failing run.

    0.13.0 M2: computed against the baseline's inherited-debt **anchor**
    (see the module docstring), not the last run's set — so re-checking
    an unfixed NEW failure keeps saying NEW instead of laundering it to
    PRE-EXISTING on the second look. ``anchor_keys is None`` means no
    baseline existed, so nothing is attributable — only the
    :meth:`no_baseline_note` is shown. ``new`` / ``pre_existing`` /
    ``resolved`` hold the distinct failure keys; ``root`` lets
    :meth:`label_for_diag` recompute a diagnostic's key for per-line
    labelling.
    """

    anchor_keys: frozenset[DiagnosticKey] | None
    root: Path | None
    new: tuple[DiagnosticKey, ...]
    pre_existing: tuple[DiagnosticKey, ...]
    resolved: tuple[DiagnosticKey, ...]

    @property
    def baseline_exists(self) -> bool:
        """Whether a baseline was on disk to diff this run against."""
        return self.anchor_keys is not None

    def label_for_diag(self, diag: S0maError) -> str | None:
        """``"NEW"`` / ``"PRE-EXISTING"`` for one error diag, or ``None``.

        ``None`` when no baseline exists (nothing is attributable) — the
        renderer then shows only :meth:`no_baseline_note`. Rule (c): a
        NEW failure after your edit is yours; "pre-existing" is only
        claimable when this returns ``"PRE-EXISTING"`` — i.e. when the
        failure is in the inherited-debt anchor, which your own checks
        can never grow.
        """
        if self.anchor_keys is None:
            return None
        key = diagnostic_key(diag, self.root)
        return "PRE-EXISTING" if key in self.anchor_keys else "NEW"

    def summary_line(self) -> str:
        """The lead line, NEW count first (spec (b)).

        e.g. ``"3 failures: 2 NEW since your last green build, 1
        pre-existing."`` A trailing ``(N resolved since baseline.)`` is
        appended when the baseline had failures this run cleared.
        """
        total = len(self.new) + len(self.pre_existing)
        parts: list[str] = []
        if self.new:
            parts.append(f"{len(self.new)} NEW since your last green build")
        if self.pre_existing:
            parts.append(f"{len(self.pre_existing)} pre-existing")
        detail = ", ".join(parts) if parts else "none attributable"
        line = f"{total} failure(s): {detail}."
        if self.resolved:
            line += f" ({len(self.resolved)} resolved since baseline.)"
        return line

    def no_baseline_note(self) -> str:
        """The one line shown when no baseline exists yet (spec (b))."""
        return (
            "No check baseline exists yet, so these failures cannot be "
            "attributed as NEW or pre-existing. A full-project check or "
            "build records one (a failing first run records its failures "
            "as the inherited pre-existing set); after that, a failure "
            "outside that inherited set is NEW — one your edit introduced."
        )

    def to_dict(self) -> dict[str, Any]:
        """JSON form carried in the ``--format json`` result's ``delta`` key."""
        report: dict[str, Any] = {
            "schema": BASELINE_SCHEMA,
            "baseline_exists": self.baseline_exists,
        }
        if self.baseline_exists:
            report["new"] = [key.to_dict() for key in self.new]
            report["pre_existing"] = [key.to_dict() for key in self.pre_existing]
            report["resolved"] = [key.to_dict() for key in self.resolved]
            report["summary"] = self.summary_line()
        else:
            report["note"] = self.no_baseline_note()
        return report


def classify(
    anchor_keys: frozenset[DiagnosticKey] | None,
    current_errors: Sequence[S0maError],
    root: Path | None,
) -> DeltaReport:
    """Classify *current_errors* against the inherited-debt *anchor_keys*.

    0.13.0 M2 semantics: PRE-EXISTING iff the key is in the anchor; NEW
    otherwise; RESOLVED = an anchor key whose failure is absent now AND
    whose module was actually re-analysed this run (a preempted module —
    parse error cut its analysis short — is not evidence of a fix, so its
    keys are neither RESOLVED here nor dropped by the recording path).
    When *anchor_keys* is ``None`` (no baseline) nothing is attributed —
    the report carries empty tuples and renders the no-baseline note.
    """
    current_keys = _distinct_error_keys(current_errors, root)
    if anchor_keys is None:
        return DeltaReport(
            anchor_keys=None, root=root, new=(), pre_existing=(), resolved=(),
        )
    current_set = frozenset(current_keys)
    preempted = _preempted_modules(current_errors, root)
    new = tuple(sorted(k for k in current_keys if k not in anchor_keys))
    pre_existing = tuple(sorted(k for k in current_keys if k in anchor_keys))
    resolved = tuple(sorted(
        k for k in anchor_keys
        if k not in current_set and k.module not in preempted
    ))
    return DeltaReport(
        anchor_keys=anchor_keys,
        root=root,
        new=new,
        pre_existing=pre_existing,
        resolved=resolved,
    )


def record_check_baseline(
    root: Path,
    diagnostics: Sequence[S0maError],
    *,
    python_paths: Iterable[str] = (),
) -> DeltaReport:
    """Classify this run against the anchor, then update the record.

    The single entry point the CLI ``check`` / ``build`` commands call at
    their terminal tail — **full-project-scope runs only** (a subset run
    must classify read-only via :func:`classify`; recording it would
    shrink the anchor on modules it never re-analysed — the caller owns
    that guard, see ``S0maCLI._record_check_baseline``).

    Order matters (the plan's state machine): load the PREVIOUS record,
    classify the current check-severity failures against its **anchor**,
    THEN persist. What is persisted:

    * ``diagnostics`` := the current failure set (the 0.12.0 last-run
      record, unchanged).
    * ``anchor`` := monotone-shrinking update — first contact (no record)
      seeds it with the current failure set (inherited debt; empty on a
      green first run); otherwise ``anchor ∩ current``, except keys of
      preempted modules (analysis cut short) which survive. Keys can
      never re-enter, so an agent's own red checks structurally cannot
      launder NEW into PRE-EXISTING.

    Returns the delta; callers that only record (``build``) may ignore
    it, callers that render (``check``) thread it into the formatters.
    """
    record = load_baseline_record(root)
    delta = classify(
        record.anchor if record is not None else None, diagnostics, root,
    )
    current_keys = _distinct_error_keys(diagnostics, root)
    current_set = frozenset(current_keys)
    if record is None:
        # First contact: the current failure set IS the inherited debt.
        new_anchor: frozenset[DiagnosticKey] = current_set
    else:
        preempted = _preempted_modules(diagnostics, root)
        new_anchor = frozenset(
            k for k in record.anchor
            if k in current_set or k.module in preempted
        )
    current_python_paths = frozenset(python_paths)
    python_file_anchor = (
        current_python_paths
        if record is None or record.python_file_anchor is None
        else record.python_file_anchor
    )
    save_baseline_keys(
        root,
        current_keys,
        anchor=new_anchor,
        python_file_anchor=python_file_anchor,
    )
    return delta
