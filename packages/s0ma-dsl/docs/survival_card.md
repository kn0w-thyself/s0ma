# s0ma survival card

The 60-second version of everything you need to author s0ma modules.
(Every declaration line by line: s0ma://guide/quick-reference — look topics
up there, do not hold it in context; error catalog: s0ma://guide/errors;
worked patterns: s0ma://guide/patterns — §31 for embodying physical hardware.)

## The loop

1. `project_status` — is this a s0ma project? If not: `init_project`
   (writes the `[tool.s0ma]` table into pyproject.toml).
2. `scaffold_module` — creates a known-valid starter module.
3. Edit the `.s0ma` file.
4. `check` after every edit — apply each diagnostic's remediation.
5. `build_project` when check is green.

## The four rules that prevent most errors

1. Only edit `.s0ma` files. Never edit generated `.py` files.
2. A nerve body is exactly ONE `def`. Nothing else at the top level of
   the body — no imports, no constants, no second def.
3. Imports never go in bodies. Declare them in the module header —
   `requires: [json, pathlib.Path]` — and the transpiler emits the
   import lines. References to other s0ma components go in `uses:`.
4. New code starts from intent in a canonical `.s0ma` component. Use
   `author_module` / `scaffold_module`; `adopt_file` is interim migration
   intake for pre-existing plain Python, not code you just wrote.

## Need several functions?

A body is one `def`, so don't cram many functions into a module and
subscript it from another: `registry["op"]` on a bare `uses: [registry]`
module object is `MODULE_SUBSCRIPT` (a runtime `TypeError`). Instead — a
`kind: SERVICE` nerve is ONE factory `def` that returns a dict of named
operations (callers subscript the *returned dict*, not the module), or
declare each operation as its own exported nerve and import it with
`uses: [module.op]`. Full idiom: s0ma://guide/patterns.

## Minimal valid module

    module greeter
        layer: DOMAIN
        version: 0.1.0
        intent: "Builds greeting documents for people."
        exports: [greet]
        requires: [json]
        uses: none
        soft_requires: none
        runtime_only_requires: none
        deferred_requires: none
        exports_helpers: none

    nerve greet :: DOMAIN
        kind: FUNCTION
        visibility: PUBLIC
        intent: "Return a JSON greeting for a name."
        expects: "name is a non-empty string"
        guarantees: "returns a non-empty JSON string"
        forbids: none
        evaluates_at: FUNCTION_BOUNDARY
        provides: none
        returns: none
        raises: none
        interface: none
        latency_ms: none
        depends_on: none
        internal: none
        expected_exceptions: none
        consumes_via_dict: none
        declares_attributes: none
        covered_by: none
        ---
        def greet(name):
            return json.dumps({"hello": name})

Every line above must be written; `none` says "nothing here".
Leaving one out is SEMANTIC_REQUIRED_STATE_OMITTED.

## If check fails

- PARSE_ERROR "body must be a function definition": the body has more
  than one top-level statement — move imports to `requires:`, keep
  exactly one `def`.
- BARE_IMPORT: delete the import line from the body AND declare the
  name in `requires:` (one edit, two parts).
- MISSING_PACKAGE: `requires:` entries must be importable Python module
  paths (`yaml`, not `PyYAML`; never your project's plain `.py` files).
- UNKNOWN_FIELD / UNRECOGNIZED_LINE: a line s0ma cannot read — a name the
  kind does not have, or a field not exactly four spaces in. Fix the
  spelling or the indent; s0ma://guide/quick-reference lists every line.
- TEST_NOT_COLLECTED: name a test's function `test_...`, or the runner
  never runs it.
- Anything else: look the code up in s0ma://guide/errors.
