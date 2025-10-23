#!/usr/bin/env python3
"""
Test client for team-specific Socket.IO updates

This script connects to the LT-Analyzer backend and subscribes to real-time
updates for a specific team on a specific track.

Usage:
    python test_team_socket.py

The script will prompt for:
- Track ID (e.g., 1 for Mariembourg, 2 for Spa)
- Team name (must match exactly as it appears in race data)

Press Ctrl+C to exit.
"""

import socketio
import sys
from datetime import datetime

# Create Socket.IO client
sio = socketio.Client(logger=False, engineio_logger=False)

# State
current_track_id = None
current_team_name = None
update_count = 0


@sio.event
def connect():
    """Handle connection to server"""
    print(f"[{datetime.now().strftime('%H:%M:%S')}] ✓ Connected to server")
    print()


@sio.event
def disconnect():
    """Handle disconnection from server"""
    print(f"\n[{datetime.now().strftime('%H:%M:%S')}] ✗ Disconnected from server")


@sio.event
def team_room_joined(data):
    """Handle successful team room join"""
    print(f"[{datetime.now().strftime('%H:%M:%S')}] ✓ Joined team room successfully")
    print(f"  Track: {data.get('track_name')} (ID: {data.get('track_id')})")
    print(f"  Team: {data.get('team_name')}")
    print(f"  Room: {data.get('room')}")
    print()
    print("=" * 80)
    print("Waiting for team updates... (Press Ctrl+C to exit)")
    print("=" * 80)
    print()


@sio.event
def team_room_error(data):
    """Handle team room errors"""
    print(f"\n[{datetime.now().strftime('%H:%M:%S')}] ✗ ERROR: {data.get('error')}")
    if data.get('track_id'):
        print(f"  Track ID: {data.get('track_id')}")
    if data.get('track_name'):
        print(f"  Track: {data.get('track_name')}")
    print()
    print("Tip: Make sure the track ID is correct and the team has race data.")
    print("You can check available teams by looking at the dashboard for that track.")


@sio.event
def team_specific_update(data):
    """Handle team-specific update events"""
    global update_count
    update_count += 1

    timestamp = datetime.now().strftime('%H:%M:%S')

    # Header
    print(f"\n{'=' * 80}")
    print(f"Update #{update_count} at {timestamp}")
    print(f"{'=' * 80}")

    # Track and team info
    print(f"Track: {data.get('track_name')} (ID: {data.get('track_id')})")
    print(f"Team: {data.get('team_name')}")
    print(f"Session ID: {data.get('session_id')}")
    print()

    # Position and status
    print(f"Position: {data.get('position')}")
    print(f"Kart: {data.get('kart')}")
    print(f"Status: {data.get('status')}")
    print()

    # Lap times and performance
    print(f"Last Lap: {data.get('last_lap') or 'N/A'}")
    print(f"Best Lap: {data.get('best_lap') or 'N/A'}")
    print(f"Total Laps: {data.get('total_laps')}")
    print(f"Runtime: {data.get('runtime') or 'N/A'}")
    print(f"Pit Stops: {data.get('pit_stops')}")
    print()

    # Gap information
    print("Gaps:")
    gap_to_leader = data.get('gap_to_leader')
    if gap_to_leader:
        print(f"  To Leader: {gap_to_leader}")
    else:
        print(f"  To Leader: LEADER (P1)")

    gap_to_front = data.get('gap_to_front')
    if gap_to_front is not None:
        print(f"  To Front:  {gap_to_front}")
    else:
        print(f"  To Front:  N/A (P1)")

    gap_to_behind = data.get('gap_to_behind')
    if gap_to_behind is not None:
        print(f"  To Behind: {gap_to_behind}")
    else:
        print(f"  To Behind: N/A (Last)")

    print()


def main():
    """Main function to run the test client"""
    global current_track_id, current_team_name

    print()
    print("=" * 80)
    print("LT-Analyzer Team Socket.IO Test Client")
    print("=" * 80)
    print()

    # Get user input
    try:
        track_id_str = input("Enter Track ID (e.g., 1 for Mariembourg, 2 for Spa): ").strip()
        if not track_id_str:
            print("Error: Track ID is required")
            sys.exit(1)

        current_track_id = int(track_id_str)

        current_team_name = input("Enter Team Name (case-sensitive, e.g., 'TEAM ABC'): ").strip()
        if not current_team_name:
            print("Error: Team name is required")
            sys.exit(1)

    except ValueError:
        print("Error: Track ID must be a number")
        sys.exit(1)
    except KeyboardInterrupt:
        print("\nCancelled by user")
        sys.exit(0)

    print()
    print("Connecting to server...")

    try:
        # Connect to server
        sio.connect('http://localhost:5000')

        # Join team room
        print(f"Joining team room for Track {current_track_id}, Team '{current_team_name}'...")
        sio.emit('join_team_room', {
            'track_id': current_track_id,
            'team_name': current_team_name
        })

        # Wait for events (blocks until Ctrl+C)
        sio.wait()

    except socketio.exceptions.ConnectionError as e:
        print(f"\n✗ Connection error: {e}")
        print("Make sure the backend server is running on localhost:5000")
        sys.exit(1)

    except KeyboardInterrupt:
        print("\n\nShutting down...")
        if sio.connected:
            # Leave team room before disconnecting
            sio.emit('leave_team_room', {
                'track_id': current_track_id,
                'team_name': current_team_name
            })
            sio.disconnect()
        print(f"Received {update_count} updates total")
        print("Goodbye!")
        sys.exit(0)

    except Exception as e:
        print(f"\n✗ Unexpected error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == '__main__':
    main()
