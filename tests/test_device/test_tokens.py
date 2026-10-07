"""Device tokens: minted from the web session, presented as a bearer."""

from __future__ import annotations

import sqlite3

from .conftest import bearer, login


class TestTokenLifecycle:
    def test_create_requires_login(self, client):
        r = client.post('/api/device/tokens', json={'label': 'x'})
        # The CSRF guard runs first for anonymous cookie-less callers.
        assert r.status_code in (401, 403)

    def test_create_requires_csrf(self, client, normal_user):
        login(client, normal_user['username'], normal_user['password'])
        r = client.post('/api/device/tokens', json={'label': 'x'})
        assert r.status_code == 403
        assert r.get_json()['error'] == 'csrf_failed'

    def test_create_returns_plaintext_once(self, client, normal_user):
        csrf = login(client, normal_user['username'], normal_user['password'])
        r = client.post('/api/device/tokens', json={'label': 'datalogger-p4'},
                        headers={'X-CSRF-Token': csrf})
        assert r.status_code == 201
        body = r.get_json()
        assert body['label'] == 'datalogger-p4'
        assert len(body['token']) >= 43            # 32 bytes base64url
        assert body['expires_at'].endswith('Z')
        # The list never echoes the secret, and stores only a hash.
        listed = client.get('/api/device/tokens').get_json()['tokens']
        assert listed[0]['id'] == body['id']
        assert 'token' not in listed[0]
        assert listed[0]['revoked'] is False
        assert listed[0]['last_seen_at'] is None
        with sqlite3.connect('auth.db') as conn:
            stored = conn.execute('SELECT token_hash FROM device_tokens WHERE id = ?',
                                  (body['id'],)).fetchone()[0]
        assert stored != body['token'] and len(stored) == 64

    def test_invalid_label_rejected(self, client, normal_user):
        csrf = login(client, normal_user['username'], normal_user['password'])
        r = client.post('/api/device/tokens', json={'label': ''}, headers={'X-CSRF-Token': csrf})
        assert r.status_code == 400
        r = client.post('/api/device/tokens', json={'label': 'x' * 65}, headers={'X-CSRF-Token': csrf})
        assert r.status_code == 400

    def test_bearer_authenticates_and_updates_last_seen(self, client, device_token):
        r = client.get('/api/device/tracks', headers=bearer(device_token['token']))
        assert r.status_code == 200
        rows = r.get_json()
        assert {'id': 1, 'name': 'Test Track', 'active': False} in rows
        assert all(set(t) == {'id', 'name', 'active'} for t in rows)
        listed = client.get('/api/device/tokens').get_json()['tokens']
        assert listed[0]['last_seen_at'] is not None
        assert listed[0]['last_seen_at'].endswith('Z')

    def test_revoke_then_401_invalid_token(self, client, device_token):
        r = client.post(f"/api/device/tokens/{device_token['id']}/revoke",
                        headers={'X-CSRF-Token': device_token['csrf']})
        assert r.status_code == 200 and r.get_json()['revoked'] is True
        r = client.get('/api/device/tracks', headers=bearer(device_token['token']))
        assert r.status_code == 401
        assert r.get_json() == {'error': 'invalid_token'}
        assert r.headers['WWW-Authenticate'] == 'Bearer'
        listed = client.get('/api/device/tokens').get_json()['tokens']
        assert listed[0]['revoked'] is True

    def test_cannot_revoke_another_users_token(self, client, device_token, admin_user):
        client.post('/api/auth/logout', headers={'X-CSRF-Token': device_token['csrf']})
        csrf = login(client, admin_user['username'], admin_user['password'])
        r = client.post(f"/api/device/tokens/{device_token['id']}/revoke",
                        headers={'X-CSRF-Token': csrf})
        assert r.status_code == 404

    def test_expired_token_rejected(self, client, device_token):
        import race_app.blueprints.device_routes as dr
        with sqlite3.connect('auth.db') as conn:
            conn.execute("UPDATE device_tokens SET expires_at = '2000-01-01T00:00:00Z' WHERE id = ?",
                         (device_token['id'],))
        dr._token_cache_invalidate()
        r = client.get('/api/device/tracks', headers=bearer(device_token['token']))
        assert r.status_code == 401
        assert r.get_json() == {'error': 'invalid_token'}

    def test_garbage_bearer_rejected(self, client, device_token):
        for hdr in ({}, {'Authorization': 'Bearer nope'}, {'Authorization': 'Basic abc'}):
            r = client.get('/api/device/tracks', headers=hdr)
            assert r.status_code == 401, hdr
            assert r.get_json() == {'error': 'invalid_token'}


class TestScope:
    def test_bearer_never_reaches_cookie_routes(self, client, device_token):
        """History / prefs / fleet / token management stay cookie-only."""
        client.post('/api/auth/logout', headers={'X-CSRF-Token': device_token['csrf']})
        h = bearer(device_token['token'])
        assert client.get('/api/track/1/pace/team?team=x', headers=h).status_code == 401
        assert client.get('/api/me/prefs/1', headers=h).status_code == 401
        assert client.get('/api/track/1/fleet/karts', headers=h).status_code == 401
        assert client.get('/api/device/tokens', headers=h).status_code == 401
        # Token management with a bearer but no cookie is still CSRF-guarded.
        r = client.post('/api/device/tokens', json={'label': 'x'}, headers=h)
        assert r.status_code == 403

    def test_device_routes_are_json_on_every_error(self, client, device_token):
        h = bearer(device_token['token'])
        r = client.get('/api/device/does-not-exist', headers=h)
        assert r.status_code == 404
        assert r.get_json() == {'error': 'not_found'}
        r = client.delete('/api/device/live', headers=h)
        assert r.status_code == 405
        assert r.get_json() == {'error': 'method_not_allowed'}
        assert r.headers['Cache-Control'] == 'no-store, no-transform'

    def test_no_redirect_on_trailing_slash(self, client, device_token):
        r = client.get('/api/device/tracks/', headers=bearer(device_token['token']))
        assert r.status_code == 200
