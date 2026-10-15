# "The guardrail catches drift" — journey:drift-recovery, from docs/s0ma_src/evidence/drift-recovery.json.
#
# Steps 0 to 4 of that evidence record, in order: a clean check, a line added
# by hand to a file the toolchain owns, the check that notices it, the build
# that refuses rather than overwrite it, and the rebuild that says out loud
# which of the two copies survives. `echo` and `tail` are plain shell commands
# and show the reader that the hand-written line is really there, and really
# gone afterwards.
#
# The beats follow docs/_generated/media/drift-recovery.json, chapters 1 to 3.
#
# The refusal is the point of this recording, so it is held long enough to
# read the finding and the remediation under it.
#
# expect-fail: 1 s0ma build .
#   The build refusing to clobber a hand-edited generated file. Exit 1 is the
#   correct, designed outcome and the whole reason this tape exists; every
#   other command on screen exits zero. scripts/record_demos.sh reads this
#   line when it re-runs the tape's commands to check the recording was honest.
#
# Three things this tape needs, all supplied by scripts/record_demos.sh:
#   S0MA_DEMO_BIN   the directory holding the s0ma under demonstration
#   S0MA_DEMO_ROOT  a scratch directory outside every repository
#   (no `Output` line, on purpose — the output paths arrive as `vhs -o`)
#
# Render:  sh scripts/record_demos.sh docs/media/tapes/drift-guardrail.tape

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
# --- the project this journey starts from, already made and already built.
Hide
Type `export PS1='$ ' PAGER=cat CLICOLOR=0`
Enter
Type `export PATH="$S0MA_DEMO_BIN:$PATH"`
Enter
Type `W="$S0MA_DEMO_ROOT/drift"; rm -rf "$W"; mkdir -p "$W"; cd "$W"`
Enter
Type `s0ma new project demo --name demo >/dev/null 2>&1; cd demo`
Enter
Type `clear`
Enter
Show

# --- beat 1: a clean run, so that everything after this is measured against
# --- a project that was in order a moment ago.
Type `s0ma check`
Sleep 700ms
Enter
Sleep 5s

# --- beat 2: somebody adds a line by hand to a file under build/, which is a
# --- folder the toolchain writes and owns.
Type `echo '# a note somebody added by hand' >> build/core_domain.py`
Sleep 700ms
Enter
Sleep 2s

Type `tail -4 build/core_domain.py`
Sleep 700ms
Enter
Sleep 6s

# --- beat 3: the check notices, and says it as a warning.
Type `s0ma check`
Sleep 700ms
Enter
Sleep 9s

# --- beat 4: the refusal. The build stops, names the file and the failure,
# --- and writes nothing — so the hand-written line is still there to read.
Type `s0ma build .`
Sleep 700ms
Enter
Sleep 14s

# --- beat 5: the recovery this journey teaches — say out loud which of the
# --- two copies survives, and rebuild from the written source.
Type `s0ma build . --force`
Sleep 700ms
Enter
Sleep 8s

# --- beat 6: the file is back to what the source says it should be, and the
# --- hand-written line is gone, as asked.
Type `tail -4 build/core_domain.py`
Sleep 700ms
Enter
Sleep 8s

# --- teardown, not shown.
Hide
Type `cd "$S0MA_DEMO_ROOT" && rm -rf "$S0MA_DEMO_ROOT/drift"`
Enter
Sleep 500ms
