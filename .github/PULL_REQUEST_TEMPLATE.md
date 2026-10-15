Thank you for this. Before you spend more time on it, one thing worth knowing:

**During the beta, pull requests are by invitation.** Please open an
[issue](https://github.com/kn0w-thyself/s0ma/issues) or a
[discussion](https://github.com/kn0w-thyself/s0ma/discussions) first, and we
will talk about it there. If it is something we should build, we will say so and
invite the pull request.

That is not a brush-off, and it is not about the quality of your work. It is
three practical things:

- **One maintainer.** A pull request nobody has time to review is worse for you
  than a "not yet" — it sits, it goes stale, and the work was for nothing.
- **A gated build.** A change has to pass the whole gate, and several parts of
  this repository are generated from other parts, so a reasonable-looking edit
  can be in the wrong file. A short conversation first usually saves a rewrite.
- **A sign-off we have to get right.** An accepted change has to arrive with
  its provenance clear and under the licence of the package it lands in. That
  is easier to agree before the code is written than after.

Issues, bug reports, questions and discussions are welcome from anybody, today,
with no invitation at all.
[CONTRIBUTING.md](https://github.com/kn0w-thyself/s0ma/blob/main/CONTRIBUTING.md)
says where each of them goes.

---

## If your pull request was invited

Delete everything above this line and tell us what the change does and why.
Then, before you mark it ready:

- [ ] **The gate is green.** `uv run python scripts/check.py` — all stages, no
      exceptions. It is what CI runs.
- [ ] **There is a `CHANGELOG.md` entry** under `## [Unreleased]`, if the change
      is one a user would notice.
- [ ] **Documentation is updated through the documentation loop**, if behaviour
      changed. See
      [maintaining the documentation](https://github.com/kn0w-thyself/s0ma/blob/main/docs/operations/docs-maintenance.md)
      — hand-editing a generated file loses the edit at the next build.
- [ ] **Every commit is signed off.** `git commit -s` adds the line. It means
      you agree to the [Developer Certificate of Origin](https://developercertificate.org/):
      that you wrote this, or have the right to send it, and that it may be
      shipped under the licence of the package it lands in.

### What the change does

<!-- What it does, and why. Link the issue or discussion it came from. -->

### How you checked it

<!-- The commands you ran and what they said. New behaviour ships with tests. -->
