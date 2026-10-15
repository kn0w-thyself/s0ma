# When s0ma refuses, and how to get back to green

Most tools treat a refusal as a failure to apologise for. This one treats it as
the product: s0ma stops, names the thing it will not do, and leaves the work
exactly where you left it.

There is evidence for that being the right instinct, and it comes from this
repository's own documentation. An audit at the end of August 2026 read every
document s0ma ships and found a single dividing line running through all of
them:

> Every documentation surface under a mechanical gate is current. Every
> documentation surface outside a gate has drifted.

Not most. Every. The pages held to their source by a check that fails were
correct; the pages held by good intentions had quietly gone wrong — a version
number three releases stale here, an install command that no longer works
there. Nobody chose that. It is just what happens to a written description that
nothing compares against the thing it describes.

The two refusals on this page are that comparison, arriving early enough to be
cheap. This is what they look like, why each one is stopping you, and the way
back to a clean run from each.

**About the output below.** Every command on this page, and every line quoted
back from it, is replayed against the real toolchain before the page ships —
so what you read here is what the product actually says. Two things are done
to it, and only two: where your own run prints the full path to your project
or the version you have installed, this page writes `{project}` and
`{version}`; and the blank lines, rules and unrelated sections a real run also
prints are left out, so the blocks below are shorter than what you will see,
never different.

## A project to break

Any project will do; a throwaway one is easier to be careless with.

```bash
s0ma new project demo --name demo
```

Work inside it from here on, and start from a clean run so that what follows is
measured against something known:

```bash
s0ma check
```

```text
3 file(s) checked. No errors.
```

Three files, nothing refused. That is the baseline.

## The first refusal: a file s0ma owns was edited

Everything under `build/` is written by s0ma from your sources. It is output —
the same way a photograph is output and the negative is not — and s0ma stamps
each generated file with a fingerprint of what it wrote, so it can tell later
whether anybody has been in there.

Add a line to the end of `build/core_domain.py`, as though you had fixed
something in the generated code:

```python
# a note somebody added by hand
```

Ask the same question as before:

```bash
s0ma check
```

```text
{project}/build/core_domain.py:1: WARNING [GENERATED_FILE_DRIFT]
  {project}/build/core_domain.py was edited by hand; a build will not overwrite it until the .s0ma source says the same thing. Move changes into src/*.s0ma, or pass --force to discard them.
  Remediation: Move the hand edits back into the .s0ma source and rebuild, or discard them with `s0ma build --force`. `s0ma verify` classifies it as EDITED.
Results: 0 error(s), 1 warning(s) [mode: dev]
3 file(s) checked. No errors.
```

`check` reads and reports; it never writes, so it tells you and lets you carry
on. The build is the one that has to decide:

```bash
s0ma build .
```

```text
── {project}/build/core_domain.py (1 error(s), 0 warning(s)) ──
{project}/build/core_domain.py:1: ERROR [GENERATED_FILE_DRIFT]
  {project}/build/core_domain.py was edited by hand; a build will not overwrite it until the .s0ma source says the same thing. Move changes into src/*.s0ma, or pass --force to discard them.
  Remediation: Move the hand edits back into the .s0ma source and rebuild, or re-run with --force to discard the edits and regenerate. `s0ma verify` classifies this file as EDITED and `s0ma check` reports it as a GENERATED_FILE_DRIFT warning.
Results: 1 error(s), 1 warning(s) [mode: dev]
```

It stops, and it stops before writing anything. Your hand-written line is still
in the file. It stops the same way whether or not any source has changed since
the last build: a build never passes a hand-edited file off as one it wrote.

**Why this is the feature.** A build that had simply carried on would have
overwritten that line with the generated version and said nothing at all — and
you would have found out much later, looking for a change you were sure you had
made. That failure is not hypothetical; it is why the refusal exists. The
message is the whole disagreement stated plainly: there are two versions of
this file, one written by you and one derived from your source, and s0ma will
not pick between them on your behalf.

There are exactly two honest ways out, and no third:

- **Keep the change.** Move it into the `.s0ma` source it belongs in, then
  build. The generated file comes back carrying your change, because now the
  source says so. If the build still stops, something in the file is not in
  the source yet.
- **Let it go.** Say so, and rebuild from the source as it stands.

The second is what this walkthrough does, since the line was only ever a
demonstration:

```bash
s0ma build . --force
```

```text
Build complete: 3 module(s) → {project}/build (manifest: build.s0ma.json)
```

`--force` is not an override that silences a check. It is the answer to the
question the refusal asked: *discard the edit*. The file is now what the source
says it should be, and the hand-written line is gone, as instructed.

## The second refusal: a promise you have not written yet

The other refusal is about something you owe rather than something you broke.

Every part of a s0ma project declares what it promises. Sometimes you do not
know yet, and s0ma would rather you said that than invented something. So it
accepts a note in place of an answer. Change the `guarantees:` line in
`src/core/core_domain.s0ma` to one:

```s0ma
    guarantees: pending("replace this temporary release debt")
```

That is allowed, and it is honest. Ask:

```bash
s0ma check
```

```text
{project}/src/core/core_domain.s0ma:13: WARNING [SEMANTIC_PENDING_DEBT]
  Semantic field 'guarantees' on 'core_domain::describe_self' is pending: replace this temporary release debt. Pending earns zero completeness credit and blocks release.
Results: 0 error(s), 1 warning(s) [mode: dev]
3 file(s) checked. No errors.
```

A warning, and the run is still clean. You are working; you have written down
what you owe; s0ma is keeping the note.

Now ask the same question the way it will be asked the day you ship. The last
line of every run tells you which reading you got, and this is the strict one:

```bash
s0ma check --mode release
```

```text
[NEW] {project}/src/core/core_domain.s0ma:13: ERROR [SEMANTIC_PENDING_DEBT]
  Semantic field 'guarantees' on 'core_domain::describe_self' is pending: replace this temporary release debt. Pending earns zero completeness credit and blocks release.
1 failure(s): 1 NEW since your last green build.
Results: 1 error(s), 0 warning(s) [mode: release]
```

Nothing about the file changed between those two runs. The mode did. That is
the whole idea: `dev` is the reading that lets you work with debts outstanding,
`release` is the reading you have to pass before you tell anyone the project is
ready, and the same note is a shrug in one and a stop in the other. `[NEW]`
means it was not there at your last clean run — a long list where only one line
says `[NEW]` usually means you just broke one thing, not fifty.

The way back is to write the promise:

```s0ma
    guarantees: "Returns a non-empty human-readable string."
```

And ask again, at the strictness that refused you:

```bash
s0ma check --mode release
```

```text
3 file(s) checked. No errors.
```

```bash
s0ma build .
```

```text
{project}/pyproject.toml:1: WARNING [HOST_RUNTIME_UNDECLARED]
  Generated Python imports the s0ma runtime, but the host project does not declare s0ma-core, s0ma-dsl in [project].dependencies.
Results: 0 error(s), 1 warning(s) [mode: dev]
Build complete: 3 module(s) → {project}/build (manifest: build.s0ma.json)
```

Green, and earned under the reading that refuses a debt.

One warning is still there, and it is a third kind of thing again. Nothing is
wrong with what you wrote: `HOST_RUNTIME_UNDECLARED` is a fact about the
environment around it, and it has been sitting under every build on this page.
Which is the cue for the next section.

## When you cannot tell which of these you are in

The states look alike from the outside and have nothing to do with one another:
something you wrote does not satisfy the rules, the build is older than your
sources, a generated file was edited, or the machine you are on is not holding
what the project assumes. Before changing anything, ask for the health report:

Run `s0ma doctor`. The report has four sections — `versions`, `project`, `mcp`, and `findings` —
and its exact contents honestly depend on the machine it runs on: which s0ma
packages are installed, where, and at what versions is precisely the question
it exists to answer, so no two machines print quite the same page. Those are the lines that settle the
question. It answers what you would otherwise guess at: which s0ma packages
this machine actually has and at what versions — which is what the warning
above was really about — which mode this project is set to, whether the build
is older than the sources, and one thing to do next. It reads and reports; it
changes nothing. When you are lost, this is the cheapest question available.

## Where else to look

- [Troubleshooting s0ma](../troubleshooting.md) tells a check failure, a stale
  build, and drift apart in plain language, and translates the common failure
  names out of shorthand. This page walks the two refusals; that page is the
  one to read when you have met a third.
- [The error-code reference](../../packages/s0ma-dsl/docs/_generated/common_errors.md)
  is the complete list, generated from the toolchain itself.
- [Getting started](../getting-started.md) is where this project came from, and
  its own walkthrough includes both of these beats.
