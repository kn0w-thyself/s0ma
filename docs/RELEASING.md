# Releasing s0ma

The canonical runbook for cutting a release of the s0ma monorepo. It supersedes the pre-consolidation per-repo checklists (`packages/*/docs/release_checklist.md`, now pointers to this file).

The flow is automated end to end: one command cuts the version, and **pushing the `v<version>` tag is the release act** — it builds the wheels, records the GitHub Release, mirrors the wheels to R2, and verifies what production actually serves. Only the owner performs that push.

## The versioning model (PRD INV-4, NFR-3)

- **Lockstep SemVer.** All four packages — `s0ma-core`, `s0ma-dsl`, `s0ma-mcp`, `s0ma-studi0` — share **one version**, recorded in one root [`CHANGELOG.md`](../CHANGELOG.md) (Keep-a-Changelog), released as **one annotated git tag** `v<version>`.
- Pre-1.0, minor versions may break with a changelog notice; post-1.0, SemVer is binding and breaking changes require a major bump plus migration tooling.
- The DSL **spec** version (`docs/s0ma-dsl-spec-v*.md`, pinned as `CURRENT_SPEC_VERSION` in `packages/s0ma-dsl/tests/test_doc_consistency.py`) and the **IR schema** version (`s0ma_dsl/ir/schema.py`) are deliberately decoupled from the distribution version — they move only when the language or IR itself changes.
- The core **spec** (`packages/s0ma-core/docs/s0ma-core-spec-v*.md`) is not decoupled: unlike the language spec, it states the runtime surface of the package that carries the version, so it is cut at the package's own version at every release. `test_current_spec_version_matches_package_version` in `packages/s0ma-core/tests/test_doc_consistency.py` enforces it, failing until `CURRENT_CORE_SPEC_VERSION` there equals `s0ma-core`'s `project.version`.

## Before you cut

- You are on a release branch made from the tip of `main` (`git switch -c release-X.Y.Z`), because the cut lands there as [three commits](#the-three-commits-of-a-cut). The tree is clean, and the full gate is green: `uv run python scripts/check.py` (ruff, mypy, all four suites, selfhost/release integrity — including the wheel-license and cold-install checks — the INV-1 spelling guard, and the living-docs version-currency guard).
- Every user-facing change since the last release is captured in the root CHANGELOG's `## [Unreleased]` section. The package changelogs are frozen pre-monorepo history; never add to them.

## The three commits of a cut

A cut lands as three commits on its release branch, so that every gate reads a tree it can read. The reason is the channel rule. A tree composed with the tag (`--head-tag vX.Y.Z`) claims the `release` channel, and the gate's `docs-application` stage refuses that tree unless `S0MA_HEAD_TAG=vX.Y.Z` is stated ([step 5](#cut-a-release)). Ordinary CI (`ci.yml`) never states a tag, on purpose: it reads `main` and pull requests, and those trees claim `preview`. So a release-composed commit is red on ordinary CI by design, and the full matrix, Windows included, can only read a preview-composed one.

| Commit | What it holds | Gated | Then |
|---|---|---|---|
| **A**, prepare | the version everywhere, the three rebuilt builds, the changelog carved, the documentation composed plainly (identity lines read `X.Y.Z (preview)`) | plainly | push the branch and open a pull request; the full matrix reads A |
| **R**, cut | A, plus the tagged compose, its five mirrors and any golden that follows ([the loop](operations/docs-maintenance.md#the-loop), step 4) | with `S0MA_HEAD_TAG=vX.Y.Z` | nothing yet: R is never pushed as a branch head |
| **P**, reopen | R composed plainly again, so its tree is byte-identical to A's | plainly | push R and P together; ordinary CI runs once, on P |

**The tag names R.** It is the one commit whose documentation says `X.Y.Z` unlabelled, and the release workflow builds the wheels from it. **`main` ends at P**, by a fast-forward, so `main` never carries release-labelled documentation. After committing P, `git rev-parse <hash-of-A>^{tree} HEAD^{tree}` must print the same hash twice.

## Cut a release

1. **Dry-run the cut, read it, then write it.** Each command is given through `make` and, below it, as the script it runs, which works without `make`:

   ```bash
   make release-cut VERSION=X.Y.Z ARGS=--allow-branch     # dry run: prints the plan, writes nothing
   make release-cut VERSION=X.Y.Z ARGS="--allow-branch --write"

   bash scripts/release_cut.sh --version X.Y.Z --allow-branch
   bash scripts/release_cut.sh --version X.Y.Z --allow-branch --write
   ```

   [`scripts/release_cut.sh`](../scripts/release_cut.sh) preflights (clean tree; on `main` unless `--allow-branch`; the target strictly newer than the current lockstep version; `## [Unreleased]` non-empty; no `## [X.Y.Z]` section already in the changelog; the served changelog mirror in sync; `git` and `uv` present). A dry run reports blocked preflights and still prints the plan; `--write` refuses on any of them before touching a file. With `--write` it bumps `version = "…"` in all four `packages/*/pyproject.toml`, carves `## [Unreleased]` into `## [X.Y.Z] — <date>` (opening a fresh empty `## [Unreleased]` above it) in the root CHANGELOG **and** in the byte-identical served mirror `packages/s0ma-mcp/src/s0ma_mcp/_docs/CHANGELOG.md`, and refreshes the lockfile with `uv sync --all-packages`. It then **prints** the remaining steps and the commit/tag/push commands — it never commits, tags, pushes, or touches the network.

   That `uv sync --all-packages` is exact: it removes the optional extras from your environment, and the documentation build in step 4 refuses to compose without core's `api` extra. Put them back before you go on, the way CI installs them:

   ```bash
   uv sync --all-packages --all-extras
   ```

2. **Finish the version bump.** The cut bumps only the four manifests. The remaining sites, by hand:

   - the four `__version__` strings: `s0ma/`, `s0ma_dsl/`, `s0ma_mcp/`, `s0ma_studi0/` `__init__.py`
   - `packages/s0ma-studi0/s0ma_src/*.s0ma` → the `version:` module headers (every module in that directory carries one; s0ma-mcp's `.s0ma` sources deliberately carry none)
   - `packages/s0ma-core/tests/test_phase3_capstone.py` → the `s0ma.__version__ == "<version>"` assertion
   - `packages/s0ma-core/docs/` → cut the core spec at `<version>`, as the failing `test_doc_consistency.py` message directs: copy the current spec to `s0ma-core-spec-v<version>.md` (the old file is never renamed), set its `**Version:**` line and update its contents for what changed (its §0 and §13 speak of the previous cut); banner the outgoing cut as historical, naming the new file; repoint the older banners at the new file (`test_historical_spec_is_bannered` checks the pre-monorepo cut's); bump `CURRENT_CORE_SPEC_VERSION`; repoint the two pages that link the current spec, `packages/s0ma-core/docs/architecture.md` and `packages/s0ma-core/docs/references/documentation_subsystem.md`; and in `docs/s0ma_src/`, move the catalog's `doc:normative/s0ma-core-spec-…` row to the new file, give the outgoing cut a `doc:historical/…` row, and record both in the ledger (`doc-classification.json` and the summary beside it)
   - `packages/s0ma-dsl/tests/test_docs_provider_diagnostics.py` → the `RELEASE = "<version>"` line. One test there composes this repository at that version and requires no finding, so a stale value fails the `s0ma-dsl` suite with `DOC_VERSION_MISMATCH`. The other test modules that carry a `RELEASE` line use it as fixture data and do not move
   - version-bearing prose and examples in the root `README.md`: the lockstep line under **Packages**, plus the wheel filenames and the `gh release download` tag in **Install**'s owner-only route. It is the only living guide that pins the release version by hand — the four `packages/*/README.md` and `docs/walkthrough.md` carry no lockstep version of their own, and the gate below proves it
   - the Claude plugin, its marketplace entry and the Desktop extension state the version too, and one command moves all three: `uv run python scripts/sync_integrations.py --write`. Claude Code treats a plugin manifest's version as a pin — users get an update only when that field moves — so a cut that skips this ships a plugin claiming the previous release. The same command keeps the launcher's two shipped copies byte-identical to `integrations/launcher/s0ma_launch.py`; the `integrations` gate stage refuses the cut if any of it is out of step.
   - review (do **not** blindly bump) the cross-package dependency floors: `s0ma-dsl` requires `s0ma-core >= …`; `s0ma-mcp` requires `s0ma-core[mcp] >= …` and `s0ma-dsl >= …`; `s0ma-studi0` requires `s0ma-core >= …` and `s0ma-dsl >= …`. Raise a floor only when the package actually needs the newer sibling.

   Then run the doc-currency check — `uv run python scripts/check_version_refs.py` (the `docs-version-currency` gate stage). It names every living doc still carrying an old version, each with a `file:line`: the root `README.md`, the `docs/*.md` guides, `AGENTS.md`, `CONTRIBUTING.md`, `editors/README.md`, and all four `packages/*/README.md`. Nothing in that set needs a hand check any more — a missed bump fails the gate, and a version that deliberately dates a past release (or sits on another axis, such as the DSL language spec) lives in the script's `ALLOWLIST` with its written justification. The same stage also asserts that every package under `packages/` is named in `CONTRIBUTING.md`'s workspace tree and `AGENTS.md`'s package map, so adding a fifth package cannot leave the toolchain documented as four.

3. **Rebuild the three committed builds** — the two self-hosted packages and the documentation application — so they record the new versions (module headers, `transpiler_version`, and in `docs/_built/` the files `build.s0ma.json` and `build.s0ma.pyi`), and leave the regenerated `_built/` trees in the commit. The commands are the ones `AGENTS.md` gives:

   ```bash
   uv run s0ma --project-root packages/s0ma-mcp build packages/s0ma-mcp --mode release --no-cache
   uv run s0ma --project-root packages/s0ma-studi0 build packages/s0ma-studi0 --no-cache
   uv run s0ma --project-root docs build docs --no-cache
   uv run s0ma --project-root docs docs render docs/s0ma_src --output-dir docs --mode release
   ```

   s0ma-studi0 takes no `--mode`: its `pyproject.toml` sets `[tool.s0ma].mode = "strict"`, and the command reads it. The last line renders the documentation application's page, `docs/reference/documentation-application.md`, which the compose in step 4 reads.

4. **Compose the documentation and refresh its five mirrors.** The version bump and the rebuild above both change what the documentation build reads, so the snapshot has to be recomposed after them and before the wheels are built. Order matters here and the reason is in [The teaching-slice build order](#the-teaching-slice-build-order) below.

   ```bash
   uv run s0ma --project-root docs docs compose --output-dir docs
   cp docs/_generated/s0ma-docs-model.json \
      packages/s0ma-mcp/src/s0ma_mcp/_docs/s0ma-docs-model.json
   cp docs/_generated/core-teaching-slice.json \
      packages/s0ma-core/src/s0ma/_teaching/slice.json
   cp docs/_generated/s0ma-docs-model.json \
      packages/s0ma-dsl/src/s0ma_dsl/_docs_snapshot/s0ma-docs-model.json
   cp docs/reference/quick-reference-readable.md \
      packages/s0ma-mcp/src/s0ma_mcp/_docs/quick-reference-readable.md
   cp docs/_generated/quick-reference-machine.json \
      packages/s0ma-mcp/src/s0ma_mcp/_docs/quick-reference-machine.json
   ```

   The third copy is what `s0ma docs`, `docs list`, `docs show` and `docs search` read when there is no checkout, the last two are the quick reference the authoring server serves, and in commit R, the one the tag names, all five have to be copied from the **tagged** compose below, before the wheels are built — otherwise an installed reader is told a version this release is not. `selfhost-build` opens the built wheels and refuses a disagreement, and runs the four commands from a cold install.

   (The served `CHANGELOG.md` mirror `make release-cut` already wrote in step 1.)

   **The release-channel form.** The compose above is *told* nothing, so it composes the `preview` channel and every identity line it renders says `X.Y.Z (preview)`. To compose the release the tag will name, state the tag:

   ```bash
   uv run s0ma --project-root docs docs compose --output-dir docs --head-tag vX.Y.Z
   ```

   The tag is a **value**, never a lookup — nothing in the documentation build runs `git` — and the rule it feeds is the pure `channel_of` of architecture §13.2. Given the tag of the version being cut it composes `release`, so the manifest, every artifact row and every identity line say `X.Y.Z` unlabelled. Given anything else — a mistyped tag, last release's tag — it composes `preview` and says so on the line under `Composed …`; read that line, because a mistyped tag is a preview build that otherwise looks like a release cut. `s0ma docs check --output-dir docs --head-tag vX.Y.Z` asks the same question of what is already committed, and is how a cut proves the committed state *is* the release state before a wheel is built.

   **Which form to run: each, in its own commit.** Commits A and P compose plainly. Commit R, the one the tag names, composes with the tag. Outside a cut, the plain form is the only one: nothing is being cut and every tree is a preview. [The three commits of a cut](#the-three-commits-of-a-cut) says why.

5. **Run the full gate** after each compose: plainly for commits A and P, and stating the same tag for commit R:

   ```bash
   uv run python scripts/check.py                        # commits A and P
   S0MA_HEAD_TAG=vX.Y.Z uv run python scripts/check.py   # commit R
   ```

   All stages must pass (`selfhost-build` byte-verifies the committed builds, checks that the wheels carry the documentation this commit composed, and smoke-installs the wheels cold).

   The variable is how the tag reaches the `docs-application` stage, which composes the tree it gates and so has to compose in the channel the tree was composed in. It reads that channel from the committed `docs/_generated/docs-manifest.json` and follows it: after step 4's plain form it composes untagged and the variable is neither needed nor read; after the tagged form it requires the tag and **refuses the run without it**, naming the exact line to re-run. That refusal is the point — it is what makes a release-composed tree gate only where a release tag is stated, so `main` cannot carry release-labelled documentation that no tag ever cut. Nothing looks the tag up: it is stated here, on the [step 4](#cut-a-release) command line, and in the `check` job of the release workflow, and it is the same value in all three.

6. **Commit the cut, three times** — once after each gate, in the order of [The three commits of a cut](#the-three-commits-of-a-cut), with the messages the script prints. Push the branch after A, and again after P, which carries R with it:

   ```bash
   git add -A
   git commit -m "s0ma: release — prepare X.Y.Z (the version, the three builds, the documentation composed as preview)"
   git push -u origin release-X.Y.Z

   git add -A
   git commit -m "s0ma: release — cut X.Y.Z"

   git add -A
   git commit -m "s0ma: release — main returns to the preview channel after X.Y.Z"
   git rev-parse <hash-of-A>^{tree} HEAD^{tree}     # the same hash twice
   git push origin release-X.Y.Z
   ```

7. **☐ OWNER — tag and push. This is the release act.** Once CI is green on P, `main` moves to P by a fast-forward, and the tag names R by its hash:

   ```bash
   git push origin release-X.Y.Z:main
   git tag -a vX.Y.Z <hash-of-R> -m "s0ma X.Y.Z — <one-line summary>"
   git push origin vX.Y.Z
   ```

   `AGENTS.md`: "Never push a `v*` tag merely to test a release: the release workflow fires on pushed tags. Create/push only when the owner explicitly authorizes it." No agent creates or pushes a `v*` tag.

## What the tag push triggers

[`.github/workflows/release.yml`](../.github/workflows/release.yml) runs five jobs in order on every `v*` tag; each needs the one before it.

1. **check** — the full `scripts/check.py` gate on Python 3.11/3.12/3.13, against the tagged commit.
2. **verify-docs-identity** — opens the wheels this tag would ship and requires the documentation inside them to be the documentation this commit composed: the embedded teaching slice's snapshot, the served `_docs` payload, the `s0ma-dsl` wheel's packaged snapshot, and the version every identity line renders. It gates the job below, so a disagreement stops the tag before anything is published. Verification only — it builds wheels into a temporary directory, reads them, and uploads nothing. **Armed by a repository variable, not by merging:** see [The teaching-slice build order](#the-teaching-slice-build-order).
3. **release** — guards that the tag matches the lockstep version in all four pyprojects (INV-4), builds wheels + sdists (`uv build --all-packages`), asserts all four built at the tag version, extracts the `## [X.Y.Z]` CHANGELOG section (a missing section **fails** the release), and creates the GitHub Release with the eight artifacts attached and that section as the notes. That release is the **record of what shipped** — the eight artifacts and this version's changelog section, kept together under the tag, so "what was in X.Y.Z" has one answer that survives the working tree. It is not an install route: testers install from R2, never from it.
4. **mirror-r2** — mirrors the four wheels plus a merged `dist/manifest.json` into the R2 bucket `s0ma-dist`, the exact layout the control plane serves. Wheel objects are immutable (a re-run verifies the already-mirrored bytes back and aborts on any mismatch); the only mutation is the manifest, whose `latest` is **forward-only** by semver. Without the `CF_API_TOKEN` secret the R2 steps skip with a loud notice — the wheels still build, but prod keeps serving the previous `latest`.
5. **verify-served** — [`scripts/verify_served.sh`](../scripts/verify_served.sh) asks the control plane, from the outside with a real tester key, what it now serves: `latest` resolves to this version, the manifest names exactly four wheels, every served wheel's sha256 matches the manifest **and** the freshly built wheel, and the published `install.sh` matches the canonical one. Served-installer drift is downgraded to a `::notice` ("CP deploy pending") because control-plane deploys are manual (hardening R10/R11); every other failure class is red. Without the `S0MA_SMOKE_KEY` secret the job skips with a notice — and a green release then does **not** mean testers can install it.

## ☐ OWNER — deploy the control plane, only when it changed

The control-plane site (installer, distribution endpoints) deploys **manually** by design (R10/R11). Deploy it only when `scripts/install.sh` or the control plane itself changed in this release — a pure library release needs no deploy. After deploying, re-run the verifier locally and confirm the drift notice is gone:

```bash
S0MA_SMOKE_KEY=<key> scripts/verify_served.sh --version X.Y.Z
```

## Rollback

Put prod back on a known-good release by moving the manifest pointer (wheel objects stay immutable), then prove it:

```bash
scripts/mirror_to_r2.sh --version <older> --dist-dir dist --allow-latest-downgrade
S0MA_SMOKE_KEY=<key> scripts/verify_served.sh --version <older>
```

`--allow-latest-downgrade` is the deliberate override of the forward-only rule and the documented rollback mechanism; it is run locally, never from CI. Editing or yanking a GitHub Release changes nothing for testers.

## The two repo secrets

- **`CF_API_TOKEN`** — a Cloudflare **User API Token** with `Account → Workers R2 Storage → Edit`. Tokens minted from the R2 dashboard's "Manage R2 API Tokens" flow do **not** work (they are S3-compatible credentials; every `r2` REST call 403s while the token verifies as valid). The verified detail, and how to test a candidate token, are in [`scripts/mirror_to_r2.sh`](../scripts/mirror_to_r2.sh)'s header.
- **`S0MA_SMOKE_KEY`** — the license key of the smoke tester, an ordinary revocable `free_tester` account kept for this purpose, so revoking it makes verification fail loudly rather than pass silently. Provisioning it, storing the key, reading the verifier's output, and the rollback recipe: [`docs/hosting-getting-started.md` §6](hosting-getting-started.md#6-owner-runbook--provisioning-a-tester).

Both are set in this repository's Settings → Secrets and variables → Actions. Neither is ever passed as a command-line argument or echoed.

## The teaching-slice build order

A wheel makes claims about a documentation build. This section is how the release makes those claims true, and how it proves it did.

### What ships, and why the order matters

Three of the four wheels carry documentation as package data. `s0ma-core` carries its teaching content as one data file — `packages/s0ma-core/src/s0ma/_teaching/slice.json`; `s0ma-mcp` carries the composed snapshot plus nine mirrored documents under `src/s0ma_mcp/_docs/`; and `s0ma-dsl` carries the same composed snapshot at `src/s0ma_dsl/_docs_snapshot/s0ma-docs-model.json`, which is what the four `s0ma docs` commands read on a machine with no checkout. None of those files is written by hand: the documentation application renders the artifacts into [`docs/_generated/`](_generated/) and the packaged copies are byte-identical mirrors, and the nine are copies of documents the catalog names. Every one of them is stamped, directly or through the snapshot, with the release version, the build channel and the snapshot hash of the documentation build it came from — and every answer those wheels serve quotes that stamp back.

So the order is not a preference. Step 4 of *Cut a release* sits where it does because of what each step reads:

1. **Bump the version** (steps 1–2). Nothing composes yet: the manifests are what the documentation build will read the product version out of.
2. **Rebuild the three committed builds** (step 3). This has to come *before* the compose, not after: the documentation build reads `s0ma_mcp.create_server` and `s0ma_mcp.get_self_registry` from the built module, and the documentation application's rendered page, so composing first would describe the previous build. Neither self-hosted build reads a mirror, so there is no loop in the other direction.
3. **Compose, then refresh the five mirrors** (step 4). The snapshot the slice is stamped with now names the release being cut and not the one before it.
4. **Build the wheels.** After the mirrors are refreshed, so the packaged slice inside `s0ma-core`, the `_docs` payload inside `s0ma-mcp` and the packaged snapshot inside `s0ma-dsl` are the ones this release composed. A wheel built before the refresh ships the previous release's teaching content, stamped with the previous release's snapshot, and nothing downstream can tell.
5. **Verify against the manifest.** The check below, which is what makes steps 1–4 more than a convention.

### The circularity this ordering avoids

The obvious arrangement — verify the wheels, then compose the documentation that describes them — cannot work, because the documentation build reads the packages it describes and the wheels carry files the documentation build produces. Composing first and verifying last cuts the loop in the one place it can be cut: the snapshot is a fact about the *source tree at the release commit*, the wheels are built from that same tree, and the verification compares two records of one commit rather than asking either artifact to describe the other.

### The check, and where it runs

[`scripts/wheel_smoke.py`](../scripts/wheel_smoke.py) builds the four wheels, opens them, and holds what they carry against [`docs/_generated/docs-manifest.json`](_generated/docs-manifest.json) — the documentation build's own identity document. Four assertions:

| What is checked | Against which manifest field |
|---|---|
| The `s0ma-core` wheel's `s0ma/_teaching/slice.json` is the artifact this build rendered, and names this build's snapshot | `artifacts[…core-teaching-slice.json].content_hash`, then `snapshot_hash` |
| The `s0ma-mcp` wheel's `s0ma_mcp/_docs/` payload is the cataloged sources, byte for byte | `artifacts[…s0ma-docs-model.json].content_hash` for the snapshot; `source_hashes[].sha256` for each mirror whose source the build reads; byte equality with the cataloged source plus catalog membership in the wheel's own snapshot for the rest |
| The `s0ma-dsl` wheel's `s0ma_dsl/_docs_snapshot/s0ma-docs-model.json` is that same composed snapshot, and byte-identical to the `s0ma-mcp` wheel's copy of it | `artifacts[…s0ma-docs-model.json].content_hash`, then the two wheels against each other |
| Every wheel is at this release's version, no artifact row comes from another build, and the identity lines render this build's version the way a reader must meet it | `product_version`, then every artifact's `release_version` / `build_channel` |

The cold-install half of the same stage then runs `s0ma docs`, `docs list`, `docs show` and `docs search` from outside any checkout and requires each to answer, with `(installed)` and this build's snapshot digest on its first line. That is not decoration: those four commands shipped unable to answer at all for four releases, because the snapshot went into the `s0ma-mcp` wheel and the `s0ma-dsl` wheel got none, and nothing ever ran them anywhere but in a checkout.

It runs **locally on every gate run**, inside `scripts/check.py`'s `selfhost-build` stage — so an unrefreshed mirror is caught in ordinary development, not at a tag. To run it alone:

```bash
uv run python scripts/wheel_smoke.py --docs-identity-only
```

The same command, with the tag passed as a value, is what the `verify-docs-identity` job runs on a tagged commit. The tag is an argument and never something the check looks up: the channel rule is a pure function of the version and the tag, which is what makes the release case provable from a fixture instead of from a tag somebody has to cut first.

### ☐ OWNER — arming the release gate

The job is in the workflow and **is armed by a repository variable, not by merging**: it enforces only where that variable is `on`. The repository these releases are cut from has had it on since 2026-10-04, ahead of the first release composed with `--head-tag`. A new copy of the repository starts unarmed, because arming is a decision, not a consequence. Two things, in order:

1. **The prerequisite.** It exists. `s0ma docs compose --output-dir docs --head-tag vX.Y.Z` states the tag as a value and composes the `release` channel through the pure rule, so the release cut at [step 4](#cut-a-release) produces a manifest, artifact rows and identity lines that say `X.Y.Z` rather than `X.Y.Z (preview)` — which is what this check requires and what it used to have no way of getting. `s0ma docs check --output-dir docs --head-tag vX.Y.Z` proves the committed tree already *is* that release, before any wheel is built. The other half of that sentence is closed too: the `docs-application` stage of `scripts/check.py` no longer composes untagged regardless — it reads the channel the committed manifest claims and follows it, so a release-composed tree gates green where the tag is stated (`S0MA_HEAD_TAG=vX.Y.Z`, [step 5](#cut-a-release)) and is refused where it is not. The `check` job in [`release.yml`](../.github/workflows/release.yml) states `github.ref_name`, so the tag push carries it too; `ci.yml` states nothing, which is correct — trees on `main` claim `preview` and compose untagged, exactly as they always have. Nothing is left in this prerequisite. The committed tree here is preview-composed because it is not a release; a cut makes one commit, R, a release at step 4, and `main` ends on the preview-composed P.
2. **The action.** Set the repository variable `S0MA_DOCS_IDENTITY_GATE` to `on` (Settings → Secrets and variables → Actions → **Variables**, the same page as the two secrets below). Unsetting it disarms the gate again. While it is unset the job still runs and passes, with a `::notice` saying that nothing checked what documentation the wheels carry — the same shape as the R2 and served-release gates, and for the same reason: a job that skips takes everything downstream with it, including the release.

One decision is still open and is deliberately not taken here: whether the compose-and-mirror step belongs in `make release-cut` (which today writes only version bumps and the changelog carve) or stays a named step somebody runs. Automating it would mean the cut script writes into two package trees, which no other step of it does.

## PyPI (ruled; not yet switched on)

PRD NFR-8 records the decision: all four packages are published to the Python package index **starting with the first release cut from the public repository**, and nothing built from the private source tree is ever published there — the documentation snapshot inside a wheel built from the private tree lists private planning documents by title, and only the public export strips them. The bare name `s0ma` is to be held as well, by a small umbrella distribution that depends on the others and is built before that release. Until that first public release, all four packages reach testers only as wheels from the owner's R2 bucket, through the entitlement-gated control plane and keyed installer.

The release workflow carries the `publish-pypi` job commented out (`# TODO: enable after PyPI account/trusted-publisher setup` marks the spot). As written it publishes the four packages, and only when it runs in the public repository; the umbrella distribution joins it when it exists. Switching it on is the last of four steps, all the owner's: create the index account with two-factor sign-in; add a trusted publisher for each of the four projects, naming the public repository, this workflow file and a `pypi` environment; create that environment in the repository's settings; then uncomment the job. The workflow signs in by identity, so no token is stored. A name on the index is held only by publishing under it, and a published release can never be removed.
