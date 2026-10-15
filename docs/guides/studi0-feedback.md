# Look at what you built, then tell us what is wrong with it

This guide walks one path end to end: put your project on screen in the studi0
viewer, notice something that does not work the way it should, and send that
observation to the people who make s0ma — with the whole report in front of you,
and nothing leaving your machine until you say so.

It is the path the documentation model records as `journey:studi0-feedback`.
Every command below — except the one that serves until you stop it — is replayed
by that journey's evidence (`docs/s0ma_src/evidence/studi0-feedback.json`), so a
command that stopped working cannot keep sitting in this guide looking correct.

**Before you start.** You have a s0ma project you have built at least once, and
you have met the words *module*, *intent*, *self-model* and *registry snapshot*
— the first-project guide is where those are taught. Reading the picture needs
nothing but the project. Sending feedback from inside s0ma is the hosted
channel's feedback function, which the public repository's first release does
not offer: it needs the feedback access a keyed install gives a machine, and
[§4 of the hosting guide](../hosting-getting-started.md#4-sending-feedback) says
how that works. Without it the sending step refuses and says so, and
a [bug report](https://github.com/kn0w-thyself/s0ma/issues/new/choose) or a
[discussion](https://github.com/kn0w-thyself/s0ma/discussions) on the repository carries the same observation with nothing to set up.

---

## 1. Put the project on screen

```bash
s0ma studi0
```

studi0 serves a small viewer on `127.0.0.1` — your own machine, nothing else —
and opens it in a browser. It prints the address it chose; pass `--no-open` if
you would rather open that address yourself.

The viewer is read-only in the strongest sense: it reads the artifacts your last
build produced, it writes nothing back into the project, and it never runs your
application. Looking at your system cannot change it.

What you are looking at is **proprioception** — the faculty of self-knowledge
that answers *what is this system made of*. Every box is a component your source
declared. The lines between them are the relationships: the ones you wrote down,
the ones the toolchain worked out from what you wrote, and the ones your tests
claim to cover. The whole picture is assembled from the project's own self-model
rather than guessed at by reading the code.

**If the page is empty**, the viewer is running and there is nothing built for
it to draw — that is the `NOT_BUILT` answer. Build the project once and reload
the page. The viewer repaints as builds land, so nothing needs restarting.

## 2. The picture is the build's own graph

The viewer does not draw a simplified version of your project. When the page
asks for what it draws, studi0 hands back the graph exactly as the build
produced it, wrapped in the reading number it belongs to — no projection, no
summary, no dropping of fields the viewer does not itself use.

You can hold the same document in your hand:

```bash
s0ma graph . --format json --detail full
```

That is the same graph, at the same level of detail, from the same source. The
launch command's own description says so in as many words. It matters because it
is what stops the picture and the project drifting apart: there is one graph,
and the viewer is a way of looking at it rather than a second opinion about it.

So when the picture surprises you — a component in a layer you did not expect, a
line between two things you thought were unrelated, a name you no longer
recognise — the surprise is about your project, not about the viewer.

## 3. Tell us what you noticed

Say the picture showed you something and the viewer made it needlessly hard to
see. That is worth telling us, and it takes one command:

```bash
s0ma feedback -m "the graph view did not say which reading it was showing"
```

One line is a whole report. s0ma writes it up, shows it back to you, and asks
you two questions. Nothing else is asked, and nothing is sent before both
answers.

**What you see first.** One heading, and then the whole report:

```text
This is the exact feedback data that would be sent — nothing else:
```

It is printed field by field under plain labels — Summary, Category, Impact,
About this install, What this report carries, What was removed — in your own
words, unedited, and every field that travels is shown. It ends with a
fingerprint of that exact report:

```text
  fingerprint: sha256:9f2c1ab4d7e05631…
  The whole fingerprint travels with this report, so the receipt that comes
  back can be checked against exactly what you approved.
```

**Then the two questions.** First, whether kn0wthyself may contact you about the
report: answering yes links it to your account email so the team can reply, and
answering no keeps it pseudonymous. Then the one that sends anything:

```text
Send exactly this feedback data? [y/N]
```

Anything but `y` sends nothing.

**There is no way around this step, and that is deliberate.** No flag skips the
approval. Run the command where there is no terminal to approve in — in a
script, or a pipeline — and s0ma composes nothing, saves nothing, sends nothing,
and tells you why:

```text
This needs a terminal: you have to see the exact feedback data, and approve it,
before anything is sent — and there is no way to do that without one.
Nothing was sent.
```

If you want to read the product's own account of all this before you type
anything, ask it:

```bash
s0ma feedback --help
```

## 4. What a feedback report carries, and what it never does

The answer is written down, in full, in the frozen feedback contract
[`docs/contracts/feedback-v1.md`](../contracts/feedback-v1.md). This section is
a plain-language reading of it; where the two differ, the contract is right.

**What the report is** ([§3.1, the envelope](../contracts/feedback-v1.md#31-envelope-s0ma-feedback1)):
your one-line summary, which kind of feedback it is, how much it is affecting
you, and — only if you were asked the longer questions and answered them — what
you expected, what actually happened, the steps, and any further detail. Nothing
else you did not write.

**What s0ma adds about your machine**
([§5, the context allow-list](../contracts/feedback-v1.md#5-context-allow-list-plan-55--nothing-else-enters-context)):
version numbers, your Python major and minor version, the operating-system
family, the processor architecture, which surface you were using, any diagnostic
codes involved, whether the thing succeeded or failed, a rough duration, and a
random installation id. That list is closed at both ends — the command builds
the report from it and nothing else, and the service refuses a report carrying
anything outside it.

**What is never sent, by construction** (§5 again): your source code, your file
contents, your prompts, your conversations with an agent, raw command output,
error traces, git remotes, repository or organization names, your account email,
your license key, and hardware identifiers. These are not filtered out at the
end; there is no path by which they get in.

**What is removed before you even see it**
([§7, redaction profile v1](../contracts/feedback-v1.md#7-redaction-profile-v1-plan-57--deterministic-ordered-idempotent)):
if the line you typed happens to contain a key, a token, an email address, a web
address, an absolute file path, your user name, a machine identifier or an error
trace, s0ma replaces it before the report is shown to you — and the report tells
you what it removed, under *What was removed*. You approve the redacted report,
because that is the one that travels.

**Pseudonymous, not anonymous**
([§12](../contracts/feedback-v1.md#12-user-facing-voice-and-recognition-rules-plan-512-owner-adjustments-a-1a-3-2026-08-27)):
each report carries a random id for this installation of s0ma, so the team can
tell two reports from one person apart without knowing who that person is. s0ma
does not claim anonymity it cannot deliver, and there is no `--anonymous` flag.

**Where it all sits** ([§8](../contracts/feedback-v1.md#8-local-state-layout-plan-58--client-machines)):
unsent reports, the record of what you have sent, and this machine's feedback
access live in `~/.s0ma` (`%USERPROFILE%\.s0ma` on Windows) — outside every
project, and never in a repository.

## 5. If you said no, or it could not get through

The report is saved as a draft just before the question that sends anything. So
a `no`, a closed laptop, or a network that was not there all leave you something
to come back to:

```bash
s0ma feedback drafts
```

That lists every report written on this machine and not yet sent, each with its
short identifier and the line you wrote. When there are none — including when
you never got as far as composing one — it says so plainly and tells you how to
start. Unsent reports are kept for 30 days and then removed; the listing is
where that tidying happens, and it tells you when it has happened.

To finish sending one, name it:

```bash
s0ma feedback submit fbd_1a2b3c4d
```

The saved report is shown again in full, the contact answer you already gave is
repeated back to you, and the same send question is asked again. The review is
not a formality you cleared once: nothing goes anywhere without a second look at
exactly what would travel.

## If something goes wrong

- **The viewer draws nothing.** Nothing has been built yet. Build once, reload.
- **`s0ma studi0` says the viewer is not installed.** The viewer ships as its
  own optional package, `s0ma-studi0`.
- **A feedback command says this machine is not connected**, or reports
  `INVALID_TOKEN`. The access code for feedback is not your license key, and it
  can expire or be withdrawn. Run `s0ma feedback enroll` to connect this machine
  again — nothing you wrote is lost, and unsent reports stay in
  `s0ma feedback drafts`. The full table of what the service can answer, and
  what to do about each answer, is
  [§5 of the hosting guide](../hosting-getting-started.md#5-troubleshooting).
- **Everything after the install** — check failures, stale builds, the viewer —
  is in [`docs/troubleshooting.md`](../troubleshooting.md).

## What this path taught

- **Proprioception** — the faculty of self-knowledge that answers what a system
  is made of. The viewer is that faculty with a picture attached.
- **Feedback** — a report to the people who make s0ma, prepared on your own
  machine, shown to you whole, and sent only after you have approved that exact
  report. Preparation is local and needs no network; approval is the only thing
  that sends anything; and what you approved is what is transmitted, what is
  stored, and what the receipt refers back to.
