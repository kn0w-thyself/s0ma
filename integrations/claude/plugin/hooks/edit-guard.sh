#!/bin/sh
# edit-guard.sh - what Claude is told around an edit in a s0ma project.
#
# Claude Code runs this from two of the plugin's hooks, in shell form: `sh` on
# macOS and Linux, Git Bash on Windows. The one argument says which, and the
# hook's JSON arrives on stdin:
#
# * before-edit, from PreToolUse on Write and Edit. An edit to a file under a
#   s0ma project's build folder is refused, with a reason that tells Claude to
#   change the .s0ma source instead.
# * after-edit, from PostToolUse on Write and Edit to a .s0ma file. s0ma checks
#   that file, and Claude is handed whatever the check reports.
#
# The PreToolUse hook runs before every Write and Edit while the plugin is on,
# in every project, so this script does the cheap part itself and stops, saying
# nothing, as soon as it can tell there is nothing to say:
#
# * after-edit: the edited file's name does not end in .s0ma;
# * before-edit: the nearest pyproject.toml at or above the file's folder does
#   not mention s0ma, or there is none, so the file is in no s0ma project;
# * either: there is no uv on this machine, so s0ma is not set up here and the
#   launcher cannot run.
#
# Everything it is not sure of goes to the launcher's before-edit or
# after-edit command, with the same input, and whatever that prints is passed
# through: a path it cannot read plainly from the JSON, a relative path, a
# pyproject.toml that mentions s0ma. The launcher reads the project for real.
#
# Four rules, none of them negotiable:
#
# * It always exits 0 and never writes to stderr. A hook that fails, or that
#   writes to stderr, puts a hook error in front of somebody who opened Claude
#   to do something else.
# * It never installs anything, never downloads anything, and opens no
#   connection: uv is run offline, with Python downloads switched off.
# * When the project's own .s0ma/preferences.json says s0ma is off here, it
#   says nothing at all. The launcher reads that file; without uv there is
#   nothing to say.
# * When s0ma is not set up, it says nothing either. The session-start hook is
#   the one that says so, once, at the start of a session.
#
# POSIX sh only - no bashisms, nothing that assumes a particular shell.

# Nothing this script runs may reach stderr, whatever goes wrong.
exec 2>/dev/null

# The launcher sits beside this file's folder. $0 is the path Claude Code gave
# sh, so the folder is everything before its last slash.
case $0 in
    */*) hooks_dir=${0%/*} ;;
    *) hooks_dir=. ;;
esac
launcher=$hooks_dir/../launcher/s0ma_launch.py

event=${1:-}
case $event in
    before-edit | after-edit) ;;
    *) exit 0 ;;
esac

input=$(cat)

# ---------------------------------------------------------------------------
# The file's path, read from the JSON only when that is plain.
#
# `file` is the path when the input names "file_path" once, as a plain string.
# `sure` is "no" when the input holds something this script will not read for
# certain - a second "file_path", whitespace it does not expect, an escape
# other than a doubled backslash - and then the launcher reads it instead.
# ---------------------------------------------------------------------------

key='"file_path"'
newline='
'
file=
sure=yes

case $input in
    *"$key"*) ;;
    # No path at all: nothing was edited that either hook has a word for.
    *) exit 0 ;;
esac
rest=${input#*"$key"}
case $rest in
    *"$key"*) sure=no ;;
esac

skip_blanks() {
    while :; do
        case $rest in
            [" 	$newline"]*) rest=${rest#?} ;;
            *) break ;;
        esac
    done
}

if [ "$sure" = yes ]; then
    skip_blanks
    case $rest in
        :*) rest=${rest#:} ;;
        *) sure=no ;;
    esac
fi
if [ "$sure" = yes ]; then
    skip_blanks
    case $rest in
        '"'*) rest=${rest#'"'} ;;
        *) sure=no ;;
    esac
fi
if [ "$sure" = yes ]; then
    case $rest in
        *'"'*) file=${rest%%'"'*} ;;
        *) sure=no ;;
    esac
fi

# A doubled backslash is one backslash, which is how a Windows path arrives:
# C:\\Users\\... becomes C:/Users/..., which Git Bash reads as the same path.
# A backslash left over after that starts some other escape, and then the
# launcher reads the path.
if [ "$sure" = yes ]; then
    case $file in
        *'\'*)
            plain=
            left=$file
            while :; do
                case $left in
                    *'\\'*)
                        plain=$plain${left%%'\\'*}/
                        left=${left#*'\\'}
                        ;;
                    *)
                        plain=$plain$left
                        break
                        ;;
                esac
            done
            case $plain in
                *'\'*) sure=no ;;
                *) file=$plain ;;
            esac
            ;;
    esac
fi
if [ "$sure" = yes ] && [ -z "$file" ]; then
    exit 0
fi

# ---------------------------------------------------------------------------
# The cheap answers.
# ---------------------------------------------------------------------------

# Whether the file at $1 mentions s0ma anywhere. A [tool.s0ma] table cannot be
# written without the word, so a file that lacks it holds none.
mentions_s0ma() {
    [ -r "$1" ] || return 0
    while IFS= read -r line || [ -n "$line" ]; do
        case $line in
            *s0ma*) return 0 ;;
        esac
    done < "$1"
    return 1
}

# Whether the folder $1, or one above it, may be a s0ma project. The nearest
# pyproject.toml decides, as it does for the launcher.
may_be_in_a_project() {
    dir=$1
    while :; do
        if [ -f "$dir/pyproject.toml" ]; then
            mentions_s0ma "$dir/pyproject.toml"
            return $?
        fi
        case $dir in
            */*) dir=${dir%/*} ;;
            *) return 1 ;;
        esac
    done
}

if [ "$sure" = yes ]; then
    case $event in
        after-edit)
            case $file in
                *.s0ma) ;;
                *) exit 0 ;;
            esac
            ;;
        before-edit)
            # Only an absolute path with no . or .. in it is walked here; the
            # launcher reads any other.
            case $file in
                */./* | */../* | */. | */..) sure=no ;;
                /* | [A-Za-z]:/*) ;;
                *) sure=no ;;
            esac
            if [ "$sure" = yes ] && [ ! -d "$file" ]; then
                if ! may_be_in_a_project "${file%/*}"; then
                    exit 0
                fi
            fi
            ;;
    esac
fi

# ---------------------------------------------------------------------------
# The rest is the launcher's.
# ---------------------------------------------------------------------------

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
    exit 0
fi

# --frozen: use the lock file beside the launcher as it is, resolving nothing.
# --offline and --no-python-downloads: if running the launcher would need
# anything from the network, uv refuses instead of fetching it. The launcher's
# answer, or its silence, goes straight to Claude Code.
printf '%s\n' "$input" |
    "$uv" run --frozen --offline --no-python-downloads --quiet --script "$launcher" "$event"
exit 0
