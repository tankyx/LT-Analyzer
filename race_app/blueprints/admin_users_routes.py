"""Admin endpoints: user management, invite codes, audit log."""
import sqlite3
import secrets

from flask import Blueprint, jsonify, request

import race_ui

from race_ui import (
    admin_required,
)


admin_users_bp = Blueprint('admin_users', __name__)


@admin_users_bp.route('/api/admin/users', methods=['GET'])
@admin_required
def get_users():
    """Get all users (admin only)"""
    with race_ui.get_db_connection() as conn:
        rows = conn.execute(
            '''SELECT id, username, email, role, created_at, last_login, is_active
               FROM users ORDER BY created_at DESC'''
        ).fetchall()
    return jsonify([dict(row) for row in rows])

@admin_users_bp.route('/api/admin/users', methods=['POST'])
@admin_required
def create_user():
    """Create new user (admin only)"""
    data = request.get_json()
    username = data.get('username')
    password = data.get('password')
    email = data.get('email')
    role = data.get('role', 'user')
    
    if not username or not password:
        return jsonify({'error': 'Username and password required'}), 400

    if role not in ('user', 'admin'):
        return jsonify({'error': 'Invalid role'}), 400

    password_hash = race_ui.hash_password(password)

    try:
        with race_ui.get_db_connection() as conn:
            cursor = conn.execute(
                '''INSERT INTO users (username, password_hash, email, role, email_verified)
                   VALUES (?, ?, ?, ?, 1)''',
                (username, password_hash, email, role),
            )
            user_id = cursor.lastrowid
    except sqlite3.IntegrityError:
        return jsonify({'error': 'Username already exists'}), 400

    race_ui._audit('admin_user_created', actor_user_id=request.current_user['id'],
           target=username, details={'role': role, 'user_id': user_id})
    return jsonify({
        'success': True,
        'user': {
            'id': user_id,
            'username': username,
            'email': email,
            'role': role,
        },
    })

_USER_UPDATABLE_COLUMNS = {'email', 'role', 'is_active', 'password_hash'}


@admin_users_bp.route('/api/admin/users/<int:user_id>', methods=['PUT'])
@admin_required
def update_user(user_id):
    """Update user (admin only)"""
    data = request.get_json(silent=True) or {}

    # Build a whitelisted (column, value) list. Column names never come from user input.
    updates = []
    params = []

    if 'email' in data:
        updates.append(('email', data['email']))
    if 'role' in data:
        if data['role'] not in ('user', 'admin'):
            return jsonify({'error': 'Invalid role'}), 400
        updates.append(('role', data['role']))
    if 'is_active' in data:
        updates.append(('is_active', 1 if data['is_active'] else 0))
    if 'password' in data and data['password']:
        updates.append(('password_hash', race_ui.hash_password(data['password'])))

    if not updates:
        return jsonify({'error': 'No fields to update'}), 400

    for col, _ in updates:
        assert col in _USER_UPDATABLE_COLUMNS, f'Column {col!r} not in whitelist'

    set_clause = ', '.join(f'{col} = ?' for col, _ in updates)
    params = [value for _, value in updates] + [user_id]

    with race_ui.get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(f'UPDATE users SET {set_clause} WHERE id = ?', params)
        # Invalidate existing sessions on password change so stolen cookies are cut off.
        if any(col == 'password_hash' for col, _ in updates):
            cursor.execute('DELETE FROM sessions WHERE user_id = ?', (user_id,))
        conn.commit()

    race_ui._audit('admin_user_updated', actor_user_id=request.current_user['id'],
           target=str(user_id),
           details={'fields': [c for c, _ in updates]})
    return jsonify({'success': True})

@admin_users_bp.route('/api/admin/users/<int:user_id>', methods=['DELETE'])
@admin_required
def delete_user(user_id):
    """Delete user (admin only)"""
    # Prevent deleting the bootstrap admin
    if user_id == 1:
        return jsonify({'error': 'Cannot delete admin user'}), 400
    with race_ui.get_db_connection() as conn:
        conn.execute('DELETE FROM sessions WHERE user_id = ?', (user_id,))
        conn.execute('DELETE FROM users WHERE id = ?', (user_id,))
    race_ui._audit('admin_user_deleted', actor_user_id=request.current_user['id'],
           target=str(user_id))
    return jsonify({'success': True})


# --- Admin invite codes -----------------------------------------------------

@admin_users_bp.route('/api/admin/invite-codes', methods=['GET'])
@admin_required
def list_invite_codes():
    with race_ui.get_db_connection() as conn:
        rows = conn.execute(
            'SELECT id, code, max_uses, uses, created_by, created_at, expires_at, note '
            'FROM invite_codes ORDER BY created_at DESC'
        ).fetchall()
    return jsonify({'invites': [dict(r) for r in rows]})


@admin_users_bp.route('/api/admin/invite-codes', methods=['POST'])
@admin_required
def create_invite_code():
    data = request.get_json(silent=True) or {}
    raw = data.get('max_uses', 1)
    try:
        max_uses = int(raw)
    except (TypeError, ValueError):
        return jsonify({'error': 'invalid_max_uses'}), 400
    if max_uses < 1 or max_uses > 1000:
        return jsonify({'error': 'invalid_max_uses'}), 400
    expires_at = (data.get('expires_at') or '').strip() or None
    note = (data.get('note') or '').strip() or None
    code = secrets.token_urlsafe(8)
    with race_ui.get_db_connection() as conn:
        conn.execute(
            'INSERT INTO invite_codes (code, max_uses, created_by, expires_at, note) '
            'VALUES (?, ?, ?, ?, ?)',
            (code, max_uses, request.current_user['id'], expires_at, note),
        )
    race_ui._audit('admin_invite_created', actor_user_id=request.current_user['id'],
           target=code, details={'max_uses': max_uses, 'expires_at': expires_at})
    return jsonify({'success': True, 'code': code, 'max_uses': max_uses})


@admin_users_bp.route('/api/admin/invite-codes/<int:invite_id>', methods=['DELETE'])
@admin_required
def revoke_invite_code(invite_id):
    with race_ui.get_db_connection() as conn:
        cur = conn.execute('DELETE FROM invite_codes WHERE id = ?', (invite_id,))
    if cur.rowcount == 0:
        return jsonify({'error': 'not_found'}), 404
    race_ui._audit('admin_invite_revoked', actor_user_id=request.current_user['id'],
           target=str(invite_id))
    return jsonify({'success': True})


# --- Admin audit-log reader -------------------------------------------------

@admin_users_bp.route('/api/admin/audit-log', methods=['GET'])
@admin_required
def admin_audit_log():
    action = (request.args.get('action') or '').strip()
    actor = (request.args.get('actor') or '').strip()
    try:
        limit = min(max(int(request.args.get('limit') or 200), 1), 1000)
    except (TypeError, ValueError):
        limit = 200
    try:
        offset = max(int(request.args.get('offset') or 0), 0)
    except (TypeError, ValueError):
        offset = 0
    clauses = []
    params: list = []
    if action:
        clauses.append('action = ?')
        params.append(action)
    if actor:
        clauses.append('actor_user_id = ?')
        try:
            params.append(int(actor))
        except (TypeError, ValueError):
            return jsonify({'error': 'invalid_actor'}), 400
    where = ('WHERE ' + ' AND '.join(clauses)) if clauses else ''
    sql = (
        f'SELECT id, actor_user_id, action, target, ip_address, user_agent, timestamp, details '
        f'FROM audit_log {where} ORDER BY timestamp DESC LIMIT ? OFFSET ?'
    )
    params.extend([limit, offset])
    with race_ui.get_db_connection() as conn:
        rows = conn.execute(sql, params).fetchall()
    return jsonify({'rows': [dict(r) for r in rows], 'limit': limit, 'offset': offset})
