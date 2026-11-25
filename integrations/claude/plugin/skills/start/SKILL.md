---
name: start
description: The quick way in. Install what is missing, ask what to build, build it and show it in studi0, in one conversation. Use when someone wants to start with s0ma, or runs /s0ma:start.
---

# Start with s0ma

This goes from nothing to a built project with studi0 open, in one
conversation. Stop for the person at most twice: once to install what is
missing, if anything is, and once to ask what to build. Everything else you
do, then say. The "show me" walk at the end also waits for them between its
steps.

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

For "show me", follow "Show me, one step at a time" at the end of this skill
instead of steps 5 to 7.

## 5. Create and build, without another question

1. **Name the folder.** Pick a short, plain name from what they said, in
   lowercase words joined by hyphens, such as `recipe-box`, and say it. It
   is created inside the folder this session is in. If a folder of that name
   is already there, pick another; never write into one that exists.
2. **Create it.** Choose the template that fits what they described:
   `--template service`, `--template library`, `--template cli`, or no
   template for the smallest starter. The `/s0ma:new` skill says what each one
   is for. Leave the mode at its default. Then author what they asked for in
   the new project, following `/s0ma:build`.
3. **Build it and check it**, from inside the new folder:

   ```bash
   s0ma check
   s0ma build .
   s0ma inspect --all
   ```

4. **Report in one line**, in this form, with the real numbers:

   > Created recipe-box in this folder · Built 3 modules, 7 parts · All checks pass

   Take every part of it from what the commands printed. The modules are the
   number on the build's `Build complete:` line. The parts are the sum of the
   `Components` column `s0ma inspect --all` prints. Say "All checks pass" only
   when `s0ma check` printed "No errors." and the build printed no error and no
   warning. A build that has either prints a `Results:` line with the counts; a
   clean build prints none.

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

## Show me, one step at a time

For "show me", build s0ma's own sample one step at a time while studi0 shows
each step land, and let the person set the pace. Everything you say about the
sample comes from what s0ma prints, never from what you expect it to be. Run
each `s0ma new project` command below from the folder this session is in, and
read its JSON.

If a command fails or refuses, which it does with an exit code other than 0 or
with `"ok": false` and an `error` in its JSON, say plainly what it printed and
stop the walk there. The one exception is a sample that is already in this
folder, in step 2.

1. **Say what s0ma is.**

   > s0ma does two things. It keeps what you want from your software, its intent, requirements, and guidelines, inside the code itself, next to the part each one belongs to. And it makes that available to AI models like me, so I work from a live, accurate picture of your system instead of guessing.

2. **Lay down the bare project.**

   ```bash
   s0ma new project --sample --step 0 --format json
   ```

   It makes the sample's folder inside this one, with nothing built yet. Keep
   from its JSON: `project_root`, the folder every later command names;
   `called`, `noun` and `example_question`, which say what the sample is; and
   `step.of`, how many steps there are.

   **If the sample is already here.** When the folder is there from an earlier
   walk and past step 0, this command refuses, and its JSON carries
   `project_root`, `at_step` and `of`. That refusal does not stop the walk.
   Say this, with `at_step` in place of `{K}` and `of` in place of `{M}`:

   > The sample is already in this folder, at step {K} of {M}. I'll pick up from there.

   Then run step 5's command with `at_step` as `<n>` on that `project_root`.
   It changes nothing, and its JSON carries everything the walk keeps. Show
   studi0 on it as in step 3, and say nothing from step 4. If that step is the
   last, go straight to step 6. Otherwise say its `line` with the "next" and
   "finish" sentence from step 5, and wait for the person. A refusal with no
   `at_step` is not this case: say what it printed and stop.

3. **Show studi0 on that folder**, as the `/s0ma:studi0` skill says, with
   `project_root` as the project folder. If studi0 is already open on that
   folder, do not open it again. Its page says nothing is built yet. That is
   right for now, so do not build the project to fill it. Before step 1,
   studi0 also prints "warning: Declared bootstrap_file does not exist on
   disk". That is expected, because that file comes with step 1, so do not
   repeat it to the person and do not act on it.

4. **Say what comes next**, with the JSON's `called` in place of `{called}`:

   > I'll build {called} one step at a time so you can watch. studi0 is open beside the chat. It's empty for now, and each step will appear there as I build it.

   Where there is no pane beside the chat, as in the terminal, the middle
   sentence is "studi0 is running at <address>." with the address studi0
   printed, and the rest is the same.

5. **Lay down step 1**, with `<folder>` the `project_root` and `<n>` the
   step's number:

   ```bash
   s0ma new project <folder> --sample --step <n> --format json
   ```

   It adds that step's files and builds them, and studi0 repaints. The last
   step is the one whose JSON says `"finished": true`. After each step but the
   last, say this, with the JSON's `line` in place of `{line}`:

   > {line} Say "next" to go on, or "finish" and I'll build the rest.

   Then stop and wait for the person.

   - **"next", "go on", "continue", or a plain yes**: lay down the next step
     the same way.
   - **"finish", "build the rest", or "all of it"**: lay down the last step,
     number `step.of`, in one command. It builds every step left.
   - **Anything else**: answer it from what is built so far, the way step 8
     says, then say again how to go on.

6. **Check it**, from `project_root`, after the last step:

   ```bash
   s0ma check
   s0ma build .
   s0ma inspect --all
   ```

   The rule in step 5 of this skill holds here too: say "all checks pass" only
   when `s0ma check` printed "No errors." and the build printed no error and
   no warning. A warning goes in its place, with its count and its code, such
   as "checks pass, with 1 warning: HOST_RUNTIME_UNDECLARED". If a check did
   not pass, say that plainly, and what it said, and stop the walk there.

7. **Say what was built**: the last step's `line`, then this, with the JSON's
   `noun` in place of `{noun}`, its `step.of` in place of `{M}`, the parts in
   place of `{N}`, and its `example_question` in place of
   `{example_question}`:

   > That's the whole {noun}: {M} steps, {N} parts, all checks pass. Now the part s0ma is for. Ask me anything about it, for example "{example_question}" I'll answer from the {noun}'s own model, not by guessing from its code.

   The parts are the sum of the `Components` column `s0ma inspect --all`
   printed, which is also the last step's `parts`.

8. **Answer from the project's own model.** Read the answer from what the
   project declares about itself: each part's intent, what it expects,
   guarantees and forbids, and how the parts connect. Do not read the `.s0ma`
   sources, the `build/` folder or `bootstrap/` to answer, and do not guess
   from names. When s0ma's own tools are in this session, use
   `project_status`, then `inspect_module` for each module the question
   touches. In the session that installed s0ma they are not there, so run,
   from `project_root`, `s0ma inspect --all` to list the modules, then
   `s0ma inspect <module> --format json` for each module the question
   touches. Say which part each fact comes from. If the model does not say,
   say that it does not.

9. **Close.**

   > Tell me what to change, or ask how any part works. Or tell me what you want to build. Two things you can say any time: "always use s0ma" and "always show studi0".

   From here on, work in the project as `/s0ma:build` says. When they say
   either of those two things, do what the `/s0ma:preferences` skill says.
