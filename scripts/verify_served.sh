#!/usr/bin/env bash
#
# s0ma served-release verification — what does prod ACTUALLY serve? (RP-M3.)
#
# The release workflow builds wheels, cuts a GitHub Release, and mirrors the
# wheels + `dist/manifest.json` into R2 (HOST-H5); the control plane serves
# both through the entitlement gate (HOST-H4). Until now nothing checked the
# RESULT from the outside, so "the mirror job was green" and "a tester can
# install this release" were different claims. This script closes that gap:
# with a real, revocable tester key it asks the control plane what it serves,
# downloads every wheel the answer names, and compares the served installer
# against the canonical copy in this repo.
#
# Three questions, in order:
#
#   1. manifest — GET <cp-host>/api/dist/manifest?version=latest with the
#      smoke key. `latest` must resolve to the version this run asks about,
#      and the wheel list must carry exactly four entries (one per
#      distribution), each with a sha256.
#   2. wheels — download every wheel the manifest names and hash it. The
#      bytes must match the manifest's sha256 AND, whenever the same filename
#      is present in --dist-dir, the wheel built locally. Together that is
#      the end-to-end proof that a keyed install of this version succeeds:
#      the installer verifies exactly these hashes.
#   3. installer — GET <cp-host>/install.sh (public: it is the source of the
#      published one-liner) and diff it against scripts/install.sh, ignoring
#      the trailing DRIFT NOTE comment block the served copy carries. Control
#      plane deploys are MANUAL by the hardening plan (R10/R11), so a
#      difference here means "the site has not been deployed yet", not "the
#      release is broken" — it gets its own non-fatal exit class.
#
# ---------------------------------------------------------------------------
# The key
# ---------------------------------------------------------------------------
# The key is read from the `S0MA_SMOKE_KEY` environment variable ONLY. It is
# deliberately not a command-line option: arguments are world-readable via
# `ps` / /proc for the life of the process. It is never echoed — every printed
# request line shows `Authorization: Bearer ***` — and the only place it is
# written is a 0600 header file inside a mktemp-rooted 0700 scratch dir that
# the EXIT trap removes (the scripts/install.sh discipline, verbatim).
#
# ---------------------------------------------------------------------------
# Exit classes (one per failure kind, so a caller can route them)
# ---------------------------------------------------------------------------
#   0  everything this run could check PASSED
#   1  usage or environment refusal — nothing was checked (no key, bad flag,
#      missing curl/python3, unreadable canonical installer)
#   2  the served installer differs from canon: "CP deploy pending". NON-FATAL
#      class — the release verified, the site is just stale (R10/R11 manual
#      deploys). The CI job downgrades this to a `::notice`.
#   3  the manifest could not be fetched, authenticated, or parsed
#   4  the served `latest` is not the version this run asked about
#   5  the manifest's wheel list is wrong (not exactly four entries, a missing
#      distribution, or an entry with no sha256)
#   6  a wheel could not be downloaded, or its bytes do not match (served vs
#      the manifest's sha256, or served vs the locally built wheel)
#   7  the published installer could not be fetched at all
#
# Every check runs even after an earlier one fails, so one run reports the
# whole picture. When several classes fail, the exit code is the lowest
# FATAL class (3 before 4 before …); class 2 is the exit code only when
# nothing else failed.
#
# ---------------------------------------------------------------------------
# This is OPERATOR / CI TOOLING the owner (or the release workflow) runs.
# Nothing in s0ma-core / s0ma-dsl / s0ma-mcp / s0ma-studi0 imports or invokes
# it (plan D-1 / PRD P-6: no network in product code). It only ever reads:
# no upload, no deploy, no write outside its own scratch dir.
#
# Usage:
#   scripts/verify_served.sh --version <X.Y.Z> [--cp-host <host>]
#                            [--dist-dir <dir>]
#
#   --version <X.Y.Z>  The release that prod is expected to serve as `latest`
#                      (required; bare version, no leading `v`).
#   --cp-host <host>   Control-plane host. Default:
#                      https://account.kn0wthyself.ai. A bare host gets
#                      https:// (as scripts/install.sh does); a value that
#                      already carries a scheme is used verbatim, so a local
#                      `wrangler pages dev` can be targeted with
#                      --cp-host http://127.0.0.1:8788.
#   --dist-dir <dir>   Directory holding the locally built wheels, compared
#                      byte-for-byte against what the control plane serves.
#                      Default: dist. Wheels that are not there are simply
#                      not compared (reported as SKIP, never as a pass).
#   -h, --help         Show this help and exit.
#
#   The license key comes from the S0MA_SMOKE_KEY environment variable.

set -euo pipefail

# ---------------------------------------------------------------------------
# Constants.
# ---------------------------------------------------------------------------
PROG="$(basename "$0")"
S0_DIR="$(cd "$(dirname "$0")/.." && pwd)"          # s0ma-new repo root
CANON_INSTALLER="$S0_DIR/scripts/install.sh"        # the canonical copy

CP_HOST_DEFAULT="https://account.kn0wthyself.ai"
DIST_DIR_DEFAULT="dist"
# The four distributions, by wheel stem (digit-zero s0ma — INV-1). The
# manifest must name exactly these, and no more.
WHEEL_STEMS="s0ma_core s0ma_dsl s0ma_mcp s0ma_studi0"
EXPECTED_WHEEL_COUNT=4

# Exit classes (see the header table).
EXIT_DRIFT=2
EXIT_MANIFEST=3
EXIT_LATEST=4
EXIT_WHEEL_LIST=5
EXIT_WHEEL_BYTES=6
EXIT_INSTALLER_FETCH=7

usage() {
    # Print the "# Usage:" block of the header comment, marker-delimited (the
    # mirror_to_r2.sh idiom: a hardcoded line range rots as the header grows).
    sed -n '/^# Usage:/,/^[^#]/p' "$0" | grep '^#' | sed 's/^# \{0,1\}//'
}

die() {
    # Class 1: a refusal before any checking happened.
    printf '%s: error: %s\n' "$PROG" "$1" >&2
    exit 1
}

# ---------------------------------------------------------------------------
# Argument parsing.
# ---------------------------------------------------------------------------
VERSION=""
CP_HOST=""
DIST_DIR=""

while [ $# -gt 0 ]; do
    case "$1" in
        --version)
            [ $# -ge 2 ] || die "--version needs an argument (e.g. --version 0.18.0)"
            VERSION="$2"; shift 2 ;;
        --version=*)
            VERSION="${1#--version=}"; shift ;;
        --cp-host)
            [ $# -ge 2 ] || die "--cp-host needs a host argument"
            CP_HOST="$2"; shift 2 ;;
        --cp-host=*)
            CP_HOST="${1#--cp-host=}"; shift ;;
        --dist-dir)
            [ $# -ge 2 ] || die "--dist-dir needs a directory argument"
            DIST_DIR="$2"; shift 2 ;;
        --dist-dir=*)
            DIST_DIR="${1#--dist-dir=}"; shift ;;
        --key|--key=*)
            # Named explicitly so the refusal explains itself, instead of
            # landing in the generic "unknown option" branch.
            die "there is no --key option: the license key is read from the S0MA_SMOKE_KEY environment variable ONLY, because command-line arguments are world-readable via 'ps'. Run: S0MA_SMOKE_KEY=<key> $PROG --version <X.Y.Z>" ;;
        -h|--help)
            usage; exit 0 ;;
        --)
            shift ;;
        -*)
            die "unknown option: $1 (run '$PROG --help')" ;;
        *)
            die "unexpected argument: $1 (run '$PROG --help')" ;;
    esac
done

[ -n "$VERSION" ] || die "a release version is required. Pass it with --version <X.Y.Z> (the version prod is expected to serve as 'latest')."
[[ "$VERSION" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]] || \
    die "--version must be a bare X.Y.Z release version, with no leading 'v' (got '$VERSION')."
[ -n "$CP_HOST" ]  || CP_HOST="$CP_HOST_DEFAULT"
[ -n "$DIST_DIR" ] || DIST_DIR="$DIST_DIR_DEFAULT"

# Resolve the base URL exactly as scripts/install.sh does: a bare host gets
# https://; anything already carrying a scheme is used verbatim (so a local
# `wrangler pages dev` over plain http can be targeted).
case "$CP_HOST" in
    *://*) BASE="$CP_HOST" ;;
    *)     BASE="https://$CP_HOST" ;;
esac
BASE="${BASE%/}"

MANIFEST_URL="$BASE/api/dist/manifest?version=latest"
INSTALLER_URL="$BASE/install.sh"

# ---------------------------------------------------------------------------
# The key — environment only, never argv, never echoed.
# ---------------------------------------------------------------------------
KEY="${S0MA_SMOKE_KEY:-}"
[ -n "$KEY" ] || die "no smoke key. Set the S0MA_SMOKE_KEY environment variable to a live tester license key (it is never a command-line argument — arguments are world-readable via 'ps'). Provision the smoke tester and store its key as described in docs/hosting-getting-started.md section 5, then re-run: S0MA_SMOKE_KEY=<key> $PROG --version $VERSION"

# ---------------------------------------------------------------------------
# Tooling.
# ---------------------------------------------------------------------------
command -v curl >/dev/null 2>&1 || die "'curl' is required (every request this script makes)."
command -v python3 >/dev/null 2>&1 || die "'python3' is required (stdlib JSON parsing — no jq dependency, matching the rest of the release tooling)."
command -v diff >/dev/null 2>&1 || die "'diff' is required (the served-vs-canonical installer comparison)."
[ -f "$CANON_INSTALLER" ] || die "the canonical installer is missing at $CANON_INSTALLER — run this script from a checkout of the s0ma repo."
if ! command -v sha256sum >/dev/null 2>&1 && ! command -v shasum >/dev/null 2>&1; then
    # Checked up front, not at first use: every byte comparison below needs
    # it, so a missing hasher is a refusal, never a half-finished report.
    die "no sha256 tool found (need 'sha256sum' or 'shasum')."
fi

sha256_of() {
    if command -v sha256sum >/dev/null 2>&1; then
        sha256sum "$1" | awk '{print $1}'
    elif command -v shasum >/dev/null 2>&1; then
        shasum -a 256 "$1" | awk '{print $1}'
    else
        die "no sha256 tool found (need 'sha256sum' or 'shasum')."
    fi
}

# ---------------------------------------------------------------------------
# Scratch dir + the Authorization header file.
#
# The key must never ride any process argv, so the header is written by the
# SHELL via a here-doc (no helper process ever holds it) into a 0600 file in
# the 0700 scratch dir, and handed to curl as `-H @file` (curl >= 7.55). The
# INT/TERM traps route interrupts through `exit` so the EXIT trap always runs.
# ---------------------------------------------------------------------------
_tmpd="$(mktemp -d "${TMPDIR:-/tmp}/s0ma-verify.XXXXXX")" || \
    die "could not create a temporary directory under ${TMPDIR:-/tmp}"
trap 'rm -rf "$_tmpd"' EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

_hdrf="$_tmpd/hdr"
cat >"$_hdrf" <<S0MA_HDR_EOF
Authorization: Bearer $KEY
S0MA_HDR_EOF
chmod 600 "$_hdrf"

# ---------------------------------------------------------------------------
# Pass / fail / drift tally. `bad` and `drift` record a failure CLASS; the
# final verdict picks the exit code from what was recorded.
# ---------------------------------------------------------------------------
PASS=0
FAIL=0
DRIFT=0
FAILED_CLASSES=""

ok()   { PASS=$((PASS + 1)); printf '  PASS: %s\n' "$1"; }
skip() { printf '  SKIP: %s\n' "$1"; }
hr()   { printf '\n=== %s ===\n' "$1"; }

bad() {
    # $1 = exit class, $2 = message.
    FAIL=$((FAIL + 1))
    FAILED_CLASSES="$FAILED_CLASSES $1"
    printf '  FAIL: %s\n' "$2" >&2
}

drift() {
    # The non-fatal class: counted, reported, but never a red CI job.
    DRIFT=1
    printf '  DRIFT: %s\n' "$1" >&2
}

# Fetch $1 into file $2. $3 is "keyed" (send the Bearer header) or "public".
# Prints the HTTP status, or 000 when the host could not be reached at all.
http_get() {
    _url="$1"; _out="$2"; _auth="$3"
    if [ "$_auth" = keyed ]; then
        _code="$(curl -sSL -o "$_out" -w '%{http_code}' -H @"$_hdrf" "$_url" 2>/dev/null || true)"
    else
        _code="$(curl -sSL -o "$_out" -w '%{http_code}' "$_url" 2>/dev/null || true)"
    fi
    # curl writes its %{http_code} even for a failed transfer (as 000), and
    # writes nothing at all if it dies earlier. Normalise both, so callers
    # only ever see three digits.
    case "$_code" in
        [0-9][0-9][0-9]) printf '%s' "$_code" ;;
        *)               printf '000' ;;
    esac
}

# Extract the value of a JSON string field ($2) from a response body file
# ($1) — the install.sh idiom, pinned to our own D-5 error shape rather than
# being a general JSON parser.
json_field() {
    sed -n 's/.*"'"$2"'"[[:space:]]*:[[:space:]]*"\([^"]*\)".*/\1/p' "$1" | head -n 1
}

# Describe a control-plane error body the way the installer does: the D-5
# `code` plus `remediation`, so the operator sees WHY, not just a status.
# Prints one line-fragment with NO trailing newline (call sites embed it).
describe_error() {
    _err_body="$1"
    _err_code="$(json_field "$_err_body" code)"
    _err_rem="$(json_field "$_err_body" remediation)"
    [ -n "$_err_code" ] || _err_code="(no structured code in the response body)"
    printf '%s' "$_err_code"
    if [ -n "$_err_rem" ]; then
        printf ' — remediation: %s' "$_err_rem"
    fi
}

printf '########################################################\n'
printf '# s0ma served-release verification (RP-M3)\n'
printf '#   control plane: %s\n' "$BASE"
printf '#   expected latest: %s\n' "$VERSION"
printf '#   local wheels: %s\n' "$DIST_DIR"
printf '#   key: from S0MA_SMOKE_KEY (never printed)\n'
printf '########################################################\n'

# ===========================================================================
# 1. The manifest: fetched with the key, `latest` resolves to $VERSION, and
#    the wheel list is exactly the four distributions with sha256s.
# ===========================================================================
hr "1. manifest (entitlement-gated)"
printf '+ curl -sSL -H "Authorization: Bearer ***" "%s"\n' "$MANIFEST_URL"

MANIFEST_BODY="$_tmpd/manifest.json"
MANIFEST_STATUS="$(http_get "$MANIFEST_URL" "$MANIFEST_BODY" keyed)"
MANIFEST_USABLE=0

case "$MANIFEST_STATUS" in
    200)
        ok "the control plane answered the manifest request (HTTP 200)"
        MANIFEST_USABLE=1 ;;
    000)
        bad "$EXIT_MANIFEST" "could not reach the control plane at $BASE (no HTTP response). Check the host and your network." ;;
    401)
        bad "$EXIT_MANIFEST" "the control plane rejected the smoke key (HTTP 401: $(describe_error "$MANIFEST_BODY")). Check that S0MA_SMOKE_KEY holds a current key for a live tester account." ;;
    403)
        bad "$EXIT_MANIFEST" "the smoke key is known but not entitled (HTTP 403: $(describe_error "$MANIFEST_BODY")). The tester account was revoked, expired, or deactivated — re-provision it." ;;
    *)
        bad "$EXIT_MANIFEST" "the manifest request returned HTTP $MANIFEST_STATUS ($(describe_error "$MANIFEST_BODY"))." ;;
esac

MAN_FACTS="$_tmpd/manifest-facts.txt"
WHEEL_ROWS="$_tmpd/manifest-wheels.txt"
: > "$MAN_FACTS"
: > "$WHEEL_ROWS"

if [ "$MANIFEST_USABLE" -eq 1 ]; then
    # Flatten the H4 response into whitespace-free rows the shell can read:
    #   version <resolved-version>
    #   wheel <name> <path> <sha256>
    # Parsing lives in python3 (stdlib) for the same reason the mirror's
    # manifest merge does: no jq dependency, identical locally and in CI.
    if ! python3 - "$MANIFEST_BODY" >"$MAN_FACTS" 2>"$_tmpd/manifest-parse.err" <<'PY'
import json
import sys

path = sys.argv[1]
try:
    with open(path, encoding="utf-8") as fh:
        doc = json.load(fh)
except (OSError, ValueError) as exc:
    sys.exit(f"the response is not valid JSON ({exc})")

if not isinstance(doc, dict):
    sys.exit("the response is not a JSON object")

version = doc.get("version")
print("version " + (version.strip() if isinstance(version, str) else ""))

wheels = doc.get("wheels")
if not isinstance(wheels, list):
    sys.exit("the response carries no 'wheels' list")

for entry in wheels:
    if not isinstance(entry, dict):
        sys.exit("a 'wheels' entry is not a JSON object")
    fields = []
    for key in ("name", "path", "sha256"):
        value = entry.get(key)
        value = value.strip() if isinstance(value, str) else ""
        if any(ch.isspace() for ch in value):
            sys.exit(f"a wheel entry's {key!r} contains whitespace: {value!r}")
        fields.append(value or "-")
    print("wheel " + " ".join(fields))
PY
    then
        bad "$EXIT_MANIFEST" "the manifest response could not be read: $(tr -d '\n' < "$_tmpd/manifest-parse.err")"
        MANIFEST_USABLE=0
    fi
fi

if [ "$MANIFEST_USABLE" -eq 1 ]; then
    SERVED_VERSION="$(sed -n 's/^version //p' "$MAN_FACTS" | head -n 1)"
    if [ "$SERVED_VERSION" = "$VERSION" ]; then
        ok "\`latest\` resolves to $VERSION — the version this run asked about"
    elif [ -z "$SERVED_VERSION" ]; then
        bad "$EXIT_LATEST" "the manifest response names no version at all, so prod cannot be shown to serve $VERSION."
    else
        bad "$EXIT_LATEST" "the control plane serves latest=$SERVED_VERSION, not $VERSION. The mirror step either did not run for this tag or wrote an older version."
    fi

    grep '^wheel ' "$MAN_FACTS" > "$WHEEL_ROWS" || true
    WHEEL_COUNT="$(wc -l < "$WHEEL_ROWS" | tr -d '[:space:]')"
    if [ "$WHEEL_COUNT" = "$EXPECTED_WHEEL_COUNT" ]; then
        ok "the manifest lists exactly $EXPECTED_WHEEL_COUNT wheels"
    else
        bad "$EXIT_WHEEL_LIST" "the manifest lists $WHEEL_COUNT wheels, expected $EXPECTED_WHEEL_COUNT (one per distribution: $WHEEL_STEMS)."
    fi

    # One entry per distribution, each carrying a sha256 — a manifest without
    # hashes cannot be verified by the installer at all.
    for stem in $WHEEL_STEMS; do
        _row="$(grep "^wheel ${stem}-" "$WHEEL_ROWS" | head -n 1 || true)"
        if [ -z "$_row" ]; then
            bad "$EXIT_WHEEL_LIST" "the manifest names no wheel for $stem — a keyed install of $VERSION would fail on the missing distribution."
            continue
        fi
        _sha="$(printf '%s' "$_row" | awk '{print $4}')"
        if [ "$_sha" = "-" ] || [ -z "$_sha" ]; then
            bad "$EXIT_WHEEL_LIST" "the manifest entry for $stem carries no sha256, so its download cannot be verified."
        else
            ok "$stem is listed with a sha256"
        fi
    done
else
    skip "the version and wheel-list checks — there is no usable manifest to read"
fi

# ===========================================================================
# 2. The wheels: download each one and compare bytes against the manifest's
#    sha256 and, when present, the locally built wheel.
# ===========================================================================
hr "2. wheels (download + sha256)"
if [ ! -s "$WHEEL_ROWS" ]; then
    skip "the wheel downloads — the manifest named none to fetch"
else
    [ -d "$DIST_DIR" ] || skip "every local comparison — the wheel directory $DIST_DIR does not exist"
    # Read from a FILE, not a pipe: a `| while` runs in a subshell and the
    # tallies incremented inside the loop would be lost (smoke_hosting.sh
    # step 6 documents the same gotcha).
    while read -r _kind _name _path _sha; do
        [ "$_kind" = "wheel" ] || continue
        if [ "$_name" = "-" ] || [ "$_path" = "-" ]; then
            bad "$EXIT_WHEEL_LIST" "a manifest wheel entry is missing its name or its path, so it cannot be downloaded at all."
            continue
        fi
        _out="$_tmpd/served-$_name"
        printf '+ curl -sSL -H "Authorization: Bearer ***" "%s/%s"\n' "$BASE" "$_path"
        _status="$(http_get "$BASE/$_path" "$_out" keyed)"
        if [ "$_status" != "200" ]; then
            bad "$EXIT_WHEEL_BYTES" "$_name could not be downloaded (HTTP $_status: $(describe_error "$_out"))."
            continue
        fi
        _got="$(sha256_of "$_out")"
        if [ "$_sha" = "-" ]; then
            skip "$_name — the manifest carried no sha256 to compare (already reported above)"
        elif [ "$_got" = "$_sha" ]; then
            ok "$_name downloaded and matches the manifest sha256"
        else
            bad "$EXIT_WHEEL_BYTES" "$_name does NOT match the manifest sha256 — manifest says $_sha, the served bytes hash to $_got. Every install of $VERSION would abort on this."
            continue
        fi

        _local="${DIST_DIR%/}/$_name"
        if [ -f "$_local" ]; then
            _local_sha="$(sha256_of "$_local")"
            if [ "$_local_sha" = "$_got" ]; then
                ok "$_name is byte-identical to the wheel built here"
            else
                bad "$EXIT_WHEEL_BYTES" "$_name differs from the wheel built here — local $_local_sha, served $_got. Prod is serving different bytes than this checkout produces."
            fi
        else
            skip "$_name — no local copy in $DIST_DIR to compare against"
        fi
    done < "$WHEEL_ROWS"
fi

# ===========================================================================
# 3. The installer: the published one-liner's source, compared against canon.
#    Public (no key): https://<host>/install.sh is what testers curl.
# ===========================================================================
hr "3. installer (served vs canonical scripts/install.sh)"
printf '+ curl -sSL "%s"\n' "$INSTALLER_URL"
SERVED_INSTALLER="$_tmpd/served-install.sh"
INSTALLER_STATUS="$(http_get "$INSTALLER_URL" "$SERVED_INSTALLER" public)"

if [ "$INSTALLER_STATUS" != "200" ]; then
    bad "$EXIT_INSTALLER_FETCH" "the published installer at $INSTALLER_URL could not be fetched (HTTP $INSTALLER_STATUS). That URL is the one-liner every tester runs, so this is a broken install path, not a drift."
else
    # The served copy is the canonical script plus a trailing DRIFT NOTE
    # comment block. Strip that block — the "# ====" banner sits directly
    # above the DRIFT NOTE line, and a single blank line separates it from
    # the script body — and compare the rest byte-for-byte. A served copy
    # with no note at all is compared whole (the same idiom as
    # scripts/smoke_hosting.sh step 0, hardened for the no-note case).
    TRIMMED="$_tmpd/served-install.trimmed.sh"
    awk '
        { lines[NR] = $0 }
        /^# DRIFT NOTE/ { note = NR }
        END {
            stop = note ? note - 2 : NR + 1
            for (i = 1; i < stop; i++) print lines[i]
        }
    ' "$SERVED_INSTALLER" > "$TRIMMED"

    if diff -u "$CANON_INSTALLER" "$TRIMMED" > "$_tmpd/installer.diff" 2>&1; then
        ok "the served installer matches scripts/install.sh (modulo its trailing DRIFT NOTE)"
    else
        drift "CP deploy pending — served installer differs from canon"
        printf '         The installer served at %s is not the scripts/install.sh in this\n' "$INSTALLER_URL" >&2
        printf '         checkout. Control-plane deploys are manual (hardening plan R10/R11):\n' >&2
        printf '         deploy the control-plane site, then re-run this check. The wheels and\n' >&2
        printf '         the manifest above are unaffected. First lines of the difference:\n' >&2
        head -n 40 "$_tmpd/installer.diff" | sed 's/^/           /' >&2
    fi
fi

# ===========================================================================
# Verdict. One line, naming the class a caller can route on.
# ===========================================================================
hr "SUMMARY"
printf '  PASS: %d\n  FAIL: %d\n' "$PASS" "$FAIL"
if [ "$DRIFT" -eq 1 ]; then
    printf '  DRIFT: 1 (served installer — the non-fatal class)\n'
fi

# The lowest FATAL class wins; the drift class is the verdict only when
# nothing else failed.
EXIT_CODE=0
for _class in "$EXIT_MANIFEST" "$EXIT_LATEST" "$EXIT_WHEEL_LIST" "$EXIT_WHEEL_BYTES" "$EXIT_INSTALLER_FETCH"; do
    case " $FAILED_CLASSES " in
        *" $_class "*)
            EXIT_CODE="$_class"
            break ;;
    esac
done
if [ "$EXIT_CODE" -eq 0 ] && [ "$DRIFT" -eq 1 ]; then
    EXIT_CODE="$EXIT_DRIFT"
fi

case "$EXIT_CODE" in
    0)
        printf '\nVERDICT: PASS — %s serves %s: manifest, all four wheels, and the installer match what this checkout built.\n' \
            "$BASE" "$VERSION" ;;
    "$EXIT_DRIFT")
        printf '\nVERDICT: CP DEPLOY PENDING (exit %s) — the release verified: %s serves %s and every wheel matches. Only the served installer differs from canon; deploy the control-plane site to close it.\n' \
            "$EXIT_CODE" "$BASE" "$VERSION" >&2 ;;
    "$EXIT_MANIFEST")
        printf '\nVERDICT: FAILED (exit %s) — the control plane did not return a usable manifest (reachability, key, or response shape). %d checks passed, %d failed.\n' \
            "$EXIT_CODE" "$PASS" "$FAIL" >&2 ;;
    "$EXIT_LATEST")
        printf '\nVERDICT: FAILED (exit %s) — %s does not serve %s as latest, so a keyed install would get a different release. %d checks passed, %d failed.\n' \
            "$EXIT_CODE" "$BASE" "$VERSION" "$PASS" "$FAIL" >&2 ;;
    "$EXIT_WHEEL_LIST")
        printf '\nVERDICT: FAILED (exit %s) — the served manifest is not the expected %s sha256-bearing wheel entries. %d checks passed, %d failed.\n' \
            "$EXIT_CODE" "$EXPECTED_WHEEL_COUNT" "$PASS" "$FAIL" >&2 ;;
    "$EXIT_WHEEL_BYTES")
        printf '\nVERDICT: FAILED (exit %s) — at least one served wheel is missing or does not match the bytes it should. %d checks passed, %d failed.\n' \
            "$EXIT_CODE" "$PASS" "$FAIL" >&2 ;;
    "$EXIT_INSTALLER_FETCH")
        printf '\nVERDICT: FAILED (exit %s) — the published installer could not be fetched from %s. %d checks passed, %d failed.\n' \
            "$EXIT_CODE" "$BASE" "$PASS" "$FAIL" >&2 ;;
esac

exit "$EXIT_CODE"
