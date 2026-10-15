"""Fixtures for documentation-subsystem import-hook tests (plan M3).

Each module here simulates generated-code output from the s0ma-dsl
transpiler: a module-level ``__s0ma_doc_ref__`` / ``__s0ma_doc_guide__``
/ ``__s0ma_example__`` marker, optionally paired with the matching
``register_doc_ref`` / ``register_doc_guide`` / ``register_example``
call. Some fixtures intentionally omit the registration call to exercise
the import hook's missing-declaration diagnostics.
"""
