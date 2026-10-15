# "You already have a codebase" — journey:retrofit-existing-codebase, from docs/s0ma_src/evidence/retrofit-existing-codebase.json.
#
# Rungs zero and one of the adoption ladder, on a real plain-Python
# application: read the whole tree without changing a byte of it, write the
# perimeter into the pyproject.toml it already had, and read back the honest
# list of what is left to convert. `ls` is a plain shell command.
#
# The application is the bookshelf lending service that the DSL suite already
# pins: packages/s0ma-dsl/tests/fixtures/brownfield/layered_app. It is copied
# out to a scratch directory first and the fixture tree is never written to,
# never run from, and never touched by uv (see that suite's NOTES.txt).
#
# The beats follow docs/_generated/media/retrofit-existing-codebase.json,
# chapters 1, 2, 4 and 5. Chapter 3 (`s0ma doctor`) is left out because its
# first line is a version number, which would date the recording.
#
# Not shown, by design: this tape is rungs zero and one only — read the tree,
# set the perimeter, read back the honest backlog. That is one sitting, and it
# is the part a person can watch and then go and do. Rung 3's loop
# (`s0ma adopt baseline`, `draft`, `verify-parity`) and `s0ma adopt status` all
# exist; they are walked a step at a time in the guide,
# `s0ma docs show doc:guide/retrofit-existing-codebase`, and as an executable
# sequence in `s0ma docs show journey:retrofit-existing-codebase`. Converting a
# module is days of work with a person authoring meaning in the middle of it,
# so a recording of it would either be dishonest about the pace or be mostly
# somebody typing prose — which is exactly what these recordings are meant not
# to do.
#
# expect-fail: 4 s0ma verify --all src
#   Exit 4 means "nothing verified": on the first day of a retrofit nothing
#   has been converted yet, so there is no transpiled module to check. The
#   screen is the honest backlog, not a failure. Every other command on screen
#   exits zero. scripts/record_demos.sh reads this line when it re-runs the
#   tape's commands to check the recording was honest.
#
# Three things this tape needs, all supplied by scripts/record_demos.sh:
#   S0MA_DEMO_BIN   the directory holding the s0ma under demonstration
#   S0MA_DEMO_ROOT  a scratch directory outside every repository
#   S0MA_DEMO_SRC   the repository root to copy the application out of
#                   (defaults to the working directory, which is why the
#                    script runs vhs from the repository root)
#   (no `Output` line, on purpose — the output paths arrive as `vhs -o`)
#
# Render:  sh scripts/record_demos.sh docs/media/tapes/retrofit.tape

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
# --- a copy of the application in a scratch directory outside every
# --- repository. The copy drops __pycache__, which is not part of the
# --- application and only changes the numbers on screen.
Hide
Type `export PS1='$ ' PAGER=cat CLICOLOR=0`
Enter
Type `SRC="${S0MA_DEMO_SRC:-$PWD}"; export PATH="$S0MA_DEMO_BIN:$PATH"`
Enter
Type `W="$S0MA_DEMO_ROOT/retrofit"; rm -rf "$W"; mkdir -p "$W"`
Enter
Type `cp -R "$SRC/packages/s0ma-dsl/tests/fixtures/brownfield/layered_app" "$W/bookshelf"`
Enter
Type `find "$W/bookshelf" -name __pycache__ -type d -exec rm -rf {} + 2>/dev/null; cd "$W/bookshelf"`
Enter
Type `clear`
Enter
Show

# --- beat 1: an ordinary Python application. No s0ma anywhere inside it.
Type `ls src/bookshelf`
Sleep 700ms
Enter
Sleep 5s

# --- beat 2: read the whole codebase without changing any of it — what is
# --- there, the perimeter it would declare, the order to convert it in, and
# --- the one command to run next.
Type `s0ma adopt scan`
Sleep 700ms
Enter
Sleep 16s

# --- beat 3: make the tree a s0ma project by declaring its perimeter, and
# --- stop there. Two things written, both quoted back; no application file
# --- is touched.
Type `s0ma adopt init`
Sleep 700ms
Enter
Sleep 9s

# --- beat 4: the honest backlog. The entry point and the package marker are
# --- recognised by the setting that exempted them; every application file is
# --- listed as UNKNOWN, which means "not converted yet", not "broken".
Type `s0ma verify --all src`
Sleep 700ms
Enter
Sleep 12s

# --- beat 5: the same facts as one number. Nought per cent for structure is
# --- correct on the first day — it is the thing the work moves.
Type `s0ma score`
Sleep 700ms
Enter
Sleep 11s

# --- teardown, not shown.
Hide
Type `cd "$S0MA_DEMO_ROOT" && rm -rf "$S0MA_DEMO_ROOT/retrofit"`
Enter
Sleep 500ms
