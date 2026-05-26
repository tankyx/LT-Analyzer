"""Top-level pytest conftest.

The pre-Phase-1 conftest used to install autouse fixtures that mocked
`sqlite3.connect`, `aiosqlite.connect`, the parser, the race_data dict, and
the track database globally. That collides with auth tests that need real
SQL semantics (constraints, partial unique indexes, transactions). Those
fixtures have moved to per-package conftests (`tests/test_api/conftest.py`
and `tests/test_websocket/conftest.py`), so the legacy test suites still
get them but new packages get a clean slate.

Only truly cross-cutting fixtures stay here.
"""

import logging
import os
import sys

import pytest

# Make project root importable for `import race_ui` etc.
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))


@pytest.fixture(autouse=True)
def disable_logging():
    """Silence loggers during tests to keep output readable."""
    logging.disable(logging.CRITICAL)
    yield
    logging.disable(logging.NOTSET)
