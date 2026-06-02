"""Fleet tracker endpoints (per-user physical-kart registry + assignments)."""
import sqlite3
import time
from datetime import datetime

from flask import Blueprint, jsonify, request

import race_ui
from race_ui import (
    UnknownTrackError,
    _audit,
    _fleet_cache,
    _internal_error,
    get_track_db_connection,
    login_required,
)


fleet_bp = Blueprint('fleet', __name__)


@fleet_bp.route('/api/track/<int:track_id>/fleet/karts', methods=['GET'])
@login_required
def list_fleet_karts(track_id):
    """List the calling user's physical-kart registry for a track."""
    try:
        uid = request.current_user['id']
        active_only = request.args.get('active', '1') not in ('0', 'false', 'no')
        conn = get_track_db_connection(track_id)
        try:
            cur = conn.cursor()
            if active_only:
                cur.execute(
                    "SELECT id, label, notes, is_active FROM fleet_karts "
                    "WHERE user_id = ? AND is_active = 1 ORDER BY label", (uid,))
            else:
                cur.execute(
                    "SELECT id, label, notes, is_active FROM fleet_karts "
                    "WHERE user_id = ? ORDER BY label", (uid,))
            karts = [
                {'id': r[0], 'label': r[1], 'notes': r[2], 'is_active': bool(r[3])}
                for r in cur.fetchall()
            ]
        finally:
            conn.close()
        return jsonify({'track_id': track_id, 'karts': karts})
    except UnknownTrackError:
        raise
    except Exception as e:
        return _internal_error(e, 'list_fleet_karts')


@fleet_bp.route('/api/track/<int:track_id>/fleet/karts', methods=['POST'])
@login_required
def create_fleet_kart(track_id):
    """Register a physical kart in the calling user's fleet."""
    try:
        uid = request.current_user['id']
        data = request.get_json(silent=True) or {}
        label = (data.get('label') or '').strip()
        if not label:
            return jsonify({'error': 'label is required'}), 400
        notes = (data.get('notes') or '').strip() or None
        now = datetime.now().isoformat()
        conn = get_track_db_connection(track_id)
        try:
            cur = conn.cursor()
            try:
                cur.execute(
                    "INSERT INTO fleet_karts (user_id, label, notes, is_active, created_at) "
                    "VALUES (?, ?, ?, 1, ?)", (uid, label, notes, now))
            except sqlite3.IntegrityError:
                return jsonify({'error': 'You already have a kart with that label'}), 409
            conn.commit()
            kart_id = cur.lastrowid
        finally:
            conn.close()
        _audit('fleet_kart_create', actor_user_id=uid,
               target=f'track_{track_id}/kart_{kart_id}', details={'label': label})
        return jsonify({'kart': {'id': kart_id, 'label': label, 'notes': notes, 'is_active': True}}), 201
    except UnknownTrackError:
        raise
    except Exception as e:
        return _internal_error(e, 'create_fleet_kart')


@fleet_bp.route('/api/track/<int:track_id>/fleet/karts/<int:kart_id>', methods=['PUT'])
@login_required
def update_fleet_kart(track_id, kart_id):
    """Edit one of the calling user's karts (label/notes/active flag)."""
    try:
        uid = request.current_user['id']
        data = request.get_json(silent=True) or {}
        sets, params = [], []
        if 'label' in data:
            label = (data.get('label') or '').strip()
            if not label:
                return jsonify({'error': 'label cannot be empty'}), 400
            sets.append('label = ?')
            params.append(label)
        if 'notes' in data:
            sets.append('notes = ?')
            params.append((data.get('notes') or '').strip() or None)
        if 'is_active' in data:
            sets.append('is_active = ?')
            params.append(1 if data.get('is_active') else 0)
        if not sets:
            return jsonify({'error': 'no fields to update'}), 400
        sets.append('updated_at = ?')
        params.append(datetime.now().isoformat())
        params.extend([kart_id, uid])
        conn = get_track_db_connection(track_id)
        try:
            cur = conn.cursor()
            try:
                cur.execute(
                    f"UPDATE fleet_karts SET {', '.join(sets)} WHERE id = ? AND user_id = ?", params)
            except sqlite3.IntegrityError:
                return jsonify({'error': 'You already have a kart with that label'}), 409
            if cur.rowcount == 0:
                return jsonify({'error': 'kart not found'}), 404
            conn.commit()
        finally:
            conn.close()
        _audit('fleet_kart_update', actor_user_id=uid,
               target=f'track_{track_id}/kart_{kart_id}', details=data)
        return jsonify({'ok': True})
    except UnknownTrackError:
        raise
    except Exception as e:
        return _internal_error(e, 'update_fleet_kart')


@fleet_bp.route('/api/track/<int:track_id>/fleet/karts/<int:kart_id>', methods=['DELETE'])
@login_required
def delete_fleet_kart(track_id, kart_id):
    """Soft-retire one of the calling user's karts. History is preserved."""
    try:
        uid = request.current_user['id']
        conn = get_track_db_connection(track_id)
        try:
            cur = conn.cursor()
            cur.execute(
                "UPDATE fleet_karts SET is_active = 0, updated_at = ? WHERE id = ? AND user_id = ?",
                (datetime.now().isoformat(), kart_id, uid))
            if cur.rowcount == 0:
                return jsonify({'error': 'kart not found'}), 404
            conn.commit()
        finally:
            conn.close()
        _audit('fleet_kart_delete', actor_user_id=uid, target=f'track_{track_id}/kart_{kart_id}')
        return jsonify({'ok': True})
    except UnknownTrackError:
        raise
    except Exception as e:
        return _internal_error(e, 'delete_fleet_kart')


@fleet_bp.route('/api/track/<int:track_id>/fleet/state', methods=['GET'])
@login_required
def get_fleet_state(track_id):
    """The calling user's current fleet board for a session. Serves a fresh
    cached payload (per user) or recomputes, pulling live standings from the
    parser for location/holder info."""
    try:
        uid = request.current_user['id']
        session_id = request.args.get('session_id', type=int) or race_ui._live_session_id(track_id)
        if not session_id:
            get_track_db_connection(track_id).close()  # validate -> 404 on unknown
            return jsonify({
                'track_id': track_id, 'session_id': None, 'timestamp': datetime.now().isoformat(),
                'field_ref_seconds': None, 'fleet_median_residual': None,
                'karts': [], 'unassigned_teams': [],
            })
        cached = _fleet_cache.get((track_id, uid))
        if (cached and cached['session_id'] == session_id
                and time.time() - cached['computed_at'] < 3.0):
            return jsonify(cached['payload'])
        payload = race_ui.compute_fleet_payload(
            track_id, session_id, uid, standings_df=race_ui._live_standings_df(track_id))
        if payload is None:
            raise UnknownTrackError(f'Unknown track_id: {track_id}')
        return jsonify(payload)
    except UnknownTrackError:
        raise
    except Exception as e:
        return _internal_error(e, 'get_fleet_state')


@fleet_bp.route('/api/track/<int:track_id>/fleet/assignments', methods=['POST'])
@login_required
def record_fleet_assignment(track_id):
    """Record that a team is now on a given physical kart (per user)."""
    try:
        uid = request.current_user['id']
        data = request.get_json(silent=True) or {}
        session_id = data.get('session_id') or race_ui._live_session_id(track_id)
        team_name = (data.get('team_name') or '').strip()
        fleet_kart_id = data.get('fleet_kart_id')
        if not session_id or not team_name or not fleet_kart_id:
            return jsonify({'error': 'session_id, team_name and fleet_kart_id are required'}), 400
        source = data.get('source') if data.get('source') in ('manual', 'inferred') else 'manual'
        conn = get_track_db_connection(track_id)
        try:
            cur = conn.cursor()
            cur.execute(
                "SELECT 1 FROM fleet_karts WHERE id = ? AND user_id = ? AND is_active = 1",
                (fleet_kart_id, uid))
            if not cur.fetchone():
                return jsonify({'error': 'unknown or inactive fleet_kart_id'}), 400
            stint_index = data.get('stint_index')
            if stint_index is None:
                # Advance past the team's current stint so this kart becomes the
                # holder and the team's previous kart frees back to Available.
                cur.execute(
                    "SELECT MAX(stint_index) FROM fleet_assignments "
                    "WHERE session_id = ? AND user_id = ? AND team_name = ? AND superseded = 0",
                    (session_id, uid, team_name))
                row = cur.fetchone()
                team_max = row[0] if row and row[0] is not None else -1
                stint_index = max(race_ui._infer_stint_index(cur, session_id, team_name), team_max + 1)
            cur.execute(
                "SELECT kart_number FROM lap_times WHERE session_id = ? AND team_name = ? "
                "ORDER BY timestamp DESC LIMIT 1", (session_id, team_name))
            row = cur.fetchone()
            kart_number = row[0] if row else None
            cur.execute(
                """INSERT INTO fleet_assignments
                   (user_id, session_id, team_name, kart_number, fleet_kart_id, stint_index,
                    source, created_at, created_by, superseded)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 0)""",
                (uid, session_id, team_name, kart_number, fleet_kart_id, int(stint_index),
                 source, datetime.now().isoformat(), uid),
            )
            # The kart is now held by a team, so it leaves its Available lane.
            cur.execute("UPDATE fleet_karts SET lane = NULL WHERE id = ? AND user_id = ?",
                        (fleet_kart_id, uid))
            conn.commit()
            assignment_id = cur.lastrowid
        finally:
            conn.close()
        _fleet_cache.pop((track_id, uid), None)
        _audit('fleet_assignment', actor_user_id=uid,
               target=f'track_{track_id}/session_{session_id}/{team_name}',
               details={'fleet_kart_id': fleet_kart_id, 'stint_index': stint_index})
        return jsonify({'assignment': {
            'id': assignment_id, 'session_id': session_id, 'team_name': team_name,
            'fleet_kart_id': fleet_kart_id, 'stint_index': stint_index, 'source': source,
        }}), 201
    except UnknownTrackError:
        raise
    except Exception as e:
        return _internal_error(e, 'record_fleet_assignment')


@fleet_bp.route('/api/track/<int:track_id>/fleet/assignments/correct', methods=['POST'])
@login_required
def correct_fleet_assignment(track_id):
    """Correct one of the user's assignments: supersede the old row, insert a
    corrected one."""
    try:
        uid = request.current_user['id']
        data = request.get_json(silent=True) or {}
        assignment_id = data.get('assignment_id')
        fleet_kart_id = data.get('fleet_kart_id')
        if not assignment_id or not fleet_kart_id:
            return jsonify({'error': 'assignment_id and fleet_kart_id are required'}), 400
        conn = get_track_db_connection(track_id)
        try:
            cur = conn.cursor()
            cur.execute(
                "SELECT session_id, team_name, kart_number, stint_index FROM fleet_assignments "
                "WHERE id = ? AND user_id = ?", (assignment_id, uid))
            old = cur.fetchone()
            if not old:
                return jsonify({'error': 'assignment not found'}), 404
            session_id, team_name, kart_number, stint_index = old
            cur.execute(
                "SELECT 1 FROM fleet_karts WHERE id = ? AND user_id = ? AND is_active = 1",
                (fleet_kart_id, uid))
            if not cur.fetchone():
                return jsonify({'error': 'unknown or inactive fleet_kart_id'}), 400
            cur.execute("UPDATE fleet_assignments SET superseded = 1 WHERE id = ?", (assignment_id,))
            cur.execute(
                """INSERT INTO fleet_assignments
                   (user_id, session_id, team_name, kart_number, fleet_kart_id, stint_index,
                    source, created_at, created_by, superseded)
                   VALUES (?, ?, ?, ?, ?, ?, 'correction', ?, ?, 0)""",
                (uid, session_id, team_name, kart_number, fleet_kart_id, stint_index,
                 datetime.now().isoformat(), uid),
            )
            conn.commit()
            new_id = cur.lastrowid
        finally:
            conn.close()
        _fleet_cache.pop((track_id, uid), None)
        _audit('fleet_assignment_correct', actor_user_id=uid,
               target=f'track_{track_id}/session_{session_id}/{team_name}',
               details={'old_id': assignment_id, 'fleet_kart_id': fleet_kart_id})
        return jsonify({'assignment': {'id': new_id, 'fleet_kart_id': fleet_kart_id}}), 201
    except UnknownTrackError:
        raise
    except Exception as e:
        return _internal_error(e, 'correct_fleet_assignment')


@fleet_bp.route('/api/track/<int:track_id>/fleet/release', methods=['POST'])
@login_required
def release_fleet_kart(track_id):
    """Dissociate a kart from its team (it was dropped) and place it in an
    Available lane. Supersedes the kart's current assignment for this user."""
    try:
        uid = request.current_user['id']
        data = request.get_json(silent=True) or {}
        fleet_kart_id = data.get('fleet_kart_id')
        session_id = data.get('session_id') or race_ui._live_session_id(track_id)
        lane = data.get('lane')
        if not fleet_kart_id or not session_id:
            return jsonify({'error': 'fleet_kart_id and session_id are required'}), 400
        conn = get_track_db_connection(track_id)
        try:
            cur = conn.cursor()
            # End every live assignment of this kart for the user in the session.
            cur.execute(
                "UPDATE fleet_assignments SET superseded = 1 "
                "WHERE user_id = ? AND session_id = ? AND fleet_kart_id = ? AND superseded = 0",
                (uid, session_id, fleet_kart_id))
            cur.execute(
                "UPDATE fleet_karts SET lane = ? WHERE id = ? AND user_id = ?",
                (int(lane) if lane is not None else None, fleet_kart_id, uid))
            if cur.rowcount == 0:
                return jsonify({'error': 'kart not found'}), 404
            conn.commit()
        finally:
            conn.close()
        _fleet_cache.pop((track_id, uid), None)
        _audit('fleet_release', actor_user_id=uid,
               target=f'track_{track_id}/session_{session_id}/kart_{fleet_kart_id}',
               details={'lane': lane})
        return jsonify({'ok': True})
    except UnknownTrackError:
        raise
    except Exception as e:
        return _internal_error(e, 'release_fleet_kart')


@fleet_bp.route('/api/track/<int:track_id>/fleet/lane', methods=['POST'])
@login_required
def set_fleet_kart_lane(track_id):
    """Move an Available kart between lanes (sets fleet_karts.lane)."""
    try:
        uid = request.current_user['id']
        data = request.get_json(silent=True) or {}
        fleet_kart_id = data.get('fleet_kart_id')
        if not fleet_kart_id:
            return jsonify({'error': 'fleet_kart_id is required'}), 400
        lane = data.get('lane')
        conn = get_track_db_connection(track_id)
        try:
            cur = conn.cursor()
            cur.execute(
                "UPDATE fleet_karts SET lane = ? WHERE id = ? AND user_id = ?",
                (int(lane) if lane is not None else None, fleet_kart_id, uid))
            if cur.rowcount == 0:
                return jsonify({'error': 'kart not found'}), 404
            conn.commit()
        finally:
            conn.close()
        _fleet_cache.pop((track_id, uid), None)
        return jsonify({'ok': True})
    except UnknownTrackError:
        raise
    except Exception as e:
        return _internal_error(e, 'set_fleet_kart_lane')


@fleet_bp.route('/api/track/<int:track_id>/fleet/assignments', methods=['GET'])
@login_required
def list_fleet_assignments(track_id):
    """The calling user's assignment log for a session incl. superseded rows."""
    try:
        uid = request.current_user['id']
        session_id = request.args.get('session_id', type=int) or race_ui._live_session_id(track_id)
        conn = get_track_db_connection(track_id)
        try:
            if not session_id:
                return jsonify({'track_id': track_id, 'session_id': None, 'assignments': []})
            cur = conn.cursor()
            cur.execute(
                """SELECT id, team_name, kart_number, fleet_kart_id, stint_index,
                          source, created_at, created_by, superseded
                     FROM fleet_assignments WHERE session_id = ? AND user_id = ?
                    ORDER BY created_at ASC, id ASC""", (session_id, uid))
            assignments = [
                {'id': r[0], 'team_name': r[1], 'kart_number': r[2], 'fleet_kart_id': r[3],
                 'stint_index': r[4], 'source': r[5], 'created_at': r[6],
                 'created_by': r[7], 'superseded': bool(r[8])}
                for r in cur.fetchall()
            ]
        finally:
            conn.close()
        return jsonify({'track_id': track_id, 'session_id': session_id, 'assignments': assignments})
    except UnknownTrackError:
        raise
    except Exception as e:
        return _internal_error(e, 'list_fleet_assignments')


@fleet_bp.route('/api/track/<int:track_id>/fleet/auto-populate', methods=['POST'])
@login_required
def auto_populate_fleet(track_id):
    """Seed the calling user's fleet from the karts currently in a session.

    For each team in the session, ensure a physical kart exists in the user's
    fleet (labelled with the team's competition number) and record a stint-0
    assignment. This is EXACT at race start: before the first pit stop the
    number plate IS the physical machine, so team N is on machine N — and a
    stint-0 assignment is always historically true regardless of when this is
    run. Idempotent per user: existing labels are reused and teams that already
    have an assignment are skipped. Spare pit-lane karts are added separately.
    """
    try:
        uid = request.current_user['id']
        data = request.get_json(silent=True) or {}
        session_id = data.get('session_id') or race_ui._live_session_id(track_id)
        if not session_id:
            return jsonify({'error': 'no active session; pass session_id'}), 400
        conn = get_track_db_connection(track_id)
        created_karts, created_assignments, skipped = [], 0, 0
        try:
            cur = conn.cursor()
            # Teams in the session with their (stable) competition number. The
            # MAX(timestamp) makes SQLite take kart_number from the latest row.
            cur.execute(
                """SELECT team_name, kart_number, MAX(timestamp) FROM lap_times
                    WHERE session_id = ? AND team_name IS NOT NULL AND team_name != ''
                      AND kart_number IS NOT NULL
                    GROUP BY team_name""",
                (session_id,),
            )
            teams = [(r[0], r[1]) for r in cur.fetchall()]
            cur.execute(
                "SELECT label, id FROM fleet_karts WHERE user_id = ? AND is_active = 1", (uid,))
            label_to_id = {row[0]: row[1] for row in cur.fetchall()}
            cur.execute(
                "SELECT DISTINCT team_name FROM fleet_assignments "
                "WHERE session_id = ? AND user_id = ? AND superseded = 0", (session_id, uid))
            assigned_teams = {row[0] for row in cur.fetchall()}
            now = datetime.now().isoformat()
            for team_name, kart_number in teams:
                label = f"K-{kart_number}"   # physical-ID convention
                kid = label_to_id.get(label)
                if kid is None:
                    cur.execute(
                        "INSERT INTO fleet_karts (user_id, label, notes, is_active, created_at) "
                        "VALUES (?, ?, 'auto from session', 1, ?)", (uid, label, now))
                    kid = cur.lastrowid
                    label_to_id[label] = kid
                    created_karts.append({'id': kid, 'label': label})
                if team_name not in assigned_teams:
                    cur.execute(
                        """INSERT INTO fleet_assignments
                           (user_id, session_id, team_name, kart_number, fleet_kart_id, stint_index,
                            source, created_at, created_by, superseded)
                           VALUES (?, ?, ?, ?, ?, 0, 'auto', ?, ?, 0)""",
                        (uid, session_id, team_name, kart_number, kid, now, uid))
                    assigned_teams.add(team_name)
                    created_assignments += 1
                else:
                    skipped += 1
            conn.commit()
        finally:
            conn.close()
        _fleet_cache.pop((track_id, uid), None)
        _audit('fleet_auto_populate', actor_user_id=uid,
               target=f'track_{track_id}/session_{session_id}',
               details={'karts': len(created_karts), 'assignments': created_assignments})
        return jsonify({
            'session_id': session_id,
            'created_karts': created_karts,
            'created_assignments': created_assignments,
            'skipped_teams': skipped,
        }), 201
    except UnknownTrackError:
        raise
    except Exception as e:
        return _internal_error(e, 'auto_populate_fleet')
