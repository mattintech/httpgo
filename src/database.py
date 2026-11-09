"""Database connection and initialization."""

import sqlite3
from pathlib import Path

from flask import current_app, g

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


def init_db(app):
    """Initialize the database schema."""
    path = app.config['DATABASE_PATH']
    Path(path).resolve().parent.mkdir(parents=True, exist_ok=True)
    db = _connect(path)
    try:
        # WAL lets readers (redirects) proceed while a write is in progress,
        # which matters with multiple gunicorn workers.
        db.execute('PRAGMA journal_mode = WAL')
        db.executescript(SCHEMA)
        db.commit()
    finally:
        db.close()
