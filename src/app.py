"""Flask application factory."""

import zlib
from datetime import timedelta

from flask import Flask, render_template
from werkzeug.exceptions import HTTPException
from werkzeug.middleware.proxy_fix import ProxyFix

from src import auth, config as app_config
from src.database import close_db, init_db

CSP = ("default-src 'self'; img-src 'self' data:; style-src 'self'; script-src 'self'; "
       "frame-ancestors 'none'; base-uri 'none'")


def create_app(overrides=None):
    """Create and configure the Flask application.

    `overrides` is merged over the environment-derived config (used by tests).
    """
    app = Flask(__name__, template_folder='views/templates', static_folder='views/static')

    app.config.update(app_config.from_env())
    app.config.update(
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE='Lax',
        PERMANENT_SESSION_LIFETIME=timedelta(days=14),
    )
    if overrides:
        app.config.update(overrides)
    app_config.validate(app.config)

    if app.config['TRUSTED_PROXIES']:
        n = app.config['TRUSTED_PROXIES']
        app.wsgi_app = ProxyFix(app.wsgi_app, x_for=n, x_proto=n, x_host=n, x_prefix=n)

    if app.config['AUTH_MODE'] == 'oidc':
        auth.init_oidc(app)

    app.teardown_appcontext(close_db)
    app.before_request(auth.csrf_protect)

    @app.template_filter('swatch')
    def swatch(name):
        """Stable colour index (0-7) for a link, so it keeps its colour across visits."""
        return zlib.crc32((name or '').encode()) % 8

    @app.context_processor
    def inject_globals():
        return {
            'csrf_token': auth.csrf_token,
            'current_user': auth.current_user(),
            'auth_mode': app.config['AUTH_MODE'],
            'site_name': app.config['SITE_NAME'],
            'can_manage': auth.is_authorized(),
        }

    @app.after_request
    def security_headers(response):
        response.headers.setdefault('X-Content-Type-Options', 'nosniff')
        response.headers.setdefault('Referrer-Policy', 'strict-origin-when-cross-origin')
        if response.mimetype == 'text/html':
            response.headers.setdefault('Content-Security-Policy', CSP)
        return response

    @app.errorhandler(HTTPException)
    def http_error(e):
        if e.code in (400, 403, 405, 500):
            return render_template('error.html', error=e), e.code
        return e

    from src.controllers.admin import admin_bp
    from src.controllers.directory import directory_bp
    from src.controllers.redirect import redirect_bp

    app.register_blueprint(auth.auth_bp)
    app.register_blueprint(directory_bp)
    app.register_blueprint(admin_bp)
    app.register_blueprint(redirect_bp)  # Must be last (catch-all route)

    init_db(app)

    if app.config['AUTH_MODE'] == 'password':
        with app.app_context():
            if auth.needs_setup():
                app.logger.warning('No admin account yet: open /setup in a browser to create one.')
    return app
