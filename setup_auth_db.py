#!/usr/bin/env python3
import sqlite3
import hashlib
from datetime import datetime

def setup_auth_database():
    """Create authentication tables and add admin user"""
    conn = sqlite3.connect('race_data.db')
    cursor = conn.cursor()
    
    # Create users table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            email TEXT,
            role TEXT DEFAULT 'user',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            last_login TIMESTAMP,
            is_active BOOLEAN DEFAULT 1
        )
    ''')
    
    # Create tracks table for admin management
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS tracks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            location TEXT,
            length_meters INTEGER,
            description TEXT,
            is_active BOOLEAN DEFAULT 1,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    # Create sessions table for login sessions
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS sessions (
            id TEXT PRIMARY KEY,
            user_id INTEGER NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            expires_at TIMESTAMP NOT NULL,
            FOREIGN KEY (user_id) REFERENCES users(id)
        )
    ''')
    
    # Create login_attempts table for security
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS login_attempts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT,
            ip_address TEXT,
            success BOOLEAN,
            attempted_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    # Hash the admin password
    admin_password = "0xC4F31664"
    password_hash = hashlib.sha256(admin_password.encode()).hexdigest()
    
    # Check if admin user exists
    cursor.execute("SELECT id FROM users WHERE username = ?", ("admin",))
    if not cursor.fetchone():
        # Insert admin user
        cursor.execute('''
            INSERT INTO users (username, password_hash, email, role) 
            VALUES (?, ?, ?, ?)
        ''', ("admin", password_hash, "admin@lt-analyzer.com", "admin"))
        print("Admin user created successfully")
    else:
        print("Admin user already exists")
    
    conn.commit()
    conn.close()
    print("Authentication database setup complete")

if __name__ == "__main__":
    setup_auth_database()