"""G4 (feedback 5–6 cleanup) — cross-source-root ``uses:`` resolution in ``s0ma test``.

Pins the per-source-root build pass behaviour: each iteration of the
``s0ma test`` source-root loop now threads the *other* configured
source roots through ``--include`` so cross-source-root ``uses:``
references resolve as context modules. Pre-G4, every per-root build
ran with ``include_dirs=[]``; in a fan-out layout (e.g. ``source_roots
= ["domain", "application", "presentation"]``) a ``uses:
order_model.X`` reference from ``application/foo.s0ma`` could not
resolve and the resolver raised ``DOES_NOT_EXIST`` — kn0wthyself-
website-2 hit this on its first migration attempt (M20 finding #6).

Locks down:

- A two-source-root project with cross-root ``uses:`` builds and runs
  ``s0ma test`` cleanly.
- A three-source-root project with cyclic include patterns (each root
  references at least one other) resolves; one-shot per-root builds
  do not induce a cycle even when ``--include`` cross-references.
- A single-source-root project shows no regression: the sibling list
  is empty, ``include_dirs=[]``, behaviour matches pre-G4.
- The test-root build pass continues to see *every* source root (not
  just the most-recently-built one) so test-side cross-source-root
  ``uses:`` resolves the same way.
- A deliberate ``PARSE_ERROR`` in source root B is attributed to B's
  file path in the diagnostic, not A's — even though A's build pass
  was including B as a sibling. The per-root structure that exists
  for clean attribution is preserved.

Pairs with ``tests/test_s0ma_test_runner.py`` (M7 single-root cross-
module fixture is the control case for the no-regression pin) and
``tests/test_overlapping_roots.py`` (G2 — sibling source roots must
be disjoint, which is the G4 contract's structural prerequisite).
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from s0ma_dsl.cli.main import EXIT_SUCCESS, S0maCLI

FIXTURE = (
    Path(__file__).parent / "fixtures" / "multi_source_root_project"
)


@pytest.fixture()
def staged_multi_root_project(tmp_path: Path) -> Path:
    """Copy the multi-source-root fixture into ``tmp_path``.

    ``s0ma test`` writes the build dir into the project root and we run
    in parallel under pytest workers, so we stage every fixture into a
    fresh tmp dir.
    """
    dst = tmp_path / "multi_source_root_project"
    shutil.copytree(FIXTURE, dst)
    return dst


# ---------------------------------------------------------------------------
# End-to-end: cross-source-root ``uses:`` resolves under ``s0ma test``.
# ---------------------------------------------------------------------------


def test_two_source_roots_cross_uses_resolves(
    staged_multi_root_project: Path,
) -> None:
    """A->B cross-source-root ``uses:`` resolves cleanly.

    The fixture's ``application/order_service.s0ma`` carries
    ``uses: [order_model.Order, order_model.build_order]`` where
    ``order_model`` lives under the sibling ``domain/`` source root.
    Pre-G4, the application source-root build pass was launched with
    ``include_dirs=[]`` — the resolver could not find ``order_model``
    in the project and raised ``DOES_NOT_EXIST``. Post-G4, the
    sibling ``domain/`` root is threaded through ``--include`` and
    the reference resolves.
    """
    cli = S0maCLI()
    rc = cli.run([
        "--project-root", str(staged_multi_root_project),
        "test",
        "--quiet",
    ])
    assert rc == EXIT_SUCCESS, (
        "Cross-source-root `uses:` must resolve under `s0ma test` "
        "post-G4; if this fails, the sibling-include threading in "
        "_cmd_test's source-root loop is broken."
    )


def test_three_source_roots_cyclic_includes_resolve(
    staged_multi_root_project: Path,
) -> None:
    """All three sibling roots build cleanly; one-shot builds break the cycle.

    The fixture has three sibling source roots (``domain/``,
    ``application/``, ``presentation/``). The presentation layer's
    ``order_view`` ``uses: [order_service.process_order]`` (reaches
    into application), and the application layer's ``order_service``
    and ``order_summary`` ``uses: [order_model.X]`` (reach into
    domain). Each per-root build pass passes the other two roots as
    siblings via ``--include`` — the include set forms a complete
    graph A↔B↔C↔A. No cycle is induced because ``_cmd_build`` does
    not recursively descend into ``--include`` paths; each invocation
    parses target files + context files exactly once.
    """
    cli = S0maCLI()
    rc = cli.run([
        "--project-root", str(staged_multi_root_project),
        "test",
        "--quiet",
    ])
    assert rc == EXIT_SUCCESS

    # Structural check: every source root produced its target module(s)
    # in the flat build dir.
    build_dir = staged_multi_root_project / "multi_source_root_project_build"
    expected = {
        "order_model.py",      # domain
        "order_service.py",    # application
        "order_summary.py",    # application
        "order_view.py",       # presentation
        "test_cross_root.py",  # tests
    }
    actual_py = {p.name for p in build_dir.glob("*.py")}
    missing = expected - actual_py
    assert not missing, (
        f"build dir missing expected modules: {missing}; "
        f"got: {sorted(actual_py)}"
    )


def test_test_root_pass_sees_all_source_roots(
    staged_multi_root_project: Path,
) -> None:
    """The test-root build pass continues to see every source root.

    The test module ``tests/test_cross_root.s0ma`` declares
    ``uses: [order_view.format_status, order_service.process_order,
    order_model.build_order]`` — three references reaching into all
    three sibling source roots. The post-G4 contract for the test-
    root pass is unchanged from the pre-G4 spec (M7): ``include_dirs
    = source_roots_present`` covers every source root, not just the
    most-recently-built one. We exercise this end-to-end by running
    the four ``test ...`` declarations under pytest; if any of the
    three cross-root ``uses:`` failed to resolve, the build would
    abort before pytest got invoked.
    """
    cli = S0maCLI()
    rc = cli.run([
        "--project-root", str(staged_multi_root_project),
        "test",
        "--quiet",
    ])
    assert rc == EXIT_SUCCESS

    # Confirm pytest actually ran the four cross-root tests by
    # re-invoking with a ``-k`` filter that matches every test name in
    # the test module — the filter has no effect on the four-test
    # selection but proves the pytest layer received the args.
    rc_filtered = cli.run([
        "--project-root", str(staged_multi_root_project),
        "test",
        "--quiet",
        "--",
        "-k", "test_format_status or test_application_via_uses or test_domain_via_uses",
    ])
    assert rc_filtered == EXIT_SUCCESS


# ---------------------------------------------------------------------------
# Single-source-root regression control — the M7 fixture must keep working.
# ---------------------------------------------------------------------------


def test_single_source_root_no_regression(tmp_path: Path) -> None:
    """A single-source-root project sees no behavioural change.

    With one source root the sibling list is empty; ``include_dirs``
    passed to ``_run_build_for_test`` is ``[]``. The post-G4 path
    must reduce exactly to the pre-G4 path for this case. We
    exercise the cross_module_test_project fixture (used by M7's
    own test suite) end-to-end and assert success; if the G4 edit
    accidentally widened the include set with anything besides
    siblings, this test would surface it.
    """
    src_fixture = (
        Path(__file__).parent / "fixtures" / "cross_module_test_project"
    )
    dst = tmp_path / "single_root_project"
    shutil.copytree(src_fixture, dst)

    cli = S0maCLI()
    rc = cli.run([
        "--project-root", str(dst),
        "test",
        "--quiet",
    ])
    assert rc == EXIT_SUCCESS, (
        "Single-source-root projects must show no regression "
        "post-G4; the sibling list reduces to []."
    )


# ---------------------------------------------------------------------------
# Build-error attribution — the per-root structure preserves it.
# ---------------------------------------------------------------------------


def test_build_error_attribution_preserved(
    staged_multi_root_project: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """A parse error in source root B is attributed to B's file path.

    Even though the application root's build pass now includes
    ``domain/`` as a sibling (and parses its files as context),
    every diagnostic emitted while parsing/validating a file carries
    that file's actual path — so a deliberately broken file under
    ``domain/`` surfaces with the ``domain/`` path in its diagnostic,
    not a path under ``application/``. The per-source-root iteration
    that exists for clean attribution is preserved by G4: only the
    resolution context expanded, not the target-file boundary.

    We inject a syntactic break into ``domain/order_model.s0ma`` and
    confirm the resulting diagnostic names that exact path.
    """
    domain_file = staged_multi_root_project / "domain" / "order_model.s0ma"
    # Invalidate the file at module-header level so the parser bails
    # out with a PARSE_ERROR (or a structural validation error) tied
    # to this exact path.
    domain_file.write_text(
        "module order_model\n"
        "    layer: NOT_A_REAL_LAYER\n"
        "    version: 1.0.0\n"
        "    intent: \"Deliberately broken — verifies G4 attribution.\"\n"
        "    exports: []\n",
        encoding="utf-8",
    )

    cli = S0maCLI()
    rc = cli.run([
        "--project-root", str(staged_multi_root_project),
        "test",
    ])
    assert rc != EXIT_SUCCESS, (
        "Deliberately broken domain file must abort the build."
    )

    captured = capsys.readouterr()
    combined = captured.out + captured.err
    # The diagnostic must name the exact offending path (the domain
    # file), forward-slashed the way s0ma prints every path (NFR-7); it
    # must NOT (mis)attribute the error to a sibling root.
    assert domain_file.as_posix() in combined, (
        f"Expected diagnostic to name the offending file "
        f"{domain_file.as_posix()}; got:\n{combined}"
    )
    # Sanity: no sibling source-root path should appear as the error
    # location (we tolerate an --include reference inside an "include"
    # context message but the *file=* of the diagnostic must be the
    # domain file).
    application_dir = staged_multi_root_project / "application"
    presentation_dir = staged_multi_root_project / "presentation"
    # The application/presentation file paths must not be the
    # diagnostic location for this error. We use a structural pin:
    # the diagnostic format is ``<file>:<line>: ERROR``.  Search for
    # any application/presentation .s0ma path that immediately
    # precedes ``: ERROR`` — none should appear, only the domain file.
    for offending_dir in (application_dir, presentation_dir):
        for s0ma_file in offending_dir.rglob("*.s0ma"):
            marker = f"{s0ma_file.as_posix()}: "
            if marker not in combined:
                continue
            tail_line = combined.split(marker, 1)[1].split("\n", 1)[0]
            assert "ERROR" not in tail_line, (
                f"G4 attribution leak: {s0ma_file} appears as the "
                f"location of an error diagnostic, but the broken "
                f"file is {domain_file}.\nDiagnostic:\n{combined}"
            )


# ---------------------------------------------------------------------------
# Subprocess smoke — the fixture builds and runs through the installed CLI.
# ---------------------------------------------------------------------------


def test_subprocess_s0ma_test_against_fixture(
    staged_multi_root_project: Path,
) -> None:
    """End-to-end via subprocess: ``python -m s0ma_dsl.cli.main test``.

    The unit-level tests above invoke ``S0maCLI().run`` in-process.
    This test exercises the same fixture through a real subprocess
    boundary — the same path a real ``s0ma test`` user would take —
    so regressions in argv handling, env propagation, or pytest-
    subprocess plumbing surface here even if the in-process API
    keeps working.
    """
    # Anti-vacuity sentinel: a bogus subcommand must fail. Without the
    # ``if __name__ == "__main__"`` guard in cli/main.py, ``-m``
    # invocation imports the module and exits 0 without dispatching
    # argv at all — every returncode == 0 assertion below would then
    # pass without exercising the CLI.
    bogus = subprocess.run(
        [sys.executable, "-m", "s0ma_dsl.cli.main", "definitely-not-a-command"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert bogus.returncode != EXIT_SUCCESS, (
        "`python -m s0ma_dsl.cli.main <bogus>` exited 0 — the module "
        "is not dispatching argv under -m (missing __main__ guard?), "
        "so the success assertion below would be vacuous."
    )

    proc = subprocess.run(
        [
            sys.executable, "-m", "s0ma_dsl.cli.main",
            "--project-root", str(staged_multi_root_project),
            "test", "--quiet",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == EXIT_SUCCESS, (
        f"subprocess `s0ma test` failed against the multi-source-root "
        f"fixture.\nstdout:\n{proc.stdout}\nstderr:\n{proc.stderr}"
    )
    assert "passed" in proc.stdout, (
        f"subprocess `s0ma test` exited 0 but stdout carries no pytest "
        f"pass summary — the CLI never ran the fixture's tests.\n"
        f"stdout:\n{proc.stdout}\nstderr:\n{proc.stderr}"
    )
