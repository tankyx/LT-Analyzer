import asyncio
import json
import logging
import sqlite3
import time
import traceback
from datetime import datetime
from typing import Optional, Dict, List, Tuple
import pandas as pd
import websockets
from bs4 import BeautifulSoup
import re


class ApexTimingWebSocketParser:
    """WebSocket-based parser for Apex Timing live data"""
    
    def __init__(self):
        self.setup_logging()
        self.setup_database()
        self.websocket = None
        self.last_data_hash = None
        self.grid_data = {}  # Store grid data by row/column
        self.row_map = {}  # Map row IDs to kart numbers
        self.column_map = {}  # Map column indices to field names
        self.custom_column_map = None  # Custom column mappings from track config
        self.data_type_column_map = {}  # Map column indices based on data-type attributes
        self.session_info = {}
        self.is_connected = False

        # Standard data-type to field name mapping
        self.DATA_TYPE_MAP = {
            'sta': 'Status',
            'rk': 'Position',
            'no': 'Kart',
            'dr': 'Team',
            'llp': 'Last Lap',
            'blp': 'Best Lap',
            'gap': 'Gap',
            'int': 'Interval',
            'otr': 'RunTime',
            'pit': 'Pit Stops',
            'tlp': 'Total Laps',
            's1': None,  # Skip sector times
            's2': None,
            's3': None,
            'grp': None,  # Skip group
        }
        
    def setup_logging(self):
        """Setup logging configuration"""
        import logging.handlers
        
        # Create a rotating file handler
        file_handler = logging.handlers.RotatingFileHandler(
            'apex_timing_websocket.log',
            maxBytes=10*1024*1024,  # 10MB
            backupCount=3
        )
        
        console_handler = logging.StreamHandler()
        
        logging.basicConfig(
            level=logging.DEBUG,
            format='%(asctime)s - %(levelname)s - %(message)s',
            handlers=[file_handler, console_handler]
        )
        self.logger = logging.getLogger(__name__)
        
    def setup_database(self):
        """Initialize the SQLite database with required tables"""
        try:
            with sqlite3.connect('race_data.db') as conn:
                conn.execute('''
                    CREATE TABLE IF NOT EXISTS race_sessions (
                        session_id INTEGER PRIMARY KEY AUTOINCREMENT,
                        start_time TEXT,
                        name TEXT,
                        track TEXT
                    )
                ''')
                
                conn.execute('''
                    CREATE TABLE IF NOT EXISTS lap_times (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        session_id INTEGER,
                        timestamp TEXT,
                        position INTEGER,
                        kart_number INTEGER,
                        team_name TEXT,
                        last_lap TEXT,
                        best_lap TEXT,
                        gap TEXT,
                        RunTime TEXT,
                        pit_stops INTEGER,
                        FOREIGN KEY (session_id) REFERENCES race_sessions(session_id)
                    )
                ''')

                conn.execute('''
                    CREATE TABLE IF NOT EXISTS lap_history (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        session_id INTEGER,
                        timestamp TEXT,
                        kart_number INTEGER,
                        team_name TEXT,
                        lap_number INTEGER,
                        lap_time TEXT,
                        position_after_lap INTEGER,
                        pit_this_lap INTEGER,
                        FOREIGN KEY (session_id) REFERENCES race_sessions(session_id)
                    )
                ''')
            self.logger.debug("Database setup complete")
        except Exception as e:
            self.logger.error(f"Database setup error: {e}")
            raise
            
    def set_column_mappings(self, mappings: Dict[str, str]) -> None:
        """Set custom column mappings from track configuration"""
        if mappings:
            self.custom_column_map = {}
            # mappings come as {"0": "Status", "1": "Position", ...} where keys are 0-based indices
            for col_idx_str, field_name in mappings.items():
                try:
                    col_idx = int(col_idx_str)
                    self.custom_column_map[col_idx] = field_name
                except (ValueError, TypeError):
                    self.logger.warning(f"Invalid column index: {col_idx_str}")
            self.logger.info(f"Custom column mappings set: {self.custom_column_map}")
    
    def _field_name_mapping(self, field: str) -> str:
        """Map frontend field names to internal field names"""
        mapping = {
            'position': 'Position',
            'kart': 'Kart',
            'team': 'Team',
            'status': 'Status',
            'lastLap': 'Last Lap',
            'bestLap': 'Best Lap',
            'gap': 'Gap',
            'pitStops': 'Pit Stops'
        }
        return mapping.get(field, field)
            
    def parse_websocket_message(self, message: str) -> Dict:
        """Parse a WebSocket message in the format: command|parameter|value"""
        parts = message.split('|', 2)
        if len(parts) < 2:
            return {}
            
        command = parts[0]
        parameter = parts[1] if len(parts) > 1 else ""
        value = parts[2] if len(parts) > 2 else ""
        
        return {
            'command': command,
            'parameter': parameter,
            'value': value
        }
        
    def process_init_message(self, data: Dict):
        """Process initialization messages"""
        parameter = data['parameter']
        value = data['value']
        
        if parameter == 'grid':
            # Grid initialization contains HTML table structure
            # Parse the HTML to extract column mappings
            from bs4 import BeautifulSoup
            soup = BeautifulSoup(value, 'html.parser')
            
            # Find header row
            header_row = soup.find('tr', {'class': 'head'})
            if header_row:
                cells = header_row.find_all('td')
                for i, cell in enumerate(cells):
                    data_type = cell.get('data-type', '')
                    text = cell.text.strip()
                    
                    # Map column based on data-type or text content
                    if data_type == 'sta':
                        self.column_map[i] = 'Status'
                    elif data_type == 'rk' or 'Clt' in text or 'Pos' in text:
                        self.column_map[i] = 'Position'
                    elif data_type == 'no' or 'Kart' in text:
                        self.column_map[i] = 'Kart'
                    elif data_type == 'dr' or 'Team' in text or 'Equipe' in text:
                        self.column_map[i] = 'Team'
                    elif data_type == 'llp' or 'Dernier' in text or 'Last' in text:
                        self.column_map[i] = 'Last Lap'
                    elif data_type == 'blp' or 'Meilleur' in text or 'Best' in text:
                        self.column_map[i] = 'Best Lap'
                    elif data_type == 'gap' or 'Ecart' in text or 'Gap' in text:
                        self.column_map[i] = 'Gap'
                    elif data_type == 'otr' or 'piste' in text or 'RunTime' in text:
                        self.column_map[i] = 'RunTime'
                    elif data_type == 'pit' or 'Stands' in text or 'Pit' in text:
                        self.column_map[i] = 'Pit Stops'
                        
                self.logger.debug(f"Column map initialized: {self.column_map}")
                
            # Also process any initial grid data rows
            data_rows = soup.find_all('tr', {'data-id': True})
            for row in data_rows:
                if row.get('class') and 'head' in row.get('class'):
                    continue
                    
                row_id = row.get('data-id')
                if row_id:
                    self.grid_data[row_id] = {}
                    cells = row.find_all('td')
                    
                    for i, cell in enumerate(cells):
                        # Use custom column map if available, otherwise use auto-detected map
                        if self.custom_column_map and i in self.custom_column_map:
                            field = self.custom_column_map[i]
                        elif i in self.column_map:
                            field = self.column_map[i]
                        else:
                            continue

                            # Special handling for different cell types
                            if field == 'Kart':
                                # Kart number might be in a div
                                div = cell.find('div')
                                value = div.text.strip() if div else cell.text.strip()
                            elif field == 'Position':
                                # Position might be in a p tag
                                p = cell.find('p')
                                value = p.text.strip() if p else cell.text.strip()
                            else:
                                value = cell.text.strip()
                                
                            self.grid_data[row_id][field] = value
                            
                            # Store kart mapping
                            if field == 'Kart' and value:
                                self.row_map[row_id] = value
                                
            self.logger.debug(f"Grid initialized with {len(self.grid_data)} rows")
                        
    def process_grid_message(self, data: Dict):
        """Process grid data messages"""
        # The grid message contains the entire HTML table
        if data['parameter'] == '' and data['value']:
            # This is the full grid HTML
            self.logger.debug("Processing full grid HTML")
            from bs4 import BeautifulSoup
            soup = BeautifulSoup(data['value'], 'html.parser')
            
            # Clear existing data
            self.grid_data.clear()
            self.row_map.clear()
            self.column_map.clear()
            self.data_type_column_map.clear()

            # Find header row to build column maps
            # ALWAYS extract data-type based mappings (highest priority)
            header_row = soup.find('tr', {'class': 'head'})
            if header_row:
                cells = header_row.find_all('td')
                for i, cell in enumerate(cells):
                    data_type = cell.get('data-type', '')
                    text = cell.text.strip()

                    # First: Build data-type based column map (PRIORITY 1)
                    if data_type and data_type in self.DATA_TYPE_MAP:
                        field_name = self.DATA_TYPE_MAP[data_type]
                        if field_name:  # Skip None values (sectors, etc.)
                            self.data_type_column_map[i] = field_name

                    # Also build text-based auto-detection as fallback (PRIORITY 3)
                    if not self.custom_column_map:
                        if data_type == 'sta':
                            self.column_map[i] = 'Status'
                        elif data_type == 'rk' or 'Clt' in text or 'Pos' in text or 'Rnk' in text:
                            self.column_map[i] = 'Position'
                        elif data_type == 'no' or 'Kart' in text:
                            self.column_map[i] = 'Kart'
                        elif data_type == 'dr' or 'Team' in text or 'Equipe' in text or 'Driver' in text:
                            self.column_map[i] = 'Team'
                        elif data_type == 'llp' or 'Dernier' in text or 'Last' in text:
                            self.column_map[i] = 'Last Lap'
                        elif data_type == 'blp' or 'Meilleur' in text or 'Best' in text:
                            self.column_map[i] = 'Best Lap'
                        elif data_type == 'gap' or 'Ecart' in text or 'Gap' in text:
                            self.column_map[i] = 'Gap'
                        elif data_type == 'int' or 'Interv' in text:
                            self.column_map[i] = 'Interval'
                        elif data_type == 'otr' or 'piste' in text or 'RunTime' in text or 'On track' in text:
                            self.column_map[i] = 'RunTime'
                        elif data_type == 'pit' or 'Stands' in text or 'Pit' in text:
                            self.column_map[i] = 'Pit Stops'
                        elif data_type == 'tlp':  # Total laps
                            self.column_map[i] = 'RunTime'  # Map to RunTime field for tracks that show lap count instead

                if self.data_type_column_map:
                    self.logger.info(f"Data-type column map extracted: {self.data_type_column_map}")
                if self.column_map:
                    self.logger.debug(f"Text-based column map auto-detected: {self.column_map}")
                if self.custom_column_map:
                    self.logger.debug(f"Custom column map loaded: {self.custom_column_map}")
            
            # Process data rows
            data_rows = soup.find_all('tr', {'data-id': True})
            for row in data_rows:
                if row.get('class') and 'head' in row.get('class'):
                    continue

                row_id = row.get('data-id')
                if row_id:
                    self.grid_data[row_id] = {}
                    cells = row.find_all('td')

                    for i, cell in enumerate(cells):
                        # Priority order: data-type map > custom map > text-based map
                        if i in self.data_type_column_map:
                            field = self.data_type_column_map[i]
                        elif self.custom_column_map and i in self.custom_column_map:
                            field = self.custom_column_map[i]
                        elif i in self.column_map:
                            field = self.column_map[i]
                        else:
                            continue

                        # Special handling for different cell types
                        if field == 'Status':
                            # Check for status classes
                            cell_class = cell.get('class', [])
                            if 'si' in cell_class:
                                value = 'Pit-in'
                            elif 'so' in cell_class:
                                value = 'Pit-out'
                            elif 'sf' in cell_class:
                                value = 'Finished'
                            else:
                                value = 'On Track'
                        elif field == 'Kart':
                            # Kart number might be in a div
                            div = cell.find('div')
                            value = div.text.strip() if div else cell.text.strip()
                        elif field == 'Position':
                            # Position might be in a p tag
                            p = cell.find('p')
                            value = p.text.strip() if p else cell.text.strip()
                        else:
                            value = cell.text.strip()

                        self.grid_data[row_id][field] = value

                        # Store kart mapping
                        if field == 'Kart' and value:
                            self.row_map[row_id] = value
                                
            self.logger.debug(f"Grid initialized with {len(self.grid_data)} rows")
        else:
            # This might be a row update
            row_id = data['parameter']
            values = data['value'].split('|')

            self.logger.debug(f"Processing grid row update for row {row_id}, {len(values)} values")

            if row_id not in self.grid_data:
                self.grid_data[row_id] = {}

            # Update grid data for this row
            for i, value in enumerate(values):
                # Priority order: data-type map > custom map > text-based map
                if i in self.data_type_column_map:
                    field = self.data_type_column_map[i]
                elif self.custom_column_map and i in self.custom_column_map:
                    field = self.custom_column_map[i]
                elif i in self.column_map:
                    field = self.column_map[i]
                else:
                    continue

                self.grid_data[row_id][field] = value.strip()

                # If this is the kart number column, store the mapping
                if field == 'Kart' and value.strip():
                    self.row_map[row_id] = value.strip()
                    
    def process_update_message(self, data: Dict):
        """Process cell update messages"""
        # Update messages have format: cellId|classOrType|value
        # Example: r900005625c1|su| or r900005625c2||13
        parts = data['value'].split('|')
        cell_id = data['parameter']

        # The actual value is the last part (could be empty)
        value = parts[1] if len(parts) > 1 else ''

        # Parse cell ID (format: r{row}c{col})
        match = re.match(r'r(\d+)c(\d+)', cell_id)
        if not match:
            self.logger.debug(f"Could not parse cell ID: {cell_id}")
            return

        row_id = f"r{match.group(1)}"
        col_idx = int(match.group(2)) - 1  # Column index is 1-based, convert to 0-based

        # Log incoming update for debugging
        self.logger.debug(f"Cell update: {row_id} col={col_idx} (1-based={match.group(2)}) value='{value}' parts={parts}")

        # Initialize row if needed
        if row_id not in self.grid_data:
            self.grid_data[row_id] = {}
            self.logger.debug(f"Created new row: {row_id}")

        # Update the specific cell
        # Priority order: data-type map > custom map > text-based map
        updated = False
        field = None

        if col_idx in self.data_type_column_map:
            field = self.data_type_column_map[col_idx]
            self.grid_data[row_id][field] = value.strip()
            self.logger.debug(f"Updated via data-type map: {row_id}[{field}] = '{value}'")
            updated = True
        elif self.custom_column_map and col_idx in self.custom_column_map:
            field = self.custom_column_map[col_idx]
            self.grid_data[row_id][field] = value.strip()
            self.logger.debug(f"Updated via custom map: {row_id}[{field}] = '{value}'")
            updated = True
        elif col_idx in self.column_map:
            field = self.column_map[col_idx]
            self.grid_data[row_id][field] = value.strip()
            self.logger.debug(f"Updated via text-based map: {row_id}[{field}] = '{value}'")
            updated = True

        if updated and field:
            # Special handling for status updates (check CSS class in parts[0])
            if field == 'Status' and len(parts) > 0:
                status_class = parts[0]
                if status_class == 'si':
                    self.grid_data[row_id]['Status'] = 'Pit-in'
                elif status_class == 'so':
                    self.grid_data[row_id]['Status'] = 'Pit-out'
                elif status_class == 'su':
                    self.grid_data[row_id]['Status'] = 'Up'
                elif status_class == 'sd':
                    self.grid_data[row_id]['Status'] = 'Down'
                elif status_class == 'sr':
                    self.grid_data[row_id]['Status'] = 'On Track'

            # Update kart mapping if this is a kart number
            if field == 'Kart' and value.strip():
                self.row_map[row_id] = value.strip()

        if not updated:
            self.logger.debug(f"Column {col_idx} not in any column maps (data-type: {list(self.data_type_column_map.keys())}, custom: {list(self.custom_column_map.keys()) if self.custom_column_map else 'None'}, text: {list(self.column_map.keys())})")
                
    def process_css_message(self, data: Dict):
        """Process CSS class update messages (used for status indicators)"""
        cell_id = data['parameter']
        css_class = data['value']
        
        # Parse cell ID
        match = re.match(r'r(\d+)c(\d+)', cell_id)
        if not match:
            return
            
        row_id = f"r{match.group(1)}"
        
        # Check if this is a status column (usually column 0 or 1)
        if 'si' in css_class:
            status = 'Pit-in'
        elif 'so' in css_class:
            status = 'Pit-out'
        elif 'sf' in css_class:
            status = 'Finished'
        elif 'ss' in css_class:
            status = 'Stopped'
        elif 'su' in css_class:
            status = 'Up'
        elif 'sd' in css_class:
            status = 'Down'
        else:
            status = 'On Track'
            
        if row_id not in self.grid_data:
            self.grid_data[row_id] = {}
        self.grid_data[row_id]['Status'] = status
        
    def process_title_message(self, data: Dict):
        """Process title messages (session info)"""
        title = data['value']
        self.session_info['title'] = title
        self.logger.debug(f"Session title: {title}")
        
    def get_current_standings(self) -> pd.DataFrame:
        """Convert current grid data to DataFrame format compatible with existing code"""
        teams = []
        
        self.logger.debug(f"get_current_standings: grid_data has {len(self.grid_data)} rows")
        
        for row_id, row_data in self.grid_data.items():
            if 'Kart' in row_data and row_data['Kart']:
                team_name = row_data.get('Team', '')

                # Validate team name - warn if it looks like a lap time
                if team_name and ':' in team_name and '.' in team_name:
                    # Check if it matches lap time format (M:SS.mmm or MM:SS.mmm)
                    import re
                    if re.match(r'^\d{1,2}:\d{2}\.\d{3}$', team_name):
                        self.logger.warning(f"Team name looks like lap time for kart {row_data.get('Kart', '')}: '{team_name}' - possible column mapping issue")

                team_data = {
                    'Status': row_data.get('Status', 'On Track'),
                    'Position': row_data.get('Position', ''),
                    'Kart': row_data.get('Kart', ''),
                    'Team': team_name,
                    'Last Lap': row_data.get('Last Lap', ''),
                    'Best Lap': row_data.get('Best Lap', ''),
                    'Gap': row_data.get('Gap', ''),
                    'RunTime': row_data.get('RunTime', ''),
                    'Pit Stops': row_data.get('Pit Stops', '0')
                }
                teams.append(team_data)
                
        # Sort by position
        teams.sort(key=lambda x: int(x['Position']) if x['Position'].isdigit() else 999)
        
        self.logger.debug(f"Returning {len(teams)} teams from get_current_standings")
        if teams:
            self.logger.debug(f"First team: {teams[0]}")
        
        return pd.DataFrame(teams)
        
    def store_lap_data(self, session_id: int, df: pd.DataFrame):
        """Store lap timing data in database (reuse from Playwright parser)"""
        if df.empty:
            return

        timestamp = datetime.now().isoformat()
        current_records = []
        lap_history_records = []
        
        try:
            with sqlite3.connect('race_data.db') as conn:
                previous_state = pd.read_sql_query('''
                    SELECT kart_number, RunTime, last_lap, best_lap, pit_stops
                    FROM lap_times 
                    WHERE session_id = ? 
                    ORDER BY timestamp DESC
                ''', conn, params=(session_id,))
        except:
            previous_state = pd.DataFrame()
        
        for _, row in df.iterrows():
            try:
                position = int(row['Position']) if row.get('Position', '').strip() else None
                kart = int(row['Kart']) if row.get('Kart', '').strip() else None
                # Parse RunTime from MM:SS format to seconds
                runtime_str = row.get('RunTime', '0')
                if ':' in runtime_str:
                    parts = runtime_str.split(':')
                    runtime = int(parts[0]) * 60 + int(parts[1])
                else:
                    runtime = int(runtime_str) if runtime_str.strip() else 0
                
                current_records.append((
                    session_id,
                    timestamp,
                    position,
                    kart,
                    row.get('Team', ''),
                    row.get('Last Lap', ''),
                    row.get('Best Lap', ''),
                    row.get('Gap', ''),
                    runtime,
                    int(row.get('Pit Stops', '0'))
                ))

                # Check for new laps
                if not previous_state.empty:
                    prev_kart_state = previous_state[previous_state['kart_number'] == kart]
                    if not prev_kart_state.empty:
                        prev_runtime = prev_kart_state.iloc[0]['RunTime']
                        prev_last_lap = prev_kart_state.iloc[0]['last_lap']
                        current_last_lap = row.get('Last Lap', '')
                        
                        if runtime != prev_runtime and current_last_lap and current_last_lap != prev_last_lap:
                            lap_history_records.append((
                                session_id,
                                timestamp,
                                kart,
                                row.get('Team', ''),
                                runtime,
                                current_last_lap,
                                position,
                                int(row.get('Pit Stops', '0'))
                            ))

            except Exception as e:
                self.logger.warning(f"Error processing row {row}: {e}")
                continue

        if current_records:
            try:
                with sqlite3.connect('race_data.db') as conn:
                    conn.executemany('''
                        INSERT INTO lap_times 
                        (session_id, timestamp, position, kart_number, team_name,
                        last_lap, best_lap, gap, RunTime, pit_stops)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ''', current_records)
                    
                    if lap_history_records:
                        conn.executemany('''
                            INSERT INTO lap_history 
                            (session_id, timestamp, kart_number, team_name, 
                            lap_number, lap_time, position_after_lap, pit_this_lap)
                            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                        ''', lap_history_records)
                    
                    self.logger.debug(f"Stored {len(current_records)} current records and {len(lap_history_records)} lap history records")
            except Exception as e:
                self.logger.error(f"Error storing data in database: {e}")
                
    def store_session_data(self, session_name: str, track: str) -> int:
        """Store new session information and return session ID"""
        with sqlite3.connect('race_data.db') as conn:
            cursor = conn.cursor()
            cursor.execute(
                "INSERT INTO race_sessions (start_time, name, track) VALUES (?, ?, ?)",
                (datetime.now().isoformat(), session_name, track)
            )
            return cursor.lastrowid
            
    async def connect_websocket(self, ws_url: str):
        """Connect to the WebSocket endpoint"""
        try:
            self.logger.debug(f"Connecting to WebSocket: {ws_url}")
            
            # Try connecting with different parameters
            # Add headers that might be required
            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/137.0.0.0 Safari/537.36",
                "Origin": "https://www.apex-timing.com",
                "Accept-Language": "en-US,en;q=0.9,fr-FR;q=0.8,fr;q=0.7",
                "Pragma": "no-cache",
                "Cache-Control": "no-cache",
            }
            
            try:
                # First try with default settings
                import websockets
                # Check websockets version and use appropriate parameters
                if hasattr(websockets, '__version__') and websockets.__version__ >= '10.0':
                    self.websocket = await websockets.connect(
                        ws_url,
                        additional_headers=headers,  # Use additional_headers for newer versions
                        ping_interval=20,
                        ping_timeout=10,
                        close_timeout=10,
                        compression="deflate"
                    )
                else:
                    # For older versions, headers go in subprotocol
                    self.websocket = await websockets.connect(
                        ws_url,
                        ping_interval=20,
                        ping_timeout=10,
                        close_timeout=10
                    )
            except Exception as e:
                self.logger.warning(f"Default connection failed: {e}, trying with SSL context...")
                # Try with custom SSL context if it's WSS
                if ws_url.startswith('wss://'):
                    import ssl
                    ssl_context = ssl.create_default_context()
                    ssl_context.check_hostname = False
                    ssl_context.verify_mode = ssl.CERT_NONE
                    if hasattr(websockets, '__version__') and websockets.__version__ >= '10.0':
                        self.websocket = await websockets.connect(
                            ws_url,
                            ssl=ssl_context,
                            additional_headers=headers,
                            ping_interval=20,
                            ping_timeout=10,
                            close_timeout=10,
                            compression="deflate"
                        )
                    else:
                        self.websocket = await websockets.connect(
                            ws_url,
                            ssl=ssl_context,
                            ping_interval=20,
                            ping_timeout=10,
                            close_timeout=10
                        )
                else:
                    raise
                    
            self.is_connected = True
            self.logger.debug("WebSocket connected successfully")
            
            # Check WebSocket state
            if self.websocket:
                # For newer websockets library versions, check if connection is open differently
                try:
                    if hasattr(self.websocket, 'open'):
                        self.logger.debug("WebSocket state: open" if self.websocket.open else "WebSocket state: closed")
                    elif hasattr(self.websocket, 'state'):
                        self.logger.debug(f"WebSocket state: {self.websocket.state}")
                    else:
                        self.logger.debug("WebSocket connected (state check not available)")
                except Exception as e:
                    self.logger.debug(f"Could not check WebSocket state: {e}")
                
            return True
        except Exception as e:
            self.logger.error(f"Failed to connect to WebSocket: {e}")
            self.logger.error(f"WebSocket URL was: {ws_url}")
            self.is_connected = False
            return False
            
    async def disconnect_websocket(self):
        """Disconnect from the WebSocket"""
        if self.websocket:
            await self.websocket.close()
            self.websocket = None
            self.is_connected = False
            self.logger.debug("WebSocket disconnected")
            
    async def monitor_race_websocket(self, ws_url: str, session_name: str = "Live Session", 
                                   track: str = "Karting Mariembourg"):
        """Monitor race data via WebSocket"""
        session_id = self.store_session_data(session_name, track)
        reconnect_delay = 5
        
        while True:
            try:
                # Connect to WebSocket
                if not await self.connect_websocket(ws_url):
                    self.logger.warning(f"Retrying connection in {reconnect_delay} seconds...")
                    await asyncio.sleep(reconnect_delay)
                    reconnect_delay = min(reconnect_delay * 2, 60)  # Exponential backoff
                    continue
                    
                reconnect_delay = 5  # Reset on successful connection
                
                # Send initial message to request data (some WebSocket servers require this)
                try:
                    await self.websocket.send("init")
                    self.logger.debug("Sent init message to WebSocket")
                except Exception as e:
                    self.logger.warning(f"Could not send init message: {e}")
                
                # Listen for messages
                self.logger.debug("Waiting for WebSocket messages...")
                message_count = 0
                async for message in self.websocket:
                    message_count += 1
                    try:
                        # Log only the raw message
                        self.logger.info(f"WebSocket message #{message_count}: {message}")
                        
                        # Split message by newlines as it contains multiple commands
                        lines = message.strip().split('\n')
                        
                        for i, line in enumerate(lines):
                            if not line.strip():
                                continue
                                
                            # Parse each command line
                            parsed = self.parse_websocket_message(line)
                            if not parsed:
                                continue
                                
                            command = parsed['command']
                            
                            # Process different message types
                            if command == 'init':
                                self.process_init_message(parsed)
                            elif command == 'grid':
                                self.process_grid_message(parsed)
                            elif command == 'update':
                                self.process_update_message(parsed)
                            elif command == 'css':
                                self.process_css_message(parsed)
                            elif command == 'title1':
                                self.session_info['title1'] = parsed['value']
                                self.logger.debug(f"Session title1: {parsed['value']}")
                            elif command == 'title2':
                                self.session_info['title2'] = parsed['value']
                                self.logger.debug(f"Session title2: {parsed['value']}")
                            elif command == 'title':
                                self.process_title_message(parsed)
                            elif command == 'clear':
                                # Clear data for the specified element
                                if parsed['parameter'] == 'grid':
                                    self.grid_data.clear()
                                    self.row_map.clear()
                            elif command == 'com':
                                # Comment/info message
                                self.session_info['comment'] = parsed['value']
                                self.logger.debug(f"Comment message: {parsed['value']}")
                            elif command == 'msg':
                                # Message (best lap info etc)
                                self.session_info['message'] = parsed['value']
                                self.logger.debug(f"Message update: {parsed['value']}")
                            elif command == 'track':
                                # Track info
                                self.session_info['track'] = parsed['value']
                                self.logger.debug(f"Track info: {parsed['value']}")
                            elif command.startswith('r') and 'c' in command:
                                # Cell update message (e.g., r15c6|ti|3:28.267)
                                cell_id = command
                                update_type = parsed['parameter']
                                value = parsed['value']
                                
                                # Parse cell ID (format: r{row}c{col})
                                match = re.match(r'r(\d+)c(\d+)', cell_id)
                                if match:
                                    row_id = f"r{match.group(1)}"
                                    col_idx = int(match.group(2)) - 1  # Column index is 1-based, convert to 0-based
                                    
                                    # Initialize row if needed
                                    if row_id not in self.grid_data:
                                        self.grid_data[row_id] = {}
                                    
                                    # Use custom column mappings if available, otherwise use defaults
                                    if self.custom_column_map and col_idx in self.custom_column_map:
                                        # Use custom mapping
                                        field_name = self.custom_column_map[col_idx]
                                        if field_name == 'Status' and update_type in ['gs', 'si', 'so', 'su', 'sd']:
                                            # Handle status updates
                                            if update_type == 'gs':
                                                self.grid_data[row_id]['Status'] = 'On Track'
                                            elif update_type == 'si':
                                                self.grid_data[row_id]['Status'] = 'Pit-in'
                                            elif update_type == 'so':
                                                self.grid_data[row_id]['Status'] = 'Pit-out'
                                            elif update_type == 'su':
                                                self.grid_data[row_id]['Status'] = 'Up'
                                            elif update_type == 'sd':
                                                self.grid_data[row_id]['Status'] = 'Down'
                                        else:
                                            # Regular field update
                                            self.grid_data[row_id][field_name] = value
                                            if field_name == 'Kart' and value:
                                                self.row_map[row_id] = value
                                    elif col_idx == 0:  # c1 - Status (default mapping)
                                        if update_type in ['sr', 'si', 'so', 'su', 'sd', 'in']:
                                            if update_type == 'sr' or update_type == 'in':
                                                self.grid_data[row_id]['Status'] = 'On Track'
                                            elif update_type == 'si':
                                                self.grid_data[row_id]['Status'] = 'Pit-in'
                                            elif update_type == 'so':
                                                self.grid_data[row_id]['Status'] = 'Pit-out'
                                            elif update_type == 'su':
                                                self.grid_data[row_id]['Status'] = 'Up'
                                            elif update_type == 'sd':
                                                self.grid_data[row_id]['Status'] = 'Down'
                                    elif col_idx == 1:  # c2 - Position
                                        self.grid_data[row_id]['Position'] = value
                                    elif col_idx == 2:  # c3 - Kart number
                                        self.grid_data[row_id]['Kart'] = value
                                        if value:
                                            self.row_map[row_id] = value
                                    elif col_idx == 3:  # c4 - Team name
                                        self.grid_data[row_id]['Team'] = value
                                    elif col_idx == 4:  # c5 - Last Lap
                                        self.grid_data[row_id]['Last Lap'] = value
                                    elif col_idx == 5:  # c6 - Gap
                                        self.grid_data[row_id]['Gap'] = value
                                    elif col_idx == 6:  # c7 - Interval
                                        self.grid_data[row_id]['Interval'] = value
                                    elif col_idx == 7:  # c8 - Best Lap
                                        self.grid_data[row_id]['Best Lap'] = value
                                    elif col_idx == 8:  # c9 - RunTime
                                        self.grid_data[row_id]['RunTime'] = value
                                    elif col_idx == 9:  # c10 - Pit Stops
                                        self.grid_data[row_id]['Pit Stops'] = value
                                    
                                    self.logger.debug(f"Cell update: {cell_id} col={col_idx+1} type={update_type} value={value}")
                            elif command.startswith('r'):
                                # Row update message (e.g., r35407|#|14)
                                # These indicate position changes or other row-level updates
                                row_id = command
                                update_type = parsed['parameter']
                                value = parsed['value']
                                
                                if update_type == '#':
                                    # Position update
                                    if row_id not in self.grid_data:
                                        self.grid_data[row_id] = {}
                                    self.grid_data[row_id]['Position'] = value
                                    self.logger.debug(f"Position update: {row_id} -> position {value}")
                                elif update_type == '*':
                                    # Some other update, possibly timing
                                    self.logger.debug(f"Row update: {row_id} type={update_type} value={value}")
                            else:
                                # Log unrecognized commands
                                self.logger.debug(f"Unrecognized command: {command} with parameter={parsed.get('parameter', 'N/A')} and value={parsed.get('value', 'N/A')[:50]}...")
                                
                        # After processing all commands in the message, save to database
                        df = self.get_current_standings()
                        if not df.empty:
                            self.store_lap_data(session_id, df)
                            self.logger.debug(f"Processed {len(df)} teams from WebSocket message #{message_count}")
                            # Log sample data for debugging
                            if len(df) > 0:
                                first_team = df.iloc[0]
                                self.logger.debug(f"Leader: Pos={first_team.get('Position')}, "
                                               f"Kart={first_team.get('Kart')}, Team={first_team.get('Team')}, "
                                               f"Gap={first_team.get('Gap')}, Status={first_team.get('Status')}")
                        else:
                            self.logger.debug(f"No team data in WebSocket message #{message_count}")
                        
                        self.logger.debug(f"=== End of WebSocket message #{message_count} processing ===")
                            
                    except Exception as e:
                        self.logger.error(f"Error processing message: {e}")
                        self.logger.error(traceback.format_exc())
                        
            except websockets.exceptions.ConnectionClosed as e:
                self.logger.warning(f"WebSocket connection closed: {e}")
                self.logger.warning(f"Close code: {e.code}, reason: {e.reason}")
                self.is_connected = False
                await asyncio.sleep(reconnect_delay)
            except Exception as e:
                self.logger.error(f"WebSocket error: {e}")
                self.logger.error(traceback.format_exc())
                self.is_connected = False
                await asyncio.sleep(reconnect_delay)
                
    async def get_current_data(self) -> Tuple[pd.DataFrame, Dict[str, str]]:
        """Get current race data in format compatible with existing code"""
        df = self.get_current_standings()
        return df, self.session_info


# Example usage
async def main():
    parser = ApexTimingWebSocketParser()
    
    # WebSocket URL would need to be determined from the Apex Timing page
    # This is just an example - actual URL would need to be discovered
    ws_url = "wss://www.apex-timing.com/live-timing/karting-mariembourg/ws"
    
    try:
        await parser.monitor_race_websocket(ws_url)
    except KeyboardInterrupt:
        print("Stopping WebSocket monitor...")
    finally:
        await parser.disconnect_websocket()


if __name__ == "__main__":
    asyncio.run(main())