#!/usr/bin/env python3
"""The documentation application's gate — the ``docs-application`` stage.

ADR-012 §4 gave this stage a charter before anything implemented it. This
script is that charter, executable, and each of its seven items is a named
step below so a reader can check the promise against the code:

1. **Build the snapshot from scratch.** ``build(root)`` boots its own
   provider registry every time and reads no ``.s0ma/registry.db``, no
   cached artifact and nothing a previous run left behind (ADR-012 §3).
2. **Run coverage, authority, link, version, mirror and drift
   validation.** Every one of those gates lives inside that call, which
   is why this script runs no gate of its own: the application API *is*
   the pipeline, and a stage that re-implemented a gate would be a second
   opinion nobody reconciles.
3. **Render every artifact to temporary storage and byte-compare.** Two
   comparisons, and they answer different questions. ``check()`` compares
   the strings this build rendered against the committed files without
   opening anything for writing; the temp render then puts the same
   artifacts through ``write()`` — the function ``s0ma docs compose``
   uses — into a throwaway directory and compares *those* bytes. The
   second one is what catches a writer that mangles an encoding or a line
   ending on this platform, which is the defect ADR-012 §3 names as the
   one that survives a same-directory re-run.
4. **Prove the catalog is complete and non-vacuous.** Completeness is
   ``check_completeness``, inside the build. Non-vacuity is
   ``CATALOG_FLOORS``, also inside the build. What this script adds is
   *visibility*: it prints the corpus it compared and refuses a run whose
   counts fell under the application's own declared floors, so "the docs
   stage passed" can never mean "there was nothing to look at".
5. **No network, no repository writes.** The offline guard below is armed
   before ``s0ma_dsl`` is imported and covers every step, including the
   two that go through the CLI in this same process. Nothing here writes
   under the checkout: the only writes are into a
   :class:`tempfile.TemporaryDirectory`.
6. **Source-located remediation for every failure.** Findings are printed
   in the model's own four-part form — location, code, message, and what
   to write instead.
7. **Collect independent failures.** Every step runs even after an
   earlier one failed, and the exit code is the first non-zero one.

**What rides here rather than in ``selfhost-build``.** The committed
``docs/_built/`` tree is byte-gated by step 4 of this stage, not by the
self-host stage that gates the s0ma-mcp and s0ma-studi0 builds, for three
reasons that all point the same way. The self-host stage rebuilds **in
place** and restores afterwards, and charter item 5 forbids this
application from writing into the repository at all — ``s0ma build
--check`` renders to a temporary directory and writes nothing, so it is
the instrument that fits the charter. ``SelfHosted`` describes a
*distribution* whose wheel ships its build output, and ADR-012 §1 is
explicit that the documentation project is not a distribution and ships in
no wheel. And ADR-012 §4 chose this stage's slot precisely so that a
documentation failure is reported "while the tree is still the tree that
was committed" — which is a statement that the documentation checks finish
before ``selfhost-build`` starts touching anything.

**The declared mode is read, never assumed.** ``docs/pyproject.toml``
carries ``[tool.s0ma].mode``, and since 0.8.0 ``s0ma build`` reads that key
itself — so step 4 passes no ``--mode`` flag and proves the table-driven
path, exactly as the self-host stage does. The doc-emitter subcommands do
*not* read the table (the key is honoured by the six project-resolving
commands only), so step 3 reads the value out of the project table here and
passes it on. Either way the mode on that one line is the mode this gate
enforces, and no second copy of it exists in this file.

**The channel is followed, never chosen** (H2c). Step 1 composes the tree
it is gating, so it can only byte-compare against a committed artifact if
it composes in the *same channel* that artifact was composed in — and the
committed tree already says which one that was, in the ``build_channel``
of the manifest this stage reads anyway. So the claim leads and this gate
follows it: a tree claiming ``preview`` is composed untagged, exactly as
every tree was before this paragraph existed, and a tree claiming a
release is composed at the tag :data:`HEAD_TAG_ENV` states. What makes
that a property rather than a convenience is the *absent* case. A
release-composed tree with nobody stating the tag is refused, which means
a release-composed tree gates only where the release tag is stated — the
release cut and the tag push — and ``main`` cannot quietly carry
release-labelled documentation, because the gate that guards ``main`` has
no tag to state. The tag arrives as a value in both directions and
:func:`head_tag_for_claim` is the whole of the rule; nothing here runs
``git``, so no tree can promote itself by standing somewhere.
"""

from __future__ import annotations

import argparse
import os
import socket
import sys
import tempfile
import tomllib
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Sequence

    from s0ma_dsl.docs_model.application import Build
    from s0ma_dsl.docs_model.manifest import DocsManifest
    from s0ma_dsl.docs_model.providers import Finding
    from s0ma_dsl.docs_model.records import DocsBundle

ROOT = Path(__file__).resolve().parent.parent

#: The documentation application's root, relative to a checkout. Named
#: here as a string rather than imported, because this script has to find
#: ``docs/pyproject.toml`` before it imports anything from ``s0ma_dsl``
#: (the offline guard is armed first, and reading the mode is what tells
#: step 3 which mode to run in). Step 1 asserts it equals the API's own
#: ``DOCS_ROOT``, so the two cannot drift apart silently.
DOCS_ROOT = "docs"


# ---------------------------------------------------------------------------
# The offline guard (charter item 5) — armed before s0ma_dsl is imported
# ---------------------------------------------------------------------------


class NetworkAttempted(RuntimeError):
    """Something in this stage tried to reach the network.

    Never expected, and never caught: ADR-012 §3 lists local network
    services among the things a documentation build must not depend on,
    so an attempt is a defect in the build rather than a condition this
    stage recovers from. It surfaces as a traceback naming this class,
    which is the loudest available answer to "did the gate go online".
    """


#: Addresses that are this machine talking to itself. A guard that
#: refused these would not be stricter, it would be wrong: composing this
#: repository's documentation runs core's MCP server's ``list_tools()``
#: through ``asyncio.run`` in-process, and an asyncio event loop builds
#: its self-pipe out of a socket pair — on POSIX a bare
#: ``socket.socketpair()``, on Windows a loopback ``bind``/``connect``
#: pair, because Windows has no ``AF_UNIX`` socketpair. Blocking loopback
#: would therefore make this gate pass on POSIX and fail on Windows for a
#: reason that has nothing to do with documentation, which is exactly the
#: class of defect the cross-platform rule exists to catch.
LOOPBACK = frozenset({"", "localhost", "127.0.0.1", "::1", "0.0.0.0", "::"})


def _is_local(address: object) -> bool:
    """True when *address* is this machine — a Unix path or loopback."""
    if isinstance(address, str | bytes):
        return True  # an AF_UNIX path never leaves the machine
    if isinstance(address, tuple) and address:
        host = address[0]
        if isinstance(host, bytes):
            host = host.decode("utf-8", errors="replace")
        return str(host) in LOOPBACK
    return False


def arm_offline_guard() -> None:
    """Refuse every call that would reach a host other than this one.

    The methods are patched **on the real class**, not the module
    attribute, and that is the durable half of the B3 spike's lesson:
    patching ``socket.socket`` alone misses a caller that already bound
    the class with ``from socket import socket``, while patching the
    methods catches every instance however the class was reached. The
    spike replaced the class as well because it wanted to forbid creating
    a socket at all; forbidding the *operation* instead means there is no
    class to replace, and therefore no ``class SSLSocket(socket)``
    subclassing hazard to work around.

    What is refused is reaching somewhere else: connecting to a non-local
    address, or resolving a name that is not loopback. What is allowed is
    this machine talking to itself, for :data:`LOOPBACK`'s reason.
    ``subprocess`` is untouched on purpose — the one process a
    documentation build starts is ``git ls-files``, a read of the local
    checkout.
    """
    real_socket = socket.socket
    real_connect = real_socket.connect
    real_connect_ex = real_socket.connect_ex
    real_create_connection = socket.create_connection
    real_getaddrinfo = socket.getaddrinfo

    def connect(self: Any, address: Any, *args: Any, **kwargs: Any) -> Any:
        if not _is_local(address):
            raise NetworkAttempted(f"connect to {address!r}")
        return real_connect(self, address, *args, **kwargs)

    def connect_ex(self: Any, address: Any, *args: Any, **kwargs: Any) -> Any:
        if not _is_local(address):
            raise NetworkAttempted(f"connect_ex to {address!r}")
        return real_connect_ex(self, address, *args, **kwargs)

    def create_connection(address: Any, *args: Any, **kwargs: Any) -> Any:
        if not _is_local(address):
            raise NetworkAttempted(f"create_connection to {address!r}")
        return real_create_connection(address, *args, **kwargs)

    def getaddrinfo(host: Any, *args: Any, **kwargs: Any) -> Any:
        if host is not None and not _is_local((host, None)):
            raise NetworkAttempted(f"getaddrinfo for {host!r}")
        return real_getaddrinfo(host, *args, **kwargs)

    real_socket.connect = connect  # type: ignore[method-assign]
    real_socket.connect_ex = connect_ex  # type: ignore[method-assign]
    socket.create_connection = create_connection
    socket.getaddrinfo = getaddrinfo


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------


def _report(findings: Sequence[Finding], heading: str) -> int:
    """Print every finding in the model's four-part form (charter item 6)."""
    if not findings:
        return 0
    print(f"{heading}: {len(findings)} finding(s).")
    for item in findings:
        print(f"\n  {item.rendered()}")
        print(f"    -> {item.remediation}")
    print()
    return 1


def _declared_mode(root: Path) -> str:
    """``[tool.s0ma].mode`` from the documentation project's own table."""
    table = tomllib.loads(
        (root / DOCS_ROOT / "pyproject.toml").read_text(encoding="utf-8")
    )
    mode = table["tool"]["s0ma"]["mode"]
    if not isinstance(mode, str):  # pragma: no cover - the loader refuses first
        raise TypeError(f"{DOCS_ROOT}/pyproject.toml declares a non-string mode")
    return mode


# ---------------------------------------------------------------------------
# The channel this committed tree claims (H2c)
# ---------------------------------------------------------------------------

#: Where a release tag is stated to this stage. ``--head-tag`` (H2b) is the
#: interactive channel for the same value; this is the non-interactive one,
#: because ``scripts/check.py`` runs its stages as subprocesses and a flag
#: would have to be threaded through a runner that knows nothing about
#: documentation. One value, one rule, stated either way — and stated
#: rather than looked up, which is why the release case is provable here
#: from a scratch tree instead of from a tag somebody has to cut first.
HEAD_TAG_ENV = "S0MA_HEAD_TAG"


def committed_claim(root: Path) -> DocsManifest | None:
    """The manifest the committed tree carries, or ``None`` if it carries none.

    Read through the application's own reader, which refuses an unknown
    key and a missing one alike — the same reading H2's wheel verification
    makes of a released manifest, so "the gate and the wheel disagree
    about what this document says" is not a failure either can have.

    ``None`` covers the tree that has no manifest and the tree whose
    manifest is unreadable, and neither is refused *here*. Both are
    already failures of step 1 — an absent manifest is an artifact
    rendered and never committed, an unreadable one is bytes that differ —
    and those reports name the file and say what to run. Refusing twice
    would replace a located finding with a vaguer one earlier.
    """
    from s0ma_dsl.docs_model.application import DOCS_MANIFEST_OUTPUT
    from s0ma_dsl.docs_model.manifest import manifest_from_json

    path = root / DOCS_ROOT / DOCS_MANIFEST_OUTPUT
    if not path.is_file():
        return None
    try:
        return manifest_from_json(path.read_text(encoding="utf-8"))
    except (ValueError, OSError):
        # ValueError covers both the reader's DocsManifestError and the
        # JSONDecodeError under it; the bytes gate reports the real defect.
        return None


def head_tag_for_claim(
    *, claimed_channel: str, product_version: str, stated: str
) -> tuple[str, str]:
    """The tag to compose with, or the refusal that says why there is none.

    The whole of H2c's rule, pure and in one place, so that what the gate
    does is a function of three values a test can supply rather than of a
    checkout somebody has to construct.

    Returns ``(head_tag, refusal)``. An empty refusal means compose with
    ``head_tag`` — empty itself for the preview claim, which is every tree
    in ordinary development and is byte-for-byte what this stage did
    before the channel existed. A non-empty refusal means this tree claims
    a composition the gate was not told how to reproduce, and the string
    is what to print.

    ``stated`` is :data:`HEAD_TAG_ENV`'s value, passed in rather than read
    here for the reason ``channel_of`` takes its tag as a parameter: a
    rule that reached for the environment could not be asked a question
    about a tree it is not standing in.
    """
    from s0ma_dsl.docs_model.manifest import channel_of, version_tag
    from s0ma_dsl.docs_model.records import PREVIEW_CHANNEL, RELEASE_CHANNEL

    if claimed_channel == PREVIEW_CHANNEL:
        # ``stated`` is deliberately not consulted. A preview tree composes
        # untagged whatever the environment holds, which keeps this path
        # byte-identical to the one every contributor has always run and
        # keeps an exported variable from turning main red. It also leaves
        # the one judgement it might tempt — a preview-composed tree *at* a
        # release tag — where H2 already makes it, in the wheel
        # verification that has a negative fixture for exactly that; a
        # gate re-deciding it here would be a second opinion nobody
        # reconciles.
        return "", ""

    expected = version_tag(product_version)

    if claimed_channel != RELEASE_CHANNEL:
        # ``historical`` is the third channel and is *declared*, never
        # derived (architecture §13.2) — so no tag reproduces it and this
        # gate has nothing to compose against.
        return "", (
            f"{DOCS_ROOT}/_generated/docs-manifest.json claims the "
            f"{claimed_channel} channel, and this application composes no "
            f"such build: `channel_of` derives {PREVIEW_CHANNEL} and "
            f"{RELEASE_CHANNEL} from a version and a tag, and nothing else. "
            f"A channel written by hand is a tree nothing can rebuild, so "
            f"there is no composition for this stage to compare against.\n"
            f"  -> recompose the tree — `uv run s0ma --project-root "
            f"{DOCS_ROOT} docs compose --output-dir {DOCS_ROOT}` for a "
            f"preview, `--head-tag {expected}` for the release."
        )

    if not stated:
        return "", (
            f"{DOCS_ROOT}/_generated/docs-manifest.json claims the "
            f"{claimed_channel} channel at {product_version}, and nothing "
            f"stated the tag it was cut under. This stage composes the tree "
            f"it gates and compares the bytes, so it can only reproduce a "
            f"{claimed_channel} build when it is told the same value "
            f"`s0ma docs compose --head-tag` was given — as a value, never a "
            f"lookup: nothing here runs `git`.\n"
            f"  -> state it and run the gate again:\n"
            f"       {HEAD_TAG_ENV}={expected} uv run python scripts/check.py\n"
            f"     A {claimed_channel}-composed tree therefore gates only "
            f"where the release tag is stated, which is the release cut and "
            f"the tag push. On main, compose without --head-tag: a tree "
            f"nobody cut is a {PREVIEW_CHANNEL} tree, and this refusal is "
            f"what stops main from carrying {claimed_channel}-labelled "
            f"documentation nobody released."
        )

    if channel_of(product_version=product_version, head_tag=stated) != claimed_channel:
        return "", (
            f"{DOCS_ROOT}/_generated/docs-manifest.json claims the "
            f"{claimed_channel} channel at {product_version} and "
            f"{HEAD_TAG_ENV} states {stated}, which is not {expected}. By "
            f"the rule the build itself used (`channel_of`, architecture "
            f"§13.2) a tree standing at {stated} composes "
            f"{channel_of(product_version=product_version, head_tag=stated)}, "
            f"so the claim and the stated tag describe two different builds "
            f"and no composition satisfies both.\n"
            f"  -> state {expected} if this is that release; if it is not, "
            f"recompose without --head-tag so the tree says what it is."
        )

    return stated, ""


def channel_decision(root: Path) -> tuple[str, str, str]:
    """``(head_tag, announcement, refusal)`` for the tree at *root*.

    The thin shell around the rule: it reads the committed claim and the
    environment, and every judgement it makes is
    :func:`head_tag_for_claim`'s.
    """
    from s0ma_dsl.docs_model.application import DOCS_MANIFEST_OUTPUT

    claim = committed_claim(root)
    if claim is None:
        # No readable claim, so no tag: compose the way this stage always
        # did and let step 1 report the manifest itself, which it will.
        return "", (
            f"Channel: {DOCS_ROOT}/{DOCS_MANIFEST_OUTPUT} states no readable "
            f"claim; composing untagged and leaving the manifest to step 1."
        ), ""

    head_tag, refusal = head_tag_for_claim(
        claimed_channel=claim.build_channel,
        product_version=claim.product_version,
        stated=os.environ.get(HEAD_TAG_ENV, "").strip(),
    )
    if refusal:
        return "", "", refusal
    where = f"at the tag {HEAD_TAG_ENV} states, {head_tag}" if head_tag else "untagged"
    return head_tag, (
        f"Channel: the committed manifest claims {claim.build_channel} at "
        f"{claim.product_version}; composing {where}."
    ), ""


# ---------------------------------------------------------------------------
# Step 1 — compose from scratch, gate, and byte-compare (charter items 1-4, 6)
# ---------------------------------------------------------------------------


def compose_and_compare(root: Path, head_tag: str = "") -> tuple[int, Build | None]:
    """Build the snapshot, run every gate, and compare every artifact.

    Returns the step's exit code and the composition, so the determinism
    step can compare against this one rather than composing three times.
    A composition that raised has no bundle to hand back, and the caller
    skips the steps that would need one.

    ``head_tag`` is :func:`channel_decision`'s answer, and empty — the
    default, and every tree that claims a preview — composes exactly what
    this step composed before the channel existed.
    """
    from s0ma_dsl.docs_model import application as api
    from s0ma_dsl.docs_model.providers_catalog import CATALOG_FLOORS, PROVIDER_ID
    from s0ma_dsl.docs_model.records import DocsModelError

    build, check, write = api.build, api.check, api.write

    # The path this script had to know before it could import anything is
    # the path the application declares. Two names for one directory is
    # how a gate ends up checking a tree nobody builds.
    assert api.DOCS_ROOT == DOCS_ROOT, (api.DOCS_ROOT, DOCS_ROOT)
    base = root / DOCS_ROOT

    try:
        result = build(root, head_tag=head_tag)
    except DocsModelError as exc:
        # A provider refusing its source, or a composition that cannot be
        # built at all. There is no bundle to report findings about, so
        # this is the one failure that is a message rather than a list.
        print(f"the documentation could not be composed: {exc}")
        return 1, None

    stamp = result.bundle.stamp
    print(f"Composed {stamp.snapshot_hash} at release {stamp.release_version}.")

    # Charter item 4, made visible. The floors themselves are the
    # application's, asserted inside the build; what is printed here is
    # the size of the corpus this run actually put under comparison, so a
    # gate that passed over nothing cannot read as a gate that passed.
    documents = len(result.bundle.documents)
    corpus_floor = CATALOG_FLOORS[PROVIDER_ID, "documents"]
    # Half the declared-output set is computed from the concepts this
    # build composed (F5), so the artifact floor is a question about this
    # build rather than a constant. Asked the way the application asks it.
    artifact_floor = len(api.generated_outputs(result.bundle))
    policy = api.coverage_policy(root)
    unbound = sum(
        1 for surface in result.bundle.surfaces if not surface.component_refs
    )
    print(
        f"Corpus: {documents} document(s) (floor {corpus_floor}), "
        f"{len(result.bundle.concepts)} concept(s), "
        f"{len(result.bundle.surfaces)} surface(s), "
        f"{len(result.bundle.journeys)} journey(s); "
        f"{len(result.artifacts)} artifact(s) (floor {artifact_floor})."
    )
    print(
        f"Ledgers: reference_only {len(policy.surface_exceptions)}/"
        f"{api.REFERENCE_ONLY_CEILING} surface(s) + "
        f"{len(policy.channel_exceptions)} channel ruling(s); "
        f"unbound {unbound}/{api.UNBOUND_CEILING} surface(s)."
    )

    codes = [_report(result.findings, "The composition does not check out")]
    codes.append(_report(check(result, base), "The committed artifacts have drifted"))

    # Charter item 3's temporary render. The same writer the write command
    # uses, pointed somewhere that is not the repository, compared file by
    # file against what is committed.
    with tempfile.TemporaryDirectory(prefix="s0ma-docs-gate-") as scratch:
        rendered = write(result, Path(scratch))
        emitted = sorted(
            path.relative_to(scratch).as_posix()
            for path in Path(scratch).rglob("*")
            if path.is_file()
        )
        codes.append(
            _compare_temp_render(
                base, Path(scratch), rendered, emitted, result.bundle
            )
        )

    if documents < corpus_floor or len(result.artifacts) < artifact_floor:
        # Both are gated inside the build as DOC_GATE_VACUOUS findings, so
        # reaching here means one of those gates stopped firing. Refusing
        # twice is cheap; a gate that passed vacuously is not.
        print(
            f"the corpus this stage compared is below the application's own "
            f"floors ({documents} document(s) against {corpus_floor}, "
            f"{len(result.artifacts)} artifact(s) against {artifact_floor}) "
            f"and no finding said so — check the floors in the application "
            f"before believing this run."
        )
        codes.append(1)

    return next((code for code in codes if code != 0), 0), result


def _compare_temp_render(
    base: Path,
    scratch: Path,
    rendered: Sequence[Path],
    emitted: Sequence[str],
    bundle: DocsBundle,
) -> int:
    """Every temp-rendered artifact equals the committed one, byte for byte."""
    from s0ma_dsl.docs_model.application import generated_outputs

    expected = sorted(generated_outputs(bundle))
    failed = 0
    if emitted != expected:
        print(
            f"the temporary render produced {emitted} and the application "
            f"declares {expected}. A writer that emits a file the declared "
            f"set has not heard of writes one nothing compares."
        )
        failed = 1
    for path in rendered:
        relative = path.relative_to(scratch).as_posix()
        committed = base / Path(relative)
        if not committed.is_file():
            print(f"{DOCS_ROOT}/{relative}: rendered but never committed.")
            failed = 1
            continue
        if committed.read_bytes() != path.read_bytes():
            print(
                f"{DOCS_ROOT}/{relative}: the bytes `s0ma docs compose` would "
                f"write differ from the bytes committed. Run "
                f"`uv run s0ma --project-root {DOCS_ROOT} docs compose "
                f"--output-dir {DOCS_ROOT}` and commit the result."
            )
            failed = 1
    return failed


# ---------------------------------------------------------------------------
# Step 2 — the same tree composes the same way twice
# ---------------------------------------------------------------------------


def compose_twice(root: Path, first: Build, head_tag: str = "") -> int:
    """A second composition of the same checkout is the same composition.

    ADR-012's acceptance asks for the stage green twice from clean, and
    the property underneath that is determinism: no wall clock, no
    randomness, no import order reaching a record. Proving it inside one
    run costs a second composition and catches the failure in the run
    that introduced it rather than in the next one.

    The same ``head_tag`` as the first composition, because the question
    is whether one tree composes twice the same way — two compositions
    told different things would answer a question nobody asked.
    """
    from s0ma_dsl.docs_model.application import build

    second = build(root, head_tag=head_tag)
    if second.bundle.stamp.snapshot_hash != first.bundle.stamp.snapshot_hash:
        print(
            f"composing the same checkout twice produced "
            f"{first.bundle.stamp.snapshot_hash} and then "
            f"{second.bundle.stamp.snapshot_hash}. Something in the "
            f"composition is reading a clock, a random value, or an "
            f"import order (ADR-012 §3)."
        )
        return 1
    differing = sorted(
        one.relative
        for one, other in zip(first.artifacts, second.artifacts, strict=True)
        if one.content != other.content
    )
    if differing:
        print(
            f"two compositions of one checkout rendered the same snapshot "
            f"hash and different bytes for: {', '.join(differing)}. The "
            f"non-determinism is in a renderer rather than in the model."
        )
        return 1
    print("Determinism: two compositions of this checkout agree, hash and bytes.")
    return 0


# ---------------------------------------------------------------------------
# Steps 3 and 4 — the doc-declaration surface and the committed build
# ---------------------------------------------------------------------------


def _cli(argv: list[str]) -> int:
    """Run one ``s0ma`` invocation in this process, under the guard.

    In-process rather than as a subprocess for one reason: the offline
    guard is armed here, and a child process would not inherit it. The
    CLI returns its exit code rather than raising ``SystemExit`` (that
    happens in ``cli.main.main``, one level above ``S0maCLI.run``), so
    the code is the value.
    """
    from s0ma_dsl.cli.main import S0maCLI

    print(f"  $ s0ma {' '.join(argv)}", flush=True)
    return S0maCLI().run(argv)


def check_declared_doc_outputs(root: Path, mode: str) -> int:
    """Every ``doc-ref`` / ``doc-guide`` output equals what re-renders.

    ``s0ma docs check-drift`` re-renders each declaration into memory and
    compares against the committed file; the doc-emitter subcommands do
    not read ``[tool.s0ma].mode``, so the declared mode is passed in
    rather than defaulted — which is what makes ``EMPTY_DOC_FILTER`` and
    the release-mode coverage checks part of this gate.

    Passing this step over an empty set of declarations is not possible
    while the project declares ``release``, and that is where this step's
    anti-vacuity floor lives rather than in a count here:
    ``MISSING_PUBLIC_DOC_REF`` fails the run the moment a PUBLIC nerve
    stops being covered by a ``doc-ref``, and ``EMPTY_DOC_FILTER`` fails
    it the moment a ``doc-ref`` stops matching anything. A silent drop to
    zero declarations turns this step red before it has nothing to
    compare.
    """
    return _cli([
        "--project-root", str(root / DOCS_ROOT),
        "docs", "check-drift", str(root / DOCS_ROOT / "s0ma_src"),
        "--output-dir", str(root / DOCS_ROOT),
        "--mode", mode,
    ])


def _built_snapshot(built: Path) -> dict[str, bytes]:
    """Every file under *built* as relative-POSIX -> bytes.

    The same reading ``scripts/check.py`` takes of a self-hosted
    package's committed build, and it skips the same two subtrees: the
    regenerable ``.s0ma.cache/`` (gitignored, and this stage builds with
    ``--no-cache``) and ``__pycache__/`` (the interpreter's, not the
    transpiler's).
    """
    snapshot: dict[str, bytes] = {}
    for path in sorted(built.rglob("*")):
        if not path.is_file():
            continue
        relative = path.relative_to(built).as_posix()
        if relative.startswith(".s0ma.cache/") or "/__pycache__/" in f"/{relative}":
            continue
        snapshot[relative] = path.read_bytes()
    return snapshot


def check_committed_build(root: Path) -> int:
    """The committed ``docs/_built/`` tree is what the sources produce.

    The project is copied — ``pyproject.toml`` and ``s0ma_src/``, which
    is everything a build reads — into a temporary directory and built
    *there*, then every emitted byte is compared against every committed
    one. Two properties fall out of that shape, and neither would from a
    rebuild in place:

    * **Nothing is written under the checkout** (charter item 5). The
      build's own ``.s0ma/`` state and its cache land in the temporary
      copy and go away with it, so a red gate cannot leave the working
      tree dirty and there is nothing to restore in a ``finally``.
    * **It is the cross-path determinism proof.** ADR-012 §3 asks this
      application's gate to keep the shape the B1 spike proved — two
      copies of one project at different absolute paths rendering
      identical bytes — because "Windows CI is real and a path leaking
      into a rendered page is exactly the defect that survives a
      same-directory re-run". Building at a path that is not the
      checkout's is what asks that question on every run.

    ``build --check`` was the obvious instrument and is not enough: it
    compares only the per-module outputs, so the manifest, the typed
    stub, the package ``__init__`` and the two self-context artifacts —
    five of the nine committed files — would never be looked at.

    No ``--mode`` flag. ``s0ma build`` reads ``[tool.s0ma].mode`` from the
    copied ``pyproject.toml``, so the declared mode stays load-bearing and
    this file never becomes a second place the ramp has to be edited.
    """
    import shutil

    committed = _built_snapshot(root / DOCS_ROOT / "_built")
    if not committed:
        print(
            f"{DOCS_ROOT}/_built holds no committed files. There is nothing "
            f"for this step to compare, which is a passing gate over an "
            f"absent build rather than a build that matches."
        )
        return 1

    with tempfile.TemporaryDirectory(prefix="s0ma-docs-build-") as scratch:
        project = Path(scratch) / DOCS_ROOT
        project.mkdir(parents=True)
        shutil.copy2(root / DOCS_ROOT / "pyproject.toml", project / "pyproject.toml")
        shutil.copytree(root / DOCS_ROOT / "s0ma_src", project / "s0ma_src")

        code = _cli([
            "--project-root", str(project),
            "build", str(project),
            "--no-cache",
            "--quiet",
        ])
        if code != 0:
            print(
                f"`s0ma build` failed (exit {code}) — the .s0ma sources do "
                f"not build; fix them before worrying about byte-equality."
            )
            return 1

        rebuilt = _built_snapshot(project / "_built")

    changed = sorted(
        relative
        for relative in committed.keys() & rebuilt.keys()
        if committed[relative] != rebuilt[relative]
    )
    missing = sorted(committed.keys() - rebuilt.keys())
    unexpected = sorted(rebuilt.keys() - committed.keys())
    if not (changed or missing or unexpected):
        print(
            f"Committed build: {len(committed)} file(s) byte-identical to a "
            f"build of the same sources at another path."
        )
        return 0

    print(
        f"the committed {DOCS_ROOT}/_built tree is not what these sources "
        f"produce:"
    )
    for relative in changed:
        print(f"  CHANGED    {relative}")
    for relative in missing:
        print(f"  MISSING    {relative} (committed, not re-emitted)")
    for relative in unexpected:
        print(f"  UNEXPECTED {relative} (re-emitted, not committed)")
    print(
        f"  -> either a .s0ma source or the transpiler changed without a "
        f"rebuild (run `uv run s0ma --project-root {DOCS_ROOT} build "
        f"{DOCS_ROOT}` and commit s0ma_src/ and _built/ together), or a "
        f"machine path reached a build artifact and the build stopped being "
        f"path-independent (ADR-012 §3). Both are real failures."
    )
    return 1


# ---------------------------------------------------------------------------
# The stage
# ---------------------------------------------------------------------------


def check(root: Path = ROOT) -> int:
    """Run every step against *root*, collecting rather than stopping."""
    mode = _declared_mode(root)
    print(f"docs-application: gating {root / DOCS_ROOT} at mode {mode}.")

    # Before any step, because every step after this one composes and a
    # composition in the wrong channel compares the right bytes against
    # the wrong build. This is not a step and does not collect (charter
    # item 7 is about independent failures; nothing here is independent of
    # knowing what to compose) — it decides whether there is a gate to run.
    head_tag, announcement, refusal = channel_decision(root)
    if refusal:
        print(f"\n  -- the channel this committed tree claims\n{refusal}\n")
        print("docs-application: the tree's own claim was not reproducible; "
              "nothing was gated.")
        return 1
    print(announcement)

    codes: list[int] = []
    print("\n  -- compose from scratch, gate, and byte-compare")
    code, result = compose_and_compare(root, head_tag)
    codes.append(code)

    if result is not None:
        print("\n  -- the same checkout composes the same way twice")
        codes.append(compose_twice(root, result, head_tag))

    print("\n  -- declared doc outputs match what the emitter renders")
    codes.append(check_declared_doc_outputs(root, mode))

    print("\n  -- the committed application build is what the sources produce")
    codes.append(check_committed_build(root))

    failed = [code for code in codes if code != 0]
    print()
    if failed:
        print(f"docs-application: {len(failed)} step(s) failed.")
        return failed[0]
    print("docs-application: every step passed.")
    return 0


def main(argv: list[str] | None = None) -> int:
    # Windows consoles/redirections can default to cp1252, where echoing a
    # finding (the model's prose is full of em-dashes) would raise
    # UnicodeEncodeError and kill this gate's own reporting. Same guard,
    # and same reason, as scripts/check.py; a subprocess needs its own.
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except AttributeError:  # non-TextIOWrapper streams (e.g. captured/wrapped)
        pass

    parser = argparse.ArgumentParser(
        description="s0ma documentation application gate (ADR-012 §4)"
    )
    parser.add_argument(
        "root",
        nargs="?",
        default=None,
        help="checkout root to gate (default: this script's repository)",
    )
    options = parser.parse_args(argv)
    arm_offline_guard()
    return check(ROOT if options.root is None else Path(options.root).resolve())


if __name__ == "__main__":
    raise SystemExit(main())
