import React, { useState, useEffect, useCallback, useMemo } from 'react';
import {
  LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, Legend,
  ResponsiveContainer, ReferenceLine, Label, Area, ComposedChart
} from 'recharts';
import { motion } from 'framer-motion';

// Toggle component for switching between regular and adjusted gap modes
const ModeToggle = ({ mode, setMode, isDarkMode }) => (
  <div className="flex items-center space-x-2">
    <span className={`text-sm ${mode === 'regular' ? (isDarkMode ? 'text-blue-300' : 'text-blue-600') : (isDarkMode ? 'text-gray-400' : 'text-gray-500')}`}>
      Regular Gap
    </span>
    <button 
      onClick={() => setMode(mode === 'regular' ? 'adjusted' : 'regular')}
      className={`relative inline-flex h-6 w-11 items-center rounded-full transition-colors ${mode === 'adjusted' ? (isDarkMode ? 'bg-blue-600' : 'bg-blue-500') : (isDarkMode ? 'bg-gray-600' : 'bg-gray-300')}`}
    >
      <span 
        className={`inline-block h-4 w-4 transform rounded-full bg-white transition-transform ${mode === 'adjusted' ? 'translate-x-6' : 'translate-x-1'}`} 
      />
    </button>
    <span className={`text-sm ${mode === 'adjusted' ? (isDarkMode ? 'text-blue-300' : 'text-blue-600') : (isDarkMode ? 'text-gray-400' : 'text-gray-500')}`}>
      Adjusted for Pit Stops
    </span>
  </div>
);

const TimeDeltaChart = ({ 
  gapHistory, 
  teams, 
  monitoredTeams,
  isDarkMode = false,
  onColorAssignment,
  onTeamHover
}) => {
  const [chartData, setChartData] = useState([]);
  const [teamColors, setTeamColors] = useState({});
  const [hoveredTeam, setHoveredTeam] = useState(null);
  const [chartKey, setChartKey] = useState(0);
  const [gapMode, setGapMode] = useState('regular'); // 'regular' or 'adjusted'
  
  // Force chart re-render when theme or mode changes
  useEffect(() => {
    setChartKey(prev => prev + 1);
  }, [isDarkMode, gapMode]);

  // Generate team colors
  const generateColor = useCallback((kartNumber) => {
    const kartId = parseInt(kartNumber);
    
    const goldenRatioConjugate = 0.618033988749895;
    let hue = (kartId * goldenRatioConjugate) % 1;
    hue = Math.round(hue * 360);
    
    // Vary saturation and lightness further based on kart number
    const saturation = 70 + ((kartId % 3) * 10); // 70%, 80%, or 90%
    const lightness = isDarkMode ? 
      (50 + ((kartId % 5) * 5)) : // 50-70% for dark mode
      (40 - ((kartId % 3) * 5));  // 30-40% for light mode
    
    return `hsl(${hue}, ${saturation}%, ${lightness}%)`;
  }, [isDarkMode]);

  // Prepare data with sliding window of 15 laps
  useEffect(() => {
    if (!gapHistory || Object.keys(gapHistory).length === 0) return;
  
    // Set team colors
    const colors = {};
    monitoredTeams.forEach(kart => {
      colors[kart] = generateColor(kart);
    });
    setTeamColors(colors);
    
    // Pass colors to parent component if callback exists
    if (onColorAssignment) {
      onColorAssignment(colors);
    }

    // Prepare chart data
    const preparedData = [];
    let maxLaps = 0;

    // Find max number of laps
    monitoredTeams.forEach(kartNum => {
      if (gapHistory[kartNum] && gapHistory[kartNum].gaps) {
        maxLaps = Math.max(maxLaps, gapHistory[kartNum].gaps.length);
      }
    });

    const MAX_VISIBLE_LAPS = 15;
    const windowStart = Math.max(0, maxLaps - MAX_VISIBLE_LAPS);
    
    for (let i = windowStart; i < maxLaps; i++) {
      const lapNumber = i + 1;
      
      const lapData = { 
        lap: lapNumber,
        absoluteLap: lapNumber
      };
      
      monitoredTeams.forEach(kartNum => {
        const team = teams.find(t => t.Kart === kartNum);
        
        // Check if we have data for this team at this lap
        if (gapHistory[kartNum]) {
          // Get regular gap
          if (gapHistory[kartNum].gaps && gapHistory[kartNum].gaps[i] !== undefined) {
            lapData[`kart_${kartNum}`] = gapHistory[kartNum].gaps[i];
          }
          
          // Get adjusted gap if available
          if (gapHistory[kartNum].adjusted_gaps && gapHistory[kartNum].adjusted_gaps[i] !== undefined) {
            lapData[`kart_${kartNum}_adjusted`] = gapHistory[kartNum].adjusted_gaps[i];
          } else if (gapHistory[kartNum].gaps && gapHistory[kartNum].gaps[i] !== undefined) {
            // Fallback if adjusted gaps aren't available yet
            lapData[`kart_${kartNum}_adjusted`] = gapHistory[kartNum].gaps[i];
          }
          
          // Store team info
          if (team) {
            lapData[`kart_${kartNum}_team`] = team.Team || `Kart ${kartNum}`;
            lapData[`kart_${kartNum}_status`] = team.Status || 'On Track';
            lapData[`kart_${kartNum}_position`] = team.Position;
          }
        }
      });
      
      preparedData.push(lapData);
    }

    setChartData(preparedData);
  }, [gapHistory, teams, monitoredTeams, isDarkMode, generateColor]);

  // Custom tooltip component
  const CustomTooltip = ({ active, payload, label }) => {
    if (active && payload && payload.length) {
      // Get the actual lap number
      const dataIndex = label - 1;
      const absoluteLap = chartData[dataIndex]?.absoluteLap || label;
      
      // Filter payload to only include the current mode's data
      const filteredPayload = payload.filter(entry => {
        const dataKey = entry.dataKey;
        return gapMode === 'adjusted' 
          ? dataKey.includes('_adjusted')
          : !dataKey.includes('_adjusted');
      });
      
      // Sort data by gap value
      const sortedPayload = [...filteredPayload].sort((a, b) => a.value - b.value);
      
      return (
        <div className={`p-4 rounded-lg shadow-lg border max-w-xs ${isDarkMode ? 'bg-gray-800 border-gray-700' : 'bg-white border-gray-200'}`}>
          <div className="flex items-center space-x-2 mb-2">
            <div className={`w-8 h-8 rounded-full flex items-center justify-center ${isDarkMode ? 'bg-gray-700' : 'bg-gray-100'}`}>
              <span className="font-bold">{absoluteLap}</span>
            </div>
            <h3 className={`font-semibold ${isDarkMode ? 'text-gray-200' : 'text-gray-800'}`}>Lap {absoluteLap}</h3>
          </div>
          
          <div className="space-y-2 mt-2 max-h-60 overflow-y-auto">
            {sortedPayload.map(entry => {
              const kartNum = entry.dataKey.replace('kart_', '').replace('_adjusted', '');
              const teamName = chartData[dataIndex]?.[`kart_${kartNum}_team`] || `Kart ${kartNum}`;
              const gap = entry.value;
              const color = teamColors[kartNum] || entry.color;
              const status = chartData[dataIndex]?.[`kart_${kartNum}_status`];
              const position = chartData[dataIndex]?.[`kart_${kartNum}_position`];
              
              const team = teams.find(t => t.Kart === kartNum);
              const pitStops = team?.['Pit Stops'] || '0';
              
              return (
                <div key={entry.dataKey} className={`flex items-center p-2 rounded ${hoveredTeam === kartNum ? (isDarkMode ? 'bg-gray-700' : 'bg-gray-100') : ''}`}>
                  <div className="flex-shrink-0 mr-3">
                    <div className="w-3 h-10 rounded-sm" style={{ backgroundColor: color }}></div>
                  </div>
                  <div className="flex-grow">
                    <div className="flex items-center gap-2">
                      <div className={`text-xs font-medium text-center rounded px-1 ${isDarkMode ? 'bg-gray-700' : 'bg-gray-200'}`}>
                        P{position || '?'}
                      </div>
                      <div className={`font-medium truncate ${isDarkMode ? 'text-gray-200' : 'text-gray-800'}`}>
                        {teamName}
                      </div>
                    </div>
                    <div className="flex items-center mt-1">
                      <span className={`text-sm ${status === 'Pit-in' ? 'text-red-500 font-semibold' : (isDarkMode ? 'text-gray-400' : 'text-gray-600')}`}>
                        {status === 'Pit-in' ? '🔴 In Pits' : status || 'On Track'}
                      </span>
                      {gapMode === 'adjusted' && (
                        <span className="text-xs ml-2 px-1.5 py-0.5 rounded bg-blue-100 text-blue-800 dark:bg-blue-900 dark:text-blue-200">
                          {pitStops} Pit{parseInt(pitStops) !== 1 ? 's' : ''}
                        </span>
                      )}
                    </div>
                  </div>
                  <div className="flex-shrink-0 text-right">
                    <span 
                      className={`font-bold text-base ${gap < 0 ? 'text-green-500' : gap > 0 ? 'text-red-500' : 'text-blue-500'}`}
                    >
                      {gap.toFixed(3)}s
                    </span>
                    <div className="text-xs mt-1">
                      {gap < 0 ? '▼ Catching' : gap > 0 ? '▲ Falling back' : 'Same pace'}
                    </div>
                  </div>
                </div>
              );
            })}
          </div>
        </div>
      );
    }
    return null;
  };

  // Get min and max Y values for chart
  const { minGap, maxGap } = useMemo(() => {
    let min = 0;
    let max = 0;
    
    if (chartData.length > 0) {
      for (const lapData of chartData) {
        for (const kartNum of monitoredTeams) {
          const key = gapMode === 'adjusted' ? `kart_${kartNum}_adjusted` : `kart_${kartNum}`;
          if (lapData[key] !== undefined) {
            min = Math.min(min, lapData[key]);
            max = Math.max(max, lapData[key]);
          }
        }
      }
    }
    
    // Add buffer and ensure minimum range
    const buffer = Math.max(1, (max - min) * 0.2);
    min = Math.floor(min - buffer);
    max = Math.ceil(max + buffer);
    
    if (max - min < 2) {
      min -= 1;
      max += 1;
    }
    
    return { minGap: min, maxGap: max };
  }, [chartData, monitoredTeams, gapMode]);

  // Empty state when no teams are monitored
  if (!gapHistory || Object.keys(gapHistory).length === 0 || monitoredTeams.length === 0) {
    return (
      <div className={`rounded-lg shadow p-4 mb-4 transition-colors duration-300 ${isDarkMode ? 'bg-gray-800' : 'bg-white'}`}>
        <div className="flex items-center gap-2 mb-3">
          <svg className="w-5 h-5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
            <path d="M3 10h18M3 14h18m-9-4v8m-7 0h14a2 2 0 002-2V8a2 2 0 00-2-2H5a2 2 0 00-2 2v8a2 2 0 002 2z" />
          </svg>
          <h2 className="font-bold text-lg">Race Delta Analysis</h2>
        </div>
        <div className={`text-center py-12 rounded-lg border-2 border-dashed ${isDarkMode ? 'border-gray-700 text-gray-400' : 'border-gray-200 text-gray-500'}`}>
          <svg className="w-12 h-12 mx-auto mb-3 opacity-30" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M13 10V3L4 14h7v7l9-11h-7z" />
          </svg>
          <p className="text-lg font-medium">No data available</p>
          <p className="mt-2">Monitor teams to see the time delta chart</p>
          <button 
            className={`mt-4 px-4 py-2 rounded-md transition-colors ${isDarkMode ? 'bg-gray-700 hover:bg-gray-600 text-gray-200' : 'bg-gray-100 hover:bg-gray-200 text-gray-800'}`}
          >
            Monitor teams by clicking the star icon
          </button>
        </div>
      </div>
    );
  }

  return (
    <motion.div 
      initial={{ opacity: 0, y: 20 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.5 }}
      className={`rounded-lg shadow overflow-hidden transition-colors duration-300 ${isDarkMode ? 'bg-gray-800' : 'bg-white'}`}
    >
      <div className={`px-4 py-3 border-b ${isDarkMode ? 'border-gray-700 bg-gray-700' : 'border-gray-200 bg-gray-50'}`}>
        <div className="flex flex-col md:flex-row items-start md:items-center justify-between gap-2">
          <h2 className="font-bold text-lg flex items-center gap-2">
            <svg className="w-5 h-5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <path d="M3 10h18M3 14h18m-9-4v8m-7 0h14a2 2 0 002-2V8a2 2 0 00-2-2H5a2 2 0 00-2 2v8a2 2 0 002 2z" />
            </svg>
            Race Delta Analysis
          </h2>
          
          <div className="flex items-center gap-4">
            <ModeToggle 
              mode={gapMode} 
              setMode={setGapMode}
              isDarkMode={isDarkMode}
            />
            
            <div className={`text-xs rounded-md px-2 py-1 ${isDarkMode ? 'bg-blue-900 text-blue-100' : 'bg-blue-50 text-blue-800'}`}>
              <span>Showing last 15 laps</span>
            </div>
          </div>
        </div>
      </div>
      
      <div className="p-4">
        <div className="h-64 w-full">
          <ResponsiveContainer width="100%" height="100%" key={chartKey}>
            <ComposedChart
              data={chartData}
              margin={{ top: 5, right: 30, left: 10, bottom: 5 }}
              onMouseLeave={() => {
                setHoveredTeam(null);
                if (onTeamHover) onTeamHover(null);
              }}
            >
              <CartesianGrid 
                strokeDasharray="3 3" 
                stroke={isDarkMode ? '#374151' : '#e5e7eb'} 
                vertical={false}
              />
              <XAxis 
                dataKey="lap" 
                domain={[chartData[0]?.lap || 0, chartData[chartData.length-1]?.lap || 15]}
                label={{ 
                  value: 'Lap', 
                  position: 'insideBottomRight', 
                  offset: -5,
                  fill: isDarkMode ? '#9ca3af' : '#4b5563'
                }}
                tick={{ fill: isDarkMode ? '#9ca3af' : '#4b5563' }}
              />
              <YAxis 
                domain={[minGap, maxGap]}
                label={{ 
                  value: gapMode === 'adjusted' ? 'Adjusted Gap (s)' : 'Time Delta (s)', 
                  angle: -90, 
                  position: 'insideLeft',
                  style: { textAnchor: 'middle', fill: isDarkMode ? '#9ca3af' : '#4b5563' }
                }}
                tick={{ fill: isDarkMode ? '#9ca3af' : '#4b5563' }}
              />
              
              {/* Zero line represents your team's reference point */}
              <ReferenceLine 
                y={0} 
                stroke={isDarkMode ? '#d1d5db' : '#6b7280'} 
                strokeWidth={2}
                strokeDasharray="3 3"
              >
                <Label 
                  value="Your Team" 
                  position="right" 
                  fill={isDarkMode ? '#e5e7eb' : '#4b5563'}
                />
              </ReferenceLine>
              
              <Tooltip content={<CustomTooltip />} />
              
              <Legend 
                onMouseEnter={(e) => {
                  if (e.dataKey && typeof e.dataKey === 'string') {
                    // Remove the '_adjusted' suffix if present
                    const dataKey = e.dataKey.replace('_adjusted', '');
                    const kartNum = dataKey.replace('kart_', '');
                    setHoveredTeam(kartNum);
                    if (onTeamHover) onTeamHover(kartNum);
                  }
                }}
                onMouseLeave={() => {
                  setHoveredTeam(null);
                  if (onTeamHover) onTeamHover(null);
                }}
                formatter={(value) => {
                  if (typeof value === 'string') {
                    // Just return the kart number without team name and remove '_adjusted' suffix
                    return `Kart #${value.replace('kart_', '').replace('_adjusted', '')}`;
                  }
                  return value;
                }}
                iconType="circle"
                wrapperStyle={{ paddingTop: 10 }}
              />
              
              {monitoredTeams.map(kartNum => {
                const color = teamColors[kartNum];
                const isHighlighted = hoveredTeam === kartNum;
                const team = teams.find(t => t.Kart === kartNum);
                const isInPits = team?.Status === 'Pit-in';
                
                // Determine which data key to use based on mode
                const dataKey = gapMode === 'adjusted' ? `kart_${kartNum}_adjusted` : `kart_${kartNum}`;
                const displayName = `kart_${kartNum}${gapMode === 'adjusted' ? '_adjusted' : ''}`;
                
                if (isInPits) {
                  // For pit stops, render a special highlighted area
                  return (
                    <Area
                      key={dataKey}
                      type="monotone"
                      dataKey={dataKey}
                      name={displayName}
                      fill={`${color}30`} // Semi-transparent fill
                      stroke={color}
                      strokeWidth={isHighlighted ? 3 : 2}
                      strokeDasharray="5 2"
                      activeDot={{
                        r: 8,
                        fill: color,
                        stroke: isDarkMode ? '#1f2937' : '#ffffff'
                      }}
                    />
                  );
                }
                
                return (
                  <Line
                    key={dataKey}
                    type="monotone"
                    dataKey={dataKey}
                    name={displayName}
                    stroke={color}
                    strokeWidth={isHighlighted ? 3 : 2}
                    dot={{ 
                      r: isHighlighted ? 6 : 4,
                      strokeWidth: isHighlighted ? 2 : 1,
                      fill: isDarkMode ? '#1f2937' : '#ffffff',
                      stroke: color
                    }}
                    activeDot={{ 
                      r: 8, 
                      stroke: isDarkMode ? '#1f2937' : '#ffffff',
                      strokeWidth: 2,
                      fill: color
                    }}
                    connectNulls
                    animateNewValues
                    isAnimationActive={true}
                  />
                );
              })}
            </ComposedChart>
          </ResponsiveContainer>
        </div>
        
        <div className={`text-xs mt-3 flex flex-wrap justify-center gap-3 ${isDarkMode ? 'text-gray-400' : 'text-gray-500'}`}>
          <div className="flex items-center gap-2">
            <div className="flex items-center">
              <div className="h-px w-5 bg-gray-400"></div>
              <div className="h-3 w-3 rounded-full bg-gray-400"></div>
            </div>
            <span>Teams on track</span>
          </div>
          <div className="flex items-center gap-2">
            <div className="flex items-center">
              <div className="h-px w-5 bg-gray-400 dashed-line"></div>
              <div className="h-3 w-3 rounded-full bg-red-400"></div>
            </div>
            <span>Teams in pits</span>
          </div>
          <div className="flex items-center gap-2">
            <span className="text-green-500">▼</span>
            <span>Getting closer</span>
          </div>
          <div className="flex items-center gap-2">
            <span className="text-red-500">▲</span>
            <span>Falling behind</span>
          </div>
          {gapMode === 'adjusted' && (
            <div className="flex items-center gap-2 ml-4">
              <span className="px-1 py-0.5 text-xs rounded-full bg-blue-100 text-blue-800 dark:bg-blue-900 dark:text-blue-200">Pit time: 2:38</span>
            </div>
          )}
        </div>
      </div>
    </motion.div>
  );
};

export default TimeDeltaChart;
