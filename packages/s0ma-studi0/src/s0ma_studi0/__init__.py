"""s0ma-studi0 — the local studi0 viewer, and its single bootstrap module.

studi0 serves one page on loopback and shows a s0ma project its own
component graph, read from that project's build artifacts and nothing
else (PRD §7.6, FR-STUDI0-1..9). It never executes the project it is
showing, never calls a model, and never reaches past ``127.0.0.1``. It
writes exactly one file into the target tree — ``.s0ma/studi0/
active.json``, the presence marker that says a viewer is running here —
and removes it again on the way out; nothing else in the tree is ever
written.

Usage::

    s0ma studi0 <project_root>          # the door: the DSL CLI subcommand

    # or programmatically — the same call the subcommand makes:
    from pathlib import Path

    from s0ma_studi0 import launch
    launch(Path("path/to/project"), open_browser=False)

Self-hosting: THE single bootstrap module
=========================================

This package is itself a s0ma application, and this file is its **one
handwritten Python module** (the s0ma-mcp precedent, ADR-001): the
server's behavior is authored in ``s0ma_src/*.s0ma`` and shipped as the
transpiler's committed build output in the generated subpackage
``_built/``. What stays handwritten here is exactly what cannot be
emitted:

* **the bootstrap** — ``s0ma.bootstrap.bootstrap_imports`` reads
  ``_built/build.s0ma.json`` and imports each built module under its
  canonical flat name in topological order (executing its emitted
  ``@component``/``register_*`` self-registrations exactly once), then
  aliases it into this package's namespace
  (``s0ma_studi0.studi0_server``) so every import form keeps working.
  A built module cannot bootstrap itself into existence;
* **the entry points** — :func:`launch`, the frozen call the
  ``s0ma studi0`` subcommand makes, and :func:`main`, the same journey
  for direct execution. They compose the built nerves: open a viewing
  session, start the watch that keeps it current, bind a server on it,
  report the address it really bound, mark the project as watched, open
  a browser at it, serve until interrupted, and take the mark and the
  watch back down on the way out.

The flat name is the ONLY runtime identity. Never import a built module
through its on-disk dotted path (``s0ma_studi0._built.<module>``) at
runtime — that would execute the module a second time and double its
registrations. The ``TYPE_CHECKING`` import below is the one sanctioned
use of the dotted path: it gives mypy the real module symbol table for
the exact same file, so emitted symbols stay strictly typed here (D-2).

There is deliberately no ``__main__.py``: a second handwritten module
would break the one-bootstrap-file rule that ``[tool.s0ma]``
``bootstrap_files`` declares. Direct execution goes through
:func:`main`.
"""

from __future__ import annotations

import atexit
import sys
import webbrowser
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    # Static identity for type checkers only — the same files the
    # bootstrap imports below under their flat names (see the
    # docstring).
    from s0ma_studi0._built import sh0w_assets as sh0w_assets
    from s0ma_studi0._built import studi0_narration as studi0_narration
    from s0ma_studi0._built import studi0_server as studi0_server
    from s0ma_studi0._built import studi0_state as studi0_state
    from s0ma_studi0._built import studi0_watch as studi0_watch

__version__ = "0.19.1"

__all__ = [
    "__version__",
    "launch",
    "main",
    "sh0w_assets",
    "studi0_narration",
    "studi0_server",
    "studi0_state",
    "studi0_watch",
]

if not TYPE_CHECKING:
    # M10: the loader lives in Apache-licensed s0ma-core, so a package
    # that ships its own committed build boots without the authoring
    # packages on the runtime path (INV-9).
    from s0ma.bootstrap import bootstrap_imports

    # One module object per built module, executed exactly once under
    # its canonical flat name (the DSL's import contract: build_dir on
    # sys.path, manifest-driven topological order).
    _built_modules = bootstrap_imports(Path(__file__).parent / "_built")

    # Package-namespace alias: the same module object is reachable as
    # s0ma_studi0.studi0_server (attribute AND sys.modules entry), so
    # `from s0ma_studi0.studi0_server import route_request` and
    # `import s0ma_studi0.studi0_server` both work. One object, two
    # names — never two executions.
    sh0w_assets = _built_modules["sh0w_assets"]
    studi0_narration = _built_modules["studi0_narration"]
    studi0_server = _built_modules["studi0_server"]
    studi0_state = _built_modules["studi0_state"]
    studi0_watch = _built_modules["studi0_watch"]
    for _flat_name in (
        "sh0w_assets",
        "studi0_narration",
        "studi0_server",
        "studi0_state",
        "studi0_watch",
    ):
        sys.modules[__name__ + "." + _flat_name] = _built_modules[_flat_name]


def launch(
    project_root: Path,
    *,
    port: int = 0,
    open_browser: bool = True,
) -> int:
    """Serve studi0 for one project until interrupted; return the exit code.

    The frozen entry point the ``s0ma studi0`` subcommand calls. Opens a
    viewing session on the project and starts the watch that keeps it
    current, so the graph API is already truthful before the first
    request arrives. Binds the loopback interface only — studi0 is
    never offered to another machine — prints exactly one line naming
    the project and the URL it is really serving, opens a browser there
    unless asked not to, then serves until Ctrl-C (or until another
    thread calls ``shutdown()`` on the server). The watch is stopped on
    every exit path, including a failure to bind.

    Once the socket is really bound, the project is marked as watched:
    ``.s0ma/studi0/active.json`` carries this process's id and the port
    that was actually bound. That marker is how the authoring MCP
    server knows to ask an agent for narration — and, in its absence,
    knows not to. It is written after the bind (so it never advertises
    a port nothing is listening on) and removed on the way out, by the
    same ``finally`` that stops the watch and, belt and braces, by an
    ``atexit`` hook for the exit paths that never unwind this frame.

    Args:
        project_root: The project to show. Opened read-only apart from
            that one presence marker; studi0 writes nothing else into
            the target tree.
        port: The port to bind, or 0 (the default) to let the OS assign
            a free one. The printed URL always carries the real port.
        open_browser: Open the URL in the user's browser once the server
            is bound. ``False`` is the ``--no-open`` behavior, and the
            only form tests should use.

    Returns:
        The process exit code: 0 after a clean shutdown.
    """
    session = studi0_state.create_session(project_root)
    watcher = studi0_watch.start_watcher(session)

    def _unmark() -> None:
        """Take this launch's presence marker back down."""
        studi0_narration.clear_presence(project_root)

    marked = False
    try:
        server = studi0_server.create_server(project_root, port, session)
        address = studi0_server.bound_address(server)
        url = f"http://{address['host']}:{address['port']}/"
        studi0_narration.write_presence(project_root, address["port"])
        # A closure per launch, so unregistering this one cannot cancel
        # another launch's hook in the same process.
        atexit.register(_unmark)
        marked = True
        # Flushed explicitly: this line is the only way a caller learns
        # the URL, and stdout is block-buffered whenever it is not a
        # terminal (a pipe, a CI log, an agent capturing the
        # subprocess) — without the flush the line would not appear
        # until the server exits.
        print(
            f"studi0 serving {studi0_server.project_display_name(project_root)} at {url}",
            flush=True,
        )
        if open_browser:
            webbrowser.open(url)
        return studi0_server.run_server(server)
    finally:
        if marked:
            atexit.unregister(_unmark)
            _unmark()
        studi0_watch.stop_watcher(watcher)


def main(argv: list[str] | None = None) -> int:
    """Run :func:`launch` for a project root given on the command line.

    Direct-execution entry point, kept deliberately thin: the supported
    door is ``s0ma studi0``, which owns the flags (``--port``,
    ``--no-open``). Here a single optional positional argument names the
    project root; without it, the current directory is shown.

    Args:
        argv: Argument list to read instead of ``sys.argv[1:]``.

    Returns:
        The process exit code from :func:`launch`.
    """
    arguments = list(sys.argv[1:] if argv is None else argv)
    project_root = Path(arguments[0]) if arguments else Path.cwd()
    return launch(project_root)
