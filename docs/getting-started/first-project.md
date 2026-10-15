# Your first s0ma project

This walks a first session with s0ma from start to finish: you make a project,
ask the toolchain whether it holds together, add a module of your own, see what
a mistake looks like, build it, and then ask the project what it now knows
about itself. It takes about twenty minutes and leaves you with something real
on disk rather than a demonstration you have watched.

Every command below is run by a machine before this page ships, and every line
of output it quotes is compared against what really came back, so what you read
here is what the toolchain actually says.

## Before you start

One thing is assumed and everything else is taught here: that you already know
roughly what s0ma is — a platform built on the idea that software should carry
an accurate, queryable model of itself — and that you want a project of your
own. If that is not yet true, [the cold-start guide](../getting-started.md)
makes the case first and is the better page to begin on.

You also need s0ma installed. If the `s0ma` command does not run yet, there is
one route in, and the first section of [the cold-start guide](../getting-started.md)
states it once: clone the repository and build the four packages from source,
with the exact commands in the repository's own `README.md` under "Install".
s0ma is not yet published on the usual Python package index, so the ordinary
`pip install` route will not find it.

Once the command runs, nothing else is needed. Everything on this page works
offline, with no coding agent connected and nothing running in the background.

## 1. Make the project

s0ma starts a project for you, rather than asking you to arrange one:

```bash
s0ma new project demo --name demo
cd demo
```

We call it `demo` here; use any name you like, keeping in mind that the output
quoted below names this one. The `--name` part is the name the project declares
for itself — it would default to the folder's name, and saying it once keeps
the two from drifting apart if you rename the folder later.

The command names each file as it writes it: a settings file, a starter feature
with one working part in it, a test for that part, a map of the project, a set
of instructions for coding agents, and a `build` folder. The settings it writes
include the project's strictness mode, `dev`, which we come back to in a
moment. The last thing the command does is build what it has just written, so
the project is already complete and already built before you have typed a
second command.

## 2. What the project is made of

Open `src/core/core_domain.s0ma`. It is the starter feature, and it is worth
two minutes because every file you will ever write in s0ma has this shape.

The file opens with a **module** header, and the header speaks for the whole
file. It gives the file a name, places it in one architectural band, says what
the file is responsible for, and lists what it draws on from elsewhere and what
it lets other files use. Nothing enters or leaves the file without appearing in
one of those lists.

Two of the header's lines are worth naming.

**`layer:`** is the architectural band the file belongs to, and everything in
the file shares it. The bands are a fixed, short list of names written in
capitals — the subject matter itself, the work that coordinates it, the two
edges where a program meets people and meets other systems, and one band s0ma
keeps for its own machinery. A fixed rule says which band may depend on which,
so a band is a real constraint rather than a label.

**`intent:`** is the sentence that says why the thing exists. Every declared
part carries one and nothing is exempt. It is not a comment that someone
remembered to add: it is part of the declaration, so it cannot be left out and
it cannot quietly drift away from the thing it describes. You will see this
sentence again in section 7, when the project reads it back to you.

Below the header come the declarations — here, one working part called
`describe_self`. Each declaration describes itself first and carries its code
after, with a line of exactly three hyphens between the description and the
code. That is the whole anatomy of a **.s0ma file**: a header that speaks for
the file, then declarations, each one description-then-code. There is no other
arrangement to choose between.

## 3. Ask whether it holds together

This is the question you will ask more often than any other:

```bash
s0ma check
```

It reads every source file in the project and validates all of it, and it
generates nothing — no Python, no build output, nothing you have to clean up.
That is what makes it cheap, and being cheap is what lets you run it
constantly, after every edit if you like. The one thing it does keep is a small
note to itself, under `.s0ma/`, remembering what was clean the last time; that
note is where the `[NEW]` marker in section 5 comes from.

A clean run says so in one line and stops:

```text
3 file(s) checked. No errors.
```

Two ideas are underneath that line.

The first is **strictness mode** — the `dev` your project declared for itself
when it was created. The mode decides how severely the toolchain treats what it
finds. The most forgiving mode exists for bringing an existing codebase across,
where nearly everything is a warning. `dev` is the balanced everyday setting,
and it is what you want now. A stricter mode turns nearly everything into a
refusal and belongs in the automated checks before a change is merged, and the
release mode adds requirements of its own for the moment you ship. Your project
chose `dev`, and you can leave it there for a long time.

The second is the **check and build loop**, which is simply the shape of the
work: check the source, build it, run the verifications, then ask the built
system what it now contains. You are going to do exactly that in the next four
sections.

## 4. Add a module of your own

The starter feature is someone else's. Add one of yours:

```bash
s0ma new module greeting -o src
```

`-o src` says which folder to write it into. The command creates
`src/greeting.s0ma` and immediately tells you the file it has just written is
already valid, which is a small thing that matters: you never start from
something broken.

What it writes is a stub, with the word `TODO` everywhere a sentence belongs.
Replace the whole file with this:

```s0ma
module greeting
    layer: DOMAIN
    version: 0.1.0
    intent: "Greet the person using this project, by name."
    exports: [greet]
    requires: []
    uses: []

    soft_requires: none
    runtime_only_requires: none
    deferred_requires: none
    exports_helpers: none
nerve greet :: DOMAIN
    kind: FUNCTION
    visibility: PUBLIC
    intent: "Return a greeting for the name it is given."
    expects: "A name, as text."
    guarantees: "Returns a greeting that contains the name."
    forbids: none
    evaluates_at: FUNCTION_BOUNDARY
    provides: none
    returns: none
    raises: none
    interface: none
    latency_ms: none
    depends_on: none
    internal: none
    expected_exceptions: none
    consumes_via_dict: none
    declares_attributes: none
    covered_by: none
    ---
    def greet(name: str) -> str:
        """Return a greeting for the name it is given."""
        return f"Hello, {name}!"
```

It is the same anatomy as the starter file: a header that speaks for the file,
then one declaration that says what it expects and what it guarantees, then
three hyphens, then three lines of perfectly ordinary Python. The `forbids:`
line under the guarantee says what the part must never do, however it is
called, and `none` there means it rules nothing out. The long list of `none`
entries is the file answering questions rather than ignoring them — each one is
a thing this part could have declared and does not.

Ask the same question again:

```bash
s0ma check
```

It should now say `4 file(s) checked. No errors.`

## 5. What a mistake looks like

Suppose you had written the band in lower case — `layer: domain` rather than
`layer: DOMAIN`. The check would have stopped and said this:

```text
[NEW] /path/to/demo/src/greeting.s0ma:1: ERROR [PARSE_ERROR]
  Invalid layer: 'domain'
  Remediation: Valid layers are: DOMAIN, APPLICATION, INFRASTRUCTURE, PRESENTATION, FRAMEWORK
```

The first line carries your project's real location where `/path/to/demo` is
written here. Read what the rest of it gives you. It names the file. It quotes
the value it would not accept, rather than describing it. It lists what it
would have accepted instead. And it marks the finding `[NEW]`, meaning this one
was not there the last time the project was clean — so on a longer list you can
tell what you have just broken from what you already knew about.

The summary under it is worth reading too — `Results: 1 error(s), 0 warning(s) [mode: dev]`.
The mode from section 3 is on every summary, so you always know how severely
what you are reading was judged.

Nothing was built from that file. That is the useful part: a file the toolchain
cannot read produces no output at all, so there is nothing half-written to
clean up and nothing to undo. Repair the value it quoted, run `s0ma check`
again, and carry on.

## 6. Build what you checked

```bash
s0ma build src
```

Three things come back.

A **warning** about the host runtime, which is expected here and is not a
failure: it is telling you that the Python this project generates will import
the s0ma runtime, and that the project has not yet declared it as a dependency
of its own. That matters when you ship the project to a machine that is not
yours. For a project you have just made, on the machine you made it on, it is a
note rather than a problem.

A **summary line** — `Results: 0 error(s), 1 warning(s) [mode: dev]` — the same
shape as the one in section 5, and the same mode.

A **build**: the modules written, where they went, and the name of the file
that lists them. Every file the build made is under `build/`.

What the build produces is more than Python. When a s0ma program runs, every
declared part registers itself in a single index under a full name that joins
its file's name to its own. That index is the **registry snapshot**, and it is
what the running system consults whenever anything asks what it contains.
Because the names are qualified, two files may each hold a part called the same
thing without either hiding the other, and the index is complete — it includes
the parts no other file is allowed to call. The build writes the record that
index is made from, which is what the next section reads.

## 7. Ask the project what it knows about itself

```bash
s0ma inspect .
```

Every module comes back with its band, its version, its purpose, where it came
from, and the parts inside it. Find `greeting` in the list, and read the line
that starts `Intent:`. It is your sentence, from section 4, coming back out of
the project.

That is the point of the whole exercise. This is the **self-model**: the
project's record of itself — every declared part with its purpose, its kind,
its band, what it promises and what it depends on, along with the relationships
between them. It is load-bearing rather than descriptive. Being declared is a
condition of a part existing at all, so the record cannot fall behind the code
the way a written document does.

You can also see how the parts are wired to one another:

```bash
s0ma graph .
```

In a project this young that is mostly a count: how many nodes the graph holds,
and how many connections have been declared between them. There are no
connections yet, and an empty answer here is a real answer rather than a
missing one — nothing has claimed to depend on anything.

One rule follows from all of this, and it is the one to take away. Every fact
about your project has exactly one home. Facts a person states — what a part is
for, what it promises, what it depends on — you write once, in the source under
`src/`. Facts the toolchain can work out for itself — the generated Python, the
record of what exists, the rendered documentation — belong to the build, and
writing one of them by hand is refused rather than accepted as a shortcut. That
is the **authored-versus-generated boundary**: edit `.s0ma` files, never the
contents of `build/`. If you want something in `build/` to change, change what
it was made from and build again.

## When it does not go like this

Two failures are common enough to name.

**The check stops on a file it cannot read** — the `PARSE_ERROR` of section 5.
It names the file and quotes the value it refused. Repair that value and run
the check again; nothing was built from it, so there is nothing else to undo.

**Something your file asked for is not installed here.** If a file names a
Python package that this environment cannot import, the check says so. Ask for
the health report with `s0ma doctor`: it lists which s0ma packages this
environment actually has and whether it can see your project at all, which is
the question a missing import raises. If something is genuinely absent, install
it again by the route you used at the top of this page.

For anything else, [troubleshooting](../troubleshooting.md) starts with that
same health report and works outward through installing, stale builds, drift,
agent setup and the visual viewer.

## Where to go next

- [The cold-start guide](../getting-started.md) takes the same project further:
  release-mode checks, asking the model questions from a coding agent, watching
  the guardrails refuse a hand edit, and proving the result in the environment
  it will really run in.
- [The walkthrough](../walkthrough.md) builds something larger, one declaration
  at a time.
- [Removing s0ma](../uninstall.md) covers taking all of it off the machine
  again, including the project state and the build output, if you decide this
  is not for you. Deleting the `demo` folder is enough to undo this page.
