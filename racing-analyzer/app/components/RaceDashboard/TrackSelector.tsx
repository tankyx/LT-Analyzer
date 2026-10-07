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
      <div className={`text-sm ${'text-muted'}`}>
        Loading tracks...
      </div>
    );
  }

  return (
    <div>
      <label className={`block text-xs mb-2 ${'text-muted'}`}>
        Select Track (will start data collection):
      </label>
      <div className={`max-h-48 overflow-y-auto rounded-none border ${
        'border-line'
      }`}>
        {tracks.length === 0 ? (
          <div className={`p-3 text-sm text-center ${'text-muted'}`}>
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
                      ? 'bg-info/50 text-info border-info' 
                      : 'bg-info/15 text-info border-info')
                  : (isDarkMode 
                      ? 'bg-surface hover:bg-surface-2 text-ink border-line' 
                      : 'bg-surface hover:bg-surface-2 text-ink border-line')
                }
              `}
            >
              <div className="flex items-center justify-between">
                <span className="font-medium">{track.track_name}</span>
                {track.websocket_url && (
                  <span className={`text-xs ${'text-muted'}`}>
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