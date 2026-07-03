#!/usr/bin/env python3
"""WSGI entry point for production deployment with gunicorn.

Usage (pm2 / systemd):
    racing-venv/bin/gunicorn -k gthread -w 1 --threads 600 \
        --timeout 120 --graceful-timeout 30 --keep-alive 5 \
        -b 127.0.0.1:5000 wsgi:app

Notes:
 - MUST run with a single worker (-w 1): the app hosts the in-process
   multi-track parser loop and all Socket.IO room state; there is no
   message_queue for cross-process fan-out.
 - gthread (threads) rather than eventlet/gevent: monkey-patching breaks the
   asyncio event loop the track parsers run on. Socket.IO runs in threading
   mode with native WebSocket support via simple-websocket; each connected
   websocket client pins one thread, so size --threads above the target
   concurrent-user count.
 - Importing race_ui does NOT start monitoring (that lives in its __main__
   block for the dev server), so we start it here, once.
"""

from race_ui import app, socketio, start_multi_track_monitoring

_monitoring_started = False


def _ensure_monitoring_started():
    """Idempotent guard — safe if the module is imported more than once."""
    global _monitoring_started
    if not _monitoring_started:
        _monitoring_started = True
        start_multi_track_monitoring()


_ensure_monitoring_started()

if __name__ == '__main__':
    socketio.run(app)
