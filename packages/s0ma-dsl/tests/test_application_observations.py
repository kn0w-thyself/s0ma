"""Build and boot an application in a fresh process, then exercise its real consumer."""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest


@pytest.mark.parametrize("renamed", [False, True], ids=["original", "renamed"])
def test_application_observations(tmp_path: Path, renamed: bool) -> None:
    fixture = Path(__file__).parent / "fixtures" / "application_observations"
    project = tmp_path / "project"
    shutil.copytree(fixture, project)
    result = subprocess.run(
        [sys.executable, str(project / "acceptance.py"), *(["--renamed"] if renamed else [])],
        cwd=project,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    evidence = json.loads(result.stdout.splitlines()[-1])
    assert evidence["ok"] is True
    assert evidence["model_calls"] == evidence["network_calls"] == 0
    assert evidence["recorded_contexts"] >= 17
    assert evidence["provider"] == ("ArchiveProvider" if renamed else "FixtureProvider")
    assert evidence["operation"] == ("collect_brief" if renamed else "retrieve_digest")
