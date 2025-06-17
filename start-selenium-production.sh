#!/bin/bash
# Start Flask with gunicorn and eventlet for production WebSocket support

cd /home/ubuntu/LT-Analyzer

# Activate virtual environment
source racing-venv/bin/activate

# Install gunicorn if not already installed
pip install gunicorn[eventlet]

# Start gunicorn with eventlet worker for WebSocket support
# Using 1 worker because we need to maintain WebSocket connections and shared state
exec gunicorn --worker-class eventlet -w 1 --bind 127.0.0.1:5000 --timeout 120 wsgi:app