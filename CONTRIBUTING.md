# Contributing to s0ma

## If you are new here

Welcome. Here is where each kind of message goes — pick the row that fits and
you are done.

| You want to | Do this |
|---|---|
| **Ask a question** | Start a [discussion](https://github.com/kn0w-thyself/s0ma/discussions). Answers there stay findable for the next person. [Troubleshooting](docs/troubleshooting.md) answers most stops already — begin with `uv run s0ma doctor`. |
| **Report a bug** | Open a [bug report](https://github.com/kn0w-thyself/s0ma/issues/new/choose). The form asks for the output of `s0ma doctor`, what happened, what you expected, and the smallest way to make it happen again. |
| **Report a security problem** | Privately, never in an issue. [SECURITY.md](SECURITY.md) has the two routes and what to expect. |
| **Tell us about s0ma itself** | The same two places: a [discussion](https://github.com/kn0w-thyself/s0ma/discussions) for an idea, a question, or an account of how it went, and a [bug report](https://github.com/kn0w-thyself/s0ma/issues/new/choose) for something that is wrong. Neither needs a key or an account. |
| **Offer a change** | Open an issue or a discussion first — see the next paragraph. |

**Pull requests are by invitation during the beta.** Issues, bug reports and
discussions are open to everybody, today, and they are the contribution we most
want. Code is different: there is one maintainer, the build is gated end to end,
and an accepted change has to arrive with its provenance clear and under the
licence of the package it lands in — so we ask you to raise the idea first
rather than write something we may not be able to take. If it is something we
should build, we will say so and invite the pull request, with a sign-off on
each commit. This is a beta posture, not a permanent one.

Two things to know before you read further:

- **Licences.** Each package's licence is stated in its own `LICENSE` file and
  summarised in the [README](README.md#license); **Licensing** below says how a
  contribution inherits one.
- **studi0 is an early preview.** The visual environment ships and works, and
  there is more coming. Judge it as a preview.
- **Paths that begin `plans/`.** Comments, commit history and some documents
  cite files under `plans/` — for example `plans/complete/…`. That is the
  maintainers' planning archive, which is kept private; nothing you need in
  order to use or change s0ma is in it, and a citation of it is a record of
  where a decision came from, not a link you are expected to follow.

Everyone taking part is asked to follow the
[code of conduct](CODE_OF_CONDUCT.md).

The rest of this page is the working detail: how the repository is laid out, how
to set it up, the gate every change passes, and the conventions a change
follows.

---

Contributions are reviewed against the product's binding principles and
invariants — see [`references/s0ma-prd.md`](references/s0ma-prd.md)
(§5 Principles, §6 Invariants) before sending anything substantial.

## Workspace layout

This is a single uv workspace (one lockfile, one virtualenv) containing
four independently installable packages:

```
s0ma-new/
├── packages/
│   ├── s0ma-core/    # the self-knowledge framework (module: s0ma)
│   ├── s0ma-dsl/     # the .s0ma transpiler + s0ma CLI (module: s0ma_dsl)
│   ├── s0ma-mcp/     # the authoring MCP server (module: s0ma_mcp)
│   └── s0ma-studi0/  # the local visual environment `s0ma studi0`, hosting
│                     # the sh0w graph renderer (module: s0ma_studi0)
├── scripts/check.py  # the unified quality gate (what CI runs)
├── docs/             # repo-level docs (e.g. RELEASING.md)
├── references/       # the product PRD
└── CHANGELOG.md      # single Keep-a-Changelog for all packages (lockstep versions)
```

Dependency direction is one-way: `s0ma-mcp` / `s0ma-studi0` → `s0ma-dsl` →
`s0ma-core` (INV-6); core must stay fully functional without the other three.

## Licensing

The whole workspace is under one license, and a contribution inherits it:

- **All four packages are Apache-2.0** — the runtime foundation, the language,
  compiler and `s0ma` CLI, the authoring server, and the viewer.
- The repository root carries the same `LICENSE`, and a `NOTICE` beside it.
  Under Apache-2.0 section 5, a contribution you submit is offered under that
  same license unless you say otherwise in writing, so no separate agreement
  is needed.

Wheel metadata, classifiers, bundled `LICENSE` files, the PRD, and the
package docs must all agree; the `selfhost-build` stage checks all four
wheels' license metadata as part of the gate.

## Getting set up

Python ≥ 3.11 and [uv](https://docs.astral.sh/uv/) are required.

```bash
git clone https://github.com/kn0w-thyself/s0ma.git && cd s0ma
uv sync --all-packages --all-extras
```

macOS, Linux, and Windows are all first-class dev environments (native CPython; CI runs the full gate on Linux and Windows — NFR-7).

**Windows note — no `make` required.** The Makefiles are thin typing-savers over commands you can always run directly: the whole gate is `uv run python scripts/check.py` (below), and the one package-local convenience, `make docs-derived` (regenerates s0ma-dsl's derived docs when `tests/test_doc_consistency.py` asks for it), is equivalently `uv run s0ma docs render docs/_generators/ --output-dir docs/` run from `packages/s0ma-dsl/`.

## The check pipeline

One command is the whole gate — run it before every push; CI runs exactly
the same thing on `ubuntu-latest` (Python 3.11/3.12/3.13) and
`windows-latest` (3.11/3.13):

```bash
uv run python scripts/check.py            # ruff, mypy, four suites, selfhost,
                                          # wheels/cold install, docs, spelling
uv run python scripts/check.py --only pytest-dsl   # any subset; --list shows stages
```

`make check` / `make test` / `make lint` are thin wrappers over the same
script. All stages must pass — there are no advisory warnings (PRD P-3).

**The `integrations` stage.** `integrations/` holds what ships *around* the
packages — the launcher, the Claude Code plugin and the Claude Desktop
extension — so it has a stage of its own, after `pytest-studi0`. It runs ruff
over `integrations/` and `scripts/sync_integrations.py`; holds the launcher to
`mypy --strict` twice, in the native view and in the `--platform win32` view
(two shipped packages carry a copy of that one file and it runs on Windows for
real); checks that those copies, the three manifest versions and the feedback
skill's body are in step (`sync_integrations.py --check`); then runs
`uv run pytest integrations -q`. **Every change to
`integrations/launcher/s0ma_launch.py` is followed by
`uv run python scripts/sync_integrations.py --write`** — the plugin's and the
extension's copies are byte-identical to it, and that script is the only way
they change.

**The `authored-lines` stage.** Every `intent`, `guarantees`, `invariants`,
`schema` and `forbids` line in the repository's own `.s0ma` sources, test
fixtures and spike fixtures, and in the registrations written in Python
(`@component`, `ComponentSpec` and `Contract` under `packages/*/src`), stands
on its own: it names no plan, milestone, wave, review item, date, person or
ruling, and whatever it cites - a PRD requirement or invariant by its id, an
ADR by its number, a contract revision, a section of the specification its
project is written against - must resolve against the record that defines
it. `scripts/check_authored_lines.py` refuses any other line and prints the
three answers: reword it to stand alone, replace the reference with one that
resolves, or record a product term that merely shares a word with the
planning record in the script's `ALLOWLIST` with a justification. The rule
itself is written where agents and people learn to write a line: the quick
reference, the agent system prompt and the patterns guide.

**The build refuses NEW check errors (0.13.0 M2).** `s0ma build` (and the
MCP `build_project` tool) consults the per-project check baseline before
emitting: if your edit introduces a **NEW** check-severity error since the
last baseline, the build refuses — no artifacts written — and leads with
the labelled new-error list and the rule *"new check errors block builds;
fix them or pass `allow_new_errors=true` with a reason"*. `check` runs
strict while `build` runs dev, so a code that is a warning to the build
(e.g. `PROVIDES_KEY_MISMATCH`) is still a check error and is gated. Pass
`--allow-new-errors` (CLI) / `allow_new_errors=true` (MCP) to override
(the override is recorded in `build.s0ma.json`). This is **separate** from
`--force` (which discards hand-edits to a generated `.py` —
`GENERATED_FILE_DRIFT`); the two flags are never conflated. Pre-existing
errors alone never block (brownfield stays viable), and a missing baseline
degrades to warn-and-build. Re-running `check` on your own red tree does
**not** launder NEW into PRE-EXISTING: attribution keys on the baseline's
inherited-debt *anchor*, which is seeded at first contact and only ever
shrinks (a failure leaves it when observed fixed, and never re-enters).

## The spelling law (INV-1)

The product is spelled **`s0ma`** — lowercase s, digit **zero**, m, a —
in every identifier, extension, config key, document, and user-visible
string (case variants `s0ma` / `S0ma` / `S0MA`). The letter-o spelling is
forbidden except in git history, pre-consolidation changelog entries,
`plans/` and root `references/`, and legacy-migration code marked
`# legacy-spelling: intentional` on the same line.

The guard is enforced mechanically: `scripts/check.py`'s `spelling` stage
scans every tracked text file and fails CI on any violation.

## Commit messages

Follow the repo convention:

```
s0ma: <summary>                       # e.g. s0ma: cut X.Y.Z
s0ma: M<N> — <summary>                # milestone work
```

Keep commits focused; mechanical sweeps (formatting, renames) go in
separate commits from behavioral changes.

## Tests and docs

- New behavior ships with tests; the existing suites are floors, not
  ceilings (NFR-2). Golden/determinism fixtures are regenerated only via
  their documented mechanisms, with diffs reviewed as mechanical-only.
- User-facing changes get an entry in the root `CHANGELOG.md` (the
  package changelogs are frozen pre-monorepo history).

## Releases

Maintainers cut releases per [`docs/RELEASING.md`](docs/RELEASING.md)
(lockstep version bump, root CHANGELOG stamp, annotated `v<version>` tag,
tag-triggered release workflow).
