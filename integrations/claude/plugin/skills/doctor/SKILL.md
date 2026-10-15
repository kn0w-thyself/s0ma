---
name: doctor
description: Work out why s0ma is not doing what it should, from `s0ma-launch status` and `s0ma doctor`, and say what each finding means. Use when s0ma tools are missing or something behaves oddly.
---

# Find out what is wrong with s0ma

Two commands, in this order. Both read local files only and change nothing, so
run them without asking. Then explain, do not paste: say what is wrong and what
to do about it, in the order that unblocks the person fastest.

## 1. Is s0ma reachable at all?

```bash
s0ma-launch status
```

If the command itself is not found, the plugin's programs are not on the path:
check `/plugin` lists s0ma as enabled, then restart Claude. If it runs, read
these lines:

- **Runs here / Why** — which copy of s0ma would start, and the reason.
  `nothing yet` means nothing is installed: run `/s0ma:setup`.
- **Project** — the directory s0ma treats as the project, and whether it is
  pinned. A pin that names a version nobody installed is a common cause of
  "s0ma stopped working": `/s0ma:update` covers pinning.
- **License key** — present or not, and its last four characters. That is all
  anyone ever sees of it, here or anywhere else.
- **Subscription** — the last answer the account service gave.
  `not checked yet` is normal on a machine that has never downloaded anything.
- **uv** — the path in use. Missing uv is the one failure that stops everything,
  including the s0ma server itself; `/s0ma:setup` step 1 fixes it.

If a command exits non-zero, the number says what happened: 2 the command line
was wrong, 3 s0ma is not installed, 4 no license key or it was refused, 5 the
network could not be reached, 6 a download did not match its checksum, 7 uv is
missing.

## 2. Are the toolchain and the project healthy?

```bash
s0ma doctor
```

It diagnoses rather than gates, so it exits 0 even with findings. Read its
sections in this order:

- **versions** — the four s0ma packages and the Python they run on. They should
  all carry the same version; if they do not, the install is mixed and
  `/s0ma:update` is the fix.
- **project** — the project it found, or a plain statement that there is none.
  No project is only a problem if the person expected one; otherwise offer
  `/s0ma:new` or `/s0ma:retrofit`.
- **mcp** — whether the server program exists and how it would be registered.
- **findings** — each one marked `info`, `warning` or `error`, most with a
  `->` line saying what to do. Work errors first, then warnings, and say out
  loud which `info` lines are expected rather than listing them all.

The last line is `ok` or `BROKEN ENVIRONMENT`. Only the second one means the
installation itself cannot be trusted.

## 3. Say what to do next

End with one recommendation, not a list. If nothing is wrong and the person
still cannot do what they wanted, the problem is in their project rather than
in s0ma — run `s0ma check` and `s0ma verify build` there and read those
instead. If s0ma itself is at fault, `/s0ma:feedback` sends a report, and they
approve exactly what it contains before anything leaves the machine.
