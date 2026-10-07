"""Device-facing API for constrained clients (the ESP32 datalogger).

Routes (cookie session + CSRF, from the web UI):
  POST /api/device/tokens
  GET  /api/device/tokens
  POST /api/device/tokens/<id>/revoke
  POST /api/device/pairing-codes          mint an 8-char pairing code
  GET  /api/device/pairing-codes/<id>     pending / paired / expired

Route (anonymous, one call per board, per-IP throttle):
  POST /api/device/pair                   {code} -> the long-lived token

Routes (`Authorization: Bearer <token>`, no cookie, no CSRF):
  GET  /api/device/tracks
  GET  /api/device/live        one flat row, ETag / 304
  GET  /api/device/stream      Server-Sent Events: `team`, `alert`, heartbeat
  POST /api/device/pit-alert

Scope of a device token: read live timing for the owner's account and raise
pit alerts. Nothing else — history, fleet and admin routes never accept one.

Transport rules (a microcontroller over cellular): flat JSON, JSON on every
error, `no-transform` so the edge never compresses, no redirects
(`strict_slashes=False`), zone-suffixed timestamps.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
import threading
import time
from datetime import datetime, timedelta, timezone
from functools import wraps

from flask import Blueprint, Response, jsonify, request

import multi_track_manager
import race_ui
from race_app.device_hub import (
    HEARTBEAT_SECONDS,
    SSE_HEARTBEAT,
    SSE_RETRY,
    TOKEN_LIFETIME_DAYS,
    generate_token,
    hash_token,
    hub,
    sse_event,
    utc_now_iso,
)
from race_app.blueprints.pit_alert_routes import (
    MAX_ALERT_MESSAGE,
    dispatch_pit_alert,
)
from race_ui import _internal_error, _rate_limit_hit, get_db_connection, login_required


device_bp = Blueprint('device', __name__)

# Wake SSE streams whenever a parser commits an update.
multi_track_manager.add_update_listener(hub.notify_track)

MAX_LABEL = 64
MAX_TEAM_QUERY = 128
TOKEN_CACHE_TTL = 60           # seconds a verified token stays cached
LAST_SEEN_WRITE_INTERVAL = 60  # throttle last_seen_at writes per token
# About one request every 2 s per token: two hits per 4 s window, the third
# is refused. A stray retry does not trip it; a tight loop does.
LIVE_RATE = (3, 4)
PIT_ALERT_RATE = (11, 60)      # ten alerts a minute per token
RETRY_AFTER_SECONDS = '2'

# Pairing codes: 8 symbols from an alphabet without 0/O/1/I, shown as
# ABCD-EFGH. 40 bits is plenty for something that lives 10 minutes, is used
# once, and sits behind a per-IP throttle.
PAIR_ALPHABET = 'ABCDEFGHJKLMNPQRSTUVWXYZ23456789'
PAIR_CODE_LEN = 8
PAIR_CODE_TTL_SECONDS = 600
PAIR_RATE = (11, 60)           # ten attempts a minute per IP

_token_cache: dict = {}        # token_hash -> (info, cached_at)
_token_cache_lock = threading.Lock()
_last_seen_written: dict = {}  # token_id -> monotonic


def _utc_iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _token_cache_invalidate() -> None:
    with _token_cache_lock:
        _token_cache.clear()


def _lookup_token(raw: str):
    """Verified token info or None. Cached briefly; a revoke clears the cache
    so the next request from that board is refused."""
    if not raw or len(raw) > 256:
        return None
    th = hash_token(raw)
    now = time.time()
    with _token_cache_lock:
        entry = _token_cache.get(th)
        if entry and now - entry[1] < TOKEN_CACHE_TTL:
            info = entry[0]
            if info['expires_at'] > _utc_iso(_now_utc()):
                return dict(info)
            _token_cache.pop(th, None)
            return None

    with get_db_connection() as conn:
        row = conn.execute(
            '''SELECT t.id, t.label, t.user_id, t.expires_at, t.revoked_at,
                      u.username, u.role, u.email, u.is_active
               FROM device_tokens t JOIN users u ON u.id = t.user_id
               WHERE t.token_hash = ?''',
            (th,),
        ).fetchone()
    if not row or row['revoked_at'] or not row['is_active']:
        return None
    if row['expires_at'] <= _utc_iso(_now_utc()):
        return None
    info = {
        'id': int(row['id']),
        'label': row['label'],
        'expires_at': row['expires_at'],
        'user': {'id': int(row['user_id']), 'username': row['username'],
                 'role': row['role'], 'email': row['email']},
    }
    with _token_cache_lock:
        if len(_token_cache) > 5000:
            _token_cache.clear()
        _token_cache[th] = (info, now)
    return dict(info)


def _touch_last_seen(token_id: int) -> None:
    now = time.monotonic()
    last = _last_seen_written.get(token_id)
    if last is not None and now - last < LAST_SEEN_WRITE_INTERVAL:
        return
    _last_seen_written[token_id] = now
    try:
        with get_db_connection() as conn:
            conn.execute('UPDATE device_tokens SET last_seen_at = ? WHERE id = ?',
                         (utc_now_iso(), token_id))
    except Exception as exc:  # pragma: no cover — best effort
        print(f'[device] last_seen update failed: {exc}')


def _invalid_token():
    resp = jsonify({'error': 'invalid_token'})
    resp.status_code = 401
    resp.headers['WWW-Authenticate'] = 'Bearer'
    return resp


def _rate_limited(retry_after: str = RETRY_AFTER_SECONDS):
    resp = jsonify({'error': 'rate_limited'})
    resp.status_code = 429
    resp.headers['Retry-After'] = retry_after
    return resp


def device_token_required(f):
    """Authenticate with `Authorization: Bearer <token>` only — never the
    cookie session, so a browser tab can never reach these by accident."""
    @wraps(f)
    def decorated(*args, **kwargs):
        auth = request.headers.get('Authorization', '')
        if not auth.startswith('Bearer '):
            return _invalid_token()
        info = _lookup_token(auth[7:].strip())
        if not info:
            return _invalid_token()
        request.current_user = info['user']
        request.device = {'id': info['id'], 'label': info['label']}
        _touch_last_seen(info['id'])
        return f(*args, **kwargs)
    return decorated


# --- Token management (web UI, cookie + CSRF) ---------------------------------

def _token_row_json(row, online: set) -> dict:
    return {
        'id': int(row['id']),
        'label': row['label'],
        'created_at': row['created_at'],
        'expires_at': row['expires_at'],
        'last_seen_at': row['last_seen_at'],
        'revoked': row['revoked_at'] is not None,
        'revoked_at': row['revoked_at'],
        'online': int(row['id']) in online,
    }


@device_bp.route('/api/device/tokens', methods=['POST'], strict_slashes=False)
@login_required
def create_device_token():
    data = request.get_json(silent=True) or {}
    label = str(data.get('label') or '').strip()
    if not _valid_label(label):
        return jsonify({'error': 'invalid_label'}), 400
    user = request.current_user
    try:
        minted = _mint_token(user['id'], label, conn=None)
        race_ui._audit('device_token.create', actor_user_id=user['id'],
                       target=str(minted['id']), details={'label': label})
        return jsonify(minted), 201
    except Exception as exc:
        return _internal_error(exc, context='create_device_token')


def _mint_token(user_id: int, label: str, conn=None) -> dict:
    """Insert a device token and return the one-time plaintext payload.
    Uses `conn` when given (so pairing can mint inside its own transaction)."""
    raw = generate_token()
    now = _now_utc()
    expires = now + timedelta(days=TOKEN_LIFETIME_DAYS)
    sql = ('''INSERT INTO device_tokens (user_id, label, token_hash, created_at, expires_at)
              VALUES (?, ?, ?, ?, ?)''',
           (user_id, label, hash_token(raw), _utc_iso(now), _utc_iso(expires)))
    if conn is None:
        with get_db_connection() as c:
            token_id = c.execute(*sql).lastrowid
    else:
        token_id = conn.execute(*sql).lastrowid
    return {
        'id': int(token_id),
        'label': label,
        'token': raw,
        'created_at': _utc_iso(now),
        'expires_at': _utc_iso(expires),
    }


# --- Pairing codes ---------------------------------------------------------------

def _valid_label(label) -> bool:
    return bool(label) and len(label) <= MAX_LABEL and label.isprintable()


def generate_pairing_code() -> str:
    return ''.join(secrets.choice(PAIR_ALPHABET) for _ in range(PAIR_CODE_LEN))


def format_pairing_code(code: str) -> str:
    return f'{code[:4]}-{code[4:]}'


def normalise_pairing_code(raw) -> str:
    """Upper-case, drop separators and spaces; what a person types on a board."""
    if not isinstance(raw, str):
        return ''
    return ''.join(ch for ch in raw.upper() if ch.isalnum())


def hash_pairing_code(code: str) -> str:
    """HMAC with the app secret: a leaked auth.db alone cannot redeem codes."""
    key = race_ui.app.secret_key
    if isinstance(key, str):
        key = key.encode('utf-8')
    return hmac.new(key or b'', code.encode('utf-8'), hashlib.sha256).hexdigest()


def _pairing_status(row) -> str:
    if row['used_at']:
        return 'paired'
    if row['expires_at'] <= utc_now_iso():
        return 'expired'
    return 'pending'


@device_bp.route('/api/device/pairing-codes', methods=['POST'], strict_slashes=False)
@login_required
def create_pairing_code():
    data = request.get_json(silent=True) or {}
    label = str(data.get('label') or '').strip()
    if not _valid_label(label):
        return jsonify({'error': 'invalid_label'}), 400
    user = request.current_user
    try:
        code = generate_pairing_code()
        now = _now_utc()
        expires = now + timedelta(seconds=PAIR_CODE_TTL_SECONDS)
        with get_db_connection() as conn:
            # Housekeeping: codes are worthless a day after expiry.
            conn.execute('DELETE FROM device_pairing_codes WHERE expires_at < ?',
                         (_utc_iso(now - timedelta(days=1)),))
            cur = conn.execute(
                '''INSERT INTO device_pairing_codes (user_id, label, code_hash, created_at, expires_at)
                   VALUES (?, ?, ?, ?, ?)''',
                (user['id'], label, hash_pairing_code(code), _utc_iso(now), _utc_iso(expires)),
            )
            code_id = cur.lastrowid
        race_ui._audit('device_pairing.create', actor_user_id=user['id'],
                       target=str(code_id), details={'label': label})
        return jsonify({
            'id': int(code_id),
            'label': label,
            'code': format_pairing_code(code),
            'expires_at': _utc_iso(expires),
            'expires_in': PAIR_CODE_TTL_SECONDS,
            'status': 'pending',
        }), 201
    except Exception as exc:
        return _internal_error(exc, context='create_pairing_code')


@device_bp.route('/api/device/pairing-codes/<int:code_id>', methods=['GET'], strict_slashes=False)
@login_required
def pairing_code_status(code_id: int):
    user = request.current_user
    try:
        with get_db_connection() as conn:
            row = conn.execute(
                '''SELECT id, label, expires_at, used_at, token_id
                   FROM device_pairing_codes WHERE id = ? AND user_id = ?''',
                (code_id, user['id']),
            ).fetchone()
        if not row:
            return jsonify({'error': 'not_found'}), 404
        return jsonify({
            'id': int(row['id']),
            'label': row['label'],
            'status': _pairing_status(row),
            'expires_at': row['expires_at'],
            'token_id': row['token_id'],
        })
    except Exception as exc:
        return _internal_error(exc, context='pairing_code_status')


@device_bp.route('/api/device/pair', methods=['POST'], strict_slashes=False)
def pair_device():
    """Anonymous: the board trades its pairing code for the long-lived token.
    Single use — the row is claimed atomically, so two boards racing on the
    same code cannot both win."""
    ip = request.remote_addr or '-'
    if _rate_limit_hit('device_pair_ip', ip, *PAIR_RATE):
        return _rate_limited('6')
    data = request.get_json(silent=True) or {}
    code = normalise_pairing_code(data.get('code'))
    if len(code) != PAIR_CODE_LEN:
        return jsonify({'error': 'invalid_code'}), 400
    try:
        now_iso = utc_now_iso()
        with get_db_connection() as conn:
            conn.execute('BEGIN IMMEDIATE')
            row = conn.execute(
                '''SELECT id, user_id, label FROM device_pairing_codes
                   WHERE code_hash = ? AND used_at IS NULL AND expires_at > ?''',
                (hash_pairing_code(code), now_iso),
            ).fetchone()
            if not row:
                conn.execute('ROLLBACK')
                return jsonify({'error': 'invalid_code'}), 400
            minted = _mint_token(int(row['user_id']), row['label'], conn=conn)
            conn.execute(
                'UPDATE device_pairing_codes SET used_at = ?, token_id = ? WHERE id = ?',
                (now_iso, minted['id'], row['id']),
            )
            conn.execute('COMMIT')
        race_ui._audit('device_token.pair', actor_user_id=int(row['user_id']),
                       target=str(minted['id']), details={'label': row['label'], 'code_id': row['id']})
        return jsonify(minted)
    except Exception as exc:
        return _internal_error(exc, context='pair_device')


@device_bp.route('/api/device/tokens', methods=['GET'], strict_slashes=False)
@login_required
def list_device_tokens():
    user = request.current_user
    try:
        with get_db_connection() as conn:
            rows = conn.execute(
                '''SELECT id, label, created_at, expires_at, last_seen_at, revoked_at
                   FROM device_tokens WHERE user_id = ? ORDER BY id DESC''',
                (user['id'],),
            ).fetchall()
        online = hub.online_devices(user['id'])
        return jsonify({'tokens': [_token_row_json(r, online) for r in rows]})
    except Exception as exc:
        return _internal_error(exc, context='list_device_tokens')


@device_bp.route('/api/device/tokens/<int:token_id>/revoke', methods=['POST'], strict_slashes=False)
@login_required
def revoke_device_token(token_id: int):
    user = request.current_user
    try:
        with get_db_connection() as conn:
            row = conn.execute(
                'SELECT id, revoked_at FROM device_tokens WHERE id = ? AND user_id = ?',
                (token_id, user['id']),
            ).fetchone()
            if not row:
                return jsonify({'error': 'not_found'}), 404
            if row['revoked_at'] is None:
                conn.execute('UPDATE device_tokens SET revoked_at = ? WHERE id = ?',
                             (utc_now_iso(), token_id))
        _token_cache_invalidate()
        race_ui._audit('device_token.revoke', actor_user_id=user['id'], target=str(token_id))
        return jsonify({'ok': True, 'id': token_id, 'revoked': True})
    except Exception as exc:
        return _internal_error(exc, context='revoke_device_token')


# --- Bearer routes -------------------------------------------------------------

def _parse_track_id():
    raw = request.args.get('track_id', '')
    try:
        tid = int(raw)
    except (TypeError, ValueError):
        return None
    return tid if tid > 0 else None


def _team_query():
    team = (request.args.get('team') or '').strip()
    if not team or len(team) > MAX_TEAM_QUERY:
        return None
    return team


def _live_teams(track_id: int):
    """(session_id, teams) from the live parser, or (None, None)."""
    session_id = race_ui._live_session_id(track_id)
    df = race_ui._live_standings_df(track_id)
    if not session_id or df is None or df.empty:
        return None, None
    return session_id, df.to_dict('records')


def _etag_matches(seq: int) -> bool:
    inm = request.headers.get('If-None-Match', '')
    for tag in inm.split(','):
        tag = tag.strip()
        if tag.startswith('W/'):
            tag = tag[2:]
        if tag.strip('"') == str(seq):
            return True
    return False


@device_bp.route('/api/device/tracks', methods=['GET'], strict_slashes=False)
@device_token_required
def device_tracks():
    try:
        parsers = getattr(race_ui.multi_track_manager, 'parsers', {}) or {}
        out = []
        for t in race_ui.track_db.get_all_tracks():
            if not t.get('is_active', 1):
                continue
            parser = parsers.get(t['id'])
            out.append({
                'id': int(t['id']),
                'name': t.get('track_name') or '',
                'active': bool(parser is not None and getattr(parser, 'session_active_status', None) is True),
            })
        return jsonify(out)
    except Exception as exc:
        return _internal_error(exc, context='device_tracks')


@device_bp.route('/api/device/live', methods=['GET'], strict_slashes=False)
@device_token_required
def device_live():
    if _rate_limit_hit('device_live', str(request.device['id']), *LIVE_RATE):
        return _rate_limited()
    track_id = _parse_track_id()
    if track_id is None:
        return jsonify({'error': 'invalid_track_id'}), 400
    team = _team_query()
    if team is None:
        return jsonify({'error': 'team_required'}), 400
    try:
        if not race_ui.track_db.get_track_by_id(track_id):
            return jsonify({'error': 'unknown_track'}), 404
        session_id, teams = _live_teams(track_id)
        if teams is None:
            return jsonify({'error': 'no_live_session'}), 404
        row = hub.build_row(request.current_user['id'], track_id, session_id, teams, team)
        if row is None:
            return jsonify({'error': 'unknown_team'}), 404
        etag = f'"{row["seq"]}"'
        if _etag_matches(row['seq']):
            resp = Response(status=304)
            resp.headers['ETag'] = etag
            return resp
        resp = jsonify(row)
        resp.headers['ETag'] = etag
        return resp
    except Exception as exc:
        return _internal_error(exc, context='device_live')


@device_bp.route('/api/device/stream', methods=['GET'], strict_slashes=False)
@device_token_required
def device_stream():
    track_id = _parse_track_id()
    if track_id is None:
        return jsonify({'error': 'invalid_track_id'}), 400
    team = _team_query()
    if team is None:
        return jsonify({'error': 'team_required'}), 400
    if not race_ui.track_db.get_track_by_id(track_id):
        return jsonify({'error': 'unknown_track'}), 404

    user_id = request.current_user['id']
    device = request.device
    sub = hub.subscribe(device['id'], device['label'], user_id, track_id, team)
    if sub is None:
        return _rate_limited('10')

    def snapshot():
        """Current `event: team` frame, or a `status` frame while quiet."""
        session_id, teams = _live_teams(track_id)
        if teams is None:
            return None, sse_event('status', {'error': 'no_live_session', 'track_id': track_id,
                                              'updated_at': utc_now_iso()})
        row = hub.build_row(user_id, track_id, session_id, teams, team)
        if row is None:
            return None, sse_event('status', {'error': 'unknown_team', 'track_id': track_id,
                                              'team': team, 'updated_at': utc_now_iso()})
        sub.matched_team = row['matched_team']
        return row, sse_event('team', row, event_id=row['seq'])

    def generate():
        try:
            yield SSE_RETRY
            row, frame = snapshot()
            yield frame
            sub.last_seq = row['seq'] if row else None
            for alert in hub.take_pending_alerts(sub):
                yield sse_event('alert', alert, event_id=alert.get('event_id'))
            while not sub.closed:
                data, alerts = sub.wait(HEARTBEAT_SECONDS)
                sent = False
                for alert in alerts:
                    yield sse_event('alert', alert, event_id=alert.get('event_id'))
                    sent = True
                if data:
                    row, frame = snapshot()
                    seq = row['seq'] if row else None
                    if seq != sub.last_seq:
                        sub.last_seq = seq
                        yield frame
                        sent = True
                if not sent:
                    yield SSE_HEARTBEAT
        finally:
            hub.unsubscribe(sub)

    resp = Response(generate(), mimetype='text/event-stream')
    resp.headers['Cache-Control'] = 'no-cache, no-transform'
    resp.headers['X-Accel-Buffering'] = 'no'
    return resp


@device_bp.route('/api/device/pit-alert', methods=['POST'], strict_slashes=False)
@device_token_required
def device_pit_alert():
    if _rate_limit_hit('device_pit_alert', str(request.device['id']), *PIT_ALERT_RATE):
        return _rate_limited('6')
    data = request.get_json(silent=True) or {}
    track_id = data.get('track_id')
    team_name = data.get('team_name')
    alert_message = str(data.get('alert_message') or 'PIT NOW')[:MAX_ALERT_MESSAGE]
    try:
        track_id = int(track_id)
    except (TypeError, ValueError):
        return jsonify({'error': 'invalid_track_id'}), 400
    if not team_name or not isinstance(team_name, str) or len(team_name) > MAX_TEAM_QUERY:
        return jsonify({'error': 'team_required'}), 400
    try:
        if not race_ui.track_db.get_track_by_id(track_id):
            return jsonify({'error': 'unknown_track'}), 404
        result = dispatch_pit_alert(
            request.current_user, track_id, team_name, alert_message,
            origin='device', origin_label=request.device['label'],
            exclude_device_id=request.device['id'],
        )
        return jsonify({
            'ok': True,
            'delivered_to': result['delivered_to'],
            'devices_online': result['devices_online'],
            'timestamp': utc_now_iso(),
        })
    except Exception as exc:
        return _internal_error(exc, context='device_pit_alert')
