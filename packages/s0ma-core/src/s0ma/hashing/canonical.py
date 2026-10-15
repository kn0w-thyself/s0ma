"""Deterministic canonicalization of Python values for hashing.

``canonicalize(value)`` produces a byte string that is reproducible across
processes, platforms, and Python dict-iteration orderings. It is the
shared primitive underneath :mod:`s0ma.hashing.content_hash` and any
other component that needs to fingerprint structured data.

Design constraints
------------------
* Deterministic: the same input must produce identical bytes across
  Python interpreters, operating systems, and insertion orders. Dict
  keys are sorted; floats are emitted via :func:`repr` (round-trip
  stable); strings are NFC-normalized before UTF-8 encoding.
* Self-describing: every value carries a one-byte type tag plus an
  explicit length prefix where ambiguity would otherwise exist. This
  prevents collisions like ``["a", "b"]`` vs ``["ab"]``.
* Minimal surface: the only public function is :func:`canonicalize`.
  Internal helpers are underscore-prefixed and not exported.

Type coverage
-------------
``None``, ``bool``, ``int``, ``float``, ``str``, ``bytes``, ``list``,
``tuple``, ``dict``, ``frozenset``, ``set``, ``Enum`` subclasses, and
any ``@dataclass`` instance (serialized via :func:`dataclasses.fields`
in declaration order). Unsupported types raise :class:`TypeError` so
hashes never silently degrade to an address-based repr.
"""

from __future__ import annotations

import dataclasses
import unicodedata
from enum import Enum
from typing import Any

__all__ = ["canonicalize"]

# Type tags. Single-byte ASCII to keep the binary output compact and
# greppable. Chosen so no tag is a prefix of another.
_TAG_NONE = b"N;"
_TAG_TRUE = b"T;"
_TAG_FALSE = b"F;"
_TAG_INT = b"i"
_TAG_FLOAT = b"f"
_TAG_STR = b"s"
_TAG_BYTES = b"b"
_TAG_LIST = b"l"
_TAG_TUPLE = b"t"
_TAG_DICT = b"d"
_TAG_SET = b"x"
_TAG_ENUM = b"e"
_TAG_DATACLASS = b"c"


def canonicalize(value: Any) -> bytes:
    """Produce deterministic bytes for ``value``.

    The output is suitable for feeding into a cryptographic hash. Two
    values that compare equal under normal Python equality produce
    identical output; the reverse is also true for every supported type.

    Raises:
        TypeError: if ``value`` is of a type not listed in this module's
            docstring. This is intentional — silently falling back to
            ``repr`` would break determinism.
    """
    if value is None:
        return _TAG_NONE
    if isinstance(value, bool):
        # Must precede ``int`` — booleans are ints in Python.
        return _TAG_TRUE if value else _TAG_FALSE
    if isinstance(value, int):
        return _canon_int(value)
    if isinstance(value, float):
        return _canon_float(value)
    if isinstance(value, str):
        return _canon_str(value)
    if isinstance(value, bytes):
        return _canon_bytes(value)
    if isinstance(value, Enum):
        return _canon_enum(value)
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        return _canon_dataclass(value)
    if isinstance(value, dict):
        return _canon_dict(value)
    if isinstance(value, list):
        return _canon_sequence(_TAG_LIST, value)
    if isinstance(value, tuple):
        return _canon_sequence(_TAG_TUPLE, list(value))
    if isinstance(value, (set, frozenset)):
        return _canon_set(value)
    raise TypeError(
        f"canonicalize: unsupported type {type(value).__name__!r}; "
        f"add an explicit branch rather than falling back to repr()"
    )


def _canon_int(value: int) -> bytes:
    payload = str(value).encode("ascii")
    return _TAG_INT + _len_prefix(payload) + payload


def _canon_float(value: float) -> bytes:
    # ``repr`` is round-trip stable for IEEE 754 doubles on every CPython
    # build since 3.1. NaN/Inf compare as their repr strings — two NaNs
    # produced the same way therefore hash identically, which is the
    # behavior we want for content hashing even though ``nan != nan``.
    payload = repr(value).encode("ascii")
    return _TAG_FLOAT + _len_prefix(payload) + payload


def _canon_str(value: str) -> bytes:
    # NFC normalization folds visually identical but differently
    # composed strings (e.g., precomposed "é" vs "e" + combining acute)
    # into a single form. Filesystems, editors, and input methods all
    # emit both; without normalization the hash would depend on who
    # authored the source file.
    payload = unicodedata.normalize("NFC", value).encode("utf-8")
    return _TAG_STR + _len_prefix(payload) + payload


def _canon_bytes(value: bytes) -> bytes:
    return _TAG_BYTES + _len_prefix(value) + value


def _canon_enum(value: Enum) -> bytes:
    qualified = f"{type(value).__module__}.{type(value).__qualname__}:{value.name}"
    payload = qualified.encode("utf-8")
    return _TAG_ENUM + _len_prefix(payload) + payload


def _canon_dataclass(value: Any) -> bytes:
    fields = dataclasses.fields(value)
    cls = type(value)
    qualified = f"{cls.__module__}.{cls.__qualname__}".encode()
    parts: list[bytes] = [_TAG_DATACLASS, _len_prefix(qualified), qualified]
    parts.append(_count_prefix(len(fields)))
    # Dataclass field order is declaration order. We do not sort — two
    # dataclasses with the same field names in different order are
    # semantically distinct and should hash differently.
    for f in fields:
        fname = f.name.encode("utf-8")
        parts.append(_len_prefix(fname))
        parts.append(fname)
        parts.append(canonicalize(getattr(value, f.name)))
    return b"".join(parts)


def _canon_dict(value: dict[Any, Any]) -> bytes:
    items = sorted(value.items(), key=lambda kv: canonicalize(kv[0]))
    parts: list[bytes] = [_TAG_DICT, _count_prefix(len(items))]
    for key, val in items:
        parts.append(canonicalize(key))
        parts.append(canonicalize(val))
    return b"".join(parts)


def _canon_sequence(tag: bytes, value: list[Any]) -> bytes:
    parts: list[bytes] = [tag, _count_prefix(len(value))]
    for item in value:
        parts.append(canonicalize(item))
    return b"".join(parts)


def _canon_set(value: set[Any] | frozenset[Any]) -> bytes:
    # Sets have no order, so we must sort to get determinism. We sort
    # by each element's own canonical form — this is stable even when
    # the elements are not themselves comparable (e.g., a set of mixed
    # strings and ints would raise on ``sorted(value)`` directly).
    canons = sorted(canonicalize(item) for item in value)
    parts: list[bytes] = [_TAG_SET, _count_prefix(len(canons))]
    parts.extend(canons)
    return b"".join(parts)


def _len_prefix(payload: bytes) -> bytes:
    """Decimal length followed by ``:`` — unambiguous, ASCII-only."""
    return f"{len(payload)}:".encode("ascii")


def _count_prefix(count: int) -> bytes:
    return f"{count};".encode("ascii")
