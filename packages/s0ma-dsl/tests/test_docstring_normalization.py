"""Emit-time docstring normalization (DSL-M3, F-M3-8, P-7).

The emitter rewrites every body docstring to its PEP 257
``inspect.cleandoc`` form at emit time so the emitted ``__doc__`` is
interpreter-independent at the ARTIFACT level. CPython 3.13 dedents
``__doc__`` at compile time (python/cpython#81283) while ≤3.12 preserves
the source indentation, so byte-identical emitted code would otherwise
serve different ``__doc__`` bytes per interpreter (the F-M3-8 CI failure
on the 3.11/3.12 legs only). Normalising the docstring literal in the
emitted source collapses both raw forms to one canonical string.

This module pins:
  - the normaliser helper's behaviour (multi-line indented docstrings are
    cleaned; single-line / no-docstring bodies are byte-unchanged; class
    + method docstrings both normalise; escapes / raw prefixes survive);
  - the interpreter-independence property end-to-end: a fixture project
    with a multi-line docstring builds, and the emitted module's
    ``__doc__`` equals ``inspect.cleandoc(__doc__)`` — the fixed point
    that makes it the same on every interpreter and that keeps the mcp
    binding-layer ``normalize_docstring`` a no-op (the surface snapshot
    must not move).
"""

from __future__ import annotations

import inspect
import textwrap
from typing import TYPE_CHECKING

from s0ma_dsl.cli.main import EXIT_SUCCESS, S0maCLI
from s0ma_dsl.codegen.python_emitter import _normalize_body_docstrings

if TYPE_CHECKING:
    from pathlib import Path


# ---------------------------------------------------------------------------
# Helper-level: _normalize_body_docstrings
# ---------------------------------------------------------------------------


def _doc_of(source: str, name: str) -> str | None:
    """Compile *source* and return ``<name>.__doc__``."""
    ns: dict[str, object] = {}
    exec(compile(source, "<test>", "exec"), ns)  # noqa: S102 — test-only
    obj = ns[name]
    return obj.__doc__  # type: ignore[union-attr]


def test_multiline_docstring_becomes_interpreter_independent() -> None:
    """A multi-line, indented docstring is rewritten to its cleandoc form."""
    body = textwrap.dedent(
        '''\
        def greet(name: str) -> str:
            """Render the greeting for ``name``.

            A second paragraph, indented four under the def.
            """
            return name'''
    )
    out = _normalize_body_docstrings(body)
    doc = _doc_of(out, "greet")
    assert doc is not None
    # The emitted __doc__ is already its own cleandoc fixed point — so
    # every interpreter (3.11 verbatim, 3.13 compile-time dedent) yields
    # the same bytes.
    assert doc == inspect.cleandoc(doc)
    # And it equals cleandoc of the ORIGINAL authored docstring value.
    assert doc == (
        "Render the greeting for ``name``.\n\n"
        "A second paragraph, indented four under the def."
    )


def test_single_line_docstring_is_byte_unchanged() -> None:
    """A single-line docstring needs no normalisation — bytes untouched."""
    body = 'def g():\n    """Already clean."""\n    return 1'
    assert _normalize_body_docstrings(body) == body


def test_no_docstring_body_is_byte_unchanged() -> None:
    """A body without any docstring is returned verbatim."""
    body = "def h(x: int) -> int:\n    return x + 1"
    assert _normalize_body_docstrings(body) == body


def test_class_and_method_docstrings_both_normalised() -> None:
    """Both the class docstring and a method docstring are normalised."""
    body = textwrap.dedent(
        '''\
        class Greeter:
            """Greeter service.

            Indented class docstring.
            """

            def greet(self, name: str) -> str:
                """Greet ``name``.

                Indented method docstring.
                """
                return name'''
    )
    out = _normalize_body_docstrings(body)
    ns: dict[str, object] = {}
    exec(compile(out, "<test>", "exec"), ns)  # noqa: S102 — test-only
    cls = ns["Greeter"]
    assert cls.__doc__ == inspect.cleandoc(cls.__doc__)  # type: ignore[union-attr]
    assert cls.greet.__doc__ == inspect.cleandoc(cls.greet.__doc__)  # type: ignore[union-attr]


def test_raw_prefix_and_escapes_survive_normalisation() -> None:
    """Whitespace-only transform: a raw prefix and ``\\d`` escape survive.

    The normaliser operates on the docstring's SOURCE whitespace, never
    re-rendering from the parsed value — so a raw-string prefix and any
    embedded escape are preserved exactly while the indentation is
    cleaned. (Guards against a naive "re-emit from the value"
    implementation that would change the literal beyond whitespace.)
    """
    body = textwrap.dedent(
        r'''
        def matcher() -> str:
            r"""Pattern \d+ for digits.

            Indented continuation.
            """
            return ""'''
    ).lstrip("\n")
    out = _normalize_body_docstrings(body)
    # The raw prefix is still present in the emitted source.
    assert 'r"""' in out
    doc = _doc_of(out, "matcher")
    assert doc is not None
    assert doc == inspect.cleandoc(doc)
    # The backslash escape is preserved in the value (raw string: ``\d``).
    assert "\\d+" in doc


def test_normaliser_is_idempotent() -> None:
    """Running the normaliser twice changes nothing the second time."""
    body = textwrap.dedent(
        '''\
        def f():
            """Line one.

            Line two indented.
            """
            return 1'''
    )
    once = _normalize_body_docstrings(body)
    twice = _normalize_body_docstrings(once)
    assert once == twice


def test_unparseable_body_returned_unchanged() -> None:
    """A body that does not parse is returned verbatim (not a validator)."""
    body = "def broken(:\n    not valid python"
    assert _normalize_body_docstrings(body) == body


# ---------------------------------------------------------------------------
# End-to-end: a real build emits interpreter-independent docstrings
# ---------------------------------------------------------------------------


_MODULE_WITH_MULTILINE_DOCSTRING = textwrap.dedent(
    '''\
module greeter
    layer: DOMAIN
    version: 1.0.0
    intent: "Module whose nerve carries a multi-line indented docstring."
    exports: [greet]

    requires: none
    uses: none
    soft_requires: none
    runtime_only_requires: none
    deferred_requires: none
    exports_helpers: none
nerve greet :: DOMAIN
    kind: FUNCTION
    visibility: PUBLIC
    intent: "Greet a user by name."
    expects: "name is a non-empty string"
    guarantees: "returns a greeting string"
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
    covered_by: none
    ---
    def greet(name: str) -> str:
        """Return a greeting for ``name``.

        The body of this docstring is indented four spaces under the
        ``def`` in the authored source. After emit-time normalization
        the emitted ``__doc__`` carries no common margin, so it reads
        identically on CPython 3.11 (verbatim) and 3.13 (compile-time
        dedent).
        """
        return "hello " + name
'''
)


def test_built_module_docstring_is_interpreter_independent(
    tmp_path: Path,
) -> None:
    """A built nerve's emitted ``__doc__`` is its own cleandoc fixed point.

    This is the property F-M3-8 needs: the emitted ``__doc__`` already
    equals ``inspect.cleandoc(__doc__)``, so it is byte-identical across
    interpreters AND the mcp binding-layer ``normalize_docstring`` is a
    no-op on it (which is why the surface snapshot does not move).
    """
    project = tmp_path / "greeter_proj"
    (project / "src").mkdir(parents=True)
    (project / "pyproject.toml").write_text(
        textwrap.dedent(
            """\
            [project]
            name = "greeter_proj"
            version = "0.1.0"

            [tool.s0ma]
            source_roots = ["src"]
            build_dir = "build"
            """
        ),
        encoding="utf-8",
        newline="\n",
    )
    (project / "src" / "greeter.s0ma").write_text(
        _MODULE_WITH_MULTILINE_DOCSTRING, encoding="utf-8", newline="\n"
    )

    cli = S0maCLI()
    rc = cli.run([
        "--project-root", str(project),
        "build", str(project),
        "--mode", "dev",
        "--no-cache",
        "--quiet",
    ])
    assert rc == EXIT_SUCCESS

    emitted = (project / "build" / "greeter.py").read_text(encoding="utf-8")
    # Import the emitted module in isolation and read the nerve's __doc__.
    ns: dict[str, object] = {}
    exec(compile(emitted, "greeter.py", "exec"), ns)  # noqa: S102 — test-only
    greet = ns["greet"]
    doc = greet.__doc__  # type: ignore[union-attr]
    assert doc is not None
    assert doc == inspect.cleandoc(doc), (
        "emitted __doc__ is not its own cleandoc fixed point — it would "
        "differ across interpreters and move the mcp surface snapshot"
    )
    # The continuation lines carry no common leading margin in the emitted
    # source (that is what makes the 3.13 compile-time dedent a no-op).
    assert '"""Return a greeting for ``name``.' in emitted
