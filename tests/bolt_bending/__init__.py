"""Makes tests/bolt_bending a package. Do not delete.

`test_app_smoke.py` and `test_kernel.py` share their basenames with files in
`tests/tierod/`. Without this file pytest imports both as the same top-level
module name and collection fails with an import-file-mismatch error.
"""
