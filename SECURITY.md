# Reporting a security problem

If you have found a security problem in s0ma, we want to hear about it — and we
would rather hear about it privately, before anyone else does. This page says
how to reach us, what helps, what you can expect back, and what counts.

## Report it privately

**First choice — GitHub's private vulnerability reporting.** Open the
repository's **Security** tab and choose **Report a vulnerability**:

<https://github.com/kn0w-thyself/s0ma/security/advisories/new>

It keeps your report, the conversation, the fix and the published advisory in
one private thread, and it is the route that credits you automatically when the
advisory goes out.

**Second choice — email.** Write to **security@kn0wthyself.ai**. That address
goes to a person. Use it if you would rather not use GitHub, or if you cannot
reach the repository at all.

**Please do not open a public issue, a discussion, or a pull request** for
anything that could be used against somebody before it is fixed. A public report
is a working exploit handed to everyone who reads it, including the people you
are trying to protect. If you are not sure whether what you have found is a
security problem, treat it as one and tell us privately — we will say if it is
not, and no harm is done.

There is also a machine-readable contact file at
<https://kn0wthyself.ai/.well-known/security.txt>.

## What to include

The more of this you can give us, the faster the fix:

- **What you found**, and why you think it is a problem.
- **Where** — which package, which command, which file, or which address.
- **How to reproduce it**, in as few steps as you can manage. A short
  reproduction is the difference between a fix this week and a fortnight of
  questions.
- **What somebody could do with it** — the impact, in your own words.
- **Your versions.** `s0ma doctor` prints them, along with the paths it found
  things at. Paste its output; trim the paths if you would rather not share
  them.
- **How you would like to be credited**, if you would like to be.

Please take out anything from your own project that you would not want us to
have, and never send us a key, a token or a password of any kind. We do not need
your source code to fix a bug in ours.

## What to expect, and when

These are the times we think we can keep. They are a commitment to answer, not a
service-level agreement, and they are counted in working days:

- **We acknowledge your report within 3 working days**, so you know a person has
  it.
- **We give you an assessment within 10 working days**: whether we agree it is a
  security problem, how serious we think it is, and what we intend to do. If we
  disagree, we say why rather than going quiet.
- **We tell you when it is fixed**, and in which release.
- **We ask you to hold the details private until a fix is out, or for 90 days
  from your report, whichever comes first.** If we need longer than that we will
  come back to you and say why, rather than let the clock run out in silence.
- **We credit you by the name you choose**, or leave you out of it if you prefer.

This is a very small project — one maintainer — so we answer as people rather
than as a process. If something is going to take a while, we would rather tell
you that than say nothing.

**There is no bounty programme.** We do not pay for reports. We say so plainly
so that nobody spends their evening on one expecting otherwise. What we can
offer is a quick, human answer, credit where you want it, and our genuine
thanks.

## Which versions get fixes

**The newest release.** s0ma is a pre-1.0 product under active development and
all four packages ship one version together, so a security fix goes out in a new
release rather than being carried back into an older one. Updating is the
supported way to get a fix. [How releases work](docs/RELEASING.md) explains the
versioning.

## What is in scope

- **The four packages** — `s0ma-core`, `s0ma-dsl`, `s0ma-mcp` and `s0ma-studi0`.
- **The launcher, the Claude Code plugin and the Claude Desktop extension**
  under [`integrations/`](integrations) — the pieces that start s0ma for a
  coding agent and keep it current.

## What is not

- **Denial of service by volume**, and scanner output with no demonstrated
  impact. A report that something is slow under load is welcome as an ordinary
  bug; it is not handled as a vulnerability.
- **Social engineering, phishing, and physical access** — anything aimed at a
  person rather than at the software.
- **Services we buy rather than build.** Report those to the company that runs
  them. Tell us too, and we will follow it up.
- **Findings that need an attacker to already be on the machine** — anything
  that assumes administrator or root access, or control of the account of the
  person using s0ma. If you are already there, s0ma is not what is protecting
  the machine.

## Safe harbour

If you are researching in good faith and you follow this page, we will not bring
or support legal action against you over your research, and we will say so
publicly if somebody else does.

Good faith means, in plain words: use your own installations and your own
data; do not read, change or delete anybody else's; stop as soon as you have
shown that a problem exists, rather than seeing how far it goes; do not degrade
anything other people rely on; and give us a reasonable chance to fix it before
you tell the world. If you are not sure whether something crosses a line, ask us
first — we would much rather have the conversation.

## What s0ma does on your machine

Security-minded people usually want these four facts before anything else. Each
one is written up properly — with the test or gate that holds it — in
[what s0ma trusts](docs/trust-model.md), which is the page to read rather than
this summary:

- **Nothing about your project is sent anywhere.** Not a file, not a name, not a
  count, by any part of s0ma.
  ([every connection s0ma can make](docs/trust-model.md#every-connection-s0ma-can-make))
- **Nothing checks a licence or an entitlement in order to run.** There is no
  check before s0ma starts and nothing that switches it off, and nothing built
  from this repository contacts a service unless you ask it to.
  ([what never happens](docs/trust-model.md#what-never-happens))
- **The feedback function is the only part of s0ma that sends your words
  anywhere, and you read and approve the exact report first.** Silence is no,
  and no flag skips the question.
  ([feedback](docs/trust-model.md#feedback-nothing-leaves-without-you))
- **The viewer listens only to your own machine.** `s0ma studi0` binds the
  loopback address, answers `GET` and nothing else, and writes nothing in
  response to any request. The optional HTTP view of a project's self-model is
  different, and the reasons are set out there.
  ([what listens, and to whom](docs/trust-model.md#what-listens-and-to-whom))

## Elsewhere

- [Contributing to s0ma](CONTRIBUTING.md) — how to ask a question or report an
  ordinary bug.
- [Code of conduct](CODE_OF_CONDUCT.md).
- [What s0ma trusts](docs/trust-model.md) — the full account, with its proofs.
