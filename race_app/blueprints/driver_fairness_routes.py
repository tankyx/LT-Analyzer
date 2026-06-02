"""Driver fairness endpoint."""
import math

from flask import Blueprint, jsonify, request

from race_ui import (
    LAP_MAX_SECONDS,
    LAP_MIN_SECONDS,
    MIN_SESSIONS_AGG,
    MIN_SESSIONS_VERDICT,
    _analyze_endurance_session,
    _analyze_sprint_session,
    _chi2_sf,
    _classify_session_mode,
    _ensure_session_layouts,
    _expand_alias_group,
    _fetch_driver_session_ids,
    _filter_sessions_by_layout_and_window,
    _find_matching_team_names,
    _internal_error,
    _normal_cdf,
    _safe_parse_time,
    _stddev,
    _window_cutoff,
    app,
    get_track_db_connection,
    track_db,
)


driver_fairness_bp = Blueprint('driver_fairness', __name__)


@driver_fairness_bp.route('/api/driver/fairness', methods=['GET'])
def get_driver_fairness():
    """Per-track kart fairness analysis for a driver.

    Returns sprint kart-factor samples + a randomness test on kart assignment,
    plus endurance stint-pace stability. Aggregate conclusions are gated by
    MIN_SESSIONS_AGG; randomness verdicts require MIN_SESSIONS_VERDICT.

    Query params:
      name (required)       - driver/team name
      track_id (required)   - track to analyze
      layout_id (optional)  - restrict to one physical layout
      window_months         - rolling window in months (default 12; 0 = all)
    """
    try:
        raw_name = request.args.get('name', '').strip()
        if not raw_name:
            return jsonify({'error': 'name parameter is required'}), 400
        alias_names = _expand_alias_group(raw_name)
        if not alias_names:
            return jsonify({'error': 'name parameter is required'}), 400

        track_id = request.args.get('track_id', type=int)
        if not track_id:
            return jsonify({'error': 'track_id parameter is required'}), 400

        track_row = track_db.get_track_by_id(track_id)
        if not track_row:
            return jsonify({'error': f'Unknown track_id {track_id}'}), 404

        layout_id = request.args.get('layout_id', type=int)
        try:
            window_months = int(request.args.get('window_months', 12))
        except (TypeError, ValueError):
            window_months = 12
        window_cutoff = _window_cutoff(window_months)

        # Legacy field-best band (same semantics as the track endpoint) — lets
        # callers scope the randomness tests to a sub-band of a layout without
        # having to define a new one.
        def _opt_float(name):
            v = request.args.get(name)
            if v is None or v == '':
                return None
            try:
                return float(v)
            except (TypeError, ValueError):
                return None
        min_field_best = _opt_float('min_field_best')
        max_field_best = _opt_float('max_field_best')

        conn = get_track_db_connection(track_id)
        cur = conn.cursor()

        # Compute field-best per session (used for backfill + band filter).
        raw_field = {}
        cur.execute('SELECT session_id, best_lap FROM lap_times WHERE best_lap IS NOT NULL AND best_lap != ""')
        for sid, bl in cur.fetchall():
            secs = _safe_parse_time(bl)
            if secs == float('inf') or secs < LAP_MIN_SECONDS or secs > LAP_MAX_SECONDS:
                continue
            if sid not in raw_field or secs < raw_field[sid]:
                raw_field[sid] = secs

        if layout_id is not None:
            _ensure_session_layouts(conn, track_id, raw_field)

        allowed_sids = _filter_sessions_by_layout_and_window(conn, layout_id, window_cutoff)

        # Apply the legacy field-best band on top of layout/window. Intersect
        # with allowed_sids when both are active.
        if min_field_best is not None or max_field_best is not None:
            band_sids = set()
            for sid, fb in raw_field.items():
                if min_field_best is not None and fb < min_field_best:
                    continue
                if max_field_best is not None and fb > max_field_best:
                    continue
                band_sids.add(sid)
            allowed_sids = band_sids if allowed_sids is None else (allowed_sids & band_sids)

        # Find all sessions where any alias appears — in EITHER lap_history or
        # lap_times, so we don't miss tracks where the parser only wrote to
        # lap_times (see _fetch_driver_session_ids).
        history_names, times_names = _find_matching_team_names(cur, alias_names)
        session_rows = [
            (sid, start) for sid, _name, start in
            _fetch_driver_session_ids(cur, history_names, times_names)
        ]
        if allowed_sids is not None:
            session_rows = [(sid, s) for sid, s in session_rows if sid in allowed_sids]

        sprint_samples = []
        endurance_sessions = []

        for session_id, session_date in session_rows:
            mode = _classify_session_mode(cur, session_id, history_names, times_names)
            if mode == 'sprint':
                sprint_samples.extend(_analyze_sprint_session(
                    cur, session_id, session_date, history_names, times_names
                ))
            elif mode == 'endurance':
                r = _analyze_endurance_session(cur, session_id, session_date, alias_names)
                if r:
                    endurance_sessions.append(r)

        conn.close()

        # Sprint aggregate
        sprint_session_count = len({s['session_id'] for s in sprint_samples})
        sprint_block = {
            'enabled': sprint_session_count >= MIN_SESSIONS_AGG,
            'session_count': sprint_session_count,
            'sample_count': len(sprint_samples),
            'samples': sprint_samples,
        }
        if sprint_samples:
            factors = [s['kart_factor'] for s in sprint_samples]
            mean_factor = sum(factors) / len(factors)
            sprint_block['mean_factor'] = round(mean_factor, 5)
            sprint_block['stddev_factor'] = round(_stddev(factors), 5)

            # Top-quartile karts in sessions where the driver appeared.
            # Threshold per session = max(1, K//4). Expected count under
            # random assignment = sum of (threshold_i / K_i) across samples —
            # NOT n*0.25, because the threshold rounds down and small
            # sessions contribute less than 25% per sample.
            top_q_obs = 0
            expected_sum = 0.0
            var_sum = 0.0  # sum of p_i*(1-p_i) for normal approximation
            # Quartile bucket counts (0 = best 25% via rank_percentile)
            quartile_counts = [0, 0, 0, 0]
            for s in sprint_samples:
                K = s['karts_in_session']
                threshold = max(1, K // 4)
                p_i = threshold / K
                expected_sum += p_i
                var_sum += p_i * (1.0 - p_i)
                if s['kart_rank'] <= threshold:
                    top_q_obs += 1
                # Quartile via rank_percentile so buckets carry ~equal mass
                # under Uniform(0,1) null
                p = s.get('rank_percentile', (s['kart_rank'] - 0.5) / K)
                q = min(3, int(p * 4))
                quartile_counts[q] += 1

            sprint_block['top_quartile_count'] = top_q_obs
            sprint_block['top_quartile_expected'] = round(expected_sum, 3)
            sprint_block['quartile_counts'] = quartile_counts

            # One-sided p-value for "more top-quartile karts than random".
            # Poisson-binomial via normal approximation with continuity
            # correction; valid for the sample sizes we care about (n >= ~10).
            n = len(sprint_samples)
            if var_sum > 0:
                z = (top_q_obs - 0.5 - expected_sum) / math.sqrt(var_sum)
                sprint_block['top_quartile_p_value'] = round(1.0 - _normal_cdf(z), 5)
            else:
                sprint_block['top_quartile_p_value'] = None

            # Chi-squared goodness-of-fit against Uniform(0,1) percentile
            # under random assignment → 4 buckets with 25% mass each.
            expected_per_bucket = n / 4.0
            chi2 = 0.0
            if expected_per_bucket > 0:
                for obs in quartile_counts:
                    chi2 += (obs - expected_per_bucket) ** 2 / expected_per_bucket
            sprint_block['chi2_statistic'] = round(chi2, 4)
            sprint_block['chi2_df'] = 3
            sprint_block['chi2_p_value'] = round(_chi2_sf(chi2, 3), 5)

            # Verdict is only meaningful with enough samples to power the
            # test against realistic alternatives. Below the threshold we
            # withhold the verdict entirely rather than mislead with a
            # "looks random" result that just reflects low power.
            if n >= MIN_SESSIONS_VERDICT:
                p_chi = sprint_block['chi2_p_value']
                p_top = sprint_block['top_quartile_p_value']
                if p_chi is not None and p_chi < 0.05:
                    sprint_block['randomness_verdict'] = 'non_random'
                elif p_top is not None and p_top < 0.05:
                    sprint_block['randomness_verdict'] = 'non_random_top_heavy'
                else:
                    sprint_block['randomness_verdict'] = 'consistent_with_random'
            else:
                sprint_block['randomness_verdict'] = 'insufficient_data'
        else:
            sprint_block['mean_factor'] = None
            sprint_block['stddev_factor'] = None
            sprint_block['top_quartile_count'] = 0
            sprint_block['top_quartile_expected'] = 0.0
            sprint_block['quartile_counts'] = [0, 0, 0, 0]
            sprint_block['top_quartile_p_value'] = None
            sprint_block['chi2_statistic'] = None
            sprint_block['chi2_df'] = 3
            sprint_block['chi2_p_value'] = None
            sprint_block['randomness_verdict'] = 'insufficient_data'

        sprint_block['min_sessions_verdict'] = MIN_SESSIONS_VERDICT

        endurance_block = {
            'enabled': len(endurance_sessions) >= MIN_SESSIONS_AGG,
            'session_count': len(endurance_sessions),
            'sessions': endurance_sessions,
            'flagged_count': sum(1 for s in endurance_sessions if s.get('flagged')),
        }

        return jsonify({
            'driver_name': raw_name,
            'track_id': track_id,
            'track_name': track_row.get('track_name') if isinstance(track_row, dict) else track_row[1],
            'layout_id': layout_id,
            'window_months': window_months,
            'min_sessions_threshold': MIN_SESSIONS_AGG,
            'min_sessions_verdict': MIN_SESSIONS_VERDICT,
            'sprint': sprint_block,
            'endurance': endurance_block,
        })

    except Exception as e:
        app.logger.exception("fairness endpoint failed")
        return _internal_error(e)

