// racing-analyzer/app/components/RaceDashboard/SimulationControls.tsx
import React, { useState, useEffect } from 'react';
import TrackManager from './TrackManager';
import ApiService from '../../services/ApiService';

interface SimulationControlsProps {
  onStart: (isSimulation?: boolean, timingUrl?: string, websocketUrl?: string, trackId?: number) => void;
  onStop: () => void;
  isSimulating?: boolean;
  isDarkMode?: boolean;
  isSimulationMode?: boolean;
  currentTimingUrl?: string;
}

const SimulationControls: React.FC<SimulationControlsProps> = ({ 
  onStart, 
  onStop, 
  isSimulating = false,
  isDarkMode = false,
  isSimulationMode = false,
  currentTimingUrl = ''
}) => {
  const [isStarting, setIsStarting] = useState(false);
  const [isStopping, setIsStopping] = useState(false);
  const [status, setStatus] = useState<string | null>(null);
  const [timer, setTimer] = useState<number>(0);
  const [showModeSelector, setShowModeSelector] = useState(false);
  const [timingUrl, setTimingUrl] = useState(currentTimingUrl || 'https://www.apex-timing.com/live-timing/karting-mariembourg/index.html');
  const [websocketUrl, setWebsocketUrl] = useState('');
  const [selectedTrackId, setSelectedTrackId] = useState<number | null>(null);
  const [showUrlInput, setShowUrlInput] = useState(true);

  // Update timing URL when currentTimingUrl changes (only on mount)
  useEffect(() => {
    if (currentTimingUrl) {
      setTimingUrl(currentTimingUrl);
    }
  }, [currentTimingUrl]);

  // Start a timer when simulation is running
  useEffect(() => {
    let interval: NodeJS.Timeout | null = null;
    
    if (isSimulating) {
      interval = setInterval(() => {
        setTimer(prev => prev + 1);
      }, 1000);
    } else {
      setTimer(0);
    }
    
    return () => {
      if (interval) clearInterval(interval);
    };
  }, [isSimulating]);

  // Format time as HH:MM:SS
  const formatTime = (seconds: number): string => {
    const hrs = Math.floor(seconds / 3600);
    const mins = Math.floor((seconds % 3600) / 60);
    const secs = seconds % 60;
    
    return `${hrs.toString().padStart(2, '0')}:${mins.toString().padStart(2, '0')}:${secs.toString().padStart(2, '0')}`;
  };

  const handleStart = async (mode?: 'real' | 'simulation') => {
    setIsStarting(true);
    const isSimulation = mode === 'simulation';
    
    // Validate URL for real mode
    if (!isSimulation && !timingUrl.trim()) {
      setStatus('Please enter a timing URL');
      setIsStarting(false);
      return;
    }
    
    setStatus(isSimulation ? 'Starting simulation...' : 'Starting real data collection...');
    
    try {
      await onStart(
        isSimulation, 
        isSimulation ? undefined : timingUrl, 
        isSimulation ? undefined : websocketUrl,
        isSimulation ? undefined : selectedTrackId || undefined
      );
      setStatus(isSimulation ? 'Simulation running' : 'Real data collection running');
      setShowModeSelector(false);
    } catch (error) {
      setStatus(`Error starting: ${error instanceof Error ? error.message : 'Unknown error'}`);
    } finally {
      setIsStarting(false);
    }
  };

  const handleStop = async () => {
    setIsStopping(true);
    setStatus('Stopping simulation...');
    
    try {
      await onStop();
      setStatus('Simulation stopped');
    } catch (error) {
      setStatus(`Error stopping simulation: ${error instanceof Error ? error.message : 'Unknown error'}`);
    } finally {
      setIsStopping(false);
    }
  };

  return (
    <div className={`rounded-lg shadow p-4 mb-6 transition-colors ${isDarkMode ? 'bg-gray-800' : 'bg-white'}`}>
      <div className="flex flex-col sm:flex-row sm:items-center justify-between mb-4">
        <h2 className="font-semibold text-lg mb-2 sm:mb-0 flex items-center">
          <svg className="w-5 h-5 mr-2" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <circle cx="12" cy="12" r="10" />
            <path d="M10 8l6 4-6 4V8z" />
          </svg>
          Simulation Controls
        </h2>
        
        {isSimulating && (
          <div className="flex items-center gap-2">
            <div className={`text-sm rounded-full px-3 py-1 flex items-center ${isDarkMode ? 'bg-green-900 text-green-200' : 'bg-green-100 text-green-800'}`}>
              <span className="w-2 h-2 rounded-full bg-green-500 inline-block animate-pulse mr-2"></span>
              {isSimulationMode ? 'Simulation' : 'Real Data'} Active - {formatTime(timer)}
            </div>
          </div>
        )}
      </div>
      
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        <div className={`rounded-lg p-4 border ${isDarkMode ? 'border-gray-700 bg-gray-700' : 'border-gray-200 bg-gray-50'}`}>
          <div className="flex flex-col space-y-4">
            {/* Track Selection Mode Toggle */}
            <div className="flex gap-2 mb-2">
              <button
                onClick={() => setShowUrlInput(false)}
                className={`flex-1 px-3 py-2 rounded text-sm font-medium transition-all border
                  ${!showUrlInput
                    ? (isDarkMode 
                        ? 'bg-blue-700 text-white border-blue-600' 
                        : 'bg-blue-100 text-blue-800 border-blue-300')
                    : (isDarkMode 
                        ? 'bg-gray-800 text-gray-300 border-gray-600 hover:bg-gray-700' 
                        : 'bg-white text-gray-700 border-gray-300 hover:bg-gray-50')
                  }
                `}
              >
                Select Track
              </button>
              <button
                onClick={() => setShowUrlInput(true)}
                className={`flex-1 px-3 py-2 rounded text-sm font-medium transition-all border
                  ${showUrlInput
                    ? (isDarkMode 
                        ? 'bg-blue-700 text-white border-blue-600' 
                        : 'bg-blue-100 text-blue-800 border-blue-300')
                    : (isDarkMode 
                        ? 'bg-gray-800 text-gray-300 border-gray-600 hover:bg-gray-700' 
                        : 'bg-white text-gray-700 border-gray-300 hover:bg-gray-50')
                  }
                `}
              >
                Manual URL
              </button>
            </div>

            {/* Track Selection or URL Input */}
            {showUrlInput ? (
              <div>
                <label className={`block text-xs mb-1 ${isDarkMode ? 'text-gray-400' : 'text-gray-500'}`}>
                  Live Timing URL:
                </label>
                <div className="flex gap-2">
                  <input
                    type="text"
                    value={timingUrl}
                    onChange={(e) => {
                      setTimingUrl(e.target.value);
                      setSelectedTrackId(null);
                    }}
                    placeholder="https://www.apex-timing.com/live-timing/..."
                    className={`flex-1 px-3 py-2 rounded border text-sm
                      ${isDarkMode 
                        ? 'bg-gray-900 border-gray-600 text-gray-100 placeholder-gray-500' 
                        : 'bg-white border-gray-300 text-gray-900 placeholder-gray-400'
                      }
                      focus:outline-none focus:ring-2 focus:ring-blue-500
                    `}
                  />
                </div>
                <div className="mt-2">
                  <label className={`block text-xs mb-1 ${isDarkMode ? 'text-gray-400' : 'text-gray-500'}`}>
                    WebSocket URL (required):
                  </label>
                    <input
                      type="text"
                      value={websocketUrl}
                      onChange={(e) => setWebsocketUrl(e.target.value)}
                      placeholder="ws://www.apex-timing.com:8585/"
                      className={`w-full px-3 py-2 rounded border text-sm
                        ${isDarkMode 
                          ? 'bg-gray-900 border-gray-600 text-gray-100 placeholder-gray-500' 
                          : 'bg-white border-gray-300 text-gray-900 placeholder-gray-400'
                        }
                        focus:outline-none focus:ring-2 focus:ring-blue-500
                      `}
                    />
                </div>
              </div>
            ) : (
              <div className="max-h-64 overflow-y-auto">
                <TrackManager
                  onSelectTrack={async (track) => {
                    try {
                      // Reset race data when changing tracks
                      await ApiService.resetRaceData();
                      
                      setSelectedTrackId(track.id);
                      setTimingUrl(track.timing_url);
                      setWebsocketUrl(track.websocket_url || '');
                    } catch (error) {
                      console.error('Error resetting race data:', error);
                    }
                  }}
                  selectedTrackId={selectedTrackId}
                />
              </div>
            )}


            {!isSimulating && showModeSelector && (
              <div className={`p-4 rounded-lg border ${isDarkMode ? 'border-gray-600 bg-gray-800' : 'border-gray-300 bg-white'}`}>
                <p className={`text-sm mb-3 ${isDarkMode ? 'text-gray-300' : 'text-gray-600'}`}>Choose data source:</p>
                
                <div className="flex space-x-3">
                  <button
                    onClick={() => handleStart('real')}
                    disabled={isStarting}
                    className={`flex-1 px-3 py-2 rounded text-sm font-medium transition-all
                      ${isDarkMode 
                        ? 'bg-blue-700 hover:bg-blue-600 text-white' 
                        : 'bg-blue-500 hover:bg-blue-600 text-white'
                      }
                    `}
                  >
                    Real Data
                  </button>
                  <button
                    onClick={() => handleStart('simulation')}
                    disabled={isStarting}
                    className={`flex-1 px-3 py-2 rounded text-sm font-medium transition-all
                      ${isDarkMode 
                        ? 'bg-purple-700 hover:bg-purple-600 text-white' 
                        : 'bg-purple-500 hover:bg-purple-600 text-white'
                      }
                    `}
                  >
                    Simulation
                  </button>
                </div>
              </div>
            )}
            
            <div className="flex space-x-4">
              <button
                onClick={() => {
                  if (!isSimulating) {
                    setShowModeSelector(!showModeSelector);
                  }
                }}
                disabled={isStarting || isStopping || isSimulating}
                className={`flex-1 flex items-center justify-center gap-2 px-4 py-3 rounded font-medium transition-all
                  ${isStarting ? 'opacity-70 cursor-wait' : ''}
                  ${isSimulating ? 'opacity-50 cursor-not-allowed' : ''}
                  ${isDarkMode 
                    ? 'bg-green-700 hover:bg-green-600 text-white disabled:bg-gray-700 disabled:text-gray-400' 
                    : 'bg-green-500 hover:bg-green-600 text-white disabled:bg-gray-200 disabled:text-gray-500'
                  }
                `}
              >
                {isStarting ? (
                  <>
                    <svg className="animate-spin h-5 w-5 text-white" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24">
                      <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4"></circle>
                      <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path>
                    </svg>
                    Starting...
                  </>
                ) : (
                  <>
                    <svg className="w-5 h-5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                      <path d="M5 3l14 9-14 9V3z" />
                    </svg>
                    Start Collection
                  </>
                )}
              </button>
            
            <button
              onClick={handleStop}
              disabled={isStopping || !isSimulating}
              className={`flex-1 flex items-center justify-center gap-2 px-4 py-3 rounded font-medium transition-all
                ${isStopping ? 'opacity-70 cursor-wait' : ''}
                ${!isSimulating ? 'opacity-50 cursor-not-allowed' : ''}
                ${isDarkMode 
                  ? 'bg-red-700 hover:bg-red-600 text-white disabled:bg-gray-700 disabled:text-gray-400' 
                  : 'bg-red-500 hover:bg-red-600 text-white disabled:bg-gray-200 disabled:text-gray-500'
                }
              `}
            >
              {isStopping ? (
                <>
                  <svg className="animate-spin h-5 w-5 text-white" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24">
                    <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4"></circle>
                    <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path>
                  </svg>
                  Stopping...
                </>
              ) : (
                <>
                  <svg className="w-5 h-5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                    <rect x="6" y="6" width="12" height="12" />
                  </svg>
                  Stop Simulation
                </>
              )}
            </button>
          </div>
          </div>
        </div>
        
        <div className={`rounded-lg p-4 border ${isDarkMode ? 'border-gray-700 bg-gray-700' : 'border-gray-200 bg-gray-50'}`}>
          <h3 className={`text-sm mb-2 flex items-center gap-1 ${isDarkMode ? 'text-gray-300' : 'text-gray-600'}`}>
            <svg className="w-4 h-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <path d="M13 16h-1v-4h-1m1-4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
            </svg>
            Simulation Status
          </h3>
          
          {status ? (
            <div className={`font-medium ${
              status.includes('running') ? 'text-green-500' : 
              status.includes('stopped') ? (isDarkMode ? 'text-orange-400' : 'text-orange-500') : 
              status.includes('Error') ? 'text-red-500' : 
              (isDarkMode ? 'text-blue-400' : 'text-blue-600')
            }`}>
              {status}
            </div>
          ) : (
            <div className={`${isDarkMode ? 'text-gray-400' : 'text-gray-500'}`}>
              Ready to start simulation
            </div>
          )}
          
          <div className="mt-2 text-xs text-gray-500">
            {isSimulating ? (
              <div className="space-y-1">
                <div className="flex items-center gap-1">
                  <span className="inline-block w-2 h-2 rounded-full bg-green-500 animate-pulse"></span>
                  {isSimulationMode ? 'The simulation is running at 4x real-time speed' : 'Collecting real-time data from Apex Timing'}
                </div>
              </div>
            ) : (
              "Press Start to begin data collection"
            )}
          </div>
        </div>
      </div>
    </div>
  );
};

export default SimulationControls;
