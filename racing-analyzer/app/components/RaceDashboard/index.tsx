import React, { useState, useEffect } from 'react';

// Types
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

interface SessionInfo {
  dyn1?: string;
  dyn2?: string;
  light?: string;
}

interface Alert {
  id: number;
  message: string;
}

const RaceDashboard = () => {
  const [teams, setTeams] = useState<Team[]>([]);
  const [sessionInfo, setSessionInfo] = useState<SessionInfo>({});
  const [lastUpdate, setLastUpdate] = useState<string>('');
  const [myTeam, setMyTeam] = useState<string>('');
  const [monitoredTeams, setMonitoredTeams] = useState<string[]>([]);
  const [alerts, setAlerts] = useState<Alert[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const fetchData = async () => {
      try {
        const response = await fetch('http://localhost:5000/api/race-data');
        if (!response.ok) {
          throw new Error('Failed to fetch race data');
        }
        const data = await response.json();
        setTeams(data.teams);
        setSessionInfo(data.session_info);
        setLastUpdate(data.last_update);
        setIsLoading(false);
        checkPitStops(data.teams);
      } catch (error) {
        setError(error instanceof Error ? error.message : 'An error occurred');
        setIsLoading(false);
      }
    };

    fetchData();
    const interval = setInterval(fetchData, 5000);
    return () => clearInterval(interval);
  }, []);

  const checkPitStops = (currentTeams: Team[]) => {
    monitoredTeams.forEach(kartNum => {
      const team = currentTeams.find(t => t.Kart === kartNum);
      if (team && parseInt(team['Pit Stops']) > (team.lastPitCount || 0)) {
        setAlerts(prev => [...prev, {
          id: Date.now(),
          message: `${team.Team} is pitting!`
        }]);
        team.lastPitCount = parseInt(team['Pit Stops']);
      }
    });
  };

  const calculateRealGap = (competitor: Team): string => {
    const PIT_TIME = 150; // 2min30sec in seconds
    const myTeamData = teams.find(t => t.Kart === myTeam);
    if (!myTeamData) return '0.0';
    
    const pitDiff = parseInt(competitor['Pit Stops']) - parseInt(myTeamData['Pit Stops']);
    const baseGap = parseFloat(competitor.Gap || '0');
    return (baseGap + (pitDiff * PIT_TIME)).toFixed(1);
  };

  const directCompetitors = React.useMemo(() => {
    if (!myTeam) return [];
    const myTeamData = teams.find(t => t.Kart === myTeam);
    if (!myTeamData) return [];
    
    const myClass = myTeamData.Team.charAt(0);
    const myPos = parseInt(myTeamData.Position);
    
    return teams.filter(team => 
      team.Team.charAt(0) === myClass &&
      Math.abs(parseInt(team.Position) - myPos) <= 1 &&
      team.Kart !== myTeam
    );
  }, [teams, myTeam]);

  if (isLoading) {
    return (
      <div className="flex items-center justify-center min-h-screen">
        <div className="text-lg">Loading race data...</div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="flex items-center justify-center min-h-screen">
        <div className="text-red-600">Error: {error}</div>
      </div>
    );
  }

  return (
    <div className="bg-gray-100 min-h-screen p-6">
      <div className="max-w-7xl mx-auto bg-white rounded-lg shadow-lg p-6">
        <h1 className="text-2xl font-bold mb-6">Race Analysis</h1>

        {/* Team Selection */}
        <div className="grid grid-cols-1 md:grid-cols-2 gap-6 mb-6">
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-2">
              My Team
            </label>
            <select 
              value={myTeam}
              onChange={(e) => setMyTeam(e.target.value)}
              className="w-full p-2 border rounded-lg bg-white"
            >
              <option value="">Select Team</option>
              {teams.map(team => (
                <option key={team.Kart} value={team.Kart}>
                  {team.Team} (Kart #{team.Kart})
                </option>
              ))}
            </select>
          </div>
          
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-2">
              Teams to Monitor
            </label>
            <select 
              multiple
              value={monitoredTeams}
              onChange={(e) => setMonitoredTeams(
                Array.from(e.target.selectedOptions, option => option.value)
              )}
              className="w-full p-2 border rounded-lg bg-white h-32"
            >
              {teams.map(team => (
                <option key={team.Kart} value={team.Kart}>
                  {team.Team} (Kart #{team.Kart})
                </option>
              ))}
            </select>
          </div>
        </div>

        {/* Session Info */}
        <div className="bg-blue-50 rounded-lg p-4 mb-6">
          <h2 className="font-semibold mb-2">Session Information</h2>
          <p>{sessionInfo.dyn1}</p>
          <p className="text-sm text-gray-600 mt-2">Last Update: {lastUpdate}</p>
        </div>

        {/* Alerts */}
        {alerts.length > 0 && (
          <div className="mb-6 space-y-2">
            {alerts.map(alert => (
              <div key={alert.id} className="bg-red-50 text-red-700 p-4 rounded-lg">
                {alert.message}
              </div>
            ))}
          </div>
        )}

        {/* Main Data Display */}
        <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
          {/* Direct Competitors */}
          <div className="bg-white rounded-lg shadow p-4">
            <h2 className="font-bold text-lg mb-4">Direct Competitors</h2>
            <div className="space-y-3">
              {directCompetitors.map(competitor => (
                <div key={competitor.Kart} className="border-b pb-3">
                  <div className="flex justify-between items-center mb-1">
                    <span className="font-medium">{competitor.Team}</span>
                    <span className="text-gray-700">Gap: {calculateRealGap(competitor)}s</span>
                  </div>
                  <div className="text-sm text-gray-600">
                    Last Lap: {competitor['Last Lap']} | 
                    Pits: {competitor['Pit Stops']}
                  </div>
                </div>
              ))}
            </div>
          </div>

          {/* Standings Table */}
          <div className="bg-white rounded-lg shadow p-4">
            <h2 className="font-bold text-lg mb-4">Current Standings</h2>
            <div className="overflow-x-auto">
              <table className="w-full">
                <thead className="bg-gray-50">
                  <tr>
                    <th className="px-4 py-2 text-left">Pos</th>
                    <th className="px-4 py-2 text-left">Team</th>
                    <th className="px-4 py-2 text-left">Last Lap</th>
                    <th className="px-4 py-2 text-left">Best Lap</th>
                    <th className="px-4 py-2 text-right">Gap</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-gray-200">
                  {[...teams]
                    .sort((a, b) => parseInt(a.Position) - parseInt(b.Position))
                    .map(team => (
                    <tr key={team.Kart} className="hover:bg-gray-50">
                      <td className="px-4 py-2">{team.Position}</td>
                      <td className="px-4 py-2">
                        <div className="font-medium">{team.Team}</div>
                        <div className="text-sm text-gray-500">Kart #{team.Kart}</div>
                      </td>
                      <td className="px-4 py-2">{team['Last Lap']}</td>
                      <td className="px-4 py-2">{team['Best Lap']}</td>
                      <td className="px-4 py-2 text-right">{team.Gap}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
};

export default RaceDashboard;