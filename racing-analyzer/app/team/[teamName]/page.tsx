'use client';

import { useEffect, useState } from 'react';
import { useRouter, useParams } from 'next/navigation';
import ApiService from '../../services/ApiService';
import { useAuth } from '../../contexts/AuthContext';

interface TeamSession {
  session_id: number;
  track_id: number;
  track_name: string;
  session_name: string;
  session_date: string;
  total_laps: number;
  best_lap: string | null;
  avg_lap: string | null;
}

interface OverallStats {
  total_sessions: number;
  total_laps: number;
  tracks_raced: number;
  best_lap_overall: string | null;
}

interface SessionLap {
  lap_number: number;
  lap_time: string;
  timestamp: string;
  pit_this_lap: boolean;
  position_after_lap: number;
}

export default function TeamProfilePage() {
  const { user, loading: authLoading } = useAuth();
  const router = useRouter();
  const params = useParams();
  const teamName = decodeURIComponent(params.teamName as string);

  const [sessions, setSessions] = useState<TeamSession[]>([]);
  const [overallStats, setOverallStats] = useState<OverallStats | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [selectedTrack, setSelectedTrack] = useState<number | null>(null);
  const [sortBy, setSortBy] = useState<'date' | 'track' | 'laps' | 'best_lap'>('date');
  const [sortOrder, setSortOrder] = useState<'asc' | 'desc'>('desc');
  const [expandedSession, setExpandedSession] = useState<{trackId: number, sessionId: number} | null>(null);
  const [sessionLaps, setSessionLaps] = useState<SessionLap[]>([]);
  const [loadingLaps, setLoadingLaps] = useState(false);

  useEffect(() => {
    if (!authLoading && !user) {
      router.push('/login');
    }
  }, [user, authLoading, router]);

  useEffect(() => {
    const fetchTeamData = async () => {
      if (!teamName) return;

      setLoading(true);
      setError(null);

      try {
        const result = await ApiService.getCrossTrackSessions(teamName);
        setSessions(result.sessions || []);
        setOverallStats(result.overall_stats || null);
      } catch (err) {
        console.error('Error fetching team data:', err);
        setError(err instanceof Error ? err.message : 'Failed to load team data');
      } finally {
        setLoading(false);
      }
    };

    fetchTeamData();
  }, [teamName]);

  // Filter and sort sessions
  const filteredAndSortedSessions = sessions
    .filter(session => selectedTrack === null || session.track_id === selectedTrack)
    .sort((a, b) => {
      let comparison = 0;

      switch (sortBy) {
        case 'date':
          comparison = new Date(a.session_date).getTime() - new Date(b.session_date).getTime();
          break;
        case 'track':
          comparison = a.track_name.localeCompare(b.track_name);
          break;
        case 'laps':
          comparison = a.total_laps - b.total_laps;
          break;
        case 'best_lap':
          const aLap = parseLapTime(a.best_lap);
          const bLap = parseLapTime(b.best_lap);
          comparison = aLap - bLap;
          break;
      }

      return sortOrder === 'asc' ? comparison : -comparison;
    });

  // Get unique tracks for filter
  const uniqueTracks = Array.from(new Set(sessions.map(s => s.track_id)))
    .map(trackId => {
      const session = sessions.find(s => s.track_id === trackId);
      return { id: trackId, name: session?.track_name || '' };
    })
    .sort((a, b) => a.name.localeCompare(b.name));

  const parseLapTime = (lapTime: string | null): number => {
    if (!lapTime) return Infinity;
    const parts = lapTime.split(':');
    if (parts.length === 2) {
      return parseInt(parts[0]) * 60 + parseFloat(parts[1]);
    }
    return parseFloat(lapTime);
  };

  const handleSort = (column: 'date' | 'track' | 'laps' | 'best_lap') => {
    if (sortBy === column) {
      setSortOrder(sortOrder === 'asc' ? 'desc' : 'asc');
    } else {
      setSortBy(column);
      setSortOrder('desc');
    }
  };

  const toggleSessionLaps = async (trackId: number, sessionId: number) => {
    // If clicking the same session, collapse it
    if (expandedSession?.trackId === trackId && expandedSession?.sessionId === sessionId) {
      setExpandedSession(null);
      setSessionLaps([]);
      return;
    }

    // Expand new session and fetch laps
    setExpandedSession({ trackId, sessionId });
    setLoadingLaps(true);
    try {
      const result = await ApiService.getSessionLaps(teamName, trackId, sessionId);
      setSessionLaps(result.laps || []);
    } catch (err) {
      console.error('Error fetching session laps:', err);
      setSessionLaps([]);
    } finally {
      setLoadingLaps(false);
    }
  };

  if (authLoading || loading) {
    return (
      <div className="min-h-screen bg-gradient-to-br from-gray-900 via-gray-800 to-gray-900 flex items-center justify-center">
        <div className="text-white text-xl">Loading team profile...</div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="min-h-screen bg-gradient-to-br from-gray-900 via-gray-800 to-gray-900 flex items-center justify-center">
        <div className="bg-red-900 text-red-200 p-6 rounded-lg max-w-md">
          <h2 className="text-xl font-bold mb-2">Error</h2>
          <p>{error}</p>
          <button
            onClick={() => router.push('/data')}
            className="mt-4 px-4 py-2 bg-red-700 hover:bg-red-600 rounded-lg transition-colors"
          >
            Back to Data Page
          </button>
        </div>
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-gradient-to-br from-gray-900 via-gray-800 to-gray-900 p-6">
      <div className="max-w-7xl mx-auto">
        {/* Header */}
        <div className="mb-6">
          <button
            onClick={() => router.push('/data')}
            className="text-blue-400 hover:text-blue-300 mb-4 flex items-center gap-2"
          >
            ← Back to Data Page
          </button>
          <h1 className="text-4xl font-bold text-white capitalize">{teamName}</h1>
          <p className="text-gray-400 mt-2">Complete racing history across all tracks</p>
        </div>

        {/* Overall Statistics */}
        {overallStats && (
          <div className="bg-gray-800 rounded-lg p-6 mb-6">
            <h2 className="text-2xl font-semibold text-white mb-4">Overall Statistics</h2>
            <div className="grid grid-cols-1 md:grid-cols-4 gap-4">
              <div className="bg-gray-700 rounded-lg p-4">
                <div className="text-gray-400 text-sm mb-1">Total Sessions</div>
                <div className="text-3xl font-bold text-blue-400">{overallStats.total_sessions}</div>
              </div>
              <div className="bg-gray-700 rounded-lg p-4">
                <div className="text-gray-400 text-sm mb-1">Total Laps</div>
                <div className="text-3xl font-bold text-green-400">{overallStats.total_laps}</div>
              </div>
              <div className="bg-gray-700 rounded-lg p-4">
                <div className="text-gray-400 text-sm mb-1">Tracks Raced</div>
                <div className="text-3xl font-bold text-yellow-400">{overallStats.tracks_raced}</div>
              </div>
              <div className="bg-gray-700 rounded-lg p-4">
                <div className="text-gray-400 text-sm mb-1">Best Lap Overall</div>
                <div className="text-3xl font-bold text-purple-400">
                  {overallStats.best_lap_overall || 'N/A'}
                </div>
              </div>
            </div>
          </div>
        )}

        {/* Sessions Table */}
        <div className="bg-gray-800 rounded-lg p-6">
          <div className="flex items-center justify-between mb-4">
            <h2 className="text-2xl font-semibold text-white">Session History</h2>

            {/* Track Filter */}
            <div className="flex items-center gap-2">
              <label className="text-gray-400 text-sm">Filter by Track:</label>
              <select
                value={selectedTrack || ''}
                onChange={(e) => setSelectedTrack(e.target.value ? parseInt(e.target.value) : null)}
                className="px-4 py-2 bg-gray-700 text-white rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500"
              >
                <option value="">All Tracks</option>
                {uniqueTracks.map(track => (
                  <option key={track.id} value={track.id}>{track.name}</option>
                ))}
              </select>
            </div>
          </div>

          {filteredAndSortedSessions.length > 0 ? (
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead className="bg-gray-700">
                  <tr className="text-left border-b border-gray-600">
                    <th
                      className="px-4 py-3 text-gray-300 cursor-pointer hover:text-white"
                      onClick={() => handleSort('date')}
                    >
                      Date {sortBy === 'date' && (sortOrder === 'asc' ? '↑' : '↓')}
                    </th>
                    <th
                      className="px-4 py-3 text-gray-300 cursor-pointer hover:text-white"
                      onClick={() => handleSort('track')}
                    >
                      Track {sortBy === 'track' && (sortOrder === 'asc' ? '↑' : '↓')}
                    </th>
                    <th className="px-4 py-3 text-gray-300">Session</th>
                    <th
                      className="px-4 py-3 text-gray-300 cursor-pointer hover:text-white"
                      onClick={() => handleSort('laps')}
                    >
                      Total Laps {sortBy === 'laps' && (sortOrder === 'asc' ? '↑' : '↓')}
                    </th>
                    <th
                      className="px-4 py-3 text-gray-300 cursor-pointer hover:text-white"
                      onClick={() => handleSort('best_lap')}
                    >
                      Best Lap {sortBy === 'best_lap' && (sortOrder === 'asc' ? '↑' : '↓')}
                    </th>
                    <th className="px-4 py-3 text-gray-300">Avg Lap</th>
                  </tr>
                </thead>
                <tbody>
                  {filteredAndSortedSessions.map((session, index) => {
                    const isExpanded = expandedSession?.trackId === session.track_id &&
                                       expandedSession?.sessionId === session.session_id;
                    return (
                      <>
                        <tr
                          key={`${session.track_id}-${session.session_id}-${index}`}
                          className="border-b border-gray-700 hover:bg-gray-700 transition-colors cursor-pointer"
                          onClick={() => toggleSessionLaps(session.track_id, session.session_id)}
                        >
                          <td className="px-4 py-3 text-gray-400">
                            <span className="mr-2">{isExpanded ? '▼' : '▶'}</span>
                            {session.session_date
                              ? new Date(session.session_date).toLocaleDateString('en-US', {
                                  month: '2-digit',
                                  day: '2-digit',
                                  year: 'numeric'
                                })
                              : 'N/A'
                            }
                          </td>
                          <td className="px-4 py-3 text-blue-300">{session.track_name}</td>
                          <td className="px-4 py-3 text-white">{session.session_name}</td>
                          <td className="px-4 py-3 text-yellow-300">{session.total_laps}</td>
                          <td className="px-4 py-3 text-green-300">{session.best_lap || 'N/A'}</td>
                          <td className="px-4 py-3 text-purple-300">{session.avg_lap || 'N/A'}</td>
                        </tr>
                        {isExpanded && (
                          <tr key={`laps-${session.track_id}-${session.session_id}`}>
                            <td colSpan={6} className="px-4 py-4 bg-gray-750">
                              {loadingLaps ? (
                                <div className="text-center text-gray-400 py-4">
                                  Loading laps...
                                </div>
                              ) : sessionLaps.length > 0 ? (
                                <div className="max-h-96 overflow-y-auto">
                                  <h4 className="text-white font-semibold mb-2">
                                    Lap Details ({sessionLaps.length} laps)
                                  </h4>
                                  <table className="w-full text-xs">
                                    <thead className="bg-gray-700 sticky top-0">
                                      <tr className="text-left">
                                        <th className="px-3 py-2 text-gray-300">Lap #</th>
                                        <th className="px-3 py-2 text-gray-300">Lap Time</th>
                                        <th className="px-3 py-2 text-gray-300">Position</th>
                                        <th className="px-3 py-2 text-gray-300">Pit Stop</th>
                                        <th className="px-3 py-2 text-gray-300">Timestamp</th>
                                      </tr>
                                    </thead>
                                    <tbody>
                                      {sessionLaps.map((lap) => (
                                        <tr
                                          key={lap.lap_number}
                                          className={`border-b border-gray-700 ${lap.pit_this_lap ? 'bg-orange-900 bg-opacity-20' : ''}`}
                                        >
                                          <td className="px-3 py-2 text-gray-300">{lap.lap_number}</td>
                                          <td className="px-3 py-2 text-white">{lap.lap_time}</td>
                                          <td className="px-3 py-2 text-yellow-300">{lap.position_after_lap || 'N/A'}</td>
                                          <td className="px-3 py-2 text-orange-300">
                                            {lap.pit_this_lap ? '🔧 Pit' : ''}
                                          </td>
                                          <td className="px-3 py-2 text-gray-400">
                                            {lap.timestamp ? new Date(lap.timestamp).toLocaleTimeString() : 'N/A'}
                                          </td>
                                        </tr>
                                      ))}
                                    </tbody>
                                  </table>
                                </div>
                              ) : (
                                <div className="text-center text-gray-400 py-4">
                                  No lap data available for this session
                                </div>
                              )}
                            </td>
                          </tr>
                        )}
                      </>
                    );
                  })}
                </tbody>
              </table>
            </div>
          ) : (
            <div className="text-center text-gray-400 py-8">
              {selectedTrack
                ? 'No sessions found for this track.'
                : 'No sessions found for this team.'}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
