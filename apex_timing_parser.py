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
        """Initialize Playwright browser with optimized settings"""
        try:
            self.playwright = await async_playwright().start()
            self.logger.info("Starting Playwright browser...")
            
            # Launch browser with improved options for stability
            self.browser = await self.playwright.chromium.launch(
                headless=True,
                args=[
                    "--disable-gpu",
                    "--disable-dev-shm-usage",
                    "--disable-setuid-sandbox",
                    "--no-sandbox",
                    "--disable-web-security",  # This might help with some CORS issues
                    "--disable-features=IsolateOrigins,site-per-process",  # Helps with iframe content
                    "--disable-site-isolation-trials"
                ]
            )
            
            # Create a page with modified settings
            context = await self.browser.new_context(
                viewport={"width": 1920, "height": 1080},  # Larger viewport
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/96.0.4664.110 Safari/537.36"  # Modern UA
            )
            
            # Set cookies properly - using domain instead of url
            await context.add_cookies([{
                "name": "liveTiming_resolution",
                "value": "big",
                "domain": "www.apex-timing.com",
                "path": "/"
            }])
            
            self.page = await context.new_page()
            
            # Set a longer default timeout
            self.page.set_default_timeout(45000)  # 45 seconds
            
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
                
                # Wait for the elements to load
                self.logger.info("Waiting for elements to load...")
                
                # Wait for the #live element which should contain everything
                await self.page.wait_for_selector("#live", timeout=30000, state="attached")
                
                # Check if the page has loaded properly by waiting for key containers
                await self.page.wait_for_selector("#global", timeout=10000, state="attached")
                
                # Don't wait for visibility, just check if elements exist
                # Give the page a moment to initialize JavaScript
                await asyncio.sleep(2)
                
                # Get HTML using JavaScript evaluation to extract even hidden content
                grid_html = await self.page.evaluate("""
                    () => {
                        // First check if grid container exists
                        const gridContainer = document.querySelector('#grid');
                        if (gridContainer) {
                            return gridContainer.outerHTML;
                        }
                        
                        // Try to find tgrid anywhere in the document
                        const tgridElement = document.querySelector('#tgrid');
                        if (tgridElement) {
                            // Walk up to find appropriate container
                            let container = tgridElement.parentElement;
                            while (container && !container.id && container.tagName !== 'BODY') {
                                container = container.parentElement;
                            }
                            return container && container.id ? container.outerHTML : tgridElement.outerHTML;
                        }
                        
                        return '';
                    }
                """)
                
                dyna_html = await self.page.evaluate("""
                    () => {
                        const dynaTable = document.querySelector('table.dyna');
                        if (dynaTable) {
                            return dynaTable.outerHTML;
                        }
                        
                        // Try alternate approach
                        const dynaCells = document.querySelectorAll('[data-id="dyn1"], [data-id="dyn2"], [data-id="light"]');
                        if (dynaCells.length > 0) {
                            // Find common ancestor
                            let container = dynaCells[0].parentElement;
                            while (container && container.tagName !== 'TABLE' && container.tagName !== 'BODY') {
                                container = container.parentElement;
                            }
                            return container && container.tagName === 'TABLE' ? container.outerHTML : '';
                        }
                        
                        return '';
                    }
                """)
                
                # Log the found HTML content length for debugging
                self.logger.info(f"Retrieved HTML content: grid={len(grid_html)} chars, dyna={len(dyna_html)} chars")
                
                if grid_html and dyna_html:
                    self.logger.info("Successfully retrieved HTML content")
                    return grid_html, dyna_html
                else:
                    self.logger.warning("Failed to extract some content: " + 
                                       (f"grid_html missing" if not grid_html else "") + 
                                       (f"dyna_html missing" if not dyna_html else ""))
                    
                    # Take a screenshot for debugging if content is missing
                    await self.page.screenshot(path=f"page_debug_{retry_count}.png")
                    
                    if retry_count >= max_retries - 1:
                        # On last attempt, try to get any content we can
                        full_html = await self.page.content()
                        self.logger.info(f"Retrieved full page HTML as fallback ({len(full_html)} chars)")
                        
                        # Try to extract from full HTML if needed
                        if not grid_html or not dyna_html:
                            soup = BeautifulSoup(full_html, 'html.parser')
                            
                            if not grid_html:
                                grid_element = soup.find(id='grid')
                                if grid_element:
                                    grid_html = str(grid_element)
                                    self.logger.info("Extracted grid_html from full page content")
                            
                            if not dyna_html:
                                dyna_element = soup.find('table', class_='dyna')
                                if dyna_element:
                                    dyna_html = str(dyna_element)
                                    self.logger.info("Extracted dyna_html from full page content")
                        
                        return grid_html or "", dyna_html or ""
                
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
            
            # First try to find the grid table
            grid_table = soup.find('table', {'id': 'tgrid'})
            if not grid_table:
                self.logger.error("Could not find grid table with id 'tgrid'")
                return pd.DataFrame()
    
            # Find the header row
            header_row = grid_table.find('tr', {'class': 'head'}) or grid_table.find('tr', {'data-id': 'r0'})
            if not header_row:
                self.logger.error("Could not find header row")
                return pd.DataFrame()
    
            # Create a mapping of column types based on the header
            column_types = {}
            for cell in header_row.find_all('td'):
                if cell.get('data-type'):
                    column_types[cell.get('data-id')] = cell.get('data-type')
    
            # Process rows
            rows = grid_table.find_all('tr')
            self.logger.debug(f"Found {len(rows)} rows in table")
            
            for row in rows:
                # Skip header row and progress lap rows
                if ('head' in row.get('class', []) or 
                    'progress_lap' in row.get('class', []) or 
                    row.get('data-id') == 'r0'):
                    continue
                
                try:
                    # Extract row data id to get row number
                    row_id = row.get('data-id', '')
                    
                    row_data = {
                        'Status': 'On Track',  # Default status
                        'Position': None,
                        'Kart': None,
                        'Team': None,
                        'Last Lap': None,
                        'Best Lap': None,
                        'Gap': None,
                        'RunTime': None,
                        'Pit Stops': None
                    }
                    
                    # Process each cell based on data-type
                    for cell in row.find_all('td'):
                        cell_type = cell.get('data-type')
                        if not cell_type:
                            continue
                        
                        # Handle different cell types
                        if cell_type == 'sta':  # Status
                            status_class = cell.get('class', [])
                            if status_class:
                                if 'si' in status_class:
                                    row_data['Status'] = 'Pit-in'
                                elif 'so' in status_class:
                                    row_data['Status'] = 'Pit-out'
                                elif 'sf' in status_class:
                                    row_data['Status'] = 'Finished'
                                elif 'ss' in status_class:
                                    row_data['Status'] = 'Stopped'
                                elif 'su' in status_class:
                                    row_data['Status'] = 'Up'
                                elif 'sd' in status_class:
                                    row_data['Status'] = 'Down'
                                elif 'sl' in status_class:
                                    row_data['Status'] = 'Lapped'
                        
                        elif cell_type == 'rk':  # Position
                            p_tag = cell.find('p')
                            if p_tag:
                                row_data['Position'] = p_tag.text.strip()
                        
                        elif cell_type == 'no':  # Kart Number
                            div_tag = cell.find('div', {'class': 'no1'})
                            if div_tag:
                                row_data['Kart'] = div_tag.text.strip()
                        
                        elif cell_type == 'dr':  # Team/Driver Name
                            row_data['Team'] = cell.text.strip()
                        
                        elif cell_type == 'llp':  # Last Lap
                            row_data['Last Lap'] = cell.text.strip()
                        
                        elif cell_type == 'blp':  # Best Lap
                            row_data['Best Lap'] = cell.text.strip()
                        
                        elif cell_type == 'gap':  # Gap
                            row_data['Gap'] = cell.text.strip()
                        
                        elif cell_type == 'otr':  # On Track (runtime)
                            row_data['RunTime'] = cell.text.strip()
                        
                        elif cell_type == 'pit':  # Pit Stops
                            row_data['Pit Stops'] = cell.text.strip() or '0'
                    
                    # Only add rows with valid Position and Kart
                    if row_data['Position'] and row_data['Kart']:
                        data.append(row_data)
                        
                except Exception as e:
                    self.logger.warning(f"Error processing row {row.get('data-id', '')}: {e}")
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
