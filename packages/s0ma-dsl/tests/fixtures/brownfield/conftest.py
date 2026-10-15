"""Keep the brownfield fixture applications out of the DSL test suite.

The directories beside this file are complete, plain-Python applications
with test suites of their own. They exist to be read, scanned, drafted and
converted by the ``s0ma adopt`` family — never to run as part of this
package's suite.

Without this file they would run anyway. ``pytest packages/s0ma-dsl/tests``
passes an explicit path, which turns off ``testpaths``, so pytest walks the
whole tree and collects any ``test_*.py`` it finds, fixture applications
included. Their assertions would then be reported as DSL test results and
their module names would go on ``sys.path``.

``collect_ignore`` is read from the conftest nearest the directory being
considered, so listing the application directories here stops the walk at
this level and nothing below is imported. The entries are relative to this
file. Every application directory — every neighbour whose name does not
start with an underscore — must be listed;
``packages/s0ma-dsl/tests/test_brownfield_fixtures.py`` fails if one is
missing, so a new fixture application cannot arrive unnoticed.

Running an application's own tests is unaffected: those runs start inside
the application directory, which is below this one, so this conftest is
never loaded for them.
"""

from __future__ import annotations

collect_ignore = [
    "layered_app",
    "multi_pkg_app",
    "tiny_app",
]
