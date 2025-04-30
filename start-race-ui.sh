#!/bin/bash

# Kill any existing Xvfb processes
pkill Xvfb

# Remove any stale lock files
rm -f /tmp/.X*-lock
rm -f /tmp/.X11-unix/X*

# Start Xvfb with a unique display number
DISPLAY_NUM=99
Xvfb :${DISPLAY_NUM} -screen 0 1920x1080x24 &
XVFB_PID=$!

# Wait for Xvfb to start
sleep 2

# Set DISPLAY environment variable
export DISPLAY=:${DISPLAY_NUM}

echo "Starting race_ui.py with virtual display :${DISPLAY_NUM}"

# Run your Python script
python3 /home/ubuntu/LT-Analyzer/race_ui.py &
APP_PID=$!

# Setup trap to clean up
cleanup() {
    echo "Cleaning up processes..."
    kill -9 $APP_PID 2>/dev/null || true
    kill -9 $XVFB_PID 2>/dev/null || true
    rm -f /tmp/.X${DISPLAY_NUM}-lock
    rm -f /tmp/.X11-unix/X${DISPLAY_NUM}
    exit 0
}

# Catch termination signals
trap cleanup SIGINT SIGTERM

# Wait for the process to finish
wait $APP_PID
cleanup
