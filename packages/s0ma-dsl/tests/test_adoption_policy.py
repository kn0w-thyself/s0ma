"""0.14 M4 consumer-pinned adoption exception policy trajectories."""

from __future__ import annotations

import json
from dataclasses import replace
from typing import TYPE_CHECKING, Any

import pytest

if TYPE_CHECKING:
    from pathlib import Path

from s0ma_dsl.adoption_policy import (
    ADOPTION_POLICY_SCHEMA,
    AdoptionPolicyError,
    load_and_resolve_policy,
    parse_exceptions,
    policy_sha256,
    resolve_exceptions,
    resolve_project_exemptions,
)
from s0ma_dsl.cli.main import EXIT_SUCCESS, EXIT_USAGE_ERROR, S0maCLI
from s0ma_dsl.project import S0maProject


@pytest.fixture()
def policy_project(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> Path:
    root = tmp_path / "policy_project"
    cli = S0maCLI()
    assert cli.run(["new", "project", str(root), "--quiet"]) == EXIT_SUCCESS
    assert cli.run([
        "--project-root", str(root),
        "build", str(root / "src"), "--mode", "migration", "--quiet",
    ]) == EXIT_SUCCESS
    vendor = root / "src" / "vendor" / "acme"
    vendor.mkdir(parents=True)
    (vendor / "legacy.py").write_text("VALUE = 1\n", encoding="utf-8")
    capsys.readouterr()
    return root


@pytest.fixture()
def pure_legacy_project(tmp_path: Path) -> S0maProject:
    """A brownfield project with no modeled source to protect the boundary."""
    root = tmp_path / "pure_legacy"
    for directory in (
        root / "src" / "vendor" / "acme",
        root / "vendor" / "acme",
        root / "tests",
        root / "legacy_build",
    ):
        directory.mkdir(parents=True, exist_ok=True)
    (root / "src" / "legacy.py").write_text("VALUE = 1\n", encoding="utf-8")
    (root / "src" / "vendor" / "acme" / "upstream.py").write_text(
        "VALUE = 2\n", encoding="utf-8"
    )
    (root / "vendor" / "acme" / "upstream.py").write_text(
        "VALUE = 3\n", encoding="utf-8"
    )
    (root / "pyproject.toml").write_text(
        """[project]
name = "pure-legacy"
version = "0.1.0"

[tool.s0ma]
source_roots = ["src"]
test_roots = ["tests"]
build_dir = "legacy_build"
""",
        encoding="utf-8",
    )
    return S0maProject.discover(root)


def _score(
    root: Path,
    capsys: pytest.CaptureFixture[str],
    *extra: str,
) -> tuple[int, dict[str, Any] | None, str]:
    capsys.readouterr()
    rc = S0maCLI().run([
        "--project-root", str(root), "score", "--format", "json", *extra,
    ])
    captured = capsys.readouterr()
    return (
        rc,
        json.loads(captured.out) if captured.out.strip() else None,
        captured.err,
    )


def test_frozen_scoped_glob_allowed_but_root_catchalls_refused() -> None:
    entries = parse_exceptions([{
        "path_glob": "vendor/acme/**",
        "category": "vendored",
        "reason": "upstream-owned source",
    }], source="test")
    assert entries[0].path_glob == "vendor/acme/**"
    for catchall in ("*", "**", "**/*", "*/**"):
        with pytest.raises(AdoptionPolicyError, match="catch-all|wildcard root"):
            parse_exceptions([{
                "path_glob": catchall,
                "category": "vendored",
                "reason": "too broad",
            }], source="test")


@pytest.mark.parametrize(
    "path_glob",
    (
        "src/**",
        "src/*",
        "src/**/*",
        "src/*/**",
        "tests/**",
        "legacy_build/**",
    ),
)
def test_configured_root_wide_globs_refused_without_modeled_source(
    pure_legacy_project: S0maProject,
    tmp_path: Path,
    path_glob: str,
) -> None:
    """Neither caller nor project policy may waive a whole configured root."""
    raw_exception = {
        "path_glob": path_glob,
        "category": "vendored",
        "reason": "too broad for a configured project boundary",
    }
    caller_policy = tmp_path / "root-wide-policy.json"
    caller_policy.write_text(json.dumps({
        "schema": ADOPTION_POLICY_SCHEMA,
        "exceptions": [raw_exception],
    }), encoding="utf-8")
    with pytest.raises(
        AdoptionPolicyError,
        match="root-wide for configured (source root|test root|build dir)",
    ):
        load_and_resolve_policy(pure_legacy_project, caller_policy)

    local_entries = parse_exceptions([raw_exception], source="project adoption_exempt")
    local_project = replace(pure_legacy_project, adoption_exempt=local_entries)
    with pytest.raises(
        AdoptionPolicyError,
        match="root-wide for configured (source root|test root|build dir)",
    ):
        resolve_project_exemptions(local_project)


@pytest.mark.parametrize(
    ("path_glob", "expected_path"),
    (
        ("src/vendor/acme/**", "src/vendor/acme/upstream.py"),
        ("vendor/acme/**", "vendor/acme/upstream.py"),
    ),
)
def test_scoped_vendor_subtrees_remain_valid(
    pure_legacy_project: S0maProject,
    path_glob: str,
    expected_path: str,
) -> None:
    entries = parse_exceptions([{
        "path_glob": path_glob,
        "category": "vendored",
        "reason": "upstream-owned subtree",
    }], source="test")
    resolved = resolve_exceptions(
        pure_legacy_project,
        entries,
        include_hash=True,
    )
    assert [item["path"] for item in resolved.matched_paths] == [expected_path]


def test_project_local_exception_classifies_but_never_waives(
    policy_project: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    pyproject = policy_project / "pyproject.toml"
    pyproject.write_text(
        pyproject.read_text(encoding="utf-8")
        + '\nadoption_exempt = [{path_glob = "src/vendor/acme/**", '
        'category = "vendored", reason = "upstream-owned source"}]\n',
        encoding="utf-8",
    )
    rc, report, _ = _score(policy_project, capsys, "--gate-mode", "release")
    assert rc == EXIT_SUCCESS
    assert report is not None
    registration = report["faculties"]["proprioception"]["metrics"]["registration"]
    assert registration["unknown"] == 1
    local = registration["project_adoption_exempt"]
    assert local["waives_gate"] is False
    assert [item["path"] for item in local["matched_paths"]] == [
        "src/vendor/acme/legacy.py"
    ]


def test_project_local_catchall_is_refused_not_used_as_waiver(
    policy_project: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    pyproject = policy_project / "pyproject.toml"
    pyproject.write_text(
        pyproject.read_text(encoding="utf-8")
        + '\nadoption_exempt = [{path_glob = "**", category = "vendored", '
        'reason = "everything"}]\n',
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="catch-all"):
        _score(policy_project, capsys, "--gate-mode", "release")


def test_caller_policy_is_hashed_enumerated_and_waives_only_matched_debt(
    policy_project: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    policy = policy_project / "release-adoption-policy.json"
    policy.write_text(json.dumps({
        "schema": ADOPTION_POLICY_SCHEMA,
        "exceptions": [{
            "path_glob": "src/vendor/acme/**",
            "category": "vendored",
            "reason": "upstream-owned source",
        }],
    }), encoding="utf-8")
    entries = parse_exceptions(json.loads(policy.read_text())["exceptions"], source="x")
    expected = policy_sha256(entries)
    rc, report, _ = _score(
        policy_project,
        capsys,
        "--gate-mode", "release",
        "--adoption-policy", policy.name,
        "--expected-adoption-policy-hash", expected,
    )
    assert rc == EXIT_SUCCESS
    assert report is not None
    registration = report["faculties"]["proprioception"]["metrics"]["registration"]
    assert registration["unknown"] == 0
    assert registration["caller_policy_exempt"] == 1
    evidence = registration["adoption_policy"]
    assert evidence["sha256"] == expected
    assert evidence["matched_count"] == 1
    assert evidence["matched_paths"][0]["path"] == "src/vendor/acme/legacy.py"


def test_policy_hash_mismatch_and_modeled_source_match_are_refused(
    policy_project: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    policy = policy_project / "policy.json"
    policy.write_text(json.dumps({
        "schema": ADOPTION_POLICY_SCHEMA,
        "exceptions": [{
            "path_glob": "src/vendor/acme/**",
            "category": "vendored",
            "reason": "upstream",
        }],
    }), encoding="utf-8")
    rc, report, _ = _score(
        policy_project,
        capsys,
        "--gate-mode", "release",
        "--adoption-policy", policy.name,
        "--expected-adoption-policy-hash", "sha256:" + "0" * 64,
    )
    assert rc == EXIT_USAGE_ERROR
    assert report is None

    policy.write_text(json.dumps({
        "schema": ADOPTION_POLICY_SCHEMA,
        "exceptions": [{
            "path_glob": "src/core/**",
            "category": "generated",
            "reason": "invalid attempt to exempt modeled source",
        }],
    }), encoding="utf-8")
    rc, report, error = _score(
        policy_project, capsys, "--gate-mode", "release",
        "--adoption-policy", policy.name,
    )
    assert rc == EXIT_USAGE_ERROR
    assert report is None
    assert "matches modeled source" in error
