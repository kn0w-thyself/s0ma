#!/usr/bin/env python3
"""Secret scan over a directory tree — the export's last look before publication.

Fresh history means only the *tree* has to be scanned: the public repository
starts at one commit, so nothing a scan of the working files misses can be
recovered from an earlier one. That is the whole reason this script is a
tree scanner and not a history scanner.

Two engines, one report:

* **``gitleaks``, when it is on PATH.** It is the better scanner and it is
  kept current by people who do this full time. This script shells out to
  it, reads its JSON report, and prints the same one-line findings it
  prints for its own pass, so the report a reader sees does not depend on
  which engine produced it.
* **This script's own regular expressions otherwise.** ``gitleaks`` was not
  installed on the machine where the export tool was written, and an export
  that cannot be checked on the owner's own laptop is an export nobody
  checks. The rules below are the ones the 2026-09-17 sweep used, promoted
  from a one-off command line into something with tests and an allowlist.

**A finding is never echoed in full.** Each line names the file, the line
number, the rule, and the first and last four characters of the match.
Enough to find it; not enough to leak it into a terminal history, a CI log,
or a report pasted into a chat window.

Deliberately fake secrets exist in this repository and must keep existing:
the feedback redaction corpus cannot prove it redacts a Stripe key without
carrying something Stripe-key-shaped. ``ALLOWLIST`` names those paths, one
justification each, in the shape ``scripts/check_links.py`` uses — and an
allowlist entry that stops matching anything is reported, so an exemption
cannot outlive its reason.

**Email addresses are scanned too**, because the thing most likely to reach
a public repository by accident is not a credential but a person. Any
address whose domain is not on ``EMAIL_DOMAINS`` is reported so the owner
can rule on it; the report lists every domain it saw, including the
allowed ones, so the allowlist itself can be audited from the output.

Usage (no network, deterministic, same answer on every platform):

    uv run python scripts/scan_secrets.py <directory>
    uv run python scripts/scan_secrets.py <directory> --rules scripts/public_export.toml
    uv run python scripts/scan_secrets.py <directory> --no-gitleaks

Exit code 0 when the tree is clean, 1 when anything was found or the scan
could not be trusted.

Owner-run on macOS or Linux, and on Windows: it is pure ``pathlib`` and
reads every file as bytes, so it carries no POSIX assumption.
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from fnmatch import fnmatch
from pathlib import Path
from typing import Iterable, Iterator, Sequence

#: Directory names pruned at any depth. Build output, virtual environments
#: and tool caches are not the published tree, and scanning a ``.venv``
#: means scanning every dependency's test fixtures.
PRUNED_DIR_NAMES: frozenset[str] = frozenset(
    {
        ".git",
        ".venv",
        "venv",
        ".mypy_cache",
        ".pytest_cache",
        ".ruff_cache",
        ".hypothesis",
        "__pycache__",
        "node_modules",
        ".s0ma.cache",
        "__s0ma_cache__",
        "dist",
        "build",
    }
)

#: Read at most this many bytes of any one file. A secret lives on a line;
#: a 40 MB generated JSON does not become more interesting after the first
#: few megabytes, and the cap keeps a scan of a tree with large artifacts
#: from turning into a memory event.
MAX_FILE_BYTES = 8 * 1024 * 1024

#: Email domains that are fine to publish. Everything else is reported for
#: a ruling rather than judged here — an address is a person, and which
#: people may appear in a public repository is not a decision a regular
#: expression gets to take.
EMAIL_DOMAINS: frozenset[str] = frozenset(
    {
        # The product's own canonical domain (plan 5, FD-5).
        "kn0wthyself.ai",
        # Reserved-for-documentation domains (RFC 2606 / RFC 6761).
        "example.com",
        "example.org",
        "example.net",
        "example.invalid",
        "example.co.uk",
        # Git and GitHub's own machine addresses.
        "github.com",
        "users.noreply.github.com",
        "noreply.github.com",
        # Anthropic, for the co-authorship trailer and the plugin manifests.
        "anthropic.com",
    }
)


@dataclass(frozen=True)
class Rule:
    """One named pattern, and the plain sentence that says what it finds."""

    name: str
    pattern: re.Pattern[str]
    what: str


@dataclass(frozen=True)
class Allowed:
    """One path that deliberately carries something a rule matches.

    ``path`` is a tree-relative glob and ``rule`` is the rule name it is
    exempt from (``"*"`` for every rule), so an entry covers one file and
    one class of finding rather than switching the scan off wholesale.
    """

    path: str
    rule: str
    why: str


#: Deliberately-planted matches. Every one of these was read before it was
#: written down; none is a real credential. Reach for this last: a match
#: is nearly always a real finding, and the honest fixes are to delete the
#: value, to move it to a secret, or to shorten a documented example until
#: it no longer looks like the thing it documents.
ALLOWLIST: tuple[Allowed, ...] = (
    Allowed(
        "packages/s0ma-dsl/tests/fixtures/feedback_redaction_corpus.jsonl",
        "*",
        "the redaction corpus: fake keys and tokens are its inputs — a "
        "redactor cannot be proved against a corpus with nothing to redact",
    ),
    Allowed(
        "packages/s0ma-dsl/tests/test_feedback_redact.py",
        "*",
        "the redaction suite's inline cases, same reason as the corpus",
    ),
    Allowed(
        "packages/s0ma-dsl/tests/test_cli_feedback.py",
        "*",
        "fixture keys and access codes for the feedback command suite",
    ),
    Allowed(
        "packages/s0ma-dsl/tests/test_feedback_client.py",
        "*",
        "fixture keys and access codes for the feedback client suite",
    ),
    Allowed(
        "packages/s0ma-dsl/tests/test_install_script.py",
        "s0ma-key",
        "the installer suite's placeholder keys, spelled REDACTME and VALUE",
    ),
    Allowed(
        "packages/s0ma-dsl/tests/test_verify_served_script.py",
        "s0ma-key",
        "the verify-served suite's placeholder smoke key",
    ),
    Allowed(
        "packages/s0ma-dsl/tests/test_feedback_model.py",
        "email",
        "the fixture account on a client block, whose domain is x.com",
    ),
    Allowed(
        "packages/s0ma-dsl/tests/test_scan_secrets_script.py",
        "*",
        "this scanner's own suite: it plants one of every shape it looks for, "
        "because a scanner proved against nothing is proved against nothing",
    ),
    Allowed(
        "integrations/launcher/tests/*",
        "s0ma-key",
        "the launcher suite's fixture key, spelled `not_a_real_key`",
    ),
    Allowed(
        "docs/archive/pre-monorepo/*/plans/s0ma-PRD.md",
        "email",
        "a 2009 research paper whose title reads as an address is cited in "
        "the frozen pre-monorepo requirements document",
    ),
)


#: The rules. Ordered so the specific ones report before the catch-all
#: generic assignment, and named so an allowlist entry can exempt one.
RULES: tuple[Rule, ...] = (
    Rule(
        "private-key",
        re.compile(r"-----BEGIN (?:[A-Z ]+ )?PRIVATE KEY-----"),
        "a private key header",
    ),
    Rule(
        "aws-access-key-id",
        re.compile(r"\b(?:AKIA|ASIA|AGPA|AIDA|AROA|AIPA|ANPA|ANVA|ABIA)[0-9A-Z]{16}\b"),
        "an AWS access key id",
    ),
    Rule(
        "github-token",
        re.compile(r"\b(?:gh[pousr]_[A-Za-z0-9]{16,}|github_pat_[A-Za-z0-9_]{20,})\b"),
        "a GitHub token",
    ),
    Rule(
        "stripe-key",
        re.compile(r"\b(?:sk_live_|sk_test_|rk_live_|rk_test_|whsec_)[A-Za-z0-9]{16,}\b"),
        "a Stripe key or webhook signing secret",
    ),
    Rule(
        "slack-token",
        re.compile(r"\bxox[abeoprs]-[A-Za-z0-9-]{10,}\b"),
        "a Slack token",
    ),
    Rule(
        "s0ma-key",
        re.compile(r"\bs0ma_(?:test|live|fb)_[A-Za-z0-9_-]{8,}\b"),
        "a s0ma licence key or feedback access code",
    ),
    Rule(
        "account-identifier",
        re.compile(
            r"(?i)\b[a-z0-9_]*(?:account|zone)[a-z0-9_]*(?:_?id)?\b"
            r"\s*[:=]\s*[\"']?[0-9a-f]{32}\b"
        ),
        "a 32-hex value assigned to something named like an account or zone",
    ),
    Rule(
        "assigned-secret",
        re.compile(r"(?i)\b(?:api[_-]?key|secret|token|password)\b\s*[:=]\s*[\"'][^\"']{16,}[\"']"),
        "a quoted value of at least sixteen characters assigned to a "
        "secret-sounding name",
    ),
)

#: An email address, matched loosely on purpose: a scan that misses an
#: address because it carried a plus tag has failed at its one job. The
#: domain is what is judged.
_EMAIL_RE = re.compile(r"\b[A-Za-z0-9._%+-]+@((?:[A-Za-z0-9-]+\.)+[A-Za-z]{2,})\b")

#: A written-out escape (backslash then ``n``, ``r`` or ``t``) inside a quoted
#: string. Source code kept as a JSON string - the replayed evidence files hold
#: whole Python fixtures that way - writes a decorator on a new line as
#: ``\n@pytest.fixture``, and the letter of the escape then reads as the local
#: part of an address at the domain "pytest.fixture". Blanking the escape for
#: the email pass, rather than refusing a match that follows a backslash, keeps
#: the other direction true as well: a real address written straight after an
#: escaped newline is still found, without the stray letter glued to it.
_WRITTEN_ESCAPE_RE = re.compile(r"\\[nrt]")


@dataclass(frozen=True)
class Finding:
    """One reported line. ``shown`` is the redacted match, never the match."""

    path: str
    lineno: int
    rule: str
    shown: str

    @property
    def sort_key(self) -> tuple[str, int, str]:
        return (self.path, self.lineno, self.rule)


def redact(match: str) -> str:
    """The first and last four characters, and nothing in between.

    A match of nine characters or fewer would leak most of itself under
    that rule, so it is reported by length alone.
    """
    collapsed = " ".join(match.split())
    if len(collapsed) <= 9:
        return f"<{len(collapsed)} characters>"
    return f"{collapsed[:4]}...{collapsed[-4:]}"


def is_allowed(path: str, rule: str, allowlist: Sequence[Allowed]) -> int | None:
    """Index of the allowlist entry that exempts this finding, or ``None``."""
    for index, entry in enumerate(allowlist):
        if entry.rule not in (rule, "*"):
            continue
        if fnmatch(path, entry.path) or path == entry.path:
            return index
    return None


def scannable_files(root: Path) -> Iterator[Path]:
    """Every readable, non-pruned file under ``root``, in sorted order."""
    stack = [root]
    while stack:
        directory = stack.pop()
        try:
            entries = sorted(directory.iterdir())
        except OSError:
            continue
        for entry in entries:
            if entry.is_symlink():
                continue
            if entry.is_dir():
                if entry.name not in PRUNED_DIR_NAMES and not entry.name.endswith(".egg-info"):
                    stack.append(entry)
                continue
            if entry.is_file():
                yield entry


def _text_of(path: Path) -> str | None:
    """The file's text, or ``None`` when it is binary or unreadable."""
    try:
        data = path.read_bytes()[:MAX_FILE_BYTES]
    except OSError:
        return None
    if b"\0" in data[:8192]:  # grep -I semantics
        return None
    return data.decode("utf-8", errors="replace")


@dataclass(frozen=True)
class Report:
    """Everything one scan learned, so a caller can print or re-use it."""

    findings: tuple[Finding, ...]
    email_domains: tuple[tuple[str, int], ...]
    allowed_domains: frozenset[str]
    scanned: int
    exempt: int
    unused_allowlist: tuple[Allowed, ...]
    engine: str


def scan_tree(
    root: Path,
    *,
    allowlist: Sequence[Allowed] = ALLOWLIST,
    email_domains: Iterable[str] = EMAIL_DOMAINS,
) -> Report:
    """This script's own pass. No subprocess, no network, no writes."""
    allowed_domains = frozenset(email_domains)
    findings: list[Finding] = []
    domains: dict[str, int] = {}
    used: set[int] = set()
    present: list[str] = []
    scanned = 0
    exempt = 0

    for path in scannable_files(root):
        text = _text_of(path)
        if text is None:
            continue
        scanned += 1
        rel = path.relative_to(root).as_posix()
        present.append(rel)
        for lineno, line in enumerate(text.splitlines(), 1):
            for rule in RULES:
                for match in rule.pattern.finditer(line):
                    index = is_allowed(rel, rule.name, allowlist)
                    if index is not None:
                        used.add(index)
                        exempt += 1
                        continue
                    findings.append(Finding(rel, lineno, rule.name, redact(match.group(0))))
            for match in _EMAIL_RE.finditer(_WRITTEN_ESCAPE_RE.sub("  ", line)):
                domain = match.group(1).lower()
                domains[domain] = domains.get(domain, 0) + 1
                if domain in allowed_domains:
                    continue
                index = is_allowed(rel, "email", allowlist)
                if index is not None:
                    used.add(index)
                    exempt += 1
                    continue
                findings.append(Finding(rel, lineno, "email", redact(match.group(0))))

    return Report(
        findings=tuple(sorted(findings, key=lambda item: item.sort_key)),
        email_domains=tuple(sorted(domains.items())),
        allowed_domains=allowed_domains,
        scanned=scanned,
        exempt=exempt,
        unused_allowlist=stale_entries(allowlist, used, present),
        engine="own-rules",
    )


def stale_entries(
    allowlist: Sequence[Allowed], used: set[int], present: Sequence[str]
) -> tuple[Allowed, ...]:
    """Allowlist entries whose file is here and whose reason is not.

    An entry whose path matches nothing in this tree is not stale — the
    public export legitimately leaves files out, and an export scan that
    complained about every withheld file would train its reader to skim.
    An entry whose file IS here and matched nothing has outlived its
    justification, and that is worth a line.
    """
    stale: list[Allowed] = []
    for index, entry in enumerate(allowlist):
        if index in used:
            continue
        if any(fnmatch(rel, entry.path) or rel == entry.path for rel in present):
            stale.append(entry)
    return tuple(stale)


def gitleaks_path() -> str | None:
    """``gitleaks`` on PATH, or ``None``."""
    return shutil.which("gitleaks")


def scan_with_gitleaks(
    root: Path,
    executable: str,
    *,
    allowlist: Sequence[Allowed] = ALLOWLIST,
    email_domains: Iterable[str] = EMAIL_DOMAINS,
) -> Report:
    """Run ``gitleaks`` over the tree and translate its report.

    The email pass is this script's own either way — ``gitleaks`` looks
    for credentials, and an address that should not be published is not a
    credential. So a gitleaks run is gitleaks' findings plus our domains.
    """
    with tempfile.TemporaryDirectory() as workspace:
        report_path = Path(workspace) / "gitleaks.json"
        completed = subprocess.run(
            [
                executable,
                "detect",
                "--no-git",
                "--source",
                str(root),
                "--report-format",
                "json",
                "--report-path",
                str(report_path),
                "--exit-code",
                "0",
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )
        if completed.returncode != 0 or not report_path.is_file():
            detail = (completed.stderr or completed.stdout or "").strip().splitlines()
            raise RuntimeError(
                "gitleaks did not produce a report "
                f"(exit {completed.returncode}): {detail[-1] if detail else 'no output'}"
            )
        raw = report_path.read_text(encoding="utf-8").strip()

    parsed: list[dict[str, object]] = json.loads(raw) if raw else []
    findings: list[Finding] = []
    used: set[int] = set()
    exempt = 0
    for item in parsed:
        rel = Path(str(item.get("File", ""))).as_posix()
        if Path(rel).is_absolute():
            rel = Path(rel).relative_to(root).as_posix()
        rule = f"gitleaks:{item.get('RuleID', 'unknown')}"
        index = is_allowed(rel, rule, allowlist)
        if index is None:
            index = is_allowed(rel, "*", allowlist)
        if index is not None:
            used.add(index)
            exempt += 1
            continue
        start = item.get("StartLine", 0)
        findings.append(
            Finding(
                path=rel,
                lineno=start if isinstance(start, int) else 0,
                rule=rule,
                shown=redact(str(item.get("Secret", ""))),
            )
        )

    own = scan_tree(root, allowlist=allowlist, email_domains=email_domains)
    findings.extend(item for item in own.findings if item.rule == "email")
    return Report(
        findings=tuple(sorted(findings, key=lambda item: item.sort_key)),
        email_domains=own.email_domains,
        allowed_domains=own.allowed_domains,
        scanned=own.scanned,
        exempt=exempt + own.exempt,
        unused_allowlist=own.unused_allowlist,
        engine="gitleaks",
    )


def scan(
    root: Path,
    *,
    allowlist: Sequence[Allowed] = ALLOWLIST,
    email_domains: Iterable[str] = EMAIL_DOMAINS,
    use_gitleaks: bool = True,
) -> Report:
    """Scan ``root`` with the best engine available."""
    executable = gitleaks_path() if use_gitleaks else None
    if executable is not None:
        return scan_with_gitleaks(
            root, executable, allowlist=allowlist, email_domains=email_domains
        )
    return scan_tree(root, allowlist=allowlist, email_domains=email_domains)


def print_report(report: Report, root: Path) -> None:
    """One plain line per finding, then the domains, then the verdict."""
    for finding in report.findings:
        print(f"FOUND {finding.path}:{finding.lineno} {finding.rule} {finding.shown}")

    if report.email_domains:
        print("\nEmail domains seen (count, domain, allowed):")
        for domain, count in report.email_domains:
            mark = "allowed" if domain in report.allowed_domains else "REPORTED"
            print(f"  {count:5}  {domain:32} {mark}")

    for entry in report.unused_allowlist:
        print(
            f"UNUSED ALLOWLIST {entry.path} (rule {entry.rule}) matched nothing. "
            f"Drop the entry, or find out what moved. Reason on file: {entry.why}"
        )

    name = root.name or str(root)
    if report.findings:
        print(
            f"\nsecret scan: {len(report.findings)} finding(s) in {name}/ "
            f"({report.scanned} text file(s) read with {report.engine}, "
            f"{report.exempt} allowlisted). Read each one in the file itself; "
            f"only the first and last four characters are printed here on "
            f"purpose. A deliberate fake needs an ALLOWLIST entry in "
            f"scripts/scan_secrets.py with a one-line justification."
        )
        return
    print(
        f"secret scan: PASS - {report.scanned} text file(s) read with "
        f"{report.engine}, {report.exempt} allowlisted match(es), "
        f"{len(report.email_domains)} email domain(s) seen"
    )


def load_rules_allowlist(path: Path) -> tuple[tuple[Allowed, ...], frozenset[str]]:
    """Extra allowlist entries and domains from an export rules file.

    Read from ``[secret_scan]``; both keys optional. Entries here ADD to
    the built-ins rather than replacing them, so the standing
    justifications keep one home.
    """
    import tomllib

    with path.open("rb") as handle:
        document = tomllib.load(handle)
    section = document.get("secret_scan", {})
    if not isinstance(section, dict):
        raise ValueError(f"{path.name}: [secret_scan] is not a table")
    extra: list[Allowed] = []
    for item in section.get("allow", []):
        if not isinstance(item, dict) or not {"path", "rule", "why"} <= set(item):
            raise ValueError(
                f"{path.name}: every [[secret_scan.allow]] entry needs path, rule and why"
            )
        extra.append(Allowed(str(item["path"]), str(item["rule"]), str(item["why"])))
    domains = {str(item).lower() for item in section.get("email_domains", [])}
    return tuple(extra), frozenset(domains)


def force_utf8_streams() -> None:
    """Pin stdout/stderr to UTF-8.

    A Windows console or redirection can default to cp1252, where echoing
    a path with an em dash raises ``UnicodeEncodeError`` and kills the
    scan's own reporting. Same guard, and same reason, as
    ``scripts/check.py``; a separate process needs its own.
    """
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if callable(reconfigure):
            reconfigure(encoding="utf-8", errors="replace")


def main(argv: list[str] | None = None) -> int:
    force_utf8_streams()

    parser = argparse.ArgumentParser(description="s0ma secret scan over a directory tree")
    parser.add_argument("directory", help="the tree to scan")
    parser.add_argument(
        "--rules",
        type=Path,
        default=None,
        help="an export rules file whose [secret_scan] section adds allowlist entries",
    )
    parser.add_argument(
        "--no-gitleaks",
        action="store_true",
        help="use this script's own rules even when gitleaks is on PATH",
    )
    options = parser.parse_args(argv)

    root = Path(options.directory).resolve()
    if not root.is_dir():
        print(f"ERROR {root} is not a directory.")
        return 1

    allowlist = ALLOWLIST
    domains = EMAIL_DOMAINS
    if options.rules is not None:
        try:
            extra, extra_domains = load_rules_allowlist(options.rules)
        except (OSError, ValueError) as error:
            print(f"ERROR cannot read {options.rules}: {error}")
            return 1
        allowlist = allowlist + extra
        domains = domains | extra_domains

    try:
        report = scan(
            root,
            allowlist=allowlist,
            email_domains=domains,
            use_gitleaks=not options.no_gitleaks,
        )
    except (OSError, RuntimeError, json.JSONDecodeError) as error:
        print(f"ERROR the scan could not be completed: {error}")
        return 1

    print_report(report, root)
    return 1 if report.findings else 0


if __name__ == "__main__":
    raise SystemExit(main())
