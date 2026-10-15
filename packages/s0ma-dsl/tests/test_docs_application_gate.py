"""The ``docs-application`` gate — ``scripts/check_docs_application.py``.

Milestone F1 of the docs-function plan (internal) §11. ADR-012 §4 wrote the
stage's charter a phase before anything ran it; these are the proofs that
the charter is kept rather than described.

The interesting half is the red half. A gate that has only ever been seen
green is a gate nobody has watched work, so every claim below is made
twice — once on the tree as it stands, and once against a **copy** of the
checkout with a deliberate fault planted in it:

* a committed application artifact edited by hand;
* the ``doc-ref`` render edited by hand;
* a file in the committed ``docs/_built/`` tree edited by hand;
* a tracked Markdown file nobody cataloged.

Each has to turn the stage red *and name the file*, because "the docs
stage failed" is a report somebody then has to reproduce by hand.

**Why a copy rather than the tree.** Charter item 5 says the stage makes
no repository writes, and a test that planted a fault in ``docs/`` would
have to write one — and would leave the checkout dirty if it died between
the plant and the restore. The copy is built from ``git ls-files`` plus the
untracked-but-not-ignored files, which is the working tree as a future
commit would see it, and it is a real git repository because the catalog's
completeness gate asks ``git ls-files`` what the corpus is. Running the
stage against it is also the cross-path proof in its own right: the gate
passes at an absolute path that is not the one anything was built at.

**Why the offline guard is proved in a subprocess.** Arming it replaces
methods on ``socket.socket`` for the whole process, and a test that armed
it here would arm it for every test that ran afterwards. The subprocess
pays a fraction of a second and contaminates nothing.
"""

from __future__ import annotations

import importlib.util
import os
import re
import shutil
import subprocess
import sys
import time
from functools import cache
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from s0ma_dsl.docs_model.records import (
    HISTORICAL_CHANNEL,
    PREVIEW_CHANNEL,
    RELEASE_CHANNEL,
)
from tests._committed_claim import claimed_head_tag, preview_tree_only

if TYPE_CHECKING:
    from collections.abc import Iterator
    from types import ModuleType

#: The monorepo root (this file: packages/s0ma-dsl/tests/<file>).
REPO_ROOT = Path(__file__).resolve().parents[3]
GATE = REPO_ROOT / "scripts" / "check_docs_application.py"
CHECK_PY = REPO_ROOT / "scripts" / "check.py"

_GIT = shutil.which("git")

#: The stage's own budget. F1's target is under two minutes; the live
#: stage runs in about a second, so the assertion is set an order of
#: magnitude above the measurement rather than at it — a regression this
#: catches is a structural one (a provider that started walking the tree,
#: a gate that started re-composing per record), not a slow machine.
RUNTIME_BUDGET_SECONDS = 120.0


def _is_checkout() -> bool:
    return (REPO_ROOT / ".git").exists() and _GIT is not None


requires_checkout = pytest.mark.skipif(
    not _is_checkout(), reason="not a git checkout (wheel-install context)"
)


@cache
def _gate() -> ModuleType:
    """Import ``scripts/check_docs_application.py`` for unit-level proofs.

    Registered in ``sys.modules`` before execution for the reason
    ``test_check_links_script.py`` gives: ``@dataclass`` resolves a
    class's module through it, and a file-path module loaded without that
    registration fails inside the decorator.
    """
    spec = importlib.util.spec_from_file_location("s0ma_check_docs_application", GATE)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


#: Loads the gate module and arms its guard in a fresh interpreter. The
#: guard replaces methods on ``socket.socket`` for the whole process, so
#: every proof about it runs somewhere that is thrown away afterwards.
_PROBE_PREAMBLE = (
    "import sys\n"
    "import importlib.util\n"
    f"spec = importlib.util.spec_from_file_location('gate', {str(GATE)!r})\n"
    "module = importlib.util.module_from_spec(spec)\n"
    "sys.modules['gate'] = module\n"
    "spec.loader.exec_module(module)\n"
    "module.arm_offline_guard()\n"
)


def _run_gate(
    root: Path | None = None, *, head_tag: str | None = None
) -> subprocess.CompletedProcess[str]:
    """Run the stage as its own process and return the whole result.

    ``head_tag`` states the release tag through the environment, which is
    how a release cut and the tag push state it (H2c). ``None`` means
    nobody stated one, and the variable is **removed** rather than merely
    not added: a developer who happens to export it would otherwise get
    different answers out of this suite than CI gets, which is the one
    thing a proof about an environment variable must not allow.
    """
    argv = [sys.executable, str(GATE)]
    if root is not None:
        argv.append(str(root))
    environment = dict(os.environ)
    environment.pop(_gate().HEAD_TAG_ENV, None)
    if head_tag is not None:
        environment[_gate().HEAD_TAG_ENV] = head_tag
    return subprocess.run(  # noqa: S603 - fixed argv, no shell
        argv,
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        env=environment,
        check=False,
    )


@pytest.fixture(scope="module")
def checkout(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """A throwaway copy of this checkout that the gate passes on.

    Tracked files plus untracked-and-not-ignored ones, which is what a
    commit of the working tree would contain; ``git init`` and ``git add``
    make it a repository, because the completeness gate's corpus is
    ``git ls-files`` and a copy without an index reports an empty one.
    """
    if not _is_checkout():  # pragma: no cover - guarded by the marker
        pytest.skip("not a git checkout")
    destination = tmp_path_factory.mktemp("s0ma-checkout")
    listed: list[str] = []
    for arguments in (["-z"], ["--others", "--exclude-standard", "-z"]):
        result = subprocess.run(  # noqa: S603 - fixed argv, no shell
            ["git", "-C", str(REPO_ROOT), "ls-files", *arguments],  # noqa: S607
            capture_output=True,
            text=True,
            encoding="utf-8",
            check=True,
        )
        listed.extend(item for item in result.stdout.split("\0") if item)
    for relative in listed:
        source = REPO_ROOT / relative
        if not source.is_file():  # a deleted-but-still-indexed path
            continue
        target = destination / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
    for arguments in (["init", "-q"], ["add", "-A"]):
        subprocess.run(  # noqa: S603 - fixed argv, no shell
            ["git", "-C", str(destination), *arguments],  # noqa: S607
            capture_output=True,
            check=True,
        )
    return destination


class Plant:
    """Plants a fault in the copy and remembers how to undo it.

    Every fault is planted through this so the module-scoped copy is the
    same tree for the next test whether the last one passed, failed, or
    raised — the ``finally`` in the fixture is what makes a red proof
    safe to write.
    """

    def __init__(self, checkout: Path) -> None:
        self.checkout = checkout
        self.saved: dict[Path, bytes | None] = {}

    def edit(self, relative: str, appended: str) -> Path:
        """Hand-edit a committed file, the way a person would."""
        path = self.checkout / relative
        self.saved.setdefault(path, path.read_bytes() if path.is_file() else None)
        path.write_text(
            path.read_text(encoding="utf-8") + appended,
            encoding="utf-8",
            newline="\n",
        )
        return path

    def create(self, relative: str, content: str) -> Path:
        """Add a *tracked* file — the corpus is ``git ls-files``."""
        path = self.checkout / relative
        self.saved.setdefault(path, path.read_bytes() if path.is_file() else None)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8", newline="\n")
        subprocess.run(  # noqa: S603 - fixed argv, no shell
            ["git", "-C", str(self.checkout), "add", relative],  # noqa: S607
            capture_output=True,
            check=True,
        )
        return path

    def restore(self) -> None:
        for path, before in self.saved.items():
            if before is None:
                path.unlink(missing_ok=True)
            else:
                path.write_bytes(before)
        subprocess.run(  # noqa: S603 - fixed argv, no shell
            ["git", "-C", str(self.checkout), "add", "-A"],  # noqa: S607
            capture_output=True,
            check=False,
        )


@pytest.fixture
def planted(checkout: Path) -> Iterator[Plant]:
    """Restore whatever a test planted, however the test ended."""
    plant = Plant(checkout)
    try:
        yield plant
    finally:
        plant.restore()


@pytest.fixture(scope="module")
def released(
    checkout: Path, tmp_path_factory: pytest.TempPathFactory
) -> tuple[Path, str]:
    """A **release-composed** copy of the checkout, and the tag it was cut at.

    The state H2c exists for, and the one no branch of this repository is
    ever in: a tree whose committed documentation says it was built in the
    release channel. Composed here rather than committed anywhere, because
    committing one would put release-labelled documentation on a branch
    nobody released — which is precisely what the refusal below prevents.

    A copy of its own, not the shared ``checkout``: this recomposes
    every declared artifact, which no ``Plant`` could put back.

    The tag is not invented. It is :func:`version_tag` of the product
    version the committed manifest already carries, read through the
    application's own reader, so a version bump cannot leave this fixture
    composing a release of something else.
    """
    from s0ma_dsl.cli.main import S0maCLI
    from s0ma_dsl.docs_model.manifest import manifest_from_json, version_tag

    destination = tmp_path_factory.mktemp("s0ma-released")
    tree = destination / "tree"
    shutil.copytree(checkout, tree)
    docs = tree / "docs"
    manifest = manifest_from_json(
        (docs / "_generated" / "docs-manifest.json").read_text(encoding="utf-8")
    )
    tag = version_tag(manifest.product_version)
    code = S0maCLI().run([
        "--project-root", str(docs),
        "docs", "compose",
        "--output-dir", str(docs),
        "--head-tag", tag,
    ])
    assert code == 0, f"composing the release copy failed with {code}"
    recomposed = manifest_from_json(
        (docs / "_generated" / "docs-manifest.json").read_text(encoding="utf-8")
    )
    # The fixture is only a fixture if it actually produced the state.
    assert recomposed.build_channel == RELEASE_CHANNEL, recomposed.build_channel
    return tree, tag


# ---------------------------------------------------------------------------
# The offline guard (ADR-012 §4, charter item 5)
# ---------------------------------------------------------------------------


class TestTheOfflineGuard:
    """No host but this one, and this one only because asyncio needs it."""

    @pytest.mark.parametrize(
        "address",
        [
            "/tmp/some.sock",
            b"/tmp/some.sock",
            ("127.0.0.1", 8080),
            ("::1", 8080),
            ("localhost", 80),
            (b"127.0.0.1", 80),
        ],
    )
    def test_local_addresses_are_local(self, address: object) -> None:
        assert _gate()._is_local(address) is True

    @pytest.mark.parametrize(
        "address",
        [
            ("kn0wthyself.ai", 443),
            ("8.8.8.8", 53),
            ("127.0.0.2", 80),
            (),
            None,
            42,
        ],
    )
    def test_everything_else_is_not(self, address: object) -> None:
        assert _gate()._is_local(address) is False

    def test_a_remote_connection_raises_network_attempted(self) -> None:
        """The guard bites, in a process of its own so it bites nobody else."""
        probe = _PROBE_PREAMBLE + (
            "import socket\n"
            "try:\n"
            "    socket.create_connection(('kn0wthyself.ai', 443), timeout=1)\n"
            "except module.NetworkAttempted:\n"
            "    print('REFUSED')\n"
        )
        result = subprocess.run(  # noqa: S603 - fixed argv, no shell
            [sys.executable, "-c", probe],
            capture_output=True,
            text=True,
            encoding="utf-8",
            check=False,
        )
        assert result.returncode == 0, result.stdout + result.stderr
        assert "REFUSED" in result.stdout

    def test_an_asyncio_event_loop_still_starts(self) -> None:
        """The reason loopback is allowed, asserted rather than assumed.

        Composing this repository's documentation runs core's MCP server
        through ``asyncio.run``, and an event loop builds its self-pipe
        out of a socket pair. A guard that refused that would fail this
        gate for a reason unrelated to documentation — and would fail it
        differently on Windows, where the pair is a loopback connect.
        """
        probe = _PROBE_PREAMBLE + (
            "import asyncio\n"
            "async def nothing():\n"
            "    return 'LOOP OK'\n"
            "print(asyncio.run(nothing()))\n"
        )
        result = subprocess.run(  # noqa: S603 - fixed argv, no shell
            [sys.executable, "-c", probe],
            capture_output=True,
            text=True,
            encoding="utf-8",
            check=False,
        )
        assert result.returncode == 0, result.stdout + result.stderr
        assert "LOOP OK" in result.stdout


# ---------------------------------------------------------------------------
# The stage on the tree as it stands
# ---------------------------------------------------------------------------


class TestTheStageOnThisCheckout:
    """Green, quick, and it leaves nothing behind.

    Told the tree's own tag when the committed tree claims release, as the
    release workflow tells it; on a preview tree nothing is stated.
    """

    @requires_checkout
    def test_the_stage_passes_and_says_what_it_compared(self) -> None:
        started = time.monotonic()
        result = _run_gate(head_tag=claimed_head_tag() or None)
        elapsed = time.monotonic() - started
        assert result.returncode == 0, result.stdout + result.stderr
        assert "docs-application: every step passed." in result.stdout
        # Charter item 4 made visible: a run that compared nothing would
        # print the same verdict with none of these counts in it.
        assert "Corpus:" in result.stdout
        assert "Ledgers: reference_only" in result.stdout
        assert "Determinism: two compositions" in result.stdout
        assert "Committed build:" in result.stdout
        assert elapsed < RUNTIME_BUDGET_SECONDS, f"{elapsed:.1f}s"

    @requires_checkout
    def test_the_stage_writes_nothing_into_the_repository(self) -> None:
        """Charter item 5, proved the way C8 proved SDA-INV-9."""

        def porcelain() -> str:
            return subprocess.run(  # noqa: S603 - fixed argv, no shell
                ["git", "-C", str(REPO_ROOT), "status", "--porcelain"],  # noqa: S607
                capture_output=True,
                text=True,
                encoding="utf-8",
                check=True,
            ).stdout

        before = porcelain()
        assert _run_gate(head_tag=claimed_head_tag() or None).returncode == 0
        assert porcelain() == before


# ---------------------------------------------------------------------------
# The stage against a copy, with faults planted in it
# ---------------------------------------------------------------------------


@requires_checkout
class TestTheStageAgainstACopy:
    """Every failure class turns it red, and every one of them names a file.

    The copy carries the committed tree's claim, so the stage is told the
    tree's own tag when that claim is release, and nothing on a preview tree.
    """

    def test_an_unfaulted_copy_passes(self, checkout: Path) -> None:
        """Path independence: the same tree gates green somewhere else.

        ADR-012 §3 asks this application's gate to keep the B1 spike's
        cross-path shape, because a machine path leaking into a rendered
        artifact is the defect a same-directory re-run cannot see.
        """
        result = _run_gate(checkout, head_tag=claimed_head_tag() or None)
        assert result.returncode == 0, result.stdout + result.stderr

    def test_a_drifted_application_artifact_is_named(
        self, checkout: Path, planted: Plant
    ) -> None:
        planted.edit("docs/reference/concepts-index.md", "\nhand edit\n")
        result = _run_gate(checkout, head_tag=claimed_head_tag() or None)
        assert result.returncode != 0
        assert "DOC_OUTPUT_DRIFT" in result.stdout
        assert "reference/concepts-index.md" in result.stdout
        # The remediation, not just the verdict.
        assert "Run the write command" in result.stdout

    def test_a_drifted_doc_ref_render_is_named(
        self, checkout: Path, planted: Plant
    ) -> None:
        planted.edit(
            "docs/reference/documentation-application.md", "\nhand edit\n"
        )
        result = _run_gate(checkout, head_tag=claimed_head_tag() or None)
        assert result.returncode != 0
        assert "DRIFT_DETECTED" in result.stdout
        assert "documentation-application.md" in result.stdout
        assert "s0ma docs render" in result.stdout

    def test_a_drifted_committed_build_file_is_named(
        self, checkout: Path, planted: Plant
    ) -> None:
        planted.edit("docs/_built/self_prompt_card.md", "\nhand edit\n")
        result = _run_gate(checkout, head_tag=claimed_head_tag() or None)
        assert result.returncode != 0
        assert "CHANGED    self_prompt_card.md" in result.stdout
        assert "commit s0ma_src/ and _built/ together" in result.stdout

    def test_an_uncataloged_document_is_named(
        self, checkout: Path, planted: Plant
    ) -> None:
        """The A6 guard's question, asked by this stage instead.

        Not the F2 equivalence note — that milestone owns retiring the
        temporary ledger guard and recording the subsumption. This is the
        half F2 will cite: a tracked Markdown file nobody classified fails
        here, located at the file.
        """
        planted.create(
            "docs/an-uncataloged-page.md", "# Nobody cataloged this\n"
        )
        result = _run_gate(checkout, head_tag=claimed_head_tag() or None)
        assert result.returncode != 0
        assert "DOC_DOCUMENT_UNCATALOGED" in result.stdout
        assert "docs/an-uncataloged-page.md" in result.stdout

    def test_independent_failures_are_all_reported(
        self, checkout: Path, planted: Plant
    ) -> None:
        """Charter item 7: never stop at the first.

        Two faults in two different steps. A stage that returned after the
        first would report one of them, and the contributor would fix it,
        re-run, and meet the second.
        """
        planted.edit("docs/reference/concepts-index.md", "\nhand edit\n")
        planted.edit("docs/_built/self_prompt_card.md", "\nhand edit\n")
        result = _run_gate(checkout, head_tag=claimed_head_tag() or None)
        assert result.returncode != 0
        assert "DOC_OUTPUT_DRIFT" in result.stdout
        assert "CHANGED    self_prompt_card.md" in result.stdout
        assert "docs-application: 2 step(s) failed." in result.stdout


# ---------------------------------------------------------------------------
# The channel the committed tree claims (H2c)
# ---------------------------------------------------------------------------


class TestTheChannelRule:
    """``head_tag_for_claim``: three values in, one decision out.

    The rule is pure so that the four states can be asked as questions
    rather than constructed as checkouts. Each one is asked again against
    a real tree below; these fix *what* the answers are, those fix that
    the stage acts on them.
    """

    def _decide(self, channel: str, stated: str = "") -> tuple[str, str]:
        return _gate().head_tag_for_claim(
            claimed_channel=channel, product_version="0.18.1", stated=stated
        )

    def test_a_preview_claim_composes_untagged(self) -> None:
        assert self._decide(PREVIEW_CHANNEL) == ("", "")

    def test_a_preview_claim_ignores_a_stated_tag(self) -> None:
        """An exported variable cannot change what a preview tree composes.

        The deliberate half of the rule. A contributor with the variable
        left in their shell gates the same tree the same way as CI, and
        the one judgement it might tempt — a preview-composed tree *at* a
        release tag — stays where H2 makes it, in the wheel verification
        that has a negative fixture for it.
        """
        assert self._decide(PREVIEW_CHANNEL, "v0.18.1") == ("", "")
        assert self._decide(PREVIEW_CHANNEL, "v9.9.9") == ("", "")

    def test_a_release_claim_at_its_own_tag_composes_at_that_tag(self) -> None:
        assert self._decide(RELEASE_CHANNEL, "v0.18.1") == ("v0.18.1", "")

    def test_a_release_claim_with_nothing_stated_is_refused(self) -> None:
        head_tag, refusal = self._decide(RELEASE_CHANNEL)
        assert head_tag == ""
        # The four parts a refusal owes a reader: what this tree claims,
        # why that cannot be reproduced, the exact line to run, and the
        # rule that makes the absent case a refusal rather than a default.
        assert "docs-manifest.json" in refusal
        assert f"{_gate().HEAD_TAG_ENV}=v0.18.1 uv run python scripts/check.py" in (
            refusal
        )
        assert "compose without --head-tag" in refusal

    def test_a_release_claim_at_another_tag_is_refused(self) -> None:
        head_tag, refusal = self._decide(RELEASE_CHANNEL, "v9.9.9")
        assert head_tag == ""
        assert "v9.9.9" in refusal and "v0.18.1" in refusal
        # It says which channel that tag *would* compose, by asking the
        # build's own rule rather than by asserting it.
        assert f"composes {PREVIEW_CHANNEL}" in refusal

    def test_a_channel_nothing_derives_is_refused(self) -> None:
        """``historical`` is declared, never derived — so nothing rebuilds it."""
        head_tag, refusal = self._decide(HISTORICAL_CHANNEL)
        assert head_tag == ""
        assert HISTORICAL_CHANNEL in refusal
        assert "docs compose" in refusal

    def test_the_gate_spells_no_channel_of_its_own(self) -> None:
        """The channel words come from the model, like the mode does.

        The sibling of ``test_the_declared_mode_is_read_from_the_project_table``
        and the same failure it guards against: a second copy of a value
        the application owns, which drifts the moment the application's
        moves.
        """
        source = GATE.read_text(encoding="utf-8")
        assert f'"{PREVIEW_CHANNEL}"' not in source
        assert f'"{HISTORICAL_CHANNEL}"' not in source

    def test_the_gate_never_looks_a_tag_up(self) -> None:
        """Stated as a value, in the gate as in ``channel_of`` and H2's smoke.

        A gate that shelled out to ``git`` for its own channel would decide
        what kind of tree it was gating from where the tree was standing,
        which is exactly the promotion this milestone refuses.
        """
        source = GATE.read_text(encoding="utf-8")
        for forbidden in ("git describe", "git tag", "git rev-parse"):
            assert forbidden not in source, forbidden


@requires_checkout
class TestTheStageFollowsTheClaim:
    """The same four states, against real trees, through the real stage."""

    @preview_tree_only
    def test_this_tree_claims_preview_and_gates_green_untagged(
        self, checkout: Path
    ) -> None:
        result = _run_gate(checkout)
        assert result.returncode == 0, result.stdout + result.stderr
        assert f"claims {PREVIEW_CHANNEL}" in result.stdout
        assert "composing untagged" in result.stdout

    @staticmethod
    def _stable(text: str) -> str:
        """The report with its throwaway directory names normalised away.

        Steps 3 and 4 echo the ``s0ma`` commands they run, and those name
        a :class:`tempfile.TemporaryDirectory` whose suffix is random per
        run — so any two runs of one tree differ in that token whatever
        else they do. Normalising it is what lets the comparison below be
        an equality about the channel rather than about ``mkdtemp``.
        """
        return re.sub(r"s0ma-docs-(build|gate)-\w+", r"s0ma-docs-\1-SCRATCH", text)

    @preview_tree_only
    def test_a_stated_tag_changes_nothing_about_a_preview_tree(
        self, checkout: Path
    ) -> None:
        """The zero-change promise, as an equality rather than a claim.

        The same report with the variable set to a release tag and with it
        absent — which is what makes this milestone safe on a repository
        where every tree is a preview tree, including the one belonging to
        a contributor who exported the variable and forgot.
        """
        stated = _run_gate(checkout, head_tag="v0.18.1")
        absent = _run_gate(checkout)
        assert absent.returncode == 0, absent.stdout + absent.stderr
        assert stated.returncode == absent.returncode
        assert self._stable(stated.stdout) == self._stable(absent.stdout)

    def test_a_release_tree_with_nothing_stated_is_refused(
        self, released: tuple[Path, str]
    ) -> None:
        """The property: main cannot quietly carry release-labelled docs.

        A release-composed tree gates only where the release tag is
        stated. Nowhere states it on a branch, so a tree composed as a
        release does not reach ``main`` green.
        """
        tree, tag = released
        result = _run_gate(tree)
        assert result.returncode != 0, result.stdout
        assert f"claims the {RELEASE_CHANNEL} channel" in result.stdout
        assert f"{_gate().HEAD_TAG_ENV}={tag} uv run python scripts/check.py" in (
            result.stdout
        )
        # And it refuses rather than reporting a green gate over nothing.
        assert "nothing was gated" in result.stdout
        assert "every step passed" not in result.stdout

    def test_a_release_tree_gates_green_at_its_own_tag(
        self, released: tuple[Path, str]
    ) -> None:
        """The half that makes a release cut possible at all.

        Before H2c this run failed on all forty-two channel-bearing
        artifacts, so step 5 of the release runbook could not pass on a
        release-composed tree and neither could the ``check`` job the tag
        push runs.
        """
        tree, tag = released
        result = _run_gate(tree, head_tag=tag)
        assert result.returncode == 0, result.stdout + result.stderr
        assert f"claims {RELEASE_CHANNEL}" in result.stdout
        assert "docs-application: every step passed." in result.stdout

    def test_a_release_tree_at_the_wrong_tag_is_refused(
        self, released: tuple[Path, str]
    ) -> None:
        tree, tag = released
        result = _run_gate(tree, head_tag="v9.9.9")
        assert result.returncode != 0, result.stdout
        assert "v9.9.9" in result.stdout and tag in result.stdout
        assert "nothing was gated" in result.stdout

    def test_the_stage_still_writes_nothing_into_the_release_tree(
        self, released: tuple[Path, str]
    ) -> None:
        """Charter item 5 holds on the path H2c added, not only the old one."""
        tree, tag = released
        before = {
            path: path.read_bytes()
            for path in sorted((tree / "docs" / "_generated").rglob("*"))
            if path.is_file()
        }
        assert _run_gate(tree, head_tag=tag).returncode == 0
        after = {
            path: path.read_bytes()
            for path in sorted((tree / "docs" / "_generated").rglob("*"))
            if path.is_file()
        }
        assert after == before


# ---------------------------------------------------------------------------
# Wiring — the gate is only a gate if check.py runs it
# ---------------------------------------------------------------------------


class TestTheWiring:
    def test_the_stage_is_registered_and_runs_before_selfhost_build(self) -> None:
        """ADR-012 §4 fixes the slot, so the order is a claim, not a habit."""
        source = CHECK_PY.read_text(encoding="utf-8")
        assert '"docs-application"' in source
        assert "scripts/check_docs_application.py" in source
        assert source.index('"pytest-studi0"') < source.index('"docs-application"')
        assert source.index('"docs-application"') < source.index('"selfhost-build"')

    @requires_checkout
    def test_the_stage_is_listed(self) -> None:
        result = subprocess.run(  # noqa: S603 - fixed argv, no shell
            [sys.executable, str(CHECK_PY), "--list"],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            encoding="utf-8",
            check=False,
        )
        assert result.returncode == 0, result.stdout + result.stderr
        assert "docs-application" in result.stdout

    @requires_checkout
    def test_only_runs_it(self) -> None:
        """The real exit code of the invocation F1's acceptance names.

        On the one commit a release tag names, the environment states that
        tag, as the release workflow does. On a preview tree it is passed
        through untouched.
        """
        tag = claimed_head_tag()
        environment = {**os.environ, _gate().HEAD_TAG_ENV: tag} if tag else None
        result = subprocess.run(  # noqa: S603 - fixed argv, no shell
            [sys.executable, str(CHECK_PY), "--only", "docs-application"],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            encoding="utf-8",
            env=environment,
            check=False,
        )
        assert result.returncode == 0, result.stdout + result.stderr
        assert "PASS  docs-application" in result.stdout

    def test_the_declared_mode_is_read_from_the_project_table(self) -> None:
        """The stage never carries its own copy of the strictness ramp."""
        assert _gate()._declared_mode(REPO_ROOT) == "release"
        source = GATE.read_text(encoding="utf-8")
        assert '"release"' not in source, (
            "the gate must read [tool.s0ma].mode rather than restate it"
        )
