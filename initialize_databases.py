#!/usr/bin/env python3
"""
Initialize auth.db and tracks.db with required tables
"""

import sqlite3
import bcrypt

def initialize_auth_db():
    """Initialize auth database with users table"""
    print("Initializing auth.db...")
    conn = sqlite3.connect('auth.db')
    cursor = conn.cursor()

    # Create users table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            email TEXT,
            role TEXT DEFAULT 'user',
            is_active BOOLEAN DEFAULT 1,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            last_login TIMESTAMP
        )
    ''')

    # Create sessions table for Flask-Login
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS sessions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            session_token TEXT UNIQUE NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            expires_at TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users(id)
        )
    ''')

    # Check if admin user exists
    cursor.execute("SELECT COUNT(*) FROM users WHERE username = 'admin'")
    if cursor.fetchone()[0] == 0:
        # Create default admin user (password: admin)
        password_hash = bcrypt.hashpw('admin'.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')
        cursor.execute(
            "INSERT INTO users (username, password_hash, email, role) VALUES (?, ?, ?, ?)",
            ('admin', password_hash, 'admin@localhost', 'admin')
        )
        print("Created default admin user (username: admin, password: admin)")

    conn.commit()
    conn.close()
    print("auth.db initialized successfully")

def initialize_tracks_db():
    """Initialize tracks database with tracks table"""
    print("Initializing tracks.db...")
    conn = sqlite3.connect('tracks.db')
    cursor = conn.cursor()

    # Create tracks table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS tracks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            track_name TEXT NOT NULL,
            location TEXT,
            length_meters INTEGER,
            description TEXT,
            timing_url TEXT,
            websocket_url TEXT,
            column_mappings TEXT,
            is_active BOOLEAN DEFAULT 1,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')

    # Check if Mariembourg track exists
    cursor.execute("SELECT COUNT(*) FROM tracks WHERE track_name = 'Karting Mariembourg'")
    if cursor.fetchone()[0] == 0:
        # Create default Mariembourg track
        cursor.execute('''
            INSERT INTO tracks (track_name, location, length_meters, description, timing_url, websocket_url, is_active)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        ''', (
            'Karting Mariembourg',
            'Mariembourg, Belgium',
            1360,
            'Karting track in Mariembourg',
            'https://www.apex-timing.com/live-timing/karting-mariembourg/index.html',
            'ws://www.apex-timing.com:8585/',
            1
        ))
        print("Created default Mariembourg track")

    conn.commit()
    conn.close()
    print("tracks.db initialized successfully")

if __name__ == '__main__':
    initialize_auth_db()
    initialize_tracks_db()
    print("\nDatabase initialization complete!")
    print("Default credentials - Username: admin, Password: admin")
    print("Please change the admin password after first login.")
