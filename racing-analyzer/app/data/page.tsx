'use client';

import { useState, useEffect } from 'react';
import { useRouter } from 'next/navigation';
import { useAuth } from '../contexts/AuthContext';
import ApiService from '../services/ApiService';
import { LineChart, Line, BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, Legend, ResponsiveContainer } from 'recharts';

interface Team {
  name: string;
  classes: string;
}

interface Session {
  session_id: number;
  start_time: string;
  name: string;
  lap_records: number;
  best_lap: string;
}

interface TeamStats {
  team_name: string;
  total_records: number;
  best_lap_time: string;
  sessions_participated: number;
  classes_raced: string[];
  max_pit_stops: number;
  total_laps_completed: number;
  avg_lap_seconds: number;
  total_pit_stops: number;
  sessions: Session[];
}

interface TeamComparison {
  team_name: string;
  total_records: number;
  best_lap_time: string;
  sessions_participated: number;
  classes_raced: string[];
  total_laps_completed: number;
  avg_lap_seconds: number;
  lap_times: number[];
}

interface CommonSession {
  session_id: number;
  start_time: string;
  name: string;
  track: string;
  teams_present: number;
}

interface LapDetail {
  lap_number: number;
  lap_time: number;
  pit_stop: boolean;
}

interface LapDetailsData {
  [teamName: string]: LapDetail[];
}

interface Stint {
  stint_number: number;
  start_lap: number;
  end_lap: number;
  lap_count: number;
}

interface TeamStints {
  team_name: string;
  stints: Stint[];
}

interface Track {
  id: number;
  track_name: string;
  timing_url: string;
  websocket_url: string;
}

export default function DataPage() {
  const { user, loading } = useAuth();
  const router = useRouter();

  const [tracks, setTracks] = useState<Track[]>([]);
  const [selectedTrackId, setSelectedTrackId] = useState<number>(1);
  const [searchQuery, setSearchQuery] = useState('');
  const [searchResults, setSearchResults] = useState<Team[]>([]);
  const [searching, setSearching] = useState(false);
  const [selectedTeams, setSelectedTeams] = useState<string[]>([]);
  const [teamStats, setTeamStats] = useState<{ [key: string]: TeamStats }>({});
  const [comparisonData, setComparisonData] = useState<TeamComparison[]>([]);
  const [loadingStats, setLoadingStats] = useState(false);
  const [commonSessions, setCommonSessions] = useState<CommonSession[]>([]);
  const [selectedSession, setSelectedSession] = useState<number | null>(null);
  const [lapDetails, setLapDetails] = useState<LapDetailsData>({});
  const [stintStart, setStintStart] = useState<number>(1);
  const [stintEnd, setStintEnd] = useState<number>(50);
  const [teamStints, setTeamStints] = useState<TeamStints[]>([]);
  const [selectedStint, setSelectedStint] = useState<string>('');

  useEffect(() => {
    if (!loading && !user) {
      router.push('/login');
    }
  }, [user, loading, router]);

  // Load tracks on mount
  useEffect(() => {
    const loadTracks = async () => {
      try {
        const result = await ApiService.getTracks();
        setTracks(result.tracks || []);
      } catch (error) {
        console.error('Error loading tracks:', error);
      }
    };
    loadTracks();
  }, []);

  // Reset selections when track changes
  useEffect(() => {
    setSelectedTeams([]);
    setTeamStats({});
    setComparisonData([]);
    setCommonSessions([]);
    setSelectedSession(null);
    setLapDetails({});
    setTeamStints([]);
    setSearchQuery('');
    setSearchResults([]);
  }, [selectedTrackId]);

  // Search teams with debounce
  useEffect(() => {
    const timer = setTimeout(async () => {
      if (searchQuery.trim().length >= 2) {
        setSearching(true);
        try {
          const result = await ApiService.searchTeams(searchQuery, selectedTrackId);
          setSearchResults(result.teams || []);
        } catch (error) {
          console.error('Error searching teams:', error);
          setSearchResults([]);
        } finally {
          setSearching(false);
        }
      } else {
        setSearchResults([]);
      }
    }, 300);

    return () => clearTimeout(timer);
  }, [searchQuery, selectedTrackId]);

  // Fetch common sessions when teams change
  useEffect(() => {
    const fetchCommonSessions = async () => {
      if (selectedTeams.length >= 1) {
        try {
          const result = await ApiService.getCommonSessions(selectedTeams, selectedTrackId);
          setCommonSessions(result.sessions || []);
          // Auto-select most recent session
          if (result.sessions && result.sessions.length > 0) {
            setSelectedSession(result.sessions[0].session_id);
          } else {
            setSelectedSession(null);
          }
        } catch (error) {
          console.error('Error fetching common sessions:', error);
          setCommonSessions([]);
          setSelectedSession(null);
        }
      } else {
        setCommonSessions([]);
        setSelectedSession(null);
      }
    };

    fetchCommonSessions();
  }, [selectedTeams, selectedTrackId]);

  // Refetch stats when session changes
  useEffect(() => {
    const refetchStats = async () => {
      if (selectedTeams.length === 0) return;

      setLoadingStats(true);
      try {
        // Refetch individual team stats
        const statsPromises = selectedTeams.map(team =>
          ApiService.getTeamStats(team, selectedSession || undefined, selectedTrackId)
        );
        const statsResults = await Promise.all(statsPromises);

        const newTeamStats: { [key: string]: TeamStats } = {};
        selectedTeams.forEach((team, idx) => {
          newTeamStats[team] = statsResults[idx];
        });
        setTeamStats(newTeamStats);

        // Refetch comparison data if applicable
        if (selectedTeams.length >= 2) {
          const comparison = await ApiService.compareTeams(selectedTeams, selectedSession || undefined, selectedTrackId);
          setComparisonData(comparison.comparison || []);
        }
      } catch (error) {
        console.error('Error refetching stats:', error);
      } finally {
        setLoadingStats(false);
      }
    };

    refetchStats();
  }, [selectedSession]);

  const addTeamToComparison = async (teamName: string) => {
    if (selectedTeams.includes(teamName)) {
      return;
    }

    const newSelectedTeams = [...selectedTeams, teamName];
    setSelectedTeams(newSelectedTeams);

    // Fetch team stats
    setLoadingStats(true);
    try {
      const stats = await ApiService.getTeamStats(teamName, selectedSession || undefined, selectedTrackId);
      setTeamStats(prev => ({ ...prev, [teamName]: stats }));

      // If we have 2+ teams, fetch comparison data
      if (newSelectedTeams.length >= 2) {
        const comparison = await ApiService.compareTeams(newSelectedTeams, selectedSession || undefined, selectedTrackId);
        setComparisonData(comparison.comparison || []);
      }
    } catch (error) {
      console.error('Error fetching team stats:', error);
    } finally {
      setLoadingStats(false);
    }
  };

  const removeTeamFromComparison = async (teamName: string) => {
    const newSelectedTeams = selectedTeams.filter(t => t !== teamName);
    setSelectedTeams(newSelectedTeams);

    // Remove from team stats
    const newTeamStats = { ...teamStats };
    delete newTeamStats[teamName];
    setTeamStats(newTeamStats);

    // Update comparison
    if (newSelectedTeams.length >= 2) {
      try {
        const comparison = await ApiService.compareTeams(newSelectedTeams, selectedSession || undefined, selectedTrackId);
        setComparisonData(comparison.comparison || []);
      } catch (error) {
        console.error('Error fetching comparison:', error);
      }
    } else {
      setComparisonData([]);
    }
  };

  // Fetch detailed lap data when session and teams change
  useEffect(() => {
    const fetchLapDetails = async () => {
      if (selectedTeams.length >= 2 && selectedSession) {
        try {
          const result = await ApiService.getLapDetails(selectedTeams, selectedSession, selectedTrackId);
          setLapDetails(result.lap_details || {});
          setTeamStints(result.stints || []);

          // Auto-set to first stint if available
          if (result.stints && result.stints.length > 0 && result.stints[0].stints.length > 0) {
            const firstTeam = result.stints[0];
            const firstStint = firstTeam.stints[0];
            setStintStart(firstStint.start_lap);
            setStintEnd(firstStint.end_lap);
            setSelectedStint(`${firstTeam.team_name}-${firstStint.stint_number}`);
          } else if (result.lap_details) {
            // Fallback: Auto-set stint range based on available data
            const allLaps = Object.values(result.lap_details).flat() as LapDetail[];
            if (allLaps.length > 0) {
              const minLap = Math.min(...allLaps.map(l => l.lap_number));
              const maxLap = Math.max(...allLaps.map(l => l.lap_number));
              setStintStart(minLap);
              setStintEnd(Math.min(minLap + 49, maxLap));
            }
          }
        } catch (error) {
          console.error('Error fetching lap details:', error);
        }
      } else {
        setLapDetails({});
        setTeamStints([]);
        setSelectedStint('');
      }
    };

    fetchLapDetails();
  }, [selectedTeams, selectedSession, selectedTrackId]);

  // Handle stint selection
  const handleStintSelection = (stintKey: string) => {
    setSelectedStint(stintKey);
    if (stintKey === '') {
      // Reset to full range
      const allLaps = Object.values(lapDetails).flat() as LapDetail[];
      if (allLaps.length > 0) {
        const minLap = Math.min(...allLaps.map(l => l.lap_number));
        const maxLap = Math.max(...allLaps.map(l => l.lap_number));
        setStintStart(minLap);
        setStintEnd(Math.min(minLap + 49, maxLap));
      }
    } else {
      // Parse the stint key (format: "teamname-stintnumber")
      const [teamName, stintNumberStr] = stintKey.split('-');
      const stintNumber = parseInt(stintNumberStr);

      const teamStint = teamStints.find(ts => ts.team_name === teamName);
      if (teamStint) {
        const stint = teamStint.stints.find(s => s.stint_number === stintNumber);
        if (stint) {
          setStintStart(stint.start_lap);
          setStintEnd(stint.end_lap);
        }
      }
    }
  };

  // Calculate moving average
  const calculateMovingAverage = (data: LapDetail[], window: number = 10): { lap_number: number; avg: number }[] => {
    if (data.length < window) return [];

    const result = [];
    for (let i = window - 1; i < data.length; i++) {
      const windowData = data.slice(i - window + 1, i + 1);
      const avg = windowData.reduce((sum, lap) => sum + lap.lap_time, 0) / window;
      result.push({
        lap_number: data[i].lap_number,
        avg: avg
      });
    }
    return result;
  };

  const formatLapTime = (seconds: number | null) => {
    if (!seconds) return 'N/A';
    const mins = Math.floor(seconds / 60);
    const secs = (seconds % 60).toFixed(3);
    return `${mins}:${secs.padStart(6, '0')}`;
  };

  if (loading) {
    return (
      <div className="flex items-center justify-center min-h-screen bg-gray-900">
        <div className="text-white">Loading...</div>
      </div>
    );
  }

  if (!user) {
    return null;
  }

  return (
    <div className="min-h-screen bg-gray-900 p-6">
      <div className="max-w-7xl mx-auto">
        <h1 className="text-3xl font-bold text-white mb-6">Team Data Analysis</h1>

        {/* Track Selector */}
        <div className="bg-gray-800 rounded-lg p-6 mb-6">
          <h2 className="text-xl font-semibold text-white mb-4">Select Track</h2>
          <select
            value={selectedTrackId}
            onChange={(e) => setSelectedTrackId(parseInt(e.target.value))}
            className="w-full px-4 py-2 bg-gray-700 text-white rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500"
          >
            {tracks.map((track) => (
              <option key={track.id} value={track.id}>
                {track.track_name}
              </option>
            ))}
          </select>
        </div>

        {/* Search Section */}
        <div className="bg-gray-800 rounded-lg p-6 mb-6">
          <h2 className="text-xl font-semibold text-white mb-4">Search Teams</h2>
          <div className="relative">
            <input
              type="text"
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              placeholder="Search for a team name..."
              className="w-full px-4 py-2 bg-gray-700 text-white rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500"
            />
            {searching && (
              <div className="absolute right-3 top-2.5 text-gray-400">Searching...</div>
            )}
          </div>

          {/* Search Results */}
          {searchResults.length > 0 && (
            <div className="mt-4 bg-gray-700 rounded-lg max-h-60 overflow-y-auto">
              {searchResults.map((team) => (
                <div
                  key={team.name}
                  onClick={() => addTeamToComparison(team.name)}
                  className="px-4 py-2 hover:bg-gray-600 cursor-pointer flex justify-between items-center border-b border-gray-600 last:border-b-0"
                >
                  <span className="text-white">{team.name}</span>
                  <span className="text-sm text-gray-400">Classes: {team.classes}</span>
                </div>
              ))}
            </div>
          )}
        </div>

        {/* Selected Teams */}
        {selectedTeams.length > 0 && (
          <div className="bg-gray-800 rounded-lg p-6 mb-6">
            <h2 className="text-xl font-semibold text-white mb-4">
              Selected Teams ({selectedTeams.length})
            </h2>
            <div className="flex flex-wrap gap-2">
              {selectedTeams.map((team) => (
                <div
                  key={team}
                  className="bg-blue-600 text-white px-4 py-2 rounded-lg flex items-center gap-2"
                >
                  <span>{team}</span>
                  <button
                    onClick={() => removeTeamFromComparison(team)}
                    className="text-white hover:text-red-300"
                  >
                    ✕
                  </button>
                </div>
              ))}
            </div>
          </div>
        )}

        {/* Session Selector */}
        {commonSessions.length > 0 && (
          <div className="bg-gray-800 rounded-lg p-6 mb-6">
            <h2 className="text-xl font-semibold text-white mb-4">
              Select Session (showing only sessions where all teams participated)
            </h2>
            <select
              value={selectedSession || ''}
              onChange={(e) => setSelectedSession(e.target.value ? parseInt(e.target.value) : null)}
              className="w-full px-4 py-2 bg-gray-700 text-white rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500"
            >
              <option value="">All Sessions</option>
              {commonSessions.map((session) => (
                <option key={session.session_id} value={session.session_id}>
                  {new Date(session.start_time).toLocaleDateString()} - {session.name} (Session {session.session_id})
                </option>
              ))}
            </select>
            {selectedSession && (
              <div className="mt-2 text-sm text-gray-400">
                {commonSessions.find(s => s.session_id === selectedSession)?.start_time &&
                  `Date: ${new Date(commonSessions.find(s => s.session_id === selectedSession)!.start_time).toLocaleString()}`
                }
              </div>
            )}
          </div>
        )}

        {/* Individual Team Stats */}
        {selectedTeams.length > 0 && (
          <div className="grid grid-cols-1 md:grid-cols-2 gap-6 mb-6">
            {selectedTeams.map((teamName) => {
              const stats = teamStats[teamName];
              if (!stats) return null;

              return (
                <div key={teamName} className="bg-gray-800 rounded-lg p-6">
                  <h3 className="text-lg font-semibold text-white mb-4 capitalize">{teamName}</h3>
                  <div className="grid grid-cols-2 gap-4 text-sm">
                    <div>
                      <p className="text-gray-400">Best Lap Time</p>
                      <p className="text-white font-semibold">{stats.best_lap_time || 'N/A'}</p>
                    </div>
                    <div>
                      <p className="text-gray-400">Avg Lap Time</p>
                      <p className="text-white font-semibold">
                        {stats.avg_lap_seconds ? formatLapTime(stats.avg_lap_seconds) : 'N/A'}
                      </p>
                    </div>
                    <div>
                      <p className="text-gray-400">Total Laps</p>
                      <p className="text-white font-semibold">{stats.total_laps_completed}</p>
                    </div>
                    <div>
                      <p className="text-gray-400">Sessions</p>
                      <p className="text-white font-semibold">{stats.sessions_participated}</p>
                    </div>
                    <div>
                      <p className="text-gray-400">Total Pit Stops</p>
                      <p className="text-white font-semibold">{stats.total_pit_stops}</p>
                    </div>
                    <div>
                      <p className="text-gray-400">Classes</p>
                      <p className="text-white font-semibold">{stats.classes_raced.join(', ')}</p>
                    </div>
                  </div>
                </div>
              );
            })}
          </div>
        )}

        {/* Comparison Charts */}
        {comparisonData.length >= 2 && (
          <div className="space-y-6">
            {/* Best Lap Time Comparison */}
            <div className="bg-gray-800 rounded-lg p-6">
              <h2 className="text-xl font-semibold text-white mb-4">Best Lap Time Comparison</h2>
              <ResponsiveContainer width="100%" height={300}>
                <BarChart data={comparisonData}>
                  <CartesianGrid strokeDasharray="3 3" stroke="#374151" />
                  <XAxis dataKey="team_name" stroke="#9CA3AF" />
                  <YAxis stroke="#9CA3AF" />
                  <Tooltip
                    contentStyle={{ backgroundColor: '#1F2937', border: 'none' }}
                    labelStyle={{ color: '#fff' }}
                  />
                  <Legend />
                  <Bar dataKey="best_lap_time" fill="#3B82F6" name="Best Lap Time" />
                </BarChart>
              </ResponsiveContainer>
            </div>

            {/* Average Lap Time Comparison */}
            <div className="bg-gray-800 rounded-lg p-6">
              <h2 className="text-xl font-semibold text-white mb-4">Average Lap Time Comparison</h2>
              <ResponsiveContainer width="100%" height={300}>
                <BarChart data={comparisonData}>
                  <CartesianGrid strokeDasharray="3 3" stroke="#374151" />
                  <XAxis dataKey="team_name" stroke="#9CA3AF" />
                  <YAxis stroke="#9CA3AF" />
                  <Tooltip
                    contentStyle={{ backgroundColor: '#1F2937', border: 'none' }}
                    labelStyle={{ color: '#fff' }}
                  />
                  <Legend />
                  <Bar dataKey="avg_lap_seconds" fill="#10B981" name="Avg Lap Time (s)" />
                </BarChart>
              </ResponsiveContainer>
            </div>

            {/* Lap Times Comparison with Stint Selector */}
            {Object.keys(lapDetails).length > 0 && selectedSession && (
              <>
                {/* Stint Selector */}
                <div className="bg-gray-800 rounded-lg p-6">
                  <h2 className="text-xl font-semibold text-white mb-4">Select Stint or Lap Range</h2>

                  {/* Stint Dropdown */}
                  {teamStints.length > 0 && (
                    <div className="mb-4">
                      <label className="text-gray-400 text-sm mb-2 block">Quick Select Stint</label>
                      <select
                        value={selectedStint}
                        onChange={(e) => handleStintSelection(e.target.value)}
                        className="w-full px-4 py-2 bg-gray-700 text-white rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500"
                      >
                        <option value="">Custom Range</option>
                        {teamStints.map((teamStint) =>
                          teamStint.stints.map((stint) => (
                            <option
                              key={`${teamStint.team_name}-${stint.stint_number}`}
                              value={`${teamStint.team_name}-${stint.stint_number}`}
                            >
                              {teamStint.team_name} - Stint {stint.stint_number} (Laps {stint.start_lap}-{stint.end_lap}, {stint.lap_count} laps)
                            </option>
                          ))
                        )}
                      </select>
                    </div>
                  )}

                  {/* Manual Lap Range */}
                  <div className="grid grid-cols-2 gap-4">
                    <div>
                      <label className="text-gray-400 text-sm mb-2 block">Start Lap</label>
                      <input
                        type="number"
                        value={stintStart}
                        onChange={(e) => {
                          setStintStart(parseInt(e.target.value) || 1);
                          setSelectedStint(''); // Clear stint selection when manually changing
                        }}
                        className="w-full px-4 py-2 bg-gray-700 text-white rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500"
                        min={1}
                      />
                    </div>
                    <div>
                      <label className="text-gray-400 text-sm mb-2 block">End Lap</label>
                      <input
                        type="number"
                        value={stintEnd}
                        onChange={(e) => {
                          setStintEnd(parseInt(e.target.value) || 50);
                          setSelectedStint(''); // Clear stint selection when manually changing
                        }}
                        className="w-full px-4 py-2 bg-gray-700 text-white rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500"
                        min={stintStart}
                      />
                    </div>
                  </div>
                  <div className="mt-3 text-sm text-gray-400">
                    Showing {stintEnd - stintStart + 1} laps (Lap {stintStart} to {stintEnd})
                  </div>
                </div>

                {/* Selected Stint Lap Times */}
                <div className="bg-gray-800 rounded-lg p-6">
                  <h2 className="text-xl font-semibold text-white mb-4">
                    Lap Times Comparison (Laps {stintStart}-{stintEnd})
                  </h2>
                  <ResponsiveContainer width="100%" height={400}>
                    <LineChart>
                      <CartesianGrid strokeDasharray="3 3" stroke="#374151" />
                      <XAxis
                        dataKey="lap_number"
                        type="number"
                        domain={[stintStart, stintEnd]}
                        stroke="#9CA3AF"
                        label={{ value: 'Lap Number', position: 'insideBottom', offset: -5 }}
                      />
                      <YAxis
                        stroke="#9CA3AF"
                        domain={['dataMin - 2', 'dataMax + 2']}
                        label={{ value: 'Lap Time (seconds)', angle: -90, position: 'insideLeft' }}
                      />
                      <Tooltip
                        contentStyle={{ backgroundColor: '#1F2937', border: 'none' }}
                        labelStyle={{ color: '#fff' }}
                        formatter={(value: number) => [`${value.toFixed(3)}s`, 'Lap Time']}
                      />
                      <Legend />
                      {Object.entries(lapDetails).map(([teamName, laps], idx) => {
                        const colors = ['#3B82F6', '#10B981', '#F59E0B', '#EF4444', '#8B5CF6'];
                        const filteredLaps = laps.filter(
                          lap => lap.lap_number >= stintStart && lap.lap_number <= stintEnd
                        );

                        return (
                          <Line
                            key={teamName}
                            data={filteredLaps}
                            type="monotone"
                            dataKey="lap_time"
                            stroke={colors[idx % colors.length]}
                            name={teamName}
                            strokeWidth={2}
                            dot={{ r: 3 }}
                            connectNulls
                          />
                        );
                      })}
                    </LineChart>
                  </ResponsiveContainer>
                </div>

                {/* Full Race with 10-Lap Moving Average */}
                <div className="bg-gray-800 rounded-lg p-6">
                  <h2 className="text-xl font-semibold text-white mb-4">
                    Full Race Pace (10-Lap Rolling Average)
                  </h2>
                  <ResponsiveContainer width="100%" height={500}>
                    <LineChart>
                      <CartesianGrid strokeDasharray="3 3" stroke="#374151" />
                      <XAxis
                        dataKey="lap_number"
                        type="number"
                        stroke="#9CA3AF"
                        label={{ value: 'Lap Number', position: 'insideBottom', offset: -5 }}
                      />
                      <YAxis
                        stroke="#9CA3AF"
                        domain={['dataMin - 1', 'dataMax + 1']}
                        label={{ value: 'Average Lap Time (seconds)', angle: -90, position: 'insideLeft' }}
                      />
                      <Tooltip
                        contentStyle={{ backgroundColor: '#1F2937', border: 'none' }}
                        labelStyle={{ color: '#fff' }}
                        formatter={(value: number) => [`${value.toFixed(3)}s`, '10-Lap Avg']}
                      />
                      <Legend />
                      {Object.entries(lapDetails).map(([teamName, laps], idx) => {
                        const colors = ['#3B82F6', '#10B981', '#F59E0B', '#EF4444', '#8B5CF6'];
                        const movingAvg = calculateMovingAverage(laps, 10);

                        return (
                          <Line
                            key={teamName}
                            data={movingAvg}
                            type="monotone"
                            dataKey="avg"
                            stroke={colors[idx % colors.length]}
                            name={`${teamName} (10-lap avg)`}
                            strokeWidth={2}
                            dot={false}
                            connectNulls
                          />
                        );
                      })}
                    </LineChart>
                  </ResponsiveContainer>
                  <div className="mt-4 text-sm text-gray-400">
                    This chart shows the 10-lap rolling average to smooth out pit stops and traffic effects.
                    Lower is faster.
                  </div>
                </div>

                {/* Lap-by-Lap Comparison Table */}
                {selectedTeams.length === 2 && (
                  <div className="bg-gray-800 rounded-lg p-6">
                    <h2 className="text-xl font-semibold text-white mb-4">
                      Lap-by-Lap Comparison
                    </h2>
                    <div className="text-sm text-gray-400 mb-4">
                      Total laps: Team 1: {lapDetails[selectedTeams[0]]?.length || 0},
                      Team 2: {lapDetails[selectedTeams[1]]?.length || 0}
                    </div>
                    <div className="overflow-x-auto max-h-[600px] overflow-y-auto">
                      <table className="w-full text-sm">
                        <thead className="sticky top-0 bg-gray-700">
                          <tr className="text-left border-b border-gray-600">
                            <th className="px-4 py-3 text-gray-300">Lap</th>
                            <th className="px-4 py-3 text-blue-400">{selectedTeams[0]}</th>
                            <th className="px-4 py-3 text-green-400">{selectedTeams[1]}</th>
                            <th className="px-4 py-3 text-yellow-400">Delta</th>
                          </tr>
                        </thead>
                        <tbody>
                          {(() => {
                            const team1Laps = lapDetails[selectedTeams[0]] || [];
                            const team2Laps = lapDetails[selectedTeams[1]] || [];
                            const maxLaps = Math.max(team1Laps.length, team2Laps.length);

                            const rows = [];
                            for (let i = 0; i < maxLaps; i++) {
                              const team1Lap = team1Laps[i];
                              const team2Lap = team2Laps[i];
                              const lapNum = team1Lap?.lap_number || team2Lap?.lap_number || i + 1;

                              const team1Time = team1Lap?.lap_time;
                              const team2Time = team2Lap?.lap_time;
                              const delta = team1Time && team2Time ? team1Time - team2Time : null;

                              // Highlight pit laps
                              const team1IsPit = team1Lap?.pit_stop || (team1Time && team1Time >= 225);
                              const team2IsPit = team2Lap?.pit_stop || (team2Time && team2Time >= 225);

                              rows.push(
                                <tr key={i} className="border-b border-gray-700 hover:bg-gray-750">
                                  <td className="px-4 py-2 text-white font-medium">{lapNum}</td>
                                  <td className={`px-4 py-2 ${team1IsPit ? 'text-orange-400 font-bold' : 'text-blue-300'}`}>
                                    {team1Time ? formatLapTime(team1Time) : '-'}
                                  </td>
                                  <td className={`px-4 py-2 ${team2IsPit ? 'text-orange-400 font-bold' : 'text-green-300'}`}>
                                    {team2Time ? formatLapTime(team2Time) : '-'}
                                  </td>
                                  <td className={`px-4 py-2 font-medium ${
                                    !delta ? 'text-gray-500' :
                                    delta > 0 ? 'text-red-400' : 'text-green-400'
                                  }`}>
                                    {delta !== null ? (delta > 0 ? '+' : '') + delta.toFixed(3) : '-'}
                                  </td>
                                </tr>
                              );
                            }
                            return rows;
                          })()}
                        </tbody>
                      </table>
                    </div>
                    <div className="mt-4 text-sm text-gray-400">
                      <span className="text-orange-400 font-bold">Orange</span> indicates pit lap (≥3:45).
                      Delta: positive means {selectedTeams[0]} was slower, negative means faster.
                    </div>
                  </div>
                )}
              </>
            )}
          </div>
        )}

        {loadingStats && (
          <div className="text-center text-white py-8">
            Loading team statistics...
          </div>
        )}

        {selectedTeams.length === 0 && (
          <div className="text-center text-gray-400 py-12">
            <p className="text-lg">Search for teams above to start analyzing and comparing data</p>
          </div>
        )}
      </div>
    </div>
  );
}
