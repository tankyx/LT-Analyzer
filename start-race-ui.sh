#!/bin/bash
set -e  # Exit on any error

# Function to cleanup processes on exit
cleanup() {
  echo "Cleaning up processes..."
  pkill -f Xvfb || true
  pkill -f geckodriver || true
  pkill -f firefox || true
}

# Ensure cleanup runs on exit
trap cleanup EXIT

# Set up Python environment
cd /home/ubuntu/LT-Analyzer
source racing-venv/bin/activate

# Make sure Firefox is installed
if ! command -v firefox &> /dev/null; then
  echo "Firefox not found. Attempting to install..."
  sudo apt update
  sudo apt install -y firefox
fi

# Kill any existing Xvfb processes
pkill -f Xvfb || true

# Choose a different display number to avoid conflicts
export DISPLAY=:99

# Start Xvfb with more memory and a smaller screen
Xvfb $DISPLAY -screen 0 1280x720x24 -ac +extension GLX +render -noreset &
XVFB_PID=$!
echo "Started Xvfb with PID: $XVFB_PID"

# Wait for Xvfb to initialize
sleep 3

# Test if Xvfb is working
if ! xdpyinfo -display $DISPLAY >/dev/null 2>&1; then
  echo "Xvfb failed to start properly"
  exit 1
fi

echo "Xvfb is running correctly"

# Start the application
echo "Starting race_ui.py..."
python race_ui.py
