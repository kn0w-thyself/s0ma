# Removing s0ma

This page takes s0ma off your machine completely: the installed software, the
small amount of state it keeps, and every place it registered itself. s0ma can
have arrived more than one way — from a copy of the source, which is the route
the public repository offers, or through the hosted channel's routes, through
Claude or with a key in a terminal — and the steps below cover all of them.
Take the ones that apply to you; the first thing each step says is how to tell.

Three things worth knowing before you start.

**Nothing on this page contacts anyone.** Removal is deleting files and running
a package-manager command. There is no account to close as part of removing
s0ma and no farewell message sent anywhere. One part of s0ma does start
something by itself — the launcher looking for a newer version, at most once a
day, and only when it was installed through Claude — and removing it is
[step 2](#2-take-s0ma-out-of-claude). Every request s0ma can make is listed, one
row each, in [what s0ma trusts](trust-model.md#every-connection-s0ma-can-make).

**Nothing here reaches the s0ma side.** If this machine was installed with a
key, that key and the account behind it are untouched by anything on this
page — see [Reinstalling later](#reinstalling-later).

**If you have feedback, send it first.** A bug report or a discussion on the
repository needs nothing from this machine. On a machine with feedback access —
a keyed install gives it one — `s0ma feedback` also works, but that access
lives in one of the directories you are about to delete, so it stops working
partway through. Sending takes a moment:

```bash
uv run s0ma feedback --message "removing s0ma because ..."
```

You see the finished report and approve it before anything leaves the machine,
exactly as described in [`hosting-getting-started.md` §4](hosting-getting-started.md#4-sending-feedback).

**Your own work is never touched by any step here.** The one thing to be careful
about is a name collision explained in [step 5](#5-remove-what-s0ma-left-in-a-project):
a *directory* called `.s0ma/` is s0ma's own scratch state and is safe to delete,
while *files* ending in `.s0ma` are the source you wrote and are not.

---

## At a glance

| Step | What it removes | Skip it if |
|---|---|---|
| [1](#1-stop-anything-that-is-still-running) | Running viewer and server processes | Nothing s0ma-related is running |
| [2](#2-take-s0ma-out-of-claude) | The Claude Code plugin, or the Claude Desktop extension | You never installed either |
| [3](#3-take-the-s0ma-server-out-of-any-other-coding-agent) | The s0ma server's registration in some other agent | You never registered it |
| [4](#4-remove-the-installed-software) | The s0ma packages installed into a project or an environment | s0ma only ever arrived through Claude |
| [5](#5-remove-what-s0ma-left-in-a-project) | Scratch state, generated code, and the project's own s0ma settings | You deleted the whole project in step 4 |
| [6](#6-remove-the-folder-in-your-home-directory) | The toolchain, the downloads, your key, feedback drafts and receipts | — |

Steps 1 to 4 take s0ma off. Steps 5 and 6 are tidying, and both are optional if
you are simply putting s0ma aside for a while — except for one part of step 5,
which changes a project rather than your machine, and says so where it comes up.

---

## 1. Stop anything that is still running

Two s0ma things can be running, and neither survives a reboot, so this step is
about not fighting a live process while you delete its files.

**studi0, the visual viewer.** If you started it with `s0ma studi0`, it is
serving a page in a terminal and blocking that terminal. Press **Ctrl-C** there.
On its way out it removes the small marker file it wrote into the project
(`.s0ma/studi0/active.json`). If studi0 was killed rather than interrupted, that
marker can be left behind; it is harmless, and step 5 removes it with everything
else.

**The authoring server.** You never start `s0ma-mcp` yourself — your coding
agent starts it as a child process and stops it when the agent stops. Quitting
your agent is enough, and through Claude that also stops the small launcher
that started it. (If you ever ran `s0ma-mcp` directly and it appeared to hang:
that is correct behavior, not a fault. It is a server waiting to be spoken to.
Ctrl-C ends it.)

---

## 2. Take s0ma out of Claude

Skip this if you never added the plugin or the extension — if `/plugin` in
Claude Code does not list s0ma, and Claude Desktop's Extensions settings do not
either, there is nothing here to do.

Both of these are **wrappers**. Each one is a little configuration, six named
commands, a start-up notice and a copy of the small program that starts s0ma.
Neither holds the s0ma toolchain itself: that lives in one folder in your home
directory, and [step 6](#6-remove-the-folder-in-your-home-directory) is where it
goes. Removing the wrapper alone is enough to stop s0ma doing anything at all,
including looking for newer versions.

**The Claude Code plugin.** Remove it the way you added it, with Claude's own
uninstall:

```text
/plugin
```

Find s0ma under installed plugins and uninstall it. In a terminal, the same
thing is `claude plugin uninstall s0ma@kn0wthyself`.

**Your key is Claude's to remove, not s0ma's.** What you typed into the
**s0ma license key** field was masked as you typed it and handed to the
operating system's own secure storage rather than written into a settings file,
which is Claude Code's documented behaviour for a setting marked sensitive. What
its uninstall does with that value is Anthropic's to document, not ours to
assert — so if you would rather be certain, **empty the field before you
uninstall**: open `/plugin`, clear **s0ma license key**, then remove the plugin.

**The Claude Desktop extension.** Open **Settings → Extensions**, find s0ma, and
remove it there. Its **s0ma license key** setting is held the same way — the
operating system's secure storage — and the same advice applies: clear the field
first if you want to be sure of it.

An extension is installed for one person, so removing it affects your own
Claude Desktop and nobody else's.

---

## 3. Take the s0ma server out of any other coding agent

Skip this if Claude was the only agent you used s0ma with.

Removing the software without removing the registration leaves your agent
trying to start a server that is no longer there. In **Claude Code**, from the
directory where you installed s0ma:

```bash
claude mcp remove s0ma
```

That is the mirror image of the `claude mcp add s0ma ...` line the installer
ran. With no scope given it removes the server from wherever it was registered.
`claude mcp list` shows what is registered if you want to confirm before and
after. (The plugin in step 2 registers the server for itself and needs none of
this; this step is for a registration you or the installer made by hand.)

**In any other MCP client**, the registration is an entry in that client's own
configuration — a block naming a server (usually `s0ma`) and the command that
starts it (`uv run s0ma-mcp` or `s0ma-mcp`). Delete that entry and restart the
client. Clients differ in where the configuration lives and whether they offer
a command for this; your client's documentation for *adding* a server names the
file to edit.

One thing to notice: if the installer registered the server **for the project**,
the registration is a file called `.mcp.json` inside the project directory.
Deleting the whole project directory in step 4 takes it with it.

---

## 4. Remove the installed software

Skip this if s0ma only ever arrived through Claude: nothing was installed into
any project of yours, and step 6 is where that copy lives.

Otherwise, take the route that matches how s0ma got onto this machine. If you
are not sure, run `uv run s0ma doctor` in the directory you have been working
in: its `versions` block lists the s0ma packages it can see, and its `project`
line names the directory it resolved.

### A. The one-line keyed installer (a project with its own s0ma)

The installer put everything inside one directory — the `my-app` you named when
you ran it. Nothing was installed outside it, and nothing was installed
system-wide. That directory holds:

| Inside the project directory | What it is |
|---|---|
| `.venv/` | The private Python environment holding the four s0ma packages |
| `.wheels/` | The downloaded installation files, kept after installing |
| `pyproject.toml`, `uv.lock` | The project's own package list |
| `.mcp.json` | The agent registration from step 3 |
| everything else | The starter project the installer scaffolded, plus whatever you wrote |

**If that directory was only ever for trying s0ma out**, deleting it removes
every trace of the installation in one move:

```bash
rm -rf my-app
```

On Windows PowerShell: `Remove-Item -Recurse -Force my-app`.

**If you wrote something in there you want to keep**, remove only the parts
s0ma installed and leave your files where they are:

```bash
cd my-app
uv remove s0ma-core s0ma-dsl s0ma-mcp s0ma-studi0
rm -rf .venv .wheels
```

`uv remove` uninstalls the four packages and takes them back out of the
project's package list; deleting `.venv/` and `.wheels/` reclaims the disk
space. Your source files, including everything you authored, are untouched.

### B. A virtual environment you made yourself

If you installed the s0ma packages into a Python environment you created — with
`pip install` and the four installation files — remove them the same way:

```bash
pip uninstall s0ma-studi0 s0ma-mcp s0ma-dsl s0ma-core
```

`pip` asks you to confirm each one. The order shown removes the add-ons before
the pieces they build on, which keeps the output easy to follow.

If that environment existed *only* for s0ma, deleting the environment directory
is simpler and more complete than uninstalling package by package:

```bash
rm -rf .venv
```

### Optional: the shared download cache

`uv` keeps a machine-wide cache of everything it has ever installed, so the s0ma
installation files may still be sitting in it. This step is only about disk
space, and it is safe:

```bash
uv cache clean s0ma-core s0ma-dsl s0ma-mcp s0ma-studi0
```

Naming the four packages matters. `uv cache clean` with no names clears the
cache for **every** project on the machine — not harmful, but every other
project then re-downloads what it needs.

---

## 5. Remove what s0ma left in a project

If a project directory is gone, so is all of this, and you can skip the step.
Otherwise this step has two halves, and they are not alike: the first removes
things s0ma made and can make again, and the second changes the project itself.

### Generated output and scratch state — yours to delete

Any directory where you ran a s0ma command may hold up to four things s0ma
made. All four are **regenerated from your authored sources** by the next
`s0ma build`, so deleting them cannot lose work.

| Name | What it holds | Safe to delete? |
|---|---|---|
| `build/` | The Python that s0ma generated from your `.s0ma` sources | Yes — it is output, never source |
| `.s0ma/` | Local scratch state: a record of the problems your last check already knew about (so it can tell you which ones are new), a small local database, and the studi0 marker | Yes |
| `.s0ma.cache/` | The cache that lets a rebuild skip unchanged files | Yes |
| `__s0ma_cache__/` | The same cache under an older name; only in projects that predate the rename | Yes |

```bash
rm -rf build .s0ma .s0ma.cache __s0ma_cache__
```

**One name, two very different things.** `.s0ma` on its own is a *directory* —
s0ma's scratch state, and what the command above removes. A *file* whose name
ends in `.s0ma` (`src/core/core_domain.s0ma` and its siblings) is source **you
wrote**. The command above leaves every one of those alone, because it names a
directory and not a pattern; keep them if you want your authored work after
s0ma is gone.

If your project's package file sets a different build directory
(`[tool.s0ma].build_dir`), substitute that name for `build` above.

One more, only if you kept the project: the scaffolder wrote the
`/s0ma-feedback` shortcut for Claude Code into
`.claude/skills/s0ma-feedback/SKILL.md`. It sits with your project's other agent
files and does nothing once the software is gone, so remove it too:

```bash
rm -rf .claude/skills/s0ma-feedback
```

### The project's own s0ma settings — a change to the project

Two more things may be in the project, and neither is about your machine.

| Name | What it is | Before you delete it |
|---|---|---|
| `[tool.s0ma]` in `pyproject.toml` | The project's own settings for s0ma: where its sources are, how strict a check is, where the build goes, which test runner it uses | It is the project's, not yours. Deleting it does not uninstall anything; it throws away settings that somebody will have to work out again |
| `.s0ma-version` | One line naming the version of s0ma this project is held on, so everyone working on it uses the same one | The same. It exists precisely so a project does not drift between machines |

Both are usually committed, so **removing them is a change to the project and to
everyone who works on it**, not a step in cleaning up your own computer. If you
are only removing s0ma from *this* machine, leave them alone and s0ma will
simply stop being run here. If you really are taking s0ma out of the project,
that is an ordinary edit and an ordinary commit — do it deliberately, with the
same care as any other change to a shared file.

---

## 6. Remove the folder in your home directory

One folder sits outside every project:

- macOS and Linux: `~/.s0ma`
- Windows: `%USERPROFILE%\.s0ma`

It is never inside a repository, and it is where everything that is not tied to
one project lives — the toolchain s0ma installed for itself, the files it was
installed from, your key if you saved it there, and the feedback function's
state. What is in it depends on how s0ma arrived: a machine that only ever used
the keyed installer has the feedback rows and nothing else, and a machine
installed from source has no such folder at all unless it was given feedback
access.

| What is in it | What it is | What deleting it costs you |
|---|---|---|
| `license` | The key `s0ma-launch activate` saved here, readable by you and nobody else where the platform allows that | You are asked for a key again the next time s0ma fetches anything. If your key lives in Claude's settings instead, this file was never written |
| `launcher/config.json` | Two settings: how s0ma keeps itself current, and which host it asks | Both go back to their defaults |
| `launcher/state.json` | What is installed, which version runs here, when it last looked for a newer one, and the last thing that went wrong | Nothing you can lose. s0ma looks for a newer version on the next start instead of waiting out the day |
| `launcher/update.log` | Everything the quiet update printed, in its own words, with the previous log kept beside it as `update.log.1` | Only the record of what past updates did. Nothing reads it back: the newest failure is kept in `state.json` instead |
| `launcher/update.lock` | The file two updates use so that only one of them runs | Nothing, unless an update is running as you read this |
| `toolchains/<version>/` | One private Python environment per version of s0ma, each finished with a `.complete` marker so a half-built one is never used | **The installed software itself.** Every version has to be downloaded and built again |
| `downloads/` | The files each version was installed from, kept and checked against their checksums so a reinstall need not fetch them twice | Only time: they are fetched again on the next install |
| `feedback-token` | This machine's feedback access. **Not** your license key — the key was exchanged for this once, and never travels with a report | `s0ma feedback` stops working until `uv run s0ma feedback enroll` |
| `installation_id` | The random identifier that stands in for your name on a feedback report | Nothing you can lose. A new one is made when it is next needed, so reports sent afterwards no longer look like the same machine as the ones before |
| `feedback-drafts/` | One file per report you wrote and have not sent | Anything unsent. Check first — the command is below |
| `feedback-receipts.jsonl` | One line per report you did send: when it went, and enough of the summary to recognise it | Your own copy of the record. The reports themselves are on the s0ma side, and `uv run s0ma feedback list` still shows them while you have feedback access |

**One folder, two owners, and a variable that moves only half of it.** If you
set `S0MA_HOME`, it moves the launcher's own files — the key, the settings, the
installed versions, the downloads. The feedback rows always use your home
directory. So on a machine where `S0MA_HOME` is set there are two places to
look, not one.

**Confirm you have sent anything you meant to send**, because unsent drafts are
in here:

```bash
uv run s0ma feedback drafts
```

Then remove it. Nothing needs to be stopped first as long as step 1 was done and
Claude is closed:

```bash
rm -rf ~/.s0ma
```

On Windows PowerShell: `Remove-Item -Recurse -Force $env:USERPROFILE\.s0ma`. If
you set `S0MA_HOME`, remove that folder too — and this one, which still holds
the feedback rows.

**If you would rather keep some of it**, the table above is the menu. Deleting
`toolchains/` and `downloads/` reclaims nearly all the disk space and leaves
your key, your settings and your feedback record in place:

```bash
rm -rf ~/.s0ma/toolchains ~/.s0ma/downloads
```

Deleting any of this does not delete anything you already sent, and it does not
touch anything on the s0ma side. Reports you sent stay yours to remove whenever you like —
see [Changing your mind](hosting-getting-started.md#changing-your-mind) — but you
need working feedback access to do it, so do that part **before** this step or
after reconnecting.

---

## What is not touched

None of the steps above go near:

- **Your own project files** — every `.s0ma` file you authored, every ordinary
  Python file, your tests, your notes, your git history. s0ma only ever
  generated into `build/` and its own state directories.
- **Your git repository.** Nothing here runs a git command.
- **Python, `uv`, `curl`, or your editor.** They were prerequisites, not part of
  s0ma, and other things on your machine use them.
- **Claude itself.** Step 2 removes one plugin or one extension; step 3 removes
  one server registration. Neither touches anything else Claude holds.
- **Anything on the s0ma side** — feedback you already sent, and, if this
  machine was installed with a key, the key and the account behind it. None of
  that is on your machine.

## Reinstalling later

Reinstalling is the route you used before, and the one the public repository
offers is stated once, in
[Getting started §1](getting-started.md#1-create-a-real-project): clone the
repository and build from it, with the commands in the root `README.md`
"Install" section. Build into a **new, empty directory** even if you kept an
old project, and move your `.s0ma` sources across afterwards.

If s0ma arrived through the hosted channel, which the public repository's
first release does not offer, the two routes are described once each, and a
key does not expire when you remove the software:
[s0ma in Claude](guides/claude-integration.md) is the whole Claude route,
including where the key goes, and
[the tester page](hosting-getting-started.md#7-the-exact-command-canonical)
holds the keyed installer's command; point it at a fresh directory (see
[Re-running](hosting-getting-started.md#re-running)).

A fresh keyed install reconnects this machine to feedback for you. You only need
to do it by hand if you deleted the home directory in step 6 and are not
re-running the installer:

```bash
uv run s0ma feedback enroll
```

---

## If something resisted removal

A file that will not delete, a registration that keeps coming back, a command
that fails halfway — those are worth telling us about, and they are exactly the
kind of thing that never gets reported because the person is on their way out.

A [bug report](https://github.com/kn0w-thyself/s0ma/issues/new/choose) on the
repository needs nothing from the machine you are clearing. On a machine with
feedback access, the report can also go from the project directory, **before**
you delete the home directory in step 6:

```bash
uv run s0ma feedback --message "uninstall: rm -rf .venv failed with ..."
```

If you have already deleted it, reconnect with `uv run s0ma feedback enroll`
first. Either way you see the finished report and approve it before anything is
sent, and it carries no source code, no file contents, and no name.

Useful to include: which step you were on, the exact command, and what it
printed back.

**See also:** [`troubleshooting.md`](troubleshooting.md) for problems while s0ma
is still installed, and [`getting-started.md` §1](getting-started.md#1-create-a-real-project)
for the route in that this page reverses.
