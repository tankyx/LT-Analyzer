from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from bs4 import BeautifulSoup
import pandas as pd
import sqlite3
from datetime import datetime
import time
import logging
from typing import Optional, Dict
import traceback
import os

class ApexTimingParser:
    def __init__(self):
        self.setup_logging()
        self.setup_database()
        self.setup_driver()
        
    def setup_logging(self):
        import logging.handlers
        
        # Create a rotating file handler that limits the log size
        file_handler = logging.handlers.RotatingFileHandler(
            'apex_timing.log',
            maxBytes=10*1024*1024,  # 10MB max size
            backupCount=3           # Keep 3 backup files
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
                        lap_type TEXT,
                        position_after_lap INTEGER,
                        pit_this_lap INTEGER,
                        FOREIGN KEY (session_id) REFERENCES sessions(session_id)
                    )
                ''')
        except Exception as e:
            self.logger.error(f"Database setup error: {e}")
            raise

    def setup_driver(self):
        try:
            from selenium import webdriver
            from selenium.webdriver.chrome.options import Options
            from selenium.webdriver.chrome.service import Service
            from webdriver_manager.chrome import ChromeDriverManager
            
            # Create Chrome options with more robust settings
            chrome_options = Options()
            chrome_options.add_argument("--headless=new")  # Use new headless mode
            chrome_options.add_argument("--no-sandbox")
            chrome_options.add_argument("--disable-dev-shm-usage")
            chrome_options.add_argument("--disable-gpu")
            chrome_options.add_argument("--window-size=1280,720")
            
            # These options help with stability in CI/server environments
            chrome_options.add_argument("--disable-extensions")
            chrome_options.add_argument("--disable-infobars")
            chrome_options.add_argument("--disable-setuid-sandbox")
            chrome_options.add_argument("--disable-dev-tools")
            chrome_options.add_argument("--no-zygote")
            chrome_options.add_argument("--single-process")
            chrome_options.add_argument("--remote-debugging-port=9222")
            
            # Explicitly set binary location to system chromium
            chrome_options.binary_location = "/usr/bin/chromium-browser"
            
            self.logger.info("Setting up ChromeDriver...")
            
            # Install the ChromeDriver
            driver_manager = ChromeDriverManager()
            driver_path = driver_manager.install()
            self.logger.info(f"ChromeDriver installed at: {driver_path}")
            
            service = Service(executable_path=driver_path)
            
            # Initialize Chrome driver with explicit service path
            self.logger.info("Initializing Chrome WebDriver...")
            self.driver = webdriver.Chrome(
                service=service,
                options=chrome_options
            )
            
            # Set explicit timeouts
            self.driver.set_page_load_timeout(30)
            self.driver.set_script_timeout(15)
            
            self.wait = WebDriverWait(self.driver, 15)
            self.logger.info("WebDriver setup successful with Chrome headless")
        except Exception as e:
            self.logger.error(f"WebDriver setup error: {e}")
            self.logger.error(traceback.format_exc())
            raise

    def get_page_content(self, url: str) -> tuple[str, str]:
        """Load page and wait for content to be available"""
        retry_count = 0
        max_retries = 3
        
        while retry_count < max_retries:
            try:
                self.logger.info(f"Loading URL: {url} (Attempt {retry_count + 1})")
                
                # Clear cookies and cache for a fresh session
                if hasattr(self, 'driver') and self.driver:
                    try:
                        self.driver.delete_all_cookies()
                        self.logger.debug("Cookies cleared")
                    except:
                        pass  # Ignore errors when clearing cookies
                
                # Load the page with a timeout
                self.driver.get(url)
                
                # Wait for initial page load
                self.logger.debug("Waiting for body to load...")
                self.wait.until(EC.presence_of_element_located((By.TAG_NAME, "body")))
                self.logger.debug("Page body loaded")
                
                # Use a shorter, more targeted approach
                self.logger.debug("Locating grid element...")
                grid = self.wait.until(EC.presence_of_element_located((By.ID, "grid")))
                
                self.logger.debug("Locating dyna element...")
                dyna = self.wait.until(EC.presence_of_element_located((By.CLASS_NAME, "dyna")))
                
                # Don't wait for table rows, just get what's available
                self.logger.debug("Extracting HTML content...")
                grid_html = grid.get_attribute('outerHTML')
                dyna_html = dyna.get_attribute('outerHTML')
                
                self.logger.info("Successfully retrieved HTML content")
                return grid_html, dyna_html
                
            except Exception as e:
                retry_count += 1
                self.logger.error(f"Error loading page (attempt {retry_count}): {e}")
                
                # Try to recreate the driver on failure
                if retry_count < max_retries:
                    self.logger.info("Recreating WebDriver...")
                    try:
                        if hasattr(self, 'driver') and self.driver:
                            self.driver.quit()
                    except:
                        pass  # Ignore errors when quitting the driver
                    
                    try:
                        self.setup_driver()
                    except Exception as setup_error:
                        self.logger.error(f"Failed to recreate WebDriver: {setup_error}")
                
                # Sleep before retrying
                time.sleep(2)
        
        # If all retries failed, return empty strings
        self.logger.error(f"All {max_retries} attempts to load page failed")
        return "", ""

    def parse_dyna_info(self, html_content: str) -> Dict[str, str]:
        """Parse the dynamic information from the dyna table"""
        try:
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
                        'Status' : None,
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
            for col in ['Position', 'Kart', 'Team', 'Last Lap', 'Best Lap', 'Gap', 'RunTime', 'Pit Stops', 'Status']:
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
                previous_state = pd.read_sql('''
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
                RunTime = int(row.get('RunTime', '0')) if row.get('RunTime', '').strip() else 0
                
                current_records.append((
                    session_id,
                    timestamp,
                    position,
                    kart,
                    row.get('Team', ''),
                    row.get('Last Lap', ''),
                    row.get('Best Lap', ''),
                    row.get('Gap', ''),
                    RunTime,
                    int(row.get('Pit Stops', '0'))
                ))

                # Check for new laps
                if not previous_state.empty:
                    prev_kart_state = previous_state[previous_state['kart_number'] == kart]
                    if not prev_kart_state.empty:
                        prev_runtime = prev_kart_state.iloc[0]['RunTime']
                        prev_last_lap = prev_kart_state.iloc[0]['last_lap']
                        current_last_lap = row.get('Last Lap', '')
                        
                        if RunTime != prev_runtime and current_last_lap and current_last_lap != prev_last_lap:
                            lap_history_records.append((
                                session_id,
                                timestamp,
                                kart,
                                row.get('Team', ''),
                                RunTime,
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
                        last_lap, best_lap, gap, laps, pit_stops)
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

    def monitor_race(self, url: str, interval: int = 1):
        """Continuously monitor race data"""
        pd.set_option('display.max_rows', None)
        pd.set_option('display.max_columns', None)
        pd.set_option('display.width', None)
        pd.set_option('display.colheader_justify', 'left')
        pd.set_option('display.precision', 3)
        
        session_id = self.store_session_data("Live Session", "Karting Mariembourg")
        
        try:
            while True:
                try:
                    self.logger.info("Fetching new data...")
                    grid_html, dyna_html = self.get_page_content(url)
                    
                    if grid_html and dyna_html:
                        # Parse dynamic info
                        dyna_info = self.parse_dyna_info(dyna_html)
                        
                        # Parse grid data
                        df = self.parse_grid_data(grid_html)
                        if not df.empty:
                            self.store_lap_data(session_id, df)
                            
                            # Clear screen
                            os.system('cls' if os.name == 'nt' else 'clear')
                            
                            # Print dynamic info if available
                            if dyna_info:
                                print("\nSession Information:")
                                print("-" * 120)
                                if 'dyn1' in dyna_info:
                                    print(f"Status: {dyna_info['dyn1']}")
                                if 'light' in dyna_info:
                                    print(f"Light: {dyna_info['light']}")
                                print("-" * 120)
                            
                            print("\nCurrent Standings:")
                            print("-" * 120)
                            
                            try:
                                # Rest of the standings display code remains the same
                                display_columns = ['Status', 'Position', 'Kart', 'Team', 'Last Lap', 'Best Lap', 'Gap', 'RunTime', 'Pit Stops']
                                standings_df = df[display_columns].copy()
                                
                                # Clean the data
                                standings_df['Position'] = pd.to_numeric(standings_df['Position'], errors='coerce')
                                standings_df['RunTime'] = standings_df['RunTime'].fillna('0')
                                standings_df['Pit Stops'] = standings_df['Pit Stops'].fillna('0')
                                
                                # Sort by position
                                standings_df = standings_df.sort_values('Position')
                                
                                # Rename for display
                                standings_df = standings_df.rename(columns={'RunTime': 'Time'})
                                standings_df = standings_df.rename(columns={'Position': 'Pos'})
                                standings_df = standings_df.rename(columns={'Kart': '#'})
                                standings_df = standings_df.rename(columns={'Pit Stops': 'Pits'})
                                standings_df = standings_df.rename(columns={'Last Lap': 'Last'})
                                standings_df = standings_df.rename(columns={'Best Lap': 'Best'})
                                
                                print(standings_df.to_string(
                                    index=False,
                                    justify='left',
                                    col_space={
                                        'Status': 8,
                                        'Pos': 3,
                                        '#': 3,
                                        'Team': 20,
                                        'Last': 12,
                                        'Best': 12,
                                        'Gap': 12,
                                        'Time': 4,
                                        'Pits': 2
                                    }
                                ))
                            except Exception as e:
                                self.logger.error(f"Error formatting display: {e}")
                                print(df.to_string(index=False))
                            
                            print("-" * 120)
                            print(f"Last Update: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
                            
                        else:
                            self.logger.warning("No data parsed from HTML content")
                    
                    self.logger.info(f"Waiting {interval} seconds before next update...")
                    time.sleep(interval)
                    
                except Exception as e:
                    self.logger.error(f"Error in monitoring loop: {e}")
                    self.logger.info("Attempting to reconnect...")
                    self.setup_driver()
                    time.sleep(interval)
                
        except KeyboardInterrupt:
            self.logger.info("Stopping data collection...")
        finally:
            self.cleanup()

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
            print("\nLap Statistics:")
            print("-" * 120)
            print(stats_df.to_string(index=False))
            print("-" * 120)

    def cleanup(self):
        """Clean up resources"""
        try:
            if hasattr(self, 'driver'):
                self.driver.quit()
        except:
            pass

def main():
    parser = None
    try:
        parser = ApexTimingParser()
        url = "https://www.apex-timing.com/live-timing/karting-mariembourg/index.html"
        parser.monitor_race(url)
    except Exception as e:
        print(f"Error: {e}")
    finally:
        if parser:
            parser.cleanup()

if __name__ == "__main__":
    main()
