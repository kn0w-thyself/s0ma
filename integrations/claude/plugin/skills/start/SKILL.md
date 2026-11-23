---
name: start
description: The quick way in. Install what is missing, ask what to build, build it and show it in studi0, in one conversation. Use when someone wants to start with s0ma, or runs /s0ma:start.
---

# Start with s0ma

This goes from nothing to a built project with studi0 open, in one
conversation. Stop for the person at most twice: once to install what is
missing, if anything is, and once to ask what to build. Everything else you
do, then say.

The sentences in quotation blocks are said word for word. In them, say "this
Mac" on macOS, "this PC" on Windows and "this computer" on Linux.

## 1. See what is missing

Ask nothing yet. Run:

```bash
s0ma-launch status
```

It reads local files only and changes nothing. What it prints decides the
next step:

- **It fails with exit code 7** and says s0ma needs a small program called uv:
  uv is missing. s0ma cannot be installed or run without it, so both are
  missing.
- **`Runs here:` is `nothing yet`** and `Why:` says s0ma is not installed on
  this machine yet: only s0ma is missing.
- **`Runs here:` names a copy of s0ma**: nothing is missing. Go straight to
  step 4.
- **Anything else**, such as a `Why:` about a pinned version or about
  `S0MA_TOOLCHAIN`, or `s0ma-launch` not found at all: this is an install to
  repair, not a first run. Say what it printed and hand over to `/s0ma:setup`.

If s0ma is installed, run `s0ma-launch prefs` too. If its last line, the one
about whether this is a s0ma project, answers "yes", the folder this session
is in is already a s0ma project: skip the rest, and build what they ask,
following `/s0ma:build`. If its first line ends "In this project: s0ma is
off.", say so, say `/s0ma:on` turns it back on, and stop.

## 2. One question for everything that is missing

With no uv and no s0ma, ask:

> Two things are missing on this Mac: uv, a small tool s0ma uses to manage its own Python, and s0ma itself. Both go in your home folder, and nothing in your projects changes. Install them?

With uv there and only s0ma missing, ask:

> One thing is missing on this Mac: s0ma itself. It goes in your home folder, and nothing in your projects changes. Install it?

One yes covers all of it: do not ask again before any step below. On a no,
stop politely, and say that `/s0ma:start` picks up again any time.

## 3. Install, on the yes

1. **uv**, if it is missing, with its own installer for the system:
   - macOS or Linux: `curl -LsSf https://astral.sh/uv/install.sh | sh`
   - Windows: `powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"`
2. **s0ma**, with `s0ma-launch install`. It needs no license key. A first
   install can take a few minutes on a slow connection; let its progress show.

There is no restart between the two. The plugin's `s0ma` and `s0ma-launch`
commands look for uv on the path and in the places uv's installers put it, so
they find it in this same session.

When both are done, say one short line, in this form, naming only what
happened (leave out "Installed uv" when uv was already there):

> Installed uv · Installing s0ma… done

If any step fails, say plainly what it printed and hand over to `/s0ma:setup`,
which holds the detailed checks. Do not try another way round.

This is for you, not for the person: s0ma's own tools in Claude arrive with the
next session. For the rest of this one, do everything through the `s0ma`
command in the terminal. There is nothing to restart for what follows, so do
not ask them to.

## 4. Ask what to build

> s0ma is ready. What do you want to build? One sentence is enough. Or say "show me" and I'll build a small sample so you can watch how it works.

When step 1 found nothing missing, begin the conversation here, and leave out
"s0ma is ready." when it was never in doubt.

## 5. Create and build, without another question

1. **Name the folder.** Pick a short, plain name from what they said, in
   lowercase words joined by hyphens, such as `tip-calculator`, and say it. It
   is created inside the folder this session is in. If a folder of that name
   is already there, pick another; never write into one that exists.
2. **Create it.** For "show me", the sample:

   ```bash
   s0ma new project tip-calculator --template pipeline
   ```

   Otherwise choose the template that fits what they described:
   `--template service`, `--template library`, `--template cli`, or no
   template for the smallest starter. The `/s0ma:new` skill says what each one
   is for. Leave the mode at its default. Then, for anything but "show me",
   author what they asked for in the new project, following `/s0ma:build`.
3. **Build it and check it**, from inside the new folder:

   ```bash
   s0ma check
   s0ma build .
   s0ma inspect --all
   ```

4. **Report in one line**, in this form, with the real numbers:

   > Created tip-calculator in this folder · Built 3 modules, 7 parts · All checks pass

   Take every part of it from what the commands printed. The modules are the
   number on the build's `Build complete:` line. The parts are the sum of the
   `Components` column `s0ma inspect --all` prints. Say "All checks pass" only
   when `s0ma check` printed "No errors." and the build's `Results:` line shows
   no errors and no warnings.

   A warning is not a failure, but it was printed, so say it: put its count and
   its code in place of "All checks pass", for example "Checks pass, with 1
   warning: HOST_RUNTIME_UNDECLARED". Do not change anything to make a warning
   go away unless the person asks. If a check did not pass, say that plainly
   instead, and what it said.

## 6. Show studi0, without asking

Start it and show it as the `/s0ma:studi0` skill says. Then say:

> It's built, and studi0 is open beside the chat. That's your app as a live map: every part and how they connect. It updates as I build.

Where there is no pane beside the chat, as in the terminal, the first sentence
is "It's built, and studi0 is running at <address>." with the address studi0
printed, and the rest is the same.

## 7. Close

> Tell me what to change, or ask how any part works. Two things you can say any time: "always use s0ma" and "always show studi0".

From here on, work in the project as `/s0ma:build` says. When they say either
of those two things, do what the `/s0ma:preferences` skill says.
