"""Where a read surface finds the documentation it is asked to read.

Milestone F6 of the docs-function plan (internal) §11, task T2. The four
read commands — the navigation map, ``list``, ``show`` and ``search`` —
all answer from one composed snapshot, and none of them composes it.
Composition reads a checkout (:func:`~s0ma_dsl.docs_model.application.build`
walks ``references/``, ``packages/`` and the catalog); a person asking
``s0ma docs show concept:nerve`` may have no checkout at all. This module
is the seam between those two facts.

**Two origins, one shape.** A :class:`Snapshot` says which build answered
and where it was found:

``checkout``
    ``docs/_generated/s0ma-docs-model.json`` under a repository root found
    by walking upward from the working directory. The committed snapshot,
    which the F1 stage byte-gates, so a contributor reading it reads
    exactly what the build produced.
``installed``
    A snapshot shipped inside an installed wheel, produced by a registered
    loader. **The registration point is :func:`register_installed_loader`
    and it is deliberately open**, and the default loader is
    :func:`packaged_loader`, which reads
    ``s0ma_dsl/_docs_snapshot/s0ma-docs-model.json`` — a byte copy of the
    composed snapshot, committed inside the package directory and so
    carried by the wheel.

    That copy is the fix for a defect that outlived the milestone which
    opened this seam. F8 packaged the composed snapshot into the
    ``s0ma-mcp`` wheel, where the MCP resources read it, and a teaching
    slice into ``s0ma-core``; nothing ever filled the place this loader
    looks, so every read command answered an installed person "no
    documentation snapshot was found" while answering a contributor
    perfectly. The lesson is written into the gates rather than only into
    this paragraph: a dsl test byte-compares the copy against
    ``docs/_generated/s0ma-docs-model.json`` and names the ``cp`` that
    refreshes it, and ``scripts/wheel_smoke.py`` runs ``s0ma docs`` from a
    cold install outside any checkout.

The order is checkout first. A contributor with a checkout is asking about
*this tree*, and answering them from a wheel installed months ago would be
the one failure mode a version-stamped read surface exists to prevent.

**Offline, and nothing here reaches for a clock.** The loader reads one
file and parses it. It takes no network, consults no environment beyond
the directory it was asked to start from, and returns the same
:class:`Snapshot` for the same bytes on any platform — which is what lets
the four commands be byte-deterministic (plan §3.1 rule 4).

**Aliases travel with the snapshot, since F9.** They did not before, and
the note this paragraph replaces recorded that as a limitation of the seam:
``@1`` carried no alias field, so the alternate terms were read a second
time out of the authored concept files, which only exist in a checkout. A
wheel therefore resolved every id and every name and no earlier name at
all — the ALIAS match class was dead on every served channel. The pairs are
now written into the bundle by the composer
(:class:`~s0ma_dsl.docs_model.records.AliasEntry`), so both origins fill
:attr:`Snapshot.aliases` from the one place, through
:meth:`~s0ma_dsl.docs_model.records.DocsBundle.alias_index`. An origin that
carries none still resolves every id and every name; it just says so by
carrying an empty index rather than by having nowhere to look.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

from s0ma_dsl.docs_model.ids import AliasIndex
from s0ma_dsl.docs_model.records import DocsModelError

if TYPE_CHECKING:
    from s0ma_dsl.docs_model.records import DocsBundle

__all__ = [
    "CHECKOUT",
    "INSTALLED",
    "ORIGINS",
    "PACKAGED_LOADER",
    "PACKAGED_SNAPSHOT",
    "DocsBundleUnavailableError",
    "InstalledLoader",
    "Snapshot",
    "checkout_root",
    "checkout_snapshot",
    "installed_loaders",
    "installed_snapshot",
    "load_snapshot",
    "packaged_loader",
    "packaged_snapshot_path",
    "register_installed_loader",
    "registered_names",
    "snapshot_relative_path",
    "unregister_installed_loader",
]


#: The two origins a snapshot can have. Written as words rather than as an
#: enum because they are printed: a person who runs ``s0ma docs`` in a
#: checkout and again from an installed wheel should be able to see, in the
#: output, which one answered.
CHECKOUT = "checkout"
INSTALLED = "installed"

#: Both, in the order :func:`load_snapshot` tries them.
ORIGINS: tuple[str, ...] = (CHECKOUT, INSTALLED)

#: Where the snapshot packaged inside the ``s0ma_dsl`` wheel sits, relative
#: to the package directory. The documentation loop fills it, with the
#: third of its three ``cp`` lines (``docs/operations/docs-maintenance.md``,
#: ``docs/RELEASING.md`` step 4), and nothing else ever writes it: it is a
#: byte copy of ``docs/_generated/s0ma-docs-model.json``, never an edited
#: file. :func:`packaged_loader` returning ``None`` for an absent one is
#: still the honest answer rather than a failure — an editable install run
#: from outside its checkout is exactly that case.
PACKAGED_SNAPSHOT = "_docs_snapshot/s0ma-docs-model.json"

#: The name the default installed loader is registered under.
PACKAGED_LOADER = "packaged"


class DocsBundleUnavailableError(DocsModelError):
    """No snapshot could be found to answer a documentation question.

    Raised rather than reported as a finding, and the distinction is the
    one :class:`~s0ma_dsl.docs_model.map_of_record.DocsMapError` draws:
    a finding is something an author fixes in a source file, and this is
    the read surface saying it has nothing at all to read. The message
    names every place that was looked in, because the remediation depends
    entirely on which of them the person expected to work.
    """


@dataclass(frozen=True)
class Snapshot:
    """One composed build, and where the read surface found it.

    ``origin`` is :data:`CHECKOUT` or :data:`INSTALLED`; ``location`` is
    where it came from, as text, for a diagnostic. **``location`` is never
    printed by a read command**: it is an absolute machine path in the
    checkout case, and plan §3.1 rule 4 keeps absolute paths out of
    anything a build emits. The origin word is what reaches a reader, and
    it is the part that answers the only question a reader has — is this
    the tree I am standing in, or the wheel I installed.

    ``aliases`` are the alternate spellings this build knows about, read
    off the bundle it was loaded from. The empty index is a real answer,
    not a missing one: see the module docstring.
    """

    origin: str
    location: str
    bundle: DocsBundle
    aliases: AliasIndex = field(default=AliasIndex(entries=()))

    def release_version(self) -> str:
        """The release this documentation describes."""
        return self.bundle.stamp.release_version

    def version_line(self) -> str:
        """The release as a reader meets it, labelled unless it is released.

        The written form rather than the bare field (H1, architecture
        §13.2), for the read surfaces that put a version in front of a
        person. :meth:`release_version` stays the bare one, because a
        machine-readable answer is not a line a reader reads — the two are
        separate for the same reason the stamp keeps ``release_version``
        and ``build_channel`` apart.
        """
        return self.bundle.stamp.version_line()

    def snapshot_hash(self) -> str:
        """The digest of the record set this documentation was built from."""
        return self.bundle.stamp.snapshot_hash


#: What an installed-bundle loader looks like: no arguments, and either a
#: snapshot or an honest ``None``. A loader that cannot find its file
#: returns ``None`` rather than raising, so one absent packaging step does
#: not stop a second loader from answering.
InstalledLoader = Callable[[], "Snapshot | None"]


def snapshot_relative_path() -> str:
    """The committed snapshot's path inside a checkout, repository-relative.

    Composed from the application's own two constants rather than written
    out again, for the reason
    :data:`~s0ma_dsl.docs_model.reference_pages.REFERENCE_OUTPUTS` gives
    for holding the page paths in one place: a second copy of a path is a
    second thing that can be edited alone. The import is deferred because
    :mod:`~s0ma_dsl.docs_model.application` pulls in every provider, and a
    module whose whole job is to *avoid* composing should not make a
    reader pay for the composer at import time.
    """
    from s0ma_dsl.docs_model.application import DOCS_ROOT, SNAPSHOT_OUTPUT

    return f"{DOCS_ROOT}/{SNAPSHOT_OUTPUT}"


# ---------------------------------------------------------------------------
# The checkout origin
# ---------------------------------------------------------------------------


def checkout_root(start: Path | None = None) -> Path | None:
    """The repository root at or above ``start``, or ``None`` for none.

    "Repository root" here means exactly one thing: the directory holding
    the committed snapshot. Not the directory holding ``.git`` — a
    checkout with no composed documentation cannot answer a documentation
    question, and finding it would only turn an honest miss into a
    confusing one — and not the resolved ``[tool.s0ma]`` project either,
    which is about the project being built rather than about the tree it
    is being built in.

    The walk is upward and stops at the filesystem root. ``start``
    defaults to the working directory, which is the only ambient input
    this module takes and the one the person typing the command chose.
    """
    relative = snapshot_relative_path()
    here = (start if start is not None else Path.cwd()).resolve()
    for candidate in (here, *here.parents):
        if (candidate / relative).is_file():
            return candidate
    return None


def checkout_snapshot(start: Path | None = None) -> Snapshot | None:
    """The committed snapshot of the checkout at or above ``start``.

    ``None`` when there is no such checkout — the caller decides whether
    that is a miss worth reporting, because for
    :func:`load_snapshot` it is simply the first of two places to look.
    """
    from s0ma_dsl.docs_model.serialize import deserialize_bundle

    root = checkout_root(start)
    if root is None:
        return None
    path = root / snapshot_relative_path()
    bundle = deserialize_bundle(path.read_text(encoding="utf-8"))
    return Snapshot(
        origin=CHECKOUT,
        location=str(path),
        bundle=bundle,
        aliases=bundle.alias_index(),
    )


# ---------------------------------------------------------------------------
# The installed origin — the registration point
# ---------------------------------------------------------------------------

#: Every registered installed loader, keyed by name. A dict rather than a
#: list so a loader can be replaced by name (a test stages one, F8 replaces
#: the placeholder) and so the iteration order is a *declared* sort by name
#: rather than the order modules happened to import in — plan §3.1 rule 4
#: again, applied to a registry instead of to a rendering.
_INSTALLED: dict[str, InstalledLoader] = {}


def packaged_snapshot_path() -> Path:
    """Where a snapshot packaged inside this installed wheel would be.

    Computed from this module's own location, so it points inside whatever
    copy of ``s0ma_dsl`` is actually imported — the installed one for a
    wheel install, the checkout's for an editable one.
    """
    return Path(__file__).resolve().parent.parent / PACKAGED_SNAPSHOT


def packaged_loader() -> Snapshot | None:
    """The snapshot packaged beside this module, if one was shipped.

    Registered by default, and in an installed toolchain it is the loader
    that answers: the wheel carries
    ``s0ma_dsl/_docs_snapshot/s0ma-docs-model.json`` and this reads it. It
    still returns ``None`` rather than raising when the file is absent,
    which is the editable-install case — a checkout's package directory
    holds the committed copy, so even there it usually answers, and
    :func:`load_snapshot` has already preferred the checkout by then.
    """
    from s0ma_dsl.docs_model.serialize import deserialize_bundle

    path = packaged_snapshot_path()
    if not path.is_file():
        return None
    bundle = deserialize_bundle(path.read_text(encoding="utf-8"))
    return Snapshot(
        origin=INSTALLED,
        location=str(path),
        bundle=bundle,
        aliases=bundle.alias_index(),
    )


def register_installed_loader(name: str, loader: InstalledLoader) -> None:
    """Register a way of finding a snapshot inside an installed package.

    ``name`` is what the loader is known by, and registering a name twice
    replaces the first — that is deliberate, and it is how F8 puts the
    packaged slice in place of :func:`packaged_loader` without either of
    them having to know the other exists.
    """
    if not name.strip():
        raise DocsBundleUnavailableError(
            "an installed-bundle loader needs a name; the names are what "
            "make the registry replaceable and its order declared"
        )
    _INSTALLED[name] = loader


def unregister_installed_loader(name: str) -> None:
    """Remove a registered loader, refusing a name nothing registered."""
    if name not in _INSTALLED:
        raise DocsBundleUnavailableError(
            f"no installed-bundle loader is registered as {name!r}; the "
            f"registered ones are: {', '.join(registered_names()) or 'none'}"
        )
    del _INSTALLED[name]


def registered_names() -> tuple[str, ...]:
    """Every registered loader's name, sorted."""
    return tuple(sorted(_INSTALLED))


def installed_loaders() -> tuple[tuple[str, InstalledLoader], ...]:
    """Every registered loader, sorted by name."""
    return tuple((name, _INSTALLED[name]) for name in registered_names())


def installed_snapshot() -> Snapshot | None:
    """The first registered loader's snapshot, in name order, or ``None``."""
    for _name, loader in installed_loaders():
        found = loader()
        if found is not None:
            return found
    return None


register_installed_loader(PACKAGED_LOADER, packaged_loader)


# ---------------------------------------------------------------------------
# The one entry point
# ---------------------------------------------------------------------------


def load_snapshot(start: Path | None = None) -> Snapshot:
    """The documentation this invocation answers from.

    Checkout first, then every registered installed loader in name order.
    Raises :class:`DocsBundleUnavailableError` when neither has anything, with the
    places that were looked in named — a read surface that said only
    "documentation unavailable" would leave the person guessing which half
    of the seam to fix.
    """
    found = checkout_snapshot(start)
    if found is not None:
        return found
    found = installed_snapshot()
    if found is not None:
        return found
    names = ", ".join(registered_names()) or "none"
    raise DocsBundleUnavailableError(
        f"no documentation snapshot was found. A checkout answers from "
        f"{snapshot_relative_path()} at or above the directory you ran "
        f"this in, and an installed toolchain answers from the snapshot "
        f"inside the s0ma-dsl wheel, at s0ma_dsl/{PACKAGED_SNAPSHOT} "
        f"(loaders registered: {names}). This installation has neither, "
        f"which means one of two things: it is a development install being "
        f"run outside its own checkout, or its package files are "
        f"incomplete. Two ways out. Run the command from inside the "
        f"checkout — where `s0ma --project-root docs docs compose "
        f"--output-dir docs` writes the snapshot if it is missing — or "
        f"reinstall from the release wheels, which carry it."
    )
