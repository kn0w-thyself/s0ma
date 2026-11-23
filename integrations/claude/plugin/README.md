# s0ma for Claude Code

s0ma gives Claude a living model of the software you are building: what each
part is for, what it depends on, and why it is there. This folder is the s0ma
plugin for Claude Code. It adds twelve named commands, three hooks, the s0ma
server, and the small launcher that installs s0ma and starts the right copy of
it for each project.

It is a Claude Code plugin only. It has a `bin/` folder, and claude.ai and
Cowork do not install a plugin that has one.

This page says everything the plugin runs, fetches, sends and writes, so you
can decide whether to install it.

## What it runs

**Three hooks**, from `hooks/hooks.json`. Each runs a shell script in the
plugin's `hooks/` folder with `sh`, which on Windows is Git Bash.

- **When a session starts**, `hooks/session-start.sh` gives Claude a short
  note on whether s0ma is set up on this machine and what it can do in this
  folder, and gives you a line only when there is something to say. With uv
  on the machine it asks the launcher's `session-hint`; without uv it reads one
  fixed sentence from `scripts/not-set-up.txt`.
- **Before each Write and Edit**, `hooks/edit-guard.sh before-edit` refuses an
  edit to a file under a s0ma project's build folder, and tells Claude to
  change the `.s0ma` source instead. Outside a s0ma project it stops at once,
  without starting uv or Python.
- **After a Write or Edit to a `.s0ma` file**, `hooks/edit-guard.sh after-edit`
  has the copy of s0ma already installed for the project run `s0ma check` on
  that one file, and hands Claude what it finds.

Each hook command begins with `echo --% >/dev/null;` and ends with
`# | out-null`. In `sh` that `echo` writes nothing and the end is a comment.
On Windows without Git Bash, Claude Code runs the line in PowerShell instead,
where `--%` turns the rest of the line into plain text for `echo` and
`| out-null` throws it away, so the hook runs as nothing instead of failing.

**The server**, from `.mcp.json`, is started by `scripts/s0ma-serve` on macOS
and Linux, and by `scripts/s0ma-serve.cmd` on Windows. When uv is on the
machine and already has Python 3.11 or newer, it hands over to the launcher's
`serve`. Otherwise a stand-in answers, so the server never shows as failed: on
macOS and Linux the stand-in is the end of `scripts/s0ma-serve` itself, and on
Windows it is `scripts/s0ma-stand-in.ps1`, started in Windows PowerShell with
`-NoLogo -NoProfile -NonInteractive -ExecutionPolicy Bypass -File`. The
stand-in speaks over standard input and output only, and offers one tool that
says s0ma is not set up here yet.

**The launcher**, `launcher/s0ma_launch.py`, is one Python file. Everything
above that starts it does so through `uv run --frozen`, with the lock file
beside it, `launcher/s0ma_launch.py.lock`, which lists no packages at all. The
hooks and the server also pass `--offline` and `--no-python-downloads`, so
they never fetch anything.

**Two commands in `bin/`**, `s0ma` and `s0ma-launch`, each with a `.cmd` twin
for Windows. Claude Code puts `bin/` on the path of the terminal Claude uses.
Both find uv and hand everything to the launcher: `s0ma` runs the copy of s0ma
that belongs to the project, and `s0ma-launch` is the launcher's own command
line.

**Twelve skills** in `skills/`. They are instructions for Claude, and what they
run is `s0ma-launch` and `s0ma`.

## What it fetches, and when

Nothing, until you ask. The hooks and the server open no connection, and
nothing is installed when the plugin is.

When you ask for s0ma to be installed or updated (`/s0ma:start`,
`/s0ma:setup` and `/s0ma:update` run `s0ma-launch install` or
`s0ma-launch update`):

- **With no license key**, which is the usual case, the launcher contacts
  nobody. uv fetches s0ma at the version this plugin brings, and the
  open-source packages it depends on, from the Python package index uv is set
  up to use: by default pypi.org, which serves its files from
  files.pythonhosted.org.
- **With a license key**, the launcher asks account.kn0wthyself.ai what that
  version is made of, downloads its four files from there, and checks each
  against the checksum it was given. The key travels in the request's
  authorization header and nowhere else. uv still fetches the open-source
  dependencies from the package index, and never sees the key. With a key, and
  only with one, the launcher also looks for a newer version on its own at
  most once a day, unless you set updates to off.
- **If this machine has no Python 3.11 or newer**, uv may download one, from
  wherever its own settings point. The launcher does not choose that place.

`s0ma-launch activate`, which you run yourself to save a key, asks
account.kn0wthyself.ai once whether the key is good. `s0ma-launch pin` asks it
once whether the version you named exists, unless you add `--offline` or have
no key.

`/s0ma:start` installs uv when it is missing, only after you say yes, with
uv's own installer from astral.sh:

```text
curl -LsSf https://astral.sh/uv/install.sh | sh
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
```

That installer then fetches uv from uv's makers, not from s0ma.

`/s0ma:feedback` sends one report to account.kn0wthyself.ai, and only after
you have read the exact report and approved it. It needs feedback access,
which only a keyed install gives a machine; without it nothing is sent, and
Claude points you to the issue tracker instead.

`/s0ma:studi0` starts studi0, s0ma's viewer, which serves on this machine only.
Claude checks whether one is already running at `localhost` and shows it at
`studi0.localhost`. Both names are this machine.

Nothing sends analytics, usage counts or error reports, and nothing about your
project, your files or your conversation leaves the machine.

## What it writes, and where

- **s0ma's own folder** in your home directory, `~/.s0ma` on macOS and Linux
  and `%USERPROFILE%\.s0ma` on Windows: the installed copies of s0ma, the files
  they were installed from, the launcher's settings and state, the update log,
  a key if you saved one with `s0ma-launch activate`, and feedback drafts and
  receipts. `S0MA_HOME` moves the launcher's part of it.
- **uv**, if `/s0ma:start` installed it, wherever uv's installer puts it in
  your home folder.
- **In a project**, only when you ask: a new project folder from `/s0ma:start`
  or `/s0ma:new`, the `.s0ma` sources Claude edits for you, and what s0ma's
  own build and tools write when Claude uses them. `/s0ma:off`,
  `/s0ma:on` and `/s0ma:preferences`, and your answer to studi0's offer, write
  one small file, `.s0ma/preferences.json`. While studi0 runs, it writes
  `.s0ma/studi0/active.json`.

The hooks write nothing, and neither does the stand-in server.

## Switching it off

- **For one project:** `/s0ma:off`, or say "turn s0ma off here". `/s0ma:on`
  turns it back on.
- **Everywhere:** disable the s0ma plugin in Claude Code's `/plugin` manager.

[Removing s0ma](../../../docs/uninstall.md) has the complete uninstall steps,
and [What s0ma trusts](../../../docs/trust-model.md) has every connection s0ma
can make, with the test that holds each one.

## Reporting a problem

Open an issue on the
[s0ma issue tracker](https://github.com/kn0w-thyself/s0ma/issues). Issues there
are public, so leave out anything private.

## License

Apache License 2.0. See `LICENSE`.
