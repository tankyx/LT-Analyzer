#!/bin/bash

source /home/ubuntu/LT-Analyzer/racing-venv/bin/activate
python /home/ubuntu/LT-Analyzer/race_ui.py &
APP_PID=$!

# Catch termination signals
trap cleanup SIGINT SIGTERM

# Wait for the process to finish
wait $APP_PID
cleanup
