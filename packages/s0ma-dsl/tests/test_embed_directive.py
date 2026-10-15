"""M12 (feedback 5–6) — ``@file()`` content embed directive on CONSTANT cells.

Locks down the post-M12 behaviour for ``content: @file("path")``:

- The path resolves relative to the .s0ma source's directory; the
  embedded content is read at parse time and emitted byte-for-byte
  into the generated Python via ``r\"\"\"...\"\"\"`` (or ``repr()`` when
  the content contains the triple-quote sequence).
- A missing or unreadable embedded file produces ``EMBEDDED_FILE_NOT_FOUND``
  at error severity in every strictness mode.
- Editing the embedded file invalidates the consuming module's cache —
  the next build re-emits that module rather than serving a stale .py.
- The build manifest's ``external_content_files`` map records each
  embed under ``"<module>::<cell>"`` with its path-as-written and
  ``sha256:<hex>``.
- Triple-quote content falls through to the ``repr()`` fallback and
  still passes the M2 ``ast.parse`` build invariant.

Pairs with ``tests/fixtures/embed_html/`` (the reference fixture).
"""

from __future__ import annotations

import json
import shutil
import sys
import textwrap
from pathlib import Path

import pytest

from s0ma_dsl.cli.main import EXIT_SUCCESS, EXIT_VALIDATION_ERROR, S0maCLI
from s0ma_dsl.codegen.build_manifest import MANIFEST_FILENAME, load_manifest

REPO_ROOT = Path(__file__).parent.parent
FIXTURE = REPO_ROOT / "tests" / "fixtures" / "embed_html"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def fresh_project(tmp_path: Path) -> Path:
    """Copy ``tests/fixtures/embed_html`` into a writeable tmp tree.

    Tests that mutate the embedded HTML or the .s0ma source need their
    own copy so they don't pollute the repo fixture for other tests.
    """
    dst = tmp_path / "embed_html"
    shutil.copytree(FIXTURE, dst)
    return dst


def _build(project: Path, out_dir: Path, *, no_cache: bool = True) -> int:
    """Run ``s0ma build`` against *project* into *out_dir*.

    Passes ``--force-output-dir`` so the build proceeds even when
    ``out_dir`` disagrees with the fixture's configured
    ``[tool.s0ma].build_dir`` (POST-11a / M-16, 0.16.0).
    """
    args = [
        "--project-root", str(project),
        "build", str(project),
        "--output-dir", str(out_dir),
        "--force-output-dir",
        "--mode", "dev",
    ]
    if no_cache:
        args.append("--no-cache")
    return S0maCLI().run(args)


# ---------------------------------------------------------------------------
# Acceptance tests
# ---------------------------------------------------------------------------


def test_embed_resolves_relative_path(fresh_project: Path, tmp_path: Path) -> None:
    """The embedded HTML must round-trip byte-for-byte into the generated .py.

    Acceptance criterion (plan M12): "the embedded content round-trips
    byte-for-byte". Build the fixture, import the generated module's
    ``VIZ_TEMPLATE`` constant, compare to the original file's bytes.
    """
    out_dir = tmp_path / "build"
    rc = _build(fresh_project, out_dir)
    assert rc == EXIT_SUCCESS

    py_path = out_dir / "embed_test.py"
    assert py_path.is_file()

    # Importing the emitted module's VIZ_TEMPLATE must equal the
    # original HTML byte-for-byte.
    original = (fresh_project / "templates" / "viz.html").read_text(
        encoding="utf-8",
    )

    sys.path.insert(0, str(out_dir))
    # Drop any cached version of the module from a prior test
    # (importlib caches per-name, not per-path).
    sys.modules.pop("embed_test", None)
    try:
        import embed_test  # type: ignore[import-not-found]
        assert original == embed_test.VIZ_TEMPLATE
    finally:
        sys.path.remove(str(out_dir))
        sys.modules.pop("embed_test", None)


def test_embed_missing_file_errors(fresh_project: Path, tmp_path: Path) -> None:
    """A missing embedded file produces ``EMBEDDED_FILE_NOT_FOUND``.

    Acceptance criterion (plan M12): "s0ma check validates that the
    referenced file exists and is readable. Otherwise: EMBEDDED_FILE_NOT_FOUND
    error." The error's severity is ``error`` in every strictness mode
    (config.SEVERITY_MATRIX).
    """
    # Remove the embedded file but leave the .s0ma source unchanged.
    (fresh_project / "templates" / "viz.html").unlink()

    out_dir = tmp_path / "build"
    rc = _build(fresh_project, out_dir)
    # Build path surfaces parse-time S0maSemanticError as a validation
    # failure exit code.
    assert rc == EXIT_VALIDATION_ERROR
    # The build artifacts should not have been emitted.
    assert not (out_dir / "embed_test.py").exists()


def test_embed_check_surfaces_error_code(fresh_project: Path, capsys) -> None:
    """``s0ma check`` exposes the ``EMBEDDED_FILE_NOT_FOUND`` error code."""
    (fresh_project / "templates" / "viz.html").unlink()

    rc = S0maCLI().run([
        "--project-root", str(fresh_project),
        "check", str(fresh_project),
        "--mode", "dev",
        "--format", "json",
    ])
    assert rc == EXIT_VALIDATION_ERROR
    out = capsys.readouterr().out
    payload = json.loads(out)
    # The CLI's JSON output groups by severity (``errors`` vs
    # ``warnings``); concatenate both so the assertion is robust to
    # future severity changes.
    codes = {d["code"] for d in payload.get("errors", [])}
    codes.update(d["code"] for d in payload.get("warnings", []))
    assert "EMBEDDED_FILE_NOT_FOUND" in codes


def test_embed_invalidates_cache_on_change(
    fresh_project: Path, tmp_path: Path,
) -> None:
    """Editing the embedded file invalidates the consuming module's cache.

    Acceptance criterion (plan M12): "Editing the embedded file
    invalidates cache and produces a re-transpile."
    """
    out_dir = tmp_path / "build"
    fresh_project / ".s0ma.cache"

    # Build #1: cache miss, populates cache.
    rc1 = _build(fresh_project, out_dir, no_cache=False)
    assert rc1 == EXIT_SUCCESS
    py1 = (out_dir / "embed_test.py").read_text(encoding="utf-8")
    assert "Hello, s0ma" in py1

    # Build #2 (no source changes): cache hit — output stable.
    rc2 = _build(fresh_project, out_dir, no_cache=False)
    assert rc2 == EXIT_SUCCESS
    py2 = (out_dir / "embed_test.py").read_text(encoding="utf-8")
    assert py2 == py1

    # Mutate the embedded file (NOT the .s0ma source) and rebuild.
    html_path = fresh_project / "templates" / "viz.html"
    html = html_path.read_text(encoding="utf-8")
    mutated = html.replace("Hello, s0ma", "Goodbye, s0ma")
    assert mutated != html, "fixture sentinel string is missing"
    html_path.write_text(mutated, encoding="utf-8")

    rc3 = _build(fresh_project, out_dir, no_cache=False)
    assert rc3 == EXIT_SUCCESS
    py3 = (out_dir / "embed_test.py").read_text(encoding="utf-8")

    assert py3 != py1, (
        "expected the second build to re-emit after the embedded "
        "file changed; the cache should have missed but appears "
        "to have served stale output."
    )
    assert "Goodbye, s0ma" in py3
    assert "Hello, s0ma" not in py3


def test_embed_records_source_in_manifest(
    fresh_project: Path, tmp_path: Path,
) -> None:
    """``build.s0ma.json`` lists the external content file with hash.

    Acceptance criterion (plan M12 step 3): "Include it in
    build.s0ma.json under a new external_content_files map:
    { '<module>::<cell>': { 'path': ..., 'hash': ... } }."
    """
    out_dir = tmp_path / "build"
    rc = _build(fresh_project, out_dir)
    assert rc == EXIT_SUCCESS

    manifest_path = out_dir / MANIFEST_FILENAME
    assert manifest_path.is_file()

    manifest = load_manifest(out_dir)
    key = "embed_test::VIZ_TEMPLATE"
    assert key in manifest.external_content_files
    entry = manifest.external_content_files[key]
    # The path stays exactly as written in the .s0ma source —
    # relative paths are not absolutised so the manifest is portable.
    assert entry.path == "templates/viz.html"
    # The hash is sha256:<64 hex chars>.
    assert entry.hash.startswith("sha256:")
    assert len(entry.hash) == len("sha256:") + 64

    # Cross-check by also reading the JSON directly — guards against
    # the loader silently dropping the field on a future schema bump.
    raw = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert raw["external_content_files"][key]["path"] == "templates/viz.html"


def test_embed_with_triple_quote_in_content(tmp_path: Path) -> None:
    """HTML containing the triple-quote sequence still embeds correctly.

    Acceptance criterion (plan M12 step 3): "use ``r\"\"\"...\"\"\"`` if
    the content has no ``\"\"\"``. If ``\"\"\"`` appears in content,
    fall back to ``repr()`` of the full string."

    The build invariant from M2 (``ast.parse``) catches any encoding
    mistake, so the test confirms (a) the fixture builds successfully
    and (b) the round-tripped value matches byte-for-byte.
    """
    project = tmp_path / "embed_triple"
    project.mkdir()
    (project / "pyproject.toml").write_text(textwrap.dedent("""
        [project]
        name = "embed_triple_fixture"
        version = "0.0.1"

        [tool.s0ma]
        source_roots = ["."]
        test_roots = []
        build_dir = "embed_triple_build"
        bootstrap_files = []
    """).strip() + "\n", encoding="utf-8")

    # Content with triple-quote sequences and a backslash —
    # guaranteed to fall through to the repr() fallback.
    weird_content = textwrap.dedent('''
        text with """triple quotes""" inside
        and a backslash\\nbut not at the end
        plus singles ' and doubles "
    ''').strip()
    (project / "embed_triple.s0ma").write_text(textwrap.dedent('''\
module embed_triple
    layer: PRESENTATION
    version: 0.0.1
    intent: "Triple-quote fallback fixture for M12."
    requires: []
    uses: []
    exports: [WEIRD_PROMPT]

    soft_requires: none
    runtime_only_requires: none
    deferred_requires: none
    exports_helpers: none
cell WEIRD_PROMPT :: PRESENTATION
    kind: CONSTANT
    visibility: PUBLIC
    intent: "Prompt text containing triple-quote sequences — exercises the repr() fallback."
    schema: "string"
    content: @file("prompts/weird.txt")
    invariants: none
    covered_by: none
''').strip() + "\n", encoding="utf-8")
    (project / "prompts").mkdir()
    (project / "prompts" / "weird.txt").write_text(
        weird_content, encoding="utf-8",
    )

    out_dir = tmp_path / "build"
    rc = _build(project, out_dir)
    assert rc == EXIT_SUCCESS

    # The emitted .py must parse (the M2 build invariant runs at
    # write time; we just confirm the file is on disk).
    py_path = out_dir / "embed_triple.py"
    assert py_path.is_file()
    py_src = py_path.read_text(encoding="utf-8")
    # The repr() fallback emits a single-quoted form; confirm we
    # didn't accidentally use the unsafe r""" form.
    assert 'r"""' not in py_src or '"""' not in weird_content  # belt + braces

    # Round-trip via import — the content must equal the file's bytes.
    sys.path.insert(0, str(out_dir))
    sys.modules.pop("embed_triple", None)
    try:
        import embed_triple  # type: ignore[import-not-found]
        assert weird_content == embed_triple.WEIRD_PROMPT
    finally:
        sys.path.remove(str(out_dir))
        sys.modules.pop("embed_triple", None)


# ---------------------------------------------------------------------------
# Defensive grammar tests
# ---------------------------------------------------------------------------


def test_embed_and_inline_body_combination_rejected(tmp_path: Path) -> None:
    """A cell with both ``content: @file(...)`` and ``--- ... ---`` body fails.

    M12 is explicit: pick one form. The parser raises a ``PARSE_ERROR``
    naming the cell so the author knows which declaration to fix.
    """
    project = tmp_path / "embed_combined"
    project.mkdir()
    (project / "pyproject.toml").write_text(textwrap.dedent("""
        [project]
        name = "x"
        version = "0.0.1"
        [tool.s0ma]
        source_roots = ["."]
        test_roots = []
        build_dir = "x_build"
        bootstrap_files = []
    """).strip() + "\n", encoding="utf-8")

    (project / "combined.txt").write_text("ignored", encoding="utf-8")
    (project / "combined.s0ma").write_text(textwrap.dedent('''\
module combined
    layer: APPLICATION
    version: 0.0.1
    intent: "Both forms — must be rejected."
    requires: []
    uses: []
    exports: [BOTH]

    soft_requires: none
    runtime_only_requires: none
    deferred_requires: none
    exports_helpers: none
cell BOTH :: APPLICATION
    kind: CONSTANT
    visibility: INTERNAL
    intent: "Both forms simultaneously."
    schema: "string"
    content: @file("combined.txt")
    invariants: none
    covered_by: none
    ---
    BOTH = "inline"
''').strip() + "\n", encoding="utf-8")

    rc = S0maCLI().run([
        "--project-root", str(project),
        "check", str(project),
        "--mode", "dev",
    ])
    assert rc == EXIT_VALIDATION_ERROR


def test_embed_on_non_constant_cell_rejected(tmp_path: Path) -> None:
    """The embed directive is CONSTANT-only in v0.12.0 — others reject."""
    project = tmp_path / "embed_model"
    project.mkdir()
    (project / "pyproject.toml").write_text(textwrap.dedent("""
        [project]
        name = "x"
        version = "0.0.1"
        [tool.s0ma]
        source_roots = ["."]
        test_roots = []
        build_dir = "x_build"
        bootstrap_files = []
    """).strip() + "\n", encoding="utf-8")

    (project / "schema.txt").write_text("ignored", encoding="utf-8")
    (project / "embed_model.s0ma").write_text(textwrap.dedent('''\
module embed_model
    layer: APPLICATION
    version: 0.0.1
    intent: "Embed on a MODEL cell — must reject."
    requires: []
    uses: []
    exports: []

    soft_requires: none
    runtime_only_requires: none
    deferred_requires: none
    exports_helpers: none
cell BadModel :: APPLICATION
    kind: MODEL
    visibility: INTERNAL
    intent: "Should not be allowed."
    schema: "anything"
    content: @file("schema.txt")
    invariants: none
    covered_by: none
''').strip() + "\n", encoding="utf-8")

    rc = S0maCLI().run([
        "--project-root", str(project),
        "check", str(project),
        "--mode", "dev",
    ])
    assert rc == EXIT_VALIDATION_ERROR
