"""Read-only SQLite connections (added 2026-11-05, refactor stage 3).

Before, eight modules each built the same URI by hand. The operations scripts (backup.py, export.py, check.py) and the
dashboard keep their own one-line copy on purpose: they must keep working when anything else in the folder is broken
(tests/test_kill.py runs the dashboard from a bare folder), so they depend on the standard library only.

connect_ro(path) opens an existing database read-only through SQLite's URI "mode=ro": SQLite itself refuses any write
on it, and a missing file raises sqlite3.OperationalError instead of creating an empty database. Python 3.8+."""
import sqlite3
from pathlib import Path


def uri_ro(path):
    """The read-only URI for path: file:///abs/path?mode=ro (percent-encoded, so spaces and '#' are safe)."""
    return Path(path).resolve().as_uri() + "?mode=ro"


def connect_ro(path, row_factory=None):
    """A read-only connection to an existing SQLite file; row_factory (for example sqlite3.Row) is set when given."""
    c = sqlite3.connect(uri_ro(path), uri=True)
    if row_factory is not None:
        c.row_factory = row_factory
    return c
