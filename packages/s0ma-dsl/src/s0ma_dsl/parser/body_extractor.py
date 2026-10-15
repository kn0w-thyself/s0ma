"""Body extraction and validation for .s0ma declaration bodies.

Extracts Python code bodies from raw text captured after ``---`` separators,
validates them for prohibited constructs, and classifies the body type
(function, class, assignment, type alias).

Uses Python's ``tokenize`` module for indentation-aware body boundary
detection and ``ast`` module for structural validation and prohibited
construct detection.

PRD references: FR-07 (exact body preservation), FR-08 (parser strategy),
FR-18 (no-escape-hatch policy), FR-19 (nerve body restrictions).
"""

from __future__ import annotations

import ast
from dataclasses import dataclass
from enum import Enum, unique

from s0ma.decorators import component, internal
from s0ma.types import ComponentKind, Layer

from s0ma_dsl.ast_nodes.enums import Kind
from s0ma_dsl.config import StrictnessMode, get_severity
from s0ma_dsl.errors import S0maParseError, S0maSemanticError

__all__ = [
    "BodyType",
    "BodyInfo",
    "extract_body",
    "validate_body",
    "validate_example_body",
]


# ---------------------------------------------------------------------------
# Body type classification
# ---------------------------------------------------------------------------


@component(
    name="S0maDSL_BodyType",
    kind=ComponentKind.MODEL,
    layer=Layer.FRAMEWORK,
    intent=(
        "Enumerates the structural types of Python bodies found in .s0ma declarations: function, "
        "class, assignment, or type alias."
    ),
    idempotent=True,
    is_framework=True,
)
@unique
class BodyType(Enum):
    """Classification of a Python body's top-level construct."""

    FUNCTION = "function"
    CLASS = "class"
    ASSIGNMENT = "assignment"
    TYPE_ALIAS = "type_alias"
    UNKNOWN = "unknown"


@component(
    name="S0maDSL_BodyInfo",
    kind=ComponentKind.MODEL,
    layer=Layer.FRAMEWORK,
    intent=(
        "Holds extracted information about a Python body: its type, preserved source text, "
        "dedented text for AST analysis, and the parsed AST node."
    ),
    idempotent=True,
    is_framework=True,
)
@dataclass(frozen=True)
class BodyInfo:
    """Extracted information about a Python body from a .s0ma declaration.

    ``source_text`` is the original text exactly as it appeared in the .s0ma
    file (including indentation). ``dedented_text`` is the same text with
    leading indentation removed for AST parsing. ``ast_node`` is the parsed
    AST module node (if the body is syntactically valid Python).
    """

    body_type: BodyType
    source_text: str
    dedented_text: str
    ast_node: ast.Module | None = None
    function_name: str | None = None
    class_name: str | None = None


# ---------------------------------------------------------------------------
# Prohibited construct patterns
# ---------------------------------------------------------------------------

# Names that are prohibited in code bodies (FR-18, spec §4.7.5)
_PROHIBITED_NAMES = frozenset({"exec", "eval", "__import__"})

# Attribute access patterns that are prohibited
_PROHIBITED_ATTR_PATTERNS = frozenset({
    ("importlib", "import_module"),
})


# ---------------------------------------------------------------------------
# Core extraction
# ---------------------------------------------------------------------------


@internal
def _detect_base_indent(text: str) -> int:
    """Detect the base indentation level of a body text block.

    Uses Python's tokenize module to find the first INDENT or NAME token
    and determines the indentation from it. Falls back to examining the
    first non-blank line directly.

    Returns the number of leading spaces on the first meaningful line.
    """
    for line in text.split("\n"):
        stripped = line.lstrip()
        if stripped and not stripped.startswith("#"):
            return len(line) - len(stripped)
    return 0


@internal
def _dedent_body(text: str) -> str:
    """Remove common leading whitespace from body text.

    Computes the base indent from the first non-blank, non-comment line
    and strips that many leading spaces from each line. This is more
    robust than ``textwrap.dedent`` for .s0ma bodies because the body
    text captured by the declaration splitter may include trailing
    comments at column 0 (e.g., comments between a body and the next
    declaration). Such comments would defeat ``textwrap.dedent``'s
    common-prefix algorithm.

    Preserves relative indentation within the body.
    """
    base_indent = _detect_base_indent(text)
    if base_indent == 0:
        return text

    lines = text.split("\n")
    result = []
    prefix = " " * base_indent
    for line in lines:
        if line.startswith(prefix):
            result.append(line[base_indent:])
        elif not line.strip():
            # Blank lines: preserve as empty
            result.append("")
        else:
            # Lines with less indent than base (e.g., comments at column 0):
            # keep as-is — they're typically trailing comments captured by
            # the declaration splitter. They're syntactically valid Python
            # (comments are harmless to ast.parse).
            result.append(line)
    return "\n".join(result)


@internal
def _classify_body(tree: ast.Module) -> tuple[BodyType, str | None]:
    """Classify the top-level construct in a parsed body AST.

    Returns (body_type, name) where name is the function or class name
    if applicable.
    """
    if not tree.body:
        return BodyType.UNKNOWN, None

    # The body may have decorators followed by a def/class.
    # Find the primary statement (skip any leading expression statements
    # that might be docstrings if present — but normally bodies are
    # just a single construct).
    first = tree.body[0]

    if isinstance(first, (ast.FunctionDef, ast.AsyncFunctionDef)):
        return BodyType.FUNCTION, first.name

    if isinstance(first, ast.ClassDef):
        return BodyType.CLASS, first.name

    if isinstance(first, (ast.Assign, ast.AnnAssign)):
        return BodyType.ASSIGNMENT, _extract_assignment_name(first)

    # Python 3.12+ type alias statement: type X = ...
    if hasattr(ast, "TypeAlias") and isinstance(first, ast.TypeAlias):
        name = first.name.id if isinstance(first.name, ast.Name) else None
        return BodyType.TYPE_ALIAS, name

    return BodyType.UNKNOWN, None


@internal
def _extract_assignment_name(node: ast.Assign | ast.AnnAssign) -> str | None:
    """Extract the target name from an assignment statement."""
    if isinstance(node, ast.AnnAssign):
        if isinstance(node.target, ast.Name):
            return node.target.id
        return None
    if isinstance(node, ast.Assign) and len(node.targets) == 1:
        target = node.targets[0]
        if isinstance(target, ast.Name):
            return target.id
    return None


@component(
    name="S0maDSL_extract_body",
    kind=ComponentKind.FUNCTION,
    layer=Layer.FRAMEWORK,
    intent=(
        "Extracts and classifies a Python body from raw text, preserving the original source "
        "exactly while producing a dedented AST for analysis."
    ),
    idempotent=True,
    is_framework=True,
)
def extract_body(
    raw_body: str,
    filename: str = "<string>",
    body_start_line: int = 1,
) -> BodyInfo:
    """Extract and classify a Python body from raw text.

    The raw body text is preserved exactly as-is (FR-07). A dedented
    version is parsed with ``ast.parse()`` for structural analysis.

    Args:
        raw_body: The raw body text captured after the ``---`` separator.
        filename: Source file path for diagnostics.
        body_start_line: Line number where the body starts in the .s0ma file.

    Returns:
        A ``BodyInfo`` with the body type, preserved text, and parsed AST.

    Raises:
        S0maParseError: If the body is not syntactically valid Python.
    """
    if not raw_body or not raw_body.strip():
        raise S0maParseError(
            code="PARSE_ERROR",
            message="Empty body after separator.",
            file=filename,
            line=body_start_line,
            column=1,
            severity="error",
            remediation="Add a Python function, class, or assignment after the --- separator.",
            context={"reason": "empty_body"},
        )

    dedented = _dedent_body(raw_body)

    # Parse with ast to validate syntax and classify
    try:
        tree = ast.parse(dedented, filename=filename, mode="exec")
    except SyntaxError as e:
        raise S0maParseError(
            code="PARSE_ERROR",
            message=f"Invalid Python syntax in body: {e.msg}",
            file=filename,
            line=body_start_line + (e.lineno - 1 if e.lineno else 0),
            column=e.offset or 1,
            severity="error",
            remediation="Fix the Python syntax in the body after the --- separator.",
            context={"syntax_error": str(e)},
        ) from e

    body_type, name = _classify_body(tree)

    return BodyInfo(
        body_type=body_type,
        source_text=raw_body,
        dedented_text=dedented,
        ast_node=tree,
        function_name=name if body_type == BodyType.FUNCTION else None,
        class_name=name if body_type == BodyType.CLASS else None,
    )


# ---------------------------------------------------------------------------
# Body validation
# ---------------------------------------------------------------------------


@component(
    name="S0maDSL_validate_body",
    kind=ComponentKind.FUNCTION,
    layer=Layer.FRAMEWORK,
    intent=(
        "Validates a .s0ma body against declaration-type constraints and prohibited construct "
        "rules, returning structured errors."
    ),
    idempotent=True,
    is_framework=True,
)
def validate_body(
    body_info: BodyInfo,
    decl_type: str,
    decl_name: str,
    kind: Kind | None,
    filename: str,
    body_start_line: int,
    mode: StrictnessMode = StrictnessMode.DEV,
) -> list[S0maParseError | S0maSemanticError]:
    """Validate a body against declaration-type constraints and prohibited constructs.

    Checks:
    - Nerve bodies must be function definitions (FR-19).
    - Cell bodies must match their kind (class for MODEL/EXCEPTION/ENUM/CONFIG,
      assignment for CONSTANT, type for TYPE).
    - Ganglion, test, and helper bodies must be function definitions.
    - Prohibited constructs: exec, eval, __import__, importlib.import_module,
      monkey-patching patterns (FR-18).
    - Bare import statements in bodies are rejected (FR-18).

    Args:
        body_info: The extracted body information.
        decl_type: The declaration type ("nerve", "cell", "ganglion", "test", "helper").
        decl_name: The declaration name for diagnostics.
        kind: The component kind (for cells, determines expected body type).
        filename: Source file path for diagnostics.
        body_start_line: Line number where the body starts in the .s0ma file.
        mode: Strictness mode for severity modulation.

    Returns:
        A list of errors/warnings. Empty list means validation passed.
    """
    errors: list[S0maParseError | S0maSemanticError] = []

    # --- Declaration-type body constraints ---
    if decl_type == "nerve":
        _validate_nerve_body(body_info, decl_name, kind, filename, body_start_line, errors)
    elif decl_type == "cell" and kind is not None:
        _validate_cell_body(body_info, decl_name, kind, filename, body_start_line, errors)
    elif decl_type in ("ganglion", "test"):
        _validate_function_body(body_info, decl_type, decl_name, filename, body_start_line, errors)
    elif decl_type == "helper":
        # POST-4a (0.15.0): helper bodies may be a function or a class.
        # The pre-POST-4a M13 contract required a function — extending to
        # classes lets M13 helpers encapsulate state without routing
        # through the registry (retires the ``cell kind: MODEL
        # visibility: INTERNAL`` workaround for module-private classes).
        _validate_helper_body(body_info, decl_name, filename, body_start_line, errors)

    # --- Prohibited constructs (FR-18) ---
    if body_info.ast_node is not None:
        _check_prohibited_constructs(
            body_info.ast_node, decl_name, filename, body_start_line, mode, errors,
        )
        _check_bare_imports(
            body_info.ast_node, decl_name, filename, body_start_line, mode, errors,
        )

    return errors


# ---------------------------------------------------------------------------
# Declaration-type body validators
# ---------------------------------------------------------------------------


_CLASS_BODY_ALLOWED_KINDS = frozenset({Kind.SERVICE, Kind.ADAPTER})


@internal
def _body_has_imports_and_def(body_info: BodyInfo) -> bool:
    """True when the body's top level mixes imports with a function def.

    This is the canonical first-time-user failure shape: normal Python
    (imports at the top, then a ``def``) pasted into a ``.s0ma`` body.
    ``_classify_body`` returns ``UNKNOWN`` for it because the first
    top-level statement is an import, so the PARSE_ERROR remediation
    uses this detector to lead with the exact fix instead of a generic
    "must be a def" restatement.
    """
    tree = body_info.ast_node
    if tree is None:
        return False
    has_import = any(
        isinstance(stmt, (ast.Import, ast.ImportFrom)) for stmt in tree.body
    )
    has_def = any(
        isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef))
        for stmt in tree.body
    )
    return has_import and has_def


@internal
def _function_body_remediation(
    decl_type: str,
    decl_name: str,
    body_info: BodyInfo,
) -> str:
    """Build the PARSE_ERROR remediation for a must-be-a-def body.

    Teaches the two rules that kill first-time users: (1) the body must
    be exactly ONE ``def``, and (2) imports never go in the body — they
    are declared in the module header's ``requires:`` list and the
    transpiler generates the import lines. When the body detectably
    contains imports plus a def (normal Python pasted in), the
    remediation leads with that state-aware diagnosis.
    """
    if _body_has_imports_and_def(body_info):
        lead = (
            f"The body contains import statements outside the def. Move each "
            f"import to the module header's `requires:` list (the transpiler "
            f"generates the import lines) and keep exactly ONE "
            f"`def {decl_name}(...)` in the body."
        )
    else:
        lead = (
            f"The body of {decl_type} '{decl_name}' must be exactly ONE "
            f"`def {decl_name}(...)` function — nothing else at the top "
            f"level. Imports never go in the body: declare them in the "
            f"module header's `requires:` list and the transpiler generates "
            f"the import lines."
        )
    return (
        f"{lead}\n"
        f"A valid {decl_type} body looks like:\n"
        f"    ---\n"
        f"    def {decl_name}(arg):\n"
        f"        result = do_work(arg)\n"
        f"        return result\n"
        f"(imports belong in the module header: requires: [json, mypkg:helper])"
    )


@internal
def _validate_nerve_body(
    body_info: BodyInfo,
    decl_name: str,
    kind: Kind | None,
    filename: str,
    body_start_line: int,
    errors: list[S0maParseError | S0maSemanticError],
) -> None:
    """Validate nerve body type against its kind.

    SERVICE and ADAPTER nerves may use either function or class bodies.
    All other nerve kinds require function bodies (FR-19).
    """
    if body_info.body_type == BodyType.CLASS:
        if kind not in _CLASS_BODY_ALLOWED_KINDS:
            errors.append(S0maSemanticError(
                code="CLASS_BODY_IN_NERVE",
                message=(
                    f"Nerve '{decl_name}' has a class body, but only SERVICE and "
                    f"ADAPTER nerves may use class bodies."
                ),
                file=filename,
                line=body_start_line,
                column=1,
                severity="error",
                remediation=(
                    f"Replace the class definition in nerve '{decl_name}' with a "
                    f"'def' function, or change the nerve's kind to SERVICE or ADAPTER."
                ),
                context={
                    "declaration": decl_name,
                    "found": "class",
                    "expected": "def",
                    "kind": kind.value if kind else None,
                    "class_allowed_kinds": sorted(k.value for k in _CLASS_BODY_ALLOWED_KINDS),
                },
            ))
    elif body_info.body_type not in (BodyType.FUNCTION,):
        errors.append(S0maParseError(
            code="PARSE_ERROR",
            message=(
                f"Nerve '{decl_name}' body must be a function definition (def), "
                f"found {body_info.body_type.value}."
            ),
            file=filename,
            line=body_start_line,
            column=1,
            severity="error",
            remediation=_function_body_remediation("nerve", decl_name, body_info),
            context={
                "declaration": decl_name,
                "found": body_info.body_type.value,
                "expected": "function",
                "imports_in_body": _body_has_imports_and_def(body_info),
            },
        ))


@internal
def _validate_cell_body(
    body_info: BodyInfo,
    decl_name: str,
    kind: Kind,
    filename: str,
    body_start_line: int,
    errors: list[S0maParseError | S0maSemanticError],
) -> None:
    """Validate that a cell body matches its kind."""
    # Kinds that expect class definitions
    class_kinds = {Kind.MODEL, Kind.EXCEPTION, Kind.ENUM, Kind.CONFIG}
    # Kinds that expect assignments
    assignment_kinds = {Kind.CONSTANT}
    # Kinds that expect type aliases
    type_kinds = {Kind.TYPE}

    if kind in class_kinds and body_info.body_type != BodyType.CLASS:
        errors.append(S0maParseError(
            code="PARSE_ERROR",
            message=(
                f"Cell '{decl_name}' of kind {kind.value} expects a class definition, "
                f"found {body_info.body_type.value}."
            ),
            file=filename,
            line=body_start_line,
            column=1,
            severity="error",
            remediation=(
                f"The body of cell '{decl_name}' (kind: {kind.value}) must be a class definition. "
                f"Use 'class {decl_name}:' in the body."
            ),
            context={
                "declaration": decl_name,
                "kind": kind.value,
                "found": body_info.body_type.value,
            },
        ))
    elif kind in assignment_kinds and body_info.body_type not in (BodyType.ASSIGNMENT,):
        errors.append(S0maParseError(
            code="PARSE_ERROR",
            message=(
                f"Cell '{decl_name}' of kind CONSTANT expects an assignment, "
                f"found {body_info.body_type.value}."
            ),
            file=filename,
            line=body_start_line,
            column=1,
            severity="error",
            remediation=(
                f"The body of cell '{decl_name}' (kind: CONSTANT) must be a bare assignment. "
                f"Use '{decl_name}: type = value' or '{decl_name} = value'."
            ),
            context={
                "declaration": decl_name,
                "kind": "CONSTANT",
                "found": body_info.body_type.value,
            },
        ))
    elif kind in type_kinds and body_info.body_type not in (
        BodyType.TYPE_ALIAS, BodyType.ASSIGNMENT,
    ):
        # TYPE cells can be either type alias statements (Python 3.12+) or
        # assignment-style type aliases (TypeAlias = ...)
        errors.append(S0maParseError(
            code="PARSE_ERROR",
            message=(
                f"Cell '{decl_name}' of kind TYPE expects a type alias, "
                f"found {body_info.body_type.value}."
            ),
            file=filename,
            line=body_start_line,
            column=1,
            severity="error",
            remediation=(
                f"The body of cell '{decl_name}' (kind: TYPE) must be a type alias. "
                f"Use '{decl_name} = SomeType' or 'type {decl_name} = SomeType' (Python 3.12+)."
            ),
            context={
                "declaration": decl_name,
                "kind": "TYPE",
                "found": body_info.body_type.value,
            },
        ))


@internal
def _validate_function_body(
    body_info: BodyInfo,
    decl_type: str,
    decl_name: str,
    filename: str,
    body_start_line: int,
    errors: list[S0maParseError | S0maSemanticError],
) -> None:
    """Validate that a ganglion or test body is a function definition."""
    if body_info.body_type != BodyType.FUNCTION:
        errors.append(S0maParseError(
            code="PARSE_ERROR",
            message=(
                f"{decl_type.capitalize()} '{decl_name}' body must be a function definition, "
                f"found {body_info.body_type.value}."
            ),
            file=filename,
            line=body_start_line,
            column=1,
            severity="error",
            remediation=_function_body_remediation(decl_type, decl_name, body_info),
            context={
                "declaration": decl_name,
                "found": body_info.body_type.value,
                "expected": "function",
                "imports_in_body": _body_has_imports_and_def(body_info),
            },
        ))


@internal
def _validate_helper_body(
    body_info: BodyInfo,
    decl_name: str,
    filename: str,
    body_start_line: int,
    errors: list[S0maParseError | S0maSemanticError],
) -> None:
    """Validate that a helper body is a function OR class definition (POST-4a).

    POST-4a (0.15.0): helper bodies may be either ``def`` or ``class``.
    Function bodies remain the dominant shape (the M13 motivating
    examples are formatters / parsers); class bodies retire the
    legacy ``cell kind: MODEL visibility: INTERNAL`` workaround that
    routed module-private classes through the registry.

    Other body shapes (``assignment``, ``type_alias``, ``unknown``) are
    rejected — a helper still must declare something Python-callable
    or instantiable, not a bare value.
    """
    if body_info.body_type not in (BodyType.FUNCTION, BodyType.CLASS):
        errors.append(S0maParseError(
            code="PARSE_ERROR",
            message=(
                f"Helper '{decl_name}' body must be a function or class "
                f"definition, found {body_info.body_type.value}."
            ),
            file=filename,
            line=body_start_line,
            column=1,
            severity="error",
            remediation=(
                f"Wrap the body of helper '{decl_name}' in a "
                f"'def {decl_name}(...)' function or a 'class "
                f"{decl_name}:' definition."
            ),
            context={
                "declaration": decl_name,
                "found": body_info.body_type.value,
                "expected": "function or class",
            },
        ))


# ---------------------------------------------------------------------------
# Prohibited construct detection (FR-18, spec §4.7.5)
# ---------------------------------------------------------------------------


class _ProhibitedConstructVisitor(ast.NodeVisitor):
    """AST visitor that detects prohibited runtime escape hatches."""

    def __init__(self) -> None:
        self.findings: list[tuple[int, str, str]] = []  # (line, construct, description)

    def visit_Call(self, node: ast.Call) -> None:
        # Check for exec(), eval(), __import__()
        if isinstance(node.func, ast.Name) and node.func.id in _PROHIBITED_NAMES:
            self.findings.append((
                node.lineno,
                node.func.id,
                f"Direct call to '{node.func.id}()' is prohibited in .s0ma bodies.",
            ))

        # Check for importlib.import_module()
        if isinstance(node.func, ast.Attribute) and (
            isinstance(node.func.value, ast.Name)
            and (node.func.value.id, node.func.attr) in _PROHIBITED_ATTR_PATTERNS
        ):
            construct = f"{node.func.value.id}.{node.func.attr}"
            self.findings.append((
                node.lineno,
                construct,
                f"Call to '{construct}()' is prohibited in .s0ma bodies.",
            ))

        # Check for monkey-patching: setattr(obj, name, value) where name is a string
        if isinstance(node.func, ast.Name) and node.func.id == "setattr":
            self.findings.append((
                node.lineno,
                "setattr",
                "Call to 'setattr()' is a potential monkey-patching pattern and is prohibited.",
            ))

        self.generic_visit(node)

    def visit_Attribute(self, node: ast.Attribute) -> None:
        # Check for obj.__dict__ assignment patterns (monkey-patching)
        if node.attr == "__dict__":
            # Only flag if it's being used in an assignment context
            # (the parent will be ast.Assign or ast.AugAssign etc.)
            # We'll be conservative and not flag reads, only detect the
            # more dangerous setattr pattern above.
            pass
        self.generic_visit(node)


@component(
    name="S0maDSL_validate_example_body",
    kind=ComponentKind.FUNCTION,
    layer=Layer.FRAMEWORK,
    intent=(
        "Validates an example declaration's python body — rejects exec/eval/__import__ but "
        "permits free-form structure and bare imports."
    ),
    idempotent=True,
    is_framework=True,
)
def validate_example_body(
    body_info: BodyInfo,
    decl_name: str,
    filename: str,
    body_start_line: int,
    mode: StrictnessMode = StrictnessMode.DEV,
) -> list[S0maParseError | S0maSemanticError]:
    """Validate an ``example`` declaration body.

    Example bodies are demonstrations, not first-class components. Unlike
    nerve/cell/ganglion/test bodies they are not constrained to a single
    top-level construct, and they are permitted to contain bare ``import``
    statements (an example may legitimately need to demonstrate imports).

    Only the runtime escape-hatch check is run: ``exec``, ``eval``,
    ``__import__``, ``importlib.import_module``, and ``setattr``-style
    monkey patching remain prohibited.

    Args:
        body_info: The extracted body information.
        decl_name: The example name for diagnostics.
        filename: Source file path for diagnostics.
        body_start_line: Line number where the body starts in the .s0ma file.
        mode: Strictness mode for severity modulation.

    Returns:
        A list of errors/warnings. Empty list means validation passed.
    """
    errors: list[S0maParseError | S0maSemanticError] = []
    if body_info.ast_node is not None:
        _check_prohibited_constructs(
            body_info.ast_node, decl_name, filename, body_start_line, mode, errors,
        )
    return errors


@internal
def _check_prohibited_constructs(
    tree: ast.Module,
    decl_name: str,
    filename: str,
    body_start_line: int,
    mode: StrictnessMode,
    errors: list[S0maParseError | S0maSemanticError],
) -> None:
    """Check for prohibited runtime escape hatches in the body AST."""
    severity = get_severity("PROHIBITED_CONSTRUCT", mode)
    if severity is None:
        return

    visitor = _ProhibitedConstructVisitor()
    visitor.visit(tree)

    for rel_line, construct, description in visitor.findings:
        abs_line = body_start_line + rel_line - 1
        errors.append(S0maSemanticError(
            code="PROHIBITED_CONSTRUCT",
            message=f"Prohibited construct '{construct}' in '{decl_name}': {description}",
            file=filename,
            line=abs_line,
            column=1,
            severity=severity,
            remediation=(
                f"Remove the use of '{construct}' from '{decl_name}'. "
                "All dependencies must be declared in the module's 'requires' or 'uses' fields. "
                "Dynamic imports, eval, and monkey-patching bypass the self-model."
            ),
            context={"declaration": decl_name, "construct": construct},
        ))


@internal
def _check_bare_imports(
    tree: ast.Module,
    decl_name: str,
    filename: str,
    body_start_line: int,
    mode: StrictnessMode,
    errors: list[S0maParseError | S0maSemanticError],
) -> None:
    """Check for bare import statements in the body AST."""
    severity = get_severity("BARE_IMPORT", mode)
    if severity is None:
        return

    for node in ast.walk(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            abs_line = body_start_line + node.lineno - 1
            if isinstance(node, ast.Import):
                names = ", ".join(alias.name for alias in node.names)
                stmt = f"import {names}"
            else:
                names = ", ".join(alias.name for alias in node.names)
                stmt = f"from {node.module} import {names}" if node.module else f"import {names}"

            errors.append(S0maSemanticError(
                code="BARE_IMPORT",
                message=f"Bare import statement in '{decl_name}': '{stmt}'.",
                file=filename,
                line=abs_line,
                column=1,
                severity=severity,
                remediation=(
                    f"Fix in ONE edit, two parts: (1) declare the dependency in the "
                    f"module header — `requires:` for Python imports (or "
                    f"`deferred_requires:` to defer the import to call time with "
                    f"per-call failure semantics; `uses:` for s0ma component "
                    f"references), AND (2) delete the `{stmt}` line from the body of "
                    f"'{decl_name}'. The transpiler generates the import lines from "
                    f"the declarations — a bare import in the body is always an "
                    f"error even after the header declares it."
                ),
                context={"declaration": decl_name, "import_statement": stmt},
            ))
