#!/usr/bin/env python3
"""Test WebSocket connectivity to the Flask-SocketIO server"""

import socketio

# Create a Socket.IO client
sio = socketio.Client(logger=True, engineio_logger=True)

@sio.event
def connect():
    print("Connected to server!")

@sio.event
def disconnect():
    print("Disconnected from server!")

@sio.event
def race_data_update(data):
    print("Received race data update:")
    print(f"- Teams: {len(data.get('teams', []))} teams")
    print(f"- Last update: {data.get('last_update', 'N/A')}")
    print(f"- Is running: {data.get('is_running', False)}")

if __name__ == '__main__':
    try:
        # Try to connect to the local server
        print("Attempting to connect to http://localhost:5000...")
        sio.connect('http://localhost:5000', transports=['polling', 'websocket'])
        
        # Wait a bit to receive data
        sio.sleep(2)
        
        # Disconnect
        sio.disconnect()
        
    except Exception as e:
        print(f"Error: {e}")