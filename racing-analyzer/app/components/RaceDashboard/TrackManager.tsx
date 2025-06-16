import React, { useState, useEffect } from 'react';
import { X, Plus, Edit2, Trash2, Check, AlertCircle } from 'lucide-react';

interface Track {
  id: number;
  track_name: string;
  timing_url: string;
  websocket_url: string | null;
  created_at: string;
  updated_at: string;
}

interface TrackManagerProps {
  onSelectTrack?: (track: Track) => void;
  selectedTrackId?: number | null;
}

const TrackManager: React.FC<TrackManagerProps> = ({ onSelectTrack, selectedTrackId }) => {
  const [tracks, setTracks] = useState<Track[]>([]);
  const [isAddingTrack, setIsAddingTrack] = useState(false);
  const [editingTrackId, setEditingTrackId] = useState<number | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  
  // Form state
  const [formData, setFormData] = useState({
    track_name: '',
    timing_url: '',
    websocket_url: ''
  });

  // Fetch tracks on component mount
  useEffect(() => {
    fetchTracks();
  }, []);

  const fetchTracks = async () => {
    try {
      setLoading(true);
      const response = await fetch('http://localhost:5000/api/tracks');
      const data = await response.json();
      setTracks(data.tracks || []);
      setError(null);
    } catch (err) {
      setError('Failed to fetch tracks');
      console.error('Error fetching tracks:', err);
    } finally {
      setLoading(false);
    }
  };

  const handleAddTrack = async () => {
    if (!formData.track_name || !formData.timing_url) {
      setError('Track name and timing URL are required');
      return;
    }

    try {
      const response = await fetch('http://localhost:5000/api/tracks', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          track_name: formData.track_name,
          timing_url: formData.timing_url,
          websocket_url: formData.websocket_url || null
        })
      });

      if (!response.ok) {
        const data = await response.json();
        throw new Error(data.error || 'Failed to add track');
      }

      await fetchTracks();
      setIsAddingTrack(false);
      setFormData({ track_name: '', timing_url: '', websocket_url: '' });
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to add track');
    }
  };

  const handleUpdateTrack = async (trackId: number) => {
    const track = tracks.find(t => t.id === trackId);
    if (!track) return;

    try {
      const response = await fetch(`http://localhost:5000/api/tracks/${trackId}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          track_name: formData.track_name || track.track_name,
          timing_url: formData.timing_url || track.timing_url,
          websocket_url: formData.websocket_url || track.websocket_url
        })
      });

      if (!response.ok) {
        const data = await response.json();
        throw new Error(data.error || 'Failed to update track');
      }

      await fetchTracks();
      setEditingTrackId(null);
      setFormData({ track_name: '', timing_url: '', websocket_url: '' });
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to update track');
    }
  };

  const handleDeleteTrack = async (trackId: number) => {
    if (!confirm('Are you sure you want to delete this track?')) return;

    try {
      const response = await fetch(`http://localhost:5000/api/tracks/${trackId}`, {
        method: 'DELETE'
      });

      if (!response.ok) {
        const data = await response.json();
        throw new Error(data.error || 'Failed to delete track');
      }

      await fetchTracks();
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to delete track');
    }
  };

  const startEditingTrack = (track: Track) => {
    setEditingTrackId(track.id);
    setFormData({
      track_name: track.track_name,
      timing_url: track.timing_url,
      websocket_url: track.websocket_url || ''
    });
  };

  const cancelEditing = () => {
    setEditingTrackId(null);
    setIsAddingTrack(false);
    setFormData({ track_name: '', timing_url: '', websocket_url: '' });
    setError(null);
  };

  if (loading) {
    return <div className="text-gray-400">Loading tracks...</div>;
  }

  return (
    <div className="bg-gray-900 rounded-lg p-6">
      <div className="flex justify-between items-center mb-6">
        <h2 className="text-xl font-bold text-white">Track Manager</h2>
        {!isAddingTrack && (
          <button
            onClick={() => setIsAddingTrack(true)}
            className="flex items-center gap-2 px-4 py-2 bg-blue-600 text-white rounded hover:bg-blue-700 transition-colors"
          >
            <Plus className="w-4 h-4" />
            Add Track
          </button>
        )}
      </div>

      {error && (
        <div className="mb-4 p-3 bg-red-900/50 border border-red-700 rounded flex items-center gap-2 text-red-200">
          <AlertCircle className="w-4 h-4" />
          {error}
        </div>
      )}

      {/* Add new track form */}
      {isAddingTrack && (
        <div className="mb-6 p-4 bg-gray-800 rounded-lg">
          <h3 className="text-lg font-semibold text-white mb-4">Add New Track</h3>
          <div className="space-y-4">
            <div>
              <label className="block text-sm font-medium text-gray-300 mb-1">
                Track Name *
              </label>
              <input
                type="text"
                value={formData.track_name}
                onChange={(e) => setFormData({ ...formData, track_name: e.target.value })}
                className="w-full px-3 py-2 bg-gray-700 text-white rounded border border-gray-600 focus:border-blue-500 focus:outline-none"
                placeholder="e.g., Karting Mariembourg"
              />
            </div>
            <div>
              <label className="block text-sm font-medium text-gray-300 mb-1">
                Timing URL *
              </label>
              <input
                type="text"
                value={formData.timing_url}
                onChange={(e) => setFormData({ ...formData, timing_url: e.target.value })}
                className="w-full px-3 py-2 bg-gray-700 text-white rounded border border-gray-600 focus:border-blue-500 focus:outline-none"
                placeholder="e.g., https://www.apex-timing.com/live-timing/karting-mariembourg/index.html"
              />
            </div>
            <div>
              <label className="block text-sm font-medium text-gray-300 mb-1">
                WebSocket URL (optional)
              </label>
              <input
                type="text"
                value={formData.websocket_url}
                onChange={(e) => setFormData({ ...formData, websocket_url: e.target.value })}
                className="w-full px-3 py-2 bg-gray-700 text-white rounded border border-gray-600 focus:border-blue-500 focus:outline-none"
                placeholder="e.g., ws://www.apex-timing.com:8585/"
              />
            </div>
            <div className="flex gap-2">
              <button
                onClick={handleAddTrack}
                className="px-4 py-2 bg-green-600 text-white rounded hover:bg-green-700 transition-colors"
              >
                Save Track
              </button>
              <button
                onClick={cancelEditing}
                className="px-4 py-2 bg-gray-600 text-white rounded hover:bg-gray-700 transition-colors"
              >
                Cancel
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Track list */}
      <div className="space-y-2">
        {tracks.length === 0 ? (
          <p className="text-gray-400 text-center py-8">
            No tracks configured. Add your first track to get started.
          </p>
        ) : (
          tracks.map((track) => (
            <div
              key={track.id}
              className={`p-4 bg-gray-800 rounded-lg ${
                selectedTrackId === track.id ? 'ring-2 ring-blue-500' : ''
              }`}
            >
              {editingTrackId === track.id ? (
                // Edit form
                <div className="space-y-3">
                  <input
                    type="text"
                    value={formData.track_name}
                    onChange={(e) => setFormData({ ...formData, track_name: e.target.value })}
                    className="w-full px-3 py-2 bg-gray-700 text-white rounded border border-gray-600 focus:border-blue-500 focus:outline-none"
                  />
                  <input
                    type="text"
                    value={formData.timing_url}
                    onChange={(e) => setFormData({ ...formData, timing_url: e.target.value })}
                    className="w-full px-3 py-2 bg-gray-700 text-white rounded border border-gray-600 focus:border-blue-500 focus:outline-none"
                  />
                  <input
                    type="text"
                    value={formData.websocket_url}
                    onChange={(e) => setFormData({ ...formData, websocket_url: e.target.value })}
                    className="w-full px-3 py-2 bg-gray-700 text-white rounded border border-gray-600 focus:border-blue-500 focus:outline-none"
                    placeholder="WebSocket URL (optional)"
                  />
                  <div className="flex gap-2">
                    <button
                      onClick={() => handleUpdateTrack(track.id)}
                      className="p-2 bg-green-600 text-white rounded hover:bg-green-700 transition-colors"
                    >
                      <Check className="w-4 h-4" />
                    </button>
                    <button
                      onClick={cancelEditing}
                      className="p-2 bg-gray-600 text-white rounded hover:bg-gray-700 transition-colors"
                    >
                      <X className="w-4 h-4" />
                    </button>
                  </div>
                </div>
              ) : (
                // Display mode
                <div className="flex items-center justify-between">
                  <div 
                    className="flex-1 cursor-pointer"
                    onClick={() => onSelectTrack && onSelectTrack(track)}
                  >
                    <h3 className="text-lg font-semibold text-white">{track.track_name}</h3>
                    <p className="text-sm text-gray-400 truncate">{track.timing_url}</p>
                    {track.websocket_url && (
                      <p className="text-sm text-gray-500 truncate">WS: {track.websocket_url}</p>
                    )}
                  </div>
                  <div className="flex items-center gap-2">
                    <button
                      onClick={() => startEditingTrack(track)}
                      className="p-2 text-gray-400 hover:text-white transition-colors"
                    >
                      <Edit2 className="w-4 h-4" />
                    </button>
                    <button
                      onClick={() => handleDeleteTrack(track.id)}
                      className="p-2 text-gray-400 hover:text-red-400 transition-colors"
                    >
                      <Trash2 className="w-4 h-4" />
                    </button>
                  </div>
                </div>
              )}
            </div>
          ))
        )}
      </div>
    </div>
  );
};

export default TrackManager;