"""Phase 1 hot-path infrastructure: session cache, in-memory limiter,
query-cache bounds, stale-while-revalidate."""

import time
from unittest.mock import patch

import pytest

from tests.test_auth.conftest import csrf_token, login_as


pytestmark = pytest.mark.integration


class TestSessionCache:
    def test_cache_hit_skips_db(self, auth_app, client, authenticated_user):
        login_as(client, authenticated_user['username'], authenticated_user['password'])
        assert client.get('/api/auth/check').get_json()['authenticated'] is True
        # Second verify must be served from cache: break the DB path and check
        # the request still authenticates.
        with patch.object(auth_app, 'get_db_connection', side_effect=AssertionError('DB touched')):
            resp = client.get('/api/auth/check')
        assert resp.get_json()['authenticated'] is True

    def test_logout_invalidates_cached_token(self, auth_app, client, authenticated_user):
        login_as(client, authenticated_user['username'], authenticated_user['password'])
        client.get('/api/auth/check')  # warm the cache
        token = csrf_token(client)
        client.post('/api/auth/logout', headers={'X-CSRF-Token': token})
        resp = client.get('/api/auth/check')
        assert resp.get_json()['authenticated'] is False

    def test_admin_user_update_clears_cache(self, auth_app, client, authenticated_user):
        login_as(client, authenticated_user['username'], authenticated_user['password'])
        client.get('/api/auth/check')  # warm
        with auth_app._session_cache_lock:
            assert len(auth_app._session_cache) >= 1
        auth_app._session_cache_invalidate()
        with auth_app._session_cache_lock:
            assert len(auth_app._session_cache) == 0

    def test_expired_ttl_falls_back_to_db(self, auth_app, client, authenticated_user, monkeypatch):
        login_as(client, authenticated_user['username'], authenticated_user['password'])
        client.get('/api/auth/check')  # warm
        monkeypatch.setattr(auth_app, 'SESSION_CACHE_TTL_SECONDS', 0)
        with patch.object(auth_app, 'get_db_connection',
                          wraps=auth_app.get_db_connection) as spy:
            resp = client.get('/api/auth/check')
        assert resp.get_json()['authenticated'] is True
        assert spy.call_count >= 1


class TestInMemoryRateLimiter:
    def test_sliding_window_expiry(self, auth_app, reset_db, monkeypatch):
        clock = [1000.0]
        monkeypatch.setattr(auth_app.time, 'monotonic', lambda: clock[0])
        assert auth_app._rate_limit_hit('w', 'k', max_events=2, window_seconds=10) is False
        assert auth_app._rate_limit_hit('w', 'k', max_events=2, window_seconds=10) is True
        clock[0] += 11  # both events age out of the window
        assert auth_app._rate_limit_hit('w', 'k', max_events=2, window_seconds=10) is False

    def test_reset_clears_state(self, auth_app, reset_db):
        auth_app._rate_limit_hit('b2', 'k2', max_events=1, window_seconds=60)
        auth_app._rate_limit_reset()
        with auth_app._rate_limit_lock:
            assert not auth_app._rate_limit_windows


class TestQueryCacheBounds:
    def test_size_cap_evicts_oldest(self, auth_app, reset_db, monkeypatch):
        monkeypatch.setattr(auth_app, 'QUERY_CACHE_MAX_ENTRIES', 5)
        with auth_app._query_cache_lock:
            auth_app._query_cache.clear()
        for i in range(8):
            auth_app._cache_put(f'capkey:{i}', i, ttl=60 + i)
        with auth_app._query_cache_lock:
            assert len(auth_app._query_cache) <= 5
            # Newest entries survive.
            assert 'capkey:7' in auth_app._query_cache


class TestStaleWhileRevalidate:
    def test_cold_computes_inline(self, auth_app, reset_db):
        with auth_app._query_cache_lock:
            auth_app._query_cache.clear()
        calls = []
        result = auth_app._cache_get_swr('swr:a', lambda: calls.append(1) or 'v1')
        assert result == 'v1' and len(calls) == 1

    def test_fresh_serves_cached_without_compute(self, auth_app, reset_db):
        auth_app._cache_put('swr:b', 'cached', ttl=60)
        result = auth_app._cache_get_swr('swr:b', lambda: pytest.fail('must not compute'))
        assert result == 'cached'

    def test_stale_serves_old_value_and_refreshes_in_background(self, auth_app, reset_db):
        auth_app._cache_put('swr:c', 'old', ttl=-1)  # already expired
        result = auth_app._cache_get_swr('swr:c', lambda: 'new')
        assert result == 'old'
        # Background refresh lands shortly after.
        deadline = time.time() + 5
        while time.time() < deadline:
            entry = auth_app._query_cache.get('swr:c')
            if entry and entry[1] == 'new':
                break
            time.sleep(0.02)
        assert auth_app._query_cache.get('swr:c')[1] == 'new'

    def test_cold_path_single_flight(self, auth_app, reset_db):
        """Concurrent cold requests must run compute exactly once (found by
        the N=300 load test: parallel cold top-teams aggregations exhausted
        the /tmp tmpfs with sqlite temp files)."""
        import threading as _threading
        with auth_app._query_cache_lock:
            auth_app._query_cache.clear()
        calls = []
        gate = _threading.Event()

        def slow_compute():
            calls.append(1)
            gate.wait(2)  # hold the flight so all threads pile up behind it
            return 'computed'

        results = []
        threads = [_threading.Thread(
            target=lambda: results.append(
                auth_app._cache_get_swr('swr:flight', slow_compute)))
            for _ in range(8)]
        for t in threads:
            t.start()
        time.sleep(0.2)
        gate.set()
        for t in threads:
            t.join(timeout=5)
        assert results == ['computed'] * 8
        assert len(calls) == 1
