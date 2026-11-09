"""Key/value settings stored in the database (admin account, API token)."""

import sqlite3

from src.database import get_db


def get(key, default=None):
    row = get_db().execute('SELECT value FROM settings WHERE key = ?', (key,)).fetchone()
    return row['value'] if row else default


def put(key, value):
    db = get_db()
    db.execute('INSERT INTO settings (key, value) VALUES (?, ?) '
               'ON CONFLICT(key) DO UPDATE SET value = excluded.value', (key, value))
    db.commit()


def delete(key):
    db = get_db()
    db.execute('DELETE FROM settings WHERE key = ?', (key,))
    db.commit()


def insert_once(values):
    """Insert several keys atomically; return False if any already exists.

    Used by first-run setup so two people submitting at once can't both win.
    """
    db = get_db()
    try:
        with db:
            db.executemany('INSERT INTO settings (key, value) VALUES (?, ?)', values.items())
    except sqlite3.IntegrityError:
        return False
    return True
