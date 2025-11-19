#!/usr/bin/env python3
"""
Room Monitor and Pit Alert System
Monitors Socket.IO room joins and sends pit alerts when devices join

Usage:
    python3 monitor_and_alert.py --track 10 --team "ENZO.H" --message "PIT NOW!"
    python3 monitor_and_alert.py --room team_track_10_ENZO.H --message "BOX BOX BOX"
    python3 monitor_and_alert.py --list-rooms  # List active rooms
    python3 monitor_and_alert.py --room-status team_track_10_ENZO.H  # Check room status
"""

import requests
import json
import time
import sys
import argparse
from datetime import datetime

try:
    from flask_socketio import SocketIO
    from flask import Flask
    WS_AVAILABLE = True
except ImportError:
    WS_AVAILABLE = False

# Configuration
BACKEND_URL = "http://localhost:5000"
SOCKETIO_URL = "http://localhost:5000"
CHECK_INTERVAL = 2  # seconds

def log_message(message):
    """Log with timestamp"""
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {message}")

def check_api_health():
    """Check if backend API is responding"""
    try:
        response = requests.get(f"{BACKEND_URL}/api/tracks/status", timeout=5)
        return response.status_code == 200
    except:
        return False

def list_active_rooms():
    """List all active Socket.IO rooms"""
    log_message("📋 Fetching active rooms from backend...")
    try:
        response = requests.post(f"{BACKEND_URL}/api/admin/socketio/rooms", timeout=5)
        if response.status_code == 200:
            rooms = response.json()
            log_message(f"✅ Found {len(rooms)} active rooms")
            for room in rooms:
                log_message(f"   - {room}")
            return rooms
        else:
            log_message(f"⚠️  API returned status {response.status_code}")
            return []
    except Exception as e:
        log_message(f"❌ Failed to fetch rooms: {e}")
        return []

def check_room_status(room_name):
    """Check if a specific room has clients"""
    log_message(f"🔍 Checking room status: {room_name}")
    try:
        response = requests.post(
            f"{BACKEND_URL}/api/admin/socketio/room-info",
            json={"room": room_name},
            timeout=5
        )
        
        if response.status_code == 200:
            data = response.json()
            client_count = data.get('client_count', 0)
            log_message(f"   Clients in room: {client_count}")
            
            clients = data.get('clients', [])
            if clients:
                log_message(f"   Client IDs:")
                for client in clients:
                    log_message(f"     - {client}")
            
            return client_count, clients
        else:
            log_message(f"⚠️  API error: {response.status_code}")
            return 0, []
    except Exception as e:
        log_message(f"❌ Error: {e}")
        return 0, []

def send_pit_alert(track_id, team_name, message="PIT NOW"):
    """Send a pit alert via API"""
    log_message(f"🚨 Sending pit alert to team {team_name} on track {track_id}")
    
    payload = {
        "track_id": str(track_id),
        "team_name": team_name,
        "alert_message": message
    }
    
    try:
        response = requests.post(
            f"{BACKEND_URL}/api/trigger-pit-alert",
            json=payload,
            timeout=5
        )
        
        if response.status_code == 200:
            result = response.json()
            log_message(f"✅ Pit alert sent successfully!")
            log_message(f"   Room: {result.get('room')}")
            log_message(f"   Message: {result.get('message')}")
            return True
        else:
            log_message(f"❌ API error: {response.status_code} - {response.text}")
            return False
    except Exception as e:
        log_message(f"❌ Failed to send pit alert: {e}")
        return False

def monitor_and_alert(track_id, team_name, message, timeout=60):
    """
    Monitor a room and send alert when client joins
    
    Args:
        track_id: Track ID (e.g., "10")
        team_name: Team name (e.g., "ENZO.H")
        message: Pit alert message
        timeout: Maximum time to wait in seconds
    """
    room_name = f"team_track_{track_id}_{team_name}"
    
    log_message(f"🔔 Starting monitor for room: {room_name}")
    log_message(f"⏱️  Timeout: {timeout} seconds")
    log_message(f"📢 Alert message: '{message}'")
    log_message("")
    
    # Check initial room status
    initial_count, _ = check_room_status(room_name)
    
    if initial_count > 0:
        log_message("⚠️  Room already has clients!")
        response = input("Send alert immediately? (y/n): ")
        if response.lower() == 'y':
            return send_pit_alert(track_id, team_name, message)
    
    # Monitor for joins
    log_message("👀 Monitoring for client joins...")
    log_message("Press Ctrl+C to cancel")
    log_message("")
    
    start_time = time.time()
    alert_sent = False
    
    try:
        while time.time() - start_time < timeout:
            current_count, clients = check_room_status(room_name)
            
            if current_count > initial_count:
                log_message(f"🎉 NEW CLIENT JOINED! (Total: {current_count})")
                
                # Send pit alert
                if send_pit_alert(track_id, team_name, message):
                    log_message("✅ Alert delivered to newly joined client")
                    alert_sent = True
                else:
                    log_message("❌ Failed to deliver alert")
                
                break
            elif current_count < initial_count:
                log_message(f"📉 Client left room (now: {current_count})")
                initial_count = current_count
            
            time.sleep(CHECK_INTERVAL)
            
            # Show progress
            elapsed = int(time.time() - start_time)
            if elapsed % 10 == 0 and elapsed > 0:
                log_message(f"⏳ Waiting... ({elapsed}s elapsed)")
        
        if not alert_sent:
            log_message(f"⏰ Timeout reached ({timeout}s)")
            log_message("No new clients joined the room")
        
        return alert_sent
        
    except KeyboardInterrupt:
        log_message("")
        log_message("🛑 Monitoring cancelled by user")
        return False

def continuous_monitor(track_id, team_name, message):
    """Continuously monitor room and send alerts whenever someone joins"""
    room_name = f"team_track_{track_id}_{team_name}"
    
    log_message(f"🔔 Starting CONTINUOUS monitor for: {room_name}")
    log_message("Alerts will be sent EVERY time a client joins")
    log_message("Press Ctrl+C to stop")
    log_message("")
    
    last_client_count = 0
    alerts_sent = 0
    
    try:
        while True:
            current_count, clients = check_room_status(room_name)
            
            if current_count > last_client_count:
                new_joins = current_count - last_client_count
                log_message(f"🎉 {new_joins} new client(s) joined! (Total: {current_count})")
                
                if send_pit_alert(track_id, team_name, message):
                    alerts_sent += 1
                    log_message(f"✅ Alert #{alerts_sent} sent")
                else:
                    log_message("❌ Alert failed to send")
            
            last_client_count = current_count
            time.sleep(CHECK_INTERVAL)
            
    except KeyboardInterrupt:
        log_message("")
        log_message(f"🛑 Continuous monitoring stopped")
        log_message(f"   Total alerts sent: {alerts_sent}")
        return alerts_sent > 0

def main():
    parser = argparse.ArgumentParser(description='Monitor Socket.IO rooms and send pit alerts')
    
    parser.add_argument('--track', type=str, help='Track ID (e.g., 10)')
    parser.add_argument('--team', type=str, help='Team name (e.g., ENZO.H)')
    parser.add_argument('--room', type=str, help='Full room name (e.g., team_track_10_ENZO.H)')
    parser.add_argument('--message', type=str, default="PIT NOW", help='Alert message')
    parser.add_argument('--timeout', type=int, default=60, help='Timeout in seconds (default: 60)')
    parser.add_argument('--continuous', action='store_true', help='Continuous monitoring mode')
    parser.add_argument('--list-rooms', action='store_true', help='List all active rooms')
    parser.add_argument('--room-status', type=str, help='Check status of specific room')
    
    args = parser.parse_args()
    
    # Check API health
    if not check_api_health():
        log_message("❌ Backend API is not responding. Is the server running?")
        sys.exit(1)
    
    log_message("✅ Backend API is responding")
    log_message("")
    
    # Handle different modes
    if args.list_rooms:
        list_active_rooms()
        
    elif args.room_status:
        check_room_status(args.room_status)
        
    elif args.continuous:
        # Continuous monitoring mode
        if args.room:
            # Extract track and team from room name if provided
            # Format: team_track_{track_id}_{team_name}
            parts = args.room.split('_')
            if len(parts) >= 4 and parts[0] == 'team' and parts[1] == 'track':
                track_id = parts[2]
                team_name = '_'.join(parts[3:])  # Handle teams with underscores
                continuous_monitor(track_id, team_name, args.message)
            else:
                log_message(f"❌ Invalid room format: {args.room}")
                log_message("   Expected: team_track_{id}_{team_name}")
                sys.exit(1)
        elif args.track and args.team:
            continuous_monitor(args.track, args.team, args.message)
        else:
            log_message("❌ Need --track and --team or --room for continuous monitoring")
            sys.exit(1)
            
    elif args.room:
        # Single check with room name
        parts = args.room.split('_')
        if len(parts) >= 4 and parts[0] == 'team' and parts[1] == 'track':
            track_id = parts[2]
            team_name = '_'.join(parts[3:])
            monitor_and_alert(track_id, team_name, args.message, args.timeout)
        else:
            log_message(f"❌ Invalid room format: {args.room}")
            log_message("   Expected: team_track_{id}_{team_name}")
            sys.exit(1)
            
    elif args.track and args.team:
        # Single check with track and team
        monitor_and_alert(args.track, args.team, args.message, args.timeout)
        
    else:
        log_message("❌ Insufficient arguments")
        log_message("   Use --help for usage information")
        log_message("")
        log_message("Examples:")
        log_message("  python3 monitor_and_alert.py --track 10 --team 'ENZO.H' --message 'PIT NOW!'")
        log_message("  python3 monitor_and_alert.py --room team_track_10_ENZO.H --continuous")
        log_message("  python3 monitor_and_alert.py --list-rooms")
        log_message("  python3 monitor_and_alert.py --room-status team_track_10_ENZO.H")
        sys.exit(1)

if __name__ == "__main__":
    main()