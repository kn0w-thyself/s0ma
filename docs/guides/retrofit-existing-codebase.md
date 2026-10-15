# Retrofitting an existing codebase

You have an application that works, and there is Python in it — all of it, or
the part the rest is reached from. You want it to be a s0ma application — one
that carries an accurate, queryable account of itself — without stopping the
work and without losing behaviour on the way.

s0ma compiles Python, so the ladder below walks the Python in your codebase.
What is not Python is not left outside: a service written in another language,
a binary you call, a file the application carries, are declared from the Python
side as references — an `integration` naming the outside system, an `ADAPTER`
nerve wrapping the call to it, a `CONSTANT` cell carrying the file — and so
enter the model and the dependency graph without being compiled. Support for
more languages is on the development roadmap.

This page is the path. The adoption ladder is five rungs, taken in order and
designed to be walked over weeks. A project sits halfway up it for a long time,
and that is a normal, measurable state rather than a mess. Nothing asks you to
convert everything at once, and nothing asks you to trust that a conversion was
faithful — each rung ends with a number or a refusal that says whether it was.
It is written for two readers at once: the person deciding what to convert and
in what order, and the agent doing the mechanical work.

**About the output below.** Where a real run prints the full path to your
project, this page writes `{project}`, and unrelated lines are left out — so the
blocks are shorter than what you will see, never different. A block showing the
*shape* of a file rather than a recorded run says so.

## The card

Five rungs, eight commands, three rules. Enough to start.

- **0 Assess** — read the codebase, get a conversion order. Writes nothing.
- **1 Perimeter** — make the tree a s0ma project. Your code is untouched.
- **2 Register in place** — optional, for big trees.
- **3 Convert** — one module at a time, leaves first. Repeat.
- **4 Ratchet** — `migration` → `dev` → `strict` → `release`.

```console
s0ma adopt scan               # rung 0: what is here, and what to convert
s0ma adopt init               # rung 1: the perimeter, in pyproject.toml
s0ma adopt status             # any time: the rung and the next command

s0ma adopt baseline <module>  # rung 3, in order: what it promises now
s0ma adopt draft <module>     #   that .py file becomes a .s0ma draft
s0ma check                    #   every line still to write
s0ma build                    #   emit the converted module
s0ma adopt verify-parity <m>  #   built vs. baseline, then what is left
```

Rung 3 is the loop: baseline, draft, author every `FIXME(adopt):` line, check,
build, verify parity, run your tests, then delete the old `.py` — but only
after **aliasing** it: binding its old name to the built module in the
package's `__init__.py`, which `verify-parity` prints.

**Rule 1 — baseline before you delete anything.** It is taken from the `.py`;
delete it first and there is nothing to compare against.

**Rule 2 — never edit the build directory** (`<project>_build`, or
`[tool.s0ma].build_dir` if you set one). Every build rewrites it; edits there
are found and refused.

**Rule 3 — placeholders are errors on purpose.** A draft's `FIXME(adopt):`
lines fail `s0ma check` in every mode, so a half-finished conversion cannot
build green.

**Declare the runtime:** built code imports `s0ma-core` and `s0ma-dsl`: name
both in `[project].dependencies`, and install them where it runs.

**When stuck:** `s0ma adopt status` has the next command at every rung, and
every command answers `--help`.

## Rung 0 — Assess

**What you do.** Read the codebase without changing it, and decide two things:
which module to convert first, and which [layer](../learn/layer.md) each module
will declare.

```console
s0ma adopt scan
```

**What you should see.** One screen, in five parts: what was found (modules,
lines, public entities, how many are already registered); the perimeter it
proposes; the first ten modules of a leaf-first conversion order, each with a
size band and a proposed layer; any import cycles and warnings; and the next
command to run. `--format json` prints the same facts for an agent to read, and
`--detail <module>` prints one module's census in full.

**What it means.** The order is the plan. It is leaf-first — modules that
import nothing else in the project come first — because converting a leaf never
asks you to point at a module that has not been converted yet. Files the
perimeter declares as deliberate plain-Python exceptions are not in that list,
and the screen says which ones and why: nobody converts the entry point that
starts the program.

The proposals are evidence, not instructions, and each carries its reasons in
plain words. From the lending service this page uses as its example:

```text
bookshelf.models        DOMAIN           high
    its name contains `models`, and things called that are usually a DOMAIN concern.
    it defines things of its own and imports nothing from the rest of the project
    and nothing that reaches outside the program.
```

A module with no layer and `low` confidence means the scan found nothing to go
on and the choice is yours.

**What the scan reads, and what it leaves alone.** A repository is rarely all
one project. Benchmark harnesses, linters and test generators keep directories
of sample applications, reference solutions and fixture trees beside their own
code — Python that is *input*, not source. The scan reads your code and counts
the rest, saying so in one line: `840 other Python files are outside them and
not in this scan: fixtures/ 632, samples/ 208.`

It works out which directories are yours from evidence you already wrote: the
packages your `pyproject.toml` declares, the entry points it names, and which
of your top-level packages import each other. When that evidence is thin it
says nothing and reads the whole directory, which is the safe answer rather
than the clever one. Either way you have the last word:

```console
s0ma adopt scan --source-root harness --source-root evaluators
```

Name each directory that holds your code, as many times as you need. What you
name is what is read, what is proposed as the perimeter, and what every later
command counts — so a tree of four packages side by side is as ordinary as one
package under `src/`.

**What can go wrong.**

- *The scan reports a cycle.* Two modules that import each other cannot both be
  converted first. Break it before rung 3, or confirm that one side's import is
  inside a function — a deferred import is declared separately and need not be
  broken, but it does have to stay deferred.
- *A module fails to parse.* The scan records it and carries on; it is almost
  always a file that is not Python for this interpreter.
- *The proposed layers contradict each other.* Read the next section first. This
  is the most expensive thing on the page to get wrong.
- *The scan reads a directory that is not your code, or leaves out one that is.*
  Say so with `--source-root`, once per directory. Nothing is guessed twice: the
  roots you name are the roots the next command writes.

## Choosing layers, before anything else

Every s0ma file declares exactly one `layer`, and a fixed table says which layer
may reach which. That table is narrower than the runtime's own tolerance, so a
layering that looks fine while your code is still plain Python can turn out to
be unbuildable once it is converted. Choose against the table from day one and
the question never comes up twice. In one line each: `DOMAIN` reaches only
itself and the framework; `APPLICATION` reaches `DOMAIN` and itself;
`PRESENTATION` and `INFRASTRUCTURE` each reach `DOMAIN`, `APPLICATION` and
themselves, and never each other; `FRAMEWORK` is s0ma's own and not yours to
declare. The [layer page](../learn/layer.md) is the fuller account.

The scan checks its own proposals against that table and says so when they
collide. In the example service, they do:

```text
bookshelf.api already imports bookshelf.storage when it loads, but the layer
rules do not let a PRESENTATION module reach an INFRASTRUCTURE one — if both
of these proposed layers are right, that import has to change before the
converted project will build.
```

That is a design decision arriving early and cheaply, which is the point. Three
honest answers: move the shared thing down into a layer both can reach; have
the lower layer publish an interface the higher one fills in; or decide one of
the two layers was wrong. What you must not do is discover it module by module,
six weeks in.

## Rung 1 — The perimeter

**What you do.** Make the tree a s0ma project. No application file is touched.

```console
s0ma adopt init
```

**What you should see.** A `[tool.s0ma]` table appended to your existing
`pyproject.toml` — appended, so your original bytes stay exactly as they
were — carrying `mode = "migration"`, `source_roots`, `bootstrap_files` and
`package_markers`. Then the commands to run next.

Those four settings are the whole perimeter. `[tool.s0ma].source_roots` says
where your code lives — one directory, or one entry for each package that sits
side by side at the top of your tree. `[tool.s0ma].bootstrap_files` and
`[tool.s0ma].package_markers` declare the plain-Python files that are meant to
stay plain — the entry point that starts the program, and the `__init__.py`
files that only re-export. `[tool.s0ma].mode` starts at the most forgiving
strictness mode there is.

Two settings arrive only when the tree needs them. When your tests live in a
directory outside the source roots, `test_roots` names it, so those files are
not counted as code waiting to be converted. When the code *is* the project
directory — a flat tree with no `src/` — you get `test_roots = []` instead,
with a comment saying why: s0ma refuses a test root sitting inside a source
root, so until the code moves into a directory of its own the test files here
keep counting as unconverted.

The perimeter it writes is the perimeter it decided: what `s0ma adopt scan`
printed, or exactly the directories you named with `--source-root` (repeat the
flag, one per directory). `--dry-run` prints those same bytes, writes nothing,
and runs every check the real run runs — including loading the project — so a
dry run that says yes is a promise.

**Several packages, no `src/`.** A repository whose packages sit side by side at
the top — `harness/`, `evaluators/`, `telemetry/` — names each of them:
`s0ma adopt init --source-root harness --source-root evaluators --source-root
telemetry`. Two things follow from that shape and neither needs thinking about
twice: a module keeps its package in its name (`telemetry.mining`, not
`mining`), and the alias in rung 3's last step climbs one directory fewer,
because the package sits one directory nearer the top. The command prints the
lines for your layout, so there is no number to work out.

**Declare the s0ma runtime now, before the first conversion.** A converted
module imports `s0ma-core` and `s0ma-dsl` when it loads, so a project that
converts anything and has not declared them ships an application that cannot
import itself. Add both to `[project].dependencies` and install them in the
environment that runs the application. The build says so once, as
`HOST_RUNTIME_UNDECLARED`; declaring them is what clears it, and
`s0ma verify-host` is how you prove the environment really has them.

`s0ma doctor` is the other half of that question: it reports what this machine
has installed and what this project is set to, and while a retrofit is in
progress it defers to the ladder — "mid-retrofit — `s0ma adopt status` has the
next command" — rather than offering the advice it gives a new project.

**What it means.** Ask the project what it now thinks of itself:

```console
s0ma verify --all src
```

```text
  PACKAGE_MARKER {project}/src/bookshelf/__init__.py
           (declared under [tool.s0ma].package_markers (Python package marker))
  BOOTSTRAP {project}/src/bookshelf/__main__.py
           (declared under [tool.s0ma].bootstrap_files (intentional plain-Python entry point))
  UNKNOWN  {project}/src/bookshelf/errors.py
  UNKNOWN  {project}/src/bookshelf/lending.py
  …

UNKNOWN (9 files): s0ma has no model of these files yet. That is the backlog,
  not a fault. Convert one by writing a .s0ma source for it and running
  `s0ma build`; or, if a file is meant to stay plain Python, name it under
  [tool.s0ma].bootstrap_files in pyproject.toml.

Verified 0 module(s). 1 bootstrap file(s) recognized. 1 package marker(s). 9 unknown.
Coverage: 0 modeled s0ma module(s), 0 roster-adopted file(s), 9 unknown plain-Python file(s).
HOLLOW_MODEL: 0 adopted, 0 modeled — the self-model cannot answer questions about this code.
```

One line per file, and the sentence that explains them once, underneath.

Nine `UNKNOWN` files is not a failure. It is the honest backlog: every file that
is neither converted nor declared as deliberately exempt. It is the number that
has to fall, and watching it fall is how you know the work is real. `s0ma score`
turns the same facts into one number and a breakdown; at the perimeter it reads
`0.0%` for structure, which is correct, and it lists the exempt set by name, so
what sits outside s0ma is a reading rather than a matter of trust.

**What can go wrong.**

- *It refuses because the project is already a s0ma project.* Then you are past
  rung 1; run `s0ma adopt status`.
- *A file is `UNKNOWN` and you have decided it stays plain Python for now.*
  Record the decision rather than leaving it in the backlog:
  `s0ma adopt file <path> --description "..."` writes the path, your one-line
  reason and the file's content hash into a committed record, and `s0ma verify`
  then reports it as `ADOPTED` instead of `UNKNOWN`. It is visible debt, not
  credit — the self-model still cannot answer a question about that file.
- *You run `s0ma score` by naming the project from outside it.* It warns that it
  is operating without project discovery and reports the default mode rather
  than yours. Run it from inside the project, or pass `--project-root`.
- *It refuses because the perimeter will not load.* Source roots may not sit
  inside one another — `.` beside `src` is the pair that trips it — because
  every file under the inner one would be discovered twice. Name roots that do
  not overlap. Nothing is written when it refuses, in a dry run or a real one.
- *`s0ma verify` takes one target at a time.* With several source roots, run it
  once per root and add the numbers up; `s0ma score` and `s0ma adopt status`
  count the whole perimeter in one go.

## Rung 2 — Register in place (optional)

A way-station, not a destination, and worth taking only on a large codebase —
roughly, one where rung 3 will take more than a few weeks. It has no command of
its own yet; the loop below is the supported way to do it, written out here
because there is nowhere else to read it.

The idea: decorate the Python you already have, in place, so the self-model
comes alive months before the conversion finishes. You get a queryable model and
the structural checks immediately — and, the part that pays for the work, you
author each part's `name`, `kind`, `layer` and `intent` once, in Python, and the
draft step at rung 3 lifts them into the `.s0ma` file unchanged.

Install the import hook in its lenient form, load the application, and read back
what it saw:

```python
from s0ma import initialize

registry = initialize(project_root="src", persist=False, strict=False)

import bookshelf.api          # or run the project's own test suite here

for anomaly in registry.import_hook_anomalies:
    print(anomaly.name, "—", anomaly.description)
```

`strict=False` is doing the work: the hook warns rather than raising, so the
application still runs while you are partway through. Each record names one
public class or function that is neither registered nor marked internal — the
example service produces thirty-three, the first of them
`bookshelf.config — Unregistered public function 'loan_length_days' in module
'bookshelf.config'.` Burn the list down by decorating each one:

```python
from s0ma.decorators import component, internal
from s0ma.types import ComponentKind, Layer

@component(
    name="Bookshelf_LoanRegister",
    kind=ComponentKind.SERVICE,
    layer=Layer.DOMAIN,
    intent="Hold every open loan and decide whether another one may be made.",
)
class LoanRegister:
    ...
```

Or `@internal(reason="...")` for something that genuinely is not part of the
system's account of itself. The rung is finished when the anomaly count reaches
zero under the application's own import closure.

Two warnings. **Names are global** — the registry namespace is shared with
s0ma's own framework parts, so prefix yours with the project's name. And **use
the layer table from the previous section, not the runtime's**: the runtime is
more tolerant than the build, and a layering chosen against the looser rule will
have to be redone at rung 3.

Skipping this rung loses nothing — rung 3 works the same way from undecorated
Python. You simply author the meaning later, in the `.s0ma` file, instead of
earlier, in Python.

## Rung 3 — Convert one module, end to end

This is the rung you repeat. Everything below happens to one module, and the
next module starts from a clean tree. The example is `bookshelf.errors`, near
the top of the scan's order for the lending service: ten exception classes, no
first-party imports, nothing deferred, and a public surface every other module
in the project leans on. A leaf worth having early.

**1. Baseline.** Record what the module offers, while the `.py` file is still
there to read:

```console
s0ma adopt baseline bookshelf.errors

Captured 1 baseline:
  bookshelf.errors   src/bookshelf/errors.py

Recorded in adopt-baseline.s0ma.json. Commit it with your code: it is what the
  conversion will be judged against, and it cannot be taken again once the Python file
  is gone.

Run this next:
  s0ma adopt draft bookshelf.errors   turn it into a .s0ma draft
```

That one file at the project root holds, for each public name, its normalised
signature, the type it declares, its base classes, its decorators and its
cleaned-up docstring — enough to prove later that nothing was quietly dropped,
and normalised enough that reformatting the code is not counted as a change.
Name several modules at once, or pass `--all` to record every module the
project reads as application code; recording one that has not changed writes
the same bytes, so a second run diffs empty.

Commit it. This is the one file in the whole ladder that cannot be recovered:
the moment the `.py` is deleted, nothing else says what it promised. That is
also why `adopt baseline` refuses a module whose Python has already gone, in
its own words, rather than as a typo.

**2. Draft.** Turn the Python into a `.s0ma file`:

```console
s0ma adopt draft bookshelf.errors
```

Name the module the way the scan printed it, or pass the path
(`src/bookshelf/errors.py`) — they reach the same file. What you get back:

```console
Wrote src/bookshelf/errors.s0ma

It carries 21 placeholders — that many fields whose meaning only a person can write,
  each marked FIXME(adopt): and each saying what belongs there. `s0ma check` refuses the
  draft until that work is done, in every mode — which is what stops a half-finished
  conversion from building green.
src/bookshelf/errors.py has not been touched. It is still the code that runs, and it
  stays that way until you have checked the draft, built it and compared it — then you
  delete it.

Run this next:
  s0ma check   read back every line still to write
```

The closing message names the baseline as well when you have not taken one
yet — **baseline before you delete anything**, said at the moment it still
costs nothing.

The draft is mechanical and honest about it. Structure is derived: bodies are
carried over verbatim, each top-level function becomes a nerve or — if its name
starts with an underscore — a helper, each class and each upper-case constant
becomes a cell, imports are sorted into `requires:` and `uses:`, and `__all__`
and underscore prefixes decide visibility. Meaning is not derived: every field
that says what something is *for* arrives as a `FIXME(adopt):` line. Nothing
guesses an [intent](../learn/intent.md).

For `bookshelf.errors` that is ten cells, each with `kind: EXCEPTION`, and a
header exporting all ten names. One of them, exactly as it is written:

```s0ma
cell BookNotFoundError :: DOMAIN
    kind: EXCEPTION
    visibility: PUBLIC
    intent: "FIXME(adopt): say in one sentence why this exists and who reads it."
    schema: "FIXME(adopt): say what this holds and what shape it has, in plain words."
    invariants: none
    covered_by: none
    ---
    class BookNotFoundError(CatalogError):
        """No title in the catalogue carries the requested ISBN."""

        def __init__(self, isbn: str) -> None:
            super().__init__(f"no title with ISBN {isbn} is in the catalogue")
            self.isbn = isbn
```

**The layer.** A module sits at exactly one [layer](../learn/layer.md), and the
draft will not invent one. Pass `--layer DOMAIN` when you have decided;
otherwise the scan's proposal is written only when the scan was confident, and
when it was not the draft writes a starting layer and the module's own
placeholder asks you to choose, naming what the scan thought. The placeholder
also says which way the rule points, so the choice is a derivation rather than a
guess: a module may only use modules at its own layer or below, so the layer you
want is the one that lets this module import what it already imports.

**The other three flags.** `--dry-run` prints the draft to the screen and writes
nothing, which is how you look before you leap. `--out DIR` writes it somewhere
else. `--force` replaces a draft that is already there — nothing else does, so a
half-authored draft cannot be lost by re-running the command.

The draft also carries notes about what it could not carry over. Three turn up
in almost every modern Python file:

- **`from __future__ import annotations` is dropped.** s0ma writes the generated
  file's import block itself, and a future import has to be a file's first
  statement. Annotations are therefore evaluated as written — quote any
  annotation that names something defined further down the file.
- **An `if TYPE_CHECKING:` block that reaches your own code becomes an unplaced
  block**, which fails `s0ma check` as `ADOPT_UNPLACED_CODE` until you deal with
  it — step 4 below says what that refusal asks for. Deliberately: moving
  those imports into `requires:` would make them run at import time, which can
  close a cycle the guard was holding open. Decide each one rather than having
  it decided for you. A guard that imports only from the standard library is
  moved into `requires:` for you, with a note saying so: a standard-library
  typing import cannot close a cycle of yours and costs nothing at load time.
- **Module names are flat.** A draft of `bookshelf.errors` declares
  `module errors`, and every module name in a project must be unique. If another
  package already has an `errors`, rename the draft.

**What it refuses.** A test file, a package marker, a file s0ma generated, a
file outside the project, a name nothing matches (it offers the nearest ones), a
name more than one file answers to, and a module that has been converted
already. Each refusal is one sentence saying what to type instead, and nothing
is written when one happens.

**3. Author.** Replace every `FIXME(adopt):` line with a real sentence. This is
the part no tool does, and the part the whole exercise is for — a module's
account of itself is only worth having if a person wrote it. On a `forbids:`
line, `none` — written without quotes — is an answer too, once you have looked
and found nothing the part must never do.

Write each sentence in the present tense, about the part as it is, so the line
stands on its own for a reader who has only this file: never the plan,
milestone, date, person or ruling behind the conversion, which belong to the
changelog and the planning record. It may point only at what ships with the
code and is held by a gate — a requirement, an invariant, an accepted
architecture decision, a contract revision or a section of the specification
by its id or number, a test through `covered_by:`, another part through
`uses:` or `requires:` — and at nothing else.

Another rule about writing them, which the draft also carries as its first note: a
field's value sits in double quotes on one line, and everything between the
quotes is taken exactly as written. There are no escapes, so quote anything
inside the sentence with 'single quotes' rather than a backslash.

**4. Check.** Until the placeholders are gone, `s0ma check` refuses and names
each one. That is rule 3 doing its job: a project must not build green with
un-authored meaning in it, in any mode, however forgiving.

Two refusals belong to drafts and to nothing else, and a conversion usually
meets both. Each names the declaration it is about and says what to do; these
are the same words in the shorter form.

- **`ADOPT_PLACEHOLDER_INTENT`** — a field still carries `FIXME(adopt):`. There
  is one refusal per unwritten *field*, not per declaration, so a cell whose
  `intent:` and `schema:` are both unwritten produces two. **What to do:**
  replace the whole value — marker and all — with one plain sentence of your
  own, and run `s0ma check` again. The placeholder text says what belongs
  there.
- **`ADOPT_UNPLACED_CODE`** — the draft met source text it could not place in
  any declaration and kept it word for word, as a string, in a quarantine cell
  named for the lines it came from (`ADOPT_UNPLACED_0010_0013` is lines 10 to
  13 of the original file). Nothing was lost and none of it runs. **What to
  do:** read the text, then either move it where it belongs — most often the
  module header's `requires:` or `uses:` list, an existing declaration's body,
  or a declaration of its own — or delete it, if it is code nothing needs any
  more. Either way the quarantine cell goes with it.

Both are errors in every mode, `migration` included, which is what stops a
half-finished draft from building or scoring as though somebody had written its
meaning.

**5. Build, and compare.**

```console
s0ma build
s0ma adopt verify-parity bookshelf.errors

bookshelf.errors — same surface (compared with bookshelf_build/errors.py)

1 module compared, and its surface is what it was. Run the project's own tests next:
  parity says the shape survived, and only your tests can say the behaviour did.

Before you delete src/bookshelf/errors.py:
  1. Point bookshelf.errors at the built module: put these lines in
     src/bookshelf/__init__.py, below its docstring and any `from __future__` line,
     above the package's own imports. The build directory is flat, so without them every
     `from .errors import ...` in the package stops resolving the moment the file goes.

      import sys
      from pathlib import Path

      from s0ma.bootstrap import bootstrap_imports

      _BUILT = bootstrap_imports(Path(__file__).resolve().parents[2] / "bookshelf_build")
      errors = _BUILT["errors"]
      sys.modules[f"{__name__}.errors"] = errors

  2. Declare the s0ma runtime: the built module imports s0ma-core and s0ma-dsl when it
     loads, so name both in [project].dependencies and install them in the environment
     that runs this application.
  3. Ship bookshelf_build with the application. It is imported at run time now, so it
     has to stay importable and be listed among the packages your wheel installs.

Then run this project's tests with the Python file still there and check which file the
  module came from; delete it only once the built one is what gets imported.
```

`s0ma build` with no argument builds the project you are standing in — every
source root it declares. Naming a directory (`s0ma build src`) still means
build what is under it.

Those three numbered lines are step 7, printed at the moment you need them and
computed for *this* project: the path of the package's `__init__.py`, how far
the build directory sits above it, the flat name the build gave the module and
the dotted name to bind it back to. `--format json` carries the same facts as
fields, under `before_you_delete`.

Parity reads the `.py` the build wrote — it never imports it — and compares its
public surface with the baseline from step 1. Anything that moved gets a line of
its own: the name it is about, what changed in plain words, and the text before
and after.

```console
s0ma adopt verify-parity bookshelf.errors

bookshelf.errors — 1 difference (compared with bookshelf_build/errors.py)
  BookNotFoundError.__init__  signature changed  (self, isbn: str) -> None → (self, isbn: str, shelf: str='unknown') -> None

1 module compared, 1 with differences, 1 difference in all. Each line above says what
  moved; put it back in the .s0ma source and build again, or accept the change knowing
  what it costs the callers.
```

Eight things count as a difference: a name gone, a name new, a signature, a
declared type, a docstring, a base class, a decorator, a constant's value. Four
things do not, because the build adds them and nobody could have depended on
their absence: the registration decorator above each declaration, the generated
header and its hash lines, the runtime import block and its registration calls,
and the order of `__all__` — a *different set* of exported names is a
difference; a different order is not. Documentation that arrives where there
was none is not a difference either; documentation that changes or disappears
is.

It exits 0 when every module compared has the surface it had and non-zero on
any finding, so it can gate a commit. `--format json` gives an agent the same
verdict as an `s0ma-adopt-parity@1` document, and `--all` compares every module
that has a baseline and has been built, naming the ones that have not.

**6. Run the project's own tests.** The headline check, and no s0ma command
replaces it. Run the suite the way you always have. Green, with the converted
module in place, means the conversion preserved behaviour.

**7. Alias first, test, then delete.** In that order, and the order is the
point: the alias is what keeps the package importable, so it goes in while the
original file is still there to fall back on.

*Alias.* Paste the block `verify-parity` printed into the package's own
`__init__.py` — below its docstring and any `from __future__` line, above
everything it imports of its own. `bootstrap_imports` is
the documented way to load a build — it reads the manifest and imports the
modules in dependency order — and the two bindings cover both ways a caller
reaches the module: `from .errors import …` through `sys.modules`, and
`bookshelf.errors.BookNotFoundError` through the package attribute. Both are
needed: a pre-populated `sys.modules` entry means the import system never sets
the parent attribute. One more line per module as you convert them, and the
block goes away entirely once the package has nothing handwritten left.

*Test.* Run the suite again, with `src/bookshelf/errors.py` still there, and
check which file the module came from — `python -c "import bookshelf.errors as
m; print(m.__file__)"` should print the path inside `bookshelf_build`. Until it
does, the alias is not doing what you think and the suite is still testing the
old file (which is why step 6 is a control and this is the real check).

*Delete.* Now remove `src/bookshelf/errors.py`, and run the suite one last time.

One cosmetic thing to expect on that last run, if a linter sorts your imports:
once the handwritten file is gone, the converted module exists only through
the alias, so an import sorter that decides what is first-party by looking for
a file on disk (ruff's `I001`, isort) reclassifies `from bookshelf.errors
import …` in every test file that has it. One `ruff --fix` reshuffles the
import blocks and nothing else changes; it is not a sign that the alias
failed.

Two things about the build directory, both easy to miss and both fatal to a
release. It is imported at run time now, so it has to be importable wherever the
application runs *and* be in what you ship — the wheel's package list, the
container image, whatever your deployment is. And it belongs in version control
alongside the code that imports it; its `.s0ma.cache/` directory does not.
Commit the baseline record (`adopt-baseline.s0ma.json`) too: it is what the next
conversion is judged against.

Then `s0ma verify --all src` counts one more module — the `.s0ma` source reads
as `CONVERTED`, built at the path it names — `s0ma score` goes up, and
[`s0ma adopt status`](#coming-back--where-am-i) names the next module in the
order.

**What can go wrong.** A parity finding is almost always real. The two that are
not: a decorator s0ma now expresses as a declaration field instead, and a
docstring you improved on purpose. Both deserve a moment's thought before you
accept them — which is why parity reports them rather than guessing.

One thing parity cannot see: a built module's `__name__` is its flat name. If
anything in your project pickles a class from the converted module, or reads
`__module__` to build an error message or a log channel, that string changes
even though the surface did not. The project's own tests are what catch it.

### Big modules: the dual-home technique

A thousand-line module cannot be converted in one commit and still leave the
suite green in between. The technique for that case was invented during s0ma's
own conversion of a large package, and the exact sequence is recorded in the
entry marked `F-M3-6` in
the self-host friction log (internal, not published). In
outline: alias the built module under a temporary name, have the shrinking
handwritten file re-export each converted symbol from that alias, and convert in
groups. Every consumer flips exactly once, at its own group, and every
intermediate commit has the full suite green. The final flip — delete the
handwritten file, alias the built module under the real name — is invisible to
everything that calls it, and it is the same two lines step 7 above spells out.

## Coming back — where am I?

Rung 3 is a loop walked over weeks, and the hard question on a Tuesday morning
is not how to convert a module: it is which one you were in the middle of.
That is the question `s0ma adopt status` answers. It reads the tree, writes
nothing, never runs your code, and works at every rung — including rung 0, on
a tree that is not a s0ma project at all.

```console
s0ma adopt status

bookshelf — rung 3 of 4: converting.
1 of 9 modules converted, 8 still plain Python.
  drafted 0 · placeholders 0 · adopted in place 0 · baselines 1 · parity: 1 same surface
  mode migration (floor 50%) · score not measurable yet (`s0ma score` says why)

In flight: bookshelf.errors — built, unchanged, the .py is still there.

Next — finish what is started before starting another:
  bookshelf.errors is converted and unchanged. Before you delete
    src/bookshelf/errors.py, this prints the lines that point its old name at the built
    module in src/bookshelf/__init__.py, and the two other things the step needs.
  s0ma adopt verify-parity bookshelf.errors

The whole path, rung by rung: s0ma docs show doc:guide/retrofit-existing-codebase
```

**What it means.** The first two lines are the rung and the backlog. The block
under them counts what is half done: drafts still carrying `FIXME(adopt):`
lines, files registered where they stand, baselines taken, and — once anything
has been built — what comparing the build with those baselines says. The four
verdicts are *same surface*, *with differences*, *built without a baseline*
(nothing was recorded, so nothing can be judged) and *recorded but not built*.
They appear only when there is a build, because before that the question has
not been asked of anything.

**The one next step** is chosen by a rule worth knowing: where more than one
module is part way through, the step is for the one **furthest along**. Finish
what is started before starting another — two half-converted modules leave you
unable to run the suite against either. Ties go to the scan's conversion order.
Nothing is remembered between runs: parity is recomputed from the files on disk
every time, so the verdict is about the bytes that are there now.

`--format json` prints the same reading as an `s0ma-adopt-status@1` document
for an agent: the rung, every count, the state of each module with its
placeholder count, whether it has a baseline and what parity says, and the next
step as both a sentence and a command. Two runs on an unchanged tree print the
same bytes.

## Your existing tests keep counting

You do not have to rewrite a test suite to convert an application. Release mode
demands test coverage for every public nerve, and that demand is satisfied
either by a verification written in the language, or by a `covered_by:` field
naming the suite that already covers it:

```s0ma
    covered_by: ["tests/test_lending.py — the loan-limit cases"]
```

The language checks the shape of the claim and never resolves the string, so
honesty is yours to keep — but the claim rides the record and the rendered
reference, which makes it auditable by anyone who cares to look. Name the file,
not the intention.
[Coverage credit for tests that live elsewhere](../documentation-subsystem.md#coverage-credit-for-tests-that-live-elsewhere)
is the fuller account, including what to do when you would rather write the
verifications in the language after all.

## Rung 4 — Ratchet

The [strictness mode](../learn/strictness-mode.md) is one line in
`pyproject.toml`, and moving it is the whole rung:

```toml
[tool.s0ma]
mode = "dev"
```

`migration` is the forgiving reading you started in. `dev` is the everyday one.
`strict` refuses what `dev` warns about. `release` is the reading you have to
pass before telling anyone the project is ready. Move up one step at a time, fix
what the new reading refuses, and stay there until the next step is cheap.
`s0ma score` has a floor for each — 50% at `migration` and `dev`, 75% at
`strict`, 90% at `release` — and `--gate` in CI, once you are above a floor,
refuses to let you fall back below it.

## What "done" means

Three conditions, all measurable, none a matter of opinion:

1. `s0ma check --mode release` is green.
2. `s0ma score` is at the release floor.
3. Nothing is left `UNKNOWN` except the exemptions you declared on purpose — the
   entry point, the package markers, and anything marked internal. `s0ma score`
   prints that set by name, so the audit is a reading rather than a search.

At that point the application is a s0ma application by the only definition that
means anything: its account of itself covers what it is made of, and a check
that refuses keeps the two together.

## Where to go next

- [Your first module](first-module.md) walks the anatomy of a `.s0ma file`
  slowly, in a project with nothing else in it. Worth an hour before your first
  conversion.
- [When s0ma refuses, and how to get back to green](drift-recovery.md) covers
  the two refusals you will meet most, including the one that fires when
  something edits the build directory — the
  [authored-vs-generated boundary](../learn/authored-vs-generated-boundary.md)
  is the idea underneath it.
- The [Python-to-DSL mapping tables](../../packages/s0ma-dsl/docs/migration_guide.md#step-by-step-conversion)
  are the field-by-field reference for what becomes what;
  [the leaf-first strategy](../../packages/s0ma-dsl/docs/migration_guide.md#strategy-leaf-first-gradual-strictness)
  is the order this page uses, stated from the language's side; and
  [the bootstrap pattern](../../packages/s0ma-dsl/docs/migration_guide.md#bootstrap-pattern-replacing-hand-maintained-module_import_order)
  replaces a hand-maintained list of modules at start-up with one call that
  reads the order the build worked out.
- Every idea this page names has a fuller entry in the
  [concepts index](../reference/concepts-index.md).
