"""Which channel the committed documentation was composed in, for the tests
that hold the committed files to a fresh build.

The documentation is composed in one of two channels. Every commit in
ordinary development is a preview, composed with no tag. One commit per
release, the one the tag names, is the release, composed with
``s0ma docs compose --head-tag v<version>`` (``docs/RELEASING.md``, "The
three commits of a cut"). The committed ``docs/_generated/docs-manifest.json``
records which, in ``build_channel``.

A test that compares the committed files with what a build renders has to
build the channel those files were composed in. Otherwise, on the one
release commit, every such comparison is red for a reason that is not a
defect. This module is how those tests ask, and its rule is the one the
``docs-application`` stage already follows (``committed_claim`` and
``head_tag_for_claim`` in ``scripts/check_docs_application.py``): the
committed tree's own claim decides, never the environment. A tree that
claims preview is composed untagged whatever ``S0MA_HEAD_TAG`` holds. A tree
that claims release is composed at its own tag,
``version_tag(product_version)``.

On a preview-composed tree, which is every commit but one per release,
nothing here changes what a test does: :func:`claimed_head_tag` is ``""``,
which is what ``build`` and ``docs check`` use when no tag is given, and
:data:`preview_tree_only` skips nothing.

Usage::

    from tests._committed_claim import claimed_head_tag, preview_tree_only

    composed = build(REPO_ROOT, head_tag=claimed_head_tag())

    @preview_tree_only
    def test_this_tree_is_a_preview_build() -> None: ...
"""

from __future__ import annotations

from pathlib import Path

import pytest

from s0ma_dsl.docs_model.application import DOCS_MANIFEST_OUTPUT, DOCS_ROOT
from s0ma_dsl.docs_model.manifest import manifest_from_json, version_tag
from s0ma_dsl.docs_model.records import PREVIEW_CHANNEL, RELEASE_CHANNEL

#: The monorepo root (this file: packages/s0ma-dsl/tests/<file>).
REPO_ROOT = Path(__file__).resolve().parents[3]

#: The committed manifest, the one file that says which channel the tree is.
MANIFEST = REPO_ROOT / DOCS_ROOT / DOCS_MANIFEST_OUTPUT


def committed_claim() -> tuple[str, str]:
    """The committed manifest's ``(build_channel, product_version)``.

    Read through the application's own reader, as the gate reads it. With
    no manifest to read the answer is preview, with no version: that is the
    wheel-install context, where the tests run without the documentation
    tree, and a tree nobody cut is a preview tree. An unreadable manifest
    answers the same, for the reason the gate gives: the byte comparisons
    already fail on that file and say what to run, and an error raised here
    would replace that located report with a vaguer one earlier.
    """
    if not MANIFEST.is_file():
        return PREVIEW_CHANNEL, ""
    try:
        manifest = manifest_from_json(MANIFEST.read_text(encoding="utf-8"))
    except (ValueError, OSError):
        return PREVIEW_CHANNEL, ""
    return manifest.build_channel, manifest.product_version


def claimed_head_tag() -> str:
    """The tag that reproduces the committed tree, or ``""`` for a preview.

    For a release claim this is the release's own tag, the value
    ``s0ma docs compose --head-tag`` was given when the tree was cut. For a
    preview claim it is empty, so the build composes untagged exactly as it
    always has.
    """
    channel, product_version = committed_claim()
    if channel != RELEASE_CHANNEL:
        return ""
    return version_tag(product_version)


#: Marks a proof about a preview-composed tree as such. It runs on every
#: commit but the one a release tag names, where the committed tree claims
#: release and the proof has nothing to stand on.
preview_tree_only = pytest.mark.skipif(
    committed_claim()[0] == RELEASE_CHANNEL,
    reason=(
        f"{DOCS_ROOT}/{DOCS_MANIFEST_OUTPUT} claims the {RELEASE_CHANNEL} "
        f"channel: the committed tree is composed as a release (the one "
        f"commit a tag names); this proof is about a preview-composed tree "
        f"and runs on every other commit"
    ),
)
