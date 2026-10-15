#!/usr/bin/env python3
"""s0ma Self-Check — cross-platform verification script.

Runs all verification steps in order:
1. Type checking (mypy --strict)
2. Linting (ruff)
3. Bootstrap test (Phase 1 — can the system describe itself?)
4. Self-model test (Phase 2 — does the self-model match reality?)
5. Full test suite with coverage

If any step fails, the script exits with a non-zero code.
The bootstrap test runs BEFORE the full suite — if the system
can't describe itself, other tests are meaningless.
The self-model test runs next — if the verification engine can't
verify itself, its results on other code are untrustworthy.
"""

import subprocess
import sys


def _run(label: str, cmd: list[str]) -> None:
    """Run a command, printing its label and checking for failure."""
    print(f"\n{'=' * 60}")
    print(f"  {label}")
    print(f"{'=' * 60}")
    result = subprocess.run(cmd, cwd=None)
    if result.returncode != 0:
        print(f"\nFAILED: {label}")
        sys.exit(result.returncode)
    print(f"  PASSED: {label}")


def main() -> None:
    print("=== s0ma Self-Check ===\n")

    python = sys.executable

    _run(
        "Step 1: Type checking (mypy --strict)",
        [python, "-m", "mypy", "src/s0ma/", "--strict"],
    )
    _run(
        "Step 2: Linting (ruff)",
        [python, "-m", "ruff", "check", "src/s0ma/"],
    )
    _run(
        "Step 3: Bootstrap test (Phase 1 — can it describe itself?)",
        [python, "-m", "pytest", "tests/test_bootstrap.py", "-v"],
    )
    _run(
        "Step 4: Self-model test (Phase 2 — does the model match reality?)",
        [python, "-m", "pytest", "tests/test_self_model.py", "-v"],
    )
    _run(
        "Step 5: Full test suite with coverage",
        [
            python, "-m", "pytest",
            "--cov=s0ma", "--cov-report=term-missing",
        ],
    )

    print("\n" + "=" * 60)
    print("  === All checks passed ===")
    print("=" * 60)


if __name__ == "__main__":
    main()
