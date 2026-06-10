"""Migrate Apex WebSocket URLs from www.apex-timing.com to live-data.apex-timing.com.

Apex Timing returned after an outage with a new WebSocket host architecture.
The website (www) is unchanged, but the WebSocket server now lives on the
live-data subdomain. Port numbers stay the same.

This script updates:
  1. apex_known_tracks.json — websocket_url and host fields
  2. tracks.db — websocket_url column for all apex tracks
"""

import json
import os
import shutil
import sqlite3
import sys

OLD_HOST = "www.apex-timing.com"
NEW_HOST = "live-data.apex-timing.com"
OLD_WS_PREFIX = f"wss://{OLD_HOST}"
NEW_WS_PREFIX = f"wss://{NEW_HOST}"

# ── 1. Update apex_known_tracks.json ──────────────────────────────────

def migrate_json(path):
    with open(path, 'r', encoding='utf-8') as f:
        data = json.load(f)

    changed = 0
    for entry in data:
        if entry.get('host') == OLD_HOST:
            entry['host'] = NEW_HOST
            changed += 1
        if 'websocket_url' in entry and OLD_WS_PREFIX in entry['websocket_url']:
            entry['websocket_url'] = entry['websocket_url'].replace(OLD_WS_PREFIX, NEW_WS_PREFIX)
            # mark for recount
            pass

    # Write back
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
        f.write('\n')

    print(f"  apex_known_tracks.json: {len(data)} entries, {changed} host fields updated")
    return data


# ── 2. Update tracks.db ──────────────────────────────────────────────

def migrate_db(path):
    # Backup
    backup = f"{path}.bak-{__import__('time').strftime('%Y%m%d-%H%M%S')}"
    shutil.copy2(path, backup)
    print(f"  Backup: {backup}")

    conn = sqlite3.connect(path)
    cursor = conn.cursor()

    # Count before
    before = cursor.execute(
        "SELECT COUNT(*) FROM tracks WHERE provider='apex' AND websocket_url LIKE ?",
        (f"%{OLD_HOST}%",)
    ).fetchone()[0]
    print(f"  Apex tracks with old host: {before}")

    if before == 0:
        print("  Nothing to migrate in tracks.db.")
        conn.close()
        return

    cursor.execute(
        "UPDATE tracks SET websocket_url = REPLACE(websocket_url, ?, ?), "
        "                 updated_at = CURRENT_TIMESTAMP "
        "WHERE provider = 'apex' AND websocket_url LIKE ?",
        (OLD_WS_PREFIX, NEW_WS_PREFIX, f"%{OLD_HOST}%")
    )
    updated = cursor.rowcount
    conn.commit()

    # Verify after
    after = cursor.execute(
        "SELECT COUNT(*) FROM tracks WHERE provider='apex' AND websocket_url LIKE ?",
        (f"%{OLD_HOST}%",)
    ).fetchone()[0]

    conn.close()

    print(f"  Updated: {updated} rows, remaining with old host: {after}")
    if after > 0:
        print("  WARNING: some apex tracks still reference old host!", file=sys.stderr)


# ── Main ─────────────────────────────────────────────────────────────

def main():
    print("Apex WebSocket Host Migration")
    print(f"  {OLD_HOST}  →  {NEW_HOST}")
    print()

    # JSON
    json_path = "apex_known_tracks.json"
    if os.path.exists(json_path):
        migrate_json(json_path)
    else:
        print(f"  SKIP: {json_path} not found")

    print()

    # Database
    db_path = "tracks.db"
    if os.path.exists(db_path):
        migrate_db(db_path)
    else:
        print(f"  SKIP: {db_path} not found")

    print()
    print("Done. Restart the backend for changes to take effect.")

if __name__ == '__main__':
    main()
