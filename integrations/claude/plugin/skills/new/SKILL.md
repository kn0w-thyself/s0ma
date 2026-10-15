---
name: new
description: Start a new s0ma project and prove it works, using `s0ma new project` and the static checks. Use when someone wants a fresh project, or wants to see what a s0ma project looks like.
---

# Start a new s0ma project

This writes a directory of files. Agree what it will be before you write
anything.

## 1. Check s0ma is there

Run `s0ma-launch status`. If it says nothing is installed, stop and run
`/s0ma:setup` first — nothing below will work.

## 2. Agree three things

Ask in one message, and suggest a default for each:

- **The directory.** It is created relative to where you are now. Say the full
  path back to them before you create it.
- **The shape.** `--template service` for a multi-feature application,
  `--template library` for something other code imports, `--template cli` for a
  command-line tool. Leave it out for the smallest possible starter.
- **The strictness.** `--mode dev` is the default and the right answer for new
  work. `--mode migration` is for a tree that is being converted; `strict` and
  `release` raise the bar the project's own checks hold it to.

## 3. Ask, then create

Say exactly what will appear: the directory, a `pyproject.toml` with a
`[tool.s0ma]` table, authored `.s0ma` source, tests, agent instructions, and a
generated `build/` directory. Wait for a yes.

```bash
s0ma new project my-app --template service
```

## 4. Prove it

From inside the new directory. These two import no application code and should
both exit zero in a fresh project:

```bash
s0ma check --mode release
s0ma score --gate-mode release --gate
```

`check` reads the authored source; `score` is the self-knowledge number and its
breakdown. Then build it, which compiles the `.s0ma` files into Python and
renders the app map:

```bash
s0ma build .
```

`s0ma test` runs the project's own declared tests, once its dependencies are
installed. If any of this fails on a brand-new project, that is a defect worth
reporting with `/s0ma:feedback`.

## 5. Show them what they have

Run `s0ma inspect --all` for a one-line summary of every module, and read the
app map under `build/docs/`. Then say the one rule that matters most:

> Edit the `.s0ma` files. Never edit anything under `build/` — it is generated,
> and the next build overwrites it.

Offer `s0ma docs show journey:first-project` for the guided walk through what
was just created, and `/s0ma:doctor` if anything looked wrong.
