#!/usr/bin/env python3
import sqlite3

def create_race_sessions_table():
    """Create the race_sessions table"""
    conn = sqlite3.connect('race_data.db')
    cursor = conn.cursor()
    
    # Create race_sessions table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS race_sessions (
            session_id INTEGER PRIMARY KEY AUTOINCREMENT,
            start_time TEXT,
            name TEXT,
            track TEXT
        )
    ''')
    
    conn.commit()
    conn.close()
    print("race_sessions table created successfully")

if __name__ == "__main__":
    create_race_sessions_table()