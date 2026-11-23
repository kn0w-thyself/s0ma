---
name: setup
description: Get s0ma working here — check uv, install the toolchain, say where the license key goes, and finish with a health check. Use when s0ma is missing, its tools are absent, or it was just installed.
---

# Set s0ma up

`/s0ma:start` is the quick way in: one question, then s0ma installed and a
project built. This skill is the detailed one, for checking each step and for
repairing an install.

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

If step 1 found uv but the session still began by saying s0ma is not set up
here, the plugin could not find uv when the session started. The plugin looks
on the path and in the places uv's own installers use. Installing uv the normal
way, with the command in step 1, puts it in one of those; then start a new
session. There is no setting to fill in for it.

## 3. Install s0ma when nothing is installed

Ask first. Say what it does: it downloads the s0ma toolchain into s0ma's own
directory in their home folder. With no license key on the machine, uv fetches
it from the package index it is set up to use; with one, it comes from the s0ma
service. Nothing in their project changes.

Then run `s0ma-launch install` and let its progress show. A first install takes
a few minutes on a slow connection. It works with no license key.

## 4. A license key is optional

Nobody needs a license key to install or use s0ma. A key changes where s0ma
comes from: with one, it is fetched from the s0ma service and every file is
checked against what the service says it should be; without one, uv fetches it
from the package index, at the version this plugin brings.

Never ask anyone to type, paste or read out a license key here, and never print
one. The plugin has no key setting. For someone who has a key, the right place
for it is `s0ma-launch activate`, run by the person in their own terminal. It
prompts without echoing and saves the answer for them. It needs a real
terminal, so you cannot run it for them, and the plugin only puts
`s0ma-launch` on the path of the terminal Claude uses, not on theirs. So run
`command -v s0ma-launch` yourself, show them the full path it prints, and tell
them to type that path followed by `activate` in a terminal of their own.

In Claude Desktop the s0ma extension has a license key field of its own in its
settings, which masks what is typed; that is the other right place.

Someone without a key skips this step. Someone running s0ma from a source
checkout needs none either.

## 5. Keep it current

With a license key, the s0ma toolchain looks after itself: it fetches newer
versions quietly and uses them the next time a session starts. Without one,
nothing is fetched unless someone asks: each version of the plugin brings its
own version of s0ma, and when the plugin is updated, the line a session begins
with says a newer s0ma came with it, and `/s0ma:update` installs it.
`/s0ma:update` also covers checking, updating by hand and pinning a project.

To change how s0ma keeps itself current, the person asks you, and you run
`s0ma-launch set update auto`, `s0ma-launch set update notify` or
`s0ma-launch set update off`. It is saved on this machine.

The plugin is separate, and Claude only auto-updates marketplaces that are
Anthropic's own. Tell the person how to turn it on for ours — `/plugin`,
Marketplaces, kn0wthyself, Enable auto-update — and leave them to do it.

## 6. Prove it works

Run `s0ma doctor`. Report its findings plainly, worst first, and say what each
one means for what they were trying to do. If it ends in `ok`, tell them s0ma
is ready and offer `/s0ma:new` for a new project or `/s0ma:retrofit` for code
they already have.
