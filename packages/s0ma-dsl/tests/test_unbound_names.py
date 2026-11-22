"""A name nothing binds fails ``s0ma check`` at its ``.s0ma`` line.

``compile()`` does not resolve global names, so a signature that says
``-> dict[str, Any]`` with no ``typing.Any`` in ``requires:`` used to check
clean, build, and raise ``NameError`` when the build loaded. The check walks
the emitted Python. A name read when the module loads is an error in every
mode. A name read only when a body runs is a warning in a dev build, which
still writes the module, and an error in strict and release.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from typing import TYPE_CHECKING

import pytest

from s0ma_dsl.cli.main import S0maCLI
from s0ma_dsl.codegen.unbound_names import find_unbound_names
from s0ma_dsl.config import (
    ERROR_CODE_DESCRIPTIONS,
    SEVERITY_MATRIX,
    StrictnessMode,
)

if TYPE_CHECKING:
    from pathlib import Path

LOAD = "UNBOUND_NAME_AT_LOAD"
BODY = "UNBOUND_NAME_IN_BODY"

_MODULE = """\
module probe_domain
    layer: DOMAIN
    version: 0.1.0
    intent: "Probe the names a body reads."
    exports: [probe]
    requires: {requires}
    uses: {uses}

    soft_requires: {soft}
    runtime_only_requires: none
    deferred_requires: {deferred}
    exports_helpers: none
{declarations}"""

_NERVE = """\
nerve probe :: DOMAIN
    kind: FUNCTION
    visibility: PUBLIC
    intent: "Probe one way of reading a name."
    expects: "Whatever the body takes."
    guarantees: "Nothing beyond what the body does."
    forbids: none
    evaluates_at: FUNCTION_BOUNDARY
    provides: none
    returns: none
    raises: none
    interface: none
    latency_ms: none
    depends_on: none
    internal: none
    expected_exceptions: none
    consumes_via_dict: none
    declares_attributes: none
    covered_by: ["unbound-name probe"]
    ---
{body}
"""

_PLAIN_BODY = "    def probe() -> int:\n        return 1"

_CONSTANT = """\
cell LEVEL :: DOMAIN
    kind: CONSTANT
    visibility: INTERNAL
    intent: "A constant whose annotation names something."
    schema: "int"
    invariants: none
    covered_by: none
    ---
    LEVEL: MissingType = 3

"""

_MODEL = """\
cell Reading :: DOMAIN
    kind: MODEL
    visibility: INTERNAL
    intent: "A class whose field annotation names something."
    schema: "value"
    invariants: none
    covered_by: none
    ---
    class Reading:
        \"\"\"A reading.\"\"\"

        value: MissingType = 1

"""

_HELPER_MODULE = """\
module helper_domain
    layer: DOMAIN
    version: 0.1.0
    intent: "Holds the component the probe calls."
    exports: [helper]
    requires: []
    uses: []

    soft_requires: none
    runtime_only_requires: none
    deferred_requires: none
    exports_helpers: none
nerve helper :: DOMAIN
    kind: FUNCTION
    visibility: PUBLIC
    intent: "Return one."
    expects: "No input."
    guarantees: "Returns one."
    forbids: none
    evaluates_at: FUNCTION_BOUNDARY
    provides: none
    returns: none
    raises: none
    interface: none
    latency_ms: none
    depends_on: none
    internal: none
    expected_exceptions: none
    consumes_via_dict: none
    declares_attributes: none
    covered_by: ["unbound-name probe"]
    ---
    def helper() -> int:
        return 1
"""

_TEST_MODULE = """\
module probe_domain_tests
    layer: DOMAIN
    version: 0.1.0
    intent: "Tests that reach the probe."
    uses: {uses}
    exports: []

    requires: none
    soft_requires: none
    runtime_only_requires: none
    deferred_requires: none
    exports_helpers: none
test test_probe :: DOMAIN
    intent: "The probe answers."
    tests: [probe_domain.{target}]
    expects: none
    depends_on: none
    mocks: none
    ---
    def test_probe() -> None:
        assert {target}() == 1
"""

#: Shape -> (declarations, the authored text of the failing line, code).
SHAPES: dict[str, tuple[str, str, str]] = {
    "parameter default": (
        _NERVE.format(
            body="    def probe(value: int = missing_value) -> int:\n"
            "        return value"
        ),
        "def probe(value: int = missing_value) -> int:",
        LOAD,
    ),
    "decorator": (
        _NERVE.format(
            body="    @missing_decorator\n"
            "    def probe() -> int:\n"
            "        return 1"
        ),
        "@missing_decorator",
        LOAD,
    ),
    "return annotation": (
        _NERVE.format(
            body="    def probe() -> dict[str, Any]:\n        return {}"
        ),
        "def probe() -> dict[str, Any]:",
        LOAD,
    ),
    "parameter annotation": (
        _NERVE.format(
            body="    def probe(value: MissingType) -> int:\n        return 1"
        ),
        "def probe(value: MissingType) -> int:",
        LOAD,
    ),
    "annotated constant": (
        _CONSTANT + _NERVE.format(body=_PLAIN_BODY),
        "LEVEL: MissingType = 3",
        LOAD,
    ),
    "class field": (
        _MODEL + _NERVE.format(body=_PLAIN_BODY),
        "value: MissingType = 1",
        LOAD,
    ),
    "body only": (
        _NERVE.format(
            body="    def probe() -> int:\n"
            "        total = 1\n"
            "        return total + missing_helper()"
        ),
        "return total + missing_helper()",
        BODY,
    ),
    "uses entry removed": (
        _NERVE.format(
            body="    def probe() -> int:\n        return helper()"
        ),
        "return helper()",
        BODY,
    ),
    "nested def annotation": (
        _NERVE.format(
            body="    def probe() -> int:\n"
            "        def inner(value: MissingType) -> int:\n"
            "            return 1\n"
            "        return inner(1)"
        ),
        "def inner(value: MissingType) -> int:",
        BODY,
    ),
}


@pytest.fixture(scope="module")
def seed(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """One scaffolded project, copied per test."""
    project = tmp_path_factory.mktemp("seed") / "probe"
    assert S0maCLI().run(["new", "project", str(project), "--quiet"]) == 0
    return project


@pytest.fixture
def project(
    seed: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str],
) -> Path:
    capsys.readouterr()
    target = tmp_path / "probe"
    shutil.copytree(seed, target)
    (target / "src" / "core" / "helper_domain.s0ma").write_text(
        _HELPER_MODULE, encoding="utf-8", newline="\n",
    )
    return target


def _write_probe(
    project: Path,
    declarations: str,
    *,
    requires: str = "[]",
    uses: str = "[]",
    soft: str = "none",
    deferred: str = "none",
) -> tuple[Path, str]:
    text = _MODULE.format(
        requires=requires, uses=uses, soft=soft, deferred=deferred,
        declarations=declarations,
    )
    path = project / "src" / "core" / "probe_domain.s0ma"
    path.write_text(text, encoding="utf-8", newline="\n")
    return path, text


def _line_of(text: str, marker: str) -> int:
    (line,) = [
        number
        for number, content in enumerate(text.splitlines(), start=1)
        if content.strip() == marker
    ]
    return line


def _check(
    project: Path, capsys: pytest.CaptureFixture[str], mode: str = "strict",
) -> tuple[int, dict]:
    rc = S0maCLI().run([
        "--project-root", str(project), "check", "--mode", mode,
        "--format", "json",
    ])
    return rc, json.loads(capsys.readouterr().out)


def _build(
    project: Path,
    capsys: pytest.CaptureFixture[str],
    mode: str = "dev",
    *extra: str,
) -> tuple[int, dict]:
    rc = S0maCLI().run([
        "--project-root", str(project), "build", str(project),
        "--mode", mode, "--format", "json", *extra,
    ])
    return rc, json.loads(capsys.readouterr().out)


def _name_findings(report: dict) -> list[dict]:
    return [
        finding
        for group in ("errors", "warnings")
        for finding in report.get(group, [])
        if finding["code"] in {LOAD, BODY}
    ]


class TestRegistry:
    def test_a_load_read_is_an_error_in_every_mode(self) -> None:
        assert SEVERITY_MATRIX[LOAD] == dict.fromkeys(StrictnessMode, "error")

    def test_a_body_read_ladders_with_the_mode(self) -> None:
        assert SEVERITY_MATRIX[BODY] == {
            StrictnessMode.MIGRATION: "warning",
            StrictnessMode.DEV: "warning",
            StrictnessMode.STRICT: "error",
            StrictnessMode.RELEASE: "error",
        }

    @pytest.mark.parametrize("code", [LOAD, BODY])
    def test_the_code_is_described(self, code: str) -> None:
        assert ERROR_CODE_DESCRIPTIONS[code]


@pytest.mark.parametrize("shape", sorted(SHAPES))
def test_each_shape_reports_its_code_at_the_authored_line(
    project: Path, capsys: pytest.CaptureFixture[str], shape: str,
) -> None:
    declarations, marker, code = SHAPES[shape]
    _, text = _write_probe(project, declarations)

    rc, report = _check(project, capsys)

    assert rc == 1
    (finding,) = _name_findings(report)
    assert finding["code"] == code
    assert finding["severity"] == "error"
    assert finding["file"].endswith("probe_domain.s0ma")
    assert finding["line"] == _line_of(text, marker)
    assert finding["remediation"]


def test_a_public_tests_target_with_no_uses_entry_is_a_body_read(
    project: Path, capsys: pytest.CaptureFixture[str],
) -> None:
    _write_probe(project, _NERVE.format(body=_PLAIN_BODY))
    tests = project / "tests" / "core" / "probe_domain_tests.s0ma"
    text = _TEST_MODULE.format(uses="[]", target="probe")
    tests.write_text(text, encoding="utf-8", newline="\n")

    rc, report = _check(project, capsys)

    assert rc == 1
    (finding,) = _name_findings(report)
    assert finding["code"] == BODY
    assert finding["file"].endswith("probe_domain_tests.s0ma")
    assert finding["line"] == _line_of(text, "assert probe() == 1")


def test_the_reproduction_goes_red_then_clean_then_loads(
    project: Path, capsys: pytest.CaptureFixture[str],
) -> None:
    (project / "src" / "core" / "helper_domain.s0ma").unlink()
    body = "    def probe() -> dict[str, Any]:\n        return {}"
    declarations = _NERVE.format(body=body)
    _write_probe(project, declarations, requires="none")

    rc, report = _check(project, capsys)
    assert rc == 1
    assert [f["code"] for f in _name_findings(report)] == [LOAD]
    assert "typing.Any" in _name_findings(report)[0]["remediation"]

    _write_probe(project, declarations, requires="[typing.Any]")
    rc, report = _check(project, capsys)
    assert rc == 0, report
    assert _name_findings(report) == []

    rc, _ = _build(project, capsys)
    assert rc == 0
    loaded = subprocess.run(
        [
            sys.executable, "-c",
            "from s0ma.bootstrap import bootstrap_imports;"
            "bootstrap_imports('build')",
        ],
        cwd=project,
        capture_output=True,
        text=True,
        check=False,
    )
    assert loaded.returncode == 0, loaded.stderr


class TestSilentOnWhatIsBound:
    @pytest.mark.parametrize(
        ("declarations", "options"),
        [
            pytest.param(
                _NERVE.format(
                    body='    def probe() -> "dict[str, MissingType]":\n'
                    "        return {}"
                ),
                {},
                id="quoted annotation",
            ),
            pytest.param(
                _NERVE.format(
                    body="    def probe() -> int:\n"
                    "        value: MissingType = 1\n"
                    "        return value"
                ),
                {},
                id="local variable annotation",
            ),
            pytest.param(
                _NERVE.format(
                    body="    def probe() -> int:\n"
                    "        def top() -> int:\n"
                    "            inner = 1\n"
                    "            return inner\n"
                    "        return top()"
                ),
                {},
                id="function named top",
            ),
            pytest.param(
                _NERVE.format(
                    body="    def probe() -> dict[str, Any]:\n        return {}"
                ),
                {"requires": "[typing.Any]"},
                id="requires",
            ),
            pytest.param(
                _NERVE.format(body="    def probe() -> int:\n        return helper()"),
                {"uses": "[helper_domain.helper]"},
                id="uses",
            ),
            pytest.param(
                _NERVE.format(
                    body="    def probe() -> int:\n"
                    "        return len(json.dumps({}))"
                ),
                {"soft": "[json]"},
                id="soft_requires",
            ),
            pytest.param(
                _NERVE.format(
                    body="    def probe() -> int:\n"
                    "        return len(json.dumps({}))"
                ),
                {"deferred": "[json]"},
                id="deferred_requires",
            ),
            pytest.param(
                _NERVE.format(
                    body="    def probe() -> int:\n"
                    "        return len(sorted(range(3)))"
                ),
                {},
                id="builtins",
            ),
        ],
    )
    def test_no_finding(
        self,
        project: Path,
        capsys: pytest.CaptureFixture[str],
        declarations: str,
        options: dict[str, str],
    ) -> None:
        _write_probe(project, declarations, **options)

        rc, report = _check(project, capsys)

        assert rc == 0, report
        assert _name_findings(report) == []

    def test_a_dotted_soft_requires_entry_binds_its_last_segment(
        self, project: Path, capsys: pytest.CaptureFixture[str],
    ) -> None:
        """Dev mode, because this shape draws a separate strict finding."""
        _write_probe(
            project,
            _NERVE.format(
                body="    def probe() -> int:\n"
                '        return len(metadata.version("pip"))'
            ),
            soft="[importlib.metadata]",
        )

        _, report = _check(project, capsys, "dev")

        assert _name_findings(report) == []

    def test_a_privileged_tests_import(
        self, project: Path, capsys: pytest.CaptureFixture[str],
    ) -> None:
        internal = _NERVE.format(
            body="    def secret() -> int:\n        return 1"
        ).replace("nerve probe", "nerve secret").replace(
            "visibility: PUBLIC", "visibility: INTERNAL"
        )
        _write_probe(project, _NERVE.format(body=_PLAIN_BODY) + "\n" + internal)
        tests = project / "tests" / "core" / "probe_domain_tests.s0ma"
        tests.write_text(
            _TEST_MODULE.format(uses="[]", target="secret"),
            encoding="utf-8",
            newline="\n",
        )

        rc, report = _check(project, capsys)

        assert rc == 0, report
        assert _name_findings(report) == []


class TestBuild:
    def test_a_dev_build_warns_on_a_body_read_and_writes_the_module(
        self, project: Path, capsys: pytest.CaptureFixture[str],
    ) -> None:
        declarations, _, _ = SHAPES["body only"]
        _write_probe(project, declarations)

        rc, report = _build(project, capsys)

        assert rc == 0
        (finding,) = _name_findings(report)
        assert finding["code"] == BODY
        assert finding["severity"] == "warning"
        assert (project / "build" / "probe_domain.py").is_file()

    @pytest.mark.parametrize("mode", ["strict", "release"])
    def test_a_strict_build_blocks_a_body_read(
        self, project: Path, capsys: pytest.CaptureFixture[str], mode: str,
    ) -> None:
        declarations, _, _ = SHAPES["body only"]
        _write_probe(project, declarations)

        rc, report = _build(project, capsys, mode, "--no-cache")

        assert rc == 1
        assert BODY in {f["code"] for f in _name_findings(report)}
        assert not (project / "build" / "probe_domain.py").exists()

    @pytest.mark.parametrize("mode", [m.value for m in StrictnessMode])
    def test_a_load_read_writes_nothing_in_any_mode(
        self, project: Path, capsys: pytest.CaptureFixture[str], mode: str,
    ) -> None:
        declarations, _, _ = SHAPES["return annotation"]
        _write_probe(project, declarations)

        rc, report = _build(project, capsys, mode, "--no-cache")

        assert rc == 1
        assert LOAD in {f["code"] for f in _name_findings(report)}
        assert not (project / "build" / "probe_domain.py").exists()

    def test_the_cache_does_not_hide_a_body_read_from_the_next_build(
        self, project: Path, capsys: pytest.CaptureFixture[str],
    ) -> None:
        """The cache key ignores the mode, so this entry must not be stored."""
        declarations, _, _ = SHAPES["body only"]
        _write_probe(project, declarations)

        assert _build(project, capsys)[0] == 0
        rc, report = _build(project, capsys)
        assert rc == 0
        assert [f["code"] for f in _name_findings(report)] == [BODY]

        rc, report = _build(project, capsys, "strict")
        assert rc == 1
        assert BODY in {f["code"] for f in _name_findings(report)}

    def test_a_single_file_transpile_does_not_judge_a_privileged_name(
        self, project: Path, capsys: pytest.CaptureFixture[str],
    ) -> None:
        """With no project context the emitter adds no privileged import."""
        tests = project / "tests" / "core" / "probe_domain_tests.s0ma"
        tests.write_text(
            _TEST_MODULE.format(uses="[]", target="secret"),
            encoding="utf-8",
            newline="\n",
        )

        rc = S0maCLI().run([
            "transpile", str(tests), "--output-dir", str(project / "out"),
            "--mode", "dev",
        ])

        output = capsys.readouterr()
        assert LOAD not in output.out + output.err
        assert BODY not in output.out + output.err
        assert rc == 0


def test_a_test_module_checked_outside_a_project_is_not_judged(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Its target may be in a sibling file this check was not given."""
    path = tmp_path / "probe_domain_tests.s0ma"
    path.write_text(
        _TEST_MODULE.format(uses="[]", target="secret").replace(
            "tests: [probe_domain.secret]", "tests: [secret]",
        ),
        encoding="utf-8",
        newline="\n",
    )
    monkeypatch.chdir(tmp_path)
    capsys.readouterr()

    S0maCLI().run(["check", str(path), "--format", "json"])

    assert _name_findings(json.loads(capsys.readouterr().out)) == []


def test_the_scaffolded_agents_file_names_the_import(seed: Path) -> None:
    text = (seed / "AGENTS.md").read_text(encoding="utf-8")

    assert "`dict[str, Any]` with `typing.Any` in `requires:`" in text


def _reads(source: str) -> list[tuple[str, bool]]:
    return [(r.name, r.at_load) for r in find_unbound_names(source)]


@pytest.mark.parametrize(
    "source",
    [
        pytest.param("def top():\n    x = 1\n    return x\n", id="top"),
        pytest.param(
            "def f():\n    x: Missing = 1\n    return x\n", id="local-annotation",
        ),
        pytest.param(
            'def f(a: "Missing") -> "list[Missing]":\n    return a\n',
            id="quoted-annotation",
        ),
        pytest.param(
            "class C:\n    T = int\n    def m(self, x: T) -> T:\n        return x\n",
            id="class-name-in-method-signature",
        ),
        pytest.param(
            "def f(xs):\n    [y := x for x in xs]\n    return y\n",
            id="walrus-escapes-comprehension",
        ),
        pytest.param(
            "def f():\n    try:\n        pass\n    except OSError as e:\n"
            "        return e\n",
            id="except-as",
        ),
        pytest.param(
            "def f(v):\n    match v:\n"
            "        case [a, *b]:\n            return a, b\n"
            "        case {'k': c, **d}:\n            return c, d\n"
            "        case int() as e:\n            return e\n",
            id="match-captures",
        ),
        pytest.param(
            "def f():\n    import os.path\n    from sys import argv as a\n"
            "    return os, a\n",
            id="local-imports",
        ),
        pytest.param("def f():\n    x = 1\n    del x\n    return x\n", id="del"),
        pytest.param(
            "def f():\n    global counter\n    counter = 1\n"
            "def g():\n    return counter\n",
            id="global-store",
        ),
        pytest.param(
            "def f():\n    x = 1\n    def g():\n        nonlocal x\n"
            "        x = 2\n        return x\n    return g\n",
            id="nonlocal",
        ),
        pytest.param("h = lambda a, *b, c=1, **d: (a, b, c, d)\n", id="lambda"),
        pytest.param(
            "class C:\n    def m(self):\n        return __class__\n",
            id="dunder-class",
        ),
        pytest.param("x = (__name__, __file__, __doc__)\n", id="module-dunders"),
        pytest.param(
            "class C:\n    where = __module__, __qualname__\n", id="class-dunders",
        ),
        pytest.param(
            "import sys\nif sys.argv:\n    late = 1\ndef f():\n    return late\n",
            id="conditional-module-binding",
        ),
        pytest.param(
            "def f():\n    return later\nlater = 1\n", id="bound-after-use",
        ),
        pytest.param(
            "from os.path import *\ndef f():\n    return join('a')\n",
            id="star-import",
        ),
        pytest.param(
            "from __future__ import annotations\n"
            "def f(a: Missing) -> Missing:\n    return a\n"
            "class C:\n    field: Missing\n",
            id="future-annotations",
        ),
        pytest.param(
            "globals()['made'] = 1\ndef f():\n    return made\n", id="globals",
        ),
        pytest.param(
            "try:\n    value = Missing\nexcept NameError:\n    value = None\n",
            id="name-error-guard",
        ),
        pytest.param(
            "class C(metaclass=Magic2):\n    x = provided_by_prepare\n"
            "class Magic2(type):\n    pass\n",
            id="metaclass-namespace",
        ),
        pytest.param(
            "def f():\n    return [a + b for a in range(2) for b in range(a)]\n",
            id="comprehension-variables",
        ),
        pytest.param("def f():\n    return WindowsError\n", id="platform-builtin"),
    ],
)
def test_the_walk_stays_silent(source: str) -> None:
    assert _reads(source) == []


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        pytest.param(
            "class C:\n    x = 1\n    def m(self):\n        return x\n",
            [("x", False)],
            id="class-names-invisible-in-methods",
        ),
        pytest.param(
            "class C:\n    xs = [1]\n    k = 2\n    ys = [v + k for v in xs]\n",
            [("k", True)],
            id="class-names-invisible-in-comprehensions",
        ),
        pytest.param(
            "class C:\n    def m(self, v: Missing) -> int:\n        return 1\n",
            [("Missing", True)],
            id="method-annotation",
        ),
        pytest.param(
            "def f():\n    def g(v=Missing):\n        return v\n    return g\n",
            [("Missing", False)],
            id="nested-default",
        ),
        pytest.param(
            "def f():\n    @Missing\n    def g():\n        return 1\n    return g\n",
            [("Missing", False)],
            id="nested-decorator",
        ),
        pytest.param(
            "h = lambda: Missing\n", [("Missing", False)], id="lambda-body",
        ),
        pytest.param(
            "h = lambda v=Missing: v\n", [("Missing", True)], id="lambda-default",
        ),
        pytest.param(
            "g = (v + Missing for v in range(2))\n",
            [("Missing", False)],
            id="generator-element",
        ),
        pytest.param(
            "g = (v for v in Missing)\n",
            [("Missing", True)],
            id="generator-first-iterable",
        ),
        pytest.param(
            "g = [v + Missing for v in range(2)]\n",
            [("Missing", True)],
            id="list-comprehension-element",
        ),
        pytest.param(
            "x = Missing\ndef f():\n    return Missing\n",
            [("Missing", True)],
            id="load-read-wins",
        ),
        pytest.param(
            "def f():\n    local = 1\n    return local\n"
            "def g():\n    return local\n",
            [("local", False)],
            id="another-function-local",
        ),
        pytest.param(
            "from __future__ import annotations\ndef f(v=Missing):\n    return v\n",
            [("Missing", True)],
            id="future-annotations-keep-defaults",
        ),
        pytest.param(
            "try:\n    value = Missing\nexcept ValueError:\n    value = None\n",
            [("Missing", True)],
            id="other-except-is-no-guard",
        ),
    ],
)
def test_the_walk_reports(
    source: str, expected: list[tuple[str, bool]],
) -> None:
    assert _reads(source) == expected


@pytest.mark.skipif(
    sys.version_info < (3, 12), reason="PEP 695 syntax needs Python 3.12",
)
@pytest.mark.parametrize(
    ("source", "expected"),
    [
        pytest.param("def f[T](v: T) -> T:\n    return v\n", [], id="function"),
        pytest.param(
            "class C[T](list[T]):\n    def m(self) -> T:\n        return self[0]\n",
            [],
            id="class",
        ),
        pytest.param("type A[T] = list[Missing]\n", [], id="alias-value-is-lazy"),
        pytest.param(
            "def f[T: Missing](v: T) -> T:\n    return v\n", [], id="bound-is-lazy",
        ),
        pytest.param(
            "class C:\n    X = int\n    def m[T](self, v: X) -> T:\n"
            "        return v\n",
            [],
            id="annotation-scope-sees-class",
        ),
        pytest.param(
            "class C:\n    X = int\n    def m[T](self) -> T:\n        return X\n",
            [("X", False)],
            id="body-does-not-see-class",
        ),
    ],
)
def test_type_parameters(source: str, expected: list[tuple[str, bool]]) -> None:
    assert _reads(source) == expected


_BROAD_HANDLERS = [
    pytest.param("except Exception:", id="exception"),
    pytest.param("except BaseException:", id="base-exception"),
    pytest.param("except:", id="bare"),
    pytest.param("except (ValueError, Exception):", id="tuple"),
]


@pytest.mark.parametrize("handler", _BROAD_HANDLERS)
def test_a_broad_handler_guards_a_module_level_read(handler: str) -> None:
    source = f"try:\n    value = missing\n{handler}\n    value = None\n"
    assert _reads(source) == []


@pytest.mark.parametrize("handler", _BROAD_HANDLERS)
def test_a_broad_handler_guards_a_class_body_read(handler: str) -> None:
    source = (
        "class C:\n    try:\n        value = missing\n"
        f"    {handler}\n        value = None\n"
    )
    assert _reads(source) == []


def test_a_narrow_handler_leaves_a_class_body_read_reported() -> None:
    source = (
        "class C:\n    try:\n        value = missing\n"
        "    except ValueError:\n        value = None\n"
    )
    assert _reads(source) == [("missing", True)]


@pytest.mark.parametrize("handler", _BROAD_HANDLERS)
def test_a_broad_handler_in_a_function_stays_a_body_read(handler: str) -> None:
    source = (
        "def f():\n    try:\n        return missing\n"
        f"    {handler}\n        return None\n"
    )
    assert _reads(source) == [("missing", False)]


@pytest.mark.parametrize("handler", _BROAD_HANDLERS)
def test_a_broad_handler_in_a_method_stays_a_body_read(handler: str) -> None:
    source = (
        "class C:\n    def m(self):\n        try:\n            return missing\n"
        f"        {handler}\n            return None\n"
    )
    assert _reads(source) == [("missing", False)]


@pytest.mark.parametrize("handler", _BROAD_HANDLERS)
def test_a_broad_handler_around_a_def_does_not_hide_its_body(handler: str) -> None:
    source = (
        "try:\n    def f():\n        return missing\n"
        f"{handler}\n    f = None\n"
    )
    assert _reads(source) == [("missing", False)]
