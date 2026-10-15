"""Consumer-pinned adoption exceptions for reproducible gate evaluation.

Project-local ``[tool.s0ma].adoption_exempt`` entries classify and report
files during authoring.  They never waive debt.  A caller may explicitly
provide a ``s0ma-adoption-policy@1`` JSON document to ``score`` (and the MCP
``check`` bridge); only that document can remove matched Python paths from a
pinned gate denominator.  Canonical bytes and a reported SHA-256 make the
external policy itself pinnable evidence.
"""

from __future__ import annotations

import fnmatch
import hashlib
import json
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING

from s0ma_dsl.discovery import iter_visible_files

if TYPE_CHECKING:
    from collections.abc import Sequence

    from s0ma_dsl.project import S0maProject

ADOPTION_POLICY_SCHEMA = "s0ma-adoption-policy@1"
ADOPTION_CATEGORIES = frozenset({"vendored", "generated", "data", "bootstrap"})


class AdoptionPolicyError(ValueError):
    """A policy/config exception is malformed or unsafe."""


@dataclass(frozen=True, order=True)
class AdoptionException:
    """One narrowly-scoped adoption exception."""

    path_glob: str
    category: str
    reason: str

    def to_dict(self) -> dict[str, str]:
        return {
            "path_glob": self.path_glob,
            "category": self.category,
            "reason": self.reason,
        }


@dataclass(frozen=True)
class ResolvedAdoptionPolicy:
    """Validated policy plus canonical hash and complete path inventory."""

    exceptions: tuple[AdoptionException, ...]
    sha256: str
    matched_paths: tuple[dict[str, str], ...]

    @property
    def waived_paths(self) -> frozenset[str]:
        return frozenset(item["path"] for item in self.matched_paths)

    def to_dict(self) -> dict[str, object]:
        return {
            "schema": ADOPTION_POLICY_SCHEMA,
            "sha256": self.sha256,
            "matched_count": len(self.matched_paths),
            "matched_paths": [dict(item) for item in self.matched_paths],
        }


def parse_exceptions(
    raw: object,
    *,
    source: str,
) -> tuple[AdoptionException, ...]:
    """Validate an exception list without matching it to a project yet."""
    if not isinstance(raw, list):
        raise AdoptionPolicyError(f"{source} must be a list of exception objects.")
    parsed: list[AdoptionException] = []
    for index, item in enumerate(raw):
        label = f"{source}[{index}]"
        if not isinstance(item, dict):
            raise AdoptionPolicyError(f"{label} must be an object.")
        unknown = sorted(set(item) - {"path_glob", "category", "reason"})
        if unknown:
            raise AdoptionPolicyError(
                f"{label} has unknown key(s): {', '.join(unknown)}."
            )
        path_glob = item.get("path_glob")
        category = item.get("category")
        reason = item.get("reason")
        if not isinstance(path_glob, str) or not path_glob.strip():
            raise AdoptionPolicyError(f"{label}.path_glob must be non-empty.")
        normalized = path_glob.strip().replace("\\", "/")
        _validate_glob(normalized, label=label)
        if not isinstance(category, str) or category not in ADOPTION_CATEGORIES:
            allowed = ", ".join(sorted(ADOPTION_CATEGORIES))
            raise AdoptionPolicyError(
                f"{label}.category must be one of: {allowed}."
            )
        if not isinstance(reason, str) or not reason.strip():
            raise AdoptionPolicyError(f"{label}.reason must be non-empty.")
        parsed.append(AdoptionException(
            path_glob=normalized,
            category=category,
            reason=reason.strip(),
        ))
    return tuple(sorted(parsed))


def _validate_glob(path_glob: str, *, label: str) -> None:
    """Reject escaping and catch-all shapes while allowing scoped ``dir/**``."""
    pure = PurePosixPath(path_glob)
    if pure.is_absolute() or ".." in pure.parts:
        raise AdoptionPolicyError(
            f"{label}.path_glob must stay project-relative and cannot escape root."
        )
    if path_glob.startswith("./"):
        raise AdoptionPolicyError(
            f"{label}.path_glob must use normalized project-relative POSIX form."
        )
    root_wide = {"*", "**", "**/*", "*/**", "*/**/*"}
    if path_glob in root_wide:
        raise AdoptionPolicyError(
            f"{label}.path_glob={path_glob!r} is a catch-all/root-wide pattern; "
            "name an owned subtree such as vendor/acme/**."
        )
    first = pure.parts[0] if pure.parts else ""
    if any(char in first for char in "*?["):
        raise AdoptionPolicyError(
            f"{label}.path_glob must begin with a concrete project directory, "
            "not a wildcard root."
        )


def canonical_policy_bytes(exceptions: Sequence[AdoptionException]) -> bytes:
    """Canonical UTF-8/LF bytes whose SHA-256 is reported to callers."""
    payload = {
        "schema": ADOPTION_POLICY_SCHEMA,
        "exceptions": [item.to_dict() for item in sorted(exceptions)],
    }
    return (
        json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n"
    ).encode("utf-8")


def policy_sha256(exceptions: Sequence[AdoptionException]) -> str:
    """Return the normalized policy digest using the repository convention."""
    return f"sha256:{hashlib.sha256(canonical_policy_bytes(exceptions)).hexdigest()}"


def load_policy(path: Path) -> tuple[AdoptionException, ...]:
    """Load and validate one explicit ``s0ma-adoption-policy@1`` document."""
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise AdoptionPolicyError(f"cannot read adoption policy {path}: {exc}") from exc
    if not isinstance(raw, dict):
        raise AdoptionPolicyError("adoption policy must be a JSON object.")
    if raw.get("schema") != ADOPTION_POLICY_SCHEMA:
        raise AdoptionPolicyError(
            f"adoption policy schema must be {ADOPTION_POLICY_SCHEMA!r}; "
            f"got {raw.get('schema')!r}."
        )
    unknown = sorted(set(raw) - {"schema", "exceptions"})
    if unknown:
        raise AdoptionPolicyError(
            f"adoption policy has unknown key(s): {', '.join(unknown)}."
        )
    return parse_exceptions(raw.get("exceptions"), source="adoption policy exceptions")


def _project_paths(project: S0maProject) -> tuple[str, ...]:
    """Enumerate every regular project path deterministically for reporting.

    The former local exclusion set named ``.git`` / ``.s0ma`` / ``.venv``
    / ``.s0ma.cache`` / ``__pycache__``; :func:`iter_visible_files`
    subsumes it structurally, which also drops a nested checkout of the
    same project (``.claude/worktrees/<name>/``) that would otherwise
    report every file in the tree a second time as unmodeled debt.
    """
    paths: list[str] = []
    for path in iter_visible_files(project.root):
        try:
            relative = path.resolve().relative_to(project.root.resolve())
        except (OSError, ValueError):
            continue
        paths.append(relative.as_posix())
    return tuple(sorted(set(paths)))


def _modeled_paths(project: S0maProject) -> frozenset[str]:
    """Return authored and generated paths owned by the canonical model."""
    modeled: set[str] = set()
    for root in (*project.source_roots, *project.test_roots):
        if not root.is_dir():
            continue
        for path in iter_visible_files(root, "*.s0ma"):
            try:
                modeled.add(path.resolve().relative_to(project.root.resolve()).as_posix())
            except (OSError, ValueError):
                continue
    for path in iter_visible_files(project.build_dir, "*.py"):
        try:
            content = path.read_text(encoding="utf-8")
            relative = path.resolve().relative_to(project.root.resolve()).as_posix()
        except (OSError, UnicodeDecodeError, ValueError):
            continue
        if "# s0ma-source-hash:" in content and "# s0ma-output-hash:" in content:
            modeled.add(relative)
    return frozenset(modeled)


def _configured_project_roots(
    project: S0maProject,
) -> tuple[tuple[str, tuple[str, ...]], ...]:
    """Return project-relative source/test/build roots for breadth checks."""
    try:
        project_root = project.root.resolve()
    except OSError:
        project_root = project.root
    configured: set[tuple[str, tuple[str, ...]]] = set()
    for kind, roots in (
        ("source root", project.source_roots),
        ("test root", project.test_roots),
        ("build dir", (project.build_dir,)),
    ):
        for root in roots:
            try:
                relative = root.resolve().relative_to(project_root)
            except (OSError, ValueError):
                # Policy globs are project-relative and cannot match a configured
                # root outside the project, so there is no boundary to compare.
                continue
            configured.add((kind, PurePosixPath(relative.as_posix()).parts))
    return tuple(sorted(configured))


def _reject_configured_root_wide_glob(
    project: S0maProject,
    path_glob: str,
) -> None:
    """Refuse a wildcard that begins at a configured root's first child.

    Modeled-source matching is not sufficient here: a brownfield project may
    contain only plain Python, so ``src/**`` would otherwise waive the whole
    source boundary before a canonical ``.s0ma`` file exists.
    """
    parts = PurePosixPath(path_glob).parts
    first_wildcard = next(
        (index for index, part in enumerate(parts) if any(c in part for c in "*?[")),
        None,
    )
    if first_wildcard is None:
        return
    for kind, root_parts in _configured_project_roots(project):
        if (
            first_wildcard == len(root_parts)
            and parts[:first_wildcard] == root_parts
        ):
            rendered_root = PurePosixPath(*root_parts).as_posix() or "."
            raise AdoptionPolicyError(
                f"adoption exception {path_glob!r} is root-wide for configured "
                f"{kind} {rendered_root!r}; name a concrete owned subtree such "
                "as src/vendor/acme/** or vendor/acme/**."
            )


def resolve_exceptions(
    project: S0maProject,
    exceptions: Sequence[AdoptionException],
    *,
    include_hash: bool,
) -> ResolvedAdoptionPolicy:
    """Match exceptions, refusing broad roots and modeled-source patterns."""
    project_paths = _project_paths(project)
    modeled_paths = _modeled_paths(project)
    inventory: list[dict[str, str]] = []
    for exception in sorted(exceptions):
        _reject_configured_root_wide_glob(project, exception.path_glob)
        modeled_matches = sorted(
            path for path in modeled_paths
            if fnmatch.fnmatchcase(path, exception.path_glob)
        )
        if modeled_matches:
            raise AdoptionPolicyError(
                f"adoption exception {exception.path_glob!r} matches modeled "
                f"source/artifacts ({', '.join(modeled_matches)}); modeled code "
                "cannot be exempted from its own gate."
            )
        for path in project_paths:
            if fnmatch.fnmatchcase(path, exception.path_glob):
                inventory.append({
                    "path": path,
                    "path_glob": exception.path_glob,
                    "category": exception.category,
                    "reason": exception.reason,
                })
    inventory.sort(key=lambda item: (
        item["path"], item["path_glob"], item["category"], item["reason"],
    ))
    digest = policy_sha256(exceptions) if include_hash else ""
    return ResolvedAdoptionPolicy(
        exceptions=tuple(sorted(exceptions)),
        sha256=digest,
        matched_paths=tuple(inventory),
    )


def load_and_resolve_policy(
    project: S0maProject,
    path: Path,
    *,
    expected_sha256: str | None = None,
) -> ResolvedAdoptionPolicy:
    """Load an explicit caller policy, verify its optional pin, then match."""
    exceptions = load_policy(path)
    digest = policy_sha256(exceptions)
    if expected_sha256 is not None and expected_sha256 != digest:
        raise AdoptionPolicyError(
            f"adoption policy hash mismatch: expected {expected_sha256}, got {digest}."
        )
    return resolve_exceptions(project, exceptions, include_hash=True)


def resolve_project_exemptions(project: S0maProject) -> ResolvedAdoptionPolicy:
    """Resolve project-local classification entries; never produce a gate hash."""
    return resolve_exceptions(project, project.adoption_exempt, include_hash=False)
