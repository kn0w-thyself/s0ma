#!/usr/bin/env bash
#
# s0ma release -> R2 wheel-mirror (hosting & entitlement plan, HOST-H5).
#
# On each s0ma release, this mirrors the four built wheels plus a single
# `manifest.json` into the Cloudflare R2 bucket `s0ma-dist`, in the EXACT
# object layout the control-plane distribution endpoint (HOST-H4) serves. So
# cutting a release makes it installable through the keyed control plane with
# no manual uploads.
#
# This is RELEASE/CI TOOLING ONLY. No workspace package (s0ma-core, s0ma-dsl,
# s0ma-mcp, s0ma-studi0) imports or invokes it (plan D-1: no network in product
# code). It is called from `.github/workflows/release.yml` on a real tag
# release, and is runnable locally for inspection via --dry-run.
#
# ---------------------------------------------------------------------------
# R2 object layout (the HOST-H4 contract — match byte-for-shape)
# ---------------------------------------------------------------------------
# Bucket: s0ma-dist. Everything under the `dist/` key prefix:
#
#   dist/<version>/<wheel>.whl   one object per wheel (immutable once written)
#   dist/manifest.json           the single source of truth, this NESTED shape:
#
#     {
#       "latest": "0.9.0",
#       "versions": {
#         "0.9.0": {
#           "wheels": [
#             { "name": "s0ma_core-0.9.0-py3-none-any.whl",
#               "path": "dist/0.9.0/s0ma_core-0.9.0-py3-none-any.whl",
#               "sha256": "<lowercase-hex>", "size": <bytes> },
#             ... s0ma_dsl, s0ma_mcp, s0ma_studi0 ...
#           ]
#         }
#       }
#     }
#
#   sha256 = lowercase hex of the wheel bytes; size = byte count;
#   path   = full R2 key (with the `dist/` prefix).
#
# ---------------------------------------------------------------------------
# Idempotent + immutable
# ---------------------------------------------------------------------------
# Releases are immutable: a `dist/<version>/` directory is mirrored exactly
# once. On a re-run the wheel uploads are SKIPPED (never overwritten) — but
# only after fetching each already-mirrored wheel back from R2 and comparing
# its sha256 against the local --dist-dir file. A missing or byte-different
# wheel ABORTS the run before the manifest is touched (review INF-2): the
# manifest must describe the exact bytes R2 serves, or install-time sha256
# verification hard-fails that version for every user. To deliberately
# replace a mirrored release (e.g. a rebuilt artifact), pass
# --force-overwrite, which rewrites all four wheel objects together with the
# manifest.
#
# The ONLY mutation a clean re-run performs is rewriting `dist/manifest.json`
# — it reads the existing manifest, adds or refreshes `versions["<version>"]`,
# sets top-level `latest` to <version>, and writes it back, so prior versions
# are always preserved.
#
# ---------------------------------------------------------------------------
# Forward-only `latest` (plan RD-5)
# ---------------------------------------------------------------------------
# The manifest's top-level `latest` is what every keyed install resolves when
# it asks for "latest" (`/api/dist/manifest?version=latest`). Mirroring an
# OLDER version than R2 currently serves would silently downgrade every new
# install — and a historical tag push is enough to do it by accident. So
# before anything is written, the target version is compared against the
# remote manifest's `latest` (semver, numeric per component: 0.10.0 is NEWER
# than 0.9.0) and the run ABORTS if the target is older. Re-mirroring the
# SAME version is fine — that is the verify-back path above.
#
# `--allow-latest-downgrade` is the deliberate override, and it is also THE
# documented rollback mechanism: to put prod back on a known-good release,
# re-mirror that version with the flag. Wheel objects are untouched by this
# rule — they stay immutable, and a rollback moves only the manifest pointer.
#
# ---------------------------------------------------------------------------
# Upload mechanism + credentials (OWNER ACTION)
# ---------------------------------------------------------------------------
# Uploads use `wrangler r2 object put` (the Wrangler CLI), for consistency with
# the control-plane (kts-website-3) stack, which already binds this same bucket
# as `DIST` and uses Wrangler/Cloudflare end to end. Auth is the standard
# Wrangler env var `CLOUDFLARE_API_TOKEN` (this script also accepts the
# GH-secret alias `CF_API_TOKEN` and exports it as `CLOUDFLARE_API_TOKEN`).
#
# OWNER must set, in the s0ma-new repo's GitHub Actions secrets:
#   CF_API_TOKEN  — a Cloudflare **User API Token** (My Profile -> API
#                   Tokens -> Create Custom Token) with:
#                       Account -> Workers R2 Storage -> Edit
#
#                   VERIFIED 2026-08-18, the hard way: tokens minted from the
#                   R2 dashboard's "Manage R2 API Tokens" DO NOT WORK here,
#                   even showing "Object Read & Write" on the right bucket.
#                   That flow issues S3-compatible credentials; its bearer
#                   value authenticates as a token but carries no Workers R2
#                   Storage permission the Cloudflare REST API honours, and
#                   `wrangler r2 object put` is REST. The symptom is a
#                   uniform 403 {"code":10000,"message":"Authentication
#                   error"} on EVERY r2 REST call - read and write, bucket
#                   and account level - while /user/tokens/verify says the
#                   token is valid and active.
#
#                   This is account-wide across R2, which is broader than
#                   plan D-8's bucket-only intent. D-8 as written is not
#                   achievable through this code path. Accepted because
#                   `s0ma-dist` is the account's only R2 bucket, so the
#                   practical exposure is identical.
#
#                   Verify a candidate token before trusting it:
#                     curl -H "Authorization: Bearer $CF_API_TOKEN" \
#                       https://api.cloudflare.com/client/v4/accounts/<acct>/r2/buckets
#                   Account-owned (cfat_) tokens verify at
#                   /accounts/<acct>/tokens/verify; user-owned (cfut_) ones at
#                   /user/tokens/verify. Using the wrong one reports a
#                   perfectly good token as invalid.
# The CI job passes it through as CLOUDFLARE_API_TOKEN. This script NEVER
# embeds a token and NEVER performs a real upload in --dry-run.
#
# Usage:
#   scripts/mirror_to_r2.sh --version <ver> --dist-dir <dir> [--bucket <name>]
#                           [--dry-run] [--force-overwrite]
#                           [--allow-latest-downgrade]
#                           [--existing-manifest <file>]
#
#   --version <ver>   Release version, e.g. 0.9.0 (required).
#   --dist-dir <dir>  Directory holding the four built wheels (required).
#                     Expects <stem>-<version>-py3-none-any.whl for each of
#                     s0ma_core / s0ma_dsl / s0ma_mcp / s0ma_studi0.
#   --bucket <name>   R2 bucket. Default: s0ma-dist (the H4 contract).
#   --dry-run         Print the exact objects that WOULD be written (keys +
#                     sha256 + size, in H4 layout) and the manifest JSON that
#                     would be produced, then exit. Makes NO network calls.
#   --force-overwrite DELIBERATELY replace an already-mirrored version:
#                     rewrite all four dist/<version>/ wheel objects from
#                     --dist-dir even though they exist in R2, then the
#                     manifest. Only for intentional artifact replacement;
#                     immutable-once-written is the default contract.
#   --allow-latest-downgrade
#                     Permit this run to move the manifest's `latest` BACK to
#                     an older version. Refused by default (see "Forward-only
#                     `latest`" above); this flag is the deliberate rollback
#                     mechanism.
#   --existing-manifest <file>
#                     --dry-run ONLY: treat <file> as the manifest R2
#                     currently serves instead of fetching it. Previews the
#                     real merge and evaluates the forward-only guard
#                     offline (a refused downgrade exits non-zero). Rejected
#                     without --dry-run, so a real run can never mirror
#                     against a hand-written manifest.
#   -h, --help        Show this help and exit.

set -euo pipefail

# ---------------------------------------------------------------------------
# Constants.
# ---------------------------------------------------------------------------
BUCKET_DEFAULT="s0ma-dist"
DIST_PREFIX="dist"
MANIFEST_KEY="dist/manifest.json"
# The four wheels, by distribution stem (digit-zero s0ma — INV-1).
WHEEL_STEMS="s0ma_core s0ma_dsl s0ma_mcp s0ma_studi0"

PROG="$(basename "$0")"

usage() {
    # Print the "# Usage:" block of the header comment, marker-delimited: a
    # hardcoded line range silently rots as the header above it grows (it
    # had, and printed the credentials notes instead).
    # (grep '^#' drops the terminator line the sed range ends on)
    sed -n '/^# Usage:/,/^[^#]/p' "$0" | grep '^#' | sed 's/^# \{0,1\}//'
}

die() {
    printf '%s: error: %s\n' "$PROG" "$1" >&2
    exit 1
}

# ---------------------------------------------------------------------------
# Argument parsing.
# ---------------------------------------------------------------------------
VERSION=""
DIST_DIR=""
BUCKET=""
DRY_RUN=0
FORCE_OVERWRITE=0
ALLOW_LATEST_DOWNGRADE=0
EXISTING_MANIFEST_FILE=""

while [ $# -gt 0 ]; do
    case "$1" in
        --version)
            [ $# -ge 2 ] || die "--version needs an argument (e.g. --version 0.9.0)"
            VERSION="$2"; shift 2 ;;
        --version=*)
            VERSION="${1#--version=}"; shift ;;
        --dist-dir)
            [ $# -ge 2 ] || die "--dist-dir needs a directory argument"
            DIST_DIR="$2"; shift 2 ;;
        --dist-dir=*)
            DIST_DIR="${1#--dist-dir=}"; shift ;;
        --bucket)
            [ $# -ge 2 ] || die "--bucket needs an argument"
            BUCKET="$2"; shift 2 ;;
        --bucket=*)
            BUCKET="${1#--bucket=}"; shift ;;
        --dry-run)
            DRY_RUN=1; shift ;;
        --force-overwrite)
            FORCE_OVERWRITE=1; shift ;;
        --allow-latest-downgrade)
            ALLOW_LATEST_DOWNGRADE=1; shift ;;
        --existing-manifest)
            [ $# -ge 2 ] || die "--existing-manifest needs a file argument"
            EXISTING_MANIFEST_FILE="$2"; shift 2 ;;
        --existing-manifest=*)
            EXISTING_MANIFEST_FILE="${1#--existing-manifest=}"; shift ;;
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

[ -n "$VERSION" ]  || die "a release version is required. Pass it with --version <ver> (e.g. 0.9.0)."
[ -n "$DIST_DIR" ] || die "a wheel directory is required. Pass it with --dist-dir <dir>."
[ -d "$DIST_DIR" ] || die "wheel directory does not exist: $DIST_DIR"
[ -n "$BUCKET" ]   || BUCKET="$BUCKET_DEFAULT"

if [ -n "$EXISTING_MANIFEST_FILE" ]; then
    [ "$DRY_RUN" -eq 1 ] || die "--existing-manifest is --dry-run only: a real mirror always reads the live manifest from R2, never a local file."
    [ -f "$EXISTING_MANIFEST_FILE" ] || die "--existing-manifest file does not exist: $EXISTING_MANIFEST_FILE"
fi

# ---------------------------------------------------------------------------
# Tooling: sha256 (portable) and python3 (for JSON merge — stdlib only).
# ---------------------------------------------------------------------------
sha256_of() {
    if command -v sha256sum >/dev/null 2>&1; then
        sha256sum "$1" | awk '{print $1}'
    elif command -v shasum >/dev/null 2>&1; then
        shasum -a 256 "$1" | awk '{print $1}'
    else
        die "no sha256 tool found (need 'sha256sum' or 'shasum')."
    fi
}

command -v python3 >/dev/null 2>&1 || die "'python3' is required (stdlib JSON merge)."

# ---------------------------------------------------------------------------
# Resolve the four wheels for this version, compute sha256 + size, and build
# the manifest "wheels" array for <version> in the exact H4 shape.
#
# Emits, to the two named variables below:
#   WHEELS_TSV   one line per wheel: <name>\t<path>\t<sha256>\t<size>\t<local>
#   WHEELS_JSON  the JSON array literal for versions["<version>"].wheels
# ---------------------------------------------------------------------------
WHEELS_TSV=""
WHEELS_JSON=""

build_wheel_facts() {
    _json_items=""
    for _stem in $WHEEL_STEMS; do
        _name="${_stem}-${VERSION}-py3-none-any.whl"
        _local="${DIST_DIR%/}/${_name}"
        _key="${DIST_PREFIX}/${VERSION}/${_name}"
        [ -f "$_local" ] || die "wheel not found: $_local (expected $_name in --dist-dir)"
        _sha="$(sha256_of "$_local")"
        _size="$(wc -c < "$_local" | tr -d '[:space:]')"
        WHEELS_TSV="${WHEELS_TSV}${_name}	${_key}	${_sha}	${_size}	${_local}
"
        # JSON object for this wheel (compact, stable field order matching H4).
        _obj="    { \"name\": \"${_name}\", \"path\": \"${_key}\", \"sha256\": \"${_sha}\", \"size\": ${_size} }"
        if [ -z "$_json_items" ]; then
            _json_items="$_obj"
        else
            _json_items="${_json_items},
${_obj}"
        fi
    done
    WHEELS_JSON="[
${_json_items}
  ]"
}

build_wheel_facts

# ---------------------------------------------------------------------------
# Merge the new version into the manifest. Reads $1 (existing manifest JSON, or
# empty for a fresh manifest), adds/updates versions["<version>"], sets the
# top-level "latest" to <version>, and prints the merged manifest to stdout.
# Pure Python stdlib (no jq), so it runs identically locally and in CI.
# ---------------------------------------------------------------------------
merge_manifest() {
    _existing="$1"
    VERSION="$VERSION" WHEELS_JSON="$WHEELS_JSON" EXISTING="$_existing" \
        python3 - <<'PY'
import json
import os
import sys

version = os.environ["VERSION"]
wheels = json.loads(os.environ["WHEELS_JSON"])
existing_raw = os.environ.get("EXISTING", "").strip()

if existing_raw:
    try:
        manifest = json.loads(existing_raw)
    except json.JSONDecodeError as exc:  # corrupt remote manifest -> fail loud
        sys.exit(f"existing manifest is not valid JSON: {exc}")
    if not isinstance(manifest, dict):
        sys.exit("existing manifest is not a JSON object")
else:
    manifest = {}

versions = manifest.get("versions")
if not isinstance(versions, dict):
    versions = {}
versions[version] = {"wheels": wheels}

# Reassemble with a stable, H4-matching key order: latest, then versions.
merged = {"latest": version, "versions": versions}
print(json.dumps(merged, indent=2))
PY
}

# ---------------------------------------------------------------------------
# Forward-only `latest` guard (RD-5).
#
# latest_verdict <existing-manifest-json> prints "<verdict>\t<remote latest>":
#
#   none         no manifest, or no usable string `latest` -> nothing to
#                protect (a fresh bucket).
#   greater      target is newer than the served latest  -> normal release.
#   equal        target IS the served latest             -> re-mirror.
#   less         target is OLDER than the served latest  -> DOWNGRADE.
#   unparsable   the served latest is not X.Y.Z-shaped   -> forward motion
#                cannot be proven, so it is treated like a downgrade.
#   corrupt      the served manifest is not JSON at all  -> the merge below
#                could not run either; failing HERE means nothing is written
#                (the wheel uploads have not happened yet).
#
# Comparison is numeric per component, so 0.10.0 > 0.9.0 (a string compare
# gets that backwards, and this guard exists precisely to stop a version from
# going the wrong way).
# ---------------------------------------------------------------------------
latest_verdict() {
    VERSION="$VERSION" EXISTING="$1" python3 - <<'PY'
import json
import os
import sys

target_raw = os.environ["VERSION"]
existing_raw = os.environ.get("EXISTING", "").strip()


def parse(raw):
    parts = raw.split(".")
    if len(parts) != 3 or not all(p.isdigit() for p in parts):
        return None
    return tuple(int(p) for p in parts)


target = parse(target_raw)
if target is None:
    sys.exit(f"--version must be a bare X.Y.Z release version (got {target_raw!r})")

remote = ""
if existing_raw:
    try:
        manifest = json.loads(existing_raw)
    except json.JSONDecodeError as exc:
        print(f"corrupt\t{exc}")
        raise SystemExit(0)
    if isinstance(manifest, dict):
        candidate = manifest.get("latest")
        if isinstance(candidate, str) and candidate.strip():
            remote = candidate.strip()
    else:
        print("corrupt\tthe manifest is not a JSON object")
        raise SystemExit(0)

if not remote:
    print("none\t")
    raise SystemExit(0)

parsed = parse(remote)
if parsed is None:
    verdict = "unparsable"
elif target > parsed:
    verdict = "greater"
elif target == parsed:
    verdict = "equal"
else:
    verdict = "less"
print(f"{verdict}\t{remote}")
PY
}

# Evaluate the guard against $1 (the existing manifest JSON) and either
# report and continue, or ABORT before anything is written.
check_latest_guard() {
    _verdict_line="$(latest_verdict "$1")"
    _verdict="${_verdict_line%%	*}"
    _remote="${_verdict_line#*	}"
    case "$_verdict" in
        none)
            printf '==> latest guard: the remote manifest names no `latest` yet — nothing to protect\n' ;;
        greater)
            printf '==> latest guard: %s is newer than the served latest %s — forward, ok\n' \
                "$VERSION" "$_remote" ;;
        equal)
            printf '==> latest guard: %s IS the served latest — re-mirror, latest unchanged\n' \
                "$VERSION" ;;
        less)
            [ "$ALLOW_LATEST_DOWNGRADE" -eq 1 ] || die "refusing to move \`latest\` BACKWARDS: R2 currently serves latest=$_remote, and this run would set latest=$VERSION.
Every keyed install that resolves \"latest\" would silently downgrade to the older release. Nothing was written.
If this is a deliberate rollback, re-run with --allow-latest-downgrade — that flag IS the documented rollback mechanism (wheel objects stay immutable; only the manifest pointer moves). Otherwise mirror $_remote or newer."
            printf '==> --allow-latest-downgrade: DELIBERATE ROLLBACK, moving latest %s -> %s\n' \
                "$_remote" "$VERSION" ;;
        unparsable)
            [ "$ALLOW_LATEST_DOWNGRADE" -eq 1 ] || die "cannot prove this mirror moves \`latest\` forward: the remote manifest's latest is \"$_remote\", which is not an X.Y.Z version, so it cannot be compared with $VERSION. Nothing was written.
Inspect dist/manifest.json in bucket $BUCKET. If setting latest=$VERSION is what you intend, re-run with --allow-latest-downgrade."
            printf '==> --allow-latest-downgrade: uncomparable served latest %s -> setting %s\n' \
                "$_remote" "$VERSION" ;;
        corrupt)
            # No override: the merge step could not read it either, so there
            # is no safe way to preserve the other versions it lists.
            die "the manifest in bucket $BUCKET is not valid JSON, so \`latest\` cannot be checked and the merge would lose every version it lists: $_remote
Nothing was written. Fetch dist/manifest.json, repair it (or restore a known-good copy), then re-run." ;;
        *)
            die "internal error: unknown latest-guard verdict '$_verdict'" ;;
    esac
}

# ---------------------------------------------------------------------------
# Pretty-print the object plan (keys + sha256 + size) shared by dry-run and the
# real run's audit log.
# ---------------------------------------------------------------------------
print_object_plan() {
    printf '# R2 bucket: %s\n' "$BUCKET"
    printf '# objects to write (HOST-H4 layout, key prefix "%s/"):\n' "$DIST_PREFIX"
    printf '%s' "$WHEELS_TSV" | while IFS='	' read -r _name _key _sha _size _local; do
        [ -n "$_name" ] || continue
        printf '#   %s\n' "$_key"
        printf '#       sha256=%s  size=%s bytes  (from %s)\n' "$_sha" "$_size" "$_local"
    done
    printf '#   %s   (merged: latest -> %s, versions[%s] added/updated)\n' \
        "$MANIFEST_KEY" "$VERSION" "$VERSION"
}

# ---------------------------------------------------------------------------
# --dry-run: print the object plan + the manifest that WOULD be produced.
# Makes NO network calls. Without --existing-manifest the remote manifest is
# treated as empty, so the printed manifest shows exactly this release's
# contribution and the forward-only guard has nothing to compare against;
# pass --existing-manifest <file> to preview the real merge and prove the
# guard's verdict offline.
# ---------------------------------------------------------------------------
if [ "$DRY_RUN" -eq 1 ]; then
    printf '# s0ma R2 mirror (dry run) — version %s — NO network calls\n' "$VERSION"
    print_object_plan
    DRY_EXISTING=""
    if [ -n "$EXISTING_MANIFEST_FILE" ]; then
        DRY_EXISTING="$(cat "$EXISTING_MANIFEST_FILE")"
        printf '#\n# forward-only `latest` guard, against --existing-manifest %s:\n' \
            "$EXISTING_MANIFEST_FILE"
        check_latest_guard "$DRY_EXISTING"
        printf '#\n# manifest.json that would be written (the real merge of that file\n'
        printf '# with this release):\n'
    else
        printf '#\n# the forward-only `latest` guard is NOT evaluated here: it compares\n'
        printf '# against the manifest R2 serves, which a dry run never fetches. Pass\n'
        printf '# --existing-manifest <file> to check it offline.\n'
        printf '#\n# manifest.json that would be written (existing remote manifest is\n'
        printf '# read + merged on a real run; shown here for this release alone):\n'
    fi
    merge_manifest "$DRY_EXISTING"
    exit 0
fi

# ---------------------------------------------------------------------------
# Real run (CI). Requires Wrangler + a Cloudflare API token.
# ---------------------------------------------------------------------------
command -v wrangler >/dev/null 2>&1 || die "'wrangler' is not installed (needed for the R2 upload). Install it, then re-run $PROG."

# Accept the GH-secret alias CF_API_TOKEN; Wrangler reads CLOUDFLARE_API_TOKEN.
if [ -z "${CLOUDFLARE_API_TOKEN:-}" ] && [ -n "${CF_API_TOKEN:-}" ]; then
    export CLOUDFLARE_API_TOKEN="$CF_API_TOKEN"
fi
[ -n "${CLOUDFLARE_API_TOKEN:-}" ] || \
    die "no Cloudflare API token. Set CF_API_TOKEN (or CLOUDFLARE_API_TOKEN) — a token scoped to R2 write on bucket $BUCKET only."

# One scratch dir for everything temporary (wheels fetched back for
# verification + the merged manifest), cleaned up on any exit.
SCRATCH="$(mktemp -d)"
trap 'rm -rf "$SCRATCH"' EXIT

r2_put() {
    # $1 = R2 object key, $2 = local file path. Bucket-qualified key form.
    _key="$1"; _file="$2"
    printf '+ wrangler r2 object put %s/%s --file %s --remote\n' "$BUCKET" "$_key" "$_file"
    wrangler r2 object put "$BUCKET/$_key" --file "$_file" --remote
}

r2_get() {
    # $1 = R2 object key. Prints the object to stdout; empty iff R2 said the
    # key does not exist. ANY OTHER failure (auth, network, API error) dies
    # here — an unreadable manifest must never masquerade as an absent one,
    # or the guard would read "fresh bucket, nothing to protect" and the
    # merge would write a manifest listing only this version (F-2 fix;
    # wrangler 4's not-found stderr: "The specified key does not exist.").
    _gerr="$SCRATCH/r2_get.err"
    if wrangler r2 object get "$BUCKET/$1" --pipe --remote 2>"$_gerr"; then
        rm -f "$_gerr"
        return 0
    fi
    if grep -qi "specified key does not exist" "$_gerr"; then
        rm -f "$_gerr"
        return 0
    fi
    printf 'mirror_to_r2.sh: error: could not read %s from bucket %s — a read FAILURE, not an absent object:\n' \
        "$1" "$BUCKET" >&2
    sed 's/^/    /' "$_gerr" >&2
    rm -f "$_gerr"
    die "refusing to treat a failed read as an empty bucket. Nothing was written; fix the read (token? network?) and re-run."
}

r2_exists() {
    # $1 = R2 object key. True (0) if the object exists.
    wrangler r2 object get "$BUCKET/$1" --pipe --remote >/dev/null 2>&1
}

r2_get_to() {
    # $1 = R2 object key, $2 = destination file. True (0) iff the fetch
    # succeeded. Binary-safe (unlike r2_get, which captures into a variable).
    wrangler r2 object get "$BUCKET/$1" --pipe --remote > "$2" 2>/dev/null
}

printf '==> s0ma R2 mirror: bucket %s, version %s\n' "$BUCKET" "$VERSION"
print_object_plan

# --- Forward-only `latest` (RD-5): read the served manifest ONCE, up front,
# and refuse a backwards move before any object is written. The same fetched
# copy is merged at the end of the run. ---
printf '==> reading %s (forward-only latest guard)\n' "$MANIFEST_KEY"
EXISTING_MANIFEST="$(r2_get "$MANIFEST_KEY")"
check_latest_guard "$EXISTING_MANIFEST"

upload_wheels() {
    printf '%s' "$WHEELS_TSV" | while IFS='	' read -r _name _key _sha _size _local; do
        [ -n "$_name" ] || continue
        r2_put "$_key" "$_local"
    done
}

# ---------------------------------------------------------------------------
# Verify an already-mirrored version: fetch each dist/<version>/ wheel back
# from R2 and compare its sha256 against the local --dist-dir file. Dies if
# any wheel is missing or byte-different — rewriting the manifest from local
# wheels that differ from the served objects would make install-time sha256
# verification hard-fail this version for every user (review INF-2). A
# pre-studi0 mirror (three wheels) surfaces here as a MISSING fourth object.
# ---------------------------------------------------------------------------
verify_mirrored_wheels() {
    _remote_tmp="$SCRATCH/remote-wheel"
    _bad=0
    while IFS='	' read -r _name _key _sha _size _local; do
        [ -n "$_name" ] || continue
        if ! r2_get_to "$_key" "$_remote_tmp"; then
            printf '!   %s: MISSING from R2 (partial prior mirror, or the fetch failed)\n' "$_key" >&2
            _bad=1
            continue
        fi
        _remote_sha="$(sha256_of "$_remote_tmp")"
        if [ "$_remote_sha" = "$_sha" ]; then
            printf '#   %s: ok — R2 object matches the local wheel\n' "$_key"
        else
            printf '!   %s: sha256 MISMATCH\n!       local  %s  (%s)\n!       remote %s  (what R2 serves)\n' \
                "$_key" "$_sha" "$_local" "$_remote_sha" >&2
            _bad=1
        fi
    done <<EOF
$WHEELS_TSV
EOF
    [ "$_bad" -eq 0 ] || die "version $VERSION is already mirrored and the local wheels DO NOT match the R2 objects (details above).
dist/<version>/ wheels are immutable: once mirrored they are never overwritten, and dist/manifest.json must describe the exact bytes R2 serves — writing the manifest from these local wheels would make every install of $VERSION fail sha256 verification.
Nothing was written. If you deliberately rebuilt $VERSION and mean to replace the served artifacts, re-run with --force-overwrite (rewrites all four wheel objects and the manifest together); otherwise mirror from the originally-released wheels."
}

# --- Wheels: immutable. Upload only if the version dir is not already there. ---
# Probe the first wheel key as the directory sentinel (all four are written
# together, so its presence means this version was already mirrored). An
# already-mirrored version must byte-match the local wheels before the
# manifest is rewritten; --force-overwrite skips the probe and deliberately
# rewrites the wheel objects instead.
SENTINEL_KEY="$(printf '%s' "$WHEELS_TSV" | sed -n '1p' | cut -f2)"
if [ "$FORCE_OVERWRITE" -eq 1 ]; then
    printf '==> --force-overwrite: rewriting the four wheel objects for %s (immutability override)\n' \
        "$VERSION"
    upload_wheels
elif [ -n "$SENTINEL_KEY" ] && r2_exists "$SENTINEL_KEY"; then
    printf '==> version %s already mirrored (%s exists) — skipping wheel uploads (immutable)\n' \
        "$VERSION" "$SENTINEL_KEY"
    printf '==> verifying the local wheels match the mirrored R2 objects before touching the manifest\n'
    verify_mirrored_wheels
else
    printf '==> uploading the four wheels for %s\n' "$VERSION"
    upload_wheels
fi

# --- Manifest: the only re-run mutation. Merge the copy read above (and
# already checked by the latest guard) -> write back. ---
printf '==> merging dist/manifest.json (latest -> %s)\n' "$VERSION"
MERGED_MANIFEST="$(merge_manifest "$EXISTING_MANIFEST")"

MANIFEST_TMP="$SCRATCH/manifest.json"
printf '%s\n' "$MERGED_MANIFEST" > "$MANIFEST_TMP"
r2_put "$MANIFEST_KEY" "$MANIFEST_TMP"

printf '\n==> Done. Mirrored s0ma %s to R2 bucket %s.\n' "$VERSION" "$BUCKET"
