'use client';

import { useState, useEffect } from 'react';
import { useRouter } from 'next/navigation';
import { useAuth } from '../contexts/AuthContext';
import ApiService from '../services/ApiService';
import { BarChart3, Check, Trash2, Wrench, X } from 'lucide-react';
import PageShell from '../shell/PageShell';
import SegmentedControl from '../ui/SegmentedControl';
import { CHART, seriesColor } from '../ui/chartTheme';
import TrackFairnessPanel from './TrackFairnessPanel';
import type { Track } from './types';
import {
  LineChart, Line, BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, Legend, ResponsiveContainer,
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
      <div className="flex items-center justify-center min-h-screen bg-canvas">
        <div className="text-muted text-sm">Loading…</div>
      </div>
    );
  }

  if (!user) {
    return null;
  }

  return (
    <PageShell title="Driver stats" icon={<BarChart3 size={18} />}>
        <SegmentedControl
          label="Driver stats view"
          value={activeTab}
          onChange={setActiveTab}
          className="mb-4 max-w-full overflow-x-auto"
          options={[
            { value: 'search', label: 'Driver search', short: 'Search' },
            { value: 'fairness', label: 'Kart-draw fairness', short: 'Fairness' },
            { value: 'leaderboard', label: 'Leaderboard & compare', short: 'Leaderboard' },
          ]}
        />

        {activeTab === 'fairness' && (
          <TrackFairnessPanel tracks={tracks} />
        )}

        {activeTab === 'search' && (
          <div className="bg-surface p-6 mb-6 border border-line">
            <h2 className="text-xl font-semibold text-ink mb-2">Find a driver</h2>
            <p className="text-sm text-muted mb-4">
              Search by driver/team name. Click a result to open the full profile with cross-track history, consistency stats,
              and kart-fairness analysis.
            </p>
            <div className="relative">
              <input
                type="text"
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
                placeholder="Start typing a name..."
                className="w-full px-4 py-3 bg-surface-2 text-ink text-lg border border-line-strong"
                autoFocus
              />
              {searching && <div className="absolute right-3 top-3 text-muted">Searching...</div>}
            </div>

            {searchQuery && searchResults.length > 0 && (
              <div className="mt-4 bg-surface-2 max-h-96 overflow-y-auto">
                {searchResults.map((team, idx) => (
                  <div
                    key={`${team.name}-${idx}`}
                    onClick={() => router.push(`/team/${encodeURIComponent(team.name)}`)}
                    className="px-4 py-3 hover:bg-line cursor-pointer flex justify-between items-center border-b border-line last:border-b-0"
                  >
                    <span className="text-ink">{team.name}</span>
                    <span className="text-sm text-muted">Classes: {team.classes || '—'}</span>
                  </div>
                ))}
              </div>
            )}

            {searchQuery && !searching && searchResults.length === 0 && (
              <div className="mt-4 text-muted text-sm">No drivers found matching {`"${searchQuery}"`}.</div>
            )}

            {!searchQuery && (
              <div className="mt-6 text-sm text-muted">
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
        <div className="bg-surface p-6 mb-6 border border-line">
          <h2 className="text-xl font-semibold text-ink mb-4">Select Track</h2>
          <select
            value={selectedTrackId}
            onChange={(e) => setSelectedTrackId(parseInt(e.target.value))}
            className="w-full px-4 py-2 bg-surface-2 text-ink border border-line-strong"
          >
            {tracks.map((track) => (
              <option key={track.id} value={track.id}>
                {track.track_name}
              </option>
            ))}
          </select>
        </div>

        {/* Session Selector */}
        <div className="bg-surface p-6 mb-6 border border-line">
          <h2 className="text-xl font-semibold text-ink mb-4">Filter by Session (Optional)</h2>
          <select
            value={globalSessionFilter || ''}
            onChange={(e) => setGlobalSessionFilter(e.target.value ? parseInt(e.target.value) : null)}
            className="w-full px-4 py-2 bg-surface-2 text-ink border border-line-strong"
          >
            <option value="">All Sessions</option>
            {allSessions.map((session) => (
              <option key={session.session_id} value={session.session_id}>
                Session {session.session_id} - {session.name} ({session.teams_count} teams)
              </option>
            ))}
          </select>
          {globalSessionFilter && (
            <p className="mt-2 text-sm text-muted">
              Filtering all data by selected session. Clear to view all sessions.
            </p>
          )}
        </div>

        {/* Search Section */}
        <div className="bg-surface p-6 mb-6 border border-line">
          <h2 className="text-xl font-semibold text-ink mb-4">Search Teams</h2>
          <div className="relative">
            <input
              type="text"
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              placeholder="Search for a team name..."
              className="w-full px-4 py-2 bg-surface-2 text-ink border border-line-strong"
            />
            {searching && (
              <div className="absolute right-3 top-2.5 text-muted">Searching...</div>
            )}
          </div>

          {/* Search Results */}
          {searchResults.length > 0 && (
            <div className="mt-4 bg-surface-2 max-h-60 overflow-y-auto">
              {searchResults.map((team, idx) => (
                <div
                  key={`${team.name}-${idx}`}
                  onClick={() => addTeamToComparison(team.name)}
                  className="px-4 py-2 hover:bg-line cursor-pointer flex justify-between items-center border-b border-line last:border-b-0"
                >
                  <span className="text-ink">{team.name}</span>
                  <span className="text-sm text-muted">Classes: {team.classes}</span>
                </div>
              ))}
            </div>
          )}
        </div>

        {/* Top Teams Section */}
        <div className="bg-surface p-6 mb-6 border border-line">
          <div className="flex justify-between items-center mb-4">
            <h2 className="text-xl font-semibold text-ink">Top Teams</h2>
            <select
              value={topTeamsLimit}
              onChange={(e) => setTopTeamsLimit(parseInt(e.target.value))}
              className="px-4 py-2 bg-surface-2 text-ink"
            >
              <option value={10}>Top 10</option>
              <option value={20}>Top 20</option>
              <option value={30}>Top 30</option>
            </select>
          </div>

          {loadingTopTeams ? (
            <div className="text-center text-muted py-8">Loading top teams...</div>
          ) : topTeams.length > 0 ? (
            <div className="overflow-x-auto">
              <table className="tabular w-full text-sm">
                <thead className="bg-surface-2">
                  <tr className="text-left border-b border-line">
                    <th className="px-4 py-3 text-ink">Rank</th>
                    <th className="px-4 py-3 text-ink">Team Name</th>
                    <th className="px-4 py-3 text-ink">Best Lap</th>
                    <th className="px-4 py-3 text-ink">Best Lap Set</th>
                    <th className="px-4 py-3 text-ink">Avg Lap</th>
                    <th className="px-4 py-3 text-ink">Total Laps</th>
                    <th className="px-4 py-3 text-ink">Sessions</th>
                    <th className="px-4 py-3 text-ink">Classes</th>
                    {user?.role === 'admin' && (
                      <th className="px-4 py-3 text-ink">Actions</th>
                    )}
                  </tr>
                </thead>
                <tbody>
                  {topTeams.map((team, index) => {
                    const isSelected = selectedTeams.includes(team.name);
                    return (
                      <tr
                        key={`${index}-${team.name}`}
                        className={`border-b border-line transition-colors ${
                          isSelected
                            ? 'bg-info/15 bg-opacity-30'
                            : 'hover:bg-surface-2'
                        }`}
                      >
                        <td className="px-4 py-3 text-ink font-medium">{index + 1}</td>
                        <td className="px-4 py-3 text-ink capitalize">
                          <div className="flex items-center gap-2">
                            <span
                              className="cursor-pointer hover:text-info"
                              onClick={() => !isSelected && addTeamToComparison(team.name)}
                            >
                              {team.name}
                            </span>
                            {isSelected && (
                              <Check size={14} className="text-live" aria-label="Selected" />
                            )}
                            <button
                              onClick={() => router.push(`/team/${encodeURIComponent(team.name)}`)}
                              className="text-info hover:text-info text-xs ml-2"
                              title="View team profile"
                              aria-label={`View ${team.name} profile`}
                            >
                              <BarChart3 size={14} />
                            </button>
                          </div>
                        </td>
                        <td className="px-4 py-3 text-info">{team.best_lap_time}</td>
                        <td className="px-4 py-3 text-muted text-xs">
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
                        <td className="px-4 py-3 text-live">
                          {team.avg_lap_seconds > 0 ? formatLapTime(team.avg_lap_seconds) : 'N/A'}
                        </td>
                        <td className="px-4 py-3 text-accent">{team.total_laps}</td>
                        <td className="px-4 py-3 text-class2">{team.sessions_count}</td>
                        <td className="px-4 py-3 text-muted">{team.classes}</td>
                        {user?.role === 'admin' && (
                          <td className="px-4 py-3">
                            <button
                              onClick={(e) => {
                                e.stopPropagation();
                                handleDeleteBestLap(team.name, team.best_lap_time);
                              }}
                              className="text-alarm hover:text-alarm transition-colors"
                              title="Delete best lap"
                              aria-label={`Delete best lap of ${team.name}`}
                            >
                              <Trash2 size={16} />
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
            <div className="text-center text-muted py-8">
              No teams found for this track. Teams will appear once race data is collected.
            </div>
          )}
        </div>

        {/* Mass Delete Section - Admin Only */}
        {user?.role === 'admin' && (
          <div className="bg-surface p-6 mb-6 border border-line">
            <h2 className="text-xl font-semibold text-ink mb-4">
              Mass Delete Laps (Track-Wide)
            </h2>
            <p className="text-muted text-sm mb-4">
              Delete all lap times <strong>below</strong> a specified threshold for this track.
              This is useful for removing invalid data caused by track cuts or data errors.
            </p>

            <div className="grid grid-cols-1 md:grid-cols-3 gap-4 mb-4">
              <div>
                <label className="text-muted text-sm mb-2 block">
                  Threshold (seconds) - Delete laps UNDER this value
                </label>
                <input
                  type="number"
                  step="0.1"
                  min="0"
                  placeholder="e.g., 55.0"
                  value={massDeleteThreshold || ''}
                  onChange={(e) => setMassDeleteThreshold(parseFloat(e.target.value) || 0)}
                  className="w-full px-4 py-2 bg-surface-2 text-ink border border-line-strong"
                />
                <p className="text-xs text-muted mt-1">
                  Laps under {massDeleteThreshold || 0}s will be deleted
                </p>
              </div>

              <div>
                <label className="text-muted text-sm mb-2 block">Delete Type</label>
                <select
                  value={massDeleteType}
                  onChange={(e) => setMassDeleteType(e.target.value)}
                  className="w-full px-4 py-2 bg-surface-2 text-ink border border-line-strong"
                >
                  <option value="lap_history">Individual Laps (lap_history)</option>
                  <option value="best_laps">Best Lap Records (lap_times)</option>
                </select>
                <p className="text-xs text-muted mt-1">
                  {massDeleteType === 'lap_history'
                    ? 'Deletes individual lap completion records'
                    : 'Nullifies best lap values in lap_times table'}
                </p>
              </div>

              <div className="flex items-end">
                <button
                  onClick={handleMassDelete}
                  disabled={!massDeleteThreshold || massDeleteThreshold <= 0 || massDeleting}
                  className="w-full px-4 py-2 bg-alarm text-on-signal hover:bg-alarm transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
                >
                  {massDeleting ? 'Deleting...' : 'Delete Laps'}
                </button>
              </div>
            </div>

            {massDeleteResult && (
              <div className={`mt-4 p-4 ${
                massDeleteResult.success
                  ? 'bg-live/15 text-live'
                  : 'bg-alarm/15 text-alarm'
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
          <div className="bg-surface p-6 mb-6 border border-line">
            <h2 className="text-xl font-semibold text-ink mb-4">
              Selected Teams ({selectedTeams.length})
            </h2>
            <div className="flex flex-wrap gap-2">
              {selectedTeams.map((team) => (
                <div
                  key={team}
                  className="accent-block text-accent-ink px-4 py-2 flex items-center gap-2"
                >
                  <span>{team}</span>
                  <button
                    onClick={() => removeTeamFromComparison(team)}
                    className="text-ink hover:text-alarm"
                    aria-label={`Remove ${team} from comparison`}
                  >
                    <X size={14} />
                  </button>
                </div>
              ))}
            </div>
          </div>
        )}

        {/* No Common Sessions Message */}
        {selectedTeams.length >= 2 && commonSessions.length === 0 && (
          <div className="bg-accent/15 border border-accent p-4 mb-6">
            <p className="text-accent">
              <strong>Note:</strong> These teams have not raced together in the same session.
              Showing comparison data from all their sessions combined.
              {globalSessionFilter && " (filtered by selected session above)"}
            </p>
          </div>
        )}

        {/* Session Selector */}
        {commonSessions.length > 0 && (
          <div className="bg-surface p-6 mb-6 border border-line">
            <h2 className="text-xl font-semibold text-ink mb-4">
              Select Session (showing only sessions where all teams participated)
            </h2>
            <select
              value={selectedSession || ''}
              onChange={(e) => setSelectedSession(e.target.value ? parseInt(e.target.value) : null)}
              className="w-full px-4 py-2 bg-surface-2 text-ink border border-line-strong"
            >
              <option value="">All Sessions</option>
              {commonSessions.map((session) => (
                <option key={session.session_id} value={session.session_id}>
                  {new Date(session.start_time).toLocaleDateString()} - {session.name} (Session {session.session_id})
                </option>
              ))}
            </select>
            {selectedSession && (
              <div className="mt-2 text-sm text-muted">
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
                <div key={teamName} className="bg-surface p-6 border border-line">
                  <h3 className="text-lg font-semibold text-ink mb-4 capitalize">{teamName}</h3>
                  <div className="grid grid-cols-2 gap-4 text-sm">
                    <div>
                      <p className="text-muted">Best Lap Time</p>
                      <p className="text-ink font-semibold">{stats.best_lap_time || 'N/A'}</p>
                    </div>
                    <div>
                      <p className="text-muted">Avg Lap Time</p>
                      <p className="text-ink font-semibold">
                        {stats.avg_lap_seconds ? formatLapTime(stats.avg_lap_seconds) : 'N/A'}
                      </p>
                    </div>
                    <div>
                      <p className="text-muted">Total Laps</p>
                      <p className="text-ink font-semibold">{stats.total_laps_completed}</p>
                    </div>
                    <div>
                      <p className="text-muted">Sessions</p>
                      <p className="text-ink font-semibold">{stats.sessions_participated}</p>
                    </div>
                    <div>
                      <p className="text-muted">Total Pit Stops</p>
                      <p className="text-ink font-semibold">{stats.total_pit_stops}</p>
                    </div>
                    <div>
                      <p className="text-muted">Classes</p>
                      <p className="text-ink font-semibold">{stats.classes_raced.join(', ')}</p>
                    </div>
                  </div>
                </div>
              );
            })}
          </div>
        )}

        {/* All Laps Section - Single Team Only */}
        {selectedTeams.length === 1 && (
          <div className="bg-surface p-6 mb-6 border border-line">
            <div className="flex items-center justify-between mb-4">
              <h2 className="text-xl font-semibold text-ink">
                All Laps - {selectedTeams[0]} ({allLapsTotalCount} total)
              </h2>
              <button
                onClick={() => router.push(`/team/${encodeURIComponent(selectedTeams[0])}`)}
                className="px-4 py-2 accent-block text-accent-ink hover:brightness-95 transition-colors flex items-center gap-2"
              >
                <BarChart3 size={16} /> View full profile
              </button>
            </div>

            {loadingAllLaps ? (
              <div className="text-center text-muted py-8">
                Loading laps...
              </div>
            ) : allLaps.length > 0 ? (
              <>
                <div className="overflow-x-auto mb-4">
                  <table className="tabular w-full text-sm">
                    <thead className="bg-surface-2">
                      <tr className="text-left border-b border-line">
                        <th className="px-4 py-3 text-ink">Lap #</th>
                        <th className="px-4 py-3 text-ink">Lap Time</th>
                        <th className="px-4 py-3 text-ink">Session</th>
                        <th className="px-4 py-3 text-ink">Date</th>
                        <th className="px-4 py-3 text-ink">Position</th>
                        <th className="px-4 py-3 text-ink">Pit</th>
                      </tr>
                    </thead>
                    <tbody>
                      {allLaps.map((lap, index) => (
                        <tr
                          key={`${lap.session_id}-${lap.lap_number}-${index}`}
                          className="border-b border-line hover:bg-surface-2 transition-colors"
                        >
                          <td className="px-4 py-3 text-ink">{lap.lap_number}</td>
                          <td className="px-4 py-3 text-info">{lap.lap_time}</td>
                          <td className="px-4 py-3 text-muted">{lap.session_name}</td>
                          <td className="px-4 py-3 text-muted text-xs">
                            {lap.session_date
                              ? new Date(lap.session_date).toLocaleDateString('en-US', {
                                  month: '2-digit',
                                  day: '2-digit',
                                  year: 'numeric'
                                })
                              : 'N/A'
                            }
                          </td>
                          <td className="px-4 py-3 text-accent">
                            {lap.position_after_lap ? `P${lap.position_after_lap}` : 'N/A'}
                          </td>
                          <td className="px-4 py-3 text-center">
                            {lap.pit_this_lap ? (
                              <Wrench size={14} className="text-accent inline" aria-label="Pit stop" />
                            ) : (
                              <span className="text-muted">-</span>
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
                    <div className="text-muted text-sm">
                      Showing {allLapsPage * allLapsPerPage + 1} - {Math.min((allLapsPage + 1) * allLapsPerPage, allLapsTotalCount)} of {allLapsTotalCount} laps
                    </div>
                    <div className="flex gap-2">
                      <button
                        onClick={() => setAllLapsPage(Math.max(0, allLapsPage - 1))}
                        disabled={allLapsPage === 0}
                        className="px-4 py-2 bg-surface-2 text-ink hover:bg-line transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
                      >
                        Previous
                      </button>
                      <button
                        onClick={() => setAllLapsPage(allLapsPage + 1)}
                        disabled={(allLapsPage + 1) * allLapsPerPage >= allLapsTotalCount}
                        className="px-4 py-2 bg-surface-2 text-ink hover:bg-line transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
                      >
                        Next
                      </button>
                    </div>
                  </div>
                )}
              </>
            ) : (
              <div className="text-center text-muted py-8">
                No lap data found for this team.
              </div>
            )}
          </div>
        )}

        {/* Comparison Charts */}
        {comparisonData.length >= 2 && (
          <div className="space-y-6">
            {/* Best Lap Time Comparison */}
            <div className="bg-surface p-6 border border-line">
              <h2 className="text-xl font-semibold text-ink mb-4">Best Lap Time Comparison</h2>
              <ResponsiveContainer width="100%" height={300}>
                <BarChart data={comparisonData}>
                  <CartesianGrid strokeDasharray="3 3" stroke={CHART.grid} />
                  <XAxis dataKey="team_name" stroke={CHART.axis} />
                  <YAxis stroke={CHART.axis} />
                  <Tooltip
                    contentStyle={{ backgroundColor: CHART.tooltipBg, border: `1px solid ${CHART.grid}`, color: CHART.ink }}
                    labelStyle={{ color: CHART.ink }}
                  />
                  <Legend />
                  <Bar dataKey="best_lap_time" fill={seriesColor(2)} name="Best Lap Time" />
                </BarChart>
              </ResponsiveContainer>
            </div>

            {/* Average Lap Time Comparison */}
            <div className="bg-surface p-6 border border-line">
              <h2 className="text-xl font-semibold text-ink mb-4">Average Lap Time Comparison</h2>
              <ResponsiveContainer width="100%" height={300}>
                <BarChart data={comparisonData}>
                  <CartesianGrid strokeDasharray="3 3" stroke={CHART.grid} />
                  <XAxis dataKey="team_name" stroke={CHART.axis} />
                  <YAxis stroke={CHART.axis} />
                  <Tooltip
                    contentStyle={{ backgroundColor: CHART.tooltipBg, border: `1px solid ${CHART.grid}`, color: CHART.ink }}
                    labelStyle={{ color: CHART.ink }}
                  />
                  <Legend />
                  <Bar dataKey="avg_lap_seconds" fill={seriesColor(3)} name="Avg Lap Time (s)" />
                </BarChart>
              </ResponsiveContainer>
            </div>

            {/* Lap Times Comparison with Stint Selector */}
            {Object.keys(lapDetails).length > 0 && (
              <>
                {/* Stint Selector */}
                <div className="bg-surface p-6 border border-line">
                  <h2 className="text-xl font-semibold text-ink mb-4">Select Stint or Lap Range</h2>

                  {/* Stint Dropdown */}
                  {teamStints.length > 0 && (
                    <div className="mb-4">
                      <label className="text-muted text-sm mb-2 block">Quick Select Stint</label>
                      <select
                        value={selectedStint}
                        onChange={(e) => handleStintSelection(e.target.value)}
                        className="w-full px-4 py-2 bg-surface-2 text-ink border border-line-strong"
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
                      <label className="text-muted text-sm mb-2 block">Start Lap</label>
                      <input
                        type="number"
                        value={stintStart}
                        onChange={(e) => {
                          setStintStart(parseInt(e.target.value) || 1);
                          setSelectedStint(''); // Clear stint selection when manually changing
                        }}
                        className="w-full px-4 py-2 bg-surface-2 text-ink border border-line-strong"
                        min={1}
                      />
                    </div>
                    <div>
                      <label className="text-muted text-sm mb-2 block">End Lap</label>
                      <input
                        type="number"
                        value={stintEnd}
                        onChange={(e) => {
                          setStintEnd(parseInt(e.target.value) || 50);
                          setSelectedStint(''); // Clear stint selection when manually changing
                        }}
                        className="w-full px-4 py-2 bg-surface-2 text-ink border border-line-strong"
                        min={stintStart}
                      />
                    </div>
                  </div>
                  <div className="mt-3 text-sm text-muted">
                    Showing {stintEnd - stintStart + 1} laps (Lap {stintStart} to {stintEnd})
                  </div>
                </div>

                {/* Selected Stint Lap Times */}
                <div className="bg-surface p-6 border border-line">
                  <h2 className="text-xl font-semibold text-ink mb-4">
                    Lap Times Comparison (Laps {stintStart}-{stintEnd})
                  </h2>
                  <ResponsiveContainer width="100%" height={400}>
                    <LineChart>
                      <CartesianGrid strokeDasharray="3 3" stroke={CHART.grid} />
                      <XAxis
                        dataKey="lap_number"
                        type="number"
                        domain={[stintStart, stintEnd]}
                        stroke={CHART.axis}
                        label={{ value: 'Lap Number', position: 'insideBottom', offset: -5 }}
                      />
                      <YAxis
                        stroke={CHART.axis}
                        domain={['dataMin - 2', 'dataMax + 2']}
                        label={{ value: 'Lap Time', angle: -90, position: 'insideLeft' }}
                      />
                      <Tooltip
                        contentStyle={{ backgroundColor: CHART.tooltipBg, border: `1px solid ${CHART.grid}`, color: CHART.ink }}
                        labelStyle={{ color: CHART.ink }}
                        formatter={(value: number) => [formatLapTime(value), 'Lap Time']}
                      />
                      <Legend />
                      {Object.entries(lapDetails).map(([teamName, laps], idx) => {
                        const colors = [seriesColor(2), seriesColor(3), seriesColor(1), seriesColor(0), seriesColor(4)];
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
                <div className="bg-surface p-6 border border-line">
                  <h2 className="text-xl font-semibold text-ink mb-4">
                    Full Race Pace (10-Lap Rolling Average)
                  </h2>
                  <ResponsiveContainer width="100%" height={500}>
                    <LineChart>
                      <CartesianGrid strokeDasharray="3 3" stroke={CHART.grid} />
                      <XAxis
                        dataKey="lap_number"
                        type="number"
                        stroke={CHART.axis}
                        label={{ value: 'Lap Number', position: 'insideBottom', offset: -5 }}
                      />
                      <YAxis
                        stroke={CHART.axis}
                        domain={['dataMin - 1', 'dataMax + 1']}
                        label={{ value: 'Average Lap Time', angle: -90, position: 'insideLeft' }}
                      />
                      <Tooltip
                        contentStyle={{ backgroundColor: CHART.tooltipBg, border: `1px solid ${CHART.grid}`, color: CHART.ink }}
                        labelStyle={{ color: CHART.ink }}
                        formatter={(value: number) => [formatLapTime(value), '10-Lap Avg']}
                      />
                      <Legend />
                      {Object.entries(lapDetails).map(([teamName, laps], idx) => {
                        const colors = [seriesColor(2), seriesColor(3), seriesColor(1), seriesColor(0), seriesColor(4)];
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
                  <div className="mt-4 text-sm text-muted">
                    This chart shows the 10-lap rolling average to smooth out pit stops and traffic effects.
                    Lower is faster.
                  </div>
                </div>

                {/* Lap-by-Lap Comparison Table */}
                {selectedTeams.length === 2 && (
                  <div className="bg-surface p-6 border border-line">
                    <h2 className="text-xl font-semibold text-ink mb-4">
                      Lap-by-Lap Comparison
                    </h2>
                    <div className="text-sm text-muted mb-4">
                      Total laps: Team 1: {lapDetails[selectedTeams[0]]?.length || 0},
                      Team 2: {lapDetails[selectedTeams[1]]?.length || 0}
                    </div>
                    <div className="overflow-x-auto max-h-[600px] overflow-y-auto">
                      <table className="tabular w-full text-sm">
                        <thead className="sticky top-0 bg-surface-2">
                          <tr className="text-left border-b border-line">
                            <th className="px-4 py-3 text-ink">Lap</th>
                            <th className="px-4 py-3 text-info">{selectedTeams[0]}</th>
                            <th className="px-4 py-3 text-live">{selectedTeams[1]}</th>
                            <th className="px-4 py-3 text-accent">Delta</th>
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
                                <tr key={i} className="border-b border-line hover:bg-surface">
                                  <td className="px-4 py-2 text-ink font-medium">{lapNum}</td>
                                  <td className={`px-4 py-2 ${team1IsPit ? 'text-accent font-bold' : 'text-info'}`}>
                                    {team1Time ? formatLapTime(team1Time) : '-'}
                                  </td>
                                  <td className={`px-4 py-2 ${team2IsPit ? 'text-accent font-bold' : 'text-live'}`}>
                                    {team2Time ? formatLapTime(team2Time) : '-'}
                                  </td>
                                  <td className={`px-4 py-2 font-medium ${
                                    !delta ? 'text-muted' :
                                    delta > 0 ? 'text-alarm' : 'text-live'
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
                    <div className="mt-4 text-sm text-muted">
                      <span className="text-accent font-bold">Orange</span> indicates pit lap (≥3:45).
                      Delta: positive means {selectedTeams[0]} was slower, negative means faster.
                    </div>
                  </div>
                )}
              </>
            )}
          </div>
        )}

        {loadingStats && (
          <div className="text-center text-ink py-8">
            Loading team statistics...
          </div>
        )}

        {selectedTeams.length === 0 && (
          <div className="text-center text-muted py-12">
            <p className="text-lg">Search for teams above to start analyzing and comparing data</p>
          </div>
        )}

        {/* Delete Confirmation Dialog */}
        {deleteDialogOpen && teamToDelete && (
          <div className="fixed inset-0 bg-scrim flex items-center justify-center z-50">
            <div className="bg-surface p-6 max-w-md w-full mx-4 border border-line">
              <h3 className="text-xl font-semibold text-ink mb-4">Delete Best Lap?</h3>
              <p className="text-ink mb-6">
                Are you sure you want to delete the best lap time of{' '}
                <span className="font-bold text-info">{teamToDelete.bestLap}</span> for team{' '}
                <span className="font-bold text-info capitalize">{teamToDelete.name}</span>?
                <br /><br />
                This will make the second-best lap the new best lap time.
              </p>
              <div className="flex gap-4 justify-end">
                <button
                  onClick={cancelDeleteBestLap}
                  disabled={deletingLap}
                  className="px-4 py-2 bg-line text-ink hover:bg-line transition-colors disabled:opacity-50"
                >
                  Cancel
                </button>
                <button
                  onClick={confirmDeleteBestLap}
                  disabled={deletingLap}
                  className="px-4 py-2 bg-alarm text-on-signal hover:bg-alarm transition-colors disabled:opacity-50"
                >
                  {deletingLap ? 'Deleting...' : 'Delete'}
                </button>
              </div>
            </div>
          </div>
        )}
        </>
        )}
    </PageShell>
  );
}

// ============================================================================
// Track Fairness Leaderboard panel
// ============================================================================
