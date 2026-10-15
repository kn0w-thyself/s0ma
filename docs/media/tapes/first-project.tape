# "From nothing to a checked project" — journey:first-project, from docs/s0ma_src/evidence/first-project.json.
#
# Every command on screen is one the gate already replays. `s0ma new project`,
# `s0ma check` and `s0ma build` come from first-project.json (the scaffold argv
# and steps 0 and 6); `s0ma verify` and `s0ma score` come from
# retrofit-existing-codebase.json (steps 2 and 3). `cat` is a plain shell
# command and shows the reader what the language looks like.
#
# The beats follow docs/_generated/media/first-project.json: make a project,
# read what came with it, ask whether it holds together, build what was
# checked, ask whether the build still matches its source, and read the one
# number that says how much the project knows about itself.
#
# Three things this tape needs, all supplied by scripts/record_demos.sh:
#   S0MA_DEMO_BIN   the directory holding the s0ma under demonstration
#   S0MA_DEMO_ROOT  a scratch directory outside every repository
#   (no `Output` line, on purpose — the output paths arrive as `vhs -o`, so a
#    tape can never write a binary into the repository)
#
# Render:  sh scripts/record_demos.sh docs/media/tapes/first-project.tape

Require bash

Set Shell "bash"
Set FontSize 16
Set Width 1210
Set Height 940
Set Padding 20
Set Theme "Catppuccin Mocha"
Set TypingSpeed 45ms
Set Framerate 24

# --- setup, not shown: a clean prompt, the s0ma under test first on PATH, and
# --- a fresh empty directory outside every repository to work in.
Hide
Type `export PS1='$ ' PAGER=cat CLICOLOR=0`
Enter
Type `export PATH="$S0MA_DEMO_BIN:$PATH"`
Enter
Type `W="$S0MA_DEMO_ROOT/first-project"; rm -rf "$W"; mkdir -p "$W"; cd "$W"`
Enter
Type `clear`
Enter
Show

# --- beat 1: an empty folder becomes a project, and the first build has
# --- already run by the time the command returns.
Type `s0ma new project demo --name demo`
Sleep 700ms
Enter
Sleep 7s

Type `cd demo`
Sleep 400ms
Enter
Sleep 1s

# --- beat 2: what the language actually looks like. The starter module says
# --- what it is for, what it promises, and then the plain Python underneath.
Type `cat src/core/core_domain.s0ma`
Sleep 700ms
Enter
Sleep 11s

# --- beat 3: ask whether what is in the project holds together, before
# --- anything is built from it.
Type `s0ma check`
Sleep 700ms
Enter
Sleep 5s

# --- beat 4: turn the checked source into ordinary Python, next to the record
# --- of what the project contains.
Type `s0ma build src`
Sleep 700ms
Enter
Sleep 8s

# --- beat 5: ask whether every built file still matches the source it came
# --- from. This is the same question the guardrail asks on every build.
Type `s0ma verify build`
Sleep 700ms
Enter
Sleep 7s

# --- beat 6: the same facts as one number, which is the thing that moves as a
# --- project grows.
Type `s0ma score`
Sleep 700ms
Enter
Sleep 12s

# --- teardown, not shown.
Hide
Type `cd "$S0MA_DEMO_ROOT" && rm -rf "$S0MA_DEMO_ROOT/first-project"`
Enter
Sleep 500ms
