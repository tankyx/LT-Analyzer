#!/bin/bash
set -e

# Kill any existing Xvfb processes
pkill -f Xvfb || true

# Use display 99
export DISPLAY=:99

# Start Xvfb with more memory and a smaller screen
Xvfb $DISPLAY -screen 0 1280x720x24 -ac +extension GLX +render -noreset &
XVFB_PID=$!
echo "Started Xvfb with PID: $XVFB_PID"

# Wait for Xvfb to initialize
sleep 3

# Check if Xvfb is running
if ! ps -p $XVFB_PID > /dev/null; then
  echo "Xvfb failed to start"
  exit 1
fi

echo "Xvfb is running correctly"
echo $XVFB_PID > /tmp/xvfb.pid
