"""Content-hash-based build cache for the s0ma DSL transpiler.

Implements basic caching per PRD §2.7.5: hash-based incremental cache stored
under a hidden ``.s0ma.cache/`` directory (rooted at the project root, *not*
under the build output directory). Cache invalidation is based on file
content hashes (SHA-256) and the version of s0ma-dsl that wrote the
entry. A cache hit skips the entire transpile pipeline for that file.

**Cache layout policy (M6a, feedback 5–6):** The cache directory is *internal*
bookkeeping — it is hidden (leading dot), not a Python package, and never
appears under the build output directory. The build output directory is
the importable contract; the cache directory is implementation detail.
Consumers should never import from the cache; the legacy
``__s0ma_cache__/`` directory is no longer emitted (see ADR-007 and the
"Build Output" section of the spec).

**Cache key (M4, feedback 5–6):** the cache key for each source file is the
declared ``module <name>`` — the canonical identity in s0ma's IR — *not* the
source filename's stem. The intra-module validator enforces ``stem ==
module.name`` (via ``MODULE_NAME_STEM_MISMATCH``) so the two are guaranteed
to agree on any source the cache ever sees, but the cache derives the key
from the module declaration so the canonical identity is the single source
of truth across the IR, the cache, and ``uses:`` import paths.

M7 extension: rendered ``.md`` / ``.html`` / ``.json`` doc outputs are
also tracked. The cache key combines the source ``.s0ma`` content hash
with the doc declaration's transitive content hash (``DocHashIndex``)
plus a digest of the relevant project snapshot slice; any change to a
covered cross-module entity invalidates the cached docs.

Cache layout::

    .s0ma.cache/
        mod_name.py          # Transpiled Python (internal copy, NOT importable)
        mod_name.s0ma.json   # Normalized IR
        mod_name.s0ma.map    # Source map
        mod_name.hash        # SHA-256 of source .s0ma file
        mod_name.docs.json   # Manifest of rendered doc outputs
        docs/<rel-path>      # Cached rendered .md / .html / .json files
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from pathlib import Path

from s0ma.decorators import component
from s0ma.types import ComponentKind, Layer

from s0ma_dsl import __version__

__all__ = [
    "BuildCache",
    "CacheResult",
    "RenderedDocEntry",
    "compute_embed_hashes",
    "extract_module_name",
    "scan_embed_paths",
]


# ---------------------------------------------------------------------------
# Module-name extraction (M4, feedback 5–6)
# ---------------------------------------------------------------------------

# Match the leading ``module <name>`` declaration without invoking the full
# parser. Used by the cache to derive its key from the declared module name
# (the canonical identity) rather than the source file's stem. Robust to
# leading whitespace, blank lines, and comment lines starting with ``#``.
_MODULE_DECL_RE = re.compile(
    r"^\s*module\s+([A-Za-z_][A-Za-z0-9_]*)\b",
    re.MULTILINE,
)

# M12 (feedback 5–6): match ``content: @file("path")`` directives without
# invoking the full parser. The cache needs to know which external files
# a module embeds *before* parsing so the lookup can fold their hashes
# into the cache key. The full parser still does the authoritative parse
# (and produces the precise diagnostic on malformed directives); this
# regex is intentionally permissive — it captures the path inside any
# ``@file("...")`` it encounters, anywhere in the source. The resulting
# false-positive cost is "we read more files than strictly necessary on
# cache lookup", which is harmless. False negatives (missing a real
# embed) would silently break cache invalidation, so the regex covers
# both the canonical ``    content: @file("…")`` form and the more
# tolerant whitespace variants the parser also accepts.
_EMBED_DIRECTIVE_SCAN_RE = re.compile(
    r'@file\s*\(\s*"([^"]*)"\s*\)',
)


def scan_embed_paths(source_path: Path) -> tuple[str, ...]:
    """Return the embed paths declared in *source_path* (M12).

    Reads the source as UTF-8 text and scans for any
    ``@file("path")`` occurrences. Returns the paths verbatim — relative
    paths stay relative; the caller resolves them. Returns an empty
    tuple when the file is unreadable so callers can treat it as
    "no embeds" without a separate try/except.

    Used by the cache pipeline to fold embedded files' hashes into the
    cache key without parsing the source file twice (the authoritative
    parse runs after a cache miss).
    """
    try:
        text = Path(source_path).read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return ()
    return tuple(_EMBED_DIRECTIVE_SCAN_RE.findall(text))


def compute_embed_hashes(
    source_path: Path,
    embed_paths: tuple[str, ...],
) -> tuple[str, ...]:
    """Compute ``"sha256:<hex>"`` for each embed path, in input order.

    Resolves relative paths against ``source_path``'s parent directory.
    Returns ``"sha256:MISSING"`` for any path that cannot be read — the
    parser will surface the same situation as ``EMBEDDED_FILE_NOT_FOUND``
    with full diagnostic context, but the cache still folds a stable
    sentinel into the key so that creating the missing file is a
    cache-miss event.
    """
    base_dir = Path(source_path).resolve().parent
    out: list[str] = []
    for raw_path in embed_paths:
        p = Path(raw_path)
        p = (base_dir / raw_path).resolve() if not p.is_absolute() else p.resolve()
        try:
            data = p.read_bytes()
        except OSError:
            out.append("sha256:MISSING")
            continue
        out.append(f"sha256:{hashlib.sha256(data).hexdigest()}")
    return tuple(out)


def extract_module_name(source_path: Path) -> str:
    """Return the module name declared in a ``.s0ma`` source file.

    Performs a lightweight regex-based scan of the source — the cache
    needs the canonical key *before* the full parser runs, but the
    declaration syntax is simple enough that a regex is sufficient and
    avoids a circular dependency on the parser at import time.

    Falls back to ``source_path.stem`` if no ``module`` declaration is
    found in the first non-blank, non-comment lines. The validator's
    ``MODULE_NAME_STEM_MISMATCH`` check (run on the parsed AST) is the
    authoritative gate for declared-vs-stem alignment; this fallback
    only matters for malformed inputs that will fail parse anyway, and
    keeps the cache from crashing on a missing-header source.
    """
    source_path = Path(source_path)
    try:
        text = source_path.read_text(encoding="utf-8")
    except OSError:
        return source_path.stem

    # Skip leading blank / comment lines and stop at the first real line.
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        match = _MODULE_DECL_RE.match(line)
        if match is not None:
            return match.group(1)
        # First real line was not a module declaration — leave the
        # validator to surface the structural error.
        break

    return source_path.stem


@component(
    name="S0maDSL_RenderedDocEntry",
    kind=ComponentKind.MODEL,
    layer=Layer.FRAMEWORK,
    intent=(
        "One rendered doc output cached alongside the transpiled .py — declared output path and "
        "the cached body bytes."
    ),
    idempotent=True,
    is_framework=True,
)
@dataclass(frozen=True)
class RenderedDocEntry:
    """A single cached rendered doc output.

    The cache stores rendered files inside the cache directory keyed by
    the declaration name; on a hit, the CLI replays them to the
    declared ``output_path``. ``content`` carries the exact bytes the
    renderer produced so re-runs do not need to re-render.
    """

    decl_kind: str
    """Either ``"doc-ref"`` or ``"doc-guide"``."""

    name: str
    """Declaration name."""

    output_path: Path
    """Absolute path the renderer chose for this output."""

    content: str
    """Full rendered document body — restored verbatim on a hit."""


@component(
    name="S0maDSL_CacheResult",
    kind=ComponentKind.MODEL,
    layer=Layer.FRAMEWORK,
    intent="Result of a cache lookup — indicates hit/miss and provides cached file paths on hit.",
    idempotent=True,
    is_framework=True,
)
@dataclass(frozen=True)
class CacheResult:
    """Result of a cache lookup."""

    hit: bool
    """Whether the cache had a valid entry for this source file."""

    cached_py: Path | None = None
    """Path to cached .py file (None on miss)."""

    cached_ir: Path | None = None
    """Path to cached .s0ma.json file (None on miss)."""

    cached_map: Path | None = None
    """Path to cached .s0ma.map file (None on miss)."""

    cached_docs: tuple[RenderedDocEntry, ...] = ()
    """Cached rendered doc outputs the CLI must replay on a hit."""


@component(
    name="S0maDSL_BuildCache",
    kind=ComponentKind.SERVICE,
    layer=Layer.FRAMEWORK,
    intent=(
        "Content-hash-based build cache that stores transpiler outputs and "
        "skips re-transpilation when the source file has not changed."
    ),
    idempotent=True,
    is_framework=True,
)
@dataclass
class BuildCache:
    """Content-hash-based transpiler output cache.

    Stores outputs in a hidden ``.s0ma.cache/`` directory rooted at the
    project root. The cache is internal bookkeeping — it is *not* on
    ``sys.path`` and is *not* the importable build output (which lives at
    ``<project>.build_dir`` per ADR-007). Invalidation is based on SHA-256
    of the raw ``.s0ma`` source text, of any file it embeds, and of the
    version of s0ma-dsl that wrote the entry.
    """

    cache_dir: Path
    """Root directory for cached artifacts."""

    _stats: dict[str, int] = field(default_factory=lambda: {"hits": 0, "misses": 0})

    def __post_init__(self) -> None:
        self.cache_dir = Path(self.cache_dir)

    @property
    def hits(self) -> int:
        return self._stats["hits"]

    @property
    def misses(self) -> int:
        return self._stats["misses"]

    def reset_stats(self) -> None:
        """Reset hit/miss counters."""
        self._stats = {"hits": 0, "misses": 0}

    def lookup(
        self,
        source_path: Path,
        *,
        doc_key: str | None = None,
        module_name: str | None = None,
        extra_dependency_hashes: tuple[str, ...] = (),
        published_dir: Path | None = None,
    ) -> CacheResult:
        """Check if a valid cached build exists for the given source file.

        A cache hit requires:
        1. The hash file exists and matches the current source content hash.
        2. The cached .py file exists.
        3. If *doc_key* is provided, the stored doc-key must match — this
           is the M7 invalidation hook for rendered doc outputs. The
           caller passes the digest of the relevant project slice
           (``DocHashIndex.snapshot`` slice) so changes to covered
           cross-module entities trigger a miss.
        4. If *published_dir* is provided, every artifact the cache holds
           for this module is published there with exactly the cached
           bytes. A directory that no longer holds what the build wrote —
           a file edited by hand, deleted, or replaced by an older one —
           is a miss, and the caller runs the full pipeline, whose
           write-guard decides what becomes of a hand edit. Without this
           a hit kept whatever it found, so an edit the guard refuses on
           every other path survived a rebuild of an unchanged source,
           and the build's answer depended on whether the cache existed
           (the spec says deleting the cache never affects correctness).

        The *module_name* argument is the cache key (M4, feedback 5–6).
        If omitted, it is extracted from the source file's ``module``
        declaration via :func:`extract_module_name`.

        ``extra_dependency_hashes`` (M12, feedback 5–6) folds additional
        content hashes into the comparison: each ``content: @file("path")``
        embed on a CONSTANT cell contributes its embedded file's hash so
        editing the embedded file invalidates the consuming module's
        cache. The caller (parser/IR pipeline) passes a tuple of
        ``"sha256:<hex>"`` strings in deterministic order; an empty
        tuple is the pre-M12 behaviour.
        """
        source_path = Path(source_path)
        key = module_name if module_name is not None else extract_module_name(source_path)

        hash_path = self.cache_dir / f"{key}.hash"
        py_path = self.cache_dir / f"{key}.py"
        ir_path = self.cache_dir / f"{key}.s0ma.json"
        map_path = self.cache_dir / f"{key}.s0ma.map"
        doc_key_path = self.cache_dir / f"{key}.docs.key"
        docs_manifest_path = self.cache_dir / f"{key}.docs.json"

        if not hash_path.exists() or not py_path.exists():
            self._stats["misses"] += 1
            return CacheResult(hit=False)

        # Compare content hashes
        current_hash = self._compose_source_hash(
            source_path, extra_dependency_hashes,
        )
        stored_hash = hash_path.read_text(encoding="utf-8").strip()

        if current_hash != stored_hash:
            self._stats["misses"] += 1
            return CacheResult(hit=False)

        # Doc-key check: if the caller supplied a doc_key, the stored
        # one must match (or absence ⇒ miss). If the caller didn't
        # supply one, we don't enforce — single-file transpiles without
        # a project index legitimately omit the doc key.
        if doc_key is not None:
            if not doc_key_path.exists():
                self._stats["misses"] += 1
                return CacheResult(hit=False)
            stored_doc_key = doc_key_path.read_text(encoding="utf-8").strip()
            if stored_doc_key != doc_key:
                self._stats["misses"] += 1
                return CacheResult(hit=False)

        # The published copies must still be the ones the build wrote.
        if published_dir is not None:
            for cached in (py_path, ir_path, map_path):
                if not cached.exists():
                    continue
                if not self._same_bytes(Path(published_dir) / cached.name, cached):
                    self._stats["misses"] += 1
                    return CacheResult(hit=False)

        # Replay rendered doc outputs from the manifest, if any.
        cached_docs: tuple[RenderedDocEntry, ...] = ()
        if docs_manifest_path.exists():
            try:
                manifest = json.loads(
                    docs_manifest_path.read_text(encoding="utf-8")
                )
                entries: list[RenderedDocEntry] = []
                for item in manifest.get("entries", []):
                    cache_rel = item.get("cache_rel")
                    if not cache_rel:
                        continue
                    cached_body_path = self.cache_dir / cache_rel
                    if not cached_body_path.exists():
                        # Stale manifest — treat as miss so we re-render.
                        self._stats["misses"] += 1
                        return CacheResult(hit=False)
                    entries.append(RenderedDocEntry(
                        decl_kind=item["decl_kind"],
                        name=item["name"],
                        output_path=Path(item["output_path"]),
                        content=cached_body_path.read_text(encoding="utf-8"),
                    ))
                cached_docs = tuple(entries)
            except (json.JSONDecodeError, OSError, KeyError):
                # Corrupt manifest — treat as miss.
                self._stats["misses"] += 1
                return CacheResult(hit=False)

        self._stats["hits"] += 1
        return CacheResult(
            hit=True,
            cached_py=py_path if py_path.exists() else None,
            cached_ir=ir_path if ir_path.exists() else None,
            cached_map=map_path if map_path.exists() else None,
            cached_docs=cached_docs,
        )

    def store(
        self,
        source_path: Path,
        py_content: str,
        ir_content: str | None = None,
        map_content: str | None = None,
        *,
        doc_key: str | None = None,
        docs: tuple[RenderedDocEntry, ...] = (),
        module_name: str | None = None,
        extra_dependency_hashes: tuple[str, ...] = (),
    ) -> list[Path]:
        """Store transpiler outputs in the cache.

        Writes the content hash, .py output, and optionally .s0ma.json and
        .s0ma.map outputs to the cache directory. When *docs* is non-empty,
        each rendered output's body is mirrored under
        ``.s0ma.cache/docs/`` and a manifest plus *doc_key* is written
        so the next lookup can validate and replay.

        The *module_name* argument is the cache key (M4, feedback 5–6).
        If omitted, it is extracted from the source file's ``module``
        declaration via :func:`extract_module_name`.

        ``extra_dependency_hashes`` (M12, feedback 5–6) folds additional
        content hashes into the stored cache key — see :meth:`lookup`
        for details. Pass exactly the same value here as the matching
        :meth:`lookup` call so the next build's lookup compares like
        with like.

        Returns list of written file paths.
        """
        source_path = Path(source_path)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        key = module_name if module_name is not None else extract_module_name(source_path)
        written: list[Path] = []

        # Write hash
        content_hash = self._compose_source_hash(
            source_path, extra_dependency_hashes,
        )
        hash_path = self.cache_dir / f"{key}.hash"
        hash_path.write_text(content_hash + "\n", encoding="utf-8", newline="\n")
        written.append(hash_path)

        # Write .py
        py_path = self.cache_dir / f"{key}.py"
        # Build invariant (M2, feedback 5–6 plan): emitted Python must
        # parse before being cached. Catches the case where an upstream
        # caller hands us syntactically-broken Python without going
        # through the CLI's primary validation site.
        from s0ma_dsl.codegen import validate_emitted_python

        validate_emitted_python(py_path, py_content)
        py_path.write_text(py_content, encoding="utf-8", newline="\n")
        written.append(py_path)

        # Write .s0ma.json
        if ir_content is not None:
            ir_path = self.cache_dir / f"{key}.s0ma.json"
            ir_path.write_text(ir_content, encoding="utf-8", newline="\n")
            written.append(ir_path)

        # Write .s0ma.map
        if map_content is not None:
            map_path = self.cache_dir / f"{key}.s0ma.map"
            map_path.write_text(map_content, encoding="utf-8", newline="\n")
            written.append(map_path)

        # Doc cache: write each rendered body, plus a manifest, plus
        # the doc_key so lookup can validate.
        if docs:
            doc_dir = self.cache_dir / "docs" / key
            doc_dir.mkdir(parents=True, exist_ok=True)
            manifest_entries: list[dict[str, str]] = []
            for entry in docs:
                # Use a deterministic safe filename keyed by name.
                safe_name = entry.name.replace("/", "_").replace("\\", "_")
                ext = entry.output_path.suffix or ".out"
                cache_rel = f"docs/{key}/{safe_name}{ext}"
                cached_body = self.cache_dir / cache_rel
                cached_body.parent.mkdir(parents=True, exist_ok=True)
                cached_body.write_text(entry.content, encoding="utf-8", newline="\n")
                written.append(cached_body)
                manifest_entries.append({
                    "decl_kind": entry.decl_kind,
                    "name": entry.name,
                    "output_path": str(entry.output_path),
                    "cache_rel": cache_rel,
                })
            manifest_path = self.cache_dir / f"{key}.docs.json"
            manifest_path.write_text(
                json.dumps(
                    {"entries": manifest_entries},
                    indent=2,
                    sort_keys=True,
                ) + "\n",
                encoding="utf-8",
                newline="\n",
            )
            written.append(manifest_path)
            if doc_key is not None:
                doc_key_path = self.cache_dir / f"{key}.docs.key"
                doc_key_path.write_text(doc_key + "\n", encoding="utf-8", newline="\n")
                written.append(doc_key_path)
        else:
            # No docs in this build — clear any stale doc cache.
            self._invalidate_docs(key)

        return written

    def _invalidate_docs(self, key: str) -> None:
        """Remove any cached doc artifacts for a cache key (module name)."""
        for suffix in [".docs.json", ".docs.key"]:
            cached = self.cache_dir / f"{key}{suffix}"
            if cached.exists():
                cached.unlink()
        doc_dir = self.cache_dir / "docs" / key
        if doc_dir.exists():
            import shutil
            shutil.rmtree(doc_dir)

    def invalidate(
        self,
        source_path: Path,
        *,
        module_name: str | None = None,
    ) -> None:
        """Remove all cached artifacts for a source file.

        The *module_name* argument is the cache key (M4, feedback 5–6).
        If omitted, it is extracted from the source file's ``module``
        declaration via :func:`extract_module_name`.
        """
        source_path = Path(source_path)
        key = module_name if module_name is not None else extract_module_name(source_path)

        for suffix in [".hash", ".py", ".s0ma.json", ".s0ma.map"]:
            cached = self.cache_dir / f"{key}{suffix}"
            if cached.exists():
                cached.unlink()
        self._invalidate_docs(key)

    def clear(self) -> None:
        """Remove all cached artifacts."""
        if self.cache_dir.exists():
            import shutil
            shutil.rmtree(self.cache_dir)

    @staticmethod
    def _hash_file(path: Path) -> str:
        """Compute SHA-256 hex digest of a file's contents."""
        content = Path(path).read_bytes()
        return hashlib.sha256(content).hexdigest()

    @staticmethod
    def _same_bytes(published: Path, cached: Path) -> bool:
        """True iff *published* exists and holds exactly *cached*'s bytes."""
        try:
            return published.read_bytes() == cached.read_bytes()
        except OSError:
            return False

    @classmethod
    def _compose_source_hash(
        cls,
        source_path: Path,
        extra_dependency_hashes: tuple[str, ...],
    ) -> str:
        """Compose the cache key: the transpiler version, source and embeds.

        The running ``s0ma_dsl.__version__`` — the ``transpiler_version``
        the build manifest records, and what the derived-surface cache
        already keys on — comes first, so an entry another version wrote
        never matches. Without it an upgrade replayed the old emitter's
        ``.py``, IR and map for every unchanged module under a manifest
        stamped with the new version, and a fix to what the build writes
        stayed invisible until the source changed (codebase review
        BLD-3). Entries written before the version was part of the key
        (the bare source hash) miss too, so the first build after an
        upgrade rebuilds once.

        M12 (feedback 5–6): when a module embeds external files via
        ``content: @file("path")``, those files are part of the
        module's effective source. Their content hashes are folded into
        the cache key here so editing an embedded file invalidates the
        consuming module's cache. ``extra_dependency_hashes`` is a
        deterministic-order tuple of pre-computed ``"sha256:<hex>"``
        strings.
        """
        h = hashlib.sha256()
        h.update(f"s0ma-dsl {__version__}\n".encode())
        h.update(cls._hash_file(source_path).encode("utf-8"))
        for dep_hash in extra_dependency_hashes:
            h.update(b"\n")
            h.update(dep_hash.encode("utf-8"))
        return h.hexdigest()
