---
name: retrofit
description: Bring an existing Python codebase onto s0ma one module at a time, up the adoption ladder. Use when someone wants s0ma in a tree that already has working code they cannot rewrite.
---

# Retrofit an existing codebase

Nothing here happens in one go. The ladder converts a working codebase a module
at a time, and it leaves the code working at every rung. Never convert more
than one module before its check comes back clean.

**Read the guide first.** It is the authority; this file is the running order.

- `s0ma docs show doc:guide/retrofit-existing-codebase`

The whole path as an executable sequence is
`s0ma docs show journey:retrofit-existing-codebase`.

**Check what this s0ma can do.** Run `s0ma adopt --help`. If it lists fewer
commands than the rungs below name, this toolchain is older than the ladder:
say which rungs are reachable, do those, and stop.

## Rung 0 — assess

Read-only. Nothing is written, so run it without asking.

- `s0ma adopt scan`

Report what it found: how many modules, which are leaves, which have import
cycles, what it could not parse, and the order it proposes. Agree the first
module to convert — a leaf with few imports and real tests — before going on.

## Rung 1 — make the tree a s0ma project

**This writes files.** Say exactly which two: a `[tool.s0ma]` table appended to
`pyproject.toml` — source roots, package markers, and `migration` strictness —
and a short block added to `AGENTS.md` telling agents the tree is being
converted. No application code is touched. Wait for a yes.

- `s0ma adopt init`

Then measure where they are starting from. `s0ma doctor` should come back `ok`;
`s0ma score` is the number that has to go up; and `s0ma verify --all src` lists
what s0ma cannot yet account for — `adopt init` prints that command with this
project's own source root already filled in, so copy it from there rather than
guessing. Every application file showing as `UNKNOWN` is the honest backlog,
not a fault.

## Rung 2 — optional: bring the runtime picture forward

Existing Python can be marked up in place so s0ma knows about it while it is
running, before any of it is converted. There is no command for this; the guide
carries the exact loop, and it is worth doing only when someone wants the
runtime picture early.

A file that will stay Python for a while can be recorded instead, so the
project stops counting it as unaccounted-for and notices when it changes:

```bash
s0ma adopt file path/to/module.py --description "what this file is for"
```

That is interim debt, not a conversion. It answers no questions about what the
code does.

## Rung 3 — convert, module by module, leaf first

Six steps per module, in this order. Stop between them. Every `adopt` command
below takes the module's dotted name as the scan printed it (`pkg.thing`), or
the path to its file.

1. Record what the module does today, so the conversion can be proved against
   it: `s0ma adopt baseline <module>`. Take it **before** the draft and before
   anything is deleted — once the `.py` file is gone the record cannot be made
   again.
2. Turn the Python into authored s0ma source. **This writes a new file** — name
   it and wait for a yes: `s0ma adopt draft <module>`.
3. Fill in the draft's placeholders yourself. `s0ma check` reports every
   unwritten field as `ADOPT_PLACEHOLDER_INTENT`, and any text the draft could
   not place as `ADOPT_UNPLACED_CODE`; both are errors in every mode on
   purpose, because the draft is a starting point, not an answer. Ask the
   person whenever the intent of a function is not obvious from the code.
4. `s0ma check` and then `s0ma build` — both work on the project you are in.
   Two rounds of fix-and-recheck is the budget; if it is still red after that,
   something about the module is wrong for the ladder, not for you — say so.
5. Prove the converted module offers the same things as the original:
   `s0ma adopt verify-parity <module>`.
6. A clean verdict ends with a short "Before you delete …" list written for
   this project. Do it in the order it gives. First the **alias**: the build
   directory is flat, so removing `pkg/thing.py` breaks every
   `from .thing import …` in the package until its `__init__.py` binds the old
   name to the built module — the verdict prints the exact lines to paste.
   Then the two things it names beside them: the s0ma runtime declared in
   `[project].dependencies` and installed where the application runs, and the
   build directory shipped with the application.
7. Run the project's own tests with the original still present and check which
   file the module was imported from. Only when the built one is what loads
   **and** the tests pass, ask whether to delete the original `.py` file.
   Deleting it is their decision, never yours. The alias and the deletion
   belong in one commit.

Ask where they stand at any point with `s0ma adopt status`. It answers at every
rung, writes nothing, and ends in the single next command to run.

## Rung 4 — ratchet

When enough of the tree is converted, raise `[tool.s0ma].mode` a step at a time
— `migration`, `dev`, `strict`, `release` — and make the gate mean something
with `s0ma score --gate-mode release --gate`. Raise it once and leave it
raised: a threshold that goes down again is not a threshold.
