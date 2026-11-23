---
name: build
description: Work on a s0ma project. Edit the .s0ma sources, then check, build and test, and show studi0 as preferred. Use when someone asks to add to or change a s0ma project, or to build something with s0ma.
---

# Build with s0ma

## When

The note at the start of the session says which `use` preference is in
effect, and `s0ma-launch prefs` reads it again whenever you need it.

- **`asked`**: build with s0ma when the person asks for it, or when the folder
  is already a s0ma project.
- **`always`**: new work is built as a s0ma project without asking first. Code
  that already exists is moved to s0ma only when they ask, and that is
  `/s0ma:retrofit`.

A project from nothing starts with `/s0ma:start`. Where s0ma is off in the
project (the first line of `s0ma-launch prefs` ends "In this project: s0ma is
off."), none of this applies: do not use s0ma there.

## How

1. **Read the project's own `AGENTS.md` first.** It is written for this
   project, and on anything inside the project it wins over this skill.
2. **Edit the `.s0ma` sources**, under `src/` and `tests/`. Never edit the
   files in the build folder, `build/`: they are generated, and the next build
   stops at one that was edited by hand.
3. **Check, build and test**, from the project folder:

   ```bash
   s0ma check
   s0ma build .
   s0ma test
   ```

   Run `s0ma check` after every edit, and fix what it reports by each
   finding's `Remediation` text, highest severity first. `s0ma build .`
   compiles the sources and renders the app map. `s0ma test` builds the
   project and runs its own tests.

   When s0ma's own tools are in this session, use them instead, as the
   project's `AGENTS.md` says: `project_status`, then `check` after each edit,
   then `build_project`. They are not there in the session that installed s0ma;
   the `s0ma` command does the same work.
4. **Report in one line**: what changed, that it built, and what the checks
   said, all from what the commands printed. Name a warning by its count and
   its code. Do not change anything to make a warning go away unless the
   person asks. If something did not pass, say that plainly, and what it said.

## studi0 after a build

The `studi0` preference in effect, from the same note or `s0ma-launch prefs`,
says what happens next. Starting and showing it is the `/s0ma:studi0` skill.

- **`always`**: at the first build of a session, start and show studi0, and
  say so in one sentence.
- **`offer`**: once per project, when studi0 is not showing, ask after the
  one-line report:

  > Want to watch changes like this land in studi0? It opens beside the chat.

  Where there is no pane beside the chat, as in the terminal, ask "Want to
  watch changes like this land in studi0? I'll start it and give you the
  link." instead.

  The three answers are "Yes, always", "Just this once" and "No thanks".
  Record the answer exactly as the `/s0ma:preferences` skill's section "The
  studi0 offer" says, then:

  - **"Yes, always"**: show it, and say:

    > I'll start it with each session from now on. Say "only show studi0 when I ask" to change that.

    In the terminal, say "studi0 is running: <address>" first, with the
    address it printed.
  - **"Just this once"**: show it.
  - **"No thanks"**: carry on.
- **`asked`**: nothing. studi0 opens when they ask for it.
