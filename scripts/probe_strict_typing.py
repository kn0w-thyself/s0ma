#!/usr/bin/env python3
"""Strict-typing probe corpus for emitted s0ma DSL Python (selfhost plan, M0).

Answers ONE question, repeatably: does the transpiler's emitted Python meet
``mypy --strict`` — the same gate handwritten ``s0ma-mcp`` code meets (PRD
INV-8, FR-MCP-11)? Used by the selfhost plan's M0 GO/NO-GO decision and
re-runnable by every later milestone (and CI debugging) as the emitter or
the typing floor evolves.

What it does:

1. Copies each corpus fixture into a scratch ``[tool.s0ma]`` project under a
   temp dir (3 real fixtures from the s0ma-dsl test suite + 1 synthetic
   module exercising the construct families s0ma-mcp authoring actually
   uses: typed function bodies, module-level constants, dataclass models,
   helpers, third-party typed imports like the MCP SDK's ToolAnnotations).
2. Runs ``s0ma build`` on each scratch project (the same pipeline M1 wires
   for ``packages/s0ma-mcp``).
3. Type-checks the emitted modules with ``mypy --strict`` in a flat view
   (the auto-emitted ``__init__.py`` is excluded: emitted cross-module
   imports are top-level — ``from errors import …`` — matching the
   ``sys.path.insert(0, build_dir)`` consumption model ``bootstrap_imports``
   implements; the package-idiom ``__init__.py`` would make mypy assign the
   same file two module names and refuse).
4. Categorizes EVERY error using the build's own source maps:

   - (E) emitter — the error line falls outside every declaration's
     ``body_output`` range in the ``.s0ma.map``, i.e. on emitter-generated
     scaffolding (imports, ``register_*`` calls, ``@component`` blocks), or
     the error is ``untyped-decorator`` (the decorator application is
     emitter scaffolding even though mypy reports it on the authored
     ``def`` line). (E) errors are defects this plan must fix.
   - (A) authored — the error line falls inside a declaration's authored
     body. These define the authoring discipline for M2+ (recorded in the
     friction log), not transpiler defects.
   - (D) dependency — ``import-untyped`` / ``import-not-found``: a py.typed
     gap in an imported distribution. Sub-tagged ``D-core`` (must be ZERO
     since s0ma-core ships py.typed), ``D-dsl`` (expected exactly one per
     module — ``s0ma_dsl.runtime_bridge.registration`` — accepted by the
     M0 decision to defer dsl's py.typed; the package gate covers it with
     the documented ``ignore_missing_imports`` override in
     ``packages/s0ma-mcp/pyproject.toml``), or ``D-other``.

Exit code: 0 when zero (E)-category and zero uncategorizable errors were
found (D/A inventories are reported, not gated). Non-zero otherwise.

Usage:
    uv run python scripts/probe_strict_typing.py             # full corpus
    uv run python scripts/probe_strict_typing.py --keep      # keep scratch dir
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DSL_FIXTURES = ROOT / "packages" / "s0ma-dsl" / "tests" / "fixtures"

# ---------------------------------------------------------------------------
# Corpus definition
# ---------------------------------------------------------------------------

#: The synthetic module: the construct families s0ma-mcp code actually uses
#: (mirrors resources.py / tools.py shapes — typed str/JSON bodies, a frozen
#: dataclass, a dict constant, helpers, importlib.resources, and a
#: third-party typed import: the MCP SDK's ToolAnnotations).
MCP_LIKE_S0MA = '''\
module mcp_like
    layer: PRESENTATION
    version: 0.1.0
    intent: "Synthetic probe module exercising the construct families
        s0ma-mcp authoring uses: typed function bodies, module-level
        constants, dataclass models, helpers, and third-party typed
        imports (the MCP SDK ToolAnnotations)."
    requires: [json, dataclasses.dataclass, importlib:resources, mcp.types:ToolAnnotations, typing.Any]
    exports: [GuideDoc, GUIDE_FILENAMES, render_index_document, read_only_annotations]

cell GuideDoc :: PRESENTATION
    kind: MODEL
    visibility: PUBLIC
    intent: "One packaged document: key, MCP resource URI, and packaged
        filename."
    schema: "Frozen dataclass. key: str, uri: str, filename: str. All
        fields required."
    ---
    @dataclass(frozen=True)
    class GuideDoc:
        key: str
        uri: str
        filename: str

cell GUIDE_FILENAMES :: PRESENTATION
    kind: CONSTANT
    visibility: PUBLIC
    intent: "Maps every guide key to the data filename packaged for it."
    schema: "dict[str, str] constant keyed by guide key."
    ---
    GUIDE_FILENAMES: dict[str, str] = {
        "quick-reference": "quick_reference.md",
        "patterns": "patterns_guide.md",
    }

helper _normalize_key :: PRESENTATION
    intent: "Lowercase and strip a guide key before index lookup."
    ---
    def _normalize_key(key: str) -> str:
        return key.strip().lower()

helper _read_packaged_text :: PRESENTATION
    intent: "Resolve a packaged data file as UTF-8 text via importlib.resources,
        the way the s0ma-mcp guide loader does."
    ---
    def _read_packaged_text(package: str, filename: str) -> str:
        return resources.files(package).joinpath("_docs", filename).read_text(encoding="utf-8")

nerve render_index_document :: PRESENTATION
    kind: FUNCTION
    visibility: PUBLIC
    intent: "Render the guide index as a JSON document string for an MCP
        resource body."
    expects: "GUIDE_FILENAMES is non-empty"
    guarantees: "Returns pretty-printed JSON text listing every guide key"
    evaluates_at: FUNCTION_BOUNDARY
    depends_on:
        GUIDE_FILENAMES: {relation: READS, carries: "guide index", coupling: TIGHT}
    ---
    def render_index_document(prefix: str) -> str:
        document: dict[str, Any] = {
            "prefix": _normalize_key(prefix),
            "guides": sorted(GUIDE_FILENAMES),
        }
        return json.dumps(document, indent=2)

nerve read_only_annotations :: PRESENTATION
    kind: FUNCTION
    visibility: PUBLIC
    intent: "Build the MCP SDK ToolAnnotations record for a read-only,
        closed-world tool."
    expects: "title is a short human-readable label"
    guarantees: "Returns ToolAnnotations with readOnlyHint True and
        openWorldHint False"
    evaluates_at: FUNCTION_BOUNDARY
    ---
    def read_only_annotations(title: str) -> ToolAnnotations:
        return ToolAnnotations(
            title=title,
            readOnlyHint=True,
            destructiveHint=False,
            idempotentHint=True,
            openWorldHint=False,
        )
'''


@dataclass(frozen=True)
class Fixture:
    """One probe corpus entry: .s0ma sources to build + strict-check."""

    name: str
    #: (filename, text) pairs when synthetic; None when copied from a dir.
    synthetic: tuple[tuple[str, str], ...] | None = None
    #: Directory of .s0ma files to copy (repo-relative), when not synthetic.
    source_dir: Path | None = None
    #: Filenames to skip when copying (e.g. test-role modules).
    skip: frozenset[str] = frozenset()


CORPUS: tuple[Fixture, ...] = (
    Fixture(
        name="golden_project",
        source_dir=DSL_FIXTURES / "valid" / "golden_project",
        # task_tests.s0ma is a test-role module; the probe targets the
        # production construct families (s0ma-mcp tests stay plain pytest
        # per the selfhost plan's D-2).
        skip=frozenset({"task_tests.s0ma"}),
    ),
    Fixture(
        name="multi_module",
        source_dir=DSL_FIXTURES / "valid" / "multi_module",
    ),
    Fixture(
        name="helper_declarations",
        source_dir=DSL_FIXTURES / "helper_declarations" / "clean" / "src" / "sample",
    ),
    Fixture(
        name="mcp_like",
        synthetic=(("mcp_like.s0ma", MCP_LIKE_S0MA),),
    ),
)

# ---------------------------------------------------------------------------
# Categorization
# ---------------------------------------------------------------------------

_ERROR_RE = re.compile(r"^(?P<file>[^:]+):(?P<line>\d+): error: (?P<msg>.*?)\s*\[(?P<code>[\w-]+)\]$")


@dataclass
class ProbeError:
    module: str
    line: int
    code: str
    message: str
    category: str  # "E" | "A" | "D-core" | "D-dsl" | "D-other" | "UNCATEGORIZED"


@dataclass
class FixtureResult:
    name: str
    errors: list[ProbeError] = field(default_factory=list)
    build_failed: bool = False


def _body_ranges(map_path: Path) -> list[tuple[int, int]]:
    """The authored-body output line ranges recorded in a .s0ma.map.

    Helper declarations carry no ``body_output`` in the map (a recorded
    source-map gap — see the M0 friction log); their ``output`` range is
    the emitter's one ``# Helper: <intent>`` comment line followed by the
    authored body verbatim, so ``output.start_line + 1 .. output.end_line``
    is the authored-body range.
    """
    data = json.loads(map_path.read_text(encoding="utf-8"))
    ranges: list[tuple[int, int]] = []
    for decl in data.get("mappings", {}).get("declarations", []):
        body = decl.get("body_output")
        if body:
            ranges.append((int(body["start_line"]), int(body["end_line"])))
        elif decl.get("type") == "helper" and decl.get("output"):
            output = decl["output"]
            ranges.append((int(output["start_line"]) + 1, int(output["end_line"])))
    return ranges


def _categorize(code: str, msg: str, line: int, body_ranges: list[tuple[int, int]]) -> str:
    if code in {"import-untyped", "import-not-found"}:
        if '"s0ma_dsl' in msg:
            return "D-dsl"
        if '"s0ma.' in msg or msg.endswith('"s0ma"'):
            return "D-core"
        return "D-other"
    if code == "untyped-decorator":
        # Reported on the authored def line, but the decorator application
        # is emitter scaffolding — gate it as (E).
        return "E"
    if any(start <= line <= end for start, end in body_ranges):
        return "A"
    return "E"


# ---------------------------------------------------------------------------
# Probe pipeline
# ---------------------------------------------------------------------------


def _materialize(fixture: Fixture, scratch: Path) -> Path:
    """Create the scratch [tool.s0ma] project for a fixture; return its root."""
    project = scratch / fixture.name
    src = project / "src"
    src.mkdir(parents=True)
    if fixture.synthetic is not None:
        for filename, text in fixture.synthetic:
            (src / filename).write_text(text, encoding="utf-8", newline="\n")
    else:
        assert fixture.source_dir is not None
        for path in sorted(fixture.source_dir.glob("*.s0ma")):
            if path.name in fixture.skip:
                continue
            shutil.copyfile(path, src / path.name)
    (project / "pyproject.toml").write_text(
        f'[project]\nname = "probe_{fixture.name}"\nversion = "0.0.1"\n\n'
        '[tool.s0ma]\nsource_roots = ["src"]\nbuild_dir = "build"\n',
        encoding="utf-8",
        newline="\n",
    )
    return project


def _s0ma_cli() -> list[str]:
    """The s0ma CLI invocation: the venv console script, else module form."""
    script = shutil.which("s0ma")
    if script:
        return [script]
    return [sys.executable, "-m", "s0ma_dsl.cli.main"]


def _run_fixture(fixture: Fixture, scratch: Path, verbose: bool) -> FixtureResult:
    result = FixtureResult(name=fixture.name)
    project = _materialize(fixture, scratch)

    # --project-root anchors [tool.s0ma] discovery explicitly (discovery
    # otherwise walks up from the CWD, not from the build argument) — the
    # same flag s0ma_mcp's own build_project tool passes.
    build = subprocess.run(
        [*_s0ma_cli(), "--project-root", str(project), "build", str(project)],
        capture_output=True,
        text=True,
        cwd=project,
    )
    if build.returncode != 0:
        result.build_failed = True
        print(f"  BUILD FAILED ({fixture.name}):\n{build.stdout}\n{build.stderr}")
        return result

    build_dir = project / "build"
    if not build_dir.is_dir():  # harness guard: a missing build dir must
        result.build_failed = True  # never read as a zero-error PASS
        print(f"  BUILD PRODUCED NO build/ DIR ({fixture.name}):\n{build.stdout}")
        return result
    check_dir = project / "mypy_view"
    check_dir.mkdir()
    modules: list[str] = []
    for py in sorted(build_dir.glob("*.py")):
        if py.name == "__init__.py":  # see module docstring: flat view
            continue
        shutil.copyfile(py, check_dir / py.name)
        modules.append(py.stem)

    if not modules:  # harness guard: empty corpus must never PASS
        result.build_failed = True
        print(f"  NO EMITTED MODULES FOUND ({fixture.name})")
        return result

    mypy = subprocess.run(
        [
            sys.executable,
            "-m",
            "mypy",
            "--strict",
            "--no-incremental",
            "--cache-dir",
            str(project / ".mypy_probe_cache"),
            "--no-error-summary",
            *(f"{m}.py" for m in modules),
        ],
        capture_output=True,
        text=True,
        cwd=check_dir,
    )
    if mypy.returncode not in (0, 1):  # 2 = mypy usage/crash, not findings
        result.build_failed = True
        print(f"  MYPY DID NOT RUN CLEANLY ({fixture.name}, rc={mypy.returncode}):\n{mypy.stdout}\n{mypy.stderr}")
        return result

    ranges_by_module = {
        m: _body_ranges(build_dir / f"{m}.s0ma.map")
        for m in modules
        if (build_dir / f"{m}.s0ma.map").is_file()
    }
    for raw in mypy.stdout.splitlines():
        match = _ERROR_RE.match(raw.strip())
        if not match:
            if verbose and raw.strip():
                print(f"    (non-error line) {raw}")
            continue
        module = Path(match["file"]).stem
        line = int(match["line"])
        code = match["code"]
        category = _categorize(code, match["msg"], line, ranges_by_module.get(module, []))
        result.errors.append(ProbeError(module, line, code, match["msg"], category))
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="mypy --strict probe over emitted s0ma Python")
    parser.add_argument("--keep", action="store_true", help="keep the scratch dir (prints path)")
    parser.add_argument("--verbose", action="store_true", help="echo non-error mypy lines")
    opts = parser.parse_args(argv)

    scratch = Path(tempfile.mkdtemp(prefix="s0ma-strict-probe-"))
    print(f"=== s0ma strict-typing probe (scratch: {scratch}) ===")

    results = [_run_fixture(fixture, scratch, opts.verbose) for fixture in CORPUS]

    totals: dict[str, int] = {}
    print()
    for result in results:
        status = "BUILD-FAILED" if result.build_failed else f"{len(result.errors)} error(s)"
        print(f"--- {result.name}: {status}")
        for err in result.errors:
            totals[err.category] = totals.get(err.category, 0) + 1
            print(f"  [{err.category}] {err.module}.py:{err.line} [{err.code}] {err.message}")
    print("\n=== category totals ===")
    for category in ("E", "A", "D-core", "D-dsl", "D-other", "UNCATEGORIZED"):
        print(f"  {category:14} {totals.get(category, 0)}")

    gate_failures = totals.get("E", 0) + totals.get("UNCATEGORIZED", 0)
    build_failures = sum(1 for r in results if r.build_failed)
    if not opts.keep:
        shutil.rmtree(scratch, ignore_errors=True)
    else:
        print(f"\nscratch kept: {scratch}")
    if build_failures or gate_failures:
        print(
            f"\nPROBE GATE: FAIL ({build_failures} build failure(s), "
            f"{gate_failures} (E)/uncategorized error(s))"
        )
        return 1
    print("\nPROBE GATE: PASS (zero (E)-category errors; (A)/(D) inventories above)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
