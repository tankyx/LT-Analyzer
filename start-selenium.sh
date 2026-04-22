#!/bin/bash
set -e  # Exit on any error

# Activate the Python virtual environment
cd /home/ubuntu/LT-Analyzer
source racing-venv/bin/activate

# Load environment variables from .env (FLASK_SECRET_KEY, CORS_ORIGINS, etc.)
if [ -f .env ]; then
    set -a
    . ./.env
    set +a
fi

# Set environment variables
export PYTHONUNBUFFERED=1

# Start the Flask application with Playwright backend
exec python race_ui.py
