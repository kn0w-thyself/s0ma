#!/bin/sh
# s0ma: the Claude integration, proved end to end, by hand.
#
# Milestone Q2 of plans/s0ma-beta-prep-2-claude-integration.md. Two things
# happen here, in order:
#
#   1. The end-to-end smoke (integrations/launcher/tests/test_e2e_real_wheels.py)
#      builds the four REAL s0ma wheels from this tree, serves them from a fake
#      control plane on a loopback port, installs them with the launcher, starts
#      the real s0ma-mcp through `serve`, completes a real MCP handshake, lets a
#      newer version arrive on its own, and proves a pinned project stays put.
#
#   2. If a `claude` binary is on this machine, `claude --plugin-dir ... mcp list`
#      asks Claude Code itself to start the plugin's server and report whether it
#      connected. No model is called and nothing is spent.
#
# What this never touches: the real ~/.s0ma (everything happens under a
# temporary directory this script removes when it finishes), ~/.claude (no
# plugin is installed, no marketplace is added, no server is registered), and
# the real control plane (nothing here ever addresses a kn0wthyself host).
#
# POSIX sh on purpose - no bashisms - but it is the POSIX half of the work: on
# Windows, run the pytest command it prints below directly.
#
# Usage:  sh scripts/smoke_claude_integration.sh

set -eu

ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
TEST_FILE="integrations/launcher/tests/test_e2e_real_wheels.py"
PLUGIN_DIR="$ROOT/integrations/claude/plugin"

# ---------------------------------------------------------------------------
# Refuse to run anywhere near a real control plane.
# ---------------------------------------------------------------------------

case "${S0MA_CP_HOST-}" in
    "") ;;
    http://127.0.0.1|http://127.0.0.1:*|\
    http://localhost|http://localhost:*|\
    http://\[::1\]|http://\[::1\]:*|\
    127.0.0.1|127.0.0.1:*|localhost|localhost:*) ;;
    *)
        printf 'Refusing to run: S0MA_CP_HOST is set to "%s".\n' "$S0MA_CP_HOST" >&2
        printf 'This smoke only ever talks to a control plane on this machine.\n' >&2
        printf 'Unset S0MA_CP_HOST and run it again.\n' >&2
        exit 2
        ;;
esac

# Nothing below reads any of these, and an exported one would only muddy what
# the run proves. The tests build the environment their subprocesses get from
# scratch; this just makes the same promise at the outer edge.
unset S0MA_CP_HOST S0MA_HOME S0MA_LICENSE_KEY S0MA_TOOLCHAIN S0MA_UPDATE || true
unset S0MA_LAUNCH_OFFLINE_INSTALL || true

WORK=$(mktemp -d 2>/dev/null || mktemp -d -t s0ma-smoke)
trap 'rm -rf "$WORK"' EXIT INT TERM HUP

printf '\n== s0ma: the Claude integration, end to end ==\n'
printf 'repository:  %s\n' "$ROOT"
printf 'scratch:     %s (removed when this finishes)\n\n' "$WORK"

# ---------------------------------------------------------------------------
# 1. The end-to-end smoke.
# ---------------------------------------------------------------------------

printf '%s\n\n' '-- 1/2: real wheels, real install, real MCP handshake --'
# --basetemp puts pytest's own scratch inside ours, so the several hundred
# megabytes of real virtual environments this builds go away with everything
# else rather than accumulating under the system temporary directory.
if (cd "$ROOT" && S0MA_E2E=1 uv run pytest "$TEST_FILE" -v -s --basetemp="$WORK/pytest"); then
    E2E=pass
else
    E2E=fail
fi

# ---------------------------------------------------------------------------
# 2. Claude Code's own health check on the plugin's server, if `claude` is here.
# ---------------------------------------------------------------------------

printf '\n%s\n\n' '-- 2/2: Claude Code starts the plugin server and reports on it --'
if ! command -v claude >/dev/null 2>&1; then
    printf 'No `claude` on PATH, so its own verdict cannot be taken. Skipped.\n'
    MCP=skipped
else
    VERSION=$(sed -n 's/^version = "\(.*\)"/\1/p' "$ROOT/packages/s0ma-core/pyproject.toml" \
        | head -n 1)
    if [ -z "$VERSION" ]; then
        printf 'Could not read the version from packages/s0ma-core/pyproject.toml.\n' >&2
        MCP=fail
    else
        printf 'Installing a real s0ma %s toolchain under the scratch directory...\n' "$VERSION"
        # The same shape the launcher's own `install` leaves behind: a uv
        # environment per version under toolchains/, with the .complete marker
        # written last. Built here rather than fetched, because this half of the
        # script is about Claude Code, not about the control plane.
        HOME_DIR="$WORK/s0ma-home"
        PROJECT_DIR="$WORK/project"
        TOOLCHAIN="$HOME_DIR/toolchains/$VERSION"
        mkdir -p "$HOME_DIR/toolchains" "$PROJECT_DIR"
        MCP=pass
        for package in s0ma-core s0ma-dsl s0ma-mcp s0ma-studi0; do
            uv build --package "$package" --wheel --out-dir "$WORK/dist" >/dev/null 2>&1 \
                || MCP=fail
        done
        if [ "$MCP" = pass ]; then
            uv venv --relocatable "$TOOLCHAIN" >/dev/null 2>&1 || MCP=fail
            uv pip install --python "$TOOLCHAIN/bin/python" "$WORK"/dist/*.whl \
                >/dev/null 2>&1 || MCP=fail
        fi
        if [ "$MCP" = fail ]; then
            printf 'Could not build a toolchain to point Claude at.\n' >&2
        else
            printf '%s\n' "$VERSION" > "$TOOLCHAIN/.complete"
            printf 'Asking Claude Code to start the plugin server...\n\n'
            # Run from an empty project so the toolchain under test is the one
            # in the scratch S0MA_HOME, never this repository's own .venv. No
            # licence key is given and updates are off, so the launcher has
            # nothing to ask any control plane for.
            OUT=$(cd "$PROJECT_DIR" && S0MA_HOME="$HOME_DIR" S0MA_UPDATE=off \
                DISABLE_AUTOUPDATER=1 CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC=1 \
                claude --plugin-dir "$PLUGIN_DIR" mcp list 2>&1) || true
            printf '%s\n' "$OUT"
            LINE=$(printf '%s\n' "$OUT" | grep 's0ma:s0ma:' || true)
            case "$LINE" in
                *Connected*) MCP=pass ;;
                "")
                    printf '\nClaude Code listed no s0ma server at all.\n' >&2
                    MCP=fail
                    ;;
                *)
                    printf '\nClaude Code did not report the s0ma server as connected.\n' >&2
                    MCP=fail
                    ;;
            esac
        fi
    fi
fi

# ---------------------------------------------------------------------------
# What happened.
# ---------------------------------------------------------------------------

printf '\n== summary ==\n'
printf 'end-to-end smoke (install, serve, handshake, update, pin):  %s\n' "$E2E"
printf 'Claude Code reports the plugin server connected:            %s\n' "$MCP"
printf 'the real ~/.s0ma and ~/.claude were not touched.\n\n'

if [ "$E2E" = pass ] && [ "$MCP" != fail ]; then
    printf 'All good.\n'
    exit 0
fi
printf 'Something did not pass. The detail is above.\n'
exit 1
