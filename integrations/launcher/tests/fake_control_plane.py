"""A stand-in for the s0ma control plane, on this machine, for the tests.

**Nothing in the launcher's tests ever contacts the real control plane.** Every
test that involves a network points ``S0MA_CP_HOST`` at the little HTTP server
in this file, which listens on a loopback address and a port the operating
system chooses. It answers the same three routes the real one does, in the same
JSON shapes:

* ``GET /api/dist/manifest?version=latest|X.Y.Z`` ->
  ``{"version": ..., "wheels": [{"name", "path", "sha256", "size"}, ...]}``
* ``GET /dist/<version>/<wheel>`` -> the bytes of that wheel
* ``GET /api/key/check`` -> ``{"ok": true, "status", "plan", "access_ends"}``

and the same refusals: ``{"ok": false, "code": ..., "remediation": ...}`` with
401 ``INVALID_KEY``, 403 ``NOT_ENTITLED``, 404 ``NOT_FOUND`` and 429
``RATE_LIMITED`` (with a ``Retry-After`` header). Every route checks the
``Authorization: Bearer <key>`` header, and every request is recorded so a test
can prove where the key did and did not travel.

The wheels it serves are **real wheels** - a zip with a ``*.dist-info``
directory holding ``METADATA``, ``WHEEL``, ``RECORD`` and ``entry_points.txt`` -
built here, from nothing, with no network and no build backend. They declare no
dependencies, so ``uv`` can install them with ``--offline`` and the tests do a
genuine install in well under a second. ``s0ma_mcp`` provides the ``s0ma-mcp``
command and ``s0ma_dsl`` provides ``s0ma``; both print their version and stop.

The one test that needs more than a stand-in - the end-to-end smoke in
``test_e2e_real_wheels.py`` - hands the plane the four **real** wheels instead,
through :meth:`FakeControlPlane.publish_directory`. Publishing is the only thing
that differs; every route, check and switch is the same.

Switches, all off by default, each set as a plain attribute on the running
plane: ``invalid_key``, ``not_entitled``, ``rate_limited``, ``wrong_sha``,
``truncate``, ``slow_seconds``, ``notice``, ``key_check_ok``.
"""

from __future__ import annotations

import base64
import hashlib
import json
import threading
import time
import zipfile
from collections.abc import Iterable, Iterator
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import pytest

#: The four distributions a copy of s0ma is made of, and the command each one
#: provides. The same names the real wheels carry.
FAKE_DISTRIBUTIONS: tuple[tuple[str, str | None], ...] = (
    ("s0ma_core", None),
    ("s0ma_dsl", "s0ma"),
    ("s0ma_mcp", "s0ma-mcp"),
    ("s0ma_studi0", None),
)

#: What the manifest claims a wheel hashes to when ``wrong_sha`` is on. A real
#: sha256 in shape, and not the hash of anything.
BAD_SHA256 = "0" * 64

_WHEEL_METADATA = """Wheel-Version: 1.0
Generator: s0ma-launch-tests
Root-Is-Purelib: true
Tag: py3-none-any
"""


def _record_line(name: str, data: bytes) -> str:
    digest = base64.urlsafe_b64encode(hashlib.sha256(data).digest()).rstrip(b"=")
    return f"{name},sha256={digest.decode('ascii')},{len(data)}"


def build_fake_wheel(
    into: Path, distribution: str, version: str, *, console_script: str | None = None
) -> Path:
    """Build one real, tiny, dependency-free wheel and return the file.

    A wheel is a zip file with a ``<name>-<version>.dist-info`` directory in it,
    so that is what this writes: the metadata a package manager reads, a
    ``RECORD`` with a real hash for every file (uv checks it), one module, and
    - when the distribution provides a command - an ``entry_points.txt`` that
    makes the package manager write that command into the environment's ``bin``
    (or ``Scripts``) directory.
    """
    into.mkdir(parents=True, exist_ok=True)
    module = distribution + "_stand_in"
    dist_info = f"{distribution}-{version}.dist-info"
    files: dict[str, bytes] = {
        module
        + ".py": (
            f'VERSION = "{version}"\n\n\n'
            "def main() -> int:\n"
            f'    print("{distribution} {version}")\n'
            "    return 0\n"
        ).encode("utf-8"),
        dist_info
        + "/METADATA": (
            "Metadata-Version: 2.1\n"
            f"Name: {distribution.replace('_', '-')}\n"
            f"Version: {version}\n"
            "Summary: a stand-in built by the s0ma launcher's tests\n"
        ).encode("utf-8"),
        dist_info + "/WHEEL": _WHEEL_METADATA.encode("utf-8"),
    }
    if console_script:
        files[dist_info + "/entry_points.txt"] = (
            f"[console_scripts]\n{console_script} = {module}:main\n"
        ).encode("utf-8")
    record = "".join(
        _record_line(name, data) + "\n" for name, data in sorted(files.items())
    )
    files[dist_info + "/RECORD"] = (record + f"{dist_info}/RECORD,,\n").encode("utf-8")

    path = into / f"{distribution}-{version}-py3-none-any.whl"
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, data in sorted(files.items()):
            archive.writestr(name, data)
    return path


def build_fake_wheels(into: Path, version: str) -> list[Path]:
    """The four wheels one version of s0ma is made of."""
    return [
        build_fake_wheel(into, distribution, version, console_script=script)
        for distribution, script in FAKE_DISTRIBUTIONS
    ]


@dataclass
class ServedWheel:
    """One file the fake plane can hand out."""

    name: str
    path: str
    data: bytes
    sha256: str


@dataclass
class FakeControlPlane:
    """The control plane, as far as a test is concerned."""

    key: str
    work: Path

    #: version -> the wheels published for it.
    versions: dict[str, list[ServedWheel]] = field(default_factory=dict)
    latest: str | None = None

    # Switches. Each one is a thing the real control plane can do.
    invalid_key: bool = False
    not_entitled: bool = False
    rate_limited: bool = False
    wrong_sha: bool = False
    truncate: bool = False
    slow_seconds: float = 0.0
    notice: str | None = None
    key_check_ok: bool = True

    #: Every request, as ``"GET /path?query"``. Read by the tests that prove a
    #: license key never travels in a URL.
    requests: list[str] = field(default_factory=list)
    #: Every ``Authorization`` header seen, in the order they arrived.
    authorizations: list[str] = field(default_factory=list)

    server: ThreadingHTTPServer | None = None
    thread: threading.Thread | None = None

    # -- publishing -------------------------------------------------------

    def publish(self, version: str) -> list[ServedWheel]:
        """Build and serve one version, and make it the newest one."""
        return self.publish_wheels(version, build_fake_wheels(self.work / version, version))

    def publish_wheels(self, version: str, wheels: Iterable[Path]) -> list[ServedWheel]:
        """Serve wheel files that already exist, and make *version* the newest.

        Every test but one hands this the tiny stand-ins :func:`build_fake_wheels`
        makes, through :meth:`publish`. The end-to-end smoke
        (``test_e2e_real_wheels.py``) hands it the four **real** s0ma wheels,
        built from this tree by ``uv build``, so that the whole journey - fetch,
        verify, install, start, update - happens against the files a subscriber
        would actually receive. Nothing else about the plane changes: the same
        routes, the same Bearer check, the same switches.
        """
        served: list[ServedWheel] = []
        for path in wheels:
            data = path.read_bytes()
            served.append(
                ServedWheel(
                    name=path.name,
                    path=f"dist/{version}/{path.name}",
                    data=data,
                    sha256=hashlib.sha256(data).hexdigest(),
                )
            )
        if not served:
            raise ValueError(f"no wheels were given to publish as {version}")
        self.versions[version] = served
        self.latest = version
        return served

    def publish_directory(self, version: str, directory: Path) -> list[ServedWheel]:
        """Serve every ``*.whl`` in *directory* as *version*, newest first."""
        return self.publish_wheels(version, sorted(directory.glob("*.whl")))

    def wheel_files(self, version: str) -> list[Path]:
        """Where the built wheels for *version* are on disk."""
        return sorted((self.work / version).glob("*.whl"))

    # -- running ----------------------------------------------------------

    @property
    def host(self) -> str:
        """What to put in ``S0MA_CP_HOST``: a loopback address with its port."""
        if self.server is None:  # pragma: no cover - a test that forgot to start it
            raise RuntimeError("the fake control plane is not running")
        return f"http://127.0.0.1:{self.server.server_address[1]}"

    def start(self) -> None:
        handler = _handler_for(self)
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
        self.server.daemon_threads = True
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def stop(self) -> None:
        if self.server is not None:
            self.server.shutdown()
            self.server.server_close()
            self.server = None
        if self.thread is not None:
            self.thread.join(timeout=5)
            self.thread = None

    # -- answering --------------------------------------------------------

    def manifest_for(self, version: str | None) -> dict[str, Any] | None:
        """The manifest answer for a version, or ``None`` when there is none."""
        wanted = self.latest if (version is None or version == "latest") else version
        if wanted is None or wanted not in self.versions:
            return None
        return {
            "version": wanted,
            "latest": self.latest,
            "wheels": [
                {
                    "name": wheel.name,
                    "path": wheel.path,
                    "sha256": BAD_SHA256 if self.wrong_sha else wheel.sha256,
                    "size": len(wheel.data),
                }
                for wheel in self.versions[wanted]
            ],
        }

    def find_wheel(self, path: str) -> ServedWheel | None:
        for wheels in self.versions.values():
            for wheel in wheels:
                if wheel.path == path:
                    return wheel
        return None


def _handler_for(plane: FakeControlPlane) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.0"

        def log_message(self, *_args: Any) -> None:
            """Say nothing. A test's output is for the test."""

        # -- helpers ------------------------------------------------------

        def _send(self, status: int, body: bytes, kind: str, extra: dict[str, str]) -> None:
            self.send_response(status)
            self.send_header("Content-Type", kind)
            self.send_header("Content-Length", str(len(body)))
            for name, value in extra.items():
                self.send_header(name, value)
            self.end_headers()
            self.wfile.write(body)

        def _json(self, status: int, body: dict[str, Any], **extra: str) -> None:
            self._send(
                status,
                json.dumps(body).encode("utf-8"),
                "application/json",
                extra,
            )

        def _refuse(self, status: int, code: str, remediation: str, **extra: str) -> None:
            self._json(
                status, {"ok": False, "code": code, "remediation": remediation}, **extra
            )

        def _gate(self) -> bool:
            """Check the key and the switches; ``True`` when the request may go on."""
            header = self.headers.get("Authorization", "")
            plane.authorizations.append(header)
            if plane.slow_seconds:
                time.sleep(plane.slow_seconds)
            if plane.invalid_key or header != "Bearer " + plane.key:
                self._refuse(
                    401,
                    "INVALID_KEY",
                    "Check your key at https://account.example.invalid.",
                )
                return False
            if plane.not_entitled:
                self._refuse(
                    403,
                    "NOT_ENTITLED",
                    "This account's access has ended.",
                )
                return False
            if plane.rate_limited:
                self._refuse(
                    429,
                    "RATE_LIMITED",
                    "Too many requests; wait a moment.",
                    **{"Retry-After": "30"},
                )
                return False
            return True

        # -- routes -------------------------------------------------------

        def do_GET(self) -> None:  # noqa: N802 - the name http.server requires
            plane.requests.append(f"GET {self.path}")
            if not self._gate():
                return
            split = urlsplit(self.path)
            if split.path == "/api/key/check":
                self._key_check()
            elif split.path == "/api/dist/manifest":
                self._manifest(split.query)
            elif split.path.startswith("/dist/"):
                self._wheel(split.path.lstrip("/"))
            else:
                self._refuse(404, "NOT_FOUND", "No such thing here.")

        def _key_check(self) -> None:
            if not plane.key_check_ok:
                self._refuse(401, "INVALID_KEY", "That key is not one of ours.")
                return
            body: dict[str, Any] = {
                "ok": True,
                "status": "active",
                "plan": "beta",
                "access_ends": None,
            }
            if plane.notice:
                body["notice"] = plane.notice
            self._json(200, body)

        def _manifest(self, query: str) -> None:
            wanted: str | None = None
            for part in query.split("&"):
                name, _, value = part.partition("=")
                if name == "version":
                    wanted = value or None
            manifest = plane.manifest_for(wanted)
            if manifest is None:
                self._refuse(404, "NOT_FOUND", "No such version is published.")
                return
            if plane.notice:
                manifest["notice"] = plane.notice
            self._json(200, manifest)

        def _wheel(self, path: str) -> None:
            wheel = plane.find_wheel(path)
            if wheel is None:
                self._refuse(404, "NOT_FOUND", "No such file is published.")
                return
            data = wheel.data
            self.send_response(200)
            self.send_header("Content-Type", "application/octet-stream")
            # The declared length is always the whole file: a truncated answer
            # is one that stops early, which is what a dropped connection looks
            # like to the launcher.
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data[: len(data) // 2] if plane.truncate else data)

    return Handler


# ---------------------------------------------------------------------------
# Fixtures. Imported by name into the test modules that need them:
#
#     from fake_control_plane import control_plane  # noqa: F401
# ---------------------------------------------------------------------------


@pytest.fixture
def control_plane(tmp_path: Path, fake_key: str) -> Iterator[FakeControlPlane]:
    """A fake control plane, running, with s0ma 0.18.0 published on it."""
    plane = FakeControlPlane(key=fake_key, work=tmp_path / "control-plane")
    plane.publish("0.18.0")
    plane.start()
    try:
        yield plane
    finally:
        plane.stop()


@pytest.fixture
def keyed(
    control_plane: FakeControlPlane, monkeypatch: pytest.MonkeyPatch
) -> FakeControlPlane:
    """A running fake plane that the launcher is pointed at, with a key set.

    Also switches on the test-only offline flag, so the real ``uv`` install the
    tests perform resolves nothing from any network.
    """
    monkeypatch.setenv("S0MA_CP_HOST", control_plane.host)
    monkeypatch.setenv("S0MA_LICENSE_KEY", control_plane.key)
    monkeypatch.setenv("S0MA_LAUNCH_OFFLINE_INSTALL", "1")
    return control_plane
