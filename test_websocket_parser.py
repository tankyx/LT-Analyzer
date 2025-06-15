#!/usr/bin/env python3
"""
Test script to demonstrate WebSocket parser usage
"""

import asyncio
import sys
from apex_timing_websocket import ApexTimingWebSocketParser


async def test_websocket_parser():
    """Test the WebSocket parser with sample messages"""
    
    # Create parser instance
    parser = ApexTimingWebSocketParser()
    
    # Sample WebSocket messages from your data
    sample_messages = [
        "init|grid|Position|Kart|Team|Last Lap|Best Lap|Gap|RunTime|Pit Stops",
        "css|r34613c0|si",  # Pit-in status
        "grid|r34613|1|502|Barracuda2|1:13.111|1:13.095|0.000|45:23|2",
        "grid|r34614|2|556|High Octane racing|1:13.234|1:13.112|1.234|45:22|2",
        "update|r34613c4|1:12.999",  # Update last lap time
        "update|r34613c7|45:24",  # Update runtime
        "css|r34613c0|so",  # Pit-out status
        "title||Karting Mariembourg - Live Timing",
        "update|r34614c1|3",  # Position change
        "update|r34614c6|2.456",  # Gap update
    ]
    
    print("Testing WebSocket message parsing...")
    print("-" * 60)
    
    # Process each message
    for message in sample_messages:
        print(f"\nProcessing: {message}")
        parsed = parser.parse_websocket_message(message)
        
        if parsed['command'] == 'init':
            parser.process_init_message(parsed)
            print(f"  -> Initialized grid columns")
            
        elif parsed['command'] == 'grid':
            parser.process_grid_message(parsed)
            print(f"  -> Added/updated grid row: {parsed['parameter']}")
            
        elif parsed['command'] == 'update':
            parser.process_update_message(parsed)
            print(f"  -> Updated cell: {parsed['parameter']} = {parsed['value']}")
            
        elif parsed['command'] == 'css':
            parser.process_css_message(parsed)
            print(f"  -> Updated status for cell: {parsed['parameter']}")
            
        elif parsed['command'] == 'title':
            parser.process_title_message(parsed)
            print(f"  -> Set title: {parsed['value']}")
    
    # Display current standings
    print("\n" + "=" * 60)
    print("Current Standings:")
    print("=" * 60)
    
    df = parser.get_current_standings()
    if not df.empty:
        print(df.to_string(index=False))
    else:
        print("No data available")
        
    print("\nColumn mappings:", parser.column_map)
    print("Row mappings:", parser.row_map)
    

async def test_real_websocket():
    """Test with a real WebSocket connection (requires valid URL)"""
    
    parser = ApexTimingWebSocketParser()
    
    # NOTE: You'll need to find the actual WebSocket URL from the Apex Timing page
    # This is just an example URL structure
    ws_url = "wss://www.apex-timing.com/live-timing/karting-mariembourg/ws"
    
    print(f"Attempting to connect to: {ws_url}")
    print("NOTE: This may fail if the URL is incorrect or the server requires authentication")
    print("-" * 60)
    
    try:
        # Try to connect
        connected = await parser.connect_websocket(ws_url)
        if connected:
            print("Connected successfully!")
            
            # Listen for a few messages
            timeout = 10  # seconds
            print(f"Listening for messages for {timeout} seconds...")
            
            try:
                await asyncio.wait_for(
                    parser.monitor_race_websocket(ws_url),
                    timeout=timeout
                )
            except asyncio.TimeoutError:
                print(f"\nStopped after {timeout} seconds")
                
            # Show current data
            df = parser.get_current_standings()
            if not df.empty:
                print("\nCurrent standings:")
                print(df.to_string(index=False))
            else:
                print("\nNo data received")
                
        else:
            print("Failed to connect")
            
    except Exception as e:
        print(f"Error: {e}")
    finally:
        await parser.disconnect_websocket()


async def main():
    """Main test function"""
    
    if len(sys.argv) > 1 and sys.argv[1] == '--real':
        # Test with real WebSocket connection
        await test_real_websocket()
    else:
        # Test with sample messages
        await test_websocket_parser()
        print("\n\nTo test with a real WebSocket connection, run:")
        print("  python test_websocket_parser.py --real")


if __name__ == "__main__":
    asyncio.run(main())