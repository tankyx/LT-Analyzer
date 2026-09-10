/** Class prefix helpers for Apex team names ("1 - TEAM" / "2 - TEAM"). */
export const getTeamClass = (teamName: string): string | null => {
  if (teamName.startsWith('1 - ')) return '1';
  if (teamName.startsWith('2 - ')) return '2';
  return null;
};

/** Strip the class prefix for display; the class chip carries it instead. */
export const displayTeamName = (teamName: string): string =>
  getTeamClass(teamName) ? teamName.slice(4) : teamName;
