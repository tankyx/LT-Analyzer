import React from 'react';

interface TrackStatus {
  track_id: number;
  track_name: string;
  active: boolean;
  last_update?: string;
  teams_count?: number;
}

interface MultiTrackStatusProps {
  tracks: TrackStatus[];
  selectedTrackId: number;
  onSelectTrack: (trackId: number) => void;
  isDarkMode: boolean;
}

const MultiTrackStatus: React.FC<MultiTrackStatusProps> = ({
  tracks,
  selectedTrackId,
  onSelectTrack,
  isDarkMode
}) => {
  return (
    <div className={`rounded-lg p-4 flex flex-col h-full max-h-[400px] ${isDarkMode ? 'bg-gray-700' : 'bg-blue-50'}`}>
      <h2 className={`text-lg font-semibold mb-4 flex items-center flex-shrink-0 ${isDarkMode ? 'text-white' : 'text-gray-900'}`}>
        <svg className="w-5 h-5 mr-2" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M9 19v-6a2 2 0 00-2-2H5a2 2 0 00-2 2v6a2 2 0 002 2h2a2 2 0 002-2zm0 0V9a2 2 0 012-2h2a2 2 0 012 2v10m-6 0a2 2 0 002 2h2a2 2 0 002-2m0 0V5a2 2 0 012-2h2a2 2 0 012 2v14a2 2 0 01-2 2h-2a2 2 0 01-2-2z" />
        </svg>
        All Tracks Status
      </h2>

      <div className="space-y-2 overflow-y-auto flex-1 pr-2 -mr-2 min-h-0">
        {tracks.length === 0 ? (
          <div className={`text-sm ${isDarkMode ? 'text-gray-400' : 'text-gray-600'}`}>
            No tracks configured
          </div>
        ) : (
          tracks.map(track => (
            <button
              key={track.track_id}
              onClick={() => onSelectTrack(track.track_id)}
              className={`w-full text-left p-3 rounded-lg transition-all ${
                track.track_id === selectedTrackId
                  ? isDarkMode
                    ? 'bg-blue-900 border-2 border-blue-400'
                    : 'bg-blue-100 border-2 border-blue-500'
                  : isDarkMode
                    ? 'bg-gray-800 border border-gray-600 hover:bg-gray-750'
                    : 'bg-white border border-gray-300 hover:bg-gray-50'
              }`}
            >
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-2 flex-1">
                  <div className={`w-3 h-3 rounded-full ${
                    track.active
                      ? 'bg-green-500 animate-pulse'
                      : 'bg-gray-400'
                  }`} />
                  <div>
                    <div className={`font-medium ${
                      track.track_id === selectedTrackId
                        ? isDarkMode ? 'text-blue-200' : 'text-blue-900'
                        : isDarkMode ? 'text-white' : 'text-gray-900'
                    }`}>
                      {track.track_name}
                    </div>
                    <div className={`text-xs ${
                      isDarkMode ? 'text-gray-400' : 'text-gray-600'
                    }`}>
                      {track.active ? (
                        <>
                          <span className="text-green-600 dark:text-green-400 font-medium">● Active</span>
                          {track.teams_count !== undefined && ` • ${track.teams_count} teams`}
                        </>
                      ) : (
                        <span className="text-gray-500">○ No session</span>
                      )}
                    </div>
                  </div>
                </div>

                {track.track_id === selectedTrackId && (
                  <svg className="w-5 h-5 text-blue-500" fill="currentColor" viewBox="0 0 20 20">
                    <path fillRule="evenodd" d="M10 18a8 8 0 100-16 8 8 0 000 16zm3.707-9.293a1 1 0 00-1.414-1.414L9 10.586 7.707 9.293a1 1 0 00-1.414 1.414l2 2a1 1 0 001.414 0l4-4z" clipRule="evenodd" />
                  </svg>
                )}
              </div>

              {track.last_update && (
                <div className={`text-xs mt-1 ${
                  isDarkMode ? 'text-gray-500' : 'text-gray-500'
                }`}>
                  Last update: {new Date(track.last_update).toLocaleTimeString()}
                </div>
              )}
            </button>
          ))
        )}
      </div>
    </div>
  );
};

export default MultiTrackStatus;
