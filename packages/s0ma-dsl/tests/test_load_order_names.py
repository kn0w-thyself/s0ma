"""A load read before its binding fails ``s0ma check`` at its ``.s0ma`` line.

The name check counted a name bound anywhere at module level as bound, so a
method annotated with its own class, a constant reading a later one, and a
name imported only under ``TYPE_CHECKING`` all checked clean, built, and
raised ``NameError`` on import. These tests hold the ordered walk: what it
reports, the many shapes that really do load and must stay silent, and the
declared Python range that decides whether an annotation counts.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
import textwrap
import types
from typing import TYPE_CHECKING

import pytest

from s0ma_dsl.cli.main import S0maCLI
from s0ma_dsl.codegen.unbound_names import (
    _annotations_run_at_load,
    find_unbound_names,
)
from s0ma_dsl.config import ERROR_CODE_DESCRIPTIONS, StrictnessMode

if TYPE_CHECKING:
    from pathlib import Path

LOAD = "UNBOUND_NAME_AT_LOAD"

_HEADER = """\
module probe_domain
    layer: DOMAIN
    version: 0.1.0
    intent: "Probe the order a module binds and reads names in."
    exports: [probe]
    requires: {requires}
    uses: []

    soft_requires: none
    runtime_only_requires: none
    deferred_requires: none
    exports_helpers: none
"""


def _indent(body: str) -> str:
    return textwrap.indent(textwrap.dedent(body).strip("\n"), "    ")


def _cell(name: str, body: str, kind: str = "MODEL") -> str:
    return f"""cell {name} :: DOMAIN
    kind: {kind}
    visibility: INTERNAL
    intent: "A cell for the load-order probe."
    schema: "value"
    invariants: none
    covered_by: ["load-order probe"]
    ---
{_indent(body)}

"""


def _constant(name: str, body: str) -> str:
    return _cell(name, body, kind="CONSTANT")


def _nerve(name: str, body: str, visibility: str = "INTERNAL") -> str:
    return f"""nerve {name} :: DOMAIN
    kind: FUNCTION
    visibility: {visibility}
    intent: "A nerve for the load-order probe."
    expects: "No input."
    guarantees: "Returns a value."
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
    covered_by: ["load-order probe"]
    ---
{_indent(body)}

"""


def _helper(name: str, body: str) -> str:
    return f"""helper {name} :: DOMAIN
    intent: "A helper for the load-order probe."
    ---
{_indent(body)}

"""


_PROBE = _nerve(
    "probe",
    '''
    def probe() -> int:
        """Answer."""
        return 1
    ''',
    visibility="PUBLIC",
)


def _own(member: str) -> str:
    return _cell(
        "Book",
        f'''
        class Book:
            """Holds a record."""

            {member}
        ''',
    )


_LATER = _cell(
    "Later",
    '''
    class Later:
        """Declared after its first reader."""

        value: int = 1
    ''',
)
_SECOND = _constant("SECOND", "SECOND = 1")
_DECORATOR = _helper(
    "_later_deco",
    '''
    def _later_deco(fn):
        """Return the function."""
        return fn
    ''',
)
_BASE = _cell(
    "Base",
    '''
    class Base:
        """The base."""
    ''',
)
_GUARD_ONLY = _constant(
    "TC_GUARD",
    """
    TC_GUARD = 1
    if TYPE_CHECKING:
        Decimal = int
    """,
)
_GUARD_WITH_ELSE = _constant(
    "TC_GUARD",
    """
    TC_GUARD = 1
    if TYPE_CHECKING:
        Decimal = int
    else:
        Decimal = float
    """,
)
_TC = "[typing.TYPE_CHECKING]"


def _first(signature: str) -> str:
    return _nerve(
        "first",
        f'''
        {signature}
            """Read."""
            return None
        ''',
    )


#: Shape -> (declarations, the failing line, ``requires:``, is an annotation).
FAILING: dict[str, tuple[list[str], str, str, bool]] = {
    "own name in a return": (
        [_own("def clone(self) -> Book:\n                return self")],
        "def clone(self) -> Book:", "[]", True,
    ),
    "own name in a parameter": (
        [_own("def merge(self, other: Book) -> None:\n                return None")],
        "def merge(self, other: Book) -> None:", "[]", True,
    ),
    "own name as a default": (
        [_own("def merge(self, other=Book) -> None:\n                return None")],
        "def merge(self, other=Book) -> None:", "[]", False,
    ),
    "own name in a class field": (
        [_own("peer: Book | None = None")],
        "peer: Book | None = None", "[]", True,
    ),
    "forward annotation": (
        [_first("def first() -> Later:"), _LATER],
        "def first() -> Later:", "[]", True,
    ),
    "forward constant value": (
        [_constant("FIRST", "FIRST = SECOND + 1"), _SECOND],
        "FIRST = SECOND + 1", "[]", False,
    ),
    "forward default": (
        [_first("def first(level: int = SECOND) -> int:"), _SECOND],
        "def first(level: int = SECOND) -> int:", "[]", False,
    ),
    "forward base class": (
        [
            _cell(
                "Child",
                '''
                class Child(Base):
                    """Inherits a later base."""
                ''',
            ),
            _BASE,
        ],
        "class Child(Base):", "[]", False,
    ),
    "forward decorator": (
        [
            _nerve(
                "first",
                '''
                @_later_deco
                def first() -> int:
                    """Read."""
                    return 1
                ''',
            ),
            _DECORATOR,
        ],
        "@_later_deco", "[]", False,
    ),
    "TYPE_CHECKING name in a signature": (
        [_GUARD_ONLY, _first("def first(item: Decimal) -> None:")],
        "def first(item: Decimal) -> None:", _TC, True,
    ),
    "TYPE_CHECKING name in a class field": (
        [
            _GUARD_ONLY,
            _cell(
                "Holder",
                '''
                class Holder:
                    """Holds a value."""

                    item: Decimal | None = None
                ''',
            ),
        ],
        "item: Decimal | None = None", _TC, True,
    ),
    "TYPE_CHECKING name in an annotated constant": (
        [_GUARD_ONLY, _constant("FIRST", "FIRST: Decimal | None = None")],
        "FIRST: Decimal | None = None", _TC, True,
    ),
}

#: The fixed form of each failing shape. Each one checks clean and loads.
FIXED: dict[str, tuple[list[str], str]] = {
    "quoted own return": (
        [_own('def clone(self) -> "Book":\n                return self')], "[]",
    ),
    "quoted own parameter": (
        [_own('def merge(self, other: "Book") -> None:\n                return None')],
        "[]",
    ),
    "quoted own field": ([_own('peer: "Book | None" = None')], "[]"),
    "quoted forward annotation": (
        [_first('def first() -> "Later":'), _LATER], "[]",
    ),
    "moved forward annotation": ([_LATER, _first("def first() -> Later:")], "[]"),
    "moved constant value": (
        [_SECOND, _constant("FIRST", "FIRST = SECOND + 1")], "[]",
    ),
    "moved default": (
        [_SECOND, _first("def first(level: int = SECOND) -> int:")], "[]",
    ),
    "moved base class": (
        [
            _BASE,
            _cell(
                "Child",
                '''
                class Child(Base):
                    """Inherits an earlier base."""
                ''',
            ),
        ],
        "[]",
    ),
    "moved decorator": (
        [
            _DECORATOR,
            _nerve(
                "first",
                '''
                @_later_deco
                def first() -> int:
                    """Read."""
                    return 1
                ''',
            ),
        ],
        "[]",
    ),
    "quoted TYPE_CHECKING name": (
        [_GUARD_ONLY, _first('def first(item: "Decimal") -> None:')], _TC,
    ),
    "TYPE_CHECKING with an else binding": (
        [_GUARD_WITH_ELSE, _first("def first(item: Decimal) -> None:")], _TC,
    ),
    "a body reading a later name": (
        [
            _nerve(
                "first",
                '''
                def first() -> int:
                    """A body runs after the module has loaded."""
                    return SECOND
                ''',
            ),
            _SECOND,
        ],
        "[]",
    ),
}


@pytest.fixture(scope="module")
def seed(tmp_path_factory: pytest.TempPathFactory) -> Path:
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
    return target


def _write(project: Path, declarations: list[str], requires: str) -> str:
    text = _HEADER.format(requires=requires) + "".join([*declarations, _PROBE])
    path = project / "src" / "core" / "probe_domain.s0ma"
    path.write_text(text, encoding="utf-8", newline="\n")
    return text


def _set_range(project: Path, spec: str | None) -> None:
    """Write *spec* as the project's ``requires-python``, or remove it."""
    path = project / "pyproject.toml"
    text = path.read_text(encoding="utf-8")
    line = "" if spec is None else f'requires-python = "{spec}"\n'
    text, count = re.subn(r'requires-python = "[^"]*"\n', line, text)
    assert count == 1
    path.write_text(text, encoding="utf-8", newline="\n")


def _check(
    project: Path, capsys: pytest.CaptureFixture[str], mode: str = "dev",
) -> tuple[int, list[dict]]:
    rc = S0maCLI().run([
        "--project-root", str(project), "check", "--mode", mode, "--format", "json",
    ])
    report = json.loads(capsys.readouterr().out)
    return rc, [f for f in report.get("errors", []) if f["code"] == LOAD]


def _build(
    project: Path,
    capsys: pytest.CaptureFixture[str],
    *extra: str,
    mode: str = "dev",
) -> tuple[int, list[dict]]:
    rc = S0maCLI().run([
        "--project-root", str(project), "build", str(project),
        "--mode", mode, "--format", "json", *extra,
    ])
    report = json.loads(capsys.readouterr().out)
    return rc, [f for f in report.get("errors", []) if f["code"] == LOAD]


def _line_of(text: str, marker: str) -> int:
    (line,) = [
        number
        for number, content in enumerate(text.splitlines(), start=1)
        if content.strip() == marker
    ]
    return line


def _load_built(project: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            sys.executable, "-c",
            "from s0ma.bootstrap import bootstrap_imports;"
            "bootstrap_imports('build');"
            "import probe_domain",
        ],
        cwd=project,
        capture_output=True,
        text=True,
        check=False,
    )


class TestEachFailingShape:
    @pytest.mark.parametrize("shape", sorted(FAILING))
    def test_check_reports_it_at_the_authored_line(
        self, project: Path, capsys: pytest.CaptureFixture[str], shape: str,
    ) -> None:
        declarations, marker, requires, _ = FAILING[shape]
        text = _write(project, declarations, requires)

        rc, findings = _check(project, capsys)

        assert rc == 1
        (finding,) = findings
        assert finding["severity"] == "error"
        assert finding["file"].endswith("probe_domain.s0ma")
        assert finding["line"] == _line_of(text, marker)
        assert finding["remediation"]

    @pytest.mark.parametrize("shape", sorted(FAILING))
    def test_build_reports_it_and_writes_nothing(
        self, project: Path, capsys: pytest.CaptureFixture[str], shape: str,
    ) -> None:
        declarations, marker, requires, _ = FAILING[shape]
        text = _write(project, declarations, requires)

        rc, findings = _build(project, capsys, "--no-cache")

        assert rc == 1
        assert [f["line"] for f in findings] == [_line_of(text, marker)]
        assert not (project / "build" / "probe_domain.py").exists()

    @pytest.mark.parametrize("mode", [m.value for m in StrictnessMode])
    def test_it_is_an_error_in_every_mode(
        self, project: Path, capsys: pytest.CaptureFixture[str], mode: str,
    ) -> None:
        declarations, _, requires, _ = FAILING["own name in a return"]
        _write(project, declarations, requires)

        rc, findings = _check(project, capsys, mode)

        assert rc == 1
        assert [f["severity"] for f in findings] == ["error"]


class TestTheMessageNamesTheFix:
    @pytest.mark.parametrize(
        ("shape", "says", "fix"),
        [
            ("own name in a return", "class being defined", "quote the annotation"),
            ("own name as a default", "class being defined", "after the class"),
            ("forward annotation", "comes later", "quote the annotation"),
            ("forward default", "comes later", "move the declaration"),
            (
                "TYPE_CHECKING name in a signature",
                "`if TYPE_CHECKING:`",
                "`requires:`",
            ),
        ],
    )
    def test_case_and_fix(
        self,
        project: Path,
        capsys: pytest.CaptureFixture[str],
        shape: str,
        says: str,
        fix: str,
    ) -> None:
        declarations, _, requires, _ = FAILING[shape]
        _write(project, declarations, requires)

        _, (finding,) = _check(project, capsys)

        assert says in finding["message"]
        assert fix in finding["remediation"]

    def test_an_annotation_names_the_pythons_it_fails_on(
        self, project: Path, capsys: pytest.CaptureFixture[str],
    ) -> None:
        declarations, _, requires, _ = FAILING["forward annotation"]
        _write(project, declarations, requires)

        _, (finding,) = _check(project, capsys)

        assert "Python 3.11 to 3.13" in finding["message"]

    def test_a_default_fails_on_every_python(
        self, project: Path, capsys: pytest.CaptureFixture[str],
    ) -> None:
        declarations, _, requires, _ = FAILING["forward default"]
        _write(project, declarations, requires)

        _, (finding,) = _check(project, capsys)

        assert "every Python" in finding["message"]

    def test_a_name_nothing_binds_keeps_its_message(
        self, project: Path, capsys: pytest.CaptureFixture[str],
    ) -> None:
        _write(project, [_first("def first() -> Missing:")], "[]")

        _, (finding,) = _check(project, capsys)

        assert "nothing binds that name" in finding["message"]

    def test_the_registered_description_says_when(self) -> None:
        assert "nothing has bound it when it is read" in ERROR_CODE_DESCRIPTIONS[LOAD]


@pytest.mark.parametrize("shape", sorted(FIXED))
def test_the_fixed_form_is_silent_and_loads(
    project: Path, capsys: pytest.CaptureFixture[str], shape: str,
) -> None:
    declarations, requires = FIXED[shape]
    _write(project, declarations, requires)

    rc, findings = _check(project, capsys)
    assert (rc, findings) == (0, [])

    rc, findings = _build(project, capsys, "--no-cache")
    assert (rc, findings) == (0, [])

    loaded = _load_built(project)
    assert loaded.returncode == 0, loaded.stderr


_ANNOTATION_SHAPES = sorted(shape for shape, row in FAILING.items() if row[3])
_ALWAYS_SHAPES = ["forward default", "forward base class", "forward decorator"]


class TestThePythonFloor:
    @pytest.mark.parametrize("spec", [">=3.11", ">=3.13,<3.15"])
    @pytest.mark.parametrize("shape", _ANNOTATION_SHAPES)
    def test_an_annotation_read_is_reported_below_3_14(
        self,
        project: Path,
        capsys: pytest.CaptureFixture[str],
        shape: str,
        spec: str,
    ) -> None:
        declarations, _, requires, _ = FAILING[shape]
        _write(project, declarations, requires)
        _set_range(project, spec)

        assert _check(project, capsys)[0] == 1
        assert _build(project, capsys, "--no-cache")[0] == 1

    @pytest.mark.parametrize("spec", [">=3.14", None, "latest"])
    @pytest.mark.parametrize("shape", _ANNOTATION_SHAPES)
    def test_an_annotation_read_is_silent_otherwise(
        self,
        project: Path,
        capsys: pytest.CaptureFixture[str],
        shape: str,
        spec: str | None,
    ) -> None:
        declarations, _, requires, _ = FAILING[shape]
        _write(project, declarations, requires)
        _set_range(project, spec)

        assert _check(project, capsys) == (0, [])
        assert _build(project, capsys, "--no-cache") == (0, [])

    @pytest.mark.parametrize(
        "spec", [">=3.11", ">=3.13,<3.15", ">=3.14", None, "latest"],
    )
    @pytest.mark.parametrize("shape", _ALWAYS_SHAPES)
    def test_a_read_that_fails_on_every_python_is_always_reported(
        self,
        project: Path,
        capsys: pytest.CaptureFixture[str],
        shape: str,
        spec: str | None,
    ) -> None:
        declarations, marker, requires, _ = FAILING[shape]
        text = _write(project, declarations, requires)
        _set_range(project, spec)

        rc, findings = _check(project, capsys)
        assert rc == 1
        assert [f["line"] for f in findings] == [_line_of(text, marker)]

        rc, findings = _build(project, capsys, "--no-cache")
        assert rc == 1
        assert [f["line"] for f in findings] == [_line_of(text, marker)]

    def test_lowering_the_floor_is_not_hidden_by_the_build_cache(
        self, project: Path, capsys: pytest.CaptureFixture[str],
    ) -> None:
        """A build that hits the cache runs no check."""
        declarations, _, requires, _ = FAILING["own name in a return"]
        _write(project, declarations, requires)
        _set_range(project, ">=3.14")
        assert _build(project, capsys)[0] == 0

        _set_range(project, ">=3.11")

        rc, findings = _build(project, capsys)
        assert rc == 1
        assert len(findings) == 1

    @pytest.mark.parametrize(
        ("spec", "expected"),
        [
            ((">=3.11",), True),
            ((">=3.13", "<3.15"), True),
            ((">=3.11", "<3.14"), True),
            (("<3.14",), True),
            (("~=3.13",), True),
            (("~=3.13.2",), True),
            (("==3.13.*",), True),
            (("==3.12",), True),
            ((">3.13",), True),
            ((">=3.13.2",), True),
            ((">=3.13", "!=3.13.0"), True),
            ((">=3.13", "!=3.13.*", "<3.14"), False),
            (("!=3.11.*", "!=3.12.*", "!=3.13.*"), False),
            ((">=3.14",), False),
            (("==3.14.*",), False),
            (("~=3.14",), False),
            ((">3.13.99", "<3.14"), True),
            (("<3.11",), False),
            ((">=3.14", "<3.11"), False),
            (None, False),
            ((), False),
            (("latest",), False),
            ((">=3.11", "latest"), False),
            ((">=3.11rc1",), False),
            (("===3.13",), False),
            (("~=3",), False),
            ((">=3.13.*",), False),
        ],
    )
    def test_the_range_reading(
        self, spec: tuple[str, ...] | None, expected: bool,
    ) -> None:
        assert _annotations_run_at_load(spec) is expected


#: Plain Python that loads and must stay silent. Each runs for real below.
LOADS: dict[str, str] = {
    "dead_if": "if False:\n    y = LATER\nLATER = 1\n",
    "main_guard": "if __name__ == '__main__':\n    print(LATER)\nLATER = 1\n",
    "short_circuit_and": "y = False and LATER\nLATER = 1\n",
    "short_circuit_or": "y = True or LATER\nLATER = 1\n",
    "ternary": "y = 1 if True else LATER\nLATER = 1\n",
    "compare_chain": "y = 2 < 1 < LATER\nLATER = 1\n",
    "empty_comprehension": "y = [LATER for _ in ()]\nLATER = 1\n",
    "generator_lazy": "y = (LATER for _ in (1,))\nLATER = 1\n",
    "lambda_body": "f = lambda: LATER\nLATER = 1\n",
    "assert_message": "assert True, LATER\nLATER = 1\n",
    "except_type_unraised": (
        "try:\n    pass\nexcept LATER:\n    pass\nLATER = ValueError\n"
    ),
    "while_false": "while False:\n    y = LATER\nLATER = 1\n",
    "for_empty": "for _ in ():\n    y = LATER\nLATER = 1\n",
    "suppress_nameerror": (
        "import contextlib\nwith contextlib.suppress(NameError):\n"
        "    y = LATER\nLATER = 1\n"
    ),
    "try_nameerror": "try:\n    y = LATER\nexcept NameError:\n    y = 0\nLATER = 1\n",
    "try_broad": "try:\n    y = LATER\nexcept Exception:\n    y = 0\nLATER = 1\n",
    "try_finally_after_bind": (
        "try:\n    LATER = 1\nfinally:\n    y = LATER\n"
    ),
    "builtin_shadow": "y = len('a')\nlen = 3\n",
    "builtin_shadow_annotation": "def f(a: int) -> int:\n    return a\nint = 3\n",
    "loop_later_pass": "for i in range(2):\n    if i:\n        y = prev\n    prev = i\n",
    "ann_self_value": "x: x = int\n",
    "class_local_then_global": "G = 1\nclass A:\n    y = G\n    G = 2\n",
    "class_reads_own_earlier": (
        "class A:\n    T = int\n    def f(self) -> T:\n        return 1\n"
    ),
    "global_by_call": (
        "def init():\n    global LATER\n    LATER = 1\ninit()\ny = LATER\n"
    ),
    "globals_write": "globals()['LATER'] = 1\ny = LATER\nLATER = 2\n",
    "sys_modules_write": (
        "import sys\nsys.modules[__name__].LATER = 1\ny = LATER\nLATER = 2\n"
    ),
    "sys_modules_get_write": (
        "import sys\nsetattr(sys.modules.get(__name__), 'LATER', 1)\n"
        "y = LATER\nLATER = 2\n"
    ),
    "sys_alias_write": (
        "import sys as s\ns.modules[__name__].LATER = 1\ny = LATER\nLATER = 2\n"
    ),
    "from_sys_modules_write": (
        "from sys import modules\nmodules[__name__].LATER = 1\ny = LATER\nLATER = 2\n"
    ),
    "self_import_write": "import probe as me\nme.LATER = 1\ny = LATER\nLATER = 2\n",
    "self_from_import_write": (
        "import sys\nfrom probe import __name__ as me\n"
        "sys.modules[me].LATER = 1\ny = LATER\nLATER = 2\n"
    ),
    "importlib_self_write": (
        "import importlib\nimportlib.import_module(__name__).LATER = 1\n"
        "y = LATER\nLATER = 2\n"
    ),
    "import_module_alias_write": (
        "import importlib as il\nil.import_module(__name__).LATER = 1\n"
        "y = LATER\nLATER = 2\n"
    ),
    "bare_import_module_write": (
        "from importlib import import_module\n"
        "import_module(__name__).LATER = 1\ny = LATER\nLATER = 2\n"
    ),
    "renamed_import_module_write": (
        "from importlib import import_module as load\n"
        "load(__name__).LATER = 1\ny = LATER\nLATER = 2\n"
    ),
    "function_globals_write": (
        "def f():\n    pass\nf.__globals__['LATER'] = 1\ny = LATER\nLATER = 2\n"
    ),
    "frame_globals_write": (
        "import inspect\ninspect.currentframe().f_globals['LATER'] = 1\n"
        "y = LATER\nLATER = 2\n"
    ),
    "builtins_alias_write": (
        "import builtins as b\nb.LATER = 1\ny = LATER\nLATER = 2\ndel b.LATER\n"
    ),
    "metaclass_prepare": (
        "class M(type):\n    @classmethod\n    def __prepare__(m, n, b):\n"
        "        return {'LATER': 1}\n"
        "class A(metaclass=M):\n    y = LATER\nLATER = 2\n"
    ),
    "inherited_metaclass_prepare": (
        "class M(type):\n    @classmethod\n    def __prepare__(m, n, b):\n"
        "        return {'LATER': 1}\n"
        "class Base(metaclass=M):\n    pass\n"
        "class A(Base):\n    y = LATER\nLATER = 2\n"
    ),
    "metaclass_from_a_call": (
        "class M(type):\n    @classmethod\n    def __prepare__(m, n, b):\n"
        "        return {'LATER': 1}\n"
        "def with_meta():\n    return M('Tmp', (), {})\n"
        "class A(with_meta()):\n    y = LATER\nLATER = 2\n"
    ),
    "metaclass_through_a_variable": (
        "class M(type):\n    @classmethod\n    def __prepare__(m, n, b):\n"
        "        return {'LATER': 1}\n"
        "Base = M('Base', (), {})\n"
        "class A(Base):\n    y = LATER\nLATER = 2\n"
    ),
    "metaclass_through_double_star": (
        "class M(type):\n    @classmethod\n    def __prepare__(m, n, b, **k):\n"
        "        return {'LATER': 1}\n"
        "opts = {'metaclass': M}\n"
        "class A(**opts):\n    y = LATER\nLATER = 2\n"
    ),
    "metaclass_through_star_bases": (
        "class M(type):\n    @classmethod\n    def __prepare__(m, n, b):\n"
        "        return {'LATER': 1}\n"
        "class Base(metaclass=M):\n    pass\n"
        "bases = (Base,)\n"
        "class A(*bases):\n    y = LATER\nLATER = 2\n"
    ),
    "future_annotations": (
        "from __future__ import annotations\n"
        "class Foo:\n    def f(self) -> Foo:\n        return self\n"
    ),
    "type_checking_else": (
        "from typing import TYPE_CHECKING\nif TYPE_CHECKING:\n    X = int\n"
        "else:\n    X = str\ndef f(a: X) -> X:\n    return a\n"
    ),
    "not_type_checking": (
        "from typing import TYPE_CHECKING\nif not TYPE_CHECKING:\n    X = str\n"
        "def f(a: X) -> X:\n    return a\n"
    ),
    "own_flag_named_type_checking": (
        "TYPE_CHECKING = True\nif TYPE_CHECKING:\n    X = int\n"
        "def f(a: X) -> X:\n    return a\n"
    ),
    "typing_flag_set_by_hand": (
        "import typing\ntyping.TYPE_CHECKING = True\n"
        "if typing.TYPE_CHECKING:\n    X = int\n"
        "typing.TYPE_CHECKING = False\n"
        "def f(a: X) -> X:\n    return a\n"
    ),
    "quoted_forward": "def f(a: 'L') -> 'L':\n    return a\nclass L:\n    pass\n",
    "later_with_item_is_swallowed": (
        "import contextlib\nwith contextlib.suppress(NameError), LATER:\n"
        "    pass\nLATER = 1\n"
    ),
    "target_reads_an_earlier_target": "items = [0]\ni, items[i] = 0, 1\n",
    "walrus_in_a_dict_value": "d = {1: (a := 2), a: 3}\n",
    "walrus_earlier_in_the_same_tuple": "t = ((a := 1), a)\n",
    "class_keyword_after_walrus": (
        "class M(type):\n    def __new__(m, n, b, d, **k):\n"
        "        return super().__new__(m, n, b, d)\n"
        "    def __init__(c, n, b, d, **k):\n        pass\n"
        "class A(metaclass=M, flag=(f := 1), other=f):\n    pass\n"
    ),
    "second_comparison_operand_never_reached": "y = 1 > 2 > LATER\nLATER = 1\n",
}

#: A read that runs on every load, so the module cannot be imported.
RAISES: dict[str, str] = {
    "value": "y = LATER\nLATER = 1\n",
    "own_default": "class Foo:\n    def f(self, a=Foo):\n        return a\n",
    "base": "class A(B):\n    pass\nclass B:\n    pass\n",
    "decorator": "@later\ndef f():\n    pass\ndef later(fn):\n    return fn\n",
    "if_test": "if LATER:\n    pass\nLATER = 1\n",
    "while_test": "while LATER:\n    LATER = 0\n",
    "for_iterable": "for x in LATER:\n    pass\nLATER = ()\n",
    "with_context": "with LATER:\n    pass\nLATER = None\n",
    "first_iterable": "y = [v for v in LATER]\nLATER = ()\n",
    "lambda_default": "f = lambda a=LATER: a\nLATER = 1\n",
    "left_of_and": "y = LATER and 1\nLATER = 1\n",
    "ternary_test": "y = 1 if LATER else 2\nLATER = 1\n",
    "first_comparison_operand": "y = LATER < 1\nLATER = 1\n",
    "augmented": "LATER += 1\nLATER = 1\n",
    "bare_annotation_binds_nothing": "x: int\ny = x\nx = 1\n",
    "class_body_value": "class A:\n    y = LATER\nLATER = 1\n",
    "method_default": "class A:\n    def m(self, v=LATER):\n        return v\nLATER = 1\n",
    "method_decorator": (
        "class A:\n    @later\n    def m(self):\n        return 1\n"
        "def later(fn):\n    return fn\n"
    ),
    "type_checking_default": (
        "from typing import TYPE_CHECKING\nif TYPE_CHECKING:\n    X = 1\n"
        "def f(a=X):\n    return a\n"
    ),
    "dotted_type_checking_default": (
        "import typing\nif typing.TYPE_CHECKING:\n    X = 1\ny = X\n"
    ),
    "type_checking_read_above_real_binding": (
        "from typing import TYPE_CHECKING\nif TYPE_CHECKING:\n    X = 1\n"
        "y = X\nX = 2\n"
    ),
    "imported_base_with_own_name": (
        "import enum\nclass Color(enum.Enum):\n    RED = 1\n"
        "    def f(self, other=Color):\n        return other\n"
    ),
}


def _run_as_module(source: str) -> None:
    """Execute *source* as a real module called ``probe``."""
    module = types.ModuleType("probe")
    sys.modules["probe"] = module
    try:
        exec(compile(source, "<shape>", "exec"), module.__dict__)  # noqa: S102
    finally:
        sys.modules.pop("probe", None)


def _order_reads(source: str) -> list[str]:
    return [
        read.name
        for read in find_unbound_names(
            source, module_name="probe", requires_python=(">=3.11",),
        )
    ]


class TestShapesThatLoad:
    @pytest.mark.parametrize("shape", sorted(LOADS))
    def test_it_really_loads(self, shape: str) -> None:
        _run_as_module(LOADS[shape])

    @pytest.mark.parametrize("shape", sorted(LOADS))
    def test_it_is_silent(self, shape: str) -> None:
        assert _order_reads(LOADS[shape]) == []

    def test_an_assert_is_gone_under_dash_o(self) -> None:
        source = "assert LATER\nLATER = 1\n"

        loaded = subprocess.run(
            [sys.executable, "-O", "-c", source],
            capture_output=True,
            text=True,
            check=False,
        )

        assert loaded.returncode == 0, loaded.stderr
        assert _order_reads(source) == []

    @pytest.mark.parametrize(
        "source",
        [
            pytest.param(
                "from os.path import *\ny = LATER\nLATER = 1\n", id="star-import",
            ),
            pytest.param(
                "def set_it():\n    global LATER\n    LATER = 1\ny = LATER\n",
                id="declared-global",
            ),
            pytest.param(
                "class A:\n    y = LATER\n    LATER = 1\nLATER = 2\n",
                id="class-binds-it-later",
            ),
            pytest.param(
                "def f():\n    return LATER\ny = f\nLATER = 1\n",
                id="function-body",
            ),
        ],
    )
    def test_what_the_rule_leaves_alone(self, source: str) -> None:
        assert _order_reads(source) == []

    def test_a_shadowed_stdlib_loader_does_not_close_the_check(self) -> None:
        """The emitter's own helper touches ``sys.modules`` under a mangled key."""
        source = (
            "def _s0ma_import_shadowed(_name):\n"
            "    import sys as _sys\n"
            "    return _sys.modules.get('_s0ma_shadowed__' + _name)\n"
            "y = LATER\nLATER = 1\n"
        )
        assert _order_reads(source) == ["LATER"]

    def test_a_same_word_import_keeps_the_check_on(self) -> None:
        """``from django.db import models`` in a module named ``models``."""
        source = "from collections import abc\nx = abc.Mapping\ny = LATER\nLATER = 1\n"
        found = find_unbound_names(
            source, module_name="abc", requires_python=(">=3.11",),
        )
        assert [read.name for read in found] == ["LATER"]

    @pytest.mark.parametrize(
        "imported",
        [
            pytest.param("import app.probe as me", id="import-as"),
            pytest.param("from app import probe as me", id="from-import"),
        ],
    )
    def test_a_qualified_self_import_that_writes_closes_the_check(
        self, imported: str,
    ) -> None:
        source = f"{imported}\nme.LATER = 1\ny = LATER\nLATER = 2\n"
        assert _order_reads(source) == []

    def test_the_wider_guard_also_covers_a_name_nothing_binds(self) -> None:
        source = "import sys\nsys.modules.get(__name__).made = 1\nvalue = made\n"
        assert find_unbound_names(source) == []


class TestShapesThatFail:
    @pytest.mark.parametrize("shape", sorted(RAISES))
    def test_it_really_raises(self, shape: str) -> None:
        with pytest.raises(NameError):
            _run_as_module(RAISES[shape])

    @pytest.mark.parametrize("shape", sorted(RAISES))
    def test_it_is_reported(self, shape: str) -> None:
        assert _order_reads(RAISES[shape])

    @pytest.mark.parametrize(
        "source",
        [
            pytest.param(
                "class Foo:\n    def f(self) -> Foo:\n        return self\n",
                id="own-return",
            ),
            pytest.param("def f(a: Later):\n    pass\nLater = 1\n", id="forward"),
            pytest.param("x: Later = 1\nLater = 2\n", id="module-annotation"),
            pytest.param(
                "from typing import TYPE_CHECKING\nif TYPE_CHECKING:\n"
                "    from decimal import Decimal\n"
                "def f(a: Decimal):\n    return a\n",
                id="type-checking",
            ),
        ],
    )
    def test_an_annotation_needs_a_declared_range(self, source: str) -> None:
        assert _order_reads(source)
        assert find_unbound_names(source, module_name="probe") == []
        assert (
            find_unbound_names(
                source, module_name="probe", requires_python=(">=3.14",),
            )
            == []
        )


#: Modules that mention a namespace route but never reach their own module.
#: Each holds (source, the name reported, whether it is a load read).
ROUTES_TO_ANOTHER_MODULE: dict[str, tuple[str, str, bool]] = {
    "import_module_of_another": (
        "import importlib\n"
        "def mood() -> dict[str, Any]:\n"
        '    return {"m": importlib.import_module("json")}\n',
        "Any",
        True,
    ),
    "membership_in_sys_modules": (
        "import sys\n"
        "def mood() -> dict[str, Any]:\n"
        '    return {"m": "json" in sys.modules}\n',
        "Any",
        True,
    ),
    "store_under_another_key": (
        "import sys\n"
        "def hold(value: Missing) -> None:\n"
        '    sys.modules["_holder"] = object()\n',
        "Missing",
        True,
    ),
    "own_class_beside_a_sys_modules_read": (
        "import sys\n"
        "class Book:\n"
        "    def clone(self) -> Book:\n"
        '        return sys.modules["json"]\n',
        "Book",
        True,
    ),
    "body_read_beside_import_module": (
        "import importlib\n"
        "def mood():\n"
        '    importlib.import_module("json")\n'
        "    return missing\n",
        "missing",
        False,
    ),
    "signature_beside_a_globals_read": (
        "import sys\n"
        "def mood() -> Missing:\n"
        '    return sys._getframe().f_globals.get("__name__")\n',
        "Missing",
        True,
    ),
    "dunder_import_of_another": (
        'json = __import__("json")\ndef mood() -> Missing:\n    return json\n',
        "Missing",
        True,
    ),
    "aliased_sys_modules_pop_of_another": (
        "import sys as s\n"
        "def mood() -> Missing:\n"
        '    return s.modules.pop("json", None)\n',
        "Missing",
        True,
    ),
    "from_sys_modules_get_of_another": (
        "from sys import modules\n"
        "def mood() -> Missing:\n"
        '    return modules.get("json")\n',
        "Missing",
        True,
    ),
}

#: Each reaches its own namespace and binds ``X`` there: (setup, the reach).
ROUTES_TO_ITSELF: dict[str, tuple[str, str]] = {
    "sys_modules_store": ("import sys\n", "sys.modules[__name__].X = 1\n"),
    "sys_modules_get": ("import sys\n", "sys.modules.get(__name__).X = 1\n"),
    "sys_modules_setdefault": (
        "import sys\n",
        "sys.modules.setdefault(__name__, None).X = 1\n",
    ),
    "sys_modules_own_constant": ("import sys\n", 'sys.modules["probe"].X = 1\n'),
    "aliased_sys_modules": ("import sys as s\n", "s.modules[__name__].X = 1\n"),
    "from_sys_modules": ("from sys import modules\n", "modules[__name__].X = 1\n"),
    "import_module": (
        "import importlib\n",
        "importlib.import_module(__name__).X = 1\n",
    ),
    "import_module_own_constant": (
        "import importlib\n",
        'importlib.import_module("probe").X = 1\n',
    ),
    "bare_import_module": (
        "from importlib import import_module\n",
        "import_module(__name__).X = 1\n",
    ),
    "dunder_import": ("", "__import__(__name__).X = 1\n"),
    "self_import": ("", "import probe as me\nme.X = 1\n"),
    "frame_globals_store": ("import sys\n", 'sys._getframe().f_globals["X"] = 1\n'),
    "function_globals_update": (
        "def f():\n    pass\n",
        "f.__globals__.update(X=1)\n",
    ),
    "function_globals_setdefault": (
        "def f():\n    pass\n",
        'f.__globals__.setdefault("X", 1)\n',
    ),
    "globals_through_an_alias": (
        "import sys\n",
        'g = sys._getframe().f_globals\ng["X"] = 1\n',
    ),
    "globals_update_through_an_alias": (
        "import sys\n",
        "g = sys._getframe().f_globals\ng.update(X=1)\n",
    ),
    "builtins_store": ("import builtins\n", "builtins.X = 1\n"),
}


class TestOwnNamespaceGuard:
    @pytest.mark.parametrize("shape", sorted(ROUTES_TO_ANOTHER_MODULE))
    def test_a_route_to_another_module_keeps_the_check_on(self, shape: str) -> None:
        source, name, at_load = ROUTES_TO_ANOTHER_MODULE[shape]

        found = find_unbound_names(
            source, module_name="probe", requires_python=(">=3.11",),
        )

        assert [(read.name, read.at_load) for read in found] == [(name, at_load)]

    @pytest.mark.parametrize("shape", sorted(ROUTES_TO_ITSELF))
    def test_a_route_to_itself_stops_the_check(self, shape: str) -> None:
        setup, reach = ROUTES_TO_ITSELF[shape]
        read = "y = X\n"

        assert _order_reads(setup + read) == ["X"]
        assert _order_reads(setup + reach + read) == []

    @pytest.mark.parametrize("shape", sorted(set(ROUTES_TO_ITSELF) - {"builtins_store"}))
    def test_a_route_to_itself_really_binds_the_name(self, shape: str) -> None:
        setup, reach = ROUTES_TO_ITSELF[shape]

        _run_as_module(setup + reach + "y = X\n")

    def test_a_read_through_a_globals_alias_keeps_the_check_on(self) -> None:
        source = (
            "import sys\n"
            "g = sys._getframe().f_globals\n"
            'name = g["__name__"]\n'
            "y = X\n"
        )
        assert _order_reads(source) == ["X"]


@pytest.mark.skipif(
    sys.version_info < (3, 12), reason="PEP 695 syntax needs Python 3.12",
)
class TestTypeParameters:
    @pytest.mark.parametrize(
        "source",
        [
            pytest.param("def f[T](v: T) -> T:\n    return v\n", id="function"),
            pytest.param(
                "class C[T](list[T]):\n    x: T\n    def m(self) -> T:\n"
                "        return self[0]\n",
                id="class",
            ),
            pytest.param("type A = Later\nLater = int\n", id="alias-is-lazy"),
        ],
    )
    def test_silent(self, source: str) -> None:
        _run_as_module(source)
        assert _order_reads(source) == []

    def test_a_later_base_is_still_read(self) -> None:
        assert _order_reads("class C[T](Later):\n    pass\nLater = object\n") == [
            "Later",
        ]
