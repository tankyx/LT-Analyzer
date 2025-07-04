import React, { useState, useEffect } from 'react';
import { X, Plus, Edit2, Trash2, Check, AlertCircle } from 'lucide-react';
import ApiService from '../../services/ApiService';

interface ColumnMappings {
  position?: number;
  kart?: number;
  team?: number;
  status?: number;
  lastLap?: number;
  bestLap?: number;
  gap?: number;
  pitStops?: number;
}

interface Track {
  id: number;
  track_name: string;
  timing_url: string;
  websocket_url: string | null;
  column_mappings?: ColumnMappings;
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
  
  const [columnMappings, setColumnMappings] = useState<ColumnMappings>({
    position: 3,
    kart: 4,
    team: 5,
    status: 1,
    lastLap: 6,
    bestLap: 7,
    gap: 8,
    pitStops: 9
  });
  
  const [showColumnMapping, setShowColumnMapping] = useState(false);

  // Fetch tracks on component mount
  useEffect(() => {
    fetchTracks();
  }, []);

  const fetchTracks = async () => {
    try {
      setLoading(true);
      const data = await ApiService.getTracks();
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
      await ApiService.addTrack({
        track_name: formData.track_name,
        timing_url: formData.timing_url,
        websocket_url: formData.websocket_url || undefined,
        column_mappings: columnMappings
      });

      await fetchTracks();
      setIsAddingTrack(false);
      setFormData({ track_name: '', timing_url: '', websocket_url: '' });
      setColumnMappings({
        position: 3,
        kart: 4,
        team: 5,
        status: 1,
        lastLap: 6,
        bestLap: 7,
        gap: 8,
        pitStops: 9
      });
      setShowColumnMapping(false);
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to add track');
    }
  };

  const handleUpdateTrack = async (trackId: number) => {
    const track = tracks.find(t => t.id === trackId);
    if (!track) return;

    try {
      await ApiService.updateTrack(trackId, {
        track_name: formData.track_name || track.track_name,
        timing_url: formData.timing_url || track.timing_url,
        websocket_url: formData.websocket_url || track.websocket_url || undefined,
        column_mappings: columnMappings
      });

      await fetchTracks();
      setEditingTrackId(null);
      setFormData({ track_name: '', timing_url: '', websocket_url: '' });
      setColumnMappings({
        position: 3,
        kart: 4,
        team: 5,
        status: 1,
        lastLap: 6,
        bestLap: 7,
        gap: 8,
        pitStops: 9
      });
      setShowColumnMapping(false);
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to update track');
    }
  };

  const handleDeleteTrack = async (trackId: number) => {
    if (!confirm('Are you sure you want to delete this track?')) return;

    try {
      await ApiService.deleteTrack(trackId);
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
    if (track.column_mappings) {
      setColumnMappings(track.column_mappings);
    }
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
            
            {/* Column Mapping Section */}
            <div className="border-t border-gray-700 pt-4">
              <button
                type="button"
                onClick={() => setShowColumnMapping(!showColumnMapping)}
                className="flex items-center gap-2 text-sm text-blue-400 hover:text-blue-300"
              >
                <svg 
                  className={`w-4 h-4 transition-transform ${showColumnMapping ? 'rotate-90' : ''}`} 
                  fill="none" 
                  stroke="currentColor" 
                  viewBox="0 0 24 24"
                >
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 5l7 7-7 7" />
                </svg>
                Configure Column Mappings (Advanced)
              </button>
              
              {showColumnMapping && (
                <div className="mt-4 p-4 bg-gray-900 rounded-lg">
                  <p className="text-xs text-gray-400 mb-4">
                    Specify which column number contains each type of data. Column numbers start at 1.
                  </p>
                  <div className="grid grid-cols-2 gap-4">
                    <div>
                      <label className="block text-xs font-medium text-gray-400 mb-1">
                        Position Column
                      </label>
                      <input
                        type="number"
                        min="1"
                        value={columnMappings.position || ''}
                        onChange={(e) => setColumnMappings({ ...columnMappings, position: parseInt(e.target.value) || undefined })}
                        className="w-full px-2 py-1 bg-gray-800 text-white rounded border border-gray-700 focus:border-blue-500 focus:outline-none text-sm"
                        placeholder="e.g., 3"
                      />
                    </div>
                    <div>
                      <label className="block text-xs font-medium text-gray-400 mb-1">
                        Kart Number Column
                      </label>
                      <input
                        type="number"
                        min="1"
                        value={columnMappings.kart || ''}
                        onChange={(e) => setColumnMappings({ ...columnMappings, kart: parseInt(e.target.value) || undefined })}
                        className="w-full px-2 py-1 bg-gray-800 text-white rounded border border-gray-700 focus:border-blue-500 focus:outline-none text-sm"
                        placeholder="e.g., 4"
                      />
                    </div>
                    <div>
                      <label className="block text-xs font-medium text-gray-400 mb-1">
                        Team Name Column
                      </label>
                      <input
                        type="number"
                        min="1"
                        value={columnMappings.team || ''}
                        onChange={(e) => setColumnMappings({ ...columnMappings, team: parseInt(e.target.value) || undefined })}
                        className="w-full px-2 py-1 bg-gray-800 text-white rounded border border-gray-700 focus:border-blue-500 focus:outline-none text-sm"
                        placeholder="e.g., 5"
                      />
                    </div>
                    <div>
                      <label className="block text-xs font-medium text-gray-400 mb-1">
                        Status Column
                      </label>
                      <input
                        type="number"
                        min="1"
                        value={columnMappings.status || ''}
                        onChange={(e) => setColumnMappings({ ...columnMappings, status: parseInt(e.target.value) || undefined })}
                        className="w-full px-2 py-1 bg-gray-800 text-white rounded border border-gray-700 focus:border-blue-500 focus:outline-none text-sm"
                        placeholder="e.g., 1"
                      />
                    </div>
                    <div>
                      <label className="block text-xs font-medium text-gray-400 mb-1">
                        Last Lap Column
                      </label>
                      <input
                        type="number"
                        min="1"
                        value={columnMappings.lastLap || ''}
                        onChange={(e) => setColumnMappings({ ...columnMappings, lastLap: parseInt(e.target.value) || undefined })}
                        className="w-full px-2 py-1 bg-gray-800 text-white rounded border border-gray-700 focus:border-blue-500 focus:outline-none text-sm"
                        placeholder="e.g., 6"
                      />
                    </div>
                    <div>
                      <label className="block text-xs font-medium text-gray-400 mb-1">
                        Best Lap Column
                      </label>
                      <input
                        type="number"
                        min="1"
                        value={columnMappings.bestLap || ''}
                        onChange={(e) => setColumnMappings({ ...columnMappings, bestLap: parseInt(e.target.value) || undefined })}
                        className="w-full px-2 py-1 bg-gray-800 text-white rounded border border-gray-700 focus:border-blue-500 focus:outline-none text-sm"
                        placeholder="e.g., 7"
                      />
                    </div>
                    <div>
                      <label className="block text-xs font-medium text-gray-400 mb-1">
                        Gap Column
                      </label>
                      <input
                        type="number"
                        min="1"
                        value={columnMappings.gap || ''}
                        onChange={(e) => setColumnMappings({ ...columnMappings, gap: parseInt(e.target.value) || undefined })}
                        className="w-full px-2 py-1 bg-gray-800 text-white rounded border border-gray-700 focus:border-blue-500 focus:outline-none text-sm"
                        placeholder="e.g., 8"
                      />
                    </div>
                    <div>
                      <label className="block text-xs font-medium text-gray-400 mb-1">
                        Pit Stops Column
                      </label>
                      <input
                        type="number"
                        min="1"
                        value={columnMappings.pitStops || ''}
                        onChange={(e) => setColumnMappings({ ...columnMappings, pitStops: parseInt(e.target.value) || undefined })}
                        className="w-full px-2 py-1 bg-gray-800 text-white rounded border border-gray-700 focus:border-blue-500 focus:outline-none text-sm"
                        placeholder="e.g., 9"
                      />
                    </div>
                  </div>
                </div>
              )}
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
                  
                  {/* Column Mapping Button for Edit */}
                  <button
                    type="button"
                    onClick={() => setShowColumnMapping(!showColumnMapping)}
                    className="text-xs text-blue-400 hover:text-blue-300"
                  >
                    {showColumnMapping ? 'Hide' : 'Show'} Column Mappings
                  </button>
                  
                  {showColumnMapping && (
                    <div className="p-3 bg-gray-900 rounded text-xs">
                      <div className="grid grid-cols-2 gap-2">
                        {Object.entries({
                          position: 'Position',
                          kart: 'Kart',
                          team: 'Team',
                          status: 'Status',
                          lastLap: 'Last Lap',
                          bestLap: 'Best Lap',
                          gap: 'Gap',
                          pitStops: 'Pit Stops'
                        }).map(([key, label]) => (
                          <div key={key}>
                            <label className="block text-gray-400 mb-1">{label}</label>
                            <input
                              type="number"
                              min="1"
                              value={columnMappings[key as keyof ColumnMappings] || ''}
                              onChange={(e) => setColumnMappings({ 
                                ...columnMappings, 
                                [key]: parseInt(e.target.value) || undefined 
                              })}
                              className="w-full px-2 py-1 bg-gray-800 text-white rounded border border-gray-700"
                            />
                          </div>
                        ))}
                      </div>
                    </div>
                  )}
                  
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