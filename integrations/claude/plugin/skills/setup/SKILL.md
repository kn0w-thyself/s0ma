---
name: setup
description: Get s0ma working here — check uv, install the toolchain, say where the license key goes, and finish with a health check. Use when s0ma is missing, its tools are absent, or it was just installed.
---

# Set s0ma up

Work the steps in order. Stop at the first one that fails and fix that one; the
later steps depend on it. Everything here runs in the terminal, so it still
works when the s0ma server is dead — which is the usual reason someone is
reading this.

If any command answers that it is not built yet, this is a preview build: say
exactly what it printed and stop.

## 1. Is uv on this machine?

Run `command -v uv`.

- It prints a path: go to step 2.
- It prints nothing: s0ma cannot start at all without uv, so this is the whole
  problem. Offer the one command for their platform, and **ask before running
  it** — it installs a program on their machine:
  - macOS or Linux: `curl -LsSf https://astral.sh/uv/install.sh | sh`
  - Windows: `powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"`

  The reference is <https://docs.astral.sh/uv/getting-started/installation/>.
  After it finishes, Claude has to be restarted before it can see uv.

## 2. What does s0ma think is going on?

Run `s0ma-launch status`. It reads local files only, contacts nothing, and
never prints a license key. Read its "Runs here", "Why" and "Next step" lines
back to the person in your own words.

If `s0ma-launch` is not found, the plugin's own programs are not on the path:
check that `/plugin` lists s0ma as enabled, then restart Claude.

If step 1 found uv but the s0ma server still did not start, Claude was launched
without the shell's path. Show the person the path `command -v uv` printed and
tell them to put it in the s0ma plugin's setting called **Where uv lives on
this computer**: `/config` on a build that shows the plugin's settings,
otherwise turn the s0ma plugin off and on again in `/plugin` and answer the
prompt. Never ask them to hand-edit a settings file.

## 3. Install s0ma when nothing is installed

Ask first. Say what it does: it downloads the s0ma toolchain into s0ma's own
directory in their home folder. Nothing in their project changes.

Then run `s0ma-launch install` and let its progress show. A first install takes
a few minutes on a slow connection.

## 4. Where the license key goes

Never ask anyone to type, paste or read out a license key here, and never print
one. There are exactly two right places for it:

- the s0ma plugin's **s0ma license key** field in Claude, which masks what is
  typed and stores it in the operating system's own secure storage. Claude asks
  when the plugin is enabled; to replace it, turn the plugin off and on again
  in `/plugin`.
- `s0ma-launch activate`, run by the person in their own terminal. It prompts
  without echoing and saves the answer for them. It needs a real terminal, so
  you cannot run it for them, and the plugin only puts `s0ma-launch` on the
  path of the terminal Claude uses, not on theirs. So run
  `command -v s0ma-launch` yourself, show them the full path it prints, and
  tell them to type that path followed by `activate` in a terminal of their
  own. Offer this only when the settings field is not an option for them.

It is only needed to download s0ma. Someone running s0ma from a source checkout
needs none.

## 5. Keep it current

The s0ma toolchain looks after itself: it fetches newer versions quietly and
uses them the next time a session starts. `/s0ma:update` covers checking,
updating by hand and pinning a project.

The plugin is separate, and Claude only auto-updates marketplaces that are
Anthropic's own. Tell the person how to turn it on for ours — `/plugin`,
Marketplaces, kn0wthyself, Enable auto-update — and leave them to do it.

## 6. Prove it works

Run `s0ma doctor`. Report its findings plainly, worst first, and say what each
one means for what they were trying to do. If it ends in `ok`, tell them s0ma
is ready and offer `/s0ma:new` for a new project or `/s0ma:retrofit` for code
they already have.
