"""Pipeline bootstrap: the single handwritten entry point.

This is the one sanctioned plain-Python module in the project (declared in
``[tool.s0ma].bootstrap_files``). Everything else is authored as ``.s0ma``
and emitted into the build directory; this file only hands the song the
player reads to the page, and prints the page.

Run it after a build (``s0ma build .``)::

    python bootstrap/main.py        # the first built-in song
    python bootstrap/main.py 1      # the second one
"""

from __future__ import annotations

import sys
from pathlib import Path

from s0ma.bootstrap import bootstrap_imports


def main(turn: int = 0) -> str:
    """Read the song for *turn*, build its page, and print it."""
    build_dir = Path(__file__).resolve().parent.parent / "build"
    modules = bootstrap_imports(build_dir.as_posix())

    track = modules["player"].read_now_playing(turn)
    text: str = modules["page"].song_to_page(track)
    print(f"now playing: {track.title} by {track.artist}")
    print(text, end="")
    return text


if __name__ == "__main__":
    main(int(sys.argv[1]) if len(sys.argv) > 1 else 0)
