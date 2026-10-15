"""Deprecated home of ``bootstrap_imports`` — the loader now lives in s0ma-core.

The manifest-driven bootstrap moved to :mod:`s0ma.bootstrap` in 0.16.x
(M10). Importing it from here still works and behaves identically — the
name below *is* the core function, called through a thin delegating
wrapper — but the import emits a :class:`DeprecationWarning` naming the
new path::

    from s0ma.bootstrap import bootstrap_imports   # new
    from s0ma_dsl.runtime import bootstrap_imports # deprecated, still works

Why it moved
------------

``bootstrap_imports`` is the one authoring-package symbol a *deployed*
application had to import at process start. That made every s0ma-built
app depend on the transpiler at runtime — and the transpiler was then
under a proprietary license: in an environment with no authoring
packages installed, the blessed one-line bootstrap died with
``ModuleNotFoundError: No module named 's0ma_dsl'``. PRD INV-9 forbids a
license-gated import on a deployed system's boot path, so the loader
moved into ``s0ma-core`` (Apache-2.0). The authoring packages are
Apache-2.0 too now; the reason that still stands is that a deployed
application should not need the authoring toolchain installed at all. INV-2 forbids a silent
rename, so this module stays: existing bootstrap files keep working
unchanged, with a warning that names their migration.

``runtime_bridge`` is unaffected — it is the *registration adapter* a
transpiled module calls at load time, not the user-facing boot helper.
(It also exposes ``import_modules_from_manifest``, the pre-M10 helper
that imports the manifest's modules in alphabetical order;
``bootstrap_imports`` is the topological superset and the recommended
public surface.)
"""

from __future__ import annotations

import warnings
from typing import TYPE_CHECKING

from s0ma.bootstrap import bootstrap_imports as _core_bootstrap_imports

if TYPE_CHECKING:
    from pathlib import Path
    from types import ModuleType

__all__ = ["bootstrap_imports"]

warnings.warn(
    "s0ma_dsl.runtime.bootstrap_imports has moved to s0ma.bootstrap "
    "(s0ma-core). Import it as `from s0ma.bootstrap import "
    "bootstrap_imports` so deployed applications no longer need the "
    "authoring packages at runtime. This re-export still works and "
    "behaves identically.",
    DeprecationWarning,
    stacklevel=2,
)


def bootstrap_imports(
    build_dir: Path | str,
    *,
    sys_path_insert: bool = True,
    roles: tuple[str, ...] = ("source",),
) -> dict[str, ModuleType]:
    """Deprecated alias for :func:`s0ma.bootstrap.bootstrap_imports`.

    Same signature, same behaviour, same exceptions — the call is
    forwarded unchanged to the core implementation. See that function for
    the full contract; see this module's docstring for why the loader
    moved.
    """
    return _core_bootstrap_imports(
        build_dir,
        sys_path_insert=sys_path_insert,
        roles=roles,
    )
