import React, { useState } from 'react';

interface PitStopConfigProps {
  pitStopTime: number;
  setPitStopTime: (time: number) => void;
  requiredPitStops: number;
  setRequiredPitStops: (stops: number) => void;
  defaultLapTime: number;
  setDefaultLapTime: (time: number) => void;
  /** Kept for call-site compatibility; theming now comes from CSS tokens. */
  isDarkMode?: boolean;
}

const PitStopConfig: React.FC<PitStopConfigProps> = ({
  pitStopTime,
  setPitStopTime,
  requiredPitStops,
  setRequiredPitStops,
  defaultLapTime,
  setDefaultLapTime,
}) => {
  const [isOpen, setIsOpen] = useState(false);
  const [formError, setFormError] = useState<string | null>(null);
  const [localPitTime, setLocalPitTime] = useState(() => {
    const minutes = Math.floor(pitStopTime / 60);
    const seconds = pitStopTime % 60;
    return `${minutes}:${seconds.toString().padStart(2, '0')}`;
  });
  const [localStopsCount, setLocalStopsCount] = useState(requiredPitStops);
  const [localDefaultLap, setLocalDefaultLap] = useState(() => {
    const minutes = Math.floor(defaultLapTime / 60);
    const seconds = Math.round(defaultLapTime % 60);
    return `${minutes}:${seconds.toString().padStart(2, '0')}`;
  });

  const MMSS = /^\d+:[0-5]\d$/;
  const handleSave = () => {
    if (!MMSS.test(localPitTime) || !MMSS.test(localDefaultLap)) {
      setFormError('Enter times as M:SS — e.g. 2:38, 1:30.');
      return;
    }
    const [pitMinutes, pitSeconds] = localPitTime.split(':').map(Number);
    const pitTotalSeconds = (pitMinutes * 60) + pitSeconds;

    const [lapMinutes, lapSeconds] = localDefaultLap.split(':').map(Number);
    const lapTotalSeconds = (lapMinutes * 60) + lapSeconds;

    setPitStopTime(pitTotalSeconds);
    setRequiredPitStops(localStopsCount);
    setDefaultLapTime(lapTotalSeconds);
    setFormError(null);
    setIsOpen(false);
  };

  const inputCls =
    'w-full px-3 py-2 rounded-none border border-line bg-canvas text-ink focus:outline-none focus-visible:ring-2 focus-visible:ring-accent/60';

  return (
    <div className="mb-4">
      <button
        type="button"
        onClick={() => setIsOpen(!isOpen)}
        aria-expanded={isOpen}
        aria-controls="pit-stop-settings"
        className="flex items-center gap-2 px-3 py-2 rounded-none bg-surface-2 text-ink hover:bg-line transition-colors focus:outline-none focus-visible:ring-2 focus-visible:ring-accent/60"
      >
        <svg
          className="w-5 h-5"
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          strokeWidth="2"
          aria-hidden
        >
          <path strokeLinecap="round" strokeLinejoin="round" d="M12 6V4m0 2a2 2 0 100 4m0-4a2 2 0 110 4m-6 8a2 2 0 100-4m0 4a2 2 0 110-4m0 4v2m0-6V4m6 6v10m6-2a2 2 0 100-4m0 4a2 2 0 110-4m0 4v2m0-6V4" />
        </svg>
        Pit Stop Settings
        {!isOpen && (
          <span className="text-sm ml-2 opacity-80 tabular">
            {requiredPitStops} stops, {Math.floor(pitStopTime / 60)}:{(pitStopTime % 60).toString().padStart(2, '0')} each
          </span>
        )}
      </button>

      {isOpen && (
        <div id="pit-stop-settings" className="mt-2 p-4 rounded-none border border-line bg-surface">
          <h3 className="font-medium mb-3">Pit Stop Configuration</h3>

          <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
            <div>
              <label htmlFor="required-stops" className="block text-sm font-medium mb-1 text-muted">
                Required Pit Stops
              </label>
              <input
                id="required-stops"
                type="number"
                min="0"
                max="20"
                value={localStopsCount}
                onChange={(e) => setLocalStopsCount(parseInt(e.target.value) || 0)}
                className={inputCls}
              />
              <p className="mt-1 text-xs text-muted">
                Number of mandatory pit stops during the race
              </p>
            </div>

            <div>
              <label htmlFor="pit-stop-time" className="block text-sm font-medium mb-1 text-muted">
                Pit Stop Time (MM:SS)
              </label>
              <input
                id="pit-stop-time"
                type="text"
                pattern="[0-9]+:[0-5][0-9]"
                placeholder="2:38"
                value={localPitTime}
                onChange={(e) => setLocalPitTime(e.target.value)}
                className={inputCls}
              />
              <p className="mt-1 text-xs text-muted">
                Average time spent in pits (e.g., 2:38)
              </p>
            </div>

            <div>
              <label htmlFor="default-lap" className="block text-sm font-medium mb-1 text-muted">
                Default Lap Time (MM:SS)
              </label>
              <input
                id="default-lap"
                type="text"
                pattern="[0-9]+:[0-5][0-9]"
                placeholder="1:30"
                value={localDefaultLap}
                onChange={(e) => setLocalDefaultLap(e.target.value)}
                className={inputCls}
              />
              <p className="mt-1 text-xs text-muted">
                Used for gap calculations when no historical data
              </p>
            </div>
          </div>

          {formError && (
            <p role="alert" className="mt-3 text-xs text-alarm">{formError}</p>
          )}
          <div className="mt-4 flex justify-end gap-2">
            <button
              type="button"
              onClick={() => setIsOpen(false)}
              className="px-3 py-1.5 rounded-none bg-surface-2 hover:bg-line text-ink transition-colors focus:outline-none focus-visible:ring-2 focus-visible:ring-accent/60"
            >
              Cancel
            </button>
            <button
              type="button"
              onClick={handleSave}
              className="px-3 py-1.5 rounded-none accent-gradient text-accent-ink flex items-center gap-1 transition-colors hover:brightness-95 focus:outline-none focus-visible:ring-2 focus-visible:ring-accent/60"
            >
              <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24" aria-hidden>
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
