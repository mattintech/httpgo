import re

import pytest

from src.app import create_app


@pytest.fixture
def make_app(tmp_path, monkeypatch):
    monkeypatch.setenv('SECRET_KEY', 'test-secret')

    def _make(**overrides):
        config = {'TESTING': True, 'DATABASE_PATH': str(tmp_path / 'test.db')}
        config.update(overrides)
        return create_app(config)
    return _make


@pytest.fixture
def app(make_app):
    return make_app(AUTH_MODE='none')


@pytest.fixture
def client(app):
    return app.test_client()


def csrf(client, path='/admin/'):
    """Load a page and return the CSRF token embedded in it."""
    html = client.get(path).get_data(as_text=True)
    return re.search(r'name="csrf-token" content="([^"]+)"', html).group(1)


@pytest.fixture
def add_link(client):
    def _add(shortname, url, description=''):
        resp = client.post('/admin/api/links', json={
            'shortname': shortname, 'url': url, 'description': description})
        assert resp.status_code == 201, resp.get_json()
        return resp.get_json()
    return _add
