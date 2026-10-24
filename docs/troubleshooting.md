# Troubleshooting s0ma

Things that go wrong, what they usually mean, and the command that fixes them.
Written for someone using s0ma, not someone building it. Each entry follows the
same shape: **what you see**, **what it usually means**, **what to do**, and
what to tell us if that does not work.

Two ground rules that save time:

- **Run s0ma commands with `uv run` from inside your project directory** —
  `uv run s0ma check`, not `s0ma check`. That is what makes s0ma use the
  installation belonging to *this* project. A bare `s0ma` uses whatever the
  system finds first, which may be a different copy or none at all.
- **Nothing here needs the internet.** Every command on this page works
  offline. The only things that start network activity are the feedback
  commands, which you run deliberately — and, where s0ma was installed through
  the hosted channel, its installer and one daily check for a newer version,
  which you can switch off.
  [`trust-model.md`](trust-model.md#every-connection-s0ma-can-make) lists
  every request that exists, one row each, with what it carries and how to stop
  it.

Related pages: [`getting-started.md`](getting-started.md) for the first
journey and the one route in the public repository offers, and
[`uninstall.md`](uninstall.md) for taking s0ma back off. Two sections below
are about the hosted channel's routes — the keyed installer and installing
through Claude — which the public repository's first release does not offer;
skip them unless s0ma arrived that way.

---

## Start here: `s0ma doctor`

Before anything else, ask s0ma what it thinks its own situation is:

```bash
uv run s0ma doctor
```

It answers in one screen and never changes anything:

| Section | What it tells you |
|---|---|
| `versions` | Python, and each installed s0ma package with its version |
| `project` | Which directory it decided is your project, that project's strictness setting, how many of its modules are up to date, and whether the build as a whole is current |
| `mcp` | Whether the authoring server can be found, and the line that registers it with your agent |
| `license`, `update check` | Deliberate placeholders in this release, labelled as such |
| `findings` | Everything above that deserves attention, each with the command that addresses it |

Two things to know about how to read it. **Findings are advice, not failure** —
`doctor` finishes successfully even when it has plenty to say, and it only
fails outright when the installation itself is broken. And **`project: not a
s0ma project`** simply means you are standing somewhere else: `cd` into your
project directory and run it again.

Most of the rest of this page is about a finding `doctor` has already named.

---

## "Which version am I actually running?"

**What you see:** behavior that does not match the documentation, or two
machines behaving differently.

**What it usually means:** more copies of s0ma on the machine than you thought,
and a command reaching one you did not intend.

**What to do:** there is no `s0ma --version` flag; `doctor` is the answer,
because it reports every s0ma package at once:

```bash
uv run s0ma doctor
```

Read the `versions` block. **Every s0ma package listed should show the same
version** — the installer puts all four on at once and they are released
together as a set, so a mismatch means the set got mixed. If they differ,
reinstall from the same source rather than trying to patch one package up to the
others. (The `mcp SDK` line is a third-party library with its own numbering, and
is not expected to match.)

If you want to know *which copy* is answering, the `mcp` section prints the
path where it found the authoring server, and that path tells you which
environment you are in.

**Still wrong?** Send us the whole `doctor` output — it is short, carries no
source code, and answers most version questions on its own.

---

## "`s0ma docs` says no documentation snapshot was found"

**What you see:** `s0ma docs` — or `docs list`, `docs show …`, `docs search …` —
stops with `no documentation snapshot was found`, and names the two places it
looked.

**What it usually means:** the copy of s0ma answering you has no documentation
inside it. There are only two ways that happens. Either you are running a
development install — a copy installed from a source tree rather than from the
release wheels — from a directory outside that tree; or the installation is
incomplete, which usually means an interrupted install.

**What to do:** reinstall from built wheels. From a clone of the repository,
build the four packages and install them again — the root `README.md` "Install"
section has the commands; if s0ma arrived through the hosted channel, repeat
that route. Built wheels carry the documentation, so a complete install always
answers.

If you are working *in* a clone of the s0ma source tree, run the command from
inside that tree instead — s0ma will answer from the tree you are standing in,
which is almost certainly the one you meant.

You can tell which happened from the first line of any `s0ma docs` answer once
it works again. It ends in `(installed)` when the answer came from the wheel and
`(checkout)` when it came from a source tree you are standing in.

**Still stuck?** Run `uv run s0ma doctor` and send us the `versions` block. A
package missing from it, or one at a different version from the rest, is the
usual cause and the fastest thing for us to confirm.

---

## Installing, license keys, and the download

*This section is about the hosted channel's keyed installer, which the public
repository's first release does not offer; an install from a clone has no key
and no download.*

**What you see:** the installer stops with a short block naming a code such as
`INVALID_KEY`, `NOT_ENTITLED`, `NOT_FOUND`, `RATE_LIMITED`, a checksum
mismatch, or a plain inability to reach the s0ma service.

**What it usually means:** something about the key or the download, not
something about your project.

**What to do:** these are all documented, with a table of every code and its fix,
in [`hosting-getting-started.md` §5](hosting-getting-started.md#5-troubleshooting)
— on the same page as the installer they come from. This page deliberately does
not repeat that table, so that there is only ever one copy of those facts to
keep true. Go there.

The one thing worth repeating: the installer is safe to re-run, and the
cleanest recovery from a run that stopped halfway is a **fresh, empty target
directory** rather than re-running into the half-made one.

---

## Installed through Claude: what each refusal means

*The Claude route is the hosted channel's, and the public repository's first
release does not offer it; this section is for a machine where s0ma arrived
that way.*

This section is for the plugin and the Claude Desktop extension. Commands are
spelled the way the Claude Code plugin makes them available — `s0ma-launch …`
and `s0ma …`, with no `uv run`, because the plugin puts both on the path of the
terminal Claude Code uses — and the numbers and notices below are the same on
both routes. Everything else on this page still applies once s0ma is running.
[Installing and updating s0ma in Claude](guides/claude-integration.md) is the
route itself; this is what to do when it says no.

**First move, always:**

```bash
s0ma-launch status
```

It reads local files, contacts nothing, and never prints a license key. Its
"Runs here", "Why" and "Next step" lines usually answer the question on their
own. If the command itself is not found, the plugin's own programs are not on
the path: check that `/plugin` lists s0ma as enabled, then restart Claude.

### What the number at the end means

Every `s0ma-launch` command ends in a number, and your agent sees it even when
the sentence scrolled past. Zero is success. The rest:

| You see | What it means | What to do |
|---|---|---|
| **2** | The command line was wrong, or what you asked for cannot be done here — a version that is not shaped like one, `pin` in a project that carries its own s0ma, `activate` where there is no terminal to type into, or a version the service has never heard of. | Read the sentence printed with it: each one names the correction. `activate` in particular needs a real terminal — in Claude, put the key in the plugin's settings instead. |
| **3** | s0ma is not installed, or could not be. Either nothing is installed here, or this copy has no such command, or `uv` refused to build the environment — in which case the message quotes the last lines `uv` printed. | Run `/s0ma:setup`, or `s0ma-launch install`. When `uv` spoke, read its lines first: they are about your machine, not about s0ma. Nothing was installed and nothing already installed has changed. |
| **4** | There is no license key on this machine, or the one that was used has been refused, or this account's access to new versions has ended. | The key goes in the plugin's **s0ma license key** field, or into `s0ma-launch activate` in your own terminal — never into a conversation. If access has ended, nothing installed stops working; only new downloads do. |
| **5** | Something about the network. The service could not be reached, or it was busy and asked this machine to wait, or it answered with something s0ma could not read. | Nothing was fetched and the copy on this machine keeps working. Try again in a little while; if it was a busy answer, the message says roughly how long it asked for. |
| **6** | A downloaded file was not the file the service described, so it was deleted and the install stopped. | Nearly always a download cut short: run it again. If it keeps happening on the same file, tell us — that is worth knowing about. |
| **7** | `uv` is not on this computer, or could not be run. | This is the one failure that stops everything, including the s0ma server itself. Install uv from <https://docs.astral.sh/uv/getting-started/installation/> and restart Claude. If uv *is* installed and this still happens, Claude was started without your shell's path: run `command -v uv` and paste that one path into the plugin's **Where uv lives on this computer** setting. |

### The line a new session sometimes starts with

s0ma tells a new session at most one thing, and only when there is something to
say. Silence is the normal case and means all is well. The six it can say:

| You see | What it means | What to do |
|---|---|---|
| *s0ma's tools are not available in this session.* … *s0ma is not installed on this machine yet.* | Claude started, found no s0ma to run, and answered with a stand-in server that can only report that. | Run `/s0ma:setup`. Then start a new session, so the real s0ma takes over. |
| *s0ma's tools are not available in this session.* … *This project asks for s0ma … in its `.s0ma-version` file, and that version is not installed on this machine.* | The project is pinned to a version this machine does not have. s0ma will not quietly run a different one. | `s0ma-launch install --version <the version it named>`, or `s0ma-launch unpin` to follow the newest installed version instead. |
| *The last time s0ma used your license key, it was refused.* | The service did not accept the key when s0ma last tried to fetch something. Everything installed keeps working. | Check the whole key was pasted, then put it back in the plugin's settings, or run `s0ma-launch activate` in a terminal. Never type a key into the chat. |
| *This account's access to new versions of s0ma has ended.* | News, not an error. The copy you have keeps working; only downloads of newer versions stop. | Nothing, unless you want new versions — in which case the message names the account page. |
| *s0ma … is available; s0ma … is what runs here.* | This machine is set to `notify`, so it looked and did not fetch. | `/s0ma:update` when you want it, or switch the setting to `auto` and stop being asked. |
| *s0ma … was fetched quietly in the background, and it is what Claude will use from your next session.* | An automatic update finished. Nothing changed underneath the session you were in. | Nothing. Start a new session whenever you like. |

One more line exists for the rare case where the real sentence would be too long
to read at a glance — *s0ma has something to say about this machine, and it did
not fit in one line* — and `/s0ma:doctor` prints the whole story.

**Nothing you see here can be caused by the notice itself.** It reads two local
files, opens no connection, and is written so that anything at all going wrong
ends as silence rather than as a hook error in front of somebody who opened
Claude to do something else.

### `/s0ma:update` says there is nothing newer, and I know there is

**What you see:** nothing at the start of a session about a newer s0ma, or
Claude telling you this machine is already current — when you know a newer
version was released.

**What it usually means:** nothing here has asked recently. The line a session
can begin with is drawn from **what the last check found**, and s0ma looks at
most once a day of its own accord — so a version released after this morning's
look is not news to this machine yet. And `s0ma-launch status` never claims to
know what the newest version is at all: it reports what is installed here, what
would run, and why. Only one command asks the service.

**What to do:** ask it now.

```bash
s0ma-launch update --check
```

That asks once and prints what is installed here, what the newest one is, and
what to do about the difference. If it names a newer one, `s0ma-launch update`
moves to it, and the change takes effect from your next session. If `--check`
also says there is nothing newer, there is nothing newer.

Two other reasons a machine legitimately stays where it is, both of which
`s0ma-launch status` names on its "Updates" and "Project" lines: **How s0ma
keeps itself current** is set to `off`, so s0ma never looks by itself — `update
--check` and `update` both still work, because `off` governs what s0ma does
unasked, not what you may ask for; or this project carries its own s0ma, or is
pinned with a `.s0ma-version` file, in which case no update moves it and that is
exactly what pinning is for.

**Still puzzled?** Send us what `s0ma-launch update --check` printed and which
version you expected.

### The key was refused

**What you see:** *The last time s0ma used your license key, it was refused*, at
the start of a session; or a command ending in **4**; or `s0ma-launch activate`
saying the key was not accepted.

**What it usually means:** the service did not accept the key that was used.
Usually only part of it was pasted. This is a different message from *this
account's access to new versions has ended*, which is not about the key at all.

**What to do:**

1. **Check the whole key.** s0ma never prints a key back — the most you ever see
   of one, anywhere, is `s0ma_...` and its last four characters — so compare what
   you pasted with what your account page shows.
2. **Put it in one of the two places it goes.** The **s0ma license key** field
   in the plugin's or the extension's settings, where it is masked as you type
   and kept by the operating system's own secure storage; or `s0ma-launch
   activate`, typed by you at a terminal of your own, which asks without showing
   what you type.
3. **Never type or paste a key into a conversation.** No part of s0ma will ever
   ask you to, and none of the `/s0ma:*` commands will either. A key pasted into
   a chat is a key in a transcript. Claude cannot run `activate` for you, and
   that is deliberate.
4. **Start a new session**, or run the command again.

Nothing installed stops working while a key is refused; only new downloads do.

**Still refused?** Tell us the exact message and whether the key works on your
account page. Do not send us the key.

### "`s0ma-launch: command not found`" in my own terminal

**What you see:** Claude runs `s0ma-launch status` happily, but the same command
in your own Terminal or PowerShell says it cannot find it.

**What it usually means:** exactly what it says, and it is deliberate. The
plugin puts `s0ma` and `s0ma-launch` on the path of the terminal **Claude Code
itself uses**. It does not change your own shell's path, because a plugin that
quietly edited your shell would be doing something you did not ask for.

**What to do:** for anything you can ask Claude to do, just ask — "run
`s0ma-launch status`" works. For the one thing Claude cannot do for you, saving
a key, ask for `/s0ma:setup`: it finds the launcher and shows you the full path
it is at, and you type that path followed by `activate` in your own terminal.
Working from a copy of the s0ma source instead? Then the commands are there
already, through `uv run`.

**Still stuck?** Tell us what `/s0ma:setup` printed as the path.

### Claude says the s0ma server failed to start

**What you see:** Claude reports that it could not start the s0ma server, or a
session begins with *s0ma's tools are not available in this session*, or a
command ends in **7**.

**What it usually means:** `uv` is on your machine but Claude cannot see it.
Claude started from a desktop icon does not always inherit the path your
terminal has, so a `uv` installed into your own home directory is invisible to
it. This is the one failure that stops everything, because uv is what builds
s0ma's own environments.

**What to do:**

1. **Check uv is really there**, in your own terminal: `command -v uv` on macOS
   and Linux, `where uv` on Windows. If nothing comes back, install it from
   <https://docs.astral.sh/uv/getting-started/installation/> and restart Claude.
2. **If it printed a path**, that is the answer: paste that one path into the
   plugin's **Where uv lives on this computer** setting, then restart Claude.
   The setting exists for this and nothing else, which is why it is otherwise
   best left alone.
3. **Then run `/s0ma:setup`**, which checks uv first and carries on from there.

In Claude Desktop there is no uv setting to fill in: the extension is started
through uv by Claude Desktop itself. If the server will not start there, it is
worth telling us about.

**Still failing?** Send us what `/s0ma:setup` printed, and the path
`command -v uv` gave.

---

## A check failure, a stale build, and drift are three different things

They produce similar-looking red text and have completely different causes.
Telling them apart is most of the work.

**A check failure means what you wrote does not satisfy the rules.**
`s0ma check` reads your `.s0ma` sources and reports what is missing,
contradictory, or not allowed — a required field left out, a name that refers
to nothing, an import written in the wrong place. It never runs your code and
never changes a file. How strict it is depends on the mode: your project's
`[tool.s0ma].mode` setting decides by default (a scaffolded project starts at
`dev`), and `--mode` overrides it for one run. The same file can be clean in
`dev` and fail in `release`, and that is the design, not a bug — `release` is
the strict reading you have to pass before shipping. `check` also remembers
your last clean run in a small local file, so its output marks failures as
`[NEW]` and tells you how many are new since then; a long list where only one
is `[NEW]` usually means you just broke one thing, not fifty.

**Staleness means the generated code is older than what you wrote.** s0ma
records a fingerprint of every source file when it builds. When you edit a
source and do not rebuild, that fingerprint stops matching, and everything
downstream — the generated Python, the graph, the viewer — is honestly
described as `stale`: it is showing the last real build, not a guess about your
unsaved thinking. `doctor` says so in one line (`build stale`, `1 module
stale`) and hands you the fix, which is always just:

```bash
uv run s0ma build src
```

**Drift means a generated file was edited by hand.** Everything under `build/`
is output: s0ma writes it from your sources and stamps it so it can tell later
whether anyone changed it. When someone does, `s0ma build` **refuses to
overwrite that file** rather than silently erasing the edit — that refusal is
the feature. The message names the file and offers the two honest ways out:
move the change into the `.s0ma` source it belongs in, or discard it with
`--force`:

```bash
uv run s0ma build src --force     # discards the hand edits, regenerates from source
```

The same word covers documentation: a page s0ma generates from your model that
no longer matches the model has drifted. `uv run s0ma docs check-drift src`
names each page that no longer matches and how far apart they are, and
`uv run s0ma docs render` regenerates them from the model.

---

## Common check failures, in plain language

`s0ma check` names each problem with a code in square brackets, quotes the file
and line, and prints a `Remediation:` line telling you the fix. **Read the
remediation line first** — it is written for the exact situation you are in and
is more specific than any table can be.

This is the same list a reader meets in the complete
[error-code reference](../packages/s0ma-dsl/docs/_generated/common_errors.md),
translated out of the shorthand:

| You see | What it means | What to do |
|---|---|---|
| `PARSE_ERROR` | s0ma could not read the file as `.s0ma` at all. Usually a stray character, a missing `---` before a body, or a block indented inconsistently. | Look at the line it names and the one above it. Nothing else in that file is checked until this is fixed. |
| `MISSING_FIELD` | A declaration leaves out something s0ma requires. | Add the named field. |
| `SEMANTIC_REQUIRED_STATE_OMITTED` | You left a field out that s0ma will not guess at. It wants you to say *something*: a real value, the word `none`, or `pending("why not yet")`. | Say one of the three. Silence is the only answer it rejects. |
| `UNKNOWN_FIELD` | A line names something this kind of declaration does not have — usually a misspelling (`tagz:` for `tags:`), or a line that belongs to another kind. s0ma does not read it, so whatever it was meant to say is not said. Until 2026-09-29 such a line was passed over in silence. | Correct the name, or move the line to the declaration it belongs to; the message names the line it thinks you meant. A warning day to day, refused in `strict` and `release`. |
| `UNRECOGNIZED_LINE` | A line inside a declaration is not a field, not part of a list or a block of text, and not a comment — almost always a field indented by the wrong number of spaces. | Start the field exactly four spaces in. Same weight as the row above. |
| `TEST_NOT_COLLECTED` | A test declaration's code defines no function named `test...`, so the test runner never runs it, while the declaration still counted as coverage for the parts it names. | Name the function `test_<something>`. Same weight as the two rows above. |
| `SEMANTIC_PENDING_DEBT` | You wrote `pending("...")` somewhere. That is allowed and honest, and it is recorded as a debt: it earns no credit and blocks a release-mode run. | Nothing, while you are still working. Replace it with a real value before you claim the project is releasable. |
| `BARE_IMPORT` | An `import` line sits inside a body. s0ma writes the imports itself, from what the module header declares. | One edit with two halves: add the name to the header's `requires:` (or `uses:` if it is another s0ma component) **and** delete the `import` line. Doing only half leaves the error in place. |
| `MISSING_PACKAGE` | The header requires something that is not installed in this environment. | Install it, or correct the spelling. Check you are running through `uv run` and inside the right project. |
| `DOES_NOT_EXIST` | A name you referred to is not in this project. | Usually a typo or a rename that did not reach every reference. |
| `NOT_EXPORTED` | The thing exists, but the module holding it does not publish it. | Add it to that module's `exports:` list, or refer to something that is already public. |
| `MODULE_NAME_STEM_MISMATCH` | The filename and the `module` name inside the file disagree. | Rename one to match the other. |
| `MODULE_NAME_COLLISION` / `DUPLICATE_DECLARATION` | Two things claim the same name — two files declaring one module, or one module declaring one name twice. | Rename one. The message suggests a name. |
| `CIRCULAR_DEPENDENCY` / `MODULE_DEPENDENCY_CYCLE` | Two or more modules depend on each other in a loop, so nothing can be built first. | Break the loop: move the shared piece into a third module both can use. |
| `CROSS_LAYER_DEPENDENCY` | Something in a higher layer is being reached from a lower one. Layers only flow one way. | Move the piece, or reconsider which layer each belongs in. |
| `VESTIGIAL_IMPORT` | Something is declared but never used. | Delete the declaration — or use it, if the omission was the mistake. |
| `PROVIDES_KEY_MISMATCH` / `MISSING_RETURN_KEY` | The header promises a set of names and the body returns a different set. | Make the two agree; the message lists exactly which names are missing or extra. |
| `GENERATED_FILE_DRIFT` | Someone edited a file under `build/`. See [the section above](#a-check-failure-a-stale-build-and-drift-are-three-different-things). | Move the change into the source, or `s0ma build src --force` to discard it. |
| `HOST_RUNTIME_UNDECLARED` | The generated code uses the s0ma runtime, but your project's package list does not mention it. A warning, not a stop. | Add `s0ma-core` and `s0ma-dsl` to your project's dependencies. |
| `MODULE_OUTSIDE_PROJECT_ROOTS` | The build was given a directory, and a module in it lives under none of the roots your `[tool.s0ma]` table declares, so the build recorded it as source, not as a test. A warning, not a stop. | Add the module's directory to `source_roots` or `test_roots`, or move the file under one of the declared roots. A bare `s0ma build` reads only the declared roots, so it never raises this. |
| `MISSING_TEST_COVERAGE` / `MISSING_PUBLIC_DOC_REF` / `MISSING_EMBEDDED_EXAMPLE` | Something public has no test, no documentation, or an unused example. **These only appear in release mode** — the release gate is where those become required. | Write the missing test, documentation, or example, or stop running in release mode until you are ready to. |

**A message you cannot act on is a defect in the message, and we want to hear
about it.** Send us the code, the line you were looking at, and what you
expected it to mean — that is one of the most useful reports a beta tester can
file.

---

## What an exit code means

Every `s0ma` command ends with a number a script or a CI job can read. The
same five numbers mean the same things in every command:

| Exit code | Meaning |
|---|---|
| `0` | Done. |
| `1` | What you wrote does not pass: a check failure, a build error, or host verification that found a problem. |
| `2` | The command line was wrong, or a refusal made for safety: an unknown option, a missing argument, an interpreter s0ma would not silently substitute for the one you meant. |
| `3` | s0ma itself failed. Send it as a feedback report. |
| `4` | Nothing to verify: `s0ma verify` found no built s0ma module under the target, and an empty "all clean" is not a pass. |

`s0ma verify` and `s0ma build` say more precisely what a `1` was, and the
language specification writes those ladders out (its sections 4.13 and 4.14).

## "It built, but into the wrong place"

The project is found by walking upward from the **directory you are in** to
the nearest `pyproject.toml` with a `[tool.s0ma]` table — not from the path you
pass to the command. Run from an unrelated directory, `s0ma build
/path/to/project` finds no table, warns in one line that a table went unused,
and falls back to a build that scatters its output next to the sources (and
exits `0`). Either fix works: `cd` into the project first, or put
`--project-root` *before* the subcommand:

```bash
uv run s0ma --project-root /path/to/project build /path/to/project
```

That flag is the one the authoring server's own `build_project` tool passes,
which is why a build run by a coding agent never meets this.

## The s0ma server does not show up in your agent

**What you see:** in Claude Code, `/mcp` does not list `s0ma-authoring`; or the
s0ma tools and the `/s0ma-feedback` shortcut are not offered; or your agent
reports that it could not start a server.

**What it usually means:** either the registration never happened, or it
happened somewhere other than where you are working.

**What to do**, in this order:

1. **Confirm the software is there.** `uv run s0ma doctor`, and look at the
   `mcp` section: it says whether it can find the server and prints the exact
   registration line if you need it.
2. **Confirm the registration exists.** `claude mcp list`. The installer
   registers the server *for the project*, which means the registration lives
   in a file called `.mcp.json` **inside your project directory** — so open the
   project folder in your agent, not the folder above it, and not a different
   project.
3. **Register it again if it is missing.** From the project directory:

   ```bash
   claude mcp add s0ma --scope project -- uv run s0ma-mcp
   ```

   The installer skips this step, with a printed note, when it cannot find
   Claude Code on your machine — so if you installed Claude Code afterwards,
   this line is simply the step that was skipped.
4. **Restart your agent.** A newly added server is picked up when the client
   next starts, not mid-session. In Claude Code you will also be asked to
   approve the project's server the first time.

**Do not test the server by running `s0ma-mcp` on its own.** It will appear to
hang. That is correct: it is a server waiting for a client to speak to it, and
there is nothing to see. Ctrl-C ends it.

**Still missing?** Tell us what `claude mcp list` printed, whether
`.mcp.json` exists in your project, and which client you are using.

---

## studi0 will not open, or will not update

studi0 is the local visual view of your project. `s0ma studi0` starts a small
server on your own machine, prints one line with the address it really used,
and opens your browser there. It serves until you press Ctrl-C.

**"The optional `s0ma-studi0` package is not importable in this environment."**
Most often the command ran outside the project and looked in the wrong
environment: re-run it as `uv run s0ma studi0` from the project directory. If
the viewer really is absent, note that the hint that message prints
(`pip install s0ma-studi0`) does **not** work during the beta, because s0ma is
not published on the public package index. How you get it back depends on how
s0ma arrived: re-run the keyed installer; or, if the downloaded files are still
in your project's `.wheels/` folder, add the viewer back with
`uv add ./.wheels/s0ma_studi0-*.whl`. A machine that gets s0ma through Claude
never meets this: the four packages are installed together, as a set, every
time.

**Nothing opens, but the terminal looks busy.** That is the server running
normally. Copy the address it printed into a browser yourself, or start it with
`uv run s0ma studi0 --no-open` and do that deliberately. The address is always
on your own machine and never reachable from another one.

**A full-page message instead of a graph.** studi0 draws what your last build
produced, so with no build there is nothing to draw. It says so and gives you
the command; run `uv run s0ma build src` and it fills in.

**The page is blank.** The page needs JavaScript enabled. With scripting turned
off it says so and points you at `uv run s0ma graph --format json --detail
full`, which is the same information as text.

**Amber markers and a banner saying the build is stale.** Not a fault — the
honest answer described [above](#a-check-failure-a-stale-build-and-drift-are-three-different-things).
studi0 is showing your last real build because you have edited a source since.
Rebuild in another terminal and the page catches up on its own within a second
or two; the markers clear as it does.

**Nothing changes after a rebuild.** studi0 re-reads the project continuously
and refreshes only when the build's content genuinely changed, so an
"unchanged" page after a rebuild that changed nothing is correct. If the
content really did change, check the rebuild actually succeeded — a build that
failed left the previous one in place, which is exactly what studi0 is showing
you.

**The port is taken.** Only possible if you pinned one with `--port`. Drop the
flag and let the machine pick a free port for you.

**Still stuck?** Send us the one line studi0 printed at startup, plus what the
page showed instead of the graph.

---

## Still stuck? What to put in a feedback report

Telling us is the point of the beta. A
[bug report](https://github.com/kn0w-thyself/s0ma/issues/new/choose) for
something that is wrong, or a
[discussion](https://github.com/kn0w-thyself/s0ma/discussions) for a question
or an account of how it went, needs nothing set up. On a machine with feedback
access — a keyed install gives it one — a report also takes one command from
your project directory:

```bash
uv run s0ma feedback --message "s0ma check reported X and I could not tell what to change"
```

You always see the finished report and approve it before anything is sent —
there is no flag that skips that, and your agent cannot approve on your behalf.
Reports carry no source code, no file contents, no conversations, and no name.
The other ways in all end at the same approval step: `/s0ma:feedback` if you
have the s0ma plugin; `/s0ma-feedback` in a project the s0ma scaffolder made,
which writes that shortcut into the project itself; the `feedback` prompt in any
MCP client; or simply telling your agent in plain English. All of it is
described in
[`hosting-getting-started.md` §4](hosting-getting-started.md#4-sending-feedback).

The five things that make a report immediately actionable:

1. **The exact command you ran**, including whether it began `uv run`.
2. **What it printed**, especially the code in square brackets and the line it
   pointed at.
3. **What you expected instead** — this is the one we cannot reconstruct, and
   the one that most often turns out to be the real finding.
4. **The `s0ma doctor` output**, which settles versions, project detection, and
   build freshness in one paste.
5. **Whether it happens again** from a clean start.

If a message was confusing rather than wrong, say that plainly. A message that
is technically accurate and still leaves you stuck is a defect we can fix, and
it is the kind we most need told to us.
