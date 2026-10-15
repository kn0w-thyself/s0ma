"""The feedback token store and the license-key exchange (contract §2.2/§8).

A tester's license key is exchanged **once** for a scoped feedback token,
and the key never accompanies a feedback report again (FD-4). The token
lives at ``~/.s0ma/feedback-token`` as owner-only JSON:
``{token, token_prefix, expires_ts, cp_host}``.

Three ways a token is found, in order:

1. ``S0MA_FEEDBACK_TOKEN`` — an environment override (FD-3). Its host comes
   from ``S0MA_CP_HOST`` or the production default, and its expiry is
   unknown, so it is never treated as expired: the environment is the
   caller's declaration and this module does not second-guess it.
2. the stored file, when it parses and has not expired;
3. nothing — reported as a :class:`TokenLookup` carrying a *reason* and the
   remediation to show the user, never as an exception.

An expired stored token reads as **absent with a reason**: a client that
sent it would get a 401 and a confusing message, so the expiry is caught
where the remediation ("enroll again") can still be helpful.

This module holds no transport. :func:`exchange` performs its one POST
through :mod:`s0ma_dsl.feedback.client`, the single module in this package
the milestone boundary allows to carry a socket; the import is inside the
function so that merely reading the token store never pulls a network
stack into the process.

The plaintext token is treated as a secret: it is kept out of
:func:`repr`, and no function here logs, prints, or embeds it in a message.
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from s0ma_dsl.feedback.state import state_dir, write_private_text

if TYPE_CHECKING:
    from pathlib import Path

    from s0ma_dsl.feedback.client import FeedbackResult

__all__ = [
    "CP_HOST_ENV_VAR",
    "DEFAULT_CP_HOST",
    "TOKEN_ABSENT",
    "TOKEN_ENDPOINT_PATH",
    "TOKEN_ENV_VAR",
    "TOKEN_EXPIRED",
    "TOKEN_FILENAME",
    "TOKEN_PREFIX_CHARS",
    "TOKEN_UNREADABLE",
    "StoredToken",
    "TokenLookup",
    "base_url",
    "clear_token",
    "default_cp_host",
    "exchange",
    "read_token",
    "token_path",
    "token_prefix_of",
    "write_token",
]

#: Owner-only JSON file holding this machine's feedback token (§8).
TOKEN_FILENAME = "feedback-token"

#: Environment override for the token itself (FD-3, contract §8).
TOKEN_ENV_VAR = "S0MA_FEEDBACK_TOKEN"

#: Environment override for the control-plane host.
CP_HOST_ENV_VAR = "S0MA_CP_HOST"

#: Production control plane. ``scripts/install.sh`` carries the same
#: default and the same scheme rule (a bare host gets https).
DEFAULT_CP_HOST = "account.kn0wthyself.ai"

#: Displayable prefix length — the first 12 characters of the token
#: (contract §2.2). Enough to recognise which token is stored; useless as
#: a credential.
TOKEN_PREFIX_CHARS = 12

#: Path of the token-exchange endpoint (contract §2).
TOKEN_ENDPOINT_PATH = "/api/feedback/token"

#: Lookup reasons. They name the user's situation, not an error class.
TOKEN_ABSENT = "absent"
TOKEN_EXPIRED = "expired"
TOKEN_UNREADABLE = "unreadable"

_REMEDIATION = {
    TOKEN_ABSENT: (
        "This machine is not set up to send feedback yet. "
        "Run `s0ma feedback enroll` to connect it to your s0ma account."
    ),
    TOKEN_EXPIRED: (
        "This machine's feedback access has expired. "
        "Run `s0ma feedback enroll` to renew it."
    ),
    TOKEN_UNREADABLE: (
        "The stored feedback access could not be read. "
        "Run `s0ma feedback enroll` to replace it."
    ),
}


def _now_ms() -> int:
    """Epoch milliseconds from the client clock (the contract's ts unit)."""
    return int(time.time() * 1000)


def default_cp_host() -> str:
    """Return the control-plane host: ``S0MA_CP_HOST`` or the default."""
    return os.environ.get(CP_HOST_ENV_VAR, "").strip() or DEFAULT_CP_HOST


def base_url(cp_host: str | None = None) -> str:
    """Return the base URL for *cp_host*, applying the installer's rule.

    A bare host gets ``https://`` — production is never plaintext by
    accident. A value that already carries a scheme is used verbatim, so a
    local ``wrangler pages dev`` can be targeted with
    ``http://127.0.0.1:8788`` exactly as ``scripts/install.sh --cp-host``
    allows. Any trailing slash is dropped so paths concatenate cleanly.
    """
    host = (cp_host or default_cp_host()).strip()
    if "://" not in host:
        host = f"https://{host}"
    return host.rstrip("/")


def token_path(home: Path | None = None) -> Path:
    """Return ``~/.s0ma/feedback-token`` without creating anything."""
    return state_dir(home) / TOKEN_FILENAME


def token_prefix_of(token: str) -> str:
    """Return the displayable prefix of *token* (contract §2.2)."""
    return token[:TOKEN_PREFIX_CHARS]


@dataclass(frozen=True)
class StoredToken:
    """One feedback token and the facts needed to use it.

    ``token`` is excluded from :func:`repr` on purpose: this object travels
    through result types, tracebacks, and debug output, and the plaintext
    must not travel with it.
    """

    token: str = field(repr=False)
    token_prefix: str = ""
    expires_ts: int | None = None
    cp_host: str = DEFAULT_CP_HOST
    source: str = "file"
    """``file`` or ``environment`` — where this token was found."""

    def is_expired(self, now_ms: int | None = None) -> bool:
        """Whether the token's expiry has passed.

        A token with no known expiry (the environment override) is never
        expired: the caller who set the variable is the authority.
        """
        if self.expires_ts is None:
            return False
        return (now_ms if now_ms is not None else _now_ms()) >= self.expires_ts

    def to_dict(self) -> dict[str, Any]:
        """Serialize to the stored file shape (contract §8) — four keys.

        ``source`` is runtime knowledge, not stored state, so it is not
        written: a token read back from disk is a file token by definition.
        """
        return {
            "token": self.token,
            "token_prefix": self.token_prefix,
            "expires_ts": self.expires_ts,
            "cp_host": self.cp_host,
        }


@dataclass(frozen=True)
class TokenLookup:
    """The result of looking for this machine's feedback token.

    Absence is an ordinary answer, not a failure: ``token`` is ``None`` and
    *reason* says which of the three situations applies, with *remediation*
    a sentence the caller can show as it stands.
    """

    token: StoredToken | None = None
    reason: str | None = None
    remediation: str | None = None

    @property
    def ok(self) -> bool:
        """Whether a usable token was found."""
        return self.token is not None


def _missing(reason: str) -> TokenLookup:
    """Build the absent-with-a-reason lookup for *reason*."""
    return TokenLookup(reason=reason, remediation=_REMEDIATION[reason])


def _token_from_dict(document: Any) -> StoredToken:
    """Rebuild a stored token, or raise :class:`ValueError`."""
    if not isinstance(document, dict):
        raise ValueError("the token file must hold an object")
    token = document.get("token")
    if not isinstance(token, str) or not token.strip():
        raise ValueError("the token file carries no token")
    expires_ts = document.get("expires_ts")
    if expires_ts is not None and (
        not isinstance(expires_ts, int) or isinstance(expires_ts, bool)
    ):
        raise ValueError("expires_ts must be epoch milliseconds")
    prefix = document.get("token_prefix")
    cp_host = document.get("cp_host")
    return StoredToken(
        token=token.strip(),
        token_prefix=prefix if isinstance(prefix, str) and prefix else token_prefix_of(token),
        expires_ts=expires_ts,
        cp_host=cp_host if isinstance(cp_host, str) and cp_host else DEFAULT_CP_HOST,
        source="file",
    )


def read_token(home: Path | None = None, now_ms: int | None = None) -> TokenLookup:
    """Find this machine's feedback token, environment override first."""
    override = os.environ.get(TOKEN_ENV_VAR, "").strip()
    if override:
        return TokenLookup(
            token=StoredToken(
                token=override,
                token_prefix=token_prefix_of(override),
                expires_ts=None,
                cp_host=default_cp_host(),
                source="environment",
            )
        )
    path = token_path(home)
    try:
        raw = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return _missing(TOKEN_ABSENT)
    except (OSError, UnicodeDecodeError):
        return _missing(TOKEN_UNREADABLE)
    try:
        stored = _token_from_dict(json.loads(raw))
    except (ValueError, TypeError):
        return _missing(TOKEN_UNREADABLE)
    if stored.is_expired(now_ms):
        return _missing(TOKEN_EXPIRED)
    return TokenLookup(token=stored)


def write_token(
    *,
    token: str,
    expires_ts: int | None = None,
    cp_host: str | None = None,
    token_prefix: str | None = None,
    home: Path | None = None,
) -> StoredToken:
    """Store *token* owner-only and return the stored record.

    Raises :class:`ValueError` on an empty token and :class:`OSError` when
    the state directory cannot be written.
    """
    value = token.strip()
    if not value:
        raise ValueError("a feedback token cannot be empty")
    stored = StoredToken(
        token=value,
        token_prefix=token_prefix or token_prefix_of(value),
        expires_ts=expires_ts,
        cp_host=cp_host or default_cp_host(),
        source="file",
    )
    text = json.dumps(stored.to_dict(), indent=2, ensure_ascii=False, sort_keys=True)
    write_private_text(token_path(home), f"{text}\n")
    return stored


def clear_token(home: Path | None = None) -> bool:
    """Delete the stored token; return whether a file was removed."""
    try:
        token_path(home).unlink()
    except OSError:
        return False
    return True


def exchange(
    license_key: str,
    *,
    cp_host: str | None = None,
    pseudonym: str | None = None,
    home: Path | None = None,
    timeout: float | None = None,
) -> FeedbackResult:
    """Exchange a license key for a feedback token, and store the token.

    This is the only moment a license key is sent anywhere by the feedback
    engine (FD-4): the token it returns is what every later report carries.
    On success the token is written to ``~/.s0ma/feedback-token`` and the
    returned result's ``token`` holds the stored record; on failure the
    server's ``code`` and ``remediation`` are surfaced as they arrived and
    nothing is written.

    *pseudonym* is **not** sent by default. The contract makes it optional,
    and leaving it out keeps the installation pseudonym that travels in
    feedback reports unlinked from the account at exchange time; a caller
    that wants the server to know it must say so explicitly.
    """
    # Imported here, not at module scope: reading the token store must not
    # pull a network stack into the process (see the module docstring). The
    # module alias also keeps the name distinct from the type-checking-only
    # import above.
    from s0ma_dsl.feedback import client as transport

    key = license_key.strip()
    if not key:
        return transport.FeedbackResult(
            ok=False,
            code=transport.CODE_BAD_REQUEST,
            message="No license key was supplied, so there was nothing to enroll with.",
            remediation=(
                "Pass your s0ma license key with `--key`, or set S0MA_LICENSE_KEY, "
                "then run `s0ma feedback enroll` again."
            ),
        )
    host = cp_host or default_cp_host()
    body: dict[str, Any] = {}
    if pseudonym is not None:
        body["pseudonym"] = pseudonym
    result = transport.request_json(
        "POST",
        f"{base_url(host)}{TOKEN_ENDPOINT_PATH}",
        bearer=key,
        body=body,
        timeout=transport.DEFAULT_TIMEOUT_SECONDS if timeout is None else timeout,
    )
    if not result.ok:
        return result
    document = result.data or {}
    token = document.get("token")
    if not isinstance(token, str) or not token.strip():
        return transport.FeedbackResult(
            ok=False,
            code=transport.CODE_INVALID_RESPONSE,
            message="The s0ma service replied without the access this machine needs.",
            remediation="Try `s0ma feedback enroll` again in a few minutes.",
            status_code=result.status_code,
            data=result.data,
        )
    expires_ts = document.get("expires_ts")
    prefix = document.get("token_prefix")
    stored = write_token(
        token=token,
        expires_ts=(
            expires_ts
            if isinstance(expires_ts, int) and not isinstance(expires_ts, bool)
            else None
        ),
        cp_host=host,
        token_prefix=prefix if isinstance(prefix, str) and prefix else None,
        home=home,
    )
    # The response body is deliberately dropped: it is the one body in the
    # contract that carries a plaintext token, and a result travels through
    # logs and tracebacks. The stored record holds everything a caller needs.
    return transport.FeedbackResult(ok=True, status_code=result.status_code, token=stored)
