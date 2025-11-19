#!/bin/bash
# Absolute path to venv Python
cd /home/ubuntu/LT-Analyzer
exec /home/ubuntu/LT-Analyzer/racing-venv/bin/python race_ui.py --multi-track --config /home/ubuntu/LT-Analyzer/multi-track-config.yml
