"""Phase 0 scale-hardening: CORS fail-loud, SSRF validation, gated consistency."""

import socket as socket_module
from unittest.mock import patch

import pytest

from tests.test_auth.conftest import csrf_token, login_as


pytestmark = pytest.mark.integration


class TestCorsFailLoud:
    def test_raises_in_production_without_cors_origins(self, auth_app, monkeypatch):
        monkeypatch.setenv('FLASK_ENV', 'production')
        monkeypatch.setenv('CORS_ORIGINS', '')
        with pytest.raises(RuntimeError, match='CORS_ORIGINS'):
            auth_app._parse_cors_origins()

    def test_dev_falls_back_to_localhost(self, auth_app, monkeypatch):
        monkeypatch.delenv('FLASK_ENV', raising=False)
        monkeypatch.setenv('CORS_ORIGINS', '')
        assert auth_app._parse_cors_origins() == ['http://localhost:3000']

    def test_explicit_origins_parsed(self, auth_app, monkeypatch):
        monkeypatch.setenv('CORS_ORIGINS', 'https://a.example, https://b.example')
        assert auth_app._parse_cors_origins() == ['https://a.example', 'https://b.example']


class TestTrackUrlSsrfValidator:
    def _err(self, auth_app, url):
        return auth_app._validate_track_url(url, 'websocket_url')

    def test_rejects_bad_scheme(self, auth_app):
        assert 'scheme' in self._err(auth_app, 'ftp://example.com/feed')

    def test_rejects_file_scheme(self, auth_app):
        assert 'scheme' in self._err(auth_app, 'file:///etc/passwd')

    def test_rejects_userinfo(self, auth_app):
        assert 'credentials' in self._err(auth_app, 'wss://user:pass@8.8.8.8/')

    def test_rejects_loopback(self, auth_app):
        assert 'non-public' in self._err(auth_app, 'wss://127.0.0.1:8092/')

    def test_rejects_private_range(self, auth_app):
        assert 'non-public' in self._err(auth_app, 'https://192.168.1.10/live')

    def test_rejects_metadata_endpoint(self, auth_app):
        assert 'non-public' in self._err(auth_app, 'http://169.254.169.254/latest/meta-data/')

    def test_rejects_unresolvable_host(self, auth_app):
        with patch.object(auth_app.socket_module, 'getaddrinfo',
                          side_effect=socket_module.gaierror('nope')):
            assert 'does not resolve' in self._err(auth_app, 'wss://does-not-exist.invalid/')

    def test_accepts_public_host(self, auth_app):
        fake = [(socket_module.AF_INET, None, None, '', ('93.184.216.34', 0))]
        with patch.object(auth_app.socket_module, 'getaddrinfo', return_value=fake):
            assert self._err(auth_app, 'wss://www.apex-timing.com:8092/') is None

    def test_hostname_resolving_private_rejected(self, auth_app):
        """DNS-rebinding shape: public-looking name resolving to private space."""
        fake = [(socket_module.AF_INET, None, None, '', ('10.0.0.5', 0))]
        with patch.object(auth_app.socket_module, 'getaddrinfo', return_value=fake):
            assert 'non-public' in self._err(auth_app, 'wss://sneaky.example.com/')

    def test_allow_private_override(self, auth_app, monkeypatch):
        monkeypatch.setattr(auth_app, 'ALLOW_PRIVATE_TRACK_URLS', True)
        assert self._err(auth_app, 'wss://127.0.0.1:8092/') is None


class TestAdminTrackEndpointsValidateUrls:
    def _login_admin(self, client, authenticated_admin):
        login_as(client, authenticated_admin['username'], authenticated_admin['password'])
        return csrf_token(client)

    def test_add_track_rejects_private_websocket_url(self, auth_app, client, authenticated_admin):
        token = self._login_admin(client, authenticated_admin)
        resp = client.post(
            '/api/admin/tracks',
            json={'name': 'Evil Track', 'websocket_url': 'wss://127.0.0.1:5000/'},
            headers={'X-CSRF-Token': token},
        )
        assert resp.status_code == 400
        assert 'non-public' in resp.get_json()['error']

    def test_update_track_rejects_bad_scheme(self, auth_app, client, authenticated_admin):
        token = self._login_admin(client, authenticated_admin)
        result = auth_app.track_db.add_track(
            track_name='SSRF Update Target', timing_url='', websocket_url=None)
        resp = client.put(
            f'/api/admin/tracks/{result["id"]}',
            json={'timing_url': 'file:///etc/passwd'},
            headers={'X-CSRF-Token': token},
        )
        assert resp.status_code == 400
        assert 'scheme' in resp.get_json()['error']

    def test_add_track_allows_empty_urls(self, auth_app, client, authenticated_admin):
        token = self._login_admin(client, authenticated_admin)
        resp = client.post(
            '/api/admin/tracks',
            json={'name': 'URL-less Track', 'websocket_url': '', 'timing_url': ''},
            headers={'X-CSRF-Token': token},
        )
        assert resp.status_code == 201


class TestDriverConsistencyGated:
    def test_anonymous_blocked(self, client):
        resp = client.get('/api/driver/consistency?name=foo')
        assert resp.status_code == 401

    def test_logged_in_allowed(self, auth_app, client, authenticated_user):
        login_as(client, authenticated_user['username'], authenticated_user['password'])
        resp = client.get('/api/driver/consistency?name=some-driver-nobody')
        # No track data in the test env — but the request must clear the auth gate.
        assert resp.status_code == 200
