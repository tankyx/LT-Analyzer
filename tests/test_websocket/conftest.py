"""Mocks for legacy test_websocket/ tests."""

from unittest.mock import Mock

import pytest


@pytest.fixture(autouse=True)
def mock_database(monkeypatch):
    mock_sqlite = Mock()
    mock_connection = Mock()
    mock_cursor = Mock()

    mock_cursor.fetchall.return_value = []
    mock_cursor.fetchone.return_value = None
    mock_cursor.execute.return_value = mock_cursor
    mock_cursor.__enter__ = Mock(return_value=mock_cursor)
    mock_cursor.__exit__ = Mock(return_value=None)

    mock_connection.cursor.return_value = mock_cursor
    mock_connection.execute.return_value = mock_cursor
    mock_connection.commit = Mock()
    mock_connection.__enter__ = Mock(return_value=mock_connection)
    mock_connection.__exit__ = Mock(return_value=None)

    mock_sqlite.connect.return_value = mock_connection
    monkeypatch.setattr('sqlite3.connect', mock_sqlite.connect)

    mock_aiosqlite = Mock()
    mock_async_connection = Mock()
    mock_async_connection.__aenter__ = Mock(return_value=mock_async_connection)
    mock_async_connection.__aexit__ = Mock(return_value=None)
    mock_async_connection.execute = Mock()
    mock_async_connection.commit = Mock()
    mock_aiosqlite.connect.return_value = mock_async_connection
    monkeypatch.setattr('aiosqlite.connect', mock_aiosqlite.connect)

    return mock_sqlite, mock_aiosqlite


@pytest.fixture
def mock_websocket_connection(monkeypatch):
    mock_ws = Mock()
    mock_ws.send = Mock()
    mock_ws.recv = Mock()
    mock_ws.close = Mock()

    async def mock_connect(*args, **kwargs):
        return mock_ws

    monkeypatch.setattr('websockets.connect', mock_connect)
    return mock_ws
