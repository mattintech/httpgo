"""Application configuration, read from environment variables."""

import logging
import os
import secrets
from pathlib import Path

log = logging.getLogger(__name__)

AUTH_MODES = ('none', 'password', 'oidc')


def _bool(value, default=False):
    if value is None or value == '':
        return default
    return value.strip().lower() in ('1', 'true', 'yes', 'on')


def _list(value):
    return [item.strip().lower() for item in (value or '').split(',') if item.strip()]


def _load_secret_key(database_path):
    """Use SECRET_KEY if set, otherwise generate one and persist it next to the DB.

    Persisting means sessions survive restarts and are shared across workers
    without the operator having to manage a secret by hand.
    """
    key = os.environ.get('SECRET_KEY')
    if key:
        return key

    key_file = Path(database_path).resolve().parent / 'secret_key'
    try:
        return key_file.read_text().strip()
    except FileNotFoundError:
        pass

    key = secrets.token_hex(32)
    try:
        key_file.parent.mkdir(parents=True, exist_ok=True)
        # O_EXCL so concurrent workers don't clobber each other's key.
        fd = os.open(key_file, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, 'w') as f:
            f.write(key)
    except FileExistsError:
        return key_file.read_text().strip()
    except OSError as e:
        log.warning('Could not persist secret key to %s (%s); sessions will '
                    'not survive restarts. Set SECRET_KEY to fix.', key_file, e)
    return key


def from_env():
    """Build the Flask config dict from the environment."""
    database_path = os.environ.get('DATABASE_PATH', 'golinks.db')
    auth_mode = os.environ.get('AUTH_MODE', 'password').strip().lower()

    return {
        'DATABASE_PATH': database_path,
        'SECRET_KEY': _load_secret_key(database_path),
        'SITE_NAME': os.environ.get('SITE_NAME', 'go'),

        # Auth: none | password | oidc
        'AUTH_MODE': auth_mode,
        'ADMIN_USERNAME': os.environ.get('ADMIN_USERNAME', 'admin'),
        'ADMIN_PASSWORD': os.environ.get('ADMIN_PASSWORD'),
        'ADMIN_PASSWORD_HASH': os.environ.get('ADMIN_PASSWORD_HASH'),
        'ADMIN_API_TOKEN': os.environ.get('ADMIN_API_TOKEN'),

        'OIDC_DISCOVERY_URL': os.environ.get('OIDC_DISCOVERY_URL'),
        'OIDC_CLIENT_ID': os.environ.get('OIDC_CLIENT_ID'),
        'OIDC_CLIENT_SECRET': os.environ.get('OIDC_CLIENT_SECRET'),
        'OIDC_SCOPES': os.environ.get('OIDC_SCOPES', 'openid email profile'),
        'OIDC_PROVIDER_NAME': os.environ.get('OIDC_PROVIDER_NAME', 'SSO'),
        'ADMIN_EMAILS': _list(os.environ.get('ADMIN_EMAILS')),
        'ADMIN_EMAIL_DOMAINS': _list(os.environ.get('ADMIN_EMAIL_DOMAINS')),
        'OIDC_ALLOW_ANY_USER': _bool(os.environ.get('OIDC_ALLOW_ANY_USER')),

        # Deployment
        'TRUSTED_PROXIES': int(os.environ.get('TRUSTED_PROXIES', '0')),
        'SESSION_COOKIE_SECURE': _bool(os.environ.get('SESSION_COOKIE_SECURE')),
    }


def validate(config):
    """Fail fast on misconfiguration rather than at first login."""
    mode = config['AUTH_MODE']
    if mode not in AUTH_MODES:
        raise RuntimeError(f"AUTH_MODE must be one of {', '.join(AUTH_MODES)} (got {mode!r})")

    if mode == 'oidc':
        missing = [k for k in ('OIDC_DISCOVERY_URL', 'OIDC_CLIENT_ID', 'OIDC_CLIENT_SECRET')
                   if not config.get(k)]
        if missing:
            raise RuntimeError(f"AUTH_MODE=oidc requires {', '.join(missing)}")
        if not (config.get('ADMIN_EMAILS') or config.get('ADMIN_EMAIL_DOMAINS')
                or config.get('OIDC_ALLOW_ANY_USER')):
            raise RuntimeError(
                'AUTH_MODE=oidc requires ADMIN_EMAILS or ADMIN_EMAIL_DOMAINS to restrict '
                'who can manage links (or OIDC_ALLOW_ANY_USER=true if your provider '
                'only contains trusted users)')

    if mode == 'none':
        log.warning('AUTH_MODE=none: anyone who can reach this server can add, edit '
                    'and delete links. Set AUTH_MODE=password or AUTH_MODE=oidc.')
