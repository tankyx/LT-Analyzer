import pytest
import json
import sys
from unittest.mock import Mock, patch, MagicMock
from race_ui import app, db_pool, race_data, track_db

@pytest.fixture
def client():
    """Create a test client for the Flask app."""
    app.config['TESTING'] = True
    with app.test_client() as client:
        with app.app_context():
            yield client

@pytest.fixture
def mock_race_data():
    """Mock the race data manager instance."""
    with patch('race_ui.race_data') as mock:
        mock.get.side_effect = lambda key, default=None: {
            'teams': [
                {'Kart': '1', 'Team': 'My Team', 'Position': '2', 'Class': 'Class 1'},
                {'Kart': '2', 'Team': 'Top Team', 'Position': '1', 'Class': 'Class 1'},
            ],
            'session_info': {'light': 'GREEN', 'title': 'Race'},
            'my_team': 'My Team',
            'monitored_teams': ['My Team', 'Top Team'],
            'gap_history': {},
            'pit_config': {
                'enabled': True,
                'lapTimeThreshold': 150,
                'minPitDuration': 20
            }
        }.get(key, default)
        mock.set = Mock()
        mock.update_monitored_teams = Mock()
        yield mock

@pytest.fixture
def mock_parser():
    """Mock the WebSocket parser."""
    with patch('race_ui.parser') as mock:
        mock.is_running = False
        mock.status = {
            'connected': False,
            'running': False,
            'last_update': None,
            'error': None
        }
        yield mock

class TestRaceDataEndpoint:
    def test_get_race_data_success(self, client, mock_race_data):
        """Test successful retrieval of race data."""
        # Mock the get_serializable method
        mock_race_data.get_serializable.return_value = {
            'teams': [
                {'Kart': '1', 'Team': 'My Team', 'Position': '2'},
                {'Kart': '2', 'Team': 'Top Team', 'Position': '1'}
            ],
            'session_info': {'light': 'GREEN', 'title': 'Race'},
            'my_team': 'My Team',
            'monitored_teams': ['My Team', 'Top Team']
        }
        
        response = client.get('/api/race-data')
        assert response.status_code == 200
        
        data = json.loads(response.data)
        assert 'teams' in data
        assert 'session_info' in data
        assert 'my_team' in data
        assert len(data['teams']) == 2

    def test_get_race_data_no_teams(self, client, mock_race_data):
        """Test race data when no teams are present."""
        mock_race_data.get_serializable.return_value = {
            'teams': [],
            'session_info': {},
            'my_team': None,
            'monitored_teams': []
        }
        
        response = client.get('/api/race-data')
        assert response.status_code == 200
        
        data = json.loads(response.data)
        assert data['teams'] == []

class TestMonitoringEndpoint:
    def test_update_monitoring_success(self, client, mock_race_data):
        """Test successful monitoring update."""
        payload = {
            'myTeam': 'Team 3',
            'monitoredTeams': ['Team 3', 'Team 4']
        }
        response = client.post('/api/update-monitoring',
                             json=payload,
                             content_type='application/json')
        assert response.status_code == 200
        
        data = json.loads(response.data)
        assert data['status'] == 'success'

    def test_update_monitoring_empty_data(self, client):
        """Test monitoring update with empty data."""
        response = client.post('/api/update-monitoring',
                             json={},
                             content_type='application/json')
        assert response.status_code == 200  # Empty data is allowed

class TestSimulationControl:
    def test_start_simulation_success(self, client, mock_parser):
        """Test successful simulation start."""
        # Mock thread to prevent actual thread creation
        with patch('race_ui.threading.Thread') as mock_thread:
            mock_thread_instance = Mock()
            mock_thread.return_value = mock_thread_instance
            
            payload = {'simulation': True}
            response = client.post('/api/start-simulation',
                                 json=payload,
                                 content_type='application/json')
            assert response.status_code == 200
            
            data = json.loads(response.data)
            assert data['status'] == 'success'
            assert 'message' in data

    def test_start_simulation_already_running(self, client, mock_parser):
        """Test starting simulation when already running."""
        # Create a mock thread that reports as alive
        mock_thread_instance = Mock()
        mock_thread_instance.is_alive.return_value = True
        mock_thread_instance.join = Mock()
        
        # Patch the module-level update_thread variable and stop_event
        with patch.object(sys.modules['race_ui'], 'update_thread', mock_thread_instance):
            with patch.object(sys.modules['race_ui'], 'stop_event') as mock_stop_event:
                with patch('race_ui.threading.Thread') as mock_thread:
                    mock_new_thread = Mock()
                    mock_thread.return_value = mock_new_thread
                    
                    payload = {'simulation': True}
                    response = client.post('/api/start-simulation',
                                         json=payload,
                                         content_type='application/json')
                    assert response.status_code == 200
                    
                    data = json.loads(response.data)
                    assert data['status'] == 'success'  # It stops the old thread and starts new
                    
                    # Verify old thread was stopped
                    mock_stop_event.set.assert_called_once()
                    mock_thread_instance.join.assert_called_once()

    def test_stop_simulation_success(self, client, mock_parser):
        """Test successful simulation stop."""
        # Simulate running thread
        with patch('race_ui.update_thread') as mock_thread:
            with patch('race_ui.stop_event') as mock_event:
                mock_thread.is_alive.return_value = True
                
                response = client.post('/api/stop-simulation')
                assert response.status_code == 200
                
                data = json.loads(response.data)
                assert data['status'] == 'success'
                mock_event.set.assert_called_once()

    def test_stop_simulation_not_running(self, client, mock_parser):
        """Test stopping simulation when not running."""
        # No thread running
        with patch('race_ui.update_thread', None):
            response = client.post('/api/stop-simulation')
            assert response.status_code == 200
            
            data = json.loads(response.data)
            assert data['status'] == 'success'  # Still returns success

class TestParserStatus:
    def test_get_parser_status(self, client, mock_parser):
        """Test getting parser status."""
        # Make sure update_thread is None
        with patch.object(sys.modules['race_ui'], 'update_thread', None):
            response = client.get('/api/parser-status')
            assert response.status_code == 200
            
            data = json.loads(response.data)
            assert 'status' in data
            assert 'last_update' in data
            assert data['status'] == 'stopped'  # Default status

class TestPitConfig:
    def test_update_pit_config_success(self, client, mock_race_data):
        """Test successful pit configuration update."""
        payload = {
            'enabled': True,
            'lapTimeThreshold': 180,
            'minPitDuration': 25,
            'adjustForPitStops': True,
            'remainingStops': {
                '1': 3,
                '2': 2
            }
        }
        response = client.post('/api/update-pit-config',
                             json=payload,
                             content_type='application/json')
        assert response.status_code == 200
        
        data = json.loads(response.data)
        assert data['status'] == 'success'

    def test_update_pit_config_empty_data(self, client):
        """Test pit config update with empty data."""
        payload = {}
        response = client.post('/api/update-pit-config',
                             json=payload,
                             content_type='application/json')
        assert response.status_code == 200  # Empty data is allowed

class TestResetRaceData:
    def test_reset_race_data_success(self, client):
        """Test successful race data reset."""
        response = client.post('/api/reset-race-data')
        assert response.status_code == 200
        
        data = json.loads(response.data)
        assert data['status'] == 'success'
        assert 'message' in data

class TestTrackEndpoints:
    def test_get_tracks(self, client):
        """Test getting list of tracks."""
        # track_db is mocked in conftest.py, so we use it directly
        from race_ui import track_db
        track_db.get_all_tracks.return_value = [
            {'id': 1, 'name': 'Track 1', 'api_id': 'track1'},
            {'id': 2, 'name': 'Track 2', 'api_id': 'track2'}
        ]
        
        response = client.get('/api/tracks')
        assert response.status_code == 200
        
        data = json.loads(response.data)
        assert 'tracks' in data
        assert len(data['tracks']) == 2
        assert data['tracks'][0]['name'] == 'Track 1'

    def test_get_track_by_id(self, client):
        """Test getting a specific track."""
        from race_ui import track_db
        track_db.get_track_by_id.return_value = {
            'id': 1, 
            'name': 'Track 1', 
            'api_id': 'track1'
        }
        
        response = client.get('/api/tracks/1')
        assert response.status_code == 200
        
        data = json.loads(response.data)
        assert data['name'] == 'Track 1'

    def test_get_track_not_found(self, client):
        """Test getting non-existent track."""
        from race_ui import track_db
        track_db.get_track_by_id.return_value = None
        
        response = client.get('/api/tracks/999')
        assert response.status_code == 404