#!/bin/bash
set -e

cd /home/ubuntu/LT-Analyzer
source racing-venv/bin/activate

# Install required packages if not present
pip install selenium webdriver_manager flask flask-cors

# Start Xvfb first
./start-xvfb.sh

# Set the display for the application
export DISPLAY=:99
export MOZ_HEADLESS=1

# Run the application
exec python race_ui.py
