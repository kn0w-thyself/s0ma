# M6b legacy_layout_project fixture

Two `.s0ma` source files used by `tests/test_migrate_layout.py` to
verify `s0ma migrate-layout` cleans pre-M6a build artifacts and emits
the M6a/M6b flat layout from scratch.

The legacy artifacts (`__s0ma_cache__/`, per-layer subdirs) are *not*
checked into the fixture — tests construct them in `tmp_path` so the
fixture tree itself stays clean and the assertions can rebuild a
known-bad pre-state on demand.
