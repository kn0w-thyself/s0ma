"""What one documentation build is, written down so another can be compared to it.

Milestone H1 of the docs-function plan (internal) §13, implementing the
architecture plan's §13.1 schema and §13.2 channel rules:

```text
schema              s0ma-docs-model@1
product_version     lockstep distribution version
source_commit       exact commit id
package_versions    all four distributions
provider_schemas    adapter id -> schema version
source_hashes       canonical source identities and hashes
snapshot_hash       canonical hash of the composed graph
artifacts           sorted ArtifactRecord list
```

**No timestamp appears anywhere**, which architecture §13.1 states as a
rule and this module keeps as a property: nothing here reads a clock, an
environment variable, a locale, a machine path or a network. Every value
is computed from records the composition already holds and from values the
caller declares. Two builds of one tree therefore write the same bytes,
which is the acceptance criterion of the whole initiative and the reason
publication time belongs to release infrastructure rather than to
documentation identity.

**Two interpretations this module makes, and why.**

*One.* ``source_commit`` is **not** a git object name. Three things rule
that out and any one of them would be enough. A build that shelled out to
``git`` would be a subprocess inside a composition the provider contract
forbids side effects in (SDA-INV-8, ``providers`` module docstring). The
manifest is itself a committed, byte-gated artifact, so a value that
changes with the commit *containing* it has no fixed point — the file
would be stale the instant it was committed, every time, forever. And the
place the identity is finally checked is a cold wheel (H2), where there is
no repository to ask. So ``source_commit`` is the identity of the exact
source state this documentation was built from, computed the way this
build is allowed to compute anything: a digest over every source the
providers read, path and content hash, sorted. It answers the question the
field exists to answer — *which exact state of the sources is this?* — and
it answers it offline, reproducibly, and from a wheel.

*Two.* ``build_channel`` is a manifest field, though §13.1's list does not
name one. §13.2 defines three channels and makes claims about what a
release build may contain; a manifest that did not record which channel it
was would make every one of those claims uncheckable, and
``DOC_VERSION_MISMATCH`` — the diagnostic §11 mints for exactly this
failure class — would have nothing to read. The field is on the manifest
and on every artifact it lists, because "a preview artifact inside a
release manifest" is a statement about the pair.

**The channel is derived, never hand-set.** :func:`channel_of` is the
whole rule: a build is a release build when the commit it is built from is
exactly the commit a tag naming the lockstep version points at, and a
preview build otherwise. The rule is a pure function of two values, and
the tag arrives *as a value* — this module never looks for one. That is
not squeamishness about git: it is what keeps the rule testable on a tree
with no tags at all (this repository's, today: every build here is a
preview build) and what keeps the release case provable from a fixture
rather than from a tag somebody has to cut first.
"""

from __future__ import annotations

from dataclasses import dataclass, fields
from typing import TYPE_CHECKING

from s0ma_dsl.docs_model.records import (
    BUILD_CHANNELS,
    PREVIEW_CHANNEL,
    RELEASE_CHANNEL,
    SCHEMA,
    DocsModelError,
)
from s0ma_dsl.docs_model.serialize import (
    canonical_json,
    content_hash,
    record_from_plain,
    to_plain,
)

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping, Sequence

    from s0ma_dsl.docs_model.providers import ProviderResult
    from s0ma_dsl.docs_model.records import DocsBundle

__all__ = [
    "ARTIFACT_FIELDS",
    "ARTIFACT_FORMATS",
    "ARTIFACT_ID_PREFIX",
    "LOCKSTEP_ANCHOR",
    "MANIFEST_FIELDS",
    "MANIFEST_SCHEMA",
    "ArtifactRecord",
    "DocsManifest",
    "DocsManifestError",
    "PackageVersion",
    "ProviderSchema",
    "SourceHash",
    "artifact_format",
    "artifact_id",
    "channel_of",
    "manifest_from_json",
    "manifest_of",
    "package_versions_of",
    "product_version_of",
    "provider_schemas_of",
    "render_manifest",
    "source_commit_of",
    "source_hashes_of",
    "version_tag",
]


class DocsManifestError(DocsModelError):
    """A manifest cannot be built from what this build knows."""


#: The manifest's ``schema`` field, which architecture §13.1 writes as
#: ``s0ma-docs-model@1``: the manifest describes one composed model and is
#: versioned with it rather than beside it. A second version line would be
#: a second thing to bump, and the first release that bumped one and not
#: the other would ship a manifest claiming to describe a model it does
#: not.
MANIFEST_SCHEMA = SCHEMA

#: The distribution whose ``project.version`` *is* the product version
#: (PRD INV-4, and the anchor ``scripts/check_version_refs.py`` already
#: uses). s0ma-core sits at the bottom of the dependency stack, so it is
#: the one version the other three are held equal to rather than one of
#: four opinions.
#:
#: ``docs/pyproject.toml`` is deliberately **not** consulted, and that is
#: the decision worth writing down here rather than leaving to be
#: rediscovered. The documentation application is a s0ma project pinned at
#: ``0.0.0`` on purpose: it ships in no wheel, is installed by nobody, and
#: is outside the lockstep for exactly that reason. Reading its version as
#: the product version would make every rendered page claim to document
#: s0ma 0.0.0. What the manifest states is the version of the *product the
#: documentation describes*, and the product is the four distributions.
LOCKSTEP_ANCHOR = "s0ma-core"

#: Every id this module mints starts here. Artifact ids live only inside a
#: manifest — nothing in the bundle resolves against them, so they are not
#: an :mod:`~s0ma_dsl.docs_model.ids` form and adding one would put a
#: seventh addressable kind into the model's join key for no caller.
ARTIFACT_ID_PREFIX = "artifact:"

#: File suffix to architecture §6.6 format word, for the formats a
#: documentation build actually writes. The other two words §6.6 lists —
#: ``html`` and ``mcp_resource`` — are reachable by other producers
#: (studi0's viewer, the MCP server's served copies) and are not invented
#: here for outputs that do not exist yet.
#:
#: ``media_manifest`` was the third of those at H1 and is no longer: H3
#: renders the packages architecture §13.3 mints that word for, so the
#: format is now claimed the same way ``package_data`` is — by the
#: application naming which of its outputs are of that kind. See
#: :func:`artifact_format`.
ARTIFACT_FORMATS: Mapping[str, str] = {
    ".md": "markdown",
    ".json": "json",
}


# ---------------------------------------------------------------------------
# The parts
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class PackageVersion:
    """One distribution and the version it ships at."""

    distribution: str
    version: str


@dataclass(frozen=True)
class ProviderSchema:
    """One adapter and the model version its records were emitted against.

    A pair rather than a mapping because a provider emitting records
    against two schema versions is a real state — a half-migrated adapter —
    and a mapping would silently keep one of them. Two rows say so, and
    :func:`~s0ma_dsl.docs_model.validate.check_manifest` reports it.
    """

    provider_id: str
    schema_version: str


@dataclass(frozen=True)
class SourceHash:
    """One source a provider read, and the digest of what it read.

    ``sha256`` is the full sixty-four character digest the provenance
    carries (``Provenance.source_sha256``), not the shortened house form:
    this field exists so somebody outside the build can re-hash the file
    and compare, and a truncated digest is a weaker comparison for no
    saving anybody benefits from.
    """

    source: str
    sha256: str


@dataclass(frozen=True)
class ArtifactRecord:
    """One rendered output, described the way architecture §6.6 asks.

    ``id``            a stable output id, minted from the path.
    ``format``        one of §6.6's format words.
    ``source_document``  the catalog row this output is the rendering of,
                      or empty where the output is a machine artifact no
                      document claims. Empty is a real answer here and not
                      a gap, and which outputs give it is a *rule* rather
                      than a list: the catalog's corpus is tracked
                      Markdown and ADR-012 §2.3 rule B-2 keeps
                      reader-facing pages out of ``_generated/``
                      entirely, so every output under that directory has
                      no row by design and every output outside it has
                      one. Stated as a rule because the alternative was
                      an enumeration, and the enumeration had already
                      gone stale twice — H3's media packages and I2's
                      coverage report both landed in ``_generated/``
                      after it was written, and neither edited it.
    ``path_or_uri``   repository-relative, forward-slashed.
    ``content_hash``  the house digest of the exact bytes rendered.
    ``release_version``  the version this output represents.
    ``source_snapshot``  the snapshot digest it was rendered from.
    ``build_channel`` which channel rendered it (§13.2, H1's addition).

    The last three are what make a mixed build detectable at all. An
    artifact carrying its own version and its own snapshot means a manifest
    assembled from two builds is a manifest whose rows disagree with its
    head — which is precisely ``DOC_VERSION_MISMATCH``, and precisely what
    a manifest of paths and hashes alone could never notice.
    """

    id: str
    format: str
    source_document: str
    path_or_uri: str
    content_hash: str
    release_version: str
    source_snapshot: str
    build_channel: str


@dataclass(frozen=True)
class DocsManifest:
    """One build's identity: architecture §13.1, in §13.1's order.

    Every field is a value the build already knows. Nothing here is read
    from the environment and nothing is a time.
    """

    schema: str
    product_version: str
    build_channel: str
    source_commit: str
    package_versions: tuple[PackageVersion, ...]
    provider_schemas: tuple[ProviderSchema, ...]
    source_hashes: tuple[SourceHash, ...]
    snapshot_hash: str
    artifacts: tuple[ArtifactRecord, ...]


# ---------------------------------------------------------------------------
# The channel rule
# ---------------------------------------------------------------------------


def version_tag(product_version: str) -> str:
    """The tag a release of ``product_version`` is cut under: ``v1.2.3``.

    One place, because the rule below compares against it and
    ``scripts/release_cut.sh`` writes it — two spellings of one convention
    is how a release build silently decides it is a preview.
    """
    return f"v{product_version}"


def channel_of(*, product_version: str, head_tag: str = "") -> str:
    """Which channel a build belongs to (architecture §13.2).

    ``head_tag`` is the tag the built commit is *exactly* at, as a value —
    what ``git describe --exact-match --tags HEAD`` would print, supplied
    by whoever knows. Empty means "no tag", which is every build in a
    working checkout and every build of this repository today.

    The rule, whole:

    * a build is a **release** build when the commit it is built from is
      exactly the commit tagged for the lockstep version it claims;
    * every other build is a **preview** build.

    ``historical`` is not derived and cannot be: an immutable snapshot kept
    against an older version is a *decision to keep it*, made after the
    fact by whoever republishes it, and no property of the tree says so.
    It is a value a caller declares.

    A tag that names some other version is not a release of *this* one —
    it is a tree standing on v0.17.0 with 0.18.1 in its manifests, which is
    the mixing this milestone exists to refuse — so it reads as preview and
    the gate reports the disagreement it can see.
    """
    if head_tag and head_tag == version_tag(product_version):
        return RELEASE_CHANNEL
    return PREVIEW_CHANNEL


# ---------------------------------------------------------------------------
# The facts, each from one place
# ---------------------------------------------------------------------------


def package_versions_of(
    packages: Iterable[tuple[str, str]],
) -> tuple[PackageVersion, ...]:
    """Every distribution's version, sorted by distribution name.

    The pairs arrive from
    :func:`~s0ma_dsl.docs_model.providers_repo.package_facts`, which is
    the one reading of the four ``pyproject.toml`` files this repository
    makes. They are not re-read here: a second reading of a version is how
    a manifest and a records graph come to disagree about one number with
    nobody at fault.
    """
    return tuple(
        PackageVersion(distribution=name, version=version)
        for name, version in sorted(set(packages))
    )


def product_version_of(packages: Sequence[PackageVersion]) -> str:
    """The lockstep version: :data:`LOCKSTEP_ANCHOR`'s own.

    Refuses rather than guesses when the anchor is absent. A manifest whose
    product version was inferred from whichever distribution happened to
    sort first would be a number nobody decided, and every artifact in the
    build would then claim to represent it.
    """
    for item in packages:
        if item.distribution == LOCKSTEP_ANCHOR:
            return item.version
    named = ", ".join(sorted(item.distribution for item in packages)) or "none"
    raise DocsManifestError(
        f"the product version is {LOCKSTEP_ANCHOR}'s version (PRD INV-4) and "
        f"this build read no such distribution; it read: {named}. A manifest "
        f"cannot state which release it describes without it."
    )


def provider_schemas_of(
    results: Iterable[ProviderResult],
) -> tuple[ProviderSchema, ...]:
    """Every ``(adapter, schema version)`` pair the build emitted, sorted.

    Read off the provenance the providers stamped rather than off the
    registry, because the registry knows which adapters ran and only the
    records know what they were written against — which is the whole
    reason ``Provenance.schema_version`` is a separate field from the
    build stamp's ``schema``.

    A provider that emitted nothing contributes no row. That is honest and
    it is not a hole: an empty provider is already ``DOC_GATE_VACUOUS``'s
    subject, reported by the floors, and inventing a row for it here would
    put a schema claim in the manifest that no record backs.
    """
    pairs = {
        (item.provenance.adapter_id, item.provenance.schema_version)
        for result in results
        for item in result.records
    }
    return tuple(
        ProviderSchema(provider_id=adapter, schema_version=version)
        for adapter, version in sorted(pairs)
    )


def source_hashes_of(results: Iterable[ProviderResult]) -> tuple[SourceHash, ...]:
    """Every source the build read, with its digest, sorted and distinct.

    :meth:`~s0ma_dsl.docs_model.providers.ProviderResult.sources` is the
    per-provider answer; this is the union. Two providers reading one file
    contribute one row, because the row is about the file.
    """
    pairs = {pair for result in results for pair in result.sources()}
    return tuple(
        SourceHash(source=source, sha256=digest) for source, digest in sorted(pairs)
    )


def source_commit_of(source_hashes: Sequence[SourceHash]) -> str:
    """The identity of the source state this build read.

    A digest over the sorted ``(source, sha256)`` pairs, in the house
    digest form. See the module docstring for why this is not a git object
    name; in one line: the value has to survive being committed, and has to
    be computable inside a wheel.

    An empty source set produces the digest of an empty list rather than an
    empty string, so that "this build read nothing" is a *statable* fact
    with an identity of its own instead of a blank that reads like a
    missing field. The build that produced it is already refused by the
    anti-vacuity floors.

    The records are digested as records rather than as pre-flattened data:
    :func:`~s0ma_dsl.docs_model.serialize.content_hash` flattens what it is
    given, and handing it something already flat would be flattening twice
    — which the serializer refuses outright, since a bare mapping is not a
    shape the model writes.
    """
    return content_hash(tuple(source_hashes))


def artifact_id(relative: str) -> str:
    """The stable output id of the artifact written at ``relative``.

    The path, prefixed. Architecture §6.8 says paths are mutable and
    identifiers are contracts, which is an argument for an id that does not
    *have* to move when a path does — but inventing a second name for every
    output would create exactly the independently maintained inventory §8.2
    forbids, and there is no authored source for such names. The path is
    the identity this build actually has; a rename is a manifest diff that
    a reviewer sees, which is the honest form of the tradeoff.
    """
    return f"{ARTIFACT_ID_PREFIX}{relative}"


def artifact_format(
    relative: str,
    *,
    packaged: frozenset[str] = frozenset(),
    media: frozenset[str] = frozenset(),
) -> str:
    """Which of architecture §6.6's format words describes this output.

    ``packaged`` names the outputs whose purpose is to be carried inside
    another distribution's wheel — the core teaching slice today. They are
    JSON on disk and ``package_data`` in the model, because §6.6's formats
    describe what an artifact *is for* and the slice is not a document
    anyone opens; it is payload another package ships. The set is a
    parameter rather than a constant here for the reason every decision in
    this package is: the machinery knows the formats, and the application
    says which of its outputs are packaged.

    ``media`` is H3's, and it is the same argument in the same shape. A
    media package is JSON on disk and ``media_manifest`` in the model,
    because §6.6 mints that word for exactly what architecture §13.3
    describes and a package is not a document anyone reads for its
    content: it is the release-bound input a human walkthrough is produced
    from. Calling it plain ``json`` would file it beside the inventories
    and leave §6.6's sixth word naming nothing this build writes.

    Membership in both sets is a contradiction rather than an ordering
    question, so it is refused instead of resolved: an artifact that was
    both a wheel payload and a production input would need two format
    words, and picking one silently would make the manifest's answer
    depend on the order of two lines here.
    """
    both = packaged & media
    if relative in both:
        raise DocsManifestError(
            f"{relative} is declared both packaged and media; §6.6's format "
            f"names what an artifact is *for*, and an output with two "
            f"purposes has no single answer this manifest can state."
        )
    if relative in packaged:
        return "package_data"
    if relative in media:
        return "media_manifest"
    suffix = relative[relative.rfind(".") :] if "." in relative else ""
    fmt = ARTIFACT_FORMATS.get(suffix)
    if fmt is None:
        raise DocsManifestError(
            f"{relative} has no format this manifest can name; the formats "
            f"architecture §6.6 allows for a rendered file are "
            f"{', '.join(sorted(set(ARTIFACT_FORMATS.values())))}, and an "
            f"artifact whose format is unstated carries no provenance "
            f"(DOC_PROVENANCE_MISSING is the rule this would break)."
        )
    return fmt


def _documents_by_source(bundle: DocsBundle, docs_root: str) -> Mapping[str, str]:
    """Catalog row id per rendered path, for the rows that name one.

    The join is on the document's canonical source, which is
    repository-relative, against the artifact's path made
    repository-relative the same way. Nothing is guessed: a path with no
    row gets no id.
    """
    prefix = f"{docs_root}/"
    found: dict[str, str] = {}
    for record in bundle.documents:
        source = record.canonical_source
        if source.startswith(prefix):
            found.setdefault(source[len(prefix) :], record.id)
    return found


# ---------------------------------------------------------------------------
# The manifest
# ---------------------------------------------------------------------------


def manifest_of(
    bundle: DocsBundle,
    *,
    results: Sequence[ProviderResult],
    packages: Iterable[tuple[str, str]],
    artifacts: Sequence[tuple[str, str]],
    docs_root: str,
    packaged: frozenset[str] = frozenset(),
    media: frozenset[str] = frozenset(),
) -> DocsManifest:
    """This build's manifest, from what the build already holds.

    ``artifacts`` are ``(relative path, rendered text)`` pairs — the bytes
    themselves rather than paths to read, because the manifest describes
    what this build *rendered* and a manifest that re-read the files from
    disk would describe what somebody last committed. That is the same
    distinction :func:`~s0ma_dsl.docs_model.application.check` draws when
    it compares in memory against disk, and getting it backwards here would
    make the drift gate self-confirming.

    The manifest does **not** list itself, and cannot: its own content hash
    would have to be computed from bytes that contain it. What covers the
    manifest is the byte gate over the committed file, the same gate that
    covers every other declared output — so the artifact set is complete in
    the only sense available, and the one file it omits is the one file the
    reader is already holding.

    The channel is read off the stamp rather than taken as an argument, so
    that the manifest and every page rendered from the same bundle cannot
    disagree about which build they are.
    """
    versions = package_versions_of(packages)
    product_version = product_version_of(versions)
    hashes = source_hashes_of(results)
    by_source = _documents_by_source(bundle, docs_root)
    channel = bundle.stamp.build_channel
    listed = tuple(
        ArtifactRecord(
            id=artifact_id(relative),
            format=artifact_format(relative, packaged=packaged, media=media),
            source_document=by_source.get(relative, ""),
            path_or_uri=f"{docs_root}/{relative}",
            content_hash=content_hash(text),
            release_version=product_version,
            source_snapshot=bundle.stamp.snapshot_hash,
            build_channel=channel,
        )
        for relative, text in sorted(artifacts)
    )
    return DocsManifest(
        schema=MANIFEST_SCHEMA,
        product_version=product_version,
        build_channel=channel,
        source_commit=source_commit_of(hashes),
        package_versions=versions,
        provider_schemas=provider_schemas_of(results),
        source_hashes=hashes,
        snapshot_hash=bundle.stamp.snapshot_hash,
        artifacts=listed,
    )


def render_manifest(manifest: DocsManifest) -> str:
    """The manifest as the one text form a documentation document may have.

    :func:`~s0ma_dsl.docs_model.serialize.canonical_json` and nothing else:
    sorted keys, two-space indentation, non-ASCII as itself, exactly one
    trailing line feed. The same writer the composed snapshot and the three
    inventories go through, so a reader who has opened one has opened all
    five and a byte comparison means the same thing over each.
    """
    if manifest.build_channel not in BUILD_CHANNELS:
        raise DocsManifestError(
            f"{manifest.build_channel!r} is not a documentation channel; "
            f"architecture §13.2 defines {', '.join(BUILD_CHANNELS)}, and a "
            f"manifest that named a fourth would describe a publication "
            f"posture nothing downstream knows how to treat."
        )
    return canonical_json(to_plain(manifest))


def manifest_from_json(text: str) -> DocsManifest:
    """Read a manifest back from its canonical text, refusing any mismatch.

    :func:`~s0ma_dsl.docs_model.serialize.record_from_plain` does the work,
    which is the point rather than a convenience: it is the same reader the
    composed snapshot goes through, so an unknown key is an error and a
    missing one is too. A manifest is the document H2's wheel verification
    reads out of a release, and a reader that tolerated a stray field would
    quietly accept a manifest written by something other than this
    application.
    """
    import json

    document = json.loads(text)
    if not isinstance(document, dict):
        raise DocsManifestError("a manifest is an object; this text is not one")
    return record_from_plain(DocsManifest, document, "manifest")


#: The manifest's field names, in declaration order. Exported so a proof
#: can assert the written document carries architecture §13.1's list and
#: nothing else — the schema is the contract H2's wheel verification reads,
#: and a field added without a decision is a contract change nobody made.
MANIFEST_FIELDS: tuple[str, ...] = tuple(item.name for item in fields(DocsManifest))

#: Architecture §6.6's ArtifactRecord fields, same purpose.
ARTIFACT_FIELDS: tuple[str, ...] = tuple(item.name for item in fields(ArtifactRecord))
