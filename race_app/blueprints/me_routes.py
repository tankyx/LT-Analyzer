"""Per-user preferences endpoints (Phase 2).

Routes:
  GET    /api/me/prefs/<track_id>
  PUT    /api/me/prefs/<track_id>
  DELETE /api/me/prefs/<track_id>
  GET    /api/me/selected-track
  PUT    /api/me/selected-track
"""

import json

from flask import Blueprint, jsonify, request

from race_ui import (
    DEFAULT_LAP_TIME,
    PIT_STOP_TIME,
    REQUIRED_PIT_STOPS,
    _audit,
    get_db_connection,
    login_required,
    socketio,
)


me_bp = Blueprint('me', __name__)


_PREFS_DEFAULTS = {
    'my_team': None,
    'monitored_teams': [],
    'pit_stop_time': PIT_STOP_TIME,
    'required_pit_stops': REQUIRED_PIT_STOPS,
    'default_lap_time': DEFAULT_LAP_TIME,
    'stint_planner_config': {},
    'stint_planner_presets': [],
    'stint_assignments': [],
    'driver_names': [],
    'current_driver_index': 0,
}

# Fields the client may PUT; anything else is silently ignored.
_PREFS_PUTTABLE = set(_PREFS_DEFAULTS.keys())

# JSON-encoded columns (the rest are scalar).
_PREFS_JSON_COLS = {
    'monitored_teams', 'stint_planner_config', 'stint_planner_presets',
    'stint_assignments', 'driver_names',
}


def _prefs_row_to_json(row, track_id: int) -> dict:
    """Convert a sqlite Row (or None) to the public JSON shape, applying defaults."""
    out = {'track_id': track_id, **_PREFS_DEFAULTS, 'updated_at': None}
    if row is None:
        return out
    for k in _PREFS_DEFAULTS:
        val = row[k] if k in row.keys() else None
        if val is None:
            continue
        if k in _PREFS_JSON_COLS:
            try:
                out[k] = json.loads(val)
            except (TypeError, ValueError):
                out[k] = _PREFS_DEFAULTS[k]
        else:
            out[k] = val
    out['updated_at'] = row['updated_at'] if 'updated_at' in row.keys() else None
    return out


def _validate_prefs_patch(patch: dict) -> tuple[bool, str]:
    """Return (ok, error_code). Reject obviously-bad payloads early."""
    if not isinstance(patch, dict):
        return False, 'invalid_payload'
    if 'my_team' in patch and patch['my_team'] is not None and not isinstance(patch['my_team'], str):
        return False, 'invalid_my_team'
    if 'monitored_teams' in patch:
        v = patch['monitored_teams']
        if not isinstance(v, list) or not all(isinstance(x, (str, int)) for x in v):
            return False, 'invalid_monitored_teams'
        if len(v) > 100:
            return False, 'invalid_monitored_teams'
    if 'pit_stop_time' in patch:
        v = patch['pit_stop_time']
        if not isinstance(v, int) or not (0 < v <= 3600):
            return False, 'invalid_pit_stop_time'
    if 'required_pit_stops' in patch:
        v = patch['required_pit_stops']
        if not isinstance(v, int) or not (0 <= v <= 100):
            return False, 'invalid_required_pit_stops'
    if 'default_lap_time' in patch:
        v = patch['default_lap_time']
        if not isinstance(v, (int, float)) or not (0 < float(v) <= 3600):
            return False, 'invalid_default_lap_time'
    if 'stint_planner_config' in patch and not isinstance(patch['stint_planner_config'], dict):
        return False, 'invalid_stint_planner_config'
    if 'stint_planner_presets' in patch:
        v = patch['stint_planner_presets']
        if not isinstance(v, list) or len(v) > 50:
            return False, 'invalid_stint_planner_presets'
    if 'stint_assignments' in patch:
        v = patch['stint_assignments']
        if not isinstance(v, list) or len(v) > 200:
            return False, 'invalid_stint_assignments'
    if 'driver_names' in patch:
        v = patch['driver_names']
        if not isinstance(v, list) or not all(isinstance(x, str) for x in v):
            return False, 'invalid_driver_names'
        if len(v) > 20:
            return False, 'invalid_driver_names'
    if 'current_driver_index' in patch:
        v = patch['current_driver_index']
        if not isinstance(v, int) or v < 0 or v > 100:
            return False, 'invalid_current_driver_index'
    return True, ''


@me_bp.route('/api/me/prefs/<int:track_id>', methods=['GET'])
@login_required
def me_prefs_get(track_id):
    user = request.current_user
    with get_db_connection() as conn:
        row = conn.execute(
            'SELECT * FROM user_track_prefs WHERE user_id = ? AND track_id = ?',
            (user['id'], track_id),
        ).fetchone()
    return jsonify({'prefs': _prefs_row_to_json(row, track_id)})


@me_bp.route('/api/me/prefs/<int:track_id>', methods=['PUT'])
@login_required
def me_prefs_put(track_id):
    user = request.current_user
    patch_raw = request.get_json(silent=True)
    if patch_raw is None:
        return jsonify({'error': 'invalid_payload'}), 400
    # Strip anything not in the whitelist (silently ignore unknown fields).
    patch = {k: v for k, v in patch_raw.items() if k in _PREFS_PUTTABLE}
    ok, reason = _validate_prefs_patch(patch)
    if not ok:
        return jsonify({'error': reason}), 400

    # Convert JSON columns to strings for storage.
    storage = {}
    for k, v in patch.items():
        if k in _PREFS_JSON_COLS:
            storage[k] = json.dumps(v)
        else:
            storage[k] = v

    with get_db_connection() as conn:
        # UPSERT — sqlite's "ON CONFLICT" against the unique (user_id, track_id).
        # We always insert with the patch fields set to their patch values and
        # NULL for everything else; on conflict we only update the patch fields.
        cols = list(storage.keys())
        if cols:
            placeholders = ', '.join('?' for _ in cols)
            update_clause = ', '.join(f'{c} = excluded.{c}' for c in cols)
            sql = (
                f'INSERT INTO user_track_prefs (user_id, track_id, {", ".join(cols)}, updated_at) '
                f'VALUES (?, ?, {placeholders}, CURRENT_TIMESTAMP) '
                f'ON CONFLICT(user_id, track_id) DO UPDATE SET '
                f'{update_clause}, updated_at = CURRENT_TIMESTAMP'
            )
            params = [user['id'], track_id, *storage.values()]
        else:
            # Empty patch — just touch updated_at so the row exists.
            sql = (
                'INSERT INTO user_track_prefs (user_id, track_id, updated_at) '
                'VALUES (?, ?, CURRENT_TIMESTAMP) '
                'ON CONFLICT(user_id, track_id) DO UPDATE SET updated_at = CURRENT_TIMESTAMP'
            )
            params = [user['id'], track_id]
        conn.execute(sql, params)
        conn.commit()

        row = conn.execute(
            'SELECT * FROM user_track_prefs WHERE user_id = ? AND track_id = ?',
            (user['id'], track_id),
        ).fetchone()

    _audit('prefs_updated', actor_user_id=user['id'],
           target=f'track_{track_id}', details={'fields': sorted(patch.keys())})

    prefs_json = _prefs_row_to_json(row, track_id)
    # Phase 2.5: broadcast a "go re-fetch" ping to all other live tabs/devices
    # on the same account. Receivers compare updated_at to skip their own
    # echo (the value they themselves just wrote).
    try:
        socketio.emit('prefs_updated', {
            'user_id': user['id'],
            'track_id': track_id,
            'updated_at': prefs_json.get('updated_at'),
        }, room=f'user_prefs_{user["id"]}')
    except Exception as emit_err:  # pragma: no cover — defensive
        print(f'prefs_updated emit failed: {emit_err}')

    return jsonify({'prefs': prefs_json})


# --- Selected-track (per-user, cross-track) preference --------------------

@me_bp.route('/api/me/selected-track', methods=['GET'])
@login_required
def me_selected_track_get():
    user = request.current_user
    with get_db_connection() as conn:
        row = conn.execute(
            'SELECT selected_track_id FROM users WHERE id = ?', (user['id'],)
        ).fetchone()
    return jsonify({'track_id': row['selected_track_id'] if row else None})


@me_bp.route('/api/me/selected-track', methods=['PUT'])
@login_required
def me_selected_track_put():
    user = request.current_user
    data = request.get_json(silent=True) or {}
    raw = data.get('track_id')
    if raw is None:
        return jsonify({'error': 'track_id_required'}), 400
    try:
        track_id = int(raw)
    except (TypeError, ValueError):
        return jsonify({'error': 'invalid_track_id'}), 400
    if not (1 <= track_id <= 100000):
        return jsonify({'error': 'invalid_track_id'}), 400
    with get_db_connection() as conn:
        conn.execute(
            'UPDATE users SET selected_track_id = ? WHERE id = ?',
            (track_id, user['id']),
        )
        conn.commit()
    try:
        socketio.emit('selected_track_updated', {
            'user_id': user['id'],
            'track_id': track_id,
        }, room=f'user_prefs_{user["id"]}')
    except Exception as emit_err:  # pragma: no cover — defensive
        print(f'selected_track_updated emit failed: {emit_err}')
    return jsonify({'track_id': track_id})


@me_bp.route('/api/me/prefs/<int:track_id>', methods=['DELETE'])
@login_required
def me_prefs_delete(track_id):
    user = request.current_user
    with get_db_connection() as conn:
        conn.execute(
            'DELETE FROM user_track_prefs WHERE user_id = ? AND track_id = ?',
            (user['id'], track_id),
        )
        conn.commit()
    _audit('prefs_reset', actor_user_id=user['id'], target=f'track_{track_id}')
    return jsonify({'prefs': _prefs_row_to_json(None, track_id)})
