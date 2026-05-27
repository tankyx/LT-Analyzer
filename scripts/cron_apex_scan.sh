#!/bin/bash
# Periodic Apex feed-port scan: discover karting circuits that are live right now
# and add the newly-named ones to tracks.db. Restarts the backend ONLY when new
# tracks were actually added (so it doesn't disrupt live data collection on every
# run). Intended to run from cron — see the crontab entry installed alongside it.
#
#   crontab:  0 */3 * * * /home/ubuntu/LT-Analyzer/scripts/cron_apex_scan.sh
set -u
cd /home/ubuntu/LT-Analyzer || exit 1
PY=./racing-venv/bin/python
LOG=logs/apex_scan.log
mkdir -p logs

ts() { date '+%Y-%m-%d %H:%M:%S'; }

before=$(sqlite3 tracks.db "SELECT COUNT(*) FROM tracks;" 2>/dev/null || echo 0)
echo "[$(ts)] scan start (tracks=$before)" >> "$LOG"

# --named-only: never re-introduce the port-placeholder rows the operator pruned;
# an idle circuit gets added later once a scan catches it with a live name.
"$PY" scripts/scan_apex_ports.py --start 6900 --end 9999 --concurrency 60 \
      --apply --named-only >> "$LOG" 2>&1

after=$(sqlite3 tracks.db "SELECT COUNT(*) FROM tracks;" 2>/dev/null || echo "$before")
added=$(( after - before ))
echo "[$(ts)] scan done (tracks=$after, +$added)" >> "$LOG"

if [ "$added" -gt 0 ]; then
    echo "[$(ts)] +$added new track(s) — restarting backend to monitor them" >> "$LOG"
    pm2 restart lt-analyzer-backend >> "$LOG" 2>&1
fi
