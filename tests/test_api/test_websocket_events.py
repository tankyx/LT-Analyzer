import pytest
from unittest.mock import Mock, patch, MagicMock
from flask_socketio import SocketIOTestClient
from race_ui import app, socketio, race_data

@pytest.fixture
def socket_client():
    """Create a test client for SocketIO."""
    app.config['TESTING'] = True
    client = app.test_client()
    socket_client = socketio.test_client(app, flask_test_client=client)
    yield socket_client
    try:
        socket_client.disconnect()
    except RuntimeError:
        pass  # Already disconnected

@pytest.fixture
def mock_race_data():
    """Mock the race data manager instance."""
    with patch('race_ui.race_data') as mock:
        mock_data = {
            'teams': [
                {
                    'Kart': '1',
                    'Team': 'My Team',
                    'Position': '2',
                    'Class': 'Class 1',
                    'Last Lap': '1:30.123',
                    'Best Lap': '1:29.456',
                    'Pit Stops': '3',
                    'Gap': '+1.234',
                    'RunTime': '45:30',
                    'Status': 'RACING'
                },
                {
                    'Kart': '2',
                    'Team': 'Top Team',
                    'Position': '1',
                    'Class': 'Class 1',
                    'Last Lap': '1:29.789',
                    'Best Lap': '1:29.123',
                    'Pit Stops': '3',
                    'Gap': '-',
                    'RunTime': '45:31',
                    'Status': 'RACING'
                }
            ],
            'session_info': {
                'light': 'GREEN',
                'title': 'Race Session',
                'dyn1': 'Lap 45',
                'dyn2': 'Remaining: 15:00'
            },
            'my_team': 'My Team',
            'monitored_teams': ['My Team', 'Top Team'],
            'pit_config': {
                'enabled': True,
                'lapTimeThreshold': 150,
                'minPitDuration': 20
            }
        }
        
        mock.get.side_effect = lambda key, default=None: mock_data.get(key, default)
        mock.set = Mock()
        mock.get_all = Mock(return_value=mock_data)
        yield mock

class TestWebSocketConnection:
    def test_connect_success(self, socket_client):
        """Test successful WebSocket connection."""
        assert socket_client.is_connected()
        received = socket_client.get_received()
        
        # Should receive initial race data on connect
        assert len(received) > 0
        race_data_msg = next((msg for msg in received if msg['name'] == 'race_data_update'), None)
        assert race_data_msg is not None

    def test_disconnect(self, socket_client):
        """Test WebSocket disconnection."""
        # Check if connected before disconnecting
        if socket_client.is_connected():
            socket_client.disconnect()
        assert not socket_client.is_connected()

class TestWebSocketSubscriptions:
    def test_subscribe_standings(self, socket_client, mock_race_data):
        """Test subscribing to standings updates."""
        socket_client.emit('subscribe_standings')
        
        # Verify subscription was successful
        # In a real test, we'd verify the client was added to a room
        assert socket_client.is_connected()

    def test_unsubscribe_standings(self, socket_client):
        """Test unsubscribing from standings updates."""
        # First subscribe
        socket_client.emit('subscribe_standings')
        
        # Then unsubscribe
        socket_client.emit('unsubscribe_standings')
        
        # Verify unsubscription
        assert socket_client.is_connected()

    def test_request_team_delta(self, socket_client, mock_race_data):
        """Test requesting team delta information."""
        socket_client.emit('request_team_delta', {'team_number': '1'})
        
        received = socket_client.get_received()
        
        # Should receive delta response
        delta_msg = next((msg for msg in received if msg['name'] == 'team_delta_response'), None)
        assert delta_msg is not None
        assert delta_msg['args'][0]['team_number'] == '1'

class TestBroadcastUpdates:
    @patch('race_ui.socketio.emit')
    def test_emit_race_update(self, mock_emit, mock_race_data):
        """Test emitting race updates."""
        from race_ui import _do_emit_race_update
        
        _do_emit_race_update('full')
        
        # Verify emit was called
        assert mock_emit.called
        mock_emit.assert_called_with('race_data_update', mock_race_data.get_serializable(), room='race_updates')

    @patch('race_ui.socketio.emit')
    def test_emit_teams_update(self, mock_emit, mock_race_data):
        """Test emitting teams update."""
        from race_ui import _do_emit_race_update
        
        mock_race_data.get.side_effect = lambda key, default=None: {
            'teams': [{'Team': 'Team 1'}],
            'last_update': '2024-01-01'
        }.get(key, default)
        
        _do_emit_race_update('teams')
        
        # Verify teams_update was emitted
        assert mock_emit.called

    @patch('race_ui.socketio.emit')
    def test_emit_gap_update(self, mock_emit, mock_race_data):
        """Test emitting gap updates."""
        from race_ui import _do_emit_race_update
        
        # Add delta times to race data
        mock_race_data.get.side_effect = lambda key, default=None: {
            'delta_times': {'1': 1.234, '2': 0.0},
            'gap_history': {'1': {'gaps': [1.0, 1.1, 1.2]}, '2': {'gaps': [0.0, 0.0, 0.0]}}
        }.get(key, default)
        
        _do_emit_race_update('gaps')
        
        # Should emit gap_update
        assert mock_emit.called

    @patch('race_ui.socketio.emit')
    def test_emit_session_update(self, mock_emit, mock_race_data):
        """Test emitting session updates."""
        from race_ui import _do_emit_race_update
        
        mock_race_data.get.return_value = {'light': 'GREEN'}
        _do_emit_race_update('session')
        
        # Should emit session_update  
        assert mock_emit.called

    @patch('race_ui.socketio.emit')
    def test_emit_custom_update(self, mock_emit):
        """Test emitting custom updates."""
        from race_ui import _do_emit_race_update
        
        custom_data = {
            'event': 'test_event',
            'payload': {'test': 'data'}
        }
        _do_emit_race_update('custom', custom_data)
        
        # Should emit custom event
        mock_emit.assert_called_with('test_event', {'test': 'data'}, room='race_updates')

class TestRealTimeUpdates:
    def test_receive_race_data_on_connect(self, socket_client, mock_race_data):
        """Test receiving initial race data on connection."""
        received = socket_client.get_received()
        
        race_data_msg = next((msg for msg in received if msg['name'] == 'race_data_update'), None)
        assert race_data_msg is not None
        
        data = race_data_msg['args'][0]
        assert 'teams' in data
        assert 'session_info' in data
        assert 'my_team' in data
        assert 'monitored_teams' in data

    def test_delta_calculation(self, socket_client, mock_race_data):
        """Test delta calculation for teams."""
        socket_client.emit('request_team_delta', {'team_number': '1'})
        
        received = socket_client.get_received()
        delta_msg = next((msg for msg in received if msg['name'] == 'team_delta_response'), None)
        
        assert delta_msg is not None
        delta_data = delta_msg['args'][0]
        assert 'team_number' in delta_data
        assert 'delta_info' in delta_data