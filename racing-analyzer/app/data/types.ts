// Types shared by the Driver stats page and its panels.

export interface Track {
  id: number;
  track_name: string;
  timing_url: string;
  websocket_url: string;
}

export type VarDefVerdict = 'consistent' | 'deficit_flagged' | 'insufficient_data';
