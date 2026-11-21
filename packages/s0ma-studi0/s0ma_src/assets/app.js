/* sh0w — the studi0 graph viewer.
 *
 * One file, no imports, no build step, no external URL of any kind
 * (FR-STUDI0-7). Vanilla JS + SVG against evergreen browsers. The file
 * contains no `import`/`export` statement, so it loads either as an ES
 * module (how index.html loads it) or as a classic script (how the
 * file:// dev harness loads it).
 *
 * Boot modes (plan §3.6):
 *   1. fixture — window.__S0MA_FIXTURE__ holds an s0ma-graph@2 payload;
 *      render it once, no polling.
 *   2. live — poll /api/state every 1000 ms; when seq changes, fetch
 *      /api/graph, diff it against what is on screen, repaint.
 *
 * Truth discipline: everything drawn or written in the inspector comes
 * from the payload. Nothing is inferred, nothing is invented, and an
 * absent value says so. The canonical s0ma-ir@3 state wrappers
 * ({state: value|none|pending}) are projected for display, never
 * flattened away: `pending` is authoring debt and is shown as such.
 *
 * Two kinds of truth, never mixed: the GRAPH is what the project's
 * build says, and NARRATION is what an agent says it is doing. The
 * narration pane carries the second, marked as self-report, in its own
 * surface with its own visual language — no checkmarks, no verified
 * affordances, and never a mark on the canvas itself. The only thing
 * narration is allowed to do to the graph is FOCUS it: naming a
 * component that really exists selects it, exactly as a click would.
 * A name the graph does not carry moves nothing at all.
 *
 * Determinism: the FIRST layout of a payload is a pure function of
 * (payload, toggle state, per-organ collapse choices). No randomness,
 * no clock, no measurement of rendered text feeds a position.
 *
 * Spatial stability: after that first layout, grid slots are sticky for
 * the session. A build landing while the page is open never re-flows
 * what is already on screen — a new component takes the next free slot
 * in its organ, a removed one leaves its slot empty, and everything
 * else stays exactly where the reader last saw it. Changing a
 * visibility toggle is a different question, not a delta, and answers
 * with a fresh deterministic layout.
 */

/* ------------------------------------------------------------------ *
 * Constants
 * ------------------------------------------------------------------ */

var POLL_INTERVAL_MS = 1000;

/* How many builds the list of changes keeps. Older ones drop off the
 * end, and the list says how many have. */
var CHANGES_KEPT = 30;

/* Layout metrics, in user units. */
var NODE_W = 132;
var NODE_H = 82;
var NODE_GAP_X = 18;
var NODE_GAP_Y = 16;
var GLYPH_CY = 27; /* glyph centre, from the node cell's top edge */
var LABEL_Y = 58;
var STALE_CHIP_Y = 66;
var NODE_LABEL_MAX_CHARS = 20;

var ORGAN_PAD_X = 20;
var ORGAN_PAD_TOP = 8;
var ORGAN_PAD_BOTTOM = 20;
var ORGAN_HEADER_H = 44;
var ORGAN_COLLAPSED_PAD = 10;
var ORGAN_GAP_X = 44;
var ORGAN_GAP_Y = 30;
var ORGAN_MIN_W = 236;

var BAND_PAD_TOP = 42;
var BAND_PAD_BOTTOM = 24;
var BAND_GAP_Y = 18;
/* Organs wrap to a second row inside a band past this width, so one
 * crowded layer cannot stretch the canvas indefinitely sideways. */
var BAND_MAX_WIDTH = 2600;
var CONTENT_X = 32;

/* Band tints are drawn far past the content on both sides so a layer
 * reads as a band across the view however far the graph is panned. The
 * bleed is presentation only: it never enters the layout size, so
 * fit-to-view still frames the content and not the tint. */
var BAND_BLEED = 6000;

var FIT_PAD = 48;

/* An organ renders collapsed when the whole view holds more visible
 * nodes than this. One constant, deliberately tunable (plan §6). */
var COLLAPSE_THRESHOLD = 60;

/* The materialize beat — this file's only motion, and the only motion
 * anywhere on the canvas. It exists to answer one question ("what just
 * changed?") and it stops answering it after a few seconds.
 *
 * The durations live in app.css, which owns the animations; the two
 * milliseconds named here are the JS side of the same contract — when
 * the marks are dropped from the DOM. They are deliberately a little
 * longer than their CSS counterparts so a mark is never pulled out from
 * under an animation that is still running. Under
 * prefers-reduced-motion nothing animates, the ring is drawn statically
 * instead, and these timers are what make it appear for the same few
 * seconds and then go: every transition stays perceivable without
 * motion (truth language §11). */
var BEAT_RING_MS = 4000;
var BEAT_OUT_MS = 300;
var BEAT_EXPIRY_MS = BEAT_RING_MS + 300;
var BEAT_SWEEP_MS = BEAT_OUT_MS + 120;

/* How far the highlight ring sits outside the thing it highlights. */
var BEAT_RING_INSET = 5;

/* NOT_BUILT is the code /api/graph answers when the project has no build
 * artifacts; the state document says the same with build_status
 * "missing". Either answer means "nothing is built", never "offline". */
var NOT_BUILT_CODE = "NOT_BUILT";

/* An empty band is as tall as a band holding one row of parts, so the
 * first build lands in bands of about the size they already had. */
var EMPTY_BAND_H =
  BAND_PAD_TOP +
  ORGAN_HEADER_H +
  ORGAN_PAD_TOP +
  NODE_H +
  ORGAN_PAD_BOTTOM +
  BAND_PAD_BOTTOM;

var LAYER_ORDER = [
  "PRESENTATION",
  "APPLICATION",
  "DOMAIN",
  "INFRASTRUCTURE",
  "FRAMEWORK",
];

/* Sort order for nodes inside an organ. */
var DECLARATION_ORDER = [
  "ganglion",
  "nerve",
  "cell",
  "axon",
  "test",
  "helper",
  "doc_ref",
  "doc_guide",
  "example",
];

/* Declaration types hidden until the "tests and docs" toggle is on. */
var TEST_AND_DOC_TYPES = {
  test: true,
  helper: true,
  doc_ref: true,
  doc_guide: true,
  example: true,
};

/* Shape + letter per declaration type. Never colour alone. */
var GLYPH_LETTER = {
  ganglion: "G",
  nerve: "N",
  cell: "C",
  axon: "A",
  test: "T",
  helper: "H",
  doc_ref: "D",
  doc_guide: "D",
  example: "E",
};

var FAMILY_LABEL = {
  authored: "authored",
  derived: "derived",
  verification: "verification",
};

/* Fields the inspector lifts to the top of the field list when present. */
var FIELD_PRIORITY = ["guarantees", "expects", "forbids"];

/* The plain phrase shown after a field's DSL term in the inspector:
 * the term first, in monospace, then a separator, then this phrase.
 * A field with no entry here is labelled by its term alone. These are
 * labels, not definitions: what each term means is not written here. */
var FIELD_PHRASE = {
  intent: "what it is for",
  guarantees: "what it promises",
  forbids: "what it must never do",
  expects: "what it needs before it runs",
  schema: "its shape",
  invariants: "what must always be true of it",
  covered_by: "checked by",
  value: "its value",
};

/* The fields the component inspector shows above the fold, in order,
 * by declaration type. This sets the order only: a field after `intent`
 * is shown when the part's payload carries its key, so a declaration
 * type that has no such line shows no row for it. A key that is present
 * is never folded away; with nothing declared it says so. After these
 * come the two relationship sections, then one disclosure for the rest. */
var ABOVE_THE_FOLD = {
  nerve: ["intent", "guarantees", "forbids", "expects"],
  ganglion: ["intent", "guarantees", "forbids", "expects"],
  cell: ["intent", "schema", "invariants", "value"],
};
var ABOVE_THE_FOLD_DEFAULT = ["intent"];

/* The plain phrase after each term the module inspector labels, kept
 * apart from FIELD_PHRASE so a component field that shares a name is
 * never relabelled. The module's `intent` uses FIELD_PHRASE. */
var MODULE_PHRASE = {
  uses: "parts of other files it may reach",
  requires: "code from outside the project",
  exports: "what it offers to other files",
};

/* The three import lists the module inspector folds into one counted
 * line when they are not declared. */
var MODULE_FOLDED_LISTS = [
  "soft_requires",
  "deferred_requires",
  "runtime_only_requires",
];

/* Fields the inspector shows somewhere other than the field list under
 * the fold: kind and visibility head that list, covered_by sits with
 * the verification relationships, and depends_on is what the
 * dependencies section draws from the authored edges. */
var FIELDS_SHOWN_ELSEWHERE = {
  covered_by: true,
  depends_on: true,
};

/* The four movement phases the narration schema froze. A phase outside
 * this map is never rendered — the server refuses the line first, and
 * this is the second wall. */
var PHASE_LABEL = {
  orient: "orient",
  author: "author",
  verify: "verify",
  move_on: "move on",
};

/* How many narrations the pane shows at once. The payload is already
 * bounded server-side; this is the reading limit, not the truth limit,
 * and the pane says what it is not showing. */
var NARRATION_SHOWN = 12;

/* Where a word the page prints is explained in s0ma's own dictionary,
 * when the word is not itself one of an entry's names. Ids only: every
 * definition arrives with /api/graph, copied from the teaching slice
 * s0ma-core ships, and no definition is written in this file. Keyed by
 * the role a word plays where it is printed: a layer name (a value of
 * `layer`, such as APPLICATION) and a relation word in a relationship
 * row (such as READS or CALLS). */
var TERM_POINTERS = {
  "layer-name": "concept:layer",
  relation: "concept:axon",
};

/* The three contract lines, pointed at the contract entry. Kept in a
 * constant of their own so they can be removed in one edit once the
 * dictionary carries an entry for each. */
var CONTRACT_FIELD_POINTERS = {
  guarantees: "concept:contract",
  forbids: "concept:contract",
  expects: "concept:contract",
};

/* Every word this page can print in a term position, with the role it
 * plays there. Run through resolveTerm, the list is the dictionary's
 * "On this page" section: what this page can show, whichever graph it
 * happens to be showing. */
var PAGE_TERM_WORDS = [
  ["ganglion", null],
  ["nerve", null],
  ["cell", null],
  ["axon", null],
  ["test", null],
  ["helper", null],
  ["doc_ref", null],
  ["doc_guide", null],
  ["example", null],
  ["module", null],
  ["layer", null],
  ["APPLICATION", "layer-name"],
  ["intent", null],
  ["guarantees", null],
  ["forbids", null],
  ["expects", null],
  ["schema", null],
  ["invariants", null],
  ["value", null],
  ["covered_by", null],
  ["uses", null],
  ["requires", null],
  ["exports", null],
  ["kind", null],
  ["visibility", null],
  ["version", null],
  ["tags", null],
  ["soft_requires", null],
  ["deferred_requires", null],
  ["runtime_only_requires", null],
  ["privileged", null],
  ["READS", "relation"],
];

/* The SVG namespace, read from a probe element instead of a URL
 * literal: no absolute URL of any scheme appears in this file, so the
 * page can be proven self-contained by inspection (FR-STUDI0-7). */
var SVG_NS = (function () {
  var probe = document.createElement("div");
  probe.innerHTML = "<svg></svg>";
  return probe.firstChild.namespaceURI;
})();

/* ------------------------------------------------------------------ *
 * Session state
 * ------------------------------------------------------------------ */

var state = {
  live: false,
  seq: 0,
  graph: null,
  model: null,
  layout: null,
  /* Null until something has said what the build is: the page infers
   * nothing, so it does not claim "nothing is built" before the server
   * has answered. */
  buildStatus: null,
  /* True from the moment the server answers that nothing is built until
   * a graph arrives. While it holds, the canvas shows the empty bands,
   * and the graph that ends it is diffed against nothing, so every part
   * of the first build arrives with the added-part beat. */
  notBuilt: false,
  staleModules: [],
  toggles: { tests: false, framework: false },
  collapseOverrides: {},
  selection: null,
  viewBox: null,
  fitted: false,
  offline: false,
  offlineDismissed: false,
  error: null,
  /* What the last payload changed. Drives the materialize beat, and is
   * dropped again once the beat is over. */
  delta: emptyDelta(),
  /* True between "a delta arrived" and "the paint that showed it". */
  beatPending: false,
  /* The parts the newest build added, kept outlined after the beat is
   * over (see "The outline that stays"). */
  outlined: {},
  /* The list of changes: one entry per build that added, changed, or
   * removed something since this page opened, newest first. It lives
   * here and nowhere else (see "What changed since you opened this
   * page"). `made` numbers the entries, `dropped` counts the ones past
   * the cap, and `shown` is the toolbar toggle. */
  changes: { entries: [], made: 0, dropped: 0, shown: true },
  /* Sticky layout memory, one entry per module (see organSlotting).
   * Wiped whenever `slotKey` changes, which is the only thing that
   * licenses a full relayout. */
  slots: {},
  slotKey: null,
  defaultCollapsed: false,
  /* What an agent has said it is doing: the bounded window the server
   * serves, how many narrations there have been in all, and how many
   * session-log lines the server read and refused. Self-report, kept
   * out of `graph` and `model` on purpose. */
  narration: { entries: [], total: 0, invalid: 0 },
  /* The ordinal of the newest narration focus sync has already acted
   * on, so an unchanged window never re-steers the canvas. */
  narrationFocused: 0,
  /* Whether the component inspector's two disclosures are open, so a
   * live repaint of the same selection keeps them as the reader left
   * them. A new selection starts with both closed. */
  disclosure: { key: null, more: false, undeclared: false },
  /* s0ma's own definitions of its words, as /api/graph serves them
   * (the terms block), indexed for the resolver. Empty when the server
   * sent none, and then no word on the page is a control. */
  terms: { source: null, entries: [], byId: {}, byName: {} },
  termsText: null,
  /* The one term card open in the inspector: which selection it belongs
   * to and which control opened it, so a repaint of the same selection
   * keeps it open and a new selection closes it. */
  termCard: { selection: null, key: null, more: false },
  /* The dictionary, which shares the right panel with the inspector:
   * whether it is open, which entry is open in it, the selection to go
   * back to, and whether its "more terms" disclosure is open. */
  dictionary: { open: false, entry: null, back: null, rest: false },
  dictionaryCard: { more: false },
};

var ui = {};

/* The two timers this file owns, both of them the beat's own lifecycle
 * and nothing else. */
var beatExpiryTimer = null;
var beatSweepTimer = null;

/* ------------------------------------------------------------------ *
 * Small helpers
 * ------------------------------------------------------------------ */

function r2(value) {
  return Math.round(value * 100) / 100;
}

function el(tag, className, text) {
  var node = document.createElement(tag);
  if (className) {
    node.className = className;
  }
  if (text !== undefined && text !== null) {
    node.textContent = text;
  }
  return node;
}

function svgEl(tag, attrs) {
  var node = document.createElementNS(SVG_NS, tag);
  if (attrs) {
    for (var key in attrs) {
      if (Object.prototype.hasOwnProperty.call(attrs, key)) {
        node.setAttribute(key, String(attrs[key]));
      }
    }
  }
  return node;
}

function svgText(x, y, className, text, attrs) {
  var node = svgEl("text", attrs || {});
  node.setAttribute("x", String(r2(x)));
  node.setAttribute("y", String(r2(y)));
  if (className) {
    node.setAttribute("class", className);
  }
  node.textContent = text;
  return node;
}

function clear(node) {
  while (node.firstChild) {
    node.removeChild(node.firstChild);
  }
}

function shortName(canonicalId) {
  var marker = canonicalId.indexOf("::");
  return marker === -1 ? canonicalId : canonicalId.slice(marker + 2);
}

function middleTruncate(text, max) {
  if (text.length <= max) {
    return text;
  }
  var keep = max - 1;
  var head = Math.ceil(keep / 2);
  var tail = keep - head;
  return text.slice(0, head) + "…" + text.slice(text.length - tail);
}

/* Deterministic width estimate: layout must never depend on how a
 * particular browser measures a particular font. */
function estimateTextWidth(text, pxPerChar) {
  return text.length * pxPerChar;
}

function declarationRank(declarationType) {
  var index = DECLARATION_ORDER.indexOf(declarationType);
  return index === -1 ? DECLARATION_ORDER.length : index;
}

function compareStrings(a, b) {
  if (a < b) {
    return -1;
  }
  return a > b ? 1 : 0;
}

/* Element-wise list equality. Deliberately not a join-and-compare: any
 * separator is a guess about what the strings cannot contain, and this
 * question ("did the stale set change?") deserves an answer that does
 * not rest on a guess. */
function sameStringList(a, b) {
  if (a.length !== b.length) {
    return false;
  }
  for (var i = 0; i < a.length; i += 1) {
    if (a[i] !== b[i]) {
      return false;
    }
  }
  return true;
}

function hasKeys(map) {
  for (var key in map) {
    if (Object.prototype.hasOwnProperty.call(map, key)) {
      return true;
    }
  }
  return false;
}

/* ------------------------------------------------------------------ *
 * State-wrapper projection (plan §3.2 "As implemented")
 * ------------------------------------------------------------------ */

/* Projects one IR leaf for display:
 *   {state: "value", value: X}      -> {kind: "value", value: X}
 *   {state: "none"}                 -> {kind: "none"}
 *   {state: "pending", reason: R}   -> {kind: "pending", reason: R}
 *   anything else (a plain scalar,
 *   list or map the IR carries
 *   without a wrapper)              -> {kind: "value", value: it}
 * A missing key is "none": the field was not declared. */
function projectValue(raw) {
  if (raw === undefined || raw === null) {
    return { kind: "none" };
  }
  if (
    typeof raw === "object" &&
    !Array.isArray(raw) &&
    typeof raw.state === "string"
  ) {
    if (raw.state === "value") {
      return { kind: "value", value: raw.value };
    }
    if (raw.state === "none") {
      return { kind: "none" };
    }
    if (raw.state === "pending") {
      return { kind: "pending", reason: raw.reason };
    }
  }
  return { kind: "value", value: raw };
}

/* One-line projection for tooltips and other single-string surfaces. */
function projectToLine(raw, absentText) {
  var projected = projectValue(raw);
  if (projected.kind === "none") {
    return absentText;
  }
  if (projected.kind === "pending") {
    return "pending: " + valueToLine(projected.reason);
  }
  return valueToLine(projected.value);
}

function valueToLine(value) {
  if (value === undefined || value === null) {
    return "";
  }
  if (Array.isArray(value)) {
    return value.map(valueToLine).join(", ");
  }
  if (typeof value === "object") {
    var parts = [];
    var keys = Object.keys(value).sort(compareStrings);
    for (var i = 0; i < keys.length; i += 1) {
      parts.push(keys[i] + ": " + valueToLine(value[keys[i]]));
    }
    return parts.join("; ");
  }
  return String(value);
}

/* ------------------------------------------------------------------ *
 * Model
 * ------------------------------------------------------------------ */

function buildModel(graph) {
  var components = graph && graph.components ? graph.components : {};
  var rawModules = graph && graph.modules ? graph.modules : [];
  var rawEdges = graph && graph.edges ? graph.edges : {};

  var modules = {};
  var moduleNames = [];
  var i;

  for (i = 0; i < rawModules.length; i += 1) {
    var entry = rawModules[i];
    modules[entry.name] = entry;
    moduleNames.push(entry.name);
  }

  var componentIds = Object.keys(components).sort(compareStrings);

  /* A component whose module is missing from `modules` still belongs
   * somewhere: fall back to a module record built from what the
   * component itself declares. Nothing is invented — the module name
   * and layer are the component's own. */
  for (i = 0; i < componentIds.length; i += 1) {
    var component = components[componentIds[i]];
    var moduleName = component.module;
    if (moduleName && !modules[moduleName]) {
      modules[moduleName] = {
        name: moduleName,
        layer: component.layer,
        intent: null,
        components: [],
      };
      moduleNames.push(moduleName);
    }
  }
  moduleNames.sort(compareStrings);

  var edges = [];
  var families = ["authored", "derived", "verification"];
  for (i = 0; i < families.length; i += 1) {
    var family = families[i];
    var list = rawEdges[family] || [];
    for (var j = 0; j < list.length; j += 1) {
      var raw = list[j];
      var source = family === "verification" ? raw.test : raw.source;
      var target = family === "verification" ? raw.validates : raw.target;
      edges.push({
        family: family,
        source: source,
        target: target,
        relation: raw.relation || null,
        origin: raw.origin || null,
        carries: raw.carries,
        coupling: raw.coupling,
        intent: raw.intent,
        index: edges.length,
      });
    }
  }

  var integrations = graph && graph.integrations ? graph.integrations : [];
  var integrationsByModule = {};
  var integrationsById = {};
  for (i = 0; i < integrations.length; i += 1) {
    var integration = integrations[i];
    var owner = integration.module || "";
    if (!integrationsByModule[owner]) {
      integrationsByModule[owner] = [];
    }
    integrationsByModule[owner].push(integration);
    integrationsById[integration.canonical_id] = integration;
  }

  var freshness = graph ? graph.freshness : null;

  return {
    components: components,
    componentIds: componentIds,
    modules: modules,
    moduleNames: moduleNames,
    edges: edges,
    integrations: integrations,
    integrationsByModule: integrationsByModule,
    integrationsById: integrationsById,
    freshness: freshness || null,
  };
}

function deriveStateFromGraph(graph) {
  var freshness = graph ? graph.freshness : null;
  if (!freshness || !freshness.status) {
    return { build_status: "missing", stale_modules: [] };
  }
  return {
    build_status: freshness.status,
    stale_modules: freshness.stale_modules || [],
  };
}

function isStaleModule(moduleName) {
  return state.staleModules.indexOf(moduleName) !== -1;
}

/* ------------------------------------------------------------------ *
 * Visibility
 * ------------------------------------------------------------------ */

function isComponentVisible(component) {
  if (TEST_AND_DOC_TYPES[component.declaration_type] && !state.toggles.tests) {
    return false;
  }
  if (component.layer === "FRAMEWORK" && !state.toggles.framework) {
    return false;
  }
  return true;
}

function isModuleVisible(moduleName) {
  var module = state.model.modules[moduleName];
  if (module && module.layer === "FRAMEWORK" && !state.toggles.framework) {
    return false;
  }
  return true;
}

/* ------------------------------------------------------------------ *
 * Layout (deterministic; no physics, no measurement)
 * ------------------------------------------------------------------ */

function computeLayout() {
  var model = state.model;
  var visible = {};
  var visibleIds = [];
  var i;
  var j;

  for (i = 0; i < model.componentIds.length; i += 1) {
    var id = model.componentIds[i];
    var component = model.components[id];
    if (isComponentVisible(component) && isModuleVisible(component.module)) {
      visible[id] = true;
      visibleIds.push(id);
    }
  }

  /* A toggle changes which question the view is answering, so it earns
   * a fresh deterministic layout. A delta does not. */
  var key = slotKey();
  var firstLayout = state.slotKey !== key;
  if (firstLayout) {
    state.slots = {};
    state.slotKey = key;
    state.defaultCollapsed = visibleIds.length > COLLAPSE_THRESHOLD;
  }
  /* Held from the first layout: a build that pushes the node count past
   * the collapse threshold must not fold the whole view up under the
   * reader. Expand-all and collapse-all remain the way to change it. */
  var defaultCollapsed = state.defaultCollapsed;

  /* Group visible components by module, in (declaration type, name)
   * order — the order the grid fills. */
  var byModule = {};
  for (i = 0; i < visibleIds.length; i += 1) {
    var component2 = model.components[visibleIds[i]];
    var moduleName = component2.module || "";
    if (!byModule[moduleName]) {
      byModule[moduleName] = [];
    }
    byModule[moduleName].push(component2);
  }
  for (var name in byModule) {
    if (Object.prototype.hasOwnProperty.call(byModule, name)) {
      byModule[name].sort(function (a, b) {
        var rank = declarationRank(a.declaration_type) -
          declarationRank(b.declaration_type);
        if (rank !== 0) {
          return rank;
        }
        return compareStrings(a.canonical_id, b.canonical_id);
      });
    }
  }

  /* Bands: only layers that actually hold a visible module. */
  var modulesByLayer = {};
  var presentModules = Object.keys(byModule).sort(compareStrings);
  for (i = 0; i < presentModules.length; i += 1) {
    var moduleRecord = model.modules[presentModules[i]];
    var layer = (moduleRecord && moduleRecord.layer) || "FRAMEWORK";
    if (!modulesByLayer[layer]) {
      modulesByLayer[layer] = [];
    }
    modulesByLayer[layer].push(presentModules[i]);
  }

  var organs = [];
  var organsByModule = {};
  var nodesById = {};
  var bands = [];
  var y = 0;
  var maxRight = 0;

  for (i = 0; i < LAYER_ORDER.length; i += 1) {
    var bandLayer = LAYER_ORDER[i];
    var bandModules = modulesByLayer[bandLayer];
    if (!bandModules || bandModules.length === 0) {
      continue;
    }
    bandModules = orderModulesInBand(bandModules, visible);

    var bandTop = y;
    var cursorX = CONTENT_X;
    var rowTop = bandTop + BAND_PAD_TOP;
    var rowHeight = 0;

    for (j = 0; j < bandModules.length; j += 1) {
      var organModule = bandModules[j];
      var members = byModule[organModule];
      var slotting = organSlotting(organModule, members);
      var collapsed = organCollapsed(organModule, defaultCollapsed);
      var geometry = organGeometry(organModule, slotting, members.length, collapsed);

      if (
        cursorX > CONTENT_X &&
        cursorX + geometry.width > CONTENT_X + BAND_MAX_WIDTH
      ) {
        cursorX = CONTENT_X;
        rowTop = rowTop + rowHeight + ORGAN_GAP_Y;
        rowHeight = 0;
      }

      var organ = {
        module: organModule,
        layer: bandLayer,
        collapsed: collapsed,
        stale: isStaleModule(organModule),
        members: members,
        integrations: model.integrationsByModule[organModule] || [],
        x: cursorX,
        y: rowTop,
        width: geometry.width,
        height: geometry.height,
        cols: geometry.cols,
        rows: geometry.rows,
        nodes: [],
      };
      organ.headerBox = {
        x: organ.x,
        y: organ.y,
        w: organ.width,
        h: ORGAN_HEADER_H,
      };

      if (!collapsed) {
        /* Slot -> cell. The offset is frozen with the organ's first
         * layout, so a header that grows a chip widens the box to the
         * right and leaves every node exactly where it was. */
        var gridLeft = organ.x + slotting.offsetX;
        var gridTop = organ.y + ORGAN_HEADER_H + ORGAN_PAD_TOP;
        for (var k = 0; k < members.length; k += 1) {
          var slot = slotting.index[members[k].canonical_id];
          var col = slot % slotting.cols;
          var row = Math.floor(slot / slotting.cols);
          var node = {
            id: members[k].canonical_id,
            component: members[k],
            organ: organ,
            slot: slot,
            x: gridLeft + col * (NODE_W + NODE_GAP_X),
            y: gridTop + row * (NODE_H + NODE_GAP_Y),
            w: NODE_W,
            h: NODE_H,
          };
          organ.nodes.push(node);
          nodesById[node.id] = node;
        }
      }

      organs.push(organ);
      organsByModule[organModule] = organ;
      cursorX = cursorX + geometry.width + ORGAN_GAP_X;
      rowHeight = Math.max(rowHeight, geometry.height);
      maxRight = Math.max(maxRight, organ.x + organ.width);
    }

    var bandBottom = rowTop + rowHeight + BAND_PAD_BOTTOM;
    bands.push({
      layer: bandLayer,
      y: bandTop,
      height: bandBottom - bandTop,
    });
    y = bandBottom + BAND_GAP_Y;
  }

  var width = Math.max(maxRight + CONTENT_X, CONTENT_X * 2 + ORGAN_MIN_W);
  var height = Math.max(y - BAND_GAP_Y, 1);
  for (i = 0; i < bands.length; i += 1) {
    bands[i].width = width;
  }

  var layout = {
    bands: bands,
    organs: organs,
    organsByModule: organsByModule,
    nodesById: nodesById,
    visible: visible,
    visibleCount: visibleIds.length,
    width: width,
    height: height,
    defaultCollapsed: defaultCollapsed,
  };
  layout.edgeGroups = computeEdgeGroups(layout);
  return layout;
}

/* The layout of a project with nothing built: every standard band, in
 * the usual order and with the usual names, holding nothing. The
 * FRAMEWORK band follows its toolbar toggle, as it does with a graph. */
function emptyLayout() {
  var width = CONTENT_X * 2 + ORGAN_MIN_W * 3 + ORGAN_GAP_X * 2;
  var bands = [];
  var y = 0;
  for (var i = 0; i < LAYER_ORDER.length; i += 1) {
    if (LAYER_ORDER[i] === "FRAMEWORK" && !state.toggles.framework) {
      continue;
    }
    bands.push({
      layer: LAYER_ORDER[i],
      y: y,
      height: EMPTY_BAND_H,
      width: width,
    });
    y = y + EMPTY_BAND_H + BAND_GAP_Y;
  }
  return {
    bands: bands,
    organs: [],
    organsByModule: {},
    nodesById: {},
    visible: {},
    visibleCount: 0,
    width: width,
    height: Math.max(y - BAND_GAP_Y, 1),
    defaultCollapsed: false,
    edgeGroups: [],
  };
}

function organCollapsed(moduleName, defaultCollapsed) {
  if (
    Object.prototype.hasOwnProperty.call(state.collapseOverrides, moduleName)
  ) {
    return state.collapseOverrides[moduleName];
  }
  return defaultCollapsed;
}

/* The identity of the current visibility question. The sticky slot map
 * belongs to one answer of it; a different answer starts over. */
function slotKey() {
  return (
    (state.toggles.tests ? "tests" : "-") +
    "/" +
    (state.toggles.framework ? "framework" : "-")
  );
}

/* The sticky grid of one organ: how many columns it has, which slot
 * each component sits in, and how many slots it has ever handed out.
 *
 * First time through, this is exactly the pure layout M4 specified —
 * ceil(sqrt(n)) columns, members filling slots 0..n-1 in (declaration
 * type, name) order. From then on it only ever grows: a component new
 * to the payload takes the next never-used slot (the organ grows
 * downward), and a component that leaves takes its slot out of use for
 * the rest of the session rather than letting its neighbours slide up
 * into the gap. Neither event moves anything already on screen, which
 * is the whole point (plan §4 M5.T2, scope §3.2). */
function organSlotting(moduleName, members) {
  var memory = state.slots[moduleName];
  var i;
  if (!memory) {
    memory = {
      cols: Math.max(1, Math.ceil(Math.sqrt(members.length))),
      index: {},
      capacity: 0,
      /* Both settle on the organ's first layout (see organGeometry). */
      offsetX: null,
      width: 0,
    };
    state.slots[moduleName] = memory;
  }
  for (i = 0; i < members.length; i += 1) {
    var id = members[i].canonical_id;
    if (memory.index[id] === undefined) {
      memory.index[id] = memory.capacity;
      memory.capacity += 1;
    }
  }
  return memory;
}

function organGeometry(moduleName, slotting, count, collapsed) {
  var cols = slotting.cols;
  /* Rows are cut for every slot ever handed out, not just the occupied
   * ones: a removal leaves a hole, and an organ that shrank back would
   * drag its whole band up with it. */
  var rows = Math.max(1, Math.ceil(Math.max(slotting.capacity, 1) / cols));
  var gridWidth = cols * NODE_W + (cols - 1) * NODE_GAP_X;

  var headerWidth = Math.max(
    ORGAN_MIN_W,
    headerWidthEstimate(moduleName, count)
  );
  var expandedWidth = Math.max(headerWidth, gridWidth + ORGAN_PAD_X * 2);
  /* Monotonic: "13 components" is a wider header than "9 components",
   * and an organ that breathed in and out with its own label would move
   * every organ to its right on every build. */
  if (expandedWidth > slotting.width) {
    slotting.width = expandedWidth;
  }
  if (slotting.offsetX === null) {
    /* Centre the grid once, against the organ's first width. Later
     * growth is added on the right, so this offset stays true. */
    slotting.offsetX = (slotting.width - gridWidth) / 2;
  }

  /* Collapsed, an organ is only its header, so it may be narrower —
   * collapsing is the reader's own doing, not a delta arriving. */
  var width = collapsed ? headerWidth : slotting.width;

  var height = collapsed
    ? ORGAN_HEADER_H + ORGAN_COLLAPSED_PAD
    : ORGAN_HEADER_H +
      ORGAN_PAD_TOP +
      rows * NODE_H +
      (rows - 1) * NODE_GAP_Y +
      ORGAN_PAD_BOTTOM;

  return { width: width, height: height, cols: cols, rows: rows };
}

function organLayer(moduleName) {
  var module = state.model.modules[moduleName];
  return (module && module.layer) || "";
}

function headerMetaText(count) {
  return count === 1 ? "1 component" : count + " components";
}

/* Chip text is 9.5px and can be uppercase and letter-spaced (a layer
 * name) or lowercase (a stale marker), so a single per-character
 * average is not enough to keep text inside its pill. Still a pure
 * estimate — nothing is measured, so the layout stays identical across
 * browsers and font stacks. */
function chipTextWidth(text) {
  var width = 0;
  for (var i = 0; i < text.length; i += 1) {
    var ch = text.charAt(i);
    if (ch >= "A" && ch <= "Z") {
      width += 7.2;
    } else if (ch === " " || ch === ":" || ch === "." || ch === "_") {
      width += 3.4;
    } else {
      width += 5.6;
    }
  }
  return width;
}

function chipWidth(text) {
  return chipTextWidth(text) + 14;
}

function integrationChipTexts(moduleName) {
  var integrations = state.model.integrationsByModule[moduleName] || [];
  var texts = [];
  for (var i = 0; i < integrations.length && i < 2; i += 1) {
    texts.push("integration: " + integrations[i].name);
  }
  return texts;
}

/* Header width is estimated, never measured: layout must not change
 * with the browser's font metrics. Every chip that will be drawn is
 * counted here so a header never runs past its organ. */
function headerWidthEstimate(moduleName, count) {
  var width =
    ORGAN_PAD_X * 2 +
    14 +
    estimateTextWidth(moduleName, 7.6) +
    12 +
    chipWidth(organLayer(moduleName)) +
    8 +
    estimateTextWidth(headerMetaText(count), 6.3) +
    12;
  var integrations = integrationChipTexts(moduleName);
  for (var i = 0; i < integrations.length; i += 1) {
    width += chipWidth(integrations[i]) + 6;
  }
  if (isStaleModule(moduleName)) {
    width += chipWidth("stale") + 6 + 18;
  }
  return width;
}

/* Within a band, order modules so dependencies sit to the right:
 * a topological order over the aggregated inter-module edges, with
 * name-ascending tie-breaks (and a name-ascending choice when a cycle
 * leaves nothing with an empty in-edge set). */
function orderModulesInBand(moduleNames, visible) {
  var names = moduleNames.slice().sort(compareStrings);
  var inBand = {};
  var i;
  for (i = 0; i < names.length; i += 1) {
    inBand[names[i]] = true;
  }

  var dependsOn = {};
  var indegree = {};
  for (i = 0; i < names.length; i += 1) {
    dependsOn[names[i]] = {};
    indegree[names[i]] = 0;
  }

  var edges = state.model.edges;
  for (i = 0; i < edges.length; i += 1) {
    var edge = edges[i];
    /* Verification edges are evidence, not dependency direction, so
     * module order does not shift when the tests toggle changes. */
    if (edge.family === "verification") {
      continue;
    }
    if (!visible[edge.source] || !visible[edge.target]) {
      continue;
    }
    var sourceModule = state.model.components[edge.source].module;
    var targetModule = state.model.components[edge.target].module;
    if (sourceModule === targetModule) {
      continue;
    }
    if (!inBand[sourceModule] || !inBand[targetModule]) {
      continue;
    }
    if (!dependsOn[sourceModule][targetModule]) {
      dependsOn[sourceModule][targetModule] = true;
      indegree[targetModule] += 1;
    }
  }

  var remaining = names.slice();
  var ordered = [];
  while (remaining.length > 0) {
    var pick = -1;
    for (i = 0; i < remaining.length; i += 1) {
      if (indegree[remaining[i]] === 0) {
        pick = i;
        break;
      }
    }
    if (pick === -1) {
      pick = 0; /* cycle: fall back to the name-ascending choice */
    }
    var chosen = remaining.splice(pick, 1)[0];
    ordered.push(chosen);
    var targets = Object.keys(dependsOn[chosen]).sort(compareStrings);
    for (i = 0; i < targets.length; i += 1) {
      if (indegree[targets[i]] !== undefined) {
        indegree[targets[i]] -= 1;
      }
    }
  }
  return ordered;
}

/* ------------------------------------------------------------------ *
 * Edge routing
 * ------------------------------------------------------------------ */

function anchorFor(layout, canonicalId) {
  if (!layout.visible[canonicalId]) {
    /* Hidden by a filter, not by collapse: the edge has nowhere
     * honest to land, so it is not drawn. The inspector still lists
     * it. */
    return null;
  }
  var node = layout.nodesById[canonicalId];
  if (node) {
    return {
      key: "n:" + canonicalId,
      box: { x: node.x, y: node.y, w: node.w, h: node.h },
    };
  }
  var component = state.model.components[canonicalId];
  if (!component) {
    return null;
  }
  var organ = layout.organsByModule[component.module];
  if (!organ) {
    return null;
  }
  return { key: "o:" + organ.module, box: organ.headerBox };
}

function computeEdgeGroups(layout) {
  var groups = [];
  var byKey = {};
  var edges = state.model.edges;
  for (var i = 0; i < edges.length; i += 1) {
    var edge = edges[i];
    if (edge.family === "verification" && !state.toggles.tests) {
      continue;
    }
    var from = anchorFor(layout, edge.source);
    var to = anchorFor(layout, edge.target);
    if (!from || !to || from.key === to.key) {
      continue;
    }
    var key = edge.family + "|" + from.key + "|" + to.key;
    var group = byKey[key];
    if (!group) {
      group = {
        key: key,
        family: edge.family,
        from: from,
        to: to,
        edges: [],
        aggregated: from.key.charAt(0) === "o" || to.key.charAt(0) === "o",
      };
      byKey[key] = group;
      groups.push(group);
    }
    group.edges.push(edge);
  }
  for (var j = 0; j < groups.length; j += 1) {
    groups[j].geometry = edgeGeometry(groups[j].from.box, groups[j].to.box);
  }
  return groups;
}

function edgeGeometry(a, b) {
  var ac = { x: a.x + a.w / 2, y: a.y + a.h / 2 };
  var bc = { x: b.x + b.w / 2, y: b.y + b.h / 2 };
  var dx = bc.x - ac.x;
  var dy = bc.y - ac.y;
  var p1;
  var p2;
  var c1;
  var c2;

  if (Math.abs(dx) >= Math.abs(dy)) {
    p1 = { x: dx >= 0 ? a.x + a.w : a.x, y: ac.y };
    p2 = { x: dx >= 0 ? b.x : b.x + b.w, y: bc.y };
    var kx = Math.max(28, Math.min(150, Math.abs(p2.x - p1.x) * 0.42));
    c1 = { x: p1.x + (dx >= 0 ? kx : -kx), y: p1.y };
    c2 = { x: p2.x - (dx >= 0 ? kx : -kx), y: p2.y };
  } else {
    p1 = { x: ac.x, y: dy >= 0 ? a.y + a.h : a.y };
    p2 = { x: bc.x, y: dy >= 0 ? b.y : b.y + b.h };
    var ky = Math.max(24, Math.min(130, Math.abs(p2.y - p1.y) * 0.42));
    c1 = { x: p1.x, y: p1.y + (dy >= 0 ? ky : -ky) };
    c2 = { x: p2.x, y: p2.y - (dy >= 0 ? ky : -ky) };
  }

  var d =
    "M " +
    r2(p1.x) +
    " " +
    r2(p1.y) +
    " C " +
    r2(c1.x) +
    " " +
    r2(c1.y) +
    ", " +
    r2(c2.x) +
    " " +
    r2(c2.y) +
    ", " +
    r2(p2.x) +
    " " +
    r2(p2.y);

  return { d: d, mid: cubicPoint(p1, c1, c2, p2, 0.5) };
}

function cubicPoint(p0, p1, p2, p3, t) {
  var mt = 1 - t;
  var a = mt * mt * mt;
  var b = 3 * mt * mt * t;
  var c = 3 * mt * t * t;
  var d = t * t * t;
  return {
    x: a * p0.x + b * p1.x + c * p2.x + d * p3.x,
    y: a * p0.y + b * p1.y + c * p2.y + d * p3.y,
  };
}

/* ------------------------------------------------------------------ *
 * Shell
 * ------------------------------------------------------------------ */

function buildShell(mount) {
  clear(mount);
  var root = el("div", "sh0w");

  var topbar = el("header", "topbar");
  var brand = el("div", "brand");
  brand.appendChild(el("span", "brand-mark", "s0ma studi0"));
  brand.appendChild(
    el("span", "brand-sub", "sh0w — canonical component graph")
  );
  topbar.appendChild(brand);

  var toolbar = el("div", "toolbar");
  toolbar.setAttribute("role", "toolbar");
  toolbar.setAttribute("aria-label", "view controls");

  ui.toggleTests = toolbarButton("tests and docs", function () {
    state.toggles.tests = !state.toggles.tests;
    render();
  });
  ui.toggleTests.setAttribute("aria-pressed", "false");
  ui.toggleTests.title =
    "show test, helper and doc declarations, and draw verification edges";

  ui.toggleFramework = toolbarButton("framework layer", function () {
    state.toggles.framework = !state.toggles.framework;
    render();
  });
  ui.toggleFramework.setAttribute("aria-pressed", "false");
  ui.toggleFramework.title = "show FRAMEWORK-layer modules";

  toolbar.appendChild(ui.toggleTests);
  toolbar.appendChild(ui.toggleFramework);
  toolbar.appendChild(el("span", "toolbar-sep"));
  toolbar.appendChild(
    toolbarButton("expand all", function () {
      setAllCollapsed(false);
    })
  );
  toolbar.appendChild(
    toolbarButton("collapse all", function () {
      setAllCollapsed(true);
    })
  );
  toolbar.appendChild(el("span", "toolbar-sep"));

  var zoomOut = toolbarButton("−", function () {
    zoomBy(1 / 0.8);
  });
  zoomOut.className = "btn btn--icon";
  zoomOut.setAttribute("aria-label", "zoom out");
  zoomOut.title = "zoom out (-)";
  var zoomIn = toolbarButton("+", function () {
    zoomBy(0.8);
  });
  zoomIn.className = "btn btn--icon";
  zoomIn.setAttribute("aria-label", "zoom in");
  zoomIn.title = "zoom in (+)";
  var fit = toolbarButton("fit", function () {
    fitToView();
  });
  fit.title = "fit the whole graph in view (f)";

  toolbar.appendChild(zoomOut);
  toolbar.appendChild(zoomIn);
  toolbar.appendChild(fit);

  toolbar.appendChild(el("span", "toolbar-sep"));

  /* A real toggle for the list of changes, pressed by default. */
  ui.changesButton = toolbarButton("changes", toggleChanges);
  ui.changesButton.setAttribute("aria-pressed", "true");
  ui.changesButton.title =
    "the builds that landed since this page opened, and what each changed";
  toolbar.appendChild(ui.changesButton);

  /* Hidden until /api/graph brings s0ma's definitions: with none, there
   * is no dictionary to open and the toolbar reads as it always has. */
  ui.termsButton = toolbarButton("terms", toggleDictionary);
  ui.termsButton.setAttribute("aria-pressed", "false");
  ui.termsButton.title = "s0ma's own definitions of the words on this page";
  ui.termsButton.hidden = true;
  toolbar.appendChild(ui.termsButton);
  topbar.appendChild(toolbar);
  root.appendChild(topbar);

  ui.banners = el("div", "banners");
  root.appendChild(ui.banners);

  ui.stage = el("main", "stage");

  /* The left column, first in the stage so Tab reaches it before the
   * graph: the list of changes on top, narration under it. */
  ui.sideColumn = el("div", "side-column");
  ui.stage.appendChild(ui.sideColumn);
  buildChangesPane(ui.sideColumn);

  /* Hidden until something has actually been narrated: an empty pane
   * would be a claim that nothing is happening, which is not the same
   * as nobody saying anything. */
  ui.narration = el("aside", "narration");
  ui.narration.setAttribute("aria-label", "agent narration (self-reported)");
  ui.narration.setAttribute("tabindex", "-1");
  ui.narration.hidden = true;
  ui.sideColumn.appendChild(ui.narration);

  ui.canvasWrap = el("div", "canvas-wrap");
  ui.canvas = svgEl("svg", {
    class: "canvas",
    preserveAspectRatio: "xMidYMid meet",
    role: "application",
    "aria-label": "component graph",
  });
  ui.canvas.appendChild(buildDefs());
  ui.viewport = svgEl("g", { class: "viewport" });
  ui.layerBands = svgEl("g", { class: "layer-bands" });
  ui.layerOrgans = svgEl("g", { class: "layer-organs" });
  ui.layerEdges = svgEl("g", { class: "layer-edges" });
  /* Nodes on their way out live here for the length of their fade:
   * they have already left the model, so they must not sit in the
   * layer the next paint rebuilds. */
  ui.layerGhosts = svgEl("g", { class: "layer-ghosts" });
  ui.layerNodes = svgEl("g", { class: "layer-nodes" });
  ui.viewport.appendChild(ui.layerBands);
  ui.viewport.appendChild(ui.layerOrgans);
  ui.viewport.appendChild(ui.layerEdges);
  ui.viewport.appendChild(ui.layerGhosts);
  ui.viewport.appendChild(ui.layerNodes);
  ui.canvas.appendChild(ui.viewport);
  ui.canvasWrap.appendChild(ui.canvas);
  ui.legendTerms = [];
  ui.canvasWrap.appendChild(buildLegend());
  ui.statusLine = el("div", "status-line");
  ui.statusLine.hidden = true;
  ui.canvasWrap.appendChild(ui.statusLine);
  /* Shown over the empty bands once the server has said nothing is
   * built: one plain sentence, and the command in the monospace face. */
  ui.emptyState = el("div", "empty-state");
  ui.emptyState.setAttribute("role", "status");
  ui.emptyState.appendChild(
    el(
      "p",
      "empty-sentence",
      "Nothing is built yet. Parts appear here when the first build lands."
    )
  );
  ui.emptyState.appendChild(
    el("code", "empty-command", "s0ma build <project root>")
  );
  ui.emptyState.hidden = true;
  ui.canvasWrap.appendChild(ui.emptyState);
  ui.stage.appendChild(ui.canvasWrap);

  ui.inspector = el("aside", "inspector");
  ui.inspector.setAttribute("aria-label", "inspector");
  ui.inspector.setAttribute("tabindex", "-1");
  ui.inspector.hidden = true;
  ui.stage.appendChild(ui.inspector);

  root.appendChild(ui.stage);
  mount.appendChild(root);
  ui.root = root;

  attachCanvasInteraction();
  document.addEventListener("keydown", onDocumentKeyDown);
}

function toolbarButton(label, handler) {
  var button = el("button", "btn", label);
  button.type = "button";
  button.addEventListener("click", handler);
  return button;
}

function buildDefs() {
  var defs = svgEl("defs");
  var families = ["authored", "derived", "verification"];
  for (var i = 0; i < families.length; i += 1) {
    var marker = svgEl("marker", {
      id: "sh0w-arrow-" + families[i],
      markerWidth: 7,
      markerHeight: 7,
      refX: 6.2,
      refY: 3,
      orient: "auto",
      markerUnits: "userSpaceOnUse",
    });
    marker.appendChild(
      svgEl("path", {
        class: "edge-arrow",
        d: "M 0 0 L 7 3 L 0 6 z",
        fill: "#8f98a3",
      })
    );
    defs.appendChild(marker);
  }
  return defs;
}

function buildLegend() {
  var legend = el("div", "legend");
  var shapes = el("div", "legend-row");
  var glyphs = [
    ["ganglion", "ganglion"],
    ["nerve", "nerve"],
    ["cell", "cell"],
    ["axon", "axon"],
    ["test", "test"],
  ];
  for (var i = 0; i < glyphs.length; i += 1) {
    var item = el("span", "legend-item");
    var swatch = svgEl("svg", { class: "legend-swatch", viewBox: "0 0 20 20" });
    swatch.appendChild(glyphShape(glyphs[i][0], 10, 10, 0.42));
    item.appendChild(swatch);
    var glyphName = el("span", null, glyphs[i][1]);
    item.appendChild(glyphName);
    ui.legendTerms.push({ item: item, node: glyphName, word: glyphs[i][1], entryId: null });
    shapes.appendChild(item);
  }
  legend.appendChild(shapes);

  var lines = el("div", "legend-row");
  var styles = [
    ["authored", "authored"],
    ["derived", "derived"],
    ["verification", "verification"],
  ];
  for (var j = 0; j < styles.length; j += 1) {
    var lineItem = el("span", "legend-item");
    var lineSwatch = svgEl("svg", {
      class: "legend-swatch",
      viewBox: "0 0 20 20",
    });
    var group = svgEl("g", { class: "edge edge--" + styles[j][0] });
    group.appendChild(
      svgEl("path", { class: "edge-line", d: "M 1 10 L 19 10" })
    );
    lineSwatch.appendChild(group);
    lineItem.appendChild(lineSwatch);
    lineItem.appendChild(el("span", null, styles[j][1]));
    lines.appendChild(lineItem);
  }
  legend.appendChild(lines);
  return legend;
}

/* ------------------------------------------------------------------ *
 * Render
 * ------------------------------------------------------------------ */

function render() {
  if (!ui.root) {
    return;
  }
  ui.toggleTests.setAttribute("aria-pressed", String(state.toggles.tests));
  ui.toggleFramework.setAttribute(
    "aria-pressed",
    String(state.toggles.framework)
  );

  renderBanners();
  renderChanges();

  if (state.buildStatus === "missing" || !state.model) {
    /* There is no graph to beat on. Drop the delta rather than let it
     * wait for a paint that would replay it out of its moment. */
    state.beatPending = false;
    state.delta = emptyDelta();
    renderEmptyState();
    return;
  }
  ui.emptyState.hidden = true;

  state.layout = computeLayout();
  dropSelectionOfVanishedEdge();
  renderBands(state.layout);
  renderOrgans(state.layout);
  renderEdges(state.layout);
  if (state.beatPending) {
    /* Rescue the departing nodes before the layer they live in is
     * rebuilt without them. */
    harvestGhosts();
  }
  renderNodes(state.layout);
  renderStatusLine(state.layout);

  if (!state.fitted) {
    fitToView();
    state.fitted = true;
  } else {
    applyViewBox();
  }
  applySelection();

  if (state.beatPending) {
    state.beatPending = false;
    scheduleBeatEnd();
  }
}

/* A toggle can remove the very edge the inspector is describing (the
 * verification family disappears with the tests toggle). Rather than
 * leave a panel describing something no longer on the canvas, close
 * it. A hidden NODE keeps its panel: the component still exists, it is
 * only filtered out of the drawing. */
function dropSelectionOfVanishedEdge() {
  if (!state.selection || state.selection.type !== "edge") {
    return;
  }
  var groups = state.layout.edgeGroups;
  for (var i = 0; i < groups.length; i += 1) {
    if (groups[i].key === state.selection.key) {
      return;
    }
  }
  state.selection = null;
  ui.inspector.hidden = true;
  clear(ui.inspector);
}

function renderBanners() {
  clear(ui.banners);

  if (state.error) {
    var errorBanner = el("div", "banner banner--offline");
    errorBanner.setAttribute("role", "status");
    errorBanner.appendChild(el("span", "chip", "error"));
    errorBanner.appendChild(el("span", "banner-text", state.error));
    ui.banners.appendChild(errorBanner);
  }

  if (state.offline && !state.offlineDismissed) {
    var offline = el("div", "banner banner--offline");
    offline.setAttribute("role", "status");
    offline.appendChild(el("span", "chip", "offline"));
    offline.appendChild(
      el(
        "span",
        "banner-text",
        "viewer disconnected — relaunch with s0ma studi0"
      )
    );
    var dismiss = el("button", "btn banner-dismiss", "dismiss");
    dismiss.type = "button";
    dismiss.addEventListener("click", function () {
      state.offlineDismissed = true;
      renderBanners();
    });
    offline.appendChild(dismiss);
    ui.banners.appendChild(offline);
  }

  if (state.buildStatus === "stale" && state.staleModules.length > 0) {
    var stale = el("div", "banner banner--stale");
    stale.setAttribute("role", "status");
    stale.appendChild(el("span", "chip chip--stale", "stale"));
    var text = el("span", "banner-text");
    text.appendChild(
      el("span", "banner-modules", state.staleModules.join(", "))
    );
    text.appendChild(
      document.createTextNode(
        (state.staleModules.length === 1 ? " has" : " have") +
          " changed since the last build — " +
          "showing last canonical build — run s0ma build to refresh"
      )
    );
    stale.appendChild(text);
    ui.banners.appendChild(stale);
  }
}

/* No graph on the page. Before anything has said what the build is, the
 * canvas stays blank. Once it has been said that nothing is built, the
 * canvas draws the standard bands, empty, with the sentence and the
 * command over them, and the status line says the same in words. The
 * next graph is fitted afresh, since these bands are not its layout. */
function renderEmptyState() {
  clear(ui.layerOrgans);
  clear(ui.layerEdges);
  clear(ui.layerGhosts);
  clear(ui.layerNodes);
  state.fitted = false;
  if (state.buildStatus !== "missing") {
    clear(ui.layerBands);
    state.layout = null;
    ui.emptyState.hidden = true;
    ui.statusLine.hidden = true;
    return;
  }
  state.layout = emptyLayout();
  renderBands(state.layout);
  fitToView();
  ui.emptyState.hidden = false;
  ui.statusLine.textContent = "nothing is built yet";
  ui.statusLine.hidden = false;
}

function renderBands(layout) {
  clear(ui.layerBands);
  for (var i = 0; i < layout.bands.length; i += 1) {
    var band = layout.bands[i];
    ui.layerBands.appendChild(
      svgEl("rect", {
        class: "band-tint",
        "data-layer": band.layer,
        x: -BAND_BLEED,
        y: r2(band.y),
        width: r2(band.width + BAND_BLEED * 2),
        height: r2(band.height),
      })
    );
    ui.layerBands.appendChild(
      svgText(CONTENT_X, band.y + 26, "band-label", band.layer)
    );
  }
}

function renderOrgans(layout) {
  clear(ui.layerOrgans);
  for (var i = 0; i < layout.organs.length; i += 1) {
    ui.layerOrgans.appendChild(organElement(layout.organs[i]));
  }
}

function organElement(organ) {
  var classes = "organ";
  if (organ.stale) {
    classes += " is-stale";
  }
  var group = svgEl("g", {
    class: classes,
    "data-module": organ.module,
    role: "group",
    "aria-label": organAriaLabel(organ),
  });

  /* A module that has just gone stale gets the ring and nothing else:
   * the chips appear, and no pixel moves. Staleness is a fact about
   * the build, not an event to animate. */
  if (state.delta.stale[organ.module]) {
    group.setAttribute("data-delta", "stale");
    group.appendChild(
      beatRing(organ.x, organ.y, organ.width, organ.height, 14)
    );
  }

  group.appendChild(
    svgEl("rect", {
      class: "organ-body",
      x: r2(organ.x),
      y: r2(organ.y),
      width: r2(organ.width),
      height: r2(organ.height),
      rx: 10,
    })
  );

  if (!organ.collapsed) {
    group.appendChild(
      svgEl("line", {
        class: "organ-header-rule",
        x1: r2(organ.x),
        y1: r2(organ.y + ORGAN_HEADER_H),
        x2: r2(organ.x + organ.width),
        y2: r2(organ.y + ORGAN_HEADER_H),
      })
    );
  }

  if (organ.stale) {
    group.appendChild(staleTriangle(organ.x + organ.width, organ.y, 16));
  }

  var caret = svgText(
    organ.x + ORGAN_PAD_X,
    organ.y + 27,
    "organ-caret",
    organ.collapsed ? "▶" : "▼"
  );
  group.appendChild(caret);

  var nameX = organ.x + ORGAN_PAD_X + 14;
  group.appendChild(svgText(nameX, organ.y + 27, "organ-name", organ.module));

  var chipX = nameX + estimateTextWidth(organ.module, 7.6) + 12;
  var layerChip = svgChip(
    chipX,
    organ.y + 14,
    organLayer(organ.module),
    "svg-chip--layer"
  );
  group.appendChild(layerChip.node);
  chipX += layerChip.width + 8;

  var meta = headerMetaText(organ.members.length);
  group.appendChild(svgText(chipX, organ.y + 27, "organ-meta", meta));
  chipX += estimateTextWidth(meta, 6.3) + 12;

  var i;
  for (i = 0; i < organ.integrations.length && i < 2; i += 1) {
    var integration = organ.integrations[i];
    var chip = svgChip(
      chipX,
      organ.y + 14,
      "integration: " + integration.name,
      "svg-chip--integration"
    );
    chip.node.style.cursor = "pointer";
    bindIntegrationChip(chip.node, integration.canonical_id);
    group.appendChild(chip.node);
    chipX += chip.width + 6;
  }

  if (organ.stale) {
    var staleChip = svgChip(chipX, organ.y + 14, "stale", "svg-chip--stale");
    group.appendChild(staleChip.node);
    chipX += staleChip.width + 6;
  }

  var moduleRecord = state.model.modules[organ.module];
  var title = svgEl("title");
  title.textContent =
    organ.module +
    " — " +
    projectToLine(moduleRecord ? moduleRecord.intent : null, "intent not declared");
  group.appendChild(title);

  return group;
}

/* The header's click/focus target lives in the top layer with the
 * nodes, not in the organ group, so the tab order reads module by
 * module: header, then that module's nodes, then the next header. */
function organHeaderHit(organ) {
  var header = svgEl("rect", {
    class: "organ-header-hit",
    "data-organ-header": organ.module,
    x: r2(organ.x),
    y: r2(organ.y),
    width: r2(organ.width),
    height: ORGAN_HEADER_H,
    rx: 10,
    tabindex: "0",
    role: "button",
    "aria-expanded": String(!organ.collapsed),
    "aria-label":
      (organ.collapsed ? "expand" : "collapse") + " module " + organ.module,
  });
  header.addEventListener("click", function (event) {
    event.stopPropagation();
    toggleOrgan(organ.module);
  });
  header.addEventListener("keydown", function (event) {
    if (event.key === "Enter" || event.key === " ") {
      event.preventDefault();
      event.stopPropagation();
      toggleOrgan(organ.module);
    }
  });
  return header;
}

/* The module's name, as the control that selects the module. It sits
 * over the name only, after the header in the tab order, so the rest of
 * the header and the arrow keep collapsing and expanding the module. */
function organNameHit(organ) {
  var nameX = organ.x + ORGAN_PAD_X + 14;
  var hit = svgEl("rect", {
    class: "organ-name-hit",
    "data-organ-name": organ.module,
    x: r2(nameX - 4),
    y: r2(organ.y + 11),
    width: r2(estimateTextWidth(organ.module, 7.6) + 8),
    height: 22,
    rx: 4,
    tabindex: "0",
    role: "button",
    "aria-label": "inspect module " + organ.module,
  });
  hit.addEventListener("click", function (event) {
    event.stopPropagation();
    select({ type: "module", id: organ.module });
  });
  hit.addEventListener("keydown", function (event) {
    if (event.key === "Enter" || event.key === " ") {
      event.preventDefault();
      event.stopPropagation();
      select({ type: "module", id: organ.module });
    }
  });
  return hit;
}

function organAriaLabel(organ) {
  var parts = [
    "module " + organ.module,
    (state.model.modules[organ.module] || {}).layer || "unknown layer",
    organ.members.length + " components",
    organ.collapsed ? "collapsed" : "expanded",
  ];
  if (organ.stale) {
    parts.push("stale");
  }
  return parts.join(", ");
}

function staleTriangle(rightX, topY, size) {
  return svgEl("path", {
    class: "stale-triangle",
    d:
      "M " +
      r2(rightX - size) +
      " " +
      r2(topY) +
      " L " +
      r2(rightX) +
      " " +
      r2(topY) +
      " L " +
      r2(rightX) +
      " " +
      r2(topY + size) +
      " z",
  });
}

function svgChip(x, y, text, extraClass) {
  var width = chipWidth(text);
  var group = svgEl("g", {
    class: "svg-chip " + (extraClass || ""),
  });
  group.appendChild(
    svgEl("rect", {
      class: "svg-chip-box",
      x: r2(x),
      y: r2(y),
      width: r2(width),
      height: 16,
      rx: 8,
    })
  );
  group.appendChild(svgText(x + 7, y + 11.5, "svg-chip-text", text));
  return { node: group, width: width };
}

function bindIntegrationChip(node, canonicalId) {
  node.addEventListener("click", function (event) {
    event.stopPropagation();
    select({ type: "integration", id: canonicalId });
  });
}

function renderEdges(layout) {
  clear(ui.layerEdges);
  var groups = layout.edgeGroups;
  for (var i = 0; i < groups.length; i += 1) {
    var group = groups[i];
    var node = svgEl("g", {
      class: "edge edge--" + group.family,
      "data-edge": group.key,
    });
    node.appendChild(
      svgEl("path", {
        class: "edge-line",
        d: group.geometry.d,
        "marker-end": "url(#sh0w-arrow-" + group.family + ")",
      })
    );
    var hit = svgEl("path", { class: "edge-hit", d: group.geometry.d });
    node.appendChild(hit);

    var title = svgEl("title");
    title.textContent = edgeSummaryLine(group);
    node.appendChild(title);

    if (group.edges.length > 1) {
      var mid = group.geometry.mid;
      var label = String(group.edges.length);
      var width = estimateTextWidth(label, 6.2) + 12;
      node.appendChild(
        svgEl("rect", {
          class: "edge-count-box",
          x: r2(mid.x - width / 2),
          y: r2(mid.y - 8),
          width: r2(width),
          height: 16,
          rx: 8,
        })
      );
      node.appendChild(
        svgText(mid.x, mid.y + 4, "edge-count-text", label)
      );
    }

    bindEdge(node, group.key);
    ui.layerEdges.appendChild(node);
  }
}

function bindEdge(node, key) {
  node.addEventListener("click", function (event) {
    event.stopPropagation();
    select({ type: "edge", key: key });
  });
}

function edgeSummaryLine(group) {
  if (group.edges.length === 1) {
    var edge = group.edges[0];
    return (
      FAMILY_LABEL[group.family] +
      ": " +
      edge.source +
      " → " +
      edge.target +
      (edge.relation ? " (" + edge.relation + ")" : "")
    );
  }
  return (
    group.edges.length +
    " " +
    FAMILY_LABEL[group.family] +
    " edges — click to list them"
  );
}

function renderNodes(layout) {
  clear(ui.layerNodes);
  for (var i = 0; i < layout.organs.length; i += 1) {
    var organ = layout.organs[i];
    ui.layerNodes.appendChild(organHeaderHit(organ));
    ui.layerNodes.appendChild(organNameHit(organ));
    for (var j = 0; j < organ.nodes.length; j += 1) {
      ui.layerNodes.appendChild(nodeElement(organ.nodes[j], organ));
    }
  }
}

function nodeElement(node, organ) {
  var component = node.component;
  var declarationType = component.declaration_type;
  var classes = "node node-" + declarationType;
  if (organ.stale) {
    classes += " is-stale";
  }
  if (state.outlined[node.id]) {
    classes += " is-outlined";
  }

  var group = svgEl("g", {
    class: classes,
    "data-node": node.id,
    tabindex: "0",
    role: "button",
    "aria-label":
      shortName(node.id) +
      ", " +
      declarationType +
      ", " +
      (component.layer || "unknown layer"),
  });
  var mark = deltaMark(node.id);
  if (mark) {
    group.setAttribute("data-delta", mark);
    group.appendChild(beatRing(node.x, node.y, node.w, node.h, 12));
  }
  if (state.outlined[node.id]) {
    group.appendChild(arrivalOutline(node.x, node.y, node.w, node.h));
  }

  group.appendChild(
    svgEl("rect", {
      class: "node-focus-ring",
      x: r2(node.x + 2),
      y: r2(node.y + 2),
      width: r2(node.w - 4),
      height: r2(node.h - 4),
      rx: 9,
    })
  );

  var cx = node.x + node.w / 2;
  var cy = node.y + GLYPH_CY;
  group.appendChild(glyphShape(declarationType, cx, cy, 1));
  group.appendChild(
    svgText(cx, cy + 4, "node-letter", GLYPH_LETTER[declarationType] || "?")
  );

  group.appendChild(
    svgText(
      cx,
      node.y + LABEL_Y,
      "node-label",
      middleTruncate(shortName(node.id), NODE_LABEL_MAX_CHARS)
    )
  );

  if (organ.stale) {
    var chip = svgChip(
      cx - chipWidth("stale") / 2,
      node.y + STALE_CHIP_Y,
      "stale",
      "svg-chip--stale"
    );
    group.appendChild(chip.node);
    group.appendChild(staleTriangle(node.x + node.w - 4, node.y + 4, 11));
  }

  var title = svgEl("title");
  title.textContent =
    node.id + " — " + projectToLine(component.intent, "intent not declared");
  group.appendChild(title);

  group.appendChild(
    svgEl("rect", {
      class: "node-hit",
      x: r2(node.x),
      y: r2(node.y),
      width: r2(node.w),
      height: r2(node.h),
    })
  );

  group.addEventListener("click", function (event) {
    event.stopPropagation();
    select({ type: "node", id: node.id });
  });
  group.addEventListener("keydown", function (event) {
    if (event.key === "Enter" || event.key === " ") {
      event.preventDefault();
      event.stopPropagation();
      select({ type: "node", id: node.id });
    }
  });
  return group;
}

/* Shapes are drawn around (cx, cy); `scale` shrinks them for the
 * legend swatches. */
function glyphShape(declarationType, cx, cy, scale) {
  var s = scale || 1;
  if (declarationType === "nerve") {
    return svgEl("rect", {
      class: "node-glyph",
      x: r2(cx - 23 * s),
      y: r2(cy - 15 * s),
      width: r2(46 * s),
      height: r2(30 * s),
      rx: r2(9 * s),
    });
  }
  if (declarationType === "cell") {
    return svgEl("circle", {
      class: "node-glyph",
      cx: r2(cx),
      cy: r2(cy),
      r: r2(16 * s),
    });
  }
  if (declarationType === "ganglion") {
    return svgEl("polygon", {
      class: "node-glyph",
      points: polygonPoints(
        [
          [-11, -16],
          [11, -16],
          [21, 0],
          [11, 16],
          [-11, 16],
          [-21, 0],
        ],
        cx,
        cy,
        s
      ),
    });
  }
  if (declarationType === "axon") {
    return svgEl("polygon", {
      class: "node-glyph",
      points: polygonPoints(
        [
          [0, -18],
          [19, 0],
          [0, 18],
          [-19, 0],
        ],
        cx,
        cy,
        s
      ),
    });
  }
  if (declarationType === "test") {
    return svgEl("rect", {
      class: "node-glyph",
      x: r2(cx - 15 * s),
      y: r2(cy - 15 * s),
      width: r2(30 * s),
      height: r2(30 * s),
      rx: r2(3 * s),
    });
  }
  return svgEl("circle", {
    class: "node-glyph",
    cx: r2(cx),
    cy: r2(cy),
    r: r2(14 * s),
  });
}

function polygonPoints(points, cx, cy, scale) {
  var out = [];
  for (var i = 0; i < points.length; i += 1) {
    out.push(
      r2(cx + points[i][0] * scale) + "," + r2(cy + points[i][1] * scale)
    );
  }
  return out.join(" ");
}

function renderStatusLine(layout) {
  var total = state.model.componentIds.length;
  var drawn = 0;
  for (var i = 0; i < layout.edgeGroups.length; i += 1) {
    drawn += layout.edgeGroups[i].edges.length;
  }
  var parts = [
    layout.visibleCount + " of " + total + " components shown",
    layout.organs.length + " modules",
    drawn + " of " + state.model.edges.length + " edges drawn",
  ];
  var freshness = state.model.freshness;
  if (freshness && freshness.transpiler_version) {
    parts.push("built by s0ma " + freshness.transpiler_version);
  }
  ui.statusLine.textContent = parts.join(" · ");
  /* The outline is explained in words wherever it is drawn, so the mark
   * never has to be decoded from its look alone. */
  if (outlinedInView(layout) > 0) {
    ui.statusLine.appendChild(
      el("span", "status-note", "Outlined parts arrived in the newest build.")
    );
  }
  ui.statusLine.hidden = false;
}

/* How many outlined parts this layout really draws: a part hidden by a
 * toggle or folded into a collapsed organ wears no outline. */
function outlinedInView(layout) {
  var count = 0;
  for (var i = 0; i < layout.organs.length; i += 1) {
    var nodes = layout.organs[i].nodes;
    for (var j = 0; j < nodes.length; j += 1) {
      if (state.outlined[nodes[j].id]) {
        count += 1;
      }
    }
  }
  return count;
}

/* ------------------------------------------------------------------ *
 * The materialize beat
 * ------------------------------------------------------------------ *
 *
 * A build lands, and for a few seconds the view says which parts of it
 * are new, which were rewritten, and which have gone. Then it stops
 * saying so and goes back to being a map. That is the whole of the
 * motion budget (visual truth language §9: motion communicates state
 * change, never liveliness).
 *
 * The animations themselves are CSS, hung off a `data-delta` attribute
 * and a highlight-ring element. JavaScript's only part is deciding what
 * changed, drawing the ring, and taking the marks away again — the two
 * timers below. Under prefers-reduced-motion the CSS animates nothing
 * and the ring is simply drawn; the same timers still remove it, so the
 * transition is perceivable without a single moving pixel.
 */

function emptyDelta() {
  return { added: {}, removed: {}, changed: {}, stale: {} };
}

function deltaHasAny(delta) {
  return (
    hasKeys(delta.added) ||
    hasKeys(delta.removed) ||
    hasKeys(delta.changed) ||
    hasKeys(delta.stale)
  );
}

/* Which beat, if any, a component is owed on this paint. */
function deltaMark(canonicalId) {
  if (state.delta.added[canonicalId]) {
    return "added";
  }
  if (state.delta.changed[canonicalId]) {
    return "changed";
  }
  return null;
}

function beatRing(x, y, w, h, radius) {
  return svgEl("rect", {
    class: "beat-ring",
    x: r2(x - BEAT_RING_INSET),
    y: r2(y - BEAT_RING_INSET),
    width: r2(w + BEAT_RING_INSET * 2),
    height: r2(h + BEAT_RING_INSET * 2),
    rx: radius,
  });
}

/* The outline that stays.
 *
 * The beat is over in a few seconds, and a reader who looked away
 * missed it. So the parts the newest build ADDED keep a steady outline
 * after it: two thin rules just outside the part's cell. It is a static
 * style, never animated, and it stays until the next build that adds,
 * changes, or removes something lands, when that build's own additions
 * take it over, or until the page reloads. A build that changes nothing
 * a part declares leaves it where it is. A changed part gets only its
 * beat. A page opened on a project that is already built outlines
 * nothing, because nothing arrived while it was watching.
 *
 * It is told apart without colour alone: selection is ONE heavier rule
 * INSIDE the cell plus a tinted glyph and a bold label; stale is an
 * amber glyph outline, the word "stale", and a corner triangle. This is
 * a DOUBLE thin rule OUTSIDE the cell in the soft ink, and it never
 * touches the glyph or the label. It is never dashed. The status line
 * says in words what it means. */
function arrivalOutline(x, y, w, h) {
  var group = svgEl("g", { class: "arrival-outline", "aria-hidden": "true" });
  group.appendChild(
    svgEl("rect", {
      class: "arrival-rule",
      x: r2(x - 3),
      y: r2(y - 3),
      width: r2(w + 6),
      height: r2(h + 6),
      rx: 11,
    })
  );
  group.appendChild(
    svgEl("rect", {
      class: "arrival-rule",
      x: r2(x - 6),
      y: r2(y - 6),
      width: r2(w + 12),
      height: r2(h + 12),
      rx: 13,
    })
  );
  return group;
}

/* Whether a delta touched anything a part declares: staleness alone is
 * not a build that adds, changes, or removes. */
function deltaChangesParts(delta) {
  return hasKeys(delta.added) || hasKeys(delta.changed) || hasKeys(delta.removed);
}

/* Move the nodes this delta removed out of the live layer and into the
 * ghost layer, where they fade at their last known position. They are
 * no longer in the model, so they are inert: no focus, no pointer, no
 * inspector. */
function harvestGhosts() {
  clear(ui.layerGhosts);
  if (!hasKeys(state.delta.removed)) {
    return;
  }
  var living = ui.layerNodes.childNodes;
  var doomed = [];
  var i;
  for (i = 0; i < living.length; i += 1) {
    var element = living[i];
    var id = element.getAttribute ? element.getAttribute("data-node") : null;
    if (id && state.delta.removed[id]) {
      doomed.push(element);
    }
  }
  for (i = 0; i < doomed.length; i += 1) {
    var ghost = doomed[i];
    ghost.removeAttribute("data-delta");
    ghost.setAttribute("tabindex", "-1");
    ghost.setAttribute("aria-hidden", "true");
    setClassFlag(ghost, "is-removing", true);
    ui.layerGhosts.appendChild(ghost);
  }
  if (doomed.length > 0) {
    scheduleGhostSweep();
  }
}

function scheduleGhostSweep() {
  if (beatSweepTimer !== null) {
    window.clearTimeout(beatSweepTimer);
  }
  beatSweepTimer = window.setTimeout(function () {
    beatSweepTimer = null;
    clear(ui.layerGhosts);
  }, BEAT_SWEEP_MS);
}

function scheduleBeatEnd() {
  if (beatExpiryTimer !== null) {
    window.clearTimeout(beatExpiryTimer);
  }
  beatExpiryTimer = window.setTimeout(endBeat, BEAT_EXPIRY_MS);
}

/* The beat is over. The marks come off in place — no relayout, no
 * reflow, not one node moved — because ending an explanation must not
 * itself look like a change. */
function endBeat() {
  beatExpiryTimer = null;
  state.delta = emptyDelta();
  stripBeatMarks(ui.layerNodes);
  stripBeatMarks(ui.layerOrgans);
  clear(ui.layerGhosts);
}

function stripBeatMarks(layer) {
  if (!layer) {
    return;
  }
  var children = layer.childNodes;
  for (var i = 0; i < children.length; i += 1) {
    var element = children[i];
    if (!element.removeAttribute) {
      continue;
    }
    element.removeAttribute("data-delta");
    var rings = element.getElementsByTagName
      ? element.getElementsByTagName("rect")
      : [];
    for (var j = rings.length - 1; j >= 0; j -= 1) {
      if (rings[j].getAttribute("class") === "beat-ring") {
        rings[j].parentNode.removeChild(rings[j]);
      }
    }
  }
}

/* ------------------------------------------------------------------ *
 * Selection + inspector
 * ------------------------------------------------------------------ */

function select(selection) {
  if (state.dictionary.open) {
    /* A part chosen while the dictionary is open takes the panel back,
     * and the terms button lets go. */
    closeDictionaryState();
  }
  state.selection = selection;
  applySelection();
  renderInspector();
}

function clearSelection() {
  state.selection = null;
  closeDictionaryState();
  state.termCard = { selection: null, key: null, more: false };
  applySelection();
  ui.inspector.hidden = true;
  clear(ui.inspector);
}

function applySelection() {
  var nodes = ui.layerNodes.childNodes;
  var edges = ui.layerEdges.childNodes;
  var organs = ui.layerOrgans.childNodes;
  var i;
  var incident = {};
  var selection = state.selection;

  if (selection && selection.type === "node" && state.layout) {
    var groups = state.layout.edgeGroups;
    for (i = 0; i < groups.length; i += 1) {
      var group = groups[i];
      for (var j = 0; j < group.edges.length; j += 1) {
        if (
          group.edges[j].source === selection.id ||
          group.edges[j].target === selection.id
        ) {
          incident[group.key] = true;
        }
      }
    }
  }

  for (i = 0; i < nodes.length; i += 1) {
    var nodeEl = nodes[i];
    var isSelected =
      selection && selection.type === "node" &&
      nodeEl.getAttribute("data-node") === selection.id;
    setClassFlag(nodeEl, "is-selected", Boolean(isSelected));
  }

  for (i = 0; i < edges.length; i += 1) {
    var edgeEl = edges[i];
    var key = edgeEl.getAttribute("data-edge");
    var selectedEdge =
      selection && selection.type === "edge" && selection.key === key;
    setClassFlag(edgeEl, "is-selected", Boolean(selectedEdge));
    setClassFlag(edgeEl, "is-incident", Boolean(incident[key]));
    var dim =
      selection &&
      selection.type === "node" &&
      !incident[key];
    setClassFlag(edgeEl, "is-dimmed", Boolean(dim));
  }

  for (i = 0; i < organs.length; i += 1) {
    var organEl = organs[i];
    var organModule = organEl.getAttribute("data-module");
    var selectedOrgan =
      selection &&
      ((selection.type === "module" && selection.id === organModule) ||
        (selection.type === "integration" &&
          state.model.integrationsById[selection.id] &&
          state.model.integrationsById[selection.id].module === organModule));
    setClassFlag(organEl, "is-selected", Boolean(selectedOrgan));
  }
}

function setClassFlag(node, className, on) {
  var current = node.getAttribute("class") || "";
  var parts = current.split(/\s+/);
  var out = [];
  for (var i = 0; i < parts.length; i += 1) {
    if (parts[i] && parts[i] !== className) {
      out.push(parts[i]);
    }
  }
  if (on) {
    out.push(className);
  }
  node.setAttribute("class", out.join(" "));
}

function renderInspector() {
  var selection = state.selection;
  var scrolled = ui.inspector.scrollTop;
  clear(ui.inspector);
  ui.termCard = null;
  ui.termCardButton = null;
  ui.termSeen = {};
  if (state.dictionary.open) {
    ui.inspector.hidden = false;
    renderDictionary();
    /* A repaint while the dictionary is open keeps the reader's place. */
    ui.inspector.scrollTop = scrolled;
    return;
  }
  if (!selection) {
    ui.inspector.hidden = true;
    return;
  }
  ui.inspector.hidden = false;

  if (selection.type === "node") {
    renderComponentInspector(state.model.components[selection.id]);
  } else if (selection.type === "integration") {
    renderIntegrationInspector(state.model.integrationsById[selection.id]);
  } else if (selection.type === "edge") {
    renderEdgeInspector(selection.key);
  } else if (selection.type === "module") {
    renderModuleInspector(state.model.modules[selection.id]);
  }
  restoreTermCard();
}

function inspectorHead(title, subtitle) {
  var head = el("div", "inspector-head");
  head.appendChild(el("h2", "inspector-title", title));
  var close = el("button", "btn inspector-close", "close");
  close.type = "button";
  close.setAttribute("aria-label", "close inspector (Esc)");
  close.addEventListener("click", clearSelection);
  head.appendChild(close);
  ui.inspector.appendChild(head);
  if (subtitle) {
    ui.inspector.appendChild(el("p", "inspector-sub", subtitle));
  }
}

function inspectorSection(label) {
  var section = el("section", "inspector-section");
  section.appendChild(el("h3", "section-label", label));
  ui.inspector.appendChild(section);
  return section;
}

/* The component inspector. Read top to bottom: the header (short name,
 * declaration type, module and layer, the stale note), then the fields
 * that say what the part is for and what it promises, then what it
 * leans on and what leans on it, and then one disclosure for the rest.
 * Every value is the author's text exactly as written. */
function renderComponentInspector(component) {
  if (!component) {
    return;
  }
  var canonicalId = component.canonical_id;
  if (state.disclosure.key !== canonicalId) {
    state.disclosure = { key: canonicalId, more: false, undeclared: false };
  }
  componentHead(component);

  var fields = component.fields || {};
  var declarationType = component.declaration_type;
  var aboveTheFold = ABOVE_THE_FOLD[declarationType] || ABOVE_THE_FOLD_DEFAULT;
  var shownAbove = {};
  for (var i = 0; i < aboveTheFold.length; i += 1) {
    var name = aboveTheFold[i];
    if (!fieldIsCarried(name, declarationType, fields)) {
      continue;
    }
    shownAbove[name] = true;
    var raw = name === "intent" ? component.intent : fields[name];
    var section = fieldSection(name);
    var holder = el(name === "intent" ? "p" : "div", "intent-text");
    appendFieldValue(holder, name, raw, name !== "intent" && !(name in fields));
    section.appendChild(holder);
  }

  renderDependencies(canonicalId, fields.depends_on);
  renderDependents(canonicalId);

  /* Pending is authoring debt, so it is never folded away: a pending
   * field that would sit under the fold is shown here instead. */
  var keys = orderedFieldKeys(fields);
  var rest = [];
  var undeclared = [];
  for (var j = 0; j < keys.length; j += 1) {
    var key = keys[j];
    if (shownAbove[key] || FIELDS_SHOWN_ELSEWHERE[key]) {
      continue;
    }
    var projected = projectValue(fields[key]);
    if (projected.kind === "pending") {
      var pendingSection = fieldSection(key);
      var pendingHolder = el("div", "intent-text");
      appendProjectedValue(pendingHolder, fields[key]);
      pendingSection.appendChild(pendingHolder);
    } else if (projected.kind === "none" || isEmptyValue(projected.value)) {
      undeclared.push(key);
    } else {
      rest.push(key);
    }
  }

  renderMoreAboutThisPart(component, fields, rest, undeclared);
}

/* Whether an above-the-fold row is drawn: `intent` always, any other
 * field only when the payload carries its key. The one exception is
 * `forbids` on a nerve or a ganglion, which every current build writes:
 * a payload without it is from an older build, and says "not declared". */
function fieldIsCarried(name, declarationType, fields) {
  if (name === "intent" || name in fields) {
    return true;
  }
  return (
    name === "forbids" &&
    (declarationType === "nerve" || declarationType === "ganglion")
  );
}

function componentHead(component) {
  inspectorHead(shortName(component.canonical_id), null);

  var tagLine = el("p", "inspector-tagline");
  var declControl = component.declaration_type
    ? inspectorTerm(component.declaration_type, null, "decl-tag")
    : null;
  tagLine.appendChild(
    declControl ||
      el("code", "decl-tag", component.declaration_type || "not declared")
  );
  ui.inspector.appendChild(tagLine);

  var where = el("p", "inspector-where");
  appendTermWord(where, "module");
  where.appendChild(document.createTextNode(" "));
  appendTermValue(where, component.module);
  where.appendChild(el("span", "label-sep", " · "));
  appendTermWord(where, "layer");
  where.appendChild(document.createTextNode(" "));
  appendTermValue(where, component.layer, "layer-name");
  ui.inspector.appendChild(where);

  if (isStaleModule(component.module)) {
    var note = el(
      "p",
      "inspector-note",
      "stale — last canonical build. Module " +
        component.module +
        " has changed since this build; run s0ma build to refresh."
    );
    ui.inspector.appendChild(note);
  }
}

/* A DSL word or value in monospace, or "not declared" when absent. With
 * a role (a layer name, a relation word), a value s0ma's dictionary
 * explains is the control that opens its card; without one, a value is
 * never a control, so an enum value or a module name stays as written. */
function appendTermValue(host, value, role) {
  if (value === undefined || value === null || value === "") {
    host.appendChild(el("span", "value-absent", "not declared"));
    return;
  }
  var control = role ? inspectorTerm(String(value), role, "term") : null;
  host.appendChild(control || el("code", "term", String(value)));
}

/* A DSL word the page prints itself (`module`, `layer`, a field name),
 * as the control that opens its card when s0ma's dictionary explains
 * it, and in monospace exactly as before when it does not. */
function appendTermWord(host, word) {
  var control = inspectorTerm(word, null, "term");
  host.appendChild(control || el("code", "term", word));
}

/* A field's label: the DSL term in monospace, a separator, then the
 * plain phrase. A term with no phrase is labelled by the term alone.
 * The term is the control that opens its card when s0ma's dictionary
 * explains it; the phrase is never part of the control. */
function fieldLabel(tag, className, term, phrase) {
  var label = el(tag, className);
  var control = inspectorTerm(term, null, "term");
  if (control) {
    label.appendChild(control);
  } else {
    label.appendChild(el("code", "term", term));
  }
  if (phrase) {
    label.appendChild(el("span", "label-sep", " · "));
    label.appendChild(el("span", "label-phrase", phrase));
  }
  return label;
}

function fieldSection(term) {
  var section = el("section", "inspector-section");
  section.appendChild(fieldLabel("h3", "field-label", term, FIELD_PHRASE[term]));
  ui.inspector.appendChild(section);
  return section;
}

/* A section whose label is plain words, not a DSL term: "dependencies"
 * and "dependents" are this page's words, not the language's. */
function plainSection(word, phrase) {
  var section = el("section", "inspector-section");
  var label = el("h3", "field-label");
  label.appendChild(el("span", "label-word", word));
  label.appendChild(el("span", "label-sep", " · "));
  label.appendChild(el("span", "label-phrase", phrase));
  section.appendChild(label);
  ui.inspector.appendChild(section);
  return section;
}

/* One field above the fold. `forbids` is the one field whose `none`
 * state is shown as `none` rather than "not declared": the line is
 * required on a nerve and a ganglion, and a build refuses a part that
 * leaves it out in every mode, so a `none` state in the payload is the
 * author's written answer. A payload from a build that predates the
 * line carries no `forbids` key at all, and that says "not declared". */
function appendFieldValue(host, name, raw, absent) {
  if (
    name === "forbids" &&
    !absent &&
    raw &&
    typeof raw === "object" &&
    raw.state === "none"
  ) {
    host.appendChild(el("code", "term", "none"));
    return;
  }
  appendProjectedValue(host, raw);
}

function isEmptyValue(value) {
  if (value === undefined || value === null) {
    return true;
  }
  if (Array.isArray(value)) {
    return value.length === 0;
  }
  if (typeof value === "object") {
    return Object.keys(value).length === 0;
  }
  return false;
}

/* The relationships of one family pair that touch `canonicalId` from
 * one side. Verification edges are listed under the fold, with
 * `covered_by`. */
function relationshipsOf(canonicalId, direction) {
  var out = [];
  var edges = state.model.edges;
  for (var i = 0; i < edges.length; i += 1) {
    var edge = edges[i];
    if (edge.family !== "authored" && edge.family !== "derived") {
      continue;
    }
    if (direction === "out" ? edge.source === canonicalId : edge.target === canonicalId) {
      out.push(edge);
    }
  }
  return out;
}

function renderDependencies(canonicalId, dependsOn) {
  var section = plainSection("dependencies", "what it leans on");
  var edges = relationshipsOf(canonicalId, "out");
  if (projectValue(dependsOn).kind === "pending") {
    var holder = el("div", "intent-text");
    appendProjectedValue(holder, dependsOn);
    section.appendChild(holder);
  }
  appendRelationRows(section, edges, "out", "none declared");
}

function renderDependents(canonicalId) {
  var section = plainSection("dependents", "what leans on it");
  appendRelationRows(
    section,
    relationshipsOf(canonicalId, "in"),
    "in",
    "none in this graph"
  );
}

function appendRelationRows(section, edges, direction, emptyText) {
  if (edges.length === 0) {
    section.appendChild(el("p", "value-absent", emptyText));
    return;
  }
  var list = el("ul", "rel-list");
  for (var i = 0; i < edges.length; i += 1) {
    list.appendChild(relationRow(edges[i], direction));
  }
  section.appendChild(list);
}

/* One relationship: the relation word, the part at the other end as
 * the control that selects it, then where the relationship comes from
 * and, for an authored one, what it carries. */
function relationRow(edge, direction) {
  var item = el("li", "rel-item");
  var head = el("div", "rel-head");
  appendTermValue(head, edge.relation, "relation");
  head.appendChild(document.createTextNode(" "));
  head.appendChild(peerControl(direction === "in" ? edge.source : edge.target));
  item.appendChild(head);

  var meta = el("div", "rel-meta");
  meta.appendChild(document.createTextNode(FAMILY_LABEL[edge.family]));
  if (edge.family === "authored") {
    meta.appendChild(el("span", "label-sep", " · "));
    meta.appendChild(el("code", "term", "carries"));
    meta.appendChild(
      document.createTextNode(" " + projectToLine(edge.carries, "not declared"))
    );
  }
  item.appendChild(meta);
  return item;
}

/* The other end of a relationship. A part the graph carries is a button
 * that selects it through the same path a click on its node takes; a
 * name the graph does not carry is shown as text and says so. */
function peerControl(peerId) {
  var kind = null;
  if (state.model.components[peerId]) {
    kind = "node";
  } else if (state.model.integrationsById[peerId]) {
    kind = "integration";
  }
  if (!kind) {
    var unknown = el("span", "rel-peer");
    unknown.appendChild(el("code", "term", shortName(peerId)));
    unknown.appendChild(el("span", "narration-unknown-note", " not in this graph"));
    unknown.title = peerId;
    return unknown;
  }
  var button = el("button", "rel-peer rel-peer-button", shortName(peerId));
  button.type = "button";
  button.title = peerId;
  button.setAttribute("aria-label", "show " + peerId + " in the graph");
  button.addEventListener("click", function () {
    if (kind === "node") {
      select({ type: "node", id: peerId });
    } else {
      select({ type: "integration", id: peerId });
    }
    ui.inspector.focus();
  });
  return button;
}

/* Everything else about the part, behind one disclosure. A native
 * <details>: reachable by keyboard, its open state exposed to assistive
 * technology, and it opens with no motion. */
function renderMoreAboutThisPart(component, fields, rest, undeclared) {
  var more = el("details", "inspector-more");
  more.open = state.disclosure.more;
  more.addEventListener("toggle", function () {
    state.disclosure.more = more.open;
  });
  more.appendChild(el("summary", "inspector-more-summary", "More about this part"));

  var basics = el("dl", "dl");
  appendTermDefinition(basics, "kind", component.kind);
  appendTermDefinition(basics, "visibility", component.visibility);
  more.appendChild(basics);

  renderVerification(more, component.canonical_id, fields);

  if (rest.length > 0) {
    var list = el("dl", "dl inspector-more-block");
    for (var i = 0; i < rest.length; i += 1) {
      appendLabelledDefinition(list, rest[i], fields[rest[i]]);
    }
    more.appendChild(list);
  }

  if (undeclared.length > 0) {
    var unset = el("details", "inspector-undeclared inspector-more-block");
    unset.open = state.disclosure.undeclared;
    unset.addEventListener("toggle", function () {
      state.disclosure.undeclared = unset.open;
    });
    unset.appendChild(
      el(
        "summary",
        "inspector-undeclared-summary",
        undeclared.length +
          (undeclared.length === 1 ? " field not declared" : " fields not declared")
      )
    );
    var names = el("ul", "inspector-undeclared-list");
    for (var j = 0; j < undeclared.length; j += 1) {
      var item = el("li");
      appendTermWord(item, undeclared[j]);
      names.appendChild(item);
    }
    unset.appendChild(names);
    more.appendChild(unset);
  }

  var origin = el("dl", "dl inspector-more-block");
  origin.appendChild(el("dt", null, "Written in"));
  var written = el("dd");
  appendLocation(written, component.location);
  origin.appendChild(written);
  origin.appendChild(el("dt", null, "canonical id"));
  var idHolder = el("dd");
  idHolder.appendChild(el("code", "term", component.canonical_id));
  origin.appendChild(idHolder);
  more.appendChild(origin);

  ui.inspector.appendChild(more);
}

/* `covered_by` and the verification relationships, side by side: what
 * the author says checks this part, and what the build found doing so. */
function renderVerification(host, canonicalId, fields) {
  var outgoing = [];
  var incoming = [];
  var edges = state.model.edges;
  for (var i = 0; i < edges.length; i += 1) {
    var edge = edges[i];
    if (edge.family !== "verification") {
      continue;
    }
    if (edge.source === canonicalId) {
      outgoing.push(edge);
    } else if (edge.target === canonicalId) {
      incoming.push(edge);
    }
  }
  var hasField = "covered_by" in fields;
  if (!hasField && outgoing.length === 0 && incoming.length === 0) {
    return;
  }

  var block = el("div", "inspector-more-block");
  if (hasField) {
    var list = el("dl", "dl");
    appendLabelledDefinition(list, "covered_by", fields.covered_by);
    block.appendChild(list);
  }
  if (outgoing.length + incoming.length > 0) {
    var rels = el("ul", "rel-list");
    var j;
    for (j = 0; j < outgoing.length; j += 1) {
      rels.appendChild(edgeListItem(outgoing[j], "out"));
    }
    for (j = 0; j < incoming.length; j += 1) {
      rels.appendChild(edgeListItem(incoming[j], "in"));
    }
    block.appendChild(rels);
    if (!state.toggles.tests) {
      block.appendChild(
        el(
          "p",
          "rel-meta",
          "verification edges are always listed here; turn on " +
            "“tests and docs” to draw them on the graph."
        )
      );
    }
  }
  host.appendChild(block);
}

/* A definition whose term is a DSL field name, with its plain phrase
 * when it has one. */
function appendLabelledDefinition(list, term, raw) {
  list.appendChild(fieldLabel("dt", null, term, FIELD_PHRASE[term]));
  var dd = el("dd");
  appendProjectedValue(dd, raw);
  list.appendChild(dd);
}

/* A definition whose term and value are both DSL words (kind,
 * visibility and their enum values). */
function appendTermDefinition(list, term, value) {
  var dt = el("dt");
  appendTermWord(dt, term);
  list.appendChild(dt);
  var dd = el("dd");
  var projected = projectValue(value);
  if (projected.kind === "pending") {
    appendProjectedValue(dd, value);
  } else {
    appendTermValue(dd, projected.kind === "value" ? projected.value : null);
  }
  list.appendChild(dd);
}

/* The module inspector. Read top to bottom: the header (the module's
 * name, a `module` tag, its layer and how many components it holds,
 * the stale note), then what it is for, which parts of other files it
 * may reach, what it needs from outside the project, what it offers,
 * and which modules reach into it; then one disclosure for the rest.
 * A row is drawn only when the module record carries its key, so a
 * payload from an older build shows the header and `intent` alone. */
function renderModuleInspector(module) {
  if (!module) {
    return;
  }
  var name = module.name;
  var disclosureKey = "module " + name;
  if (state.disclosure.key !== disclosureKey) {
    state.disclosure = { key: disclosureKey, more: false, undeclared: false };
  }
  moduleHead(module);

  var intent = fieldSection("intent");
  var holder = el("p", "intent-text");
  appendProjectedValue(holder, module.intent);
  intent.appendChild(holder);

  var imports = module.imports;
  var carriesImports = Boolean(imports) && typeof imports === "object";
  if (carriesImports && "uses" in imports) {
    renderModuleUses(imports.uses);
  }
  if (carriesImports && "requires" in imports) {
    renderModuleRequires(imports.requires);
  }
  if ("exports" in module) {
    renderModuleExports(name, module.exports);
  }
  if (carriesImports) {
    renderModuleUsedBy(name);
  }

  renderMoreAboutThisModule(module);
}

function moduleHead(module) {
  inspectorHead(module.name, null);

  var tagLine = el("p", "inspector-tagline");
  var moduleTag = inspectorTerm("module", null, "decl-tag");
  tagLine.appendChild(moduleTag || el("code", "decl-tag", "module"));
  ui.inspector.appendChild(tagLine);

  var count = 0;
  var ids = state.model.componentIds;
  for (var i = 0; i < ids.length; i += 1) {
    if (state.model.components[ids[i]].module === module.name) {
      count += 1;
    }
  }
  var where = el("p", "inspector-where");
  appendTermWord(where, "layer");
  where.appendChild(document.createTextNode(" "));
  appendTermValue(where, module.layer, "layer-name");
  where.appendChild(el("span", "label-sep", " · "));
  where.appendChild(document.createTextNode(headerMetaText(count)));
  ui.inspector.appendChild(where);

  if (isStaleModule(module.name)) {
    ui.inspector.appendChild(
      el(
        "p",
        "inspector-note",
        "stale — last canonical build. Module " +
          module.name +
          " has changed since this build; run s0ma build to refresh."
      )
    );
  }
}

function moduleSection(term) {
  var section = el("section", "inspector-section");
  section.appendChild(fieldLabel("h3", "field-label", term, MODULE_PHRASE[term]));
  ui.inspector.appendChild(section);
  return section;
}

/* A declared list of names: the list itself when it holds names,
 * `[]` when the author declared it empty, and otherwise the state
 * wrapper's own words ("not declared", "pending:" and the reason). */
function declaredNames(raw) {
  var projected = projectValue(raw);
  if (projected.kind === "value" && Array.isArray(projected.value)) {
    return projected.value;
  }
  return null;
}

function appendListState(section, raw) {
  var holder = el("div", "intent-text");
  appendProjectedValue(holder, raw);
  section.appendChild(holder);
}

function appendEmptyList(section) {
  var holder = el("p", "intent-text");
  holder.appendChild(el("code", "term", "[]"));
  section.appendChild(holder);
}

/* One `uses` entry names a module and a part of it, `module.part`. The
 * module is the longest module name in the graph the entry starts with;
 * an entry naming no module the graph carries splits at its last dot. */
function splitUsesEntry(entry) {
  var text = String(entry);
  var best = null;
  var names = state.model.moduleNames;
  for (var i = 0; i < names.length; i += 1) {
    var candidate = names[i];
    if (
      text.indexOf(candidate + ".") === 0 &&
      (best === null || candidate.length > best.length)
    ) {
      best = candidate;
    }
  }
  if (best !== null) {
    return { module: best, part: text.slice(best.length + 1) };
  }
  var dot = text.lastIndexOf(".");
  if (dot <= 0) {
    return { module: null, part: text };
  }
  return { module: text.slice(0, dot), part: text.slice(dot + 1) };
}

/* `uses`, grouped under "from" and the other module's name. Each part
 * goes through peerControl, the relationship rows' own path: a part the
 * graph carries is the button that selects it, and a name it does not
 * carry is shown as written and selects nothing. */
function renderModuleUses(raw) {
  var section = moduleSection("uses");
  var entries = declaredNames(raw);
  if (entries === null) {
    appendListState(section, raw);
    return;
  }
  if (entries.length === 0) {
    appendEmptyList(section);
    return;
  }
  var order = [];
  var groups = {};
  for (var i = 0; i < entries.length; i += 1) {
    var split = splitUsesEntry(entries[i]);
    var key = split.module === null ? "" : split.module;
    if (!Object.prototype.hasOwnProperty.call(groups, key)) {
      groups[key] = [];
      order.push(key);
    }
    groups[key].push(split);
  }
  for (var g = 0; g < order.length; g += 1) {
    var group = el("div", "rel-group");
    if (order[g] !== "") {
      var label = el("p", "rel-group-label");
      label.appendChild(document.createTextNode("from "));
      label.appendChild(el("code", "term", order[g]));
      group.appendChild(label);
    }
    var list = el("ul", "rel-list");
    var parts = groups[order[g]];
    for (var j = 0; j < parts.length; j += 1) {
      var item = el("li", "rel-item");
      item.appendChild(
        peerControl(
          parts[j].module === null
            ? parts[j].part
            : parts[j].module + "::" + parts[j].part
        )
      );
      list.appendChild(item);
    }
    group.appendChild(list);
    section.appendChild(group);
  }
}

/* `requires`: code from outside the project, so never in the graph.
 * The names are shown as written and are not controls. */
function renderModuleRequires(raw) {
  var section = moduleSection("requires");
  var names = declaredNames(raw);
  if (names === null) {
    appendListState(section, raw);
    return;
  }
  if (names.length === 0) {
    appendEmptyList(section);
    return;
  }
  var list = el("ul", "rel-list");
  for (var i = 0; i < names.length; i += 1) {
    var item = el("li", "rel-item");
    item.appendChild(el("code", "rel-peer", String(names[i])));
    list.appendChild(item);
  }
  section.appendChild(list);
}

/* `exports`: each name selects that part when the graph carries it. */
function renderModuleExports(moduleName, raw) {
  var section = moduleSection("exports");
  var names = declaredNames(raw);
  if (names === null) {
    appendListState(section, raw);
    return;
  }
  if (names.length === 0) {
    appendEmptyList(section);
    return;
  }
  var list = el("ul", "rel-list");
  for (var i = 0; i < names.length; i += 1) {
    var item = el("li", "rel-item");
    item.appendChild(peerControl(moduleName + "::" + String(names[i])));
    list.appendChild(item);
  }
  section.appendChild(list);
}

/* The modules whose declared `uses` name a part of `moduleName`: a
 * reverse index over every module's own `uses` list, built here from
 * declared data and nothing else. `unknown` counts the other modules
 * whose `uses` cannot be read (no key, or pending), so the panel never
 * calls the list complete when it cannot know. */
function modulesUsing(moduleName) {
  var found = [];
  var unknown = 0;
  var names = state.model.moduleNames;
  for (var i = 0; i < names.length; i += 1) {
    var other = names[i];
    if (other === moduleName) {
      continue;
    }
    var record = state.model.modules[other];
    var imports = record && record.imports;
    var hasUses = Boolean(imports) && typeof imports === "object" && "uses" in imports;
    var entries = hasUses ? declaredNames(imports.uses) : null;
    if (!entries) {
      if (!hasUses || projectValue(imports.uses).kind !== "none") {
        unknown += 1;
      }
      continue;
    }
    for (var j = 0; j < entries.length; j += 1) {
      if (splitUsesEntry(entries[j]).module === moduleName) {
        found.push(other);
        break;
      }
    }
  }
  return { found: found, unknown: unknown };
}

function renderModuleUsedBy(moduleName) {
  var section = plainSection("used by", "files that reach into it");
  var reverse = modulesUsing(moduleName);
  var users = reverse.found;
  if (users.length > 0) {
    var list = el("ul", "rel-list");
    for (var i = 0; i < users.length; i += 1) {
      var item = el("li", "rel-item");
      item.appendChild(moduleControl(users[i]));
      list.appendChild(item);
    }
    section.appendChild(list);
  }
  if (reverse.unknown > 0) {
    var note = el("p", "value-absent");
    note.appendChild(
      document.createTextNode(
        reverse.unknown === 1
          ? "1 module has not declared its "
          : reverse.unknown + " modules have not declared their "
      )
    );
    note.appendChild(el("code", "term", "uses"));
    note.appendChild(
      document.createTextNode(", so this list may be incomplete")
    );
    section.appendChild(note);
  } else if (users.length === 0) {
    section.appendChild(el("p", "value-absent", "none in this project"));
  }
}

/* A module named in the panel, as the button that selects it through
 * the same path a click on its name in the graph takes. */
function moduleControl(moduleName) {
  var button = el("button", "rel-peer rel-peer-button", moduleName);
  button.type = "button";
  button.setAttribute("aria-label", "show module " + moduleName + " in the graph");
  button.addEventListener("click", function () {
    select({ type: "module", id: moduleName });
    ui.inspector.focus();
  });
  return button;
}

/* Everything else about the module, behind one disclosure: `version`,
 * `tags`, the three other import lists (a counted line for those not
 * declared), and the file it was written in. Drawn only when the
 * record carries at least one of them. */
function renderMoreAboutThisModule(module) {
  var imports =
    module.imports && typeof module.imports === "object" ? module.imports : null;
  var hasAny =
    "version" in module || "tags" in module || "source_file" in module || imports;
  if (!hasAny) {
    return;
  }

  var more = el("details", "inspector-more");
  more.open = state.disclosure.more;
  more.addEventListener("toggle", function () {
    state.disclosure.more = more.open;
  });
  more.appendChild(
    el("summary", "inspector-more-summary", "More about this module")
  );

  var basics = el("dl", "dl");
  var shown = 0;
  if ("version" in module) {
    appendLabelledDefinition(basics, "version", module.version);
    shown += 1;
  }
  if ("tags" in module) {
    appendLabelledDefinition(basics, "tags", module.tags);
    shown += 1;
  }
  var undeclared = [];
  if (imports) {
    for (var i = 0; i < MODULE_FOLDED_LISTS.length; i += 1) {
      var key = MODULE_FOLDED_LISTS[i];
      if (!(key in imports)) {
        continue;
      }
      var listed = declaredNames(imports[key]);
      if (projectValue(imports[key]).kind === "none") {
        undeclared.push(key);
      } else if (listed !== null && listed.length === 0) {
        basics.appendChild(fieldLabel("dt", null, key, null));
        var emptyHolder = el("dd");
        emptyHolder.appendChild(el("code", "term", "[]"));
        basics.appendChild(emptyHolder);
        shown += 1;
      } else {
        appendLabelledDefinition(basics, key, imports[key]);
        shown += 1;
      }
    }
  }
  /* `privileged` is a plain list on the imports block: a row when it
   * holds names, left out when it is empty or absent. */
  var privileged = imports ? imports.privileged : null;
  if (Array.isArray(privileged) && privileged.length > 0) {
    basics.appendChild(fieldLabel("dt", null, "privileged", null));
    var privilegedHolder = el("dd");
    var privilegedList = el("ul");
    for (var p = 0; p < privileged.length; p += 1) {
      var privilegedItem = el("li");
      privilegedItem.appendChild(el("code", "term", String(privileged[p])));
      privilegedList.appendChild(privilegedItem);
    }
    privilegedHolder.appendChild(privilegedList);
    basics.appendChild(privilegedHolder);
    shown += 1;
  }
  if (shown > 0) {
    more.appendChild(basics);
  }

  if (undeclared.length > 0) {
    var unset = el("details", "inspector-undeclared inspector-more-block");
    unset.open = state.disclosure.undeclared;
    unset.addEventListener("toggle", function () {
      state.disclosure.undeclared = unset.open;
    });
    unset.appendChild(
      el(
        "summary",
        "inspector-undeclared-summary",
        undeclared.length +
          (undeclared.length === 1 ? " list not declared" : " lists not declared")
      )
    );
    var names = el("ul", "inspector-undeclared-list");
    for (var j = 0; j < undeclared.length; j += 1) {
      var item = el("li");
      appendTermWord(item, undeclared[j]);
      names.appendChild(item);
    }
    unset.appendChild(names);
    more.appendChild(unset);
  }

  if ("source_file" in module) {
    var origin = el("dl", "dl inspector-more-block");
    origin.appendChild(el("dt", null, "Written in"));
    var written = el("dd");
    var file = projectValue(module.source_file);
    appendLocation(
      written,
      file.kind === "value" && file.value ? { file: String(file.value) } : null
    );
    origin.appendChild(written);
    more.appendChild(origin);
  }

  ui.inspector.appendChild(more);
}

function renderIntegrationInspector(integration) {
  if (!integration) {
    return;
  }
  inspectorHead(integration.name, integration.canonical_id);

  var intent = fieldSection("intent");
  var holder = el("p", "intent-text");
  appendProjectedValue(holder, integration.intent);
  intent.appendChild(holder);

  var declaration = inspectorSection("declaration");
  var declarationList = el("dl", "dl");
  appendDefinition(declarationList, "kind", "integration declaration");
  appendDefinition(declarationList, "layer", integration.layer);
  appendDefinition(declarationList, "version", integration.version);
  appendDefinition(declarationList, "module", integration.module);
  declaration.appendChild(declarationList);

  var fieldsSection = inspectorSection("fields");
  var fieldList = el("dl", "dl");
  var skip = {
    canonical_id: true,
    name: true,
    module: true,
    layer: true,
    version: true,
    intent: true,
    location: true,
  };
  var keys = Object.keys(integration).sort(compareStrings);
  var shown = 0;
  for (var i = 0; i < keys.length; i += 1) {
    if (skip[keys[i]]) {
      continue;
    }
    appendDefinition(fieldList, keys[i], integration[keys[i]]);
    shown += 1;
  }
  if (shown === 0) {
    fieldsSection.appendChild(el("p", "value-absent", "not declared"));
  } else {
    fieldsSection.appendChild(fieldList);
  }

  renderRelationships(integration.canonical_id);
  renderLocation(integration.location);
}

function renderEdgeInspector(key) {
  var group = null;
  var groups = state.layout ? state.layout.edgeGroups : [];
  for (var i = 0; i < groups.length; i += 1) {
    if (groups[i].key === key) {
      group = groups[i];
      break;
    }
  }
  if (!group) {
    clearSelection();
    return;
  }

  var title =
    group.edges.length === 1
      ? FAMILY_LABEL[group.family] + " edge"
      : group.edges.length + " " + FAMILY_LABEL[group.family] + " edges";
  /* Two different things put more than one edge behind one line, and
   * the panel must not name the wrong one: an endpoint anchored to a
   * COLLAPSED ORGAN (`group.aggregated`) really is a bundle crossing a
   * module boundary, while several edges between the SAME two visible
   * nodes are just parallel declarations. Saying "collapsed module"
   * for the second case states a reason that is not the reason. */
  var subtitle;
  if (group.edges.length === 1) {
    subtitle = group.edges[0].source + " → " + group.edges[0].target;
  } else if (group.aggregated) {
    subtitle = "aggregated into a collapsed module";
  } else {
    subtitle = group.from.key.slice(2) + " → " + group.to.key.slice(2);
  }
  inspectorHead(title, subtitle);

  if (group.edges.length === 1 && group.family === "authored") {
    var intent = fieldSection("intent");
    var holder = el("p", "intent-text");
    appendProjectedValue(holder, group.edges[0].intent);
    intent.appendChild(holder);
  }

  var section = inspectorSection("edges");
  var list = el("ul", "rel-list");
  for (var j = 0; j < group.edges.length; j += 1) {
    list.appendChild(edgeListItem(group.edges[j], null));
  }
  section.appendChild(list);
}

function orderedFieldKeys(fields) {
  var keys = Object.keys(fields).sort(compareStrings);
  var head = [];
  var tail = [];
  for (var i = 0; i < keys.length; i += 1) {
    if (FIELD_PRIORITY.indexOf(keys[i]) !== -1) {
      head.push(keys[i]);
    } else {
      tail.push(keys[i]);
    }
  }
  head.sort(function (a, b) {
    return FIELD_PRIORITY.indexOf(a) - FIELD_PRIORITY.indexOf(b);
  });
  return head.concat(tail);
}

function appendDefinition(list, term, raw) {
  list.appendChild(el("dt", null, term));
  var dd = el("dd");
  appendProjectedValue(dd, raw);
  list.appendChild(dd);
}

/* The one place a state wrapper becomes pixels. `none` says "not
 * declared" in a muted voice; `pending` says so out loud, because
 * pending is authoring debt someone still owes (text + treatment,
 * never colour alone). */
function appendProjectedValue(host, raw) {
  var projected = projectValue(raw);

  if (projected.kind === "none") {
    host.appendChild(el("span", "value-absent", "not declared"));
    return;
  }

  if (projected.kind === "pending") {
    var pending = el("span", "value-pending");
    pending.appendChild(el("span", "pending-word", "pending:"));
    pending.appendChild(
      document.createTextNode(" " + valueToLine(projected.reason))
    );
    host.appendChild(pending);
    return;
  }

  appendPlainValue(host, projected.value);
}

function appendPlainValue(host, value) {
  if (value === undefined || value === null) {
    host.appendChild(el("span", "value-absent", "not declared"));
    return;
  }
  if (Array.isArray(value)) {
    if (value.length === 0) {
      host.appendChild(el("span", "value-absent", "not declared"));
      return;
    }
    var list = el("ul");
    for (var i = 0; i < value.length; i += 1) {
      var item = el("li");
      appendPlainValue(item, value[i]);
      list.appendChild(item);
    }
    host.appendChild(list);
    return;
  }
  if (typeof value === "object") {
    var keys = Object.keys(value).sort(compareStrings);
    if (keys.length === 0) {
      host.appendChild(el("span", "value-absent", "not declared"));
      return;
    }
    var nested = el("dl", "dl");
    for (var j = 0; j < keys.length; j += 1) {
      appendDefinition(nested, keys[j], value[keys[j]]);
    }
    host.appendChild(nested);
    return;
  }
  host.appendChild(document.createTextNode(String(value)));
}

function renderRelationships(canonicalId) {
  var section = inspectorSection("relationships");
  var families = ["authored", "derived", "verification"];
  var edges = state.model.edges;
  var found = 0;

  for (var f = 0; f < families.length; f += 1) {
    var family = families[f];
    var outgoing = [];
    var incoming = [];
    for (var i = 0; i < edges.length; i += 1) {
      var edge = edges[i];
      if (edge.family !== family) {
        continue;
      }
      if (edge.source === canonicalId) {
        outgoing.push(edge);
      } else if (edge.target === canonicalId) {
        incoming.push(edge);
      }
    }
    if (outgoing.length === 0 && incoming.length === 0) {
      continue;
    }
    found += outgoing.length + incoming.length;

    var group = el("div", "rel-group");
    group.appendChild(
      el(
        "p",
        "rel-group-label",
        FAMILY_LABEL[family] + " (" + (outgoing.length + incoming.length) + ")"
      )
    );
    var list = el("ul", "rel-list");
    var j;
    for (j = 0; j < outgoing.length; j += 1) {
      list.appendChild(edgeListItem(outgoing[j], "out"));
    }
    for (j = 0; j < incoming.length; j += 1) {
      list.appendChild(edgeListItem(incoming[j], "in"));
    }
    group.appendChild(list);

    if (family === "verification" && !state.toggles.tests) {
      group.appendChild(
        el(
          "p",
          "rel-meta",
          "verification edges are always listed here; turn on " +
            "“tests and docs” to draw them on the graph."
        )
      );
    }
    section.appendChild(group);
  }

  if (found === 0) {
    section.appendChild(el("p", "value-absent", "none declared"));
  }
}

function edgeListItem(edge, direction) {
  var item = el("li", "rel-item");
  var head = el("div", "rel-head");

  var relationText = edge.relation
    ? edge.relation
    : edge.family === "verification"
      ? direction === "in"
        ? "verified by"
        : "verifies"
      : edge.family;
  /* Only a relation word the payload carries is a term; the page's own
   * fallbacks ("verifies", a family name) stay plain. */
  var relationControl = edge.relation
    ? inspectorTerm(String(edge.relation), "relation", "rel-relation")
    : null;
  head.appendChild(relationControl || el("span", "rel-relation", relationText));

  var peer;
  if (direction === "in") {
    head.appendChild(el("span", "rel-arrow", "←"));
    peer = edge.source;
  } else if (direction === "out") {
    head.appendChild(el("span", "rel-arrow", "→"));
    peer = edge.target;
  } else {
    /* No direction to report relative to a selected component: name
     * both ends instead. */
    head.appendChild(el("span", "rel-arrow", " "));
    peer = edge.source + " → " + edge.target;
  }
  head.appendChild(el("span", "rel-peer", peer));
  item.appendChild(head);

  var meta = [FAMILY_LABEL[edge.family] + " edge"];
  meta.push("origin " + (edge.origin || "not declared"));
  if (edge.coupling !== undefined && edge.coupling !== null) {
    meta.push("coupling " + valueToLine(projectValue(edge.coupling).value));
  }
  item.appendChild(el("div", "rel-meta", meta.join(" · ")));

  if (edge.carries !== undefined && edge.carries !== null) {
    item.appendChild(
      el(
        "div",
        "rel-meta",
        "carries: " + projectToLine(edge.carries, "not declared")
      )
    );
  }
  if (edge.intent !== undefined && edge.intent !== null) {
    item.appendChild(
      el("div", "rel-intent", projectToLine(edge.intent, "not declared"))
    );
  }
  return item;
}

function renderLocation(location) {
  var section = inspectorSection("location");
  var holder = el("p");
  appendLocation(holder, location);
  section.appendChild(holder);
}

/* The file and lines a declaration was written in, or "not declared". */
function appendLocation(host, location) {
  var projected = projectValue(location);
  if (projected.kind !== "value" || !projected.value) {
    host.appendChild(el("span", "value-absent", "not declared"));
    return;
  }
  var value = projected.value;
  var file = value.file || "";
  var start = value.line !== undefined ? value.line : value.start_line;
  var end = value.end_line;
  var text = file;
  if (start !== undefined && start !== null) {
    text += " · lines " + start;
    if (end !== undefined && end !== null && end !== start) {
      text += "–" + end;
    }
  }
  if (!text) {
    host.appendChild(el("span", "value-absent", "not declared"));
    return;
  }
  host.appendChild(el("span", "location-text", text));
}

/* ------------------------------------------------------------------ *
 * Terms: s0ma's own definitions of the words this page prints
 * ------------------------------------------------------------------ *
 *
 * /api/graph carries a terms block beside the graph: s0ma's own entry
 * for each of its concepts, copied from the teaching slice s0ma-core
 * ships. A word the page prints in a term position becomes a control
 * when an entry explains it, and the control opens a card with that
 * entry's text, unchanged. Nothing here writes a definition: the page
 * keeps only the pointers above, and those are ids. With no terms
 * block, no word is a control and the page reads as it always has.
 */

/* Take the terms block off a /api/graph document (or the fixture's
 * global). Anything that is not a list of entries reads as none. */
function applyTerms(block) {
  var text = block === undefined ? "" : JSON.stringify(block);
  if (text === state.termsText) {
    return;
  }
  state.termsText = text;
  var raw = block && Array.isArray(block.entries) ? block.entries : [];
  var entries = [];
  var byId = {};
  var byName = {};
  for (var i = 0; i < raw.length; i += 1) {
    var entry = raw[i];
    if (
      !entry ||
      typeof entry.id !== "string" ||
      typeof entry.name !== "string" ||
      typeof entry.summary !== "string"
    ) {
      continue;
    }
    entries.push(entry);
    byId[entry.id] = entry;
    var names = Array.isArray(entry.names) ? entry.names : [];
    for (var j = 0; j < names.length; j += 1) {
      var key = termKey(names[j]);
      if (key && !Object.prototype.hasOwnProperty.call(byName, key)) {
        byName[key] = entry;
      }
    }
  }
  state.terms = {
    source: entries.length > 0 && block.source ? block.source : null,
    entries: entries,
    byId: byId,
    byName: byName,
  };
  if (entries.length === 0 && state.dictionary.open) {
    closeDictionaryState();
    state.selection = null;
    ui.inspector.hidden = true;
    clear(ui.inspector);
  }
  syncTermsButton();
  renderLegendTerms();
}

/* How a word and a name are compared: lowercased, and without the
 * trailing colon the dictionary writes on a line name (`uses:`). */
function termKey(word) {
  var text = String(word).toLowerCase();
  if (text.length > 1 && text.charAt(text.length - 1) === ":") {
    text = text.slice(0, -1);
  }
  return text;
}

/* The one resolver: the entry of s0ma's dictionary that explains
 * `word` where it is printed, or null. A role points through
 * TERM_POINTERS; a contract line through CONTRACT_FIELD_POINTERS;
 * otherwise the entry whose names hold the word. No match is no
 * control, and the word is drawn exactly as it is without one. */
function resolveTerm(word, role) {
  if (state.terms.entries.length === 0) {
    return null;
  }
  if (word === undefined || word === null || word === "") {
    return null;
  }
  var byId = state.terms.byId;
  if (role && Object.prototype.hasOwnProperty.call(TERM_POINTERS, role)) {
    return byId[TERM_POINTERS[role]] || null;
  }
  var text = String(word);
  if (Object.prototype.hasOwnProperty.call(CONTRACT_FIELD_POINTERS, text)) {
    return byId[CONTRACT_FIELD_POINTERS[text]] || null;
  }
  var key = termKey(text);
  if (Object.prototype.hasOwnProperty.call(state.terms.byName, key)) {
    return state.terms.byName[key];
  }
  return null;
}

/* Whether `word` is one of the entry's own names, so the card need not
 * say where it is explained. */
function isOwnName(entry, word) {
  var key = termKey(word);
  var names = Array.isArray(entry.names) ? entry.names : [];
  for (var i = 0; i < names.length; i += 1) {
    if (termKey(names[i]) === key) {
      return true;
    }
  }
  return false;
}

/* A word in a term position of the inspector, as a real button that
 * opens its card under the row, or null when no entry explains it. */
function inspectorTerm(word, role, className) {
  var entry = resolveTerm(word, role);
  if (!entry) {
    return null;
  }
  var text = String(word);
  var button = el("button", "term-control " + className, text);
  button.type = "button";
  button.setAttribute("aria-expanded", "false");
  var seen = ui.termSeen[text] || 0;
  ui.termSeen[text] = seen + 1;
  button.setAttribute("data-term-key", text + "#" + seen);
  button.sh0wTerm = { word: text, entry: entry };
  button.addEventListener("click", function () {
    toggleTermCard(button);
  });
  return button;
}

/* The card: where the word is explained when it is not the entry's own
 * name, the entry's summary, its definition behind "Read more", and the
 * command that prints the whole entry. Every sentence is the entry's
 * own, unchanged. */
function termCard(tag, word, entry, memory) {
  var card = el(tag, "term-card");
  if (word !== null && !isOwnName(entry, word)) {
    var under = el("p", "term-card-under");
    under.appendChild(el("code", "term", word));
    under.appendChild(document.createTextNode(" is explained under "));
    under.appendChild(el("code", "term", entry.name));
    card.appendChild(under);
  }
  card.appendChild(el("p", "term-card-summary", entry.summary));
  if (typeof entry.definition === "string" && entry.definition) {
    var more = el("details", "term-card-more");
    more.open = Boolean(memory.more);
    more.addEventListener("toggle", function () {
      memory.more = more.open;
    });
    more.appendChild(el("summary", null, "Read more"));
    more.appendChild(el("p", "term-card-definition", entry.definition));
    card.appendChild(more);
  }
  var full = el("p", "term-card-entry");
  full.appendChild(document.createTextNode("Full entry: "));
  full.appendChild(el("code", "term-card-command", "s0ma docs show " + entry.id));
  card.appendChild(full);
  return card;
}

/* The row a control sits in, and the element its card goes under: the
 * header subtitle for a header word, the definition for a field name
 * in a list, and otherwise the row itself. */
function termCardAnchor(button) {
  var row = button.closest(
    ".inspector-tagline, .inspector-where, .field-label, dt, .rel-head, li"
  );
  if (!row) {
    return button;
  }
  if (/\binspector-(tagline|where)\b/.test(row.className)) {
    return ui.inspector.querySelector(".inspector-where") || row;
  }
  if (row.tagName === "DT" && row.nextElementSibling && row.nextElementSibling.tagName === "DD") {
    return row.nextElementSibling;
  }
  return row;
}

function cardTagFor(anchor) {
  var parent = anchor.parentNode && anchor.parentNode.tagName;
  if (parent === "DL") {
    return "dd";
  }
  if (parent === "UL" || parent === "OL") {
    return "li";
  }
  return "div";
}

function selectionKey(selection) {
  if (!selection) {
    return null;
  }
  return selection.type + " " + (selection.type === "edge" ? selection.key : selection.id);
}

function toggleTermCard(button) {
  var wasOpen = ui.termCardButton === button;
  closeTermCard();
  if (wasOpen) {
    state.termCard = { selection: null, key: null, more: false };
    return;
  }
  state.termCard = {
    selection: selectionKey(state.selection),
    key: button.getAttribute("data-term-key"),
    more: false,
  };
  openTermCard(button);
}

function openTermCard(button) {
  var term = button.sh0wTerm;
  var anchor = termCardAnchor(button);
  var card = termCard(cardTagFor(anchor), term.word, term.entry, state.termCard);
  anchor.parentNode.insertBefore(card, anchor.nextSibling);
  button.setAttribute("aria-expanded", "true");
  ui.termCard = card;
  ui.termCardButton = button;
}

function closeTermCard() {
  if (ui.termCard && ui.termCard.parentNode) {
    ui.termCard.parentNode.removeChild(ui.termCard);
  }
  if (ui.termCardButton) {
    ui.termCardButton.setAttribute("aria-expanded", "false");
  }
  ui.termCard = null;
  ui.termCardButton = null;
}

/* After the inspector is drawn again: the card stays open on a repaint
 * of the same selection, and closes when the selection has changed. */
function restoreTermCard() {
  var wanted = state.termCard;
  if (!wanted.key || wanted.selection !== selectionKey(state.selection)) {
    state.termCard = { selection: null, key: null, more: false };
    return;
  }
  var buttons = ui.inspector.querySelectorAll("button[data-term-key]");
  for (var i = 0; i < buttons.length; i += 1) {
    if (buttons[i].getAttribute("data-term-key") === wanted.key) {
      openTermCard(buttons[i]);
      return;
    }
  }
  state.termCard = { selection: null, key: null, more: false };
}

/* The legend's glyph names: a control that opens the dictionary on the
 * glyph's entry, or the plain word when no entry explains it. The
 * legend lets the canvas take the pointer everywhere but its buttons. */
function renderLegendTerms() {
  var records = ui.legendTerms || [];
  for (var i = 0; i < records.length; i += 1) {
    var record = records[i];
    var entry = resolveTerm(record.word, null);
    var next;
    if (entry) {
      next = el("button", "term-control legend-term", record.word);
      next.type = "button";
      next.setAttribute("aria-expanded", "false");
      next.addEventListener(
        "click",
        (function (entryId) {
          return function () {
            openDictionary(entryId);
          };
        })(entry.id)
      );
    } else {
      next = el("span", null, record.word);
    }
    record.item.replaceChild(next, record.node);
    record.node = next;
    record.entryId = entry ? entry.id : null;
  }
  syncTermsButton();
}

function syncTermsButton() {
  if (!ui.termsButton) {
    return;
  }
  var has = state.terms.entries.length > 0;
  ui.termsButton.hidden = !has;
  ui.termsButton.setAttribute("aria-pressed", String(state.dictionary.open));
  var records = ui.legendTerms || [];
  for (var i = 0; i < records.length; i += 1) {
    if (records[i].entryId) {
      records[i].node.setAttribute(
        "aria-expanded",
        String(state.dictionary.open && state.dictionary.entry === records[i].entryId)
      );
    }
  }
}

/* The toolbar's terms button. Closed, it opens the dictionary. Open,
 * it goes back to the part the dictionary was opened from, as "back
 * to" does, when that part still exists, and otherwise closes the
 * panel. */
function toggleDictionary() {
  if (state.dictionary.open) {
    var back = state.dictionary.back;
    if (back && selectionStillExists(back)) {
      select(back);
      ui.inspector.focus();
      return;
    }
    clearSelection();
    return;
  }
  openDictionary(null);
}

function closeDictionaryState() {
  state.dictionary = { open: false, entry: null, back: null, rest: false };
  state.dictionaryCard = { more: false };
  syncTermsButton();
}

/* Open the dictionary in the right panel, with `entryId` open and in
 * view when one is named. A part selected at that moment is kept as
 * the place "back to" returns to. */
function openDictionary(entryId) {
  if (state.terms.entries.length === 0) {
    return;
  }
  if (!state.dictionary.open) {
    state.dictionary = {
      open: true,
      entry: null,
      back: state.selection,
      rest: false,
    };
  }
  state.dictionary.entry = entryId;
  state.dictionaryCard = { more: false };
  if (entryId && !pageTermIds()[entryId]) {
    state.dictionary.rest = true;
  }
  state.selection = null;
  state.termCard = { selection: null, key: null, more: false };
  applySelection();
  syncTermsButton();
  renderInspector();
  ui.inspector.scrollTop = 0;
  var row = entryId ? ui.dictionaryRows[entryId] : null;
  if (row) {
    row.item.scrollIntoView({ block: "nearest" });
    row.name.focus();
  } else {
    ui.inspector.focus();
  }
}

/* The entries this page's own term positions can resolve to. */
function pageTermIds() {
  var ids = {};
  for (var i = 0; i < PAGE_TERM_WORDS.length; i += 1) {
    var entry = resolveTerm(PAGE_TERM_WORDS[i][0], PAGE_TERM_WORDS[i][1]);
    if (entry) {
      ids[entry.id] = true;
    }
  }
  return ids;
}

function compareEntryNames(a, b) {
  return (
    compareStrings(a.name.toLowerCase(), b.name.toLowerCase()) ||
    compareStrings(a.id, b.id)
  );
}

function selectionStillExists(selection) {
  if (!selection || !state.model) {
    return false;
  }
  if (selection.type === "node") {
    return Boolean(state.model.components[selection.id]);
  }
  if (selection.type === "module") {
    return Boolean(state.model.modules[selection.id]);
  }
  if (selection.type === "integration") {
    return Boolean(state.model.integrationsById[selection.id]);
  }
  var groups = state.layout ? state.layout.edgeGroups : [];
  for (var i = 0; i < groups.length; i += 1) {
    if (groups[i].key === selection.key) {
      return true;
    }
  }
  return false;
}

function selectionName(selection) {
  if (selection.type === "node") {
    return shortName(selection.id);
  }
  if (selection.type === "integration") {
    return state.model.integrationsById[selection.id].name;
  }
  if (selection.type === "module") {
    return selection.id;
  }
  return "the edge";
}

/* The dictionary: s0ma's entries for the words this page can show,
 * then the rest behind one closed disclosure. A row is the entry's
 * name and its summary; opening it puts the card in the summary's
 * place. One row open at a time. */
function renderDictionary() {
  ui.dictionaryRows = {};
  var head = el("div", "inspector-head");
  head.appendChild(el("h2", "inspector-title", "Terms"));
  var close = el("button", "btn inspector-close", "close");
  close.type = "button";
  close.setAttribute("aria-label", "close terms (Esc)");
  close.addEventListener("click", clearSelection);
  head.appendChild(close);
  ui.inspector.appendChild(head);

  var source = state.terms.source;
  var version = source && source.release_version ? " " + source.release_version : "";
  ui.inspector.appendChild(
    el("p", "terms-source", "s0ma's own definitions, from s0ma" + version)
  );

  var back = state.dictionary.back;
  if (back && selectionStillExists(back)) {
    var backButton = el("button", "btn terms-back", "back to " + selectionName(back));
    backButton.type = "button";
    backButton.addEventListener("click", function () {
      select(back);
      ui.inspector.focus();
    });
    ui.inspector.appendChild(backButton);
  }

  var onPage = pageTermIds();
  var shown = [];
  var rest = [];
  var entries = state.terms.entries;
  for (var i = 0; i < entries.length; i += 1) {
    (onPage[entries[i].id] ? shown : rest).push(entries[i]);
  }
  shown.sort(compareEntryNames);
  rest.sort(compareEntryNames);

  var section = el("section", "inspector-section terms-section");
  section.appendChild(el("h3", "section-label", "On this page"));
  section.appendChild(dictionaryList(shown));
  ui.inspector.appendChild(section);

  if (rest.length > 0) {
    var more = el("details", "inspector-more terms-more");
    more.open = state.dictionary.rest;
    more.addEventListener("toggle", function () {
      state.dictionary.rest = more.open;
    });
    more.appendChild(
      el(
        "summary",
        "inspector-more-summary",
        rest.length +
          (rest.length === 1 ? " more term from s0ma" : " more terms from s0ma")
      )
    );
    more.appendChild(dictionaryList(rest));
    ui.inspector.appendChild(more);
  }
}

function dictionaryList(entries) {
  var list = el("ul", "rel-list terms-list");
  for (var i = 0; i < entries.length; i += 1) {
    list.appendChild(dictionaryRow(entries[i]));
  }
  return list;
}

function dictionaryRow(entry) {
  var item = el("li", "rel-item terms-row");
  var name = el("button", "term-control terms-name", entry.name);
  name.type = "button";
  name.addEventListener("click", function () {
    toggleDictionaryRow(entry.id);
  });
  item.appendChild(name);
  var row = { item: item, name: name, body: null, entry: entry };
  ui.dictionaryRows[entry.id] = row;
  setDictionaryRowOpen(row, state.dictionary.entry === entry.id);
  return item;
}

function setDictionaryRowOpen(row, open) {
  var body = open
    ? termCard("div", null, row.entry, state.dictionaryCard)
    : el("p", "terms-summary", row.entry.summary);
  if (row.body) {
    row.item.replaceChild(body, row.body);
  } else {
    row.item.appendChild(body);
  }
  row.body = body;
  row.name.setAttribute("aria-expanded", String(open));
}

function toggleDictionaryRow(entryId) {
  var current = state.dictionary.entry;
  if (current && ui.dictionaryRows[current]) {
    setDictionaryRowOpen(ui.dictionaryRows[current], false);
  }
  state.dictionaryCard = { more: false };
  if (current === entryId) {
    state.dictionary.entry = null;
  } else {
    state.dictionary.entry = entryId;
    setDictionaryRowOpen(ui.dictionaryRows[entryId], true);
  }
  syncTermsButton();
}

/* ------------------------------------------------------------------ *
 * What changed since you opened this page
 * ------------------------------------------------------------------ *
 *
 * The beat says what a build changed for a few seconds; this list keeps
 * saying it. One entry per build that added, changed, or removed
 * something a part declares, newest first. A build that only moved
 * lines or only changed freshness makes no entry and uses no number.
 *
 * Nothing here is inferred: every line is read off the two graphs the
 * page really received, the one on screen and the one that replaced it
 * (diffGraphs). A build that follows "nothing is built" is said to be
 * the first build, because the page was told so.
 *
 * It lives only in this page's memory. Nothing is written anywhere: no
 * storage of any kind, no file, no request. A reload clears it. It
 * keeps the newest CHANGES_KEPT entries and says how many have dropped.
 * It carries no clock time, because this file reads no clock.
 *
 * Part names are DSL names, set in the monospace face; a name the
 * current graph still carries is the same control a relationship row
 * uses, and selects the part as a click on it does. A name that is gone
 * is plain text. The pane follows the view toggles as the canvas does:
 * a part they hide is counted in one line, not listed.
 */

function buildChangesPane(host) {
  ui.changes = el("aside", "changes");
  ui.changes.setAttribute("aria-label", "what changed since you opened this page");
  ui.changes.setAttribute("tabindex", "-1");
  ui.changes.appendChild(
    el("h2", "changes-title", "What changed since you opened this page")
  );
  ui.changesEmpty = el(
    "p",
    "changes-empty",
    "Nothing yet. Each build that lands is listed here and stays until you reload."
  );
  ui.changes.appendChild(ui.changesEmpty);
  ui.changesList = el("ol", "changes-list");
  ui.changesList.setAttribute("aria-live", "polite");
  ui.changes.appendChild(ui.changesList);
  ui.changesFoot = el("p", "changes-foot");
  ui.changesFoot.hidden = true;
  ui.changes.appendChild(ui.changesFoot);
  host.appendChild(ui.changes);
}

/* Keep one build's changes. Called only for a delta that touched a
 * part (deltaChangesParts), so a build that changed nothing declared
 * makes no entry. Each part keeps what the view toggles need to know
 * about it, read from the graph it was in. */
function recordChange(delta, previousGraph, nextGraph, firstBuild) {
  var record = changeRecord(delta, previousGraph, nextGraph);
  state.changes.made += 1;
  record.number = state.changes.made;
  record.firstBuild = firstBuild;
  state.changes.entries.unshift(record);
  while (state.changes.entries.length > CHANGES_KEPT) {
    state.changes.entries.pop();
    state.changes.dropped += 1;
  }
}

function changeRecord(delta, previousGraph, nextGraph) {
  var record = { added: [], changed: [], removed: [] };
  var nextComponents = nextGraph.components || {};
  var previousComponents = previousGraph.components || {};
  var ids = Object.keys(delta.added).sort(compareStrings);
  var i;
  for (i = 0; i < ids.length; i += 1) {
    record.added.push(changePart(ids[i], nextComponents[ids[i]]));
  }
  ids = Object.keys(delta.changed).sort(compareStrings);
  for (i = 0; i < ids.length; i += 1) {
    var part = changePart(ids[i], nextComponents[ids[i]]);
    part.lines = delta.changed[ids[i]].slice();
    record.changed.push(part);
  }
  ids = Object.keys(delta.removed).sort(compareStrings);
  for (i = 0; i < ids.length; i += 1) {
    record.removed.push(changePart(ids[i], previousComponents[ids[i]]));
  }
  return record;
}

function changePart(canonicalId, component) {
  var known = component || {};
  return {
    id: canonicalId,
    declarationType: known.declaration_type || null,
    layer: known.layer || null,
  };
}

/* The same two rules isComponentVisible applies, on what the entry
 * kept, so a removed part is judged the way it was drawn. */
function changePartInView(part) {
  if (TEST_AND_DOC_TYPES[part.declarationType] && !state.toggles.tests) {
    return false;
  }
  if (part.layer === "FRAMEWORK" && !state.toggles.framework) {
    return false;
  }
  return true;
}

function toggleChanges() {
  state.changes.shown = !state.changes.shown;
  renderChanges();
}

/* The column holds the list and narration; it goes only when both do. */
function syncSideColumn() {
  if (!ui.sideColumn) {
    return;
  }
  var narrating = Boolean(ui.narration) && !ui.narration.hidden;
  setClassFlag(ui.sideColumn, "has-narration", narrating);
  ui.sideColumn.hidden = !state.changes.shown && !narrating;
}

function renderChanges() {
  if (!ui.changes) {
    return;
  }
  ui.changesButton.setAttribute("aria-pressed", String(state.changes.shown));
  ui.changes.hidden = !state.changes.shown;
  syncSideColumn();
  var entries = state.changes.entries;
  ui.changesEmpty.hidden = entries.length > 0;
  var items = [];
  for (var i = 0; i < entries.length; i += 1) {
    items.push(changeEntryItem(entries[i]));
  }
  reconcileChangeItems(items);
  var dropped = state.changes.dropped;
  ui.changesFoot.hidden = dropped === 0;
  ui.changesFoot.textContent =
    dropped === 1
      ? "1 earlier build is not listed."
      : dropped + " earlier builds are not listed.";
}

/* The list is a polite live region, so it is updated in place: an entry
 * that reads exactly as before is left alone, and only a new or
 * different one is put in. A screen reader hears the new build, not the
 * whole list again. */
function reconcileChangeItems(items) {
  var list = ui.changesList;
  for (var i = 0; i < items.length; i += 1) {
    var current = list.childNodes[i] || null;
    if (current && current.isEqualNode(items[i])) {
      continue;
    }
    if (
      current &&
      current.getAttribute("data-entry") === items[i].getAttribute("data-entry")
    ) {
      list.replaceChild(items[i], current);
    } else {
      list.insertBefore(items[i], current);
    }
  }
  while (list.childNodes.length > items.length) {
    list.removeChild(list.lastChild);
  }
}

function changeEntryItem(entry) {
  var item = el("li", "changes-item");
  item.setAttribute("data-entry", String(entry.number));
  var hidden = {};
  var added = changePartsInView(entry.added, hidden);
  var changed = changePartsInView(entry.changed, hidden);
  var removed = changePartsInView(entry.removed, hidden);

  var head = el("p", "changes-head");
  head.appendChild(el("strong", null, "Build " + entry.number));
  head.appendChild(el("span", "label-sep", " · "));
  head.appendChild(
    document.createTextNode(
      (entry.firstBuild ? "the first build, " : "") +
        changeCounts(added.length, changed.length, removed.length)
    )
  );
  item.appendChild(head);

  var i;
  if (added.length > 0) {
    var addedLine = el("p", "changes-line");
    addedLine.appendChild(el("span", "changes-verb", "added "));
    for (i = 0; i < added.length; i += 1) {
      if (i > 0) {
        addedLine.appendChild(document.createTextNode(", "));
      }
      addedLine.appendChild(changePartName(added[i].id));
    }
    item.appendChild(addedLine);
  }
  for (i = 0; i < changed.length; i += 1) {
    var changedLine = el("p", "changes-line");
    changedLine.appendChild(el("span", "changes-verb", "changed "));
    changedLine.appendChild(changePartName(changed[i].id));
    changedLine.appendChild(document.createTextNode(": "));
    var lines = changed[i].lines;
    for (var j = 0; j < lines.length; j += 1) {
      if (j > 0) {
        changedLine.appendChild(document.createTextNode(", "));
      }
      if (lines[j] === "dependencies") {
        changedLine.appendChild(document.createTextNode("dependencies"));
      } else {
        changedLine.appendChild(el("code", "term", lines[j]));
      }
    }
    item.appendChild(changedLine);
  }
  if (removed.length > 0) {
    var removedLine = el("p", "changes-line");
    removedLine.appendChild(el("span", "changes-verb", "removed "));
    for (i = 0; i < removed.length; i += 1) {
      if (i > 0) {
        removedLine.appendChild(document.createTextNode(", "));
      }
      removedLine.appendChild(changeGoneName(removed[i].id));
    }
    item.appendChild(removedLine);
  }
  var hiddenCount = Object.keys(hidden).length;
  if (hiddenCount > 0) {
    item.appendChild(
      el(
        "p",
        "changes-hidden",
        hiddenCount === 1
          ? "1 more part is hidden by the toolbar toggles."
          : hiddenCount + " more parts are hidden by the toolbar toggles."
      )
    );
  }
  return item;
}

function changePartsInView(parts, hidden) {
  var out = [];
  for (var i = 0; i < parts.length; i += 1) {
    if (changePartInView(parts[i])) {
      out.push(parts[i]);
    } else {
      hidden[parts[i].id] = true;
    }
  }
  return out;
}

/* "added 2 parts, changed 1": the noun rides on the first count only,
 * singular and plural right. */
function changeCounts(added, changed, removed) {
  var phrases = [];
  var counts = [
    ["added", added],
    ["changed", changed],
    ["removed", removed],
  ];
  for (var i = 0; i < counts.length; i += 1) {
    var n = counts[i][1];
    if (n === 0) {
      continue;
    }
    var noun = phrases.length > 0 ? "" : n === 1 ? " part" : " parts";
    phrases.push(counts[i][0] + " " + n + noun);
  }
  if (phrases.length === 0) {
    return "no parts in view";
  }
  return phrases.join(", ");
}

/* A part the current graph carries is the relationship rows' own
 * control; one it no longer carries is plain text, never a dead one. */
function changePartName(canonicalId) {
  if (state.model && state.model.components[canonicalId]) {
    var control = peerControl(canonicalId);
    setClassFlag(control, "changes-name", true);
    return control;
  }
  return changeGoneName(canonicalId);
}

function changeGoneName(canonicalId) {
  var name = el("code", "changes-name", shortName(canonicalId));
  name.title = canonicalId;
  return name;
}

/* ------------------------------------------------------------------ *
 * Narration — the agent's account of its own work
 * ------------------------------------------------------------------ *
 *
 * A second kind of truth, and the pane says so out loud: every entry
 * here was written by an agent about itself, and studi0 verified none
 * of it. The visual language is deliberately unlike the graph's — a
 * sunken surface, a dashed edge, no glyphs and no checkmarks — so no
 * reader can take a narration for a declaration. Provenance is stated
 * in words, not only in styling, and the counts say plainly how much
 * is not shown and how many lines were unreadable.
 */

/* Take the narration block off a /api/state document. A server that has
 * never seen a narration says so with an empty window and two zeros;
 * a document without the block at all (an older studi0) is read the
 * same way rather than guessed about. */
function applyNarration(stateDoc) {
  var block = (stateDoc && stateDoc.narration) || {};
  var entries = block.entries || [];
  state.narration = {
    entries: entries,
    total: typeof block.total === "number" ? block.total : entries.length,
    invalid: typeof block.invalid === "number" ? block.invalid : 0,
  };
  renderNarration();
  syncNarrationFocus();
}

/* The newest narration steers the canvas, and only the newest, and only
 * once: whatever it names is selected exactly as a click would select
 * it. Names the graph does not carry move nothing — no error, no
 * message, no guess at what was meant (GP-3 silence). */
function syncNarrationFocus() {
  var entries = state.narration.entries;
  if (!entries.length || !state.model) {
    return;
  }
  var newest = entries[entries.length - 1];
  var ordinal = typeof newest.n === "number" ? newest.n : 0;
  if (ordinal <= state.narrationFocused) {
    return;
  }
  /* Marked as acted on either way: an unresolvable narration is not
   * retried on every poll, it is simply not a focus instruction. */
  state.narrationFocused = ordinal;
  var subject = firstKnownSubject(newest.subjects);
  if (subject) {
    select({ type: "node", id: subject });
  }
}

/* The FIRST subject the current graph actually carries — declared
 * order, so which one wins is the narration's choice and not ours. */
function firstKnownSubject(subjects) {
  if (!subjects || !state.model) {
    return null;
  }
  for (var i = 0; i < subjects.length; i += 1) {
    if (state.model.components[subjects[i]]) {
      return subjects[i];
    }
  }
  return null;
}

function renderNarration() {
  if (!ui.narration) {
    return;
  }
  clear(ui.narration);
  var narration = state.narration;
  var entries = narration.entries;
  if (!entries.length && !narration.invalid) {
    ui.narration.hidden = true;
    syncSideColumn();
    return;
  }
  ui.narration.hidden = false;
  syncSideColumn();

  var head = el("div", "narration-head");
  head.appendChild(el("h2", "narration-title", "agent narration"));
  ui.narration.appendChild(head);
  /* The provenance line, in words: this is what an agent SAID, and
   * nothing on this pane was checked against the project. */
  ui.narration.appendChild(
    el(
      "p",
      "narration-provenance",
      "self-reported by the agent working here — not verified against " +
        "the build. The graph beside it is the canonical truth."
    )
  );

  var shown = entries.slice(Math.max(0, entries.length - NARRATION_SHOWN));
  var list = el("ol", "narration-list");
  /* Newest at top: the list is built in reverse and told so, rather
   * than reversed visually, so a screen reader hears the same order a
   * reader sees. */
  list.setAttribute("reversed", "reversed");
  for (var i = shown.length - 1; i >= 0; i -= 1) {
    list.appendChild(narrationItem(shown[i]));
  }
  ui.narration.appendChild(list);

  ui.narration.appendChild(narrationFoot(narration, shown.length));
}

function narrationItem(entry) {
  var item = el("li", "narration-item");
  item.appendChild(el("p", "narration-movement", String(entry.movement)));
  if (entry.why) {
    item.appendChild(el("p", "narration-why", String(entry.why)));
  }

  var meta = el("div", "narration-meta");
  var phase = String(entry.phase);
  meta.appendChild(
    el("span", "chip chip--phase", PHASE_LABEL[phase] || phase)
  );

  var subjects = entry.subjects || [];
  for (var i = 0; i < subjects.length; i += 1) {
    meta.appendChild(narrationSubject(String(subjects[i])));
  }
  item.appendChild(meta);
  return item;
}

/* A subject the graph carries is a button that selects it — the same
 * path a click on the node takes. A subject the graph does not carry is
 * shown as text, labelled for what it is: a name studi0 cannot find. It
 * is never hidden, because the agent did say it. */
function narrationSubject(canonicalId) {
  if (state.model && state.model.components[canonicalId]) {
    var button = el("button", "narration-subject", shortName(canonicalId));
    button.type = "button";
    button.title = canonicalId;
    button.setAttribute("aria-label", "show " + canonicalId + " in the graph");
    button.addEventListener("click", function () {
      select({ type: "node", id: canonicalId });
    });
    return button;
  }
  var unknown = el("span", "narration-subject narration-subject--unknown");
  unknown.appendChild(el("span", null, shortName(canonicalId)));
  unknown.appendChild(el("span", "narration-unknown-note", "not in this graph"));
  unknown.title = canonicalId;
  return unknown;
}

function narrationFoot(narration, shownCount) {
  var parts = [];
  if (narration.total > shownCount) {
    parts.push(
      shownCount + " of " + narration.total + " narrated movements shown"
    );
  } else {
    parts.push(narration.total + " narrated movements");
  }
  if (narration.invalid) {
    /* Never rendered as narration, never repaired — but never hidden
     * either: a line studi0 could not read is a fact about the log. */
    parts.push(
      narration.invalid +
        (narration.invalid === 1
          ? " line unreadable — not shown"
          : " lines unreadable — not shown")
    );
  }
  var foot = el("p", "narration-foot", parts.join(" · "));
  if (narration.invalid) {
    foot.className = "narration-foot narration-foot--flagged";
  }
  return foot;
}

/* ------------------------------------------------------------------ *
 * Collapse controls
 * ------------------------------------------------------------------ */

function toggleOrgan(moduleName) {
  var current = state.layout && state.layout.organsByModule[moduleName]
    ? state.layout.organsByModule[moduleName].collapsed
    : false;
  state.collapseOverrides[moduleName] = !current;
  render();
}

function setAllCollapsed(collapsed) {
  if (!state.layout) {
    return;
  }
  for (var i = 0; i < state.layout.organs.length; i += 1) {
    state.collapseOverrides[state.layout.organs[i].module] = collapsed;
  }
  render();
}

/* ------------------------------------------------------------------ *
 * Pan, zoom, keyboard
 * ------------------------------------------------------------------ */

function applyViewBox() {
  var box = state.viewBox;
  if (!box) {
    return;
  }
  ui.canvas.setAttribute(
    "viewBox",
    r2(box.x) + " " + r2(box.y) + " " + r2(box.w) + " " + r2(box.h)
  );
}

function fitToView() {
  if (!state.layout) {
    return;
  }
  state.viewBox = {
    x: -FIT_PAD,
    y: -FIT_PAD,
    w: state.layout.width + FIT_PAD * 2,
    h: state.layout.height + FIT_PAD * 2,
  };
  applyViewBox();
}

function zoomBy(factor, focus) {
  if (!state.viewBox) {
    return;
  }
  var box = state.viewBox;
  var limitW = state.layout ? state.layout.width * 8 + 400 : 40000;
  var newW = Math.max(160, Math.min(limitW, box.w * factor));
  var scale = newW / box.w;
  var point = focus || { x: box.x + box.w / 2, y: box.y + box.h / 2 };
  state.viewBox = {
    x: point.x - (point.x - box.x) * scale,
    y: point.y - (point.y - box.y) * scale,
    w: box.w * scale,
    h: box.h * scale,
  };
  applyViewBox();
}

function clientToUser(clientX, clientY, matrix) {
  var ctm = matrix || ui.canvas.getScreenCTM();
  if (!ctm) {
    return null;
  }
  var point = ui.canvas.createSVGPoint();
  point.x = clientX;
  point.y = clientY;
  return point.matrixTransform(ctm.inverse ? ctm.inverse() : ctm);
}

function attachCanvasInteraction() {
  var panning = null;
  var suppressClick = false;

  ui.canvas.addEventListener("wheel", function (event) {
    if (!state.viewBox) {
      return;
    }
    event.preventDefault();
    var focus = clientToUser(event.clientX, event.clientY);
    var factor = event.deltaY > 0 ? 1.12 : 1 / 1.12;
    zoomBy(factor, focus || undefined);
  });

  function onPointerMove(event) {
    if (!panning || !panning.start) {
      return;
    }
    var current = clientToUser(event.clientX, event.clientY, panning.matrix);
    if (!current) {
      return;
    }
    var dx = current.x - panning.start.x;
    var dy = current.y - panning.start.y;
    if (!panning.moved) {
      /* Below the threshold this is a click, not a drag: leave the
       * view alone so selecting a node does not nudge the canvas. */
      if (Math.abs(dx) <= 2 && Math.abs(dy) <= 2) {
        return;
      }
      panning.moved = true;
      ui.canvas.classList.add("is-panning");
    }
    state.viewBox = {
      x: panning.box.x - dx,
      y: panning.box.y - dy,
      w: panning.box.w,
      h: panning.box.h,
    };
    applyViewBox();
  }

  function onPointerUp() {
    if (!panning) {
      return;
    }
    suppressClick = panning.moved;
    panning = null;
    ui.canvas.classList.remove("is-panning");
    window.removeEventListener("pointermove", onPointerMove);
    window.removeEventListener("pointerup", onPointerUp);
    window.removeEventListener("pointercancel", onPointerUp);
  }

  ui.canvas.addEventListener("pointerdown", function (event) {
    if (event.button !== 0 || !state.viewBox) {
      return;
    }
    var ctm = ui.canvas.getScreenCTM();
    if (!ctm) {
      return;
    }
    /* Deliberately no setPointerCapture: capturing retargets the
     * following click to the canvas, which would swallow every click
     * on a node. The window listeners below keep a drag alive outside
     * the canvas without that cost. */
    panning = {
      matrix: ctm,
      start: clientToUser(event.clientX, event.clientY, ctm),
      box: {
        x: state.viewBox.x,
        y: state.viewBox.y,
        w: state.viewBox.w,
        h: state.viewBox.h,
      },
      moved: false,
    };
    window.addEventListener("pointermove", onPointerMove);
    window.addEventListener("pointerup", onPointerUp);
    window.addEventListener("pointercancel", onPointerUp);
  });

  /* A click on empty canvas clears the selection; the click that ends
   * a drag does not. */
  ui.canvas.addEventListener("click", function () {
    if (suppressClick) {
      suppressClick = false;
      return;
    }
    if (state.selection) {
      clearSelection();
    }
  });
}

function panBy(dxFraction, dyFraction) {
  if (!state.viewBox) {
    return;
  }
  state.viewBox = {
    x: state.viewBox.x + state.viewBox.w * dxFraction,
    y: state.viewBox.y + state.viewBox.h * dyFraction,
    w: state.viewBox.w,
    h: state.viewBox.h,
  };
  applyViewBox();
}

function onDocumentKeyDown(event) {
  var target = event.target;
  if (
    target &&
    target.tagName &&
    /^(INPUT|TEXTAREA|SELECT)$/.test(target.tagName)
  ) {
    return;
  }

  if (event.key === "Escape") {
    if (state.selection || state.dictionary.open) {
      clearSelection();
      event.preventDefault();
    }
    return;
  }
  if (event.metaKey || event.ctrlKey || event.altKey) {
    return;
  }

  /* Enter / Space act on whatever the graph has focused. The focused
   * element handles this itself when the key event reaches it, but SVG
   * focus targeting varies between engines, so the document is the
   * backstop: the keyboard contract must not depend on it. */
  if (event.key === "Enter" || event.key === " ") {
    var active = document.activeElement;
    if (active && active.getAttribute) {
      var focusedNode = active.getAttribute("data-node");
      if (focusedNode) {
        select({ type: "node", id: focusedNode });
        event.preventDefault();
        return;
      }
      var focusedName = active.getAttribute("data-organ-name");
      if (focusedName) {
        select({ type: "module", id: focusedName });
        event.preventDefault();
        return;
      }
      var focusedHeader = active.getAttribute("data-organ-header");
      if (focusedHeader) {
        toggleOrgan(focusedHeader);
        event.preventDefault();
        return;
      }
    }
    return;
  }

  switch (event.key) {
    case "ArrowLeft":
      panBy(-0.08, 0);
      event.preventDefault();
      break;
    case "ArrowRight":
      panBy(0.08, 0);
      event.preventDefault();
      break;
    case "ArrowUp":
      panBy(0, -0.08);
      event.preventDefault();
      break;
    case "ArrowDown":
      panBy(0, 0.08);
      event.preventDefault();
      break;
    case "+":
    case "=":
      zoomBy(0.8);
      event.preventDefault();
      break;
    case "-":
    case "_":
      zoomBy(1 / 0.8);
      event.preventDefault();
      break;
    case "f":
    case "F":
      fitToView();
      event.preventDefault();
      break;
    default:
      break;
  }
}

/* ------------------------------------------------------------------ *
 * Payload application + live loop
 * ------------------------------------------------------------------ */

function applyGraph(graph, stateDoc) {
  /* After the server has said nothing is built, the page has shown that
   * nothing is there, so the first build is a change from an empty graph
   * and each of its parts gets the beat any added part gets. */
  var previous = state.notBuilt ? { components: {} } : state.graph;
  var firstBuild = state.notBuilt;
  state.notBuilt = false;
  var delta = diffGraphs(previous, graph);
  var derived = stateDoc || deriveStateFromGraph(graph);
  var nextStale = (derived.stale_modules || []).slice().sort(compareStrings);
  delta.stale = newlyStale(state.staleModules, nextStale);

  state.delta = delta;
  if (deltaChangesParts(delta)) {
    /* The newest build's additions take the outline over; one that
     * added nothing clears it. */
    state.outlined = {};
    for (var addedId in delta.added) {
      if (Object.prototype.hasOwnProperty.call(delta.added, addedId)) {
        state.outlined[addedId] = true;
      }
    }
    recordChange(delta, previous, graph, firstBuild);
  }
  state.graph = graph;
  state.model = buildModel(graph);
  state.buildStatus = derived.build_status || "missing";
  state.staleModules = nextStale;
  state.error = null;
  /* Only a real change earns the beat. A first payload on a page that
   * opened on a built project is not a change: nothing was on screen to
   * change from. The first build after "nothing is built" is one. */
  state.beatPending = deltaHasAny(delta);

  if (state.selection && state.selection.type === "node") {
    if (!state.model.components[state.selection.id]) {
      state.selection = null;
    }
  }
  if (state.selection && state.selection.type === "module") {
    if (!state.model.modules[state.selection.id]) {
      state.selection = null;
    }
  }
  render();
  renderInspector();
}

/* Which modules crossed into staleness with this reading. A module that
 * was already stale is not news, and a module that just became fresh
 * again says so by dropping its chips. */
function newlyStale(previousStale, nextStale) {
  var flipped = {};
  var was = {};
  var i;
  for (i = 0; i < previousStale.length; i += 1) {
    was[previousStale[i]] = true;
  }
  for (i = 0; i < nextStale.length; i += 1) {
    if (!was[nextStale[i]]) {
      flipped[nextStale[i]] = true;
    }
  }
  return flipped;
}

/* Component-level diff: what the payload added, dropped, or rewrote.
 * `changed` maps each rewritten component to the declared lines that
 * differ (see declaredChanges), so the beat and the list of changes
 * read the same answer. */
function diffGraphs(previous, next) {
  var delta = emptyDelta();
  var nextComponents = (next && next.components) || {};
  var previousComponents = (previous && previous.components) || {};
  var key;
  if (!previous) {
    return delta;
  }
  for (key in nextComponents) {
    if (!Object.prototype.hasOwnProperty.call(nextComponents, key)) {
      continue;
    }
    if (!Object.prototype.hasOwnProperty.call(previousComponents, key)) {
      delta.added[key] = true;
    } else {
      var lines = declaredChanges(previous, next, key);
      if (lines.length > 0) {
        delta.changed[key] = lines;
      }
    }
  }
  for (key in previousComponents) {
    if (
      Object.prototype.hasOwnProperty.call(previousComponents, key) &&
      !Object.prototype.hasOwnProperty.call(nextComponents, key)
    ) {
      delta.removed[key] = true;
    }
  }
  return delta;
}

/* What counts as a change to a part: something it DECLARES differs.
 *
 * Where it sits in its file is not a declaration. A part inserted
 * above another moves that one's line numbers, and the one below has
 * not changed, so `location` is never compared. Everything else on the
 * component's entry is compared one declared line at a time, and each
 * line that differs is named by its own DSL name: `intent` first, then
 * every key under its fields whose value differs (in the inspector's
 * order), then its declaration facts (`kind`, `visibility`, `layer`).
 *
 * Its relationships count too, from its own side only: if the set of
 * things it leans on differs (the relationships its inspector lists
 * under dependencies), the part changed, and that line is named by the
 * plain word "dependencies". A change only in what leans on it is a
 * change to the other part, not to this one. */
var NOT_A_DECLARED_LINE = { location: true, fields: true, intent: true };

function declaredChanges(previousGraph, nextGraph, canonicalId) {
  var before = previousGraph.components[canonicalId] || {};
  var after = nextGraph.components[canonicalId] || {};
  var lines = [];
  var key;
  var i;
  if (!sameDeclared(before.intent, after.intent)) {
    lines.push("intent");
  }
  var beforeFields = before.fields || {};
  var afterFields = after.fields || {};
  var fieldUnion = {};
  for (key in beforeFields) {
    if (Object.prototype.hasOwnProperty.call(beforeFields, key)) {
      fieldUnion[key] = true;
    }
  }
  for (key in afterFields) {
    if (Object.prototype.hasOwnProperty.call(afterFields, key)) {
      fieldUnion[key] = true;
    }
  }
  var fieldKeys = orderedFieldKeys(fieldUnion);
  for (i = 0; i < fieldKeys.length; i += 1) {
    if (!sameDeclared(beforeFields[fieldKeys[i]], afterFields[fieldKeys[i]])) {
      lines.push(fieldKeys[i]);
    }
  }
  var facts = {};
  for (key in before) {
    if (Object.prototype.hasOwnProperty.call(before, key) && !NOT_A_DECLARED_LINE[key]) {
      facts[key] = true;
    }
  }
  for (key in after) {
    if (Object.prototype.hasOwnProperty.call(after, key) && !NOT_A_DECLARED_LINE[key]) {
      facts[key] = true;
    }
  }
  var factKeys = Object.keys(facts).sort(compareStrings);
  for (i = 0; i < factKeys.length; i += 1) {
    if (!sameDeclared(before[factKeys[i]], after[factKeys[i]])) {
      lines.push(factKeys[i]);
    }
  }
  if (
    !sameStringList(
      dependencyKeys(previousGraph, canonicalId),
      dependencyKeys(nextGraph, canonicalId)
    )
  ) {
    lines.push("dependencies");
  }
  return lines;
}

function sameDeclared(a, b) {
  return JSON.stringify(a) === JSON.stringify(b);
}

/* The relationships that leave a part, as its inspector lists them
 * under dependencies (authored and derived, not verification), each
 * reduced to what that row shows: the family, the relation, the part at
 * the other end, and an authored one's `carries`. Sorted, so the order
 * the build wrote them in is not itself a change. */
function dependencyKeys(graph, canonicalId) {
  var edges = (graph && graph.edges) || {};
  var families = ["authored", "derived"];
  var keys = [];
  for (var i = 0; i < families.length; i += 1) {
    var list = edges[families[i]] || [];
    for (var j = 0; j < list.length; j += 1) {
      if (list[j].source === canonicalId) {
        keys.push(
          JSON.stringify([
            families[i],
            list[j].relation || null,
            list[j].target,
            families[i] === "authored" ? list[j].carries : null,
          ])
        );
      }
    }
  }
  return keys.sort(compareStrings);
}

function startLive() {
  state.live = true;
  pollOnce();
  window.setInterval(pollOnce, POLL_INTERVAL_MS);
}

function pollOnce() {
  fetch("/api/state", { cache: "no-store" })
    .then(function (response) {
      if (!response.ok) {
        throw new Error("/api/state responded " + response.status);
      }
      return response.json();
    })
    .then(function (stateDoc) {
      setOffline(false);
      if (stateDoc.error) {
        showError(stateDoc.error.message || "the viewer reported an error");
        return null;
      }
      if (stateDoc.build_status === "missing") {
        /* The server has said nothing is built, so there is no graph to
         * ask for. The viewer is connected; the project is unbuilt. */
        state.seq = stateDoc.seq;
        applyNotBuilt();
        return null;
      }
      if (stateDoc.seq !== state.seq || !state.graph) {
        state.seq = stateDoc.seq;
        /* Narration is applied on the far side of the graph fetch, so
         * a movement that names a component this very build added can
         * still resolve to it. */
        return fetchGraph(stateDoc);
      }
      applyStateOnly(stateDoc);
      applyNarration(stateDoc);
      return null;
    })
    .catch(function () {
      setOffline(true);
    });
}

function fetchGraph(stateDoc) {
  return fetch("/api/graph", { cache: "no-store" })
    .then(function (response) {
      return response.json().then(function (document_) {
        return { ok: response.ok, status: response.status, document: document_ };
      });
    })
    .then(function (answer) {
      var document_ = answer.document;
      /* The graph route's own answer for a project with no build: the
       * server is there and has said so, which is not being offline. */
      if (
        document_ &&
        document_.error &&
        document_.error.code === NOT_BUILT_CODE
      ) {
        applyNotBuilt();
        return;
      }
      if (!answer.ok) {
        throw new Error("/api/graph responded " + answer.status);
      }
      if (document_.error) {
        showError(document_.error.message || "the viewer reported an error");
        return;
      }
      if (typeof document_.seq === "number") {
        state.seq = document_.seq;
      }
      /* Before the graph, so the repaint the graph causes already knows
       * which words s0ma's dictionary explains. */
      applyTerms(document_.terms);
      applyGraph(document_.graph, stateDoc);
      applyNarration(stateDoc);
    });
}

function applyStateOnly(stateDoc) {
  var nextStatus = stateDoc.build_status || state.buildStatus;
  var nextStale = (stateDoc.stale_modules || []).slice().sort(compareStrings);
  if (
    nextStatus === state.buildStatus &&
    sameStringList(nextStale, state.staleModules)
  ) {
    return;
  }
  /* The graph itself did not move, so this is a staleness beat and
   * nothing more: chips appear, ring appears, no motion. */
  state.delta = emptyDelta();
  state.delta.stale = newlyStale(state.staleModules, nextStale);
  state.buildStatus = nextStatus;
  state.staleModules = nextStale;
  state.beatPending = deltaHasAny(state.delta);
  render();
}

/* The server has said nothing is built. Whatever graph was on the page
 * is no longer a build, so it goes, and so does a selection in it. Said
 * again on every poll, so it repaints only the first time. */
function applyNotBuilt() {
  if (state.notBuilt) {
    return;
  }
  state.notBuilt = true;
  state.graph = null;
  state.model = null;
  state.buildStatus = "missing";
  state.staleModules = [];
  state.error = null;
  if (state.selection) {
    state.selection = null;
    renderInspector();
  }
  render();
}

function setOffline(offline) {
  if (state.offline === offline) {
    return;
  }
  state.offline = offline;
  if (!offline) {
    state.offlineDismissed = false;
  }
  renderBanners();
}

function showError(message) {
  state.error = message;
  renderBanners();
}

/* ------------------------------------------------------------------ *
 * Boot
 * ------------------------------------------------------------------ */

function boot() {
  var mount = document.getElementById("s0ma-sh0w");
  if (!mount) {
    mount = document.createElement("div");
    mount.id = "s0ma-sh0w";
    document.body.appendChild(mount);
  }
  buildShell(mount);

  var fixture = window.__S0MA_FIXTURE__;
  if (fixture) {
    /* Fixture mode: one payload, no polling (plan §3.6). An optional
     * second global carries a narration block in the shape /api/state
     * serves, so the pane can be worked on and looked at without a
     * server; absent, applyNarration leaves the pane hidden. A third,
     * optional, carries a terms block in the shape /api/graph serves;
     * absent, the page has no term controls and no terms button. */
    applyTerms(window.__S0MA_TERMS__);
    applyGraph(fixture, deriveStateFromGraph(fixture));
    applyNarration({ narration: window.__S0MA_NARRATION__ });
    return;
  }
  render();
  startLive();
}

if (document.readyState === "loading") {
  document.addEventListener("DOMContentLoaded", boot);
} else {
  boot();
}
