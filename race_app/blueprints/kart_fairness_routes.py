"""Kart-fairness (track-wide, driver-normalized) endpoint."""
import math
import sqlite3

from flask import Blueprint, jsonify, request

from race_ui import (
    LAP_MAX_SECONDS,
    LAP_MIN_SECONDS,
    MIN_SESSIONS_VERDICT,
    _ensure_session_layouts,
    _filter_sessions_by_layout_and_window,
    _format_seconds,
    _gammainc_upper_reg,
    _internal_error,
    _is_test_placeholder,
    _quantile,
    _safe_parse_time,
    _stddev,
    _strip_driver_class_prefix,
    _window_cutoff,
    app,
    get_track_db_connection,
    track_db,
)


kart_fairness_bp = Blueprint('kart_fairness', __name__)


@kart_fairness_bp.route('/api/track/<int:track_id>/kart-fairness', methods=['GET'])
def get_track_kart_fairness(track_id):
    """Track-wide kart-fairness leaderboard, driver-normalized.

    Rather than comparing drivers' absolute pace (which mixes skill with kart
    quality), this compares each driver to a STABLE personal reference — the
    10th-percentile of their session bests (PB-min has extreme-value bias that
    worsens the more sessions a driver has).

    Per-driver metrics:
      pb_seconds                  - min session-best (legacy "best ever")
      reference_p10_seconds       - 10th-percentile session-best (stable ref)
      mean_session_best_seconds   - avg of each session's best lap
      stddev_session_best_seconds - σ of session bests (dispersion)
      iqr_session_best_seconds    - IQR of session bests (robust dispersion)
      mean_gap_to_reference_pct   - avg (session_best - ref) / ref, in percent
      mean_relative_pace          - mean (session_best / session_median_best)
      stddev_relative_pace        - σ of that ratio (HEADLINE metric — low =
                                    consistent relative pace = lucky karts)

    Query params:
      min_sessions (default 3)  - minimum sessions to include a driver
      layout_id                 - restrict to a single physical layout
      window_months (default 12)- rolling window; 0 = no window
      min_field_best / max_field_best - legacy band filter (still supported)
    """
    try:
        try:
            min_sessions = int(request.args.get('min_sessions', 3))
        except (TypeError, ValueError):
            min_sessions = 3
        min_sessions = max(2, min(50, min_sessions))

        layout_id = request.args.get('layout_id', type=int)
        try:
            window_months = int(request.args.get('window_months', 12))
        except (TypeError, ValueError):
            window_months = 12
        window_cutoff = _window_cutoff(window_months)

        # Legacy field-best filter: still honoured when layout_id is not
        # provided. Layout id supersedes these when present.
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

        track_row = track_db.get_track_by_id(track_id)
        if not track_row:
            return jsonify({'error': f'Unknown track_id {track_id}'}), 404

        conn = get_track_db_connection(track_id)
        cur = conn.cursor()

        # One bulk scan: every (session, team) pair with distinct best_lap
        # snapshots. Python-side min (vs. SQL MIN on raw strings) because the
        # values mix MM:SS.mmm and SS.mmm formats.
        cur.execute(
            """
            SELECT session_id, team_name, best_lap FROM lap_times
             WHERE best_lap IS NOT NULL AND best_lap != ''
               AND team_name IS NOT NULL AND team_name != ''
             GROUP BY session_id, team_name, best_lap
            """
        )
        raw_rows = cur.fetchall()

        # (session, team) -> best seconds (keep the min across snapshots).
        # Test/staff placeholders are dropped here so they don't inflate session
        # medians or noise floors.
        session_team_best = {}
        for sid, team, bl in raw_rows:
            if _is_test_placeholder(_strip_driver_class_prefix(team)):
                continue
            secs = _safe_parse_time(bl)
            if secs == float('inf') or secs < LAP_MIN_SECONDS or secs > LAP_MAX_SECONDS:
                continue
            key = (sid, team)
            if key not in session_team_best or secs < session_team_best[key]:
                session_team_best[key] = secs

        # Per-session field-best for config detection + noise filter
        per_session_bests = {}  # session -> list of all team bests
        for (sid, _team), secs in session_team_best.items():
            per_session_bests.setdefault(sid, []).append(secs)
        session_field_best = {sid: min(v) for sid, v in per_session_bests.items() if v}

        # Backfill layout_id on any NULL sessions using the field-best we
        # just computed; then apply the layout + window filter.
        _ensure_session_layouts(conn, track_id, session_field_best)
        allowed_sids = _filter_sessions_by_layout_and_window(conn, layout_id, window_cutoff)
        conn.close()
        if allowed_sids is not None:
            session_team_best = {k: v for k, v in session_team_best.items() if k[0] in allowed_sids}
            per_session_bests = {k: v for k, v in per_session_bests.items() if k in allowed_sids}

        # Legacy field-best band filter (for UI that hasn't migrated to layout_id yet)
        if min_field_best is not None or max_field_best is not None:
            allowed = set()
            for sid, fb in session_field_best.items():
                if allowed_sids is not None and sid not in allowed_sids:
                    continue
                if min_field_best is not None and fb < min_field_best:
                    continue
                if max_field_best is not None and fb > max_field_best:
                    continue
                allowed.add(sid)
            session_team_best = {k: v for k, v in session_team_best.items() if k[0] in allowed}
            per_session_bests = {k: v for k, v in per_session_bests.items() if k in allowed}

        # Per-session noise floor (75% of the session median) + store the
        # median itself so we can normalise each driver's session best against
        # the field's daily pace — this cancels day-to-day condition effects
        # (weather, track temp, wind) that would otherwise distort the
        # PB-based gap metric.
        session_floor = {}
        session_median_best = {}
        for sid, vals in per_session_bests.items():
            if len(vals) < 3:
                session_floor[sid] = 0.0
                session_median_best[sid] = None
                continue
            svals = sorted(vals)
            median = svals[len(svals) // 2]
            session_floor[sid] = median * 0.75
            session_median_best[sid] = median

        # Build alias lookup: for every team_name appearing in lap_times, find
        # the canonical name to merge records under. Anything without an alias
        # entry maps to itself.
        alias_canon = {}
        try:
            with sqlite3.connect('auth.db') as aconn:
                rows = aconn.execute(
                    'SELECT canonical_name, alias_name FROM driver_aliases'
                ).fetchall()
                for canon, alias in rows:
                    alias_canon[alias.lower()] = canon
                    alias_canon[canon.lower()] = canon  # canonical resolves to itself
        except sqlite3.Error as e:
            app.logger.warning(f"alias lookup failed in track kart fairness: {e}")

        def _canonical_of(name):
            # Step 1: remove per-driver class prefix so HC-/JR-/G- entries merge
            stripped = _strip_driver_class_prefix(name)
            # Step 2: apply alias mapping to the stripped form
            return alias_canon.get(stripped.lower(), stripped)

        # Group clean session bests per driver (collapsed under canonical names).
        # A driver can appear under multiple aliases WITHIN a single session
        # (endurance driver change or simple relabeling) — keep the better of
        # the two as the session's best for that canonical driver. Test/staff
        # placeholder names (APEXTEST, EQUIPE TEST, 'test 2', etc.) are dropped
        # entirely because they pollute per-session medians as well.
        canon_session_best = {}
        for (sid, team), secs in session_team_best.items():
            if secs < session_floor.get(sid, 0.0):
                continue
            canon = _canonical_of(team)
            if _is_test_placeholder(canon):
                continue
            key = (canon, sid)
            if key not in canon_session_best or secs < canon_session_best[key]:
                canon_session_best[key] = secs

        per_driver = {}  # canonical team -> list of (session_id, session_best_seconds)
        for (canon, sid), secs in canon_session_best.items():
            per_driver.setdefault(canon, []).append((sid, secs))

        drivers = []
        for team, rows in per_driver.items():
            if len(rows) < min_sessions:
                continue
            session_bests = [s for _, s in rows]
            sorted_sb = sorted(session_bests)
            pb = sorted_sb[0]
            if pb <= 0:
                continue

            # Stable reference: 10th-percentile. Bounded below by pb, above by
            # the median — immune to extreme-value bias in a way that min()
            # (classic "PB") is not. At ≥10 sessions P10 is a true order stat;
            # at <10 the linear-interpolated quantile gracefully degrades
            # toward min without collapsing onto it.
            ref_p10 = _quantile(sorted_sb, 0.10)
            q1 = _quantile(sorted_sb, 0.25)
            q3 = _quantile(sorted_sb, 0.75)
            iqr = (q3 - q1) if (q1 is not None and q3 is not None) else 0.0

            mean_sb = sum(session_bests) / len(session_bests)
            sd_sb = _stddev(session_bests)

            gaps_ref_pct = [(s - ref_p10) / ref_p10 * 100.0 for s in session_bests]
            mean_gap_ref_pct = sum(gaps_ref_pct) / len(gaps_ref_pct)
            max_gap_ref_pct = max(gaps_ref_pct)
            within_1_ref = sum(1 for s in session_bests if s <= ref_p10 * 1.01) / len(session_bests)
            within_0_5_ref = sum(1 for s in session_bests if s <= ref_p10 * 1.005) / len(session_bests)

            # Legacy PB-based gap (kept for backward compat with old UI)
            gaps_pb_pct = [(s - pb) / pb * 100.0 for s in session_bests]
            mean_gap_pb_pct = sum(gaps_pb_pct) / len(gaps_pb_pct)
            max_gap_pb_pct = max(gaps_pb_pct)
            within_1_pb = sum(1 for s in session_bests if s <= pb * 1.01) / len(session_bests)
            within_0_5_pb = sum(1 for s in session_bests if s <= pb * 1.005) / len(session_bests)

            # Conditions-normalised metric: driver's session best / session's
            # field median. Cancels weather / track temp / wind because they
            # affect the field uniformly.
            rel_paces = [
                secs / session_median_best[sid]
                for sid, secs in rows
                if session_median_best.get(sid)
            ]
            if rel_paces:
                mean_rel = sum(rel_paces) / len(rel_paces)
                sd_rel = _stddev(rel_paces)
                best_rel = min(rel_paces)
                worst_rel = max(rel_paces)
            else:
                mean_rel = sd_rel = best_rel = worst_rel = None

            drivers.append({
                'name': team,
                'sessions': len(session_bests),
                'pb': _format_seconds(pb),
                'pb_seconds': round(pb, 3),
                'reference_p10_seconds': round(ref_p10, 3),
                'reference_p10': _format_seconds(ref_p10),
                'mean_session_best_seconds': round(mean_sb, 3),
                'stddev_session_best_seconds': round(sd_sb, 3),
                'iqr_session_best_seconds': round(iqr, 3),
                # NEW: P10-referenced gap metrics (preferred — no extreme-value bias)
                'mean_gap_to_reference_pct': round(mean_gap_ref_pct, 3),
                'max_gap_to_reference_pct': round(max_gap_ref_pct, 3),
                'pct_within_1pct_reference': round(within_1_ref, 4),
                'pct_within_0_5pct_reference': round(within_0_5_ref, 4),
                # Legacy PB-referenced gap metrics (backward compat; biased for
                # frequent racers — use the reference_p10 versions above)
                'mean_gap_to_pb_pct': round(mean_gap_pb_pct, 3),
                'max_gap_to_pb_pct': round(max_gap_pb_pct, 3),
                'pct_within_1pct_pb': round(within_1_pb, 4),
                'pct_within_0_5pct_pb': round(within_0_5_pb, 4),
                # Conditions-normalised pace (session best / field median)
                'mean_relative_pace': round(mean_rel, 5) if mean_rel is not None else None,
                'stddev_relative_pace': round(sd_rel, 5) if sd_rel is not None else None,
                'best_relative_pace': round(best_rel, 5) if best_rel is not None else None,
                'worst_relative_pace': round(worst_rel, 5) if worst_rel is not None else None,
            })

        # ------------------------------------------------------------------
        # Variance-deficit test (conditions-residualized): does the driver's
        # session-best, AFTER subtracting each session's field-median, cluster
        # tighter than what the fleet's inherent kart variation should allow?
        # ------------------------------------------------------------------
        # Rental-kart fleets have real kart-to-kart variation (≈1–2 s at most
        # venues). Under random kart assignment this variation has to show up
        # in every driver's lap-time series. A driver whose outcomes don't
        # swing as much as the fleet typically does is a candidate for
        # systematically favourable draws.
        #
        # Why residuals, not raw session-bests: track conditions (grip,
        # weather, tyre wear) move the WHOLE field together by seconds. A
        # driver who races in a wider range of conditions would get a larger
        # raw σ even under perfectly random draws — the test would be biased
        # against frequent racers. Subtracting the session median cancels the
        # common-mode shift, leaving only the driver-specific component
        # (kart effect + execution noise). Under H0 that residual variance
        # ≈ σ²_kart + σ²_noise and should be similar for every driver.
        #
        # Null estimator: the MEDIAN across every qualifying driver of their
        # own sample variance of residuals. Robust to a few very consistent
        # or very erratic drivers.
        #
        # Test: (n-1)·s²_obs / σ²_expected ~ χ²(n-1) under H0. One-sided lower
        # tail p. Flag only when ratio < 0.8 AND p < 0.05 AND n ≥ 15.
        MIN_N_VARDEF = 15

        def _residuals(canon):
            res = []
            for sid, sec in per_driver[canon]:
                med = session_median_best.get(sid)
                if med is not None and med > 0:
                    res.append(sec - med)
            return res

        driver_variances = []
        for canon, rows_ in per_driver.items():
            residuals = _residuals(canon)
            if len(residuals) < 3:
                continue
            mean_r = sum(residuals) / len(residuals)
            var_r = sum((r - mean_r) ** 2 for r in residuals) / (len(residuals) - 1)
            if var_r > 0:
                driver_variances.append(var_r)

        if driver_variances:
            sv = sorted(driver_variances)
            expected_variance = sv[len(sv) // 2]  # median
            expected_sd = math.sqrt(expected_variance)
        else:
            expected_variance = None
            expected_sd = None

        for driver_dict in drivers:
            canon = driver_dict['name']
            residuals = _residuals(canon)
            n = len(residuals)
            observed_sd = None
            ratio = None
            p_low = None
            verdict = 'insufficient_data'

            if n >= 3 and expected_variance and expected_variance > 0:
                mean_r = sum(residuals) / n
                observed_var = sum((r - mean_r) ** 2 for r in residuals) / (n - 1)
                observed_sd = math.sqrt(observed_var)
                ratio = observed_sd / expected_sd if expected_sd > 0 else None
                chi_stat = (n - 1) * observed_var / expected_variance
                # One-sided lower-tail p-value: P(X < chi_stat | X ~ χ²(n-1)).
                if chi_stat > 0:
                    upper = _gammainc_upper_reg((n - 1) / 2.0, chi_stat / 2.0)
                    p_low = max(0.0, min(1.0, 1.0 - upper))
                else:
                    p_low = 0.0

                if n >= MIN_N_VARDEF:
                    if ratio is not None and ratio < 0.8 and p_low < 0.05:
                        verdict = 'deficit_flagged'
                    else:
                        verdict = 'consistent'
                else:
                    verdict = 'insufficient_data'

            driver_dict.update({
                'vardef_n_sessions': n,
                'vardef_observed_sd_seconds': round(observed_sd, 3) if observed_sd is not None else None,
                'vardef_expected_sd_seconds': round(expected_sd, 3) if expected_sd is not None else None,
                'vardef_ratio': round(ratio, 3) if ratio is not None else None,
                'vardef_p_value': round(p_low, 5) if p_low is not None else None,
                'vardef_verdict': verdict,
            })

        # Default sort: σRel asc (dispersion of relative pace — the
        # headline metric, immune to both PB-bias and condition drift).
        # Drivers with no σRel (singleton sessions) sink to the bottom.
        drivers.sort(key=lambda d: (
            d['stddev_relative_pace'] if d['stddev_relative_pace'] is not None else float('inf'),
            d['mean_gap_to_reference_pct'],
        ))

        return jsonify({
            'track_id': track_id,
            'track_name': track_row['track_name'],
            'min_sessions_threshold': min_sessions,
            'min_sessions_verdict': MIN_SESSIONS_VERDICT,
            'layout_id': layout_id,
            'window_months': window_months,
            'filter_min_field_best': min_field_best,
            'filter_max_field_best': max_field_best,
            'sessions_included': len(per_session_bests),
            'driver_count': len(drivers),
            'drivers': drivers,
        })

    except Exception as e:
        app.logger.exception("track kart fairness endpoint failed")
        return _internal_error(e)

