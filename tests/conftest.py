import pytest
import sys
import os
from unittest.mock import Mock

# Add the parent directory to the Python path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

# Mock database operations for tests
@pytest.fixture(autouse=True)
def mock_database(monkeypatch):
    """Mock database operations to avoid actual database access during tests."""
    # Mock sqlite3
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
    
    # Mock aiosqlite
    mock_aiosqlite = Mock()
    mock_async_connection = Mock()
    mock_async_connection.__aenter__ = Mock(return_value=mock_async_connection)
    mock_async_connection.__aexit__ = Mock(return_value=None)
    mock_async_connection.execute = Mock()
    mock_async_connection.commit = Mock()
    mock_aiosqlite.connect.return_value = mock_async_connection
    
    monkeypatch.setattr('aiosqlite.connect', mock_aiosqlite.connect)
    
    return mock_sqlite, mock_aiosqlite

# Mock the parser module to avoid actual WebSocket connections
@pytest.fixture(autouse=True)
def mock_parser_module(monkeypatch):
    """Mock the parser module to prevent actual WebSocket connections."""
    mock_parser = Mock()
    mock_parser.is_running = False
    mock_parser.status = {
        'connected': False,
        'running': False,
        'last_update': None,
        'error': None
    }
    mock_parser.start = Mock()
    mock_parser.stop = Mock()
    
    monkeypatch.setattr('race_ui.parser', mock_parser)
    return mock_parser

# Mock the race data manager
@pytest.fixture(autouse=True)
def mock_race_data_module(monkeypatch):
    """Mock the race data manager module."""
    mock_data = Mock()
    default_data = {
        'teams': [],
        'session_info': {},
        'my_team': None,
        'monitored_teams': [],
        'pit_config': {
            'enabled': True,
            'lapTimeThreshold': 150,
            'minPitDuration': 20
        }
    }
    mock_data.get = Mock(side_effect=lambda key, default=None: default_data.get(key, default))
    mock_data.set = Mock()
    mock_data.update_monitored_teams = Mock()
    mock_data.get_all = Mock(return_value={})
    mock_data.get_serializable = Mock(return_value=default_data)
    
    monkeypatch.setattr('race_ui.race_data', mock_data)
    return mock_data

# Mock WebSocket connections
@pytest.fixture
def mock_websocket_connection(monkeypatch):
    """Mock WebSocket connections."""
    mock_ws = Mock()
    mock_ws.send = Mock()
    mock_ws.recv = Mock()
    mock_ws.close = Mock()
    
    async def mock_connect(*args, **kwargs):
        return mock_ws
    
    monkeypatch.setattr('websockets.connect', mock_connect)
    return mock_ws

# Disable logging during tests
@pytest.fixture(autouse=True)
def disable_logging():
    """Disable logging during tests to reduce noise."""
    import logging
    logging.disable(logging.CRITICAL)
    yield
    logging.disable(logging.NOTSET)

# Mock Flask-SocketIO for WebSocket tests
@pytest.fixture(autouse=True)
def mock_socketio_module(monkeypatch):
    """Mock Flask-SocketIO module to prevent JSON serialization issues."""
    try:
        import flask_socketio
        # Patch emit to not actually serialize data
        original_emit = flask_socketio.emit
        def mock_emit(event, data=None, **kwargs):
            # Just store the call, don't try to serialize Mock objects
            return None
        monkeypatch.setattr('flask_socketio.emit', mock_emit)
    except ImportError:
        pass

# Mock the track database
@pytest.fixture(autouse=True)
def mock_track_db_module(monkeypatch):
    """Mock the track database module."""
    mock_track_db = Mock()
    mock_track_db.get_tracks = Mock(return_value=[])
    mock_track_db.get_all_tracks = Mock(return_value=[])
    mock_track_db.get_track = Mock(return_value=None)
    mock_track_db.get_track_by_id = Mock(return_value=None)
    mock_track_db.add_track = Mock()
    mock_track_db.update_track = Mock()
    mock_track_db.delete_track = Mock()
    
    monkeypatch.setattr('race_ui.track_db', mock_track_db)
    return mock_track_db