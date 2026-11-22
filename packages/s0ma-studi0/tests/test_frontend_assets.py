"""Tripwires for the sh0w frontend assets (M4).

There is no Node toolchain in this repository (owner decision D-4), so
there are no JavaScript unit tests. What lives here is deliberately
narrow: file-level assertions that the properties the rest of the system
depends on are still present in the shipped assets.

Pinned here:

* the three assets exist where the server embeds them from
  (``s0ma_src/assets/``);
* the two boot modes are still wired — the fixture global the dev
  harness sets, and the ``/api/state`` poll of live mode (plan §3.6);
* the accessibility floor the acceptance gate names (A10) is still in
  the file — ``aria-label`` on the SVG surface, a
  ``prefers-reduced-motion`` rule, and a reduced-motion variant of the
  materialize beat that keeps every transition perceivable;
* the materialize beat is still the only motion in the stylesheet
  (M5): four keyframes, one per delta treatment, and nothing else;
* the page is self-contained (FR-STUDI0-7): no asset reaches for an
  ``http://`` or ``https://`` URL, so nothing is fetched from a CDN, a
  font host, or anywhere else off this machine;
* the fixture payload is a parseable ``s0ma-graph@2`` document and still
  carries a ``pending`` state wrapper, so the authoring-debt projection
  has something to render;
* the dev harness loads the real ``app.js`` and hands it the fixture,
  byte-identical to the checked-in payload;
* the narration pane (M11) is still wired, still labelled as
  self-report, still visually unlike the graph, and still steers the
  canvas only through the selection path a click already uses;
* the term controls, their card and the dictionary are still wired to
  the terms block /api/graph serves, keep only ids in the page, and
  leave the page as it was when there is no terms block; the harness's
  terms data is what the server builds from the packaged slice;
* a project with nothing built is not a lost connection: once the server
  has said so, the canvas draws the standard bands, empty, with one plain
  sentence and the command, and the first build's parts arrive with the
  added-part beat;
* a part is changed only when something it declares differs (never its
  location alone), the parts the newest build added stay outlined until
  the next build that changes something, and the list of changes keeps
  each build's entry in page memory only, newest first, capped, behind a
  toolbar toggle, with no storage and no clock;
* a module that arrives is placed after the modules already drawn in
  its band, and a large build is revealed module by module, in an order
  that puts a module after the ones it leans on, with the counts said in
  words, a "Show the rest" button, the usual beat and nothing new, an
  early end for each thing that changes the question, and no reveal at
  all under reduced motion;
* the view follows the build: it starts out following, a move by hand
  stops it and `fit` starts it again, a build makes room before it lands,
  the ease is one named length done in script and asks about reduced
  motion first, and the marker says in fixed words how many of the newest
  build's parts are out of view and which way.

Whether the graph *looks* right is not decidable here; that is the
browser pass over ``tests/fixtures/dev_harness.html``.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

PACKAGE_ROOT = Path(__file__).resolve().parents[1]
ASSET_DIR = PACKAGE_ROOT / "s0ma_src" / "assets"
FIXTURE_DIR = PACKAGE_ROOT / "tests" / "fixtures"

INDEX_HTML = ASSET_DIR / "index.html"
APP_CSS = ASSET_DIR / "app.css"
APP_JS = ASSET_DIR / "app.js"
DEV_HARNESS = FIXTURE_DIR / "dev_harness.html"
FIXTURE_PAYLOAD = FIXTURE_DIR / "sh0w_fixture_payload.json"
NARRATION_FIXTURE = FIXTURE_DIR / "sh0w_narration_fixture.json"
TERMS_FIXTURE = FIXTURE_DIR / "sh0w_terms_fixture.json"

ASSET_FILES = (INDEX_HTML, APP_CSS, APP_JS)
SELF_CONTAINED_FILES = (INDEX_HTML, APP_CSS, APP_JS, DEV_HARNESS)


def read(path: Path) -> str:
    """Read *path* as utf-8 — never the platform's locale default."""
    return path.read_text(encoding="utf-8")


@pytest.mark.parametrize("path", ASSET_FILES, ids=lambda p: p.name)
def test_asset_exists_and_is_not_empty(path: Path) -> None:
    assert path.is_file(), f"missing frontend asset: {path.name}"
    assert read(path).strip(), f"empty frontend asset: {path.name}"


def test_index_html_loads_the_served_asset_routes() -> None:
    """``/`` must pull the assets from the routes the server serves."""
    index = read(INDEX_HTML)
    assert "/assets/app.css" in index
    assert "/assets/app.js" in index


def test_app_js_supports_both_boot_modes() -> None:
    """Fixture mode and live mode are both wired (plan §3.6)."""
    app_js = read(APP_JS)
    assert "__S0MA_FIXTURE__" in app_js, "fixture boot mode is missing"
    assert "/api/state" in app_js, "live poll of /api/state is missing"
    assert "/api/graph" in app_js, "live fetch of /api/graph is missing"


def test_reduced_motion_is_honored() -> None:
    """A11y floor (A10): reduced motion must be addressed somewhere."""
    combined = read(APP_CSS) + read(APP_JS)
    assert "prefers-reduced-motion" in combined


def test_graph_surface_is_labelled() -> None:
    """Nodes carry screen-reader labels, not just shapes (A10)."""
    assert "aria-label" in read(APP_JS)


def test_the_materialize_beat_is_the_only_motion() -> None:
    """All four delta treatments exist, and nothing else animates.

    A tripwire, not a proof — whether the beat *lands* is a browser
    matter. What is checkable here is that the four animations the beat
    is made of are still declared, and that they are still the only
    ``@keyframes`` in the stylesheet: an animation that appears here
    without a delta behind it would be decoration, which this viewer
    does not do (visual truth language §9, §12).
    """
    app_css = read(APP_CSS)
    declared = set(re.findall(r"@keyframes\s+([A-Za-z0-9_-]+)", app_css))
    assert declared == {
        "sh0w-materialize",
        "sh0w-vanish",
        "sh0w-ring-fade",
        "sh0w-outline-pulse",
    }
    # The ring outlives the movement, and then stops.
    assert "sh0w-ring-fade 4000ms" in app_css
    assert "BEAT_RING_MS = 4000" in read(APP_JS)


def test_reduced_motion_keeps_the_beat_and_drops_its_motion() -> None:
    """A10: every transition stays perceivable with motion turned off.

    The blanket reduced-motion reset would leave the highlight ring
    invisible — its fade would simply complete at once — so the ring is
    given back explicitly, unanimated, and removed by the same timer
    that ends the animated version.
    """
    app_css = read(APP_CSS)
    reduced = app_css[app_css.index("@media (prefers-reduced-motion: reduce)") :]
    assert ".beat-ring" in reduced
    assert reduced.count("animation: none !important") == 4


def test_every_stylesheet_colour_is_a_token() -> None:
    """Colours live only in the ``:root`` token block.

    Every rule reaches a colour through ``var(--...)``, so a palette is
    changed in one place and no rule keeps a stray literal behind.
    """
    app_css = read(APP_CSS)
    # Each entry opens a block whose body may hold colour literals. A
    # second palette (for example under prefers-color-scheme: dark) is
    # allowed by adding its opening line here.
    token_blocks = (":root {",)
    outside = app_css
    for opening in token_blocks:
        start = outside.index(opening)
        end = outside.index("\n}", start) + len("\n}")
        outside = outside[:start] + outside[end:]
    literal = re.compile(r"#[0-9A-Fa-f]{3,8}\b|\b(?:rgba?|hsla?)\(")
    assert literal.findall(outside) == []


@pytest.mark.parametrize(
    "path", (*SELF_CONTAINED_FILES, NARRATION_FIXTURE, TERMS_FIXTURE), ids=lambda p: p.name
)
def test_no_asset_reaches_off_this_machine(path: Path) -> None:
    """FR-STUDI0-7: the page is fully self-contained.

    No CDN, no web font, no remote image, no analytics beacon — and no
    SVG namespace URL literal either, which is why ``app.js`` reads the
    namespace off a probe element instead of hard-coding it.
    """
    text = read(path)
    assert "http://" not in text, f"{path.name} references an http:// URL"
    assert "https://" not in text, f"{path.name} references an https:// URL"


def test_fixture_payload_is_a_graph2_document() -> None:
    payload = json.loads(read(FIXTURE_PAYLOAD))
    assert payload["schema"] == "s0ma-graph@2"
    assert payload["components"], "fixture declares no components"
    assert payload["modules"], "fixture declares no modules"
    for family in ("authored", "derived", "verification"):
        assert payload["edges"][family], f"fixture has no {family} edges"


def test_fixture_payload_exercises_every_state_wrapper() -> None:
    """The projection of value / none / pending needs all three present."""
    raw = read(FIXTURE_PAYLOAD)
    assert '"state": "pending"' in raw, "no pending wrapper to project"
    assert '"state": "none"' in raw, "no none wrapper to project"
    assert '"state": "value"' in raw, "no value wrapper to project"


def test_fixture_payload_covers_every_declaration_glyph() -> None:
    """Each glyph the layout can draw has a component to draw it for."""
    payload = json.loads(read(FIXTURE_PAYLOAD))
    declared = {
        component["declaration_type"]
        for component in payload["components"].values()
    }
    assert {"nerve", "cell", "ganglion", "axon", "test"} <= declared


def test_fixture_payload_has_a_stale_module() -> None:
    """The stale treatment (banner, chips, triangles) needs a subject."""
    payload = json.loads(read(FIXTURE_PAYLOAD))
    freshness = payload["freshness"]
    assert freshness["status"] == "stale"
    assert freshness["stale_modules"], "stale status names no module"
    module_names = {module["name"] for module in payload["modules"]}
    assert set(freshness["stale_modules"]) <= module_names


def test_dev_harness_loads_the_real_assets_with_the_fixture() -> None:
    harness = read(DEV_HARNESS)
    assert "../../s0ma_src/assets/app.js" in harness
    assert "../../s0ma_src/assets/app.css" in harness
    assert "__S0MA_FIXTURE__" in harness


def _embedded(harness: str, element_id: str) -> object:
    """One JSON block the dev harness carries, by element id."""
    opener = '<script id="' + element_id + '" type="application/json">'
    start = harness.index(opener) + len(opener)
    end = harness.index("</" + "script>", start)
    return json.loads(harness[start:end])


def test_dev_harness_payload_matches_the_checked_in_fixture() -> None:
    """The harness embeds the payload; the two must not drift."""
    assert _embedded(read(DEV_HARNESS), "sh0w-fixture") == json.loads(
        read(FIXTURE_PAYLOAD)
    )


# ---------------------------------------------------------------------------
# The narration pane (M11)
# ---------------------------------------------------------------------------


def test_the_narration_pane_is_wired() -> None:
    """The pane reads the served block and nothing else."""
    app_js = read(APP_JS)
    assert "function applyNarration(" in app_js
    assert "function renderNarration(" in app_js
    assert "stateDoc.narration" in app_js or "stateDoc && stateDoc.narration" in app_js
    assert '"narration"' in app_js or "narration-list" in app_js


def test_narration_is_labelled_as_self_report() -> None:
    """Provenance is stated in words, not left to styling (truth language).

    A reader must not have to infer from a dashed border that what they
    are looking at is unverified. The pane says so.
    """
    app_js = read(APP_JS)
    assert "self-reported by the agent working here" in app_js
    assert "not verified against" in app_js
    assert "agent narration (self-reported)" in app_js


def test_narration_claims_no_verification_affordance() -> None:
    """No checkmark, no tick, and no unnegated claim of verification.

    studi0 checked none of this. The word ``verified`` may appear on the
    pane only in a sentence that denies it — "not verified against the
    build" — never as a badge, a mark, or an affordance.
    """
    app_js = read(APP_JS)
    pane = app_js[
        app_js.index("function applyNarration(") : app_js.index("* Collapse controls")
    ]
    for glyph in ("✓", "✔", "☑", "✅"):
        assert glyph not in pane, glyph
    for claim in ("verified", "confirmed", "validated"):
        cursor = pane.find(claim)
        while cursor != -1:
            assert pane[max(0, cursor - 4) : cursor] == "not ", claim
            cursor = pane.find(claim, cursor + 1)


def test_narration_focus_uses_the_ordinary_selection_path() -> None:
    """GP-2: a narration focuses the graph exactly as a click would.

    Not a second highlighting mechanism — the same ``select`` call the
    node hit target makes, so a focused component is inspected, dimmed
    against, and cleared by every control that already exists.
    """
    app_js = read(APP_JS)
    assert "function syncNarrationFocus(" in app_js
    assert 'select({ type: "node", id: subject })' in app_js
    assert 'select({ type: "node", id: canonicalId })' in app_js


def test_an_unresolvable_subject_moves_nothing_and_says_nothing() -> None:
    """GP-3 silence: a name the graph lacks is shown, never acted on."""
    app_js = read(APP_JS)
    assert "function firstKnownSubject(" in app_js
    assert "not in this graph" in app_js
    # The resolver consults the model and returns null rather than
    # guessing at a near match.
    assert "return null;" in app_js


def test_narration_states_what_it_is_not_showing() -> None:
    """A bounded window must never read as a complete transcript."""
    app_js = read(APP_JS)
    assert "narrated movements shown" in app_js
    assert "lines unreadable — not shown" in app_js
    assert "line unreadable — not shown" in app_js


def test_the_narration_pane_is_keyboard_reachable() -> None:
    """A10: the pane and its subject controls are real focusable elements."""
    app_js = read(APP_JS)
    assert 'ui.narration.setAttribute("tabindex", "-1")' in app_js
    assert 'ui.narration.setAttribute("aria-label"' in app_js
    # Subjects that resolve are buttons with their own labels, not
    # click handlers bolted to a span.
    assert 'el("button", "narration-subject"' in app_js
    assert '"show " + canonicalId + " in the graph"' in app_js
    assert 'button.type = "button"' in app_js


def test_the_narration_pane_looks_unlike_the_graph() -> None:
    """Self-report and canonical truth must be separable at a glance."""
    app_css = read(APP_CSS)
    narration = app_css[app_css.index(".narration {") : app_css.index(".inspector {")]
    assert "border-right: 1px dashed" in narration
    assert "var(--surface-sunken)" in narration
    # Amber means stale, and only stale: the narration pane never
    # borrows it, or the two meanings would collide.
    for amber in ("--amber", "--amber-mark", "--amber-soft", "--amber-line"):
        assert amber not in narration, amber


def test_the_narration_pane_never_animates() -> None:
    """It is a list of statements, so reduced motion has nothing to undo."""
    app_css = read(APP_CSS)
    narration = app_css[app_css.index(".narration {") : app_css.index(".inspector {")]
    assert "animation" not in narration
    assert "transition" not in narration


def test_the_flagged_narration_state_is_not_colour_alone() -> None:
    """A10: unreadable lines are said in words and carried by weight."""
    app_css = read(APP_CSS)
    flagged = app_css[app_css.index(".narration-foot--flagged {") :]
    flagged = flagged[: flagged.index("}")]
    assert "font-weight" in flagged
    assert "unreadable" in read(APP_JS)


def test_the_narration_fixture_exercises_the_pane() -> None:
    """Every branch the pane can draw has a fixture entry to draw it for."""
    fixture = json.loads(read(NARRATION_FIXTURE))
    entries = fixture["entries"]
    graph = json.loads(read(FIXTURE_PAYLOAD))

    assert {entry["phase"] for entry in entries} == {
        "orient",
        "author",
        "verify",
        "move_on",
    }
    assert any(entry["why"] is None for entry in entries), "no absent why to draw"
    assert any(len(entry["subjects"]) > 1 for entry in entries)
    # One subject the graph carries (a focusable button) and one it does
    # not (the "not in this graph" treatment).
    subjects = {subject for entry in entries for subject in entry["subjects"]}
    assert subjects & set(graph["components"]), "no resolvable subject"
    assert subjects - set(graph["components"]), "no unresolvable subject"
    assert fixture["invalid"] >= 1, "no refused line to report"
    assert fixture["total"] == len(entries)


def test_dev_harness_narration_matches_the_checked_in_fixture() -> None:
    """The harness embeds the narration block too; the two must not drift."""
    harness = read(DEV_HARNESS)
    assert "__S0MA_NARRATION__" in harness
    assert _embedded(harness, "sh0w-narration") == json.loads(read(NARRATION_FIXTURE))


# ---------------------------------------------------------------------------
# The component inspector: DSL term first, the long tail folded away
# ---------------------------------------------------------------------------


def _component_inspector(app_js: str) -> str:
    start = app_js.index("function renderComponentInspector(")
    return app_js[start : app_js.index("\n}\n", start)]


def test_inspector_labels_put_the_dsl_term_first() -> None:
    """Each label is the term in monospace, a separator, then the phrase."""
    app_js = read(APP_JS)
    for term, phrase in (
        ("intent", "what it is for"),
        ("guarantees", "what it promises"),
        ("forbids", "what it must never do"),
        ("expects", "what it needs before it runs"),
        ("schema", "its shape"),
        ("invariants", "what must always be true of it"),
        ("covered_by", "checked by"),
        ("value", "its value"),
    ):
        assert f'  {term}: "{phrase}",' in app_js, term
    assert 'label.appendChild(el("code", "term", term));' in app_js
    assert 'el("span", "label-sep", " · ")' in app_js
    assert 'plainSection("dependencies", "what it leans on")' in app_js
    assert 'plainSection("dependents", "what leans on it")' in app_js


def test_inspector_above_the_fold_order() -> None:
    """intent, guarantees, forbids, expects, then the two relationship lists."""
    app_js = read(APP_JS)
    assert 'nerve: ["intent", "guarantees", "forbids", "expects"],' in app_js
    assert 'ganglion: ["intent", "guarantees", "forbids", "expects"],' in app_js
    assert 'cell: ["intent", "schema", "invariants", "value"],' in app_js
    body = _component_inspector(app_js)
    order = [
        body.index("componentHead(component);"),
        body.index("for (var i = 0; i < aboveTheFold.length; i += 1)"),
        body.index("renderDependencies("),
        body.index("renderDependents("),
        body.index("renderMoreAboutThisPart("),
    ]
    assert order == sorted(order)


def test_inspector_folds_the_rest_into_one_disclosure() -> None:
    """One native disclosure, a counted not-declared line, pending never folded."""
    app_js = read(APP_JS)
    assert 'el("details", "inspector-more")' in app_js
    assert '"More about this part"' in app_js
    assert '" fields not declared"' in app_js
    assert '" field not declared"' in app_js
    body = _component_inspector(app_js)
    # A pending field is drawn above the disclosure, before it is built.
    assert body.index('projected.kind === "pending"') < body.index(
        "renderMoreAboutThisPart("
    )
    assert "undeclared.push(key);" in body


def test_inspector_relationships_select_through_the_click_path() -> None:
    """The part at the other end is a button that calls the same select()."""
    app_js = read(APP_JS)
    assert 'el("button", "rel-peer rel-peer-button", shortName(peerId))' in app_js
    assert 'select({ type: "node", id: peerId })' in app_js
    assert '"show " + peerId + " in the graph"' in app_js


def test_inspector_shows_a_written_forbids_none_as_none() -> None:
    """``forbids: none`` is an answer; a payload without the key says so."""
    app_js = read(APP_JS)
    assert 'name === "forbids" &&' in app_js
    assert 'host.appendChild(el("code", "term", "none"));' in app_js


def test_the_inspector_never_animates() -> None:
    """The disclosure opens at once: the inspector's rules carry no motion."""
    app_css = read(APP_CSS)
    inspector = app_css[app_css.index(".inspector {") : app_css.index(".empty-state {")]
    assert "animation" not in inspector
    assert "transition" not in inspector


def test_fixture_payload_carries_forbids_in_every_state() -> None:
    """The harness has a written sentence, a written none and a pending one."""
    payload = json.loads(read(FIXTURE_PAYLOAD))
    states = {
        component["fields"]["forbids"]["state"]
        for component in payload["components"].values()
        if "forbids" in component["fields"]
    }
    assert states == {"value", "none", "pending"}


def test_inspector_rows_follow_the_keys_the_payload_carries() -> None:
    """A field after intent is drawn only when the part carries its key.

    A row saying "not declared" for a line the declaration type does not
    have would be false. The one exception is forbids on a nerve or a
    ganglion, which an older build's payload lacks.
    """
    app_js = read(APP_JS)
    body = _component_inspector(app_js)
    assert "if (!fieldIsCarried(name, declarationType, fields)) {" in body
    assert 'if (name === "intent" || name in fields) {' in app_js
    assert (
        'name === "forbids" &&\n'
        '    (declarationType === "nerve" || declarationType === "ganglion")'
    ) in app_js


# ---------------------------------------------------------------------------
# The module panel: a module is selectable, and its panel reads its record
# ---------------------------------------------------------------------------


def _module_inspector(app_js: str) -> str:
    start = app_js.index("function renderModuleInspector(")
    return app_js[start : app_js.index("\n}\n", start)]


def test_a_module_is_selected_through_the_click_path() -> None:
    """The module's name is a real control that calls the same select()."""
    app_js = read(APP_JS)
    assert 'select({ type: "module", id: organ.module })' in app_js
    assert '"aria-label": "inspect module " + organ.module,' in app_js
    assert '"data-organ-name": organ.module,' in app_js
    assert 'select({ type: "module", id: focusedName })' in app_js
    assert 'renderModuleInspector(state.model.modules[selection.id])' in app_js
    # The name sits after the header in the tab order, so the arrow and
    # the rest of the header keep collapsing and expanding the module.
    assert (
        "ui.layerNodes.appendChild(organHeaderHit(organ));\n"
        "    ui.layerNodes.appendChild(organNameHit(organ));"
    ) in app_js


def test_a_module_selection_survives_a_refresh_until_the_module_is_gone() -> None:
    app_js = read(APP_JS)
    assert (
        '  if (state.selection && state.selection.type === "module") {\n'
        "    if (!state.model.modules[state.selection.id]) {\n"
        "      state.selection = null;"
    ) in app_js


def test_module_panel_labels_put_the_dsl_term_first() -> None:
    """``uses``, ``requires``, ``exports`` are terms; "used by" is not."""
    app_js = read(APP_JS)
    for term, phrase in (
        ("uses", "parts of other files it may reach"),
        ("requires", "code from outside the project"),
        ("exports", "what it offers to other files"),
    ):
        assert f'  {term}: "{phrase}",' in app_js, term
    assert 'plainSection("used by", "files that reach into it")' in app_js
    assert 'el("code", "decl-tag", "module")' in app_js
    assert '"More about this module"' in app_js
    assert '" lists not declared"' in app_js
    assert '" list not declared"' in app_js
    assert '"none in this project"' in app_js


def test_module_panel_above_the_fold_order() -> None:
    """header, intent, uses, requires, exports, used by, then the fold."""
    body = _module_inspector(read(APP_JS))
    order = [
        body.index("moduleHead(module);"),
        body.index('fieldSection("intent")'),
        body.index("renderModuleUses("),
        body.index("renderModuleRequires("),
        body.index("renderModuleExports("),
        body.index("renderModuleUsedBy("),
        body.index("renderMoreAboutThisModule("),
    ]
    assert order == sorted(order)


def test_module_panel_rows_follow_the_keys_the_record_carries() -> None:
    """An older payload's module record shows the header and intent alone."""
    body = _module_inspector(read(APP_JS))
    assert 'if (carriesImports && "uses" in imports) {' in body
    assert 'if (carriesImports && "requires" in imports) {' in body
    assert 'if ("exports" in module) {' in body
    assert "if (carriesImports) {\n    renderModuleUsedBy(name);" in body


def test_module_panel_names_select_through_the_relationship_path() -> None:
    """uses and exports go through peerControl; requires names never do."""
    app_js = read(APP_JS)
    assert 'parts[j].module + "::" + parts[j].part' in app_js
    assert 'peerControl(moduleName + "::" + String(names[i]))' in app_js
    requires = app_js[
        app_js.index("function renderModuleRequires(") : app_js.index(
            "function renderModuleExports("
        )
    ]
    assert "peerControl(" not in requires
    assert "button" not in requires


def test_used_by_is_a_reverse_index_of_declared_uses() -> None:
    """Built from every module's own ``uses`` list, never from edges."""
    app_js = read(APP_JS)
    reverse = app_js[
        app_js.index("function modulesUsing(") : app_js.index(
            "function renderModuleUsedBy("
        )
    ]
    assert "declaredNames(imports.uses)" in reverse
    assert "splitUsesEntry(entries[j]).module === moduleName" in reverse
    assert "edges" not in reverse
    assert '"show module " + moduleName + " in the graph"' in app_js


def test_used_by_never_claims_completeness_it_cannot_know() -> None:
    """A module whose ``uses`` is absent or pending makes the list partial."""
    app_js = read(APP_JS)
    reverse = app_js[
        app_js.index("function modulesUsing(") : app_js.index(
            "function moduleControl("
        )
    ]
    assert 'if (!hasUses || projectValue(imports.uses).kind !== "none") {' in reverse
    assert '"1 module has not declared its "' in reverse
    assert '" modules have not declared their "' in reverse
    assert '", so this list may be incomplete"' in reverse
    # "none in this project" is said only when nothing is unknown.
    assert reverse.index("if (reverse.unknown > 0) {") < reverse.index(
        '"none in this project"'
    )


def test_module_fold_shows_a_privileged_list_with_entries() -> None:
    app_js = read(APP_JS)
    fold = app_js[app_js.index("function renderMoreAboutThisModule(") :]
    fold = fold[: fold.index("\n}\n")]
    assert "if (Array.isArray(privileged) && privileged.length > 0) {" in fold
    assert 'fieldLabel("dt", null, "privileged", null)' in fold
    assert 'el("code", "term", String(privileged[p]))' in fold


def test_fixture_module_records_carry_the_module_panel_keys() -> None:
    """The harness has a module record to draw every module panel row for."""
    payload = json.loads(read(FIXTURE_PAYLOAD))
    for module in payload["modules"]:
        for key in ("imports", "exports", "version", "tags", "source_file"):
            assert key in module, (module["name"], key)
    uses = [
        entry
        for module in payload["modules"]
        if module["imports"]["uses"]["state"] == "value"
        for entry in module["imports"]["uses"]["value"]
    ]
    assert uses, "no declared uses to build used by from"


# ---------------------------------------------------------------------------
# Terms: s0ma's own definitions, opened from the words the page prints
# ---------------------------------------------------------------------------


def _between(text: str, start: str, end: str) -> str:
    begin = text.index(start)
    return text[begin : text.index(end, begin)]


def test_terms_arrive_with_the_graph_and_with_the_fixture() -> None:
    """Live mode reads the block /api/graph serves; fixture mode a global."""
    app_js = read(APP_JS)
    assert "function applyTerms(" in app_js
    assert "applyTerms(document_.terms);" in app_js
    assert "applyTerms(window.__S0MA_TERMS__);" in app_js
    # Applied before the graph, so the repaint already knows the words.
    fetch = _between(app_js, "function fetchGraph(", "\n}\n")
    assert fetch.index("applyTerms(") < fetch.index("applyGraph(")


def test_the_page_keeps_pointers_and_never_a_definition() -> None:
    """Ids only: three role and field pointers, in their own constants."""
    app_js = read(APP_JS)
    pointers = _between(app_js, "var TERM_POINTERS = {", "};")
    assert '"layer-name": "concept:layer",' in pointers
    assert 'relation: "concept:axon",' in pointers
    contract = _between(app_js, "var CONTRACT_FIELD_POINTERS = {", "};")
    for field in ("guarantees", "forbids", "expects"):
        assert f'  {field}: "concept:contract",' in contract, field
    assert contract.count("concept:") == 3
    # No summary or definition text from the slice is written in any asset.
    terms = json.loads(read(TERMS_FIXTURE))
    for path in ASSET_FILES:
        text = read(path)
        for entry in terms["entries"]:
            assert entry["summary"] not in text, (path.name, entry["id"])
            assert entry.get("definition", "\0") not in text, (path.name, entry["id"])


def test_one_resolver_and_its_order() -> None:
    """A role pointer, then a contract line, then the entry's own names."""
    resolver = _between(read(APP_JS), "function resolveTerm(", "\n}\n")
    order = [
        resolver.index("TERM_POINTERS[role]"),
        resolver.index("CONTRACT_FIELD_POINTERS[text]"),
        resolver.index("state.terms.byName"),
    ]
    assert order == sorted(order)
    assert "return null;" in resolver
    assert ".toLowerCase()" in _between(read(APP_JS), "function termKey(", "\n}\n")


def test_a_term_control_is_a_real_button_with_aria_expanded() -> None:
    app_js = read(APP_JS)
    control = _between(app_js, "function inspectorTerm(", "\n}\n")
    assert 'el("button", "term-control " + className, text)' in control
    assert 'button.type = "button";' in control
    assert 'button.setAttribute("aria-expanded", "false");' in control
    assert 'button.setAttribute("aria-expanded", "true");' in app_js


def test_the_term_positions_are_wired() -> None:
    """Header, labels, fold names, relation words and the legend."""
    app_js = read(APP_JS)
    assert 'inspectorTerm(component.declaration_type, null, "decl-tag")' in app_js
    assert 'inspectorTerm("module", null, "decl-tag")' in app_js
    assert 'appendTermValue(where, component.layer, "layer-name");' in app_js
    assert 'appendTermValue(where, module.layer, "layer-name");' in app_js
    assert 'appendTermWord(where, "module");' in app_js
    assert 'appendTermWord(where, "layer");' in app_js
    label = _between(app_js, "function fieldLabel(", "\n}\n")
    assert 'inspectorTerm(term, null, "term")' in label
    # The plain phrase is appended after the control, never inside it.
    assert label.index("inspectorTerm(") < label.index('"label-phrase"')
    assert "appendTermWord(dt, term);" in app_js
    assert "appendTermWord(item, undeclared[j]);" in app_js
    assert 'appendTermValue(head, edge.relation, "relation");' in app_js
    assert 'inspectorTerm(String(edge.relation), "relation", "rel-relation")' in app_js
    assert 'el("button", "term-control legend-term", record.word)' in app_js


def test_the_card_holds_its_parts_in_order() -> None:
    """Where it is explained, the summary, Read more, then the command."""
    card = _between(read(APP_JS), "function termCard(", "\n}\n")
    order = [
        card.index("!isOwnName(entry, word)"),
        card.index('" is explained under "'),
        card.index("entry.summary"),
        card.index('el("details", "term-card-more")'),
        card.index('"Read more"'),
        card.index('el("p", "term-card-definition", entry.definition)'),
        card.index('"Full entry: "'),
        card.index('"s0ma docs show " + entry.id'),
    ]
    assert order == sorted(order)
    # The command is text in the monospace face, never a link.
    assert 'el("code", "term-card-command", "s0ma docs show " + entry.id)' in card
    assert '"a"' not in card and "href" not in card


def test_one_card_at_a_time_that_survives_a_repaint() -> None:
    app_js = read(APP_JS)
    toggle = _between(app_js, "function toggleTermCard(", "\n}\n")
    assert "closeTermCard();" in toggle
    restore = _between(app_js, "function restoreTermCard(", "\n}\n")
    assert "wanted.selection !== selectionKey(state.selection)" in restore
    inspector = _between(app_js, "function renderInspector(", "\n}\n")
    assert "restoreTermCard();" in inspector


def test_the_dictionary_is_wired() -> None:
    """A terms button, the heading, its sections, back, and Esc."""
    app_js = read(APP_JS)
    assert 'ui.termsButton = toolbarButton("terms", toggleDictionary);' in app_js
    assert 'ui.termsButton.setAttribute("aria-pressed", "false");' in app_js
    assert 'ui.termsButton.setAttribute("aria-pressed", String(state.dictionary.open));' in (
        app_js
    )
    dictionary = _between(app_js, "function renderDictionary(", "\n}\n")
    order = [
        dictionary.index('"Terms"'),
        dictionary.index('"close"'),
        dictionary.index("\"s0ma's own definitions, from s0ma\""),
        dictionary.index('"back to " + selectionName(back)'),
        dictionary.index('"On this page"'),
        dictionary.index('" more terms from s0ma"'),
    ]
    assert order == sorted(order)
    assert "source.release_version" in dictionary
    assert 'el("details", "inspector-more terms-more")' in dictionary
    assert "PAGE_TERM_WORDS" in _between(app_js, "function pageTermIds(", "\n}\n")
    # A part chosen while the dictionary is open takes the panel back.
    assert "closeDictionaryState();" in _between(app_js, "function select(", "\n}\n")
    assert "if (state.selection || state.dictionary.open) {" in app_js
    # A legend glyph name opens the dictionary on its entry.
    assert "openDictionary(entryId);" in app_js
    assert 'scrollIntoView({ block: "nearest" })' in app_js


def test_pressing_terms_again_returns_to_the_part() -> None:
    """Open, the terms button goes back to the part, as "back to" does."""
    app_js = read(APP_JS)
    toggle = _between(app_js, "function toggleDictionary(", "\n}\n")
    order = [
        toggle.index("if (state.dictionary.open) {"),
        toggle.index("var back = state.dictionary.back;"),
        toggle.index("if (back && selectionStillExists(back)) {"),
        toggle.index("select(back);"),
        toggle.index("ui.inspector.focus();"),
        toggle.index("clearSelection();"),
        toggle.index("openDictionary(null);"),
    ]
    assert order == sorted(order)
    # The dictionary's own back button does the same two steps.
    dictionary = _between(app_js, "function renderDictionary(", "\n}\n")
    assert "if (back && selectionStillExists(back)) {" in dictionary
    assert "select(back);\n      ui.inspector.focus();" in dictionary


def test_with_no_terms_the_page_reads_as_before() -> None:
    """No entries: no control anywhere, no terms button, the old elements."""
    app_js = read(APP_JS)
    resolver = _between(app_js, "function resolveTerm(", "\n}\n")
    assert resolver.index("if (state.terms.entries.length === 0) {") < resolver.index(
        "TERM_POINTERS"
    )
    assert "ui.termsButton.hidden = true;" in app_js
    assert "ui.termsButton.hidden = !has;" in app_js
    # Every position falls back to the element it drew before.
    assert 'el("code", "decl-tag", component.declaration_type || "not declared")' in app_js
    assert 'moduleTag || el("code", "decl-tag", "module")' in app_js
    assert 'label.appendChild(el("code", "term", term));' in app_js
    assert 'control || el("code", "term", word)' in app_js
    assert 'relationControl || el("span", "rel-relation", relationText)' in app_js
    assert 'next = el("span", null, record.word);' in app_js


def test_the_plain_words_stay_in_the_plain_face() -> None:
    """Monospace is for DSL words and commands; the card's own words are not."""
    app_js = read(APP_JS)
    for phrase in ('"Read more"', '"Full entry: "', '" is explained under "', '"Terms"'):
        line = next(text for text in app_js.splitlines() if phrase in text)
        assert '"code"' not in line, phrase
    app_css = read(APP_CSS)
    card = _between(app_css, ".term-card {", "}")
    assert "font-family: var(--font);" in card


def test_the_legend_takes_the_pointer_only_on_its_buttons() -> None:
    app_css = read(APP_CSS)
    legend = _between(app_css, ".legend {", "}")
    assert "pointer-events: none;" in legend
    assert ".legend .term-control {\n  pointer-events: auto;\n}" in app_css


def test_terms_styles_add_no_motion() -> None:
    app_css = read(APP_CSS)
    terms = _between(app_css, "/* A word s0ma's own dictionary explains", ".empty-state {")
    assert "animation" not in terms
    assert "transition" not in terms
    assert "@keyframes" not in terms


def test_the_terms_fixture_is_what_the_server_builds() -> None:
    """The harness's terms come from the packaged slice, never from a hand.

    The fixture's entries must equal what studi0 builds from the slice
    s0ma-core ships. The source stamp is checked for shape only, because
    every documentation build moves its snapshot hash. When this fails
    after a change to s0ma's concepts, regenerate the fixture (and the
    harness block that embeds it) from packages/s0ma-studi0 with:

        uv run python -c "import json, s0ma_studi0; print(json.dumps(
            s0ma_studi0.studi0_state.teaching_terms(), indent=2,
            sort_keys=True, ensure_ascii=False))"
    """
    import s0ma_studi0

    built = s0ma_studi0.studi0_state.teaching_terms()
    fixture = json.loads(read(TERMS_FIXTURE))
    assert built["entries"], "the packaged slice gave no entries"
    assert fixture["entries"] == built["entries"]
    assert set(fixture["source"]) == {"release_version", "snapshot_hash"}


def test_dev_harness_terms_match_the_checked_in_fixture() -> None:
    harness = read(DEV_HARNESS)
    assert "__S0MA_TERMS__" in harness
    assert _embedded(harness, "sh0w-terms") == json.loads(read(TERMS_FIXTURE))


# ---------------------------------------------------------------- not built


NOT_BUILT_SENTENCE = "Nothing is built yet. Parts appear here when the first build lands."


def test_the_not_built_sentence_and_its_command() -> None:
    """One plain sentence in the plain face, and the command in monospace."""
    app_js = read(APP_JS)
    sentence_line = next(text for text in app_js.splitlines() if NOT_BUILT_SENTENCE in text)
    assert '"code"' not in sentence_line
    assert '"p",\n      "empty-sentence",' in app_js
    assert 'el("code", "empty-command", "s0ma build <project root>")' in app_js
    app_css = read(APP_CSS)
    assert "font-family: var(--font);" in _between(app_css, ".empty-sentence {", "}")
    assert "font-family: var(--mono);" in _between(app_css, ".empty-command {", "}")
    # The status line says the same in words.
    assert 'ui.statusText.textContent = "nothing is built yet";' in app_js


def test_not_built_is_not_offline() -> None:
    """Both wire answers for an unbuilt project lead to the empty state.

    The state document's ``build_status: "missing"`` is read before any
    graph is asked for, and the graph route's ``NOT_BUILT`` answer is read
    before a non-ok status is treated as a lost connection.
    """
    app_js = read(APP_JS)
    assert 'var NOT_BUILT_CODE = "NOT_BUILT";' in app_js
    poll = _between(app_js, "function pollOnce(", "\n}\n")
    assert poll.index('stateDoc.build_status === "missing"') < poll.index("fetchGraph(")
    assert "applyNotBuilt();" in poll
    fetch = _between(app_js, "function fetchGraph(", "\n}\n")
    assert fetch.index("document_.error.code === NOT_BUILT_CODE") < fetch.index("if (!answer.ok) {")
    not_built = _between(app_js, "function applyNotBuilt(", "\n}\n")
    assert "setOffline" not in not_built
    assert 'state.buildStatus = "missing";' in not_built


def test_the_empty_state_waits_for_the_server() -> None:
    """Nothing is inferred: no "nothing is built" before an answer says so."""
    app_js = read(APP_JS)
    assert "  buildStatus: null,\n" in app_js
    empty = _between(app_js, "function renderEmptyState(", "\n}\n")
    assert empty.index('if (state.buildStatus !== "missing") {') < empty.index(
        "ui.emptyState.hidden = false;"
    )


def test_the_empty_canvas_draws_the_standard_bands() -> None:
    """Every layer band, in the usual order, the framework one on its toggle."""
    app_js = read(APP_JS)
    layout = _between(app_js, "function emptyLayout(", "\n}\n")
    assert "LAYER_ORDER.length" in layout
    assert 'LAYER_ORDER[i] === "FRAMEWORK" && !state.toggles.framework' in layout
    empty = _between(app_js, "function renderEmptyState(", "\n}\n")
    assert empty.index("state.layout = emptyLayout();") < empty.index("renderBands(state.layout);")


def test_the_first_build_gets_the_added_part_beat() -> None:
    """After "nothing is built", the first graph is diffed against nothing."""
    app_js = read(APP_JS)
    apply = _between(app_js, "function applyGraph(", "\n}\n")
    assert apply.index("state.notBuilt ? { components: {} } : state.graph") < apply.index(
        "diffGraphs(previous, graph)"
    )
    assert "state.beatPending = deltaHasAny(delta);" in apply


def test_the_empty_state_adds_no_motion() -> None:
    app_css = read(APP_CSS)
    empty = _between(app_css, ".empty-state {", "@media (max-width: 900px)")
    assert "animation" not in empty
    assert "transition" not in empty
    assert "@keyframes" not in empty


# ------------------------------------------------------------ what changed


def test_a_moved_line_is_not_a_change() -> None:
    """A part is changed only when something it declares differs.

    Where it sits in its file is not a declaration: ``location`` is never
    compared, so a part pushed down by an insertion above it is not
    marked. The beat reads the same answer as the list of changes.
    """
    app_js = read(APP_JS)
    rule = _between(app_js, "var NOT_A_DECLARED_LINE", ";\n")
    assert "location: true" in rule
    diff = _between(app_js, "function diffGraphs(", "\n}\n")
    assert "JSON.stringify(previousComponents[key])" not in diff
    assert "declaredChanges(previous, next, key)" in diff
    assert "delta.changed[key] = lines;" in diff


def test_the_declared_lines_are_named_in_order() -> None:
    """``intent``, then each field key that differs, then declaration facts."""
    app_js = read(APP_JS)
    changes = _between(app_js, "function declaredChanges(", "\n}\n")
    intent = changes.index('lines.push("intent");')
    fields = changes.index("lines.push(fieldKeys[i]);")
    facts = changes.index("lines.push(factKeys[i]);")
    dependencies = changes.index('lines.push("dependencies");')
    assert intent < fields < facts < dependencies
    assert "orderedFieldKeys(fieldUnion)" in changes


def test_dependencies_are_compared_from_the_part_s_own_side() -> None:
    """What it leans on counts; what leans on it does not."""
    app_js = read(APP_JS)
    keys = _between(app_js, "function dependencyKeys(", "\n}\n")
    assert 'var families = ["authored", "derived"];' in keys
    assert "list[j].source === canonicalId" in keys
    assert "list[j].target === canonicalId" not in keys
    assert "return keys.sort(compareStrings);" in keys


OUTLINE_SENTENCE = "Outlined parts arrived in the newest build."


def test_the_newest_build_s_additions_stay_outlined() -> None:
    """Added parts keep an outline after the beat, until the next build.

    The outline is taken over only by a build that adds, changes, or
    removes something; the beat's own end never touches it; a page
    opened on a built project starts with nothing outlined.
    """
    app_js = read(APP_JS)
    assert "  outlined: {},\n" in app_js
    apply = _between(app_js, "function applyGraph(", "\n}\n")
    assert "if (deltaChangesParts(delta)) {" in apply
    assert "state.outlined = {};" in apply
    assert "state.outlined[addedId] = true;" in apply
    assert "delta.changed" not in apply
    takes = _between(app_js, "function deltaChangesParts(", "\n}\n")
    assert "delta.stale" not in takes
    end = _between(app_js, "function endBeat(", "\n}\n")
    assert "outlined" not in end
    strip = _between(app_js, "function stripBeatMarks(", "\n}\n")
    assert '"beat-ring"' in strip and "arrival" not in strip
    node = _between(app_js, "function nodeElement(", "\n}\n")
    assert "if (state.outlined[node.id]) {" in node
    assert "arrivalOutline(node.x, node.y, node.w, node.h)" in node


def test_the_outline_is_static_and_not_dashed() -> None:
    app_css = read(APP_CSS)
    outline = _between(app_css, ".arrival-outline {", "/* ----")
    assert "animation" not in outline
    assert "transition" not in outline
    assert "dasharray" not in outline
    assert "stroke: var(--ink-soft);" in outline
    # Selection is the accent rule inside the cell; this is not it.
    assert "--accent" not in outline
    assert "--amber" not in outline


def test_the_status_line_says_what_the_outline_means() -> None:
    app_js = read(APP_JS)
    status = _between(app_js, "function renderStatusLine(", "\n}\n")
    assert status.index("if (outlinedInView(layout) > 0) {") < status.index(OUTLINE_SENTENCE)
    line = next(text for text in app_js.splitlines() if OUTLINE_SENTENCE in text)
    assert '"code"' not in line


CHANGES_HEADING = "What changed since you opened this page"
CHANGES_EMPTY = "Nothing yet. Each build that lands is listed here and stays until you reload."


def test_the_list_of_changes_is_an_aside_with_a_polite_live_list() -> None:
    app_js = read(APP_JS)
    pane = _between(app_js, "function buildChangesPane(", "\n}\n")
    assert 'ui.changes = el("aside", "changes");' in pane
    label = 'ui.changes.setAttribute("aria-label", "what changed since you opened this page");'
    assert label in pane
    assert 'ui.changesList.setAttribute("aria-live", "polite");' in pane
    assert '"' + CHANGES_HEADING + '"' in pane
    assert '"' + CHANGES_EMPTY + '"' in pane
    # Updated in place, so a screen reader hears the new build only.
    reconcile = _between(app_js, "function reconcileChangeItems(", "\n}\n")
    assert "current.isEqualNode(items[i])" in reconcile


def test_the_list_sits_above_narration_in_the_left_column() -> None:
    """Narration keeps its pane, heading and attribution, under the list."""
    app_js = read(APP_JS)
    shell = _between(app_js, "function buildShell(", "\n}\n")
    assert shell.index("buildChangesPane(ui.sideColumn);") < shell.index(
        "ui.sideColumn.appendChild(ui.narration);"
    )
    assert shell.index("ui.stage.appendChild(ui.sideColumn);") < shell.index(
        "ui.stage.appendChild(ui.canvasWrap);"
    )
    column = _between(app_js, "function syncSideColumn(", "\n}\n")
    assert "ui.sideColumn.hidden = !state.changes.shown && !narrating;" in column
    narration = _between(app_js, "function renderNarration(", "\n}\n")
    assert narration.count("syncSideColumn();") == 2


def test_one_entry_per_build_that_changed_a_part_newest_first() -> None:
    """Only a build that adds, changes, or removes makes an entry and a number."""
    app_js = read(APP_JS)
    apply = _between(app_js, "function applyGraph(", "\n}\n")
    gate = apply.index("if (deltaChangesParts(delta)) {")
    assert gate < apply.index("recordChange(delta, previous, graph, firstBuild);")
    assert apply.index("var firstBuild = state.notBuilt;") < apply.index("state.notBuilt = false;")
    record = _between(app_js, "function recordChange(", "\n}\n")
    assert "state.changes.made += 1;" in record
    assert "state.changes.entries.unshift(record);" in record
    # A page opened on a built project has nothing to diff against.
    diff = _between(app_js, "function diffGraphs(", "\n}\n")
    assert "if (!previous) {\n    return delta;\n  }" in diff


def test_the_list_keeps_the_newest_thirty_and_says_how_many_dropped() -> None:
    app_js = read(APP_JS)
    assert "var CHANGES_KEPT = 30;" in app_js
    record = _between(app_js, "function recordChange(", "\n}\n")
    assert "while (state.changes.entries.length > CHANGES_KEPT) {" in record
    assert "state.changes.entries.pop();" in record
    assert "state.changes.dropped += 1;" in record
    assert '"1 earlier build is not listed."' in app_js
    assert '" earlier builds are not listed."' in app_js


def test_an_entry_reads_in_its_order_and_its_words() -> None:
    app_js = read(APP_JS)
    item = _between(app_js, "function changeEntryItem(", "\n}\n")
    assert 'el("strong", null, "Build " + entry.number)' in item
    assert '(entry.firstBuild ? "the first build, " : "")' in item
    order = [
        item.index('"changes-verb", "added "'),
        item.index('"changes-verb", "changed "'),
        item.index('"changes-verb", "removed "'),
    ]
    assert order == sorted(order)
    # Part names: the relationship rows' control while the part exists,
    # plain text once it is gone; removed parts are always plain text.
    assert "changePartName(addedShown[i].id)" in item
    assert "changePartName(changed[i].id)" in item
    assert "changeGoneName(removed[i].id)" in item
    name = _between(app_js, "function changePartName(", "\n}\n")
    assert "state.model.components[canonicalId]" in name
    assert "peerControl(canonicalId)" in name
    gone = _between(app_js, "function changeGoneName(", "\n}\n")
    assert 'el("code", "changes-name", shortName(canonicalId))' in gone
    assert "button" not in gone
    # DSL terms in monospace, "dependencies" in the plain face.
    assert 'document.createTextNode("dependencies")' in item
    assert 'el("code", "term", lines[j])' in item


def test_the_counts_are_said_in_words() -> None:
    app_js = read(APP_JS)
    counts = _between(app_js, "function changeCounts(", "\n}\n")
    assert '["added", added],\n    ["changed", changed],\n    ["removed", removed],' in counts
    assert 'n === 1 ? " part" : " parts"' in counts
    assert 'phrases.join(", ")' in counts


def test_the_changes_toggle_is_a_real_pressed_button_beside_terms() -> None:
    app_js = read(APP_JS)
    shell = _between(app_js, "function buildShell(", "\n}\n")
    assert 'ui.changesButton = toolbarButton("changes", toggleChanges);' in shell
    assert 'ui.changesButton.setAttribute("aria-pressed", "true");' in shell
    assert shell.index("toolbar.appendChild(ui.changesButton);") < shell.index(
        "toolbar.appendChild(ui.termsButton);"
    )
    assert "  changes: { entries: [], made: 0, dropped: 0, shown: true },\n" in app_js
    toggle = _between(app_js, "function toggleChanges(", "\n}\n")
    assert "state.changes.shown = !state.changes.shown;" in toggle
    render_changes = _between(app_js, "function renderChanges(", "\n}\n")
    assert 'ui.changesButton.setAttribute("aria-pressed", String(state.changes.shown));' in (
        render_changes
    )
    assert "ui.changes.hidden = !state.changes.shown;" in render_changes


def test_the_page_stores_nothing_and_reads_no_clock() -> None:
    """The list lives in page memory only, and carries no clock time."""
    app_js = read(APP_JS)
    for storage in ("localStorage", "sessionStorage", "document.cookie", "indexedDB"):
        assert storage not in app_js, storage
    for clock in ("new Date", "Date.now", "performance.now", "toLocaleTimeString"):
        assert clock not in app_js, clock


def test_the_list_styles_add_no_motion_and_no_dashes() -> None:
    app_css = read(APP_CSS)
    pane = _between(app_css, ".side-column {", "-- narration */")
    assert "animation" not in pane
    assert "transition" not in pane
    assert "px dashed" not in pane
    assert "dasharray" not in pane
    assert "font-family: var(--mono);" in _between(app_css, ".changes-name {", "}")


# ------------------------------------------------------------ a steady band


def test_a_module_that_arrives_is_placed_after_the_ones_drawn() -> None:
    """A band keeps the order its modules were first placed in.

    The sort still decides the first layout, so a page opened on a built
    project lays out as before, and it still decides the order among the
    modules that arrive together; a module already placed never moves
    over for one that arrives. The memory goes with the slot memory, so
    a toggle that relays the view out sorts afresh, and a reload does.
    """
    app_js = read(APP_JS)
    layout = _between(app_js, "function computeLayout(", "\n}\n")
    assert "bandModules = steadyBandOrder(orderModulesInBand(bandModules, visible));" in layout
    first = _between(layout, "if (firstLayout) {", "\n  }")
    assert "state.slots = {};" in first
    assert "state.bandOrder = {};" in first
    assert "state.bandOrderNext = 0;" in first
    steady = _between(app_js, "function steadyBandOrder(", "\n}\n")
    assert "if (state.bandOrder[sorted[i]] === undefined) {" in steady
    assert "state.bandOrder[sorted[i]] = state.bandOrderNext;" in steady
    assert "return state.bandOrder[a] - state.bandOrder[b];" in steady
    assert "  bandOrder: {},\n  bandOrderNext: 0,\n" in app_js


# ------------------------------------------------------------ the reveal

REVEAL_BUTTON = "Show the rest"


def test_a_reveal_needs_more_than_four_parts_in_view_in_two_modules() -> None:
    """Anything smaller appears at once; "in view" is the list's own notion."""
    app_js = read(APP_JS)
    assert "var REVEAL_MORE_THAN = 4;" in app_js
    groups = _between(app_js, "function revealGroups(", "\n}\n")
    assert "changePartInView(changePart(ids[i], component))" in groups
    assert "if (count <= REVEAL_MORE_THAN || names.length < 2) {\n    return null;" in groups
    # One group per module, holding all of its new parts.
    assert "byModule[moduleName].push(ids[i]);" in groups
    assert "groups.push({ module: chosen, ids: byModule[chosen] });" in groups


def test_a_module_comes_after_the_modules_it_leans_on() -> None:
    """Dependencies first, among this build's modules; ties bottom band first."""
    app_js = read(APP_JS)
    groups = _between(app_js, "function revealGroups(", "\n}\n")
    assert 'if (edge.family === "verification") {\n      continue;' in groups
    assert "if (from !== to && byModule[from] && byModule[to]) {" in groups
    assert "leansOnlyOnPlaced(leansOn[remaining[i]], placed)" in groups
    # A cycle leaves nothing ready, and the tie rule decides.
    assert "ready = remaining.slice();" in groups
    assert "ready.sort(compareRevealModules);" in groups
    compare = _between(app_js, "function compareRevealModules(", "\n}\n")
    assert "revealBandRank(b) - revealBandRank(a)" in compare
    assert "return compareStrings(a, b);" in compare
    rank = _between(app_js, "function revealBandRank(", "\n}\n")
    assert "LAYER_ORDER.indexOf(layer)" in rank


def test_the_pause_is_one_named_constant_and_the_beat_is_reused() -> None:
    """Each group gets the usual beat; the pace is one value to tune."""
    app_js = read(APP_JS)
    assert app_js.count("var REVEAL_PAUSE_MS = ") == 1
    assert "var REVEAL_PAUSE_MS = 2000;" in app_js
    assert app_js.count("window.setTimeout(revealNext, REVEAL_PAUSE_MS)") == 2
    start = _between(app_js, "function startReveal(", "\n}\n")
    assert "delete state.delta.added[groups[i].ids[j]];" in start
    show = _between(app_js, "function showParts(", "\n}\n")
    assert "state.delta.added[ids[i]] = true;" in show
    assert "nodeElement(node, node.organ)" in show
    assert "scheduleBeatEnd();" in show
    # The reveal adds no motion of its own.
    app_css = read(APP_CSS)
    reveal_css = _between(app_css, ".status-reveal {", "/* ----")
    assert "animation" not in reveal_css
    assert "transition" not in reveal_css


def test_what_is_not_yet_shown_is_not_drawn() -> None:
    """Parts wait, edges wait for both ends, a new module waits for its group."""
    app_js = read(APP_JS)
    edges = _between(app_js, "function computeEdgeGroups(", "\n}\n")
    assert "if (notYetShown(edge.source) || notYetShown(edge.target)) {" in edges
    nodes = _between(app_js, "function renderNodes(", "\n}\n")
    assert "if (!organShown(organ)) {" in nodes
    assert "if (!notYetShown(organ.nodes[j].id)) {" in nodes
    organs = _between(app_js, "function renderOrgans(", "\n}\n")
    assert "if (organShown(layout.organs[i])) {" in organs
    # Counted as not shown, and wearing no outline until it is.
    status = _between(app_js, "function renderStatusLine(", "\n}\n")
    assert "state.reveal.total - state.reveal.shownCount" in status
    outlined = _between(app_js, "function outlinedInView(", "\n}\n")
    assert "!notYetShown(nodes[j].id)" in outlined


def test_the_status_line_says_how_many_are_showing_beside_a_real_button() -> None:
    app_js = read(APP_JS)
    sentence = _between(app_js, "function revealSentenceText(", "\n}\n")
    assert '"This build added " +' in sentence
    assert '" parts. Showing " +' in sentence
    assert '", module by module."' in sentence
    shell = _between(app_js, "function buildShell(", "\n}\n")
    assert 'ui.revealButton = toolbarButton("' + REVEAL_BUTTON + '", showTheRest);' in shell
    toolbar_button = _between(app_js, "function toolbarButton(", "\n}\n")
    assert 'el("button", "btn", label)' in toolbar_button
    assert 'button.type = "button";' in toolbar_button
    assert "finishReveal(true);" in _between(app_js, "function showTheRest(", "\n}\n")
    # Gone when the reveal ends.
    note = _between(app_js, "function renderRevealNote(", "\n}\n")
    assert "ui.revealNote.hidden = !reveal;" in note
    assert "state.reveal = null;" in _between(app_js, "function endReveal(", "\n}\n")
    # The status line takes no pointer, except on this button.
    app_css = read(APP_CSS)
    assert "pointer-events: auto;" in _between(app_css, ".status-line .status-button {", "}")
    assert "display: none;" in _between(app_css, ".status-reveal[hidden] {", "}")


def test_a_reveal_is_announced_once_politely() -> None:
    """Said when a reveal starts, in words that stay true; not once per group."""
    app_js = read(APP_JS)
    shell = _between(app_js, "function buildShell(", "\n}\n")
    assert 'ui.revealAnnounce.setAttribute("aria-live", "polite");' in shell
    assert "ui.statusLine.appendChild(ui.revealAnnounce);" in shell
    # Written in one place, and emptied in one place.
    assert app_js.count("ui.revealAnnounce.textContent =") == 2
    assert app_js.count('ui.revealAnnounce.textContent = "";') == 1
    start = _between(app_js, "function startReveal(", "\n}\n")
    assert '"This build added " + total + " parts. Showing them module by module."' in start
    assert 'ui.changesList.setAttribute("aria-busy", "true");' in start
    end = _between(app_js, "function endReveal(", "\n}\n")
    assert 'ui.revealAnnounce.textContent = "";' in end
    assert 'ui.changesList.removeAttribute("aria-busy");' in end
    assert "ui.revealAnnounce" not in _between(app_js, "function showParts(", "\n}\n")
    assert "clip-path: inset(50%);" in _between(read(APP_CSS), ".visually-hidden {", "}")


def test_the_list_entry_says_showing_and_names_only_what_is_shown() -> None:
    app_js = read(APP_JS)
    item = _between(app_js, "function changeEntryItem(", "\n}\n")
    assert "state.reveal && state.reveal.entry === entry.number ? state.reveal : null" in item
    assert '"showing " + reveal.shownCount + " of " + reveal.total' in item
    # The count is the build's whole count; the names wait for their group.
    assert "changeCounts(added.length, changed.length, removed.length)" in item
    assert "if (!reveal || !notYetShown(added[i].id)) {" in item
    # Nothing is dropped: the record keeps every added part.
    record = _between(app_js, "function changeRecord(", "\n}\n")
    assert "record.added.push(changePart(ids[i], nextComponents[ids[i]]));" in record


def test_each_thing_that_ends_a_reveal_early() -> None:
    app_js = read(APP_JS)
    # A newer build that adds, changes, or removes something, before its
    # own delta takes over and its entry is made.
    apply = _between(app_js, "function applyGraph(", "\n}\n")
    ends = apply.index("finishReveal(false);")
    assert apply.rindex("if (deltaChangesParts(delta)) {", 0, ends) < ends
    assert ends < apply.index("state.delta = delta;")
    assert ends < apply.index("recordChange(delta, previous, graph, firstBuild);")
    assert apply.index("startReveal(delta);") < apply.index("render();")
    # The toolbar controls that change what is in view.
    shell = _between(app_js, "function buildShell(", "\n}\n")
    for toggle in ("state.toggles.tests = !state.toggles.tests;",
                   "state.toggles.framework = !state.toggles.framework;"):
        assert "finishReveal(false);\n    " + toggle in shell
    collapse = _between(app_js, "function setAllCollapsed(", "\n}\n")
    assert collapse.index("finishReveal(false);") < collapse.index("render();")
    # Selecting something not yet shown.
    select_fn = _between(app_js, "function select(", "\n}\n")
    assert "if (selectsWhatIsNotYetShown(selection)) {\n    finishReveal(true);" in select_fn
    # The project becoming unbuilt.
    not_built = _between(app_js, "function applyNotBuilt(", "\n}\n")
    assert not_built.index("finishReveal(false);") < not_built.index("render();")
    # Ending stops the pause.
    end = _between(app_js, "function endReveal(", "\n}\n")
    assert "window.clearTimeout(revealTimer);" in end


def test_under_reduced_motion_there_is_no_reveal() -> None:
    app_js = read(APP_JS)
    reduced = _between(app_js, "function prefersReducedMotion(", "\n}\n")
    assert 'window.matchMedia("(prefers-reduced-motion: reduce)").matches' in reduced
    groups = _between(app_js, "function revealGroups(", "\n}\n")
    assert groups.index("if (prefersReducedMotion()) {\n    return null;") < groups.index(
        "Object.keys(delta.added)"
    )


def test_the_view_starts_out_following_and_stores_nothing() -> None:
    app_js = read(APP_JS)
    assert "  following: true,\n" in app_js
    assert "state.fitted" not in app_js
    # A move by hand stops following; fit starts it again.
    for fn in ("function zoomBy(", "function panBy("):
        assert "stopFollowing();" in _between(app_js, fn, "\n}\n"), fn
    stop = _between(app_js, "function stopFollowing(", "\n}\n")
    assert stop.index("settleView();") < stop.index("state.following = false;")
    fit = _between(app_js, "function fitAndFollow(", "\n}\n")
    assert "state.following = true;" in fit
    assert "easeViewTo(fitBox(state.layout), null);" in fit
    shell = _between(app_js, "function buildShell(", "\n}\n")
    assert 'var fit = toolbarButton("fit", function () {\n    fitAndFollow();' in shell
    keys = _between(app_js, "function onDocumentKeyDown(", "\n}\n")
    assert 'case "F":\n      fitAndFollow();' in keys
    # A drag that pans stops following; a click below the threshold does not.
    move = _between(app_js, "function onPointerMove(", "\n  }\n")
    assert move.index("Math.abs(dx) <= 2 && Math.abs(dy) <= 2") < move.index("stopFollowing();")


def test_the_fit_tooltip_says_the_view_keeps_it() -> None:
    shell = _between(read(APP_JS), "function buildShell(", "\n}\n")
    assert 'fit.title = "fit the whole graph in view and keep it there (f)";' in shell


def test_the_ease_is_one_named_length_done_in_script() -> None:
    app_js = read(APP_JS)
    assert app_js.count("var VIEW_EASE_MS = ") == 1
    assert "var VIEW_EASE_MS = 450;" in app_js
    step = _between(app_js, "function stepViewEase(", "\n}\n")
    assert "(now - ease.start) / VIEW_EASE_MS" in step
    assert "window.requestAnimationFrame(stepViewEase)" in step
    # No keyframe and no CSS transition for it: the keyframe set is pinned
    # above, and the view's own rules carry neither.
    marker_css = _between(read(APP_CSS), ".view-marker {", ".visually-hidden {")
    assert "animation" not in marker_css
    assert "transition" not in marker_css


def test_the_ease_asks_about_reduced_motion_first() -> None:
    app_js = read(APP_JS)
    ease = _between(app_js, "function easeViewTo(", "\n}\n")
    assert ease.index("prefersReducedMotion()") < ease.index("window.requestAnimationFrame")
    hold = _between(app_js, "function holdBuildForTheView(", "\n}\n")
    assert hold.index("prefersReducedMotion()") < hold.index("heldBuild = {")


def test_a_build_makes_room_then_lands_whole() -> None:
    app_js = read(APP_JS)
    apply = _between(app_js, "function applyGraph(", "\n}\n")
    # The hold comes before anything the build changes on the page.
    hold = apply.index("if (holdBuildForTheView(graph, stateDoc)) {")
    assert hold < apply.index("diffGraphs(previous, graph)")
    assert hold < apply.index("recordChange(delta, previous, graph, firstBuild);")
    assert apply.index("render();") < apply.index("frameTheLandedBuild(drawn, arrived);")
    land = _between(app_js, "function landHeldBuild(", "\n}\n")
    assert "applyGraph(held.graph, held.stateDoc);" in land
    # What arrives during an ease ends it first.
    for fn in ("function applyNotBuilt(", "function setAllCollapsed(", "function toggleOrgan("):
        assert "settleView();" in _between(app_js, fn, "\n}\n"), fn


def test_the_marker_says_how_many_and_which_way() -> None:
    app_js = read(APP_JS)
    text = _between(app_js, "function markerText(", "\n}\n")
    assert '"1 new part " + where + " · show it"' in text
    assert 'count + " new parts " + where + " · show them"' in text
    way = _between(app_js, "function markerDirection(", "\n}\n")
    for where in ('"above"', '"below"', '"to the left"', '"to the right"'):
        assert where in way, where
    # A real button that does what fit does, and not a live region.
    shell = _between(app_js, "function buildShell(", "\n}\n")
    assert 'ui.viewMarker = toolbarButton("", fitAndFollow);' in shell
    marker = shell[
        shell.index("ui.viewMarker = ") : shell.index("ui.canvasWrap.appendChild(ui.viewMarker);")
    ]
    assert "aria-live" not in marker
    # Counted in the list of changes' sense, against what the canvas shows.
    count = _between(app_js, "function renderViewMarker(", "\n}\n")
    assert "changePartInView(changePart(markerIds[i], component))" in count
    assert "getBoundingClientRect" in _between(app_js, "function shownBox(", "\n}\n")
