import React, { useState } from 'react';

interface PitStopConfigProps {
  pitStopTime: number;
  setPitStopTime: (time: number) => void;
  requiredPitStops: number;
  setRequiredPitStops: (stops: number) => void;
  isDarkMode?: boolean;
}

const PitStopConfig: React.FC<PitStopConfigProps> = ({ 
  pitStopTime,
  setPitStopTime,
  requiredPitStops,
  setRequiredPitStops,
  isDarkMode = false 
}) => {
  const [isOpen, setIsOpen] = useState(false);
  const [localPitTime, setLocalPitTime] = useState(() => {
    // Convert seconds to MM:SS format
    const minutes = Math.floor(pitStopTime / 60);
    const seconds = pitStopTime % 60;
    return `${minutes}:${seconds.toString().padStart(2, '0')}`;
  });
  const [localStopsCount, setLocalStopsCount] = useState(requiredPitStops);
  
  const handleSave = () => {
    // Parse the MM:SS format to seconds
    const [minutes, seconds] = localPitTime.split(':').map(Number);
    const totalSeconds = (minutes * 60) + seconds;
    
    setPitStopTime(totalSeconds);
    setRequiredPitStops(localStopsCount);
    setIsOpen(false);
  };
  
  return (
    <div className="mb-4">
      <button
        onClick={() => setIsOpen(!isOpen)}
        className={`flex items-center gap-2 px-3 py-2 rounded-lg transition-colors ${
          isDarkMode 
            ? 'bg-gray-700 hover:bg-gray-600 text-white' 
            : 'bg-blue-50 hover:bg-blue-100 text-blue-700'
        }`}
      >
        <svg 
          className="w-5 h-5" 
          viewBox="0 0 24 24" 
          fill="none" 
          stroke="currentColor" 
          strokeWidth="2"
        >
          <path strokeLinecap="round" strokeLinejoin="round" d="M12 6V4m0 2a2 2 0 100 4m0-4a2 2 0 110 4m-6 8a2 2 0 100-4m0 4a2 2 0 110-4m0 4v2m0-6V4m6 6v10m6-2a2 2 0 100-4m0 4a2 2 0 110-4m0 4v2m0-6V4" />
        </svg>
        Pit Stop Settings
        {!isOpen && (
          <span className="text-sm ml-2 opacity-80">
            {requiredPitStops} stops, {Math.floor(pitStopTime / 60)}:{(pitStopTime % 60).toString().padStart(2, '0')} each
          </span>
        )}
      </button>
      
      {isOpen && (
        <div className={`mt-2 p-4 rounded-lg border ${
          isDarkMode 
            ? 'bg-gray-800 border-gray-700' 
            : 'bg-white border-gray-200'
        }`}>
          <h3 className="font-medium mb-3">Pit Stop Configuration</h3>
          
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            <div>
              <label className={`block text-sm font-medium mb-1 ${
                isDarkMode ? 'text-gray-300' : 'text-gray-700'
              }`}>
                Required Pit Stops
              </label>
              <input
                type="number"
                min="0"
                max="20"
                value={localStopsCount}
                onChange={(e) => setLocalStopsCount(parseInt(e.target.value) || 0)}
                className={`w-full px-3 py-2 rounded-md border ${
                  isDarkMode 
                    ? 'bg-gray-700 border-gray-600 text-white' 
                    : 'bg-white border-gray-300 text-gray-900'
                }`}
              />
              <p className={`mt-1 text-xs ${
                isDarkMode ? 'text-gray-400' : 'text-gray-500'
              }`}>
                Number of mandatory pit stops during the race
              </p>
            </div>
            
            <div>
              <label className={`block text-sm font-medium mb-1 ${
                isDarkMode ? 'text-gray-300' : 'text-gray-700'
              }`}>
                Pit Stop Time (MM:SS)
              </label>
              <input
                type="text"
                pattern="[0-9]+:[0-5][0-9]"
                placeholder="2:38"
                value={localPitTime}
                onChange={(e) => setLocalPitTime(e.target.value)}
                className={`w-full px-3 py-2 rounded-md border ${
                  isDarkMode 
                    ? 'bg-gray-700 border-gray-600 text-white' 
                    : 'bg-white border-gray-300 text-gray-900'
                }`}
              />
              <p className={`mt-1 text-xs ${
                isDarkMode ? 'text-gray-400' : 'text-gray-500'
              }`}>
                Average time spent in pits (e.g., 2:38)
              </p>
            </div>
          </div>
          
          <div className="mt-4 flex justify-end gap-2">
            <button
              onClick={() => setIsOpen(false)}
              className={`px-3 py-1.5 rounded ${
                isDarkMode 
                  ? 'bg-gray-700 hover:bg-gray-600 text-gray-300' 
                  : 'bg-gray-100 hover:bg-gray-200 text-gray-700'
              }`}
            >
              Cancel
            </button>
            <button
              onClick={handleSave}
              className={`px-3 py-1.5 rounded flex items-center gap-1 ${
                isDarkMode 
                  ? 'bg-blue-600 hover:bg-blue-500 text-white' 
                  : 'bg-blue-500 hover:bg-blue-600 text-white'
              }`}
            >
              <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M5 13l4 4L19 7" />
              </svg>
              Apply Settings
            </button>
          </div>
        </div>
      )}
    </div>
  );
};

export default PitStopConfig;
