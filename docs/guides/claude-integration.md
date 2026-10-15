# s0ma in Claude

s0ma gives Claude a self-model of the software you are building — an accurate,
queryable account of what each part is for, what it depends on, and why — so
answers about your project come from the project itself. Installed through
Claude it is one plugin (Claude Code) or one extension (Claude Desktop), and
after that it looks after itself.

This page is the whole route: what to install, where your key goes, how updates
behave, how to hold a project still, and how to take it all off again.

**The short version.**

- **Claude Code** — add the kn0wthyself marketplace, install `s0ma@kn0wthyself`,
  answer three settings, run `/s0ma:setup`.
- **Claude Desktop** — open the s0ma extension file and answer two settings.
- **Your key** goes in the masked settings field — or into `s0ma-launch
  activate` at a terminal of your own. Never into a conversation.
- **Updates** are fetched quietly in the background and used from your *next*
  session — never in the middle of one. The version you were on is kept.
- **One project on one version:** `s0ma-launch pin` holds it there,
  `s0ma-launch unpin` lets it follow along again.
- **A project that already carries its own s0ma** is never moved by any of this.

## Not the route the public repository offers

**Nothing on this page is part of the public repository's first release.** That
release offers one way in — clone the repository and build from it — stated
once in [Getting started §1](../getting-started.md#1-create-a-real-project),
with its commands in the root `README.md` "Install" section. The plugin, the
marketplace and the Desktop extension are built and work; publishing them is a
later step, and this page is the account of the route they make, kept for when
that step is taken. Until then:

- **Claude Code** installs from a folder. Point it at the folder that holds
  `.claude-plugin/marketplace.json` — in a checkout of the s0ma repository that
  is `integrations/claude/`:

  ```text
  /plugin marketplace add <path to that folder>
  /plugin install s0ma@kn0wthyself
  ```

  Everything after this section is the same either way.

- **Claude Desktop** needs the extension built first. From a checkout:
  `scripts/pack_desktop_extension.sh`. It stages the extension outside the
  repository, and prints the two commands that pack it when the packer is not
  already installed.

When this route is published, the marketplace lives at
`kn0w-thyself/claude-plugins` and the extension file is published alongside it.

## What you need first

**uv.** One small program, the only thing s0ma asks of your machine: it looks
after s0ma's own Python environments. Install it from
<https://docs.astral.sh/uv/getting-started/installation/>, or with the one line
for your platform:

```text
macOS, Linux:  curl -LsSf https://astral.sh/uv/install.sh | sh
Windows:       powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
```

Restart Claude afterwards, so it can see the new program.

**A key**, if you want the download. Your key from account.kn0wthyself.ai is
what fetches s0ma's own files and nothing else. Running s0ma from a source
checkout needs no key at all.

You do not need to install Python. uv provides one.

## Install in Claude Code

1. **Add the marketplace.** Ours needs nobody's approval and is not Anthropic's:

   ```text
   /plugin marketplace add kn0w-thyself/claude-plugins
   ```

2. **Install the plugin.**

   ```text
   /plugin install s0ma@kn0wthyself
   ```

3. **Answer the three settings.** Claude asks for these when the plugin is
   enabled. Each is named here exactly as it appears on screen:

   | Setting | What to put there |
   |---|---|
   | **s0ma license key** | Your key. What you type is masked, and it is kept in this computer's own secure storage — never written into a settings file, never shown in a conversation. Leave it empty if you run s0ma from source. |
   | **How s0ma keeps itself current** | `auto`, `notify` or `off`. `auto` is the default and is what most people want; the section on updates below says what each one does. |
   | **Where uv lives on this computer** | Leave it alone. It exists for one failure: Claude started from a desktop icon cannot always see the programs your terminal can. If s0ma will not start, run `command -v uv` and paste that one path here. |

4. **Run `/s0ma:setup`.** It checks uv, reports what is installed, offers to
   install s0ma if nothing is, says where your key goes, and finishes with
   `s0ma doctor`. It works entirely through the terminal, so it still works when
   the s0ma server itself could not start — which is the usual reason for
   reading this page.

**Where the `s0ma-launch` commands on this page run.** The plugin puts `s0ma`
and `s0ma-launch` on the path of the terminal Claude Code itself uses, so
"run `s0ma-launch status`" is something you can simply ask Claude to do. They
are not added to your own shell's path: in a terminal of your own, those
commands exist only if you put them there — from a source checkout, or from the
plugin's own folder.

## Install in Claude Desktop

Claude Desktop takes an extension file rather than a plugin. Open it, drag it
onto the Claude Desktop window, or use **Settings → Extensions → Advanced
settings → Install Extension**. Claude Desktop shows you what the extension is
and what it asks for before anything is installed.

It asks for two settings, not three: **s0ma license key** and **How s0ma keeps
itself current**, both exactly as described above. There is no uv setting here,
because an extension of this kind is started by Claude Desktop through uv
itself, which is also why you do not have to install Python for it.

Claude Desktop runs on macOS and Windows, so the extension does too. On Linux,
use Claude Code.

One difference worth knowing: an extension you were given as a file is updated
by installing the newer file. The s0ma **toolchain** inside it still updates
itself exactly as described below — it is the wrapper, not s0ma, that stays
where it is.

## Where your key goes, and where it must never go

There are two right places, and a conversation is not one of them:

- **the masked settings field** in the plugin or the extension. What you type is
  not echoed and is stored by the operating system, not by a file in your
  project;
- **`s0ma-launch activate`**, typed by you at a terminal of your own — for
  anyone who has the launcher to hand, such as a source checkout. It prompts
  without showing what you type, checks the key once, and saves it in s0ma's own
  folder in your home directory. On macOS and Linux it makes that file readable
  by you and nobody else; on Windows it says plainly that it could not, and asks
  you to check the folder it is in. It needs a real terminal to type into and
  refuses anywhere else, so it is not something Claude can run for you.

If you installed through Claude and have not gone looking for the launcher on
your own machine, the settings field is your answer: it is the one place that
needs nothing else.

**Never type or paste a key into a chat.** No part of s0ma will ever ask you to,
and none of the `/s0ma:*` commands will either. A key pasted into a conversation
is a key in a transcript.

s0ma never prints your key back. The most anyone ever sees of it — in `status`,
in a message, in a log — is `s0ma_...` and its last four characters.

The key is used for one thing: fetching s0ma's own files from
account.kn0wthyself.ai. Nothing you write, and nothing about your project, ever
travels with it. [What s0ma trusts](../trust-model.md#what-s0ma-sends-when-it-is-installed-through-claude)
states exactly which requests exist, what each carries, and how to stop each
one.

## How updates work

The toolchain keeps itself current. When Claude starts s0ma, the version that
is installed starts immediately; then, separately and quietly, s0ma looks for a
newer one and installs it beside the old one. The newer one is used **from your
next session**. Nothing ever changes underneath a session in progress, and the
version you were on is kept.

The three answers to **How s0ma keeps itself current**, in plain words:

| Setting | What happens |
|---|---|
| `auto` | s0ma fetches a newer version in the background and starts using it next session. The default. |
| `notify` | s0ma looks, and tells you at the start of a session. Nothing is fetched until you ask. |
| `off` | s0ma never looks on its own. You can still update by hand whenever you want. |

Four things hold whatever the setting says:

- **s0ma never asks more than once a day**, and never at all without a key to
  ask with.
- **It only ever moves the copy s0ma installed for itself.** A project with its
  own s0ma, a project pinned to a version, and a checkout you pointed s0ma at
  are all left exactly as they are.
- **A failed update is silent.** It cannot interrupt a session or turn into an
  error in front of you. What went wrong is recorded: `s0ma-launch status`
  shows the last one, and `update.log`, in the launcher's corner of s0ma's own
  folder, has the detail.
- **An update can change generated files.** A newer toolchain is allowed to
  write a slightly different `build/` directory, so a project that needs its
  generated output to stay byte-for-byte stable should pin.

To do it deliberately, ask Claude for `/s0ma:update`, or run it yourself:

```text
s0ma-launch update --check     # asks whether there is a newer one; installs nothing
s0ma-launch update             # move to it now
```

`update` works even when the setting is `off`: `off` governs what s0ma does on
its own, not what you may ask for.

## Holding a project on one version

```text
s0ma-launch pin <version>      # the version you want, written into .s0ma-version
s0ma-launch unpin              # follow the newest installed version again
```

`pin` writes one small file, `.s0ma-version`, in the project directory. While it
is there, nothing moves that project — not an automatic update, not a manual
one. Commit the file and everyone working on the project is held on the same
version.

**Going back** is the same command. The previous version is always kept after an
update, so pinning it puts the project back on it. If you pin a version this
machine does not have, s0ma says so and names the command that fetches it:
`s0ma-launch install --version <the version>`.

To see what is installed and what would run here, ask for `/s0ma:doctor`, or run
`s0ma-launch status` — it reads local files only and contacts nothing.

## The plugin updates separately from s0ma itself

Two different things update on two different schedules, and neither updates the
other. The toolchain looks after itself, as above. The plugin is Claude's to
manage — and **Claude only auto-updates Anthropic's own marketplaces.** Ours is
not one, so a new plugin arrives when you ask for it:

```text
/plugin update s0ma@kn0wthyself
```

To stop thinking about it, turn auto-update on for our marketplace once:
`/plugin` → **Marketplaces** → **kn0wthyself** → **Enable auto-update**. Claude
then checks after a session has started and asks you to reload; the session you
are in keeps the version it loaded.

The plugin is deliberately thin — configuration, six named commands, a start-up
notice and the small program that starts s0ma — so it changes rarely, and a
slightly old one is not a problem.

## When you are offline

Everything that is already on your machine works. s0ma starts the version you
have, `s0ma-launch status` answers in full, and the quiet update simply fails
and writes one line down where `status` can show it to you later.

A deliberate `install` or `update` with no network says so plainly — that it
could not reach the service, that the copy on this machine keeps working, and to
try again when the network is back. Nothing is half-installed: a version is
built beside the one in use and only takes its place once it is complete.

## When access to new versions ends

**Today's behaviour**, stated as behaviour rather than as a promise about the
future:

- **What is installed keeps working.** Nothing is checked before s0ma starts,
  and nothing switches off.
- **Downloads of new versions stop.** The service refuses the request, s0ma
  writes down what it was told, and `s0ma-launch status` says *this account's
  access to new versions has ended*. A session may begin with one line saying
  the same thing and pointing at account.kn0wthyself.ai.

What a lapsed subscription should cost beyond that has not been decided, and
nothing in s0ma decides it quietly.

## A project that carries its own s0ma

Every project installed by the keyed installer has the toolchain inside its own
environment. Those projects are pinned by construction: s0ma will not move them,
an update does not touch them, and `pin` and `unpin` both refuse with a sentence
saying why. To move one, change the s0ma packages in the project itself, the way
you would change any other dependency.

This is deliberate. Nothing that arrived through Claude reaches into a project
that already answered the question for itself.

## The six things you can ask for by name

The plugin adds six commands. Type the name, or just say what you want.

| Command | What it does |
|---|---|
| `/s0ma:setup` | Gets s0ma working here: checks uv, installs the toolchain, says where the key goes, ends with a health check. The recovery path when anything is wrong. |
| `/s0ma:new` | Starts a new s0ma project with `s0ma new project`, and proves it works. |
| `/s0ma:retrofit` | Brings an existing codebase onto s0ma one module at a time, starting from the Python in it. The long version is [Retrofitting an existing codebase](retrofit-existing-codebase.md). |
| `/s0ma:feedback` | Sends feedback about s0ma to the team. You read the exact report and approve it before anything leaves the machine. |
| `/s0ma:update` | Checks for a newer s0ma, moves to it, or explains pinning. |
| `/s0ma:doctor` | Works out why s0ma is not doing what it should, and says what each finding means. |

Every one of them works through the terminal, so they all still work when the
s0ma server itself could not start.

## Taking it off again

Remove the plugin with `/plugin`, or the extension through Claude Desktop's
Extensions settings; each is Claude's own uninstall and takes the wrapper away,
not the toolchain.

The toolchain, everything s0ma downloaded, and your key if you saved it with
`s0ma-launch activate`, all live in one folder in your home directory —
`~/.s0ma` on macOS and Linux, `%USERPROFILE%\.s0ma` on Windows — which is never
inside a project.
[Removing s0ma](../uninstall.md) is the complete account: what to stop first,
what each thing is, and what deleting it costs you.

---

Installing some other way? The route the public repository's first release
offers — the source route — is stated once in
[Getting started §1](../getting-started.md#1-create-a-real-project), with its
commands in the root `README.md` "Install" section.
If something here did not behave as described,
[Troubleshooting](../troubleshooting.md) translates what s0ma printed into what
to do about it — and telling us is the point of a beta: `/s0ma:feedback`, or
`s0ma feedback` in a terminal, or — with no key and no enrolment at all — a
[bug report](https://github.com/kn0w-thyself/s0ma/issues/new/choose) or a
[discussion](https://github.com/kn0w-thyself/s0ma/discussions) on the
repository.
