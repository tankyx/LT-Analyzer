'use client';

import { useState, useEffect } from 'react';
import { useRouter } from 'next/navigation';
import { useAuth } from '../contexts/AuthContext';
import ApiService from '../services/ApiService';
import {
  LineChart, Line, BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, Legend, ResponsiveContainer,
  ScatterChart, Scatter, ZAxis, ReferenceLine, Cell,
} from 'recharts';

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

interface AllSession {
  session_id: number;
  start_time: string;
  name: string;
  track: string;
  teams_count: number;
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

interface TopTeam {
  name: string;
  best_lap_time: string;
  best_lap_timestamp?: string;
  avg_lap_seconds: number;
  total_laps: number;
  sessions_count: number;
  classes: string;
}

interface LapData {
  lap_number: number;
  lap_time: string;
  session_id: number;
  session_name: string;
  session_date: string;
  timestamp: string;
  pit_this_lap: boolean;
  position_after_lap: number;
}

export default function DataPage() {
  const { user, loading } = useAuth();
  const router = useRouter();

  const [activeTab, setActiveTab] = useState<'search' | 'leaderboard' | 'fairness'>('search');
  const [tracks, setTracks] = useState<Track[]>([]);
  const [selectedTrackId, setSelectedTrackId] = useState<number>(1);
  const [allSessions, setAllSessions] = useState<AllSession[]>([]);
  const [globalSessionFilter, setGlobalSessionFilter] = useState<number | null>(null);
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
  const [topTeams, setTopTeams] = useState<TopTeam[]>([]);
  const [topTeamsLimit, setTopTeamsLimit] = useState<number>(10);
  const [loadingTopTeams, setLoadingTopTeams] = useState(false);
  const [deleteDialogOpen, setDeleteDialogOpen] = useState(false);
  const [teamToDelete, setTeamToDelete] = useState<{name: string, bestLap: string} | null>(null);
  const [deletingLap, setDeletingLap] = useState(false);

  // Mass delete state
  const [massDeleteThreshold, setMassDeleteThreshold] = useState<number>(0);
  const [massDeleteType, setMassDeleteType] = useState<string>('lap_history');
  const [massDeleting, setMassDeleting] = useState(false);
  const [massDeleteResult, setMassDeleteResult] = useState<{success: boolean; message: string; rows_affected?: number; delete_type?: string; threshold_seconds?: number} | null>(null);

  // All laps state
  const [allLaps, setAllLaps] = useState<LapData[]>([]);
  const [allLapsPage, setAllLapsPage] = useState<number>(0);
  const [allLapsPerPage] = useState<number>(50);
  const [allLapsTotalCount, setAllLapsTotalCount] = useState<number>(0);
  const [loadingAllLaps, setLoadingAllLaps] = useState(false);

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

  // Load all sessions when track changes
  useEffect(() => {
    const loadSessions = async () => {
      try {
        const result = await ApiService.getAllSessions(selectedTrackId);
        setAllSessions(result.sessions || []);
      } catch (error) {
        console.error('Error loading sessions:', error);
        setAllSessions([]);
      }
    };
    loadSessions();
  }, [selectedTrackId]);

  // Reset selections when track changes
  useEffect(() => {
    setSelectedTeams([]);
    setTeamStats({});
    setComparisonData([]);
    setCommonSessions([]);
    setSelectedSession(null);
    setGlobalSessionFilter(null);
    setLapDetails({});
    setTeamStints([]);
    setSearchQuery('');
    setSearchResults([]);
  }, [selectedTrackId]);

  // Load top teams when track, limit, or session filter changes
  useEffect(() => {
    let cancelled = false;
    const loadTopTeams = async () => {
      setLoadingTopTeams(true);
      try {
        const result = await ApiService.getTopTeams(
          selectedTrackId,
          topTeamsLimit,
          globalSessionFilter || undefined
        );
        if (cancelled) return;
        setTopTeams(result.teams || []);
      } catch (error) {
        if (cancelled) return;
        console.error('Error loading top teams:', error);
        setTopTeams([]);
      } finally {
        if (!cancelled) setLoadingTopTeams(false);
      }
    };

    loadTopTeams();
    return () => { cancelled = true; };
  }, [selectedTrackId, topTeamsLimit, globalSessionFilter]);

  // Search teams with debounce
  useEffect(() => {
    let cancelled = false;
    const timer = setTimeout(async () => {
      if (searchQuery.trim().length >= 2) {
        setSearching(true);
        try {
          const result = await ApiService.searchTeams(searchQuery, selectedTrackId);
          if (cancelled) return;
          setSearchResults(result.teams || []);
        } catch (error) {
          if (cancelled) return;
          console.error('Error searching teams:', error);
          setSearchResults([]);
        } finally {
          if (!cancelled) setSearching(false);
        }
      } else {
        setSearchResults([]);
      }
    }, 300);

    return () => {
      cancelled = true;
      clearTimeout(timer);
    };
  }, [searchQuery, selectedTrackId]);

  // Fetch common sessions when teams change
  useEffect(() => {
    const fetchCommonSessions = async () => {
      if (selectedTeams.length >= 1) {
        try {
          const result = await ApiService.getCommonSessions(selectedTeams, selectedTrackId);
          let sessions = result.sessions || [];

          // If globalSessionFilter is set, ensure it's in the list
          if (globalSessionFilter) {
            const filterSessionExists = sessions.some((s: CommonSession) => s.session_id === globalSessionFilter);
            if (!filterSessionExists) {
              // Find the filtered session from allSessions and add it
              const filteredSession = allSessions.find((s: AllSession) => s.session_id === globalSessionFilter);
              if (filteredSession) {
                sessions = [{
                  session_id: filteredSession.session_id,
                  start_time: filteredSession.start_time,
                  name: filteredSession.name,
                  track: filteredSession.track,
                  teams_present: filteredSession.teams_count
                }, ...sessions];
              }
            }
            // Auto-select the filtered session
            setSelectedSession(globalSessionFilter);
          } else {
            // Auto-select most recent session
            if (sessions.length > 0) {
              setSelectedSession(sessions[0].session_id);
            } else {
              setSelectedSession(null);
            }
          }

          setCommonSessions(sessions);
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
  }, [selectedTeams, selectedTrackId, globalSessionFilter, allSessions]);

  // Refetch stats when session changes
  useEffect(() => {
    let cancelled = false;
    const refetchStats = async () => {
      if (selectedTeams.length === 0) return;

      setLoadingStats(true);
      try {
        // Use allSettled so one team's failure doesn't wipe out the whole panel.
        const statsPromises = selectedTeams.map(team =>
          ApiService.getTeamStats(team, selectedSession || undefined, selectedTrackId)
        );
        const statsResults = await Promise.allSettled(statsPromises);
        if (cancelled) return;

        const newTeamStats: { [key: string]: TeamStats } = {};
        selectedTeams.forEach((team, idx) => {
          const r = statsResults[idx];
          if (r.status === 'fulfilled') {
            newTeamStats[team] = r.value;
          } else {
            console.error(`Stats fetch failed for ${team}:`, r.reason);
          }
        });
        setTeamStats(newTeamStats);

        if (selectedTeams.length >= 2) {
          const comparison = await ApiService.compareTeams(selectedTeams, selectedSession || undefined, selectedTrackId);
          if (cancelled) return;
          setComparisonData(comparison.comparison || []);
        }
      } catch (error) {
        if (cancelled) return;
        console.error('Error refetching stats:', error);
      } finally {
        if (!cancelled) setLoadingStats(false);
      }
    };

    refetchStats();
    return () => { cancelled = true; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
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

  const handleDeleteBestLap = (teamName: string, bestLapTime: string) => {
    setTeamToDelete({ name: teamName, bestLap: bestLapTime });
    setDeleteDialogOpen(true);
  };

  const confirmDeleteBestLap = async () => {
    if (!teamToDelete) return;

    setDeletingLap(true);
    try {
      await ApiService.deleteBestLap(teamToDelete.name, selectedTrackId, teamToDelete.bestLap);

      // Refresh top teams list
      const result = await ApiService.getTopTeams(selectedTrackId, topTeamsLimit);
      setTopTeams(result.teams || []);

      // Close dialog
      setDeleteDialogOpen(false);
      setTeamToDelete(null);

      alert(`Best lap deleted successfully for ${teamToDelete.name}`);
    } catch (error) {
      console.error('Error deleting best lap:', error);
      alert(`Failed to delete best lap: ${error instanceof Error ? error.message : 'Unknown error'}`);
    } finally {
      setDeletingLap(false);
    }
  };

  const cancelDeleteBestLap = () => {
    setDeleteDialogOpen(false);
    setTeamToDelete(null);
  };

  // Mass delete handler
  const handleMassDelete = async () => {
    if (!massDeleteThreshold || massDeleteThreshold <= 0) {
      alert('Please enter a valid threshold value (greater than 0 seconds)');
      return;
    }

    const confirmed = window.confirm(
      `Are you sure you want to delete all laps UNDER ${massDeleteThreshold} seconds?\n\n` +
      `Delete Mode: ${massDeleteType === 'lap_history' ? 'Individual Lap Records' : 'Best Lap Records'}\n` +
      `Track: ${tracks.find(t => t.id === selectedTrackId)?.track_name || 'Unknown'}\n\n` +
      `This action affects the entire track and CANNOT be undone!`
    );

    if (!confirmed) return;

    setMassDeleting(true);
    setMassDeleteResult(null);

    try {
      const result = await ApiService.massDeleteLaps(
        selectedTrackId,
        massDeleteThreshold,
        massDeleteType
      );
      setMassDeleteResult(result);

      // Refresh top teams list
      const topTeamsResult = await ApiService.getTopTeams(selectedTrackId, topTeamsLimit);
      setTopTeams(topTeamsResult.teams || []);
    } catch (error) {
      setMassDeleteResult({
        success: false,
        message: `Error: ${error instanceof Error ? error.message : 'Unknown error'}`
      });
    } finally {
      setMassDeleting(false);
    }
  };

  // Fetch all laps when single team is selected
  useEffect(() => {
    const fetchAllLaps = async () => {
      if (selectedTeams.length === 1) {
        setLoadingAllLaps(true);
        try {
          const result = await ApiService.getAllLaps(
            selectedTeams[0],
            selectedTrackId,
            globalSessionFilter || undefined,
            allLapsPerPage,
            allLapsPage * allLapsPerPage
          );
          setAllLaps(result.laps || []);
          setAllLapsTotalCount(result.total_laps || 0);
        } catch (error) {
          console.error('Error fetching all laps:', error);
          setAllLaps([]);
        } finally {
          setLoadingAllLaps(false);
        }
      } else {
        setAllLaps([]);
        setAllLapsTotalCount(0);
        setAllLapsPage(0);
      }
    };

    fetchAllLaps();
  }, [selectedTeams, selectedTrackId, globalSessionFilter, allLapsPage, allLapsPerPage]);

  // Fetch detailed lap data when session and teams change
  useEffect(() => {
    const fetchLapDetails = async () => {
      if (selectedTeams.length >= 2) {
        try {
          // Use selectedSession if available, otherwise use globalSessionFilter, otherwise undefined (all sessions)
          const sessionToUse = selectedSession || globalSessionFilter || undefined;
          const result = await ApiService.getLapDetails(selectedTeams, sessionToUse, selectedTrackId);
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
  }, [selectedTeams, selectedSession, globalSessionFilter, selectedTrackId]);

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
        <h1 className="text-3xl font-bold text-white mb-6">Driver Stats</h1>

        <div className="border-b border-gray-700 mb-4 flex gap-2">
          <button
            onClick={() => setActiveTab('search')}
            className={`px-4 py-2 text-sm font-medium border-b-2 transition-colors ${
              activeTab === 'search' ? 'text-white border-blue-400' : 'text-gray-400 border-transparent hover:text-gray-200'
            }`}
          >
            Driver Search
          </button>
          <button
            onClick={() => setActiveTab('fairness')}
            className={`px-4 py-2 text-sm font-medium border-b-2 transition-colors ${
              activeTab === 'fairness' ? 'text-white border-blue-400' : 'text-gray-400 border-transparent hover:text-gray-200'
            }`}
          >
            Kart-Draw Fairness
          </button>
          <button
            onClick={() => setActiveTab('leaderboard')}
            className={`px-4 py-2 text-sm font-medium border-b-2 transition-colors ${
              activeTab === 'leaderboard' ? 'text-white border-blue-400' : 'text-gray-400 border-transparent hover:text-gray-200'
            }`}
          >
            Leaderboard & Compare
          </button>
        </div>

        {activeTab === 'fairness' && (
          <TrackFairnessPanel tracks={tracks} />
        )}

        {activeTab === 'search' && (
          <div className="bg-gray-800 rounded-lg p-6 mb-6">
            <h2 className="text-xl font-semibold text-white mb-2">Find a driver</h2>
            <p className="text-sm text-gray-400 mb-4">
              Search by driver/team name. Click a result to open the full profile with cross-track history, consistency stats,
              and kart-fairness analysis.
            </p>
            <div className="relative">
              <input
                type="text"
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
                placeholder="Start typing a name..."
                className="w-full px-4 py-3 bg-gray-700 text-white text-lg rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500"
                autoFocus
              />
              {searching && <div className="absolute right-3 top-3 text-gray-400">Searching...</div>}
            </div>

            {searchQuery && searchResults.length > 0 && (
              <div className="mt-4 bg-gray-700 rounded-lg max-h-96 overflow-y-auto">
                {searchResults.map((team, idx) => (
                  <div
                    key={`${team.name}-${idx}`}
                    onClick={() => router.push(`/team/${encodeURIComponent(team.name)}`)}
                    className="px-4 py-3 hover:bg-gray-600 cursor-pointer flex justify-between items-center border-b border-gray-600 last:border-b-0"
                  >
                    <span className="text-white">{team.name}</span>
                    <span className="text-sm text-gray-400">Classes: {team.classes || '—'}</span>
                  </div>
                ))}
              </div>
            )}

            {searchQuery && !searching && searchResults.length === 0 && (
              <div className="mt-4 text-gray-400 text-sm">No drivers found matching {`"${searchQuery}"`}.</div>
            )}

            {!searchQuery && (
              <div className="mt-6 text-sm text-gray-500">
                Tip: the search is case-insensitive and matches partial names (e.g. {`"delvenne"`} finds both
                {' '}{`"DELVENNE Simon"`} and {`"SIMON DELVENNE"`}). Cross-track sessions and stats are gathered automatically from every
                configured track.
              </div>
            )}
          </div>
        )}

        {activeTab === 'leaderboard' && (
        <>

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

        {/* Session Selector */}
        <div className="bg-gray-800 rounded-lg p-6 mb-6">
          <h2 className="text-xl font-semibold text-white mb-4">Filter by Session (Optional)</h2>
          <select
            value={globalSessionFilter || ''}
            onChange={(e) => setGlobalSessionFilter(e.target.value ? parseInt(e.target.value) : null)}
            className="w-full px-4 py-2 bg-gray-700 text-white rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500"
          >
            <option value="">All Sessions</option>
            {allSessions.map((session) => (
              <option key={session.session_id} value={session.session_id}>
                Session {session.session_id} - {session.name} ({session.teams_count} teams)
              </option>
            ))}
          </select>
          {globalSessionFilter && (
            <p className="mt-2 text-sm text-gray-400">
              Filtering all data by selected session. Clear to view all sessions.
            </p>
          )}
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
              {searchResults.map((team, idx) => (
                <div
                  key={`${team.name}-${idx}`}
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

        {/* Top Teams Section */}
        <div className="bg-gray-800 rounded-lg p-6 mb-6">
          <div className="flex justify-between items-center mb-4">
            <h2 className="text-xl font-semibold text-white">Top Teams</h2>
            <select
              value={topTeamsLimit}
              onChange={(e) => setTopTeamsLimit(parseInt(e.target.value))}
              className="px-4 py-2 bg-gray-700 text-white rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500"
            >
              <option value={10}>Top 10</option>
              <option value={20}>Top 20</option>
              <option value={30}>Top 30</option>
            </select>
          </div>

          {loadingTopTeams ? (
            <div className="text-center text-gray-400 py-8">Loading top teams...</div>
          ) : topTeams.length > 0 ? (
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead className="bg-gray-700">
                  <tr className="text-left border-b border-gray-600">
                    <th className="px-4 py-3 text-gray-300">Rank</th>
                    <th className="px-4 py-3 text-gray-300">Team Name</th>
                    <th className="px-4 py-3 text-gray-300">Best Lap</th>
                    <th className="px-4 py-3 text-gray-300">Best Lap Set</th>
                    <th className="px-4 py-3 text-gray-300">Avg Lap</th>
                    <th className="px-4 py-3 text-gray-300">Total Laps</th>
                    <th className="px-4 py-3 text-gray-300">Sessions</th>
                    <th className="px-4 py-3 text-gray-300">Classes</th>
                    {user?.role === 'admin' && (
                      <th className="px-4 py-3 text-gray-300">Actions</th>
                    )}
                  </tr>
                </thead>
                <tbody>
                  {topTeams.map((team, index) => {
                    const isSelected = selectedTeams.includes(team.name);
                    return (
                      <tr
                        key={`${index}-${team.name}`}
                        className={`border-b border-gray-700 transition-colors ${
                          isSelected
                            ? 'bg-blue-900 bg-opacity-30'
                            : 'hover:bg-gray-700'
                        }`}
                      >
                        <td className="px-4 py-3 text-white font-medium">{index + 1}</td>
                        <td className="px-4 py-3 text-white capitalize">
                          <div className="flex items-center gap-2">
                            <span
                              className="cursor-pointer hover:text-blue-300"
                              onClick={() => !isSelected && addTeamToComparison(team.name)}
                            >
                              {team.name}
                            </span>
                            {isSelected && (
                              <span className="text-green-400 text-xs">✓</span>
                            )}
                            <button
                              onClick={() => router.push(`/team/${encodeURIComponent(team.name)}`)}
                              className="text-blue-400 hover:text-blue-300 text-xs ml-2"
                              title="View team profile"
                            >
                              📊
                            </button>
                          </div>
                        </td>
                        <td className="px-4 py-3 text-blue-300">{team.best_lap_time}</td>
                        <td className="px-4 py-3 text-gray-400 text-xs">
                          {team.best_lap_timestamp
                            ? new Date(team.best_lap_timestamp).toLocaleString('en-US', {
                                month: '2-digit',
                                day: '2-digit',
                                year: 'numeric',
                                hour: '2-digit',
                                minute: '2-digit'
                              })
                            : 'N/A'
                          }
                        </td>
                        <td className="px-4 py-3 text-green-300">
                          {team.avg_lap_seconds > 0 ? formatLapTime(team.avg_lap_seconds) : 'N/A'}
                        </td>
                        <td className="px-4 py-3 text-yellow-300">{team.total_laps}</td>
                        <td className="px-4 py-3 text-purple-300">{team.sessions_count}</td>
                        <td className="px-4 py-3 text-gray-400">{team.classes}</td>
                        {user?.role === 'admin' && (
                          <td className="px-4 py-3">
                            <button
                              onClick={(e) => {
                                e.stopPropagation();
                                handleDeleteBestLap(team.name, team.best_lap_time);
                              }}
                              className="text-red-400 hover:text-red-300 transition-colors"
                              title="Delete best lap"
                            >
                              🗑️
                            </button>
                          </td>
                        )}
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          ) : (
            <div className="text-center text-gray-400 py-8">
              No teams found for this track. Teams will appear once race data is collected.
            </div>
          )}
        </div>

        {/* Mass Delete Section - Admin Only */}
        {user?.role === 'admin' && (
          <div className="bg-gray-800 rounded-lg p-6 mb-6">
            <h2 className="text-xl font-semibold text-white mb-4">
              Mass Delete Laps (Track-Wide)
            </h2>
            <p className="text-gray-400 text-sm mb-4">
              Delete all lap times <strong>below</strong> a specified threshold for this track.
              This is useful for removing invalid data caused by track cuts or data errors.
            </p>

            <div className="grid grid-cols-1 md:grid-cols-3 gap-4 mb-4">
              <div>
                <label className="text-gray-400 text-sm mb-2 block">
                  Threshold (seconds) - Delete laps UNDER this value
                </label>
                <input
                  type="number"
                  step="0.1"
                  min="0"
                  placeholder="e.g., 55.0"
                  value={massDeleteThreshold || ''}
                  onChange={(e) => setMassDeleteThreshold(parseFloat(e.target.value) || 0)}
                  className="w-full px-4 py-2 bg-gray-700 text-white rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500"
                />
                <p className="text-xs text-gray-500 mt-1">
                  Laps under {massDeleteThreshold || 0}s will be deleted
                </p>
              </div>

              <div>
                <label className="text-gray-400 text-sm mb-2 block">Delete Type</label>
                <select
                  value={massDeleteType}
                  onChange={(e) => setMassDeleteType(e.target.value)}
                  className="w-full px-4 py-2 bg-gray-700 text-white rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500"
                >
                  <option value="lap_history">Individual Laps (lap_history)</option>
                  <option value="best_laps">Best Lap Records (lap_times)</option>
                </select>
                <p className="text-xs text-gray-500 mt-1">
                  {massDeleteType === 'lap_history'
                    ? 'Deletes individual lap completion records'
                    : 'Nullifies best lap values in lap_times table'}
                </p>
              </div>

              <div className="flex items-end">
                <button
                  onClick={handleMassDelete}
                  disabled={!massDeleteThreshold || massDeleteThreshold <= 0 || massDeleting}
                  className="w-full px-4 py-2 bg-red-600 text-white rounded-lg hover:bg-red-500 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
                >
                  {massDeleting ? 'Deleting...' : 'Delete Laps'}
                </button>
              </div>
            </div>

            {massDeleteResult && (
              <div className={`mt-4 p-4 rounded-lg ${
                massDeleteResult.success
                  ? 'bg-green-900 text-green-200'
                  : 'bg-red-900 text-red-200'
              }`}>
                <p className="font-semibold">{massDeleteResult.message}</p>
                {massDeleteResult.rows_affected !== undefined && (
                  <p className="text-sm mt-1">
                    Rows affected: {massDeleteResult.rows_affected}
                    {massDeleteResult.delete_type && ` (${massDeleteResult.delete_type})`}
                    {massDeleteResult.threshold_seconds && ` | Threshold: ${massDeleteResult.threshold_seconds}s`}
                  </p>
                )}
              </div>
            )}
          </div>
        )}

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

        {/* No Common Sessions Message */}
        {selectedTeams.length >= 2 && commonSessions.length === 0 && (
          <div className="bg-yellow-900 border border-yellow-600 rounded-lg p-4 mb-6">
            <p className="text-yellow-200">
              <strong>Note:</strong> These teams have not raced together in the same session.
              Showing comparison data from all their sessions combined.
              {globalSessionFilter && " (filtered by selected session above)"}
            </p>
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

        {/* All Laps Section - Single Team Only */}
        {selectedTeams.length === 1 && (
          <div className="bg-gray-800 rounded-lg p-6 mb-6">
            <div className="flex items-center justify-between mb-4">
              <h2 className="text-xl font-semibold text-white">
                All Laps - {selectedTeams[0]} ({allLapsTotalCount} total)
              </h2>
              <button
                onClick={() => router.push(`/team/${encodeURIComponent(selectedTeams[0])}`)}
                className="px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-500 transition-colors flex items-center gap-2"
              >
                📊 View Full Profile
              </button>
            </div>

            {loadingAllLaps ? (
              <div className="text-center text-gray-400 py-8">
                Loading laps...
              </div>
            ) : allLaps.length > 0 ? (
              <>
                <div className="overflow-x-auto mb-4">
                  <table className="w-full text-sm">
                    <thead className="bg-gray-700">
                      <tr className="text-left border-b border-gray-600">
                        <th className="px-4 py-3 text-gray-300">Lap #</th>
                        <th className="px-4 py-3 text-gray-300">Lap Time</th>
                        <th className="px-4 py-3 text-gray-300">Session</th>
                        <th className="px-4 py-3 text-gray-300">Date</th>
                        <th className="px-4 py-3 text-gray-300">Position</th>
                        <th className="px-4 py-3 text-gray-300">Pit</th>
                      </tr>
                    </thead>
                    <tbody>
                      {allLaps.map((lap, index) => (
                        <tr
                          key={`${lap.session_id}-${lap.lap_number}-${index}`}
                          className="border-b border-gray-700 hover:bg-gray-700 transition-colors"
                        >
                          <td className="px-4 py-3 text-white">{lap.lap_number}</td>
                          <td className="px-4 py-3 text-blue-300">{lap.lap_time}</td>
                          <td className="px-4 py-3 text-gray-400">{lap.session_name}</td>
                          <td className="px-4 py-3 text-gray-400 text-xs">
                            {lap.session_date
                              ? new Date(lap.session_date).toLocaleDateString('en-US', {
                                  month: '2-digit',
                                  day: '2-digit',
                                  year: 'numeric'
                                })
                              : 'N/A'
                            }
                          </td>
                          <td className="px-4 py-3 text-yellow-300">
                            {lap.position_after_lap ? `P${lap.position_after_lap}` : 'N/A'}
                          </td>
                          <td className="px-4 py-3 text-center">
                            {lap.pit_this_lap ? (
                              <span className="text-orange-400">🛠️</span>
                            ) : (
                              <span className="text-gray-600">-</span>
                            )}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>

                {/* Pagination */}
                {allLapsTotalCount > allLapsPerPage && (
                  <div className="flex items-center justify-between">
                    <div className="text-gray-400 text-sm">
                      Showing {allLapsPage * allLapsPerPage + 1} - {Math.min((allLapsPage + 1) * allLapsPerPage, allLapsTotalCount)} of {allLapsTotalCount} laps
                    </div>
                    <div className="flex gap-2">
                      <button
                        onClick={() => setAllLapsPage(Math.max(0, allLapsPage - 1))}
                        disabled={allLapsPage === 0}
                        className="px-4 py-2 bg-gray-700 text-white rounded-lg hover:bg-gray-600 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
                      >
                        Previous
                      </button>
                      <button
                        onClick={() => setAllLapsPage(allLapsPage + 1)}
                        disabled={(allLapsPage + 1) * allLapsPerPage >= allLapsTotalCount}
                        className="px-4 py-2 bg-gray-700 text-white rounded-lg hover:bg-gray-600 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
                      >
                        Next
                      </button>
                    </div>
                  </div>
                )}
              </>
            ) : (
              <div className="text-center text-gray-400 py-8">
                No lap data found for this team.
              </div>
            )}
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
            {Object.keys(lapDetails).length > 0 && (
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
                        label={{ value: 'Lap Time', angle: -90, position: 'insideLeft' }}
                      />
                      <Tooltip
                        contentStyle={{ backgroundColor: '#1F2937', border: 'none' }}
                        labelStyle={{ color: '#fff' }}
                        formatter={(value: number) => [formatLapTime(value), 'Lap Time']}
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
                        label={{ value: 'Average Lap Time', angle: -90, position: 'insideLeft' }}
                      />
                      <Tooltip
                        contentStyle={{ backgroundColor: '#1F2937', border: 'none' }}
                        labelStyle={{ color: '#fff' }}
                        formatter={(value: number) => [formatLapTime(value), '10-Lap Avg']}
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

        {/* Delete Confirmation Dialog */}
        {deleteDialogOpen && teamToDelete && (
          <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50">
            <div className="bg-gray-800 rounded-lg p-6 max-w-md w-full mx-4">
              <h3 className="text-xl font-semibold text-white mb-4">Delete Best Lap?</h3>
              <p className="text-gray-300 mb-6">
                Are you sure you want to delete the best lap time of{' '}
                <span className="font-bold text-blue-300">{teamToDelete.bestLap}</span> for team{' '}
                <span className="font-bold text-blue-300 capitalize">{teamToDelete.name}</span>?
                <br /><br />
                This will make the second-best lap the new best lap time.
              </p>
              <div className="flex gap-4 justify-end">
                <button
                  onClick={cancelDeleteBestLap}
                  disabled={deletingLap}
                  className="px-4 py-2 bg-gray-600 text-white rounded-lg hover:bg-gray-500 transition-colors disabled:opacity-50"
                >
                  Cancel
                </button>
                <button
                  onClick={confirmDeleteBestLap}
                  disabled={deletingLap}
                  className="px-4 py-2 bg-red-600 text-white rounded-lg hover:bg-red-500 transition-colors disabled:opacity-50"
                >
                  {deletingLap ? 'Deleting...' : 'Delete'}
                </button>
              </div>
            </div>
          </div>
        )}
        </>
        )}
      </div>
    </div>
  );
}

// ============================================================================
// Track Fairness Leaderboard panel
// ============================================================================

type VarDefVerdict = 'consistent' | 'deficit_flagged' | 'insufficient_data';

interface TrackFairnessDriver {
  name: string;
  sessions: number;
  pb: string;
  pb_seconds: number;
  mean_session_best_seconds: number;
  stddev_session_best_seconds: number;
  mean_gap_to_pb_pct: number;
  max_gap_to_pb_pct: number;
  pct_within_1pct_pb: number;
  pct_within_0_5pct_pb: number;
  mean_relative_pace: number | null;
  stddev_relative_pace: number | null;
  best_relative_pace: number | null;
  worst_relative_pace: number | null;
  vardef_n_sessions: number;
  vardef_observed_sd_seconds: number | null;
  vardef_expected_sd_seconds: number | null;
  vardef_ratio: number | null;
  vardef_p_value: number | null;
  vardef_verdict: VarDefVerdict;
}

type FairnessSortKey =
  | 'mean_gap_to_pb_pct'
  | 'stddev_session_best_seconds'
  | 'pct_within_1pct_pb'
  | 'sessions'
  | 'pb_seconds'
  | 'stddev_relative_pace'
  | 'mean_relative_pace'
  | 'vardef_ratio'
  | 'vardef_p_value';

interface SessionConfigsResponse {
  track_id: number;
  track_name: string;
  session_count: number;
  field_best_min: number | null;
  field_best_max: number | null;
  histogram: { field_best_bin: number; count: number }[];
  suggested_splits: { gap: number; below: number; above: number }[];
}

interface LayoutEntry {
  id: number;
  name: string;
  min_field_best: number | null;
  max_field_best: number | null;
  is_default: boolean;
}

function TrackFairnessPanel({ tracks }: { tracks: Track[] }) {
  const router = useRouter();
  const [trackId, setTrackId] = useState<number | null>(null);
  const [minSessions, setMinSessions] = useState<number>(5);
  const [minFieldBest, setMinFieldBest] = useState<string>('');
  const [maxFieldBest, setMaxFieldBest] = useState<string>('');
  const [layoutId, setLayoutId] = useState<number | null>(null);
  const [windowMonths, setWindowMonths] = useState<number>(12);
  const [layouts, setLayouts] = useState<LayoutEntry[]>([]);
  const [data, setData] = useState<TrackFairnessDriver[] | null>(null);
  const [configs, setConfigs] = useState<SessionConfigsResponse | null>(null);
  const [trackName, setTrackName] = useState<string>('');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [sortKey, setSortKey] = useState<FairnessSortKey>('stddev_relative_pace');
  const [sortDesc, setSortDesc] = useState(false);

  // Default to first track once tracks load
  useEffect(() => {
    if (trackId === null && tracks.length > 0) setTrackId(tracks[0].id);
  }, [tracks, trackId]);

  // Load session-config histogram to help pick layout thresholds
  useEffect(() => {
    if (trackId === null) return;
    let cancelled = false;
    ApiService.getTrackSessionConfigs(trackId)
      .then(res => { if (!cancelled) setConfigs(res); })
      .catch(() => { if (!cancelled) setConfigs(null); });
    return () => { cancelled = true; };
  }, [trackId]);

  // Load layouts for the selected track
  useEffect(() => {
    if (trackId === null) { setLayouts([]); setLayoutId(null); return; }
    let cancelled = false;
    ApiService.getTrackLayouts(trackId)
      .then(res => {
        if (cancelled) return;
        const list: LayoutEntry[] = res?.layouts || [];
        setLayouts(list);
        // Reset selection whenever track changes; user opts in per track.
        setLayoutId(null);
      })
      .catch(() => {
        if (!cancelled) { setLayouts([]); setLayoutId(null); }
      });
    return () => { cancelled = true; };
  }, [trackId]);

  useEffect(() => {
    if (trackId === null) return;
    let cancelled = false;
    setLoading(true);
    setError(null);
    setData(null);
    const minFB = minFieldBest.trim() === '' ? undefined : parseFloat(minFieldBest);
    const maxFB = maxFieldBest.trim() === '' ? undefined : parseFloat(maxFieldBest);
    ApiService.getTrackKartFairness(trackId, minSessions, minFB, maxFB, layoutId, windowMonths)
      .then(res => {
        if (cancelled) return;
        setData(res.drivers || []);
        setTrackName(res.track_name || '');
      })
      .catch(err => {
        if (cancelled) return;
        setError(err instanceof Error ? err.message : 'Failed to load kart fairness');
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [trackId, minSessions, minFieldBest, maxFieldBest, layoutId, windowMonths]);

  const sortedDrivers = (() => {
    if (!data) return [];
    const copy = [...data];
    copy.sort((a, b) => {
      const dir = sortDesc ? -1 : 1;
      switch (sortKey) {
        case 'mean_gap_to_pb_pct':
          return dir * (a.mean_gap_to_pb_pct - b.mean_gap_to_pb_pct);
        case 'stddev_session_best_seconds':
          return dir * (a.stddev_session_best_seconds - b.stddev_session_best_seconds);
        case 'pct_within_1pct_pb':
          return dir * (b.pct_within_1pct_pb - a.pct_within_1pct_pb);
        case 'sessions':
          return dir * (a.sessions - b.sessions);
        case 'pb_seconds':
          return dir * (a.pb_seconds - b.pb_seconds);
        case 'stddev_relative_pace': {
          const av = a.stddev_relative_pace ?? 1e9;
          const bv = b.stddev_relative_pace ?? 1e9;
          return dir * (av - bv);
        }
        case 'mean_relative_pace': {
          const av = a.mean_relative_pace ?? 1e9;
          const bv = b.mean_relative_pace ?? 1e9;
          return dir * (av - bv);
        }
        case 'vardef_ratio': {
          // Lower ratio = less variance than typical fleet → suspect.
          const av = a.vardef_ratio ?? 99;
          const bv = b.vardef_ratio ?? 99;
          return dir * (av - bv);
        }
        case 'vardef_p_value': {
          // Smaller p = more significant variance deficit.
          const av = a.vardef_p_value ?? 2;
          const bv = b.vardef_p_value ?? 2;
          return dir * (av - bv);
        }
      }
    });
    return copy;
  })();

  const toggleSort = (k: FairnessSortKey) => {
    if (sortKey === k) {
      setSortDesc(!sortDesc);
    } else {
      setSortKey(k);
      setSortDesc(false);
    }
  };

  const headerCell = (k: FairnessSortKey, label: string) => (
    <th
      onClick={() => toggleSort(k)}
      className="px-3 py-2 text-gray-300 cursor-pointer hover:text-white select-none"
    >
      {label} {sortKey === k && (sortDesc ? '↓' : '↑')}
    </th>
  );

  // Scatter: each point is one driver. X = σRel, Y = MeanRel. Axis positions
  // are descriptive — tight, fast-relative-to-field drivers are in the
  // lower-left, but this mixes skill and kart-luck and is NOT by itself
  // evidence of favoritism. The variance-deficit panel above is the test
  // that speaks to "is the fleet's kart variation showing up in this
  // driver's outcomes?"
  const scatterData = (data || [])
    .filter(r => r.stddev_relative_pace !== null && r.mean_relative_pace !== null)
    .map(r => ({
      name: r.name,
      x: r.stddev_relative_pace as number,
      y: r.mean_relative_pace as number,
      sessions: r.sessions,
      pb: r.pb,
      worst: r.worst_relative_pace,
      vardefVerdict: r.vardef_verdict,
    }));

  const vardefFlagged = scatterData.filter(p => p.vardefVerdict === 'deficit_flagged');

  const fmtRel = (v: number) => v.toFixed(4);

  return (
    <div className="bg-gray-800 rounded-lg p-6 mb-6">
      <h2 className="text-xl font-semibold text-white mb-2">Kart-Draw Fairness — {trackName || 'select a track'}</h2>
      <p className="text-sm text-gray-400 mb-4">
        The direct test for kart-draw favouritism is the <b>variance-deficit test</b> below. For each of a driver&apos;s
        sessions we subtract that day&apos;s field-median from their session-best — this cancels the part of the swing
        that comes from track conditions (grip, temperature, wear), since those move the whole field together. What&apos;s
        left is the driver-specific variation: kart effect + execution noise. Under random kart draws the remaining
        spread should look similar across drivers. When a driver&apos;s residual σ is significantly smaller than the
        fleet-typical residual σ, the fleet&apos;s kart-to-kart noise isn&apos;t showing up in their outcomes —
        evidence of systematically favourable draws. The test doesn&apos;t need stable kart numbers across sessions;
        kart plates being shuffled between races doesn&apos;t break it.{' '}
        <span className="text-gray-500">
          σRel / MeanRel are shown for reference (consistency of relative pace) but mix skill and luck, so they
          are <u>not</u> by themselves evidence of favouritism.
        </span>
      </p>

      <div className="flex items-end gap-4 mb-4 flex-wrap">
        <div>
          <label className="block text-xs text-gray-400 mb-1">Track</label>
          <select
            value={trackId ?? ''}
            onChange={e => setTrackId(parseInt(e.target.value))}
            className="px-3 py-2 bg-gray-700 text-white rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500"
          >
            {tracks.map(t => (
              <option key={t.id} value={t.id}>{t.track_name}</option>
            ))}
          </select>
        </div>
        <div>
          <label className="block text-xs text-gray-400 mb-1">Min sessions</label>
          <input
            type="number"
            min={2}
            max={50}
            value={minSessions}
            onChange={e => {
              const v = parseInt(e.target.value);
              if (!isNaN(v)) setMinSessions(Math.max(2, Math.min(50, v)));
            }}
            className="w-20 px-3 py-2 bg-gray-700 text-white rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500"
          />
        </div>
        <div>
          <label className="block text-xs text-gray-400 mb-1">Layout</label>
          <select
            value={layoutId ?? ''}
            onChange={e => setLayoutId(e.target.value === '' ? null : parseInt(e.target.value))}
            disabled={layouts.length === 0}
            className="px-3 py-2 bg-gray-700 text-white rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500 disabled:opacity-50"
          >
            <option value="">
              {layouts.length === 0 ? 'no layouts configured' : 'all layouts'}
            </option>
            {layouts.map(l => {
              const band = [
                l.min_field_best !== null ? `${l.min_field_best}s+` : '',
                l.max_field_best !== null ? `<${l.max_field_best}s` : '',
              ].filter(Boolean).join(' ');
              return (
                <option key={l.id} value={l.id}>
                  {l.name}{band ? ` (${band})` : ''}{l.is_default ? ' ★' : ''}
                </option>
              );
            })}
          </select>
        </div>
        <div>
          <label className="block text-xs text-gray-400 mb-1">Window (months)</label>
          <select
            value={windowMonths}
            onChange={e => setWindowMonths(parseInt(e.target.value))}
            className="px-3 py-2 bg-gray-700 text-white rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500"
          >
            <option value={3}>3</option>
            <option value={6}>6</option>
            <option value={12}>12</option>
            <option value={24}>24</option>
            <option value={0}>all</option>
          </select>
        </div>
        <div>
          <label className="block text-xs text-gray-400 mb-1">Min field best (s)</label>
          <input
            type="number"
            step={0.5}
            value={minFieldBest}
            onChange={e => setMinFieldBest(e.target.value)}
            placeholder="any"
            className="w-24 px-3 py-2 bg-gray-700 text-white rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500"
          />
        </div>
        <div>
          <label className="block text-xs text-gray-400 mb-1">Max field best (s)</label>
          <input
            type="number"
            step={0.5}
            value={maxFieldBest}
            onChange={e => setMaxFieldBest(e.target.value)}
            placeholder="any"
            className="w-24 px-3 py-2 bg-gray-700 text-white rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500"
          />
        </div>
        <div className="flex flex-col text-xs text-gray-400 max-w-xs">
          <span>Layout = physical track configuration (admins define bands in the admin panel).</span>
          <span>Window caps fleet-drift: a kart labelled #7 today isn&apos;t always the same hardware a year ago.</span>
        </div>
      </div>

      {configs && configs.session_count > 0 && (
        <div className="bg-gray-900 rounded-lg p-3 mb-4">
          <div className="text-xs text-gray-400 mb-2">
            Session field-best distribution ({configs.session_count} sessions, {configs.field_best_min}s–{configs.field_best_max}s).
            Peaks = layouts. Suggested splits at largest gaps:{' '}
            {configs.suggested_splits.slice(0, 3).map((s, i) => (
              <span key={i} className="text-yellow-300 mr-2">
                {s.below}s ⇢ {s.above}s ({s.gap.toFixed(1)}s gap)
              </span>
            ))}
          </div>
          <div style={{ height: 100 }}>
            <ResponsiveContainer width="100%" height="100%">
              <BarChart data={configs.histogram} margin={{ top: 5, right: 5, bottom: 5, left: 5 }}>
                <XAxis
                  dataKey="field_best_bin"
                  stroke="#6b7280"
                  tick={{ fill: '#9ca3af', fontSize: 10 }}
                  tickFormatter={v => `${v}s`}
                />
                <YAxis stroke="#6b7280" tick={{ fill: '#9ca3af', fontSize: 10 }} />
                <Tooltip
                  contentStyle={{ background: '#1f2937', border: '1px solid #374151', fontSize: 12 }}
                  labelFormatter={v => `${v}s field best`}
                />
                <Bar dataKey="count" fill="#6366f1" />
              </BarChart>
            </ResponsiveContainer>
          </div>
        </div>
      )}

      {data && !loading && (
        <div className="text-sm text-gray-400 mb-3">
          {data.length} driver{data.length === 1 ? '' : 's'} at {trackName}
          {vardefFlagged.length > 0 && (
            <span className="ml-3 text-red-300">
              ⚠️ {vardefFlagged.length} driver{vardefFlagged.length === 1 ? '' : 's'} with a statistically significant variance deficit
            </span>
          )}
        </div>
      )}

      {loading && <div className="text-gray-300 py-4">Loading fairness data — this can take a few seconds for large tracks…</div>}
      {error && <div className="text-red-300 py-4">{error}</div>}

      {data && !loading && <VarianceDeficitPanel drivers={data} router={router} />}

      {data && !loading && scatterData.length > 0 && (
        <div className="bg-gray-900 rounded-lg p-3 mb-4">
          <div className="text-xs text-gray-300 mb-2">
            <b>Consistency of relative pace</b> — each dot is a driver. X = σ of their session-best ÷ field median
            (low = tight), Y = mean of that ratio (&lt; 1 = faster than field). Descriptive only: low-σ / fast drivers
            mix skill and kart-luck. Red dots are the drivers formally flagged by the variance-deficit test above —
            those are the kart-favoritism candidates, not position on this scatter.
          </div>
          <div style={{ height: 360 }}>
            <ResponsiveContainer width="100%" height="100%">
              <ScatterChart margin={{ top: 10, right: 20, bottom: 40, left: 50 }}>
                <CartesianGrid stroke="#374151" />
                <XAxis
                  type="number"
                  dataKey="x"
                  stroke="#9ca3af"
                  tick={{ fill: '#9ca3af', fontSize: 10 }}
                  tickFormatter={v => v.toFixed(3)}
                  label={{
                    value: 'σRel (relative-pace variance, lower = tighter)',
                    position: 'bottom',
                    fill: '#9ca3af',
                    offset: 15,
                    fontSize: 11,
                  }}
                  domain={[0, 'auto']}
                />
                <YAxis
                  type="number"
                  dataKey="y"
                  stroke="#9ca3af"
                  tick={{ fill: '#9ca3af', fontSize: 10 }}
                  tickFormatter={v => v.toFixed(3)}
                  label={{
                    value: 'MeanRel (pace vs field median, < 1 = faster)',
                    angle: -90,
                    position: 'insideLeft',
                    fill: '#9ca3af',
                    offset: -5,
                    fontSize: 11,
                  }}
                  domain={['auto', 'auto']}
                />
                <ZAxis type="number" dataKey="sessions" range={[40, 320]} />
                <Tooltip
                  contentStyle={{ background: '#1f2937', border: '1px solid #374151', fontSize: 12 }}
                  formatter={(value: number | string, name: string) => {
                    if (name === 'x' || name === 'σRel') return [Number(value).toFixed(4), 'σRel'];
                    if (name === 'y' || name === 'MeanRel') return [Number(value).toFixed(4), 'MeanRel'];
                    return [value, name];
                  }}
                  labelFormatter={() => ''}
                  content={({ active, payload }) => {
                    if (!active || !payload || payload.length === 0) return null;
                    const p = payload[0].payload as typeof scatterData[0];
                    return (
                      <div className="bg-gray-800 border border-gray-600 rounded px-3 py-2 text-xs">
                        <div className="text-white font-semibold">{p.name}</div>
                        <div className="text-gray-300">Sessions: {p.sessions} · PB: {p.pb}</div>
                        <div className="text-gray-300">σRel: {fmtRel(p.x)}</div>
                        <div className="text-gray-300">MeanRel: {fmtRel(p.y)}</div>
                        <div className="text-gray-400">Worst rel: {p.worst ? fmtRel(p.worst) : '—'}</div>
                      </div>
                    );
                  }}
                />
                {/* Prominent baseline at the field median. Above the line =
                    slower than median, below = faster. */}
                <ReferenceLine
                  y={1.0}
                  stroke="#e5e7eb"
                  strokeWidth={2}
                  strokeDasharray="6 3"
                  label={{ value: 'field median (y = 1.000)', position: 'insideTopRight', fill: '#e5e7eb', fontSize: 11 }}
                />
                <Scatter data={scatterData} onClick={(p: { name?: string }) => { if (p?.name) router.push(`/team/${encodeURIComponent(p.name)}`); }} cursor="pointer">
                  {scatterData.map((p, i) => {
                    const isFlagged = p.vardefVerdict === 'deficit_flagged';
                    return (
                      <Cell
                        key={i}
                        fill={isFlagged ? '#ef4444' : '#60a5fa'}
                        stroke={isFlagged ? '#fca5a5' : '#1f2937'}
                      />
                    );
                  })}
                </Scatter>
              </ScatterChart>
            </ResponsiveContainer>
          </div>
          <div className="text-xs text-gray-500 mt-2">
            Dot size scales with session count (bigger = more data = more reliable). Click a dot to open that driver&apos;s profile.
          </div>
        </div>
      )}

      {data && !loading && (
        data.length === 0 ? (
          <div className="text-gray-400">No drivers reached the minimum sample threshold for this track.</div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead className="bg-gray-700">
                <tr className="text-left">
                  <th className="px-3 py-2 text-gray-300">#</th>
                  <th className="px-3 py-2 text-gray-300">Driver</th>
                  {headerCell('sessions', 'Sess')}
                  {headerCell('pb_seconds', 'PB')}
                  {headerCell('stddev_relative_pace', 'σRel')}
                  {headerCell('mean_relative_pace', 'MeanRel')}
                  {headerCell('vardef_ratio', 'VarDef σ/σ*')}
                  {headerCell('vardef_p_value', 'p')}
                  <th className="px-3 py-2 text-gray-300">Verdict</th>
                  {headerCell('mean_gap_to_pb_pct', 'PB gap')}
                  {headerCell('pct_within_1pct_pb', '<1% PB')}
                </tr>
              </thead>
              <tbody>
                {sortedDrivers.map((dr, i) => {
                  // σRel thresholds: < 0.002 = extreme, < 0.003 = flag, < 0.005
                  // = tight, > 0.010 = wide/normal-ish. MeanRel: < 1.00 means
                  // consistently faster than field median. Combined lucky = both.
                  const sig = dr.stddev_relative_pace;
                  const mean = dr.mean_relative_pace;
                  const sigClass =
                    sig === null ? 'text-gray-500' :
                    sig < 0.002 ? 'text-red-300 font-semibold' :
                    sig < 0.003 ? 'text-yellow-300' :
                    sig > 0.010 ? 'text-blue-300' : 'text-gray-200';
                  const meanClass =
                    mean === null ? 'text-gray-500' :
                    mean < 0.99 ? 'text-green-300 font-semibold' :
                    mean < 1.00 ? 'text-green-300' :
                    mean > 1.02 ? 'text-blue-300' : 'text-gray-200';
                  const pbgapClass =
                    dr.mean_gap_to_pb_pct < 0.5 ? 'text-red-300' :
                    dr.mean_gap_to_pb_pct > 2.0 ? 'text-blue-300' : 'text-gray-200';
                  // Variance-deficit formatting
                  const v = dr.vardef_verdict;
                  const ratio = dr.vardef_ratio;
                  const vp = dr.vardef_p_value;
                  const obsSd = dr.vardef_observed_sd_seconds;
                  const expSd = dr.vardef_expected_sd_seconds;
                  const verdictLabel =
                    v === 'deficit_flagged' ? '⚠️ variance deficit'
                    : v === 'consistent' ? 'consistent'
                    : `(n=${dr.vardef_n_sessions}/15)`;
                  const verdictClass =
                    v === 'deficit_flagged' ? 'text-red-300 font-semibold'
                    : v === 'consistent' ? 'text-green-300'
                    : 'text-gray-500';
                  const ratioClass =
                    ratio === null ? 'text-gray-500'
                    : ratio < 0.5 ? 'text-red-300 font-semibold'
                    : ratio < 0.8 ? 'text-yellow-300'
                    : ratio < 1.2 ? 'text-gray-300'
                    : 'text-blue-300';
                  const pClass =
                    vp === null ? 'text-gray-500'
                    : vp < 0.01 ? 'text-red-300 font-semibold'
                    : vp < 0.05 ? 'text-yellow-300'
                    : 'text-gray-300';
                  const rowHighlight =
                    v === 'deficit_flagged' ? 'bg-red-900 bg-opacity-25 hover:bg-opacity-40'
                    : 'hover:bg-gray-700';

                  return (
                    <tr
                      key={`${dr.name}-${i}`}
                      className={`border-b border-gray-700 cursor-pointer ${rowHighlight}`}
                      onClick={() => router.push(`/team/${encodeURIComponent(dr.name)}`)}
                    >
                      <td className="px-3 py-2 text-gray-500">{i + 1}</td>
                      <td className="px-3 py-2 text-white">{dr.name}</td>
                      <td className="px-3 py-2 text-gray-300">{dr.sessions}</td>
                      <td className="px-3 py-2 text-green-300">{dr.pb}</td>
                      <td className={`px-3 py-2 font-mono ${sigClass}`}>
                        {sig !== null ? sig.toFixed(4) : '—'}
                      </td>
                      <td className={`px-3 py-2 font-mono ${meanClass}`}>
                        {mean !== null ? mean.toFixed(4) : '—'}
                      </td>
                      <td
                        className={`px-3 py-2 font-mono ${ratioClass}`}
                        title={
                          obsSd !== null && expSd !== null
                            ? `Observed σ=${obsSd.toFixed(2)}s · fleet-typical σ=${expSd.toFixed(2)}s`
                            : ''
                        }
                      >
                        {ratio !== null ? ratio.toFixed(2) : '—'}
                      </td>
                      <td className={`px-3 py-2 font-mono ${pClass}`}>
                        {vp !== null ? (vp < 0.0001 ? '<0.0001' : vp.toFixed(4)) : '—'}
                      </td>
                      <td className={`px-3 py-2 text-xs ${verdictClass}`}>
                        {verdictLabel}
                      </td>
                      <td className={`px-3 py-2 ${pbgapClass}`}>{dr.mean_gap_to_pb_pct.toFixed(2)}%</td>
                      <td className="px-3 py-2 text-gray-300">{(dr.pct_within_1pct_pb * 100).toFixed(0)}%</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
            <p className="text-xs text-gray-500 mt-3">
              <b>σRel</b> / <b>MeanRel</b> describe <i>outcome</i> consistency (session-best ÷ field median) — a
              mix of skill and kart-luck that is <u>not</u> by itself evidence of favouritism. The direct test is{' '}
              <b>VarDef σ/σ*</b> — the ratio of the driver&apos;s own σ of (session-best − session-median) vs. the
              fleet-typical σ. The subtraction cancels track conditions (grip, weather, wear) that move the whole
              field together, so what&apos;s left is each driver&apos;s own kart-effect + execution-noise spread.
              Under random kart draws the ratio should be ≈ 1. A ratio well below 1, with a significant <b>p</b>,
              means the fleet&apos;s kart-to-kart variation isn&apos;t showing up in this driver&apos;s results —
              the telltale of systematically favourable draws.{' '}
              <b>Verdict</b> fires only at n ≥ 15 sessions AND ratio &lt; 0.8 AND p &lt; 0.05; below that threshold the
              cell shows <span className="text-gray-400">(n/15)</span> so we don&apos;t cry wolf on small samples.
              Click any header to resort — try <b>VarDef σ/σ*</b> ascending to surface the tightest-variance drivers.
            </p>
          </div>
        )
      )}
    </div>
  );
}

// ============================================================================
// Variance-Deficit Panel — flags drivers whose session-best spread is tighter
// than the fleet's inherent kart variation should impose under random draws.
// ============================================================================

function VardefCard({
  dr,
  tone,
  router,
}: {
  dr: TrackFairnessDriver;
  tone: 'red' | 'yellow';
  router: ReturnType<typeof useRouter>;
}) {
  const obs = dr.vardef_observed_sd_seconds;
  const exp = dr.vardef_expected_sd_seconds;
  const ratio = dr.vardef_ratio;
  const p = dr.vardef_p_value;
  const fmtP = (v: number | null) => v === null ? '—' : (v < 0.0001 ? '<0.0001' : v.toFixed(4));
  const border =
    tone === 'red' ? 'border-red-600 bg-red-900 bg-opacity-25'
    : 'border-yellow-600 bg-yellow-900 bg-opacity-20';
  return (
    <div
      onClick={() => router.push(`/team/${encodeURIComponent(dr.name)}`)}
      className={`border ${border} rounded-lg p-3 cursor-pointer hover:brightness-110`}
    >
      <div className="flex items-baseline justify-between mb-1">
        <span className="text-white font-semibold">{dr.name}</span>
        <span className="text-xs text-gray-400">{dr.vardef_n_sessions} sessions</span>
      </div>
      <div className="text-xs text-gray-200 font-mono">
        Observed σ: <b>{obs !== null ? `${obs.toFixed(2)}s` : '—'}</b> ·
        Fleet-typical σ: <b>{exp !== null ? `${exp.toFixed(2)}s` : '—'}</b> ·
        Ratio: <b>{ratio !== null ? ratio.toFixed(2) : '—'}</b>
      </div>
      <div className="text-xs text-gray-400 font-mono">
        One-sided χ² p = {fmtP(p)}
      </div>
    </div>
  );
}

function VarianceDeficitPanel({
  drivers,
  router,
}: {
  drivers: TrackFairnessDriver[];
  router: ReturnType<typeof useRouter>;
}) {
  // Buckets: formally flagged (n >= 15, ratio < 0.8, p < 0.05), watch
  // (ratio < 0.8 and p < 0.05 but n < 15), and everyone else.
  const flagged: TrackFairnessDriver[] = [];
  const watch: TrackFairnessDriver[] = [];
  let eligible = 0;
  let expectedSd: number | null = null;
  for (const d of drivers) {
    if (expectedSd === null && d.vardef_expected_sd_seconds !== null) {
      expectedSd = d.vardef_expected_sd_seconds;
    }
    if (d.vardef_n_sessions >= 3) eligible += 1;
    const ratio = d.vardef_ratio;
    const p = d.vardef_p_value;
    if (ratio === null || p === null) continue;
    if (d.vardef_verdict === 'deficit_flagged') {
      flagged.push(d);
    } else if (ratio < 0.8 && p < 0.05) {
      watch.push(d);
    }
  }
  const byRatioAsc = (a: TrackFairnessDriver, b: TrackFairnessDriver) =>
    (a.vardef_ratio ?? 99) - (b.vardef_ratio ?? 99);
  flagged.sort(byRatioAsc);
  watch.sort(byRatioAsc);

  if (eligible === 0) {
    return (
      <div className="bg-gray-900 rounded-lg p-4 mb-4 text-sm text-gray-400 border border-gray-700">
        🎯 <b>Variance-deficit shortlist</b>: no driver has enough sessions in the current filter. Widen the window or
        loosen min-sessions.
      </div>
    );
  }

  return (
    <div className="bg-gray-900 rounded-lg p-4 mb-4 border border-gray-700">
      <div className="flex items-baseline justify-between mb-3">
        <h3 className="text-white font-semibold">🎯 Variance-deficit shortlist</h3>
        <span className="text-xs text-gray-400">
          Scanned {eligible} driver{eligible === 1 ? '' : 's'} · fleet-typical σ ≈ {expectedSd !== null ? `${expectedSd.toFixed(2)}s` : '—'} · {flagged.length + watch.length} candidate{flagged.length + watch.length === 1 ? '' : 's'}
        </span>
      </div>
      <p className="text-xs text-gray-400 mb-3">
        For each driver we compute the standard deviation of (session-best − session-median) — this cancels track
        conditions so only driver-specific variation remains. Then we compare it to the median residual σ across all
        qualifying drivers (fleet-typical σ). Under random kart assignment the ratio should be ≈ 1. A ratio
        significantly below 1 means the fleet&apos;s kart-to-kart variation isn&apos;t showing up in this
        driver&apos;s results — consistent with systematically favourable draws.
        <b> Flagged</b> = formal verdict (n ≥ 15, ratio &lt; 0.8, p &lt; 0.05).
        <b> Watch list</b> = same magnitude + p-value but fewer than 15 sessions yet. Click any card for the profile.
      </p>

      {flagged.length === 0 && watch.length === 0 && (
        <div className="text-sm text-green-300">
          No driver&apos;s session-best spread is tighter than the fleet&apos;s inherent variation allows — consistent
          with random kart draws. 👍
        </div>
      )}

      {flagged.length > 0 && (
        <div className="mb-3">
          <div className="text-sm text-red-300 font-semibold mb-2">
            ⚠️ Variance deficit — formal verdict (n ≥ 15)
          </div>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-2">
            {flagged.map(d => (
              <VardefCard key={d.name} dr={d} tone="red" router={router} />
            ))}
          </div>
        </div>
      )}

      {watch.length > 0 && (
        <div>
          <div className="text-sm text-yellow-300 font-semibold mb-2">
            👀 Watch list — tight σ + p &lt; 0.05 but fewer than 15 sessions
          </div>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-2">
            {watch.map(d => (
              <VardefCard key={d.name} dr={d} tone="yellow" router={router} />
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
