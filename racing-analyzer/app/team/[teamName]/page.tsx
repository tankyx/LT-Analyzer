'use client';

import { useEffect, useRef, useState } from 'react';
import { useRouter, useParams } from 'next/navigation';
import {
  BarChart,
  Bar,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
  LineChart,
  Line,
  Legend,
  ReferenceLine,
} from 'recharts';
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

interface TrackBest {
  track_id: number;
  track_name: string;
  best_lap: string | null;
  best_lap_seconds: number;
  session_id: number;
  session_date: string;
}

interface OverallStats {
  total_sessions: number;
  total_laps: number;
  tracks_raced: number;
  bests_by_track: TrackBest[];
}

interface SessionLap {
  lap_number: number;
  lap_time: string;
  timestamp: string;
  pit_this_lap: boolean;
  position_after_lap: number;
}

interface ConsistencySession {
  session_id: number;
  session_name: string;
  session_date: string;
  track_id: number;
  track_name: string;
  total_laps: number;
  clean_laps: number;
  pit_laps: number;
  best_lap: string | null;
  best_lap_seconds: number;
  mean_lap_seconds: number;
  median_lap_seconds: number;
  stddev_seconds: number;
  cov: number;
  pct_within_0_5s: number;
  pct_within_1s: number;
  pct_within_2s: number;
}

interface ConsistencyResponse {
  driver_name: string;
  overall: {
    total_sessions: number;
    total_laps: number;
    tracks_raced: number;
    bests_by_track: TrackBest[];
    career_mean_seconds: number | null;
    career_stddev_seconds: number | null;
    career_cov: number | null;
  };
  sessions: ConsistencySession[];
  trend: Array<{ date: string; track_name: string; best: number; mean: number; stddev: number }>;
}

interface SprintSample {
  session_id: number;
  session_date: string;
  kart_number: number;
  kart_best_seconds: number;
  session_median_seconds: number;
  kart_factor: number;
  kart_rank: number;
  karts_in_session: number;
}

interface EnduranceSessionRow {
  session_id: number;
  session_date: string;
  driver_team_name: string;
  field_team_count: number;
  stint_count: number;
  stint_gaps: number[];
  mean_gap: number;
  stddev_gap: number;
  mean_percentile: number | null;
  stddev_percentile: number | null;
  flagged: boolean;
}

interface FairnessResponse {
  driver_name: string;
  track_id: number;
  track_name: string;
  min_sessions_threshold: number;
  sprint: {
    enabled: boolean;
    session_count: number;
    sample_count: number;
    samples: SprintSample[];
    mean_factor: number | null;
    stddev_factor: number | null;
    top_quartile_count: number;
    top_quartile_expected: number;
  };
  endurance: {
    enabled: boolean;
    session_count: number;
    sessions: EnduranceSessionRow[];
    flagged_count: number;
  };
}

interface Track {
  id: number;
  track_name: string;
}

interface AliasRow {
  id: number;
  canonical_name: string;
  alias_name: string;
  added_by: string | null;
  added_at: string | null;
}

interface AliasesResponse {
  canonical_names: string[];
  aliases: AliasRow[];
}

type TabKey = 'sessions' | 'consistency' | 'fairness';

const parseLapTime = (lapTime: string | null): number => {
  if (!lapTime) return Infinity;
  const parts = lapTime.split(':');
  if (parts.length === 2) {
    return parseInt(parts[0]) * 60 + parseFloat(parts[1]);
  }
  return parseFloat(lapTime);
};

export default function TeamProfilePage() {
  const { user, loading: authLoading } = useAuth();
  const router = useRouter();
  const params = useParams();
  const teamName = decodeURIComponent(params.teamName as string);

  const [activeTab, setActiveTab] = useState<TabKey>('sessions');

  // Sessions tab state
  const [sessions, setSessions] = useState<TeamSession[]>([]);
  const [overallStats, setOverallStats] = useState<OverallStats | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [selectedTrack, setSelectedTrack] = useState<number | null>(null);
  const [sortBy, setSortBy] = useState<'date' | 'track' | 'laps' | 'best_lap'>('date');
  const [sortOrder, setSortOrder] = useState<'asc' | 'desc'>('desc');
  const [expandedSession, setExpandedSession] = useState<{ trackId: number; sessionId: number } | null>(null);
  const [sessionLaps, setSessionLaps] = useState<SessionLap[]>([]);
  const [loadingLaps, setLoadingLaps] = useState(false);
  const sessionLapsReqId = useRef(0);

  // Consistency tab state
  const [consistency, setConsistency] = useState<ConsistencyResponse | null>(null);
  const [loadingConsistency, setLoadingConsistency] = useState(false);
  const [consistencyError, setConsistencyError] = useState<string | null>(null);

  // Fairness tab state
  const [tracks, setTracks] = useState<Track[]>([]);
  const [fairnessTrackId, setFairnessTrackId] = useState<number | null>(null);
  const [fairness, setFairness] = useState<FairnessResponse | null>(null);
  const [loadingFairness, setLoadingFairness] = useState(false);
  const [fairnessError, setFairnessError] = useState<string | null>(null);

  // Aliases
  const [aliases, setAliases] = useState<AliasesResponse | null>(null);
  const [aliasesError, setAliasesError] = useState<string | null>(null);
  const [newAlias, setNewAlias] = useState('');
  const [aliasBusy, setAliasBusy] = useState(false);

  const reloadAliases = async () => {
    try {
      const res = await ApiService.getDriverAliases(teamName);
      setAliases(res);
      setAliasesError(null);
    } catch (err) {
      setAliasesError(err instanceof Error ? err.message : 'Failed to load aliases');
    }
  };

  useEffect(() => {
    if (!authLoading && !user) {
      router.push('/login');
    }
  }, [user, authLoading, router]);

  // Fetch cross-track sessions (Sessions tab data — also used for tab 1 header stats)
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

  // Fetch aliases on mount/teamName change
  useEffect(() => {
    if (!teamName) return;
    let cancelled = false;
    ApiService.getDriverAliases(teamName)
      .then(res => {
        if (cancelled) return;
        setAliases(res);
      })
      .catch(err => {
        if (cancelled) return;
        setAliasesError(err instanceof Error ? err.message : 'Failed to load aliases');
      });
    return () => {
      cancelled = true;
    };
  }, [teamName]);

  // Fetch list of tracks for the fairness selector
  useEffect(() => {
    let cancelled = false;
    ApiService.getTracks()
      .then(res => {
        if (cancelled) return;
        const list: Track[] = (res.tracks || res || []).map((t: { id: number; track_name: string }) => ({
          id: t.id,
          track_name: t.track_name,
        }));
        setTracks(list);
        if (list.length > 0 && fairnessTrackId === null) {
          setFairnessTrackId(list[0].id);
        }
      })
      .catch(err => console.error('Error fetching tracks:', err));
    return () => {
      cancelled = true;
    };
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  // Lazy-load consistency data when tab first opened. Keyed by teamName so a
  // different driver reloads; ref-guards avoid re-triggering from the state
  // updates the effect itself performs.
  const consistencyLoadedFor = useRef<string | null>(null);
  useEffect(() => {
    if (activeTab !== 'consistency') return;
    if (consistencyLoadedFor.current === teamName) return;
    consistencyLoadedFor.current = teamName;
    let cancelled = false;
    setLoadingConsistency(true);
    setConsistencyError(null);
    setConsistency(null);
    ApiService.getDriverConsistency(teamName)
      .then(res => {
        if (cancelled) return;
        setConsistency(res);
      })
      .catch(err => {
        if (cancelled) return;
        consistencyLoadedFor.current = null; // allow retry
        setConsistencyError(err instanceof Error ? err.message : 'Failed to load consistency');
      })
      .finally(() => {
        if (!cancelled) setLoadingConsistency(false);
      });
    return () => {
      cancelled = true;
    };
  }, [activeTab, teamName]);

  // Lazy-load fairness when tab opened or track changes. Keyed by (team, track).
  const fairnessLoadedFor = useRef<string | null>(null);
  useEffect(() => {
    if (activeTab !== 'fairness' || !fairnessTrackId) return;
    const key = `${teamName}__${fairnessTrackId}`;
    if (fairnessLoadedFor.current === key) return;
    fairnessLoadedFor.current = key;
    let cancelled = false;
    setLoadingFairness(true);
    setFairnessError(null);
    setFairness(null);
    ApiService.getDriverFairness(teamName, fairnessTrackId)
      .then(res => {
        if (cancelled) return;
        setFairness(res);
      })
      .catch(err => {
        if (cancelled) return;
        fairnessLoadedFor.current = null;
        setFairnessError(err instanceof Error ? err.message : 'Failed to load fairness');
      })
      .finally(() => {
        if (!cancelled) setLoadingFairness(false);
      });
    return () => {
      cancelled = true;
    };
  }, [activeTab, teamName, fairnessTrackId]);

  // Sessions tab helpers
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
          comparison = parseLapTime(a.best_lap) - parseLapTime(b.best_lap);
          break;
      }
      return sortOrder === 'asc' ? comparison : -comparison;
    });

  const uniqueTracks = Array.from(new Set(sessions.map(s => s.track_id)))
    .map(trackId => {
      const s = sessions.find(x => x.track_id === trackId);
      return { id: trackId, name: s?.track_name || '' };
    })
    .sort((a, b) => a.name.localeCompare(b.name));

  const handleSort = (column: 'date' | 'track' | 'laps' | 'best_lap') => {
    if (sortBy === column) {
      setSortOrder(sortOrder === 'asc' ? 'desc' : 'asc');
    } else {
      setSortBy(column);
      setSortOrder('desc');
    }
  };

  const toggleSessionLaps = async (trackId: number, sessionId: number) => {
    if (expandedSession?.trackId === trackId && expandedSession?.sessionId === sessionId) {
      sessionLapsReqId.current += 1;
      setExpandedSession(null);
      setSessionLaps([]);
      return;
    }
    const reqId = ++sessionLapsReqId.current;
    setExpandedSession({ trackId, sessionId });
    setLoadingLaps(true);
    try {
      const result = await ApiService.getSessionLaps(teamName, trackId, sessionId);
      if (reqId !== sessionLapsReqId.current) return;
      setSessionLaps(result.laps || []);
    } catch (err) {
      if (reqId !== sessionLapsReqId.current) return;
      console.error('Error fetching session laps:', err);
      setSessionLaps([]);
    } finally {
      if (reqId === sessionLapsReqId.current) setLoadingLaps(false);
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

  const TabButton = ({ tab, label }: { tab: TabKey; label: string }) => (
    <button
      onClick={() => setActiveTab(tab)}
      className={`px-4 py-2 text-sm font-medium border-b-2 transition-colors ${
        activeTab === tab
          ? 'text-white border-blue-400'
          : 'text-gray-400 border-transparent hover:text-gray-200'
      }`}
    >
      {label}
    </button>
  );

  return (
    <div className="min-h-screen bg-gradient-to-br from-gray-900 via-gray-800 to-gray-900 p-6">
      <div className="max-w-7xl mx-auto">
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

        {overallStats && (
          <div className="bg-gray-800 rounded-lg p-6 mb-6">
            <h2 className="text-2xl font-semibold text-white mb-4">Overall Statistics</h2>
            <div className="grid grid-cols-1 md:grid-cols-3 gap-4 mb-4">
              <StatCard label="Total Sessions" value={overallStats.total_sessions} color="text-blue-400" />
              <StatCard label="Total Laps" value={overallStats.total_laps} color="text-green-400" />
              <StatCard label="Tracks Raced" value={overallStats.tracks_raced} color="text-yellow-400" />
            </div>
            {overallStats.bests_by_track && overallStats.bests_by_track.length > 0 && (
              <div>
                <h3 className="text-sm uppercase tracking-wide text-gray-400 mb-2">Best Lap by Track</h3>
                <div className="grid grid-cols-2 md:grid-cols-4 gap-2">
                  {overallStats.bests_by_track.map(b => (
                    <div key={b.track_id} className="bg-gray-700 rounded-lg px-3 py-2">
                      <div className="text-xs text-gray-400">{b.track_name}</div>
                      <div className="text-lg font-bold text-purple-300">{b.best_lap || 'N/A'}</div>
                    </div>
                  ))}
                </div>
                <p className="text-xs text-gray-500 mt-2">
                  Laps on different tracks aren&apos;t comparable, so best times are shown per track.
                </p>
              </div>
            )}
          </div>
        )}

        <AliasPanel
          teamName={teamName}
          aliases={aliases}
          error={aliasesError}
          isAdmin={user?.role === 'admin'}
          newAlias={newAlias}
          setNewAlias={setNewAlias}
          busy={aliasBusy}
          onAdd={async () => {
            if (!newAlias.trim() || !aliases) return;
            const canonical = aliases.canonical_names[0] || teamName;
            setAliasBusy(true);
            try {
              await ApiService.addDriverAlias(canonical, newAlias.trim());
              setNewAlias('');
              await reloadAliases();
            } catch (err) {
              setAliasesError(err instanceof Error ? err.message : 'Failed to add alias');
            } finally {
              setAliasBusy(false);
            }
          }}
          onDelete={async (id: number) => {
            if (!confirm('Delete this alias?')) return;
            setAliasBusy(true);
            try {
              await ApiService.deleteDriverAlias(id);
              await reloadAliases();
            } catch (err) {
              setAliasesError(err instanceof Error ? err.message : 'Failed to delete alias');
            } finally {
              setAliasBusy(false);
            }
          }}
        />

        <div className="border-b border-gray-700 mb-4 flex gap-2">
          <TabButton tab="sessions" label="Sessions" />
          <TabButton tab="consistency" label="Consistency" />
          <TabButton tab="fairness" label="Kart Fairness" />
        </div>

        {activeTab === 'sessions' && (
          <SessionsTab
            sessions={filteredAndSortedSessions}
            uniqueTracks={uniqueTracks}
            selectedTrack={selectedTrack}
            setSelectedTrack={setSelectedTrack}
            sortBy={sortBy}
            sortOrder={sortOrder}
            onSort={handleSort}
            expandedSession={expandedSession}
            sessionLaps={sessionLaps}
            loadingLaps={loadingLaps}
            onToggle={toggleSessionLaps}
          />
        )}

        {activeTab === 'consistency' && (
          <ConsistencyTab
            loading={loadingConsistency}
            error={consistencyError}
            data={consistency}
          />
        )}

        {activeTab === 'fairness' && (
          <FairnessTab
            loading={loadingFairness}
            error={fairnessError}
            data={fairness}
            tracks={tracks}
            trackId={fairnessTrackId}
            setTrackId={setFairnessTrackId}
          />
        )}
      </div>
    </div>
  );
}

interface AliasSuggestion {
  name: string;
  classes: string;
  track_names: string[];
  track_count: number;
  via_alias: boolean;
}

function AliasPanel({
  teamName,
  aliases,
  error,
  isAdmin,
  newAlias,
  setNewAlias,
  busy,
  onAdd,
  onDelete,
}: {
  teamName: string;
  aliases: AliasesResponse | null;
  error: string | null;
  isAdmin: boolean;
  newAlias: string;
  setNewAlias: (v: string) => void;
  busy: boolean;
  onAdd: () => void;
  onDelete: (id: number) => void;
}) {
  const hasGroup = aliases && (aliases.aliases.length > 0 || aliases.canonical_names.length > 1);
  const canonical = aliases?.canonical_names[0] || teamName;
  const viewingIsCanonical = canonical.toLowerCase() === teamName.toLowerCase();

  const [suggestions, setSuggestions] = useState<AliasSuggestion[]>([]);
  const [searching, setSearching] = useState(false);
  const [showSuggestions, setShowSuggestions] = useState(false);
  const searchReqId = useRef(0);

  useEffect(() => {
    const q = newAlias.trim();
    if (q.length < 2) {
      setSuggestions([]);
      setSearching(false);
      return;
    }
    const reqId = ++searchReqId.current;
    setSearching(true);
    const t = setTimeout(() => {
      ApiService.searchTeamsAllTracks(q, 10)
        .then(res => {
          if (reqId !== searchReqId.current) return;
          setSuggestions(res.teams || []);
        })
        .catch(() => {
          if (reqId !== searchReqId.current) return;
          setSuggestions([]);
        })
        .finally(() => {
          if (reqId === searchReqId.current) setSearching(false);
        });
    }, 200);
    return () => clearTimeout(t);
  }, [newAlias]);

  const pickSuggestion = (s: AliasSuggestion) => {
    setNewAlias(s.name);
    setShowSuggestions(false);
  };

  const existingAliasNames = new Set([
    canonical.toLowerCase(),
    ...(aliases?.aliases.map(a => a.alias_name.toLowerCase()) || []),
  ]);

  return (
    <div className="bg-gray-800 rounded-lg p-4 mb-6">
      <div className="flex items-center justify-between mb-2">
        <h3 className="text-sm font-semibold text-gray-200 uppercase tracking-wide">Aliases</h3>
        {aliases && !viewingIsCanonical && (
          <span className="text-xs text-gray-400">
            Canonical: <span className="text-blue-300">{canonical}</span>
          </span>
        )}
      </div>

      {error && <div className="text-xs text-red-300 mb-2">{error}</div>}

      {hasGroup ? (
        <div className="flex flex-wrap gap-2 mb-2">
          {aliases!.aliases.map(a => (
            <span
              key={a.id}
              className="inline-flex items-center gap-2 px-2 py-1 rounded-full bg-gray-700 text-xs text-gray-200"
              title={a.added_by ? `added by ${a.added_by}` : undefined}
            >
              {a.alias_name}
              {isAdmin && (
                <button
                  onClick={() => onDelete(a.id)}
                  disabled={busy}
                  className="text-red-400 hover:text-red-300 disabled:opacity-50"
                  aria-label={`Remove alias ${a.alias_name}`}
                >
                  ✕
                </button>
              )}
            </span>
          ))}
        </div>
      ) : (
        <div className="text-xs text-gray-500 mb-2">
          No aliases configured{isAdmin ? '. Search the database below to merge a driver record (e.g. "SIMON R4B" → "DELVENNE Simon").' : '.'}
        </div>
      )}

      {isAdmin && (
        <div className="relative">
          <div className="flex gap-2 mt-2">
            <div className="flex-1 relative">
              <input
                type="text"
                value={newAlias}
                onChange={e => {
                  setNewAlias(e.target.value);
                  setShowSuggestions(true);
                }}
                onFocus={() => setShowSuggestions(true)}
                onBlur={() => setTimeout(() => setShowSuggestions(false), 150)}
                placeholder={`Search for a name to alias to "${canonical}"`}
                className="w-full px-3 py-1.5 bg-gray-700 text-white text-sm rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500"
                onKeyDown={e => {
                  if (e.key === 'Enter' && !showSuggestions) onAdd();
                }}
              />
              {searching && (
                <span className="absolute right-3 top-1.5 text-xs text-gray-400">...</span>
              )}
            </div>
            <button
              onClick={onAdd}
              disabled={busy || !newAlias.trim()}
              className="px-3 py-1.5 bg-blue-600 hover:bg-blue-700 disabled:opacity-50 text-white text-sm rounded-lg"
            >
              {busy ? '...' : 'Add'}
            </button>
          </div>

          {showSuggestions && suggestions.length > 0 && (
            <div className="absolute z-10 left-0 right-0 mt-1 bg-gray-900 border border-gray-700 rounded-lg max-h-72 overflow-y-auto shadow-xl">
              {suggestions.map((s) => {
                const already = existingAliasNames.has(s.name.toLowerCase());
                return (
                  <button
                    key={s.name}
                    onMouseDown={(e) => e.preventDefault()}
                    onClick={() => pickSuggestion(s)}
                    disabled={already}
                    className={`w-full text-left px-3 py-2 text-sm border-b border-gray-800 last:border-b-0 ${
                      already ? 'opacity-40 cursor-not-allowed' : 'hover:bg-gray-800 cursor-pointer'
                    }`}
                  >
                    <div className="flex items-center justify-between gap-2">
                      <span className="text-white">{s.name}</span>
                      <span className="text-xs text-gray-500">
                        {s.via_alias && !s.track_count ? 'alias record' : `${s.track_count} track${s.track_count === 1 ? '' : 's'}`}
                      </span>
                    </div>
                    {s.track_names.length > 0 && (
                      <div className="text-xs text-gray-500 mt-0.5">
                        {s.track_names.join(' · ')}
                        {s.classes && <span className="ml-2">· Classes: {s.classes}</span>}
                      </div>
                    )}
                    {already && <div className="text-xs text-yellow-400 mt-0.5">already in this group</div>}
                  </button>
                );
              })}
            </div>
          )}

          {showSuggestions && !searching && newAlias.trim().length >= 2 && suggestions.length === 0 && (
            <div className="absolute z-10 left-0 right-0 mt-1 bg-gray-900 border border-gray-700 rounded-lg px-3 py-2 text-xs text-gray-500">
              No matches. You can still add it as a free-form alias.
            </div>
          )}
        </div>
      )}
    </div>
  );
}

function StatCard({ label, value, color }: { label: string; value: string | number; color: string }) {
  return (
    <div className="bg-gray-700 rounded-lg p-4">
      <div className="text-gray-400 text-sm mb-1">{label}</div>
      <div className={`text-3xl font-bold ${color}`}>{value}</div>
    </div>
  );
}

// ============================================================================
// Sessions tab
// ============================================================================

function SessionsTab({
  sessions,
  uniqueTracks,
  selectedTrack,
  setSelectedTrack,
  sortBy,
  sortOrder,
  onSort,
  expandedSession,
  sessionLaps,
  loadingLaps,
  onToggle,
}: {
  sessions: TeamSession[];
  uniqueTracks: { id: number; name: string }[];
  selectedTrack: number | null;
  setSelectedTrack: (v: number | null) => void;
  sortBy: 'date' | 'track' | 'laps' | 'best_lap';
  sortOrder: 'asc' | 'desc';
  onSort: (col: 'date' | 'track' | 'laps' | 'best_lap') => void;
  expandedSession: { trackId: number; sessionId: number } | null;
  sessionLaps: SessionLap[];
  loadingLaps: boolean;
  onToggle: (trackId: number, sessionId: number) => void;
}) {
  return (
    <div className="bg-gray-800 rounded-lg p-6">
      <div className="flex items-center justify-between mb-4">
        <h2 className="text-2xl font-semibold text-white">Session History</h2>
        <div className="flex items-center gap-2">
          <label className="text-gray-400 text-sm">Filter by Track:</label>
          <select
            value={selectedTrack || ''}
            onChange={e => setSelectedTrack(e.target.value ? parseInt(e.target.value) : null)}
            className="px-4 py-2 bg-gray-700 text-white rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500"
          >
            <option value="">All Tracks</option>
            {uniqueTracks.map(track => (
              <option key={track.id} value={track.id}>{track.name}</option>
            ))}
          </select>
        </div>
      </div>

      {sessions.length > 0 ? (
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead className="bg-gray-700">
              <tr className="text-left border-b border-gray-600">
                <th className="px-4 py-3 text-gray-300 cursor-pointer hover:text-white" onClick={() => onSort('date')}>
                  Date {sortBy === 'date' && (sortOrder === 'asc' ? '↑' : '↓')}
                </th>
                <th className="px-4 py-3 text-gray-300 cursor-pointer hover:text-white" onClick={() => onSort('track')}>
                  Track {sortBy === 'track' && (sortOrder === 'asc' ? '↑' : '↓')}
                </th>
                <th className="px-4 py-3 text-gray-300">Session</th>
                <th className="px-4 py-3 text-gray-300 cursor-pointer hover:text-white" onClick={() => onSort('laps')}>
                  Total Laps {sortBy === 'laps' && (sortOrder === 'asc' ? '↑' : '↓')}
                </th>
                <th className="px-4 py-3 text-gray-300 cursor-pointer hover:text-white" onClick={() => onSort('best_lap')}>
                  Best Lap {sortBy === 'best_lap' && (sortOrder === 'asc' ? '↑' : '↓')}
                </th>
                <th className="px-4 py-3 text-gray-300">Avg Lap</th>
              </tr>
            </thead>
            <tbody>
              {sessions.map((session, index) => {
                const isExpanded = expandedSession?.trackId === session.track_id && expandedSession?.sessionId === session.session_id;
                return (
                  <>
                    <tr
                      key={`${session.track_id}-${session.session_id}-${index}`}
                      className="border-b border-gray-700 hover:bg-gray-700 transition-colors cursor-pointer"
                      onClick={() => onToggle(session.track_id, session.session_id)}
                    >
                      <td className="px-4 py-3 text-gray-400">
                        <span className="mr-2">{isExpanded ? '▼' : '▶'}</span>
                        {session.session_date
                          ? new Date(session.session_date).toLocaleDateString('en-US', { month: '2-digit', day: '2-digit', year: 'numeric' })
                          : 'N/A'}
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
                            <div className="text-center text-gray-400 py-4">Loading laps...</div>
                          ) : sessionLaps.length > 0 ? (
                            <div className="max-h-96 overflow-y-auto">
                              <h4 className="text-white font-semibold mb-2">Lap Details ({sessionLaps.length} laps)</h4>
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
                                      <td className="px-3 py-2 text-orange-300">{lap.pit_this_lap ? '🔧 Pit' : ''}</td>
                                      <td className="px-3 py-2 text-gray-400">
                                        {lap.timestamp ? new Date(lap.timestamp).toLocaleTimeString() : 'N/A'}
                                      </td>
                                    </tr>
                                  ))}
                                </tbody>
                              </table>
                            </div>
                          ) : (
                            <div className="text-center text-gray-400 py-4">No lap data available for this session</div>
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
          {selectedTrack ? 'No sessions found for this track.' : 'No sessions found for this team.'}
        </div>
      )}
    </div>
  );
}

// ============================================================================
// Consistency tab
// ============================================================================

function ConsistencyTab({
  loading,
  error,
  data,
}: {
  loading: boolean;
  error: string | null;
  data: ConsistencyResponse | null;
}) {
  if (loading) {
    return <div className="bg-gray-800 rounded-lg p-6 text-gray-300">Loading consistency stats...</div>;
  }
  if (error) {
    return <div className="bg-red-900 rounded-lg p-6 text-red-200">{error}</div>;
  }
  if (!data || data.sessions.length === 0) {
    return <div className="bg-gray-800 rounded-lg p-6 text-gray-400">No consistency data available.</div>;
  }

  const trendData = data.trend.map(t => ({
    date: t.date ? new Date(t.date).toLocaleDateString('en-US', { month: 'short', day: 'numeric' }) : '',
    stddev: t.stddev,
    best: t.best,
  }));

  const barData = data.sessions.slice(0, 20).map(s => ({
    label: `${s.track_name.slice(0, 6)} ${s.session_date ? new Date(s.session_date).toLocaleDateString('en-US', { month: '2-digit', day: '2-digit' }) : ''}`,
    stddev: s.stddev_seconds,
    cov: +(s.cov * 100).toFixed(2),
    clean: s.clean_laps,
  }));

  return (
    <div className="space-y-6">
      <div className="bg-gray-800 rounded-lg p-6">
        <h3 className="text-xl font-semibold text-white mb-4">Career Consistency</h3>
        <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
          <StatCard
            label="Career σ (s)"
            value={data.overall.career_stddev_seconds !== null ? data.overall.career_stddev_seconds.toFixed(2) : 'N/A'}
            color="text-blue-300"
          />
          <StatCard
            label="Career CoV"
            value={data.overall.career_cov !== null ? `${(data.overall.career_cov * 100).toFixed(2)}%` : 'N/A'}
            color="text-green-300"
          />
          <StatCard
            label="Career Mean (s)"
            value={data.overall.career_mean_seconds !== null ? data.overall.career_mean_seconds.toFixed(2) : 'N/A'}
            color="text-yellow-300"
          />
          <StatCard label="Sessions" value={data.overall.total_sessions} color="text-purple-300" />
        </div>
        <p className="text-xs text-gray-500 mt-3">
          Lower σ / CoV = steadier pace. Pit-in laps and clear outliers (&gt;3× median or &gt;3&nbsp;min) are excluded.
        </p>
      </div>

      <div className="bg-gray-800 rounded-lg p-6">
        <h3 className="text-xl font-semibold text-white mb-4">σ Over Time (older → newer)</h3>
        {trendData.length > 1 ? (
          <div className="h-64">
            <ResponsiveContainer width="100%" height="100%">
              <LineChart data={trendData}>
                <CartesianGrid strokeDasharray="3 3" stroke="#374151" />
                <XAxis dataKey="date" stroke="#9ca3af" tick={{ fontSize: 11 }} />
                <YAxis stroke="#9ca3af" tick={{ fontSize: 11 }} label={{ value: 'σ (s)', angle: -90, position: 'insideLeft', fill: '#9ca3af' }} />
                <Tooltip contentStyle={{ backgroundColor: '#1f2937', border: '1px solid #374151' }} labelStyle={{ color: '#d1d5db' }} />
                <Legend />
                <Line type="monotone" dataKey="stddev" stroke="#60a5fa" name="σ (s)" dot={false} />
              </LineChart>
            </ResponsiveContainer>
          </div>
        ) : (
          <div className="text-gray-400 text-sm">Not enough sessions to plot a trend yet.</div>
        )}
      </div>

      <div className="bg-gray-800 rounded-lg p-6">
        <h3 className="text-xl font-semibold text-white mb-4">Per-Session σ (last 20)</h3>
        <div className="h-72">
          <ResponsiveContainer width="100%" height="100%">
            <BarChart data={barData}>
              <CartesianGrid strokeDasharray="3 3" stroke="#374151" />
              <XAxis dataKey="label" stroke="#9ca3af" tick={{ fontSize: 10 }} interval={0} angle={-40} textAnchor="end" height={80} />
              <YAxis stroke="#9ca3af" tick={{ fontSize: 11 }} />
              <Tooltip contentStyle={{ backgroundColor: '#1f2937', border: '1px solid #374151' }} labelStyle={{ color: '#d1d5db' }} />
              <Bar dataKey="stddev" fill="#60a5fa" name="σ (s)" />
            </BarChart>
          </ResponsiveContainer>
        </div>
      </div>

      <div className="bg-gray-800 rounded-lg p-6">
        <h3 className="text-xl font-semibold text-white mb-4">Session Detail</h3>
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead className="bg-gray-700">
              <tr className="text-left">
                <th className="px-3 py-2 text-gray-300">Date</th>
                <th className="px-3 py-2 text-gray-300">Track</th>
                <th className="px-3 py-2 text-gray-300">Clean Laps</th>
                <th className="px-3 py-2 text-gray-300">Best</th>
                <th className="px-3 py-2 text-gray-300">σ (s)</th>
                <th className="px-3 py-2 text-gray-300">CoV</th>
                <th className="px-3 py-2 text-gray-300">Within 0.5s</th>
                <th className="px-3 py-2 text-gray-300">Within 1s</th>
                <th className="px-3 py-2 text-gray-300">Within 2s</th>
              </tr>
            </thead>
            <tbody>
              {data.sessions.map(s => (
                <tr key={`${s.track_id}-${s.session_id}`} className="border-b border-gray-700 hover:bg-gray-700">
                  <td className="px-3 py-2 text-gray-400">
                    {s.session_date ? new Date(s.session_date).toLocaleDateString('en-US', { month: '2-digit', day: '2-digit', year: '2-digit' }) : ''}
                  </td>
                  <td className="px-3 py-2 text-blue-300">{s.track_name}</td>
                  <td className="px-3 py-2 text-gray-300">{s.clean_laps} / {s.total_laps}</td>
                  <td className="px-3 py-2 text-green-300">{s.best_lap || 'N/A'}</td>
                  <td className="px-3 py-2 text-yellow-300">{s.stddev_seconds.toFixed(2)}</td>
                  <td className="px-3 py-2 text-yellow-300">{(s.cov * 100).toFixed(2)}%</td>
                  <td className="px-3 py-2 text-purple-300">{(s.pct_within_0_5s * 100).toFixed(0)}%</td>
                  <td className="px-3 py-2 text-purple-300">{(s.pct_within_1s * 100).toFixed(0)}%</td>
                  <td className="px-3 py-2 text-purple-300">{(s.pct_within_2s * 100).toFixed(0)}%</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}

// ============================================================================
// Fairness tab
// ============================================================================

function FairnessTab({
  loading,
  error,
  data,
  tracks,
  trackId,
  setTrackId,
}: {
  loading: boolean;
  error: string | null;
  data: FairnessResponse | null;
  tracks: Track[];
  trackId: number | null;
  setTrackId: (id: number) => void;
}) {
  return (
    <div className="space-y-6">
      <div className="bg-gray-800 rounded-lg p-4 flex items-center gap-3">
        <label className="text-gray-300 text-sm">Track:</label>
        <select
          value={trackId || ''}
          onChange={e => setTrackId(parseInt(e.target.value))}
          className="px-4 py-2 bg-gray-700 text-white rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500"
        >
          {tracks.map(t => (
            <option key={t.id} value={t.id}>{t.track_name}</option>
          ))}
        </select>
        <p className="text-xs text-gray-500 ml-3">
          Kart analysis is per-track. A minimum of {data?.min_sessions_threshold ?? 5} sessions is required before aggregate conclusions are shown.
        </p>
      </div>

      {loading && <div className="bg-gray-800 rounded-lg p-6 text-gray-300">Loading fairness analysis...</div>}
      {error && <div className="bg-red-900 rounded-lg p-6 text-red-200">{error}</div>}

      {data && !loading && (
        <>
          <SprintFairnessPanel block={data.sprint} threshold={data.min_sessions_threshold} />
          <EnduranceFairnessPanel block={data.endurance} threshold={data.min_sessions_threshold} />
        </>
      )}
    </div>
  );
}

function SprintFairnessPanel({ block, threshold }: { block: FairnessResponse['sprint']; threshold: number }) {
  const samples = block.samples;

  const buckets = [0.94, 0.96, 0.98, 1.00, 1.02, 1.04, 1.06];
  const histogram = buckets.slice(0, -1).map((lo, i) => {
    const hi = buckets[i + 1];
    const n = samples.filter(s => s.kart_factor >= lo && s.kart_factor < hi).length;
    return { range: `${lo.toFixed(2)}–${hi.toFixed(2)}`, count: n };
  });

  return (
    <div className="bg-gray-800 rounded-lg p-6">
      <div className="flex items-baseline justify-between mb-4">
        <h3 className="text-xl font-semibold text-white">Sprint — Kart Draw Fairness</h3>
        <span className={`text-xs px-2 py-1 rounded ${block.enabled ? 'bg-green-900 text-green-300' : 'bg-yellow-900 text-yellow-200'}`}>
          {block.enabled ? 'Aggregate enabled' : `Needs ≥ ${threshold} sprint sessions`}
        </span>
      </div>

      <p className="text-sm text-gray-400 mb-4">
        For each sprint race at this track, a <b>kart factor</b> is computed: kart’s best lap ÷ session median. &lt; 1.00 = fast kart,
        &gt; 1.00 = slow. A fair draw produces a factor distribution centred on 1.00. Consistently &lt;1.00 = suspiciously good karts.
      </p>

      <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-4">
        <StatCard label="Sessions" value={block.session_count} color="text-blue-300" />
        <StatCard label="Kart samples" value={block.sample_count} color="text-green-300" />
        <StatCard
          label="Mean factor"
          value={block.mean_factor !== null ? block.mean_factor.toFixed(4) : 'N/A'}
          color="text-yellow-300"
        />
        <StatCard
          label="Top-quartile karts"
          value={
            block.sample_count > 0
              ? `${block.top_quartile_count} / ${block.top_quartile_expected.toFixed(1)} expected`
              : 'N/A'
          }
          color="text-purple-300"
        />
      </div>

      {samples.length > 0 && (
        <>
          <div className="h-64 mb-4">
            <ResponsiveContainer width="100%" height="100%">
              <BarChart data={histogram}>
                <CartesianGrid strokeDasharray="3 3" stroke="#374151" />
                <XAxis dataKey="range" stroke="#9ca3af" tick={{ fontSize: 11 }} />
                <YAxis stroke="#9ca3af" tick={{ fontSize: 11 }} />
                <Tooltip contentStyle={{ backgroundColor: '#1f2937', border: '1px solid #374151' }} labelStyle={{ color: '#d1d5db' }} />
                <ReferenceLine x="1.00–1.02" stroke="#f59e0b" strokeDasharray="3 3" />
                <Bar dataKey="count" fill="#60a5fa" name="Kart samples" />
              </BarChart>
            </ResponsiveContainer>
          </div>

          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead className="bg-gray-700">
                <tr className="text-left">
                  <th className="px-3 py-2 text-gray-300">Date</th>
                  <th className="px-3 py-2 text-gray-300">Kart #</th>
                  <th className="px-3 py-2 text-gray-300">Rank</th>
                  <th className="px-3 py-2 text-gray-300">Factor</th>
                  <th className="px-3 py-2 text-gray-300">Kart best (s)</th>
                  <th className="px-3 py-2 text-gray-300">Session median (s)</th>
                </tr>
              </thead>
              <tbody>
                {samples.map((s, i) => {
                  const topQ = s.kart_rank <= Math.max(1, Math.floor(s.karts_in_session / 4));
                  return (
                    <tr key={`${s.session_id}-${s.kart_number}-${i}`} className="border-b border-gray-700 hover:bg-gray-700">
                      <td className="px-3 py-2 text-gray-400">
                        {s.session_date ? new Date(s.session_date).toLocaleDateString('en-US', { month: '2-digit', day: '2-digit', year: '2-digit' }) : ''}
                      </td>
                      <td className="px-3 py-2 text-white">{s.kart_number}</td>
                      <td className={`px-3 py-2 ${topQ ? 'text-green-300 font-bold' : 'text-gray-300'}`}>
                        {s.kart_rank} / {s.karts_in_session}
                      </td>
                      <td className={`px-3 py-2 ${s.kart_factor < 0.99 ? 'text-green-300' : s.kart_factor > 1.01 ? 'text-red-300' : 'text-gray-300'}`}>
                        {s.kart_factor.toFixed(4)}
                      </td>
                      <td className="px-3 py-2 text-gray-300">{s.kart_best_seconds.toFixed(3)}</td>
                      <td className="px-3 py-2 text-gray-300">{s.session_median_seconds.toFixed(3)}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </>
      )}

      {samples.length === 0 && (
        <div className="text-gray-400 text-sm">No sprint sessions for this driver at this track.</div>
      )}
    </div>
  );
}

function EnduranceFairnessPanel({ block, threshold }: { block: FairnessResponse['endurance']; threshold: number }) {
  return (
    <div className="bg-gray-800 rounded-lg p-6">
      <div className="flex items-baseline justify-between mb-4">
        <h3 className="text-xl font-semibold text-white">Endurance — Stint-Pace Stability</h3>
        <span className={`text-xs px-2 py-1 rounded ${block.enabled ? 'bg-green-900 text-green-300' : 'bg-yellow-900 text-yellow-200'}`}>
          {block.enabled ? 'Aggregate enabled' : `Needs ≥ ${threshold} endurance sessions`}
        </span>
      </div>

      <p className="text-sm text-gray-400 mb-4">
        In endurance the kart number is the team&apos;s transponder, not the physical kart — so we can&apos;t measure physical-kart luck directly.
        Instead we compare this team&apos;s per-stint pace to the field. Low σ of stint gaps combined with a small mean gap = suspiciously stable
        (either excellent driving or consistently good karts). Suggestive, not diagnostic. Data may be sparse: the parser writes one lap row per
        live-timing poll, so short endurance sessions can show only a couple of stints.
      </p>

      <div className="grid grid-cols-2 md:grid-cols-3 gap-4 mb-4">
        <StatCard label="Sessions analyzed" value={block.session_count} color="text-blue-300" />
        <StatCard label="Flagged sessions" value={block.flagged_count} color={block.flagged_count > 0 ? 'text-red-300' : 'text-green-300'} />
        <StatCard
          label="Flag rate"
          value={block.session_count > 0 ? `${Math.round((block.flagged_count / block.session_count) * 100)}%` : 'N/A'}
          color="text-yellow-300"
        />
      </div>

      {block.sessions.length > 0 ? (
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead className="bg-gray-700">
              <tr className="text-left">
                <th className="px-3 py-2 text-gray-300">Date</th>
                <th className="px-3 py-2 text-gray-300">Stints</th>
                <th className="px-3 py-2 text-gray-300">Mean gap (s)</th>
                <th className="px-3 py-2 text-gray-300">σ gap (s)</th>
                <th className="px-3 py-2 text-gray-300">Mean percentile</th>
                <th className="px-3 py-2 text-gray-300">σ percentile</th>
                <th className="px-3 py-2 text-gray-300">Flag</th>
              </tr>
            </thead>
            <tbody>
              {block.sessions.map(s => (
                <tr key={s.session_id} className={`border-b border-gray-700 ${s.flagged ? 'bg-red-900 bg-opacity-30' : 'hover:bg-gray-700'}`}>
                  <td className="px-3 py-2 text-gray-400">
                    {s.session_date ? new Date(s.session_date).toLocaleDateString('en-US', { month: '2-digit', day: '2-digit', year: '2-digit' }) : ''}
                  </td>
                  <td className="px-3 py-2 text-gray-300">{s.stint_count}</td>
                  <td className="px-3 py-2 text-yellow-300">{s.mean_gap.toFixed(2)}</td>
                  <td className="px-3 py-2 text-yellow-300">{s.stddev_gap.toFixed(2)}</td>
                  <td className="px-3 py-2 text-purple-300">
                    {s.mean_percentile !== null ? `${s.mean_percentile.toFixed(0)}%` : 'N/A'}
                  </td>
                  <td className="px-3 py-2 text-purple-300">
                    {s.stddev_percentile !== null ? `${s.stddev_percentile.toFixed(0)}%` : 'N/A'}
                  </td>
                  <td className="px-3 py-2">
                    {s.flagged ? <span className="text-red-300">⚠️ investigate</span> : <span className="text-green-300">ok</span>}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : (
        <div className="text-gray-400 text-sm">No endurance sessions for this driver at this track.</div>
      )}
    </div>
  );
}
