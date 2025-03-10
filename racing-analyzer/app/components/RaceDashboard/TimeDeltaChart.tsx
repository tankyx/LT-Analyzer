// racing-analyzer/app/components/RaceDashboard/TimeDeltaChart.tsx
import React, { useEffect, useRef, useState } from 'react';

// Types
interface GapHistory {
  [kart: string]: {
    gaps: number[];
    last_update: string;
  };
}

interface Team {
  Kart: string;
  Team: string;
  Position: string;
  'Last Lap': string;
  'Best Lap': string;
  'Pit Stops': string;
  Gap: string;
  RunTime: string;
  Status?: string;
  lastPitCount?: number;
}

interface TimeDeltaChartProps {
  gapHistory: GapHistory;
  teams: Team[];
  monitoredTeams: string[];
  isDarkMode?: boolean; 
}

interface TooltipData {
  visible: boolean;
  x: number;
  y: number;
  kart: string;
  teamName: string;
  lap: number;
  gap: number;
}

const TimeDeltaChart: React.FC<TimeDeltaChartProps> = ({ 
  gapHistory, 
  teams, 
  monitoredTeams,
  isDarkMode = false
}) => {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const containerRef = useRef<HTMLDivElement>(null);
  const [tooltip, setTooltip] = useState<TooltipData>({
    visible: false,
    x: 0,
    y: 0,
    kart: '',
    teamName: '',
    lap: 0,
    gap: 0
  });
  const [chartData, setChartData] = useState<any[]>([]);
  const [teamColors, setTeamColors] = useState<Record<string, string>>({});
  const [highlightedKart, setHighlightedKart] = useState<string | null>(null);

  /**
   * Generates a color based on kart number to ensure consistent colors
   */
  const generateColor = (kartNumber: string): string => {
    // Simple hash function to generate consistent colors
    const hash = kartNumber.split('').reduce((acc, char) => {
      return char.charCodeAt(0) + ((acc << 5) - acc);
    }, 0);
    
    // Generate a hue from 0 to 360
    const hue = Math.abs(hash) % 360;
    
    // Use different saturation/lightness based on dark mode
    const saturation = isDarkMode ? '80%' : '70%';
    const lightness = isDarkMode ? '60%' : '45%';
    
    return `hsl(${hue}, ${saturation}, ${lightness})`;
  };

  // Prepare data and colors
  useEffect(() => {
    if (!gapHistory || Object.keys(gapHistory).length === 0) return;

    // Set team colors
    const colors: Record<string, string> = {};
    monitoredTeams.forEach(kart => {
      colors[kart] = generateColor(kart);
    });
    setTeamColors(colors);

    // Prepare chart data
    const preparedData: any[] = [];
    let maxLaps = 0;

    // Find max number of laps
    monitoredTeams.forEach(kartNum => {
      if (gapHistory[kartNum] && gapHistory[kartNum].gaps) {
        maxLaps = Math.max(maxLaps, gapHistory[kartNum].gaps.length);
      }
    });

    // Create data structure for each lap
    for (let i = 0; i < maxLaps; i++) {
      const lapData: any = { lap: i + 1 };
      
      monitoredTeams.forEach(kartNum => {
        if (gapHistory[kartNum] && gapHistory[kartNum].gaps && gapHistory[kartNum].gaps[i] !== undefined) {
          lapData[`kart_${kartNum}`] = gapHistory[kartNum].gaps[i];
          lapData[`kart_${kartNum}_team`] = teams.find(t => t.Kart === kartNum)?.Team || `Kart ${kartNum}`;
        }
      });
      
      preparedData.push(lapData);
    }

    setChartData(preparedData);
  }, [gapHistory, teams, monitoredTeams, isDarkMode]);

  // Handle mouse movement for tooltips
  const handleMouseMove = (e: React.MouseEvent<HTMLCanvasElement>) => {
    if (!canvasRef.current || chartData.length === 0) return;
    
    const canvas = canvasRef.current;
    const rect = canvas.getBoundingClientRect();
    const x = e.clientX - rect.left;
    const y = e.clientY - rect.top;
    
    // Chart dimensions and padding
    const width = canvas.width;
    const height = canvas.height;
    const padding = {
      top: 30,
      right: 30,
      bottom: 40,
      left: 60
    };
    
    const chartWidth = width - padding.left - padding.right;
    const chartHeight = height - padding.top - padding.bottom;
    
    // Find min and max values for y-axis scaling
    let minGap = 0;
    let maxGap = 0;
    
    monitoredTeams.forEach(kartNum => {
      if (gapHistory[kartNum] && gapHistory[kartNum].gaps) {
        const gaps = gapHistory[kartNum].gaps;
        const kartMin = Math.min(...gaps);
        const kartMax = Math.max(...gaps);
        
        if (kartMin < minGap) minGap = kartMin;
        if (kartMax > maxGap) maxGap = kartMax;
      }
    });
    
    // Add some buffer to min/max
    minGap = Math.floor(minGap - 1);
    maxGap = Math.ceil(maxGap + 1);
    
    // Make sure we have some range even if all values are the same
    if (minGap === maxGap) {
      minGap -= 1;
      maxGap += 1;
    }
    
    const maxLaps = chartData.length;
    
    // Check if mouse is in chart area
    if (x < padding.left || x > width - padding.right || 
        y < padding.top || y > height - padding.bottom) {
      setTooltip({ ...tooltip, visible: false });
      setHighlightedKart(null);
      return;
    }
    
    // Convert mouse position to data coordinates
    const xRatio = (x - padding.left) / chartWidth;
    const lapIndex = Math.floor(xRatio * maxLaps);
    
    if (lapIndex < 0 || lapIndex >= chartData.length) {
      setTooltip({ ...tooltip, visible: false });
      setHighlightedKart(null);
      return;
    }
    
    const lapData = chartData[lapIndex];
    
    // Find the closest data point to mouse position
    let closestDist = Infinity;
    let closestKart = '';
    let closestGap = 0;
    let closestTeam = '';
    
    monitoredTeams.forEach(kartNum => {
      const dataKey = `kart_${kartNum}`;
      if (lapData[dataKey] !== undefined) {
        const gap = lapData[dataKey];
        const yPos = padding.top + chartHeight - ((gap - minGap) / (maxGap - minGap) * chartHeight);
        const dist = Math.abs(y - yPos);
        
        if (dist < closestDist) {
          closestDist = dist;
          closestKart = kartNum;
          closestGap = gap;
          closestTeam = lapData[`${dataKey}_team`] || '';
        }
      }
    });
    
    if (closestKart && closestDist < 20) {
      const tooltipX = padding.left + (lapData.lap - 0.5) * (chartWidth / maxLaps);
      const tooltipY = padding.top + chartHeight - ((closestGap - minGap) / (maxGap - minGap) * chartHeight);
      
      setTooltip({
        visible: true,
        x: tooltipX,
        y: tooltipY,
        kart: closestKart,
        teamName: closestTeam,
        lap: lapData.lap,
        gap: closestGap
      });
      
      setHighlightedKart(closestKart);
    } else {
      setTooltip({ ...tooltip, visible: false });
      setHighlightedKart(null);
    }
  };

  const handleMouseLeave = () => {
    setTooltip({ ...tooltip, visible: false });
    setHighlightedKart(null);
  };

  // Draw the chart
  useEffect(() => {
    if (!canvasRef.current || chartData.length === 0) return;

    const canvas = canvasRef.current;
    const ctx = canvas.getContext('2d');
    if (!ctx) return;

    // Get canvas dimensions
    const width = canvas.width;
    const height = canvas.height;
    
    // Clear the canvas
    ctx.clearRect(0, 0, width, height);
    
    // Set up the chart area with some padding
    const padding = {
      top: 30,
      right: 30,
      bottom: 40,
      left: 60
    };
    
    const chartWidth = width - padding.left - padding.right;
    const chartHeight = height - padding.top - padding.bottom;
    
    // Find min and max values for y-axis scaling
    let minGap = 0;
    let maxGap = 0;
    
    monitoredTeams.forEach(kartNum => {
      if (gapHistory[kartNum] && gapHistory[kartNum].gaps) {
        const gaps = gapHistory[kartNum].gaps;
        const kartMin = Math.min(...gaps);
        const kartMax = Math.max(...gaps);
        
        if (kartMin < minGap) minGap = kartMin;
        if (kartMax > maxGap) maxGap = kartMax;
      }
    });
    
    // Add some buffer to min/max
    minGap = Math.floor(minGap - 1);
    maxGap = Math.ceil(maxGap + 1);
    
    // Make sure we have some range even if all values are the same
    if (minGap === maxGap) {
      minGap -= 1;
      maxGap += 1;
    }
    
    // Background color based on dark mode
    ctx.fillStyle = isDarkMode ? '#1f2937' : '#fcfcfc'; // Dark mode: gray-800, Light mode: almost white
    ctx.fillRect(0, 0, width, height);
    
    // Chart background
    ctx.fillStyle = isDarkMode ? '#111827' : '#f8f9fa'; // Dark mode: gray-900, Light mode: very light gray
    ctx.fillRect(padding.left, padding.top, chartWidth, chartHeight);
    
    // Chart border - subtle
    ctx.strokeStyle = isDarkMode ? '#374151' : '#e2e8f0'; // Dark mode: gray-700, Light mode: light gray
    ctx.lineWidth = 1;
    ctx.strokeRect(padding.left, padding.top, chartWidth, chartHeight);
    
    // Draw grid lines
    const ySteps = 5;
    const yStepSize = (maxGap - minGap) / ySteps;
    
    // Horizontal grid lines
    ctx.strokeStyle = isDarkMode ? '#374151' : '#e2e8f0'; // Dark mode: gray-700, Light mode: light gray
    ctx.beginPath();
    for (let i = 0; i <= ySteps; i++) {
      const y = padding.top + (i * chartHeight / ySteps);
      ctx.moveTo(padding.left, y);
      ctx.lineTo(padding.left + chartWidth, y);
    }
    ctx.stroke();
    
    // Vertical grid lines
    const xSteps = Math.min(10, chartData.length);
    const xStepSize = Math.ceil(chartData.length / xSteps);
    
    ctx.beginPath();
    for (let i = 1; i <= chartData.length; i++) {
      if (i % xStepSize !== 0 && i !== chartData.length) continue;
      const x = padding.left + (i * chartWidth / chartData.length);
      ctx.moveTo(x, padding.top);
      ctx.lineTo(x, padding.top + chartHeight);
    }
    ctx.stroke();
    
    // Draw axes
    ctx.strokeStyle = isDarkMode ? '#9ca3af' : '#64748b'; // Dark mode: gray-400, Light mode: gray-500
    ctx.lineWidth = 1.5;
    
    // Draw y-axis
    ctx.beginPath();
    ctx.moveTo(padding.left, padding.top);
    ctx.lineTo(padding.left, padding.top + chartHeight);
    ctx.stroke();
    
    // Draw x-axis
    ctx.beginPath();
    ctx.moveTo(padding.left, padding.top + chartHeight);
    ctx.lineTo(padding.left + chartWidth, padding.top + chartHeight);
    ctx.stroke();
    
    // Draw y-axis labels
    ctx.fillStyle = isDarkMode ? '#e5e7eb' : '#64748b'; // Dark mode: gray-200, Light mode: gray-500
    ctx.font = '12px Inter, system-ui, sans-serif';
    ctx.textAlign = 'right';
    ctx.textBaseline = 'middle';
    
    for (let i = 0; i <= ySteps; i++) {
      const value = maxGap - i * yStepSize;
      const y = padding.top + (i * chartHeight / ySteps);
      
      ctx.fillText(value.toFixed(1) + 's', padding.left - 8, y);
      
      // Axis ticks
      ctx.beginPath();
      ctx.moveTo(padding.left - 4, y);
      ctx.lineTo(padding.left, y);
      ctx.stroke();
    }
    
    // Draw x-axis labels
    ctx.textAlign = 'center';
    ctx.textBaseline = 'top';
    
    for (let i = 1; i <= chartData.length; i++) {
      if (i % xStepSize !== 0 && i !== chartData.length) continue;
      
      const x = padding.left + (i * chartWidth / chartData.length);
      
      ctx.fillText(i.toString(), x, padding.top + chartHeight + 8);
      
      // Axis ticks
      ctx.beginPath();
      ctx.moveTo(x, padding.top + chartHeight);
      ctx.lineTo(x, padding.top + chartHeight + 4);
      ctx.stroke();
    }
    
    // Add axis labels
    ctx.font = '14px Inter, system-ui, sans-serif';
    ctx.fillStyle = isDarkMode ? '#e5e7eb' : '#475569'; // Dark mode: gray-200, Light mode: gray-600
    ctx.textAlign = 'center';
    ctx.fillText('Lap', padding.left + chartWidth / 2, padding.top + chartHeight + 30);
    
    ctx.save();
    ctx.translate(padding.left - 40, padding.top + chartHeight / 2);
    ctx.rotate(-Math.PI / 2);
    ctx.textAlign = 'center';
    ctx.fillText('Delta (s)', 0, 0);
    ctx.restore();
    
    // Draw zero line (reference line for your team)
    const zeroY = padding.top + chartHeight * (maxGap / (maxGap - minGap));
    ctx.strokeStyle = isDarkMode ? '#6b7280' : '#f8fafc'; // Dark mode: gray-500, Light mode: light color
    ctx.lineWidth = 2;
    ctx.beginPath();
    ctx.moveTo(padding.left, zeroY);
    ctx.lineTo(padding.left + chartWidth, zeroY);
    ctx.stroke();
    
    // Add subtle drop shadow to the zero line
    ctx.strokeStyle = isDarkMode ? '#4b5563' : '#cbd5e1'; // Dark mode: gray-600, Light mode: light gray
    ctx.lineWidth = 1;
    ctx.beginPath();
    ctx.moveTo(padding.left, zeroY + 2);
    ctx.lineTo(padding.left + chartWidth, zeroY + 2);
    ctx.stroke();
    
    // Draw lines for each team (draw non-highlighted teams first)
    const drawTeam = (kartNum: string, isHighlighted: boolean) => {
      if (!gapHistory[kartNum] || !gapHistory[kartNum].gaps || gapHistory[kartNum].gaps.length === 0) return;
      
      const team = teams.find(t => t.Kart === kartNum);
      const color = teamColors[kartNum];
      const gaps = gapHistory[kartNum].gaps;
      
      // Line style based on highlight state
      ctx.strokeStyle = color;
      ctx.lineWidth = isHighlighted ? 4 : 2.5;
      ctx.lineCap = 'round';
      ctx.lineJoin = 'round';
      
      // Add line shadow for depth
      if (isHighlighted) {
        ctx.shadowColor = isDarkMode ? 'rgba(255, 255, 255, 0.3)' : 'rgba(0, 0, 0, 0.2)';
        ctx.shadowBlur = 6;
        ctx.shadowOffsetX = 0;
        ctx.shadowOffsetY = 0;
      } else {
        ctx.shadowColor = isDarkMode ? 'rgba(0, 0, 0, 0.3)' : 'rgba(0, 0, 0, 0.1)';
        ctx.shadowBlur = 3;
        ctx.shadowOffsetX = 1;
        ctx.shadowOffsetY = 1;
      }
      
      ctx.beginPath();
      
      gaps.forEach((gap, index) => {
        // Convert data points to canvas coordinates
        const x = padding.left + ((index + 0.5) * chartWidth / chartData.length);
        const y = padding.top + chartHeight - ((gap - minGap) / (maxGap - minGap) * chartHeight);
        
        if (index === 0) {
          ctx.moveTo(x, y);
        } else {
          ctx.lineTo(x, y);
        }
      });
      
      ctx.stroke();
      
      // Remove shadow for dots
      ctx.shadowColor = 'transparent';
      ctx.shadowBlur = 0;
      ctx.shadowOffsetX = 0;
      ctx.shadowOffsetY = 0;
      
      // Draw data points
      gaps.forEach((gap, index) => {
        const x = padding.left + ((index + 0.5) * chartWidth / chartData.length);
        const y = padding.top + chartHeight - ((gap - minGap) / (maxGap - minGap) * chartHeight);
        
        // Dot style based on highlight state
        const outerRadius = isHighlighted ? 5 : 4;
        const innerRadius = isHighlighted ? 2.5 : 2;
        
        // Draw dot with white center
        ctx.beginPath();
        ctx.arc(x, y, outerRadius, 0, Math.PI * 2);
        ctx.fillStyle = color;
        ctx.fill();
        
        ctx.beginPath();
        ctx.arc(x, y, innerRadius, 0, Math.PI * 2);
        ctx.fillStyle = isDarkMode ? '#1f2937' : 'white'; // Dark mode: dark gray, Light mode: white
        ctx.fill();
        
        // Highlight last point with larger dot
        if (index === gaps.length - 1) {
          ctx.beginPath();
          ctx.arc(x, y, isHighlighted ? 7 : 6, 0, Math.PI * 2);
          ctx.fillStyle = color;
          ctx.fill();
          
          ctx.beginPath();
          ctx.arc(x, y, isHighlighted ? 4 : 3, 0, Math.PI * 2);
          ctx.fillStyle = isDarkMode ? '#1f2937' : 'white'; // Dark mode: dark gray, Light mode: white
          ctx.fill();
        }
      });
    };
    
    // First draw non-highlighted teams
    monitoredTeams.forEach(kartNum => {
      if (kartNum !== highlightedKart) {
        drawTeam(kartNum, false);
      }
    });
    
    // Then draw highlighted team on top
    if (highlightedKart) {
      drawTeam(highlightedKart, true);
    }
    
    // Draw tooltip if visible
    if (tooltip.visible) {
      const tooltipWidth = 150;
      const tooltipHeight = 75;
      let tooltipX = tooltip.x + 10;
      
      // Keep tooltip within chart bounds
      if (tooltipX + tooltipWidth > width - padding.right) {
        tooltipX = tooltip.x - tooltipWidth - 10;
      }
      
      // Draw tooltip background with shadow
      ctx.shadowColor = isDarkMode ? 'rgba(0, 0, 0, 0.5)' : 'rgba(0, 0, 0, 0.2)';
      ctx.shadowBlur = 10;
      ctx.shadowOffsetX = 2;
      ctx.shadowOffsetY = 2;
      
      ctx.fillStyle = isDarkMode ? '#374151' : '#ffffff'; // Dark mode: gray-700, Light mode: white
      ctx.beginPath();
      ctx.roundRect(tooltipX, tooltip.y - tooltipHeight / 2, tooltipWidth, tooltipHeight, 8);
      ctx.fill();
      
      // Remove shadow
      ctx.shadowColor = 'transparent';
      ctx.shadowBlur = 0;
      ctx.shadowOffsetX = 0;
      ctx.shadowOffsetY = 0;
      
      // Draw tooltip border
      ctx.strokeStyle = isDarkMode ? '#4b5563' : '#e2e8f0'; // Dark mode: gray-600, Light mode: light gray
      ctx.lineWidth = 1;
      ctx.beginPath();
      ctx.roundRect(tooltipX, tooltip.y - tooltipHeight / 2, tooltipWidth, tooltipHeight, 8);
      ctx.stroke();
      
      // Draw team color indicator
      const teamColor = teamColors[tooltip.kart];
      ctx.fillStyle = teamColor;
      ctx.beginPath();
      ctx.roundRect(tooltipX + 8, tooltip.y - tooltipHeight / 2 + 8, 4, 25, 2);
      ctx.fill();
      
      // Draw tooltip content
      ctx.fillStyle = isDarkMode ? '#f3f4f6' : '#0f172a'; // Dark mode: gray-100, Light mode: almost black
      ctx.font = 'bold 12px Inter, system-ui, sans-serif';
      ctx.textAlign = 'left';
      ctx.textBaseline = 'top';
      ctx.fillText(tooltip.teamName, tooltipX + 18, tooltip.y - tooltipHeight / 2 + 8);
      
      ctx.font = '12px Inter, system-ui, sans-serif';
      ctx.fillStyle = isDarkMode ? '#d1d5db' : '#374151'; // Dark mode: gray-300, Light mode: gray-700
      ctx.fillText(`Kart #${tooltip.kart}`, tooltipX + 18, tooltip.y - tooltipHeight / 2 + 28);
      ctx.fillText(`Lap: ${tooltip.lap}`, tooltipX + 18, tooltip.y - tooltipHeight / 2 + 44);
      
      const gapText = `Gap: ${tooltip.gap.toFixed(3)}s`;
      ctx.fillStyle = tooltip.gap >= 0 ? 
        (isDarkMode ? '#ef4444' : '#dc2626') : // Red: dark mode vs light mode
        (isDarkMode ? '#22c55e' : '#16a34a');  // Green: dark mode vs light mode
      ctx.fillText(gapText, tooltipX + 18, tooltip.y - tooltipHeight / 2 + 60);
    }
    
    // Add legend
    const legendY = padding.top - 20;
    let legendX = padding.left;
    
    monitoredTeams.forEach(kartNum => {
      const team = teams.find(t => t.Kart === kartNum);
      if (!team) return;
      
      const teamName = team.Team;
      const shortName = teamName.length > 15 ? teamName.substring(0, 12) + '...' : teamName;
      const color = teamColors[kartNum];
      
      // Legend item container with highlight effect
      const isHighlighted = kartNum === highlightedKart;
      
      if (isHighlighted) {
        // Draw highlight background for legend item
        ctx.fillStyle = isDarkMode ? 'rgba(255, 255, 255, 0.1)' : 'rgba(0, 0, 0, 0.05)';
        const textWidth = ctx.measureText(`${shortName} (#${kartNum})`).width;
        ctx.beginPath();
        ctx.roundRect(legendX - 4, legendY - 6, textWidth + 28, 12, 4);
        ctx.fill();
      }
      
      // Draw color box
      ctx.fillStyle = color;
      ctx.fillRect(legendX, legendY, 12, 6);
      
      // Draw team name
      ctx.fillStyle = isDarkMode ? '#e5e7eb' : '#475569'; // Dark mode: gray-200, Light mode: gray-600
      ctx.font = isHighlighted ? 'bold 11px Inter, system-ui, sans-serif' : '11px Inter, system-ui, sans-serif';
      ctx.textAlign = 'left';
      ctx.textBaseline = 'middle';
      ctx.fillText(`${shortName} (#${kartNum})`, legendX + 16, legendY + 3);
      
      // Move to next legend item
      legendX += ctx.measureText(`${shortName} (#${kartNum})`).width + 30;
    });
    
  }, [chartData, gapHistory, teams, monitoredTeams, teamColors, tooltip, highlightedKart, isDarkMode]);

  // Handle window resize to make the chart responsive
  useEffect(() => {
    const handleResize = () => {
      if (canvasRef.current && containerRef.current) {
        const container = containerRef.current;
        const canvas = canvasRef.current;
        
        // Set canvas dimensions based on container size with proper resolution
        const devicePixelRatio = window.devicePixelRatio || 1;
        canvas.width = container.clientWidth * devicePixelRatio;
        canvas.height = Math.min(300, container.clientHeight) * devicePixelRatio;
        
        // Adjust CSS dimensions
        canvas.style.width = `${container.clientWidth}px`;
        canvas.style.height = `${Math.min(300, container.clientHeight)}px`;
        
        // Scale canvas context to counter devicePixelRatio
        const ctx = canvas.getContext('2d');
        if (ctx) {
          ctx.scale(devicePixelRatio, devicePixelRatio);
        }
      }
    };
    
    window.addEventListener('resize', handleResize);
    handleResize(); // Initial resize
    
    return () => {
      window.removeEventListener('resize', handleResize);
    };
  }, []);

  if (!gapHistory || Object.keys(gapHistory).length === 0 || monitoredTeams.length === 0) {
    return (
      <div className={`rounded-lg shadow p-4 mb-4 transition-colors duration-300 ${isDarkMode ? 'bg-gray-800' : 'bg-white'}`}>
        <div className="flex items-center gap-2 mb-3">
          <svg className="w-5 h-5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
            <path d="M3 10h18M3 14h18m-9-4v8m-7 0h14a2 2 0 002-2V8a2 2 0 00-2-2H5a2 2 0 00-2 2v8a2 2 0 002 2z" />
          </svg>
          <h2 className="font-bold text-lg">Time Delta Chart</h2>
        </div>
        <div className={`text-center py-12 rounded-lg border-2 border-dashed ${isDarkMode ? 'border-gray-700 text-gray-400' : 'border-gray-200 text-gray-500'}`}>
          <svg className="w-12 h-12 mx-auto mb-3 opacity-30" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M13 10V3L4 14h7v7l9-11h-7z" />
          </svg>
          <p className="text-lg font-medium">No data available</p>
          <p className="mt-2">Monitor teams to see the time delta chart</p>
          <button 
            onClick={() => {}} // This would be connected to a "show me how" function
            className={`mt-4 px-4 py-2 rounded-md transition-colors ${isDarkMode ? 'bg-gray-700 hover:bg-gray-600 text-gray-200' : 'bg-gray-100 hover:bg-gray-200 text-gray-800'}`}
          >
            Monitor teams by clicking the star icon
          </button>
        </div>
      </div>
    );
  }

  return (
    <div className={`rounded-lg shadow overflow-hidden transition-colors duration-300 ${isDarkMode ? 'bg-gray-800' : 'bg-white'}`}>
      <div className={`px-4 py-3 border-b ${isDarkMode ? 'border-gray-700 bg-gray-700' : 'border-gray-200 bg-gray-50'}`}>
        <h2 className="font-bold text-lg flex items-center gap-2">
          <svg className="w-5 h-5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
            <path d="M3 10h18M3 14h18m-9-4v8m-7 0h14a2 2 0 002-2V8a2 2 0 00-2-2H5a2 2 0 00-2 2v8a2 2 0 002 2z" />
          </svg>
          Time Delta Chart
        </h2>
      </div>
      
      <div className="p-4">
        <div className="h-64 w-full" ref={containerRef}>
          <canvas 
            ref={canvasRef} 
            className="w-full h-full cursor-crosshair"
            onMouseMove={handleMouseMove}
            onMouseLeave={handleMouseLeave}
          />
        </div>
        <div className={`text-xs mt-2 text-center ${isDarkMode ? 'text-gray-400' : 'text-gray-500'}`}>
          <div className="flex items-center justify-center gap-1">
            <div className={`h-px w-8 ${isDarkMode ? 'bg-gray-500' : 'bg-gray-400'}`}></div>
            <span>Lines show time delta compared to your team (horizontal line at 0s)</span>
            <div className={`h-px w-8 ${isDarkMode ? 'bg-gray-500' : 'bg-gray-400'}`}></div>
          </div>
          <div className="mt-1 flex justify-center items-center gap-4">
            <div className="flex items-center gap-1">
              <span className="text-green-500">↓</span>
              <span>Getting closer</span>
            </div>
            <div className="flex items-center gap-1">
              <span className="text-red-500">↑</span>
              <span>Falling behind</span>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
};

export default TimeDeltaChart;
