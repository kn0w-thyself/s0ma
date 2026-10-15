"""M5 static derived-surface provenance and cache contracts."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

import pytest

import s0ma_dsl.derived_surface as derived

if TYPE_CHECKING:
    from pathlib import Path


def _project(tmp_path: Path) -> tuple[Path, Path]:
    root = tmp_path / "project"
    source = root / "src" / "legacy_impl.py"
    source.parent.mkdir(parents=True)
    (root / "pyproject.toml").write_text(
        """\
[project]
name = "legacy-app"

[tool.s0ma]
source_roots = ["src"]
test_roots = ["tests"]
build_dir = "build"
authoring = "on"
""",
        encoding="utf-8",
    )
    source.write_text(
        """\
\"\"\"Legacy billing helpers awaiting componentization.

The second line is deliberately not the draft summary.
\"\"\"
import os
from .helpers import charge

PUBLIC_VALUE = 1
_PRIVATE_VALUE = 2

def bill_customer():
    return os.getcwd(), charge()
""",
        encoding="utf-8",
    )
    return root, source


def _cache_files(root: Path) -> list[Path]:
    return sorted((root / derived.DERIVED_CACHE_DIR).glob("*.json"))


def test_static_surface_is_provenance_marked_and_never_imports(
    tmp_path: Path,
) -> None:
    root, source = _project(tmp_path)
    sentinel = root / "import-side-effect"
    source.write_text(
        source.read_text(encoding="utf-8")
        + f"\nfrom pathlib import Path\nPath({str(sentinel)!r}).write_text('bad')\n",
        encoding="utf-8",
    )

    surface = derived.derive_python_surface(root, source)

    assert not sentinel.exists()
    assert surface["schema"] == "s0ma-derived-surface@1"
    assert surface["authority"] == "derived"
    assert surface["mapped"] is False
    assert surface["module"] == "legacy_impl"
    assert surface["source"] == "src/legacy_impl.py"
    assert surface["source_hash"].startswith("sha256:")
    assert surface["config_hash"].startswith("sha256:")
    assert surface["derivation_version"] == "1"
    assert surface["tool_version"]
    assert surface["provenance"] == {
        "method": "static_python_ast",
        "imports_executed": False,
    }
    assert surface["summary"] == {
        "state": "pending",
        "reason": "machine-derived draft requires author review",
        "draft": "Legacy billing helpers awaiting componentization.",
    }
    assert surface["exports"] == ["PUBLIC_VALUE", "bill_customer"]
    assert surface["imports"] == [".helpers", "os", "pathlib"]
    assert surface["confidence"] == "syntax_only"
    assert "does not satisfy score or gate" in surface["limitations"]


def test_cache_hit_avoids_reparsing_and_bytes_are_deterministic(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root, source = _project(tmp_path)
    first = derived.derive_python_surface(root, source)
    files = _cache_files(root)
    assert len(files) == 1
    expected_bytes = json.dumps(first, indent=2, sort_keys=True) + "\n"
    assert files[0].read_text(encoding="utf-8") == expected_bytes

    def fail_parse(*args: object, **kwargs: object) -> object:
        raise AssertionError("cache hit must not reparse source")

    monkeypatch.setattr(derived.ast, "parse", fail_parse)
    assert derived.derive_python_surface(root, source) == first


def test_identical_bytes_at_distinct_paths_have_distinct_cache_identity(
    tmp_path: Path,
) -> None:
    root, source = _project(tmp_path)
    sibling = source.with_name("legacy_copy.py")
    sibling.write_bytes(source.read_bytes())

    original = derived.derive_python_surface(root, source)
    copy = derived.derive_python_surface(root, sibling)

    assert original["source_hash"] == copy["source_hash"]
    assert original["source"] == "src/legacy_impl.py"
    assert original["module"] == "legacy_impl"
    assert copy["source"] == "src/legacy_copy.py"
    assert copy["module"] == "legacy_copy"
    assert len(_cache_files(root)) == 2
    cached_sources = {
        json.loads(path.read_text(encoding="utf-8"))["source"]
        for path in _cache_files(root)
    }
    assert cached_sources == {"src/legacy_impl.py", "src/legacy_copy.py"}


def test_source_config_tool_and_schema_changes_each_invalidate_cache(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root, source = _project(tmp_path)
    initial = derived.derive_python_surface(root, source)
    assert len(_cache_files(root)) == 1

    source.write_text(
        source.read_text(encoding="utf-8") + "\nNEW_EXPORT = 3\n",
        encoding="utf-8",
    )
    source_changed = derived.derive_python_surface(root, source)
    assert source_changed["source_hash"] != initial["source_hash"]
    assert len(_cache_files(root)) == 2

    pyproject = root / "pyproject.toml"
    pyproject.write_text(
        pyproject.read_text(encoding="utf-8").replace(
            'authoring = "on"', 'authoring = "off"'
        ),
        encoding="utf-8",
    )
    config_changed = derived.derive_python_surface(root, source)
    assert config_changed["config_hash"] != source_changed["config_hash"]
    assert len(_cache_files(root)) == 3

    monkeypatch.setattr(derived, "__version__", "0.13.0-test-tool-change")
    tool_changed = derived.derive_python_surface(root, source)
    assert tool_changed["tool_version"] == "0.13.0-test-tool-change"
    assert len(_cache_files(root)) == 4

    monkeypatch.setattr(derived, "DERIVED_SURFACE_SCHEMA", "s0ma-derived-surface@99")
    schema_changed = derived.derive_python_surface(root, source)
    assert schema_changed["schema"] == "s0ma-derived-surface@99"
    assert len(_cache_files(root)) == 5


def test_cache_symlink_escape_is_refused(tmp_path: Path) -> None:
    root, source = _project(tmp_path)
    outside = tmp_path / "outside"
    outside.mkdir()
    cache_parent = root / ".s0ma.cache"
    try:
        cache_parent.symlink_to(outside, target_is_directory=True)
    except OSError:
        pytest.skip("platform does not permit symlink creation")

    with pytest.raises(derived.DerivedSurfaceError, match="escapes the project root"):
        derived.derive_python_surface(root, source)
