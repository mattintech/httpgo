"""Admin controller - manage go-links (add, edit, delete)."""

import secrets
from datetime import datetime, timezone

from flask import (Blueprint, current_app, flash, jsonify, redirect, render_template,
                   request, session, url_for)

from src import auth
from src.auth import require_admin
from src.models import settings
from src.models.link import Link

admin_bp = Blueprint('admin', __name__, url_prefix='/admin')
admin_bp.before_request(require_admin)


@admin_bp.route('/')
def index():
    """Show the admin management interface.

    ?new=<name> opens the "new link" dialog pre-filled (used by the 404 page).
    """
    links = Link.get_all(order_by='shortname')
    prefill = request.args.get('new')
    if prefill is not None:
        prefill = prefill.strip().lower()
    return render_template('admin.html', links=links, prefill=prefill)


@admin_bp.route('/add', methods=['POST'])
def add():
    form = request.form
    try:
        link = Link.create(form.get('shortname', ''), form.get('url', ''),
                           form.get('description', ''))
    except ValueError as e:
        flash(str(e), 'error')
        # Re-open the dialog with what the user typed so nothing is lost.
        links = Link.get_all(order_by='shortname')
        return render_template('admin.html', links=links, form=form,
                               reopen='new', prefill=None), 400
    flash(f'Created go/{link.shortname}', 'success')
    return redirect(url_for('admin.index'))


@admin_bp.route('/edit/<shortname>', methods=['POST'])
def edit(shortname):
    try:
        link = Link.update(shortname, request.form.get('url', ''),
                           request.form.get('description', ''))
    except LookupError:
        flash(f'go/{shortname} no longer exists', 'error')
    except ValueError as e:
        flash(f'Could not save go/{shortname}: {e}', 'error')
    else:
        flash(f'Saved go/{link.shortname}', 'success')
    return redirect(url_for('admin.index'))


@admin_bp.route('/delete/<shortname>', methods=['POST'])
def delete(shortname):
    try:
        Link.delete(shortname)
    except LookupError:
        flash(f'go/{shortname} no longer exists', 'error')
    else:
        flash(f'Deleted go/{shortname}', 'success')
    return redirect(url_for('admin.index'))


# Settings --------------------------------------------------------------------

def _render_settings(status=200):
    return render_template(
        'settings.html',
        password_managed_by_env=auth.env_credentials(),
        username=auth.admin_username(),
        env_api_token=bool(current_app.config.get('ADMIN_API_TOKEN')),
        api_token_created=settings.get('api_token_created'),
        # Shown exactly once (only the hash is stored), then dropped from the session.
        new_token=session.pop('new_api_token', None),
    ), status


@admin_bp.route('/settings')
def settings_page():
    if auth.auth_mode() == 'none':
        flash('Sign-in is turned off (AUTH_MODE=none), so there is nothing to configure.', 'error')
        return redirect(url_for('admin.index'))
    return _render_settings()


@admin_bp.route('/settings/password', methods=['POST'])
def change_password():
    if auth.auth_mode() != 'password' or auth.env_credentials():
        flash('The password is managed by environment variables.', 'error')
        return redirect(url_for('admin.settings_page'))

    form = request.form
    if not auth.check_password(auth.admin_username(), form.get('current', '')):
        flash('Current password is incorrect.', 'error')
        return _render_settings(status=400)
    error = auth.validate_new_password(form.get('password', ''), form.get('confirm', ''))
    if error:
        flash(error, 'error')
        return _render_settings(status=400)

    auth.set_admin_password(form['password'])
    auth.login_user(auth.admin_username())  # keep this session; others are signed out
    flash('Password changed. Other devices have been signed out.', 'success')
    return redirect(url_for('admin.settings_page'))


@admin_bp.route('/settings/token', methods=['POST'])
def generate_token():
    token = 'hgo_' + secrets.token_urlsafe(32)
    settings.put('api_token_hash', auth.hash_api_token(token))
    settings.put('api_token_created',
                 datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC'))
    session['new_api_token'] = token
    return redirect(url_for('admin.settings_page'))


@admin_bp.route('/settings/token/revoke', methods=['POST'])
def revoke_token():
    settings.delete('api_token_hash')
    settings.delete('api_token_created')
    flash('API token revoked.', 'success')
    return redirect(url_for('admin.settings_page'))


# REST API endpoints for programmatic access ---------------------------------

def _json_body():
    data = request.get_json(silent=True)
    return data if isinstance(data, dict) else None


@admin_bp.route('/api/links', methods=['GET'])
def api_list():
    return jsonify([link.to_dict() for link in Link.get_all()])


@admin_bp.route('/api/links', methods=['POST'])
def api_create():
    data = _json_body()
    if data is None:
        return jsonify({'error': 'JSON object body required'}), 400
    try:
        link = Link.create(data.get('shortname', ''), data.get('url', ''),
                           data.get('description', ''))
    except ValueError as e:
        status = 409 if 'already exists' in str(e) else 400
        return jsonify({'error': str(e)}), status
    return jsonify(link.to_dict()), 201


@admin_bp.route('/api/links/<shortname>', methods=['GET'])
def api_get(shortname):
    link = Link.get_by_shortname(shortname)
    if not link:
        return jsonify({'error': 'Link not found'}), 404
    return jsonify(link.to_dict())


@admin_bp.route('/api/links/<shortname>', methods=['PUT', 'PATCH'])
def api_update(shortname):
    data = _json_body()
    if data is None:
        return jsonify({'error': 'JSON object body required'}), 400
    try:
        link = Link.update(shortname, data.get('url'), data.get('description'))
    except LookupError as e:
        return jsonify({'error': str(e)}), 404
    except ValueError as e:
        return jsonify({'error': str(e)}), 400
    return jsonify(link.to_dict())


@admin_bp.route('/api/links/<shortname>', methods=['DELETE'])
def api_delete(shortname):
    try:
        Link.delete(shortname)
    except LookupError as e:
        return jsonify({'error': str(e)}), 404
    return '', 204
