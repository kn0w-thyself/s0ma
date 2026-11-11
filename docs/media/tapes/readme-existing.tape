# "You already have a codebase." A README clip, about thirteen seconds.
#
# `s0ma adopt scan` reads a plain Python application and writes nothing. The
# application is the bookshelf lending service the DSL suite pins at
# packages/s0ma-dsl/tests/fixtures/brownfield/layered_app, copied out first so
# the fixture is never touched. `head -22` is a plain shell command: it keeps
# the clip to the count, the perimeter and the order to convert in, which is
# one screen. The longer recording of the same journey is retrofit.tape.
#
# Needs, all supplied by scripts/record_demos.sh:
#   S0MA_DEMO_BIN   the directory holding the s0ma under demonstration
#   S0MA_DEMO_ROOT  a scratch directory outside every repository
#   S0MA_DEMO_SRC   the repository root to copy the application out of
#
# Render:  sh scripts/record_demos.sh <this file>

Require bash

Set Shell "bash"
Set FontSize 18
Set Width 1100
Set Height 640
Set Padding 20
Set Theme "Catppuccin Mocha"
Set TypingSpeed 35ms
Set Framerate 20

Hide
Type `export PS1='$ ' PAGER=cat CLICOLOR=0`
Enter
Type `SRC="${S0MA_DEMO_SRC:-$PWD}"; export PATH="$S0MA_DEMO_BIN:$PATH"`
Enter
Type `W="$S0MA_DEMO_ROOT/existing"; rm -rf "$W"; mkdir -p "$W"`
Enter
Type `cp -R "$SRC/packages/s0ma-dsl/tests/fixtures/brownfield/layered_app" "$W/bookshelf"`
Enter
Type `find "$W/bookshelf" -name __pycache__ -type d -exec rm -rf {} + 2>/dev/null; cd "$W/bookshelf"`
Enter
Type `clear`
Enter
Sleep 2s
Show

Type `# an ordinary Python app, with no s0ma in it yet`
Sleep 400ms
Enter
Sleep 600ms

Type `s0ma adopt scan | head -22`
Sleep 500ms
Enter
Sleep 10s

Hide
Type `cd "$S0MA_DEMO_ROOT" && rm -rf "$S0MA_DEMO_ROOT/existing"`
Enter
Sleep 500ms
