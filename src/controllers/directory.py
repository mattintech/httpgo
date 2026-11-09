"""Directory controller - public listing of all go-links."""

from flask import Blueprint, current_app, jsonify, render_template, request

from src.database import get_db
from src.models.link import Link

directory_bp = Blueprint('directory', __name__)


@directory_bp.route('/')
def index():
    links = Link.get_all(order_by='shortname')
    return render_template('directory.html', links=links)


@directory_bp.route('/api/search')
def search():
    query = request.args.get('q', '').strip()
    links = Link.search(query) if query else Link.get_all(order_by='shortname')
    return jsonify([link.to_dict() for link in links])


@directory_bp.route('/favicon.ico')
def favicon():
    return current_app.send_static_file('favicon.svg'), 200, {'Content-Type': 'image/svg+xml'}


@directory_bp.route('/healthz')
def healthz():
    get_db().execute('SELECT 1').fetchone()
    return {'status': 'ok'}
