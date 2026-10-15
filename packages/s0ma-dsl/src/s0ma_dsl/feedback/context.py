"""The allow-listed context collector (contract §5).

The context block is the only place a feedback report carries facts the
user did not type, so it is built — never copied. :func:`build_context`
takes typed keyword arguments and nothing else: there is no parameter that
accepts a caller-supplied map, so a foreign key has no route in. As a
second gate, everything it assembles passes through
:func:`enforce_allow_list`, which raises :class:`ContextAllowListError`
if a key outside :data:`~s0ma_dsl.feedback.model.CONTEXT_ALLOWED_KEYS`
ever appears. (That raise is a bug guard for s0ma's own code. A
hand-assembled context reaching validation is reported as a structured
``SCHEMA_INVALID`` problem instead — see
:func:`s0ma_dsl.feedback.model.validate_payload`.)

Excluded by construction, and not addable without a PRD amendment: source
code, file contents, prompts, conversation transcripts, raw stdout/stderr,
stack traces, git remotes, repository or organization names, account
email, license keys, and hardware identifiers. The pseudonym is a random
installation id from :mod:`s0ma_dsl.feedback.state` — never a hardware
fingerprint.

Nothing here touches the network; the only I/O is reading (and, on first
use, writing) ``~/.s0ma/installation_id``.
"""

from __future__ import annotations

import platform
import sys
from dataclasses import dataclass
from importlib import metadata
from typing import TYPE_CHECKING, Any

from s0ma_dsl.feedback.model import CHANNELS, CONTEXT_ALLOWED_KEYS
from s0ma_dsl.feedback.state import installation_id

if TYPE_CHECKING:
    from collections.abc import Sequence
    from pathlib import Path

__all__ = [
    "COHORT",
    "DISTRIBUTIONS",
    "DURATION_BUCKETS",
    "OS_FAMILIES",
    "OUTCOMES",
    "S0MA_VERSION_DISTRIBUTION",
    "ClientInfo",
    "ContextAllowListError",
    "SurfaceInfo",
    "architecture",
    "build_context",
    "distribution_versions",
    "duration_bucket",
    "enforce_allow_list",
    "os_family",
    "python_series",
]

#: The one cohort this beta reports under (contract §5).
COHORT = "beta"

#: Context key -> distribution name, for the four s0ma distributions.
#: Absent distributions report ``None`` rather than dropping the key, so a
#: core+dsl-only install is legible in the inbox (INV-6).
DISTRIBUTIONS: tuple[tuple[str, str], ...] = (
    ("s0ma_core", "s0ma-core"),
    ("s0ma_dsl", "s0ma-dsl"),
    ("s0ma_mcp", "s0ma-mcp"),
    ("s0ma_studi0", "s0ma-studi0"),
)

#: The distribution whose version answers "which s0ma is this?". Versions
#: are released in lockstep, and this code ships inside s0ma-dsl.
S0MA_VERSION_DISTRIBUTION = "s0ma-dsl"

#: Operating-system families (contract §5). Anything else reports
#: ``other`` rather than leaking an unmapped platform string.
OS_FAMILIES: tuple[str, ...] = ("macos", "linux", "windows", "other")

#: Outcome vocabulary for the surface the report is about.
OUTCOMES: tuple[str, ...] = ("success", "failure")

#: Duration buckets, coarse on purpose: the contract asks for a bucket
#: rather than "an unnecessarily precise trace".
DURATION_BUCKETS: tuple[str, ...] = ("<1s", "1-5s", "5-30s", "30s-2m", ">2m")

# Upper bound (seconds, exclusive) for each bucket except the last.
_DURATION_EDGES: tuple[tuple[float, str], ...] = (
    (1.0, "<1s"),
    (5.0, "1-5s"),
    (30.0, "5-30s"),
    (120.0, "30s-2m"),
)

_OS_FAMILY_BY_SYSTEM = {
    "Darwin": "macos",
    "Linux": "linux",
    "Windows": "windows",
}


class ContextAllowListError(ValueError):
    """A key outside the contract §5 allow-list reached a feedback context.

    Raised only against s0ma's own collector output: it means this module
    tried to record something the privacy contract forbids, which is a bug
    to fix here, not a user error to report.
    """


@dataclass(frozen=True)
class ClientInfo:
    """The coding client hosting s0ma, when the host exposes it.

    MCP fills this from ``clientInfo``; the CLI leaves it unset.
    """

    name: str
    version: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """Serialize to the ``{name, version}`` shape contract §5 allows."""
        return {"name": self.name, "version": self.version}


@dataclass(frozen=True)
class SurfaceInfo:
    """The s0ma surface a report is about, e.g. tool ``check``."""

    kind: str
    name: str

    def to_dict(self) -> dict[str, Any]:
        """Serialize to the ``{kind, name}`` shape contract §5 allows."""
        return {"kind": self.kind, "name": self.name}


def _dist_version(distribution: str) -> str | None:
    """Installed version of *distribution*, or ``None`` when absent."""
    try:
        return metadata.version(distribution)
    except metadata.PackageNotFoundError:
        return None


def distribution_versions() -> dict[str, str | None]:
    """Return the four s0ma distribution versions, ``None`` where absent."""
    return {key: _dist_version(name) for key, name in DISTRIBUTIONS}


def python_series() -> str:
    """Return the running Python as ``major.minor`` — never the full build."""
    return f"{sys.version_info.major}.{sys.version_info.minor}"


def os_family() -> str:
    """Return the operating-system family (contract §5's closed list)."""
    return _OS_FAMILY_BY_SYSTEM.get(platform.system(), "other")


def architecture() -> str:
    """Return the CPU architecture, e.g. ``arm64`` — not a machine id."""
    return platform.machine().strip().lower() or "unknown"


def duration_bucket(seconds: float) -> str:
    """Bucket a duration into one of :data:`DURATION_BUCKETS`.

    Deliberately coarse: the inbox needs "this was slow", not a timing
    trace that could fingerprint a machine.
    """
    if seconds < 0:
        raise ValueError("duration in seconds cannot be negative")
    for edge, label in _DURATION_EDGES:
        if seconds < edge:
            return label
    return DURATION_BUCKETS[-1]


def enforce_allow_list(context: dict[str, Any]) -> dict[str, Any]:
    """Return *context* key-sorted, or raise on a non-allow-listed key.

    The second of the two client-side gates contract §5 requires. Sorting
    is a readability nicety only — canonical serialization sorts anyway.
    """
    foreign = sorted(set(context) - CONTEXT_ALLOWED_KEYS)
    if foreign:
        raise ContextAllowListError(
            "feedback context may not carry: "
            f"{', '.join(foreign)}. Allowed keys: "
            f"{', '.join(sorted(CONTEXT_ALLOWED_KEYS))}."
        )
    return dict(sorted(context.items()))


def _pseudonym(home: Path | None) -> str | None:
    """The installation pseudonym, or ``None`` when state is unwritable.

    An unwritable home is not a reason to refuse feedback: the report
    simply travels without a pseudonym.
    """
    try:
        return installation_id(home)
    except OSError:
        return None


def build_context(
    *,
    channel: str = "cli",
    client: ClientInfo | None = None,
    surface: SurfaceInfo | None = None,
    diagnostic_codes: Sequence[str] | None = None,
    outcome: str | None = None,
    duration_seconds: float | None = None,
    mcp_protocol_version: str | None = None,
    include_pseudonym: bool = True,
    home: Path | None = None,
) -> dict[str, Any]:
    """Collect the allow-listed context for one feedback report.

    Every parameter is typed and optional; there is no way to pass an
    arbitrary key, and the result is checked against the allow-list before
    it is returned.

    Always present: the s0ma version, the four distribution versions
    (``None`` where absent), the Python series, the OS family, the
    architecture, and the cohort. Present when supplied: the client, the
    surface, diagnostic codes, the outcome, and the duration bucket.
    Present unless the state directory is unwritable or *include_pseudonym*
    is false: the installation pseudonym.

    *channel* is not itself recorded — it gates the MCP-only entry, since
    contract §5 admits the MCP protocol version on the ``mcp`` channel
    alone.
    """
    if channel not in CHANNELS:
        raise ValueError(f"unknown feedback channel: {channel!r}")
    if mcp_protocol_version is not None and channel != "mcp":
        raise ValueError(
            "the MCP protocol version belongs to the mcp channel only "
            f"(contract §5); this context is for the {channel} channel"
        )

    context: dict[str, Any] = {
        "s0ma_version": _dist_version(S0MA_VERSION_DISTRIBUTION),
        "python": python_series(),
        "os": os_family(),
        "architecture": architecture(),
        "cohort": COHORT,
    }
    context.update(distribution_versions())

    if client is not None:
        context["client"] = client.to_dict()
    if surface is not None:
        context["surface"] = surface.to_dict()
    if mcp_protocol_version is not None:
        context["mcp_protocol_version"] = mcp_protocol_version
    if diagnostic_codes is not None:
        if isinstance(diagnostic_codes, str):
            raise TypeError("diagnostic_codes must be a sequence of codes, not one string")
        context["diagnostic_codes"] = [str(code) for code in diagnostic_codes]
    if outcome is not None:
        if outcome not in OUTCOMES:
            raise ValueError(f"outcome must be one of {OUTCOMES}; got {outcome!r}")
        context["outcome"] = outcome
    if duration_seconds is not None:
        context["duration_bucket"] = duration_bucket(duration_seconds)
    if include_pseudonym:
        pseudonym = _pseudonym(home)
        if pseudonym is not None:
            context["pseudonym"] = pseudonym

    return enforce_allow_list(context)
