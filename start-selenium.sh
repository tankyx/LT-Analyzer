#!/bin/bash
set -e  # Exit on any error

# Activate the Python virtual environment
cd "$HOME/LT-Analyzer"
source racing-venv/bin/activate

# Load environment variables from .env (FLASK_SECRET_KEY, CORS_ORIGINS, etc.)
if [ -f .env ]; then
    set -a
    . ./.env
    set +a
fi

# Set environment variables
export PYTHONUNBUFFERED=1

# Production server: gunicorn gthread, single worker (the app hosts the
# in-process parser loop + Socket.IO room state — see wsgi.py). Each
# connected websocket client pins one thread, so THREADS must exceed the
# target concurrent-user count. Set USE_DEV_SERVER=1 to fall back to the
# old Werkzeug dev server (instant rollback path).
if [ "${USE_DEV_SERVER:-0}" = "1" ]; then
    exec python race_ui.py
fi

GUNICORN_THREADS="${GUNICORN_THREADS:-600}"
# No access log — at hundreds of users it floods pm2 logs; nginx has one.
exec gunicorn -k gthread -w 1 --threads "$GUNICORN_THREADS" \
    --timeout 120 --graceful-timeout 30 --keep-alive 5 \
    --error-logfile - \
    -b 127.0.0.1:5000 wsgi:app
