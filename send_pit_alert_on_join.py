#!/usr/bin/env python3
"""
Send Pit Alert When Device Joins Room - Simple Version

Usage:
    python3 send_pit_alert_on_join.py --track 10 --team "ENZO.H" --message "PIT NOW!"
    
This script:
1. Monitors for devices joining a team room
2. Automatically sends a pit alert when someone joins
3. Supports both one-time and continuous monitoring
"""

import requests
import json
import time
import sys
import argparse
from datetime import datetime

BACKEND_URL = "http://localhost:5000"
CHECK_INTERVAL = 2  # seconds

def log(msg):
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}")

def check_room(room_name):
    """Check how many clients are in a room"""
    try:
        response = requests.post(
            f"{BACKEND_URL}/api/admin/socketio/room-info",
            json={"room": room_name},
            timeout=5
        )
        if response.status_code == 200:
            data = response.json()
            return data.get('client_count', 0), data.get('clients', [])
        return 0, []
    except Exception as e:
        log(f"Error checking room: {e}")
        return 0, []

def send_pit_alert(track_id, team_name, message):
    """Send pit alert via API"""
    try:
        response = requests.post(
            f"{BACKEND_URL}/api/trigger-pit-alert",
            json={
                "track_id": track_id,
                "team_name": team_name,
                "alert_message": message
            },
            timeout=5
        )
        return response.status_code == 200
    except Exception as e:
        log(f"Error sending alert: {e}")
        return False

def monitor_and_alert(track_id, team_name, message, continuous=False):
    """
    Monitor room and send alert when device joins
    
    Args:
        track_id: Track ID (e.g., "10")
        team_name: Team name (e.g., "ENZO.H")
        message: Pit alert message
        continuous: If True, keep monitoring and send alerts every time
    """
    room_name = f"team_track_{track_id}_{team_name}"
    
    log(f"🔔 Monitoring room: {room_name}")
    log(f"📢 Alert will be: '{message}'")
    log(f"{'🔄 Continuous mode' if continuous else '⏱️ One-time alert'}")
    log("")
    
    # Check initial state
    initial_count, _ = check_room(room_name)
    log(f"📊 Current clients in room: {initial_count}")
    
    alerts_sent = 0
    
    try:
        while True:
            current_count, clients = check_room(room_name)
            
            # Detect new joins
            if current_count > initial_count:
                new_clients = current_count - initial_count
                log(f"🎉 {new_clients} new device(s) joined!")
                
                # Send pit alert
                if send_pit_alert(track_id, team_name, message):
                    alerts_sent += 1
                    log(f"✅ Alert #{alerts_sent} sent!")
                else:
                    log("❌ Failed to send alert")
                
                if not continuous:
                    break
            
            elif current_count < initial_count:
                log(f"📉 Device left room (now: {current_count})")
            
            initial_count = current_count
            time.sleep(CHECK_INTERVAL)
            
    except KeyboardInterrupt:
        log("🛑 Stopped by user")
    
    if alerts_sent == 0 and not continuous:
        log("⏰ No devices joined during monitoring")
    
    return alerts_sent

def main():
    parser = argparse.ArgumentParser(
        description='Send pit alert when device joins room',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Monitor once and alert when ENZO.H joins track 10
  python3 send_pit_alert_on_join.py --track 10 --team "ENZO.H" --message "PIT NOW!"
  
  # Continuous monitoring - alert every time someone joins
  python3 send_pit_alert_on_join.py --track 10 --team "ENZO.H" --continuous
  
  # Monitor with custom message
  python3 send_pit_alert_on_join.py --track 10 --team "MARCO2904" --message "BOX BOX BOX!" --continuous
        """
    )
    
    parser.add_argument('--track', type=str, required=True, help='Track ID (e.g., 10)')
    parser.add_argument('--team', type=str, required=True, help='Team name (e.g., ENZO.H)')
    parser.add_argument('--message', type=str, default='PIT NOW!', help='Pit alert message')
    parser.add_argument('--continuous', action='store_true', help='Continuous monitoring mode')
    
    args = parser.parse_args()
    
    # Test API connectivity
    try:
        response = requests.get(f"{BACKEND_URL}/api/tracks/status", timeout=5)
        if response.status_code != 200:
            log("⚠️  Warning: API may not be fully ready")
    except:
        log("❌ Cannot connect to backend at localhost:5000")
        sys.exit(1)
    
    log("✅ Connected to backend")
    log("")
    
    # Start monitoring
    sent = monitor_and_alert(args.track, args.team, args.message, args.continuous)
    
    if sent > 0:
        log(f"")
        log(f"🎉 Mission complete! Sent {sent} alert(s)")
    else:
        log(f"")
        log("📊 Monitoring complete (no alerts sent)")

if __name__ == "__main__":
    main()
