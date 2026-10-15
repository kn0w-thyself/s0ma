#!/usr/bin/env python3
"""Release-integrity gate for wheel licenses and a cold installed journey.

The gate builds every distributable wheel once, inspects their
metadata/LICENSE payloads (plus the studi0 wheel's shipped build payload),
checks that the documentation the wheels carry is the documentation this
build composed, installs them in a temporary uv environment, then
exercises only installed artifacts from outside the checkout. It is
intentionally part of the canonical ``scripts/check.py`` run.

The documentation half is milestone H2 of ``plans/complete/s0ma-doc-function-1.md``
§13 — see *Exact-wheel documentation identity* below. It runs here rather
than in a suite because it is a claim about **wheels**, and the only way
to know what a wheel carries is to build one and look. The same
assertions are what ``.github/workflows/release.yml`` runs as a pre-serve
gate on a tagged commit (``--docs-identity-only``), so a release whose
wheels and documentation disagree stops before anything is published.
"""

from __future__ import annotations

import argparse
import email
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
import tomllib
import zipfile
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


@dataclass(frozen=True)
class PackageLicense:
    distribution: str
    expression: str
    classifier: str
    license_heading: str


EXPECTED = (
    PackageLicense(
        "s0ma-core",
        "Apache-2.0",
        "License :: OSI Approved :: Apache Software License",
        "Apache License",
    ),
    PackageLicense(
        "s0ma-dsl",
        "Apache-2.0",
        "License :: OSI Approved :: Apache Software License",
        "Apache License",
    ),
    PackageLicense(
        "s0ma-mcp",
        "Apache-2.0",
        "License :: OSI Approved :: Apache Software License",
        "Apache License",
    ),
    PackageLicense(
        "s0ma-studi0",
        "Apache-2.0",
        "License :: OSI Approved :: Apache Software License",
        "Apache License",
    ),
)

#: studi0's committed build output, which SHIPS in its wheel (the same
#: self-hosted posture as s0ma-mcp): the package ``__init__`` bootstraps
#: these emitted modules at import time, so a wheel missing any of them
#: installs a viewer that cannot start.
STUDI0_BUILT = ROOT / "packages/s0ma-studi0/src/s0ma_studi0/_built"


PROBE = r'''\
"""Cold acceptance using only installed wheels, outside the checkout."""
from __future__ import annotations

import asyncio
import json
import re
import subprocess
import sys
from importlib import metadata
from pathlib import Path

import s0ma
import s0ma_dsl
import s0ma_mcp
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from s0ma_mcp import tools

#: The client-visible surface the installed wheel must serve, injected by
#: scripts/wheel_smoke.py from the committed contract snapshot. This probe
#: deliberately runs OUTSIDE the checkout against installed artifacts only,
#: so the expectation is interpolated in rather than re-read here.
EXPECTED_SURFACE: dict[str, list[str]] = {}  # WHEEL_SMOKE_EXPECTED_SURFACE

#: How this release's version must be written wherever a reader meets it —
#: ``0.18.1`` for a release build, ``0.18.1 (preview)`` otherwise —
#: computed from the release manifest by scripts/wheel_smoke.py and
#: injected, for the same reason the surface above is: this probe runs
#: outside the checkout and may not read the manifest itself.
EXPECTED_VERSION_LINE = ""  # WHEEL_SMOKE_EXPECTED_VERSION_LINE

#: The digest of the record set this release's documentation was composed
#: from, as the release manifest records it. Injected for the same reason
#: as the two above, and used for the one claim the ``s0ma docs`` commands
#: below are here to make: the documentation an installed toolchain reads
#: is THIS build's, not a stale copy somebody's mirror step missed.
EXPECTED_SNAPSHOT_HASH = ""  # WHEEL_SMOKE_EXPECTED_SNAPSHOT_HASH

for module in (s0ma, s0ma_dsl, s0ma_mcp):
    assert "site-packages" in str(Path(module.__file__).resolve()), module.__file__
versions = {name: metadata.version(name) for name in ("s0ma-core", "s0ma-dsl", "s0ma-mcp")}
assert len(set(versions.values())) == 1, versions
print("cold: versions/imports", versions)

BIN = Path(sys.executable).absolute().parent
EXE = ".exe" if sys.platform == "win32" else ""
S0MA = (BIN / f"s0ma{EXE}").absolute()
S0MA_MCP = (BIN / f"s0ma-mcp{EXE}").absolute()
for executable in (S0MA, S0MA_MCP):
    assert executable.is_file(), executable
    assert executable.parent == BIN, (executable, BIN)


def run(*args: str, cwd: Path, expect: int = 0) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        [str(a) for a in args], cwd=cwd, capture_output=True, text=True, timeout=180
    )
    if result.returncode != expect:
        raise AssertionError(
            f"command {args!r} returned {result.returncode}, expected {expect}\n"
            f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
        )
    return result


async def handshake() -> None:
    parameters = StdioServerParameters(command=str(S0MA_MCP), args=[])
    async with stdio_client(parameters) as (read, write):
        async with ClientSession(read, write) as session:
            initialized = await session.initialize()
            assert initialized.serverInfo.name == "s0ma-authoring", initialized
            listed_tools = await session.list_tools()
            listed_resources = await session.list_resources()
            listed_prompts = await session.list_prompts()
            served = {
                "tools": sorted(tool.name for tool in listed_tools.tools),
                "resources": sorted(
                    str(resource.uri) for resource in listed_resources.resources
                ),
                "prompts": sorted(prompt.name for prompt in listed_prompts.prompts),
            }
            assert served == EXPECTED_SURFACE, (
                "the installed wheel serves a different MCP surface than the "
                "committed snapshot contract",
                {
                    kind: {
                        "missing": sorted(set(EXPECTED_SURFACE[kind]) - set(names)),
                        "unexpected": sorted(set(names) - set(EXPECTED_SURFACE[kind])),
                    }
                    for kind, names in served.items()
                    if names != EXPECTED_SURFACE[kind]
                },
            )


asyncio.run(handshake())
print("cold: MCP stdio initialize/list handshake")

scratch = Path.cwd()
doctor = run(str(S0MA), "doctor", "--format", "json", cwd=scratch)
assert "s0ma" in doctor.stdout.lower()

project = scratch / "my-app"
run(str(S0MA), "new", "project", str(project), "--quiet", cwd=scratch)

# Host verification requires the application to declare the always-emitted
# runtime packages. The wheels are installed in this exact host interpreter.
pyproject = project / "pyproject.toml"
project_text = pyproject.read_text(encoding="utf-8")
project_text = project_text.replace(
    'version = "0.1.0"\n',
    'version = "0.1.0"\ndependencies = ["s0ma-core", "s0ma-dsl"]\n',
    1,
)
pyproject.write_text(project_text, encoding="utf-8", newline="\n")

run(str(S0MA), "--project-root", str(project), "check", "--mode", "release", cwd=scratch)
run(str(S0MA), "--project-root", str(project), "score", "--gate-mode", "release", "--gate", cwd=scratch)
run(str(S0MA), "--project-root", str(project), "build", str(project), cwd=scratch)

status = tools.project_status_tool(project_root=str(project))
assert status["ok"] is True and status["is_project"] is True, status
assert status["build"]["status"] == "fresh", status
inspected = tools.inspect_module_tool(project_root=str(project), module="core_domain")
assert inspected["ok"] is True and "ir" in inspected, inspected
module_ir = inspected["ir"]
assert module_ir["module"]["name"] == "core_domain", module_ir["module"]
assert module_ir["imports"]["uses"] == {"state": "value", "value": []}, module_ir["imports"]
print("cold: project_status + canonical module/dependency inspection")

generated = project / "build" / "core_domain.py"
generated.write_text(
    generated.read_text(encoding="utf-8") + "\n# deliberate generated drift\n",
    encoding="utf-8",
    newline="\n",
)
drift = run(
    str(S0MA), "--project-root", str(project), "build", str(project), cwd=scratch, expect=1
)
assert "GENERATED_FILE_DRIFT" in drift.stdout + drift.stderr, drift
run(
    str(S0MA), "--project-root", str(project), "build", str(project), "--force", cwd=scratch
)

source = project / "src" / "core" / "core_domain.s0ma"
original = source.read_text(encoding="utf-8")
pending = re.sub(
    r'(?m)^(\s*guarantees:)\s*"[^"]*"$',
    r'\1 pending("replace this temporary release debt")',
    original,
    count=1,
)
assert pending != original
source.write_text(pending, encoding="utf-8", newline="\n")
red = run(
    str(S0MA), "--project-root", str(project), "check", "--mode", "release", cwd=scratch, expect=1
)
assert "PENDING" in (red.stdout + red.stderr).upper(), red
red_score = run(
    str(S0MA), "--project-root", str(project), "score", "--gate-mode", "release", "--gate", cwd=scratch, expect=1
)
assert "pending" in (red_score.stdout + red_score.stderr).lower(), red_score
source.write_text(original, encoding="utf-8", newline="\n")
run(str(S0MA), "--project-root", str(project), "check", "--mode", "release", cwd=scratch)
run(str(S0MA), "--project-root", str(project), "score", "--gate-mode", "release", "--gate", cwd=scratch)
run(str(S0MA), "--project-root", str(project), "build", str(project), cwd=scratch)
print("cold: generated drift and pending release debt both blocked, recovery green")

host = run(
    str(S0MA),
    "--project-root", str(project),
    "verify-host",
    "--format", "json",
    "--gate-mode", "release",
    "--python", sys.executable,
    cwd=scratch,
)
host_document = json.loads(host.stdout)
assert host_document["schema"] == "s0ma-host-verification@1", host_document
assert host_document["gate"]["passes"] is True, host_document["gate"]
print("cold: explicit verify_host passed under installed-wheel interpreter")

# H2, assertion 3, in its rendered form. Everything above proves the
# payloads agree with the manifest as data; this asks the installed wheels
# the question a reader asks — "which build am I being taught by?" — and
# requires the answer to be the release being built, written the one way
# the manifest says it must be written. Both servers are asked, because
# the failure this is for is one channel keeping a stale or unlabelled
# line while the other is fixed.
from s0ma._bootstrap import bootstrap_register
from s0ma.api.teaching import TeachingProvider
from s0ma.registry import ComponentRegistry
from s0ma_mcp import resources

registry = ComponentRegistry(persist=False)
bootstrap_register(registry)
teacher = TeachingProvider(registry, docs_dir=Path("/nonexistent_dir"))
lesson = teacher.learn_topic("nerve")
assert f"came from s0ma {EXPECTED_VERSION_LINE}," in lesson, lesson[-300:]

identity = resources.docs_snapshot_identity()
assert identity["version_line"] == EXPECTED_VERSION_LINE, identity
for name in ("docs_index_resource", "docs_concepts_resource", "docs_journeys_resource"):
    served = getattr(resources, name)()
    assert f"s0ma {EXPECTED_VERSION_LINE}" in served, (name, served[:300])
print(f"cold: every served identity line says {EXPECTED_VERSION_LINE!r}")

# The four read commands, from an installed toolchain with no checkout
# anywhere above the working directory. This is the assertion whose absence
# let `s0ma docs` ship broken: the snapshot went into the mcp wheel for the
# MCP resources and into core as a teaching slice, the dsl wheel got
# nothing, and every one of these commands answered "no documentation
# snapshot was found" for four milestones — while `s0ma --help`, `s0ma
# adopt init`, `s0ma adopt status` and the AGENTS.md block that `init`
# writes into a user's repository all sent people here.
docs = run(str(S0MA), "docs", cwd=scratch)
identity = docs.stdout.splitlines()[0]
assert EXPECTED_SNAPSHOT_HASH in identity, (
    f"the installed toolchain reads a different documentation build than "
    f"this release composed: its identity line is {identity!r} and the "
    f"release manifest's snapshot_hash is {EXPECTED_SNAPSHOT_HASH}"
)
assert "(installed)" in identity, (
    f"`s0ma docs` outside a checkout must answer from the wheel and say so; "
    f"its first line was {identity!r}"
)
assert f"s0ma {EXPECTED_VERSION_LINE}" in identity, identity

for argv, wanted in (
    (["docs", "list"], "concept:nerve"),
    (["docs", "show", "concept:nerve"], "concept:nerve"),
    (
        ["docs", "show", "doc:guide/retrofit-existing-codebase"],
        "Retrofitting an existing codebase",
    ),
    (["docs", "search", "drift"], "concept:drift"),
):
    answer = run(str(S0MA), *argv, cwd=scratch)
    first = answer.stdout.splitlines()[0]
    assert "(installed)" in first and EXPECTED_SNAPSHOT_HASH in first, (argv, first)
    assert wanted in answer.stdout, (argv, wanted, answer.stdout[:400])
print("cold: s0ma docs / list / show / search answer from the installed wheel")
'''


#: The committed client-visible MCP surface contract (AGENTS.md: regenerate
#: it only for an approved surface change; the count budget it must stay
#: inside is docs/contracts/0.14.0-schema-and-surface-budget.md §8, as
#: amended by its revision R1). The cold probe asserts the installed wheel
#: serves exactly these names, so this gate follows an approved surface
#: change automatically instead of carrying a second hand-maintained count.
SURFACE_SNAPSHOT = ROOT / "packages/s0ma-mcp/tests/snapshots/mcp_surface.json"


def cold_probe_source() -> str:
    """The probe with the values it may not read itself interpolated in.

    Three of them: the served MCP surface contract, how this release's
    version must be written (H2), and the snapshot digest this build's
    documentation was composed from. All three are facts of the
    *checkout*, and the probe deliberately runs outside it against
    installed artifacts only.
    """
    document = json.loads(SURFACE_SNAPSHOT.read_text(encoding="utf-8"))
    expected = {
        "tools": sorted(str(item["name"]) for item in document["tools"]),
        "resources": sorted(str(item["uri"]) for item in document["resources"]),
        "prompts": sorted(str(item["name"]) for item in document["prompts"]),
    }
    assert expected["tools"] and expected["resources"] and expected["prompts"], expected

    from s0ma_dsl.docs_model.manifest import manifest_from_json

    manifest = manifest_from_json(DOCS_MANIFEST.read_text(encoding="utf-8"))
    source = PROBE
    for marker, value in (
        ("WHEEL_SMOKE_EXPECTED_SURFACE", expected),
        ("WHEEL_SMOKE_EXPECTED_VERSION_LINE", _expected_version_line(manifest)),
        ("WHEEL_SMOKE_EXPECTED_SNAPSHOT_HASH", str(manifest.snapshot_hash)),
    ):
        line = next(
            candidate
            for candidate in source.splitlines()
            if candidate.endswith(f"  # {marker}")
        )
        name = line.split("=", 1)[0].split(":")[0].strip()
        source = source.replace(line, f"{name} = {value!r}", 1)
    return source


def run(argv: list[object], *, cwd: Path) -> None:
    rendered = [str(item) for item in argv]
    print(f"$ {' '.join(rendered)}", flush=True)
    subprocess.run(rendered, cwd=cwd, check=True)


def _metadata(wheel: Path) -> tuple[email.message.Message, str, list[str]]:
    with zipfile.ZipFile(wheel) as archive:
        names = archive.namelist()
        metadata_paths = [name for name in names if name.endswith(".dist-info/METADATA")]
        if len(metadata_paths) != 1:
            raise AssertionError(f"{wheel.name}: expected one METADATA, got {metadata_paths}")
        document = email.message_from_bytes(archive.read(metadata_paths[0]))
        licenses = [
            name
            for name in names
            if re.search(r"\.dist-info/(?:licenses/)?LICENSE$", name)
        ]
        if len(licenses) != 1:
            raise AssertionError(f"{wheel.name}: expected one bundled LICENSE, got {licenses}")
        return document, archive.read(licenses[0]).decode("utf-8"), licenses


def _assert_source_posture() -> None:
    root_readme = (ROOT / "README.md").read_text(encoding="utf-8")
    prd = (ROOT / "references/s0ma-prd.md").read_text(encoding="utf-8")
    assert "s0ma-core: Apache-2.0" in root_readme
    assert "s0ma-dsl: Apache-2.0" in root_readme
    assert "s0ma-mcp: Apache-2.0" in root_readme
    assert "s0ma-studi0: Apache-2.0" in root_readme
    assert "`s0ma-core`: Apache-2.0, in perpetuity" in prd
    assert "`s0ma-dsl`: Apache-2.0 (relicensed from the commercial license" in prd
    assert (
        "`s0ma-mcp` and `s0ma-studi0`: Apache-2.0 (relicensed from LicenseRef-Proprietary"
        in prd
    )
    assert "**Every distribution the monorepo ships is Apache-2.0**" in prd

    # The repository root carries the license too, byte-identical to the
    # copy in every wheel, and a NOTICE beside it. A root that lost either
    # would leave the public repository with no license GitHub can detect.
    root_license = (ROOT / "LICENSE").read_bytes()
    assert root_license == (ROOT / "packages/s0ma-core/LICENSE").read_bytes()
    notice = (ROOT / "NOTICE").read_text(encoding="utf-8")
    assert notice.startswith("s0ma\n")
    assert "Copyright 2026" in notice

    for expected in EXPECTED:
        package = ROOT / "packages" / expected.distribution
        project = tomllib.loads((package / "pyproject.toml").read_text(encoding="utf-8"))[
            "project"
        ]
        assert project["license"] == expected.expression
        assert expected.classifier in project["classifiers"]
        # lstrip: the canonical Apache-2.0 text opens with a centered
        # (whitespace-led) title line.
        assert (package / "LICENSE").read_text(encoding="utf-8").lstrip().startswith(
            expected.license_heading
        )
        readme = (package / "README.md").read_text(encoding="utf-8")
        if expected.expression == "Apache-2.0":
            assert "## License\n\nApache" in readme
        else:
            # Every distribution is Apache-2.0 today. The branch stays so a
            # future exception has to be written down rather than assumed.
            raise AssertionError(
                f"{expected.distribution}: no README license-block rule for "
                f"{expected.expression!r}"
            )

    ci = (ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8")
    assert "os: [ubuntu-latest, windows-latest]" in ci
    assert 'python-version: ["3.11", "3.12", "3.13"]' in ci
    assert '- os: windows-latest\n            python-version: "3.12"' in ci
    for expected in EXPECTED:
        project = tomllib.loads(
            (ROOT / "packages" / expected.distribution / "pyproject.toml").read_text(
                encoding="utf-8"
            )
        )["project"]
        assert project["requires-python"] == ">=3.11"
        classifiers = set(project["classifiers"])
        assert {
            "Programming Language :: Python :: 3.11",
            "Programming Language :: Python :: 3.12",
            "Programming Language :: Python :: 3.13",
        } <= classifiers


def _current_authoring_docs() -> list[Path]:
    dsl = ROOT / "packages/s0ma-dsl"
    mcp = ROOT / "packages/s0ma-mcp"
    paths = [dsl / "README.md", mcp / "README.md"]
    paths.extend(sorted((dsl / "docs").rglob("*.md")))
    paths.extend(sorted((mcp / "src/s0ma_mcp/_docs").rglob("*.md")))
    paths.extend(sorted((mcp / "src/s0ma_mcp/_built/docs").rglob("*.md")))
    return paths


def _assert_no_stale_mit_claims() -> None:
    violations: list[str] = []
    heading = re.compile(r"^## \[([^]]+)\]")
    for path in _current_authoring_docs():
        section: str | None = None
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            match = heading.match(line)
            if match:
                section = match.group(1)
            if not re.search(r"\bMIT\b|OSI Approved :: MIT", line, re.IGNORECASE):
                continue
            # Correct open-core statements are not DSL/MCP license claims.
            if "s0ma-core" in line:
                continue
            # The one intentional historical exception is the frozen 0.5.0
            # changelog section, whose released authoring packages were MIT.
            if (
                path == ROOT / "packages/s0ma-mcp/src/s0ma_mcp/_docs/CHANGELOG.md"
                and section == "0.5.0"
            ):
                continue
            violations.append(f"{path.relative_to(ROOT)}:{number}: {line.strip()}")
    if violations:
        raise AssertionError(
            "stale MIT marker in current s0ma-dsl/s0ma-mcp metadata/docs:\n"
            + "\n".join(violations)
        )


def _assert_studi0_payload(wheel: Path) -> None:
    """The studi0 wheel ships its committed build, and nothing regenerable.

    ``src/s0ma_studi0/_built/`` is product, not a build artifact of the
    packaging step: the runtime bootstraps those emitted modules, and
    ``sh0w_assets`` carries the viewer's embedded assets. The authoring
    inputs (``s0ma_src/``), the test suite and the incremental build cache
    (``.s0ma.cache/``, excluded by the package's hatch config) are NOT
    product and must stay out of the wheel.
    """
    with zipfile.ZipFile(wheel) as archive:
        names = archive.namelist()

    prefix = "s0ma_studi0/_built/"
    shipped = {name[len(prefix) :] for name in names if name.startswith(prefix)}
    committed = {
        path.relative_to(STUDI0_BUILT).as_posix()
        for path in STUDI0_BUILT.rglob("*")
        if path.is_file() and {".s0ma.cache", "__pycache__"}.isdisjoint(path.parts)
    }
    assert shipped == committed, (
        f"s0ma-studi0 wheel _built payload differs from the committed build: "
        f"missing={sorted(committed - shipped)} extra={sorted(shipped - committed)}"
    )
    # Named explicitly because its absence is the silent failure: the viewer
    # would install and start, then serve a page with no assets.
    assert "sh0w_assets.py" in shipped, sorted(shipped)

    excluded = sorted(
        name
        for name in names
        if ".s0ma.cache/" in name
        or name.startswith(("s0ma_src/", "tests/"))
        or "/s0ma_src/" in name
        or "/tests/" in name
    )
    assert not excluded, f"s0ma-studi0 wheel ships non-product paths: {excluded}"
    print(
        f"wheel payload: s0ma-studi0 ships {len(shipped)} committed _built file(s), "
        f"no .s0ma.cache/s0ma_src/tests"
    )


# ---------------------------------------------------------------------------
# Exact-wheel documentation identity (H2)
# ---------------------------------------------------------------------------
#
# Four claims a released wheel makes about a documentation build, checked
# here against the one document that build wrote about itself:
#
#   1. the core wheel's embedded teaching slice was rendered from the
#      snapshot the release manifest names;
#   2. the mcp wheel's ``_docs`` payload is the cataloged sources, byte
#      for byte;
#   2b. the dsl wheel's packaged snapshot — what ``s0ma docs`` reads with
#      no checkout — is that same composed snapshot, and byte-identical to
#      the mcp wheel's copy of it;
#   3. what those payloads say about the version is what the wheels
#      actually are.
#
# The ordering that makes this non-circular is docs/RELEASING.md's: the
# documentation is composed at the release commit, the mirrors are
# refreshed from it, and only then are the wheels built — so the manifest
# and the wheel are two records of one commit rather than either artifact
# describing the other.

#: The documentation build's identity document (H1, architecture §13.1).
#: Every assertion below is a comparison against one of its fields, named
#: in the message when it fails, because "the wheel disagrees with the
#: manifest" is only actionable if it says *about what*.
DOCS_MANIFEST = ROOT / "docs/_generated/docs-manifest.json"

#: The core wheel's embedded teaching slice, and the manifest artifact it
#: is a copy of.
CORE_SLICE_MEMBER = "s0ma/_teaching/slice.json"
CORE_SLICE_ARTIFACT = "docs/_generated/core-teaching-slice.json"

#: The mcp wheel's served-document payload, and the composed snapshot
#: inside it (which is itself a manifest artifact).
MCP_DOCS_PREFIX = "s0ma_mcp/_docs/"
MCP_SNAPSHOT_FILENAME = "s0ma-docs-model.json"
MCP_SNAPSHOT_ARTIFACT = "docs/_generated/s0ma-docs-model.json"

#: The dsl wheel's copy of the same composed snapshot — the one the four
#: ``s0ma docs`` commands read when there is no checkout. It is the third
#: of the loop's five mirrors, and it is here because its
#: absence was invisible for four milestones: the mcp copy above served the
#: MCP resources, the core slice served the teaching API, and the command
#: line had nothing at all. Every ``s0ma docs`` invocation from an
#: installed wheel answered "no documentation snapshot was found" while
#: every gate in this repository ran inside a checkout and saw the
#: checkout's answer. The cold probe below now runs the command.
DSL_SNAPSHOT_MEMBER = "s0ma_dsl/_docs_snapshot/s0ma-docs-model.json"


@dataclass(frozen=True)
class DocsPayloads:
    """What the built wheels carry about the documentation, as bytes.

    Read out of the wheels once and passed to :func:`check_docs_identity`
    as data, for two reasons. It keeps the assertions free of zipfile
    handling, and it makes the negative case testable: a proof that this
    check can *fail* needs a payload that disagrees with the manifest, and
    building a deliberately wrong wheel to get one would cost a minute per
    assertion for nothing the bytes do not already say.
    """

    #: Distribution name to the version its wheel metadata declares.
    wheel_versions: Mapping[str, str]
    #: The exact bytes of ``s0ma/_teaching/slice.json`` in the core wheel.
    core_slice: bytes
    #: Filename under ``s0ma_mcp/_docs/`` to its exact bytes in the wheel.
    mcp_docs: Mapping[str, bytes]
    #: The exact bytes of ``s0ma_dsl/_docs_snapshot/s0ma-docs-model.json``
    #: in the dsl wheel.
    dsl_snapshot: bytes


def _artifact_hash(manifest: object, path_or_uri: str) -> str:
    """The manifest's ``content_hash`` for one rendered artifact.

    Refuses absence rather than skipping it: an artifact the manifest does
    not list is an artifact nothing gated, and a verification that quietly
    passed over one would be strongest exactly where it was weakest.
    """
    for record in manifest.artifacts:  # type: ignore[attr-defined]
        if record.path_or_uri == path_or_uri:
            return str(record.content_hash)
    raise AssertionError(
        f"the release manifest lists no artifact at {path_or_uri}, so there "
        f"is nothing to compare the wheel's copy against. Compose the "
        f"documentation at this commit first (docs/RELEASING.md)."
    )


def _expected_version_line(manifest: object) -> str:
    """How this build's version must be written wherever a reader meets it.

    Built by handing the manifest's own two fields to the one rule that
    writes the line — ``BuildStamp.version_line`` — rather than by
    re-spelling ``f"{version} ({channel})"`` here. A second spelling of
    that rule is how a release build comes to serve a page still labelled
    preview with every gate green.
    """
    from s0ma_dsl.docs_model.records import BuildStamp

    return BuildStamp(
        schema=str(manifest.schema),  # type: ignore[attr-defined]
        release_version=str(manifest.product_version),  # type: ignore[attr-defined]
        snapshot_hash=str(manifest.snapshot_hash),  # type: ignore[attr-defined]
        build_channel=str(manifest.build_channel),  # type: ignore[attr-defined]
    ).version_line()


def _check_core_slice(payloads: DocsPayloads, manifest: object) -> list[str]:
    """Assertion 1: the embedded slice is this release's teaching content."""
    from s0ma.api.teaching import TeachingSlice
    from s0ma_dsl.docs_model.serialize import content_hash

    text = payloads.core_slice.decode("utf-8")
    listed = _artifact_hash(manifest, CORE_SLICE_ARTIFACT)
    carried = content_hash(text)
    assert carried == listed, (
        f"the s0ma-core wheel's {CORE_SLICE_MEMBER} is not the slice this "
        f"documentation build rendered: the manifest's artifact "
        f"{CORE_SLICE_ARTIFACT} has content_hash {listed} and the wheel "
        f"carries {carried}. The mirror was not refreshed before the wheels "
        f"were built (docs/RELEASING.md, 'The teaching-slice build order')."
    )

    document = json.loads(text)
    source = document["source"]
    # The mission assertion, stated against the field that answers it.
    assert source["snapshot_hash"] == manifest.snapshot_hash, (  # type: ignore[attr-defined]
        f"the wheel's teaching slice says it was rendered from snapshot "
        f"{source['snapshot_hash']} and the release manifest's snapshot_hash "
        f"is {manifest.snapshot_hash}. Every teaching answer this wheel "  # type: ignore[attr-defined]
        f"serves would quote a snapshot this release did not build."
    )
    assert source["release_version"] == manifest.product_version, (  # type: ignore[attr-defined]
        f"slice release_version {source['release_version']} != manifest "
        f"product_version {manifest.product_version}"  # type: ignore[attr-defined]
    )
    assert source["build_channel"] == manifest.build_channel, (  # type: ignore[attr-defined]
        f"slice build_channel {source['build_channel']} != manifest "
        f"build_channel {manifest.build_channel}"  # type: ignore[attr-defined]
    )

    # And the sentence a reader actually meets, produced by core's own
    # reader rather than reconstructed here.
    expected = _expected_version_line(manifest)
    line = TeachingSlice.load(CORE_SLICE_MEMBER, text).identity_line("concept:nerve")
    assert f"s0ma {expected}," in line, (
        f"core's teaching identity line does not describe this build: "
        f"expected the version written as {expected!r}, got {line!r}"
    )
    return [
        f"docs identity: core slice == manifest artifact {CORE_SLICE_ARTIFACT} "
        f"(content_hash {listed}), snapshot {source['snapshot_hash']}, "
        f"served as {expected!r}"
    ]


def _check_mcp_docs(payloads: DocsPayloads, manifest: object) -> list[str]:
    """Assertion 2: the ``_docs`` payload is the cataloged sources.

    Three bindings, and which one applies to a given document is *derived*
    from the manifest rather than written down here:

    * the composed snapshot is a rendered artifact, so it is bound by the
      manifest's ``artifacts[].content_hash`` — and so is any mirror
      whose source is itself an artifact this build rendered, which is
      how the quick reference and its data twin are bound since the
      authoring server started serving them (owner ruling 2026-09-29);
    * a mirror whose source the build actually read is bound by that
      source's full digest in ``source_hashes[].sha256`` — the strong
      form, and the set it covers grows on its own as providers read more;
    * every other mirror is bound by byte equality with the cataloged
      source in this checkout, plus the requirement that the source *is* a
      cataloged document in the snapshot the wheel itself carries — whose
      bytes the first binding already pinned.

    The report line counts the first two together as "bound by the
    manifest", because both are the manifest vouching for exact bytes; the
    third is the catalog vouching for membership.

    Nothing here counts the mirrors. The set is ``GUIDE_DOCS``, read from
    the package that defines it, so a tenth document ships gated.
    """
    from s0ma_dsl.docs_model.serialize import content_hash
    from s0ma_mcp.resources import GUIDE_DOCS

    snapshot_bytes = payloads.mcp_docs[MCP_SNAPSHOT_FILENAME]
    listed = _artifact_hash(manifest, MCP_SNAPSHOT_ARTIFACT)
    carried = content_hash(snapshot_bytes.decode("utf-8"))
    assert carried == listed, (
        f"the s0ma-mcp wheel's {MCP_DOCS_PREFIX}{MCP_SNAPSHOT_FILENAME} is "
        f"not the snapshot this build composed: manifest artifact "
        f"{MCP_SNAPSHOT_ARTIFACT} has content_hash {listed}, the wheel "
        f"carries {carried}. Refresh the mirror and rebuild the wheel."
    )
    snapshot = json.loads(snapshot_bytes)
    cataloged = {
        str(record.get("canonical_source", "")) for record in snapshot["documents"]
    }

    expected_members = {MCP_SNAPSHOT_FILENAME} | {
        doc.filename for doc in GUIDE_DOCS.values()
    }
    assert set(payloads.mcp_docs) == expected_members, (
        f"the s0ma-mcp wheel's {MCP_DOCS_PREFIX} payload is not the declared "
        f"set: missing={sorted(expected_members - set(payloads.mcp_docs))} "
        f"unexpected={sorted(set(payloads.mcp_docs) - expected_members)}"
    )

    digests = {
        record.source: record.sha256
        for record in manifest.source_hashes  # type: ignore[attr-defined]
    }
    rendered = {
        record.path_or_uri: str(record.content_hash)
        for record in manifest.artifacts  # type: ignore[attr-defined]
    }
    strong = 0
    for doc in sorted(GUIDE_DOCS.values(), key=lambda item: item.filename):
        shipped = payloads.mcp_docs[doc.filename]
        source = ROOT / doc.source
        assert source.is_file(), f"cataloged source moved: {doc.source}"
        assert shipped == source.read_bytes(), (
            f"the s0ma-mcp wheel's {MCP_DOCS_PREFIX}{doc.filename} differs "
            f"from its cataloged source {doc.source}. Refresh the committed "
            f"copy (cp the source over it) and rebuild the wheel."
        )
        if doc.source in rendered:
            found = content_hash(shipped.decode("utf-8"))
            assert found == rendered[doc.source], (
                f"the s0ma-mcp wheel ships {doc.filename} whose content hashes "
                f"to {found}; the manifest's artifact {doc.source} has "
                f"content_hash {rendered[doc.source]}. The copy was made from "
                f"a compose other than the one that wrote the manifest: "
                f"refresh it (step 3 of the documentation loop) and rebuild "
                f"the wheel."
            )
            strong += 1
        elif doc.source in digests:
            found = hashlib.sha256(shipped).hexdigest()
            assert found == digests[doc.source], (
                f"the s0ma-mcp wheel ships {doc.filename} whose bytes hash to "
                f"{found}; the manifest's source_hashes entry for "
                f"{doc.source} is {digests[doc.source]}. The wheel and the "
                f"manifest were built from different states of that file."
            )
            strong += 1
        else:
            assert doc.source in cataloged, (
                f"{doc.source} is served from the wheel as "
                f"{MCP_DOCS_PREFIX}{doc.filename} but is not a cataloged "
                f"document in the snapshot the wheel carries, and the "
                f"manifest records no source hash for it — so nothing in "
                f"this release binds those bytes to anything."
            )
    return [
        f"docs identity: mcp _docs == cataloged sources — "
        f"{len(GUIDE_DOCS)} mirrors ({strong} bound by the manifest's "
        f"source_hashes or artifact content_hashes, {len(GUIDE_DOCS) - strong} "
        f"by catalog membership in the wheel's own snapshot) + the snapshot "
        f"itself (content_hash {listed})"
    ]


def _check_dsl_snapshot(payloads: DocsPayloads, manifest: object) -> list[str]:
    """Assertion 2b: the command line's copy is the same build's, byte for byte.

    Two bindings, in the order that gives a drifted tree the most useful
    sentence. **Against the mcp wheel's copy first**, because that is the
    failure a half-run loop actually produces: one of the three ``cp``
    lines skipped, a mirror edited by hand, a merge that took one side.
    **Against the manifest second**, which catches the case where both
    copies were refreshed together from a compose other than the one that
    wrote the manifest — and which binds this copy to the build *directly*
    rather than through the mcp copy, so the message can name the artifact
    it disagrees with.
    """
    from s0ma_dsl.docs_model.serialize import content_hash

    assert payloads.dsl_snapshot == payloads.mcp_docs[MCP_SNAPSHOT_FILENAME], (
        f"the s0ma-dsl wheel's {DSL_SNAPSHOT_MEMBER} and the s0ma-mcp "
        f"wheel's {MCP_DOCS_PREFIX}{MCP_SNAPSHOT_FILENAME} are two copies of "
        f"one composed snapshot and their bytes differ. One of the loop's "
        f"three cp lines was not run, or a mirror was edited by hand — they "
        f"are copies, never sources (docs/operations/docs-maintenance.md "
        f"step 3)."
    )
    listed = _artifact_hash(manifest, MCP_SNAPSHOT_ARTIFACT)
    carried = content_hash(payloads.dsl_snapshot.decode("utf-8"))
    assert carried == listed, (
        f"the s0ma-dsl wheel's {DSL_SNAPSHOT_MEMBER} is not the snapshot "
        f"this build composed: manifest artifact {MCP_SNAPSHOT_ARTIFACT} has "
        f"content_hash {listed}, the wheel carries {carried}. Refresh the "
        f"mirror and rebuild the wheel — docs/operations/docs-maintenance.md "
        f"step 3, the third cp."
    )
    return [
        f"docs identity: dsl {DSL_SNAPSHOT_MEMBER} == manifest artifact "
        f"{MCP_SNAPSHOT_ARTIFACT} (content_hash {listed}) and byte-equal to "
        f"the mcp wheel's copy"
    ]


def _check_rendered_version(payloads: DocsPayloads, manifest: object) -> list[str]:
    """Assertion 3: the rendered documentation describes these wheels."""
    from s0ma_dsl.docs_model.records import BuildStamp

    version = str(manifest.product_version)  # type: ignore[attr-defined]
    channel = str(manifest.build_channel)  # type: ignore[attr-defined]
    wrong = {
        name: found
        for name, found in sorted(payloads.wheel_versions.items())
        if found != version
    }
    assert not wrong, (
        f"the manifest's product_version is {version} and these wheels are "
        f"not that version: {wrong}. The documentation describes a release "
        f"other than the one being built (PRD INV-4, DOC_VERSION_MISMATCH)."
    )

    mixed = sorted(
        f"{record.path_or_uri} ({record.release_version}/{record.build_channel})"
        for record in manifest.artifacts  # type: ignore[attr-defined]
        if record.release_version != version or record.build_channel != channel
    )
    assert not mixed, (
        f"the manifest lists artifacts from another build than its own "
        f"({version}/{channel}): {mixed}. This is DOC_VERSION_MISMATCH — a "
        f"manifest assembled from two composes."
    )

    expected = _expected_version_line(manifest)
    snapshot = json.loads(payloads.mcp_docs[MCP_SNAPSHOT_FILENAME])
    stamp = snapshot["stamp"]
    served = BuildStamp(
        schema=str(stamp["schema"]),
        release_version=str(stamp["release_version"]),
        snapshot_hash=str(stamp["snapshot_hash"]),
        build_channel=str(stamp.get("build_channel", channel)),
    ).version_line()
    assert served == expected, (
        f"the snapshot the mcp wheel serves writes its version as {served!r} "
        f"and this release's is {expected!r}: every s0ma://docs blurb would "
        f"tell its reader the wrong build."
    )
    assert stamp["snapshot_hash"] == manifest.snapshot_hash, (  # type: ignore[attr-defined]
        f"served snapshot {stamp['snapshot_hash']} != manifest snapshot_hash "
        f"{manifest.snapshot_hash}"  # type: ignore[attr-defined]
    )
    return [
        f"docs identity: {len(payloads.wheel_versions)} wheels at {version}, "
        f"{len(manifest.artifacts)} artifacts on one build, "  # type: ignore[attr-defined]
        f"served identity {expected!r}"
    ]


def check_docs_identity(
    payloads: DocsPayloads, manifest: object, *, head_tag: str = ""
) -> list[str]:
    """The three assertions, over payloads already read out of the wheels.

    ``head_tag`` is the tag the built commit is exactly at, **as a value** —
    what the release workflow knows as ``GITHUB_REF_NAME`` and what nothing
    here goes looking for. Given one, the channel the manifest declares has
    to be the channel that tag implies, by
    :func:`~s0ma_dsl.docs_model.manifest.channel_of` and no second rule.
    Empty means "nobody said", which is every local run and every build in
    a working checkout: the other assertions all still hold, and the
    channel is checked for internal agreement rather than against a tag
    that does not exist.
    """
    from s0ma_dsl.docs_model.manifest import channel_of

    report = [
        *_check_core_slice(payloads, manifest),
        *_check_mcp_docs(payloads, manifest),
        *_check_dsl_snapshot(payloads, manifest),
        *_check_rendered_version(payloads, manifest),
    ]
    if head_tag:
        implied = channel_of(
            product_version=str(manifest.product_version),  # type: ignore[attr-defined]
            head_tag=head_tag,
        )
        assert implied == manifest.build_channel, (  # type: ignore[attr-defined]
            f"this build is at tag {head_tag!r}, which by architecture "
            f"§13.2 makes it a {implied!r} build, and the documentation it "
            f"carries was composed as {manifest.build_channel!r}. "  # type: ignore[attr-defined]
            f"Recompose with the tag stated, before building the wheels: "
            f"uv run s0ma --project-root docs docs compose "
            f"--output-dir docs --head-tag {head_tag} (H2b), then refresh "
            f"the two mirrors — docs/RELEASING.md step 4. A release that "
            f"ships documentation labelled preview tells every reader it "
            f"is not the release they installed."
        )
        report.append(f"docs identity: tag {head_tag} implies {implied}, manifest agrees")
    return report


def _payloads_from_wheels(by_name: Mapping[str, Path]) -> DocsPayloads:
    """Read the documentation payloads out of the built wheels."""
    versions: dict[str, str] = {}
    for distribution, wheel in sorted(by_name.items()):
        document, _license_text, _paths = _metadata(wheel)
        versions[distribution] = str(document["Version"])

    with zipfile.ZipFile(by_name["s0ma-core"]) as archive:
        names = archive.namelist()
        assert CORE_SLICE_MEMBER in names, (
            f"the s0ma-core wheel does not carry {CORE_SLICE_MEMBER}; check "
            f"[tool.hatch.build.targets.wheel] in "
            f"packages/s0ma-core/pyproject.toml"
        )
        slice_bytes = archive.read(CORE_SLICE_MEMBER)

    with zipfile.ZipFile(by_name["s0ma-mcp"]) as archive:
        docs = {
            name[len(MCP_DOCS_PREFIX) :]: archive.read(name)
            for name in archive.namelist()
            if name.startswith(MCP_DOCS_PREFIX) and not name.endswith("/")
        }
    assert docs, f"the s0ma-mcp wheel carries no {MCP_DOCS_PREFIX} payload"

    with zipfile.ZipFile(by_name["s0ma-dsl"]) as archive:
        names = archive.namelist()
        assert DSL_SNAPSHOT_MEMBER in names, (
            f"the s0ma-dsl wheel does not carry {DSL_SNAPSHOT_MEMBER}, so "
            f"every `s0ma docs` command from an installed toolchain will "
            f"answer 'no documentation snapshot was found'. Refresh the "
            f"mirror (docs/operations/docs-maintenance.md step 3, the third "
            f"cp) and check [tool.hatch.build.targets.wheel] in "
            f"packages/s0ma-dsl/pyproject.toml"
        )
        dsl_snapshot = archive.read(DSL_SNAPSHOT_MEMBER)
    return DocsPayloads(
        wheel_versions=versions,
        core_slice=slice_bytes,
        mcp_docs=docs,
        dsl_snapshot=dsl_snapshot,
    )


def _assert_docs_identity(by_name: Mapping[str, Path], *, head_tag: str = "") -> None:
    """The wheel-side half of H2, over the wheels this run built."""
    from s0ma_dsl.docs_model.manifest import manifest_from_json

    assert DOCS_MANIFEST.is_file(), (
        f"{DOCS_MANIFEST.relative_to(ROOT)} is missing: nothing states what "
        f"documentation build these wheels are supposed to carry. Compose "
        f"the documentation first (docs/RELEASING.md)."
    )
    manifest = manifest_from_json(DOCS_MANIFEST.read_text(encoding="utf-8"))
    for line in check_docs_identity(
        _payloads_from_wheels(by_name), manifest, head_tag=head_tag
    ):
        print(line)


def _inspect_wheels(dist: Path, *, head_tag: str = "") -> list[Path]:
    wheels = sorted(dist.glob("*.whl"))
    if len(wheels) != len(EXPECTED):
        raise AssertionError(
            f"expected {len(EXPECTED)} wheels, found {[wheel.name for wheel in wheels]}"
        )
    by_name: dict[str, Path] = {}
    for wheel in wheels:
        document, license_text, license_paths = _metadata(wheel)
        distribution = str(document["Name"])
        by_name[distribution] = wheel
        expected = next(item for item in EXPECTED if item.distribution == distribution)
        assert document["License-Expression"] == expected.expression, (
            distribution,
            document["License-Expression"],
        )
        assert expected.classifier in document.get_all("Classifier", [])
        # lstrip: the canonical Apache-2.0 text opens with a centered
        # (whitespace-led) title line.
        assert license_text.lstrip().startswith(expected.license_heading)
        print(
            f"wheel metadata: {distribution} {document['Version']} "
            f"{document['License-Expression']} {license_paths[0]}"
        )
    assert set(by_name) == {item.distribution for item in EXPECTED}
    _assert_studi0_payload(by_name["s0ma-studi0"])
    _assert_docs_identity(by_name, head_tag=head_tag)
    return [by_name[item.distribution] for item in EXPECTED]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--metadata-only",
        action="store_true",
        help="build and inspect wheel/license metadata without the cold install",
    )
    parser.add_argument(
        "--docs-identity-only",
        action="store_true",
        help=(
            "build and inspect the wheels including the H2 "
            "documentation-identity assertions (embedded slice, mcp _docs, "
            "rendered version), without the cold install journey — the form "
            "the release workflow runs as a pre-serve gate"
        ),
    )
    parser.add_argument(
        "--head-tag",
        default="",
        metavar="TAG",
        help=(
            "the tag this commit is exactly at, as a value (the release "
            "workflow passes GITHUB_REF_NAME). Given one, the channel the "
            "documentation was composed as must be the channel that tag "
            "implies. Nothing here ever looks a tag up."
        ),
    )
    options = parser.parse_args(argv)

    _assert_source_posture()
    _assert_no_stale_mit_claims()
    with tempfile.TemporaryDirectory(prefix="s0ma-release-integrity-") as raw:
        temporary = Path(raw)
        dist = temporary / "dist"
        for expected in EXPECTED:
            run(
                ["uv", "build", "--package", expected.distribution, "--wheel", "--out-dir", dist],
                cwd=ROOT,
            )
        wheels = _inspect_wheels(dist, head_tag=options.head_tag)
        if options.docs_identity_only:
            print("release integrity: exact-wheel documentation identity PASS")
            return 0
        if options.metadata_only:
            print("release integrity: wheel licenses and source posture PASS")
            return 0

        environment = temporary / "venv"
        # Use the interpreter driving scripts/check.py so every CI matrix leg
        # runs the cold acceptance on its declared Python, not uv's default.
        run(["uv", "venv", "--python", sys.executable, environment], cwd=temporary)
        python = environment / (
            "Scripts/python.exe" if os.name == "nt" else "bin/python"
        )
        run(["uv", "pip", "install", "--python", python, *wheels], cwd=temporary)
        probe = temporary / "cold_probe.py"
        probe.write_text(cold_probe_source(), encoding="utf-8", newline="\n")
        run([python, "-I", probe], cwd=temporary)

    print("release integrity: wheel metadata + cold install journey PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
