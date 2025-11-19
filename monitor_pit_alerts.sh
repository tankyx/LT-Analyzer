#!/bin/bash
# Real-time pit alert monitor
echo "🔔 Monitoring for pit alerts in real-time..."
echo "Press Ctrl+C to stop monitoring"
echo ""
tail -f /home/ubuntu/LT-Analyzer/backend.log | grep --line-buffered -E "PIT ALERT|pit.*alert|trigger-pit-alert"
