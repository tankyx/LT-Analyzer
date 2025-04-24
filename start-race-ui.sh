#!/bin/bash

# Activate the virtual environment
source ~/LT-Analyzer/racing-venv/bin/activate

# Change to the project directory
cd ~/LT-Analyzer

# Start Xvfb on display :99
export DISPLAY=:99
Xvfb :99 -screen 0 1920x1080x24 -ac &
XVFB_PID=$!

# Function to clean up Xvfb on exit
cleanup() {
    echo "Cleaning up Xvfb process..."
    if [ -n "$XVFB_PID" ]; then
        kill $XVFB_PID
    fi
    exit
}

# Set up trap to catch script termination
trap cleanup SIGINT SIGTERM EXIT

# Sleep briefly to ensure Xvfb is fully started
sleep 1

# Run the Python script
echo "Starting race_ui.py with virtual display $DISPLAY"
python race_ui.py

