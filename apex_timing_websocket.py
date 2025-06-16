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
        self.session_info = {}
        self.is_connected = False
        
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
                    CREATE TABLE IF NOT EXISTS sessions (
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
                        FOREIGN KEY (session_id) REFERENCES sessions(session_id)
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
                        FOREIGN KEY (session_id) REFERENCES sessions(session_id)
                    )
                ''')
            self.logger.info("Database setup complete")
        except Exception as e:
            self.logger.error(f"Database setup error: {e}")
            raise
            
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
                        if i in self.column_map:
                            field = self.column_map[i]
                            
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
                                
            self.logger.info(f"Grid initialized with {len(self.grid_data)} rows")
                        
    def process_grid_message(self, data: Dict):
        """Process grid data messages"""
        row_id = data['parameter']
        values = data['value'].split('|')
        
        self.logger.debug(f"Processing grid message for row {row_id}, {len(values)} values")
        
        if row_id not in self.grid_data:
            self.grid_data[row_id] = {}
            
        # Update grid data for this row
        for i, value in enumerate(values):
            if i in self.column_map:
                field = self.column_map[i]
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
        
        # Initialize row if needed
        if row_id not in self.grid_data:
            self.grid_data[row_id] = {}
            self.logger.debug(f"Created new row: {row_id}")
            
        # Update the specific cell
        if col_idx in self.column_map:
            field = self.column_map[col_idx]
            self.grid_data[row_id][field] = value.strip()
            
            # Special handling for status updates
            if col_idx == 0 and len(parts) > 0:
                # First column is often status, parts[0] contains the status class
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
                
            self.logger.debug(f"Updated {row_id}[{field}] = {value}")
                
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
        self.logger.info(f"Session title: {title}")
        
    def get_current_standings(self) -> pd.DataFrame:
        """Convert current grid data to DataFrame format compatible with existing code"""
        teams = []
        
        self.logger.debug(f"get_current_standings: grid_data has {len(self.grid_data)} rows")
        
        for row_id, row_data in self.grid_data.items():
            if 'Kart' in row_data and row_data['Kart']:
                team_data = {
                    'Status': row_data.get('Status', 'On Track'),
                    'Position': row_data.get('Position', ''),
                    'Kart': row_data.get('Kart', ''),
                    'Team': row_data.get('Team', ''),
                    'Last Lap': row_data.get('Last Lap', ''),
                    'Best Lap': row_data.get('Best Lap', ''),
                    'Gap': row_data.get('Gap', ''),
                    'RunTime': row_data.get('RunTime', ''),
                    'Pit Stops': row_data.get('Pit Stops', '0')
                }
                teams.append(team_data)
                
        # Sort by position
        teams.sort(key=lambda x: int(x['Position']) if x['Position'].isdigit() else 999)
        
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
                runtime = int(row.get('RunTime', '0')) if row.get('RunTime', '').strip() else 0
                
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
                    
                    self.logger.info(f"Stored {len(current_records)} current records and {len(lap_history_records)} lap history records")
            except Exception as e:
                self.logger.error(f"Error storing data in database: {e}")
                
    def store_session_data(self, session_name: str, track: str) -> int:
        """Store new session information and return session ID"""
        with sqlite3.connect('race_data.db') as conn:
            cursor = conn.cursor()
            cursor.execute(
                "INSERT INTO sessions (start_time, name, track) VALUES (?, ?, ?)",
                (datetime.now().isoformat(), session_name, track)
            )
            return cursor.lastrowid
            
    async def connect_websocket(self, ws_url: str):
        """Connect to the WebSocket endpoint"""
        try:
            self.logger.info(f"Connecting to WebSocket: {ws_url}")
            
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
            self.logger.info("WebSocket connected successfully")
            
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
            self.logger.info("WebSocket disconnected")
            
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
                    self.logger.info("Sent init message to WebSocket")
                except Exception as e:
                    self.logger.warning(f"Could not send init message: {e}")
                
                # Listen for messages
                self.logger.info("Waiting for WebSocket messages...")
                message_count = 0
                async for message in self.websocket:
                    message_count += 1
                    self.logger.info(f"Received WebSocket message #{message_count}")
                    try:
                        # Debug log raw message (truncate if too long)
                        if len(message) > 200:
                            self.logger.info(f"WebSocket raw message: {message[:200]}... (truncated, total length: {len(message)})")
                        else:
                            self.logger.info(f"WebSocket raw message: {message}")
                        
                        # Parse the message
                        parsed = self.parse_websocket_message(message)
                        if not parsed:
                            continue
                            
                        command = parsed['command']
                        self.logger.debug(f"WebSocket command: {command}, parameter: {parsed.get('parameter', 'N/A')}")
                        
                        # Process different message types
                        if command == 'init':
                            self.process_init_message(parsed)
                        elif command == 'grid':
                            self.process_grid_message(parsed)
                        elif command == 'update':
                            self.process_update_message(parsed)
                        elif command == 'css':
                            self.process_css_message(parsed)
                        elif command == 'title':
                            self.process_title_message(parsed)
                        elif command == 'clear':
                            # Clear data for the specified element
                            if parsed['parameter'] == 'grid':
                                self.grid_data.clear()
                                self.row_map.clear()
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
                                
                        # Periodically save to database
                        df = self.get_current_standings()
                        if not df.empty:
                            self.store_lap_data(session_id, df)
                            self.logger.debug(f"Processed {len(df)} teams")
                            # Log sample data for debugging
                            if len(df) > 0:
                                first_team = df.iloc[0]
                                self.logger.debug(f"Sample team data - Pos: {first_team.get('Position')}, "
                                                f"Kart: {first_team.get('Kart')}, Team: {first_team.get('Team')}, "
                                                f"Gap: {first_team.get('Gap')}, Status: {first_team.get('Status')}")
                            
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