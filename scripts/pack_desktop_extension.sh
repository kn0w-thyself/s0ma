#!/bin/sh
# Pack the Claude Desktop extension as an .mcpb bundle.
#
# Usage: scripts/pack_desktop_extension.sh [output-directory]
#
# The bundle's source lives at integrations/claude/desktop/. This script copies
# it into a staging directory under the output directory, then - if the `mcpb`
# packer is already installed on this computer - validates and packs it.
#
# The .mcpb file is a build product. It is never written inside the repository
# and never committed, so the output directory defaults to a fresh temporary
# directory, whose path is printed.
#
# Nothing here downloads or installs anything. If `mcpb` is not on the PATH the
# script stages the bundle, prints the exact commands to install the packer and
# run it by hand, and exits 0.

set -eu

script_dir=$(cd "$(dirname "$0")" && pwd)
repo_root=$(cd "$script_dir/.." && pwd)
source_dir="$repo_root/integrations/claude/desktop"

if [ ! -f "$source_dir/manifest.json" ]; then
    echo "Cannot find the extension at $source_dir - is this the s0ma repository?" >&2
    exit 1
fi

# ---------------------------------------------------------------------------
# Where the build product goes.
# ---------------------------------------------------------------------------

if [ "$#" -gt 1 ]; then
    echo "Usage: $0 [output-directory]" >&2
    exit 2
fi

refuse_inside_repo() {
    case "$1" in
        "$repo_root" | "$repo_root"/*)
            echo "The .mcpb file is a build product and must not be written inside" >&2
            echo "the repository. Name a directory outside $repo_root, or give no" >&2
            echo "directory at all and a temporary one will be used." >&2
            exit 2
            ;;
    esac
}

if [ "$#" -eq 1 ]; then
    out_dir=$1
    # Judged before anything is created, so a refused path leaves no trace, and
    # again after the directory is resolved, so a symbolic link cannot slip past.
    case "$out_dir" in
        /*) refuse_inside_repo "$out_dir" ;;
        *) refuse_inside_repo "$(pwd)/$out_dir" ;;
    esac
    mkdir -p "$out_dir"
else
    out_dir=$(mktemp -d)
fi
out_dir=$(cd "$out_dir" && pwd)
refuse_inside_repo "$out_dir"

# ---------------------------------------------------------------------------
# Stage the bundle. Copying file by file means nothing that happens to be
# sitting in the source directory - a .venv, a __pycache__ - can reach the
# bundle by accident.
# ---------------------------------------------------------------------------

version=$(sed -n 's/^  "version": "\([^"]*\)".*$/\1/p' "$source_dir/manifest.json" | head -n 1)
if [ -z "$version" ]; then
    echo "Could not read the version out of $source_dir/manifest.json" >&2
    exit 1
fi

stage="$out_dir/s0ma-$version"
bundle="$out_dir/s0ma-$version.mcpb"

rm -rf "$stage"
mkdir -p "$stage/server"
cp "$source_dir/manifest.json" "$stage/manifest.json"
cp "$source_dir/pyproject.toml" "$stage/pyproject.toml"
cp "$source_dir/server/s0ma_launch.py" "$stage/server/s0ma_launch.py"

echo "s0ma $version staged at $stage"

# ---------------------------------------------------------------------------
# Pack it, if this computer already has the packer.
# ---------------------------------------------------------------------------

if ! command -v mcpb >/dev/null 2>&1; then
    echo ""
    echo "The mcpb packer is not installed on this computer, so nothing was packed."
    echo "Install it once, then run the other two commands:"
    echo ""
    echo "  npm install -g @anthropic-ai/mcpb"
    echo "  mcpb validate $stage/manifest.json"
    echo "  mcpb pack $stage $bundle"
    echo ""
    exit 0
fi

mcpb validate "$stage/manifest.json"
mcpb pack "$stage" "$bundle"

echo ""
echo "Packed: $bundle"
echo "Install it by opening it in Claude Desktop, or through"
echo "Settings > Extensions > Advanced settings > Install Extension."
