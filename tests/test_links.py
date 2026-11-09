import sqlite3

import pytest

from tests.conftest import csrf


def test_redirect_and_hits(client, add_link):
    add_link('wiki', 'https://wiki.example.com')
    resp = client.get('/wiki')
    assert resp.status_code == 302
    assert resp.headers['Location'] == 'https://wiki.example.com'
    assert client.get('/admin/api/links/wiki').get_json()['hits'] == 1


def test_lookup_is_case_insensitive_everywhere(client, add_link):
    add_link('MyApp', 'https://app.example.com')
    assert client.get('/MYAPP').status_code == 302
    assert client.get('/admin/api/links/MyApp').status_code == 200
    assert client.put('/admin/api/links/MyApp', json={'url': 'https://new.example.com'}).status_code == 200
    assert client.delete('/admin/api/links/MyApp').status_code == 204


@pytest.mark.parametrize('url,rest,query,expected', [
    ('https://x.com', '', '', 'https://x.com'),
    ('https://x.com/browse', 'ABC-1', '', 'https://x.com/browse/ABC-1'),
    ('https://x.com/browse/', 'ABC-1', '', 'https://x.com/browse/ABC-1'),
    ('https://x.com/a?b=1#frag', 'c/d', '', 'https://x.com/a/c/d?b=1#frag'),
    ('https://x.com/q?id={*}&v=2', '42', '', 'https://x.com/q?id=42&v=2'),
    ('https://x.com/a', '', 'x=1', 'https://x.com/a?x=1'),
    ('https://x.com/a?b=1', 'c', 'x=1', 'https://x.com/a/c?b=1&x=1'),
    ('https://x.com', 'a b', '', 'https://x.com/a%20b'),
])
def test_build_target(url, rest, query, expected):
    from src.controllers.redirect import build_target
    assert build_target(url, rest, query) == expected


def test_path_passthrough(client, add_link):
    add_link('jira', 'https://jira.example.com/browse')
    resp = client.get('/jira/ABC-123?focus=1')
    assert resp.headers['Location'] == 'https://jira.example.com/browse/ABC-123?focus=1'


def test_details_page(client, add_link):
    add_link('wiki', 'https://wiki.example.com', 'Team wiki')
    resp = client.get('/wiki+')
    assert resp.status_code == 200
    assert b'Team wiki' in resp.data
    assert client.get('/admin/api/links/wiki').get_json()['hits'] == 0


def test_missing_link_offers_create(client):
    resp = client.get('/nope')
    assert resp.status_code == 404
    assert b'/admin/?new=nope' in resp.data


@pytest.mark.parametrize('url', [
    'javascript:alert(1)', 'data:text/html,hi', 'ftp://x.com', 'example.com', 'https://', ''])
def test_rejects_bad_urls(client, url):
    resp = client.post('/admin/api/links', json={'shortname': 'bad', 'url': url})
    assert resp.status_code == 400


@pytest.mark.parametrize('name', ['admin', 'healthz', 'login', '-x', 'a b', 'a/b', 'café', 'x' * 65])
def test_rejects_bad_shortnames(client, name):
    resp = client.post('/admin/api/links', json={'shortname': name, 'url': 'https://x.com'})
    assert resp.status_code == 400


def test_duplicate_is_conflict(client, add_link):
    add_link('wiki', 'https://a.com')
    resp = client.post('/admin/api/links', json={'shortname': 'WIKI', 'url': 'https://b.com'})
    assert resp.status_code == 409


def test_update_rejects_bad_url(client, add_link):
    add_link('wiki', 'https://a.com')
    resp = client.put('/admin/api/links/wiki', json={'url': 'javascript:alert(1)'})
    assert resp.status_code == 400


def test_missing_link_api_404s(client):
    assert client.put('/admin/api/links/nope', json={'url': 'https://a.com'}).status_code == 404
    assert client.delete('/admin/api/links/nope').status_code == 404


def test_timestamps_are_utc_and_consistent(client, add_link, app):
    from datetime import datetime, timezone
    link = add_link('wiki', 'https://a.com')
    assert link['created_at'] == link['updated_at']
    created = datetime.strptime(link['created_at'], '%Y-%m-%d %H:%M:%S').replace(tzinfo=timezone.utc)
    assert abs((datetime.now(timezone.utc) - created).total_seconds()) < 5


def test_get_all_rejects_unknown_order(app):
    from src.models.link import Link
    with app.app_context():
        with pytest.raises(ValueError):
            Link.get_all(order_by='shortname; DROP TABLE links')


def test_search_escapes_wildcards(client, add_link):
    add_link('a', 'https://a.com', '100% done')
    add_link('b', 'https://b.com', '100 things')
    names = [l['shortname'] for l in client.get('/api/search?q=100%25').get_json()]
    assert names == ['a']


def test_wal_mode(app):
    db = sqlite3.connect(app.config['DATABASE_PATH'])
    assert db.execute('PRAGMA journal_mode').fetchone()[0] == 'wal'


def test_healthz_and_favicon(client):
    assert client.get('/healthz').get_json() == {'status': 'ok'}
    assert client.get('/favicon.ico').status_code == 200


def test_security_headers(client):
    resp = client.get('/')
    assert "frame-ancestors 'none'" in resp.headers['Content-Security-Policy']
    assert resp.headers['X-Content-Type-Options'] == 'nosniff'


def test_form_add_edit_delete_flow(client):
    token = csrf(client)
    resp = client.post('/admin/add', data={
        'csrf_token': token, 'shortname': 'wiki', 'url': 'https://a.com'}, follow_redirects=True)
    assert b'Created go/wiki' in resp.data

    resp = client.post('/admin/edit/wiki', data={
        'csrf_token': token, 'url': 'javascript:x'}, follow_redirects=True)
    assert b'Could not save go/wiki' in resp.data  # no longer fails silently

    resp = client.post('/admin/delete/wiki', data={'csrf_token': token}, follow_redirects=True)
    assert b'Deleted go/wiki' in resp.data


def test_form_add_error_keeps_input(client):
    token = csrf(client)
    resp = client.post('/admin/add', data={
        'csrf_token': token, 'shortname': 'admin', 'url': 'https://a.com', 'description': 'keep me'})
    assert resp.status_code == 400
    assert b'reserved' in resp.data and b'keep me' in resp.data
