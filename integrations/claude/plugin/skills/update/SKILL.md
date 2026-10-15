---
name: update
description: Check for a newer s0ma, move to it, or hold a project on the version it has. Use when someone asks about updating s0ma, pinning a version, or why a build suddenly changed.
---

# Update s0ma, or hold it still

s0ma normally updates itself: it starts the version that is installed, fetches
a newer one quietly in the background, and uses it the next time a session
starts. Nothing ever changes underneath a session in progress. The plugin's
**How s0ma keeps itself current** setting decides that — `auto` is the default,
`notify` only says when something is waiting, `off` never looks. This skill is
for the times someone wants to do it deliberately.

If any command answers that it is not built yet, this is a preview build: say
exactly what it printed and stop.

## 1. Find out what runs here

```bash
s0ma-launch status
```

Read the "Runs here" and "Why" lines back. They decide everything below:

- **a managed copy of s0ma** — steps 2 and 3 apply.
- **the project's own copy** — go to step 5.
- **nothing yet** — run `/s0ma:setup` instead; there is nothing to update.

## 2. Is there anything newer?

```bash
s0ma-launch update --check
```

This asks the s0ma service once and reports the answer. It installs nothing
and changes nothing about which version runs; the only thing it writes is
its own note of what it was told, which `s0ma-launch status` reads back.

## 3. Move to it — after asking

Say what will happen before you run it: the newer version is installed beside
the one in use, the previous version is kept so it can be gone back to, and the
change takes effect the next time a Claude session starts. Wait for a yes.

```bash
s0ma-launch update
```

## 4. Pinning

`s0ma-launch pin <version>` writes a small `.s0ma-version` file in the project,
and a pinned project is never moved automatically by anything.
`s0ma-launch unpin` removes that file and hands the project back to the normal
behaviour.

Pin when a project's generated output has to stay byte-for-byte stable — a
toolchain that moves can legitimately change generated files, and a pin is how
a team decides when to take that diff.

## 5. A project that carries its own s0ma

Some projects — every one installed with the keyed installer — have the
toolchain inside their own environment. Those are pinned by construction: s0ma
will not move them, and `s0ma-launch update` does not touch them. To move one,
the project's own dependency has to be updated, in the project, by whoever owns
it. Say that plainly rather than updating anything.

## 6. The plugin itself is a separate thing

Updating the toolchain does not update this plugin, and updating this plugin
does not update the toolchain. The plugin is Claude's to manage, and Claude
only auto-updates Anthropic's own marketplaces. These are for the person to
type, not for you to run: `/plugin update s0ma@kn0wthyself` for a one-off, or
`/plugin`, Marketplaces, kn0wthyself, Enable auto-update to stop thinking about
it.
