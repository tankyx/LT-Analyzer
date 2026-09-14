"""Live team-pace endpoint.

Position tells a crew very little during an endurance race: it moves with pit
strategy, lapped traffic and other teams' trouble. This exposes the measure
that does mean something — how the team is running against the field at the
same moment, stint by stint — and turns it into a keep-or-switch read on the
kart currently under them.
"""

from flask import Blueprint, jsonify, request

import race_ui
from race_ui import (
    UnknownTrackError,
    _internal_error,
    get_track_db_connection,
    login_required,
)


pace_bp = Blueprint('pace', __name__)

MAX_TEAM_NAME = 128


@pace_bp.route('/api/track/<int:track_id>/pace/team', methods=['GET'])
@login_required
def team_pace(track_id):
    """Pace report for one team in a session.

    Query: `team` (required), `session_id` (optional — defaults to the track's
    current session).
    """
    team = (request.args.get('team') or '').strip()
    if not team:
        return jsonify({'error': 'team_required'}), 400
    if len(team) > MAX_TEAM_NAME:
        return jsonify({'error': 'invalid_team'}), 400

    raw_session = request.args.get('session_id')
    session_id = None
    if raw_session not in (None, ''):
        try:
            session_id = int(raw_session)
        except (TypeError, ValueError):
            return jsonify({'error': 'invalid_session_id'}), 400

    try:
        if session_id is None:
            session_id = race_ui._live_session_id(track_id)
        if not session_id:
            return jsonify({'error': 'no_active_session'}), 404

        conn = get_track_db_connection(track_id)
        try:
            stint_data = race_ui._get_session_stint_data(track_id, session_id, conn)
            report = race_ui._compute_team_pace(
                conn, session_id, team,
                user_id=request.current_user['id'],
                stint_data=stint_data,
            )
        finally:
            conn.close()
        return jsonify(report)
    except UnknownTrackError:
        return jsonify({'error': 'unknown_track'}), 404
    except Exception as exc:  # pragma: no cover — defensive
        return _internal_error('team_pace', exc)
