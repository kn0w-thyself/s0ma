#!/usr/bin/env bash
#
# s0ma release cut — the mechanical half of docs/RELEASING.md
# (plan plans/s0ma-release-pipeline-feedback-1.md, RP-M1 T1).
#
# ---------------------------------------------------------------------------
# What it does (with --write)
# ---------------------------------------------------------------------------
#   1. Preflights: clean tree; on `main` (unless --allow-branch); the target
#      version strictly greater than the current lockstep version; the root
#      `## [Unreleased]` section non-empty; the served changelog mirror in
#      sync; `git` and `uv` on PATH.
#   2. Bumps `version = "..."` in all four packages/*/pyproject.toml, in
#      lockstep (PRD INV-4: one version, one tag, one changelog).
#   3. Carves the root CHANGELOG.md: `## [Unreleased]` becomes
#      `## [X.Y.Z] — <date>` and a fresh, empty `## [Unreleased]` heading is
#      opened above it. Nothing else in the file moves.
#   4. Applies that IDENTICAL carve to the served mirror
#      packages/s0ma-mcp/src/s0ma_mcp/_docs/CHANGELOG.md — the mirrors under
#      `_docs/` must stay byte-identical to their sources (AGENTS.md,
#      "Authored and generated paths"), so the drift gate stays green.
#   5. Refreshes the lockfile: `uv sync --all-packages`.
#   6. PRINTS the exact commit / tag / push commands. It never runs them.
#
# ---------------------------------------------------------------------------
# What it deliberately does NOT do
# ---------------------------------------------------------------------------
#   * It never commits, tags, or pushes. Pushing a `v*` tag IS the release
#     act — it fires .github/workflows/release.yml (build, GitHub Release,
#     R2 mirror). Only the owner performs it, deliberately.
#   * It makes no network calls at all.
#   * It bumps ONLY the four pyproject version lines. The other version
#     sites in docs/RELEASING.md step 2 — the four `__version__` strings,
#     the s0ma-studi0 `.s0ma` module headers, the s0ma-core capstone
#     assertion, the core specification cut at the new version, the
#     documentation-diagnostics test's `RELEASE` line, and
#     version-bearing prose — are printed as the remaining
#     manual steps, together with the three rebuilds, the documentation
#     compose and its five mirror copies, the full `scripts/check.py` gate,
#     and the three commits a cut lands as (docs/RELEASING.md, "The three
#     commits of a cut"). Read that block; the cut is not finished when
#     this script exits.
#
# Dry run is the default: with no --write nothing is written and the full
# edit plan is printed, including every file that would be touched.
#
# Usage:
#   scripts/release_cut.sh --version X.Y.Z [--write] [--allow-branch]
#                          [--date YYYY-MM-DD]
#
#   --version X.Y.Z    The release being cut (required; strict X.Y.Z).
#   --write            Apply the edits. Without it, NOTHING is written.
#   --allow-branch     Allow a cut from a branch other than `main`
#                      (rehearsals, hotfix branches). Off by default.
#   --date YYYY-MM-DD  Date stamped into the changelog heading.
#                      Defaults to today (local time).
#   -h, --help         Show this help and exit.

set -euo pipefail

# Every python3 helper below may print the em dash of a changelog heading;
# pin their stdout encoding so a cp1252-defaulting host (Windows, NFR-7)
# cannot turn that into a UnicodeEncodeError.
export PYTHONIOENCODING="utf-8"

PROG="$(basename "$0")"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

# ---------------------------------------------------------------------------
# Constants — the files this script owns.
# ---------------------------------------------------------------------------
# The four lockstep distributions (digit-zero s0ma — INV-1).
PACKAGES="s0ma-core s0ma-dsl s0ma-mcp s0ma-studi0"
CHANGELOG_REL="CHANGELOG.md"
CHANGELOG_MIRROR_REL="packages/s0ma-mcp/src/s0ma_mcp/_docs/CHANGELOG.md"
# The em dash used by every existing heading (`## [0.17.0] — 2026-08-17`).
EM_DASH="—"

usage() {
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
DATE=""
WRITE=0
ALLOW_BRANCH=0

while [ $# -gt 0 ]; do
    case "$1" in
        --version)
            [ $# -ge 2 ] || die "--version needs an argument (e.g. --version 0.18.0)"
            VERSION="$2"; shift 2 ;;
        --version=*)
            VERSION="${1#--version=}"; shift ;;
        --date)
            [ $# -ge 2 ] || die "--date needs an argument (e.g. --date 2026-08-27)"
            DATE="$2"; shift 2 ;;
        --date=*)
            DATE="${1#--date=}"; shift ;;
        --write)
            WRITE=1; shift ;;
        --allow-branch)
            ALLOW_BRANCH=1; shift ;;
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

[ -n "$VERSION" ] || die "a release version is required. Pass it with --version <X.Y.Z> (e.g. --version 0.18.0)."

case "$VERSION" in
    *[!0-9.]*|.*|*.|*..*)
        die "--version must be a bare X.Y.Z release version (got '$VERSION')." ;;
esac
printf '%s' "$VERSION" | grep -Eq '^[0-9]+\.[0-9]+\.[0-9]+$' || \
    die "--version must be a bare X.Y.Z release version (got '$VERSION')."

if [ -n "$DATE" ]; then
    printf '%s' "$DATE" | grep -Eq '^[0-9]{4}-[0-9]{2}-[0-9]{2}$' || \
        die "--date must be YYYY-MM-DD (got '$DATE')."
else
    DATE="$(date +%Y-%m-%d)"
fi

TAG="v${VERSION}"
HEADING="## [${VERSION}] ${EM_DASH} ${DATE}"

# ---------------------------------------------------------------------------
# Tooling. python3 does every file edit: byte-level read/write (no text-mode
# newline translation, no locale-dependent decode), so a cut is byte-
# predictable on macOS, Linux and the Windows box alike.
# ---------------------------------------------------------------------------
command -v python3 >/dev/null 2>&1 || die "'python3' is required (it performs the file edits)."

CHANGELOG="$ROOT/$CHANGELOG_REL"
CHANGELOG_MIRROR="$ROOT/$CHANGELOG_MIRROR_REL"

# ---------------------------------------------------------------------------
# Structural checks (hard errors in BOTH modes: the repo is not shaped the
# way a cut requires, so there is nothing meaningful to plan or to write).
# ---------------------------------------------------------------------------
PYPROJECTS=""
for _pkg in $PACKAGES; do
    _path="$ROOT/packages/$_pkg/pyproject.toml"
    [ -f "$_path" ] || die "missing $_pkg manifest: $_path"
    PYPROJECTS="${PYPROJECTS}${_path}
"
done
[ -f "$CHANGELOG" ]        || die "missing root changelog: $CHANGELOG"
[ -f "$CHANGELOG_MIRROR" ] || die "missing served changelog mirror: $CHANGELOG_MIRROR"

# Read the single `version = "..."` line from a pyproject (dies if there is
# not exactly one, so a hand-edited manifest can never be half-bumped).
read_pyproject_version() {
    python3 - "$1" <<'PY'
import pathlib
import re
import sys

path = pathlib.Path(sys.argv[1])
text = path.read_bytes().decode("utf-8")
found = re.findall(r'(?m)^version = "([^"]*)"$', text)
if len(found) != 1:
    sys.exit(
        f"{path}: expected exactly one top-level `version = \"...\"` line, "
        f"found {len(found)}"
    )
print(found[0])
PY
}

CURRENT=""
LOCKSTEP_MISMATCH=""
while IFS= read -r _path; do
    [ -n "$_path" ] || continue
    _ver="$(read_pyproject_version "$_path")"
    if [ -z "$CURRENT" ]; then
        CURRENT="$_ver"
    elif [ "$_ver" != "$CURRENT" ]; then
        LOCKSTEP_MISMATCH="${LOCKSTEP_MISMATCH}${_path} = ${_ver} (expected ${CURRENT})
"
    fi
done <<EOF
$PYPROJECTS
EOF

[ -z "$LOCKSTEP_MISMATCH" ] || die "the four packages are NOT on one lockstep version (PRD INV-4):
${LOCKSTEP_MISMATCH}Reconcile them by hand before cutting a release."

# ---------------------------------------------------------------------------
# Changelog helpers.
# ---------------------------------------------------------------------------
# Classify the root `## [Unreleased]` section: prints `missing`, `empty` or
# `nonempty`.
unreleased_state() {
    python3 - "$1" <<'PY'
import pathlib
import re
import sys

text = pathlib.Path(sys.argv[1]).read_bytes().decode("utf-8")
match = re.search(
    r"(?m)^## \[Unreleased\][^\n]*\n(.*?)(?=^## \[|\Z)",
    text,
    flags=re.DOTALL,
)
if match is None:
    print("missing")
elif match.group(1).strip():
    print("nonempty")
else:
    print("empty")
PY
}

# True (0) when the file already carries a `## [<version>]` heading.
changelog_has_version() {
    python3 - "$1" "$2" <<'PY'
import pathlib
import re
import sys

text = pathlib.Path(sys.argv[1]).read_bytes().decode("utf-8")
pattern = rf"(?m)^## \[{re.escape(sys.argv[2])}\]"
sys.exit(0 if re.search(pattern, text) else 1)
PY
}

# Print the first N lines the root changelog would have after the carve
# (dry-run preview; writes nothing).
carve_preview() {
    python3 - "$1" "$2" "$3" "$4" <<'PY'
import pathlib
import re
import sys

path, version, date, lines = sys.argv[1], sys.argv[2], sys.argv[3], int(sys.argv[4])
text = pathlib.Path(path).read_bytes().decode("utf-8")
match = re.search(r"(?m)^## \[Unreleased\][^\n]*$", text)
if match is None:
    sys.exit(f"{path}: no `## [Unreleased]` heading to carve")
carved = (
    text[: match.start()]
    + f"## [Unreleased]\n\n## [{version}] — {date}"
    + text[match.end() :]
)
head = carved[match.start() :].splitlines()[:lines]
for line in head:
    print(line)
PY
}

# Rewrite <file> in place: `## [Unreleased]` -> fresh empty `## [Unreleased]`
# + `## [<version>] — <date>`. Byte-level I/O; only the first heading match
# is touched; every other byte in the file is preserved exactly.
carve_changelog() {
    python3 - "$1" "$2" "$3" <<'PY'
import pathlib
import re
import sys

path = pathlib.Path(sys.argv[1])
version, date = sys.argv[2], sys.argv[3]
text = path.read_bytes().decode("utf-8")
match = re.search(r"(?m)^## \[Unreleased\][^\n]*$", text)
if match is None:
    sys.exit(f"{path}: no `## [Unreleased]` heading to carve")
carved = (
    text[: match.start()]
    + f"## [Unreleased]\n\n## [{version}] — {date}"
    + text[match.end() :]
)
path.write_bytes(carved.encode("utf-8"))
PY
}

# Rewrite the single `version = "<cur>"` line of a pyproject to <new>.
bump_pyproject() {
    python3 - "$1" "$2" "$3" <<'PY'
import pathlib
import re
import sys

path = pathlib.Path(sys.argv[1])
current, new = sys.argv[2], sys.argv[3]
text = path.read_bytes().decode("utf-8")
pattern = rf'(?m)^version = "{re.escape(current)}"$'
if len(re.findall(pattern, text)) != 1:
    sys.exit(f'{path}: expected exactly one `version = "{current}"` line')
text = re.sub(pattern, f'version = "{new}"', text, count=1)
path.write_bytes(text.encode("utf-8"))
PY
}

# Semver compare: prints -1 (a<b), 0 (a==b) or 1 (a>b) for two X.Y.Z
# strings. Numeric per component — "0.10.0" is NEWER than "0.9.0", which a
# string compare gets backwards.
semver_cmp() {
    python3 - "$1" "$2" <<'PY'
import sys


def parse(raw: str) -> tuple[int, ...]:
    parts = raw.split(".")
    if len(parts) != 3 or not all(p.isdigit() for p in parts):
        sys.exit(f"not an X.Y.Z version: {raw!r}")
    return tuple(int(p) for p in parts)


a, b = parse(sys.argv[1]), parse(sys.argv[2])
print(-1 if a < b else (0 if a == b else 1))
PY
}

files_identical() {
    python3 - "$1" "$2" <<'PY'
import pathlib
import sys

a = pathlib.Path(sys.argv[1]).read_bytes()
b = pathlib.Path(sys.argv[2]).read_bytes()
sys.exit(0 if a == b else 1)
PY
}

# ---------------------------------------------------------------------------
# Preflights. Each records one line in PREFLIGHT_REPORT and, when it fails,
# one remediation in PREFLIGHT_BLOCKS.
#
# A dry run REPORTS them (and still prints the plan — previewing a cut from
# a dirty tree is useful); --write REFUSES on any block, before touching a
# single file.
# ---------------------------------------------------------------------------
PREFLIGHT_REPORT=""
PREFLIGHT_BLOCKS=""

pf_ok() {
    PREFLIGHT_REPORT="${PREFLIGHT_REPORT}#   [ ok ]  $1
"
}

pf_block() {
    # $1 = one-line status, $2 = remediation paragraph.
    PREFLIGHT_REPORT="${PREFLIGHT_REPORT}#   [BLOCK] $1
"
    PREFLIGHT_BLOCKS="${PREFLIGHT_BLOCKS}  * $1
    $2
"
}

# --- git: available, a work tree, clean, on main ---------------------------
if ! command -v git >/dev/null 2>&1; then
    pf_block "git is not on PATH" "Install git; the cut needs it to check the tree state."
elif ! git -C "$ROOT" rev-parse --is-inside-work-tree >/dev/null 2>&1; then
    pf_block "$ROOT is not a git work tree" "Run the cut from a checkout of the s0ma monorepo."
else
    GIT_STATUS="$(git -C "$ROOT" status --porcelain)"
    if [ -n "$GIT_STATUS" ]; then
        _dirty_count="$(printf '%s\n' "$GIT_STATUS" | wc -l | tr -d '[:space:]')"
        _dirty_head="$(printf '%s\n' "$GIT_STATUS" | head -5 | tr '\n' ';')"
        pf_block "working tree is not clean ($_dirty_count entries: $_dirty_head)" \
            "Commit, stash or clean the tree first — a release commit must contain the cut and nothing else (untracked files count)."
    else
        pf_ok "working tree is clean"
    fi

    BRANCH="$(git -C "$ROOT" rev-parse --abbrev-ref HEAD 2>/dev/null || printf '?')"
    if [ "$BRANCH" = "main" ]; then
        pf_ok "on branch main"
    elif [ "$ALLOW_BRANCH" -eq 1 ]; then
        pf_ok "on branch $BRANCH (--allow-branch)"
    else
        pf_block "on branch $BRANCH, not main" \
            "Releases are cut from main (docs/RELEASING.md). Switch to main, or pass --allow-branch for a deliberate off-main cut."
    fi
fi

# --- version strictly forward ---------------------------------------------
CMP="$(semver_cmp "$VERSION" "$CURRENT")"
if [ "$CMP" = "1" ]; then
    pf_ok "$VERSION is strictly newer than the current lockstep $CURRENT"
else
    pf_block "$VERSION is not strictly newer than the current lockstep $CURRENT" \
        "Versions only move forward. Pick a higher X.Y.Z; a deliberate re-cut of an existing version means reverting the previous cut first."
fi

# --- the changelog has something to release --------------------------------
UNRELEASED_STATE="$(unreleased_state "$CHANGELOG")"
case "$UNRELEASED_STATE" in
    nonempty)
        pf_ok "$CHANGELOG_REL has a non-empty '## [Unreleased]' section" ;;
    empty)
        pf_block "$CHANGELOG_REL '## [Unreleased]' section is empty" \
            "There is nothing to release. Write the entries first — the release workflow publishes this exact section as the GitHub Release notes." ;;
    *)
        pf_block "$CHANGELOG_REL has no '## [Unreleased]' heading" \
            "Restore the '## [Unreleased]' heading (Keep a Changelog); the carve has nothing to work on without it." ;;
esac

# --- the target version must not already exist -----------------------------
if changelog_has_version "$CHANGELOG" "$VERSION"; then
    pf_block "$CHANGELOG_REL already has a '## [$VERSION]' section" \
        "That version was already cut. Choose the next version, or revert the earlier cut."
else
    pf_ok "no existing '## [$VERSION]' section to collide with"
fi

# --- the served mirror must be in sync BEFORE the identical edit ------------
if files_identical "$CHANGELOG" "$CHANGELOG_MIRROR"; then
    pf_ok "$CHANGELOG_MIRROR_REL is byte-identical to $CHANGELOG_REL"
else
    pf_block "$CHANGELOG_MIRROR_REL has drifted from $CHANGELOG_REL" \
        "Re-sync the served mirror (copy the root changelog over it) before cutting: mirrors under _docs/ are byte-identical by contract (AGENTS.md), and this script applies the same carve to both."
fi

# --- uv, for the lockfile refresh ------------------------------------------
if command -v uv >/dev/null 2>&1; then
    pf_ok "uv is on PATH (for 'uv sync --all-packages')"
else
    pf_block "uv is not on PATH" \
        "Install uv: the cut refreshes the lockfile with 'uv sync --all-packages'."
fi

# ---------------------------------------------------------------------------
# The edit plan (shared by dry run and --write).
# ---------------------------------------------------------------------------
print_edit_plan() {
    printf '# files this cut edits (4 manifests + 2 changelogs):\n'
    for _pkg in $PACKAGES; do
        printf '#   packages/%s/pyproject.toml\n' "$_pkg"
        printf '#       version = "%s"  ->  version = "%s"\n' "$CURRENT" "$VERSION"
    done
    printf '#   %s\n' "$CHANGELOG_REL"
    printf '#       "## [Unreleased]"  ->  fresh empty "## [Unreleased]" + "%s"\n' "$HEADING"
    printf '#   %s\n' "$CHANGELOG_MIRROR_REL"
    printf '#       the identical carve (served mirror stays byte-identical)\n'
    printf '#\n'
    printf '# then, in the repo root:\n'
    printf '#   uv sync --all-packages\n'
}

print_next_commands() {
    printf '\n'
    printf '==> Next, by hand (this script runs NONE of these):\n'
    printf '\n'
    printf '  # 1. finish the version bump — docs/RELEASING.md step 2 sites this\n'
    printf '  #    script does not touch:\n'
    printf '  #      packages/*/src/*/__init__.py            __version__ strings\n'
    printf '  #      packages/s0ma-studi0/s0ma_src/*.s0ma    version: module headers\n'
    printf '  #      packages/s0ma-core/tests/test_phase3_capstone.py\n'
    printf '  #      packages/s0ma-core/docs/s0ma-core-spec-v*.md   cut the core spec\n'
    printf '  #      packages/s0ma-dsl/tests/test_docs_provider_diagnostics.py   RELEASE\n'
    printf '  #      version-bearing prose in the root README.md and the\n'
    printf '  #      cross-package dependency floors (review, do not blindly bump)\n'
    printf '  #    the Claude plugin and the Desktop extension state the version\n'
    printf '  #    too (Claude Code treats the plugin manifest version as a pin,\n'
    printf '  #    so a cut that skips them ships a plugin claiming the old\n'
    printf '  #    release). One command moves all three of their sites:\n'
    printf '  uv run python scripts/sync_integrations.py --write\n'
    printf '  #    then confirm no living doc is left version-stale:\n'
    printf '  uv run python scripts/check_version_refs.py\n'
    printf '  # 2. put the optional extras back first. The cut ends with an exact\n'
    printf '  #    `uv sync --all-packages`, which removes them, and the documentation\n'
    printf '  #    build refuses to compose without them (docs/RELEASING.md step 1):\n'
    printf '  uv sync --all-packages --all-extras\n'
    printf '  #    then rebuild the three committed builds (docs/RELEASING.md step 3):\n'
    printf '  uv run s0ma --project-root packages/s0ma-mcp build packages/s0ma-mcp --mode release --no-cache\n'
    printf '  uv run s0ma --project-root packages/s0ma-studi0 build packages/s0ma-studi0 --no-cache\n'
    printf '  uv run s0ma --project-root docs build docs --no-cache\n'
    printf '  uv run s0ma --project-root docs docs render docs/s0ma_src --output-dir docs --mode release\n'
    printf '  # The cut lands as THREE commits on this branch, so that every gate\n'
    printf '  # reads a tree it can read: A (composed as preview), R (composed for\n'
    printf '  # the release; the tag names it), P (preview again; main ends here).\n'
    printf '  # Why: docs/RELEASING.md, "The three commits of a cut".\n'
    printf '  # 3. commit A. Compose plainly; every identity line says "preview":\n'
    printf '  uv run s0ma --project-root docs docs compose --output-dir docs\n'
    printf '  #    then the five mirror copies, in this order. Run them after EVERY\n'
    printf '  #    compose below too, and re-stamp the goldens when they change\n'
    printf '  #    (docs/operations/docs-maintenance.md, "The loop", steps 3 and 4):\n'
    printf '  cp docs/_generated/s0ma-docs-model.json packages/s0ma-mcp/src/s0ma_mcp/_docs/s0ma-docs-model.json\n'
    printf '  cp docs/_generated/core-teaching-slice.json packages/s0ma-core/src/s0ma/_teaching/slice.json\n'
    printf '  cp docs/_generated/s0ma-docs-model.json packages/s0ma-dsl/src/s0ma_dsl/_docs_snapshot/s0ma-docs-model.json\n'
    printf '  cp docs/reference/quick-reference-readable.md packages/s0ma-mcp/src/s0ma_mcp/_docs/quick-reference-readable.md\n'
    printf '  cp docs/_generated/quick-reference-machine.json packages/s0ma-mcp/src/s0ma_mcp/_docs/quick-reference-machine.json\n'
    printf '  uv run python scripts/check.py\n'
    printf '  git add -A\n'
    printf '  git commit -m "s0ma: release %s prepare %s (the version, the three builds, the documentation composed as preview)"\n' "$EM_DASH" "$VERSION"
    printf '  #    push the branch and open a pull request; the full matrix reads A:\n'
    printf '  git push -u origin release-%s\n' "$VERSION"
    printf '  # 4. commit R. Compose FOR THIS RELEASE, stating the tag\n'
    printf '  #    (docs/RELEASING.md step 4). Untagged, it composes a preview and\n'
    printf '  #    every identity line says so. Read the line under "Composed":\n'
    printf '  uv run s0ma --project-root docs docs compose --output-dir docs --head-tag %s\n' "$TAG"
    printf '  #    the five mirror copies again, all from this tagged compose; then\n'
    printf '  #    the full gate, stating the same tag (docs/RELEASING.md step 5):\n'
    printf '  S0MA_HEAD_TAG=%s uv run python scripts/check.py\n' "$TAG"
    printf '  git add -A\n'
    printf '  git commit -m "s0ma: release %s cut %s"\n' "$EM_DASH" "$VERSION"
    printf '  #    R is never pushed as a branch head. Note its hash.\n'
    printf '  # 5. commit P. Compose plainly again, the five copies again, the\n'
    printf '  #    plain gate. Nothing else may move: the tree of P is the tree of A.\n'
    printf '  uv run s0ma --project-root docs docs compose --output-dir docs\n'
    printf '  uv run python scripts/check.py\n'
    printf '  git add -A\n'
    printf '  git commit -m "s0ma: release %s main returns to the preview channel after %s"\n' "$EM_DASH" "$VERSION"
    printf '  #    prove it: this must print the same hash twice\n'
    printf '  git rev-parse <hash-of-A>^{tree} HEAD^{tree}\n'
    printf '  #    push R and P together; ordinary CI runs once, on P:\n'
    printf '  git push origin release-%s\n' "$VERSION"
    printf '  # 6. OWNER-AUTHORIZED ONLY, once CI is green on P: main moves to P by\n'
    printf '  #    a fast-forward, then the tag names R. The tag push IS the release\n'
    printf '  #    act — it fires .github/workflows/release.yml (wheels, GitHub\n'
    printf '  #    Release, R2 mirror). No agent ever runs it.\n'
    printf '  git push origin release-%s:main\n' "$VERSION"
    printf '  git tag -a %s <hash-of-R> -m "s0ma %s %s <one-line summary>"\n' "$TAG" "$VERSION" "$EM_DASH"
    printf '  git push origin %s\n' "$TAG"
}

# ---------------------------------------------------------------------------
# Dry run (default): print everything, write nothing.
# ---------------------------------------------------------------------------
if [ "$WRITE" -eq 0 ]; then
    printf '# s0ma release cut (DRY RUN) %s %s -> %s %s NOTHING is written\n' \
        "$EM_DASH" "$CURRENT" "$VERSION" "$EM_DASH"
    printf '# repo root: %s\n' "$ROOT"
    printf '# changelog heading: %s\n' "$HEADING"
    printf '#\n'
    printf '# preflights (a [BLOCK] here refuses --write):\n'
    printf '%s' "$PREFLIGHT_REPORT"
    printf '#\n'
    print_edit_plan
    printf '#\n'
    printf '# %s head after the carve:\n' "$CHANGELOG_REL"
    carve_preview "$CHANGELOG" "$VERSION" "$DATE" 6 | sed 's/^/#       /'
    print_next_commands
    printf '\n'
    if [ -n "$PREFLIGHT_BLOCKS" ]; then
        printf '==> NOTE: --write would REFUSE right now:\n%s' "$PREFLIGHT_BLOCKS"
    else
        printf '==> Preflights pass. Re-run with --write to apply the plan above.\n'
    fi
    exit 0
fi

# ---------------------------------------------------------------------------
# --write: refuse on any blocked preflight, then apply the plan.
# ---------------------------------------------------------------------------
if [ -n "$PREFLIGHT_BLOCKS" ]; then
    printf '%s: error: release cut refused %s preflight failed. Nothing was written.\n' \
        "$PROG" "$EM_DASH" >&2
    printf '%s' "$PREFLIGHT_BLOCKS" >&2
    exit 1
fi

printf '==> s0ma release cut: %s -> %s (%s)\n' "$CURRENT" "$VERSION" "$DATE"
print_edit_plan
printf '\n'

for _pkg in $PACKAGES; do
    _path="$ROOT/packages/$_pkg/pyproject.toml"
    bump_pyproject "$_path" "$CURRENT" "$VERSION"
    printf '+   packages/%s/pyproject.toml -> version = "%s"\n' "$_pkg" "$VERSION"
done

carve_changelog "$CHANGELOG" "$VERSION" "$DATE"
printf '+   %s -> %s\n' "$CHANGELOG_REL" "$HEADING"
carve_changelog "$CHANGELOG_MIRROR" "$VERSION" "$DATE"
printf '+   %s -> the identical carve\n' "$CHANGELOG_MIRROR_REL"

files_identical "$CHANGELOG" "$CHANGELOG_MIRROR" || \
    die "the changelog and its served mirror are not byte-identical after the carve.
This should be impossible (the same edit was applied to both). The edits ARE
on disk: inspect 'git diff', re-sync the mirror, and do not commit until they
match — a drifted mirror fails the repo's generated-file gate."

printf '\n==> refreshing the lockfile: uv sync --all-packages\n'
if ! (cd "$ROOT" && uv sync --all-packages); then
    die "'uv sync --all-packages' failed.
The version and changelog edits ARE already applied on disk. Fix the sync
failure and re-run 'uv sync --all-packages' by hand, or 'git checkout -- .'
to abandon this cut."
fi

print_next_commands
printf '\n==> Done. %s is cut in the working tree, uncommitted and untagged.\n' "$VERSION"
