"""Fork-safety of the workflow files in ``.github/workflows/``.

Why this test exists. Today this repository is private, so the only people
who can start a workflow run are people who are already trusted. When it is
published, anyone in the world can open a pull request, and a pull request
is *code plus a title plus a branch name*, all written by a stranger, that
this repository's own continuous integration then runs. Nearly every
publicised theft of a repository's secrets has the same shape: a workflow
that was safe while the repository was private, kept its wording after the
repository went public, and handed a stranger either a secret or a shell.

The five shapes that matter, and what this file pins:

1. **``pull_request_target``.** It looks like ``pull_request`` and behaves
   in the opposite way: the run gets the repository's own secrets and a
   writable token while the pull request's branch is a stranger's. There is
   none in this tree and there must never be one. A ``workflow_run``
   trigger that checks out the *triggering* run's branch is the same
   mistake wearing a different hat, so it is pinned too.
2. **Default permissions.** A workflow that says nothing about
   ``permissions:`` takes whatever the repository's settings hand it. Every
   workflow should say ``contents: read`` out loud, and only a job that
   genuinely publishes something may ask for more — with its reason
   written down here, in :data:`WIDENED_PERMISSIONS`.
3. **Secrets in reach of a pull request.** GitHub already withholds secrets
   from a pull request opened from a fork, but that is a platform rule this
   repository does not control and cannot see. So the workflows say it
   themselves: a workflow a pull request can start names no secret at all.
4. **The release workflow's door.** Pushing a ``v*`` tag *is* the release
   act (``docs/RELEASING.md``). That workflow must therefore be reachable
   only by pushing a tag — never by opening a pull request, never by
   pushing a branch.
5. **Script injection.** ``run: echo "${{ github.event.pull_request.title }}"``
   runs the title as shell. A pull request titled with a command is then a
   command this repository runs. Interpolating any stranger-writable value
   straight into a shell is refused here; passing it through ``env:`` is
   the safe form and is what the workflows already do with the tag.

And one reported-not-enforced fact: **how actions are pinned**. A tag like
``@v6`` is a moving pointer — whoever owns it can change what it points at.
A 40-character commit identifier cannot move. Today every action in this
tree is pinned by tag, and every one of them comes from GitHub's own
``actions`` organisation or from ``astral-sh`` (the publisher of ``uv``,
which this repository already trusts to install its toolchain). Those two
publishers are allowlisted *by name*, with the reason in
:data:`TAG_PINNED_PUBLISHERS`; anything from anyone else must carry a full
commit identifier. Moving the existing three to commit identifiers is a
recommendation in the milestone note, not a failure today.

The rules are written as functions over a *directory* of workflow files, so
the negative half of this file can copy the real workflows into ``tmp_path``,
break one rule, and prove the check catches it. Those mutations are real
tests rather than a paragraph claiming they were run once.

Parsing: PyYAML is already a dependency of this test environment and is used
here, following ``test_wheel_docs_identity.py``. Where it is absent the
parser-backed tests skip and the text-level companions still run.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest

#: The monorepo root (this file: packages/s0ma-dsl/tests/<file>).
REPO_ROOT = Path(__file__).resolve().parents[3]

#: Every file GitHub would run as a workflow. The rules apply to all of
#: them, so a workflow added tomorrow is covered the day it lands.
WORKFLOWS = REPO_ROOT / ".github" / "workflows"

#: The workflow whose trigger is the release act itself.
RELEASE_WORKFLOWS = ("release.yml",)

#: Jobs permitted to hold more than read access, each with its reason.
#: A job that is not named here and asks for write access fails the test.
WIDENED_PERMISSIONS: dict[tuple[str, str], str] = {
    ("release.yml", "release"): (
        "contents: write — this job creates the GitHub Release for a v* tag and "
        "attaches the built distributions to it. Reachable only by pushing a tag "
        "(pinned by test_the_release_workflow_opens_only_on_a_tag_push)."
    ),
}

#: Workflows that do not yet declare a top-level ``permissions:`` block.
#: This is a shrinking list, never a growing one: a workflow added without
#: the block fails, and an entry here is removed the moment its workflow
#: grows one. The single entry is a known gap, not an exemption on merit.
MISSING_TOP_LEVEL_PERMISSIONS: dict[str, str] = {
    "ci.yml": (
        "Known gap at the time this test was written. ci.yml declares no top-level "
        "permissions block, so its token is whatever the repository's Actions "
        "settings hand it. Nothing in the workflow needs write access (checkout, "
        "uv, the gate, artifact upload), so the fix is two lines. It is left to the "
        "publication runbook because the durable fix is the repository setting that "
        "makes read-only the default for every workflow at once — see "
        "front-door-a5-ci-additions.md. Remove this entry when the block lands."
    ),
}

#: Publishers whose actions may be pinned by a tag rather than by a full
#: commit identifier, each with its reason.
TAG_PINNED_PUBLISHERS: dict[str, str] = {
    "actions": (
        "GitHub's own organisation, which hosts the runners as well. Trusting a tag "
        "here trusts the same party that already runs every job."
    ),
    "astral-sh": (
        "The publisher of uv and ruff. This repository already runs uv as its "
        "toolchain and pins the uv version inside the action's inputs, so a moved "
        "tag cannot change which uv is installed."
    ),
}

#: Repository variables a workflow a pull request can start may read.
#: Empty on purpose: no such workflow reads one today, and a variable is
#: visible to anyone who can read a workflow run's log.
PULL_REQUEST_SAFE_VARIABLES: dict[str, str] = {}

#: The one token a workflow may name without that being a finding, and only
#: while the workflow's default permissions are read-only.
AUTOMATIC_TOKEN = "GITHUB_TOKEN"

#: Expression contexts a stranger can write. Interpolating one of these
#: into a shell hands the writer a shell. The list is the classic
#: script-injection set: everything a pull request, an issue, a comment or
#: a pushed commit carries as free text.
UNTRUSTED_CONTEXTS: tuple[str, ...] = (
    "github.event.pull_request.title",
    "github.event.pull_request.body",
    "github.event.pull_request.head.ref",
    "github.event.pull_request.head.label",
    "github.event.pull_request.head.repo.default_branch",
    "github.event.pull_request.head.repo.description",
    "github.event.pull_request.head.repo.homepage",
    "github.head_ref",
    "github.event.issue.title",
    "github.event.issue.body",
    "github.event.comment.body",
    "github.event.review.body",
    "github.event.review_comment.body",
    "github.event.discussion.title",
    "github.event.discussion.body",
    "github.event.head_commit.message",
    "github.event.head_commit.author.name",
    "github.event.head_commit.author.email",
    "github.event.commits",
    "github.event.workflow_run.head_branch",
    "github.event.workflow_run.head_commit.message",
    "github.event.pages",
)

#: Triggers that put a stranger's pull request in the driving seat.
PULL_REQUEST_TRIGGERS = ("pull_request", "pull_request_target")

_EXPRESSION = re.compile(r"\$\{\{(.*?)\}\}", re.DOTALL)
_SECRET = re.compile(r"secrets\.([A-Za-z_][A-Za-z0-9_-]*)")
_VARIABLE = re.compile(r"vars\.([A-Za-z_][A-Za-z0-9_-]*)")
_COMMIT_IDENTIFIER = re.compile(r"[0-9a-f]{40}")


@dataclass(frozen=True)
class Workflow:
    """One workflow file, as text and as a parsed document."""

    name: str
    text: str
    document: dict[str, Any]


def _yaml() -> Any:
    return pytest.importorskip("yaml", reason="PyYAML not installed")


def load_workflows(directory: Path) -> list[Workflow]:
    """Every workflow in *directory*, in a fixed order."""
    loaded: list[Workflow] = []
    for path in sorted(directory.glob("*.y*ml")):
        text = path.read_text(encoding="utf-8")
        document = _yaml().safe_load(text)
        loaded.append(Workflow(path.name, text, document if isinstance(document, dict) else {}))
    return loaded


def _line_of(text: str, needle: str) -> int:
    """The 1-based line where *needle* first appears, or 0 if it does not."""
    for number, line in enumerate(text.splitlines(), 1):
        if needle in line:
            return number
    return 0


def _triggers(workflow: Workflow) -> dict[str, Any]:
    """The workflow's triggers as a mapping.

    PyYAML reads a bare ``on:`` key as the boolean ``True`` (the YAML 1.1
    spelling), so both spellings are accepted rather than one guessed —
    the same accommodation ``test_wheel_docs_identity.py`` makes.
    """
    raw = workflow.document.get("on", workflow.document.get(True))
    if raw is None:
        return {}
    if isinstance(raw, str):
        return {raw: None}
    if isinstance(raw, list):
        return dict.fromkeys(raw)
    return dict(raw)


def _jobs(workflow: Workflow) -> dict[str, Any]:
    jobs = workflow.document.get("jobs")
    return jobs if isinstance(jobs, dict) else {}


def _steps(job: Any) -> list[dict[str, Any]]:
    steps = job.get("steps") if isinstance(job, dict) else None
    return [step for step in steps if isinstance(step, dict)] if isinstance(steps, list) else []


def _is_read_only(permissions: Any) -> bool:
    """Whether a ``permissions:`` value grants nothing beyond reading."""
    if permissions is None:
        # `permissions:` with nothing under it grants nothing at all.
        return True
    if isinstance(permissions, str):
        return permissions == "read-all"
    if isinstance(permissions, dict):
        return all(str(value) in {"read", "none"} for value in permissions.values())
    return False


def _expressions(text: str) -> list[tuple[int, str]]:
    """Every ``${{ ... }}`` expression outside a comment, with its line."""
    found: list[tuple[int, str]] = []
    for number, line in enumerate(text.splitlines(), 1):
        if line.lstrip().startswith("#"):
            continue
        found.extend((number, match.group(1)) for match in _EXPRESSION.finditer(line))
    return found


def no_pull_request_target(workflow: Workflow) -> list[str]:
    """Rule 1: no trigger hands a stranger's branch a trusted run."""
    findings: list[str] = []
    triggers = _triggers(workflow)
    if "pull_request_target" in triggers:
        line = _line_of(workflow.text, "pull_request_target")
        findings.append(
            f"{workflow.name}:{line}: this workflow is started by "
            "`pull_request_target`, which runs with this repository's own secrets "
            "and a writable token while the code under test belongs to whoever "
            "opened the pull request. Use `pull_request` instead."
        )
    if "workflow_run" in triggers:
        for job_name, job in _jobs(workflow).items():
            for step in _steps(job):
                uses = str(step.get("uses") or "")
                inputs = step.get("with")
                reference = str(inputs.get("ref") or "") if isinstance(inputs, dict) else ""
                if uses.startswith("actions/checkout") and "github.event" in reference:
                    line = _line_of(workflow.text, reference)
                    findings.append(
                        f"{workflow.name}:{line}: job `{job_name}` is started by a "
                        "`workflow_run` trigger and then checks out the code that "
                        "started it. That run's branch may belong to a stranger, "
                        "and this one is trusted. Check out this repository's own "
                        "commit instead."
                    )
    return findings


def read_only_by_default(workflow: Workflow) -> list[str]:
    """Rule 2: read-only unless a listed job says why it needs more."""
    findings: list[str] = []
    if "permissions" not in workflow.document:
        if workflow.name not in MISSING_TOP_LEVEL_PERMISSIONS:
            findings.append(
                f"{workflow.name}:1: this workflow declares no top-level "
                "`permissions:` block, so the access its runs get is whatever the "
                "repository's Actions settings hand out. Add `permissions:` with "
                "`contents: read` at the top of the file."
            )
    elif not _is_read_only(workflow.document.get("permissions")):
        line = _line_of(workflow.text, "permissions:")
        findings.append(
            f"{workflow.name}:{line}: the workflow's default `permissions:` grants "
            "more than reading. The default must be read-only (`contents: read`); "
            "a single job that publishes something may widen it for itself."
        )
    for job_name, job in _jobs(workflow).items():
        if not isinstance(job, dict) or "permissions" not in job:
            continue
        if _is_read_only(job.get("permissions")):
            continue
        if (workflow.name, job_name) in WIDENED_PERMISSIONS:
            continue
        line = _line_of(workflow.text, f"  {job_name}:")
        findings.append(
            f"{workflow.name}:{line}: job `{job_name}` widens its permissions "
            "beyond reading. If it really has to, add it to WIDENED_PERMISSIONS in "
            f"{Path(__file__).name} with one line saying what it publishes and why."
        )
    return findings


def no_secrets_within_reach_of_a_pull_request(workflow: Workflow) -> list[str]:
    """Rule 3: a workflow a pull request can start names no secret.

    The rule is deliberately whole-file rather than per-job. A job that
    names a secret and is kept away from pull requests by an ``if:``
    condition is one edited condition away from not being kept away at
    all, and nothing in this repository needs that arrangement.
    """
    triggers = _triggers(workflow)
    if not any(trigger in triggers for trigger in PULL_REQUEST_TRIGGERS):
        return []
    default_is_read_only = "permissions" in workflow.document and _is_read_only(
        workflow.document.get("permissions")
    )
    findings: list[str] = []
    for line, expression in _expressions(workflow.text):
        for name in _SECRET.findall(expression):
            if name == AUTOMATIC_TOKEN and default_is_read_only:
                continue
            reason = (
                "the automatically provided token is only safe here while this "
                "workflow's default permissions are read-only, and they are not"
                if name == AUTOMATIC_TOKEN
                else "a pull request opened from a fork must never be able to reach it"
            )
            findings.append(
                f"{workflow.name}:{line}: this workflow can be started by a pull "
                f"request and names the secret `{name}` — {reason}. Move the work "
                "that needs it into a workflow that pull requests cannot start."
            )
        for name in _VARIABLE.findall(expression):
            if name in PULL_REQUEST_SAFE_VARIABLES:
                continue
            findings.append(
                f"{workflow.name}:{line}: this workflow can be started by a pull "
                f"request and reads the repository variable `{name}`. Variables are "
                "not secret — anyone who can read a run's log can read them — so "
                "either confirm it carries nothing private by adding it to "
                f"PULL_REQUEST_SAFE_VARIABLES in {Path(__file__).name}, or move the "
                "step that reads it out of this workflow."
            )
    return findings


def the_release_door_is_a_tag(workflow: Workflow) -> list[str]:
    """Rule 4: the release workflow opens to a tag push and nothing else."""
    findings: list[str] = []
    triggers = _triggers(workflow)
    widens = any(
        (workflow.name, job_name) in WIDENED_PERMISSIONS for job_name in _jobs(workflow)
    )
    if widens or workflow.name in RELEASE_WORKFLOWS:
        for trigger in PULL_REQUEST_TRIGGERS:
            if trigger in triggers:
                line = _line_of(workflow.text, trigger)
                findings.append(
                    f"{workflow.name}:{line}: this workflow can write to the "
                    f"repository and is started by `{trigger}`. A pull request must "
                    "never be able to start a workflow that publishes anything."
                )
    if workflow.name not in RELEASE_WORKFLOWS:
        return findings
    allowed = {"push", "workflow_dispatch"}
    for trigger in sorted(set(triggers) - allowed):
        line = _line_of(workflow.text, str(trigger))
        findings.append(
            f"{workflow.name}:{line}: the release workflow is started by "
            f"`{trigger}`. Pushing a v* tag is the release act, so a tag push (and "
            "a deliberate manual run) are the only ways in."
        )
    push = triggers.get("push")
    if "push" in triggers:
        push = push if isinstance(push, dict) else {}
        if "tags" not in push and "tags-ignore" not in push:
            line = _line_of(workflow.text, "push:")
            findings.append(
                f"{workflow.name}:{line}: the release workflow's `push:` trigger "
                "names no tags, so it would fire on ordinary pushes. It must fire "
                "on a v* tag only."
            )
        if "branches" in push or "branches-ignore" in push:
            line = _line_of(workflow.text, "branches")
            findings.append(
                f"{workflow.name}:{line}: the release workflow's `push:` trigger "
                "names branches. Pushing a branch would then publish a release."
            )
    return findings


def no_stranger_writable_text_in_a_shell(workflow: Workflow) -> list[str]:
    """Rule 5: nothing a stranger writes is interpolated into a shell."""
    findings: list[str] = []
    for job_name, job in _jobs(workflow).items():
        for step in _steps(job):
            inputs = step.get("with")
            scripted = inputs.get("script") if isinstance(inputs, dict) else None
            for body in (step.get("run"), scripted):
                if not isinstance(body, str):
                    continue
                for match in _EXPRESSION.finditer(body):
                    context = match.group(1)
                    for untrusted in UNTRUSTED_CONTEXTS:
                        if untrusted not in context:
                            continue
                        line = _line_of(workflow.text, match.group(0))
                        findings.append(
                            f"{workflow.name}:{line}: job `{job_name}` puts "
                            f"`{untrusted}` straight into a shell. Anyone who opens "
                            "a pull request writes that text, so they would be "
                            "writing part of the command. Pass it through the "
                            "step's `env:` and use the environment variable in the "
                            "script instead."
                        )
                        break
    return findings


def actions_are_pinned(workflow: Workflow) -> list[str]:
    """Rule 6: a full commit identifier, or a publisher listed by name."""
    findings: list[str] = []
    for job_name, job in _jobs(workflow).items():
        used = [step.get("uses") for step in _steps(job)]
        if isinstance(job, dict) and isinstance(job.get("uses"), str):
            used.append(job["uses"])
        for uses in used:
            if not isinstance(uses, str) or uses.startswith(("./", ".\\", "docker://")):
                continue
            line = _line_of(workflow.text, uses)
            if "@" not in uses:
                findings.append(
                    f"{workflow.name}:{line}: job `{job_name}` uses `{uses}` without "
                    "saying which version. Pin it to a full commit identifier."
                )
                continue
            action, _, reference = uses.rpartition("@")
            publisher = action.split("/")[0]
            if _COMMIT_IDENTIFIER.fullmatch(reference):
                continue
            if publisher in TAG_PINNED_PUBLISHERS:
                continue
            findings.append(
                f"{workflow.name}:{line}: job `{job_name}` uses `{uses}`, pinned to "
                f"the moving tag `{reference}`. Whoever owns `{publisher}` can change "
                "what that tag points at, and this repository would run the new "
                "contents without noticing. Pin it to the 40-character commit "
                "identifier instead (leave the tag beside it as a comment)."
            )
    return findings


#: Every rule, in the order the module docstring introduces them.
RULES = (
    no_pull_request_target,
    read_only_by_default,
    no_secrets_within_reach_of_a_pull_request,
    the_release_door_is_a_tag,
    no_stranger_writable_text_in_a_shell,
    actions_are_pinned,
)


def scan(directory: Path) -> list[str]:
    """Every rule against every workflow in *directory*, worst first by file."""
    findings: list[str] = []
    for workflow in load_workflows(directory):
        for rule in RULES:
            findings.extend(rule(workflow))
    return findings


# --------------------------------------------------------------------------
# What today's tree must satisfy.
# --------------------------------------------------------------------------


def test_the_workflows_are_fork_safe() -> None:
    """The whole battery, against the tree as it stands."""
    findings = scan(WORKFLOWS)
    assert not findings, "\n".join(["workflow safety findings:", *findings])


def test_there_is_something_to_check() -> None:
    """The anti-vacuity floor: a scan that saw nothing proves nothing.

    Without this, deleting the workflows — or a glob that stopped matching
    them — would turn the test above into a test that always passes.
    """
    workflows = load_workflows(WORKFLOWS)
    assert len(workflows) >= 2, [workflow.name for workflow in workflows]
    steps = sum(len(_steps(job)) for wf in workflows for job in _jobs(wf).values())
    assert steps >= 20, steps
    assert any(
        trigger in _triggers(workflow)
        for workflow in workflows
        for trigger in PULL_REQUEST_TRIGGERS
    ), "no workflow is started by a pull request — has the corpus moved?"
    assert any(
        isinstance(step.get("uses"), str)
        for workflow in workflows
        for job in _jobs(workflow).values()
        for step in _steps(job)
    ), "no action is used anywhere — has the corpus moved?"


def test_the_release_workflow_opens_only_on_a_tag_push() -> None:
    """Stated separately because it is the one door that publishes."""
    release = next(wf for wf in load_workflows(WORKFLOWS) if wf.name == "release.yml")
    triggers = _triggers(release)
    assert set(triggers) <= {"push", "workflow_dispatch"}, sorted(triggers)
    assert "tags" in triggers["push"], triggers["push"]
    assert "branches" not in triggers["push"], triggers["push"]


def test_the_text_says_the_same_without_a_parser() -> None:
    """The companion that runs where PyYAML does not, as the house does it."""
    for path in sorted(WORKFLOWS.glob("*.y*ml")):
        text = path.read_text(encoding="utf-8")
        assert "pull_request_target" not in text, path.name
        for untrusted in UNTRUSTED_CONTEXTS:
            assert f"{{{{ {untrusted}" not in text, (path.name, untrusted)
    release = (WORKFLOWS / "release.yml").read_text(encoding="utf-8")
    assert '\non:\n  push:\n    tags: ["v*"]\n' in release
    assert "\npermissions:\n  contents: read\n" in release


def test_every_allowlist_entry_still_names_something_real() -> None:
    """An allowlist nobody prunes becomes a list of permissions nobody meant."""
    workflows = {workflow.name: workflow for workflow in load_workflows(WORKFLOWS)}
    for name, reason in MISSING_TOP_LEVEL_PERMISSIONS.items():
        assert name in workflows, f"{name} is allowlisted but no longer exists"
        assert reason.strip(), name
        assert "permissions" not in workflows[name].document, (
            f"{name} now declares top-level permissions — delete its "
            "MISSING_TOP_LEVEL_PERMISSIONS entry"
        )
    for (name, job_name), reason in WIDENED_PERMISSIONS.items():
        assert name in workflows, f"{name} is allowlisted but no longer exists"
        assert job_name in _jobs(workflows[name]), f"{name}: no job `{job_name}`"
        assert reason.strip(), (name, job_name)
    used = {
        str(step.get("uses")).split("/")[0]
        for workflow in workflows.values()
        for job in _jobs(workflow).values()
        for step in _steps(job)
        if isinstance(step.get("uses"), str)
    }
    for publisher, reason in TAG_PINNED_PUBLISHERS.items():
        assert publisher in used, (
            f"`{publisher}` is allowed to pin by tag but nothing uses it any more — "
            "delete the entry rather than leaving a standing grant"
        )
        assert reason.strip(), publisher


# --------------------------------------------------------------------------
# The negative half: each rule, broken on a copy, must be caught.
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class Mutation:
    """One deliberate weakening of the workflows, and what must be said."""

    rule: str
    path: str
    before: str
    after: str
    expected: str


#: Ten weakenings, at least one per rule. Each is applied to a copy of the
#: real workflows, which is scanned clean first, so the finding can only
#: have come from the mutation.
MUTATIONS = (
    Mutation(
        rule="no_pull_request_target",
        path="ci.yml",
        before="  pull_request:\n    branches: [main]",
        after="  pull_request_target:\n    branches: [main]",
        expected="`pull_request_target`",
    ),
    Mutation(
        rule="no_pull_request_target (workflow_run)",
        path="triggered.yml",
        before="",
        after=(
            "name: Triggered\n"
            "on:\n"
            "  workflow_run:\n"
            "    workflows: [CI]\n"
            "    types: [completed]\n"
            "permissions:\n"
            "  contents: read\n"
            "jobs:\n"
            "  comment:\n"
            "    runs-on: ubuntu-latest\n"
            "    steps:\n"
            "      - uses: actions/checkout@v6\n"
            "        with:\n"
            "          ref: ${{ github.event.workflow_run.head_sha }}\n"
        ),
        expected="checks out the code that started it",
    ),
    Mutation(
        rule="read_only_by_default (default widened)",
        path="release.yml",
        before="\npermissions:\n  contents: read\n",
        after="\npermissions:\n  contents: write\n",
        expected="grants more than reading",
    ),
    Mutation(
        rule="read_only_by_default (block missing)",
        path="extra.yml",
        before="",
        after=(
            "name: Extra\n"
            "on:\n"
            "  push:\n"
            "    branches: [main]\n"
            "jobs:\n"
            "  hello:\n"
            "    runs-on: ubuntu-latest\n"
            "    steps:\n"
            "      - uses: actions/checkout@v6\n"
        ),
        expected="declares no top-level `permissions:` block",
    ),
    Mutation(
        rule="read_only_by_default (job widened)",
        path="ci.yml",
        before="    runs-on: ubuntu-latest\n    needs: check\n",
        after="    runs-on: ubuntu-latest\n    needs: check\n    permissions:\n"
        "      contents: write\n",
        expected="widens its permissions beyond reading",
    ),
    Mutation(
        rule="no_secrets_within_reach_of_a_pull_request (secret)",
        path="ci.yml",
        before="      - name: Run the unified check pipeline\n        run: uv run python"
        " scripts/check.py\n",
        after="      - name: Run the unified check pipeline\n        env:\n"
        "          TOKEN: ${{ secrets.CF_API_TOKEN }}\n"
        "        run: uv run python scripts/check.py\n",
        expected="names the secret `CF_API_TOKEN`",
    ),
    Mutation(
        rule="no_secrets_within_reach_of_a_pull_request (variable)",
        path="ci.yml",
        before="      - name: Run the unified check pipeline\n        run: uv run python"
        " scripts/check.py\n",
        after="      - name: Run the unified check pipeline\n        env:\n"
        "          ACCOUNT: ${{ vars.CLOUDFLARE_ACCOUNT_ID }}\n"
        "        run: uv run python scripts/check.py\n",
        expected="reads the repository variable `CLOUDFLARE_ACCOUNT_ID`",
    ),
    Mutation(
        rule="the_release_door_is_a_tag",
        path="release.yml",
        before='\non:\n  push:\n    tags: ["v*"]\n',
        after='\non:\n  push:\n    tags: ["v*"]\n  pull_request:\n    branches: [main]\n',
        expected="never be able to start a workflow that publishes",
    ),
    Mutation(
        rule="no_stranger_writable_text_in_a_shell",
        path="ci.yml",
        before="        run: uv run python scripts/check.py\n",
        after='        run: echo "reviewing ${{ github.event.pull_request.title }}"\n',
        expected="straight into a shell",
    ),
    Mutation(
        rule="actions_are_pinned (unknown publisher)",
        path="ci.yml",
        before="        uses: actions/upload-artifact@v7\n",
        after="        uses: some-vendor/upload-artifact@v1\n",
        expected="pinned to the moving tag `v1`",
    ),
    Mutation(
        rule="actions_are_pinned (no version at all)",
        path="ci.yml",
        before="        uses: astral-sh/setup-uv@v8.2.0\n        with:\n"
        '          version: "0.9.21"\n          python-version: "3.12"\n',
        after="        uses: astral-sh/setup-uv\n        with:\n"
        '          version: "0.9.21"\n          python-version: "3.12"\n',
        expected="without saying which version",
    ),
)


def _corpus(tmp_path: Path) -> Path:
    """A throwaway copy of the real workflows, byte for byte."""
    directory = tmp_path / "workflows"
    directory.mkdir()
    for path in sorted(WORKFLOWS.glob("*.y*ml")):
        (directory / path.name).write_text(
            path.read_text(encoding="utf-8"), encoding="utf-8", newline="\n"
        )
    return directory


@pytest.mark.parametrize("mutation", MUTATIONS, ids=lambda mutation: mutation.rule)
def test_a_weakened_workflow_is_caught(mutation: Mutation, tmp_path: Path) -> None:
    """Break one rule on a copy; the scan must name it."""
    directory = _corpus(tmp_path)
    assert scan(directory) == [], "the unmutated copy must be clean"
    target = directory / mutation.path
    if mutation.before:
        text = target.read_text(encoding="utf-8")
        assert text.count(mutation.before) == 1, (
            f"{mutation.path} no longer contains the text this mutation edits — "
            "the mutation is stale and proves nothing"
        )
        target.write_text(
            text.replace(mutation.before, mutation.after), encoding="utf-8", newline="\n"
        )
    else:
        assert not target.exists(), mutation.path
        target.write_text(mutation.after, encoding="utf-8", newline="\n")
    findings = scan(directory)
    assert any(mutation.expected in finding for finding in findings), (
        f"the {mutation.rule} weakening went unnoticed. Findings: {findings}"
    )
    assert all(finding.startswith(f"{mutation.path}:") for finding in findings), findings


def test_every_rule_has_a_mutation() -> None:
    """A rule nobody proved bites is a rule nobody can rely on."""
    proven = {mutation.rule.partition(" ")[0] for mutation in MUTATIONS}
    assert {rule.__name__ for rule in RULES} <= proven
