# Watch an app being built

This guide puts a small app on screen in studi0, s0ma's local viewer, and then
has you watch your own coding agent build one like it, one request at a time.
You do not need to write any code. You read what the page shows you, and you
paste three requests.

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
s0ma new project example --template pipeline
```

This makes a folder called `example` and builds it once. The app inside reads
what is playing, measures how the song sounds, settles on a mood, chooses a
small suggestion for that mood, and shows the suggestion as the text of a small
web page. It contacts nothing: the songs are built-in samples.

Now open it in studi0:

```bash
s0ma studi0 example
```

studi0 serves a page on your own machine, prints its address, and opens it in
your browser. It keeps running until you stop it with Ctrl+C, so leave this
terminal alone and use another one for the next command.

**What you are looking at.** Each box is a part of the app. The parts sit in
bands, one per *layer*. The two middle bands hold the app's own subject and the
work on it. The top and bottom bands are its two edges: one faces the person
using the app, and one faces the world outside it. A file may reach toward the
middle but never outward, and the two edges never reach each other. The parts
are grouped by *module*, which is one `.s0ma` file and everything declared in
it. This app has four: `player`, `music`, `coach` and `page`, one per layer. The
status line reads "12 of 19 components shown". The other seven are the app's
tests and its generated docs, which stay hidden until you press
`tests and docs`.

**Click `settle_mood`.** It is in the `music` module. A panel opens with the
part's own account of itself. Each line starts with the s0ma word for it, and a
plain phrase follows:

- `intent · what it is for`: "Decides which mood a song puts across, from how
  it sounds." The *intent* is the one sentence that says what a part is for.
- `guarantees · what it promises`: "Gives back exactly one of four moods:
  lively, tense, calm, or low."
- `forbids · what it must never do`: "Never picks a mood outside those four."
- `expects · what it needs before it runs`: "The scores for how a song sounds."

Under those come `dependencies · what it leans on` and
`dependents · what leans on it`. `settle_mood` leans on `Features` and `Mood`,
and `song_to_page` leans on it. Every sentence in the panel is the text the
app's author wrote, exactly as written.

**Click a word with a dotted underline.** Click `guarantees`. The panel shows
s0ma's own definition under the word, and it starts "`guarantees` is explained
under `contract`". A part's *contract* is those three lines together: what it
needs, what it promises, and what it must never do.

**Press `terms`.** The panel turns into a dictionary of s0ma's words, headed
"Terms", with the words this page can show listed first under "On this page".
Press `terms` again to go back to `settle_mood`.

**Click a module's name.** Click `music` where it labels its group of parts.
The panel shows the module instead: "This file holds what the app knows about
music: a song, how it sounds, and the mood it settles on."

Keep this tab open if you like. You will want it later to compare with.

## 3. Now watch one being built

**What your agent builds will differ from the example.** An agent chooses its
own names and writes its own sentences, so your parts will not match the
example's word for word, and the counts below may not match either. The page
always shows what was really built. The example from section 2 is there so you
can compare.

**Start a new, separate project.**

```bash
s0ma new project song
```

This makes a folder called `song` and builds it once. It holds one starter
part, `describe_self` in the module `core_domain`, which a new project made
without a template begins with.

**Open studi0 on it,** in its own terminal:

```bash
s0ma studi0 song
```

The page shows the starter part, and a list headed "What changed since you
opened this page" that says "Nothing yet." It numbers the builds it sees from
the moment you open the page, so the first build your agent makes that changes
a part is "Build 1". A reload clears the list.

**Start your agent in the `song` folder,** so the project it works on is the one
studi0 is showing. Then give it the three requests below, one at a time. Paste
each one exactly, and wait until the agent says it has built the project before
you paste the next.

### Request 1: read what is playing, and settle on a mood

```text
In this s0ma project, start a small app that reads what is playing and settles on a mood. Add a player file that gives the song playing now, picked from a few built-in sample songs, so the app contacts nothing. Add a music file with a song, a mood, and a part that settles on a mood from the song. Then check the project and build it.
```

**What to look for.** Within about a second of the build, the new parts arrive.
Each one carries a mark for a few seconds, then keeps a thin double outline,
and the status line adds "Outlined parts arrived in the newest build." The list
of changes gains its first entry. For the example's version of this build it
reads "Build 1 · added 4 parts", then names them: `Mood`, `Track`,
`settle_mood`, `read_now_playing`. A line such as "2 more parts are hidden by
the toolbar toggles." counts the parts the toolbar keeps out of view, here the
new tests. Click any new part to read its
`intent` and its contract.

### Request 2: measure how the song sounds

```text
Now add a part to the music file that measures how a song sounds, as a few scores: how fast it feels, how much energy it has, and how bright it sounds. Then change the part that settles the mood so it works from those scores instead of from the song itself. Check the project and build it.
```

**What to look for.** This build adds parts and changes one. The outline moves
to the parts this build added, and the parts from request 1 lose theirs. The
new entry sits at the top of the list. For the example it reads
"Build 2 · added 2 parts, changed 1", with the changed part named and then the
lines that changed: "changed settle_mood: intent, expects, dependencies". Those
are the very lines you read in its panel. Click the changed part and read them
again. In the example, the part now says it needs scores, not a song. The `changes` button in
the toolbar hides the list and shows it again.

### Request 3: choose a suggestion, and show it on a page

```text
Now add a coach file and a page file. The coach file chooses a small suggestion that fits the mood, and watches the moods the app settles on to notice when they keep flipping back and forth. The page file shows the suggestion as the text of a small web page. Check the project and build it.
```

**What to look for.** A build that adds more than four parts across more than
one module does not drop them all on the page at once. It shows them one module
at a time, about two seconds apart, and a module arrives after the modules it
leans on. While that runs, the status line says how far it has got. For the
example it reads "This build added 6 parts. Showing 3 of 6, module by module.",
and a `Show the rest` button beside it shows everything at once. The entry in
the list of changes names only the parts shown so far, and it is complete when
the last module lands. If your computer is set to reduce motion, all the parts
arrive at once instead.

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
- **A banner says a module "has changed since the last build".** Its source
  file changed after the last build, so the page is still showing that last
  build. This is normal while your agent is partway through a request. The
  banner goes when the next build lands.
- **The page says "Nothing is built yet."** The project has no build for the
  page to draw. Ask your agent to build it, or run `s0ma build` in the project
  folder yourself. The page repaints as soon as the build lands.
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
  `settle_mood` quoted above. Then making `song` with `s0ma new project`, and
  landing the example's own three builds in it, one after another, from the
  sources committed with studi0's tests. After each build the transcript reads
  the graph again and finds the parts that build added.
- **Not replayed:** your agent's work. The agent writes its own files and makes
  its own `build_project` call, and no replay can stand in for a model. The
  transcript uses `s0ma build` in its place, on the example's sources.
- **Not replayed:** `s0ma studi0` itself. It serves until you stop it, so a
  replay cannot wait for it to finish. The page also asks `/api/state`, about
  once a second, whether a new build has landed, and that is only answered
  while studi0 is running.

So what the page reads is tested: the example in section 2, and the growth
from build 1 to build 3 as the example's sources describe it. How the page
draws it in a browser is not replayed here, which is why its sentences are
held to its source instead. Your own agent's three builds are not tested at
all, and this guide makes no promise about what they contain.

## What this path taught

- **Layer**: the band a file and its parts belong to. A file may reach toward
  the middle of the app, never outward, and the two edges never reach each
  other.
- **Module**: one `.s0ma` file and the parts declared in it.
- **Intent**: the one sentence that says what a part is for.
- **Contract**: what a part needs before it runs, what it promises, and what
  it must never do, written as its `expects`, `guarantees` and `forbids`.
