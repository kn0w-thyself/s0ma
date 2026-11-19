"""The job that publishes s0ma to PyPI: ``publish-pypi`` in ``release.yml``.

Why this test exists. Every other job in the release workflow can be put
right after the fact: a GitHub Release can be edited, the R2 manifest can be
pointed back at an older version. A file on PyPI cannot be replaced, and a
version number, once used there, is used for good. On top of that, nobody
can run this job ahead of time: it fires on a pushed ``v*`` tag, in the
public repository, behind an environment the owner approves. So the first
time it runs for real is the first time it runs at all.

What can be held still before that day is held here:

1. **It is last.** Nothing is uploaded to PyPI until the gate, the GitHub
   Release, the R2 mirror and the served-release check are green, and no
   job waits on it.
2. **It runs in the public repository only** (PRD NFR-8: nothing built from
   the private source tree is ever published), behind the ``pypi``
   environment.
3. **It holds an identity and no secret.** Trusted publishing: the run
   proves who it is, and no token is stored or named.
4. **It never builds.** It uploads the files the ``release`` job built, so
   PyPI and the GitHub Release hold the same bytes, and it checks that
   before it uploads anything.
5. **A run that stopped part-way can be run again**, and says which
   distribution it stopped at. The first publication depends on this: PyPI
   creates one new project per run of this job (``docs/RELEASING.md``,
   "The first publication").
6. **It publishes every distribution the workspace builds**, a dependency
   before its dependents. A package added under ``packages/`` and not
   added to the job's one list fails here, not at a tag.
7. **Every project it publishes has what its page needs.** A project's
   page on PyPI is its README and its manifest, frozen at upload. The
   umbrella arrived after the other four had been given their project
   links and had none of its own, which is how this came to be checked.

Items 4 to 6 are also *run*: the job's own shell steps are executed
against a stub ``uv``, the way ``test_install_script.py`` drives the
installer, because reading a shell loop is not the same as watching it
stop.

Parsing: PyYAML, where it is installed, following
``test_ci_workflow_safety.py``; a text-level companion runs without it.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
import tomllib
from pathlib import Path
from typing import Any

import pytest

#: The monorepo root (this file: packages/s0ma-dsl/tests/<file>).
REPO_ROOT = Path(__file__).resolve().parents[3]

RELEASE_WORKFLOW = REPO_ROOT / ".github" / "workflows" / "release.yml"

PUBLISH_JOB = "publish-pypi"

#: The job that builds the distributions and creates the GitHub Release.
BUILD_JOB = "release"

#: The only repository this job may publish from.
PUBLIC_REPOSITORY = "kn0w-thyself/s0ma"

#: The links a project's page on PyPI shows beside its README, by the label
#: each manifest gives them under ``[project.urls]``.
PROJECT_LINKS: tuple[str, ...] = ("Homepage", "Repository", "Changelog", "Issues")

#: Every job of the workflow, in the order the header lists them and the
#: order they run in.
JOBS_IN_ORDER: tuple[str, ...] = (
    "check",
    "verify-docs-identity",
    "release",
    "mirror-r2",
    "verify-served",
    PUBLISH_JOB,
)

#: The version the run-level tests pretend a tag names. Not a real release.
PRETEND_VERSION = "9.8.7"


def _workflow_text() -> str:
    return RELEASE_WORKFLOW.read_text(encoding="utf-8")


def _jobs() -> dict[str, Any]:
    yaml = pytest.importorskip("yaml", reason="PyYAML not installed")
    jobs = yaml.safe_load(_workflow_text())["jobs"]
    assert isinstance(jobs, dict)
    return jobs


def _needs(job: dict[str, Any]) -> list[str]:
    needs = job.get("needs", [])
    return [needs] if isinstance(needs, str) else list(needs)


def _runs(job: dict[str, Any]) -> str:
    return "\n".join(str(step.get("run", "")) for step in job["steps"])


def _step_running(job: dict[str, Any], marker: str) -> dict[str, Any]:
    """The one step of *job* whose script contains *marker*.

    Found by what it runs, not by what it is called, so renaming a step
    cannot quietly point a test at nothing.
    """
    found = [step for step in job["steps"] if marker in str(step.get("run", ""))]
    assert len(found) == 1, (marker, [step.get("name") for step in job["steps"]])
    step = found[0]
    assert isinstance(step, dict)
    return step


def _published_stems() -> list[str]:
    """The job's one list of distributions, as wheel stems, in upload order."""
    stems = str(_jobs()[PUBLISH_JOB]["env"]["DISTRIBUTIONS"]).split()
    assert stems, "the publish job names no distribution"
    return stems


def _stem(name: str) -> str:
    """A distribution name as the stem its wheel and sdist carry."""
    return re.sub(r"[-_.]+", "_", name).lower()


def _workspace_projects() -> dict[str, dict[str, Any]]:
    """Every package under ``packages/``, by wheel stem."""
    projects: dict[str, dict[str, Any]] = {}
    for manifest in sorted((REPO_ROOT / "packages").glob("*/pyproject.toml")):
        with manifest.open("rb") as handle:
            project = tomllib.load(handle)["project"]
        projects[_stem(project["name"])] = project
    assert len(projects) >= 4, sorted(projects)
    return projects


# ---------------------------------------------------------------------------
# Where the job sits
# ---------------------------------------------------------------------------


class TestItIsTheLastThingAReleaseDoes:
    def test_the_jobs_are_the_six_the_header_lists(self) -> None:
        assert tuple(_jobs()) == JOBS_IN_ORDER

    def test_it_waits_for_everything_else(self) -> None:
        jobs = _jobs()
        assert _needs(jobs[PUBLISH_JOB]) == [BUILD_JOB, "mirror-r2", "verify-served"]
        # And the two it names beside `release` are themselves downstream of
        # the gate, so "after everything" holds without a rule to remember.
        assert _needs(jobs["verify-served"]) == ["mirror-r2"]
        assert _needs(jobs["mirror-r2"]) == [BUILD_JOB]
        assert "check" in _needs(jobs[BUILD_JOB])

    def test_nothing_waits_for_it(self) -> None:
        """A job skipped by ``if:`` skips its dependents; this one has none."""
        for name, job in _jobs().items():
            assert PUBLISH_JOB not in _needs(job), name

    def test_the_header_names_every_job_in_order(self) -> None:
        header = _workflow_text().partition("name: Release")[0]
        positions = [header.find(f"#   {name}:") for name in JOBS_IN_ORDER]
        assert all(position >= 0 for position in positions), positions
        assert positions == sorted(positions), positions
        assert "NOT enabled" not in header
        assert "commented-out" not in header


# ---------------------------------------------------------------------------
# Who may run it, and as whom
# ---------------------------------------------------------------------------


class TestWhoMayPublish:
    def test_it_runs_in_the_public_repository_only(self) -> None:
        condition = str(_jobs()[PUBLISH_JOB]["if"])
        assert f"github.repository == '{PUBLIC_REPOSITORY}'" in condition
        assert "||" not in condition, condition

    def test_it_waits_in_the_pypi_environment(self) -> None:
        environment = _jobs()[PUBLISH_JOB]["environment"]
        name = environment["name"] if isinstance(environment, dict) else environment
        assert name == "pypi"

    def test_it_holds_an_identity_and_nothing_else(self) -> None:
        job = _jobs()[PUBLISH_JOB]
        assert job["permissions"] == {"contents": "read", "id-token": "write"}
        # The only other job that may hold more than read access is the one
        # that creates the GitHub Release, and it holds no identity token.
        for name, other in _jobs().items():
            if name != PUBLISH_JOB:
                assert "id-token" not in (other.get("permissions") or {}), name

    def test_no_token_is_stored_or_named(self) -> None:
        job = _jobs()[PUBLISH_JOB]
        rendered = "\n".join(
            f"{step.get('run', '')}\n{step.get('env', '')}\n{step.get('with', '')}"
            for step in job["steps"]
        )
        for forbidden in ("secrets.", "--token", "--password", "--username", "UV_PUBLISH_"):
            assert forbidden not in rendered, forbidden
        assert "--trusted-publishing always" in rendered


# ---------------------------------------------------------------------------
# What it publishes
# ---------------------------------------------------------------------------


class TestItPublishesWhatTheReleaseJobBuilt:
    def test_it_never_builds_and_never_checks_out(self) -> None:
        job = _jobs()[PUBLISH_JOB]
        assert "uv build" not in _runs(job)
        uses = [str(step.get("uses", "")) for step in job["steps"]]
        assert not any(action.startswith("actions/checkout@") for action in uses), uses

    def test_the_artifact_it_downloads_is_the_one_the_release_job_uploads(self) -> None:
        jobs = _jobs()
        uploads = [
            step
            for step in jobs[BUILD_JOB]["steps"]
            if str(step.get("uses", "")).startswith("actions/upload-artifact@")
        ]
        downloads = [
            step
            for step in jobs[PUBLISH_JOB]["steps"]
            if str(step.get("uses", "")).startswith("actions/download-artifact@")
        ]
        assert len(uploads) == 1 and len(downloads) == 1, (uploads, downloads)
        assert uploads[0]["with"]["name"] == downloads[0]["with"]["name"]
        assert uploads[0]["with"]["path"] == "dist/*"
        assert downloads[0]["with"]["path"] == "dist"
        assert uploads[0]["with"]["if-no-files-found"] == "error"

    def test_the_release_job_hands_over_what_it_attached(self) -> None:
        """Built, then handed over, then attached: one ``dist/``, in that order."""
        steps = _jobs()[BUILD_JOB]["steps"]
        built = next(i for i, step in enumerate(steps) if "uv build" in str(step.get("run", "")))
        handed = next(
            i
            for i, step in enumerate(steps)
            if str(step.get("uses", "")).startswith("actions/upload-artifact@")
        )
        attached = next(
            i for i, step in enumerate(steps) if "gh release create" in str(step.get("run", ""))
        )
        assert built < handed < attached, (built, handed, attached)
        assert "dist/*" in str(steps[attached]["run"])

    def test_it_compares_its_files_with_the_github_release_before_uploading(self) -> None:
        steps = _jobs()[PUBLISH_JOB]["steps"]
        compared = next(
            i for i, step in enumerate(steps) if "gh release download" in str(step.get("run", ""))
        )
        published = next(
            i for i, step in enumerate(steps) if "uv publish" in str(step.get("run", ""))
        )
        assert compared < published
        assert "sha256sum --check --strict" in str(steps[compared]["run"])

    def test_a_stopped_upload_can_be_run_again(self) -> None:
        script = str(_step_running(_jobs()[PUBLISH_JOB], "uv publish")["run"])
        assert "--check-url https://pypi.org/simple/" in script

    def test_it_names_every_distribution_the_workspace_builds(self) -> None:
        """Adding a package is one line in the job, and forgetting it fails here."""
        stems = _published_stems()
        assert len(stems) == len(set(stems)), stems
        assert set(stems) == set(_workspace_projects()), (
            "the DISTRIBUTIONS line of the publish-pypi job and the packages under "
            "packages/ disagree. Add the new distribution's wheel stem to that line "
            "(after everything it depends on), or remove the one that is gone."
        )

    def test_a_dependency_is_uploaded_before_its_dependents(self) -> None:
        stems = _published_stems()
        projects = _workspace_projects()
        for position, stem in enumerate(stems):
            for requirement in projects[stem].get("dependencies", []):
                match = re.match(r"[A-Za-z0-9._-]+", requirement)
                assert match is not None, requirement
                needed = _stem(match.group())
                if needed in projects:
                    assert stems.index(needed) < position, (
                        f"{stem} depends on {needed}, so {needed} is uploaded first"
                    )


class TestEveryProjectHasWhatItsPageNeeds:
    def test_every_distribution_names_its_links(self) -> None:
        """A package added without them gets a page with no way back here."""
        for stem, project in _workspace_projects().items():
            links = project.get("urls", {})
            missing = [label for label in PROJECT_LINKS if label not in links]
            assert not missing, f"{stem}: [project.urls] is missing {missing}"
            for label, address in links.items():
                assert address.startswith("https://"), (stem, label, address)

    def test_every_distribution_has_a_readme_for_its_page(self) -> None:
        for manifest in sorted((REPO_ROOT / "packages").glob("*/pyproject.toml")):
            with manifest.open("rb") as handle:
                project = tomllib.load(handle)["project"]
            assert project.get("readme") == "README.md", manifest
            assert (manifest.parent / "README.md").is_file(), manifest

    def test_the_environment_links_to_a_project_this_job_publishes(self) -> None:
        address = str(_jobs()[PUBLISH_JOB]["environment"]["url"])
        match = re.fullmatch(r"https://pypi\.org/project/([a-z0-9-]+)/", address)
        assert match is not None, address
        assert _stem(match.group(1)) in _published_stems(), address


# ---------------------------------------------------------------------------
# The steps, run
# ---------------------------------------------------------------------------

_BASH = shutil.which("bash")

runs_the_steps = pytest.mark.skipif(
    sys.platform == "win32" or _BASH is None or shutil.which("sha256sum") is None,
    reason="the job runs on Linux; its steps need bash and sha256sum to be run here",
)

#: A stand-in for ``uv`` that records how it was called and fails when its
#: arguments mention ``$STUB_FAIL_ON``. It uploads nothing and reaches nothing.
_STUB_UV = """#!/bin/sh
printf '%s\\n' "$*" >> "$STUB_LOG"
case "$*" in
  *"$STUB_FAIL_ON"*) echo "error: 403 Forbidden" >&2; exit 2 ;;
esac
exit 0
"""


def _run_step(
    script: str, workdir: Path, *, fail_on: str = "no such distribution"
) -> subprocess.CompletedProcess[str]:
    """Run one of the job's ``run:`` scripts the way the runner would."""
    assert _BASH is not None
    stub_bin = workdir / "stub-bin"
    stub_bin.mkdir(exist_ok=True)
    stub = stub_bin / "uv"
    stub.write_text(_STUB_UV, encoding="utf-8")
    stub.chmod(0o755)
    environment = {
        **os.environ,
        "PATH": f"{stub_bin}{os.pathsep}{os.environ['PATH']}",
        "GITHUB_REF_NAME": f"v{PRETEND_VERSION}",
        "DISTRIBUTIONS": " ".join(_published_stems()),
        "STUB_LOG": str(workdir / "uv-calls.log"),
        "STUB_FAIL_ON": fail_on,
    }
    return subprocess.run(
        [_BASH, "--noprofile", "--norc", "-eo", "pipefail", "-c", script],
        cwd=workdir,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )


def _files_for(stem: str) -> tuple[str, str]:
    return (
        f"{stem}-{PRETEND_VERSION}-py3-none-any.whl",
        f"{stem}-{PRETEND_VERSION}.tar.gz",
    )


@pytest.fixture
def handed_over(tmp_path: Path) -> Path:
    """A directory holding the ``dist/`` the release job would hand over."""
    dist = tmp_path / "dist"
    dist.mkdir()
    for stem in _published_stems():
        for name in _files_for(stem):
            (dist / name).write_text(f"not a real distribution: {name}\n", encoding="utf-8")
    return tmp_path


def _calls(workdir: Path) -> list[str]:
    log = workdir / "uv-calls.log"
    return log.read_text(encoding="utf-8").splitlines() if log.exists() else []


@runs_the_steps
class TestTheStepsRun:
    def test_every_distribution_is_published_once_and_in_order(self, handed_over: Path) -> None:
        script = str(_step_running(_jobs()[PUBLISH_JOB], "uv publish")["run"])
        result = _run_step(script, handed_over)
        assert result.returncode == 0, result.stdout + result.stderr
        calls = _calls(handed_over)
        stems = _published_stems()
        assert len(calls) == len(stems), calls
        for stem, call in zip(stems, calls, strict=True):
            wheel, sdist = _files_for(stem)
            assert call == (
                "publish --trusted-publishing always "
                "--check-url https://pypi.org/simple/ "
                f"dist/{wheel} dist/{sdist}"
            )

    def test_it_stops_at_the_first_failure_and_names_it(self, handed_over: Path) -> None:
        stems = _published_stems()
        stopped_at = stems[2]
        script = str(_step_running(_jobs()[PUBLISH_JOB], "uv publish")["run"])
        result = _run_step(script, handed_over, fail_on=f"dist/{stopped_at}-")
        assert result.returncode == 1, result.stdout + result.stderr
        # The two before it were published, it was tried, nothing after it was.
        assert len(_calls(handed_over)) == 3, _calls(handed_over)
        project = stopped_at.replace("_", "-")
        assert f"::error title={project} {PRETEND_VERSION} was not published::" in result.stdout
        assert "re-run this job" in result.stdout
        assert "docs/RELEASING.md" in result.stdout

    def test_exactly_the_named_distributions_pass(self, handed_over: Path) -> None:
        script = str(_step_running(_jobs()[PUBLISH_JOB], "ls -1 dist")["run"])
        result = _run_step(script, handed_over)
        assert result.returncode == 0, result.stdout + result.stderr
        recorded = (handed_over / "dist.sha256").read_text(encoding="utf-8").splitlines()
        assert len(recorded) == 2 * len(_published_stems()), recorded

    def test_a_file_nobody_named_stops_the_job_before_any_upload(self, handed_over: Path) -> None:
        stray = f"s0ma_lang_surprise-{PRETEND_VERSION}-py3-none-any.whl"
        (handed_over / "dist" / stray).write_text("stray\n", encoding="utf-8")
        script = str(_step_running(_jobs()[PUBLISH_JOB], "ls -1 dist")["run"])
        result = _run_step(script, handed_over)
        assert result.returncode == 1, result.stdout + result.stderr
        assert "::error title=Unexpected distributions::" in result.stdout
        assert stray in result.stdout
        assert _calls(handed_over) == []

    def test_a_missing_file_stops_the_job_before_any_upload(self, handed_over: Path) -> None:
        wheel, _ = _files_for(_published_stems()[0])
        (handed_over / "dist" / wheel).unlink()
        script = str(_step_running(_jobs()[PUBLISH_JOB], "ls -1 dist")["run"])
        result = _run_step(script, handed_over)
        assert result.returncode == 1, result.stdout + result.stderr
        assert _calls(handed_over) == []


# ---------------------------------------------------------------------------
# The same, without a parser
# ---------------------------------------------------------------------------


def test_the_text_says_the_same_without_a_parser() -> None:
    """The companion that runs where PyYAML does not."""
    text = _workflow_text()
    job = text.partition(f"\n  {PUBLISH_JOB}:\n")[2]
    assert job, f"no `{PUBLISH_JOB}` job, or it is commented out"
    assert "\n  " + "# " + PUBLISH_JOB not in text
    assert f"github.repository == '{PUBLIC_REPOSITORY}'" in job
    assert "needs: [release, mirror-r2, verify-served]" in job
    assert "      name: pypi\n" in job
    assert "      id-token: write" in job
    assert "--trusted-publishing always" in job
    assert "--check-url https://pypi.org/simple/" in job
    assert "uv build" not in job
    assert "secrets." not in job
    # It is the last job: no other job header follows it.
    assert not re.search(r"^  [a-z][a-z0-9-]*:\n", job, flags=re.MULTILINE), job
