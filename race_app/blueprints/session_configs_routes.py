"""Session-config (layout-detection) endpoint.

Routes:
  GET /api/track/<track_id>/session-configs
"""

from flask import Blueprint, jsonify

from race_ui import (
    LAP_MAX_SECONDS,
    LAP_MIN_SECONDS,
    _internal_error,
    _safe_parse_time,
    app,
    get_track_db_connection,
    track_db,
)


session_configs_bp = Blueprint('session_configs', __name__)


@session_configs_bp.route('/api/track/<int:track_id>/session-configs', methods=['GET'])
def get_track_session_configs(track_id):
    """Return the distribution of session field-best laps for this track, so
    the UI can help users pick layout thresholds. A single track may run
    multiple physical configurations whose lap times differ by >10%.
    """
    try:
        track_row = track_db.get_track_by_id(track_id)
        if not track_row:
            return jsonify({'error': f'Unknown track_id {track_id}'}), 404

        conn = get_track_db_connection(track_id)
        cur = conn.cursor()
        cur.execute(
            """
            SELECT session_id, best_lap FROM lap_times
             WHERE best_lap IS NOT NULL AND best_lap != ''
             GROUP BY session_id, best_lap
            """
        )
        rows = cur.fetchall()
        conn.close()

        per_session_min = {}
        for sid, bl in rows:
            secs = _safe_parse_time(bl)
            if secs == float('inf') or secs < LAP_MIN_SECONDS or secs > LAP_MAX_SECONDS:
                continue
            if sid not in per_session_min or secs < per_session_min[sid]:
                per_session_min[sid] = secs

        values = sorted(per_session_min.values())
        # Bucketise into 1-second bins for histogram display
        buckets = {}
        for v in values:
            b = int(v)  # 1-second bins
            buckets[b] = buckets.get(b, 0) + 1
        histogram = [{'field_best_bin': b, 'count': c} for b, c in sorted(buckets.items())]

        # Suggested layout splits: find the largest gap in the value distribution
        gaps = []
        for i in range(1, len(values)):
            gaps.append((values[i] - values[i - 1], values[i - 1], values[i]))
        gaps.sort(reverse=True)
        suggested_splits = [
            {'gap': round(g[0], 2), 'below': round(g[1], 2), 'above': round(g[2], 2)}
            for g in gaps[:5] if g[0] >= 1.0
        ]

        return jsonify({
            'track_id': track_id,
            'track_name': track_row['track_name'],
            'session_count': len(values),
            'field_best_min': round(values[0], 2) if values else None,
            'field_best_max': round(values[-1], 2) if values else None,
            'histogram': histogram,
            'suggested_splits': suggested_splits,
        })

    except Exception as e:
        app.logger.exception("session configs endpoint failed")
        return _internal_error(e)
