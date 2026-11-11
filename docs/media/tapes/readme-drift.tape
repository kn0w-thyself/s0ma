# "It refuses to drift." A README clip, about seventeen seconds.
#
# Somebody adds a line by hand to a file the toolchain owns. The build refuses
# rather than overwrite it, and `--force` says out loud which copy survives.
# `--quiet` keeps each answer to the error and a one-line summary, which is the
# whole point of a short clip. The longer recording of the same journey is
# drift-guardrail.tape.
#
# expect-fail: 1 s0ma build . --quiet
#   The build refusing to overwrite a hand-edited generated file. Exit 1 is the
#   designed outcome and the reason this clip exists. Every other command on
#   screen exits zero.
#
# Needs, all supplied by scripts/record_demos.sh:
#   S0MA_DEMO_BIN   the directory holding the s0ma under demonstration
#   S0MA_DEMO_ROOT  a scratch directory outside every repository
#
# Render:  sh scripts/record_demos.sh <this file>

Require bash

Set Shell "bash"
Set FontSize 18
Set Width 1100
Set Height 400
Set Padding 20
Set Theme "Catppuccin Mocha"
Set TypingSpeed 35ms
Set Framerate 20

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
Sleep 3s
Show

Type `# somebody edits a generated file by hand`
Sleep 400ms
Enter
Sleep 600ms

Type `echo '# a quick fix' >> build/core_domain.py`
Sleep 500ms
Enter
Sleep 1200ms

Type `s0ma build . --quiet`
Sleep 500ms
Enter
Sleep 7s

Type `s0ma build . --force --quiet`
Sleep 500ms
Enter
Sleep 4s

Hide
Type `cd "$S0MA_DEMO_ROOT" && rm -rf "$S0MA_DEMO_ROOT/drift"`
Enter
Sleep 500ms
