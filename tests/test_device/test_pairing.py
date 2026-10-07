"""Pairing codes: 8 typed characters on the board, a 256-bit token in flash."""

from __future__ import annotations

import sqlite3

from .conftest import bearer, login


def mint_code(client, csrf, label='board-1'):
    r = client.post('/api/device/pairing-codes', json={'label': label}, headers={'X-CSRF-Token': csrf})
    assert r.status_code == 201, r.get_json()
    return r.get_json()


class TestPairing:
    def test_code_shape_and_status(self, client, normal_user):
        csrf = login(client, normal_user['username'], normal_user['password'])
        body = mint_code(client, csrf)
        code = body['code']
        assert len(code) == 9 and code[4] == '-'
        for ch in code.replace('-', ''):
            assert ch in 'ABCDEFGHJKLMNPQRSTUVWXYZ23456789'
        assert body['expires_in'] == 600 and body['expires_at'].endswith('Z')
        st = client.get(f"/api/device/pairing-codes/{body['id']}").get_json()
        assert st['status'] == 'pending' and st['label'] == 'board-1' and st['token_id'] is None
        # Only a hash is stored.
        with sqlite3.connect('auth.db') as conn:
            stored = conn.execute('SELECT code_hash FROM device_pairing_codes WHERE id = ?', (body['id'],)).fetchone()[0]
        assert stored != code.replace('-', '') and len(stored) == 64

    def test_minting_requires_login_and_label(self, client, normal_user):
        r = client.post('/api/device/pairing-codes', json={'label': 'x'})
        assert r.status_code in (401, 403)
        csrf = login(client, normal_user['username'], normal_user['password'])
        r = client.post('/api/device/pairing-codes', json={'label': ''}, headers={'X-CSRF-Token': csrf})
        assert r.status_code == 400 and r.get_json() == {'error': 'invalid_label'}

    def test_board_exchanges_code_for_a_working_token(self, client, normal_user):
        csrf = login(client, normal_user['username'], normal_user['password'])
        body = mint_code(client, csrf, label='datalogger-p4')
        client.post('/api/auth/logout', headers={'X-CSRF-Token': csrf})

        # Anonymous, no cookie, no CSRF; lower case with the dash is fine.
        r = client.post('/api/device/pair', json={'code': body['code'].lower()})
        assert r.status_code == 200, r.get_json()
        tok = r.get_json()
        assert tok['label'] == 'datalogger-p4' and len(tok['token']) >= 43
        assert tok['expires_at'].endswith('Z')

        r = client.get('/api/device/tracks', headers=bearer(tok['token']))
        assert r.status_code == 200

        # The dashboard sees it paired and listed under the same label.
        login(client, normal_user['username'], normal_user['password'])
        st = client.get(f"/api/device/pairing-codes/{body['id']}").get_json()
        assert st['status'] == 'paired' and st['token_id'] == tok['id']
        listed = client.get('/api/device/tokens').get_json()['tokens']
        assert listed[0]['id'] == tok['id'] and listed[0]['label'] == 'datalogger-p4'

    def test_code_is_single_use(self, client, normal_user):
        csrf = login(client, normal_user['username'], normal_user['password'])
        body = mint_code(client, csrf)
        assert client.post('/api/device/pair', json={'code': body['code']}).status_code == 200
        r = client.post('/api/device/pair', json={'code': body['code']})
        assert r.status_code == 400 and r.get_json() == {'error': 'invalid_code'}

    def test_expired_code_rejected(self, client, normal_user):
        csrf = login(client, normal_user['username'], normal_user['password'])
        body = mint_code(client, csrf)
        with sqlite3.connect('auth.db') as conn:
            conn.execute("UPDATE device_pairing_codes SET expires_at = '2000-01-01T00:00:00Z' WHERE id = ?", (body['id'],))
        r = client.post('/api/device/pair', json={'code': body['code']})
        assert r.status_code == 400 and r.get_json() == {'error': 'invalid_code'}
        assert client.get(f"/api/device/pairing-codes/{body['id']}").get_json()['status'] == 'expired'

    def test_wrong_or_malformed_code_rejected(self, client, normal_user):
        r = client.post('/api/device/pair', json={'code': 'ABCD-EFGH'})
        assert r.status_code == 400 and r.get_json() == {'error': 'invalid_code'}
        r = client.post('/api/device/pair', json={'code': 'ABC'})
        assert r.status_code == 400
        r = client.post('/api/device/pair', json={})
        assert r.status_code == 400
        r = client.post('/api/device/pair', json={'code': 12345678})
        assert r.status_code == 400

    def test_pair_is_throttled_per_ip(self, client, normal_user, fleet_app, monkeypatch):
        import race_app.blueprints.device_routes as dr
        monkeypatch.setattr(dr, '_rate_limit_hit', fleet_app._rate_limit_hit)
        codes = [client.post('/api/device/pair', json={'code': 'ABCD-EFGH'}).status_code for _ in range(12)]
        assert 429 in codes
        r = client.post('/api/device/pair', json={'code': 'ABCD-EFGH'})
        assert r.status_code == 429 and r.headers['Retry-After'] == '6'
        assert r.get_json() == {'error': 'rate_limited'}

    def test_status_is_owner_only(self, client, normal_user, admin_user):
        csrf = login(client, normal_user['username'], normal_user['password'])
        body = mint_code(client, csrf)
        client.post('/api/auth/logout', headers={'X-CSRF-Token': csrf})
        login(client, admin_user['username'], admin_user['password'])
        assert client.get(f"/api/device/pairing-codes/{body['id']}").status_code == 404
