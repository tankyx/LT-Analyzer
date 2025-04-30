#!/bin/bash
export DISPLAY=:99
export DBUS_SESSION_BUS_ADDRESS=/dev/null
export PYTHONUNBUFFERED=1

# Start Xvfb if not running
if ! pgrep -f "Xvfb :99" > /dev/null; then
  Xvfb :99 -screen 0 1280x720x24 -ac +extension GLX +render -noreset &
  sleep 2
  echo "Xvfb started on display :99"
fi

# Activate virtual environment
cd ~/LT-Analyzer
source racing-venv/bin/activate

# Make sure we're using the system chromium
export CHROME_PATH=/usr/bin/chromium-browser

# Run the app
exec python race_ui.py
