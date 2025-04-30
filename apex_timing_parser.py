import asyncio
import logging
import os
import sqlite3
import time
import traceback
from datetime import datetime
from typing import Optional, Dict, Tuple, List
import pandas as pd
from playwright.async_api import async_playwright, Page, Browser, Playwright
from bs4 import BeautifulSoup

class ApexTimingParserPlaywright:
    def __init__(self):
        self.setup_logging()
        self.setup_database()
        self.browser = None
        self.page = None
        self.playwright = None

    async def initialize(self):
        """Initialize Playwright browser"""
        try:
            self.playwright = await async_playwright().start()
            self.logger.info("Starting Playwright browser...")
            
            # Launch browser with appropriate options
            self.browser = await self.playwright.chromium.launch(
                headless=True,  # Run in headless mode
                args=[
                    "--disable-gpu",
                    "--disable-dev-shm-usage",
                    "--disable-setuid-sandbox",
                    "--no-sandbox",
                ]
            )
            
            # Create a new page
            self.page = await self.browser.new_page()
            self.page.set_default_timeout(30000)  # 30 seconds timeout
            
            self.logger.info("Playwright browser started successfully")
            return True
        except Exception as e:
            self.logger.error(f"Error initializing Playwright: {e}")
            self.logger.error(traceback.format_exc())
            await self.cleanup()
            return False

    async def cleanup(self):
        """Clean up Playwright resources"""
        try:
            if self.page:
                await self.page.close()
                self.page = None
            
            if self.browser:
                await self.browser.close()
                self.browser = None
                
            if self.playwright:
                await self.playwright.stop()
                self.playwright = None
            
            self.logger.info("Playwright resources cleaned up")
        except Exception as e:
            self.logger.error(f"Error during cleanup: {e}")

    def setup_logging(self):
        """Setup logging configuration"""
        import logging.handlers
        
        # Create a rotating file handler
        file_handler = logging.handlers.RotatingFileHandler(
            'apex_timing.log',
            maxBytes=10*1024*1024,  # 10MB
            backupCount=3
        )
        
        console_handler = logging.StreamHandler()
        
        logging.basicConfig(
            level=logging.INFO,
            format='%(asctime)s - %(levelname)s - %(message)s',
            handlers=[file_handler, console_handler]
        )
        self.logger = logging.getLogger(__name__)

    def setup_database(self):
        """Initialize the SQLite database with required tables"""
        try:
            # Delete existing database if it exists
            if os.path.exists('race_data.db'):
                os.remove('race_data.db')
                
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

    async def get_page_content(self, url: str) -> Tuple[str, str]:
        """Load page and wait for content to be available"""
        retry_count = 0
        max_retries = 3
        
        while retry_count < max_retries:
            try:
                self.logger.info(f"Loading URL: {url} (Attempt {retry_count + 1})")
                
                # Navigate to the URL with a timeout
                await self.page.goto(url, wait_until="domcontentloaded", timeout=30000)
                
                # Wait for the grid and dyna elements to be visible
                self.logger.info("Waiting for elements to load...")
                
                await self.page.wait_for_selector("#grid", timeout=30000)
                await self.page.wait_for_selector(".dyna", timeout=30000)
                
                # Get the HTML content
                grid_html = await self.page.locator("#grid").evaluate("el => el.outerHTML")
                dyna_html = await self.page.locator(".dyna").evaluate("el => el.outerHTML")
                
                self.logger.info("Successfully retrieved HTML content")
                return grid_html, dyna_html
                
            except Exception as e:
                retry_count += 1
                self.logger.error(f"Error loading page (attempt {retry_count}): {e}")
                self.logger.error(traceback.format_exc())
                
                if retry_count < max_retries:
                    self.logger.info("Retrying in 2 seconds...")
                    await asyncio.sleep(2)
                    
                    # Reinitialize browser if needed
                    if not self.browser or not self.page:
                        await self.initialize()
                else:
                    self.logger.error(f"All {max_retries} attempts to load page failed")
                    return "", ""
        
        # If all retries failed
        return "", ""

    def parse_dyna_info(self, html_content: str) -> Dict[str, str]:
        """Parse the dynamic information from the dyna table"""
        try:
            if not html_content:
                return {}
                
            soup = BeautifulSoup(html_content, 'html.parser')
            dyna_table = soup.find('table', class_='dyna')
            
            if not dyna_table:
                self.logger.warning("Could not find dyna table")
                return {}
                
            dyna_info = {}
            
            # Get dyn1 field (usually contains time/session info)
            dyn1_cell = dyna_table.find('td', {'data-id': 'dyn1'})
            if dyn1_cell:
                dyn1_text = dyn1_cell.text.strip()
                dyna_info['dyn1'] = dyn1_text
                self.logger.debug(f"Found dyn1: {dyn1_text}")
            
            # Get dyn2 field (if it exists)
            dyn2_cell = dyna_table.find('td', {'data-id': 'dyn2'})
            if dyn2_cell:
                dyn2_text = dyn2_cell.text.strip()
                dyna_info['dyn2'] = dyn2_text
                self.logger.debug(f"Found dyn2: {dyn2_text}")
            
            # Get light status if exists
            light_cell = dyna_table.find('td', {'data-id': 'light'})
            if light_cell:
                light_class = light_cell.get('class', [])
                light_status = light_class[0] if light_class else ''
                dyna_info['light'] = light_status
                self.logger.debug(f"Found light status: {light_status}")
            
            return dyna_info
            
        except Exception as e:
            self.logger.error(f"Error parsing dyna info: {traceback.format_exc()}")
            return {}

    def parse_grid_data(self, html_content: str) -> pd.DataFrame:
        """Parse the grid data from HTML content"""
        try:
            if not html_content:
                return pd.DataFrame()
                
            soup = BeautifulSoup(html_content, 'html.parser')
            data = []
            
            # First find the header row to get the correct column mapping
            header_row = soup.find('tr', {'class': 'head'})
            if not header_row:
                self.logger.error("Could not find header row")
                return pd.DataFrame()

            rows = soup.find_all('tr')
            self.logger.debug(f"Found {len(rows)} rows in table")
            
            for row in rows:
                # Skip header row and progress lap rows
                if 'head' in row.get('class', []) or 'progress_lap' in row.get('class', []):
                    continue
                
                try:
                    row_data = {
                        'Status': None,
                        'Position': None,
                        'Kart': None,
                        'Team': None,
                        'Last Lap': None,
                        'Best Lap': None,
                        'Gap': None,
                        'RunTime': None,
                        'Pit Stops': None
                    }
                    
                    # Status (from td with data-type='sta')
                    status_cell = row.find('td', {'data-type': 'sta'})
                    if status_cell:
                        # Define the status mappings
                        status_classes = {
                            'sf': 'Finished',  # finish
                            'si': 'Pit-in',    # pit in
                            'so': 'Pit-out',   # pit out
                            'su': 'Up',        # moving up
                            'sd': 'Down',      # moving down
                            'ss': 'Stopped',   # stopped
                            'sr': 'On Track',  # running
                            'sl': 'Lapped'     # lapped
                        }
                        
                        # Check if any status class exists directly on the status cell
                        cell_classes = status_cell.get('class', [])
                        
                        # Try to find the status
                        found_status = False
                        
                        # Check for status in cell's own classes
                        if cell_classes:
                            if isinstance(cell_classes, list):
                                for cls in cell_classes:
                                    if cls in status_classes:
                                        row_data['Status'] = status_classes[cls]
                                        found_status = True
                                        break
                            elif isinstance(cell_classes, str):
                                # If it's a string, check each status class
                                for cls, status in status_classes.items():
                                    if cls in cell_classes:
                                        row_data['Status'] = status
                                        found_status = True
                                        break
                        
                        # If status not found in cell classes, look for child elements with status classes
                        if not found_status:
                            for cls, status in status_classes.items():
                                # There might be a div or span with the class
                                status_element = status_cell.find(class_=cls)
                                if status_element:
                                    row_data['Status'] = status
                                    found_status = True
                                    break
                        
                        # Default to 'On Track' if we couldn't determine status
                        if not found_status:
                            row_data['Status'] = 'On Track'
                    else:
                        # Couldn't find a status cell
                        row_data['Status'] = 'Unknown'

                    # Position (from p tag within rk cell)
                    pos_cell = row.find('td', {'data-type': 'rk'})
                    if pos_cell:
                        pos_p = pos_cell.find('p')
                        if pos_p:
                            row_data['Position'] = pos_p.text.strip()
                    
                    # Kart number (from no1 class div)
                    kart_div = row.find('div', class_='no1')
                    if kart_div:
                        row_data['Kart'] = kart_div.text.strip()
                    
                    # Team name
                    team_cell = row.find('td', {'data-type': 'dr'})
                    if team_cell:
                        row_data['Team'] = team_cell.text.strip()
                    
                    # Last lap
                    last_lap_cell = row.find('td', {'data-type': 'llp'})
                    if last_lap_cell:
                        row_data['Last Lap'] = last_lap_cell.text.strip()
                    
                    # Best lap
                    best_lap_cell = row.find('td', {'data-type': 'blp'})
                    if best_lap_cell:
                        row_data['Best Lap'] = best_lap_cell.text.strip()
                    
                    # Gap
                    gap_cell = row.find('td', {'data-type': 'gap'})
                    if gap_cell:
                        row_data['Gap'] = gap_cell.text.strip()
                    
                    # Running time
                    laps_cell = row.find('td', {'data-type': 'otr'})
                    if laps_cell:
                        row_data['RunTime'] = laps_cell.text.strip()
                    
                    # Pit stops
                    pit_cell = row.find('td', {'data-type': 'pit'})
                    if pit_cell:
                        row_data['Pit Stops'] = pit_cell.text.strip() or '0'
                    
                    if row_data['Position'] and row_data['Kart']:
                        data.append(row_data)
                        
                except Exception as e:
                    self.logger.warning(f"Error processing row: {e}")
                    continue

            df = pd.DataFrame(data)
            # Ensure all expected columns exist with defaults if missing
            for col in ['Status', 'Position', 'Kart', 'Team', 'Last Lap', 'Best Lap', 'Gap', 'RunTime', 'Pit Stops']:
                if col not in df.columns:
                    df[col] = None
                    
            self.logger.info(f"Successfully parsed {len(df)} rows of data")
            return df
            
        except Exception as e:
            self.logger.error(f"Error parsing grid data: {traceback.format_exc()}")
            return pd.DataFrame()

    def store_lap_data(self, session_id: int, df: pd.DataFrame):
        """Store lap timing data in database"""
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

    async def monitor_race(self, url: str, interval: int = 5):
        """Continuously monitor race data"""
        pd.set_option('display.max_rows', None)
        pd.set_option('display.max_columns', None)
        pd.set_option('display.width', None)
        pd.set_option('display.colheader_justify', 'left')
        pd.set_option('display.precision', 3)
        
        session_id = self.store_session_data("Live Session", "Karting Mariembourg")
        
        try:
            # Initialize browser
            if not await self.initialize():
                self.logger.error("Failed to initialize browser. Exiting.")
                return

            while True:
                try:
                    self.logger.info("Fetching new data...")
                    grid_html, dyna_html = await self.get_page_content(url)
                    
                    if grid_html and dyna_html:
                        # Parse dynamic info
                        dyna_info = self.parse_dyna_info(dyna_html)
                        
                        # Parse grid data
                        df = self.parse_grid_data(grid_html)
                        if not df.empty:
                            self.store_lap_data(session_id, df)
                            
                            # Print status for debugging
                            self.logger.info(f"Successfully updated data at {datetime.now().isoformat()}")
                            self.logger.info(f"Current standings: {len(df)} teams")
                            
                            # Print dynamic info if available
                            if dyna_info:
                                self.logger.info(f"Session info: {dyna_info}")
                    else:
                        self.logger.warning("Failed to fetch data, will retry")

                    # Wait before next update
                    await asyncio.sleep(interval)
                    
                except Exception as e:
                    self.logger.error(f"Error in monitoring loop: {e}")
                    self.logger.error(traceback.format_exc())
                    
                    # Try to re-initialize browser if there was an error
                    await self.cleanup()
                    if not await self.initialize():
                        self.logger.error("Failed to reinitialize browser. Exiting.")
                        return
                    
                    await asyncio.sleep(interval)
                
        except KeyboardInterrupt:
            self.logger.info("Stopping data collection...")
        finally:
            await self.cleanup()

    def get_lap_statistics(self, session_id: int, kart_number: Optional[int] = None) -> pd.DataFrame:
        """Get lap statistics for a specific kart or all karts"""
        try:
            with sqlite3.connect('race_data.db') as conn:
                query = '''
                    SELECT 
                        kart_number,
                        team_name,
                        COUNT(*) as total_laps,
                        MIN(lap_time) as best_lap,
                        MAX(lap_time) as worst_lap,
                        SUM(pit_this_lap) as total_pits
                    FROM lap_history
                    WHERE session_id = ?
                '''
                params = [session_id]
                
                if kart_number is not None:
                    query += ' AND kart_number = ?'
                    params.append(kart_number)
                    
                query += ' GROUP BY kart_number, team_name ORDER BY total_laps DESC'
                
                return pd.read_sql(query, conn, params=params)
        except Exception as e:
            self.logger.error(f"Error getting lap statistics: {e}")
            return pd.DataFrame()

    def print_lap_statistics(self, session_id: int):
        """Print lap statistics for all karts"""
        stats_df = self.get_lap_statistics(session_id)
        if not stats_df.empty:
            self.logger.info("\nLap Statistics:")
            self.logger.info("-" * 80)
            self.logger.info(stats_df.to_string(index=False))
            self.logger.info("-" * 80)

# Main function to run the parser
async def main():
    parser = ApexTimingParserPlaywright()
    try:
        url = "https://www.apex-timing.com/live-timing/karting-mariembourg/index.html"
        await parser.monitor_race(url)
    except Exception as e:
        print(f"Error: {e}")
        print(traceback.format_exc())
    finally:
        await parser.cleanup()

# Entry point
if __name__ == "__main__":
    asyncio.run(main())
