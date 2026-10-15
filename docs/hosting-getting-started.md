# s0ma — getting started as a free tester

> **This is the keyed route, and it is not the route the public repository
> offers.** This page describes the hosted channel's installer, for testers the
> s0ma owner has invited and given a key. The public repository's first release
> offers one way in — clone the repository and build from it — which is stated
> once in [`getting-started.md` §1](getting-started.md#1-create-a-real-project)
> and needs nothing on this page.

You have been invited to the s0ma private beta. You received two things from the
s0ma owner:

1. **a license key** (looks like `s0ma_test_…`), and
2. **a one-command installer line** (the same one printed below).

This page is the tester-facing onboarding: what the command does, the
prerequisites, how to troubleshoot, and how to re-run. There is also a short
**owner runbook** at the end for whoever provisions testers.

> The s0ma authoring server runs **locally** on your machine. The hosted control
> plane (`account.kn0wthyself.ai`) only does two things: holds your account/key
> and serves the entitlement-gated wheel download. What this page installs never
> starts network activity on its own — there is no telemetry and no background
> reporting. The only exceptions are the installer below, which you run, and the
> **feedback** surfaces in §4, which you invoke; feedback sends only what you
> have read and approved, one report at a time.
>
> (Installing through Claude instead adds one more thing that can ask the
> control plane on its own: a daily check for a newer version, which you can
> switch off. [What s0ma trusts](trust-model.md#what-s0ma-sends-when-it-is-installed-through-claude)
> states every request either route makes.)

---

## 1. What you do

Paste your command into a terminal, substituting your real key for `<KEY>`:

```bash
sh -c "$(curl -fsSL https://account.kn0wthyself.ai/install.sh)" -- my-app --key <KEY>
```

`my-app` is the directory the installer creates for your new project — rename it
to whatever you like. That single command:

1. fetches the entitlement-gated **manifest** from the control plane (using your
   key as `Authorization: Bearer <KEY>`),
2. downloads and **sha256-verifies** the released wheels named in that
   manifest (`s0ma_core`, `s0ma_dsl`, `s0ma_mcp`, `s0ma_studi0`),
3. creates a `uv` project and installs the wheels,
4. runs `s0ma doctor` (a health check),
5. connects this machine to the **feedback** function — one request that swaps
   your license key for a feedback access code, stored at
   `~/.s0ma/feedback-token` (§4; nothing is sent, and `--no-feedback` skips it),
6. registers the **authoring MCP server** with Claude Code
   (`claude mcp add s0ma --scope project -- uv run s0ma-mcp`), and
7. scaffolds a **feature-first** starter project (`s0ma new project .`).

Then **open the `my-app/` folder in Claude Code** — the MCP server is already
registered for the project (it is written into `.mcp.json`), so your agent can
author s0ma components immediately. Confirm inside Claude Code with `/mcp`: you
should see server `s0ma-authoring`. Validate the project any time with:

```bash
cd my-app && uv run s0ma check
```

If you would rather supply the key through the environment than on the command
line, set `S0MA_LICENSE_KEY` and drop the `--key` flag:

```bash
export S0MA_LICENSE_KEY=<KEY>
sh -c "$(curl -fsSL https://account.kn0wthyself.ai/install.sh)" -- my-app
```

### See what it will do first (no network, key redacted)

Append `--dry-run` to print the exact command sequence the installer *would*
run, then exit — it executes nothing, touches no network, and **redacts your
key** as `Bearer ***`:

```bash
sh -c "$(curl -fsSL https://account.kn0wthyself.ai/install.sh)" -- my-app --key <KEY> --dry-run
```

(The `curl` that fetches the installer itself is the only network call; the
dry-run does nothing beyond that.)

---

## 2. Prerequisites

| Tool | Required? | Notes |
|---|---|---|
| `curl` | **yes** | Used to fetch the installer and the wheels. Pre-installed on macOS/Linux. |
| `uv` | **yes** | The Python package manager. Install from <https://docs.astral.sh/uv/>. The installer checks for it up front and fails loudly if it is missing. |
| `claude` (Claude Code) | optional | If absent, step 6 (MCP registration) is **skipped with a printed hint** so you can run it later; everything else still completes. |
| a license key | **yes** | Passed via `--key` or `S0MA_LICENSE_KEY`. One of the two is required. |

Python ≥ 3.11 is needed, but `uv` provisions an interpreter for the project, so
you do not have to install Python separately. On **Windows**, run the command
under **Git Bash** or **WSL** (the installer is POSIX `sh`).

---

## 3. Useful flags

| Flag | Effect |
|---|---|
| `--key <KEY>` | Your s0ma license key (or set `S0MA_LICENSE_KEY`). One is required. |
| `--version 0.x.y` | Pin a specific release instead of the default `latest` (the control plane resolves `latest` server-side). |
| `--default-off` | Scaffold the project with `[tool.s0ma].authoring = "off"`. |
| `--no-feedback` | Skip the feedback step (§4). Everything else installs as usual; connect the machine later with `s0ma feedback enroll`. |
| `--dry-run` | Print the plan and exit — no execution, no network, **key redacted**. |
| `--cp-host <host>` | Point at a non-default control-plane host (testing only; default `account.kn0wthyself.ai`). |
| `-h`, `--help` | Show the built-in usage. |

---

## 4. Sending feedback

You are a beta tester, so telling the s0ma team what happened is the point. Four
routes reach the same place; pick whichever is closest to hand.

**1. `/s0ma-feedback` — the fastest route in Claude Code.** The installer's
scaffold step writes this skill into your project, so it is already there. Type
it in Claude Code, optionally with your message:

```text
/s0ma-feedback the check command's error message did not tell me which file
```

**2. The `feedback` prompt on the s0ma MCP server** — the same journey, in any
MCP client. In Claude Code it appears as `/mcp__s0ma__feedback`; other clients
list it under the server's prompts.

**3. Just say it.** Tell your agent in plain English — *"tell the s0ma team the
scaffolder put my module in the wrong folder"* — and it will start the same
journey. If you do not name s0ma ("I have some feedback"), the agent asks you to
confirm the feedback is about s0ma before it begins: you may well be using other
tools that collect feedback too.

**4. `s0ma feedback` — any terminal, no agent required.** The universal route,
and the one to fall back to if a client cannot show you an approval prompt:

```bash
cd my-app
uv run s0ma feedback
uv run s0ma feedback --message "the doctor output scrolled off the screen"
```

### What you approve is exactly what is sent

Every route ends at the same confirmation. You see the finished report — the
exact feedback data, plus a note of anything that was redacted out of it — and
answer:

```text
Send exactly this feedback data? [y/N]
```

Nothing leaves your machine before that answer. What you read is a complete,
plain-language rendering of the exact feedback data — every field, nothing
hidden — and the fingerprint shown with it is computed from the precise bytes
that travel, so the receipt can be checked against exactly what you approved. There is no flag that skips this step, and an agent cannot approve
on your behalf. Say no and the report is kept as a local draft you can finish
later (`s0ma feedback drafts`).

Reports are **pseudonymous, not anonymous.** Each one carries a random id for
this installation of s0ma — never your name, your source code, your files, or
your conversations — and the team sees reports by that pseudonym. Your account
still exists behind the access code, so this is privacy by minimization, not a
claim we cannot be linked.

Contact is **opt-in, once per report.** Each report asks:

```text
May kn0wthyself contact you about this report? [y/N]
```

The default is no. Answer yes on the one report you want a reply about and your
account email is attached to that report only; every other report stays
pseudonymous.

### Changing your mind

Sent reports are yours to delete:

```bash
uv run s0ma feedback list             # your reports, newest first, with their ids
uv run s0ma feedback delete fb_…      # delete exactly one, by its id
```

`delete` with no id deletes nothing — it prints the list so you can pick. Ids
also land in `~/.s0ma/feedback-receipts.jsonl` as you send, so they stay findable
after the conversation has scrolled away.

### Where the local state lives

Everything the feedback function remembers sits in `~/.s0ma/`
(`%USERPROFILE%\.s0ma` on Windows) — outside every project, never in a
repository: this machine's feedback access (`feedback-token`), unsent drafts, the
receipts log, and the random installation pseudonym. Deleting that directory
resets the machine; re-connect it with `s0ma feedback enroll`.

If you would rather not have the installer connect the machine at all, pass
`--no-feedback` (§3) — everything else installs identically, and
`s0ma feedback enroll` is there whenever you change your mind.

---

## 5. Troubleshooting

See also `docs/troubleshooting.md` for everything *after* the install (check
failures, stale builds, the MCP server not appearing, studi0), and
`docs/uninstall.md` for removing s0ma completely.

The control plane returns **structured errors** — a JSON body of the shape
`{ "ok": false, "code": "…", "remediation": "…" }` with the correct HTTP status.
The installer surfaces the `code` and `remediation` on stderr, plus a
"check your key / subscription at account.kn0wthyself.ai" hint, then aborts.
The codes you might see:

| HTTP | `code` | What it means | What to do |
|---|---|---|---|
| **401** | `INVALID_KEY` | The key is missing, malformed, or unknown to the control plane. | Re-check you pasted the whole key (it starts `s0ma_test_`). If you don't have one, ask the s0ma admin for a free-tester key. |
| **403** | `NOT_ENTITLED` | The key is recognized but **no longer entitled** — revoked, expired, or its account is inactive. | Ask the s0ma admin for a new key. |
| **404** | `NOT_FOUND` | The requested version/wheel isn't present. | Drop any `--version` pin (let it default to `latest`); if it persists, tell the admin. |
| **400** | `BAD_REQUEST` | A malformed request (usually only with a hand-edited `--version`/path). | Re-run the plain one-liner without custom paths. |
| **401** | `INVALID_TOKEN` | A **feedback** command's access code is missing, expired, or was revoked (it is not your license key — see §4). | Run `s0ma feedback enroll` to connect this machine again. Nothing you wrote is lost; unsent reports stay in `s0ma feedback drafts`. |
| **429** | `RATE_LIMITED` | Too many requests in the window — installs are limited per key, feedback per machine and per account. | Wait for the `retry after ~Ns` the command prints, then try again. Repeated 429s on a first install mean something is retrying in a loop; stop it and tell the admin. |

Other failure modes the installer reports loudly and actionably:

- **No key supplied** — it names *both* `--key` and `S0MA_LICENSE_KEY` and links
  to `https://account.kn0wthyself.ai`.
- **`curl` or `uv` missing** — it tells you which and where to install it.
- **sha256 mismatch** — a downloaded wheel did not match the manifest's hash; the
  installer aborts (possible corruption or tampering). Re-run; if it persists,
  tell the admin.
- **Can't reach the control plane** — a network/DNS issue; check your connection,
  then your key/subscription at `account.kn0wthyself.ai`.

### Re-running

The installer is safe to re-run. If a run failed partway:

- It targets a **directory** (`my-app`); delete a half-made project directory and
  re-run the command to start clean, or pick a fresh directory name.
- `uv init` / `uv add` / `claude mcp add` are themselves idempotent enough that
  re-running into an existing project generally just no-ops or updates in place,
  but the cleanest recovery from a failed run is a fresh target directory.
- Use `--dry-run` first to confirm exactly what a re-run will do.

---

## 6. Owner runbook — provisioning a tester

*(For the s0ma owner. Testers can ignore this section.)*

Interim, there is **no email service** (Decision 4): you provision accounts and
hand each tester their command through whatever channel you already use (DM,
Slack, etc.). The flow:

1. **Open the control plane's admin page.** Its address, and how you sign in,
   are in the control plane's own operating manual, which lives with that
   service rather than in this repository.
2. **Paste tester emails**, one per line, into the textarea and click
   **Provision**. Each email becomes a `free_tester` account (idempotent — the
   same email never creates a duplicate) and gets a license key issued if it
   doesn't already have a live one.
3. **Copy each tester's command** from the results table. For a **newly issued**
   key the real key is shown **once** (copy it now — it is hashed at rest and
   never shown again) and is already substituted into the command:

   ```bash
   sh -c "$(curl -fsSL https://account.kn0wthyself.ai/install.sh)" -- my-app --key s0ma_test_…
   ```

   For an **existing** key (already issued earlier) the command uses a
   `<YOUR-KEY>` placeholder instead — paste in the key the tester was given
   before. To deliberately revoke-and-reissue, tick **rotate** before
   provisioning.
4. **Send each `{email → command}`** to that tester via your channel of choice.
   They paste it and follow §1 above.

**Future automation (not built yet):** because visiting agents already hit the
visitor MCP (`mcp.kn0wthyself.ai`) to learn about s0ma, that is the natural place
to later surface the `s0ma init` one-liner and a self-service signup link
(plan §1.3 funnel tie-in). Interim stays manual and keyed.

### Verifying what prod actually serves

After a release tag, the `verify-served` CI job asks the control plane — with a
real tester key — what it now serves: the manifest's `latest`, every wheel's
sha256, and the published installer. Set it up once:

1. **Provision the smoke tester** through the same admin page, using an address
   kept for that purpose. It is an ordinary revocable `free_tester` account, so
   revoking it makes the check fail loudly rather than pass silently.
2. **Store its key** as the repository secret `S0MA_SMOKE_KEY` (Settings →
   Secrets and variables → Actions). Unset, the job skips with a notice instead
   of failing red — visible, never blocking.

Reading the result: green means a tester can install that release. *"CP deploy
pending — served installer differs from canon"* is a **notice**, not a failure —
the release is good, the control-plane site simply has not been deployed yet
(deploys are manual); deploy it, then re-run. Anything else is red: the served
`latest`, the wheel list, or the wheel bytes are wrong. Run the same check by
hand any time — the key comes from the environment, never an argument:

```bash
S0MA_SMOKE_KEY=<key> scripts/verify_served.sh --version X.Y.Z
```

**Rollback.** To put prod back on a known-good release, move the manifest
pointer (wheel objects stay immutable) and re-verify:

```bash
scripts/mirror_to_r2.sh --version <older> --dist-dir dist --allow-latest-downgrade
S0MA_SMOKE_KEY=<key> scripts/verify_served.sh --version <older>
```

**Logs and the audit trail.** Operating the hosted service — where its logs
go, how long they last, and how to read its audit trail — is covered in the
control plane's own operating manual, with the commands. One rule applies on
this side of the line: keep any new logging structured, so that a log pipeline
added later can parse it.

---

## 7. The exact command (canonical)

**This page is the one place the keyed installer is described.** The route it
belongs to is the hosted channel's, which the public repository's first release
does not offer: that release's one route in — clone the repository and build
from it — is stated once in
[`getting-started.md` §1](getting-started.md#1-create-a-real-project), and its
mechanics once in the root `README.md` "Install" section. The installer itself,
its flags, its failure modes, and the feedback enrolment it performs are stated
once here, and the Claude Code plugin and the Claude Desktop extension are
stated once in [`guides/claude-integration.md`](guides/claude-integration.md).
Every other page points at one of those rather than restating any of them, so
there are never two accounts of the install to keep true. The one-liner below
is the canonical text of the command (the admin page substitutes your real key
for `<KEY>`); the admin results table prints the same line:

```bash
sh -c "$(curl -fsSL https://account.kn0wthyself.ai/install.sh)" -- my-app --key <KEY>
```
