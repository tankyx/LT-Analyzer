#!/bin/bash
export DISPLAY=:99

# Start Xvfb if not running
if ! pgrep -f "Xvfb :99" > /dev/null; then
  ~/LT-Analyzer/start-xvfb.sh
fi

# Activate virtual environment and run the app
cd ~/LT-Analyzer
source racing-venv/bin/activate

# Set Firefox options explicitly
export MOZ_HEADLESS=1
export MOZ_DBUS_REMOTE=1

# Run with explicit timeouts
python race_ui.py
