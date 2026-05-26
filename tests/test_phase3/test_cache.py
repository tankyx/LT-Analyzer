"""Phase 3: in-process TTL cache for expensive read endpoints."""

import time

import pytest


pytestmark = pytest.mark.unit


def test_cache_round_trip(auth_app):
    auth_app._query_cache.clear()
    auth_app._cache_put('k1', {'value': 42}, ttl=10)
    assert auth_app._cache_get('k1') == {'value': 42}


def test_cache_miss_returns_none(auth_app):
    auth_app._query_cache.clear()
    assert auth_app._cache_get('missing') is None


def test_cache_expiry(auth_app):
    auth_app._query_cache.clear()
    auth_app._cache_put('k_expired', 'old', ttl=0)
    # ttl=0 means expires immediately
    time.sleep(0.01)
    assert auth_app._cache_get('k_expired') is None


def test_cache_invalidate_prefix(auth_app):
    auth_app._query_cache.clear()
    auth_app._cache_put('top_teams:1:None:10', 'a', ttl=300)
    auth_app._cache_put('top_teams:1:None:20', 'b', ttl=300)
    auth_app._cache_put('top_teams:2:None:10', 'c', ttl=300)
    auth_app._cache_put('cross_track_sessions:foo', 'd', ttl=300)
    auth_app._cache_invalidate_prefix('top_teams:1:')
    assert auth_app._cache_get('top_teams:1:None:10') is None
    assert auth_app._cache_get('top_teams:1:None:20') is None
    assert auth_app._cache_get('top_teams:2:None:10') == 'c'
    assert auth_app._cache_get('cross_track_sessions:foo') == 'd'


def test_cache_stats_counters(auth_app):
    auth_app._query_cache.clear()
    auth_app._query_cache_stats['hits'] = 0
    auth_app._query_cache_stats['misses'] = 0
    auth_app._cache_get('no-such-key')
    auth_app._cache_put('hit-key', 1)
    auth_app._cache_get('hit-key')
    assert auth_app._query_cache_stats['misses'] >= 1
    assert auth_app._query_cache_stats['hits'] >= 1
