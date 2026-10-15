#!/usr/bin/env sh
#
# s0ma single-command installer (hosting & entitlement plan, HOST-H6).
#
# Collapses the documented multi-step wheel flow into one command, fetching
# the released wheels from the s0ma CONTROL PLANE (an entitlement-gated
# download keyed by your license key) instead of a private GitHub Release:
# fetch the signed manifest, download + sha256-verify the four wheels,
# create a uv project, install the wheels, run `s0ma doctor`, connect this
# machine to the feedback function, register the authoring MCP server, and
# scaffold a feature-first project.
#
# This is a convenience script the USER runs. Nothing in s0ma-core /
# s0ma-dsl / s0ma-mcp imports or invokes it (PRD P-6 / plan D-1: no network
# in product code, no toolchain coupling). The control-plane fetch lives
# ONLY here, in this user-run shell script.
#
# Usage:
#   scripts/install.sh <target-dir> --key <KEY> [--version <ver>]
#                       [--cp-host <host>] [--default-off] [--no-feedback]
#                       [--dry-run]
#
#   <target-dir>     Directory to create/initialize (required).
#   --key <KEY>      Your s0ma license key. Alternatively set the
#                    S0MA_LICENSE_KEY environment variable. One of the two
#                    is REQUIRED. Get a key at https://account.kn0wthyself.ai
#   --version <ver>  Release version to install (e.g. 0.9.0). Default:
#                    'latest', which the control plane resolves server-side.
#   --cp-host <host> Control-plane host. Default: account.kn0wthyself.ai
#                    (override only for testing against another host). A bare
#                    host gets https:// (production default); a value that
#                    already carries a scheme is used verbatim, so a local
#                    `wrangler pages dev` can be targeted with
#                    --cp-host http://127.0.0.1:8788 (HOST-H9 smoke).
#   --default-off    Pass through to `s0ma new project` so the scaffolded
#                    project sets `[tool.s0ma].authoring = "off"`.
#   --no-feedback    Skip the feedback step below. Everything else installs
#                    exactly as usual; you can connect the machine later
#                    with `s0ma feedback enroll`.
#   --dry-run        Print the exact command sequence that WOULD run, then
#                    exit. Executes nothing and touches no network. The
#                    license key is REDACTED (Bearer ***) in the output.
#   -h, --help       Show this help and exit.
#
# Feedback: after the health check the installer asks the control plane for
# this machine's feedback access and stores it in ~/.s0ma/feedback-token
# (owner-only, outside every project). That is all it does — no report is
# written or sent. Sending feedback is always something you ask for, and you
# approve the exact feedback data first. If this step cannot complete, the
# install still succeeds and says so.
#
# Prerequisites (checked up front): `curl`, the `uv` package manager, and a
# valid license key. `claude` (Claude Code) is optional; if absent, the MCP
# registration step is skipped with a printed hint.

set -eu

# ---------------------------------------------------------------------------
# Constants.
# ---------------------------------------------------------------------------
WHEEL_DIR=".wheels"
# Default control-plane host (the H4 contract; --cp-host overrides for tests).
CP_HOST_DEFAULT="account.kn0wthyself.ai"
# The four wheels, named by their distribution stems. The control-plane
# manifest carries all four (their inter-dependencies name packages that are
# not on PyPI, so each must be installed explicitly; studi0 by owner decision 2026-08-17).
WHEELS="s0ma_core s0ma_dsl s0ma_mcp s0ma_studi0"
# The MCP registration line, verbatim from docs/walkthrough.md §2 (project
# scope: writes .mcp.json so every session/teammate inherits it).
MCP_ADD="claude mcp add s0ma --scope project -- uv run s0ma-mcp"
# Feedback enrollment (docs/contracts/feedback-v1.md §2 + §8, FD-3/FD-4):
# the license key is exchanged ONCE for a scoped feedback token, which is
# stored owner-only under the user's home directory — never inside a project
# tree, never committed. These names must match s0ma_dsl.feedback.tokens /
# .state, which is what `s0ma feedback` reads afterwards.
FEEDBACK_TOKEN_ENDPOINT="/api/feedback/token"
FEEDBACK_STATE_DIR_NAME=".s0ma"
FEEDBACK_TOKEN_FILENAME="feedback-token"
# Displayable prefix length (contract §2.2) — the only part of a token this
# script is ever allowed to print.
FEEDBACK_PREFIX_CHARS=12

# Program name for messages. Do NOT use `basename "$0"`: when this installer is
# run via the published one-liner `sh -c "$(curl … install.sh)" -- …`, $0 is
# "--", and `basename --` errors out (halting the install before it starts).
# Parameter expansion is safe; fall back to a fixed name for a non-path $0.
PROG="${0##*/}"
case "$PROG" in ''|-*) PROG="install.sh" ;; esac

usage() {
    # In the one-liner form $0 is "--" (not a readable file), so self-reading the
    # header comment fails — fall back to a one-line synopsis.
    # The range is the header comment block: line 3 (the title) through the last
    # prerequisites line, just above `set -eu`. Adjust it if the header grows.
    if [ -r "$0" ]; then
        sed -n '3,54p' "$0" | sed 's/^# \{0,1\}//'
    else
        printf '%s\n' "Usage: $PROG <target-dir> --key <KEY> [--version <ver>] [--cp-host <host>] [--default-off] [--no-feedback] [--dry-run] [-h]"
    fi
}

die() {
    # Actionable, loud failure on stderr.
    printf '%s: error: %s\n' "$PROG" "$1" >&2
    exit 1
}

# ---------------------------------------------------------------------------
# Argument parsing.
# ---------------------------------------------------------------------------
TARGET=""
VERSION=""
KEY=""
CP_HOST=""
DEFAULT_OFF=""
DRY_RUN=0
NO_FEEDBACK=0

while [ $# -gt 0 ]; do
    case "$1" in
        --key)
            [ $# -ge 2 ] || die "--key needs a license-key argument"
            KEY="$2"
            shift 2
            ;;
        --key=*)
            KEY="${1#--key=}"
            shift
            ;;
        --version)
            [ $# -ge 2 ] || die "--version needs a version argument (e.g. --version 0.9.0)"
            VERSION="$2"
            shift 2
            ;;
        --version=*)
            VERSION="${1#--version=}"
            shift
            ;;
        --cp-host)
            [ $# -ge 2 ] || die "--cp-host needs a host argument"
            CP_HOST="$2"
            shift 2
            ;;
        --cp-host=*)
            CP_HOST="${1#--cp-host=}"
            shift
            ;;
        --default-off)
            DEFAULT_OFF="--default-off"
            shift
            ;;
        --no-feedback)
            NO_FEEDBACK=1
            shift
            ;;
        --dry-run)
            DRY_RUN=1
            shift
            ;;
        -h|--help)
            usage
            exit 0
            ;;
        --)
            shift
            ;;
        -*)
            die "unknown option: $1 (run '$PROG --help')"
            ;;
        *)
            if [ -n "$TARGET" ]; then
                die "unexpected extra argument: $1 (only one target dir is accepted)"
            fi
            TARGET="$1"
            shift
            ;;
    esac
done

[ -n "$TARGET" ] || die "a target directory is required. Usage: $PROG <target-dir> --key <KEY> [--version <ver>] [--default-off] [--no-feedback] [--dry-run]"

# License key: --key wins, else the S0MA_LICENSE_KEY environment variable.
# Exactly one source is required — fail loud and actionable, naming BOTH.
if [ -z "$KEY" ]; then
    KEY="${S0MA_LICENSE_KEY:-}"
fi
[ -n "$KEY" ] || die "a license key is required. Pass it with --key <KEY> or set the S0MA_LICENSE_KEY environment variable. Get a key at https://account.kn0wthyself.ai"

# Control-plane host (overridable for testing).
[ -n "$CP_HOST" ] || CP_HOST="$CP_HOST_DEFAULT"

# Version: 'latest' is resolved server-side by the manifest endpoint.
[ -n "$VERSION" ] || VERSION="latest"

# Resolve the control-plane BASE URL. A bare host (no scheme) gets https://
# (the production default; backward-compatible with --cp-host localhost:8788).
# A value that already carries a scheme (http:// or https://) is used verbatim,
# so a local `wrangler pages dev` over plain http can be targeted with
# --cp-host http://127.0.0.1:8788 (HOST-H9 smoke). Resolution happens here, so
# every URL below is built from a single base.
case "$CP_HOST" in
    *://*) ACCOUNT_URL="$CP_HOST" ;;
    *)     ACCOUNT_URL="https://$CP_HOST" ;;
esac

# Control-plane URLs (the H4 contract + the feedback-v1 contract §2).
MANIFEST_URL="$ACCOUNT_URL/api/dist/manifest?version=$VERSION"
FEEDBACK_TOKEN_URL="$ACCOUNT_URL$FEEDBACK_TOKEN_ENDPOINT"

# Where this machine's feedback access is stored (contract §8). An empty HOME
# leaves these empty, which the enrollment step reads as "nowhere to store it"
# and reports like any other non-fatal enrollment failure. The `~` form is what
# we PRINT (it is what the user recognises and what every doc names); the
# resolved form is what we write.
FEEDBACK_STATE_DIR=""
FEEDBACK_TOKEN_FILE=""
if [ -n "${HOME:-}" ]; then
    FEEDBACK_STATE_DIR="$HOME/$FEEDBACK_STATE_DIR_NAME"
    FEEDBACK_TOKEN_FILE="$FEEDBACK_STATE_DIR/$FEEDBACK_TOKEN_FILENAME"
fi
FEEDBACK_TOKEN_DISPLAY="~/$FEEDBACK_STATE_DIR_NAME/$FEEDBACK_TOKEN_FILENAME"

# The `s0ma new project .` argument line (with optional --default-off).
NEW_PROJECT_ARGS="new project ."
if [ -n "$DEFAULT_OFF" ]; then
    NEW_PROJECT_ARGS="$NEW_PROJECT_ARGS $DEFAULT_OFF"
fi

# ---------------------------------------------------------------------------
# Manifest parsing — POSIX sh, NO jq dependency.
#
# This is PINNED TO OUR OWN MANIFEST SHAPE (the H4 contract), not a general
# JSON parser. The endpoint returns a FLAT object:
#
#   {"ok":true,"version":"0.9.0","wheels":[
#       {"name":"s0ma_core-0.9.0-py3-none-any.whl",
#        "path":"dist/0.9.0/s0ma_core-0.9.0-py3-none-any.whl",
#        "sha256":"<hex>","size":12345}, ...one object per wheel...]}
#
# Strategy: split each wheel object onto its own line (turn the `},{` object
# separators into newlines), then for each known wheel stem
# (each stem in $WHEELS) select the line whose "name" starts with that
# stem and pull out its "path" / "sha256" string values. Anchoring on the
# known stems makes this robust to field ordering and to whitespace.
#
# Fragile-but-pinned: if H4 ever changes the manifest field names or nesting,
# this extraction must change in lockstep (see H9 smoke test).
# ---------------------------------------------------------------------------

# Normalize a manifest JSON blob to one wheel-object per line.
manifest_to_lines() {
    # Insert a newline before each '{' that opens a wheel object. Works
    # whether the server emits compact or pretty JSON. The trailing '\n'
    # guarantees the final wheel object is its own readable line (a body
    # without a trailing newline would otherwise be skipped by `read`).
    printf '%s\n' "$1" | tr '{' '\n'
}

# Extract the value of a JSON string field ("field":"value") from one line.
# $1 = line, $2 = field name. Prints the value (no quotes), or empty.
json_field() {
    printf '%s' "$1" | sed -n 's/.*"'"$2"'"[[:space:]]*:[[:space:]]*"\([^"]*\)".*/\1/p'
}

# Extract the value of a JSON NUMBER field ("field":123) from one body.
# $1 = body, $2 = field name. Prints the digits, or empty when the field is
# absent, null, or not a bare integer. The feedback contract's timestamps are
# epoch MILLISECONDS (feedback-v1 r6), so this is the only numeric field this
# script reads and it is copied through verbatim.
json_number_field() {
    printf '%s' "$1" | sed -n 's/.*"'"$2"'"[[:space:]]*:[[:space:]]*\(-\{0,1\}[0-9][0-9]*\).*/\1/p'
}

# Given the full manifest body and a wheel stem, print "<path>\t<sha256>".
# Selects the wheel object whose "name" begins with the stem.
wheel_path_and_sha() {
    _body="$1"
    _stem="$2"
    manifest_to_lines "$_body" | while IFS= read -r _line; do
        case "$_line" in
            *'"name"'*"\"$_stem"-*) ;;   # name starts with <stem>-
            *) continue ;;
        esac
        _path="$(json_field "$_line" path)"
        _sha="$(json_field "$_line" sha256)"
        [ -n "$_path" ] || continue
        printf '%s\t%s\n' "$_path" "$_sha"
        break
    done
}

# Compute the sha256 of a file, portably (sha256sum or shasum -a 256).
sha256_of() {
    if command -v sha256sum >/dev/null 2>&1; then
        sha256sum "$1" | awk '{print $1}'
    elif command -v shasum >/dev/null 2>&1; then
        shasum -a 256 "$1" | awk '{print $1}'
    else
        die "no sha256 tool found (need 'sha256sum' or 'shasum'). Install coreutils and re-run $PROG."
    fi
}

# ---------------------------------------------------------------------------
# --dry-run: print the exact sequence, execute nothing, no network.
#   The license key is REDACTED (Bearer ***) everywhere it would appear.
# ---------------------------------------------------------------------------
if [ "$DRY_RUN" -eq 1 ]; then
    printf '# s0ma installer (dry run) — would run, in order:\n'
    printf '# target dir:   %s\n' "$TARGET"
    printf '# control plane: %s\n' "$CP_HOST"
    printf '# version:      %s\n' "$VERSION"
    printf '# authoring:    %s\n' "$([ -n "$DEFAULT_OFF" ] && echo 'off (--default-off)' || echo 'on (default)')"
    printf '# feedback:     %s\n' "$([ "$NO_FEEDBACK" -eq 1 ] && echo 'skipped (--no-feedback)' || echo 'enroll this machine (non-fatal)')"
    printf '# (license key redacted as "Bearer ***" below)\n'
    printf '\n'
    printf 'mkdir -p %s\n' "$TARGET"
    printf 'cd %s\n' "$TARGET"
    printf 'mkdir -p %s\n' "$WHEEL_DIR"
    printf '# 1. fetch the entitlement-gated manifest (resolves wheel paths + sha256):\n'
    printf 'curl -fsSL -H "Authorization: Bearer ***" %s\n' "$MANIFEST_URL"
    printf '# 2. download each wheel and verify its sha256:\n'
    for w in $WHEELS; do
        printf 'curl -fSL -H "Authorization: Bearer ***" -o %s/%s-<version>-py3-none-any.whl %s/dist/<version>/%s-<version>-py3-none-any.whl\n' \
            "$WHEEL_DIR" "$w" "$ACCOUNT_URL" "$w"
    done
    printf '# 3. uv project + install the verified wheels + health check:\n'
    printf 'uv init --no-workspace\n'
    printf 'uv add'
    for w in $WHEELS; do
        printf ' ./%s/%s-<version>-py3-none-any.whl' "$WHEEL_DIR" "$w"
    done
    printf '\n'
    printf 'uv run s0ma doctor\n'
    if [ "$NO_FEEDBACK" -eq 1 ]; then
        printf '# 4. feedback: SKIPPED (--no-feedback). Enroll later with: s0ma feedback enroll\n'
    else
        printf "# 4. ask the control plane for this machine's feedback access (non-fatal;\n"
        printf '#    --no-feedback skips it; no feedback report is written or sent here):\n'
        printf 'curl -fsS -X POST -H "Authorization: Bearer ***" -H "Content-Type: application/json" -d "{}" %s\n' \
            "$FEEDBACK_TOKEN_URL"
        printf '#    then write {token, token_prefix, expires_ts, cp_host} to %s (dir 0700, file 0600)\n' \
            "$FEEDBACK_TOKEN_DISPLAY"
    fi
    printf '# 5. register the authoring MCP server + scaffold the project:\n'
    printf '%s\n' "$MCP_ADD"
    printf 'uv run s0ma %s\n' "$NEW_PROJECT_ARGS"
    exit 0
fi

# ---------------------------------------------------------------------------
# Prerequisite checks (real run) — fail loudly with actionable messages.
# ---------------------------------------------------------------------------
command -v curl >/dev/null 2>&1 || die "'curl' is not installed. Install it then re-run $PROG."
command -v uv >/dev/null 2>&1 || die "the 'uv' package manager is not installed. Install it from https://docs.astral.sh/uv/ then re-run $PROG."

# ---------------------------------------------------------------------------
# Private scratch dir (real run ONLY — --dry-run exited above and must touch
# nothing). One mktemp-rooted 0700 dir holds every temp file this installer
# writes (curl bodies/status, response headers, the Bearer header file):
# unpredictable name, unreadable to other users, removed by the EXIT trap on
# ANY exit. The INT/TERM traps route interrupts through `exit` so the EXIT
# trap also runs on Ctrl-C / kill in every POSIX shell (dash does not run
# EXIT traps on an untrapped fatal signal).
# Portable form: BSD/macOS mktemp -d REQUIRES the template — always pass it.
# ---------------------------------------------------------------------------
_tmpd="$(mktemp -d "${TMPDIR:-/tmp}/s0ma-install.XXXXXX")" || \
    die "could not create a temporary directory under ${TMPDIR:-/tmp}"
trap 'rm -rf "$_tmpd"' EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

# The license key must NEVER ride any process argv (argv is world-readable
# via `ps`/`/proc/<pid>/cmdline` on multi-user hosts for the life of each
# transfer). Write the Authorization header into the 0700 scratch dir via a
# here-doc — redirection by the shell itself, so no process (curl OR a
# helper like an external printf) ever holds the key in its argv — and hand
# curl the file with `-H @file` (supported since curl 7.55, 2017 — present
# on all supported platforms incl. Git-Bash/MSYS).
_hdrf="$_tmpd/hdr"
cat >"$_hdrf" <<S0MA_HDR_EOF
Authorization: Bearer $KEY
S0MA_HDR_EOF
# Belt-and-braces: the dir is already 0700, but pin the file too.
chmod 600 "$_hdrf"

run() {
    # Echo each command before executing it, so the real run is auditable.
    printf '+ %s\n' "$*"
    "$@"
}

# Surface the D-5 structured error body, then abort.
# $1 = http status, $2 = response body.
cp_fail() {
    _http="$1"
    _resp="$2"
    _code="$(json_field "$_resp" code)"
    _rem="$(json_field "$_resp" remediation)"
    [ -n "$_code" ] || _code="HTTP_$_http"
    printf '%s: error: control plane returned HTTP %s (%s)\n' "$PROG" "$_http" "$_code" >&2
    [ -n "$_rem" ] && printf '  remediation: %s\n' "$_rem" >&2
    # E2: on a 429, surface the server's Retry-After (delta-seconds) so the
    # user knows how long to wait. Informational only — NO auto-retry loop.
    # cp_fetch captured the response headers (curl -D) into $_hdrsf; HTTP/2
    # lowercases header names, hence the [Rr]/[Aa] classes; `-L` can stack
    # several header blocks, hence `tail -n 1`; a non-numeric Retry-After
    # (HTTP-date form) simply does not match and the line is skipped.
    if [ "$_http" = "429" ] && [ -r "${_hdrsf:-}" ]; then
        _ra="$(tr -d '\r' <"$_hdrsf" | sed -n 's/^[Rr]etry-[Aa]fter:[[:space:]]*\([0-9][0-9]*\).*$/\1/p' | tail -n 1)"
        [ -n "$_ra" ] && printf '  retry after ~%ss\n' "$_ra" >&2
    fi
    printf '  check your key / subscription at %s\n' "$ACCOUNT_URL" >&2
    exit 1
}

# Fetch a control-plane URL with the Bearer key and print its body to stdout.
# On a non-2xx, the structured {ok:false,code,remediation} body (D-5) is
# surfaced with the account hint, then we abort. The HTTP status is written
# to a side file (curl -w) so command substitution can keep the body intact;
# response headers are captured (-D) so cp_fail can surface Retry-After on a
# 429 (E2). All side files live in the trap-cleaned $_tmpd; the key rides
# `-H @file`, never argv.
# $1 = url
cp_fetch() {
    _url="$1"
    _bodyf="$_tmpd/body"
    _statusf="$_tmpd/status"
    _hdrsf="$_tmpd/resp-hdrs"
    if ! curl -sSL -o "$_bodyf" -D "$_hdrsf" -w '%{http_code}' \
            -H @"$_hdrf" "$_url" >"$_statusf" 2>/dev/null; then
        die "could not reach the s0ma control plane at $CP_HOST. Check your network, or your key/subscription at $ACCOUNT_URL"
    fi
    _http="$(cat "$_statusf")"
    _resp="$(cat "$_bodyf")"
    case "$_http" in
        2??) printf '%s' "$_resp" ;;
        *)   cp_fail "$_http" "$_resp" ;;
    esac
}

# ---------------------------------------------------------------------------
# Feedback enrollment (docs/contracts/feedback-v1.md §2/§8; FD-3/FD-4).
#
# ONE POST exchanges the license key for a scoped, expiring feedback token,
# which is stored owner-only at ~/.s0ma/feedback-token in exactly the shape
# s0ma_dsl.feedback.tokens reads: {token, token_prefix, expires_ts, cp_host}.
# The license key never travels with a feedback report afterwards; the body
# is EMPTY by design (contract r6 — sending the installation pseudonym here
# would let the control plane join pseudonym to account).
#
# NOTHING is sent to anyone by this step and no feedback report is composed:
# it only obtains and stores access, so that a later, user-initiated
# `s0ma feedback` has something to authenticate with.
#
# Two secrets pass through here and NEITHER may ever be echoed: the license
# key (which rides `-H @file`, never argv — see $_hdrf) and the returned
# token. Only the token's 12-character display prefix is ever printed.
#
# EVERY failure is non-fatal: this function always returns 0 and the install
# continues. `feedback_skip` prints the single warning line and the one
# remediation the user needs.
# ---------------------------------------------------------------------------

# One-line, non-fatal "we could not do this" notice. $1 = the reason.
feedback_skip() {
    printf '!! Could not set this machine up to send feedback (%s) — the install is fine; set it up later with: s0ma feedback enroll\n' "$1"
}

enroll_feedback() {
    if [ -z "$FEEDBACK_TOKEN_FILE" ]; then
        feedback_skip "no home directory is set"
        return 0
    fi

    _fbbodyf="$_tmpd/fb-body"
    _fbstatusf="$_tmpd/fb-status"
    # An empty JSON object is the whole request body (contract r6). `-d '{}'`
    # implies POST; `-X POST` is stated anyway so the intent survives a reader.
    printf '+ curl -fsS -X POST -H "Authorization: Bearer ***" -H "Content-Type: application/json" -d "{}" %s\n' \
        "$FEEDBACK_TOKEN_URL"
    if ! curl -sS -X POST -o "$_fbbodyf" -w '%{http_code}' \
            -H @"$_hdrf" -H 'Content-Type: application/json' \
            -d '{}' "$FEEDBACK_TOKEN_URL" >"$_fbstatusf" 2>/dev/null; then
        feedback_skip "the control plane could not be reached"
        return 0
    fi
    _fbhttp="$(cat "$_fbstatusf")"
    _fbresp="$(cat "$_fbbodyf")"

    # A non-2xx body carries {ok:false, code, remediation} (D-5) and NO token,
    # so surfacing its `code` leaks nothing. The body is never printed whole.
    case "$_fbhttp" in
        2??) ;;
        *)
            _fbcode="$(json_field "$_fbresp" code)"
            [ -n "$_fbcode" ] || _fbcode="HTTP_$_fbhttp"
            feedback_skip "$_fbcode"
            return 0
            ;;
    esac

    _fbtoken="$(json_field "$_fbresp" token)"
    if [ -z "$_fbtoken" ]; then
        feedback_skip "the reply carried no access for this machine"
        return 0
    fi
    # Defensive: the token is interpolated into JSON below, so a value that
    # could break out of a JSON string is refused rather than written. A real
    # token is `s0ma_fb_` + base64url, which contains none of these.
    case "$_fbtoken" in
        *'"'*|*'\'*|*' '*)
            feedback_skip "the reply carried access in an unexpected form"
            return 0
            ;;
    esac

    _fbprefix="$(json_field "$_fbresp" token_prefix)"
    # Fall back to the contract's own rule (first 12 chars) if the server did
    # not send a prefix, so the notice below always has something honest to
    # show. `printf %.Ns` truncates portably in POSIX sh.
    [ -n "$_fbprefix" ] || _fbprefix="$(printf '%.'"$FEEDBACK_PREFIX_CHARS"'s' "$_fbtoken")"
    case "$_fbprefix" in
        *'"'*|*'\'*) _fbprefix="" ;;
    esac
    _fbexpires="$(json_number_field "$_fbresp" expires_ts)"
    [ -n "$_fbexpires" ] || _fbexpires="null"

    # Create the state dir owner-only BEFORE anything lands in it, then write
    # the token file and pin it to 0600. `umask 077` scopes to this subshell-
    # free block; the explicit chmods are what actually guarantee the modes on
    # a pre-existing file. Both are best-effort off POSIX (Windows ACLs are
    # not a POSIX mode) — matching s0ma_dsl.feedback.state.
    if ! mkdir -p "$FEEDBACK_STATE_DIR" 2>/dev/null; then
        feedback_skip "could not create $FEEDBACK_TOKEN_DISPLAY"
        return 0
    fi
    chmod 700 "$FEEDBACK_STATE_DIR" 2>/dev/null || true
    # Write via a here-doc: the shell performs the redirection itself, so the
    # token never rides any process argv. Keys are sorted, matching what
    # `s0ma feedback enroll` writes.
    if ! (
        umask 077
        cat >"$FEEDBACK_TOKEN_FILE" <<S0MA_FB_EOF
{
  "cp_host": "$ACCOUNT_URL",
  "expires_ts": $_fbexpires,
  "token": "$_fbtoken",
  "token_prefix": "$_fbprefix"
}
S0MA_FB_EOF
    ) 2>/dev/null; then
        feedback_skip "could not write $FEEDBACK_TOKEN_DISPLAY"
        return 0
    fi
    chmod 600 "$FEEDBACK_TOKEN_FILE" 2>/dev/null || true

    printf '   This machine can now send feedback about s0ma — access %s… is stored at %s; use `s0ma feedback`.\n' \
        "$_fbprefix" "$FEEDBACK_TOKEN_DISPLAY"
    return 0
}

# ---------------------------------------------------------------------------
# Execute the install: keyed control-plane fetch + the proven uv/scaffold tail.
# ---------------------------------------------------------------------------
printf '==> s0ma installer: %s (version %s)\n' "$CP_HOST" "$VERSION"

run mkdir -p "$TARGET"
# Note: each `run` invocation is its own process; we cd here so the
# subsequent uv commands operate inside the target project.
cd "$TARGET" || die "could not enter target directory: $TARGET"

printf '==> Fetching the entitlement-gated manifest\n'
printf '+ curl -fsSL -H "Authorization: Bearer ***" %s\n' "$MANIFEST_URL"
MANIFEST="$(cp_fetch "$MANIFEST_URL")"
[ -n "$MANIFEST" ] || die "the control plane returned an empty manifest. Check your key/subscription at $ACCOUNT_URL"

mkdir -p "$WHEEL_DIR"

printf '==> Downloading and verifying the s0ma wheels\n'
UV_ADD_ARGS=""
for w in $WHEELS; do
    line="$(wheel_path_and_sha "$MANIFEST" "$w")"
    [ -n "$line" ] || die "wheel '$w' not found in the manifest from $CP_HOST. Check your key/subscription at $ACCOUNT_URL"
    wpath="${line%%	*}"
    wsha="${line#*	}"
    [ -n "$wpath" ] || die "could not parse a download path for '$w' from the manifest."
    wfile="$WHEEL_DIR/$(basename "$wpath")"
    # Download straight to the wheel dir, with the Bearer key riding the
    # header FILE (never argv — see the $_hdrf here-doc above).
    printf '+ curl -fSL -H "Authorization: Bearer ***" -o %s %s/%s\n' "$wfile" "$ACCOUNT_URL" "$wpath"
    curl -fSL -H @"$_hdrf" -o "$wfile" "$ACCOUNT_URL/$wpath" || \
        die "download failed for '$w' (HTTP error). Check your key/subscription at $ACCOUNT_URL"
    # Verify sha256 against the manifest value (loud failure + abort on mismatch).
    if [ -n "$wsha" ]; then
        got="$(sha256_of "$wfile")"
        if [ "$got" != "$wsha" ]; then
            die "sha256 MISMATCH for '$w': manifest says $wsha but downloaded file is $got. Aborting (possible corruption or tampering)."
        fi
        printf '  sha256 ok: %s\n' "$w"
    else
        printf '  !! manifest carried no sha256 for %s — skipping verification\n' "$w"
    fi
    UV_ADD_ARGS="$UV_ADD_ARGS ./$wfile"
done
# Strip the leading space.
UV_ADD_ARGS="${UV_ADD_ARGS# }"

printf '==> Initializing uv project\n'
# --no-workspace: a tester may run the one-liner from inside some existing
# uv workspace (their own project, or even a s0ma checkout). Without the
# flag, uv init JOINS that workspace and the subsequent `uv add <wheel>`
# fails ("Workspace dependency ... must refer to local directory, not a
# file") because the wheel's distribution name collides with a workspace
# member. The new project must always stand alone. (Found live, 2026-08-28.)
run uv init --no-workspace

printf '==> Installing the s0ma wheels\n'
# Word-split UV_ADD_ARGS deliberately (one explicit wheel path per $WHEELS entry).
# shellcheck disable=SC2086
run uv add $UV_ADD_ARGS

printf '==> Health check\n'
run uv run s0ma doctor

printf '==> Setting this machine up to send feedback\n'
if [ "$NO_FEEDBACK" -eq 1 ]; then
    printf '   skipped (--no-feedback). Set it up later with: s0ma feedback enroll\n'
else
    enroll_feedback
fi

printf '==> Registering the authoring MCP server\n'
if command -v claude >/dev/null 2>&1; then
    # shellcheck disable=SC2086
    run $MCP_ADD
else
    printf '!! Claude Code ("claude") not found on PATH — skipping MCP registration.\n'
    printf '   Register later with: %s\n' "$MCP_ADD"
fi

printf '==> Scaffolding a feature-first project\n'
# shellcheck disable=SC2086
run uv run s0ma $NEW_PROJECT_ARGS

printf '\n==> Done. s0ma is installed and a project is scaffolded in %s\n' "$TARGET"
printf '    Validate any time with: uv run s0ma check\n'
printf '    Send feedback about s0ma any time: s0ma feedback — you approve the exact feedback data before anything is sent.\n'
