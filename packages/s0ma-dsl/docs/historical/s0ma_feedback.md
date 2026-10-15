# s0ma Framework Feedback

Logged during ax0n development as issues, observations, or suggestions arise.

Please annotate the current milestone, a number/title, issue, resolution, and suggestion about how to improve s0ma (if appropriate). Please refer to the SAMPLE FEEDBACK below.

---
## SAMPLE FEEDBACK

### 2026-02-15 — Milestone 1 (Project Scaffolding)

#### 1. Package name mismatch in documentation

**Issue:** The PRD (Section 4.2) documents the s0ma dependency as `"s0ma"` in `pyproject.toml`, but the actual published package name is `s0ma-framework`. This caused the initial `pip install -e ".[dev]"` to fail with `ERROR: No matching distribution found for s0ma`.

**Resolution:** Changed the dependency to `"s0ma-framework"` in st3mcell's `pyproject.toml`.

**Suggestion:** The s0ma user guide (Section 1.1) correctly shows `pip install s0ma-framework`, but downstream documentation (like the PRD) should consistently use the pip package name `s0ma-framework` rather than the import name `s0ma`. Alternatively, consider adding a note in the user guide about this distinction.

---

