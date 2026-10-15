"""Tests for ``scripts/scan_secrets.py`` — the export's last look at a tree.

A secret scanner is the classic gate that becomes decoration without
anyone noticing. Every one of its rules reports by *matching*; a pattern
narrowed by an edit, a walk pointed at the wrong directory, or an
allowlist entry that quietly widened all produce the same output as a
clean tree — the word PASS. So the proofs here are mostly red ones: a
planted secret of each shape, and a required finding.

Three things are tested separately because they fail separately:

* **The rules**, against a tree with one of each shape planted in it.
  One is planted twice — inside the allowlist's reach and outside it — so
  the allowlist is proved to exempt a path rather than a pattern.
* **The redaction of the report.** A scanner that echoes what it finds
  moves the secret into a terminal history and a CI log. The assertion is
  that the whole match never appears in the output.
* **The gitleaks branch**, with a fake ``gitleaks`` on PATH. It is not
  installed on the machine this was written on, and an untested branch is
  a branch that fails the first time it is needed — on publication day.

This module deliberately carries strings shaped like credentials. None is
real; the scanner's own ``ALLOWLIST`` names this file with that reason,
and a test below asserts that the entry is there, so deleting it turns a
test red rather than turning the repository's own scan red.

No network, no writes outside ``tmp_path``.
"""

from __future__ import annotations

import importlib.util
import json
import os
import shutil
import stat
import subprocess
import sys
from functools import cache
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from types import ModuleType

#: The monorepo root (this file: packages/s0ma-dsl/tests/<file>).
REPO_ROOT = Path(__file__).resolve().parents[3]
SCRIPT = REPO_ROOT / "scripts" / "scan_secrets.py"

#: Planted values, assembled at run time from halves. Written this way so
#: that a crude grep of the repository for a credential shape finds the
#: shape in the scanner's own rules and here, and in neither case finds
#: something that looks like a pasted secret.
FAKE_STRIPE = "sk_" + "live_" + "0123456789abcdefghij"
FAKE_GITHUB = "ghp_" + "0123456789abcdefghijklmnopqrstuvwxyz"
FAKE_AWS = "AKIA" + "IOSFODNN7EXAMPLE"
FAKE_SLACK = "xoxb-" + "1234567890-abcdefghij"
FAKE_S0MA_KEY = "s0ma_" + "test_" + "abcdefghijkl"
FAKE_ACCOUNT = "0123456789abcdef0123456789abcdef"
FAKE_PRIVATE_KEY = "-----BEGIN RSA PRIVATE KEY-----"


@cache
def module() -> ModuleType:
    """Import the script by path, the way the other script tests do."""
    spec = importlib.util.spec_from_file_location("scan_secrets_under_test", SCRIPT)
    assert spec is not None and spec.loader is not None
    loaded = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = loaded  # registered before execution, for dataclasses
    spec.loader.exec_module(loaded)
    return loaded


def plant(root: Path) -> None:
    """A tiny tree with one of every shape the scanner looks for."""
    (root / "src").mkdir(parents=True, exist_ok=True)
    (root / "src" / "config.py").write_text(
        f'STRIPE = "{FAKE_STRIPE}"\n'
        f'GITHUB = "{FAKE_GITHUB}"\n'
        f'AWS = "{FAKE_AWS}"\n'
        f'SLACK = "{FAKE_SLACK}"\n'
        f'LICENCE = "{FAKE_S0MA_KEY}"\n'
        f"CLOUDFLARE_ACCOUNT_ID: {FAKE_ACCOUNT}\n"
        f'password = "hunter2hunter2hunter2"\n'
        f"{FAKE_PRIVATE_KEY}\n",
        encoding="utf-8",
        newline="\n",
    )
    (root / "README.md").write_text(
        "Write to somebody@elsewhere.test or support@kn0wthyself.ai.\n",
        encoding="utf-8",
        newline="\n",
    )


# ---------------------------------------------------------------------------
# The rules
# ---------------------------------------------------------------------------


class TestEveryShapeIsFound:
    """One planted value per rule, and a required finding for each."""

    @pytest.fixture()
    def findings(self, tmp_path: Path) -> dict[str, list[object]]:
        plant(tmp_path)
        report = module().scan_tree(tmp_path, allowlist=())
        grouped: dict[str, list[object]] = {}
        for finding in report.findings:
            grouped.setdefault(finding.rule, []).append(finding)
        return grouped

    @pytest.mark.parametrize(
        "rule",
        [
            "private-key",
            "aws-access-key-id",
            "github-token",
            "stripe-key",
            "slack-token",
            "s0ma-key",
            "account-identifier",
            "assigned-secret",
            "email",
        ],
    )
    def test_the_rule_reports(self, findings: dict[str, list[object]], rule: str) -> None:
        assert rule in findings, sorted(findings)

    def test_an_allowed_domain_is_not_reported(
        self, findings: dict[str, list[object]]
    ) -> None:
        """The support address is on the allowlist; the other one is not."""
        addresses = [str(item) for item in findings["email"]]
        assert len(addresses) == 1, addresses

    def test_source_code_kept_as_a_json_string_is_not_an_address(self, tmp_path: Path) -> None:
        """Found by the first export of the branch tip: three false refusals.

        The replayed evidence files hold whole Python fixtures as JSON strings,
        so a decorator on a new line is written ``\\n@pytest.fixture`` - and the
        ``n`` of the escape read as the local part of an address.
        """
        (tmp_path / "evidence.json").write_text(
            '{"content": "import pytest\\n\\n@pytest.fixture\\ndef shelf():\\n    return 1\\n"}\n',
            encoding="utf-8",
            newline="\n",
        )
        report = module().scan_tree(tmp_path, allowlist=())
        assert [item for item in report.findings if item.rule == "email"] == []

    def test_a_real_address_after_a_written_newline_is_still_found(self, tmp_path: Path) -> None:
        """The other direction: blanking the escape must not hide an address."""
        (tmp_path / "note.json").write_text(
            '{"content": "write to\\nsomebody@elsewhere.test today"}\n',
            encoding="utf-8",
            newline="\n",
        )
        report = module().scan_tree(tmp_path, allowlist=())
        emails = [item for item in report.findings if item.rule == "email"]
        assert len(emails) == 1, report.findings
        assert dict(report.email_domains) == {"elsewhere.test": 1}

    def test_a_clean_tree_reports_nothing(self, tmp_path: Path) -> None:
        """The other side of it: the rules are not red about everything."""
        (tmp_path / "a.py").write_text(
            "TOKEN_NAME = 'authorization'\nurl = 'https://example.com/x'\n",
            encoding="utf-8",
            newline="\n",
        )
        report = module().scan_tree(tmp_path, allowlist=())
        assert report.findings == ()
        assert report.scanned == 1


class TestTheAllowlistExemptsAPathNotAPattern:
    """The same shape, planted twice: once covered, once not."""

    def test_only_the_named_path_is_exempt(self, tmp_path: Path) -> None:
        scan = module()
        (tmp_path / "fixtures").mkdir()
        for name in ("fixtures/corpus.jsonl", "live.py"):
            (tmp_path / name).write_text(
                f'key = "{FAKE_STRIPE}"\n', encoding="utf-8", newline="\n"
            )
        report = scan.scan_tree(
            tmp_path,
            allowlist=(scan.Allowed("fixtures/corpus.jsonl", "stripe-key", "the corpus"),),
        )
        paths = sorted({finding.path for finding in report.findings})
        assert paths == ["live.py"]
        assert report.exempt == 1

    def test_an_entry_whose_file_is_here_and_matches_nothing_is_reported(
        self, tmp_path: Path
    ) -> None:
        scan = module()
        (tmp_path / "quiet.py").write_text("x = 1\n", encoding="utf-8", newline="\n")
        report = scan.scan_tree(
            tmp_path, allowlist=(scan.Allowed("quiet.py", "*", "used to carry one"),)
        )
        assert [entry.path for entry in report.unused_allowlist] == ["quiet.py"]

    def test_an_entry_whose_file_is_absent_is_not_reported(self, tmp_path: Path) -> None:
        """The export legitimately withholds files an entry names.

        Reporting those would put a line per withheld file in front of
        the reader, and a report nobody finishes reading is a report.
        """
        scan = module()
        (tmp_path / "quiet.py").write_text("x = 1\n", encoding="utf-8", newline="\n")
        report = scan.scan_tree(
            tmp_path, allowlist=(scan.Allowed("not/here.py", "*", "withheld"),)
        )
        assert report.unused_allowlist == ()


class TestTheReportNeverEchoesAMatch:
    """Redaction, on the output the reader actually sees."""

    def test_the_whole_secret_is_not_printed(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        plant(tmp_path)
        scan = module()
        scan.print_report(scan.scan_tree(tmp_path, allowlist=()), tmp_path)
        printed = capsys.readouterr().out
        for secret in (FAKE_STRIPE, FAKE_GITHUB, FAKE_AWS, FAKE_SLACK, FAKE_S0MA_KEY):
            assert secret not in printed
            assert secret[:4] in printed

    def test_a_short_match_is_reported_by_length_alone(self) -> None:
        """Four plus four would be most of a nine-character match."""
        assert module().redact("abcdefghi") == "<9 characters>"
        assert module().redact("abcdefghij") == "abcd...ghij"


class TestTheWalkSkipsWhatIsNotTheTree:
    def test_a_virtual_environment_is_not_scanned(self, tmp_path: Path) -> None:
        (tmp_path / ".venv" / "lib").mkdir(parents=True)
        (tmp_path / ".venv" / "lib" / "dep.py").write_text(
            f'k = "{FAKE_STRIPE}"\n', encoding="utf-8", newline="\n"
        )
        (tmp_path / "ok.py").write_text("x = 1\n", encoding="utf-8", newline="\n")
        report = module().scan_tree(tmp_path, allowlist=())
        assert report.findings == ()
        assert report.scanned == 1

    def test_a_binary_file_is_skipped(self, tmp_path: Path) -> None:
        (tmp_path / "blob.bin").write_bytes(b"\x00\x01" + FAKE_STRIPE.encode())
        report = module().scan_tree(tmp_path, allowlist=())
        assert report.findings == ()


# ---------------------------------------------------------------------------
# The gitleaks branch
# ---------------------------------------------------------------------------


def fake_gitleaks(directory: Path, findings: list[dict[str, object]]) -> Path:
    """A ``gitleaks`` on PATH that writes the report it is asked for."""
    if os.name == "nt":  # pragma: no cover - the tool refuses Windows anyway
        pytest.skip("the fake executable is a POSIX shell script")
    directory.mkdir(parents=True, exist_ok=True)
    executable = directory / "gitleaks"
    executable.write_text(
        "#!/usr/bin/env python3\n"
        "import json, sys\n"
        "args = sys.argv[1:]\n"
        "path = args[args.index('--report-path') + 1]\n"
        f"open(path, 'w').write({json.dumps(json.dumps(findings))})\n",
        encoding="utf-8",
        newline="\n",
    )
    executable.chmod(executable.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP)
    return executable


class TestGitleaksIsUsedWhenItIsThere:
    def test_its_findings_are_translated_into_our_report(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        scan = module()
        tree = tmp_path / "tree"
        tree.mkdir()
        (tree / "a.py").write_text("x = 1\n", encoding="utf-8", newline="\n")
        fake_gitleaks(
            tmp_path / "bin",
            [{"File": "a.py", "StartLine": 7, "RuleID": "stripe", "Secret": FAKE_STRIPE}],
        )
        monkeypatch.setenv("PATH", str(tmp_path / "bin") + os.pathsep + os.environ["PATH"])

        report = scan.scan(tree, allowlist=())
        assert report.engine == "gitleaks"
        assert [(f.path, f.lineno, f.rule) for f in report.findings] == [
            ("a.py", 7, "gitleaks:stripe")
        ]
        assert FAKE_STRIPE not in report.findings[0].shown

    def test_its_findings_obey_the_allowlist(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        scan = module()
        tree = tmp_path / "tree"
        tree.mkdir()
        (tree / "a.py").write_text("x = 1\n", encoding="utf-8", newline="\n")
        fake_gitleaks(
            tmp_path / "bin",
            [{"File": "a.py", "StartLine": 7, "RuleID": "stripe", "Secret": FAKE_STRIPE}],
        )
        monkeypatch.setenv("PATH", str(tmp_path / "bin") + os.pathsep + os.environ["PATH"])
        report = scan.scan(tree, allowlist=(scan.Allowed("a.py", "*", "a fixture"),))
        assert report.findings == ()

    def test_no_gitleaks_falls_back_to_our_own_rules(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        plant(tmp_path)
        monkeypatch.setattr(module(), "gitleaks_path", lambda: None)
        report = module().scan(tmp_path, allowlist=())
        assert report.engine == "own-rules"
        assert report.findings


# ---------------------------------------------------------------------------
# The command line
# ---------------------------------------------------------------------------


class TestTheCommandLine:
    def _run(self, *args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(SCRIPT), *args],
            capture_output=True,
            text=True,
            encoding="utf-8",
            check=False,
        )

    def test_a_planted_secret_exits_one(self, tmp_path: Path) -> None:
        plant(tmp_path)
        done = self._run(str(tmp_path), "--no-gitleaks")
        assert done.returncode == 1
        assert "FOUND" in done.stdout
        assert FAKE_STRIPE not in done.stdout

    def test_a_clean_tree_exits_zero_and_says_what_it_read(self, tmp_path: Path) -> None:
        (tmp_path / "a.py").write_text("x = 1\n", encoding="utf-8", newline="\n")
        done = self._run(str(tmp_path), "--no-gitleaks")
        assert done.returncode == 0, done.stdout
        assert "secret scan: PASS" in done.stdout
        assert "1 text file(s)" in done.stdout

    def test_a_missing_directory_is_refused(self, tmp_path: Path) -> None:
        done = self._run(str(tmp_path / "nope"))
        assert done.returncode == 1
        assert "is not a directory" in done.stdout

    def test_a_rules_file_adds_allowlist_entries(self, tmp_path: Path) -> None:
        tree = tmp_path / "tree"
        tree.mkdir()
        (tree / "fixture.py").write_text(
            f'k = "{FAKE_STRIPE}"\n', encoding="utf-8", newline="\n"
        )
        rules = tmp_path / "rules.toml"
        rules.write_text(
            "[secret_scan]\n"
            'email_domains = ["elsewhere.test"]\n'
            "[[secret_scan.allow]]\n"
            'path = "fixture.py"\n'
            'rule = "*"\n'
            'why = "a deliberate fake"\n',
            encoding="utf-8",
            newline="\n",
        )
        done = self._run(str(tree), "--no-gitleaks", "--rules", str(rules))
        assert done.returncode == 0, done.stdout

    def test_a_rules_entry_without_a_reason_is_refused(self, tmp_path: Path) -> None:
        rules = tmp_path / "rules.toml"
        rules.write_text(
            '[secret_scan]\n[[secret_scan.allow]]\npath = "x"\nrule = "*"\n',
            encoding="utf-8",
            newline="\n",
        )
        done = self._run(str(tmp_path), "--no-gitleaks", "--rules", str(rules))
        assert done.returncode == 1
        assert "path, rule and why" in done.stdout


# ---------------------------------------------------------------------------
# The shipped allowlist, on the real tree
# ---------------------------------------------------------------------------


class TestTheShippedAllowlist:
    def test_this_suite_is_named_in_it(self) -> None:
        """This file plants credentials on purpose and says so there."""
        entries = [entry.path for entry in module().ALLOWLIST]
        assert "packages/s0ma-dsl/tests/test_scan_secrets_script.py" in entries

    def test_every_entry_carries_a_justification(self) -> None:
        for entry in module().ALLOWLIST:
            assert len(entry.why.split()) >= 6, entry

    def test_no_shipped_entry_is_a_bare_wildcard_over_the_tree(self) -> None:
        """An exemption is for a file, not for the repository."""
        for entry in module().ALLOWLIST:
            assert entry.path not in ("*", "**", ""), entry

    @pytest.mark.skipif(not (REPO_ROOT / ".git").exists(), reason="not a git checkout")
    def test_the_scan_of_this_repository_reports_no_stale_entry(self) -> None:
        """A live run: every entry whose file is here still matches.

        Cheap enough to run (about a second over 1,100 files) and it is
        the only thing that keeps the shipped justifications honest.
        """
        scan = module()
        report = scan.scan_tree(REPO_ROOT)
        assert report.unused_allowlist == (), [
            entry.path for entry in report.unused_allowlist
        ]
        assert report.scanned > 500, report.scanned


@pytest.mark.skipif(shutil.which("gitleaks") is not None, reason="gitleaks is installed")
def test_the_fallback_is_the_engine_on_this_machine() -> None:
    """Recorded rather than assumed: gitleaks is not installed here.

    If this test starts failing, gitleaks arrived on the machine and the
    other branch is the one that runs — which is the better outcome, and
    the reason the branch above is tested with a fake.
    """
    assert module().gitleaks_path() is None
