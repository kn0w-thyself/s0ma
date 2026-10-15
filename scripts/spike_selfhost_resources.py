#!/usr/bin/env python3
"""The M0 feasibility spike, reproducible (selfhost plan, step 4).

Authors the s0ma-mcp RESOURCES surface as a real ``.s0ma`` module in a
scratch ``[tool.s0ma]`` project (embedded below — nothing in
``packages/s0ma-mcp`` changes; layout is M1's decision), builds it with the
real toolchain, and proves the four GO/NO-GO gates:

  (a) mypy --strict clean on the emitted module (same stance as the
      package gate: the documented ``s0ma_dsl.*`` ignore-missing-imports
      override; s0ma-core and s0ma-mcp resolve typed via py.typed);
  (b) deterministic rebuild — two cold builds (fresh build dir + cache),
      every artifact byte-identical; the manifest is compared as JSON and
      must be equal except the documented run-varying ``built_at`` field
      (M1's committed-build equality gate must normalize or drop it);
  (c) the EXISTING handwritten ``tests/test_resources.py`` suite (26
      tests) passes against the BUILT artifact via an import-redirection
      pytest-plugin shim (scratch-only, never landed), plus an explicit
      redirect verification that reads a resource through the in-process
      MCP boundary and asserts the serving module file IS the built one;
  (d) registration parity — every component ``components.py`` registers
      for the resources surface exists in the built module with a
      byte-identical intent and the same ComponentKind, with the two
      DSL-imposed deltas asserted exactly (URI/role catalog names vs
      identifier declaration names — the URI rides in the IR's
      ``declares_attributes``; and load_doc's INFRASTRUCTURE layer, which
      the one-layer-per-module rule + the PRESENTATION reachability
      matrix forbid in-module).

Exit 0 iff all four proofs PASS. Each proof prints PASS/FAIL evidence.

Usage:
    uv run python scripts/spike_selfhost_resources.py            # full run
    uv run python scripts/spike_selfhost_resources.py --keep     # keep scratch
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MCP_PKG = ROOT / "packages" / "s0ma-mcp"

# ---------------------------------------------------------------------------
# The spike module: resources.py ported to a .s0ma module. Intents of the
# nine components components.py registers today are byte-identical copies
# (proof d compares them). Bodies are ported verbatim where possible; the
# one cross-package piece (the self-model JSON renderer) is imported from
# s0ma_mcp.components via requires:, preserving behavior exactly.
# ---------------------------------------------------------------------------

RESOURCES_S0MA = r'''
module resources
    layer: PRESENTATION
    version: 0.7.0
    intent: "Agent-guide and meta resource providers for the s0ma authoring MCP server: the packaged alignment corpus (FR-MCP-3), the generated error catalog and changelog (FR-MCP-10), the live version surface, and the server's own self-model (FR-MCP-7)."
    requires: [json, platform, dataclasses.dataclass, importlib:metadata, importlib:resources, typing.Any, s0ma_mcp.components:self_model_json]
    exports: [GuideDoc, GUIDE_DOCS, load_doc, system_prompt_resource, quick_reference_resource, patterns_resource, spec_resource, errors_resource, changelog_resource, version_document, version_resource, self_model_resource]

cell SERVER_NAME :: PRESENTATION
    kind: CONSTANT
    visibility: INTERNAL
    intent: "The MCP server name (FR-MCP-1) rendered into the version document."
    schema: "str constant. Value: s0ma-authoring."
    ---
    SERVER_NAME: str = "s0ma-authoring"

cell GuideDoc :: PRESENTATION
    kind: MODEL
    visibility: PUBLIC
    intent: "One packaged document (agent guide or meta resource): its loader key, MCP resource URI, packaged filename, and drift-gate source path."
    schema: "Frozen dataclass. key: str, uri: str, filename: str, source: str. All fields required; source is repo-root-relative and used only by the drift gate."
    ---
    @dataclass(frozen=True)
    class GuideDoc:
        """One packaged document (agent guide or meta resource).

        Attributes:
            key: Short identifier used by :func:`load_doc`.
            uri: The MCP resource URI the server registers for it.
            filename: Filename inside ``s0ma_mcp/_docs/``.
            source: Repo-root-relative path of the in-repo source document
                this file is a committed copy of (the drift gate compares
                the two; most live under ``packages/s0ma-dsl/docs/``, the
                changelog at the repo root).
        """

        key: str
        uri: str
        filename: str
        source: str

cell GUIDE_DOCS :: PRESENTATION
    kind: CONSTANT
    visibility: PUBLIC
    intent: "Keyed registry of every packaged document the server serves: key, URI, packaged filename, and the in-repo source the drift gate byte-compares."
    schema: "dict[str, GuideDoc] keyed by loader key; source paths are monorepo-root-relative and exist only in a repo checkout."
    ---
    GUIDE_DOCS: dict[str, GuideDoc] = {
        doc.key: doc
        for doc in (
            GuideDoc(
                key="system-prompt",
                uri="s0ma://guide/system-prompt",
                filename="agent_system_prompt.md",
                source="packages/s0ma-dsl/docs/agent_system_prompt.md",
            ),
            GuideDoc(
                key="quick-reference",
                uri="s0ma://guide/quick-reference",
                filename="s0ma-dsl_quick_reference.md",
                source="packages/s0ma-dsl/docs/s0ma-dsl_quick_reference.md",
            ),
            GuideDoc(
                key="patterns",
                uri="s0ma://guide/patterns",
                filename="dsl_patterns_guide.md",
                source="packages/s0ma-dsl/docs/references/dsl_patterns_guide.md",
            ),
            GuideDoc(
                key="spec",
                uri="s0ma://spec/current",
                filename="s0ma-dsl-spec-v0.16.0.md",
                source="packages/s0ma-dsl/docs/s0ma-dsl-spec-v0.16.0.md",
            ),
            GuideDoc(
                key="errors",
                uri="s0ma://guide/errors",
                filename="common_errors.md",
                source="packages/s0ma-dsl/docs/_generated/common_errors.md",
            ),
            GuideDoc(
                key="changelog",
                uri="s0ma://meta/changelog",
                filename="CHANGELOG.md",
                source="CHANGELOG.md",
            ),
        )
    }

nerve load_doc :: PRESENTATION
    kind: ADAPTER
    visibility: PUBLIC
    intent: "Resolves the packaged agent-guide documents from s0ma_mcp/_docs package data via importlib.resources so they load from an installed wheel"
    expects: "key is one of the GUIDE_DOCS loader keys"
    guarantees: "Returns the packaged document's full UTF-8 text"
    evaluates_at: FUNCTION_BOUNDARY
    depends_on:
        GUIDE_DOCS: {relation: READS, carries: "packaged-document registry", coupling: TIGHT}
    ---
    def load_doc(key: str) -> str:
        """Return the full text of the packaged document ``key``.

        Args:
            key: One of ``"system-prompt"``, ``"quick-reference"``,
                ``"patterns"``, ``"spec"``, ``"errors"``, ``"changelog"``
                (see ``GUIDE_DOCS``).

        Returns:
            The document's UTF-8 text.

        Raises:
            KeyError: If ``key`` is not a known guide document.
            FileNotFoundError: If the packaged file is missing from the
                installed distribution (a packaging bug — the wheel smoke
                test in the consolidation plan exists to catch this).
        """
        doc = GUIDE_DOCS[key]
        path = resources.files("s0ma_mcp").joinpath("_docs", doc.filename)
        return path.read_text(encoding="utf-8")

nerve system_prompt_resource :: PRESENTATION
    kind: FUNCTION
    visibility: PUBLIC
    intent: "Serves the drop-in coding-agent system prompt that teaches an LLM how to author .s0ma files"
    expects: "the agent system prompt is packaged under s0ma_mcp/_docs"
    guarantees: "Returns the full prompt text"
    evaluates_at: FUNCTION_BOUNDARY
    declares_attributes: ["mcp_uri:s0ma://guide/system-prompt"]
    depends_on:
        load_doc: {relation: CALLS, carries: "loader key", coupling: TIGHT}
    ---
    def system_prompt_resource() -> str:
        """The s0ma DSL coding-agent system prompt.

        A drop-in prompt (or prompt fragment) instructing an LLM how to
        author .s0ma files: file structure, declaration types, required
        fields, body rules, dependency rules, visibility, naming.
        """
        return load_doc("system-prompt")

nerve quick_reference_resource :: PRESENTATION
    kind: FUNCTION
    visibility: PUBLIC
    intent: "Serves the one-page DSL quick reference an agent holds in context to author valid modules with only the MCP tools"
    expects: "the quick reference is packaged under s0ma_mcp/_docs"
    guarantees: "Returns the full quick-reference text"
    evaluates_at: FUNCTION_BOUNDARY
    declares_attributes: ["mcp_uri:s0ma://guide/quick-reference"]
    depends_on:
        load_doc: {relation: CALLS, carries: "loader key", coupling: TIGHT}
    ---
    def quick_reference_resource() -> str:
        """The one-page s0ma DSL quick reference — hold this in context.

        The survival guide for authoring: the golden rule (only edit
        .s0ma, never generated .py), project configuration, the
        development workflow, the CLI surface, declaration syntax, and
        common error codes. Designed so an agent holding only this
        document can produce a valid module using the tools here.
        """
        return load_doc("quick-reference")

nerve patterns_resource :: PRESENTATION
    kind: FUNCTION
    visibility: PUBLIC
    intent: "Serves the DSL patterns guide of worked idioms and recipes for structuring non-trivial s0ma applications"
    expects: "the patterns guide is packaged under s0ma_mcp/_docs"
    guarantees: "Returns the full patterns-guide text"
    evaluates_at: FUNCTION_BOUNDARY
    declares_attributes: ["mcp_uri:s0ma://guide/patterns"]
    depends_on:
        load_doc: {relation: CALLS, carries: "loader key", coupling: TIGHT}
    ---
    def patterns_resource() -> str:
        """The s0ma DSL patterns guide — idioms for real applications.

        Worked patterns and recipes (component shapes, layering,
        documentation declarations, testing) distilled from real s0ma
        projects. Read after the quick reference when structuring
        non-trivial modules.
        """
        return load_doc("patterns")

nerve spec_resource :: PRESENTATION
    kind: FUNCTION
    visibility: PUBLIC
    intent: "Serves the current normative s0ma DSL language specification — the authority when the guides are not enough"
    expects: "the language spec is packaged under s0ma_mcp/_docs"
    guarantees: "Returns the full specification text"
    evaluates_at: FUNCTION_BOUNDARY
    declares_attributes: ["mcp_uri:s0ma://spec/current"]
    depends_on:
        load_doc: {relation: CALLS, carries: "loader key", coupling: TIGHT}
    ---
    def spec_resource() -> str:
        """The current s0ma DSL language specification (normative).

        The full grammar and semantics: every declaration kind, field,
        namespace rule, strictness mode, error code, and artifact
        format. The authority when the guides are not enough.
        """
        return load_doc("spec")

nerve errors_resource :: PRESENTATION
    kind: FUNCTION
    visibility: PUBLIC
    intent: "Serves the generated diagnostic error catalog — every s0ma-dsl error code with its severity by mode and canonical fix"
    expects: "the generated error catalog is packaged under s0ma_mcp/_docs"
    guarantees: "Returns the full error-catalog text"
    evaluates_at: FUNCTION_BOUNDARY
    declares_attributes: ["mcp_uri:s0ma://guide/errors"]
    depends_on:
        load_doc: {relation: CALLS, carries: "loader key", coupling: TIGHT}
    ---
    def errors_resource() -> str:
        """The s0ma diagnostic error catalog (FR-MCP-10).

        Every s0ma-dsl error code in one table: severity per strictness
        mode (migration / dev / strict / release) and a one-sentence
        description of the cause and canonical fix. Look unfamiliar
        diagnostic codes up here while working the check loop — generated
        from the DSL's own error-code registry, so it cannot drift from
        the diagnostics the tools return.
        """
        return load_doc("errors")

nerve changelog_resource :: PRESENTATION
    kind: FUNCTION
    visibility: PUBLIC
    intent: "Serves the monorepo's canonical changelog so agents and humans can read what changed in the installed toolchain version"
    expects: "the changelog copy is packaged under s0ma_mcp/_docs"
    guarantees: "Returns the full changelog text"
    evaluates_at: FUNCTION_BOUNDARY
    declares_attributes: ["mcp_uri:s0ma://meta/changelog"]
    depends_on:
        load_doc: {relation: CALLS, carries: "loader key", coupling: TIGHT}
    ---
    def changelog_resource() -> str:
        """The s0ma platform changelog — what's new, per version (FR-MCP-10).

        The monorepo's canonical Keep-a-Changelog document covering every
        package (s0ma-core, s0ma-dsl, s0ma-mcp — one lockstep version,
        INV-4). Read it to learn what changed in the version you are
        running, or what an upgrade would bring; pair with
        s0ma://meta/version for the installed versions themselves.
        """
        return load_doc("changelog")

helper _dist_version :: PRESENTATION
    intent: "The installed version of a distribution, or None if it is absent from the environment."
    ---
    def _dist_version(distribution: str) -> str | None:
        """The installed version of ``distribution``, or ``None`` if absent."""
        try:
            return metadata.version(distribution)
        except metadata.PackageNotFoundError:  # pragma: no cover - broken env
            return None

nerve version_document :: PRESENTATION
    kind: FUNCTION
    visibility: PUBLIC
    intent: "Builds the version surface as a JSON-compatible dict, rendered live from importlib.metadata with no file reads and no network (FR-MCP-10, P-6)"
    expects: "importlib.metadata can see the installed distributions"
    guarantees: "Returns a dict with server, s0ma_core, s0ma_dsl, s0ma_mcp, mcp_sdk, and python keys; None marks a distribution that is not installed"
    evaluates_at: FUNCTION_BOUNDARY
    depends_on:
        SERVER_NAME: {relation: READS, carries: "server identity", coupling: TIGHT}
    ---
    def version_document() -> dict[str, Any]:
        """The version surface as a JSON-compatible dict (FR-MCP-10).

        Rendered live from ``importlib.metadata`` — no packaged file, no
        network (PRD P-6 / plan D-2). ``None`` marks a distribution that is
        not installed (a broken environment the answer should not hide).
        """
        return {
            "server": SERVER_NAME,
            "s0ma_core": _dist_version("s0ma-core"),
            "s0ma_dsl": _dist_version("s0ma-dsl"),
            "s0ma_mcp": _dist_version("s0ma-mcp"),
            "mcp_sdk": _dist_version("mcp"),
            "python": platform.python_version(),
        }

nerve version_resource :: PRESENTATION
    kind: FUNCTION
    visibility: PUBLIC
    intent: "Serves the installed toolchain versions (server, the three s0ma distributions, MCP SDK, Python) live from importlib.metadata — offline by design"
    expects: "version_document renders the installed distributions"
    guarantees: "Returns the version document as pretty-printed JSON text"
    evaluates_at: FUNCTION_BOUNDARY
    declares_attributes: ["mcp_uri:s0ma://meta/version"]
    depends_on:
        version_document: {relation: CALLS, carries: "version document", coupling: TIGHT}
    ---
    def version_resource() -> str:
        """The installed s0ma toolchain versions as JSON (FR-MCP-10).

        One document answering "what exactly am I talking to":
        {server, s0ma_core, s0ma_dsl, s0ma_mcp, mcp_sdk, python} — the
        server name and the installed versions of the three s0ma
        distributions, the MCP SDK, and the Python runtime, rendered live
        via importlib.metadata. Offline by design: no file is read and no
        network is touched. Pair with s0ma://meta/changelog to see what
        your versions contain.
        """
        return json.dumps(version_document(), indent=2)

nerve self_model_resource :: PRESENTATION
    kind: FUNCTION
    visibility: PUBLIC
    intent: "Serves this server's own live component graph as JSON — every tool, resource, and factory with kind, layer, intent, and dependencies (FR-MCP-7)"
    expects: "the s0ma_mcp self-model registry is importable"
    guarantees: "Returns the live component graph as pretty-printed JSON text"
    evaluates_at: FUNCTION_BOUNDARY
    declares_attributes: ["mcp_uri:s0ma://self/model"]
    ---
    def self_model_resource() -> str:
        """The authoring server's live self-model (FR-MCP-7) as JSON.

        The server eats its own dog food: every MCP tool and resource here
        is a registered s0ma component, and this document is the live
        graph — components with name, kind, layer, intent, and
        dependencies, rendered through s0ma-core's own registry snapshot,
        plus the server's name and version. Read it to learn what this
        server is and what it can do; the ``describe_server`` tool returns
        the same graph with an LLM-ready text rendering.
        """
        return self_model_json()
'''

PYPROJECT = '''[project]
name = "selfhost_spike"
version = "0.0.1"

[tool.s0ma]
source_roots = ["src"]
build_dir = "build"
'''

#: Mirrors the package gate's mypy stance (packages/s0ma-mcp/pyproject.toml):
#: strict everywhere; s0ma_dsl.* untyped by the documented M0 defer decision.
MYPY_INI = """[mypy]
strict = True

[mypy-s0ma_dsl.*]
ignore_missing_imports = True
"""

SHIM = '''"""Import-redirection shim (selfhost spike, M0 — scratch only, never landed).

Loaded via ``pytest -p s0ma_selfhost_shim`` BEFORE collection: installs the
spike's BUILT resources module into sys.modules under ``s0ma_mcp.resources``
so the existing handwritten test suite exercises the built artifact.
"""
import importlib.util
import sys
from pathlib import Path

BUILT = Path(__file__).resolve().parent.parent / "build" / "resources.py"

spec = importlib.util.spec_from_file_location("s0ma_mcp.resources", BUILT)
assert spec is not None and spec.loader is not None
module = importlib.util.module_from_spec(spec)
sys.modules["s0ma_mcp.resources"] = module
spec.loader.exec_module(module)

import s0ma_mcp  # noqa: E402  (bind the parent attribute explicitly too)

s0ma_mcp.resources = module
'''

REDIRECT_CHECK = '''import asyncio
import s0ma_selfhost_shim  # installs the redirect
from s0ma_mcp import resources
from s0ma_mcp.server import create_server

built = s0ma_selfhost_shim.BUILT.resolve()
assert Path(resources.__file__).resolve() == built, resources.__file__
server = create_server()
content = list(asyncio.run(server.read_resource("s0ma://guide/quick-reference")))[0].content
assert "Golden Rule" in content
print(f"redirect verified: served {len(content)} bytes from {resources.__file__}")
'''

PARITY = '''"""Registration parity (spike proof d): built module vs components.py."""
import importlib.util
import sys
from pathlib import Path

BUILD = Path(sys.argv[1])

import s0ma_mcp.components as comp
import s0ma_mcp.resources  # noqa: F401  decorations fill the catalog
import s0ma_mcp.prompts, s0ma_mcp.tools, s0ma_mcp.server  # noqa: F401,E401

today = {}
for name, spec in comp._CATALOG.items():
    if spec.module_path == "s0ma_mcp.resources":
        fn = spec.qualified_name.rsplit(".", 1)[-1]
        today[fn] = spec

spec_obj = importlib.util.spec_from_file_location("spike_built_resources", BUILD)
mod = importlib.util.module_from_spec(spec_obj)
sys.modules["spike_built_resources"] = mod
spec_obj.loader.exec_module(mod)

built = {}
for attr in vars(mod).values():
    cs = getattr(attr, "__component__", None)
    # Only specs the built module itself registered (imported names like
    # the dsl bridge functions carry their OWN __component__ from the
    # dsl framework self-registration — not part of this module).
    if cs is not None and cs.module_path == "spike_built_resources":
        built[cs.name] = cs

failures = []
deltas = []
for fn, t in sorted(today.items()):
    b = built.get(fn)
    if b is None:
        failures.append(f"MISSING in built module: {fn} (catalog name {t.name!r})")
        continue
    if b.intent != t.intent:
        failures.append(f"INTENT DIFFERS for {fn}: today {t.intent!r} built {b.intent!r}")
    if b.kind != t.kind:
        failures.append(f"KIND DIFFERS for {fn}: today {t.kind} built {b.kind}")
    if t.name != fn:
        deltas.append(f"name form: catalog {t.name!r} -> declaration {fn!r}")
    if b.layer != t.layer:
        if fn == "load_doc":
            deltas.append(f"layer: load_doc {t.layer.name} -> {b.layer.name} (one-layer-per-module)")
        else:
            failures.append(f"LAYER DIFFERS for {fn}: today {t.layer} built {b.layer}")
    if list(b.dependencies) != list(t.dependencies):
        deltas.append(f"deps for {fn}: {list(t.dependencies)} -> {list(b.dependencies)}")

extras = sorted(set(built) - set(today))
if extras != ["GuideDoc", "version_document"]:
    failures.append(f"UNEXPECTED additive components: {extras}")

print(f"today: {len(today)} resources-surface components; built: {len(built)}")
print("documented deltas (asserted, not silent):")
for d in deltas:
    print(f"  - {d}")
print(f"  - additive registrations: {extras}")
if failures:
    print("PARITY: FAIL")
    for f in failures:
        print(f"  ! {f}")
    sys.exit(1)
print("PARITY: PASS (all components present; intents byte-identical; kinds equal)")
'''

# The parity module needs Path imported for sys.argv handling at top.
PARITY = "from pathlib import Path  # noqa: F401  (re-exported for clarity)\n" + PARITY

REDIRECT_CHECK = "from pathlib import Path\n" + REDIRECT_CHECK


def _s0ma_cli() -> list[str]:
    script = shutil.which("s0ma")
    if script:
        return [script]
    return [sys.executable, "-m", "s0ma_dsl.cli.main"]


def _build(project: Path) -> None:
    result = subprocess.run(
        [*_s0ma_cli(), "--project-root", str(project), "build", str(project)],
        capture_output=True,
        text=True,
        cwd=project,
    )
    if result.returncode != 0 or not (project / "build").is_dir():
        raise SystemExit(f"spike build failed:\n{result.stdout}\n{result.stderr}")


def proof_b_deterministic_rebuild(project: Path) -> bool:
    """Two cold builds; byte-compare; manifest equal modulo built_at."""
    shutil.rmtree(project / "build", ignore_errors=True)
    shutil.rmtree(project / ".s0ma.cache", ignore_errors=True)
    _build(project)
    first = project / "build_first"
    shutil.copytree(project / "build", first)
    shutil.rmtree(project / "build")
    shutil.rmtree(project / ".s0ma.cache", ignore_errors=True)
    _build(project)
    second = project / "build"

    ok = True
    # Compare emitted FILES; the .s0ma.cache subdirectory is regenerable
    # incremental-build state (anchored inside build_dir here), not an
    # artifact — wiped between the two cold builds anyway.
    names_first = sorted(p.name for p in first.iterdir() if p.is_file())
    names_second = sorted(p.name for p in second.iterdir() if p.is_file())
    if names_first != names_second:
        print(f"  file sets differ: {names_first} vs {names_second}")
        ok = False
    for name in names_first:
        a, b = (first / name).read_bytes(), (second / name).read_bytes()
        if name == "build.s0ma.json":
            da, db = json.loads(a), json.loads(b)
            varying = {k for k in set(da) | set(db) if da.get(k) != db.get(k)}
            if varying - {"built_at"}:
                print(f"  manifest differs beyond built_at: {sorted(varying)}")
                ok = False
            else:
                note = "byte-identical" if a == b else "equal modulo built_at (run-varying by design; M1 gate must handle)"
                print(f"  build.s0ma.json: {note}")
        elif a != b:
            print(f"  BYTE DIFFERENCE in {name}")
            ok = False
    if ok:
        print(f"  {len(names_first) - 1} artifact file(s) byte-identical across two cold builds")
    return ok


def proof_a_mypy_strict(project: Path) -> bool:
    (project / "mypy-spike.ini").write_text(MYPY_INI, encoding="utf-8", newline="\n")
    result = subprocess.run(
        [
            sys.executable, "-m", "mypy",
            "--config-file", str(project / "mypy-spike.ini"),
            "--cache-dir", str(project / ".mypy_spike_cache"),
            str(project / "build" / "resources.py"),
        ],
        capture_output=True,
        text=True,
        cwd=project,
    )
    print(f"  mypy --strict: {result.stdout.strip() or result.stderr.strip()}")
    return result.returncode == 0


def proof_c_existing_suite(project: Path) -> bool:
    shim_dir = project / "shim"
    shim_dir.mkdir(exist_ok=True)
    (shim_dir / "s0ma_selfhost_shim.py").write_text(SHIM, encoding="utf-8", newline="\n")
    env = {**os.environ, "PYTHONPATH": str(shim_dir)}
    pytest_run = subprocess.run(
        [sys.executable, "-m", "pytest", "tests/test_resources.py", "-p", "s0ma_selfhost_shim", "-q"],
        capture_output=True,
        text=True,
        cwd=MCP_PKG,
        env=env,
    )
    tail = [ln for ln in pytest_run.stdout.splitlines() if ln.strip()][-1:]
    print(f"  pytest tests/test_resources.py (shimmed): {' '.join(tail)} (rc={pytest_run.returncode})")
    if pytest_run.returncode != 0:
        print(pytest_run.stdout)
        return False
    (shim_dir / "redirect_check.py").write_text(REDIRECT_CHECK, encoding="utf-8", newline="\n")
    redirect = subprocess.run(
        [sys.executable, str(shim_dir / "redirect_check.py")],
        capture_output=True,
        text=True,
        cwd=MCP_PKG,
        env=env,
    )
    print(f"  {redirect.stdout.strip() or redirect.stderr.strip()}")
    return redirect.returncode == 0


def proof_d_registration_parity(project: Path) -> bool:
    parity_path = project / "parity_check.py"
    parity_path.write_text(PARITY, encoding="utf-8", newline="\n")
    result = subprocess.run(
        [sys.executable, str(parity_path), str(project / "build" / "resources.py")],
        capture_output=True,
        text=True,
        cwd=MCP_PKG,
    )
    for line in result.stdout.splitlines():
        print(f"  {line}")
    if result.returncode != 0:
        print(result.stderr)
    return result.returncode == 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="M0 selfhost feasibility spike (resources surface)")
    parser.add_argument("--keep", action="store_true", help="keep the scratch dir (prints path)")
    opts = parser.parse_args(argv)

    scratch = Path(tempfile.mkdtemp(prefix="s0ma-selfhost-spike-"))
    project = scratch / "spike"
    (project / "src").mkdir(parents=True)
    (project / "src" / "resources.s0ma").write_text(
        RESOURCES_S0MA.lstrip("\n"), encoding="utf-8", newline="\n"
    )
    (project / "pyproject.toml").write_text(PYPROJECT, encoding="utf-8", newline="\n")
    print(f"=== s0ma selfhost spike (scratch: {project}) ===")

    results: dict[str, bool] = {}
    print("\n[proof b] deterministic rebuild (two cold builds, byte-compare)")
    results["b"] = proof_b_deterministic_rebuild(project)
    print("\n[proof a] mypy --strict on the emitted module (package-gate stance)")
    results["a"] = proof_a_mypy_strict(project)
    print("\n[proof c] existing test_resources.py against the built artifact (shim)")
    results["c"] = proof_c_existing_suite(project)
    print("\n[proof d] registration parity vs components.py")
    results["d"] = proof_d_registration_parity(project)

    print("\n=== spike verdict ===")
    for key in ("a", "b", "c", "d"):
        print(f"  proof ({key}): {'PASS' if results[key] else 'FAIL'}")
    if not opts.keep:
        shutil.rmtree(scratch, ignore_errors=True)
    else:
        print(f"scratch kept: {scratch}")
    if all(results.values()):
        print("\nSPIKE: ALL FOUR PROOFS PASS")
        return 0
    print("\nSPIKE: FAILED PROOF(S) — see evidence above")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
