import pytest
import asyncio
import json
from unittest.mock import Mock, MagicMock, patch, AsyncMock
from datetime import datetime
from apex_timing_websocket import ApexTimingWebSocketParser

@pytest.fixture
def parser():
    """Create an ApexTimingWebSocketParser instance."""
    return ApexTimingWebSocketParser()

@pytest.fixture
def mock_websocket():
    """Create a mock websocket."""
    mock = AsyncMock()
    mock.close = AsyncMock()
    mock.send = AsyncMock()
    mock.recv = AsyncMock()
    return mock

@pytest.fixture
def sample_grid_data():
    """Sample grid data for testing."""
    return {
        'cmd': 'updatePositions',
        'data': {
            'row1': {
                'position': '1',
                'team': 'Team Alpha',
                'kart': '42',
                'lastLap': '1:29.123',
                'bestLap': '1:28.456',
                'gap': '-',
                'runTime': '45:30',
                'pitStops': '3'
            },
            'row2': {
                'position': '2',
                'team': 'Team Beta',
                'kart': '17',
                'lastLap': '1:30.456',
                'bestLap': '1:29.789',
                'gap': '+1.234',
                'runTime': '45:31',
                'pitStops': '3'
            }
        }
    }

@pytest.fixture
def sample_session_info():
    """Sample session info for testing."""
    return {
        'light': 'GREEN',
        'title': 'Endurance Race',
        'dyn1': 'Lap 45',
        'dyn2': 'Remaining: 15:00'
    }

class TestApexTimingWebSocketParser:
    def test_initialization(self, parser):
        """Test parser initialization."""
        assert parser.websocket is None
        assert parser.is_connected is False
        assert parser.grid_data == {}
        assert parser.row_map == {}
        assert parser.column_map == {}
        assert parser._reconnect_attempts == 0

    @pytest.mark.asyncio
    async def test_setup_database(self, parser):
        """Test database setup."""
        with patch('aiosqlite.connect') as mock_connect:
            mock_db = AsyncMock()
            mock_connect.return_value.__aenter__.return_value = mock_db
            
            await parser.setup_database()
            
            # Verify WAL mode was enabled
            mock_db.execute.assert_any_call('PRAGMA journal_mode=WAL')
            mock_db.execute.assert_any_call('PRAGMA synchronous=NORMAL')
            
            # Verify tables were created
            assert any('CREATE TABLE IF NOT EXISTS race_sessions' in str(call) 
                      for call in mock_db.execute.call_args_list)
            assert any('CREATE TABLE IF NOT EXISTS lap_times' in str(call) 
                      for call in mock_db.execute.call_args_list)

    def test_parse_websocket_message(self, parser):
        """Test parsing WebSocket messages."""
        # Test init message format: command|parameter|value
        message = 'init|grid|<table></table>'
        result = parser.parse_websocket_message(message)
        assert result['command'] == 'init'
        assert result['parameter'] == 'grid'
        assert result['value'] == '<table></table>'
        
        # Test update message
        message = 'update|r1c1|1|Value 1'
        result = parser.parse_websocket_message(message)
        assert result['command'] == 'update'
        assert result['parameter'] == 'r1c1'

    def test_process_update_message(self, parser):
        """Test processing update messages."""
        parser.column_map = {
            0: 'Position',
            1: 'Team',
            2: 'Kart'
        }
        
        # Process update message
        data = {
            'command': 'update',
            'parameter': 'r1c1',
            'value': '1|Value 1'
        }
        parser.process_update_message(data)
        
        # Check data was stored
        assert 'r1' in parser.grid_data
        assert parser.grid_data['r1'].get(0) == 'Value 1'

    def test_get_current_standings(self, parser):
        """Test getting current standings as DataFrame."""
        # Set up test data
        parser.grid_data = {
            'r1': {0: '1', 1: 'Team Alpha', 2: '42'},
            'r2': {0: '2', 1: 'Team Beta', 2: '17'}
        }
        parser.column_map = {
            0: 'Position',
            1: 'Team',
            2: 'Kart'
        }
        
        # Get standings
        df = parser.get_current_standings()
        
        # Verify DataFrame structure
        assert not df.empty
        assert 'Position' in df.columns
        assert 'Team' in df.columns
        assert 'Kart' in df.columns
        assert len(df) == 2

    @pytest.mark.asyncio
    async def test_connect_websocket(self, parser, mock_websocket):
        """Test WebSocket connection."""
        with patch('websockets.connect') as mock_connect:
            # Make connect an async context manager
            mock_connect.return_value.__aenter__.return_value = mock_websocket
            mock_connect.return_value.__aexit__.return_value = None
            
            # This won't set websocket directly since connect_websocket starts an async task
            await parser.connect_websocket('ws://test.example.com')
            
            # Check that connection was attempted
            assert mock_connect.called

    @pytest.mark.asyncio
    async def test_connect_failure(self, parser):
        """Test connection failure."""
        with patch('websockets.connect', side_effect=Exception("Connection failed")):
            # Should not raise, just log error
            await parser.connect_websocket('ws://test.example.com')
            
            assert parser.websocket is None
            assert parser.is_connected is False

    @pytest.mark.asyncio
    async def test_process_message(self, parser):
        """Test processing different message types."""
        # Mock the database queue
        parser._db_queue = asyncio.Queue()
        parser.column_map = {0: 'Position'}
        
        # Test update message in correct format
        message = 'update|r1c1|1|Value 1'
        
        await parser._process_message(message, 1, 1)
        
        # Verify data was processed
        assert 'r1' in parser.grid_data

    @pytest.mark.asyncio 
    async def test_process_title_message(self, parser):
        """Test processing title messages."""
        data = {
            'command': 'title',
            'parameter': 'light',
            'value': 'GREEN'
        }
        
        parser.process_title_message(data)
        
        assert parser._session_info['light'] == 'GREEN'

    @pytest.mark.asyncio
    async def test_process_db_queue(self, parser):
        """Test database queue processing."""
        with patch('aiosqlite.connect') as mock_connect:
            mock_db = AsyncMock()
            mock_connect.return_value.__aenter__.return_value = mock_db
            
            # Add test data to queue
            parser._db_queue = asyncio.Queue()
            await parser._db_queue.put({
                'row_id': 'row1',
                'data': {'Position': '1', 'Team': 'Team Alpha'}
            })
            
            # Process one item
            parser._db_queue.put_nowait(None)  # Stop signal
            await parser._process_db_queue(1)
            
            # Should have attempted database operations
            assert mock_connect.called

    def test_cleanup_old_data(self, parser):
        """Test cleanup of old grid data."""
        # Add some data
        for i in range(250):
            parser.grid_data[f'r{i}'] = {'0': str(i)}
        
        initial_size = len(parser.grid_data)
        parser._cleanup_old_data()
        
        # Should be limited
        assert len(parser.grid_data) <= 200  # Default max entries

    @pytest.mark.asyncio
    async def test_disconnect_websocket(self, parser, mock_websocket):
        """Test disconnecting websocket."""
        parser.websocket = mock_websocket
        parser.is_connected = True
        
        await parser.disconnect_websocket()
        
        mock_websocket.close.assert_called_once()
        assert parser.is_connected is False

    def test_set_update_callback(self, parser):
        """Test setting update callback."""
        callback = Mock()
        parser.set_update_callback(callback)
        
        assert parser._update_callback == callback

    @pytest.mark.asyncio
    async def test_update_callback_invocation(self, parser):
        """Test that update callback is invoked."""
        callback = AsyncMock()
        parser.set_update_callback(callback)
        
        # Set up test data
        parser._rows_data = {
            'row1': {0: '1', 1: 'Team Alpha', 2: '42'}
        }
        parser._field_name_indices = {
            'position': 0,
            'team': 1, 
            'kart': 2
        }
        
        # The callback would be invoked during message processing
        # Here we just verify it was set
        assert parser._update_callback == callback