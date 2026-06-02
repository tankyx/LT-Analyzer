"""Team data analysis endpoints (/api/team-data/*)."""
import sqlite3
import time
import traceback

from flask import Blueprint, jsonify, request

import race_ui

from race_ui import (
    admin_required,
    login_required,
)


team_data_bp = Blueprint('team_data', __name__)


@team_data_bp.route('/api/team-data/common-sessions', methods=['POST'])
@login_required
def get_common_sessions():
    """Get sessions where all specified teams participated"""
    try:
        data = request.json
        team_names = data.get('teams', [])
        track_id = data.get('track_id', 1)  # Default to track 1

        if not team_names or len(team_names) < 1:
            return jsonify({'sessions': []})

        conn = race_ui.get_track_db_connection(track_id)
        cursor = conn.cursor()

        # Get sessions where all teams participated
        placeholders = ','.join(['?' for _ in team_names])
        team_names_lower = [name.strip().lower() for name in team_names]

        query = f"""
            WITH team_sessions AS (
                SELECT DISTINCT
                    lt.session_id,
                    CASE
                        WHEN lt.team_name LIKE '% - %' THEN LOWER(TRIM(SUBSTR(lt.team_name, INSTR(lt.team_name, ' - ') + 3)))
                        ELSE LOWER(TRIM(lt.team_name))
                    END as team_name
                FROM lap_times lt
                WHERE (
                    CASE
                        WHEN lt.team_name LIKE '% - %' THEN LOWER(TRIM(SUBSTR(lt.team_name, INSTR(lt.team_name, ' - ') + 3)))
                        ELSE LOWER(TRIM(lt.team_name))
                    END
                ) IN ({placeholders})
            )
            SELECT
                rs.session_id,
                rs.start_time,
                rs.name,
                rs.track,
                COUNT(DISTINCT ts.team_name) as teams_present
            FROM race_sessions rs
            JOIN team_sessions ts ON rs.session_id = ts.session_id
            GROUP BY rs.session_id
            HAVING COUNT(DISTINCT ts.team_name) = ?
            ORDER BY rs.start_time DESC
        """

        cursor.execute(query, team_names_lower + [len(team_names)])
        sessions = [{
            'session_id': row[0],
            'start_time': row[1],
            'name': row[2],
            'track': row[3],
            'teams_present': row[4]
        } for row in cursor.fetchall()]

        conn.close()

        return jsonify({'sessions': sessions})
    except Exception as e:
        print(f"Error getting common sessions: {e}")
        traceback.print_exc()
        return race_ui._internal_error(e)

@team_data_bp.route('/api/team-data/sessions', methods=['GET'])
@login_required
def get_all_sessions():
    """Get all sessions for a track"""
    try:
        track_id = request.args.get('track_id', 1, type=int)  # Default to track 1

        conn = race_ui.get_track_db_connection(track_id)
        cursor = conn.cursor()

        # Get all sessions for the track, ordered by most recent first
        query = """
            SELECT
                rs.session_id,
                rs.start_time,
                rs.name,
                rs.track,
                COUNT(DISTINCT lt.team_name) as teams_count
            FROM race_sessions rs
            LEFT JOIN lap_times lt ON rs.session_id = lt.session_id
            GROUP BY rs.session_id
            ORDER BY rs.start_time DESC
        """

        cursor.execute(query)
        sessions = [{
            'session_id': row[0],
            'start_time': row[1],
            'name': row[2],
            'track': row[3],
            'teams_count': row[4]
        } for row in cursor.fetchall()]

        conn.close()

        return jsonify({'sessions': sessions})
    except Exception as e:
        print(f"Error getting sessions: {e}")
        traceback.print_exc()
        return race_ui._internal_error(e)

@team_data_bp.route('/api/team-data/search', methods=['GET'])
@login_required
def search_teams():
    """Search for teams by name (case-insensitive, removes class prefix)"""
    try:
        search_query = request.args.get('q', '').strip()
        session_id = request.args.get('session_id', None)
        track_id = request.args.get('track_id', 1, type=int)  # Default to track 1

        if not search_query:
            return jsonify({'teams': []})

        conn = race_ui.get_track_db_connection(track_id)
        cursor = conn.cursor()

        # Build query to search teams, handling both with and without class prefix
        query = """
            SELECT DISTINCT
                CASE
                    WHEN team_name LIKE '% - %' THEN TRIM(SUBSTR(team_name, INSTR(team_name, ' - ') + 3))
                    ELSE TRIM(team_name)
                END as team_name_clean,
                CASE
                    WHEN team_name LIKE '% - %' THEN GROUP_CONCAT(DISTINCT SUBSTR(team_name, 1, 1))
                    ELSE NULL
                END as classes
            FROM lap_times
            WHERE (
                CASE
                    WHEN team_name LIKE '% - %' THEN LOWER(TRIM(SUBSTR(team_name, INSTR(team_name, ' - ') + 3)))
                    ELSE LOWER(TRIM(team_name))
                END
            ) LIKE ?
            GROUP BY team_name_clean
            ORDER BY team_name_clean
            LIMIT 20
        """

        cursor.execute(query, (f'%{search_query.lower()}%',))
        direct = [{'name': row[0], 'classes': row[1] if row[1] else ''} for row in cursor.fetchall()]

        conn.close()

        # Also surface canonical drivers whose alias (or canonical name) matches
        # the query but whose exact team_name isn't in this track's lap_times.
        direct_names_lower = {t['name'].lower() for t in direct}
        alias_canonicals = set()
        try:
            q_lower = search_query.lower()
            with sqlite3.connect('auth.db') as aconn:
                for row in aconn.execute(
                    '''SELECT DISTINCT canonical_name FROM driver_aliases
                       WHERE LOWER(canonical_name) LIKE ? OR LOWER(alias_name) LIKE ?''',
                    (f'%{q_lower}%', f'%{q_lower}%'),
                ).fetchall():
                    alias_canonicals.add(row[0])
        except sqlite3.Error as e:
            race_ui.app.logger.warning(f"alias search lookup failed: {e}")

        teams = list(direct)
        for canonical in alias_canonicals:
            if canonical.lower() not in direct_names_lower:
                teams.append({'name': canonical, 'classes': '', 'via_alias': True})

        return jsonify({'teams': teams})
    except Exception as e:
        print(f"Error searching teams: {e}")
        return race_ui._internal_error(e)


@team_data_bp.route('/api/team-data/search-all', methods=['GET'])
@login_required
def search_teams_all_tracks():
    """Search driver/team names across EVERY track's database.

    Used by the alias admin UI so you can pick an existing name from any track
    (not just the one currently selected). Returns distinct names with the list
    of tracks they appear on.

    Query params:
      q (required) - substring, case-insensitive
      limit (optional) - max distinct names to return (default 20, max 100)
    """
    try:
        if race_ui._rate_limit_hit('heavy_read_ip', request.remote_addr or '-'):
            return jsonify({'error': 'rate_limited'}), 429

        q = request.args.get('q', '').strip()
        if not q:
            return jsonify({'teams': []})
        try:
            limit = max(1, min(100, int(request.args.get('limit', 20))))
        except (TypeError, ValueError):
            limit = 20
        q_lower = q.lower()

        # Enumerate active tracks once
        with sqlite3.connect('tracks.db') as tconn:
            tracks = tconn.execute(
                'SELECT id, track_name FROM tracks WHERE is_active = 1'
            ).fetchall()

        # Aggregate distinct cleaned team names across all track DBs
        agg = {}  # name_clean_lower -> {display, classes, track_ids}
        for track_id, track_name in tracks:
            try:
                conn = race_ui.get_track_db_connection(track_id)
                cursor = conn.cursor()
                cursor.execute(
                    """
                    SELECT DISTINCT
                        CASE
                            WHEN team_name LIKE '% - %' THEN TRIM(SUBSTR(team_name, INSTR(team_name, ' - ') + 3))
                            ELSE TRIM(team_name)
                        END AS team_name_clean,
                        CASE
                            WHEN team_name LIKE '% - %' THEN SUBSTR(team_name, 1, 1)
                            ELSE NULL
                        END AS class_prefix
                    FROM lap_times
                    WHERE (
                        CASE
                            WHEN team_name LIKE '% - %' THEN LOWER(TRIM(SUBSTR(team_name, INSTR(team_name, ' - ') + 3)))
                            ELSE LOWER(TRIM(team_name))
                        END
                    ) LIKE ?
                    """,
                    (f'%{q_lower}%',),
                )
                for row in cursor.fetchall():
                    name = (row[0] or '').strip()
                    if not name:
                        continue
                    key = name.lower()
                    entry = agg.setdefault(key, {
                        'name': name,
                        'classes': set(),
                        'track_ids': set(),
                        'track_names': set(),
                    })
                    if row[1]:
                        entry['classes'].add(row[1])
                    entry['track_ids'].add(track_id)
                    entry['track_names'].add(track_name)
                conn.close()
            except Exception as track_error:
                race_ui.app.logger.warning(f"search-all: track {track_id} query failed: {track_error}")
                continue

        # Also surface aliases whose alias_name or canonical_name matches q
        try:
            with sqlite3.connect('auth.db') as aconn:
                for row in aconn.execute(
                    '''SELECT DISTINCT canonical_name FROM driver_aliases
                       WHERE LOWER(canonical_name) LIKE ? OR LOWER(alias_name) LIKE ?''',
                    (f'%{q_lower}%', f'%{q_lower}%'),
                ).fetchall():
                    name = row[0]
                    key = name.lower()
                    agg.setdefault(key, {
                        'name': name,
                        'classes': set(),
                        'track_ids': set(),
                        'track_names': set(),
                        'via_alias': True,
                    })
        except sqlite3.Error as e:
            race_ui.app.logger.warning(f"search-all alias lookup failed: {e}")

        results = sorted(agg.values(), key=lambda r: r['name'].lower())[:limit]
        return jsonify({
            'teams': [
                {
                    'name': r['name'],
                    'classes': ''.join(sorted(r['classes'])),
                    'track_names': sorted(r['track_names']),
                    'track_count': len(r['track_ids']),
                    'via_alias': r.get('via_alias', False),
                }
                for r in results
            ],
        })
    except Exception as e:
        race_ui.app.logger.exception('search-all endpoint failed')
        return race_ui._internal_error(e)


@team_data_bp.route('/api/team-data/top-teams', methods=['GET'])
@login_required
def get_top_teams():
    """Get top N teams ranked by best lap time"""
    try:
        if race_ui._rate_limit_hit('heavy_read_ip', request.remote_addr or '-'):
            return jsonify({'error': 'rate_limited'}), 429

        limit = request.args.get('limit', 10, type=int)
        track_id = request.args.get('track_id', 1, type=int)  # Default to track 1
        session_id = request.args.get('session_id', None)

        # Validate limit
        if limit not in [10, 20, 30]:
            limit = 10

        # Phase 3: cache lookup. ~60s TTL is fine for a leaderboard — laps
        # don't change that fast at the ranks that matter, and admin
        # delete/mass-delete operations invalidate the prefix.
        cache_key = f'top_teams:{track_id}:{session_id}:{limit}'
        cached = race_ui._cache_get(cache_key)
        if cached is not None:
            return jsonify(cached)

        conn = race_ui.get_track_db_connection(track_id)
        cursor = conn.cursor()

        # Build session filter
        session_filter = ""
        query_params = []
        if session_id:
            session_filter = "AND session_id = ?"
            query_params.append(int(session_id))

        # Query to get top teams with their stats
        # Handles both formats: with class prefix "1 - TEAMNAME" and without "TEAMNAME"
        # Handles mixed best_lap formats: "MM:SS.mmm" and raw seconds
        query = f"""
            WITH team_stats AS (
                SELECT
                    CASE
                        WHEN team_name LIKE '% - %' THEN
                            LOWER(TRIM(SUBSTR(team_name, INSTR(team_name, ' - ') + 3)))
                        ELSE
                            LOWER(TRIM(team_name))
                    END as team_name_clean,
                    MAX(CASE
                        WHEN team_name LIKE '% - %' THEN
                            TRIM(SUBSTR(team_name, INSTR(team_name, ' - ') + 3))
                        ELSE
                            TRIM(team_name)
                    END) as team_name_display,
                    MIN(
                        CASE
                            WHEN best_lap LIKE '%:%' THEN
                                CAST(SUBSTR(best_lap, 1, INSTR(best_lap, ':') - 1) AS REAL) * 60 +
                                CAST(SUBSTR(best_lap, INSTR(best_lap, ':') + 1) AS REAL)
                            WHEN best_lap IS NOT NULL AND best_lap != '' AND LENGTH(TRIM(best_lap)) > 0 THEN
                                CAST(best_lap AS REAL)
                            ELSE
                                NULL
                        END
                    ) as best_lap_seconds,
                    COUNT(DISTINCT session_id) as sessions_count,
                    GROUP_CONCAT(DISTINCT SUBSTR(team_name, 1, 1)) as classes
                FROM lap_times
                WHERE best_lap IS NOT NULL
                AND best_lap != ''
                AND team_name IS NOT NULL
                AND team_name != ''
                {session_filter}
                GROUP BY team_name_clean
            ),
            team_laps AS (
                SELECT
                    CASE
                        WHEN lt.team_name LIKE '% - %' THEN
                            LOWER(TRIM(SUBSTR(lt.team_name, INSTR(lt.team_name, ' - ') + 3)))
                        ELSE
                            LOWER(TRIM(lt.team_name))
                    END as team_name_clean,
                    SUM(CASE
                        WHEN lt.position = 1 AND lt.gap LIKE 'Tour %'
                        THEN CAST(SUBSTR(lt.gap, 6) AS INTEGER)
                        WHEN lt.gap LIKE '+% Tour%'
                        THEN CAST(SUBSTR(lt.gap, 6) AS INTEGER) - CAST(SUBSTR(lt.gap, INSTR(lt.gap, '+') + 1, INSTR(lt.gap, ' ') - 2) AS INTEGER)
                        ELSE 0
                    END) as total_laps
                FROM lap_times lt
                WHERE lt.team_name IS NOT NULL
                AND lt.team_name != ''
                {session_filter}
                GROUP BY team_name_clean
            ),
            avg_laps AS (
                SELECT
                    CASE
                        WHEN team_name LIKE '% - %' THEN
                            LOWER(TRIM(SUBSTR(team_name, INSTR(team_name, ' - ') + 3)))
                        ELSE
                            LOWER(TRIM(team_name))
                    END as team_name_clean,
                    AVG(
                        CASE
                            WHEN last_lap LIKE '%:%' THEN
                                CAST(SUBSTR(last_lap, 1, INSTR(last_lap, ':') - 1) AS REAL) * 60 +
                                CAST(SUBSTR(last_lap, INSTR(last_lap, ':') + 1) AS REAL)
                            ELSE NULL
                        END
                    ) as avg_lap_seconds
                FROM lap_times
                WHERE last_lap IS NOT NULL
                AND last_lap != ''
                AND last_lap LIKE '%:%'
                AND team_name IS NOT NULL
                AND team_name != ''
                {session_filter}
                GROUP BY team_name_clean
            ),
            best_lap_timestamps AS (
                SELECT
                    subq.team_name_clean,
                    MIN(subq.timestamp) as best_lap_timestamp
                FROM (
                    SELECT
                        CASE
                            WHEN team_name LIKE '% - %' THEN
                                LOWER(TRIM(SUBSTR(team_name, INSTR(team_name, ' - ') + 3)))
                            ELSE
                                LOWER(TRIM(team_name))
                        END as team_name_clean,
                        timestamp,
                        CASE
                            WHEN best_lap LIKE '%:%' THEN
                                CAST(SUBSTR(best_lap, 1, INSTR(best_lap, ':') - 1) AS REAL) * 60 +
                                CAST(SUBSTR(best_lap, INSTR(best_lap, ':') + 1) AS REAL)
                            WHEN best_lap IS NOT NULL AND best_lap != '' AND LENGTH(TRIM(best_lap)) > 0 THEN
                                CAST(best_lap AS REAL)
                            ELSE
                                NULL
                        END as best_lap_seconds
                    FROM lap_times
                    WHERE best_lap IS NOT NULL
                    AND best_lap != ''
                    AND team_name IS NOT NULL
                    AND team_name != ''
                    {session_filter}
                ) subq
                INNER JOIN team_stats ts ON subq.team_name_clean = ts.team_name_clean
                    AND subq.best_lap_seconds IS NOT NULL
                    AND ts.best_lap_seconds IS NOT NULL
                    AND ABS(subq.best_lap_seconds - ts.best_lap_seconds) < 0.01
                GROUP BY subq.team_name_clean
            )
            SELECT
                ts.team_name_display,
                ts.best_lap_seconds,
                COALESCE(al.avg_lap_seconds, 0) as avg_lap_seconds,
                COALESCE(tl.total_laps, 0) as total_laps,
                ts.sessions_count,
                ts.classes,
                blt.best_lap_timestamp
            FROM team_stats ts
            LEFT JOIN team_laps tl ON ts.team_name_clean = tl.team_name_clean
            LEFT JOIN avg_laps al ON ts.team_name_clean = al.team_name_clean
            LEFT JOIN best_lap_timestamps blt ON ts.team_name_clean = blt.team_name_clean
            WHERE ts.best_lap_seconds IS NOT NULL
            ORDER BY ts.best_lap_seconds ASC
            LIMIT ?
        """

        # Add limit parameter to query_params
        query_params_with_limit = query_params * 4 + [limit]  # session_id repeated for each CTE (now 4), then limit
        cursor.execute(query, query_params_with_limit)
        teams = []
        for row in cursor.fetchall():
            best_lap_seconds = row[1]
            # Format best_lap_seconds to MM:SS.mmm
            if best_lap_seconds:
                mins = int(best_lap_seconds // 60)
                secs = best_lap_seconds % 60
                best_lap_formatted = f"{mins}:{secs:06.3f}"
            else:
                best_lap_formatted = None

            teams.append({
                'name': row[0],
                'best_lap_time': best_lap_formatted,
                'avg_lap_seconds': row[2],
                'total_laps': row[3],
                'sessions_count': row[4],
                'classes': row[5],
                'best_lap_timestamp': row[6] if len(row) > 6 else None
            })

        conn.close()

        payload = {'teams': teams, 'limit': limit}
        race_ui._cache_put(cache_key, payload)
        return jsonify(payload)
    except Exception as e:
        print(f"Error getting top teams: {e}")
        traceback.print_exc()
        return race_ui._internal_error(e)

@team_data_bp.route('/api/team-data/stats', methods=['GET'])
@login_required
def get_team_stats():
    """Get statistics for a specific team"""
    try:
        team_name = request.args.get('team', '').strip().lower()
        session_id = request.args.get('session_id', None)
        track_id = request.args.get('track_id', 1, type=int)  # Default to track 1

        if not team_name:
            return jsonify({'error': 'race_ui.Team name required'}), 400

        conn = race_ui.get_track_db_connection(track_id)
        cursor = conn.cursor()

        # Get overall statistics
        # Handles both formats: with class prefix "1 - TEAMNAME" and without "TEAMNAME"
        stats_query = """
            SELECT
                COUNT(*) as total_records,
                MIN(
                    CASE
                        WHEN best_lap LIKE '%:%' THEN
                            CAST(SUBSTR(best_lap, 1, INSTR(best_lap, ':') - 1) AS REAL) * 60 +
                            CAST(SUBSTR(best_lap, INSTR(best_lap, ':') + 1) AS REAL)
                        WHEN best_lap IS NOT NULL AND best_lap != '' THEN
                            CAST(best_lap AS REAL)
                        ELSE NULL
                    END
                ) as best_lap_seconds,
                COUNT(DISTINCT session_id) as sessions_participated,
                GROUP_CONCAT(DISTINCT SUBSTR(team_name, 1, 1)) as classes_raced,
                MAX(pit_stops) as max_pit_stops
            FROM lap_times
            WHERE CASE
                    WHEN team_name LIKE '% - %' THEN
                        LOWER(TRIM(SUBSTR(team_name, INSTR(team_name, ' - ') + 3)))
                    ELSE
                        LOWER(TRIM(team_name))
                END = ?
        """

        cursor.execute(stats_query, (team_name,))
        stats = cursor.fetchone()

        # Calculate total laps using the race leader's lap count from gap field
        # For each session, find winner's lap count and calculate this team's laps
        session_filter = ""
        query_params = [team_name]
        if session_id:
            session_filter = "AND tfg.session_id = ?"
            query_params.append(int(session_id))

        lap_count_query = f"""
            WITH leader_laps AS (
                SELECT
                    session_id,
                    MAX(CASE
                        WHEN position = 1 AND gap LIKE 'Tour %'
                        THEN CAST(SUBSTR(gap, 6) AS INTEGER)
                        WHEN position = 1 AND gap LIKE 'Lap %'
                        THEN CAST(SUBSTR(gap, 5) AS INTEGER)
                        ELSE 0
                    END) as total_laps
                FROM lap_times
                WHERE gap LIKE 'Tour %' OR gap LIKE 'Lap %'
                GROUP BY session_id
            ),
            team_final_gap AS (
                SELECT DISTINCT
                    lt.session_id,
                    FIRST_VALUE(lt.gap) OVER (PARTITION BY lt.session_id ORDER BY lt.timestamp DESC) as final_gap
                FROM lap_times lt
                WHERE CASE
                        WHEN lt.team_name LIKE '% - %' THEN
                            LOWER(TRIM(SUBSTR(lt.team_name, INSTR(lt.team_name, ' - ') + 3)))
                        ELSE
                            LOWER(TRIM(lt.team_name))
                    END = ?
            )
            SELECT
                SUM(CASE
                    WHEN tfg.final_gap LIKE '% Tour%' THEN
                        ll.total_laps - CAST(SUBSTR(tfg.final_gap, 1, INSTR(tfg.final_gap, ' ') - 1) AS INTEGER)
                    WHEN tfg.final_gap LIKE '% Lap%' THEN
                        ll.total_laps - CAST(SUBSTR(tfg.final_gap, 1, INSTR(tfg.final_gap, ' ') - 1) AS INTEGER)
                    ELSE
                        ll.total_laps
                END) as total_laps_all_sessions
            FROM team_final_gap tfg
            JOIN leader_laps ll ON tfg.session_id = ll.session_id
            WHERE ll.total_laps > 0 {session_filter}
        """

        cursor.execute(lap_count_query, query_params)
        lap_count_result = cursor.fetchone()
        total_laps = lap_count_result[0] if lap_count_result and lap_count_result[0] else 0

        # Get lap history statistics for average lap time
        lap_history_session_filter = ""
        lap_history_params = [team_name]
        if session_id:
            lap_history_session_filter = "AND session_id = ?"
            lap_history_params.append(int(session_id))

        lap_history_query = f"""
            SELECT
                AVG(lap_seconds) as avg_lap_seconds
            FROM (
                SELECT DISTINCT
                    session_id,
                    lap_number,
                    CAST(SUBSTR(lap_time, 1, 1) AS REAL) * 60 + CAST(SUBSTR(lap_time, 3) AS REAL) as lap_seconds
                FROM lap_history
                WHERE CASE
                        WHEN team_name LIKE '% - %' THEN
                            LOWER(TRIM(SUBSTR(team_name, INSTR(team_name, ' - ') + 3)))
                        ELSE
                            LOWER(TRIM(team_name))
                    END = ?
                AND lap_time IS NOT NULL
                AND lap_time != ''
                AND lap_time NOT LIKE '%Tour%'
                AND lap_time NOT LIKE '%Lap%'
                {lap_history_session_filter}
            )
        """

        cursor.execute(lap_history_query, lap_history_params)
        lap_stats = cursor.fetchone()

        # Get session breakdown
        session_query = """
            SELECT
                rs.session_id,
                rs.start_time,
                rs.name as session_name,
                COUNT(lt.id) as lap_records,
                MIN(
                    CASE
                        WHEN lt.best_lap LIKE '%:%' THEN
                            CAST(SUBSTR(lt.best_lap, 1, INSTR(lt.best_lap, ':') - 1) AS REAL) * 60 +
                            CAST(SUBSTR(lt.best_lap, INSTR(lt.best_lap, ':') + 1) AS REAL)
                        WHEN lt.best_lap IS NOT NULL AND lt.best_lap != '' THEN
                            CAST(lt.best_lap AS REAL)
                        ELSE NULL
                    END
                ) as best_lap_seconds
            FROM race_sessions rs
            LEFT JOIN lap_times lt ON rs.session_id = lt.session_id
            WHERE CASE
                    WHEN lt.team_name LIKE '% - %' THEN
                        LOWER(TRIM(SUBSTR(lt.team_name, INSTR(lt.team_name, ' - ') + 3)))
                    ELSE
                        LOWER(TRIM(lt.team_name))
                END = ?
            GROUP BY rs.session_id
            ORDER BY rs.start_time DESC
        """

        cursor.execute(session_query, (team_name,))
        sessions = []
        for row in cursor.fetchall():
            best_lap_secs = row[4]
            if best_lap_secs:
                mins = int(best_lap_secs // 60)
                secs = best_lap_secs % 60
                best_lap_formatted = f"{mins}:{secs:06.3f}"
            else:
                best_lap_formatted = None

            sessions.append({
                'session_id': row[0],
                'start_time': row[1],
                'name': row[2],
                'lap_records': row[3],
                'best_lap': best_lap_formatted
            })

        conn.close()

        # Format best_lap_seconds to MM:SS.mmm
        best_lap_seconds = stats[1] if stats else None
        if best_lap_seconds:
            mins = int(best_lap_seconds // 60)
            secs = best_lap_seconds % 60
            best_lap_time = f"{mins}:{secs:06.3f}"
        else:
            best_lap_time = None

        return jsonify({
            'team_name': team_name,
            'total_records': stats[0] if stats else 0,
            'best_lap_time': best_lap_time,
            'sessions_participated': stats[2] if stats else 0,
            'classes_raced': stats[3].split(',') if stats and stats[3] else [],
            'max_pit_stops': stats[4] if stats else 0,
            'total_laps_completed': total_laps,  # Use calculated total from leader's lap count
            'avg_lap_seconds': round(lap_stats[0], 3) if lap_stats and lap_stats[0] else None,
            'total_pit_stops': stats[4] if stats else 0,  # Use max_pit_stops from lap_times table
            'sessions': sessions
        })
    except Exception as e:
        print(f"Error getting team stats: {e}")
        traceback.print_exc()
        return race_ui._internal_error(e)

@team_data_bp.route('/api/team-data/lap-details', methods=['POST'])
@login_required
def get_lap_details():
    """Get detailed lap-by-lap data for teams in a session"""
    try:
        data = request.json
        team_names = data.get('teams', [])
        session_id = data.get('session_id', None)
        track_id = data.get('track_id', 1)  # Default to track 1

        if not team_names or not session_id:
            return jsonify({'error': 'Teams and session_id required'}), 400

        conn = race_ui.get_track_db_connection(track_id)
        cursor = conn.cursor()

        lap_details = {}

        for team_name in team_names:
            team_name_lower = team_name.strip().lower()

            # Debug: Count total records for this team in session
            debug_count_query = """
                SELECT COUNT(*) FROM lap_times
                WHERE (
                    CASE
                        WHEN team_name LIKE '% - %' THEN LOWER(TRIM(SUBSTR(team_name, INSTR(team_name, ' - ') + 3)))
                        ELSE LOWER(TRIM(team_name))
                    END
                ) = ?
                AND session_id = ?
            """
            cursor.execute(debug_count_query, (team_name_lower, int(session_id)))
            total_records = cursor.fetchone()[0]
            race_ui.app.logger.debug('race_ui.Team %s has %s records in session %s', team_name, total_records, session_id)

            # Get all laps from lap_times by detecting when last_lap changes
            lap_query = """
                WITH lap_changes AS (
                    SELECT
                        timestamp,
                        last_lap,
                        LAG(last_lap) OVER (ORDER BY timestamp) as prev_last_lap,
                        pit_stops,
                        LAG(pit_stops, 1, 0) OVER (ORDER BY timestamp) as prev_pit_stops
                    FROM lap_times
                    WHERE (
                        CASE
                            WHEN team_name LIKE '% - %' THEN LOWER(TRIM(SUBSTR(team_name, INSTR(team_name, ' - ') + 3)))
                            ELSE LOWER(TRIM(team_name))
                        END
                    ) = ?
                    AND session_id = ?
                    AND last_lap IS NOT NULL
                    AND last_lap <> ''
                    ORDER BY timestamp
                ),
                lap_completions AS (
                    SELECT
                        ROW_NUMBER() OVER (ORDER BY timestamp) as lap_number,
                        last_lap,
                        CASE
                            WHEN last_lap LIKE '%:%' THEN
                                CAST(SUBSTR(last_lap, 1, INSTR(last_lap, ':') - 1) AS REAL) * 60 +
                                CAST(SUBSTR(last_lap, INSTR(last_lap, ':') + 1) AS REAL)
                            ELSE 0
                        END as lap_seconds,
                        CASE WHEN pit_stops > prev_pit_stops THEN 1 ELSE 0 END as had_pit
                    FROM lap_changes
                    WHERE last_lap <> prev_last_lap OR prev_last_lap IS NULL
                )
                SELECT
                    lap_number,
                    lap_seconds,
                    had_pit
                FROM lap_completions
                WHERE lap_seconds > 50 AND lap_seconds < 600
                ORDER BY lap_number ASC
            """

            cursor.execute(lap_query, (team_name_lower, int(session_id)))
            laps_raw = cursor.fetchall()
            race_ui.app.logger.debug('race_ui.Team %s - lap_details query returned %s laps', team_name, len(laps_raw))

            laps = []
            for (lap_number, lap_seconds, pit_this_lap) in laps_raw:
                laps.append({
                    'lap_number': lap_number,
                    'lap_time': lap_seconds,
                    'pit_stop': pit_this_lap > 0
                })

            lap_details[team_name] = laps

        # Detect stints for all teams based on pit stop laps (3:40 - 3:50 = 220-230 seconds)
        stints = []
        for team_name, laps in lap_details.items():
            team_stints = []
            stint_start = 1
            stint_number = 1

            for i, lap in enumerate(laps):
                # Detect pit stop lap (lap time >= 225 seconds or 3:45)
                if lap['lap_time'] >= 225:
                    # End current stint before the pit lap
                    if lap['lap_number'] > stint_start:
                        team_stints.append({
                            'stint_number': stint_number,
                            'start_lap': stint_start,
                            'end_lap': lap['lap_number'] - 1,
                            'lap_count': lap['lap_number'] - stint_start
                        })
                        stint_number += 1
                    # Next stint starts after the pit lap
                    stint_start = lap['lap_number'] + 1

            # Add final stint (from last pit to end of race)
            if laps and stint_start <= laps[-1]['lap_number']:
                team_stints.append({
                    'stint_number': stint_number,
                    'start_lap': stint_start,
                    'end_lap': laps[-1]['lap_number'],
                    'lap_count': laps[-1]['lap_number'] - stint_start + 1
                })

            stints.append({
                'team_name': team_name,
                'stints': team_stints
            })

        conn.close()

        return jsonify({
            'lap_details': lap_details,
            'stints': stints
        })
    except Exception as e:
        print(f"Error getting lap details: {e}")
        traceback.print_exc()
        return race_ui._internal_error(e)

@team_data_bp.route('/api/team-data/compare', methods=['POST'])
@login_required
def compare_teams():
    """Compare statistics for multiple teams"""
    try:
        data = request.json
        team_names = data.get('teams', [])
        session_id = data.get('session_id', None)
        track_id = data.get('track_id', 1)  # Default to track 1

        if not team_names or len(team_names) < 2:
            return jsonify({'error': 'At least 2 teams required for comparison'}), 400

        conn = race_ui.get_track_db_connection(track_id)
        cursor = conn.cursor()

        comparison = []

        for team_name in team_names:
            team_name_lower = team_name.strip().lower()

            # Build session filter
            session_filter_stats = ""
            stats_params = [team_name_lower]
            if session_id:
                session_filter_stats = "AND session_id = ?"
                stats_params.append(int(session_id))

            # Get overall statistics
            stats_query = f"""
                SELECT
                    COUNT(*) as total_records,
                    MIN(
                        CASE
                            WHEN best_lap LIKE '%:%' THEN
                                CAST(SUBSTR(best_lap, 1, INSTR(best_lap, ':') - 1) AS REAL) * 60 +
                                CAST(SUBSTR(best_lap, INSTR(best_lap, ':') + 1) AS REAL)
                            WHEN best_lap IS NOT NULL AND best_lap != '' THEN
                                CAST(best_lap AS REAL)
                            ELSE NULL
                        END
                    ) as best_lap_seconds,
                    COUNT(DISTINCT session_id) as sessions_participated,
                    GROUP_CONCAT(DISTINCT SUBSTR(team_name, 1, 1)) as classes_raced
                FROM lap_times
                WHERE CASE
                        WHEN team_name LIKE '% - %' THEN
                            LOWER(TRIM(SUBSTR(team_name, INSTR(team_name, ' - ') + 3)))
                        ELSE
                            LOWER(TRIM(team_name))
                    END = ?
                {session_filter_stats}
            """

            cursor.execute(stats_query, stats_params)
            stats = cursor.fetchone()

            # Calculate total laps using the race leader's lap count from gap field
            session_filter_laps = ""
            lap_count_params = [team_name_lower]
            if session_id:
                session_filter_laps = "AND tfg.session_id = ?"
                lap_count_params.append(int(session_id))

            lap_count_query = f"""
                WITH leader_laps AS (
                    SELECT
                        session_id,
                        MAX(CASE
                            WHEN position = 1 AND gap LIKE 'Tour %'
                            THEN CAST(SUBSTR(gap, 6) AS INTEGER)
                            WHEN position = 1 AND gap LIKE 'Lap %'
                            THEN CAST(SUBSTR(gap, 5) AS INTEGER)
                            ELSE 0
                        END) as total_laps
                    FROM lap_times
                    WHERE gap LIKE 'Tour %' OR gap LIKE 'Lap %'
                    GROUP BY session_id
                ),
                team_final_gap AS (
                    SELECT DISTINCT
                        lt.session_id,
                        FIRST_VALUE(lt.gap) OVER (PARTITION BY lt.session_id ORDER BY lt.timestamp DESC) as final_gap
                    FROM lap_times lt
                    WHERE CASE
                            WHEN lt.team_name LIKE '% - %' THEN
                                LOWER(TRIM(SUBSTR(lt.team_name, INSTR(lt.team_name, ' - ') + 3)))
                            ELSE
                                LOWER(TRIM(lt.team_name))
                        END = ?
                )
                SELECT
                    SUM(CASE
                        WHEN tfg.final_gap LIKE '% Tour%' THEN
                            ll.total_laps - CAST(SUBSTR(tfg.final_gap, 1, INSTR(tfg.final_gap, ' ') - 1) AS INTEGER)
                        WHEN tfg.final_gap LIKE '% Lap%' THEN
                            ll.total_laps - CAST(SUBSTR(tfg.final_gap, 1, INSTR(tfg.final_gap, ' ') - 1) AS INTEGER)
                        ELSE
                            ll.total_laps
                    END) as total_laps_all_sessions
                FROM team_final_gap tfg
                JOIN leader_laps ll ON tfg.session_id = ll.session_id
                WHERE ll.total_laps > 0 {session_filter_laps}
            """

            cursor.execute(lap_count_query, lap_count_params)
            lap_count_result = cursor.fetchone()
            total_laps = lap_count_result[0] if lap_count_result and lap_count_result[0] else 0

            # Get lap history statistics for average lap time
            session_filter_history = ""
            lap_history_params = [team_name_lower]
            if session_id:
                session_filter_history = "AND session_id = ?"
                lap_history_params.append(int(session_id))

            lap_history_query = f"""
                SELECT
                    AVG(lap_seconds) as avg_lap_seconds
                FROM (
                    SELECT DISTINCT
                        session_id,
                        lap_number,
                        CAST(SUBSTR(lap_time, 1, 1) AS REAL) * 60 + CAST(SUBSTR(lap_time, 3) AS REAL) as lap_seconds
                    FROM lap_history
                    WHERE CASE
                            WHEN team_name LIKE '% - %' THEN
                                LOWER(TRIM(SUBSTR(team_name, INSTR(team_name, ' - ') + 3)))
                            ELSE
                                LOWER(TRIM(team_name))
                        END = ?
                    AND lap_time IS NOT NULL
                    AND lap_time != ''
                    AND lap_time NOT LIKE '%Tour%'
                    AND lap_time NOT LIKE '%Lap%'
                    {session_filter_history}
                )
            """

            cursor.execute(lap_history_query, lap_history_params)
            lap_stats = cursor.fetchone()

            # Get lap time distribution (last 50 unique laps) - use DISTINCT to avoid duplicates
            session_filter_dist = ""
            lap_dist_params = [team_name_lower]
            if session_id:
                session_filter_dist = "AND session_id = ?"
                lap_dist_params.append(int(session_id))

            lap_dist_query = f"""
                SELECT DISTINCT
                    session_id,
                    lap_number,
                    lap_time
                FROM lap_history
                WHERE CASE
                        WHEN team_name LIKE '% - %' THEN
                            LOWER(TRIM(SUBSTR(team_name, INSTR(team_name, ' - ') + 3)))
                        ELSE
                            LOWER(TRIM(team_name))
                    END = ?
                AND lap_time IS NOT NULL
                AND lap_time != ''
                AND lap_time NOT LIKE '%Tour%'
                AND lap_time NOT LIKE '%Lap%'
                {session_filter_dist}
                ORDER BY session_id DESC, lap_number DESC
                LIMIT 50
            """

            cursor.execute(lap_dist_query, lap_dist_params)
            lap_times_raw = cursor.fetchall()

            # Parse lap times to seconds
            lap_times = []
            for (session_id, lap_number, lap_time) in lap_times_raw:
                try:
                    if ':' in lap_time:
                        parts = lap_time.split(':')
                        if len(parts) == 2:
                            minutes = int(parts[0])
                            seconds = float(parts[1].replace(',', '.'))
                            lap_seconds = minutes * 60 + seconds
                            if 50 < lap_seconds < 150:  # Filter unrealistic times
                                lap_times.append(lap_seconds)
                except Exception:
                    continue

            # Format best_lap_seconds to MM:SS.mmm
            best_lap_seconds = stats[1] if stats else None
            if best_lap_seconds:
                mins = int(best_lap_seconds // 60)
                secs = best_lap_seconds % 60
                best_lap_formatted = f"{mins}:{secs:06.3f}"
            else:
                best_lap_formatted = None

            comparison.append({
                'team_name': team_name,
                'total_records': stats[0] if stats else 0,
                'best_lap_time': best_lap_formatted,
                'sessions_participated': stats[2] if stats else 0,
                'classes_raced': stats[3].split(',') if stats and stats[3] else [],
                'total_laps_completed': total_laps,  # Use calculated total from leader's lap count
                'avg_lap_seconds': round(lap_stats[0], 3) if lap_stats and lap_stats[0] else None,
                'lap_times': lap_times[:20]  # Return last 20 laps for charting
            })

        conn.close()

        return jsonify({'comparison': comparison})
    except Exception as e:
        print(f"Error comparing teams: {e}")
        traceback.print_exc()
        return race_ui._internal_error(e)

@team_data_bp.route('/api/team-data/delete-best-lap', methods=['POST'])
@admin_required
def delete_best_lap():
    """Delete (nullify) a team's best lap time record (admin only)"""
    try:
        data = request.json
        team_name = data.get('team_name', '').strip().lower()
        track_id = data.get('track_id', 1)
        best_lap_time = data.get('best_lap_time', '').strip()

        if not team_name or not best_lap_time:
            return jsonify({'error': 'team_name and best_lap_time are required'}), 400

        # Parse best_lap_time to seconds for comparison.
        # Format is "M:SS.mmm" or raw seconds. Enforce a realistic karting range
        # to prevent accidental mass-deletion via nonsense inputs (the match uses
        # a 0.01s tolerance, so very small values would otherwise match many rows).
        try:
            best_lap_seconds = race_ui.parse_time_to_seconds(best_lap_time)
        except (ValueError, TypeError):
            return jsonify({'error': 'Invalid best_lap_time format'}), 400
        if not (30.0 <= best_lap_seconds <= 600.0):
            return jsonify({'error': 'best_lap_time out of realistic range (30-600s)'}), 400

        # Retry logic to handle database locks
        max_retries = 3
        retry_delay = 0.5  # seconds
        last_error = None

        for attempt in range(max_retries):
            try:
                conn = race_ui.get_track_db_connection(track_id, timeout=5.0)
                cursor = conn.cursor()

                # Find and nullify the best_lap field for records matching this team and lap time
                # Handle both formats: with class prefix "1 - TEAMNAME" and without "TEAMNAME"
                # Also handle mixed best_lap formats: "MM:SS.mmm" and raw seconds
                update_query = """
                    UPDATE lap_times
                    SET best_lap = NULL
                    WHERE CASE
                            WHEN team_name LIKE '% - %' THEN
                                LOWER(TRIM(SUBSTR(team_name, INSTR(team_name, ' - ') + 3)))
                            ELSE
                                LOWER(TRIM(team_name))
                        END = ?
                    AND ABS(
                        CASE
                            WHEN best_lap LIKE '%:%' THEN
                                CAST(SUBSTR(best_lap, 1, INSTR(best_lap, ':') - 1) AS REAL) * 60 +
                                CAST(SUBSTR(best_lap, INSTR(best_lap, ':') + 1) AS REAL)
                            WHEN best_lap IS NOT NULL AND best_lap != '' THEN
                                CAST(best_lap AS REAL)
                            ELSE 999999
                        END - ?
                    ) < 0.01
                """

                cursor.execute(update_query, (team_name, best_lap_seconds))
                rows_updated = cursor.rowcount
                conn.commit()
                conn.close()

                if rows_updated == 0:
                    return jsonify({'error': 'No matching lap time found for this team'}), 404

                race_ui._audit('admin_delete_best_lap',
                       actor_user_id=request.current_user['id'],
                       target=f'track_{track_id}/{team_name}',
                       details={'best_lap_time': best_lap_time, 'rows_updated': rows_updated})
                # Bust caches that might surface stale results.
                race_ui._cache_invalidate_prefix(f'top_teams:{track_id}:')
                race_ui._cache_invalidate_prefix('cross_track_sessions:')
                return jsonify({
                    'success': True,
                    'message': f'Deleted best lap time for {team_name}',
                    'rows_updated': rows_updated
                })

            except sqlite3.OperationalError as e:
                last_error = e
                if 'locked' in str(e).lower() and attempt < max_retries - 1:
                    print(f"Database locked on attempt {attempt + 1}/{max_retries}, retrying in {retry_delay}s...")
                    time.sleep(retry_delay)
                    retry_delay *= 2  # Exponential backoff
                    continue
                else:
                    raise
            finally:
                try:
                    if 'conn' in locals():
                        conn.close()
                except Exception:
                    pass

        # If we get here, all retries failed
        raise last_error if last_error else Exception("Unknown error during database operation")

    except Exception as e:
        print(f"Error deleting best lap: {e}")
        traceback.print_exc()
        return race_ui._internal_error(e)

@team_data_bp.route('/api/team-data/mass-delete-laps', methods=['POST'])
@admin_required
def mass_delete_laps():
    """
    Delete all lap times under a specified threshold (track-wide, admin only)

    Supports two deletion modes:
    1. lap_history: Delete individual lap records from lap_history table
    2. best_laps: Nullify best_lap field in lap_times if below threshold
    """
    try:
        data = request.json or {}
        track_id = data.get('track_id', 1)
        threshold_seconds = data.get('threshold_seconds')
        delete_type = data.get('delete_type', 'lap_history')

        if threshold_seconds is None:
            return jsonify({'error': 'threshold_seconds is required'}), 400

        # Coerce and sanity-check threshold. Unvalidated non-numeric input
        # previously cast to 0 via SQL CAST, which would silently match nothing
        # or worse; we require a positive float in a realistic karting range.
        try:
            threshold_seconds = float(threshold_seconds)
        except (TypeError, ValueError):
            return jsonify({'error': 'threshold_seconds must be numeric'}), 400
        if not (0 < threshold_seconds <= 3600):
            return jsonify({'error': 'threshold_seconds out of range (0, 3600]'}), 400

        try:
            track_id = int(track_id)
        except (TypeError, ValueError):
            return jsonify({'error': 'track_id must be an integer'}), 400

        # Validate delete_type
        if delete_type not in ['lap_history', 'best_laps']:
            return jsonify({'error': 'delete_type must be "lap_history" or "best_laps"'}), 400

        # Retry logic to handle database locks
        max_retries = 3
        retry_delay = 0.5
        last_error = None

        for attempt in range(max_retries):
            try:
                conn = race_ui.get_track_db_connection(track_id, timeout=10.0)
                cursor = conn.cursor()

                rows_affected = 0

                if delete_type == 'lap_history':
                    # Delete individual lap records from lap_history
                    delete_query = """
                        DELETE FROM lap_history
                        WHERE CASE
                                WHEN lap_time LIKE '%:%' THEN
                                    CAST(SUBSTR(lap_time, 1, INSTR(lap_time, ':') - 1) AS REAL) * 60 +
                                    CAST(SUBSTR(lap_time, INSTR(lap_time, ':') + 1) AS REAL)
                                WHEN lap_time IS NOT NULL AND lap_time != '' THEN
                                    CAST(lap_time AS REAL)
                                ELSE 999999
                            END < ?
                    """
                    cursor.execute(delete_query, (threshold_seconds,))
                    rows_affected = cursor.rowcount

                elif delete_type == 'best_laps':
                    # Nullify best_lap field in lap_times if below threshold
                    update_query = """
                        UPDATE lap_times
                        SET best_lap = NULL
                        WHERE CASE
                                WHEN best_lap LIKE '%:%' THEN
                                    CAST(SUBSTR(best_lap, 1, INSTR(best_lap, ':') - 1) AS REAL) * 60 +
                                    CAST(SUBSTR(best_lap, INSTR(best_lap, ':') + 1) AS REAL)
                                WHEN best_lap IS NOT NULL AND best_lap != '' THEN
                                    CAST(best_lap AS REAL)
                                ELSE 999999
                            END < ?
                    """
                    cursor.execute(update_query, (threshold_seconds,))
                    rows_affected = cursor.rowcount

                conn.commit()
                conn.close()

                race_ui._audit('admin_mass_delete_laps',
                       actor_user_id=request.current_user['id'],
                       target=f'track_{track_id}',
                       details={'delete_type': delete_type,
                                'threshold_seconds': threshold_seconds,
                                'rows_affected': rows_affected})
                # Mass deletion almost certainly changes the leaderboard.
                race_ui._cache_invalidate_prefix(f'top_teams:{track_id}:')
                race_ui._cache_invalidate_prefix('cross_track_sessions:')
                return jsonify({
                    'success': True,
                    'message': f'Mass deletion completed',
                    'rows_affected': rows_affected,
                    'delete_type': delete_type,
                    'threshold_seconds': threshold_seconds
                })

            except sqlite3.OperationalError as e:
                last_error = e
                if 'locked' in str(e).lower() and attempt < max_retries - 1:
                    print(f"Database locked on attempt {attempt + 1}/{max_retries}, retrying in {retry_delay}s...")
                    time.sleep(retry_delay)
                    retry_delay *= 2
                    continue
                else:
                    raise
            finally:
                try:
                    if 'conn' in locals():
                        conn.close()
                except Exception:
                    pass

        # If we get here, all retries failed
        raise last_error if last_error else Exception("Unknown error during mass delete operation")

    except Exception as e:
        print(f"Error in mass delete: {e}")
        traceback.print_exc()
        return race_ui._internal_error(e)

@team_data_bp.route('/api/team-data/all-laps', methods=['GET'])
@login_required
def get_all_laps():
    """
    Get all laps for a specific team on a track

    Parameters:
    - team (required): team name
    - track_id (required): track ID
    - session_id (optional): filter by session
    - limit (optional): max number of laps to return (default: 50)
    - offset (optional): pagination offset (default: 0)
    """
    try:
        team_name = request.args.get('team', '').strip().lower()
        track_id = request.args.get('track_id', 1, type=int)
        session_id = request.args.get('session_id', None, type=int)
        limit = request.args.get('limit', 50, type=int)
        offset = request.args.get('offset', 0, type=int)

        if not team_name:
            return jsonify({'error': 'team parameter is required'}), 400

        conn = race_ui.get_track_db_connection(track_id)
        cursor = conn.cursor()

        # Build session filter
        session_filter = ""
        query_params = [team_name]
        if session_id:
            session_filter = "AND lh.session_id = ?"
            query_params.append(session_id)

        # Query to get all laps with session information
        query = f"""
            SELECT
                lh.lap_number,
                lh.lap_time,
                lh.session_id,
                rs.name as session_name,
                rs.start_time as session_date,
                lh.timestamp,
                lh.pit_this_lap,
                lh.position_after_lap
            FROM lap_history lh
            JOIN race_sessions rs ON lh.session_id = rs.session_id
            WHERE CASE
                    WHEN lh.team_name LIKE '% - %' THEN
                        LOWER(TRIM(SUBSTR(lh.team_name, INSTR(lh.team_name, ' - ') + 3)))
                    ELSE
                        LOWER(TRIM(lh.team_name))
                END = ?
            {session_filter}
            ORDER BY rs.start_time DESC, lh.lap_number ASC
            LIMIT ? OFFSET ?
        """

        query_params.extend([limit, offset])
        cursor.execute(query, query_params)

        laps = []
        for row in cursor.fetchall():
            laps.append({
                'lap_number': row[0],
                'lap_time': row[1],
                'session_id': row[2],
                'session_name': row[3] if row[3] else 'Unknown Session',
                'session_date': row[4],
                'timestamp': row[5],
                'pit_this_lap': bool(row[6]),
                'position_after_lap': row[7]
            })

        # Get total count for pagination
        count_query = f"""
            SELECT COUNT(*)
            FROM lap_history lh
            WHERE CASE
                    WHEN lh.team_name LIKE '% - %' THEN
                        LOWER(TRIM(SUBSTR(lh.team_name, INSTR(lh.team_name, ' - ') + 3)))
                    ELSE
                        LOWER(TRIM(lh.team_name))
                END = ?
            {session_filter}
        """
        cursor.execute(count_query, [team_name] + (query_params[1:2] if session_id else []))
        total_laps = cursor.fetchone()[0]

        conn.close()

        return jsonify({
            'team_name': team_name,
            'track_id': track_id,
            'total_laps': total_laps,
            'laps': laps,
            'limit': limit,
            'offset': offset
        })

    except Exception as e:
        print(f"Error getting all laps: {e}")
        traceback.print_exc()
        return race_ui._internal_error(e)

@team_data_bp.route('/api/team-data/cross-track-sessions', methods=['GET'])
@login_required
def get_cross_track_sessions():
    """
    Get all sessions for a team across all tracks

    Parameters:
    - team (required): team name (supports flexible matching - finds all name variations)
    """
    try:
        if race_ui._rate_limit_hit('heavy_read_ip', request.remote_addr or '-'):
            return jsonify({'error': 'rate_limited'}), 429

        team_name = request.args.get('team', '').strip()

        if not team_name:
            return jsonify({'error': 'team parameter is required'}), 400

        # Phase 3 cache lookup — keyed by the normalised team name.
        cache_key = f'cross_track_sessions:{team_name.lower()}'
        cached = race_ui._cache_get(cache_key)
        if cached is not None:
            return jsonify(cached)

        # Expand through alias group so one search finds all name variants
        alias_names = race_ui._expand_alias_group(team_name)
        if not alias_names:
            alias_names = [team_name]

        # Get all tracks from tracks.db
        tracks_conn = sqlite3.connect('tracks.db')
        tracks_cursor = tracks_conn.cursor()
        tracks_cursor.execute('SELECT id, track_name FROM tracks WHERE is_active = 1')
        tracks = tracks_cursor.fetchall()
        tracks_conn.close()

        sessions = []
        total_laps = 0
        tracks_raced = 0
        bests_by_track_map = {}  # track_id -> best lap info for that track

        # Query each track's database
        for track_id, track_name in tracks:
            try:
                conn = race_ui.get_track_db_connection(track_id)
                cursor = conn.cursor()

                history_names, times_names = race_ui._find_matching_team_names(cursor, alias_names)
                if not history_names and not times_names:
                    conn.close()
                    continue

                session_rows = race_ui._fetch_driver_session_ids(cursor, history_names, times_names)
                track_had_sessions = False
                for session_id, session_name, session_date in session_rows:
                    laps_with_flag = race_ui._fetch_laps_for_session(cursor, session_id, history_names, times_names)
                    if not laps_with_flag:
                        continue
                    track_had_sessions = True
                    laps = [s for s, _ in laps_with_flag]
                    on_track = [s for s, pit in laps_with_flag if not pit] or laps
                    best_lap_secs = min(on_track)
                    avg_lap_secs = sum(on_track) / len(on_track)

                    best_lap_formatted = race_ui._format_seconds(best_lap_secs)
                    avg_lap_formatted = race_ui._format_seconds(avg_lap_secs)

                    cur_best = bests_by_track_map.get(track_id)
                    if cur_best is None or best_lap_secs < cur_best['best_lap_seconds']:
                        bests_by_track_map[track_id] = {
                            'track_id': track_id,
                            'track_name': track_name,
                            'best_lap': best_lap_formatted,
                            'best_lap_seconds': round(best_lap_secs, 3),
                            'session_id': session_id,
                            'session_date': session_date,
                        }

                    sessions.append({
                        'session_id': session_id,
                        'track_id': track_id,
                        'track_name': track_name,
                        'session_name': session_name if session_name else 'Unknown Session',
                        'session_date': session_date,
                        'total_laps': len(laps),
                        'best_lap': best_lap_formatted,
                        'avg_lap': avg_lap_formatted,
                    })
                    total_laps += len(laps)

                if track_had_sessions:
                    tracks_raced += 1
                conn.close()

            except Exception as track_error:
                print(f"Error querying track {track_id}: {track_error}")
                continue

        payload = {
            'team_name': team_name,
            'sessions': sessions,
            'overall_stats': {
                'total_sessions': len(sessions),
                'total_laps': total_laps,
                'tracks_raced': tracks_raced,
                'bests_by_track': sorted(bests_by_track_map.values(), key=lambda e: e['track_name']),
            }
        }
        race_ui._cache_put(cache_key, payload)
        return jsonify(payload)

    except Exception as e:
        print(f"Error getting cross-track sessions: {e}")
        traceback.print_exc()
        return race_ui._internal_error(e)

@team_data_bp.route('/api/team-data/session-laps', methods=['GET'])
@login_required
def get_session_laps():
    """
    Get all lap details for a specific team in a specific session

    Parameters:
    - team (required): team name (flexible matching)
    - track_id (required): track ID
    - session_id (required): session ID
    """
    try:
        team_name = request.args.get('team', '').strip().lower()
        track_id = request.args.get('track_id', type=int)
        session_id = request.args.get('session_id', type=int)

        if not team_name:
            return jsonify({'error': 'team parameter is required'}), 400
        if not track_id:
            return jsonify({'error': 'track_id parameter is required'}), 400
        if not session_id:
            return jsonify({'error': 'session_id parameter is required'}), 400

        # Tokenize the team name for flexible matching
        name_tokens = [token.strip() for token in team_name.split() if token.strip()]

        # Build flexible matching conditions
        conditions = []
        params = [session_id]
        for token in name_tokens:
            conditions.append("LOWER(lh.team_name) LIKE ?")
            params.append(f'%{token}%')

        where_clause = " AND ".join(conditions) if conditions else "1=1"

        conn = race_ui.get_track_db_connection(track_id)
        cursor = conn.cursor()

        # Calculate lap numbers based on chronological order since lap_number field is unreliable
        query = f"""
            SELECT
                ROW_NUMBER() OVER (ORDER BY lh.timestamp ASC) as lap_number,
                lh.lap_time,
                lh.timestamp,
                lh.pit_this_lap,
                lh.position_after_lap
            FROM lap_history lh
            WHERE lh.session_id = ?
                AND ({where_clause})
            ORDER BY lh.timestamp ASC
        """

        cursor.execute(query, params)
        rows = cursor.fetchall()

        laps = []
        for row in rows:
            lap_number, lap_time, timestamp, pit_this_lap, position_after_lap = row
            laps.append({
                'lap_number': lap_number,
                'lap_time': lap_time,
                'timestamp': timestamp,
                'pit_this_lap': bool(pit_this_lap),
                'position_after_lap': position_after_lap
            })

        # Fallback: many tracks only populate lap_times. Reconstruct per-lap
        # rows from last_lap snapshots — dedupe consecutive duplicates (the
        # race_ui.parser writes on every socket tick, so the same last_lap appears
        # many times), derive pit_this_lap from pit_stops deltas, and number
        # chronologically.
        if not laps:
            lt_conditions = []
            lt_params = [session_id]
            for token in name_tokens:
                lt_conditions.append("LOWER(team_name) LIKE ?")
                lt_params.append(f'%{token}%')
            lt_where = " AND ".join(lt_conditions) if lt_conditions else "1=1"
            cursor.execute(
                f"""
                SELECT timestamp, last_lap, position, pit_stops
                  FROM lap_times
                 WHERE session_id = ?
                   AND ({lt_where})
                   AND last_lap IS NOT NULL AND last_lap != ''
                 ORDER BY timestamp ASC
                """,
                lt_params,
            )
            prev_lap = None
            prev_pit = None
            idx = 0
            for ts, last_lap, position, pit_stops in cursor.fetchall():
                # Skip repeated ticks with the same last_lap value
                if last_lap == prev_lap:
                    continue
                try:
                    pit_val = int(pit_stops) if pit_stops is not None else None
                except (TypeError, ValueError):
                    pit_val = None
                pit_this_lap = (
                    prev_pit is not None and pit_val is not None and pit_val > prev_pit
                )
                idx += 1
                laps.append({
                    'lap_number': idx,
                    'lap_time': last_lap,
                    'timestamp': ts,
                    'pit_this_lap': bool(pit_this_lap),
                    'position_after_lap': position,
                })
                prev_lap = last_lap
                if pit_val is not None:
                    prev_pit = pit_val

        conn.close()

        return jsonify({
            'laps': laps,
            'total_count': len(laps)
        })

    except Exception as e:
        print(f"Error getting session laps: {e}")
        traceback.print_exc()
        return race_ui._internal_error(e)
