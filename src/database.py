"""Database connection and initialization."""

import logging
import sqlite3
from pathlib import Path

from flask import current_app, g

log = logging.getLogger(__name__)

SCHEMA = '''
    CREATE TABLE IF NOT EXISTS links (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        shortname TEXT UNIQUE NOT NULL,
        url TEXT NOT NULL,
        description TEXT,
        hits INTEGER DEFAULT 0,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );
    CREATE TABLE IF NOT EXISTS settings (
        key TEXT PRIMARY KEY,
        value TEXT NOT NULL
    );
'''


def _connect(path):
    db = sqlite3.connect(path, timeout=10)
    db.row_factory = sqlite3.Row
    db.execute('PRAGMA busy_timeout = 10000')
    return db


def get_db():
    """Get database connection for current request."""
    if 'db' not in g:
        g.db = _connect(current_app.config['DATABASE_PATH'])
    return g.db


def close_db(exception=None):
    """Close database connection at end of request."""
    db = g.pop('db', None)
    if db is not None:
        db.close()


def _set_journal_mode(db, mode):
    """Apply the configured journal mode; never fatal.

    WAL lets redirects read while a write is in progress, but SQLite does not
    support it on network filesystems (NFS/SMB), where DELETE is the safe choice.
    """
    try:
        actual = db.execute(f'PRAGMA journal_mode = {mode}').fetchone()[0].upper()
    except sqlite3.OperationalError as e:
        log.warning('Could not set SQLite journal mode to %s (%s); continuing.', mode, e)
        return
    if actual != mode:
        log.warning('SQLite journal mode is %s, not %s as configured.', actual, mode)


def init_db(app):
    """Initialize the database schema."""
    path = app.config['DATABASE_PATH']
    Path(path).resolve().parent.mkdir(parents=True, exist_ok=True)
    db = _connect(path)
    try:
        _set_journal_mode(db, app.config['SQLITE_JOURNAL_MODE'])
        db.executescript(SCHEMA)
        db.commit()
    finally:
        db.close()
