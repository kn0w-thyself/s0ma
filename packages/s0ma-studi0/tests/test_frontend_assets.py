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
  canvas only through the selection path a click already uses.

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


@pytest.mark.parametrize(
    "path", (*SELF_CONTAINED_FILES, NARRATION_FIXTURE), ids=lambda p: p.name
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
