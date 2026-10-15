#!/bin/sh
# s0ma: the demo recordings, rendered and then checked for honesty.
#
# Three scripted terminal recordings live in docs/media/tapes/. Each one is
# built only from commands the documentation evidence already replays on every
# gate run, so nothing on screen is a command that has never been proved to
# work. This script does two things, in order:
#
#   1. Renders each tape with vhs (which drives a real terminal through ttyd
#      and encodes the frames with ffmpeg) into a directory OUTSIDE this
#      repository. No recording is ever committed.
#
#   2. Checks that each recording was honest. It reads the same tape back,
#      pulls out every command the tape types, runs them again
#      non-interactively in a fresh scratch directory, and asserts that each
#      one exits zero — except the ones the tape itself declares as an
#      expected refusal with an `# expect-fail: <code> <command>` line. The
#      drift tape has one: its whole point is a build that refuses. If a
#      command that exits zero on screen exits non-zero here, or the other way
#      round, the recording lied and this script fails.
#
# What appears on screen. The recordings show the demonstration projects being
# made and built, and s0ma prints the resolved path of a project it builds. So
# the scratch directory those projects live in is deliberately short and says
# nothing about the machine it was recorded on: /tmp/s0ma-demo by default.
# Change it with --demo-root if you must, but keep it short, keep it outside
# every repository, and keep your user name out of it.
#
# What this never touches: this repository (the renders go to --out, which is
# refused if it sits inside any git repository), the brownfield fixture the
# retrofit tape uses (it is copied out first and the copy is what gets
# written), and any network host (nothing here addresses anything off this
# machine).
#
# POSIX sh on purpose - no bashisms - though it runs the replay under bash,
# because that is the shell the tapes declare.
#
# Usage:  sh scripts/record_demos.sh [--out DIR] [--demo-root DIR] [--webm] [tape...]
#
#   --out DIR         where the .gif and .mp4 files go. Default: a fresh
#                     temporary directory, printed when the run starts.
#                     Refused if it is inside a git repository.
#   --demo-root DIR   the scratch directory the demonstration projects are
#                     made in. This path APPEARS IN THE RECORDING.
#                     Default: /tmp/s0ma-demo
#   --webm            also encode .webm. Off by default: VP9 is not free, and
#                     roughly doubles how long a render takes.
#   tape...           tapes to render. Default: all of docs/media/tapes/*.tape

set -eu

ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
INVOKED_FROM=$PWD
TAPE_DIR="docs/media/tapes"
MAX_SECONDS=90

OUT=""
DEMO_ROOT="/tmp/s0ma-demo"
WANT_WEBM=no
TAPES=""

# ---------------------------------------------------------------------------
# Arguments.
# ---------------------------------------------------------------------------

while [ $# -gt 0 ]; do
    case $1 in
        --out)
            [ $# -ge 2 ] || { printf 'error: --out needs a directory.\n' >&2; exit 2; }
            OUT=$2
            shift 2
            ;;
        --demo-root)
            [ $# -ge 2 ] || { printf 'error: --demo-root needs a directory.\n' >&2; exit 2; }
            DEMO_ROOT=$2
            shift 2
            ;;
        --webm)
            WANT_WEBM=yes
            shift
            ;;
        -h|--help)
            printf 'Usage: sh scripts/record_demos.sh [--out DIR] [--demo-root DIR] [--webm] [tape...]\n\n'
            printf '  --out DIR         where the .gif and .mp4 go. Default: a fresh temporary\n'
            printf '                    directory. Refused if it is inside a git repository.\n'
            printf '  --demo-root DIR   scratch directory the demonstration projects are made\n'
            printf '                    in. THIS PATH APPEARS IN THE RECORDING, so keep it\n'
            printf '                    short and keep your user name out of it.\n'
            printf '                    Default: /tmp/s0ma-demo\n'
            printf '  --webm            also encode .webm. Off by default: VP9 is not free.\n'
            printf '  tape...           tapes to render. Default: docs/media/tapes/*.tape\n'
            exit 0
            ;;
        -*)
            printf 'error: unknown option "%s".\n' "$1" >&2
            exit 2
            ;;
        *)
            TAPES="$TAPES $1"
            shift
            ;;
    esac
done

# ---------------------------------------------------------------------------
# The tools this needs, and what to do when one is missing.
# ---------------------------------------------------------------------------

MISSING=""
for tool in vhs ttyd ffmpeg ffprobe bash; do
    command -v "$tool" >/dev/null 2>&1 || MISSING="$MISSING $tool"
done
if [ -n "$MISSING" ]; then
    printf 'Cannot record: missing%s.\n\n' "$MISSING" >&2
    printf 'vhs drives a real terminal to script the recording, ttyd is the\n' >&2
    printf 'terminal it drives, and ffmpeg (with ffprobe) turns the frames into\n' >&2
    printf 'a .gif and an .mp4. All three are needed; none of them is optional.\n\n' >&2
    printf '  macOS:          brew install vhs ttyd ffmpeg\n' >&2
    printf '  Linux (Debian): apt install ffmpeg, then install vhs and ttyd from\n' >&2
    printf '                  their own releases (github.com/charmbracelet/vhs,\n' >&2
    printf '                  github.com/tsl0922/ttyd)\n\n' >&2
    printf 'Then run this again.\n' >&2
    exit 2
fi

# ---------------------------------------------------------------------------
# Where the renders go. Never inside a repository: a recording is a binary,
# and binaries do not belong in this tree.
# ---------------------------------------------------------------------------

to_abs() {
    case $1 in
        /*) printf '%s\n' "$1" ;;
        *)  printf '%s/%s\n' "$INVOKED_FROM" "$1" ;;
    esac
}

# The nearest ancestor of $1 that exists, as a real path.
nearest_existing() {
    d=$1
    while [ ! -d "$d" ] && [ -n "$d" ] && [ "$d" != "/" ]; do
        d=$(dirname "$d")
    done
    (CDPATH= cd -- "$d" && pwd)
}

# Zero if $1, or anything above it, is a git working tree or a bare repository.
# A worktree's .git is a file and not a directory, so -e and not -d.
inside_git_repo() {
    d=$(nearest_existing "$1")
    while [ -n "$d" ] && [ "$d" != "/" ]; do
        if [ -e "$d/.git" ]; then
            return 0
        fi
        if [ -f "$d/HEAD" ] && [ -d "$d/objects" ] && [ -d "$d/refs" ]; then
            return 0
        fi
        d=$(dirname "$d")
    done
    [ -e "/.git" ]
}

refuse_if_in_repo() {
    if inside_git_repo "$1"; then
        printf 'Refusing to use "%s": it is inside a git repository.\n' "$2" >&2
        printf 'Recordings are binaries and none of them belongs in a tree that is\n' >&2
        printf 'under version control. Point %s somewhere outside one.\n' "$3" >&2
        exit 2
    fi
}

if [ -z "$OUT" ]; then
    OUT=$(mktemp -d 2>/dev/null || mktemp -d -t s0ma-demos)
else
    OUT=$(to_abs "$OUT")
fi
refuse_if_in_repo "$OUT" "$OUT" "--out"
mkdir -p "$OUT"
OUT=$(CDPATH= cd -- "$OUT" && pwd)

DEMO_ROOT=$(to_abs "$DEMO_ROOT")
refuse_if_in_repo "$DEMO_ROOT" "$DEMO_ROOT" "--demo-root"
mkdir -p "$DEMO_ROOT"
# Resolved, because s0ma prints the resolved path of a project it builds, and
# the banner below should say the same thing the recording will show.
DEMO_ROOT=$(CDPATH= cd -- "$DEMO_ROOT" && pwd)
case $DEMO_ROOT in
    *[[:space:]]*)
        printf 'Refusing to use "%s" as the demonstration root: it has\n' "$DEMO_ROOT" >&2
        printf 'whitespace in it, and the tapes pass this path through a shell.\n' >&2
        exit 2
        ;;
esac

# The recordings must show a s0ma, and the only one this repository can vouch
# for is its own.
DEMO_BIN="$ROOT/.venv/bin"
if [ ! -x "$DEMO_BIN/s0ma" ]; then
    printf 'No s0ma to record at %s/s0ma.\n\n' "$DEMO_BIN" >&2
    printf 'The tapes demonstrate this working tree, not whatever s0ma happens\n' >&2
    printf 'to be on your PATH. Sync the environment first:  uv sync\n' >&2
    exit 2
fi

if [ -z "$TAPES" ]; then
    TAPES=$(cd "$ROOT" && ls "$TAPE_DIR"/*.tape)
fi

CHECK_ROOT=$(mktemp -d 2>/dev/null || mktemp -d -t s0ma-check)
WORK=$(mktemp -d 2>/dev/null || mktemp -d -t s0ma-rec)
trap 'rm -rf "$WORK" "$CHECK_ROOT"' EXIT INT TERM HUP

printf '\n== s0ma: the demo recordings ==\n'
printf 'repository:        %s\n' "$ROOT"
printf 'renders to:        %s\n' "$OUT"
printf 'demonstration in:  %s  (this path appears on screen)\n' "$DEMO_ROOT"
printf 's0ma under test:   %s/s0ma\n' "$DEMO_BIN"
printf 'honesty check in:  %s (removed when this finishes)\n\n' "$CHECK_ROOT"

# ---------------------------------------------------------------------------
# Reading a tape.
#
# Every line the tape types, in order, with its delimiter removed. Both of
# VHS's string delimiters are handled; `clear` is dropped because it is
# cosmetic and needs a terminal that the replay does not have.
# ---------------------------------------------------------------------------

typed_commands() {
    sed -n \
        -e 's/^[[:space:]]*Type\(@[^ ]*\)\{0,1\}[[:space:]]*`\(.*\)`[[:space:]]*$/\2/p' \
        -e 's/^[[:space:]]*Type\(@[^ ]*\)\{0,1\}[[:space:]]*"\(.*\)"[[:space:]]*$/\2/p' \
        "$1" | grep -v '^clear$' || true
}

# The refusals a tape declares, as "<code><tab><command>".
expected_failures() {
    sed -n \
        's/^#[[:space:]]*expect-fail:[[:space:]]*\([0-9][0-9]*\)[[:space:]]\{1,\}\(.*\)$/\1	\2/p' \
        "$1" || true
}

human_size() {
    wc -c < "$1" | awk '{
        n = $1
        if (n > 1048576) printf "%.1f MB", n / 1048576
        else printf "%.0f KB", n / 1024
    }'
}

# ---------------------------------------------------------------------------
# Render, then check.
# ---------------------------------------------------------------------------

FAILED=0
SUMMARY="$WORK/summary"
: > "$SUMMARY"

for tape in $TAPES; do
    case $tape in
        /*) tape_abs=$tape ;;
        *)  tape_abs="$ROOT/$tape" ;;
    esac
    if [ ! -f "$tape_abs" ]; then
        printf 'No such tape: %s\n' "$tape" >&2
        FAILED=1
        continue
    fi
    name=$(basename "$tape_abs" .tape)

    printf -- '-- %s --\n' "$name"

    # --- 1. render -------------------------------------------------------
    set -- -o "$OUT/$name.gif" -o "$OUT/$name.mp4"
    if [ "$WANT_WEBM" = yes ]; then
        set -- "$@" -o "$OUT/$name.webm"
    fi

    rendered=yes
    # Run from the repository root so the tapes' relative paths resolve, and
    # hand the tape the three things it asks the environment for.
    if ! (
        cd "$ROOT" \
        && S0MA_DEMO_BIN="$DEMO_BIN" \
           S0MA_DEMO_ROOT="$DEMO_ROOT" \
           S0MA_DEMO_SRC="$ROOT" \
           vhs "$@" "$tape_abs"
    ) > "$WORK/$name.render.log" 2>&1; then
        rendered=no
    fi

    if [ "$rendered" = no ] || [ ! -s "$OUT/$name.mp4" ]; then
        printf 'render:  FAILED\n'
        sed 's/^/  | /' "$WORK/$name.render.log" | tail -n 20
        FAILED=1
        printf '%s\trender failed\t-\t-\n' "$name" >> "$SUMMARY"
        continue
    fi

    duration=$(ffprobe -v error -show_entries format=duration \
        -of default=noprint_wrappers=1:nokey=1 "$OUT/$name.mp4")
    sizes="gif $(human_size "$OUT/$name.gif"), mp4 $(human_size "$OUT/$name.mp4")"
    if [ -f "$OUT/$name.webm" ]; then
        sizes="$sizes, webm $(human_size "$OUT/$name.webm")"
    fi
    printf 'render:  %s  (%s s)\n' "$sizes" "$duration"

    too_long=$(awk -v d="$duration" -v m="$MAX_SECONDS" 'BEGIN { print (d > m) ? "yes" : "no" }')
    if [ "$too_long" = yes ]; then
        printf 'length:  TOO LONG - %s s, and the budget is %s s.\n' "$duration" "$MAX_SECONDS"
        FAILED=1
    fi

    # --- 2. honesty check ------------------------------------------------
    # Re-run the tape's own commands, in order, in a scratch directory of
    # their own, and record what each one exits with.
    expect="$WORK/$name.expect"
    expected_failures "$tape_abs" > "$expect"
    typed_commands "$tape_abs" > "$WORK/$name.cmds"

    replay="$WORK/$name.replay.sh"
    statfile="$WORK/$name.status"
    : > "$statfile"
    {
        printf 'set +e\n'
        printf 'cd "%s" || exit 90\n' "$ROOT"
        n=0
        while IFS= read -r cmd; do
            n=$((n + 1))
            printf '%s\n' "$cmd"
            printf 'printf "%%s\\t%%s\\n" "%s" "$?" >> "%s"\n' "$n" "$statfile"
        done < "$WORK/$name.cmds"
    } > "$replay"

    (
        S0MA_DEMO_BIN="$DEMO_BIN" \
        S0MA_DEMO_ROOT="$CHECK_ROOT" \
        S0MA_DEMO_SRC="$ROOT" \
        bash "$replay"
    ) > "$WORK/$name.replay.log" 2>&1 || true

    honest=yes
    n=0
    while IFS= read -r cmd; do
        n=$((n + 1))
        got=$(awk -F'\t' -v i="$n" '$1 == i { print $2; exit }' "$statfile")
        if [ -z "$got" ]; then
            printf '  did not run: %s\n' "$cmd"
            honest=no
            continue
        fi
        want=$(awk -F'\t' -v c="$cmd" '$2 == c { print $1; f = 1; exit } END { if (!f) print 0 }' "$expect")
        if [ "$got" != "$want" ]; then
            printf '  exit %s, expected %s: %s\n' "$got" "$want" "$cmd"
            honest=no
        fi
    done < "$WORK/$name.cmds"

    if [ "$honest" = yes ]; then
        printf 'honest:  yes  (%s command(s) re-run; %s declared refusal(s) honoured)\n\n' \
            "$n" "$(wc -l < "$expect" | tr -d ' ')"
    else
        printf 'honest:  NO - the recording does not match what the commands do.\n'
        printf '         The replay output is above; the full log is %s\n\n' \
            "$WORK/$name.replay.log"
        FAILED=1
    fi

    printf '%s\t%s s\t%s\t%s\n' "$name" "$duration" "$sizes" "$honest" >> "$SUMMARY"
done

# ---------------------------------------------------------------------------
# What happened.
# ---------------------------------------------------------------------------

printf '== summary ==\n'
awk -F'\t' '{ printf "%-18s %-10s %-34s honest: %s\n", $1, $2, $3, $4 }' "$SUMMARY"
printf '\nrenders are in %s\n' "$OUT"
printf 'nothing was written inside the repository.\n\n'

if [ "$FAILED" -eq 0 ]; then
    printf 'All good.\n'
    exit 0
fi
printf 'Something did not pass. The detail is above.\n'
exit 1
