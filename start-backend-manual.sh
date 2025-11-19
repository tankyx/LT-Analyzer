#!/bin/bash
cd /home/ubuntu/LT-Analyzer
source racing-venv/bin/activate
python race_ui.py --multi-track --config multi-track-config.yml
