"""Static, non-authoritative inspection for roster-adopted Python.

The canonical self-model is built from ``.s0ma`` and serialized as
``s0ma-ir@3``.  This module deliberately does something smaller: it parses a
roster-adopted Python file with :mod:`ast` and returns the separately named
``s0ma-derived-surface@1`` document.  It never imports the target and nothing
in check, score, verify, build, or the registry consumes its cache.
"""

from __future__ import annotations

import ast
import json
import os
import tempfile
import tomllib
from pathlib import Path
from typing import Any

from s0ma_dsl import __version__
from s0ma_dsl.codegen.build_manifest import compute_file_hash

DERIVED_SURFACE_SCHEMA = "s0ma-derived-surface@1"
DERIVATION_VERSION = "1"
DERIVED_CACHE_DIR = Path(".s0ma.cache") / "derived-surfaces"


class DerivedSurfaceError(ValueError):
    """The adopted Python source cannot be inspected safely or statically."""


def _contained(root: Path, candidate: Path) -> bool:
    try:
        return candidate.resolve().is_relative_to(root.resolve())
    except OSError:
        return False


def _project_config_hash(root: Path) -> str:
    """Hash the normalized ``[tool.s0ma]`` table and no runtime state.

    The whole tool table is conservative but stable: any project setting that
    might later affect module identity invalidates the draft.  Cache contents,
    build output, environment values, and adoption telemetry are excluded.
    """
    try:
        with (root / "pyproject.toml").open("rb") as handle:
            document = tomllib.load(handle)
    except (OSError, tomllib.TOMLDecodeError) as exc:
        raise DerivedSurfaceError(
            f"cannot read project configuration at {root / 'pyproject.toml'}: {exc}"
        ) from exc
    table = document.get("tool", {}).get("s0ma")
    if not isinstance(table, dict):
        raise DerivedSurfaceError(
            f"no [tool.s0ma] table found at {root / 'pyproject.toml'}"
        )
    canonical = json.dumps(
        table,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
        default=str,
    )
    return compute_file_hash(canonical)


def _module_name(path: Path) -> str:
    return path.parent.name if path.name == "__init__.py" else path.stem


def _literal_all(tree: ast.Module) -> list[str] | None:
    for statement in tree.body:
        if not isinstance(statement, (ast.Assign, ast.AnnAssign)):
            continue
        targets = statement.targets if isinstance(statement, ast.Assign) else [statement.target]
        if not any(isinstance(target, ast.Name) and target.id == "__all__" for target in targets):
            continue
        value = statement.value
        if not isinstance(value, (ast.List, ast.Tuple)):
            return None
        exports: list[str] = []
        for item in value.elts:
            if not isinstance(item, ast.Constant) or not isinstance(item.value, str):
                return None
            exports.append(item.value)
        return sorted(dict.fromkeys(exports))
    return None


def _static_exports(tree: ast.Module) -> list[str]:
    explicit = _literal_all(tree)
    if explicit is not None:
        return explicit
    names: set[str] = set()
    for statement in tree.body:
        if isinstance(statement, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            names.add(statement.name)
        elif isinstance(statement, ast.Assign):
            for target in statement.targets:
                if isinstance(target, ast.Name):
                    names.add(target.id)
        elif isinstance(statement, ast.AnnAssign) and isinstance(statement.target, ast.Name):
            names.add(statement.target.id)
    return sorted(name for name in names if not name.startswith("_"))


def _static_imports(tree: ast.Module) -> list[str]:
    imports: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            prefix = "." * node.level
            imports.add(prefix + (node.module or ""))
    return sorted(name for name in imports if name)


def _cache_path(root: Path, key_document: dict[str, str]) -> Path:
    key_bytes = json.dumps(
        key_document, ensure_ascii=False, separators=(",", ":"), sort_keys=True
    )
    digest = compute_file_hash(key_bytes).removeprefix("sha256:")
    cache_dir = (root / DERIVED_CACHE_DIR).resolve()
    if not cache_dir.is_relative_to(root.resolve()):
        raise DerivedSurfaceError(
            f"derived-surface cache path escapes the project root: {cache_dir}"
        )
    return cache_dir / f"{digest}.json"


def derive_python_surface(project_root: Path, source: Path) -> dict[str, Any]:
    """Return a deterministic static draft for one adopted Python file.

    Cache identity binds the source, project configuration, schema,
    derivation algorithm, and running DSL version.  The cached document is
    revalidated against those fields before use; it is an acceleration
    artifact only and is never accepted as canonical evidence.
    """
    root = project_root.resolve()
    resolved = source.resolve()
    if not _contained(root, resolved):
        raise DerivedSurfaceError(f"adopted Python path escapes project root: {source}")
    if resolved.suffix != ".py" or not resolved.is_file():
        raise DerivedSurfaceError(f"derived inspection requires a Python file: {source}")

    try:
        text = resolved.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        raise DerivedSurfaceError(f"cannot read adopted Python source {source}: {exc}") from exc
    source_identity = resolved.relative_to(root).as_posix()
    source_hash = compute_file_hash(text)
    config_hash = _project_config_hash(root)
    key_document = {
        "schema": DERIVED_SURFACE_SCHEMA,
        "derivation_version": DERIVATION_VERSION,
        "tool_version": __version__,
        "source": source_identity,
        "source_hash": source_hash,
        "config_hash": config_hash,
    }
    cache_path = _cache_path(root, key_document)
    if cache_path.is_file():
        try:
            cached = json.loads(cache_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            cached = None
        if isinstance(cached, dict) and all(
            cached.get(field) == value for field, value in key_document.items()
        ):
            return cached

    try:
        tree = ast.parse(text, filename=str(resolved), mode="exec")
    except SyntaxError as exc:
        raise DerivedSurfaceError(
            f"cannot derive a static surface from invalid Python {source}: {exc.msg} "
            f"at line {exc.lineno}"
        ) from exc

    docstring = ast.get_docstring(tree, clean=False) or ""
    draft = next((line.strip() for line in docstring.splitlines() if line.strip()), "")
    surface: dict[str, Any] = {
        "schema": DERIVED_SURFACE_SCHEMA,
        "authority": "derived",
        "mapped": False,
        "module": _module_name(resolved),
        "source": source_identity,
        "source_hash": source_hash,
        "config_hash": config_hash,
        "derivation_version": DERIVATION_VERSION,
        "tool_version": __version__,
        "provenance": {
            "method": "static_python_ast",
            "imports_executed": False,
        },
        "summary": {
            "state": "pending",
            "reason": "machine-derived draft requires author review",
            "draft": draft,
        },
        "exports": _static_exports(tree),
        "imports": _static_imports(tree),
        "confidence": "syntax_only",
        "limitations": ["unverified", "does not satisfy score or gate"],
    }

    cache_path.parent.mkdir(parents=True, exist_ok=True)
    if not _contained(root, cache_path.parent):
        raise DerivedSurfaceError(
            f"derived-surface cache path escapes the project root: {cache_path.parent}"
        )
    payload = json.dumps(surface, indent=2, sort_keys=True) + "\n"
    temp_name: str | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            newline="\n",
            dir=cache_path.parent,
            prefix=f".{cache_path.stem}.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            handle.write(payload)
            temp_name = handle.name
        os.replace(temp_name, cache_path)
    finally:
        if temp_name is not None:
            Path(temp_name).unlink(missing_ok=True)
    return surface


__all__ = [
    "DERIVATION_VERSION",
    "DERIVED_CACHE_DIR",
    "DERIVED_SURFACE_SCHEMA",
    "DerivedSurfaceError",
    "derive_python_surface",
]
