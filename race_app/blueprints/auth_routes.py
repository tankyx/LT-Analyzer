"""Auth + registration endpoints (/api/auth/*)."""
import re
import secrets
import sqlite3
import traceback
from datetime import datetime, timedelta

from email_service import send_password_reset_email, send_verification_email, send_welcome_email
from flask import Blueprint, jsonify, request, session
from turnstile import require_turnstile

import race_ui
from race_ui import (
    EMAIL_RE,
    REGISTRATION_OPEN,
    RESERVED_USERNAMES,
    RESET_TOKEN_HOURS,
    USERNAME_RE,
    VERIFICATION_TOKEN_HOURS,
    _rate_limit_hit,
    login_required,
)


auth_bp = Blueprint('auth', __name__)


@auth_bp.route('/api/auth/login', methods=['POST'])
@require_turnstile()
def login():
    """User login endpoint"""
    try:
        data = request.get_json(silent=True)
        if not data:
            return jsonify({'error': 'No data provided'}), 400

        username = (data.get('username') or '').strip()
        password = data.get('password') or ''

        if not username or not password:
            return jsonify({'error': 'Username and password required'}), 400

        ip_address = request.remote_addr or '-'

        if race_ui._is_rate_limited(username, ip_address):
            race_ui._audit('login_rate_limited', target=username)
            return jsonify({
                'error': f'Too many failed attempts. Try again in {race_ui.LOGIN_WINDOW_MINUTES} minutes.'
            }), 429

        with race_ui.get_db_connection() as conn:
            cursor = conn.cursor()

            # Record attempt up front (will flip success=1 on match)
            cursor.execute(
                '''INSERT INTO login_attempts (username, ip_address, success)
                   VALUES (?, ?, 0)''',
                (username, ip_address),
            )
            attempt_id = cursor.lastrowid

            cursor.execute(
                '''SELECT id, username, role, email, is_active, password_hash,
                          email_verified, deleted_at
                   FROM users WHERE username = ?''',
                (username,),
            )
            user = cursor.fetchone()

            if (not user or not user['is_active'] or user['deleted_at']
                    or not race_ui.verify_password(password, user['password_hash'])):
                conn.commit()
                race_ui._audit('login_failed',
                       actor_user_id=user['id'] if user else None,
                       target=username)
                return jsonify({'error': 'Invalid credentials'}), 401

            if not user['email_verified']:
                conn.commit()
                race_ui._audit('login_blocked_unverified', actor_user_id=user['id'], target=username)
                return jsonify({
                    'error': 'email_not_verified',
                    'email': user['email'],
                }), 401

            # Upgrade legacy SHA256 hash to bcrypt opportunistically.
            if not race_ui._looks_like_bcrypt(user['password_hash']):
                cursor.execute(
                    'UPDATE users SET password_hash = ? WHERE id = ?',
                    (race_ui.hash_password(password), user['id']),
                )

            cursor.execute(
                'UPDATE users SET last_login = ? WHERE id = ?',
                (datetime.now().isoformat(), user['id']),
            )
            cursor.execute(
                'UPDATE login_attempts SET success = 1 WHERE id = ?',
                (attempt_id,),
            )
            conn.commit()

            session_id = race_ui.create_session(user['id'])
            session['session_id'] = session_id
            # Rotate CSRF token so a pre-login attacker token can't be reused.
            session['csrf_token'] = secrets.token_urlsafe(32)

            race_ui._audit('login_success', actor_user_id=user['id'], target=username)
            return jsonify({
                'success': True,
                'user': {
                    'id': user['id'],
                    'username': user['username'],
                    'role': user['role'],
                    'email': user['email'],
                },
            })

    except sqlite3.Error as e:
        print(f'Database error in login: {e}')
        traceback.print_exc()
        return jsonify({'error': 'Database error occurred'}), 500
    except Exception as e:
        print(f'Login error: {e}')
        traceback.print_exc()
        return jsonify({'error': 'An error occurred during login'}), 500

@auth_bp.route('/api/auth/logout', methods=['POST'])
@login_required
def logout():
    """User logout endpoint"""
    session_id = session.get('session_id')
    if session_id:
        with race_ui.get_db_connection() as conn:
            # The token lives in session_token, not id (which is an autoincrement PK).
            # The pre-fix version of this handler matched on id and therefore never
            # actually deleted any session row.
            conn.execute('DELETE FROM sessions WHERE session_token = ?', (session_id,))
        session.clear()

    return jsonify({'success': True})

@auth_bp.route('/api/auth/check', methods=['GET'])
def check_auth():
    """Check if user is authenticated"""
    session_id = session.get('session_id')
    user = race_ui.verify_session(session_id)
    
    if user:
        return jsonify({
            'authenticated': True,
            'user': user
        })
    
    return jsonify({'authenticated': False})


# --- Phase 1 auth helpers ---------------------------------------------------

_GENERIC_REGISTRATION_FAIL = ('registration_failed',
                              'Registration failed. Check your inputs and try again.')


class _RegisterStop(Exception):
    """Sentinel raised inside register() to break out of the DB-connection block
    after we've explicitly rolled back. Doing it this way (instead of a plain
    `return`) ensures the sqlite3 connection's __exit__ doesn't auto-commit the
    pending transaction, and we can safely call race_ui._audit() with no write-lock held."""


def _validate_register_payload(data: dict) -> tuple[bool, str]:
    username = (data.get('username') or '').strip()
    email = (data.get('email') or '').strip().lower()
    password = data.get('password') or ''
    accept_terms = bool(data.get('accept_terms'))
    if not USERNAME_RE.match(username):
        return False, 'invalid_username'
    if username.lower() in RESERVED_USERNAMES:
        return False, 'reserved_username'
    if not EMAIL_RE.match(email):
        return False, 'invalid_email'
    if len(password) < 12:
        return False, 'weak_password'
    # Require at least one character from each class (upper, lower, digit, special).
    # This catches the weakest passwords without forcing users into patterns
    # they'll just pad with "!" at the end.
    if not (re.search(r'[A-Z]', password) and re.search(r'[a-z]', password)
            and re.search(r'[0-9]', password) and re.search(r'[^A-Za-z0-9]', password)):
        return False, 'weak_password'
    if not accept_terms:
        return False, 'terms_not_accepted'
    return True, ''


def _consume_invite_code(conn, code: str) -> bool:
    """Atomic invite-code use. Returns True iff a usable code was found and incremented."""
    if not code:
        return False
    row = conn.execute(
        'SELECT id, max_uses, uses, expires_at FROM invite_codes WHERE code = ?',
        (code,),
    ).fetchone()
    if not row:
        return False
    invite_id, max_uses, uses, expires_at = row['id'], row['max_uses'], row['uses'], row['expires_at']
    if expires_at and expires_at < datetime.now().isoformat():
        return False
    if uses >= max_uses:
        return False
    # Conditional update prevents two concurrent registers from each consuming
    # the last slot.
    cur = conn.execute(
        'UPDATE invite_codes SET uses = uses + 1 WHERE id = ? AND uses < max_uses',
        (invite_id,),
    )
    return cur.rowcount == 1


# --- CSRF token endpoint ----------------------------------------------------

@auth_bp.route('/api/auth/csrf', methods=['GET'])
def csrf_token():
    """Issue (and persist in Flask session) a CSRF token the frontend echoes back."""
    token = session.get('csrf_token')
    if not token:
        token = secrets.token_urlsafe(32)
        session['csrf_token'] = token
    return jsonify({'csrfToken': token})


# --- Registration / verification -------------------------------------------

@auth_bp.route('/api/auth/register', methods=['POST'])
@require_turnstile()
def register():
    data = request.get_json(silent=True) or {}
    ip_address = request.remote_addr or '-'
    if race_ui._rate_limit_hit('register_ip', ip_address):
        return jsonify({'error': 'rate_limited'}), 429

    ok, reason = _validate_register_payload(data)
    if not ok:
        if reason in ('invalid_username', 'reserved_username'):
            return jsonify({'error': 'invalid_username'}), 400
        if reason == 'invalid_email':
            return jsonify({'error': 'invalid_email'}), 400
        if reason == 'weak_password':
            return jsonify({'error': 'weak_password'}), 400
        if reason == 'terms_not_accepted':
            return jsonify({'error': 'terms_not_accepted'}), 400
        return jsonify({'error': _GENERIC_REGISTRATION_FAIL[0]}), 400

    username = data['username'].strip()
    email = data['email'].strip().lower()
    password = data['password']
    invite_code = (data.get('invite_code') or '').strip()

    new_user_id = None
    token = None
    invite_rejected = False
    conflict = False
    try:
        with race_ui.get_db_connection() as conn:
            # Invite gate unless globally open
            if not REGISTRATION_OPEN:
                if not _consume_invite_code(conn, invite_code):
                    conn.rollback()  # release locks before we audit/return
                    invite_rejected = True
                    raise _RegisterStop()

            token = secrets.token_urlsafe(32)
            expires = (datetime.now() + timedelta(hours=VERIFICATION_TOKEN_HOURS)).isoformat()
            try:
                cur = conn.execute(
                    'INSERT INTO users (username, password_hash, email, role, is_active, '
                    'email_verified, verification_token, verification_token_expires, tos_accepted_at) '
                    'VALUES (?, ?, ?, ?, 1, 0, ?, ?, ?)',
                    (username, race_ui.hash_password(password), email, 'user',
                     token, expires, datetime.now().isoformat()),
                )
                new_user_id = cur.lastrowid
            except sqlite3.IntegrityError:
                # Username or email collision — generic response (no enumeration).
                # Rolling back also un-consumes the invite code so attackers can't
                # burn invites by spamming colliding emails.
                conn.rollback()
                conflict = True
                raise _RegisterStop()

            conn.commit()
    except _RegisterStop:
        pass

    # Outside the connection block, locks released — safe to audit + respond.
    if invite_rejected:
        race_ui._audit('register_invite_rejected', target=email,
               details={'invite': bool(invite_code)})
        return jsonify({'error': _GENERIC_REGISTRATION_FAIL[0]}), 400
    if conflict:
        race_ui._audit('register_conflict', target=email)
        return jsonify({'error': _GENERIC_REGISTRATION_FAIL[0]}), 400

    try:
        ok, err = send_verification_email(
            race_ui._email_sender,
            {'username': username, 'email': email},
            token,
        )
        if not ok:
            race_ui._audit('email_send_failed', actor_user_id=new_user_id, target=email,
                   details={'template': 'verification', 'error': err})

        race_ui._audit('user_register', actor_user_id=new_user_id, target=email)
        return jsonify({
            'success': True,
            'message': 'Check your inbox to verify your email.',
        })

    except sqlite3.Error as exc:
        return race_ui._internal_error(exc, 'register')


@auth_bp.route('/api/auth/verify-email', methods=['POST'])
def verify_email():
    data = request.get_json(silent=True) or {}
    ip_address = request.remote_addr or '-'
    if race_ui._rate_limit_hit('verify_email_ip', ip_address):
        return jsonify({'error': 'rate_limited'}), 429
    token = (data.get('token') or '').strip()
    if not token:
        return jsonify({'error': 'invalid_token'}), 400
    try:
        with race_ui.get_db_connection() as conn:
            row = conn.execute(
                'SELECT id, username, email, email_verified, verification_token_expires '
                'FROM users WHERE verification_token = ? AND deleted_at IS NULL',
                (token,),
            ).fetchone()
            if not row:
                return jsonify({'error': 'invalid_token'}), 400
            if row['verification_token_expires'] and row['verification_token_expires'] < datetime.now().isoformat():
                return jsonify({'error': 'expired_token'}), 400
            conn.execute(
                'UPDATE users SET email_verified = 1, verification_token = NULL, '
                'verification_token_expires = NULL WHERE id = ?',
                (row['id'],),
            )
            conn.commit()
        race_ui._audit('email_verified', actor_user_id=row['id'], target=row['email'])
        send_welcome_email(race_ui._email_sender, {'username': row['username'], 'email': row['email']})
        return jsonify({'success': True})
    except sqlite3.Error as exc:
        return race_ui._internal_error(exc, 'verify-email')


@auth_bp.route('/api/auth/resend-verification', methods=['POST'])
@require_turnstile()
def resend_verification():
    data = request.get_json(silent=True) or {}
    email = (data.get('email') or '').strip().lower()
    ip_address = request.remote_addr or '-'
    if race_ui._rate_limit_hit('resend_verification_ip', ip_address):
        return jsonify({'success': True})  # silent rate-limit
    if email and race_ui._rate_limit_hit('resend_verification_email', email):
        return jsonify({'success': True})
    if not email or not EMAIL_RE.match(email):
        return jsonify({'success': True})
    try:
        with race_ui.get_db_connection() as conn:
            row = conn.execute(
                'SELECT id, username, email, email_verified FROM users '
                'WHERE LOWER(email) = ? AND deleted_at IS NULL',
                (email,),
            ).fetchone()
            if row and not row['email_verified']:
                token = secrets.token_urlsafe(32)
                expires = (datetime.now() + timedelta(hours=VERIFICATION_TOKEN_HOURS)).isoformat()
                conn.execute(
                    'UPDATE users SET verification_token = ?, verification_token_expires = ? '
                    'WHERE id = ?',
                    (token, expires, row['id']),
                )
                conn.commit()
                send_verification_email(
                    race_ui._email_sender,
                    {'username': row['username'], 'email': row['email']},
                    token,
                )
                race_ui._audit('verification_resent', actor_user_id=row['id'], target=row['email'])
        return jsonify({'success': True})
    except sqlite3.Error:
        return jsonify({'success': True})  # never leak DB errors here


# --- Password reset --------------------------------------------------------

@auth_bp.route('/api/auth/forgot-password', methods=['POST'])
@require_turnstile()
def forgot_password():
    data = request.get_json(silent=True) or {}
    email = (data.get('email') or '').strip().lower()
    ip_address = request.remote_addr or '-'
    if race_ui._rate_limit_hit('forgot_password_ip', ip_address):
        return jsonify({'success': True})
    if email and race_ui._rate_limit_hit('forgot_password_email', email):
        return jsonify({'success': True})
    if not email or not EMAIL_RE.match(email):
        return jsonify({'success': True})
    try:
        with race_ui.get_db_connection() as conn:
            row = conn.execute(
                'SELECT id, username, email FROM users '
                'WHERE LOWER(email) = ? AND is_active = 1 AND deleted_at IS NULL',
                (email,),
            ).fetchone()
            if row:
                token = secrets.token_urlsafe(32)
                expires = (datetime.now() + timedelta(hours=RESET_TOKEN_HOURS)).isoformat()
                conn.execute(
                    'UPDATE users SET password_reset_token = ?, password_reset_expires = ? '
                    'WHERE id = ?',
                    (token, expires, row['id']),
                )
                conn.commit()
                send_password_reset_email(
                    race_ui._email_sender,
                    {'username': row['username'], 'email': row['email']},
                    token,
                )
                race_ui._audit('password_reset_requested', actor_user_id=row['id'], target=row['email'])
        return jsonify({'success': True})
    except sqlite3.Error:
        return jsonify({'success': True})


@auth_bp.route('/api/auth/reset-password', methods=['POST'])
def reset_password():
    data = request.get_json(silent=True) or {}
    token = (data.get('token') or '').strip()
    new_password = data.get('new_password') or ''
    if not token:
        return jsonify({'error': 'invalid_token'}), 400
    if len(new_password) < 12:
        return jsonify({'error': 'weak_password'}), 400
    # Same complexity check as registration.
    if not (re.search(r'[A-Z]', new_password) and re.search(r'[a-z]', new_password)
            and re.search(r'[0-9]', new_password) and re.search(r'[^A-Za-z0-9]', new_password)):
        return jsonify({'error': 'weak_password'}), 400
    # Rate-limit per email (defence-in-depth against token guessing).
    ip = request.remote_addr or '-'
    if _rate_limit_hit('reset_password_ip', ip):
        return jsonify({'error': 'rate_limited'}), 429
    try:
        with race_ui.get_db_connection() as conn:
            row = conn.execute(
                'SELECT id, email, password_reset_expires FROM users '
                'WHERE password_reset_token = ? AND deleted_at IS NULL',
                (token,),
            ).fetchone()
            if not row:
                return jsonify({'error': 'invalid_token'}), 400
            if row['password_reset_expires'] and row['password_reset_expires'] < datetime.now().isoformat():
                return jsonify({'error': 'expired_token'}), 400
            conn.execute(
                'UPDATE users SET password_hash = ?, password_reset_token = NULL, '
                'password_reset_expires = NULL WHERE id = ?',
                (race_ui.hash_password(new_password), row['id']),
            )
            # Invalidate all live sessions for this user.
            conn.execute('DELETE FROM sessions WHERE user_id = ?', (row['id'],))
            conn.commit()
        race_ui._audit('password_reset_completed', actor_user_id=row['id'], target=row['email'])
        return jsonify({'success': True})
    except sqlite3.Error as exc:
        return race_ui._internal_error(exc, 'reset-password')


# --- Self-service /me endpoints --------------------------------------------

@auth_bp.route('/api/auth/me', methods=['GET'])
@login_required
def me_get():
    user = request.current_user
    with race_ui.get_db_connection() as conn:
        row = conn.execute(
            'SELECT id, username, email, role, created_at, last_login, '
            'email_verified, tos_accepted_at, is_active '
            'FROM users WHERE id = ?',
            (user['id'],),
        ).fetchone()
    if not row:
        return jsonify({'error': 'not_found'}), 404
    return jsonify({'user': dict(row)})


@auth_bp.route('/api/auth/me/export', methods=['POST'])
@login_required
def me_export():
    user = request.current_user
    with race_ui.get_db_connection() as conn:
        prof = conn.execute(
            'SELECT id, username, email, role, created_at, last_login, '
            'email_verified, tos_accepted_at, is_active '
            'FROM users WHERE id = ?',
            (user['id'],),
        ).fetchone()
        audit_rows = conn.execute(
            'SELECT action, target, ip_address, timestamp, details FROM audit_log '
            'WHERE actor_user_id = ? ORDER BY timestamp DESC LIMIT 1000',
            (user['id'],),
        ).fetchall()
    race_ui._audit('self_export', actor_user_id=user['id'])
    return jsonify({
        'profile': dict(prof) if prof else None,
        'audit_log': [dict(r) for r in audit_rows],
        'planner': {},
        'exported_at': datetime.now().isoformat(),
    })


@auth_bp.route('/api/auth/me', methods=['DELETE'])
@login_required
def me_delete():
    user = request.current_user
    scramble_suffix = secrets.token_urlsafe(6)
    with race_ui.get_db_connection() as conn:
        conn.execute(
            'UPDATE users SET deleted_at = CURRENT_TIMESTAMP, is_active = 0, '
            'username = ?, email = ?, verification_token = NULL, password_reset_token = NULL '
            'WHERE id = ?',
            (f'deleted_{user["id"]}_{scramble_suffix}',
             f'deleted+{user["id"]}@invalid',
             user['id']),
        )
        conn.execute('DELETE FROM sessions WHERE user_id = ?', (user['id'],))
        conn.commit()
    race_ui._audit('account_deleted', actor_user_id=user['id'])
    session.clear()
    return jsonify({'success': True})
