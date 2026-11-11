# "Ask it." A README clip: one question, one answer, about fifteen seconds.
#
# The project is the one `s0ma new project shop --template service` makes, and
# the module asked about is the one the README's first picture is drawn from.
# `s0ma inspect` answers from the project's own build record: what the module
# is for, the part inside it, and what that part leans on.
#
# The first line typed is a shell comment. It frames the question for the
# viewer and does nothing when scripts/record_demos.sh runs the commands again.
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
Set Height 640
Set Padding 20
Set Theme "Catppuccin Mocha"
Set TypingSpeed 35ms
Set Framerate 20

Hide
Type `export PS1='$ ' PAGER=cat CLICOLOR=0`
Enter
Type `export PATH="$S0MA_DEMO_BIN:$PATH"`
Enter
Type `W="$S0MA_DEMO_ROOT/ask"; rm -rf "$W"; mkdir -p "$W"; cd "$W"`
Enter
Type `s0ma new project shop --template service >/dev/null 2>&1; cd shop`
Enter
Type `clear`
Enter
Sleep 3s
Show

Type `# what is the api module, and what does it lean on?`
Sleep 400ms
Enter
Sleep 700ms

Type `s0ma inspect api_presentation`
Sleep 500ms
Enter
Sleep 9s

Hide
Type `cd "$S0MA_DEMO_ROOT" && rm -rf "$S0MA_DEMO_ROOT/ask"`
Enter
Sleep 500ms
