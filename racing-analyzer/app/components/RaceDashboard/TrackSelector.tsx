import React, { useState, useEffect } from 'react';
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

interface TrackSelectorProps {
  onSelectTrack?: (track: Track) => void;
  selectedTrackId?: number | null;
  isDarkMode?: boolean;
}

const TrackSelector: React.FC<TrackSelectorProps> = ({ onSelectTrack, selectedTrackId, isDarkMode = true }) => {
  const [tracks, setTracks] = useState<Track[]>([]);
  const [loading, setLoading] = useState(true);

  // Fetch tracks on component mount
  useEffect(() => {
    fetchTracks();
  }, []);

  const fetchTracks = async () => {
    try {
      setLoading(true);
      const data = await ApiService.getTracks();
      setTracks(data.tracks || []);
    } catch (err) {
      console.error('Error fetching tracks:', err);
    } finally {
      setLoading(false);
    }
  };

  const handleSelectTrack = (track: Track) => {
    if (onSelectTrack) {
      onSelectTrack(track);
    }
  };

  if (loading) {
    return (
      <div className={`text-sm ${isDarkMode ? 'text-gray-400' : 'text-gray-500'}`}>
        Loading tracks...
      </div>
    );
  }

  return (
    <div>
      <label className={`block text-xs mb-2 ${isDarkMode ? 'text-gray-400' : 'text-gray-500'}`}>
        Select Track (will start data collection):
      </label>
      <div className={`max-h-48 overflow-y-auto rounded border ${
        isDarkMode ? 'border-gray-600' : 'border-gray-300'
      }`}>
        {tracks.length === 0 ? (
          <div className={`p-3 text-sm text-center ${isDarkMode ? 'text-gray-500' : 'text-gray-400'}`}>
            No tracks available
          </div>
        ) : (
          tracks.map((track) => (
            <div
              key={track.id}
              onClick={() => handleSelectTrack(track)}
              className={`px-3 py-2 cursor-pointer transition-colors text-sm border-b last:border-b-0
                ${selectedTrackId === track.id 
                  ? (isDarkMode 
                      ? 'bg-blue-900/50 text-blue-300 border-blue-800' 
                      : 'bg-blue-100 text-blue-800 border-blue-200')
                  : (isDarkMode 
                      ? 'bg-gray-800 hover:bg-gray-700 text-gray-100 border-gray-700' 
                      : 'bg-white hover:bg-gray-50 text-gray-900 border-gray-200')
                }
              `}
            >
              <div className="flex items-center justify-between">
                <span className="font-medium">{track.track_name}</span>
                {track.websocket_url && (
                  <span className={`text-xs ${isDarkMode ? 'text-gray-500' : 'text-gray-400'}`}>
                    WS
                  </span>
                )}
              </div>
            </div>
          ))
        )}
      </div>
    </div>
  );
};

export default TrackSelector;