# Authoring through the agent's own tool channel

This is the loop a coding agent walks when it builds something in a s0ma
project: ask the tree what it is, write a component from its intent, have the
toolchain check it, build, and read the result back out of the system's own
record of itself. Five calls, in that order, all of them on the authoring
server the agent is already connected to.

Two readers are meant here. The first is the person setting an agent up, who
wants to know what the agent will be doing and which of its calls are safe to
let it make on its own. The second is an agent that has been handed this page —
the loop below is the one to follow, and the answers quoted from it are the
real ones.

Nothing here replaces [the walkthrough](../walkthrough.md), which covers
installing s0ma, designing an application, and the wider habits worth having.
This page is the loop itself, and every call and every quoted answer on it is
replayed against the real server before it ships.

## Point the agent at the server

With an installed wheel, one command:

```bash
claude mcp add s0ma -- s0ma-mcp
```

From an application directory that uses `uv`, the same registration scoped to
the repository, so every session and every teammate inherits it:

```bash
claude mcp add s0ma --scope project -- uv run s0ma-mcp
```

The server speaks over standard input and output and blocks when started by
hand — that is correct, not a hang. The
[walkthrough](../walkthrough.md#2-point-the-agent-at-the-server) has the full
installation routes, and [the surface index](../reference/surfaces-index.md)
lists everything the server serves.

One thing to know before the first call: each of the five tools below takes an
explicit `project_root`, and none of them writes outside the tree you name. The
agent never has to guess where it is, and you never have to trust that it
guessed correctly.

## The loop

### 1. Orient — `project_status`

The first call in any tree, before anything is written into it.

```json
{"tool": "project_status", "arguments": {"project_root": "/work/app"}}
```

One call answers the whole question of what this directory is:

```text
{
  "ok": true,
  "is_project": true,
  "project_root": "/work/app",
  "mode": "dev",
  "authoring": "on",
  "modules": [
    ...
  ],
  "build": {
    "built": true,
    "status": "fresh",
    ...
  },
  ...
}
```

A directory that is not a s0ma project is a valid answer here, not an error —
the answer says so, and points at the tool that makes one. Where it is a
project, the reply also carries every module it holds and whether each is still
fresh, what the last build produced, and what the project still owes before it
could be released.

### 2. Author — `scaffold_module`

New behaviour starts from its intent, in a skeleton the toolchain already
accepts, rather than from a Python file written first and described afterwards.

```json
{"tool": "scaffold_module", "arguments": {"kind": "SERVICE", "layer": "DOMAIN", "module_name": "greeting", "project_root": "/work/app"}}
```

The source is written into the project and handed straight back, so the agent
can edit the intent and the contracts rather than guess at them. The scaffold
also checks itself on the way out:

```text
{
  "ok": true,
  "exit_code": 0,
  "path": "/work/app/src/greeting.s0ma",
  ...
  "check": {
    "ok": true,
    ...
  },
  ...
  "suggested_next_action": "Validate the intent-authored scaffold after editing it."
}
```

What comes back is a whole component: a module header, and one declaration
under it carrying its intent, its contracts, and the single function body the
language allows. Every `TODO` in it is a sentence somebody has to write — those
intent lines are read by people and by the system itself, so they are worth the
minute they cost.

### 3. Check — `check`

After every edit, before anything is built from it.

```json
{"tool": "check", "arguments": {"mode": "dev", "project_root": "/work/app"}}
```

A clean answer counts the files it read and stops there:

```text
{
  "ok": true,
  "exit_code": 0,
  "diagnostics": {
    "by_file": [],
    "errors": [],
    "summary": {
      "errors": 0,
      "files_processed": 4,
      "mode": "dev",
      "warnings": 0
    },
    "warnings": []
  },
  ...
  "suggested_next_action": "Build only after the static diagnostics are clean."
}
```

Anything it is unhappy about arrives as a finding that names the file, the
line, the failure's own name, and what to do about it. Findings are also
labelled against the last green build, so an agent can tell a problem it has
just caused from one that was already there — and a problem it has just caused
is its own to fix before it builds.

### 4. Build — `build_project`

Only once the check is clean.

```json
{"tool": "build_project", "arguments": {"mode": "dev", "project_root": "/work/app"}}
```

The build writes the generated code and a manifest naming every module and the
order they import in. It also says what it still wants, which in a fresh
project includes the reminder that the generated code now imports the s0ma
runtime and the project has not declared it:

```text
{
  "ok": true,
  "exit_code": 0,
  "diagnostics": {
    ...
    "warnings": [
      {
        "code": "HOST_RUNTIME_UNDECLARED",
        ...
        "message": "Generated Python imports the s0ma runtime, but the host project does not declare s0ma-core, s0ma-dsl in [project].dependencies.",
        "remediation": "Name s0ma-core and s0ma-dsl in [project].dependencies — that alone clears this warning. Separately, the environment that runs the application has to have both installed; `s0ma verify-host` is how you prove it does.",
        "severity": "warning"
      }
    ]
  },
  ...
  "manifest": {
    ...
    "topological_import_order": [
      ...
    ]
  },
  ...
  "suggested_next_action": "Inspect the emitted canonical self-model before grepping code."
}
```

Generated code is written once and the same way every time, and it belongs to
the build. An edit made to it by hand is lost on the next build — and because
that would be a silent loss, the build refuses instead. See
[when it goes wrong](#when-it-goes-wrong).

### 5. Read it back — `inspect_module`

The last call closes the loop: instead of reading the code the build just
wrote, ask the system what it now knows about the component.

```json
{"tool": "inspect_module", "arguments": {"module": "greeting", "project_root": "/work/app"}}
```

```text
{
  "ok": true,
  "exit_code": 0,
  "module": "greeting",
  "ir": {
    "components": [
      {
        "canonical_id": "greeting::greeting",
        "declaration_type": "nerve",
        ...
        "provides_contracts": [
          ...
        ],
        ...
        "kind": "SERVICE",
        ...
        "visibility": "PUBLIC"
      }
    ],
    ...
  },
  ...
}
```

This is the habit worth building into an agent: the question "where is X
handled?" is answered from the system's record of itself, not from a search
through its source. That record is what the build made from the declarations,
so it cannot describe a component the project does not have.

## Application runtime-consumer acceptance

For an application, continue after step 5 with its own offline acceptance test:
boot the emitted build in a fresh process, compose the real providers and
registry, query the public inspection interfaces, and exercise the actual
consumer. Check effective configuration, policy refusals, partial observations
and actual effects. If the consumer is an agent, capture its assembled context
with a recording adapter and assert what it received. A library needs tests of
its callers; it does not need to run an agent.

The [offline application example](application-observations.md) includes refusal,
failed storage, explicit refresh, local expiry, alternate routes and failed
optional effects. Its tests cover the consumer beyond the five authoring calls.
The existing journey and transcript still cover exactly those five calls; no
new MCP surface is implied by application acceptance.

## What every answer carries

Four things ride on every result, and they are the difference between an agent
that has to be told what to do next and one that can read it:

- **`rules`** — the short list of rules that hold in this project, repeated on
  every answer so they stay in the agent's context rather than in a document it
  read once. Two of them are the ones agents get wrong most often:

  ```text
  "Only edit .s0ma sources. Never edit generated files under build/ — the build now REFUSES to overwrite a hand-edited generated file (GENERATED_FILE_DRIFT), and otherwise overwrites it on every build.",
  "A nerve body is exactly ONE def. Declare imports in the module header's requires: (the transpiler emits them) — never write import statements in the body.",
  ```

- **`next_actions` and `suggested_next_action`** — the named call to make next,
  with the arguments to make it with. `project_status` points at `check`,
  `check` points at `build_project`, and `build_project` points at
  `inspect_module`. Following them *is* the loop, which is why an agent that
  reads its answers rarely needs the loop explained to it.

- **`note`** — the standing warning that the toolchain is reachable here and
  usually nowhere else:

  ```text
  "note": "verify .s0ma edits with the check and build_project MCP tools here — the `s0ma` CLI is usually NOT on PATH in agent environments, so do not shell out to it.",
  ```

- **`schema`** — the version of the result shape itself, so a client can tell
  what it is reading.

## What each call may do

None of the five calls asks anyone to approve anything, and none can reach
outside the project root it was given.

| Call | What it does |
| --- | --- |
| `project_status` | reads |
| `scaffold_module` | writes one source file into the project |
| `check` | reads |
| `build_project` | writes the generated code and the manifest |
| `inspect_module` | reads |

That is the honest basis for letting the inner loop run unattended: the three
readers decide nothing on anybody's behalf, and the two writers only ever write
inside the tree you named. Other tools on this server do ask — sending feedback
to the s0ma team is approved by the person, in their own words, on the exact
report they were shown, and running a host verification executes the project's
own code. Those are different paths, and this one does not cross them.

## When it goes wrong

Three failures are common enough to be worth naming, and each has one answer.

**`MISSING_PROVIDED_FUNCTION` — the check refuses the edited component.** Its
`provides:` list names an operation the body never defines. Add the missing
`def`, or take the name out of `provides:`, and walk the loop the
`fix_check_failures` prompt lays out until the check is clean. That prompt is
one of five the server offers as slash commands, and they are their own copy —
written separately from this page rather than generated from it — so they
describe the same loops in their own words.

**`BARE_IMPORT` — the body carries its own import line.** The build writes the
imports from the declarations, so a line in the body is both duplicated and
unaccounted for. Move it into the module header — `requires:` for a Python
import, `uses:` for another s0ma component — take the line out of the body, and
ask the check again.

**`GENERATED_FILE_DRIFT` — the build refuses to overwrite a hand-edited
file.** Something under the build directory was changed by hand after it was
generated, and building would throw that change away. Move the change back into
the `.s0ma` source it belongs to, undo the hand edit, and ask the check again
before building.

Every failure the toolchain reports carries its own remediation text, and the
[troubleshooting guide](../troubleshooting.md) covers the ones that are about
the installation rather than about the code.

## How this page is kept true

Every call shown above, and every line quoted from an answer, is replayed
against the real authoring server before this page ships: the server is created
inside the test process, a throwaway project is scaffolded, the five calls are
made in this order, and what comes back is compared against what is written
here. The transcript is registered as `example:transcript/mcp-authoring-loop`
and the path it walks is `journey:mcp-authoring-loop`. If the product stops
answering the way this page says it does, the gate turns red and the page is
wrong on purpose — never quietly.
