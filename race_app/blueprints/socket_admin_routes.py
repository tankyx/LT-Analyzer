"""Admin endpoints for inspecting live Socket.IO state.

Routes:
  POST /api/admin/socketio/rooms
  POST /api/admin/socketio/room-info
"""

from datetime import datetime

from flask import Blueprint, jsonify, request

from race_ui import _internal_error, admin_required, socketio


socket_admin_bp = Blueprint('socket_admin', __name__)


@socket_admin_bp.route('/api/admin/socketio/rooms', methods=['POST'])
@admin_required
def admin_get_socketio_rooms():
    """Get all active Socket.IO rooms (admin only)"""
    try:
        if not hasattr(socketio, 'server') or not hasattr(socketio.server, 'rooms'):
            return jsonify({'error': 'Socket.IO server not available'}), 503

        # Get all rooms (this includes Socket.IO internal rooms)
        rooms = list(socketio.server.rooms.keys())

        # Filter out internal rooms (those that start with the client SID)
        non_internal_rooms = [room for room in rooms if not any(sid in room for sid in socketio.server.rooms.keys() if len(room) > 20)]

        # Return unique rooms
        unique_rooms = list(set(non_internal_rooms))
        unique_rooms.sort()

        return jsonify(unique_rooms)
    except Exception as e:
        return _internal_error(e, context='get_rooms')


@socket_admin_bp.route('/api/admin/socketio/room-info', methods=['POST'])
@admin_required
def admin_get_room_info():
    """Get information about a specific Socket.IO room (admin only)"""
    try:
        data = request.json
        room_name = data.get('room')

        if not room_name:
            return jsonify({'error': 'room parameter is required'}), 400

        if not hasattr(socketio, 'server') or not hasattr(socketio.server, 'rooms'):
            return jsonify({'error': 'Socket.IO server not available'}), 503

        # Get clients in the room
        clients = socketio.server.rooms.get(room_name, set())

        return jsonify({
            'room': room_name,
            'client_count': len(clients),
            'clients': list(clients),
            'timestamp': datetime.now().isoformat()
        })
    except Exception as e:
        return _internal_error(e, context='get_room_info')
