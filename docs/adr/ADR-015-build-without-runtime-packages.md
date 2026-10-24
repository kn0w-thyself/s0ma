# ADR-015: A build without the runtime packages records what it could not verify

**Status:** Proposed, put to the owner with the pull request that implements
it; merging that pull request is the ruling that accepts it
**Date:** 2026-10-23
**Context:** the build gate of `s0ma build` (the NEW check-error gate,
[CONTRIBUTING.md](../../CONTRIBUTING.md#the-check-pipeline)) meeting a PEP 517
build environment, as fr3d's wheel build met it
**References:**
[`packages/s0ma-dsl/src/s0ma_dsl/check_baseline.py`](../../packages/s0ma-dsl/src/s0ma_dsl/check_baseline.py)
(the attribution the gate keys on),
[`docs/guides/packaging.md`](../guides/packaging.md) (the guide this decision
makes possible),
[ADR-001](ADR-001-0.14-gate-integrity-and-value-loop.md) §2 (gate policy is
caller-selected, never inferred),
[ADR-007](../../packages/s0ma-dsl/docs/adr/ADR-007-single-build-layout.md) (the
manifest as the build's record of itself)

---

## Decision

`s0ma build` takes a flag, `--without-runtime-packages`, by which the caller
states that the environment the build runs in does not hold the project's
runtime packages. Under that statement:

1. A `requires:` entry the build cannot find (`MISSING_PACKAGE`) is an
   environment finding, not a contract error the edit introduced. The gate
   does not count it as a NEW check error. Every other NEW check error still
   refuses the build, and so does a `requires:` entry that names one of the
   project's own s0ma modules: that entry belongs in `uses:`, no environment
   supplies it, and the source alone settles it.
2. The build records the import names it could not find in the manifest,
   `build.s0ma.json`, under `unverified_packages`, and in its `--format json`
   report under `build_environment`. The text report prints one line naming
   them. Nothing is waved through, so `overridden_new_errors` is not written
   by the flag; a build that passes both `--without-runtime-packages` and
   `--allow-new-errors` writes both records, each for its own reason.
3. The build does not record the check baseline. What it found missing says
   nothing about the checkout's debt.
4. The flag combines with dev and migration mode only. Strict and release mode
   exist to verify every `requires:` entry, which is what the flag says cannot
   be done here, so the flag in either of them is a usage error that says so,
   whether the mode comes from `--mode` or from `[tool.s0ma].mode`.

Without the flag the gate is exactly what it was, with one addition: a
refusal whose every NEW error is a `MISSING_PACKAGE` the flag would cover
names the flag and says what it does. A refusal under the flag carries the
record of what the flag left out of the count, in the JSON document and in
one text line.

`MISSING_PACKAGE` is the one code classified this way, recorded as
`ENVIRONMENT_CODES` in `check_baseline.py`. It is the only check-severity
diagnostic whose truth depends on the packages installed in the interpreter
running the check rather than on the authored source.

## Context

`s0ma build` refuses to emit artifacts when the tree introduces check-severity
errors that the recorded check baseline (`.s0ma/check-baseline.json`) does
not hold. The gate ranks diagnostics the way `s0ma check` does, in strict
terms, so a code that is a dev-mode warning and a strict-mode error, such as
`MISSING_PACKAGE`, is gated in a dev build. The baseline is working state,
recorded per machine by the developer's full-project checks and builds.

`MISSING_PACKAGE` is raised when `importlib.util.find_spec` cannot find a
`requires:` entry in the interpreter running the build. When pip or uv builds a
project's wheel, PEP 517 build isolation gives the build backend an
environment holding `[build-system].requires` and nothing else, so every
third-party `requires:` entry is missing there. fr3d's `pip install -e .`
failed on exactly this: a green strict baseline recorded where its packages
(anthropic, croniter and more) were installed, then a refusal in the isolated
environment on `MISSING_PACKAGE` alone, with nothing edited in between. fr3d's
`hatch_build.py` now runs `s0ma build --format json`, reads the refusal, and
when every NEW error is `MISSING_PACKAGE` builds again with
`--allow-new-errors`, failing on any other new error. That is a per-project
workaround for a situation every s0ma project meets when its wheel build runs
`s0ma build`, and it records the environment's gap as an override, which it
is not.

The gate cannot tell the two causes apart on its own. A `requires:` entry that
is missing because the environment is the wrong one and an entry that is
missing because it is misspelled produce the same diagnostic. Mapping import
names to the distributions `[project].dependencies` declares would need the
installed distributions' metadata, which the isolated environment does not
have, and would be a heuristic with its own silent failures.

## Rationale

**The caller knows, so the caller says.** The one party that knows the
environment lacks the runtime packages is the build hook that runs inside it.
ADR-001 §2 set the pattern: gate policy is supplied by the caller, never
inferred by s0ma from its surroundings. A flag the hook passes is a statement
of fact; sniffing environment variables that packaging tools happen to set
would be a guess about who is calling, and would break with the next tool.

**Classification, not override.** `--allow-new-errors` means "I accept these
new contract errors", and the manifest's `overridden_new_errors` exists so
that such overrides can be counted after the fact. A packaging build has no
contract error to accept.
Recording the missing packages under their own key says what happened:
these entries were not verified here, and the project's own environment is
where they are. The two records never merge.

**The gate stays binding where it can see.** Without the flag, a missing
package in the developer's own environment is still a NEW check error and
still refuses the build. Making `MISSING_PACKAGE` unconditionally
unattributable would have weakened the gate for everyone in order to fix a
situation that only packaging builds meet.

**Verification moves rather than disappears.** `s0ma check --mode strict`
where the packages are installed, and `s0ma verify-host` under the
application's interpreter, are the places a `requires:` entry is proven.
Refusing the flag in strict and release mode keeps a flagged build from ever
reading as release evidence.

**The baseline is the developer's record.** A build that observed a foreign
environment must not seed or refresh it. A fresh clone whose first build is
the wheel build therefore still has no baseline afterwards, and the next
check or build made where the packages are installed records one.

## Consequences

- A packaging build hook passes one flag and needs no retry logic. The
  reference hook is written out in the packaging guide and exercised by
  `packages/s0ma-dsl/tests/test_docs_packaging_guide.py`.
- In a flagged build a misspelled `requires:` entry looks like any other
  missing package: it is recorded as unverified and the build goes on. It is
  caught where the packages are installed, by `s0ma check --mode strict`.
- The manifest schema stays `s0ma-build-manifest@1`: `unverified_packages` is
  additive, omitted when empty, and a manifest from a build made where the
  packages are installed is byte-identical to one made before this decision.
- The MCP `build_project` tool does not take the flag. A packaging build is
  not an authoring step, and the served surface is unchanged.
- `MISSING_PACKAGE` keeps its message and remediation. A build made with the
  flag still prints the warning, with the one-line note beside it; the
  remediation's "install the package" half is the right answer in the
  environment where the application runs.
- fr3d's hook can drop its retry and pass the flag once it depends on a
  release that carries this change.

## Alternatives considered

1. **Classify `MISSING_PACKAGE` as an environment diagnostic unconditionally:
   the delta reports it, the gate never counts it.** Rejected. It needs no
   flag, but it weakens the gate for every build: a misspelled `requires:`
   entry in the developer's own environment would build with a warning where
   it refuses today. The gate was made binding on exactly the class of
   check-red, build-green codes this one belongs to.
2. **A scoped override, `--allow-new-errors MISSING_PACKAGE`, recorded by code
   in the manifest.** Rejected. It records an environment's gap as an
   override, in the field that exists so overrides can be counted;
   it changes the shape of an existing flag, and with it the MCP tool's
   `allow_new_errors` parameter and the served surface; and a hook would pass
   it on every build, which is what a flag that states the fact does without
   calling it an override.
3. **Detect the isolated build from the environment** (variables packaging
   tools set, or the interpreter's prefix compared with the one that recorded
   the baseline). Rejected. Both are guesses about the caller. The second
   would also take a developer's new virtual environment for an isolated one,
   on every build until the next full check records its prefix.
4. **A distinct diagnostic code under the flag, a warning in every mode, in
   place of `MISSING_PACKAGE`.** Rejected for now. It would let strict and
   release mode take the flag, but it adds a code to the severity matrix, the
   diagnostics reference, the traceability matrix and the coverage policy for
   a situation the dev-mode build already serves, and a flagged strict build
   reading as strict evidence is the misreading rule 4 of the decision
   exists to prevent.
5. **Map `requires:` import names to `[project].dependencies` and treat a
   declared dependency's absence as expected.** Rejected. Import names and
   distribution names differ (`bs4` and `beautifulsoup4`, `jwt` and `pyjwt`),
   the mapping needs installed metadata the isolated environment lacks, and
   a heuristic that is right most of the time is a silent failure the rest
   of the time.
