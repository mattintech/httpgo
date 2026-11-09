"""Authentication (none / password / OIDC), API tokens and CSRF protection.

Password mode takes its credentials from ADMIN_PASSWORD / ADMIN_PASSWORD_HASH
if set, otherwise from the admin account created in the first-run setup page.
"""

import hashlib
import hmac
import secrets
import threading
import time
from urllib.parse import urlsplit

from flask import (Blueprint, abort, current_app, flash, jsonify, redirect,
                   render_template, request, session, url_for)
from werkzeug.security import check_password_hash, generate_password_hash

from src.models import settings

auth_bp = Blueprint('auth', __name__)

_oauth = None

# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------


def auth_mode():
    return current_app.config['AUTH_MODE']


MIN_PASSWORD_LENGTH = 8


def env_credentials():
    """True when the admin password is managed by environment variables."""
    cfg = current_app.config
    return bool(cfg.get('ADMIN_PASSWORD') or cfg.get('ADMIN_PASSWORD_HASH'))


def needs_setup():
    """Password mode with no account yet: the first-run setup page is live."""
    return (auth_mode() == 'password' and not env_credentials()
            and settings.get('admin_password_hash') is None)


def _session_epoch():
    """Random value stored with the account; rotating it signs out every session."""
    epoch = settings.get('session_epoch')
    if epoch is None:
        epoch = secrets.token_hex(8)
        settings.put('session_epoch', epoch)
    return epoch


def current_user():
    """The logged-in user's display name, or None."""
    user = session.get('user')
    if user and session.get('epoch') != _session_epoch():
        session.clear()
        return None
    return user


def _safe_next(target):
    """Only allow relative, same-site redirect targets after login."""
    if not target:
        return url_for('admin.index')
    parts = urlsplit(target)
    if parts.scheme or parts.netloc or not target.startswith('/') or target.startswith('//') \
            or '\\' in target:
        return url_for('admin.index')
    return target


def hash_api_token(token):
    # API tokens are long random strings, so a fast hash is appropriate.
    return hashlib.sha256(token.encode()).hexdigest()


def has_valid_api_token():
    header = request.headers.get('Authorization', '')
    if not header.startswith('Bearer '):
        return False
    sent = header[len('Bearer '):].strip()
    if not sent:
        return False
    env_token = current_app.config.get('ADMIN_API_TOKEN')
    if env_token and hmac.compare_digest(sent.encode(), env_token.encode()):
        return True
    stored = settings.get('api_token_hash')
    return bool(stored) and hmac.compare_digest(hash_api_token(sent), stored)


def is_authorized():
    if auth_mode() == 'none':
        return True
    return bool(current_user()) or has_valid_api_token()


def require_admin():
    """before_request hook for the admin blueprint."""
    if is_authorized():
        return None
    if request.path.startswith('/admin/api/'):
        if needs_setup():
            return jsonify({'error': 'Setup required: open /setup in a browser'}), 503
        return jsonify({'error': 'Authentication required'}), 401
    if needs_setup():
        return redirect(url_for('auth.setup'))
    return redirect(url_for('auth.login', next=request.full_path.rstrip('?')))


def login_user(name):
    # Clear first to prevent session fixation; keep nothing from before login.
    session.clear()
    session.permanent = True
    session['user'] = name
    session['epoch'] = _session_epoch()


# --------------------------------------------------------------------------
# CSRF
# --------------------------------------------------------------------------


def csrf_token():
    if '_csrf' not in session:
        session['_csrf'] = secrets.token_urlsafe(32)
    return session['_csrf']


def csrf_protect():
    """Reject cross-site form POSTs that lack a valid CSRF token.

    Only "simple" requests need a token: a browser can send a cross-site
    POST with a form/text content type without asking first, but PUT,
    PATCH, DELETE and application/json bodies all require a CORS preflight,
    which this app never approves. Bearer-token API calls carry no ambient
    credentials and are likewise exempt.
    """
    if request.method != 'POST':
        return
    if request.is_json or has_valid_api_token():
        return
    sent = request.form.get('csrf_token') or request.headers.get('X-CSRF-Token', '')
    expected = session.get('_csrf')
    if not expected or not hmac.compare_digest(sent.encode(), expected.encode()):
        abort(400, description='Your session expired or the form was submitted '
                               'from another site. Reload the page and try again.')


# --------------------------------------------------------------------------
# Password login (with a small in-memory brute-force throttle)
# --------------------------------------------------------------------------

_MAX_FAILURES = 5
_WINDOW = 15 * 60
_failures = {}
_failures_lock = threading.Lock()


def _throttled(ip):
    now = time.monotonic()
    with _failures_lock:
        recent = [t for t in _failures.get(ip, []) if now - t < _WINDOW]
        _failures[ip] = recent
        return len(recent) >= _MAX_FAILURES


def _record_failure(ip):
    with _failures_lock:
        _failures.setdefault(ip, []).append(time.monotonic())


def admin_username():
    if env_credentials():
        return current_app.config['ADMIN_USERNAME']
    return settings.get('admin_username')


def check_password(username, password):
    cfg = current_app.config
    expected_user = admin_username()
    if not expected_user:
        return False
    user_ok = hmac.compare_digest(username.strip().lower().encode(), expected_user.lower().encode())
    if cfg.get('ADMIN_PASSWORD_HASH'):
        pass_ok = check_password_hash(cfg['ADMIN_PASSWORD_HASH'], password)
    elif cfg.get('ADMIN_PASSWORD'):
        pass_ok = hmac.compare_digest(password.encode(), cfg['ADMIN_PASSWORD'].encode())
    else:
        pass_ok = check_password_hash(settings.get('admin_password_hash', ''), password)
    return user_ok and pass_ok


def validate_new_password(password, confirm):
    if len(password) < MIN_PASSWORD_LENGTH:
        return f'Password must be at least {MIN_PASSWORD_LENGTH} characters.'
    if password != confirm:
        return "Passwords don't match."
    return None


def set_admin_password(password):
    """Change the stored password and sign out every other session."""
    settings.put('admin_password_hash', generate_password_hash(password))
    settings.put('session_epoch', secrets.token_hex(8))


# --------------------------------------------------------------------------
# OIDC
# --------------------------------------------------------------------------


def init_oidc(app):
    global _oauth
    from authlib.integrations.flask_client import OAuth

    _oauth = OAuth(app)
    _oauth.register(
        'oidc',
        server_metadata_url=app.config['OIDC_DISCOVERY_URL'],
        client_id=app.config['OIDC_CLIENT_ID'],
        client_secret=app.config['OIDC_CLIENT_SECRET'],
        client_kwargs={'scope': app.config['OIDC_SCOPES']},
    )


def is_email_allowed(config, email, email_verified=True):
    if not email or email_verified is False:
        return False
    email = email.lower()
    if email in config['ADMIN_EMAILS']:
        return True
    domain = email.rsplit('@', 1)[-1]
    if domain in config['ADMIN_EMAIL_DOMAINS']:
        return True
    return bool(config.get('OIDC_ALLOW_ANY_USER'))


# --------------------------------------------------------------------------
# Routes
# --------------------------------------------------------------------------


@auth_bp.route('/login', methods=['GET', 'POST'])
def login():
    mode = auth_mode()
    next_url = _safe_next(request.values.get('next'))

    if mode == 'none' or current_user():
        return redirect(next_url)
    if needs_setup():
        return redirect(url_for('auth.setup'))

    if mode == 'oidc':
        if request.method == 'POST':
            session['login_next'] = next_url
            return _oauth.oidc.authorize_redirect(url_for('auth.callback', _external=True))
        return render_template('login.html', next=next_url)

    # Password mode
    if request.method == 'POST':
        ip = request.remote_addr or 'unknown'
        if _throttled(ip):
            flash('Too many failed attempts. Try again in a few minutes.', 'error')
            return render_template('login.html', next=next_url), 429
        if check_password(request.form.get('username', ''), request.form.get('password', '')):
            login_user(admin_username())
            return redirect(next_url)
        _record_failure(ip)
        flash('Incorrect username or password.', 'error')
        return render_template('login.html', next=next_url), 401

    return render_template('login.html', next=next_url)


@auth_bp.route('/setup', methods=['GET', 'POST'])
def setup():
    """First-run page: create the admin account. Gone once an account exists."""
    if not needs_setup():
        return redirect(url_for('admin.index'))

    username = request.form.get('username', '').strip()
    if request.method == 'POST':
        error = validate_new_password(request.form.get('password', ''),
                                      request.form.get('confirm', ''))
        if not username:
            error = 'Choose a username.'
        if error:
            flash(error, 'error')
            return render_template('setup.html', username=username), 400

        created = settings.insert_once({
            'admin_username': username,
            'admin_password_hash': generate_password_hash(request.form['password']),
        })
        if not created:
            flash('Setup was already completed. Sign in instead.', 'error')
            return redirect(url_for('auth.login'))

        current_app.logger.info('Admin account %r created via setup page', username)
        login_user(username)
        flash(f'Welcome, {username}! Add your first link to get started.', 'success')
        return redirect(url_for('admin.index'))

    return render_template('setup.html', username=username or 'admin')


@auth_bp.route('/auth/callback')
def callback():
    if auth_mode() != 'oidc':
        abort(404)
    try:
        token = _oauth.oidc.authorize_access_token()
    except Exception as e:  # authlib raises a variety of OAuthError subclasses
        current_app.logger.warning('OIDC login failed: %s', e)
        flash('Sign-in failed. Please try again.', 'error')
        return redirect(url_for('auth.login'))

    info = token.get('userinfo') or _oauth.oidc.userinfo(token=token)
    email = info.get('email')
    if not is_email_allowed(current_app.config, email, info.get('email_verified', True)):
        current_app.logger.warning('OIDC user %r is not allowed to manage links', email)
        flash(f'{email or "This account"} is not allowed to manage links.', 'error')
        return redirect(url_for('auth.login'))

    next_url = _safe_next(session.get('login_next'))
    login_user(email)
    return redirect(next_url)


@auth_bp.route('/logout', methods=['POST'])
def logout():
    session.clear()
    return redirect(url_for('directory.index'))

