import pytest
from werkzeug.security import generate_password_hash

from src.auth import is_email_allowed
from tests.conftest import csrf


# ---- CSRF -------------------------------------------------------------------

def test_form_post_without_csrf_is_rejected(client):
    resp = client.post('/admin/add', data={'shortname': 'x', 'url': 'https://x.com'})
    assert resp.status_code == 400
    assert client.get('/admin/api/links/x').status_code == 404


def test_form_post_with_wrong_csrf_is_rejected(client):
    csrf(client)
    resp = client.post('/admin/delete/x', data={'csrf_token': 'wrong'})
    assert resp.status_code == 400


# ---- AUTH_MODE=none ---------------------------------------------------------

def test_none_mode_admin_is_open(client):
    assert client.get('/admin/').status_code == 200


# ---- AUTH_MODE=password -----------------------------------------------------

@pytest.fixture
def pw_app(make_app):
    return make_app(AUTH_MODE='password', ADMIN_USERNAME='matt', ADMIN_PASSWORD='hunter2',
                    ADMIN_API_TOKEN='tok123')


def login(client, username='matt', password='hunter2', next_url=None):
    token = csrf(client, '/login')
    data = {'csrf_token': token, 'username': username, 'password': password}
    if next_url:
        data['next'] = next_url
    return client.post('/login', data=data)


def test_password_mode_requires_login(pw_app):
    c = pw_app.test_client()
    resp = c.get('/admin/')
    assert resp.status_code == 302 and '/login' in resp.headers['Location']
    assert c.get('/admin/api/links').status_code == 401
    assert c.post('/admin/api/links', json={'shortname': 'x', 'url': 'https://x.com'}).status_code == 401


def test_public_pages_stay_public(pw_app):
    c = pw_app.test_client()
    assert c.get('/').status_code == 200
    assert c.get('/api/search?q=x').status_code == 200


def test_password_login_and_logout(pw_app):
    c = pw_app.test_client()
    assert login(c, password='wrong').status_code == 401
    resp = login(c)
    assert resp.status_code == 302
    assert c.get('/admin/').status_code == 200
    c.post('/logout', data={'csrf_token': csrf(c, '/')})
    assert c.get('/admin/').status_code == 302


def test_password_hash_supported(make_app):
    app = make_app(AUTH_MODE='password', ADMIN_USERNAME='matt',
                   ADMIN_PASSWORD_HASH=generate_password_hash('s3cret'))
    c = app.test_client()
    assert login(c, password='s3cret').status_code == 302


def test_login_rejects_open_redirect(pw_app):
    c = pw_app.test_client()
    resp = login(c, next_url='https://evil.example.com')
    assert resp.headers['Location'] == '/admin/'
    c = pw_app.test_client()
    resp = login(c, next_url='//evil.example.com')
    assert resp.headers['Location'] == '/admin/'


def test_login_throttle(pw_app):
    from src import auth
    auth._failures.clear()
    c = pw_app.test_client()
    for _ in range(5):
        login(c, password='wrong')
    assert login(c).status_code == 429  # even the right password is blocked for now
    auth._failures.clear()


def test_api_token(pw_app):
    c = pw_app.test_client()
    headers = {'Authorization': 'Bearer tok123'}
    resp = c.post('/admin/api/links', json={'shortname': 'x', 'url': 'https://x.com'}, headers=headers)
    assert resp.status_code == 201
    assert c.get('/admin/api/links', headers={'Authorization': 'Bearer nope'}).status_code == 401


# ---- First-run setup & settings (DB-backed account) --------------------------

@pytest.fixture
def setup_app(make_app):
    # Default config: password mode, no env credentials -> setup wizard.
    return make_app(ADMIN_PASSWORD=None, ADMIN_PASSWORD_HASH=None, ADMIN_API_TOKEN=None)


def do_setup(client, username='matt', password='longpassword', confirm=None):
    return client.post('/setup', data={
        'csrf_token': csrf(client, '/setup'), 'username': username,
        'password': password, 'confirm': confirm if confirm is not None else password})


def test_default_mode_is_password_with_setup(setup_app):
    assert setup_app.config['AUTH_MODE'] == 'password'
    c = setup_app.test_client()
    assert c.get('/admin/').headers['Location'] == '/setup'
    assert c.get('/login').headers['Location'] == '/setup'
    assert c.get('/admin/api/links').status_code == 503
    assert c.get('/').status_code == 200  # directory stays public


def test_setup_validation(setup_app):
    c = setup_app.test_client()
    assert do_setup(c, password='short').status_code == 400
    assert do_setup(c, confirm='different-password').status_code == 400
    assert do_setup(c, username=' ').status_code == 400
    assert c.get('/admin/').headers['Location'] == '/setup'  # still not set up


def test_setup_creates_account_and_logs_in(setup_app):
    c = setup_app.test_client()
    resp = do_setup(c)
    assert resp.headers['Location'] == '/admin/'
    assert c.get('/admin/').status_code == 200

    # Setup page is gone now, for everyone.
    other = setup_app.test_client()
    assert other.get('/setup').headers['Location'] == '/admin/'
    assert other.post('/setup', data={'csrf_token': csrf(other, '/'), 'username': 'evil',
                                      'password': 'x' * 10, 'confirm': 'x' * 10}
                      ).headers['Location'] == '/admin/'
    assert other.get('/admin/').headers['Location'].startswith('/login')
    assert login(other, username='evil', password='x' * 10).status_code == 401
    assert login(other, username='Matt', password='longpassword').status_code == 302


def change_password(client, current, new, confirm=None):
    return client.post('/admin/settings/password', data={
        'csrf_token': csrf(client, '/admin/settings'), 'current': current,
        'password': new, 'confirm': confirm if confirm is not None else new})


def test_change_password_signs_out_other_sessions(setup_app):
    c = setup_app.test_client()
    do_setup(c)
    other = setup_app.test_client()
    login(other, password='longpassword')
    assert other.get('/admin/').status_code == 200

    assert change_password(c, 'wrong-current', 'newpassword1').status_code == 400
    assert change_password(c, 'longpassword', 'short').status_code == 400
    assert change_password(c, 'longpassword', 'newpassword1').status_code == 302

    assert c.get('/admin/').status_code == 200            # this session kept
    assert other.get('/admin/').status_code == 302        # other device signed out
    assert login(other, password='longpassword').status_code == 401
    assert login(other, password='newpassword1').status_code == 302


def test_env_password_cannot_be_changed_in_ui(pw_app):
    c = pw_app.test_client()
    login(c)
    assert b'environment variable' in c.get('/admin/settings').data
    change_password(c, 'hunter2', 'newpassword1')
    c2 = pw_app.test_client()
    assert login(c2).status_code == 302  # env password still works


def test_generated_api_token(setup_app):
    import re
    c = setup_app.test_client()
    do_setup(c)
    resp = c.post('/admin/settings/token', data={'csrf_token': csrf(c, '/admin/settings')})
    assert resp.status_code == 302  # POST-redirect-GET: refreshing won't mint another token
    html = c.get('/admin/settings').get_data(as_text=True)
    token = re.search(r'id="new-token" value="([^"]+)"', html).group(1)
    assert token.startswith('hgo_')
    assert token not in c.get('/admin/settings').get_data(as_text=True)  # shown once

    api = setup_app.test_client()
    h = {'Authorization': f'Bearer {token}'}
    assert api.get('/admin/api/links', headers=h).status_code == 200

    c.post('/admin/settings/token/revoke', data={'csrf_token': csrf(c, '/admin/settings')})
    assert api.get('/admin/api/links', headers=h).status_code == 401


def test_settings_requires_login(setup_app):
    c = setup_app.test_client()
    do_setup(c)
    anon = setup_app.test_client()
    assert anon.get('/admin/settings').status_code == 302
    assert anon.post('/admin/settings/token', data={'csrf_token': csrf(anon, '/')}).status_code == 302


def test_unknown_auth_mode(make_app):
    with pytest.raises(RuntimeError, match='AUTH_MODE'):
        make_app(AUTH_MODE='ldap')


# ---- AUTH_MODE=oidc ---------------------------------------------------------

def test_oidc_requires_allowlist(make_app):
    with pytest.raises(RuntimeError, match='ADMIN_EMAILS'):
        make_app(AUTH_MODE='oidc', OIDC_DISCOVERY_URL='https://idp/.well-known/openid-configuration',
                 OIDC_CLIENT_ID='id', OIDC_CLIENT_SECRET='secret')


def test_oidc_login_page(make_app):
    app = make_app(AUTH_MODE='oidc', OIDC_DISCOVERY_URL='https://idp/.well-known/openid-configuration',
                   OIDC_CLIENT_ID='id', OIDC_CLIENT_SECRET='secret', OIDC_PROVIDER_NAME='Google',
                   ADMIN_EMAIL_DOMAINS=['example.com'])
    c = app.test_client()
    assert c.get('/admin/').status_code == 302
    assert b'Continue with Google' in c.get('/login').data


CFG = {'ADMIN_EMAILS': ['matt@example.com'], 'ADMIN_EMAIL_DOMAINS': ['corp.com'],
       'OIDC_ALLOW_ANY_USER': False}


@pytest.mark.parametrize('email,verified,allowed', [
    ('matt@example.com', True, True),
    ('MATT@example.com', True, True),
    ('bob@corp.com', True, True),
    ('bob@corp.com', False, False),      # unverified email never allowed
    ('bob@notcorp.com', True, False),
    ('bob@evil.corp.com', True, False),  # subdomains are not the domain
    ('eve@example.com', True, False),
    (None, True, False),
])
def test_email_allowlist(email, verified, allowed):
    assert is_email_allowed(CFG, email, verified) is allowed


def test_allow_any_user():
    assert is_email_allowed({**CFG, 'OIDC_ALLOW_ANY_USER': True}, 'anyone@x.com')
