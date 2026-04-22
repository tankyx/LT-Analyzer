#!/usr/bin/env python3
"""
Initialize auth.db and tracks.db with required tables.

Admin bootstrap:
  The first admin user is created if (and only if) no user exists yet. Credentials
  come from the ADMIN_USERNAME / ADMIN_PASSWORD environment variables (typically
  loaded from .env). There is no hardcoded default password.
"""

import os
import sqlite3
import sys

import bcrypt


def _require_admin_credentials():
    username = os.environ.get('ADMIN_USERNAME', '').strip()
    password = os.environ.get('ADMIN_PASSWORD', '')
    if not username or not password:
        sys.stderr.write(
            'ERROR: ADMIN_USERNAME and ADMIN_PASSWORD must be set in the environment '
            '(or in .env) to bootstrap the initial admin user.\n'
        )
        sys.exit(1)
    if len(password) < 12:
        sys.stderr.write('ERROR: ADMIN_PASSWORD must be at least 12 characters.\n')
        sys.exit(1)
    return username, password


def initialize_auth_db():
    """Initialize auth database with users table"""
    print("Initializing auth.db...")
    conn = sqlite3.connect('auth.db')
    cursor = conn.cursor()

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

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS login_attempts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT,
            ip_address TEXT,
            success BOOLEAN,
            attempted_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')

    cursor.execute('SELECT COUNT(*) FROM users')
    user_count = cursor.fetchone()[0]
    if user_count == 0:
        username, password = _require_admin_credentials()
        password_hash = bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')
        cursor.execute(
            "INSERT INTO users (username, password_hash, email, role) VALUES (?, ?, ?, ?)",
            (username, password_hash, f'{username}@localhost', 'admin'),
        )
        print(f"Created initial admin user '{username}'. Remember to clear ADMIN_PASSWORD from .env after first boot.")
    else:
        print(f"auth.db already has {user_count} user(s); skipping admin bootstrap.")

    conn.commit()
    conn.close()
    print("auth.db initialized successfully")


def initialize_tracks_db():
    """Initialize tracks database with tracks table"""
    print("Initializing tracks.db...")
    conn = sqlite3.connect('tracks.db')
    cursor = conn.cursor()

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

    cursor.execute("SELECT COUNT(*) FROM tracks WHERE track_name = 'Karting Mariembourg'")
    if cursor.fetchone()[0] == 0:
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
            1,
        ))
        print("Created default Mariembourg track")

    conn.commit()
    conn.close()
    print("tracks.db initialized successfully")


if __name__ == '__main__':
    initialize_auth_db()
    initialize_tracks_db()
    print("\nDatabase initialization complete!")
