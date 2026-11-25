# Watch an app being built

This guide puts a small app on screen in studi0, s0ma's local viewer, and then
has you watch your own coding agent build one like it, one request at a time.
You do not need to write any code. You read what the page shows you, and you
paste six requests.

It is the path the documentation model records as
`journey:watch-an-app-being-built`. The commands you type are replayed by that
journey's evidence, two transcripts under `docs/s0ma_src/evidence/`, one for
each project you make. Your agent's work cannot be replayed, because no two
agents write the same thing. [How this page is kept true](#how-this-page-is-kept-true) says exactly
where the line falls.

## 1. What you need

- s0ma installed, with its viewer. The viewer ships as its own package,
  `s0ma-lang-studi0`, and `s0ma doctor` lists it with its version when it is
  installed.
- A coding agent connected to s0ma's authoring server, the MCP server that
  ships with s0ma. [Point the agent at the server](mcp-authoring.md#point-the-agent-at-the-server)
  shows how.
- A browser, and a folder where you keep projects. Run every command below in
  that folder.

## 2. Look at a finished app first

Start with an app that is already finished. Nothing here needs your agent, and
every step comes out the same each time.

```bash
s0ma new project example --sample
```

This makes a folder called `example` and builds it once. `--sample` lays down
s0ma's own sample app, a small support-inbox agent. It reads a customer's
message and picks out the order number, if there is one. Then it answers from a
short list of common answers, looks up the order, or hands the message to a
person, and it checks every reply against its rules before it goes out. A
watcher counts how many messages go to a person. It contacts nothing: a
scripted stand-in plays its model, and the answers and the orders are built in.
The sample is made in five steps, and `--sample` lays down all five at once.

Now open it in studi0:

```bash
s0ma studi0 example
```

studi0 serves a page on your own machine, prints its address, and opens it in
your browser. It keeps running until you stop it with Ctrl+C, so leave this
terminal alone and use another one for the next command.

**What you are looking at.** Each box is a part of the app. The parts sit in
bands, one per *layer*, and this agent fills three. The middle band, `DOMAIN`,
holds the agent's own subject: a message, a reply, the rules, and the port its
model plugs into. The top band, `APPLICATION`, holds the work on that subject:
deciding what to do with a message, and watching the replies. The bottom band,
`INFRASTRUCTURE`, faces the world outside: the two tools and the stand-in
model. A file may reach toward the middle but never outward. The page draws a
band only for a layer that has a part in it, and no part of this agent faces
the person using it, so that edge has no band here. The parts are grouped by
*module*, which is one `.s0ma` file and everything declared in it. This agent
has seven on the page: `triage` and `watch` at the top, `inbox`, `model` and
`rules` in the middle, and `scripted_model` and `tools` at the bottom. The
status line reads "10 of 16 components shown". The other six are the agent's
tests, which stay hidden until you press `tests and docs`.

**Click `keep_the_rules`.** It is in the `rules` module. A panel opens with the
part's own account of itself. Each line starts with the s0ma word for it, and a
plain phrase follows:

- `intent · what it is for`: "Checks a reply against the rules before it goes
  out." The *intent* is the one sentence that says what a part is for.
- `guarantees · what it promises`: "Gives back the reply unchanged when it
  keeps the rules, and a hand-off to a person when it does not."
- `forbids · what it must never do`: "Never lets out a reply that promises a
  refund."
- `expects · what it needs before it runs`: "A reply the agent wants to send."

Under those come `dependencies · what it leans on` and
`dependents · what leans on it`. `keep_the_rules` leans on `Reply`, and
`decide` leans on it. Every sentence in the panel is the text the app's author
wrote, exactly as written.

**Click a word with a dotted underline.** Click `guarantees`. The panel shows
s0ma's own definition under the word, and it starts "`guarantees` is explained
under `contract`". A part's *contract* is those three lines together: what it
needs, what it promises, and what it must never do.

**Press `terms`.** The panel turns into a dictionary of s0ma's words, headed
"Terms", with the words this page can show listed first under "On this page".
Press `terms` again to go back to `keep_the_rules`.

**Click a module's name.** Click `rules` where it labels its group of parts.
The panel shows the module instead: "This file holds what the agent must do
and what it must never do."

Keep this tab open if you like. You will want it later to compare with.

## 3. Now watch one being built

**What your agent builds will differ from the example.** An agent chooses its
own names and writes its own sentences, so your parts will not match the
example's word for word, and the counts below may not match either. The page
always shows what was really built. The example from section 2 is there so you
can compare.

**Start a new, separate project.**

```bash
s0ma new project helpdesk --sample --step 0
```

This makes a folder called `helpdesk` that holds the same sample at step 0:
its project file and the notes it leaves for a coding agent, with no module
and nothing built. It is where the example started before its five steps.

**Open studi0 on it,** in its own terminal:

```bash
s0ma studi0 helpdesk
```

Before it serves, studi0 warns that `bootstrap/main.py` does not exist. The
project's settings name that file as the agent's entry point, and nothing has
written it yet. The page says "Nothing is built yet. Parts appear here when
the first build lands." The page also has a list headed "What changed since
you opened this page" that says "Nothing yet." It numbers the builds it sees from
the moment you open the page, so the first build your agent makes is
"Build 1". A reload clears the list.

**Start your agent in the `helpdesk` folder,** so the project it works on is
the one studi0 is showing. Then give it the six requests below, one at a time.
Paste each one exactly, and wait until the agent says it has built the project
before you paste the next. The first five ask for the sample's five steps, and
the sixth changes a part that is already there.

### Request 1: what it hears

```text
In this s0ma project, start a small support-inbox agent. Add an inbox file with a customer message, and a part that reads what a customer wrote and picks out the order number in it, if there is one. Then check the project and build it.
```

**What to look for.** Within about a second of the build, the new parts arrive.
Each one carries a mark for a few seconds, then keeps a thin double outline,
and the status line adds "Outlined parts arrived in the newest build." The list
of changes gains its first entry. For the example's version of this build it
reads "Build 1 · the first build, added 2 parts", then names them: `Message`
and `read_message`. A line under it counts the parts the toolbar keeps out of
view, here the new test. Click any new part to read its `intent` and its
contract.

### Request 2: what it must and must never do

```text
Now add a rules file. It holds a reply, which either answers a message or hands it to a person, and a part that checks a reply before it goes out and hands it to a person instead if it promises a refund. Check the project and build it.
```

**What to look for.** The outline moves to the parts this build added, and the
parts from request 1 lose theirs. The new entry sits at the top of the list.
For the example it reads "Build 2 · added 2 parts" and names `Reply` and
`keep_the_rules`, the part you clicked in section 2.

### Request 3: its tools

```text
Now add a tools file with two tools that contact nothing: one finds the written answer to a common question in a short list, and one looks up where an order is in a short built-in list. Check the project and build it.
```

**What to look for.** A new band opens at the bottom of the page, because the
tools are the agent's edge toward the world outside. For the example the entry
reads "Build 3 · added 2 parts" and names `answer_from_faq` and
`look_up_order`.

### Request 4: how it decides

```text
Now add how the agent decides. Add a model file with a port for the model that picks what to do with a message, and a scripted stand-in for that model, so the agent runs with no account and no network. Add a triage file with a part that decides what to do with one message: answer from the list, look up the order, or hand it to a person. Every reply it writes goes through the rules. Check the project and build it.
```

**What to look for.** This build adds parts to three modules at once, and the
top band opens for `decide`. For the example the entry reads
"Build 4 · added 3 parts" and names `ReplyModel`, `ScriptedModel` and
`decide`. The line "2 more parts are hidden by the toolbar toggles." counts
the two new tests.

A build that adds more than four parts in view across more than one module
does not drop them all on the page at once. It shows them one module at a
time, about two seconds apart. While that runs, the status line says how far
it has got, and a `Show the rest` button beside it shows everything at once.
The example's version of this build adds three parts in view, so they arrive
together. Press `tests and docs` before it lands and the two new tests count
too: the status line then reads "This build added 5 parts. Showing 1 of 5,
module by module." The entry in the list of changes names only the parts shown
so far, and it is complete when the last module lands. If your computer is set
to reduce motion, all the parts arrive at once instead.

### Request 5: the check that watches it

```text
Now add a watch file with a watcher that counts how many of the agent's replies go to a person, and reports when more than half of them do. Check the project and build it.
```

**What to look for.** For the example the entry reads "Build 5 · added 1 part"
and names `watch_replies`, in the top band beside `decide`. The status line now
reads "10 of 16 components shown", as it did for the finished example.

### Request 6: change a rule

```text
Now change the rules so the agent also never promises a delivery date. Check the project and build it.
```

**What to look for.** This build adds nothing and changes one part. While your
agent is still editing, a banner may say "Changes detected. View updates after
next build." When the build lands, the changed part carries its own mark for a
few seconds, and no part keeps an outline, because nothing arrived. For the
example the entry reads "Build 6 · changed 1 part", with the changed part named
and then the lines that changed: "changed keep_the_rules: forbids". That is a
line you read in its panel in section 2. Click `keep_the_rules` and read it
again. In the example it now says "Never lets out a reply that promises a
refund or a delivery date." The `changes` button in the toolbar hides the list
and shows it again.

### The agent's own account, if it gives one

While studi0 is open on a project, s0ma's authoring server asks the agent
working there to write one short line about each main step it takes. If your
agent does, a pane headed "agent narration" appears under the list of changes,
with the line "self-reported by the agent working here". studi0 checks none of
it. The parts on the page come from the build. The narration is only what the
agent says it is doing.

## 4. If something looks off

- **Nothing arrives after a request.** The page changes only when a build
  lands. Ask your agent whether it built the project, and ask it to check and
  build if it did not. Then make sure studi0 is open on the same folder your
  agent is working in.
- **A banner says "Changes detected. View updates after next build."** A
  source file changed after the last build, so the page is still showing that
  last build. This is normal while your agent is partway through a request.
  The banner goes when the next build lands.
- **The page still says "Nothing is built yet." after a request.** The
  project has no build for the page to draw. Ask your agent to build it, or
  run `s0ma build` in the project folder yourself. The page repaints as soon
  as the build lands.
- **Something on the page is wrong, or hard to read.** Tell us.
  [Seeing your system, and telling the s0ma team what you found](studi0-feedback.md)
  is how, and it lists the repository's issues and discussions as a route
  that needs nothing set up.

## How this page is kept true

The commands in this guide are replayed by its journey's evidence, and the
quotes from the page are checked against studi0's own page source. What the
replay does, and what it cannot do:

- **Replayed:** making the example with `s0ma new project`, and reading back
  the same graph the page draws from `/api/graph`, including every line of
  `keep_the_rules` quoted above. Then making `helpdesk` with `s0ma new project`
  at step 0, and growing it with the sample's own five steps, one after
  another, each of which builds. After the last step the transcript makes the
  change request 6 asks for by hand: it adds the new rule to `rules` and its
  test, and builds with `s0ma build`. After each build it reads the graph again
  and finds the parts that build added, or the line it changed.
- **Not replayed:** your agent's work. The agent writes its own files and makes
  its own `build_project` call, and no replay can stand in for a model. The
  transcript uses the sample's own steps and one hand edit in its place.
- **Not replayed:** `s0ma studi0` itself. It serves until you stop it, so a
  replay cannot wait for it to finish. The page also asks `/api/state`, about
  once a second, whether a new build has landed, and that is only answered
  while studi0 is running.

So what the page reads is tested: the example in section 2, and the growth
from step 0 to the finished agent and its one change, as the sample's own
steps describe it. How the page
draws it in a browser is not replayed here, which is why its sentences are
held to its source instead. Your own agent's six builds are not tested at
all, and this guide makes no promise about what they contain.

## What this path taught

- **Layer**: the band a file and its parts belong to. A file may reach toward
  the middle of the app, never outward, and the two edges never reach each
  other.
- **Module**: one `.s0ma` file and the parts declared in it.
- **Intent**: the one sentence that says what a part is for.
- **Contract**: what a part needs before it runs, what it promises, and what
  it must never do, written as its `expects`, `guarantees` and `forbids`.
