#!/bin/bash
# Simplified PM2 backend startup script (no exec, just run)
cd /home/ubuntu/LT-Analyzer
source racing-venv/bin/activate
python race_ui.py --multi-track --config multi-track-config.yml
