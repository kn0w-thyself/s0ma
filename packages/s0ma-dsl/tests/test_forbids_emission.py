"""Emission of the ``forbids:`` line, and the surfaces that carry it.

A nerve's sentence rides its ``Contract(...)`` as ``forbids=[...]``, after
``postconditions`` and before ``max_latency_ms``. A ganglion's sentence rides
a ``contracts=Contract(forbids=[...])`` parameter, in the position and layout
a nerve gives ``contracts=``. ``none`` and ``pending`` emit nothing, and the
``Contract`` import is written exactly when something uses it.

The same sentence reaches the real core through the emitted module, the
self-context companion as its authored state object, and the doc resolver as
an addressable field of nerves and ganglia. The bounded self-prompt card never
carries it.
"""

from __future__ import annotations

import ast
from typing import TYPE_CHECKING, Any

import pytest

from s0ma_dsl.cli.main import EXIT_SUCCESS, S0maCLI
from s0ma_dsl.codegen.doc_emitter.markdown import render_doc_ref_markdown
from s0ma_dsl.codegen.python_emitter import PythonEmitter
from s0ma_dsl.codegen.self_context import (
    SELF_CONTEXT_FILENAME,
    SELF_PROMPT_CARD_FILENAME,
)
from s0ma_dsl.parser.s0ma_parser import _parse_entity_ref, parse_s0ma
from s0ma_dsl.resolver.doc_resolver import DocReferenceResolver, build_project_index

if TYPE_CHECKING:
    from pathlib import Path

_MODULE = "ledger_emit"
_SENTENCE = "Never writes a file or reaches the network."
_WATCH_SENTENCE = "Never changes a total it watches."
_PENDING_REASON = "Waiting on a review of what this part may touch."
_PENDING = f'pending("{_PENDING_REASON}")'
# A ``|`` block whose sentence holds double quotes, a backslash and a line break.
_BLOCK = (
    "|\n"
    '        Never prints the "secret" token or a C:\\temp path,\n'
    "        and never echoes either back."
)
_BLOCK_TEXT = (
    'Never prints the "secret" token or a C:\\temp path,\n'
    "and never echoes either back."
)
# ``guarantees:`` may not be ``none`` on a nerve; ``pending`` emits nothing.
_GUARANTEES_PENDING = 'pending("No total is promised for this part yet.")'
_IMPORT = "from s0ma.models import Contract\n"
_CONTENT_HASH = "1:" + "0" * 64

_TEMPLATE = """\
module ledger_emit
    layer: DOMAIN
    version: 1.0.0
    intent: "Keeps a running ledger total."
    exports: [post_entry]

    requires: none
    uses: none
    soft_requires: none
    runtime_only_requires: none
    deferred_requires: none
    exports_helpers: none
nerve post_entry :: DOMAIN
    kind: FUNCTION
    visibility: PUBLIC
    intent: "Adds one amount to a running total."
    expects: @EXPECTS@
    guarantees: @GUARANTEES@
    forbids: none
@POST@    evaluates_at: FUNCTION_BOUNDARY
    provides: none
    returns: none
    raises: none
    interface: none
    latency_ms: @LATENCY@
    depends_on: none
    internal: none
    expected_exceptions: none
    consumes_via_dict: none
    declares_attributes: none
    covered_by: none
    ---
    def post_entry(total, amount):
        return total + amount
nerve peek_total :: DOMAIN
    kind: FUNCTION
    visibility: INTERNAL
    intent: "Returns the running total unchanged."
    expects: none
    guarantees: @GUARANTEES_PENDING@
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
    def peek_total(total):
        return total
ganglion watch_entries :: DOMAIN
    visibility: INTERNAL
    scope: SUBSYSTEM
    intent: "Watches ledger entries for totals that drift."
    observes: [post_entry]
    on_anomaly: "Logs the total and carries on."
    forbids: none
@WATCH@    priors: "Totals never go negative."
    depends_on: none
    covered_by: none
    ---
    def watch_entries(signal):
        return signal
"""

_NERVE_DECORATOR = (
    "@component(\n"
    '    name="post_entry",\n'
    "    kind=ComponentKind.FUNCTION,\n"
    "    layer=Layer.DOMAIN,\n"
    '    intent="Adds one amount to a running total.",\n'
    "    contracts=Contract(\n"
    '        preconditions=["amount is a number."],\n'
    '        postconditions=["Returns the new total."],\n'
    '        forbids=["Never writes a file or reaches the network."],\n'
    "        max_latency_ms=50,\n"
    "    ),\n"
    '    metadata={"visibility": "PUBLIC", "evaluates_at": "FUNCTION_BOUNDARY"},\n'
    ")\n"
)

_GANGLION_DECORATOR = (
    "@component(\n"
    '    name="watch_entries",\n'
    "    kind=ComponentKind.SERVICE,\n"
    "    layer=Layer.DOMAIN,\n"
    '    intent="Watches ledger entries for totals that drift.",\n'
    "    contracts=Contract(\n"
    '        forbids=["Never changes a total it watches."],\n'
    "    ),\n"
    '    metadata={"visibility": "INTERNAL", "scope": "SUBSYSTEM", '
    '"observes": ["post_entry"], "priors": "Totals never go negative.", '
    '"on_anomaly": "Logs the total and carries on."},\n'
    ")\n"
)


def _source(
    *,
    post: str | None = f'"{_SENTENCE}"',
    watch: str | None = f'"{_WATCH_SENTENCE}"',
    post_contract: bool = True,
    extra: str = "",
) -> str:
    """Return the ledger module with the two ``forbids:`` lines given.

    ``post`` and ``watch`` are what follows ``forbids:`` on the nerve
    ``post_entry`` and on the ganglion ``watch_entries``; ``None`` leaves the
    line out. With ``post_contract=False`` the nerve has no other contract
    line: ``expects`` and ``latency_ms`` are ``none``, and ``guarantees`` is
    pending.
    ``extra`` is appended as written.
    """

    def line(value: str | None) -> str:
        return "" if value is None else f"    forbids: {value}\n"

    return (
        _TEMPLATE.replace(
            "@EXPECTS@", '"amount is a number."' if post_contract else "none"
        )
        .replace(
            "@GUARANTEES@",
            '"Returns the new total."' if post_contract else _GUARANTEES_PENDING,
        )
        .replace("@GUARANTEES_PENDING@", _GUARANTEES_PENDING)
        .replace("@LATENCY@", "50" if post_contract else "none")
        .replace("@POST@", line(post))
        .replace("@WATCH@", line(watch))
        + extra
    )


def _parse(source: str) -> Any:
    return parse_s0ma(source, filename=f"{_MODULE}.s0ma")


def _emit(source: str) -> str:
    return PythonEmitter(module_name=_MODULE).emit(_parse(source))


def _decorator(emitted: str, name: str) -> str:
    """Return the ``@component(...)`` block that decorates the function *name*."""
    end = emitted.index(f"\ndef {name}(")
    start = emitted.rindex("@component(", 0, end)
    return emitted[start : end + 1]


def _register(emitted: str) -> dict[str, Any]:
    """Run *emitted* against the real core, in a registry of its own.

    The default registry persists to ``.s0ma/registry.db``; a fresh in-memory
    one keeps a registration from leaking into the next run.
    """
    from s0ma.registry import ComponentRegistry, get_registry, set_registry

    previous = get_registry(persist=False)
    set_registry(ComponentRegistry(persist=False))
    try:
        namespace: dict[str, Any] = {"__name__": f"{_MODULE}_exec"}
        exec(compile(emitted, f"{_MODULE}.py", "exec"), namespace)
    finally:
        set_registry(previous)
    return namespace


# ---------------------------------------------------------------------------
# The emitted text
# ---------------------------------------------------------------------------


def test_a_nerve_carries_the_sentence_after_postconditions() -> None:
    emitted = _emit(_source())
    assert _decorator(emitted, "post_entry") == _NERVE_DECORATOR


def test_a_ganglion_carries_the_sentence_where_a_nerve_carries_contracts() -> None:
    emitted = _emit(_source())
    assert _decorator(emitted, "watch_entries") == _GANGLION_DECORATOR


def test_a_lone_forbids_line_takes_the_same_layout_on_both_kinds() -> None:
    emitted = _emit(_source(post_contract=False))
    for name, sentence in (
        ("post_entry", _SENTENCE),
        ("watch_entries", _WATCH_SENTENCE),
    ):
        block = _decorator(emitted, name)
        contracts = (
            "    contracts=Contract(\n"
            f'        forbids=["{sentence}"],\n'
            "    ),\n"
        )
        assert block.count(contracts) == 1
        assert (
            block.index("    intent=")
            < block.index(contracts)
            < block.index("    metadata=")
        )


@pytest.mark.parametrize(
    ("post_contract", "post", "watch", "needed"),
    [
        pytest.param(True, "none", "none", True, id="other-contract-lines"),
        pytest.param(False, f'"{_SENTENCE}"', "none", True, id="nerve-forbids-only"),
        pytest.param(
            False, "none", f'"{_WATCH_SENTENCE}"', True, id="ganglion-forbids-only"
        ),
        pytest.param(False, "none", "none", False, id="none-everywhere"),
        pytest.param(False, _PENDING, _PENDING, False, id="pending-everywhere"),
        pytest.param(False, None, None, False, id="lines-left-out"),
    ],
)
def test_the_contract_import_is_written_exactly_when_it_is_used(
    post_contract: bool, post: str | None, watch: str | None, needed: bool
) -> None:
    emitted = _emit(_source(post=post, watch=watch, post_contract=post_contract))
    ast.parse(emitted)
    assert emitted.count(_IMPORT) == (1 if needed else 0)
    assert ("contracts=Contract(" in emitted) is needed


@pytest.mark.parametrize("state", ["none", _PENDING], ids=["none", "pending"])
def test_none_and_pending_emit_no_forbids(state: str) -> None:
    emitted = _emit(_source(post=state, watch=state))
    assert "forbids=" not in emitted
    assert "contracts=" not in _decorator(emitted, "watch_entries")
    assert (
        '        postconditions=["Returns the new total."],\n'
        "        max_latency_ms=50,\n"
    ) in _decorator(emitted, "post_entry")


def test_a_quoted_none_is_content() -> None:
    emitted = _emit(_source(post='"none"', watch='"none"'))
    for name in ("post_entry", "watch_entries"):
        assert '        forbids=["none"],\n' in _decorator(emitted, name)


def test_emission_is_deterministic_and_uses_lf_only() -> None:
    source = _source(post=_BLOCK, watch=_BLOCK)
    emitted = _emit(source)
    assert emitted == _emit(source)
    assert "\r" not in emitted


# ---------------------------------------------------------------------------
# The real core
# ---------------------------------------------------------------------------


def test_the_emitted_module_registers_the_sentence_with_the_real_core() -> None:
    namespace = _register(_emit(_source()))
    nerve = namespace["post_entry"].__component__
    ganglion = namespace["watch_entries"].__component__
    assert nerve.contracts.forbids == [_SENTENCE]
    assert nerve.contracts.preconditions == ["amount is a number."]
    assert nerve.contracts.postconditions == ["Returns the new total."]
    assert nerve.contracts.max_latency_ms == 50
    assert ganglion.contracts.forbids == [_WATCH_SENTENCE]


def test_quotes_a_backslash_and_a_line_break_survive_to_the_core() -> None:
    source = _source(post=_BLOCK, watch=_BLOCK)
    module = _parse(source)
    assert module.nerves[0].forbids == _BLOCK_TEXT
    assert module.ganglia[0].forbids == _BLOCK_TEXT
    emitted = _emit(source)
    ast.parse(emitted)
    namespace = _register(emitted)
    assert namespace["post_entry"].__component__.contracts.forbids == [_BLOCK_TEXT]
    assert namespace["watch_entries"].__component__.contracts.forbids == [
        _BLOCK_TEXT
    ]


# ---------------------------------------------------------------------------
# The doc resolver and the rendered reference
# ---------------------------------------------------------------------------


def _doc_ref(covers: str, section: str) -> str:
    return (
        "doc-ref LedgerReference\n"
        '    intent: "What the ledger parts promise and rule out."\n'
        "    format: markdown\n"
        "    output: docs/ledger.md\n"
        f"    covers: [{covers}]\n"
        f"    sections: [{section}]\n"
    )


def _render(covers: str, section: str) -> tuple[str, list[Any]]:
    """Render a one-section ``doc-ref``; return the text and the resolver's reports."""
    module = _parse(_source(extra=_doc_ref(covers, section)))
    index = build_project_index({module.module.name: module})
    decl = module.doc_refs[0]
    errors = DocReferenceResolver(index=index).resolve_doc_ref(
        decl, filename=f"{_MODULE}.s0ma"
    )
    rendered = render_doc_ref_markdown(
        decl, index=index, content_hash=_CONTENT_HASH, schema_version="1.2.0"
    )
    return rendered, errors


@pytest.mark.parametrize(
    ("covers", "heading", "sentence"),
    [
        pytest.param(
            "nerve where visibility == PUBLIC",
            "### nerve::post_entry",
            _SENTENCE,
            id="nerve",
        ),
        pytest.param(
            "ganglion where visibility == INTERNAL",
            "### ganglion::watch_entries",
            _WATCH_SENTENCE,
            id="ganglion",
        ),
    ],
)
def test_sections_forbids_renders_the_sentence(
    covers: str, heading: str, sentence: str
) -> None:
    rendered, errors = _render(covers, "forbids")
    assert errors == []
    assert f"\n## forbids\n\n{heading}\n\n{sentence}\n" in rendered


def test_sections_forbids_renders_none_as_expects_none_is_rendered() -> None:
    covers = "nerve where visibility == INTERNAL"
    forbids, forbids_errors = _render(covers, "forbids")
    expects, expects_errors = _render(covers, "expects")
    assert forbids_errors == []
    assert expects_errors == []
    assert "\n### nerve::peek_total\n" in forbids
    assert forbids.replace("\n## forbids\n", "\n## expects\n") == expects


@pytest.mark.parametrize(
    ("kind", "name", "sentence"),
    [
        pytest.param("nerve", "post_entry", _SENTENCE, id="nerve"),
        pytest.param("ganglion", "watch_entries", _WATCH_SENTENCE, id="ganglion"),
    ],
)
def test_a_field_reference_to_forbids_resolves(
    kind: str, name: str, sentence: str
) -> None:
    module = _parse(_source())
    index = build_project_index({module.module.name: module})
    entity = index.lookup(kind, name)
    assert entity is not None
    assert entity.fields["forbids"] == sentence
    resolver = DocReferenceResolver(index=index)
    filename = f"{_MODULE}.s0ma"
    ref = _parse_entity_ref(f"{kind}::{name}.forbids", filename, 1)
    assert ref.field_path == ("forbids",)
    assert resolver._resolve_entity_ref(ref, filename, None) == []
    typo = _parse_entity_ref(f"{kind}::{name}.forbid", filename, 1)
    reports = resolver._resolve_entity_ref(typo, filename, None)
    assert [report.code for report in reports] == ["FIELD_NOT_FOUND"]


# ---------------------------------------------------------------------------
# The self-context companion, the core runtime, and the prompt card
# ---------------------------------------------------------------------------


_PYPROJECT = """\
[project]
name = "ledger-demo"
version = "0.1.0"
dependencies = ["s0ma-core", "s0ma-dsl"]

[tool.s0ma]
source_roots = ["src"]
build_dir = "build"
"""


def _build(parent: Path, source: str, capsys: pytest.CaptureFixture[str]) -> Path:
    """Build *source* as a one-module project under *parent*; return its manifest."""
    project = parent / "ledger"
    (project / "src").mkdir(parents=True)
    (project / "pyproject.toml").write_text(
        _PYPROJECT, encoding="utf-8", newline="\n"
    )
    (project / "src" / f"{_MODULE}.s0ma").write_text(
        source, encoding="utf-8", newline="\n"
    )
    rc = S0maCLI().run(
        ["--project-root", str(project), "build", str(project), "--no-cache", "--quiet"]
    )
    captured = capsys.readouterr()
    assert rc == EXIT_SUCCESS, captured.out + captured.err
    manifest = project / "build" / "build.s0ma.json"
    assert manifest.is_file(), captured.out + captured.err
    return manifest


def _components(document: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {item["id"]: item for item in document["components"]}


def test_the_companion_carries_the_state_and_the_core_runtime_loads_it(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    from s0ma.runtime import self_context

    manifest = _build(tmp_path, _source(watch=_PENDING), capsys)
    assert (manifest.parent / SELF_CONTEXT_FILENAME).is_file()
    built = (manifest.parent / f"{_MODULE}.py").read_text(encoding="utf-8")
    assert f'        forbids=["{_SENTENCE}"],\n' in built
    components = _components(self_context(manifest))
    assert components[f"{_MODULE}::post_entry"]["forbids"] == {
        "state": "value",
        "value": _SENTENCE,
    }
    assert components[f"{_MODULE}::watch_entries"]["forbids"] == {
        "state": "pending",
        "reason": _PENDING_REASON,
    }
    assert "forbids" not in components[f"{_MODULE}::peek_total"]


def test_the_prompt_card_is_byte_identical_with_and_without_the_line(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    from s0ma.runtime import self_context

    with_line = _build(tmp_path / "with", _source(), capsys)
    without = _build(tmp_path / "without", _source(post=None, watch=None), capsys)
    card = (with_line.parent / SELF_PROMPT_CARD_FILENAME).read_bytes()
    assert card == (without.parent / SELF_PROMPT_CARD_FILENAME).read_bytes()
    # The companions differ, so the card's sameness says something.
    assert "forbids" in _components(self_context(with_line))[f"{_MODULE}::post_entry"]
    assert "forbids" not in _components(self_context(without))[f"{_MODULE}::post_entry"]
