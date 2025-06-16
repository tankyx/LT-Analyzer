import asyncio
import logging
import re
from typing import Optional, Dict, Tuple, Union
import pandas as pd
from playwright.async_api import Page
import json

from apex_timing_parser import ApexTimingParserPlaywright
from apex_timing_websocket import ApexTimingWebSocketParser


class ApexTimingHybridParser:
    """
    Hybrid parser that can use either WebSocket or Playwright for data collection.
    Automatically detects and uses WebSocket when available, falls back to Playwright.
    """
    
    def __init__(self):
        self.setup_logging()
        self.playwright_parser = None
        self.websocket_parser = None
        self.use_websocket = False
        self.ws_url = None
        self.base_url = None
        self.force_websocket = False  # Flag to force WebSocket-only mode
        self.websocket_task = None  # Task for WebSocket monitoring
        
    def setup_logging(self):
        """Setup logging configuration"""
        logging.basicConfig(
            level=logging.INFO,
            format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
        )
        self.logger = logging.getLogger(__name__)
        
    def set_websocket_url(self, ws_url: str) -> None:
        """
        Set the WebSocket URL manually instead of auto-detecting.
        """
        self.ws_url = ws_url
        self.logger.info(f"WebSocket URL manually set to: {ws_url}")
        
    def set_column_mappings(self, mappings: Dict[str, int]) -> None:
        """
        Set custom column mappings for the WebSocket parser.
        """
        self.column_mappings = mappings
        if self.websocket_parser:
            self.websocket_parser.set_column_mappings(mappings)
        
    async def initialize(self, url: str) -> bool:
        """
        Initialize the hybrid parser.
        """
        self.base_url = url
        self.logger.info(f"Initializing hybrid parser for URL: {url}")
        
        # First, try to initialize Playwright
        self.playwright_parser = ApexTimingParserPlaywright()
        playwright_initialized = await self.playwright_parser.initialize()
        
        if playwright_initialized:
            try:
                # Navigate to page
                await self.playwright_parser.page.goto(url, wait_until="domcontentloaded", timeout=30000)
                
                # Check if we have a manually set WebSocket URL
                if self.ws_url:
                    self.logger.info(f"Using manually set WebSocket URL: {self.ws_url}")
                    
                    # Try to initialize WebSocket parser
                    self.websocket_parser = ApexTimingWebSocketParser()
                    
                    # Apply column mappings if available
                    if hasattr(self, 'column_mappings') and self.column_mappings:
                        self.websocket_parser.set_column_mappings(self.column_mappings)
                    
                    # Test WebSocket connection
                    try:
                        test_connected = await self.websocket_parser.connect_websocket(self.ws_url)
                        if test_connected:
                            self.use_websocket = True
                            self.logger.info("WebSocket connection successful - using WebSocket mode")
                            # Disconnect the test connection
                            await self.websocket_parser.disconnect_websocket()
                            
                            # Start WebSocket monitoring in the background
                            self.websocket_task = asyncio.create_task(
                                self.websocket_parser.monitor_race_websocket(self.ws_url)
                            )
                            self.logger.info("Started WebSocket monitoring task")
                        else:
                            self.logger.warning("WebSocket connection failed - falling back to Playwright")
                    except Exception as e:
                        self.logger.warning(f"WebSocket test failed: {e} - falling back to Playwright")
                else:
                    self.logger.info("No WebSocket URL provided - using Playwright mode")
                    if self.force_websocket:
                        self.logger.error("WebSocket forced but no WebSocket URL provided!")
                        return False
                    
            except Exception as e:
                self.logger.error(f"Error during initialization: {e}")
                if self.force_websocket:
                    return False
                
        # If force_websocket is set and we couldn't establish WebSocket, fail initialization
        if self.force_websocket and not self.use_websocket:
            self.logger.error("WebSocket mode forced but WebSocket connection could not be established")
            return False
                
        return playwright_initialized or (self.websocket_parser is not None and self.use_websocket)
        
    async def cleanup(self):
        """Clean up resources"""
        if self.websocket_task:
            self.websocket_task.cancel()
            try:
                await self.websocket_task
            except asyncio.CancelledError:
                pass
                
        if self.playwright_parser:
            await self.playwright_parser.cleanup()
        if self.websocket_parser and self.websocket_parser.is_connected:
            await self.websocket_parser.disconnect_websocket()
            
    async def get_page_content(self, url: str) -> Tuple[str, str]:
        """
        Get page content using the appropriate method.
        Returns (grid_html, dyna_html) for compatibility.
        """
        if self.use_websocket and self.websocket_parser:
            # For WebSocket, we need to return data in a format compatible with existing code
            df, session_info = await self.websocket_parser.get_current_data()
            
            self.logger.info(f"WebSocket data retrieved: {len(df)} teams, session_info: {session_info}")
            
            # Convert DataFrame to HTML-like format that existing parser expects
            # This is a bit of a hack but maintains compatibility
            if not df.empty:
                # Log first team for debugging
                first_team = df.iloc[0]
                self.logger.info(f"First team from WebSocket: Pos {first_team.get('Position')}, "
                                f"Kart {first_team.get('Kart')}, Team {first_team.get('Team')}")
                
                # Create a mock HTML structure
                grid_html = self._dataframe_to_mock_html(df)
                dyna_html = self._session_info_to_mock_html(session_info)
                self.logger.info(f"Returning mock HTML with {len(df)} teams")
                return grid_html, dyna_html
            else:
                self.logger.warning("WebSocket returned empty DataFrame")
                return "", ""
        else:
            # Use Playwright parser
            return await self.playwright_parser.get_page_content(url)
            
    def _dataframe_to_mock_html(self, df: pd.DataFrame) -> str:
        """Convert DataFrame to mock HTML format for compatibility"""
        html = '<table id="tgrid">'
        html += '<tr class="head">'
        
        # Add headers
        for col in df.columns:
            data_type = 'sta' if col == 'Status' else 'rk' if col == 'Position' else 'no' if col == 'Kart' else 'dr' if col == 'Team' else 'llp' if col == 'Last Lap' else 'blp' if col == 'Best Lap' else 'gap' if col == 'Gap' else 'otr' if col == 'RunTime' else 'pit'
            html += f'<td data-type="{data_type}">{col}</td>'
        html += '</tr>'
        
        # Add data rows
        for idx, row in df.iterrows():
            html += f'<tr data-id="r{idx+1}">'
            for col in df.columns:
                data_type = 'sta' if col == 'Status' else 'rk' if col == 'Position' else 'no' if col == 'Kart' else 'dr' if col == 'Team' else 'llp' if col == 'Last Lap' else 'blp' if col == 'Best Lap' else 'gap' if col == 'Gap' else 'otr' if col == 'RunTime' else 'pit'
                
                if col == 'Status':
                    status_class = 'si' if row[col] == 'Pit-in' else 'so' if row[col] == 'Pit-out' else ''
                    html += f'<td data-type="{data_type}" class="{status_class}"></td>'
                elif col == 'Position':
                    html += f'<td data-type="{data_type}"><p>{row[col]}</p></td>'
                elif col == 'Kart':
                    html += f'<td data-type="{data_type}"><div class="no1">{row[col]}</div></td>'
                else:
                    html += f'<td data-type="{data_type}">{row[col]}</td>'
            html += '</tr>'
            
        html += '</table>'
        return html
        
    def _session_info_to_mock_html(self, session_info: Dict) -> str:
        """Convert session info to mock HTML format"""
        html = '<table class="dyna">'
        if 'title' in session_info:
            html += f'<td data-id="dyn1">{session_info["title"]}</td>'
        if 'dyn2' in session_info:
            html += f'<td data-id="dyn2">{session_info["dyn2"]}</td>'
        html += '</table>'
        return html
        
    def parse_grid_data(self, html_content: str) -> pd.DataFrame:
        """Parse grid data using the appropriate parser"""
        if self.use_websocket and self.websocket_parser:
            # If using WebSocket, get the current standings directly
            return self.websocket_parser.get_current_standings()
        else:
            return self.playwright_parser.parse_grid_data(html_content)
            
    def parse_dyna_info(self, html_content: str) -> Dict[str, str]:
        """Parse dynamic info using the appropriate parser"""
        if self.use_websocket and self.websocket_parser:
            # Return the session info directly from WebSocket parser
            return self.websocket_parser.session_info
        else:
            return self.playwright_parser.parse_dyna_info(html_content)
            
    def store_lap_data(self, session_id: int, df: pd.DataFrame):
        """Store lap data using the appropriate parser"""
        if self.use_websocket and self.websocket_parser:
            self.websocket_parser.store_lap_data(session_id, df)
        else:
            self.playwright_parser.store_lap_data(session_id, df)
            
    def store_session_data(self, session_name: str, track: str) -> int:
        """Store session data using the appropriate parser"""
        if self.use_websocket and self.websocket_parser:
            return self.websocket_parser.store_session_data(session_name, track)
        else:
            return self.playwright_parser.store_session_data(session_name, track)
            
    async def monitor_race(self, url: str, interval: int = 5):
        """
        Monitor race using the appropriate method.
        """
        if not await self.initialize(url):
            self.logger.error("Failed to initialize parser")
            return
            
        if self.use_websocket and self.websocket_parser and self.ws_url:
            # Use WebSocket monitoring
            self.logger.info("Starting WebSocket monitoring")
            await self.websocket_parser.monitor_race_websocket(self.ws_url)
        else:
            # Use Playwright monitoring
            self.logger.info("Starting Playwright monitoring")
            await self.playwright_parser.monitor_race(url, interval)
            

# Example usage
async def main():
    parser = ApexTimingHybridParser()
    
    try:
        url = "https://www.apex-timing.com/live-timing/karting-mariembourg/index.html"
        await parser.monitor_race(url)
    except KeyboardInterrupt:
        print("Stopping hybrid parser...")
    finally:
        await parser.cleanup()


if __name__ == "__main__":
    asyncio.run(main())