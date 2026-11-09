"""Link model for managing URL shortcuts."""

import re
import sqlite3
from datetime import datetime, timezone
from urllib.parse import urlsplit

from src.database import get_db

# Names that collide with application routes.
RESERVED_NAMES = {
    'admin', 'api', 'static', 'favicon.ico', 'healthz',
    'login', 'logout', 'auth', 'setup',
}

SHORTNAME_RE = re.compile(r'^[a-z0-9][a-z0-9_-]{0,63}$')
ALLOWED_SCHEMES = {'http', 'https'}
ORDER_COLUMNS = {
    'shortname': 'shortname',
    'hits': 'hits DESC, shortname',
    'created': 'created_at DESC, shortname',
    'updated': 'updated_at DESC, shortname',
}


def normalize_shortname(shortname):
    return (shortname or '').strip().lower()


def _utcnow():
    # Same format as SQLite's CURRENT_TIMESTAMP so all timestamps are UTC
    # and compare/sort consistently.
    return datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')


def validate_url(url):
    url = (url or '').strip()
    if not url:
        raise ValueError('URL is required')
    parts = urlsplit(url)
    if parts.scheme.lower() not in ALLOWED_SCHEMES or not parts.netloc:
        raise ValueError('URL must be a full http:// or https:// address')
    return url


def validate_shortname(shortname):
    shortname = normalize_shortname(shortname)
    if not shortname:
        raise ValueError('Shortname is required')
    if shortname in RESERVED_NAMES:
        raise ValueError(f"'{shortname}' is a reserved name")
    if not SHORTNAME_RE.match(shortname):
        raise ValueError('Shortname must be 1-64 characters: letters, numbers, '
                         'hyphens and underscores, starting with a letter or number')
    return shortname


class Link:
    """Model for go-links."""

    def __init__(self, id=None, shortname=None, url=None, description=None,
                 hits=0, created_at=None, updated_at=None):
        self.id = id
        self.shortname = shortname
        self.url = url
        self.description = description
        self.hits = hits
        self.created_at = created_at
        self.updated_at = updated_at

    def to_dict(self):
        """Convert link to dictionary."""
        return {
            'id': self.id,
            'shortname': self.shortname,
            'url': self.url,
            'description': self.description,
            'hits': self.hits,
            'created_at': str(self.created_at) if self.created_at else None,
            'updated_at': str(self.updated_at) if self.updated_at else None,
        }

    @staticmethod
    def _row_to_link(row):
        if row is None:
            return None
        return Link(**{key: row[key] for key in row.keys()})

    @staticmethod
    def get_all(order_by='shortname'):
        """Get all links ordered by one of ORDER_COLUMNS."""
        if order_by not in ORDER_COLUMNS:
            raise ValueError(f'Cannot order by {order_by!r}')
        rows = get_db().execute(
            f'SELECT * FROM links ORDER BY {ORDER_COLUMNS[order_by]}'
        ).fetchall()
        return [Link._row_to_link(row) for row in rows]

    @staticmethod
    def get_by_shortname(shortname):
        row = get_db().execute(
            'SELECT * FROM links WHERE shortname = ?', (normalize_shortname(shortname),)
        ).fetchone()
        return Link._row_to_link(row)

    @staticmethod
    def search(query):
        """Search links by shortname, description or URL."""
        # Escape LIKE wildcards so a search for "100%" means literally that.
        escaped = query.replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_')
        term = f'%{escaped}%'
        rows = get_db().execute(
            '''SELECT * FROM links
               WHERE shortname LIKE ? ESCAPE '\\'
                  OR description LIKE ? ESCAPE '\\'
                  OR url LIKE ? ESCAPE '\\'
               ORDER BY shortname''',
            (term, term, term)
        ).fetchall()
        return [Link._row_to_link(row) for row in rows]

    @staticmethod
    def create(shortname, url, description=''):
        shortname = validate_shortname(shortname)
        url = validate_url(url)
        description = (description or '').strip()

        db = get_db()
        now = _utcnow()
        try:
            db.execute(
                'INSERT INTO links (shortname, url, description, created_at, updated_at) '
                'VALUES (?, ?, ?, ?, ?)',
                (shortname, url, description, now, now)
            )
            db.commit()
        except sqlite3.IntegrityError:
            raise ValueError(f"go/{shortname} already exists")
        return Link.get_by_shortname(shortname)

    @staticmethod
    def update(shortname, url=None, description=None):
        """Update an existing link. Fields left as None are unchanged."""
        link = Link.get_by_shortname(shortname)
        if not link:
            raise LookupError('Link not found')

        url = validate_url(url) if url is not None else link.url
        description = description.strip() if description is not None else link.description

        db = get_db()
        db.execute(
            'UPDATE links SET url = ?, description = ?, updated_at = ? WHERE shortname = ?',
            (url, description, _utcnow(), link.shortname)
        )
        db.commit()
        return Link.get_by_shortname(link.shortname)

    @staticmethod
    def delete(shortname):
        db = get_db()
        cursor = db.execute('DELETE FROM links WHERE shortname = ?',
                            (normalize_shortname(shortname),))
        db.commit()
        if cursor.rowcount == 0:
            raise LookupError('Link not found')

    @staticmethod
    def increment_hits(shortname):
        db = get_db()
        db.execute('UPDATE links SET hits = hits + 1 WHERE shortname = ?',
                   (normalize_shortname(shortname),))
        db.commit()
