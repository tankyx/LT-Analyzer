// racing-analyzer/app/components/RaceDashboard/SimulationControls.tsx
import React, { useState, useEffect } from 'react';
import TrackSelector from './TrackSelector';
import { useAuth } from '../../contexts/AuthContext';
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
  const { user } = useAuth();
  const [isStarting, setIsStarting] = useState(false);
  const [isStopping, setIsStopping] = useState(false);
  const [status, setStatus] = useState<string | null>(null);
  const [timer, setTimer] = useState<number>(0);
  const [showModeSelector, setShowModeSelector] = useState(false);
  const [timingUrl, setTimingUrl] = useState(currentTimingUrl || 'https://www.apex-timing.com/live-timing/karting-mariembourg/index.html');
  const [websocketUrl, setWebsocketUrl] = useState('');
  const [selectedTrackId, setSelectedTrackId] = useState<number | null>(null);
  const [showUrlInput, setShowUrlInput] = useState(false); // Default to Select Track mode

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
    
    console.log('handleStart called with mode:', mode);
    console.log('Current state - timingUrl:', timingUrl, 'websocketUrl:', websocketUrl, 'selectedTrackId:', selectedTrackId);
    
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
        isSimulation ? undefined : (websocketUrl || undefined), // Pass undefined instead of empty string
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
    <div className={`rounded-lg shadow p-4 mb-6 transition-colors bg-surface`}>
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
            <div className={`text-sm rounded-full px-3 py-1 flex items-center bg-live/15 text-live`}>
              <span className="w-2 h-2 rounded-full bg-live inline-block animate-pulse mr-2"></span>
              {isSimulationMode ? 'Simulation' : 'Real Data'} Active - {formatTime(timer)}
            </div>
          </div>
        )}
      </div>
      
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        <div className={`rounded-lg p-4 border border-line bg-surface-2`}>
          <div className="flex flex-col space-y-4">
            {/* Track Selection Mode Toggle - Only show for admin */}
            {user?.role === 'admin' && (
              <div className="flex gap-2 mb-2">
                <button
                  onClick={() => setShowUrlInput(false)}
                  className={`flex-1 px-3 py-2 rounded text-sm font-medium transition-all border
                    ${!showUrlInput
                      ? (isDarkMode 
                          ? 'bg-info text-white border-info' 
                          : 'bg-info/15 text-info border-info')
                      : (isDarkMode 
                          ? 'bg-surface text-ink border-line hover:bg-surface-2' 
                          : 'bg-surface text-ink border-line hover:bg-surface-2')
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
                          ? 'bg-info text-white border-info' 
                          : 'bg-info/15 text-info border-info')
                      : (isDarkMode 
                          ? 'bg-surface text-ink border-line hover:bg-surface-2' 
                          : 'bg-surface text-ink border-line hover:bg-surface-2')
                    }
                  `}
                >
                  Manual URL
                </button>
              </div>
            )}

            {/* Track Selection or URL Input */}
            {showUrlInput && user?.role === 'admin' ? (
              <div>
                <label className={`block text-xs mb-1 text-muted`}>
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
                        ? 'bg-canvas border-line text-ink placeholder:text-muted' 
                        : 'bg-surface border-line text-ink placeholder:text-muted'
                      }
                      focus:outline-none focus:ring-2 focus:ring-info
                    `}
                  />
                </div>
                <div className="mt-2">
                  <label className={`block text-xs mb-1 text-muted`}>
                    WebSocket URL (required):
                  </label>
                    <input
                      type="text"
                      value={websocketUrl}
                      onChange={(e) => setWebsocketUrl(e.target.value)}
                      placeholder="ws://www.apex-timing.com:8585/"
                      className={`w-full px-3 py-2 rounded border text-sm
                        ${isDarkMode 
                          ? 'bg-canvas border-line text-ink placeholder:text-muted' 
                          : 'bg-surface border-line text-ink placeholder:text-muted'
                        }
                        focus:outline-none focus:ring-2 focus:ring-info
                      `}
                    />
                </div>
              </div>
            ) : (
              <TrackSelector
                onSelectTrack={async (track) => {
                  try {
                    console.log('Track selected:', track);
                    
                    // Reset race data when changing tracks
                    await ApiService.resetRaceData();
                    
                    setSelectedTrackId(track.id);
                    setTimingUrl(track.timing_url);
                    // Don't set to empty string if null - keep it as empty string for the input field display
                    setWebsocketUrl(track.websocket_url || '');
                    
                    // Automatically start data collection with the selected track
                    if (track.websocket_url) {
                      console.log('Starting with websocket URL:', track.websocket_url);
                      // Pass the values directly instead of relying on state
                      setIsStarting(true);
                      setStatus('Starting real data collection...');
                      
                      try {
                        await onStart(
                          false, // not simulation
                          track.timing_url,
                          track.websocket_url,
                          track.id
                        );
                        setStatus('Real data collection running');
                        setShowModeSelector(false);
                      } catch (error) {
                        setStatus(`Error starting: ${error instanceof Error ? error.message : 'Unknown error'}`);
                      } finally {
                        setIsStarting(false);
                      }
                    } else {
                      console.log('No websocket URL, showing error message');
                      setStatus('Selected track does not have a WebSocket URL configured');
                    }
                  } catch (error) {
                    console.error('Error in track selection:', error);
                  }
                }}
                selectedTrackId={selectedTrackId}
                isDarkMode={isDarkMode}
              />
            )}


            {!isSimulating && showModeSelector && (
              <div className={`p-4 rounded-lg border border-line bg-surface`}>
                <p className={`text-sm mb-3 ${isDarkMode ? 'text-ink' : 'text-muted'}`}>Choose data source:</p>
                
                <div className="flex space-x-3">
                  <button
                    onClick={() => handleStart('real')}
                    disabled={isStarting}
                    className={`flex-1 px-3 py-2 rounded text-sm font-medium transition-all
                      ${isDarkMode 
                        ? 'bg-info hover:bg-info text-white' 
                        : 'bg-info hover:bg-info text-white'
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
                        ? 'bg-class2 hover:bg-class2 text-white' 
                        : 'bg-class2 hover:bg-class2 text-white'
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
                    ? 'bg-live hover:bg-live text-white disabled:bg-surface-2 disabled:text-muted' 
                    : 'bg-live hover:bg-live text-white disabled:bg-surface-2 disabled:text-muted'
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
                  ? 'bg-alarm hover:bg-alarm text-white disabled:bg-surface-2 disabled:text-muted' 
                  : 'bg-alarm hover:bg-alarm text-white disabled:bg-surface-2 disabled:text-muted'
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
        
        <div className={`rounded-lg p-4 border border-line bg-surface-2`}>
          <h3 className={`text-sm mb-2 flex items-center gap-1 ${isDarkMode ? 'text-ink' : 'text-muted'}`}>
            <svg className="w-4 h-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <path d="M13 16h-1v-4h-1m1-4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
            </svg>
            Simulation Status
          </h3>
          
          {status ? (
            <div className={`font-medium ${
              status.includes('running') ? 'text-live' : 
              status.includes('stopped') ? ('text-accent') : 
              status.includes('Error') ? 'text-alarm' : 
              ('text-info')
            }`}>
              {status}
            </div>
          ) : (
            <div className={`text-muted`}>
              Ready to start simulation
            </div>
          )}
          
          <div className="mt-2 text-xs text-muted">
            {isSimulating ? (
              <div className="space-y-1">
                <div className="flex items-center gap-1">
                  <span className="inline-block w-2 h-2 rounded-full bg-live animate-pulse"></span>
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
