---
name: preferences
description: Set or read how s0ma and studi0 are used, on this machine or in one project. Use when someone says "always use s0ma", "only show studi0 when I ask", or asks what their s0ma settings are.
---

# How s0ma is used, said in plain words

A person tells you how they want s0ma used, and you make it so. Nothing here
asks them to type a command: they say it, you run the command or write the
file, and you answer with the sentence below, word for word.

Two preferences are kept for the machine:

- **use**: `asked` (the default) means s0ma is used when they ask for it, or
  when the folder is already a s0ma project. `always` means new work is built
  as a s0ma project without asking first. Code that already exists is moved to
  s0ma only when they ask, whatever this says.
- **studi0**: `offer` (the default) means studi0 is offered once in each
  project, after a build. `always` means studi0 opens at the first build of
  each session. `asked` means it opens only when they ask.

A project can say its own `use` and `studi0` in a small file of its own,
`.s0ma/preferences.json`. Where the project says something, that is what holds
there; everywhere else the machine's answer holds. Each new session starts
with a short note telling you what is in effect. The person does not see it.

In every answer below, say "this Mac" on macOS, "this PC" on Windows and "this
computer" on Linux.

## On this machine

Run the command, then answer with the sentence.

| The person says | You run | You answer |
|---|---|---|
| "always use s0ma" | `s0ma-launch set use always` | Done. From now on I'll build new work with s0ma on this Mac without being asked. Say "only use s0ma when I ask" to change it. |
| "only use s0ma when I ask" | `s0ma-launch set use asked` | Done. I'll use s0ma only when you ask. Projects that are already s0ma keep working as they do now. |
| "always show studi0" | `s0ma-launch set studi0 always` | Done. I'll open studi0 at the first build of each session. |
| "only show studi0 when I ask" | `s0ma-launch set studi0 asked` | Done. studi0 stays closed until you say "show me studi0". |

To go back to offering studi0 once per project, run
`s0ma-launch set studi0 offer`. Each command saves one setting on this machine
and prints one sentence saying so; it changes nothing in any project.

## In this project only

When they say "always use s0ma in this project", write `"use": "always"` into
the project's file (the steps are below), then answer:

> Done, for this project only. Everywhere else stays as it was.

The same file takes `"use": "asked"`, `"studi0": "always"` and
`"studi0": "asked"` when someone asks for those in one project only.

## The studi0 offer

When the note at the start of the session says studi0 is offered once per
project, offer it once, after a build, if studi0 is not already showing. The
offer has three answers, and each one records something:

- **"Yes, always"**: run `s0ma-launch set studi0 always`. That holds on this
  machine, in every project. Nothing is written to the project's file for this
  answer.
- **"Just this once"**, **"No thanks"**, or no answer at all: write
  `"studi0": "asked"` into the project's file, so it is not offered in this
  project again. studi0 still opens whenever they ask for it.

## "What are my s0ma settings?"

```bash
s0ma-launch prefs
```

It reads two local files and changes nothing. Its first line is the answer, in
the words to say it in, with the real values. For example:

> On this Mac: s0ma only when asked, studi0 offered once per project. In this project: s0ma is on.

Read that line back. The lines under it say where each answer came from, if
they want to know. `s0ma-launch prefs --json` prints the same facts as JSON.

## Writing the project's file safely

The file is `.s0ma/preferences.json` in the project folder: the folder this
session was started in, which `s0ma-launch prefs` names on its `Project:` line.
Never a folder above it. Write it with your own file tools:

1. If there is no `.s0ma/` folder there, create it.
2. If the file is already there, read it first. If it holds a JSON object,
   keep every key already in it and change only the one you were asked to. If
   it holds anything else, show the person what is in it and ask before you
   replace it.
3. Write valid JSON: one object, such as `{"use": "always"}`.
4. Never touch any other file: not `.gitignore`, not `pyproject.toml`, and
   nothing else in `.s0ma/`.

The file is the person's own, and it is not meant to be committed. If the
project is a git repository that does not ignore `.s0ma/`, say so and suggest
they add `.s0ma/` to `.gitignore` themselves.

Then run `s0ma-launch prefs` and check its first line says what you meant. The
change holds from the next session; for the rest of this one, do what they
just said.
