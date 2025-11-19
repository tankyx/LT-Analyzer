#!/bin/bash
# Quick restart script for backend to apply logging changes

# Kill existing backend
echo "Stopping backend..."
pkill -f "race_ui.py" 
sleep 2

# Start fresh backend
echo "Starting backend with improved pit alert logging..."
cd /home/ubuntu/LT-Analyzer
source racing-venv/bin/activate
nohup python race_ui.py --multi-track --config multi-track-config.yml > backend.log 2>&1 &

echo "Backend restarted. Check logs in 5 seconds..."
sleep 5
tail -20 backend.log
