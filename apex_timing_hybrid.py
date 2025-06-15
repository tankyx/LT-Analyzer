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
        
    def setup_logging(self):
        """Setup logging configuration"""
        logging.basicConfig(
            level=logging.INFO,
            format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
        )
        self.logger = logging.getLogger(__name__)
        
    async def detect_websocket_url(self, page: Page) -> Optional[str]:
        """
        Detect WebSocket URL from the page by intercepting network requests
        or analyzing JavaScript code.
        """
        ws_url = None
        
        # Method 1: Listen for WebSocket connections
        async def handle_websocket(ws):
            nonlocal ws_url
            ws_url = ws.url
            self.logger.info(f"Detected WebSocket connection: {ws_url}")
            
        page.on("websocket", handle_websocket)
        
        # Wait a bit for WebSocket connections
        await page.wait_for_timeout(3000)
        
        # Method 2: Search for WebSocket URL in page scripts
        if not ws_url:
            try:
                # Look for WebSocket URLs in JavaScript
                ws_url = await page.evaluate("""
                    () => {
                        // Search for WebSocket URLs in scripts
                        const scripts = Array.from(document.querySelectorAll('script'));
                        for (const script of scripts) {
                            const content = script.textContent || '';
                            // Look for WebSocket URL patterns
                            const wsMatch = content.match(/wss?:\\/\\/[^'"\\s]+/);
                            if (wsMatch) {
                                return wsMatch[0];
                            }
                            // Look for WebSocket constructor
                            const wsConstructor = content.match(/new\\s+WebSocket\\s*\\(\\s*["']([^"']+)["']/);
                            if (wsConstructor) {
                                return wsConstructor[1];
                            }
                        }
                        
                        // Check global variables
                        if (window.ws || window.websocket || window.socket) {
                            const ws = window.ws || window.websocket || window.socket;
                            if (ws && ws.url) {
                                return ws.url;
                            }
                        }
                        
                        return null;
                    }
                """)
            except Exception as e:
                self.logger.warning(f"Error searching for WebSocket URL: {e}")
                
        # Method 3: Try common WebSocket endpoints
        if not ws_url and self.base_url:
            # Extract base domain
            import urllib.parse
            parsed = urllib.parse.urlparse(self.base_url)
            base_domain = f"{parsed.scheme}://{parsed.netloc}"
            
            # Common WebSocket paths
            common_paths = ['/ws', '/websocket', '/live-timing/ws', '/live/ws', '/socket']
            
            for path in common_paths:
                test_url = base_domain.replace('http://', 'ws://').replace('https://', 'wss://') + path
                # We can't test these directly here, but store as candidates
                if not ws_url:
                    ws_url = test_url
                    self.logger.info(f"Trying common WebSocket endpoint: {ws_url}")
                    break
                    
        return ws_url
        
    async def initialize(self, url: str) -> bool:
        """
        Initialize the hybrid parser by detecting available methods.
        """
        self.base_url = url
        self.logger.info(f"Initializing hybrid parser for URL: {url}")
        
        # First, try to initialize Playwright to detect WebSocket
        self.playwright_parser = ApexTimingParserPlaywright()
        playwright_initialized = await self.playwright_parser.initialize()
        
        if playwright_initialized:
            try:
                # Navigate to page to detect WebSocket
                await self.playwright_parser.page.goto(url, wait_until="domcontentloaded", timeout=30000)
                
                # Try to detect WebSocket URL
                self.ws_url = await self.detect_websocket_url(self.playwright_parser.page)
                
                if self.ws_url:
                    self.logger.info(f"WebSocket URL detected: {self.ws_url}")
                    
                    # Try to initialize WebSocket parser
                    self.websocket_parser = ApexTimingWebSocketParser()
                    
                    # Test WebSocket connection
                    try:
                        test_connected = await self.websocket_parser.connect_websocket(self.ws_url)
                        if test_connected:
                            self.use_websocket = True
                            self.logger.info("WebSocket connection successful - using WebSocket mode")
                            await self.websocket_parser.disconnect_websocket()
                        else:
                            self.logger.warning("WebSocket connection failed - falling back to Playwright")
                    except Exception as e:
                        self.logger.warning(f"WebSocket test failed: {e} - falling back to Playwright")
                else:
                    self.logger.info("No WebSocket detected - using Playwright mode")
                    if self.force_websocket:
                        self.logger.error("WebSocket forced but not available on this page!")
                        return False
                    
            except Exception as e:
                self.logger.error(f"Error during WebSocket detection: {e}")
                if self.force_websocket:
                    return False
                
        # If force_websocket is set and we couldn't establish WebSocket, fail initialization
        if self.force_websocket and not self.use_websocket:
            self.logger.error("WebSocket mode forced but WebSocket connection could not be established")
            return False
                
        return playwright_initialized or (self.websocket_parser is not None and self.use_websocket)
        
    async def cleanup(self):
        """Clean up resources"""
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
            
            # Convert DataFrame to HTML-like format that existing parser expects
            # This is a bit of a hack but maintains compatibility
            if not df.empty:
                # Create a mock HTML structure
                grid_html = self._dataframe_to_mock_html(df)
                dyna_html = self._session_info_to_mock_html(session_info)
                return grid_html, dyna_html
            else:
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
            # If using WebSocket, data is already in DataFrame format
            df, _ = asyncio.get_event_loop().run_until_complete(
                self.websocket_parser.get_current_data()
            )
            return df
        else:
            return self.playwright_parser.parse_grid_data(html_content)
            
    def parse_dyna_info(self, html_content: str) -> Dict[str, str]:
        """Parse dynamic info using the appropriate parser"""
        if self.use_websocket and self.websocket_parser:
            _, session_info = asyncio.get_event_loop().run_until_complete(
                self.websocket_parser.get_current_data()
            )
            return session_info
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