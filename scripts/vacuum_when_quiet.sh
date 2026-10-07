#!/bin/bash
# VACUUM race_data_track_N.db files once their track has been write-idle
# for IDLE_SECS (checks db + -wal mtimes). Usage: vacuum_when_quiet.sh 4 10
cd /home/ubuntu/LT-Analyzer || exit 1
IDLE_SECS=${IDLE_SECS:-900}
pending="$*"
while [ -n "$pending" ]; do
  remaining=""
  for t in $pending; do
    db="race_data_track_$t.db"
    last=$(stat -c %Y "$db" 2>/dev/null || echo 0)
    if [ -f "$db-wal" ]; then
      w=$(stat -c %Y "$db-wal")
      [ "$w" -gt "$last" ] && last=$w
    fi
    now=$(date +%s)
    if [ $((now - last)) -ge "$IDLE_SECS" ]; then
      before=$(du -h "$db" | cut -f1)
      echo "$(date -Is) track $t idle $((now - last))s — vacuuming ($before)"
      if sqlite3 "$db" "PRAGMA busy_timeout=60000; VACUUM;" >/dev/null; then
        echo "$(date -Is) track $t vacuumed: $before -> $(du -h "$db" | cut -f1)"
      else
        echo "$(date -Is) track $t VACUUM failed, will retry"
        remaining="$remaining $t"
      fi
    else
      remaining="$remaining $t"
    fi
  done
  pending="${remaining# }"
  [ -n "$pending" ] && sleep 300
done
echo "$(date -Is) all pending vacuums done"
