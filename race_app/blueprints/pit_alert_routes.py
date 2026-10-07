"""Pit-alert trigger endpoint.

Routes:
  POST /api/trigger-pit-alert

`dispatch_pit_alert` is the single fan-out used by this route (web / phone,
cookie session) and by `POST /api/device/pit-alert` (bearer token). Every
alert reaches:

- the triggering account's `user_{id}` Socket.IO room (phones + own tabs),
- the track room as `pit_alert_broadcast` (dashboard banner),
- the account's bearer-token boards whose SSE stream follows the track (and
  team) — narrowed by `target_device_ids` when the operator picked a board.
"""

from datetime import datetime

from flask import Blueprint, jsonify, request

from race_app.device_hub import hub, utc_now_iso
from race_ui import _internal_error, get_db_connection, login_required, socketio


pit_alert_bp = Blueprint('pit_alert', __name__)

ALERT_FLASH_COLOR = '#FF0000'
ALERT_DURATION_MS = 80000
MAX_ALERT_MESSAGE = 120


def active_device_ids(user_id: int) -> list:
    """Ids of the account's live (unrevoked, unexpired) device tokens."""
    now = utc_now_iso()
    with get_db_connection() as conn:
        rows = conn.execute(
            'SELECT id FROM device_tokens WHERE user_id = ? AND revoked_at IS NULL AND expires_at > ?',
            (user_id, now),
        ).fetchall()
    return [int(r[0]) for r in rows]


def parse_target_device_ids(payload: dict):
    """`target_device_ids` (alias `target_token_ids`): None when absent/null,
    else a list of ints. Raises ValueError on a malformed value."""
    raw = payload.get('target_device_ids', payload.get('target_token_ids'))
    if raw is None:
        return None
    if not isinstance(raw, list):
        raise ValueError('target_device_ids must be a list')
    out = []
    for v in raw:
        if isinstance(v, bool) or not isinstance(v, (int, str)):
            raise ValueError('target_device_ids must contain integers')
        out.append(int(v))
    return out


def dispatch_pit_alert(user: dict, track_id, team_name: str, alert_message: str, *,
                       origin: str = 'web', origin_label=None,
                       target_device_ids=None, exclude_device_id=None) -> dict:
    """Fan a pit alert out to phones, dashboard and boards. Returns the
    Socket.IO alert payload plus honest delivery counts."""
    user_id = user['id']
    user_room = f"user_{user_id}"
    track_room = f'track_{track_id}'

    alert_data = {
        'track_id': track_id,
        'team_name': team_name,
        'alert_type': 'pit_required',
        'alert_message': alert_message,
        # Existing Socket.IO consumers get the historical zone-less local
        # timestamp; the device copy below carries a UTC `Z` timestamp.
        'timestamp': datetime.now().isoformat(),
        'flash_color': ALERT_FLASH_COLOR,
        'duration_ms': ALERT_DURATION_MS,
        'priority': 'high',
        'triggered_by_user_id': user_id,
        'origin': origin,
        'origin_label': origin_label,
        'target_device_ids': target_device_ids,
    }

    socketio.emit('pit_alert', alert_data, room=user_room)
    socketio.emit('pit_alert_broadcast', {
        'track_id': track_id,
        'team_name': team_name,
        'alert_message': alert_message,
        'timestamp': datetime.now().isoformat(),
        'triggered_by_user_id': user_id,
        'origin': origin,
        'origin_label': origin_label,
    }, room=track_room)

    device_alert = dict(alert_data, timestamp=utc_now_iso())
    delivery = hub.deliver_alert(
        user_id, device_alert,
        track_id=track_id, team_name=team_name,
        target_device_ids=target_device_ids,
        known_device_ids=active_device_ids(user_id),
        exclude_device_id=exclude_device_id,
    )

    print(f"[PIT ALERT] by user_id={user_id} ({origin}{': ' + origin_label if origin_label else ''}) "
          f"for '{team_name}' on track {track_id}: '{alert_message}' -> "
          f"rooms {user_room}, {track_room}; boards {delivery['delivered_to']}/{delivery['devices_online']}")

    return {
        'alert': alert_data,
        'room': user_room,
        'delivered_to': delivery['delivered_to'],
        'devices_online': delivery['devices_online'],
    }


@pit_alert_bp.route('/api/trigger-pit-alert', methods=['POST'])
@login_required
def trigger_pit_alert():
    """Trigger a pit alert for a specific team on a track"""
    data = request.get_json(silent=True) or {}

    track_id = data.get('track_id')
    team_name = data.get('team_name')
    alert_message = (data.get('alert_message') or 'PIT NOW')[:MAX_ALERT_MESSAGE]

    if not track_id or not team_name:
        return jsonify({
            'status': 'error',
            'message': 'track_id and team_name are required'
        }), 400

    try:
        targets = parse_target_device_ids(data)
    except ValueError as exc:
        return jsonify({'status': 'error', 'message': str(exc)}), 400

    try:
        user = getattr(request, 'current_user', None)
        if not user:
            return jsonify({'status': 'error', 'message': 'auth required'}), 401

        if targets is not None:
            owned = set(active_device_ids(user['id']))
            targets = [t for t in targets if t in owned]
            if not targets:
                return jsonify({'status': 'error', 'message': 'unknown_device'}), 400

        result = dispatch_pit_alert(
            user, track_id, team_name, alert_message,
            origin='web', target_device_ids=targets,
        )

        return jsonify({
            'status': 'success',
            'ok': True,
            'message': f'Pit alert sent to your devices (user {user["id"]})',
            'room': result['room'],
            'alert': result['alert'],
            'delivered_to': result['delivered_to'],
            'devices_online': result['devices_online'],
        })

    except Exception as e:
        return _internal_error(e, context='trigger_pit_alert')
