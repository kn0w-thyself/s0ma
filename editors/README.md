# Editor support for `.s0ma` files

This directory ships exactly one artifact: **`s0ma.tmLanguage.json`**, a minimal
TextMate grammar that gives `.s0ma` sources real syntax highlighting in VS Code
and anything else TextMate-compatible.

**Scope boundary (PRD §9, non-goal 4).** A minimal TextMate grammar may ship
pre-1.0 as a UX item — that is this file. A *packaged* VS Code extension is a
phase-2 item, and a full editor experience (LSP, completions, diagnostics)
remains post-1.0. Nothing in this directory installs itself; everything below
is manual association.

## What the grammar highlights

- The eleven declaration keywords at column 0: `module`, `nerve`, `cell`,
  `ganglion`, `axon`, `test`, `helper`, `integration`, `doc-ref`, `doc-guide`,
  `example` — including the `:: LAYER` annotation on layered declarations and
  the `->` arrow on standalone axons.
- Metadata field keys at the four-space field column (`intent:`, `kind:`,
  `visibility:`, `expects:`, `guarantees:`, `forbids:`, `evaluates_at:`,
  `exports:`, `uses:`, … — the full set harvested from spec v0.17.0), plus
  nested mapping keys (`depends_on:` targets, `manifest:` sub-keys) and inline
  `{relation: …, carries: …, coupling: …}` maps.
- Double-quoted strings (including the multi-line continuation form),
  `#` comments, enum constants (`APPLICATION`, `PUBLIC`, `CALLS`, `TIGHT`,
  `FUNCTION_BOUNDARY`, …), numbers, block-list `-` items, the `|` block-scalar
  marker, `@file()` directives, and `module::component` references.
- The `---` body fence: everything from the fence to the next column-0
  declaration (or EOF) is scoped as **embedded Python**
  (`meta.embedded.block.python` with `include: source.python`), so bodies get
  full Python highlighting.

## VS Code and Cursor

No extension is shipped, so there are two manual routes. Cursor is a VS Code
fork and takes both routes unchanged.

### Option A (full highlighting): a local extension package

VS Code only loads TextMate grammars contributed by an extension, and current
VS Code and Cursor load only the extensions their own manifest registers, so a
folder copied into the extensions directory is ignored. Build a minimal local
package instead — two small files, zipped — and let the editor's command line
install it, which registers it. Nothing is shipped or published; the package
exists only on your machine. Anywhere outside the repository:

```
s0ma-syntax-local/
└── extension/
    ├── package.json
    └── s0ma.tmLanguage.json      ← copy from this directory
```

`extension/package.json`:

```json
{
  "name": "s0ma-syntax-local",
  "displayName": "s0ma syntax (local)",
  "description": "Local, unpackaged TextMate grammar for .s0ma files (s0ma UX phase 1).",
  "version": "0.0.1",
  "publisher": "local",
  "engines": { "vscode": "^1.75.0" },
  "contributes": {
    "languages": [
      { "id": "s0ma", "extensions": [".s0ma"] }
    ],
    "grammars": [
      {
        "language": "s0ma",
        "scopeName": "source.s0ma",
        "path": "./s0ma.tmLanguage.json",
        "embeddedLanguages": { "meta.embedded.block.python": "python" }
      }
    ]
  }
}
```

A `.vsix` package is a zip archive of that `extension/` folder, so from
`s0ma-syntax-local/`:

```bash
zip -r s0ma-syntax-local.vsix extension
code --install-extension s0ma-syntax-local.vsix
```

For Cursor, run the same command through its `cursor` shell command (installed
from its command palette); if Cursor installed the `code` command for you,
that is the same program. The editor registers the package as
`local.s0ma-syntax-local`, and `code --list-extensions` lists it. Restart the
editor (or run **Developer: Reload Window**); `.s0ma` files now open with the
`s0ma` language id and highlighted bodies. The package carries a copy of the
grammar, so when this directory's grammar changes, rebuild and reinstall.
`code --uninstall-extension local.s0ma-syntax-local` removes it. If some other
association already claims `.s0ma`, pin it explicitly in `settings.json`:

```json
"files.associations": { "*.s0ma": "s0ma" }
```

### Option B (zero setup, degraded): associate with Python

If you don't want even a local extension folder, `settings.json`:

```json
"files.associations": { "*.s0ma": "python" }
```

Python bodies highlight correctly; declaration headers and metadata fields
render as (mostly broken-looking) Python. Useful as a stopgap only.

## Other TextMate-compatible editors

Any editor that consumes `.tmLanguage.json` directly (TextMate 2.x, Sublime
Text via conversion, many web highlighters such as Shiki/Monarch bridges) can
load `s0ma.tmLanguage.json` as-is; the grammar uses only the portable
begin/end/match subset of the format and assumes a `source.python` grammar is
available for the embedded bodies.

## Verification status & known limitations

Verified statically (no live editor in this environment):

- the JSON parses and every regex compiles in the `re`/oniguruma shared
  subset;
- the declaration keyword set is drift-guarded against the language spec by
  `packages/s0ma-dsl/tests/test_editor_grammar.py`;
- the fence begin/end patterns were simulated line-by-line against the valid
  fixtures (multi-declaration files included): every embedded-Python block
  closes exactly at the next declaration header or EOF, and the grammar's
  header rules agree with the parser's own header regexes on every fixture
  line.

The Option A install route was checked by hand against current Cursor on
macOS: the package installs, registers and lists. Not verified: actual
rendering inside VS Code/TextMate (no editor available in the CI environment).
Known, accepted limitations of the minimal grammar:

- `doc-guide` prose bodies are scoped as Python like every other body, so
  `{{nerve::X}}` reference tokens inside them are not specially styled.
- A column-0 `#` comment between a Python body and the next declaration stays
  inside the embedded block (it still renders as a comment — Python's rule).
- A column-0 line *inside* a body that exactly matches a declaration header
  (only possible inside a column-0 triple-quoted string, or in invalid files)
  ends the embedded block early.
- Content referenced via `@file()` lives in its own file and is highlighted by
  that file's own language — by design.

## Keeping it honest

The grammar's ground truth is the spec
(`packages/s0ma-dsl/docs/s0ma-dsl-spec-v0.17.0.md`, lexical/grammar sections —
`test_editor_grammar.py` always harvests the *highest* on-disk spec version, so
this path is the one to rotate when a new spec lands)
and the declaration-header regexes in
`packages/s0ma-dsl/src/s0ma_dsl/parser/s0ma_parser.py`. If a declaration type
is added to the spec, `test_editor_grammar.py` fails until the grammar's three
declaration rules and the body-fence `end` pattern learn the new keyword.
