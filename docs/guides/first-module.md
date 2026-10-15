# Your first module

You have a project that builds. This page is about the next thing: writing a module of your own into it, one declaration at a time, and following it through until the system can describe it back to you.

Everything here happens inside a project that already exists. If you do not have one yet, [Getting started](../getting-started.md) makes one in a single command; so does this, if you would rather work in something throwaway:

```console
$ s0ma new project demo --name demo
```

That leaves you in a project with one starter feature in it. Change into it, and let us add a second feature beside the first.

By the end you will have written a file with two parts in it, seen the toolchain agree that it holds together, built it, and asked the built module what it now contains — and the answer will be the parts you declared, in the words you declared them in.

Some of the words below will be familiar from making the project. They are set out again here because on this page they stop being background and become choices you are making, one field at a time.

## 1. Where the file goes, and which band it belongs to

A feature is a directory under `src/`, and inside it one file per architectural band the feature needs. The file's name is the feature and the band joined by an underscore, and the name of the module inside has to match the file's name. Our feature is called `greeting` and it is subject matter rather than plumbing, so the file is `src/greeting/greeting_domain.s0ma`.

**Layer** (`concept:layer`) — the layer is the architectural band a file belongs to, and every part inside the file shares it. There are five: the subject matter itself, the work that coordinates it, the two edges where a program meets people and meets other systems, and the band s0ma keeps for its own machinery. A fixed table says which band may reach which — the subject matter reaches only itself and the framework, the two edges reach inward but never each other, and nothing reaches outward. You choose it once, for the file, and the build refuses a dependency that breaks the table rather than letting one accumulate quietly. Ours is `DOMAIN`: a greeting is part of what this project is about, not part of how it is delivered.

## 2. The header that speaks for the file

Every file opens with a header, and the header speaks for the whole file:

**Module** (`concept:module`) — the module declaration names the file, places it in one band, says what the file is responsible for, and lists both the outside code it draws on and the parts of itself that other files may use. It is the only door in and out. Because everything that crosses the file boundary is named in that one block, a tool can answer what this file needs and what it offers without reading a line of code, and the build can refuse a file that reaches for something it never declared.

**The file's shape** (`concept:s0ma-file`) — a s0ma file has a fixed anatomy: the header first, then one or more declarations, and every piece of code in it belongs to exactly one of them. Inside a declaration the description comes first and the code comes after, with a line of exactly three hyphens at the left margin between them. Nothing about a file's meaning depends on where you happen to look — the header always says what the file is, and the three hyphens always mark where the description stops and the code starts.

## 3. Three questions every part answers before anything else

Whichever kind of part you are about to write, three of its fields are decided before the rest.

**Kind** (`concept:kind`) — the kind is the archetype the part belongs to: for working logic, a plain computation, a coordinator, an adapter to something outside, or a long-running service; for structure, a data shape, a fixed value, a settings object, a list of allowed values, a type name, or an error type. It is what lets the system group its own parts by role rather than by name, so "show me every adapter" is a question the project can answer about itself.

**Visibility** (`concept:visibility`) — visibility says who may call this part from another file: everyone, only this file, or verification code as well. It governs calling and nothing else. Watchers, verifications and the documentation machinery reach every part whatever its visibility, because a system that cannot see all of itself cannot describe itself. That separation is the point: a small public surface and a complete self-description at the same time.

**Contract** (`concept:contract`) — a contract is the pair of promises a working part carries: what must be true before it is called, and what it guarantees once it has finished. Both are fields of the declaration rather than a comment beside it, so they travel with the code. Structural parts do not carry one — they say what they represent and what must always be true of them instead.

## 4. Choosing what kind of declaration to write

Four kinds are worth knowing before you write anything, because choosing between them is most of what authoring in this language is.

**Nerve** (`concept:nerve`) — a nerve is a piece of working logic that carries its own account of itself. You write the function as you normally would and, above it, say what it is for, what it needs from its caller and what it promises in return. If you would reach for a function, reach for a nerve. Ours is `greet`, and it is `PUBLIC` because the whole point of the feature is that other files call it — which also means the header has to list it among the parts this file publishes, since the header and the part have to agree.

**Cell** (`concept:cell`) — a cell holds a shape or a value instead of doing work: a data structure, a fixed value, a settings object, a list of allowed values, a type, an error type. The test is whether the logic inside serves the data's own rules rather than the wider system's work. Ours is `GREETING_OPENER`, the one word every greeting opens with, kept in one place so the wording is settled once. It is `INTERNAL`, because nothing outside this file has any business reaching for it.

**Ganglion** (`concept:ganglion`) — a ganglion is a watcher. It names the parts it observes, says what it expects normal to look like, and says what to do when what it sees does not match. It is how a system notices its own trouble rather than waiting to be told. We are not writing one here: nothing in this feature is assessing anybody else's behaviour yet, and a watcher with nothing to watch is a declaration that means nothing.

**Axon** (`concept:axon`) — an axon is a dependency somebody decided on, written down: which part leans on which, why, what travels along it, and how tightly the two are bound. It is reserved for decisions, because connections a machine can work out for itself are worked out for itself and may not be written by hand. We are not writing one here either, and the build will show you why in a moment: it works this particular connection out on its own, and says so if you declare it as well.

## 5. What this file is allowed to reach

**Uses** (`concept:uses`) — the `uses:` list names every part in another s0ma file that this file refers to, by any means at all — calling it, building it, raising it, or merely naming it in a type. Each entry has to be something the other file published, and each has to satisfy the layer rule. Ours has one entry: `core_domain.describe_self`, the starter feature's public part, which our greeting calls so that it can say what the project is. Outside code — anything from the standard library or an installed package — goes in the sibling `requires:` list instead; ours needs none.

## 6. The whole file

Put this in `src/greeting/greeting_domain.s0ma`:

```s0ma
module greeting_domain
    layer: DOMAIN
    version: 0.1.0
    intent: "The greeting feature: turn a person's name into a line that also says what this project is."
    exports: [greet]
    requires: none
    uses: [core_domain.describe_self]
    soft_requires: none
    runtime_only_requires: none
    deferred_requires: none
    exports_helpers: none

cell GREETING_OPENER :: DOMAIN
    kind: CONSTANT
    visibility: INTERNAL
    intent: "Keep the word every greeting opens with in one place, so the wording is settled once."
    schema: "The single word a greeting starts with."
    invariants: "Never empty."
    covered_by: none
    ---
    GREETING_OPENER = "Hello"

nerve greet :: DOMAIN
    kind: FUNCTION
    visibility: PUBLIC
    intent: "Greet a person by name and tell them what this project is."
    expects: "A name that is not empty."
    guarantees: "Returns one line that opens with the settled opener, names the person, and says what the project is."
    forbids: "Never returns a greeting that leaves out the person's name."
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
        """Greet a person by name and say what this project is."""
        return GREETING_OPENER + ", " + name + ". " + describe_self()
```

The `forbids:` line says what this part must never do, however it is called — here, the promise to name the person, said from the other side.

The fields set to `none` are not noise and they are not optional. Each one is a question the language asks of a part of this kind, and `none` is the answer "there is nothing here" — said out loud, so that an unanswered question and an answer of nothing never look the same.

## 7. Ask whether it holds together

Checking reads the source, validates it, and writes nothing at all, which is what makes it cheap enough to run constantly:

```console
$ s0ma check

4 file(s) checked. No errors.
```

Four files: the app map and the starter feature and its verification, which were already there, and now yours.

If the check is not happy, it says so with the file and the line that caused it, and it stops before anything is built from what it could not read. The one you are most likely to meet while learning the shape of a file is `PARSE_ERROR`, which means the code under one of your declarations is not valid Python — usually a declaration that ran into the next one because the code above it was never closed off. Repair the line it names and ask the same question again. [Troubleshooting](../troubleshooting.md#common-check-failures-in-plain-language) has the rest of them in plain language.

## 8. Build it

Building turns the source into ordinary Python and, beside each generated file, writes the record of what that file declared.

In the output below, `{project}` stands for the full path to your project; the real output prints it in full.

```console
$ s0ma build src
{project}/pyproject.toml:1: WARNING [HOST_RUNTIME_UNDECLARED]
Results: 0 error(s), 1 warning(s) [mode: dev]
Build complete: 3 module(s) → {project}/build (manifest: build.s0ma.json)
  {project}/build/greeting_domain.py
  {project}/build/greeting_domain.s0ma.json
```

The warning is about the throwaway project rather than about your module: nothing has declared that this project depends on the s0ma runtime it now imports. It is a warning and not a refusal because the mode is the everyday one.

Two of those files are yours, and the second one is the interesting one.

**The canonical record** (`concept:canonical-ir`) — beside the Python it generates, the build writes a normalised record of everything the file declared: every name in its full form, every shorthand expanded, every automatically-derived connection filled in, and a fingerprint of the whole. It says exactly what your source says, with none of the ambiguity, and it is the form tools and agents read. Do not edit it — the build rewrites it every time, and the source file is where a person writes.

## 9. Ask the module what it contains

```console
$ s0ma inspect greeting_domain
Module: greeting_domain
  Layer: DOMAIN
  Source: src/greeting/greeting_domain.s0ma
Components (2):
  greeting_domain::GREETING_OPENER [INTERNAL CONSTANT cell]
  greeting_domain::greet [PUBLIC FUNCTION nerve]
Derived edges (1):
  greeting_domain::greet --[TYPE_USES]--> core_domain::describe_self
Exports: greet
```

The real output prints a little more between those lines — the version, the intent you wrote, and a fingerprint of the file — and the summary of each part in your own words.

Read the middle of it back against what you wrote. Both parts are there, each with who may call it and which archetype it is, in the words you chose. Nothing here was inferred from a naming convention: it is your file, read back.

The line under **Derived edges** is the answer to the axon question from step 4. Nobody declared that connection. The build saw `greet` reach across to `core_domain::describe_self` and recorded the edge itself, which is exactly why writing an axon for it would be writing down something already known — and why an axon is worth spending on a decision a reader could not have worked out.

## Where to go next

- Add a verification that names the part it verifies, so the project can say which of its parts are covered and by what.
- Run the loop again after every change: check, build, inspect. Checking generates none of the build output — it keeps only a small bookkeeping note of what it has already told you — so there is no reason to wait.
- If this is your first time in a s0ma project, start one first: [your first project, from install to graph](../getting-started/first-project.md).
- The ideas this page introduced each have a fuller entry — what they are for, when to reach for them, when not to — in the [concepts index](../reference/concepts-index.md).

Every command and every line of source on this page is replayed against the real toolchain by [a transcript fixture](../s0ma_src/evidence/first-module.json), which is what keeps this page true.
