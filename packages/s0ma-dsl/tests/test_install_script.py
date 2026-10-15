"""Tests for the single-command installer ``scripts/install.sh`` (HOST-H6).

The installer is a convenience script the *user* runs — nothing in the
toolchain imports or invokes it (plan D-1 / PRD P-6: no network in product
code, no toolchain coupling). The entitlement-gated control-plane fetch
lives ONLY in this user-run shell script. These tests are therefore
deliberately **network-free**: they only

1. assert the script is POSIX-``sh``-parseable (``sh -n``), and
2. drive its ``--dry-run`` and assert the exact command sequence it WOULD
   run (control-plane manifest fetch → one wheel download per stem in
   ``WHEEL_STEMS`` → ``uv init`` → ``uv add`` naming every wheel →
   ``s0ma doctor`` → feedback enrollment → ``claude mcp add`` →
   ``s0ma new project``), plus the missing-key loud failure and the
   license-key redaction.

``--dry-run`` executes nothing and touches no network, so this is safe on
CI. The script is referenced via a path relative to THIS test file
(``parents[3]`` is the monorepo root), and every test skips gracefully when
no POSIX ``sh`` is on PATH (``shutil.which`` is ``None``) — so the gate
stays green on Linux CI and on the Git-Bash Windows box, and never breaks a
host without ``sh``.

The feedback-enrollment step (FB-M10) adds a REAL-run dimension the dry run
cannot cover: whether a failed exchange is genuinely non-fatal, and what the
token file it writes actually looks like on disk. That is exercised by
:func:`stub_toolchain` — a temp ``bin/`` holding stub ``curl``/``uv``/
``claude`` scripts placed first on ``PATH``, with ``HOME`` pointed at a temp
directory. Still no network, still no real toolchain: the installer runs end
to end against canned control-plane replies and its side effects are then
inspected. Those tests are POSIX-only (they assert 0700/0600 modes, which
Windows ACLs do not express — the same best-effort boundary
``s0ma_dsl.feedback.state`` documents).
"""

from __future__ import annotations

import json
import os
import shutil
import stat
import subprocess
from pathlib import Path

import pytest

#: The monorepo root (this file: packages/s0ma-dsl/tests/<file>).
REPO_ROOT = Path(__file__).resolve().parents[3]
INSTALL_SH = REPO_ROOT / "scripts" / "install.sh"

#: The MCP registration line the installer must emit, verbatim from
#: docs/walkthrough.md §2 (project scope). Kept identical here so a drift in
#: either place fails this test.
MCP_ADD_LINE = "claude mcp add s0ma --scope project -- uv run s0ma-mcp"

#: The wheels the installer must ship, as bare distribution stems (the
#: ``uv add`` line names every one explicitly — their inter-deps are not on
#: PyPI). This tuple PINS the intended set: install.sh's $WHEELS drifting
#: from it — a stem dropped OR added — fails the sequence test below.
WHEEL_STEMS = ("s0ma_core", "s0ma_dsl", "s0ma_mcp", "s0ma_studi0")

#: The default control-plane host (HOST-H6 / H4 contract). The installer
#: targets this unless ``--cp-host`` overrides it.
CP_HOST = "account.kn0wthyself.ai"

#: A throwaway license key used to drive --dry-run. It must NEVER appear in
#: the dry-run output — the installer redacts it as ``Bearer ***``.
TEST_KEY = "s0ma_test_REDACTME"

#: The feedback token-exchange endpoint (docs/contracts/feedback-v1.md §2).
#: Pinned here so an installer drift from the frozen contract fails loudly.
FEEDBACK_TOKEN_ENDPOINT = "/api/feedback/token"

#: The token file the installer must write (contract §8), as it appears in
#: user-facing output. The real path is ``$HOME/.s0ma/feedback-token``.
FEEDBACK_TOKEN_DISPLAY = "~/.s0ma/feedback-token"

#: The four keys ``s0ma_dsl.feedback.tokens.StoredToken.to_dict`` writes —
#: exactly what the installer's own writer must produce, no more, no less.
TOKEN_FILE_KEYS = {"token", "token_prefix", "expires_ts", "cp_host"}

#: Resolve POSIX sh once; skip the whole module if it is unavailable.
_SH = shutil.which("sh")


def _require_sh() -> str:
    if _SH is None:
        pytest.skip("POSIX sh unavailable")
    return _SH


def _dry_run(*args: str, key: str | None = TEST_KEY) -> str:
    """Run ``install.sh <args> --key <key> --dry-run`` and return combined output.

    ``--dry-run`` prints the command sequence and exits 0 without touching
    the network or the filesystem target. A key is supplied by default (the
    installer requires one); pass ``key=None`` to omit it.
    """
    sh = _require_sh()
    cmd = [sh, str(INSTALL_SH), *args]
    if key is not None:
        cmd += ["--key", key]
    cmd += ["--dry-run"]
    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        check=False,
        cwd=str(REPO_ROOT),
    )
    assert result.returncode == 0, (
        f"install.sh {' '.join(args)} exited {result.returncode}\n"
        f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
    )
    return result.stdout


def test_install_script_exists() -> None:
    assert INSTALL_SH.is_file(), f"missing installer at {INSTALL_SH}"


def test_install_script_parses_clean() -> None:
    """``sh -n scripts/install.sh`` parses without error (POSIX-clean)."""
    sh = _require_sh()
    result = subprocess.run(
        [sh, "-n", str(INSTALL_SH)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, (
        f"sh -n reported a parse error:\n{result.stderr}"
    )
    assert result.stdout == ""


def test_dry_run_emits_full_command_sequence() -> None:
    """``--dry-run`` prints the whole keyed control-plane sequence, in order."""
    out = _dry_run("my-app")

    # The key stages, each asserted present.
    assert "/api/dist/manifest?version=latest" in out  # 1. gated manifest fetch
    assert "/dist/" in out                              # 2. wheel downloads
    assert "uv init --no-workspace" in out  # standalone even inside a foreign uv workspace
    assert "uv add " in out
    assert "uv run s0ma doctor" in out
    assert MCP_ADD_LINE in out
    assert "uv run s0ma new project ." in out

    # The control-plane host appears in the manifest + download URLs.
    assert CP_HOST in out

    # Every pinned wheel is downloaded (one curl -o line each) and named
    # explicitly on the `uv add` line — and NOTHING beyond the pinned set
    # rides along: the exact counts make an unreviewed $WHEELS addition
    # fail here just as loudly as a dropped stem.
    download_lines = [
        line for line in out.splitlines() if "-o .wheels/" in line
    ]
    assert len(download_lines) == len(WHEEL_STEMS), download_lines
    for stem in WHEEL_STEMS:
        assert f"-o .wheels/{stem}-" in out, f"{stem} download line missing"
    add_line = next(
        line for line in out.splitlines() if line.startswith("uv add ")
    )
    assert add_line.count("./.wheels/") == len(WHEEL_STEMS), add_line
    for stem in WHEEL_STEMS:
        assert stem in add_line, f"{stem} missing from: {add_line}"

    # The stages appear in order:
    #   manifest fetch → wheel downloads (in WHEEL_STEMS order) → uv init
    #   → uv add → doctor → feedback enrollment → claude mcp add →
    #   new project.
    order = [
        "/api/dist/manifest",
        *(f"-o .wheels/{stem}-" for stem in WHEEL_STEMS),
        "uv init --no-workspace",
        "uv add ",
        "uv run s0ma doctor",
        FEEDBACK_TOKEN_ENDPOINT,
        MCP_ADD_LINE,
        "uv run s0ma new project .",
    ]
    positions = [out.index(token) for token in order]
    assert positions == sorted(positions), (
        f"stages out of order: {positions}\n{out}"
    )


# ---------------------------------------------------------------------------
# Feedback enrollment — the dry-run plan (FB-M10 T1).
# ---------------------------------------------------------------------------


def test_dry_run_shows_the_feedback_enrollment_step_redacted() -> None:
    """The plan shows the token exchange, with the key redacted and no token.

    The exchange is the one place the license key is spent (FD-4), so the
    dry run must show the reader exactly what would be POSTed — the frozen
    endpoint, the empty JSON body (contract r6) — while still redacting the
    key as ``Bearer ***`` like every other keyed line.
    """
    out = _dry_run("my-app", key="s0ma_test_SECRETVALUE")

    assert FEEDBACK_TOKEN_ENDPOINT in out
    enroll_line = next(
        line for line in out.splitlines() if FEEDBACK_TOKEN_ENDPOINT in line
    )
    assert 'Authorization: Bearer ***' in enroll_line, enroll_line
    assert "-X POST" in enroll_line, enroll_line
    # The contract's empty enrollment body (r6): the installation pseudonym
    # is deliberately NOT sent at exchange time.
    assert "-d \"{}\"" in enroll_line, enroll_line
    # The key never appears, here or anywhere else in the plan.
    assert "SECRETVALUE" not in out

    # The plan names the file it would write, and its shape.
    assert FEEDBACK_TOKEN_DISPLAY in out
    for key in TOKEN_FILE_KEYS:
        assert key in out, f"the plan does not name the {key!r} field"
    assert "0700" in out and "0600" in out


def test_dry_run_no_feedback_skips_enrollment_only() -> None:
    """``--no-feedback`` drops the exchange and nothing else."""
    out = _dry_run("my-app", "--no-feedback")

    assert FEEDBACK_TOKEN_ENDPOINT not in out
    # It says so, and points at the later route rather than going silent.
    assert "s0ma feedback enroll" in out
    assert "--no-feedback" in out

    # Every other stage is untouched.
    assert "/api/dist/manifest?version=latest" in out
    assert "uv run s0ma doctor" in out
    assert MCP_ADD_LINE in out
    assert "uv run s0ma new project ." in out


def test_dry_run_feedback_endpoint_follows_cp_host() -> None:
    """The exchange targets the SAME control-plane base as everything else.

    The H9 smoke drives the whole install against a local
    ``wrangler pages dev``; an enrollment hard-wired to production would
    silently spend the tester's key against prod from a local smoke.
    """
    out = _dry_run("my-app", "--cp-host", "http://127.0.0.1:8788")
    assert f"http://127.0.0.1:8788{FEEDBACK_TOKEN_ENDPOINT}" in out
    assert CP_HOST not in out


def test_dry_run_via_published_one_liner_form() -> None:
    """The PUBLISHED one-liner works: ``sh -c "$(curl … install.sh)" -- <dir>
    --key <KEY>`` runs the script with ``$0`` set to ``"--"``.

    Regression (found by the production go-live smoke): a naive
    ``PROG="$(basename "$0")"`` errors on ``basename --`` and halts the install
    before it starts. The direct-invocation and ``curl | sh -s --`` forms set a
    normal ``$0`` and hid this — but the form shipped in README / walkthrough /
    tester doc / the admin page is exactly this ``sh -c "$(…)" --`` shape.
    """
    sh = _require_sh()
    # Reproduce the published one-liner faithfully AND cross-platform: let `sh`
    # assemble the script via command substitution (`$(cat …)`, mirroring
    # production's `$(curl …)`) rather than passing the ~400-line script as a
    # single `sh -c <script>` argv element — Windows' CreateProcess argv quoting
    # mangles a large multi-line argument, so `sh` gets a broken script and
    # emits nothing. The inner `--` still sets $0='--' exactly as the one-liner
    # does; `cat scripts/install.sh` resolves against cwd=REPO_ROOT (a relative,
    # forward-slash path → no Windows drive-letter/backslash issues).
    one_liner = (
        f'sh -c "$(cat scripts/install.sh)" -- my-app --key {TEST_KEY} --dry-run'
    )
    result = subprocess.run(
        [sh, "-c", one_liner],
        capture_output=True,
        text=True,
        check=False,
        cwd=str(REPO_ROOT),
    )
    assert result.returncode == 0, (
        f"published one-liner form exited {result.returncode}\n"
        f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
    )
    # The `basename --` failure must not appear anywhere.
    assert "basename" not in result.stderr, result.stderr
    # The full keyed plan still prints, key redacted.
    assert "/api/dist/manifest?version=latest" in result.stdout
    assert "uv run s0ma new project ." in result.stdout
    assert "Authorization: Bearer ***" in result.stdout


def test_dry_run_redacts_the_license_key() -> None:
    """The license key is NEVER printed; it is redacted as ``Bearer ***``."""
    out = _dry_run("my-app", key="s0ma_test_SECRETVALUE")
    assert "s0ma_test_SECRETVALUE" not in out, "license key leaked into output!"
    assert "SECRETVALUE" not in out
    # Every place a key would appear is shown as the redacted Bearer header.
    assert "Authorization: Bearer ***" in out


def test_dry_run_via_env_var_key() -> None:
    """A key supplied via S0MA_LICENSE_KEY (no --key flag) is accepted."""
    sh = _require_sh()
    import os

    env = dict(os.environ, S0MA_LICENSE_KEY="s0ma_test_FROMENV")
    result = subprocess.run(
        [sh, str(INSTALL_SH), "my-app", "--dry-run"],
        capture_output=True,
        text=True,
        check=False,
        cwd=str(REPO_ROOT),
        env=env,
    )
    assert result.returncode == 0, (
        f"env-var key run exited {result.returncode}\n"
        f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
    )
    # The env key is also redacted (never echoed).
    assert "FROMENV" not in result.stdout
    assert "Authorization: Bearer ***" in result.stdout


def test_dry_run_default_resolves_latest_via_control_plane() -> None:
    """With no --version, the manifest is fetched with version=latest; the
    control plane resolves it server-side (no client-side tag resolution)."""
    out = _dry_run("my-app")
    assert "version=latest" in out
    # We do NOT shell out to resolve a tag anymore (no gh).
    assert "gh release" not in out
    assert "release view" not in out


def test_dry_run_explicit_version_flows_into_urls() -> None:
    """An explicit --version flows into the manifest query and download URLs."""
    out = _dry_run("my-app", "--version", "0.9.0")
    assert "/api/dist/manifest?version=0.9.0" in out
    # The version is not shown as the <version> placeholder when pinned.
    assert "version:      0.9.0" in out


def test_dry_run_custom_cp_host() -> None:
    """``--cp-host`` redirects the manifest + download URLs for testing.

    A BARE host (no scheme) still gets ``https://`` — backward-compatible."""
    out = _dry_run("my-app", "--cp-host", "localhost:8788")
    assert "https://localhost:8788/api/dist/manifest" in out
    assert CP_HOST not in out  # the default host is fully overridden


def test_dry_run_cp_host_with_scheme_is_used_verbatim() -> None:
    """A ``--cp-host`` that already carries a scheme is used as-is (HOST-H9).

    This is how the H9 smoke targets a local ``wrangler pages dev`` over plain
    http, e.g. ``--cp-host http://127.0.0.1:8788`` — the installer must NOT
    force https:// over an explicit http:// base."""
    out = _dry_run("my-app", "--cp-host", "http://127.0.0.1:8788")
    assert "http://127.0.0.1:8788/api/dist/manifest" in out
    # It must not have been rewritten to https.
    assert "https://127.0.0.1:8788" not in out
    # The wheel download lines also use the http base.
    assert "http://127.0.0.1:8788/dist/" in out


def test_dry_run_cp_host_https_scheme_preserved() -> None:
    """An explicit ``https://`` scheme is preserved (not doubled)."""
    out = _dry_run("my-app", "--cp-host", "https://staging.example.com")
    assert "https://staging.example.com/api/dist/manifest" in out
    assert "https://https://" not in out


def test_dry_run_default_off_passes_through() -> None:
    """``--default-off`` rides through to ``s0ma new project``."""
    out = _dry_run("my-app", "--default-off")
    assert "uv run s0ma new project . --default-off" in out


def test_dry_run_touches_nothing(tmp_path: Path) -> None:
    """A dry run creates neither the target nor any user-scoped state.

    The enrollment step writes outside the project (``~/.s0ma``), so the
    dry-run promise has to be checked on BOTH sides: no target directory and
    no state directory. ``HOME`` is redirected at a temp path so a real one
    is never consulted.
    """
    sh = _require_sh()
    target = tmp_path / "would-be-project"
    home = tmp_path / "home"
    home.mkdir()
    assert not target.exists()

    env = dict(os.environ, HOME=str(home), USERPROFILE=str(home))
    env.pop("S0MA_LICENSE_KEY", None)
    result = subprocess.run(
        [sh, str(INSTALL_SH), str(target), "--key", TEST_KEY, "--dry-run"],
        capture_output=True,
        text=True,
        check=False,
        cwd=str(REPO_ROOT),
        env=env,
    )
    assert result.returncode == 0, result.stderr

    # --dry-run must not create the target dir, any wheels, or ~/.s0ma.
    assert not target.exists()
    assert list(home.iterdir()) == [], "the dry run wrote user-scoped state"


def test_missing_key_fails_loudly() -> None:
    """No key (neither --key nor S0MA_LICENSE_KEY) → exit 1 with an actionable
    message naming BOTH sources (not a traceback)."""
    sh = _require_sh()
    import os

    # Scrub any inherited S0MA_LICENSE_KEY from the environment.
    env = {k: v for k, v in os.environ.items() if k != "S0MA_LICENSE_KEY"}
    result = subprocess.run(
        [sh, str(INSTALL_SH), "my-app", "--dry-run"],
        capture_output=True,
        text=True,
        check=False,
        cwd=str(REPO_ROOT),
        env=env,
    )
    assert result.returncode == 1
    assert "license key is required" in result.stderr
    # The error names both ways to supply a key.
    assert "--key" in result.stderr
    assert "S0MA_LICENSE_KEY" in result.stderr


def test_missing_target_fails_loudly() -> None:
    """No target dir → exit 1 with an actionable message (not a traceback)."""
    sh = _require_sh()
    result = subprocess.run(
        [sh, str(INSTALL_SH), "--key", TEST_KEY, "--dry-run"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 1
    assert "target directory is required" in result.stderr


def test_unknown_option_fails_loudly() -> None:
    """An unknown flag → exit 1 with an actionable message."""
    sh = _require_sh()
    result = subprocess.run(
        [sh, str(INSTALL_SH), "my-app", "--key", TEST_KEY, "--bogus"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 1
    assert "unknown option" in result.stderr


# ---------------------------------------------------------------------------
# Feedback enrollment — the REAL run, against a stub toolchain (FB-M10 T1/T2).
#
# Still no network and still no real toolchain: stub `curl`/`uv`/`claude`
# scripts sit first on PATH and answer with canned bodies, and HOME points at
# a temp directory. That buys the two things --dry-run structurally cannot
# show — that a failed exchange really is non-fatal, and what the token file
# looks like on disk.
# ---------------------------------------------------------------------------

#: The stub control plane's canned token. It must never be echoed by the
#: installer; only its 12-character display prefix may appear.
STUB_TOKEN = "s0ma_fb_STUBTOKENVALUEabcdefgh"
STUB_TOKEN_PREFIX = STUB_TOKEN[:12]
STUB_EXPIRES_TS = 1788000000000  # epoch MILLISECONDS (contract r6)

#: The stub manifest carries no `sha256` fields, so the installer's verify
#: branch reports "no sha256 — skipping" instead of failing on stub bytes.
#: The wheel version is deliberately unreal: nothing here is a s0ma release.
_STUB_VERSION = "9.9.9"

_STUB_CURL = """\
#!/usr/bin/env sh
# Stub curl for the installer tests. Understands only the flags install.sh
# uses: -o <file> (body sink), -D <file> (response headers), and the URL as
# the final argument. Prints the HTTP status on stdout, exactly as the real
# curl does under -w '%{http_code}'.
out=""; url=""; hdrs=""
while [ $# -gt 0 ]; do
    case "$1" in
        -o) out="$2"; shift 2 ;;
        -D) hdrs="$2"; shift 2 ;;
        -w|-X|-H|-d) shift 2 ;;
        -*) shift ;;
        *) url="$1"; shift ;;
    esac
done
[ -n "$hdrs" ] && printf 'HTTP/1.1 200 OK\\r\\n\\r\\n' > "$hdrs"
case "$url" in
    */api/dist/manifest*)
        [ -n "$out" ] && printf '%s' '__MANIFEST__' > "$out"
        printf '200' ;;
    */api/feedback/token)
        case "${S0MA_STUB_FEEDBACK:-ok}" in
            ok)
                [ -n "$out" ] && printf '%s' '__TOKEN_BODY__' > "$out"
                printf '200' ;;
            refused)
                [ -n "$out" ] && printf '%s' '__REFUSAL_BODY__' > "$out"
                printf '401' ;;
            unreachable)
                exit 7 ;;
        esac ;;
    *)
        [ -n "$out" ] && printf 'stub-wheel-bytes' > "$out"
        printf '200' ;;
esac
"""

_STUB_NOOP = "#!/usr/bin/env sh\nexit 0\n"


def _stub_manifest() -> str:
    wheels = ",".join(
        f'{{"name":"{stem}-{_STUB_VERSION}-py3-none-any.whl",'
        f'"path":"dist/{_STUB_VERSION}/{stem}-{_STUB_VERSION}-py3-none-any.whl"}}'
        for stem in WHEEL_STEMS
    )
    return f'{{"ok":true,"version":"{_STUB_VERSION}","wheels":[{wheels}]}}'


@pytest.fixture
def stub_toolchain(tmp_path: Path) -> dict[str, object]:
    """A temp HOME plus stub ``curl``/``uv``/``claude`` first on PATH."""
    if os.name != "posix":
        pytest.skip("the real-run install tests assert POSIX file modes")
    _require_sh()

    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    curl = (
        _STUB_CURL.replace("__MANIFEST__", _stub_manifest())
        .replace(
            "__TOKEN_BODY__",
            json.dumps(
                {
                    "ok": True,
                    "token": STUB_TOKEN,
                    "token_prefix": STUB_TOKEN_PREFIX,
                    "expires_ts": STUB_EXPIRES_TS,
                    "scopes": ["feedback:write", "feedback:delete-own"],
                },
                separators=(",", ":"),
            ),
        )
        .replace(
            "__REFUSAL_BODY__",
            json.dumps(
                {
                    "ok": False,
                    "code": "NOT_ENTITLED",
                    "remediation": "ask the s0ma admin for a new key",
                },
                separators=(",", ":"),
            ),
        )
    )
    for name, body in (("curl", curl), ("uv", _STUB_NOOP), ("claude", _STUB_NOOP)):
        script = bin_dir / name
        script.write_text(body, encoding="utf-8", newline="\n")
        script.chmod(0o755)

    home = tmp_path / "home"
    home.mkdir()
    env = dict(os.environ)
    env.pop("S0MA_LICENSE_KEY", None)
    env["HOME"] = str(home)
    env["PATH"] = f"{bin_dir}{os.pathsep}{env['PATH']}"
    return {"env": env, "home": home, "target": tmp_path / "app"}


def _install(stub: dict[str, object], *args: str, scenario: str = "ok"):
    """Run the installer for real under the stub toolchain."""
    env = dict(stub["env"])  # type: ignore[arg-type]
    env["S0MA_STUB_FEEDBACK"] = scenario
    return subprocess.run(
        [
            _require_sh(),
            str(INSTALL_SH),
            str(stub["target"]),
            "--key",
            "s0ma_test_SECRETVALUE",
            *args,
        ],
        capture_output=True,
        text=True,
        check=False,
        env=env,
    )


def test_real_run_writes_the_token_file_in_the_contract_shape(
    stub_toolchain: dict[str, object],
) -> None:
    """Enrollment writes exactly the file ``s0ma feedback`` reads back.

    The shape is ``StoredToken.to_dict``'s four keys (contract §8); the modes
    are 0700 on the directory and 0600 on the file. Neither the license key
    nor the token itself may appear in the output — only the 12-character
    display prefix.
    """
    home = stub_toolchain["home"]
    assert isinstance(home, Path)

    result = _install(stub_toolchain)
    assert result.returncode == 0, f"{result.stdout}\n{result.stderr}"

    token_file = home / ".s0ma" / "feedback-token"
    assert token_file.is_file(), result.stdout

    document = json.loads(token_file.read_text(encoding="utf-8"))
    assert set(document) == TOKEN_FILE_KEYS, document
    assert document["token"] == STUB_TOKEN
    assert document["token_prefix"] == STUB_TOKEN_PREFIX
    assert document["expires_ts"] == STUB_EXPIRES_TS
    # cp_host is the base the install actually used, so a later
    # `s0ma feedback` talks to the same control plane it enrolled with.
    assert document["cp_host"] == f"https://{CP_HOST}"

    # Owner-only, both levels (contract §8 / feedback.state).
    assert stat.S_IMODE(token_file.stat().st_mode) == 0o600
    assert stat.S_IMODE((home / ".s0ma").stat().st_mode) == 0o700

    # Secrets stay out of the transcript; the prefix is the only token text.
    combined = result.stdout + result.stderr
    assert "SECRETVALUE" not in combined
    assert STUB_TOKEN not in combined
    assert STUB_TOKEN_PREFIX in combined
    # The notice names the file and the command that uses it.
    assert FEEDBACK_TOKEN_DISPLAY in combined
    assert "s0ma feedback" in combined


@pytest.mark.parametrize("scenario", ["refused", "unreachable"])
def test_real_run_survives_a_failed_enrollment(
    stub_toolchain: dict[str, object], scenario: str
) -> None:
    """A refused or unreachable exchange never fails the install.

    Feedback is not load-bearing (FR-FB-8): the tester must still end up with
    a working, scaffolded project. The warning is one line and points at the
    command that fixes it later.
    """
    home = stub_toolchain["home"]
    target = stub_toolchain["target"]
    assert isinstance(home, Path) and isinstance(target, Path)

    result = _install(stub_toolchain, scenario=scenario)
    assert result.returncode == 0, f"{result.stdout}\n{result.stderr}"

    # The install reached its end, and nothing was stored.
    assert "Done. s0ma is installed" in result.stdout
    assert target.is_dir()
    assert not (home / ".s0ma").exists()

    warnings = [
        line
        for line in result.stdout.splitlines()
        if "Could not set this machine up to send feedback" in line
    ]
    assert len(warnings) == 1, result.stdout
    assert "s0ma feedback enroll" in warnings[0]
    assert "SECRETVALUE" not in result.stdout + result.stderr


def test_real_run_no_feedback_writes_no_token_file(
    stub_toolchain: dict[str, object],
) -> None:
    """``--no-feedback`` really does skip the exchange on a real run."""
    home = stub_toolchain["home"]
    assert isinstance(home, Path)

    result = _install(stub_toolchain, "--no-feedback")
    assert result.returncode == 0, f"{result.stdout}\n{result.stderr}"
    assert not (home / ".s0ma").exists()
    assert STUB_TOKEN_PREFIX not in result.stdout
    assert "s0ma feedback enroll" in result.stdout


def test_real_run_closing_summary_introduces_feedback(
    stub_toolchain: dict[str, object],
) -> None:
    """The last thing a tester reads names the route and the promise."""
    result = _install(stub_toolchain)
    assert result.returncode == 0, f"{result.stdout}\n{result.stderr}"
    assert (
        "Send feedback about s0ma any time: s0ma feedback — you approve the "
        "exact feedback data before anything is sent." in result.stdout
    )
    # Contract §12 / A-2: never the word "payload" in user-facing copy.
    assert "payload" not in result.stdout.lower()
