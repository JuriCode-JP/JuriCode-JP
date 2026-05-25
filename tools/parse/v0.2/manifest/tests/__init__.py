"""Tests for tools/parse/v0.2/manifest/ package.

How to run:
    cd JuriCode-JP
    pytest tools/parse/v0.2/manifest/tests -v

Why sys.path tweak in each test file:
    Parent dir `v0.2` contains a dot which is invalid in Python module names,
    so the `manifest` package is imported via filesystem path rather than
    `tools.parse.v0.2.manifest`. Each test file inserts the parent dir into
    sys.path. Same pattern as `tools/parse/v0.2/tests/test_*.py`.
"""
