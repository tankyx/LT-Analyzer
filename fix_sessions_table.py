#!/usr/bin/env python3
import sqlite3
from datetime import datetime

def fix_sessions_table():
    """Fix the sessions table schema"""
    conn = sqlite3.connect('race_data.db')
    cursor = conn.cursor()
    
    # Drop the old sessions table if it exists
    cursor.execute("DROP TABLE IF EXISTS sessions")
    
    # Create sessions table with correct schema
    cursor.execute('''
        CREATE TABLE sessions (
            id TEXT PRIMARY KEY,
            user_id INTEGER NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            expires_at TIMESTAMP NOT NULL,
            FOREIGN KEY (user_id) REFERENCES users(id)
        )
    ''')
    
    conn.commit()
    conn.close()
    print("Sessions table fixed successfully")

if __name__ == "__main__":
    fix_sessions_table()