# s0ma quick reference

This page is generated. Every line below is read from s0ma itself when the documentation is built, so editing it here would be undone by the next build — the place to make a change is the thing being described.

One page to find your way around s0ma: what the parts of a `.s0ma` file are, what each line of them means, the commands you will use most, and where to ask for more.

|  |  |
| --- | --- |
| **Describes** | s0ma 0.20.0 (preview) |
| **Packages** | `s0ma-core`, `s0ma-dsl`, `s0ma-mcp`, `s0ma-studi0`, which all share that version |
| **Language specification** | [s0ma DSL — Language Specification & Coding Agent Rulebook](../../packages/s0ma-dsl/docs/s0ma-dsl-spec-v0.17.0.md) |
| **Documentation snapshot** | `sha256:d259cef049e9be11` |
| **This page** | edition 2, last revised 2026-10-05 — [what has changed](#what-has-changed) |

A version marked `(preview)` is the latest release together with the changes made since, which are not released yet.

## Contents

1. [s0ma in one minute](#s0ma-in-one-minute)
2. [What a file looks like](#what-a-file-looks-like)
3. [The kinds of declaration](#the-kinds-of-declaration)
4. [How to read the tables](#how-to-read-the-tables)
5. [The words you choose from](#the-words-you-choose-from)
6. [Each declaration, line by line](#each-declaration-line-by-line)
7. [Everyday commands](#everyday-commands)
8. [Basic rules](#basic-rules)
9. [Finding out more](#finding-out-more)
10. [About this page](#about-this-page)

## s0ma in one minute

s0ma is a way of writing software so that the software carries an accurate description of itself.

You write `.s0ma` files. In them, every part of your program first says what it is for, what it needs and what it promises, and then gives its code. s0ma turns those files into ordinary Python, and beside the Python it keeps a record of every part. You, your program, and your coding agent can all ask that record questions, and get answers that come from the program itself instead of from a document somebody hoped to keep up to date.

Three things to know before anything else:

1. **Edit `.s0ma` files, and nothing else.** Everything in the build directory is written by s0ma and rewritten every time you build.
2. **Every line is a question, and every question gets an answer.** When the answer is "nothing", you write `none`. Leaving a required line out is an error.
3. **Check after every change.** `s0ma check` reads your files, changes none of them, and tells you what is wrong and how to put it right.

## What a file looks like

```text
module <name>                     the header: it speaks for the whole file
    layer: <LAYER>
    version: 0.1.0
    intent: "<what this file is responsible for>"
    ...

nerve <name> :: <LAYER>           a declaration: first the description ...
    kind: <KIND>
    intent: "<why this part exists>"
    ...
    ---                           ... then a line of three hyphens ...
    def <name>(...):              ... then the code
        ...
```

- A file opens with one `module` header. After it come as many declarations as you like, in any order.
- Inside a declaration the description comes first and the code comes after, with a line of exactly three hyphens between them.
- Each line of a description starts with exactly four spaces. A line that belongs to the line above it, as in a block, goes further in.
- A note to a reader starts with `#` and sits on a line of its own. Written after an answer, on the same line, it is read as part of the answer and refused.
- The file is named after its module: `module library_domain` lives in `library_domain.s0ma`.

And a project, from the outside:

```text
my-project/
    pyproject.toml                        the project's settings, under [tool.s0ma]
    src/
        library/                          one folder for each feature
            library_domain.s0ma           one file for each layer the feature needs
    tests/
        library/
            library_domain_tests.s0ma
    build/                                written by s0ma: never edit
        library_domain.py                 the Python made from your file
        library_domain.s0ma.json          the record of what your file declared
        docs/                             the pages your doc-ref and doc-guide produce
```

The settings are short, and `s0ma new project` writes them for you:

```toml
[tool.s0ma]
source_roots = ["src"]
test_roots = ["tests"]
build_dir = "build"
mode = "dev"
```

## The kinds of declaration

A file is made of declarations, and there are 11 kinds of them.

| Write a | When you have | In short | Code? |
| --- | --- | --- | --- |
| [`module`](#module) | a new file | The header every s0ma source file opens with, naming the file and declaring everything that enters and leaves it. [More](../learn/module.md) | no |
| [`nerve`](#nerve) | something that acts: it computes, decides, fetches or serves | A piece of working logic that carries its own account of what it does, what it needs, and what it promises. [More](../learn/nerve.md) | yes |
| [`cell`](#cell) | something that holds a shape or a value | A declared piece of structure — a data shape, a fixed value, a setting, a type, or an error kind — rather than a piece of behaviour. [More](../learn/cell.md) | yes |
| [`ganglion`](#ganglion) | something that watches other parts | A declared watcher: it observes named parts of the system and judges what it sees against what it expected. [More](../learn/ganglion.md) | usually |
| [`axon`](#axon) | a dependency between two files that a reader should be told about | A written-down dependency between two parts: which one leans on which, why, and how tightly. [More](../learn/axon.md) | no |
| [`helper`](#helper) | a small private routine only this file calls | A small private function inside one file, described but deliberately not registered as a part of the system. [More](../learn/helper.md) | yes |
| [`integration`](#integration) | a connection to a service you do not control | A declared adapter to an outside system, naming how to build it, how to check it is alive, and what it needs to run. [More](../learn/integration.md) | optional |
| [`test`](#test) | a check that a part keeps its promises | A verification written as a declared part of the system, naming exactly which parts it checks. [More](../learn/test.md) | yes |
| [`doc-ref`](#doc-ref) | a list or table of what the system contains | A reference page assembled entirely from what the system already knows about itself, carrying no prose of its own. [More](../learn/doc-ref.md) | no |
| [`doc-guide`](#doc-guide) | an explanation that names real parts | A written guide whose every factual claim about a named part is checked against the system rather than trusted. [More](../learn/doc-guide.md) | writing |
| [`example`](#example) | a part a reader needs to see in use | A short runnable demonstration, registered against the parts it teaches, that has to keep working. [More](../learn/example.md) | yes |

Not sure which? If it *acts*, it is a nerve. If it *holds* something, it is a cell. If it *watches*, it is a ganglion.

## How to read the tables

Each declaration below has a table with one row for each line you can write, in the order you would write them. s0ma's own messages call these lines *fields*.

**Write it?** says whether the line has to be there.

| Write it? | Means |
| --- | --- |
| Always | The line must be there. |
| When it applies | Write the line only in the situation its row describes. |
| Optional | Leave it out whenever you like. |

**May also be** says what the line may hold in place of a real answer.

| May also be | Means |
| --- | --- |
| `none` | "There is nothing here", said out loud: `raises: none`. |
| `pending` | "Not decided yet", with the reason in quotes: `expects: pending("waiting for the pricing rules")`. Day to day this is a warning. In `strict` and `release` mode it is refused until you answer. |
| — | The line needs a real answer. |

**Holds** says what kind of answer the line takes.

| Holds | Looks like |
| --- | --- |
| text | `"The day the loan starts."` Put it in double quotes. |
| name | `due_date` Letters, digits and underscores, with no spaces. |
| list | `[lend, give_back]` An empty list is `[]`. |
| one of | Exactly one of the words shown, spelled the way it is shown. |
| whole number | `50` |
| version | `0.1.0` Three numbers with dots between them. |
| `true` | Lower case, with no quotes. |
| block | Lines underneath the line itself, further in, as in the samples. |
| file path | `docs/lending_guide.md` Forward slashes, and no quotes. |
| `@file("path")` | `@file("templates/letter.txt")` The path is inside the quotes. |
| code, after the `---` line | Ordinary Python, four spaces in, as in the samples. |
| writing, after the `---` line | Ordinary sentences, four spaces in, as in the samples. |

An import is written `json` for a whole package, `datetime:date` for one name out of a package, and `numpy as np` to give it a shorter name.

Two longer forms are there when a line gets crowded. For long text, write `|` in place of the text and put the text on the lines underneath, further in. For a long list, put one item on each line underneath, each starting with `- `.

## The words you choose from

### Layer

The band a file belongs to. Every part in the file shares it, and a file may only reach files in the bands listed.

| Layer | What belongs there | May reach |
| --- | --- | --- |
| `DOMAIN` | The subject matter itself: what the program is about. | `DOMAIN` `FRAMEWORK` |
| `APPLICATION` | The work that coordinates the subject matter. | `DOMAIN` `APPLICATION` `FRAMEWORK` |
| `PRESENTATION` | The edge where the program meets people. | `DOMAIN` `APPLICATION` `PRESENTATION` `FRAMEWORK` |
| `INFRASTRUCTURE` | The edge where the program meets other systems. | `DOMAIN` `APPLICATION` `INFRASTRUCTURE` `FRAMEWORK` |
| `FRAMEWORK` | s0ma's own machinery. Leave it to s0ma. | `FRAMEWORK` |

### Kind of nerve

What sort of working logic a nerve is.

| Kind of nerve | When it |
| --- | --- |
| `FUNCTION` | works something out and hands back the answer |
| `SERVICE` | keeps running, or offers several operations |
| `ADAPTER` | talks to something outside the program |
| `ORCHESTRATOR` | coordinates other parts |

`FRAMEWORK` is accepted too. It is kept for s0ma's own machinery: leave it to s0ma.

### Kind of cell

What sort of structure a cell is.

| Kind of cell | When it holds | Its code looks like |
| --- | --- | --- |
| `MODEL` | a data shape | `class Book:` with its fields |
| `CONSTANT` | a fixed value | `LOAN_DAYS = 21` |
| `CONFIG` | settings | `class LibrarySettings:` with its defaults |
| `ENUM` | a list of allowed values | `class Shelf(Enum):` |
| `EXCEPTION` | an error type | `class BookUnavailable(Exception):` |
| `TYPE` | a name for a type | `BookId = NewType("BookId", str)` |

`FRAMEWORK` is accepted too. It is kept for s0ma's own machinery: leave it to s0ma.

### Visibility

Who may call a part from another file. It limits calling and nothing else: watchers, tests and documentation can see every part.

| Visibility | Who may call it |
| --- | --- |
| `PUBLIC` | Any file. The part must also be listed in its module's `exports`. |
| `INTERNAL` | Only the file it lives in. |
| `TEST` | The file it lives in, and tests anywhere in the project. |

### Scale

Used by `evaluates_at` on a nerve and `scope` on a ganglion.

| Scale | What is judged |
| --- | --- |
| `FUNCTION_BOUNDARY` | One part at a time: how long it took, whether it kept its promises, whether it failed. |
| `SUBSYSTEM` | Patterns across a group of parts. |
| `SYSTEM` | The system as a whole. |

### Relation

Used by `axon`, and by each entry under `depends_on`.

| Relation | The first part |
| --- | --- |
| `CALLS` | runs the second |
| `CONSTRUCTS` | creates the second, or fills in the interface the second describes |
| `READS` | reads a value or settings from the second |
| `CONFIGURES` | supplies settings to the second |
| `PRODUCES` | creates the second and sends it out |
| `CONSUMES` | receives the second and handles it |

### Coupling

Used by `axon`, and by each entry under `depends_on`.

| Coupling | Means |
| --- | --- |
| `TIGHT` | A change to the second part will probably force a change to the first. |
| `LOOSE` | The second part can change on its own. |

### Category

Used by `category` on a cell.

| Category | Changing the cell changes |
| --- | --- |
| `capability` | what the system can do |
| `behaviour` | how the system behaves, and nothing it can do |

### Format

Used by `format` on a `doc-ref` and a `doc-guide`.

| Format | The page is written as |
| --- | --- |
| `markdown` | Markdown, the plain-text form this page is written in |
| `html` | a web page |
| `json` | data for a program to read |

### Runs in

Used by `runs_in` on an example.

| Runs in | The example is run |
| --- | --- |
| `standalone` | as a small program of its own |
| `pytest` | as a test, by the test runner |
| `integration` | by a runner of your own |

## Each declaration, line by line

Every sample below comes from one small project, a town library, that passes s0ma's strictest check. See [how this page is made](#how-this-page-is-made).

### module

The header every file opens with. First line: `module <name>`, where the name is the file's name without `.s0ma`.

| Line | Write it? | May also be | Holds | What it says |
| --- | --- | --- | --- | --- |
| `layer` | Always | — | one of `DOMAIN` `APPLICATION` `PRESENTATION` `INFRASTRUCTURE` | The band the file belongs to. Every part in the file shares it. |
| `version` | Always | — | version | The file's version, chosen by a person. |
| `intent` | Always | `pending` | text | What this file is responsible for. Written to stand on its own, in the present tense: no plan, milestone, date, person or ruling. |
| `exports` | Always | `none` · `pending` | list of names | The parts other files may use. Each must be marked `visibility: PUBLIC`. `none` or `[]`: the file publishes nothing. |
| `requires` | Always | `none` · `pending` | list of imports | Outside code the file draws on: the ordinary Python imports. `none`: it needs none. |
| `uses` | Always | `none` · `pending` | list of `file.part` names | Parts of other s0ma files this file refers to. `none`: it refers to none. |
| `soft_requires` | Always | `none` · `pending` | list of imports | Outside code that may not be installed. The file still loads without it. |
| `runtime_only_requires` | Always | `none` · `pending` | list of imports | Outside code that must be loaded although no code names it, such as `pytest`. |
| `deferred_requires` | Always | `none` · `pending` | list of imports | Outside code loaded only at the moment a part that names it is called. |
| `exports_helpers` | Always | `none` · `pending` | list of helper names | Helpers deliberately opened to tests in other files. |
| `tags` | Optional | — | list of names | Labels for searching and grouping. |
| `helpers` | Optional | — | block | Helpers short enough to fit on one line each, declared here in place of a `helper` declaration of their own. |

```s0ma
module library_domain
    # What a book is, and the rules for lending one.
    layer: DOMAIN
    version: 0.1.0
    intent: "The library feature: what a book is, and the rules for lending one."
    exports: [Book, LOAN_DAYS, BookUnavailable, due_date, lending_desk]
    requires: [dataclasses:dataclass, datetime:date, datetime:timedelta]
    uses: none
    soft_requires: none
    runtime_only_requires: none
    deferred_requires: none
    exports_helpers: none
    tags: [library, lending]
```

### nerve

A piece of working logic. First line: `nerve <name> :: <LAYER>`, where the layer is the file's layer.

| Line | Write it? | May also be | Holds | What it says |
| --- | --- | --- | --- | --- |
| `kind` | Always | — | one of `FUNCTION` `SERVICE` `ADAPTER` `ORCHESTRATOR` | What sort of working logic this is. |
| `visibility` | Always | — | one of `PUBLIC` `INTERNAL` `TEST` | Who may call it from another file. |
| `intent` | Always | `pending` | text | Why this part exists. Written to stand on its own, in the present tense: no plan, milestone, date, person or ruling. |
| `expects` | Always | `none` · `pending` | text | What must be true before it is called. `none`: it asks nothing of its caller. |
| `guarantees` | Always | `pending` | text | What it promises once it has finished. Written to stand on its own, in the present tense: no plan, milestone, date, person or ruling. |
| `forbids` | Always | `none` · `pending` | text | What it must never do, however it is called. Written to stand on its own, in the present tense: no plan, milestone, date, person or ruling. `none`: it rules nothing out. |
| `evaluates_at` | Always | — | one of `FUNCTION_BOUNDARY` `SUBSYSTEM` `SYSTEM` | The scale at which watchers judge it: one part, a group, or the whole system. |
| `provides` | Always | `none` · `pending` | list of names, or a block | The operations a service offers. Each one must be a `def` in the code. A block can give each operation its own promises. |
| `returns` | Always | `none` · `pending` | list of names | The keys of the dictionary the code hands back. |
| `raises` | Always | `none` · `pending` | list of cell names | The error types it may raise. Each must be an `EXCEPTION` cell this file declares or lists in `uses`. |
| `interface` | Always | `none` · `pending` | list of names | The methods that anything standing in for this nerve must define. Goes with `abstract`. |
| `latency_ms` | Always | `none` · `pending` | whole number | The longest it may acceptably take, in thousandths of a second. |
| `depends_on` | Always | `none` · `pending` | block | The parts it leans on by decision, one to a line: `name: {relation: …, carries: "…", coupling: …}`. Name a part in another file as `file.part`. |
| `internal` | Always | `none` · `pending` | list of names, or a block | Private functions written inside the code, listed so a reader can see them. A block can give each one a reason. |
| `expected_exceptions` | Always | `none` · `pending` | list of Python names | Outside errors the code catches on purpose, such as `json.JSONDecodeError`. |
| `consumes_via_dict` | Always | `none` · `pending` | block | Settings it reads out of a dictionary by key, as pairs: `contract:` names the cell that describes them, and `param:` names what the code receives them as. |
| `declares_attributes` | Always | `none` · `pending` | list of `group:value` pairs | Claims about what it produces, such as `landmark:header`. |
| `covered_by` | Always | `none` · `pending` | list of text | Verification that lives outside s0ma: name the suite that does it. `none`: no outside evidence is claimed. |
| `abstract` | When it applies | — | `true` | Write it only for an interface other nerves fill in. Such a nerve may have no code. |
| `deferred` | When it applies | — | text | Write it only while the code is a placeholder, and say what it is waiting for. |
| `is_page_composer` | When it applies | — | `true` | Write it only on the nerve that assembles a whole page. |
| `version` | Optional | — | version | This part's own version, when you track one. |
| `tags` | Optional | — | list of names | Labels for searching and grouping. |
| `metadata` | Optional | — | block | Facts of your own, as `key: value` lines, that travel with the part. A value is quoted text, a number, `true` or `false`, or a list. s0ma stores them and never reads them. |
| `serves_as` | Optional | — | name | The name it is served under, when that differs from its own. |
| the code | Always, unless `abstract` | — | code, after the `---` line | One `def`. A `SERVICE` or an `ADAPTER` may be a `class` instead. |

You rarely type these from nothing: `s0ma new nerve <name>` writes every line for you, with `none` already in place.

This sample is a service, so it shows nearly every line in use. A plain `FUNCTION` answers most of them with `none`.

```s0ma
nerve lending_desk :: DOMAIN
    kind: SERVICE
    visibility: PUBLIC
    intent: "Lend books and take them back, keeping track of what is out."
    expects: none
    guarantees: "lend returns the due date; give_back says whether the book was out."
    forbids: "Never lend a book that is already out; lend raises BookUnavailable instead."
    evaluates_at: FUNCTION_BOUNDARY
    provides: [lend, give_back]
    returns: [lend, give_back]
    raises: [BookUnavailable]
    interface: none
    latency_ms: 50
    depends_on:
        due_date: {relation: CALLS, carries: "the day the loan starts", coupling: TIGHT}
    internal:
      - _is_out: "Say whether a title is on loan right now."
    expected_exceptions: [KeyError]
    consumes_via_dict: none
    declares_attributes: [desk:lending]
    covered_by: ["tests/test_lending.py: a book that is out cannot be lent again"]
    version: 0.1.0
    tags: [lending]
    serves_as: desk
    metadata:
        owner: "front desk"
        max_loans: 5
    ---
    def lending_desk() -> dict[str, object]:
        """Open a lending desk with every book on the shelf."""
        on_loan: set[str] = set()

        def _is_out(title: str) -> bool:
            return _tidy_title(title) in on_loan

        def lend(title: str, start: date) -> date:
            if _is_out(title):
                raise BookUnavailable(title)
            on_loan.add(_tidy_title(title))
            return due_date(start)

        def give_back(title: str) -> bool:
            try:
                on_loan.remove(_tidy_title(title))
            except KeyError:
                return False
            return True

        return {"lend": lend, "give_back": give_back}
```

### cell

A piece of structure. First line: `cell <Name> :: <LAYER>`.

| Line | Write it? | May also be | Holds | What it says |
| --- | --- | --- | --- | --- |
| `kind` | Always | — | one of `MODEL` `CONSTANT` `CONFIG` `ENUM` `EXCEPTION` `TYPE` | What sort of structure this is. |
| `visibility` | Always | — | one of `PUBLIC` `INTERNAL` `TEST` | Who may use it from another file. |
| `intent` | Always | `pending` | text | Why this part exists. Written to stand on its own, in the present tense: no plan, milestone, date, person or ruling. |
| `schema` | Always | `pending` | text | What data it represents. Written to stand on its own, in the present tense: no plan, milestone, date, person or ruling. |
| `invariants` | Always | `none` · `pending` | text | What must always be true of it. Written to stand on its own, in the present tense: no plan, milestone, date, person or ruling. `none`: no such rule. |
| `covered_by` | Always | `none` · `pending` | list of text | Verification that lives outside s0ma: name the suite that does it. `none`: no outside evidence is claimed. |
| `category` | When it applies | — | one of `capability` `behaviour` | Whether changing it changes what the system can do, or only how it behaves. |
| `deferred` | When it applies | — | text | Write it only while the code is a placeholder, and say what it is waiting for. |
| `dataclass_invariants` | When it applies | `none` · `pending` | list of text | `MODEL` cells only: rules written so a machine can read them, such as `"copies >= 0"`. |
| `placeholders` | When it applies | `none` · `pending` | list of markers | Only with `content`: the markers, shaped `__NAME__`, that the file holds for later filling in. |
| `content` | When it applies | — | `@file("path")` | `CONSTANT` cells only: take the value from a text file. Replaces the `---` line and the code. |
| `version` | Optional | — | version | This part's own version, when you track one. |
| `tags` | Optional | — | list of names | Labels for searching and grouping. |
| `metadata` | Optional | — | block | Facts of your own, as `key: value` lines, that travel with the part. A value is quoted text, a number, `true` or `false`, or a list. s0ma stores them and never reads them. |
| the code | Always, unless `content` | — | code, after the `---` line | A class, a value, or a type. A `CONSTANT` assigns to its own name: `LOAN_DAYS = 21`. |

A data shape:

```s0ma
cell Book :: DOMAIN
    kind: MODEL
    visibility: PUBLIC
    intent: "One book the library owns."
    schema: "title: str, author: str, copies: int"
    invariants: "A book always has a title, and never fewer than zero copies."
    covered_by: none
    dataclass_invariants: ["copies >= 0"]
    version: 0.1.0
    tags: [catalogue]
    metadata:
        owner: "front desk"
        shelf_count: 3
    ---
    @dataclass(frozen=True)
    class Book:
        title: str
        author: str
        copies: int
```

A fixed value:

```s0ma
cell LOAN_DAYS :: DOMAIN
    kind: CONSTANT
    visibility: PUBLIC
    intent: "How many days a loan lasts."
    schema: "A whole number of days."
    invariants: "Always greater than zero."
    covered_by: none
    category: behaviour
    ---
    LOAN_DAYS = 21
```

### ganglion

A watcher. First line: `ganglion <name> :: <LAYER>`.

| Line | Write it? | May also be | Holds | What it says |
| --- | --- | --- | --- | --- |
| `visibility` | Always | — | one of `PUBLIC` `INTERNAL` `TEST` | Who may call it from another file. |
| `intent` | Always | `pending` | text | What this watcher assesses. Written to stand on its own, in the present tense: no plan, milestone, date, person or ruling. |
| `observes` | Always | `pending` | list of nerve names | The parts it watches. |
| `scope` | Always | — | one of `FUNCTION_BOUNDARY` `SUBSYSTEM` `SYSTEM` | The scale it judges at: one part, a group, or the whole system. |
| `priors` | Always | `none` · `pending` | text | What normal is expected to look like. `none`: nothing is assumed in advance. |
| `on_anomaly` | Always | `pending` | text | What to do when what it sees does not match. |
| `forbids` | Always | `none` · `pending` | text | What this watcher must never do while it assesses. Written to stand on its own, in the present tense: no plan, milestone, date, person or ruling. `none`: it rules nothing out. |
| `depends_on` | Always | `none` · `pending` | block | The parts it leans on by decision, one to a line: `name: {relation: …, carries: "…", coupling: …}`. |
| `covered_by` | Always | `none` · `pending` | list of text | Verification that lives outside s0ma: name the suite that does it. `none`: no outside evidence is claimed. |
| `deferred` | When it applies | — | text | Write it only while the code is a placeholder, and say what it is waiting for. |
| `tags` | Optional | — | list of names | Labels for searching and grouping. |
| `metadata` | Optional | — | block | Facts of your own, as `key: value` lines, that travel with the part. A value is quoted text, a number, `true` or `false`, or a list. s0ma stores them and never reads them. |
| the code | When it applies | — | code, after the `---` line | One `def` that receives what was observed and returns a judgement. Write it when the watcher does its own judging. |

```s0ma
ganglion lending_watch :: DOMAIN
    visibility: INTERNAL
    intent: "Notice when lending starts failing more often than it should."
    observes: [lending_desk]
    scope: FUNCTION_BOUNDARY
    priors: "Lending succeeds unless the book is already out."
    on_anomaly: "Report how many loans failed so a person can look."
    forbids: "Never lend or take back a book itself; it reports how many loans failed so a person can look."
    depends_on: none
    covered_by: none
    tags: [health]
    metadata:
        owner: "front desk"
    ---
    def lending_watch(signals: list[dict[str, object]]) -> dict[str, int]:
        failures = [s for s in signals if s.get("error")]
        return {"failure_count": len(failures), "total": len(signals)}
```

### axon

A dependency between two files, written down because it was a decision. First line: `axon <this part> -> <that part>`. The first part lives in this file. The second lives in another file and is listed in this file's `uses`.

| Line | Write it? | May also be | Holds | What it says |
| --- | --- | --- | --- | --- |
| `relation` | Always | — | one of `CALLS` `CONSTRUCTS` `READS` `CONFIGURES` `PRODUCES` `CONSUMES` | What kind of dependence this is. |
| `intent` | Always | `pending` | text | Why the connection exists. Written to stand on its own, in the present tense: no plan, milestone, date, person or ruling. |
| `carries` | Always | — | text | What travels along it. |
| `coupling` | Always | — | one of `TIGHT` `LOOSE` | How closely the two parts are bound. |

An axon has no code, and every line is always written.

Inside one file, write the same thing as a `depends_on` line on the part itself. And do not write an axon for something s0ma works out by reading the code, such as which errors a part raises or which types it mentions. If the check reports `DUPLICATE_AXON`, it already knows about the connection: take the axon out.

```s0ma
axon reminder_day -> LOAN_DAYS
    relation: READS
    intent: "Reminders follow the library's loan length instead of keeping a second copy of it."
    carries: "the number of days a loan lasts"
    coupling: LOOSE
```

### helper

A small private function that never leaves its file. First line: `helper _<name> :: <LAYER>`. The name starts with an underscore by custom. A helper carries no promises of its own, so it has none of a nerve's other lines.

| Line | Write it? | May also be | Holds | What it says |
| --- | --- | --- | --- | --- |
| `intent` | Always | `pending` | text | Why this helper exists. Written to stand on its own, in the present tense: no plan, milestone, date, person or ruling. |
| `tags` | Optional | — | list of names | Labels for searching and grouping. |
| the code | Always | — | code, after the `---` line | One `def` or one `class`. |

```s0ma
helper _tidy_title :: DOMAIN
    intent: "Trim stray spaces from a title so two spellings of one book match."
    tags: [text]
    ---
    def _tidy_title(title: str) -> str:
        return " ".join(title.split())
```

A helper that fits on one line can also be written inside the module header, under `helpers:`.

### integration

A connection to an outside service. First line: `integration <Name> :: INFRASTRUCTURE`. It can only live in an `INFRASTRUCTURE` file, beside the nerve that builds it.

| Line | Write it? | May also be | Holds | What it says |
| --- | --- | --- | --- | --- |
| `version` | Always | — | version | The version of this connection. |
| `intent` | Always | `pending` | text | Why this connection exists. Written to stand on its own, in the present tense: no plan, milestone, date, person or ruling. |
| `factory` | Always | — | name of a `SERVICE` nerve in this file | The part that builds the connection. |
| `smoke_test_primary` | Always | — | name of a nerve in this file, or one listed in `uses` | The part that checks the connection is alive. |
| `manifest` | Always | `pending` | block | What it offers and what it needs, as `key: value` lines. Usual keys: `provides`, `required_env`, `requires_oauth`. You may add your own. |
| `requires` | Always | `none` · `pending` | list of imports | Outside code this connection draws on. |
| `uses` | Always | `none` · `pending` | list of `file.part` names | Parts of other s0ma files it refers to. |
| `raises` | Always | `none` · `pending` | list of cell names | The error types it may raise. |
| `tags` | Optional | — | list of names | Labels for searching and grouping. |
| the code | Optional | — | code, after the `---` line | Rarely needed: s0ma writes the routine wiring itself. |

```s0ma
integration ReminderMail :: INFRASTRUCTURE
    version: 0.1.0
    intent: "Send overdue-book reminders through the outside mail service."
    factory: mail_client
    smoke_test_primary: mail_is_reachable
    manifest:
      provides: [send_reminder]
      required_env: [MAIL_API_KEY]
      requires_oauth: false
    requires: none
    uses: none
    raises: none
    tags: [mail]
```

### test

A check that a part keeps its promises. First line: `test <name> :: <LAYER>`. Tests live in their own files under `tests/`, named to end in `_tests`, with `exports: []` in the header.

| Line | Write it? | May also be | Holds | What it says |
| --- | --- | --- | --- | --- |
| `intent` | Always | `pending` | text | What behaviour this verifies. Written to stand on its own, in the present tense: no plan, milestone, date, person or ruling. |
| `tests` | Always | `pending` | list of part names | The parts it checks. Name a part in another file as `file.part`. |
| `expects` | Always | `none` · `pending` | text | What must hold before it runs. `none`: nothing. |
| `depends_on` | Always | `none` · `pending` | block | The parts it leans on by decision, one to a line: `name: {relation: …, carries: "…", coupling: …}`. |
| `mocks` | Always | `none` · `pending` | list of nerve names | The nerves it replaces with stand-ins. |
| `tags` | Optional | — | list of names | Labels for searching and grouping. |
| the code | Always | — | code, after the `---` line | One `def` whose name starts with `test_`. The function's name decides whether the test runs; the declaration's name does not. |

```s0ma
test test_due_date_is_three_weeks_out :: DOMAIN
    intent: "A loan that starts on the first of January is due back on the twenty-second."
    tests: [library_domain.due_date]
    expects: "LOAN_DAYS is 21."
    depends_on: none
    mocks: none
    tags: [lending]
    ---
    def test_due_date_is_three_weeks_out() -> None:
        assert LOAN_DAYS == 21
        assert due_date(date(2026, 1, 1)) == date(2026, 1, 22)
```

### doc-ref

A reference page built from the parts themselves. First line: `doc-ref <name>`. It has no code and no three-hyphen line.

| Line | Write it? | May also be | Holds | What it says |
| --- | --- | --- | --- | --- |
| `intent` | Always | `pending` | text | Why this reference page exists. Written to stand on its own, in the present tense: no plan, milestone, date, person or ruling. |
| `format` | Always | — | one of `markdown` `html` `json` | The kind of file to write. |
| `output` | Always | — | file path | Where to write it, inside the build directory. |
| `covers` | Always | `pending` | list of selections | Which parts to list: `[nerve where visibility == PUBLIC]`. Or, in place of a list, a table s0ma keeps itself: `{ source: error_codes }`. |
| `sections` | When it applies | `pending` | list of field names | What to print for each part. Write it whenever `covers` selects parts. |
| `tags` | Optional | — | list of names | Labels for searching and grouping. |

```s0ma
doc-ref public_reference
    intent: "A reference page listing every part other files may call, built from the project itself."
    format: markdown
    output: docs/public_reference.md
    covers: [nerve where visibility == PUBLIC]
    sections: [intent, expects, guarantees]
    tags: [reference]
```

### doc-guide

A written guide whose claims are checked. First line: `doc-guide <name>`. After the three hyphens comes ordinary writing, in which a code sample is always an example and never typed in by hand.

| Line | Write it? | May also be | Holds | What it says |
| --- | --- | --- | --- | --- |
| `intent` | Always | `pending` | text | Why this guide exists. Written to stand on its own, in the present tense: no plan, milestone, date, person or ruling. |
| `format` | Always | — | one of `markdown` `html` `json` | The kind of file to write. |
| `output` | Always | — | file path | Where to write it, inside the build directory. |
| `covers` | Always | `pending` | list of part references | The parts the guide is about: `[nerve::due_date]`. |
| `asserts` | Always | `pending` | list of claims | Statements the build checks: `[nerve::due_date.visibility == PUBLIC]`. `[]` when there are none. |
| `examples` | Always | `pending` | list of example references | The examples it shows: `[example::lend_a_book]`. `[]` when there are none. |
| `tags` | Optional | — | list of names | Labels for searching and grouping. |
| the writing | Always | — | writing, after the `---` line | Ordinary writing. Name a part as `{{nerve::due_date}}` and show an example as `{{example::lend_a_book}}`. |

```s0ma
doc-guide lending_guide
    intent: "Explains how lending works, in words a new librarian could follow."
    format: markdown
    output: docs/lending_guide.md
    covers: [nerve::due_date]
    asserts: [nerve::due_date.visibility == PUBLIC]
    examples: [example::lend_a_book]
    tags: [guide]
    ---
    # How lending works

    A loan lasts three weeks. {{nerve::due_date}} works out the day a book is due back.

    {{example::lend_a_book}}
```

### example

A short demonstration that has to keep working. First line: `example <name>`.

| Line | Write it? | May also be | Holds | What it says |
| --- | --- | --- | --- | --- |
| `intent` | Always | `pending` | text | What this example teaches. Written to stand on its own, in the present tense: no plan, milestone, date, person or ruling. |
| `demonstrates` | Always | `pending` | list of part references | The parts it shows in use: `[nerve::due_date]`. At least one. |
| `runs_in` | Always | — | one of `standalone` `pytest` `integration` | How it is run: as a small program, as a test, or by your own runner. |
| `tags` | Optional | — | list of names | Labels for searching and grouping. |
| the code | Always | — | code, after the `---` line | Short Python, written to be read. It may carry its own `import` lines. |

```s0ma
example lend_a_book
    intent: "Shows the due date for a loan that starts on New Year's Day."
    demonstrates: [nerve::due_date]
    runs_in: standalone
    tags: [lending]
    ---
    from datetime import date

    from library_domain import due_date

    print(due_date(date(2026, 1, 1)))
```

To run the examples yourself on macOS or Linux, build first, then: `PYTHONPATH="$PWD/build" s0ma examples run src`. The first part tells Python where the built files are.

## Everyday commands

Run these in a terminal, from inside your project's folder. A first session looks like this:

```bash
s0ma new project library   # make a project that already builds
cd library
s0ma check                 # is everything in order?
s0ma build .               # turn the .s0ma files into Python
s0ma test                  # run the tests
s0ma studi0                # look at what you made
```

**Start**

| Command | What it does |
| --- | --- |
| [`s0ma new project <folder>`](cli.md#s0ma-new) | Makes a new project that already builds: its settings, a starter feature with a test, a map of the project, and a guide for coding agents. Add `--template service` for a fuller start. |
| [`s0ma new nerve <name>`](cli.md#s0ma-new) | Writes a starter file with one nerve in it and every line filled in. Works for `module`, `cell` and `test` too. |

**The everyday loop**

| Command | What it does |
| --- | --- |
| [`s0ma check`](cli.md#s0ma-check) | Reads every `.s0ma` file and reports what is wrong and how to put it right. Builds nothing. |
| [`s0ma build .`](cli.md#s0ma-build) | Turns the `.s0ma` files into Python in the build directory, with the record of each file beside it. |
| [`s0ma test`](cli.md#s0ma-test) | Builds, then runs every test. |
| [`s0ma inspect <module>`](cli.md#s0ma-inspect) | Asks a built file what it contains. `s0ma inspect --all` lists every file. |

**See the whole**

| Command | What it does |
| --- | --- |
| [`s0ma studi0`](cli.md#s0ma-studi0) | Opens studi0, the viewer: your project drawn as a graph in your browser. It changes nothing. |
| [`s0ma graph .`](cli.md#s0ma-graph) | Prints which parts depend on which. |
| [`s0ma score`](cli.md#s0ma-score) | Reports the self-knowledge score: how much of the project s0ma can describe and vouch for. |
| [`s0ma doctor`](cli.md#s0ma-doctor) | Reports which versions are installed, the state of the project, and how to connect a coding agent. |

**Keep it honest**

| Command | What it does |
| --- | --- |
| [`s0ma verify build`](cli.md#s0ma-verify) | Finds generated files that were edited by hand, or that have fallen behind their source. |
| [`s0ma check --mode release`](cli.md#s0ma-check) | Runs the strictest check, the one to pass before you ship. |
| [`s0ma docs check-drift src`](cli.md#s0ma-docs-check-drift) | Rebuilds every reference page and guide and reports any that no longer match. |

**Bring older work across**

| Command | What it does |
| --- | --- |
| [`s0ma adopt scan`](cli.md#s0ma-adopt-scan) | Reads an existing Python project and says what to convert first. Writes nothing. `s0ma adopt status` then names the next command to run. |
| [`s0ma migrate grammar`](cli.md#s0ma-migrate-grammar) | For `.s0ma` files written when lines could be left out: shows the `none` lines it would add. Add `--apply` to write them. |

**Ask, and tell**

| Command | What it does |
| --- | --- |
| [`s0ma docs`](cli.md#s0ma-docs) | Shows the map of everything s0ma can explain. |
| [`s0ma docs show <topic>`](cli.md#s0ma-docs-show) | Explains one topic: `s0ma docs show nerve`. |
| [`s0ma docs search <word>`](cli.md#s0ma-docs-search) | Finds every topic a word could mean. |
| [`s0ma feedback -m "<your words>"`](cli.md#s0ma-feedback) | Sends feedback to the people who make s0ma, after showing you exactly what will be sent. |

**How strict?** Most commands take `--mode`, and a project sets its usual one as `mode` under `[tool.s0ma]` in `pyproject.toml`.

| Mode | Meant for | How it treats what it finds | Refuses | Warns about | Does not check |
| --- | --- | --- | --- | --- | --- |
| `migration` | bringing existing code across | As `dev`, with a little more room. | 73 | 26 | 3 |
| `dev` | day to day | A mistake the build can carry on past is a warning. | 74 | 25 | 3 |
| `strict` | the automated checks before a merge | What the first two warn about is refused. | 94 | 5 | 3 |
| `release` | shipping | As `strict`, and it makes checks the others do not: they are named under the table. | 98 | 4 | 0 |

The numbers count the 102 reports whose weight depends on the mode. 73 of them are refused in every mode, so the modes differ over the rest. 13 more reports are made the same way whatever the mode.

Made only in `release`: [`MISSING_EMBEDDED_EXAMPLE`](diagnostics.md#missing_embedded_example), [`MISSING_PUBLIC_DOC_REF`](diagnostics.md#missing_public_doc_ref), [`MISSING_TEST_COVERAGE`](diagnostics.md#missing_test_coverage).

## Basic rules

1. **Only edit `.s0ma` files.** Never edit anything in the build directory. If a generated file is changed by hand, `s0ma verify` reports it and `s0ma build` refuses to go on until the change is moved into the `.s0ma` file it belongs to. Reported as [`GENERATED_FILE_DRIFT`](diagnostics.md#generated_file_drift).
2. **Every file opens with a `module` header,** and the file's name matches the module's name. Names have no dots in them: join a feature and its layer with an underscore, as in `library_domain`. Reported as [`MODULE_NAME_STEM_MISMATCH`](diagnostics.md#module_name_stem_mismatch).
3. **Every part says why it exists.** `intent` is on every declaration, and it gives the reason, not a description of the code.
4. **Answer every line marked Always.** Write `none` when there is nothing to say and `pending("reason")` when you have not decided. Do not leave the line out. Reported as [`SEMANTIC_REQUIRED_STATE_OMITTED`](diagnostics.md#semantic_required_state_omitted), [`SEMANTIC_PENDING_DEBT`](diagnostics.md#semantic_pending_debt).
5. **Spell and indent each line exactly.** A line s0ma cannot read is reported, never passed over: a name it does not know, or a line that starts in the wrong place. Day to day these are warnings. In `strict` and `release` mode they are refused. Reported as [`UNKNOWN_FIELD`](diagnostics.md#unknown_field), [`UNRECOGNIZED_LINE`](diagnostics.md#unrecognized_line).
6. **No code outside a declaration.** A nerve's code is one `def`. A `SERVICE` or an `ADAPTER` may be a `class` instead.
7. **No `import` lines in the code.** Outside code goes in the header's `requires`. Parts of other s0ma files go in `uses`. An example is the one exception. Reported as [`BARE_IMPORT`](diagnostics.md#bare_import).
8. **One layer to a file,** and a file only reaches the layers its own layer allows. Reported as [`LAYER_MISMATCH`](diagnostics.md#layer_mismatch), [`CROSS_LAYER_DEPENDENCY`](diagnostics.md#cross_layer_dependency).
9. **`exports` and `visibility` agree.** A part listed in `exports` is `PUBLIC`. A part that is not listed is `INTERNAL` or `TEST`. Reported as [`VISIBILITY_MISMATCH`](diagnostics.md#visibility_mismatch).
10. **Do not write a connection s0ma works out for itself.** It already links a part to the errors in its `raises` line and to the types its code mentions, so those need no `axon` and no `depends_on` line. Reported as [`DUPLICATE_AXON`](diagnostics.md#duplicate_axon).
11. **Name test functions `test_...`.** The function's name decides whether the test runs. One the test runner would never run is reported, because it would still count as a check on the parts it names. Reported as [`TEST_NOT_COLLECTED`](diagnostics.md#test_not_collected).
12. **When you change the code, change its description in the same edit,** and check again.
13. **Never use** `exec`, `eval`, `__import__`, or code that swaps another part's behaviour while the program runs. Reported as [`PROHIBITED_CONSTRUCT`](diagnostics.md#prohibited_construct).

## Finding out more

**Ask s0ma itself.** In a terminal, `s0ma docs` shows the map, `s0ma docs show <topic>` explains one topic, and `s0ma docs search <word>` finds the topics a word could mean. A topic can be an idea (`nerve`), a command, a setting, or the code name of a report such as `VISIBILITY_MISMATCH`.

**Ask your coding agent.** Once the agent is connected to s0ma's authoring server, `s0ma-mcp`, ask it in your own words: "what is a ganglion?", "why did the check fail?", "what does this project contain?". To connect one, register the command `s0ma-mcp` with your agent as an MCP server; `s0ma doctor` prints the line that does it for Claude Code. The server gives the agent:

| The agent can | By using |
| --- | --- |
| look up one idea, command, setting or report | the `learn_s0ma` tool, and the list of what can be asked at `s0ma://docs/index` |
| find out where it is and what to do next | the `project_status` tool |
| ask a built file what it contains | the `inspect_module` tool |
| find out which tool fits a situation | the `describe_server` tool |
| read the short rules, to keep in mind throughout | `s0ma://guide/survival-card` |
| read this page, one topic at a time | `s0ma://guide/quick-reference` |
| read the same facts as data, when it is a program doing the reading | `s0ma://guide/quick-reference.json` |
| look up any report by its code name | `s0ma://guide/errors` |
| read worked patterns for real applications | `s0ma://guide/patterns` |
| read the language specification | `s0ma://spec/current` |
| be walked through a whole task | the prompts `author_module`, `fix_check_failures`, `diagnose_fault`, `migrate_project` and `feedback` |

**If you are a coding agent reading this:** call `project_status` first and follow the `next_actions` in each answer. Pass an explicit `project_root` on every call. Check after every edit. Use the server's tools in place of the `s0ma` command, which is often not installed where you are running.

**Read the documents.** In a copy of the s0ma repository:

| For | Read |
| --- | --- |
| every document there is, and who it is for | [The s0ma documentation: the map of record](../README.md) |
| each idea explained on a page of its own, starting here | [Glossary](../learn/glossary.md) |
| the parts of a file, each with its smallest written form | [Anatomy of a .s0ma file](../learn/anatomy-of-a-s0ma-file.md) |
| writing your first file, step by step | [Your first module: the anatomy of a .s0ma file](../guides/first-module.md) |
| working through a coding agent, step by step | [Authoring through the agent's own tool channel](../guides/mcp-authoring.md) |
| every command and every option | [The s0ma command line](cli.md) |
| every setting a project can declare | [Project settings](configuration.md) |
| every report s0ma can make, and what to do about it | [Reports s0ma can make](diagnostics.md) |
| the language itself, in full | [s0ma DSL — Language Specification & Coding Agent Rulebook](../../packages/s0ma-dsl/docs/s0ma-dsl-spec-v0.17.0.md) |

## About this page

### How this page is made

- **The lines, and whether each must be written,** are read from the table inside s0ma that the check itself enforces. A line is on this page exactly when the check accepts it.
- **The words you choose from** are read from s0ma too, so a word it stops accepting leaves this page and a new one arrives on it.
- **Every sample** is cut from one small project of 7 files. The page is only written when every one of them passes s0ma's strictest check, and s0ma's own tests then build the project, run its 5 tests and run its example.
- **Every command** is checked against the command line s0ma really serves, down to each option, and every report named on this page is one s0ma can really make.
- **The explanations** are written by a person, in `docs/s0ma_src/quick-reference.json`. That file is the place to change them.

In 3 places the check accepts less than s0ma's own table says it should. This page shows what the check accepts:

- `cell`, `category`: may not be `pending`. The check reads the line as one of its two words and nothing else.
- `integration`, `factory`: may not be `pending`. The check needs the name of the nerve that builds the connection.
- `integration`, `smoke_test_primary`: may not be `pending`. The check needs the name of the nerve that tries the connection.

Everything on this page is also written as data, for a program or a coding agent to read: `docs/_generated/quick-reference-machine.json`.

### What has changed

| Edition | Date | Written for | What changed |
| --- | --- | --- | --- |
| 2 | 2026-10-05 | s0ma 0.19.0 | A working part and a watcher now carry a `forbids` line: what it must never do. It must always be written, and `none` says there is nothing to rule out. |
| 1 | 2026-09-29 | s0ma 0.19.0 | First edition. |
