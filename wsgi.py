#!/usr/bin/env python3
"""
WSGI entry point for production deployment with gunicorn
Usage: gunicorn --worker-class eventlet -w 1 --bind 127.0.0.1:5000 wsgi:app
"""

from race_ui import app, socketio

if __name__ == '__main__':
    socketio.run(app)