"""Driver lap-time consistency endpoint."""
import sqlite3

from flask import Blueprint, jsonify, request

import race_ui


driver_consistency_bp = Blueprint('driver_consistency', __name__)


@driver_consistency_bp.route('/api/driver/consistency', methods=['GET'])
def get_driver_consistency():
    """Cross-track lap-time consistency stats for a driver/team.

    Query params:
      name (required) - driver/team name (flexible tokenized matching).
    """
    try:
        raw_name = request.args.get('name', '').strip()
        if not raw_name:
            return jsonify({'error': 'name parameter is required'}), 400
        alias_names = race_ui._expand_alias_group(raw_name)
        if not alias_names:
            return jsonify({'error': 'name parameter is required'}), 400

        tracks_conn = sqlite3.connect('tracks.db')
        tracks_cursor = tracks_conn.cursor()
        tracks_cursor.execute('SELECT id, track_name FROM tracks WHERE is_active = 1')
        tracks = tracks_cursor.fetchall()
        tracks_conn.close()

        sessions_out = []
        all_laps = []  # aggregate across all sessions for overall stats
        tracks_raced = set()

        for track_id, track_name in tracks:
            try:
                conn = race_ui.get_track_db_connection(track_id)
                cur = conn.cursor()

                history_names, times_names = race_ui._find_matching_team_names(cur, alias_names)
                if not history_names and not times_names:
                    conn.close()
                    continue

                session_rows = race_ui._fetch_driver_session_ids(cur, history_names, times_names)
                per_session = {}
                for session_id, session_name, session_date in session_rows:
                    laps_with_flag = race_ui._fetch_laps_for_session(cur, session_id, history_names, times_names)
                    if not laps_with_flag:
                        continue
                    per_session[session_id] = {
                        'session_id': session_id,
                        'session_name': session_name,
                        'session_date': session_date,
                        'track_id': track_id,
                        'track_name': track_name,
                        'laps': laps_with_flag,
                        'pit_laps': sum(1 for _, pit in laps_with_flag if pit),
                    }

                conn.close()

                if per_session:
                    tracks_raced.add(track_id)

                for ent in per_session.values():
                    laps_with_flag = ent['laps']
                    if not laps_with_flag:
                        continue
                    # Outlier rejection already applied in race_ui._fetch_laps_for_session
                    # via MAD filter. Remaining 'clean' set = non-pit-in laps.
                    on_track = [s for s, pit in laps_with_flag if not pit]
                    if not on_track:
                        on_track = [s for s, _ in laps_with_flag]
                    clean = sorted(on_track)
                    laps = [s for s, _ in laps_with_flag]
                    best = min(clean)
                    mean = sum(clean) / len(clean)
                    median = clean[len(clean) // 2]
                    sd = race_ui._stddev(clean)
                    cov = (sd / mean) if mean > 0 else 0
                    within_05 = sum(1 for v in clean if v <= best + 0.5) / len(clean)
                    within_1 = sum(1 for v in clean if v <= best + 1.0) / len(clean)
                    within_2 = sum(1 for v in clean if v <= best + 2.0) / len(clean)
                    all_laps.extend(clean)
                    sessions_out.append({
                        'session_id': ent['session_id'],
                        'session_name': ent['session_name'],
                        'session_date': ent['session_date'],
                        'track_id': ent['track_id'],
                        'track_name': ent['track_name'],
                        'total_laps': len(laps),
                        'clean_laps': len(clean),
                        'pit_laps': ent['pit_laps'],
                        'best_lap': race_ui._format_seconds(best),
                        'best_lap_seconds': round(best, 3),
                        'mean_lap_seconds': round(mean, 3),
                        'median_lap_seconds': round(median, 3),
                        'stddev_seconds': round(sd, 3),
                        'cov': round(cov, 5),
                        'pct_within_0_5s': round(within_05, 4),
                        'pct_within_1s': round(within_1, 4),
                        'pct_within_2s': round(within_2, 4),
                    })

            except Exception as track_error:
                race_ui.app.logger.warning(f"consistency: track {track_id} query failed: {track_error}")
                continue

        sessions_out.sort(key=lambda s: s['session_date'] or '', reverse=True)

        # Best lap per track — lap times on different tracks aren't comparable,
        # so a single "Best Lap Overall" is misleading. Expose per-track bests.
        bests_by_track = {}
        for s in sessions_out:
            t_id = s['track_id']
            entry = bests_by_track.get(t_id)
            if entry is None or s['best_lap_seconds'] < entry['best_lap_seconds']:
                bests_by_track[t_id] = {
                    'track_id': t_id,
                    'track_name': s['track_name'],
                    'best_lap': s['best_lap'],
                    'best_lap_seconds': s['best_lap_seconds'],
                    'session_id': s['session_id'],
                    'session_date': s['session_date'],
                }

        overall = {
            'total_sessions': len(sessions_out),
            'total_laps': sum(s['total_laps'] for s in sessions_out),
            'tracks_raced': len(tracks_raced),
            'bests_by_track': sorted(bests_by_track.values(), key=lambda e: e['track_name']),
        }
        if all_laps:
            mean_all = sum(all_laps) / len(all_laps)
            sd_all = race_ui._stddev(all_laps)
            overall['career_mean_seconds'] = round(mean_all, 3)
            overall['career_stddev_seconds'] = round(sd_all, 3)
            overall['career_cov'] = round((sd_all / mean_all) if mean_all > 0 else 0, 5)
        else:
            overall['career_mean_seconds'] = None
            overall['career_stddev_seconds'] = None
            overall['career_cov'] = None

        # Trend: chronological series (oldest -> newest) of session best/stddev
        trend = [
            {
                'date': s['session_date'],
                'track_name': s['track_name'],
                'best': s['best_lap_seconds'],
                'mean': s['mean_lap_seconds'],
                'stddev': s['stddev_seconds'],
            }
            for s in sorted(sessions_out, key=lambda x: x['session_date'] or '')
        ]

        return jsonify({
            'driver_name': raw_name,
            'overall': overall,
            'sessions': sessions_out,
            'trend': trend,
        })

    except Exception as e:
        race_ui.app.logger.exception("consistency endpoint failed")
        return race_ui._internal_error(e)
