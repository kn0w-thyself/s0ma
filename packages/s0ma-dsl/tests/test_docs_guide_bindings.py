"""Gates for G6 — what the living guides claim to teach, and the one install narrative.

Milestone G6 of the docs-function plan (internal) §12, in two halves that are
the same idea asked twice: **a page may not claim more than it says**, and
**a fact may not be written down twice**.

The first half is coverage. Seven repository-level guides are living
authored prose, and until this milestone six of them carried an empty
``covers``: the catalog knew the files existed and knew nothing about what
was in them. Filling that in is free to get wrong, because a catalog row
resolves against ids and never against sentences — any real id can be
added to any row and every existing gate stays green. That is precisely
why B6 raised ``DOC_COVERAGE_UNMENTIONED`` ("a row may not claim a topic
its document's prose never names"), and why
:data:`~s0ma_dsl.docs_model.validate.DEFERRED_GATES` still carries it: the
model-wide gate waits for a prose reader. This suite is that rule asked of
these seven pages now, so the rows land honest rather than land first and
be audited later.

The claim is checked against the prose the way a reader would meet it,
and the *evidence is derived from the record*, never authored beside the
claim (:func:`_named_in`):

* a **concept** is named when its own ``term`` appears — the term the
  concepts file gives it, singular or plural, not a paraphrase. A page
  that teaches the authored-versus-generated boundary beautifully and
  never uses the phrase does not get to claim the concept; it gets to
  earn it by naming it;
* a **surface** is named when its ``public_name`` appears — ``s0ma
  check``, ``[tool.s0ma].mode``, ``PARSE_ERROR``, ``s0ma://self/model``.
  Two channels need a sharper test: an MCP tool or prompt whose name is
  an ordinary English word (``check``, ``feedback``) must appear as code
  or as a call, because otherwise every page in the corpus "names" it;
* a **journey** is named only when the page names every concept that
  journey teaches *and* requires, and every surface its steps use —
  because :func:`~s0ma_dsl.docs_model.learn_pages._teaching_documents`
  credits a document that covers a journey with all of that journey's
  concepts. A journey claim is therefore a claim about a dozen terms at
  once, and G6 made none of them: no living repo-level guide passed that
  bar, which was the honest answer and was recorded as a floor of zero
  rather than as an omission. beta-prep-1-retrofit F2a is the first one
  to clear it — the brownfield page and the retrofit journey were
  written about the same path, so the page names the whole of that
  journey's vocabulary and every surface it steps to — which is why
  :func:`_named_in` now has the third branch the rule above always
  described and never needed.

The second half is the install narrative. The August 2026 audit (§9.5)
found three near-identical accounts of installing s0ma kept aligned by
discipline alone, and warned that public materials would make a fourth.
G6 wrote the rule down instead:

    The two-route summary — tester or contributor — lives in
    ``docs/getting-started.md`` §1. The tester mechanics — the keyed
    installer, its flags, its failure modes, the feedback enrolment it
    performs — live in ``docs/hosting-getting-started.md``. Every other
    page points at one of those two rather than restating either.

"Restating" has to mean something a test can measure, so it means two
concrete things here. :data:`INSTALLER_COMMAND` is the command itself,
and it may appear only at the sites in :data:`COMMAND_SITES`, each with
its written reason. **Mechanics** is the command's host together with two
or more of :data:`INSTALLER_OPTIONS` — the co-occurrence matters, because
``--dry-run`` and ``--default-off`` are also ordinary ``s0ma`` flags and
counting them alone would fail pages that never mention the installer at
all. Both sets are pinned in both directions: a site that drops out is as
much a finding as a site that appears.

**The remainder, named rather than hidden.** Two sites used to be listed
as exceptions with their reasons, in the posture
``scripts/check_version_refs.py`` takes with its historical allowlist: the
root ``README.md``'s authored *Install* section carried the tester
mechanics in full, and ``docs/uninstall.md`` quoted the command once under
*Reinstalling later* as a quote a reader acts on. Neither does any more —
the README describes the source route alone, and the uninstall page points
at the mechanics home's §7 for the command — so the command sites are the
mechanics home alone, and a site that reappears is a finding here.

**Narrowed for the public repository's first release.** That release
offers one route in — clone the repository and build from it — and no
account, keyed installer or Claude plugin. So the summary home now states
*the source route* alone and points at the root README's *Install*
section (:data:`SOURCE_ROUTE_HOME`) for its mechanics, and it no longer
points at the keyed installer's page at all; the pointer sites point at
those same two homes and no longer name the keyed installer's page either.
The mechanics home and the mechanics sites are unchanged, and the command
sites are the mechanics home alone: the installer is still described in
exactly one place, and this suite still proves it.

**Cost.** The documentation build is composed once for the module, by the
two tests that need composed records.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import TYPE_CHECKING, Any

import pytest

from s0ma_dsl.docs_model.application import build as build_documentation
from s0ma_dsl.docs_model.ids import normalize_id
from s0ma_dsl.docs_model.providers_concepts import FORBIDDEN_IN_AUTHORED_PROSE
from s0ma_dsl.docs_model.records import ConceptRecord, JourneyRecord, SurfaceRecord
from s0ma_dsl.docs_model.validate import records_of

if TYPE_CHECKING:
    from collections.abc import Iterator, Mapping

REPO_ROOT = Path(__file__).resolve().parents[3]

# ---------------------------------------------------------------------------
# The seven living guides
# ---------------------------------------------------------------------------

#: Every living repository-level guide, by catalog id, with the file it is a
#: row about. All twelve carry declared coverage; six got it at G6, the trust
#: note got it at G7, the documentation-subsystem guide arrived with its own
#: at I1, the brownfield guide arrived with its own at beta-prep-1-retrofit
#: F1, the Claude-route guide with its own at beta-prep-2-claude D1, the
#: stability statement with its own at beta-prep-5-front-door B1, and the
#: build-outputs guide with its own at the quick-reference correction of
#: 2026-09-29 — which is what this table is for: a guide added to the corpus
#: without a weighed binding is a guide this suite reports.
LIVING_GUIDES: Mapping[str, str] = {
    "doc:guide/claude-integration": "docs/guides/claude-integration.md",
    "doc:guide/documentation-subsystem": "docs/documentation-subsystem.md",
    "doc:guide/getting-started": "docs/getting-started.md",
    "doc:guide/hosting-getting-started": "docs/hosting-getting-started.md",
    "doc:guide/releasing": "docs/RELEASING.md",
    "doc:guide/retrofit-existing-codebase": "docs/guides/retrofit-existing-codebase.md",
    "doc:guide/stability": "docs/stability.md",
    "doc:guide/troubleshooting": "docs/troubleshooting.md",
    "doc:guide/trust-model": "docs/trust-model.md",
    "doc:guide/uninstall": "docs/uninstall.md",
    "doc:guide/walkthrough": "docs/walkthrough.md",
    "doc:guide/what-the-build-writes": "docs/guides/what-the-build-writes.md",
}

#: The trust note's coverage is G7's, and its row is pinned there. Pinning
#: it here as well would make one decision live in two files, so this
#: suite asks only that it is covered at all and names the suite that owns
#: the list — which is checked, so the pointer cannot rot either.
TRUST_MODEL = "doc:guide/trust-model"
TRUST_MODEL_SUITE = "packages/s0ma-dsl/tests/test_docs_trust_model.py"

#: What each guide claims to teach. Sorted, and compared with the catalog
#: in both directions: a row edited without this table is a claim nobody
#: weighed, and a table edited without the row is a gate about nothing.
#:
#: The justification for each group is the comment above it. Every entry
#: also has to survive :class:`TestNoClaimOutrunsTheProse`, which is what
#: makes these comments statements about the file rather than intentions.
BINDINGS: Mapping[str, tuple[str, ...]] = {
    # The Claude route (beta-prep-2-claude D1): installing s0ma as a plugin
    # or an extension, and what happens to it afterwards. Its subject is
    # mostly the launcher, which is shipped around the packages rather than
    # by them and so has no surface in this model at all — there is no
    # `cli:s0ma-launch/...` to claim. What it can honestly claim is the two
    # ideas it opens with (s0ma and the self-model it gives Claude) and the
    # three `s0ma` commands it names as commands a reader runs: `doctor`,
    # which ends setup and answers "why is this not working"; `new`, which
    # the /s0ma:new row names; and `feedback`, which the last line offers as
    # the terminal route. It teaches no journey and claims none.
    "doc:guide/claude-integration": (
        "cli:s0ma/doctor",
        "cli:s0ma/feedback",
        "cli:s0ma/new",
        "concept:s0ma",
        "concept:self-model",
    ),
    # I1's self-hosted documentation-subsystem guide, which is the one page
    # in the corpus whose subject is how the corpus is made. It teaches the
    # three documentation declarations and the two concepts the drift gate
    # is built out of, the canonical IR the transitive hash is computed
    # over, the module as the thing a declaration covers, the mirror as
    # what the copies leaving the project are held to, the release channel
    # every identity line is labelled with, the strictness mode the drift
    # severity ladders over, the registry snapshot the runtime answers
    # from, and s0ma and its self-model as the premise the whole subsystem
    # cashes in. Its surfaces are the two levels it spans: the eight
    # commands a documentation author runs, the two project keys the
    # application is configured by, the eleven reports a documentation
    # change trips first, the three registration calls with the three
    # hashing symbols behind them, and the served answers the runtime
    # gives about registered documents — five REST endpoints, three MCP
    # resources and the one tool that mirrors a templated resource for
    # clients that only make tool calls.
    "doc:guide/documentation-subsystem": (
        "cli:s0ma/build",
        "cli:s0ma/docs",
        "cli:s0ma/docs/check",
        "cli:s0ma/docs/check-drift",
        "cli:s0ma/docs/compose",
        "cli:s0ma/docs/list",
        "cli:s0ma/docs/render",
        "cli:s0ma/docs/search",
        "cli:s0ma/docs/show",
        "cli:s0ma/docs/verify",
        "cli:s0ma/examples/run",
        "concept:canonical-ir",
        "concept:doc-guide",
        "concept:doc-ref",
        "concept:drift",
        "concept:drift-gate",
        "concept:example",
        "concept:mirror",
        "concept:module",
        "concept:registry-snapshot",
        "concept:release-channel",
        "concept:s0ma",
        "concept:self-model",
        "concept:strictness-mode",
        "config:build_dir",
        "config:source_roots",
        "diagnostic:ASSERT_FAILED",
        "diagnostic:COVERED_BY_EMPTY",
        "diagnostic:DRIFT_DETECTED",
        "diagnostic:EMPTY_DOC_FILTER",
        "diagnostic:ENTITY_KIND_MISMATCH",
        "diagnostic:FIELD_NOT_FOUND",
        "diagnostic:MISSING_EMBEDDED_EXAMPLE",
        "diagnostic:MISSING_PUBLIC_DOC_REF",
        "diagnostic:MISSING_TEST_COVERAGE",
        "diagnostic:PROSE_RAW_CODE_BLOCK",
        "diagnostic:UNRESOLVED_REFERENCE",
        "mcp:resource/s0ma://docs/registered-docs",
        "mcp:resource/s0ma://model/docs-for/{component}",
        "mcp:resource/s0ma://model/examples-for/{component}",
        "mcp:tool/get_examples_for",
        "python:s0ma.HASH_ALGORITHM_VERSION",
        "python:s0ma.canonicalize",
        "python:s0ma.content_hash",
        "python:s0ma.register_doc_guide",
        "python:s0ma.register_doc_ref",
        "python:s0ma.register_example",
        "rest:GET:/self/doc/{name}",
        "rest:GET:/self/docs",
        "rest:GET:/self/drift",
        "rest:GET:/self/example/{name}",
        "rest:GET:/self/examples",
    ),
    # The cold-start journey. It teaches what s0ma is and what a self-model
    # is for (its own subject), the canonical IR that a build emits beside
    # the code, the module as the thing you ask about, and drift as the
    # refusal it walks the reader into deliberately. Its surfaces are the
    # six commands the walk actually runs, the two MCP tools it tells the
    # reader to call, the diagnostic that refusal raises, the Windows
    # remedy key, and the self-prompting guide §5 hands off to. Feedback
    # goes to the repository's issues and discussions, so `s0ma feedback`
    # is no longer named here and is no longer claimed.
    "doc:guide/getting-started": (
        "cli:s0ma/build",
        "cli:s0ma/check",
        "cli:s0ma/inspect",
        "cli:s0ma/new",
        "cli:s0ma/score",
        "cli:s0ma/verify-host",
        "concept:canonical-ir",
        "concept:drift",
        "concept:module",
        "concept:s0ma",
        "concept:self-knowledge",
        "concept:self-model",
        "config:venv_path",
        "diagnostic:GENERATED_FILE_DRIFT",
        "mcp:resource/s0ma://guide/self-prompting",
        "mcp:tool/inspect_module",
        "mcp:tool/project_status",
    ),
    # The tester page. Its subject is the install, which the model has no
    # id for — no surface exists for a shell script the user runs — so the
    # coverage it can honestly declare is its other half: §4, which is the
    # canonical account of the feedback function, its five commands, its
    # prompt, and the one config key the installer's --default-off writes.
    "doc:guide/hosting-getting-started": (
        "cli:s0ma/feedback",
        "cli:s0ma/feedback/delete",
        "cli:s0ma/feedback/drafts",
        "cli:s0ma/feedback/enroll",
        "cli:s0ma/feedback/list",
        "concept:feedback",
        "config:authoring",
        "mcp:prompt/feedback",
    ),
    # The release runbook. It is about the act of releasing, not about the
    # toolchain: it teaches the mirror (the byte-identical served copies it
    # exists to keep equal) and drift (the notice it teaches a releaser to
    # read), and it is where the exported version symbol's value is decided.
    # Every s0ma command it prints is spelled with --project-root, so it
    # names none of them the way a reader would meet them, and it claims
    # none: a runbook is not where somebody learns `s0ma build`.
    "doc:guide/releasing": (
        "concept:drift",
        "concept:mirror",
        "python:s0ma.__version__",
    ),
    # The brownfield page: how a plain-Python application becomes a s0ma
    # one, rung by rung. Its concepts are the vocabulary a retrofitter has
    # to hold — s0ma and the self-model as the destination, the .s0ma file
    # and its module header with the two import lists a converted file
    # declares, the layer whose table is the section that exists because
    # choosing against it late is expensive, the kind and visibility a
    # draft derives, the three declaration forms a draft emits, the intent
    # it refuses to guess, the strictness mode the last rung ratchets, and
    # the authored-vs-generated boundary behind "never edit the build
    # directory". Its surfaces are the five commands the ladder runs
    # outside the adopt family, the adopt family as it exists today (the
    # group command, the per-file record that keeps a deliberately
    # unconverted file out of the backlog, `adopt scan`, which B4
    # shipped and the page's "Rung 0" section teaches by name,
    # `adopt init`, which C1 shipped and its "Rung 1" section teaches
    # the same way, `adopt draft`, which D4 shipped and step 2 of
    # its "Rung 3" section teaches with the draft it really writes,
    # `adopt baseline` and `adopt verify-parity`, which E2 shipped and
    # steps 1 and 5 of that section teach with the record and the
    # verdict they really print, and `adopt status`, which E3 shipped
    # and the card, rung 1 and rung 3 all send a reader to), and the
    # four perimeter keys rung 1 writes plus the build-directory key
    # rule 2 names. The `s0ma adopt` family is complete: every
    # sub-command this page names now resolves, each claimed by the
    # milestone that built it the way B4 claimed `scan`.
    # F2a added the three claims the journey brought with it: the two
    # ideas the page teaches that no other concept covered — the ladder
    # the whole page is shaped as, and the perimeter its "Rung 1"
    # section is named for — and the journey itself, which is the first
    # journey claim any living guide has been able to make (the bar is
    # the whole of that journey's vocabulary and every step surface, and
    # this page names all of it).
    # F2 (the close-out) added the two diagnostics a retrofit actually
    # meets. Both belong to drafts and to nothing else, both are errors
    # in every mode, and rung 3's "Check" step now names each one with
    # what it means and what to do — which is the claim being made here.
    # They are the first diagnostics this page claims because they are
    # the first ones it could: D3 minted them, and a code is only worth
    # naming on the page where a reader hits it.
    "doc:guide/retrofit-existing-codebase": (
        "cli:s0ma/adopt",
        "cli:s0ma/adopt/baseline",
        "cli:s0ma/adopt/draft",
        "cli:s0ma/adopt/file",
        "cli:s0ma/adopt/init",
        "cli:s0ma/adopt/scan",
        "cli:s0ma/adopt/status",
        "cli:s0ma/adopt/verify-parity",
        "cli:s0ma/build",
        "cli:s0ma/check",
        "cli:s0ma/doctor",
        "cli:s0ma/score",
        "cli:s0ma/verify",
        "concept:adoption-ladder",
        "concept:authored-vs-generated-boundary",
        "concept:cell",
        "concept:helper",
        "concept:intent",
        "concept:kind",
        "concept:layer",
        "concept:module",
        "concept:nerve",
        "concept:perimeter",
        "concept:requires",
        "concept:s0ma",
        "concept:s0ma-file",
        "concept:self-model",
        "concept:strictness-mode",
        "concept:uses",
        "concept:visibility",
        "config:bootstrap_files",
        "config:build_dir",
        "config:mode",
        "config:package_markers",
        "config:source_roots",
        "diagnostic:ADOPT_PLACEHOLDER_INTENT",
        "diagnostic:ADOPT_UNPLACED_CODE",
        "journey:retrofit-existing-codebase",
    ),
    # The stability statement (beta-prep-5-front-door B1): what a pre-1.0
    # s0ma promises and what it does not. Most of its subject has no id in
    # this model at all — an invariant, a frozen contract, a changelog
    # heading and a schema string are none of them surfaces — so the claim
    # it can honestly make is narrow and is the part a reader *acts* on.
    # `s0ma` is the premise the whole page is about. The two commands are
    # the two it tells a reader to run: `s0ma build`, whose `--check` form
    # is the committed-build equality gate the page's central habit rests
    # on, and `s0ma doctor`, which answers "what is installed here, and
    # what is this project set to" before an upgrade. Around those, the
    # three ideas §5 teaches in its own words: drift (the gap the gate
    # closes), the authored-vs-generated boundary (why the build refuses
    # to overwrite a hand-edited file) and GENERATED_FILE_DRIFT (the
    # refusal itself, named and explained). The canonical IR earns its
    # claim in §3, which is the page's account of what an unrecognised
    # schema major does — refuse and name the supported one. It names no
    # served tool or prompt, deliberately: the page's point about the
    # agent surface is that it is reviewed as a whole, not that any one
    # name is taught here. It teaches no journey and claims none.
    "doc:guide/stability": (
        "cli:s0ma/build",
        "cli:s0ma/doctor",
        "concept:authored-vs-generated-boundary",
        "concept:canonical-ir",
        "concept:drift",
        "concept:s0ma",
        "diagnostic:GENERATED_FILE_DRIFT",
    ),
    # The user-facing failure page. Its error table is the plain-language
    # rendering of twenty-two diagnostics — what you see, what it means,
    # what to do — which makes it the document those codes are written up
    # in for a person. Around it: the eight commands it walks the reader
    # through, the mode key it explains, and drift, whose distinction from
    # a check failure and a stale build is a whole section.
    "doc:guide/troubleshooting": (
        "cli:s0ma/build",
        "cli:s0ma/check",
        "cli:s0ma/docs/check-drift",
        "cli:s0ma/docs/render",
        "cli:s0ma/doctor",
        "cli:s0ma/feedback",
        "cli:s0ma/graph",
        "cli:s0ma/studi0",
        "concept:drift",
        "config:mode",
        "diagnostic:BARE_IMPORT",
        "diagnostic:CIRCULAR_DEPENDENCY",
        "diagnostic:CROSS_LAYER_DEPENDENCY",
        "diagnostic:DOES_NOT_EXIST",
        "diagnostic:DUPLICATE_DECLARATION",
        "diagnostic:GENERATED_FILE_DRIFT",
        "diagnostic:HOST_RUNTIME_UNDECLARED",
        "diagnostic:MISSING_EMBEDDED_EXAMPLE",
        "diagnostic:MISSING_FIELD",
        "diagnostic:MISSING_PACKAGE",
        "diagnostic:MISSING_PUBLIC_DOC_REF",
        "diagnostic:MISSING_RETURN_KEY",
        "diagnostic:MISSING_TEST_COVERAGE",
        "diagnostic:MODULE_DEPENDENCY_CYCLE",
        "diagnostic:MODULE_NAME_COLLISION",
        "diagnostic:MODULE_NAME_STEM_MISMATCH",
        "diagnostic:NOT_EXPORTED",
        "diagnostic:PARSE_ERROR",
        "diagnostic:PROVIDES_KEY_MISMATCH",
        "diagnostic:SEMANTIC_PENDING_DEBT",
        "diagnostic:SEMANTIC_REQUIRED_STATE_OMITTED",
        "diagnostic:VESTIGIAL_IMPORT",
    ),
    # The removal page. It teaches where the feedback function's state
    # lives and what removing it costs, and it walks six surfaces on the
    # way out: the viewer to stop, the health report that finds what to
    # remove, the four feedback commands, and the build output that the
    # next build rewrites — plus the key that renames the directory it is in.
    "doc:guide/uninstall": (
        "cli:s0ma/build",
        "cli:s0ma/doctor",
        "cli:s0ma/feedback",
        "cli:s0ma/feedback/drafts",
        "cli:s0ma/feedback/enroll",
        "cli:s0ma/studi0",
        "concept:feedback",
        "config:build_dir",
    ),
    # The end-to-end guide to building an application through the agent's
    # tool channel. Its §4 is the canonical one-line definition of the
    # declaration vocabulary (kind, and the four kinds themselves, layer,
    # intent, module, the two documentation declarations, requires:), §5
    # ratchets the strictness mode, §6 explains drift and the gates that
    # catch it; the surfaces are the six commands its verification ladder
    # runs, the mode key, all five served prompts and the nine tools it
    # tells an agent to call, and the three orientation resources plus the
    # server's own model that §3 tells the reader how to use.
    "doc:guide/walkthrough": (
        "cli:s0ma/build",
        "cli:s0ma/check",
        "cli:s0ma/docs/check-drift",
        "cli:s0ma/examples/run",
        "cli:s0ma/new",
        "cli:s0ma/test",
        "cli:s0ma/verify",
        "concept:axon",
        "concept:cell",
        "concept:doc-guide",
        "concept:doc-ref",
        "concept:drift",
        "concept:ganglion",
        "concept:intent",
        "concept:kind",
        "concept:layer",
        "concept:module",
        "concept:nerve",
        "concept:requires",
        "concept:self-model",
        "concept:strictness-mode",
        "config:mode",
        "mcp:prompt/author_module",
        "mcp:prompt/diagnose_fault",
        "mcp:prompt/feedback",
        "mcp:prompt/fix_check_failures",
        "mcp:prompt/migrate_project",
        "mcp:resource/s0ma://guide/quick-reference",
        "mcp:resource/s0ma://guide/survival-card",
        "mcp:resource/s0ma://guide/system-prompt",
        "mcp:resource/s0ma://self/model",
        "mcp:tool/build_project",
        "mcp:tool/check",
        "mcp:tool/describe_server",
        "mcp:tool/init_project",
        "mcp:tool/inspect_module",
        "mcp:tool/project_status",
        "mcp:tool/run_example",
        "mcp:tool/scaffold_module",
        "mcp:tool/verify_host",
    ),
    # The build-outputs guide. It opens the build directory of one built
    # module and says what every file is for, so its claims are the words
    # that walk does not get far without: `s0ma build`, which writes them,
    # and `s0ma verify`, whose EDITED report is the page's evidence that a
    # hand edit is noticed; the canonical IR, which §4 shows and explains
    # field by field; the self-model, which §3 says the emitted
    # registration calls build; and drift with GENERATED_FILE_DRIFT, which
    # §7 names as what a hand-edited file is and what the build refuses.
    # It names `inspect_module` and `project_status` only as readers of a
    # file, not as tools it teaches, and it claims no journey.
    "doc:guide/what-the-build-writes": (
        "cli:s0ma/build",
        "cli:s0ma/verify",
        "concept:canonical-ir",
        "concept:drift",
        "concept:self-model",
        "diagnostic:GENERATED_FILE_DRIFT",
    ),
}

#: The id prefixes a living guide's coverage may use. Documents covering
#: documents, or covering an authority, would be a different edge with a
#: different meaning; §6.7 allows ``covers`` to point anywhere, and this
#: is G6 saying what it pointed at.
#:
#: ``rest:`` was added at I1 by the first guide to teach a served HTTP
#: capability. It is not a new *kind* of claim — a REST endpoint is a
#: ``SurfaceRecord`` like a command or a tool, and ``_named_in`` already
#: judged it by its ``public_name`` — it is only a channel no guide had
#: reached before, which is why the list had not had to name it.
CLAIMABLE_PREFIXES: tuple[str, ...] = (
    "cli:",
    "concept:",
    "config:",
    "diagnostic:",
    "journey:",
    "mcp:",
    "python:",
    "rest:",
)

# ---------------------------------------------------------------------------
# The install narrative
# ---------------------------------------------------------------------------

#: Where the two routes are stated, and where the tester mechanics are.
#: The rule G6 wrote down names exactly these two, and both files say so
#: themselves (:class:`TestTheRuleIsWrittenDownWhereItApplies`).
SUMMARY_HOME = "docs/getting-started.md"
MECHANICS_HOME = "docs/hosting-getting-started.md"

#: Where the source route's mechanics live — the clone, the sync, the wheel
#: build and the install into a project. The public repository's first
#: release offers that route alone, so the summary home points here and
#: nowhere else.
SOURCE_ROUTE_HOME = "README.md"

#: The keyed installer, character for character. Quoted rather than built
#: from parts so that a page carrying a *variant* of the command is a
#: finding somewhere else rather than a silent pass here.
INSTALLER_COMMAND = 'sh -c "$(curl -fsSL https://account.kn0wthyself.ai/install.sh)"'

#: Where the command is fetched from. Half of the mechanics test: an
#: option name only counts as installer mechanics on a page that has the
#: installer on it.
INSTALLER_HOST = "account.kn0wthyself.ai/install.sh"

#: The installer's own options. Three of them (``--key``, ``--dry-run``,
#: ``--default-off``) are also ordinary ``s0ma`` flags, which is why the
#: mechanics test requires two of these *and* the host: the generated CLI
#: reference names three of them and describes no installer at all.
INSTALLER_OPTIONS: tuple[str, ...] = (
    "--cp-host",
    "--default-off",
    "--dry-run",
    "--key",
    "--no-feedback",
)

#: Every living document allowed to print the command, and why. Pinned in
#: both directions.
COMMAND_SITES: Mapping[str, str] = {
    MECHANICS_HOME: (
        "the mechanics home: this page is where the installer is described, "
        "and §7 is the canonical text of the command"
    ),
}

#: Every living document allowed to describe the installer's mechanics.
MECHANICS_SITES: Mapping[str, str] = {
    MECHANICS_HOME: "the mechanics home, and the only account of the installer",
}

#: The pages G6 reduced to pointers, and the two homes each has to point
#: at — since the public repository's first release, the summary home and
#: the source route's home rather than the keyed installer's page, which
#: they must not name. Asked positively as well as negatively: a page that
#: dropped the narrative *and* the pointer has not been single-sourced, it
#: has been emptied.
POINTER_SITES: tuple[str, ...] = (
    "docs/walkthrough.md",
    "packages/s0ma-core/docs/s0ma_user_guide.md",
)

#: Directory names whose contents are not living documentation: build
#: output, byte-mirrors of something else, and the archive.
NOT_LIVING_DIRS = frozenset({"_built", "_generated", "archive"})

#: A changelog is a record of releases, not a guide, and its entries
#: quote flags as they were introduced. Scanning it would test history.
NOT_LIVING_NAMES = frozenset({"CHANGELOG.md"})

# ---------------------------------------------------------------------------
# Shared machinery
# ---------------------------------------------------------------------------

_FORBIDDEN_FILES: tuple[str, ...] = (
    SUMMARY_HOME,
    MECHANICS_HOME,
    "docs/walkthrough.md",
    "packages/s0ma-core/docs/s0ma_user_guide.md",
)

_TOOL_WORD = re.compile(r"^[a-z][a-z0-9]*$")


def _is_checkout() -> bool:
    return (REPO_ROOT / ".git").exists()


requires_checkout = pytest.mark.skipif(
    not _is_checkout(), reason="not a git checkout (wheel-install context)"
)


def _flowed(text: str) -> str:
    """*text* with every run of whitespace collapsed to one space.

    Every guide here is hand-wrapped, so a term can sit across a line
    break this week and on one line next week. Asking the reflowed form
    asks about the sentence rather than about where the author broke the
    line.
    """
    return " ".join(text.split())


def _term_pattern(term: str) -> re.Pattern[str]:
    """The term, as a whole word, singular or plural.

    The plural is allowed because the vocabulary is authored in the
    singular and used in prose in both — the walkthrough writes
    "declaration kinds" for ``concept:kind``. Hyphen and word characters
    on either side are refused, so ``s0ma`` does not match inside
    ``s0ma-core``.
    """
    return re.compile(rf"(?<![\w-]){re.escape(term)}s?(?![\w-])", re.IGNORECASE)


def _named_in(text: str, record: Any, composed: Mapping[str, Any] | None = None) -> bool:
    """Whether *text* names *record* the way a reader would meet it.

    ``composed`` is only needed for a journey, whose rule is about the
    records it names rather than about a word of its own; the other two
    kinds are judged from the record in hand.
    """
    if isinstance(record, ConceptRecord):
        return _term_pattern(record.term).search(text) is not None
    if isinstance(record, SurfaceRecord):
        name = record.public_name
        if record.channel in {"mcp_tool", "mcp_prompt"} and _TOOL_WORD.match(name):
            # An ordinary English word — `check`, `feedback`, `transpile`.
            # It counts as naming the tool only as code or as a call.
            return f"`{name}`" in text or f"{name}(" in text
        return name in text
    if isinstance(record, JourneyRecord):
        # The module docstring's third bullet: covering a journey credits
        # the page with everything that journey teaches and requires, so
        # the page has to name all of it and every surface it steps to.
        if composed is None:
            raise TypeError("a journey is judged against the records it names")
        needed = (
            *record.concepts_taught,
            *record.concepts_required,
            *(step.surface for step in record.steps),
        )
        return all(
            _named_in(text, composed[normalize_id(item)], composed) for item in needed
        )
    raise TypeError(f"no evidence rule for {type(record).__name__}")


def _living_documents() -> Iterator[Path]:
    """Every living documentation file the narrative rule ranges over.

    The repository front door, everything under ``docs/``, the four
    package front doors, and every package's ``docs/`` tree — minus build
    output, byte-mirrors, the archive and the changelogs. That is the set
    a reader browsing this repository's documentation can reach, which is
    the set a duplicated install narrative would be duplicated *into*.
    """
    roots = [REPO_ROOT / "README.md", *(REPO_ROOT / "docs").rglob("*.md")]
    for package in sorted((REPO_ROOT / "packages").iterdir()):
        front_door = package / "README.md"
        if front_door.is_file():
            roots.append(front_door)
        roots.extend(sorted((package / "docs").rglob("*.md")))
    for path in roots:
        relative = path.relative_to(REPO_ROOT)
        if NOT_LIVING_DIRS.intersection(relative.parts):
            continue
        if path.name in NOT_LIVING_NAMES:
            continue
        yield path


def _describes_mechanics(text: str) -> bool:
    """Whether *text* explains how the keyed installer behaves."""
    if INSTALLER_HOST not in text:
        return False
    return sum(option in text for option in INSTALLER_OPTIONS) >= 2


# ---------------------------------------------------------------------------
# What every test reads, read once
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def catalog() -> dict[str, Any]:
    raw = (REPO_ROOT / "docs" / "s0ma_src" / "catalog.json").read_text(encoding="utf-8")
    return json.loads(raw)


@pytest.fixture(scope="module")
def rows(catalog: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {item["id"]: item for item in catalog["documents"]}


@pytest.fixture(scope="module")
def live() -> Any:
    """The whole documentation build, composed once for this module."""
    return build_documentation(REPO_ROOT)


@pytest.fixture(scope="module")
def composed(live: Any) -> dict[str, Any]:
    """Every record this build addresses, by its normalized id."""
    return {normalize_id(record.id): record for record in records_of(live.bundle)}


@pytest.fixture(scope="module")
def prose() -> dict[str, str]:
    """Each living guide as one flowed string."""
    return {
        document: _flowed((REPO_ROOT / path).read_text(encoding="utf-8"))
        for document, path in LIVING_GUIDES.items()
    }


# ---------------------------------------------------------------------------
# The rows (T1)
# ---------------------------------------------------------------------------


@requires_checkout
class TestEveryLivingGuideIsBound:
    """Seven guides, seven rows, and none of them empty any more."""

    @pytest.mark.parametrize(("document", "path"), sorted(LIVING_GUIDES.items()))
    def test_the_guide_has_exactly_one_living_row_about_it(
        self, document: str, path: str, rows: dict[str, dict[str, Any]], catalog: dict[str, Any]
    ) -> None:
        assert document in rows, document
        row = rows[document]
        assert row["canonical_source"] == path
        assert row["status"] == "living"
        owners = [
            item["id"] for item in catalog["documents"] if item["canonical_source"] == path
        ]
        assert owners == [document]

    @pytest.mark.parametrize("document", sorted(LIVING_GUIDES))
    def test_the_row_declares_coverage(
        self, document: str, rows: dict[str, dict[str, Any]]
    ) -> None:
        """G6's acceptance in one line: no living guide is silent."""
        assert rows[document]["covers"], document

    @pytest.mark.parametrize("document", sorted(BINDINGS))
    def test_the_row_is_the_binding_this_milestone_weighed(
        self, document: str, rows: dict[str, dict[str, Any]]
    ) -> None:
        """Both directions.

        A row edited without this table is a claim nobody weighed against
        the prose; a table edited without the row is a gate about nothing.
        """
        assert tuple(rows[document]["covers"]) == tuple(sorted(BINDINGS[document]))

    def test_the_trust_notes_coverage_stays_where_it_was_decided(
        self, rows: dict[str, dict[str, Any]]
    ) -> None:
        """G7 owns that row; this suite only refuses to let it go empty."""
        assert TRUST_MODEL not in BINDINGS
        assert rows[TRUST_MODEL]["covers"]
        owner = REPO_ROOT / TRUST_MODEL_SUITE
        assert owner.is_file(), TRUST_MODEL_SUITE
        assert TRUST_MODEL in owner.read_text(encoding="utf-8")

    def test_every_claim_is_sorted_and_claimable(
        self, rows: dict[str, dict[str, Any]]
    ) -> None:
        for document in LIVING_GUIDES:
            covers = rows[document]["covers"]
            assert covers == sorted(set(covers)), document
            for covered in covers:
                assert covered.startswith(CLAIMABLE_PREFIXES), (document, covered)

    def test_the_table_is_not_a_sample(self) -> None:
        """An anti-vacuity floor: three claims across six guides prove nothing."""
        assert sum(len(claims) for claims in BINDINGS.values()) >= 80
        for document, claims in BINDINGS.items():
            assert len(claims) >= 3, document


# ---------------------------------------------------------------------------
# Resolution (T1)
# ---------------------------------------------------------------------------


@requires_checkout
class TestEveryClaimResolves:
    """A claim the build cannot address is a pointer into nothing."""

    def test_every_claimed_id_is_a_record_this_build_composes(
        self, composed: dict[str, Any]
    ) -> None:
        for document, claims in BINDINGS.items():
            for covered in claims:
                assert normalize_id(covered) in composed, (document, covered)

    def test_every_claim_resolves_to_the_kind_its_id_promises(
        self, composed: dict[str, Any]
    ) -> None:
        """``concept:`` has to be a concept, not merely something real.

        Resolution alone would accept an id that happens to exist; a
        reader following ``covers`` is told what sort of thing is on the
        other end by the prefix, and this is what keeps that true.
        """
        expected = {
            "concept:": ConceptRecord,
            "journey:": JourneyRecord,
        }
        for document, claims in BINDINGS.items():
            for covered in claims:
                record = composed[normalize_id(covered)]
                prefix = covered.split(":", 1)[0] + ":"
                wanted = expected.get(prefix, SurfaceRecord)
                assert isinstance(record, wanted), (document, covered, type(record))


# ---------------------------------------------------------------------------
# Honesty (T1) — B6's rule, asked of these pages now
# ---------------------------------------------------------------------------


@requires_checkout
class TestNoClaimOutrunsTheProse:
    """``DOC_COVERAGE_UNMENTIONED`` is deferred model-wide; it is not deferred here."""

    def test_every_claim_is_named_by_the_prose_that_claims_it(
        self, composed: dict[str, Any], prose: dict[str, str]
    ) -> None:
        for document, claims in BINDINGS.items():
            text = prose[document]
            for covered in claims:
                record = composed[normalize_id(covered)]
                assert _named_in(text, record, composed), (document, covered)

    def test_the_evidence_rule_can_actually_fail(
        self, composed: dict[str, Any], prose: dict[str, str]
    ) -> None:
        """A matcher that says yes to everything would pass the test above.

        So: something real, named nowhere in the page that would most
        plausibly name it. The release runbook is not where a reader
        learns what a nerve is.
        """
        assert not _named_in(prose["doc:guide/releasing"], composed["concept:nerve"])
        assert not _named_in(
            prose["doc:guide/uninstall"], composed["cli:s0ma/verify-host"]
        )

    def test_no_guide_claims_a_journey_it_does_not_walk(
        self, composed: dict[str, Any], prose: dict[str, str]
    ) -> None:
        """The bar a journey claim has to clear, and the fact that none does.

        Covering a journey credits the document with every concept that
        journey teaches and requires (``learn_pages._teaching_documents``),
        so the claim is only honest when the page names all of them and
        walks every step. G6 checked all six journeys against all seven
        guides and none qualified: the E-phase journey guides own those
        paths, and these pages teach around them. The assertion is the
        derivation, not the conclusion — a guide that grows into a journey
        trips this and is told it may now claim it, which is what happened
        to the brownfield page at beta-prep-1-retrofit F2a.
        """
        journeys = [
            record for record in composed.values() if isinstance(record, JourneyRecord)
        ]
        assert len(journeys) >= 5, "the journey corpus has collapsed"
        for document, text in prose.items():
            claimed = set(BINDINGS.get(document, ()))
            for journey in journeys:
                walks = _named_in(text, journey, composed)
                assert walks == (journey.id in claimed), (document, journey.id)


# ---------------------------------------------------------------------------
# The install narrative (T2)
# ---------------------------------------------------------------------------


@requires_checkout
class TestTheInstallNarrativeIsSingleSourced:
    """One statement of the routes, one statement of the mechanics."""

    def test_the_scan_covers_a_real_corpus(self) -> None:
        found = list(_living_documents())
        assert len(found) >= 60, "the living-documentation scan found almost nothing"
        relative = {path.relative_to(REPO_ROOT).as_posix() for path in found}
        for site in (SUMMARY_HOME, MECHANICS_HOME, *COMMAND_SITES, *POINTER_SITES):
            assert site in relative, site

    def test_the_command_appears_at_exactly_the_recorded_sites(self) -> None:
        found = {
            path.relative_to(REPO_ROOT).as_posix()
            for path in _living_documents()
            if INSTALLER_COMMAND in path.read_text(encoding="utf-8")
        }
        assert found == set(COMMAND_SITES)

    def test_the_mechanics_are_described_at_exactly_the_recorded_sites(self) -> None:
        found = {
            path.relative_to(REPO_ROOT).as_posix()
            for path in _living_documents()
            if _describes_mechanics(path.read_text(encoding="utf-8"))
        }
        assert found == set(MECHANICS_SITES)

    def test_every_recorded_exception_carries_its_reason(self) -> None:
        """An allowlist without written reasons is a list of excuses."""
        for reason in (*COMMAND_SITES.values(), *MECHANICS_SITES.values()):
            assert len(reason.split()) >= 3

    @pytest.mark.parametrize("site", POINTER_SITES)
    def test_a_pointer_site_points_and_does_not_restate(self, site: str) -> None:
        text = (REPO_ROOT / site).read_text(encoding="utf-8")
        assert SUMMARY_HOME.rsplit("/", 1)[-1] in text, site
        assert SOURCE_ROUTE_HOME in text, site
        assert MECHANICS_HOME.rsplit("/", 1)[-1] not in text, site
        assert INSTALLER_COMMAND not in text, site
        assert not _describes_mechanics(text), site

    def test_the_summary_home_states_the_source_route(self) -> None:
        text = _flowed((REPO_ROOT / SUMMARY_HOME).read_text(encoding="utf-8"))
        assert "the source route" in text
        assert "the tester route" not in text
        assert "the contributor route" not in text
        assert "the Claude route" not in text


@requires_checkout
class TestTheRuleIsWrittenDownWhereItApplies:
    """A rule only a test knows is a rule the next author will break."""

    def test_the_summary_home_names_the_rule_and_the_mechanics_home(self) -> None:
        text = _flowed((REPO_ROOT / SUMMARY_HOME).read_text(encoding="utf-8"))
        assert "canonical route summary" in text
        assert SOURCE_ROUTE_HOME in text
        assert MECHANICS_HOME not in text
        assert Path(__file__).name in text

    def test_the_mechanics_home_says_it_is_the_only_account(self) -> None:
        text = _flowed((REPO_ROOT / MECHANICS_HOME).read_text(encoding="utf-8"))
        assert "the one place the keyed installer is described" in text.lower()
        assert "getting-started.md" in text


# ---------------------------------------------------------------------------
# The voice (T3)
# ---------------------------------------------------------------------------


@requires_checkout
class TestTheVoice:
    """Every page G6 edited, in this product's words."""

    @pytest.mark.parametrize("relative", _FORBIDDEN_FILES)
    def test_the_prose_never_uses_a_word_this_product_does_not(
        self, relative: str
    ) -> None:
        text = (REPO_ROOT / relative).read_text(encoding="utf-8")
        for label, pattern in FORBIDDEN_IN_AUTHORED_PROSE:
            found = pattern.search(text)
            assert found is None, f"{relative}: {label}: {found.group(0) if found else ''}"
