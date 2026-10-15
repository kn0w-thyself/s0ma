# What can change, and how you will know

If you are deciding whether to build something on s0ma, this is the page that
answers the first question: *what can change under me, and how will I find out?*

It is written to be checked rather than believed. Every promise below either
links to the document that makes it or names the command that proves it — and
where the honest answer is "this can break", the page says so, and says what to
do about it.

## Contents

- [The short version](#the-short-version)
- [What is stable now](#what-is-stable-now)
- [What is versioned by a schema string](#what-is-versioned-by-a-schema-string)
- [What can change between releases](#what-can-change-between-releases)
- [How a project protects itself](#how-a-project-protects-itself)
- [How a change is announced](#how-a-change-is-announced)
- [Which versions get fixes](#which-versions-get-fixes)
- [What "beta" means](#what-beta-means)
- [What 1.0 will mean](#what-10-will-mean)

## The short version

s0ma is **pre-1.0**, and here that means one specific thing: while the first
digit is a zero, a minor release may break something, and what announces it is a
changelog entry rather than a bigger version number
([the versioning model](RELEASING.md#the-versioning-model-prd-inv-4-nfr-3)).
It does not mean the ground moves at random. Three things you can rely on:

1. **What you have installed keeps working.** Nothing s0ma runs on your machine
   asks anyone's permission first, and an application you build on the runtime
   keeps running whatever happens outside that machine — written down as an
   invariant, in perpetuity, in [the requirements](../references/s0ma-prd.md).
2. **Anything written for a program to read says what shape it is.** Every file
   and report s0ma writes for another program carries a version string, and a
   reader that meets a number it does not know is refused rather than misled.
3. **Every change is written down once**, in [one changelog](../CHANGELOG.md),
   for one version that all four distributions share.

And one habit protects you from most of the rest: **pin the version, and commit
the build.** A pinned project does not move when the toolchain moves, and a
committed build turns "the new release generates different code" from a surprise
into a diff you read before you accept it.

## What is stable now

Three kinds of thing are written down as not-to-be-broken. The first is a short
list of invariants in [the requirements document](../references/s0ma-prd.md) —
the ones that matter to somebody building on s0ma are these:

- **The import names.** `import s0ma` is the runtime; `s0ma_dsl`, `s0ma_mcp`
  and `s0ma_studi0` are the other three modules; `s0ma` is the command. Renaming
  any of them is a major-version event with a migration tool, never a casual
  refactor (INV-2).
- **The file extensions.** Sources are `.s0ma`, the compiled record beside them
  is `.s0ma.json`, the source map is `.s0ma.map`, and the build manifest is
  `build.s0ma.json` (INV-3).
- **Determinism.** Nothing s0ma emits contains a clock reading, a random value,
  a path from the machine that built it, or an ordering that depends on the
  environment — and the same input builds byte-identical output on macOS, Linux
  and Windows (INV-5, NFR-7). This is the invariant that makes committing your
  build output worth doing.
- **The runtime is never gated.** `s0ma-core` is Apache-2.0 and fully functional
  with nothing from anyone else — no key, no permission asked, no network
  access — in perpetuity. Applications built on s0ma keep running whatever
  happens outside the machine, and no gate of any kind may enter the runtime
  path of a built application (INV-9, FR-COM-5).

The second kind is a **frozen contract**: a document that pins an interface
exactly, so that changing it is an act somebody has to perform in writing.
There are two of them, both in [`docs/contracts/`](contracts):

| Contract | What it freezes | How it may change |
|---|---|---|
| [The schema and surface budget](contracts/0.14.0-schema-and-surface-budget.md) | The version string and the exact top-level field set of the machine-readable documents listed in its [first section](contracts/0.14.0-schema-and-surface-budget.md#1-versioned-document-budget) — among them the project score, the canonical IR, the build manifest, the host-verification report and the common result an agent's tools return | A revision section appended to the document, naming exactly what is added and authorising nothing else. [Revision R1](contracts/0.14.0-schema-and-surface-budget.md#10-revision-r1--fd-5-feedback-surface-delta-2026-08-27) is the worked example |
| [The feedback contract](contracts/feedback-v1.md) | The wire format of a feedback report, the vocabulary it may use, the redaction rules applied before anything leaves your machine, and what is kept of it after it is sent | [Change control](contracts/feedback-v1.md#13-change-control): a wire-format change bumps the schema string and re-freezes the document; anything else needs a new numbered revision row. The document carries six of them |

The rule both follow is the same, and it is the only thing you have to remember
about them: **a frozen contract changes by gaining a new version or a recorded
revision, never by a silent edit.**

The third kind is a short list of promises about how change itself happens.
They hold now, before 1.0, and they will hold after it:

- **A report's code is never renamed and never reused.** Once a code such as
  `GENERATED_FILE_DRIFT` has shipped in a release, that spelling means that
  report for good. A code can be retired — it stops being made, and the
  changelog says so under *Removed* — but its name is never given to a
  different report, and a report never moves to a different code.
- **`--format json` is the interface for programs; the text is for people.**
  Where a command offers `--format json`, that output is the supported way for
  a script, a continuous-integration job or an agent to read the result. It
  carries a schema string, and within one schema number it changes only by
  addition. The text a person reads carries no such promise and may be reworded
  in any release.
- **Anything in this section gets one release of warning before it goes.** If
  something named here, or a document versioned by a schema string, ever has to
  be removed or changed in a way that breaks its readers, at least one release
  ships first in which the old way still works, warns where it can — a
  `DeprecationWarning` naming the replacement, or a notice in the command's own
  output — and is listed under *Deprecated* in the changelog. What is not named
  here can still change in a minor release with a changelog notice alone.

## What is versioned by a schema string

s0ma writes a good deal for other programs to read, and each of those documents
carries its own version — a string shaped like `s0ma-<name>@<number>`, or a
`schema_version` field. That string, not the release version, is what a reader
should key on:

| The document | Its version string |
|---|---|
| The canonical IR beside each module | a `schema_version` field |
| The build manifest, `build.s0ma.json` | `s0ma-build-manifest@1` |
| The project graph | `s0ma-graph@2` |
| The project score | `s0ma-score@2` |
| What an agent's tools return | `s0ma-tool-result@1` |
| A feedback report | `s0ma-feedback@1` |

What you may assume about a document whose number you recognise:

- **Fields may be added.** A new optional field does not move the number. When
  the build manifest learned to record each module's place in the source tree,
  it stayed at `@1`, because older readers that ignore the two new fields are
  still correct.
- **Nothing you already read is removed or re-meant.** That is what a new number
  is for: the next number up is reserved for a change that would break a reader
  of the current one.
- **An unrecognised number is refused, not guessed at.** Hand the toolchain a
  canonical IR from a major version it does not support and it stops with a
  report naming the major it does support and what to do — rebuild — rather than
  reading the file as if it were the shape it expected.

So: read the version string, ignore fields you do not know, and you will survive
every additive release without changing a line.

## What can change between releases

This is the honest half of the page.

**Wording written for people.** Most commands print for a person to read, and
that text is rewritten whenever it can be made clearer. Where a command offers
`--format json`, that form is the one written for a program — it is the form
that carries a schema string, and it is [promised](#what-is-stable-now) as the
interface a program may rely on. If a script, a continuous-integration job or an
agent needs to act on a result, read the JSON.

**The sentences in reports.** Every report s0ma can make about a project has a
code — `GENERATED_FILE_DRIFT`, `PARSE_ERROR` and the rest, every one of them
listed on [reports s0ma can make](reference/diagnostics.md) and every one of
them carried in the JSON beside its message. **Match on the code, never on the
sentence.** The sentence is prose written to help somebody fix the problem, and
it is improved between releases; the code is how the same report is addressed on
every channel. A code is registered rather than invented, so codes do not appear
casually — and once one has shipped it is
[never renamed and never reused](#what-is-stable-now), so a match you wrote
against a code keeps meaning what it meant.

**The exact bytes of generated code.** Builds are deterministic, so the same
sources and the same toolchain always produce the same output. A *different*
toolchain is a different matter: a newer release can emit a different `build/`
directory for sources you did not touch. s0ma's own
[release runbook](RELEASING.md#cut-a-release) rebuilds its committed build
output at every version bump for exactly that reason. This is not a defect, and
it is precisely why the habits in the next section exist.

**The tool surface a coding agent sees.** The tools, prompts and resources
served over the agent channel are treated as an interface rather than an
implementation detail: the whole client-visible surface is committed as a
snapshot, regenerated only for an approved change and reviewed as an exact diff
of names, descriptions, schemas and annotations before it ships
([the repository's own rule](../AGENTS.md)). Additions do happen — new
tools arrive between releases, and an agent that ignores one it does not know is
unaffected. A removal or a rename is a breaking change, announced under
*Changed* like any other.

**studi0.** The visual environment is the newest of the four distributions and
the one that promises least. It is an early preview: it does what it does
honestly and refuses to draw anything the project has not declared, and its own
[front page](../packages/s0ma-studi0/README.md) lists what is deliberately not
there yet rather than half-building it. Expect it to gain things; do not build a
workflow that depends on its current shape.

## How a project protects itself

Four things, in the order they matter.

**1. A project can carry its own toolchain.** A project with the s0ma wheels
installed into its own environment holds the version you installed until you
change those packages yourself, the way you change any other dependency, and
its lock file is the record of which one that is. Nothing outside the project
moves it: `uv run s0ma` inside the project always runs the toolchain the
project carries, whatever else is installed on the machine.

**2. Otherwise, pin the version.** Working straight out of a clone of the
repository, the toolchain is whatever commit is checked out, so hold the
project on one commit — a release tag, once there is one — and move to a newer
one deliberately, after reading the changelog. Going back is checking the older
commit out again.

**3. Commit your build, and check it.** `s0ma build <project> --check` rebuilds
the project and byte-compares the result against what is already there; a
non-zero exit means the sources and the artifacts disagree. Because builds are
deterministic and carry no machine paths, committing the build directory turns
that command into an equality gate across every machine and operating system —
and that is what converts "a newer toolchain generated different code" into a
reviewable diff in a pull request instead of a mystery in production. s0ma's own
repository does exactly this: its `selfhost-build` gate stage byte-verifies the
committed build output of the two packages written in s0ma on every run.

What that command is looking for has a name in s0ma: **drift** — the gap that
opens when a written description and the thing it describes stop agreeing. The
same mechanism keeps the **authored-vs-generated boundary** honest in the other
direction — the build refuses to overwrite a generated file somebody has edited
by hand, reporting `GENERATED_FILE_DRIFT` and offering two answers and no third:
move the edit back into the source it belongs in, or accept losing it.
[When s0ma refuses](guides/drift-recovery.md) walks both refusals end to end,
and [troubleshooting](troubleshooting.md) is the plain-words index of every
report.

**4. Read the changelog before you move.** Upgrading is the one moment when any
of this can bite, and the changelog is where the bite is described.
`s0ma doctor` tells you what this machine has and what this project is set to,
which is the other half of the same question.

## How a change is announced

**One version, one tag, one changelog.** All four distributions —
`s0ma-core`, `s0ma-dsl`, `s0ma-mcp` and `s0ma-studi0` — share a single version
number, ship from a single annotated tag, and are described in
[a single changelog](../CHANGELOG.md) at the root of the repository (INV-4).
"Which version of what" is therefore never a question you have to answer; what
each distribution contains and the licence it declares are on
[the distributions page](reference/packages.md).

**The changelog follows Keep a Changelog.** The headings actually in use are
*Added*, *Changed*, *Deprecated* and *Fixed*.

**A breaking change is labelled.** It goes under *Changed*, and its entry opens
with the word **BREAKING** — two real ones from the release that renamed the
file extension family read `BREAKING — file extension family renamed` and
`BREAKING — emitted hash markers renamed`. Reading the *Changed* section of a
release is the whole upgrade check.

**What a deprecation looks like here.** There is one in the record, and it is
the shape to expect: a moved function left in place as a thin re-export that
emits a `DeprecationWarning` naming its new home, with the old signature
unchanged so existing applications keep working, no removal scheduled, and an
entry under *Deprecated* saying all of that.

Be clear about how far that goes. **For what this page lists under
[what is stable now](#what-is-stable-now), and for any document versioned by a
schema string, the pattern is a promise**: at least one release carries the
warning, with the old way still working, before anything goes. The import names
and the command name are firmer still — a major-version event with a migration
tool, never a casual refactor (INV-2). **For everything else, before 1.0, it is
a precedent and an intention rather than a guarantee**: a minor release may
break with a changelog notice and nothing more (INV-4), and what we try to do
is the pattern above — leave the old way working, say in the warning where the
new one is, and schedule no removal until there is a reason.

## Which versions get fixes

**The newest release.** All four distributions ship one version together, so a
fix goes out in a new release rather than being carried back into an older one,
and updating is the supported way to get it. The security policy says so in
full, along with how to report something privately:
[which versions get fixes](../SECURITY.md#which-versions-get-fixes).

## What "beta" means

It means one thing here: **the software is pre-1.0** — everything above. The
public repository's first release is the code on GitHub, under its licences,
and nothing built from it checks anything in order to run.

That last point is not a courtesy; it is structural. Nothing running on your
machine asks anyone whether you are still allowed to run it: there is no check
before s0ma starts and nothing that switches it off, so what you have installed
keeps working whatever happens outside your machine — the first promise on this
page, written down as an invariant rather than as a behaviour of the moment.
Nothing built from this repository contacts a service unless you ask it to, and
[the trust model](trust-model.md) lists every request any part of s0ma can make
and how to stop each one.

## What 1.0 will mean

One thing is written down, and it is the thing that matters: **after 1.0,
semantic versioning is binding.** A breaking change then requires a major
version bump plus migration tooling, rather than a minor release and a changelog
notice (INV-4).

What has to be true before then is written down only in outline — the
consolidation rename having settled, and the agent-facing server proven against
real agent workloads (NFR-3). There is no published list of criteria for 1.0 and
no date, and this page will not invent one.
