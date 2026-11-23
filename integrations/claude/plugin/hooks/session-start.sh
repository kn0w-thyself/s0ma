#!/bin/sh
# session-start.sh - the line a new Claude session may begin with.
#
# Claude Code runs this from the plugin's SessionStart hook, in shell form:
# `sh` on macOS and Linux, Git Bash on Windows. What it prints on stdout goes
# into Claude's context; the person does not see it.
#
# With uv on this machine, it runs the launcher's `session-hint` and passes on
# whatever that prints. With no uv, or a uv that cannot run the launcher without
# fetching something first, it prints one plain sentence for Claude instead:
# s0ma is not set up here yet, and that is expected.
#
# Three rules, none of them negotiable:
#
# * It always exits 0 and never writes to stderr. A hook that fails, or that
#   writes to stderr, puts a hook error in front of somebody who opened Claude
#   to do something else.
# * It never installs anything, never downloads anything, and opens no
#   connection: uv is run offline, with Python downloads switched off.
# * When the project's own .s0ma/preferences.json says s0ma is off here, it
#   says nothing at all on its own account. With uv, the launcher says the one
#   off line for Claude; without uv there is nothing to say.
# * What it says when s0ma is not set up is written once, in
#   scripts/not-set-up.txt, which the stand-in server reads too. That is the
#   one place this side names the setup skill; the launcher names it once as
#   SETUP_SKILL, and a test holds the two to the same name.
#
# POSIX sh only - no bashisms, nothing that assumes a particular shell.

# Nothing this script runs may reach stderr, whatever goes wrong.
exec 2>/dev/null

# The launcher and the message sit beside this file's folder. $0 is the path
# Claude Code gave sh, so the folder is everything before its last slash.
case $0 in
    */*) hooks_dir=${0%/*} ;;
    *) hooks_dir=. ;;
esac
launcher=$hooks_dir/../launcher/s0ma_launch.py

# One line of plain text. `read` reports the end of a file with no newline as a
# failure, so its status is not what decides anything here.
not_set_up=
if [ -r "$hooks_dir/../scripts/not-set-up.txt" ]; then
    IFS= read -r not_set_up < "$hooks_dir/../scripts/not-set-up.txt"
fi

# The project folder is the one the launcher reads: CLAUDE_PROJECT_DIR when
# Claude set it, otherwise the working directory. The project's own file says
# s0ma is off with "s0ma": "off"; anything else, or no file, means on.
project=${CLAUDE_PROJECT_DIR:-}
if [ -z "$project" ]; then
    project=$(pwd)
fi
preferences=$project/.s0ma/preferences.json

s0ma_is_off_here() {
    [ -r "$preferences" ] &&
        grep -q '"s0ma"[[:space:]]*:[[:space:]]*"off"' "$preferences"
}

say_not_set_up() {
    if s0ma_is_off_here; then
        exit 0
    fi
    if [ -n "$not_set_up" ]; then
        printf '%s\n' "$not_set_up"
    fi
    exit 0
}

# Find uv the way the launcher does: whatever the PATH offers first, then the
# places uv's own installers put it. The list between the two markers is the
# launcher's uv_candidates, POSIX places first and then the Windows ones that
# Git Bash can see; a test fails if the two drift apart.
uv=
if command -v uv >/dev/null 2>&1; then
    uv=$(command -v uv)
else
    # BEGIN uv places
    for candidate in \
        "${HOME:-/nonexistent}/.local/bin/uv" \
        "${HOME:-/nonexistent}/.cargo/bin/uv" \
        /opt/homebrew/bin/uv \
        /usr/local/bin/uv \
        "${USERPROFILE:-/nonexistent}/.local/bin/uv.exe" \
        "${LOCALAPPDATA:-/nonexistent}/uv/bin/uv.exe" \
        "${USERPROFILE:-/nonexistent}/.cargo/bin/uv.exe" \
        "${ProgramFiles:-/nonexistent}/uv/uv.exe"
    do
        if [ -x "$candidate" ]; then
            uv=$candidate
            break
        fi
    done
    # END uv places
fi

if [ -z "$uv" ]; then
    say_not_set_up
fi

# --frozen: use the lock file beside the launcher as it is, resolving nothing.
# --offline and --no-python-downloads: if running the launcher would need
# anything from the network, uv refuses instead of fetching it.
if hint=$("$uv" run --frozen --offline --no-python-downloads --quiet --script "$launcher" session-hint); then
    if [ -n "$hint" ]; then
        printf '%s\n' "$hint"
    fi
    exit 0
fi

say_not_set_up
