import sqlite3

conn = sqlite3.connect('race_data.db')
cursor = conn.cursor()

# Check if tracks table exists
cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='tracks';")
table_exists = cursor.fetchone()
print(f"Tracks table exists: {table_exists}")

# Get all tracks
cursor.execute('SELECT * FROM tracks')
tracks = cursor.fetchall()
print(f"\nNumber of tracks in database: {len(tracks)}")

# Show all tracks
for track in tracks:
    print(f"Track: {track}")

# Get column names
cursor.execute("PRAGMA table_info(tracks)")
columns = cursor.fetchall()
print("\nTable columns:")
for col in columns:
    print(f"  {col}")

conn.close()