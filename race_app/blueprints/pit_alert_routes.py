"""Pit-alert trigger endpoint.

Routes:
  POST /api/trigger-pit-alert
"""

from datetime import datetime

from flask import Blueprint, jsonify, request

from race_ui import _internal_error, login_required, socketio


pit_alert_bp = Blueprint('pit_alert', __name__)


@pit_alert_bp.route('/api/trigger-pit-alert', methods=['POST'])
@login_required
def trigger_pit_alert():
    """Trigger a pit alert for a specific team on a track"""
    data = request.json

    track_id = data.get('track_id')
    team_name = data.get('team_name')
    alert_message = data.get('alert_message', 'PIT NOW')

    if not track_id or not team_name:
        return jsonify({
            'status': 'error',
            'message': 'track_id and team_name are required'
        }), 400

    try:
        # Per-user routing: the alert lands ONLY on devices belonging to the
        # user who triggered it (matched by session at Socket.IO connect time
        # — see handle_connect). Previously this fanned out to every device
        # in `team_track_{id}_{name}`, which meant a rival team monitoring
        # the same name would buzz too. Now you only buzz your own phones.
        user = getattr(request, 'current_user', None)
        if not user:
            return jsonify({'status': 'error', 'message': 'auth required'}), 401

        user_room = f"user_{user['id']}"
        alert_data = {
            'track_id': track_id,
            'team_name': team_name,
            'alert_type': 'pit_required',
            'alert_message': alert_message,
            'timestamp': datetime.now().isoformat(),
            'flash_color': '#FF0000',  # Red flash
            'duration_ms': 80000,      # Flash for 80 seconds
            'priority': 'high',
            # Forward the triggering user_id so a future multi-user device can
            # route between accounts if needed.
            'triggered_by_user_id': user['id'],
        }

        # Emit to the triggering user's personal room (Android + their own
        # browser tabs both receive it).
        socketio.emit('pit_alert', alert_data, room=user_room)

        # Also keep the per-track broadcast for the web dashboard's banner
        # alert (it's a UI hint shown on the standings panel, not a phone
        # notification — broader audience is fine here).
        track_room = f'track_{track_id}'
        socketio.emit('pit_alert_broadcast', {
            'track_id': track_id,
            'team_name': team_name,
            'alert_message': alert_message,
            'timestamp': datetime.now().isoformat(),
            'triggered_by_user_id': user['id'],
        }, room=track_room)

        print(f"[PIT ALERT] 🚨 by user_id={user['id']} for '{team_name}' on track {track_id}: '{alert_message}'")
        print(f"[PIT ALERT] ✅ emitted 'pit_alert' to {user_room}")
        print(f"[PIT ALERT] ✅ emitted 'pit_alert_broadcast' to {track_room}")

        return jsonify({
            'status': 'success',
            'message': f'Pit alert sent to your devices (user {user["id"]})',
            'room': user_room,
            'alert': alert_data,
        })

    except Exception as e:
        return _internal_error(e, context='trigger_pit_alert')
