#!/bin/bash
# Proper PM2 backend startup script with virtual environment

# Use the virtual environment's Python directly
cd /home/ubuntu/LT-Analyzer
export PYTHONUNBUFFERED=1

# Use the Python interpreter from the venv
exec /home/ubuntu/LT-Analyzer/racing-venv/bin/python race_ui.py --multi-track --config multi-track-config.yml