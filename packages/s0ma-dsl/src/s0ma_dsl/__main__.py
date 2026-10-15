"""Package entry point: ``python -m s0ma_dsl``.

DSL-M4 (F-M0-3, A-16): delegating to :func:`s0ma_dsl.cli.main.main`
from a package-level ``__main__`` lets ``python -m s0ma_dsl`` run the
CLI without the runpy ``RuntimeWarning`` that ``python -m
s0ma_dsl.cli.main`` triggers ("found in sys.modules after import of
package ... this may result in unpredictable behaviour" — raised because
the CLI package imports its own ``main`` submodule). The console script
``s0ma`` (``s0ma_dsl.cli.main:main``) remains the primary invocation;
this is the clean ``-m`` form for tooling (e.g. ``scripts/check.py``'s
self-host build stage).
"""

from __future__ import annotations

from s0ma_dsl.cli.main import main

if __name__ == "__main__":
    main()
