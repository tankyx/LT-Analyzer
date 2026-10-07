#!/usr/bin/env python3
"""Track-wide kart-draw fairness report.

For every driver at a track, aggregate the sprint kart assignments ("draws")
they received and test whether they got better karts than random assignment
would predict.

Method (mirrors ``/api/driver/fairness`` but computed for ALL drivers at once):

  * A *draw* is one ``(driver, kart)`` pair inside a **sprint** session — a
    session where the same driver used more than one kart, i.e. karts are
    rotated/drawn between heats.
  * Each kart is ranked by its best lap in that session. Under random
    assignment the rank percentile ``(rank - 0.5) / K`` is Uniform(0, 1), so a
    driver's mean percentile is 0.5 and the top-quartile hit rate matches the
    per-session Poisson-binomial expectation (``threshold / K``).
  * We report the driver's mean percentile (lower = better karts = favored),
    the top/bottom-quartile counts vs expectation, a two-sided z-test on the
    mean, and a one-sided top-quartile p-value (the product's headline test).
  * Benjamini-Hochberg FDR across all drivers controls for the fact that a
    track can have thousands of drivers (some will look lucky by chance).

Usage::

    python scripts/kart_draw_fairness.py --track-id 42
    python scripts/kart_draw_fairness.py --track-id 2 --window-months 0 --min-draws 10
"""
from __future__ import annotations

import argparse
import math
import os
import sqlite3
import sys
from collections import defaultdict

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from race_ui import (  # noqa: E402
    _analyze_sprint_session,
    _chi2_sf,
    _filter_sessions_by_layout_and_window,
    _is_test_placeholder,
    _normal_cdf,
    _safe_parse_time,
    _stddev,
    _strip_driver_class_prefix,
    _window_cutoff,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def load_alias_map(auth_db: str) -> dict:
    """alias/canonical (lowercased) -> canonical name."""
    alias_map: dict = {}
    try:
        with sqlite3.connect(auth_db) as conn:
            for canon, alias in conn.execute(
                'SELECT canonical_name, alias_name FROM driver_aliases'
            ):
                if canon:
                    alias_map[canon.lower()] = canon
                if alias:
                    alias_map[alias.lower()] = canon
    except sqlite3.Error:
        pass
    return alias_map


def canonical_of(name: str, alias_map: dict) -> str:
    stripped = _strip_driver_class_prefix(name)
    return alias_map.get(stripped.lower(), stripped)


def find_sprint_pairs(cur) -> set:
    """All (session_id, team_name) where the team used >1 distinct kart."""
    pairs = set()
    for table in ('lap_times', 'lap_history'):
        cur.execute(
            f"""
            SELECT session_id, team_name
              FROM {table}
             WHERE team_name IS NOT NULL AND team_name != ''
               AND kart_number IS NOT NULL
             GROUP BY session_id, team_name
            HAVING COUNT(DISTINCT kart_number) > 1
            """
        )
        pairs.update((sid, team) for sid, team in cur.fetchall())
    return pairs


def analyze_skill_controlled(session_data, driver, session_id):
    """Kart-draw samples with the target driver's own laps removed from each
    kart's quality, so a fast driver cannot inflate the karts he is ranked on.

    For every kart in the session we score it by the best lap of the OTHER
    teams (for karts the driver sat in) or by anyone (for karts he did not).
    The driver's assigned karts are then ranked within that skill-free pool.
    """
    if not session_data:
        return []
    tk = session_data['tk']
    by_kart = session_data['by_kart']
    all_best = session_data['all_best']
    median_all = session_data['median_all']
    if not tk or median_all <= 0:
        return []

    driver_karts = {k for (t, k) in tk if t == driver}
    if len(driver_karts) < 2:
        return []

    pool = {}
    for k in all_best:
        if k in driver_karts:
            others = [b for (b, t) in by_kart[k] if t != driver]
            pool[k] = min(others) if others else all_best[k]
        else:
            pool[k] = all_best[k]
    if len(pool) < 3:
        return []

    ranked = sorted(pool.items(), key=lambda kv: kv[1])
    rank_of = {k: i + 1 for i, (k, _) in enumerate(ranked)}
    n = len(ranked)

    samples = []
    for k in driver_karts:
        quality = pool[k]
        samples.append({
            'session_id': session_id,
            'kart_number': k,
            'kart_best_seconds': round(quality, 3),
            'session_median_seconds': round(median_all, 3),
            'kart_factor': round(quality / median_all, 5),
            'kart_rank': rank_of[k],
            'karts_in_session': n,
            'rank_percentile': round((rank_of[k] - 0.5) / n, 6),
        })
    return samples


def summarize(samples: list) -> dict:
    """Aggregate one driver's kart-draw samples (same math as the endpoint).

    Two tests are produced:
      * draw-level z  -- every (driver,kart) treated as independent (mirrors
        the /api/driver/fairness endpoint; over-states power when a driver's
        draws concentrate in one session).
      * session-level z -- average percentile per session first, then a z-test
        across sessions. This is the primary, cluster-robust result because
        draws inside one session share the same field and day conditions.
    """
    n = len(samples)
    percentiles = [s['rank_percentile'] for s in samples]
    factors = [s['kart_factor'] for s in samples]

    # Session-clustered: one mean percentile per session.
    per_session: dict = defaultdict(list)
    for s in samples:
        per_session[s['session_id']].append(s['rank_percentile'])
    session_means = [sum(v) / len(v) for v in per_session.values()]
    m = len(session_means)
    cluster_z = cluster_p = None
    if m >= 2:
        grand = sum(session_means) / m
        sd_sess = _stddev(session_means)
        if sd_sess > 0:
            cluster_z = (grand - 0.5) / (sd_sess / math.sqrt(m))
            cluster_p = 2.0 * (1.0 - _normal_cdf(abs(cluster_z)))

    top_obs = bottom_obs = 0
    top_exp = bottom_exp = 0.0
    top_var = bottom_var = 0.0
    quartiles = [0, 0, 0, 0]
    for s in samples:
        k = s['karts_in_session']
        thr = max(1, k // 4)
        p_top = thr / k
        top_exp += p_top
        top_var += p_top * (1.0 - p_top)
        if s['kart_rank'] <= thr:
            top_obs += 1
        # bottom quartile = the slowest thr karts
        p_bottom = thr / k
        bottom_exp += p_bottom
        bottom_var += p_bottom * (1.0 - p_bottom)
        if s['kart_rank'] > k - thr:
            bottom_obs += 1
        quartiles[min(3, int(s['rank_percentile'] * 4))] += 1

    mean_pct = sum(percentiles) / n
    sd_pct = _stddev(percentiles)
    se = sd_pct / math.sqrt(n) if n > 1 and sd_pct > 0 else None
    z_mean = (mean_pct - 0.5) / se if se else None
    p_mean = 2.0 * (1.0 - _normal_cdf(abs(z_mean))) if z_mean is not None else None

    p_top = None
    if top_var > 0:
        z = (top_obs - 0.5 - top_exp) / math.sqrt(top_var)
        p_top = 1.0 - _normal_cdf(z)
    p_bottom = None
    if bottom_var > 0:
        z = (bottom_obs - 0.5 - bottom_exp) / math.sqrt(bottom_var)
        p_bottom = 1.0 - _normal_cdf(z)

    exp_per_q = n / 4.0
    chi2 = sum((o - exp_per_q) ** 2 / exp_per_q for o in quartiles) if exp_per_q else 0.0

    return {
        'draws': n,
        'sessions': m,
        'mean_percentile': mean_pct,
        'mean_factor': sum(factors) / n,
        'cluster_z': cluster_z,
        'cluster_p': cluster_p,
        'top_obs': top_obs,
        'top_exp': top_exp,
        'bottom_obs': bottom_obs,
        'bottom_exp': bottom_exp,
        'quartiles': quartiles,
        'z_mean': z_mean,
        'p_mean': p_mean,
        'p_top': p_top,
        'p_bottom': p_bottom,
        'chi2': chi2,
        'chi2_p': _chi2_sf(chi2, 3),
    }


def bh_fdr(pvalues: list) -> list:
    """Benjamini-Hochberg adjusted q-values, aligned with the input order."""
    m = len(pvalues)
    if m == 0:
        return []
    indexed = sorted(
        ((p, i) for i, p in enumerate(pvalues) if p is not None),
        key=lambda t: t[0],
    )
    q = [None] * m
    prev = 1.0
    for rank_from_end, (p, i) in enumerate(reversed(indexed), start=1):
        rank = len(indexed) - rank_from_end + 1
        val = min(prev, p * len(indexed) / rank)
        q[i] = val
        prev = val
    return q


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--track-id', type=int, required=True)
    ap.add_argument('--window-months', type=int, default=12,
                    help='rolling window in months; 0 = all time (default 12)')
    ap.add_argument('--layout-id', type=int, default=None)
    ap.add_argument('--min-draws', type=int, default=5,
                    help='minimum kart draws to include a driver (default 5)')
    ap.add_argument('--min-sessions', type=int, default=3,
                    help='minimum sessions with draws to include a driver (default 3)')
    ap.add_argument('--top', type=int, default=25, help='rows per table (default 25)')
    ap.add_argument('--names', default=None,
                    help='comma-separated driver names; print a focused table for just these')
    ap.add_argument('--skill-controlled', action='store_true',
                    help='rank karts by OTHER drivers\' best laps (removes the driver-skill confound)')
    ap.add_argument('--alpha', type=float, default=0.05, help='FDR threshold (default 0.05)')
    ap.add_argument('--max-factor', type=float, default=1.5,
                    help='drop draws whose kart_factor exceeds this (data artefact; default 1.5)')
    ap.add_argument('--min-factor', type=float, default=0.5,
                    help='drop draws whose kart_factor is below this (data artefact; default 0.5)')
    args = ap.parse_args()

    db_path = os.path.join(ROOT, f'race_data_track_{args.track_id}.db')
    if not os.path.exists(db_path):
        print(f'No database at {db_path}', file=sys.stderr)
        return 2

    # Track name for the header
    track_name = f'track {args.track_id}'
    try:
        with sqlite3.connect(os.path.join(ROOT, 'tracks.db')) as tconn:
            row = tconn.execute('SELECT track_name FROM tracks WHERE id=?',
                                (args.track_id,)).fetchone()
            if row:
                track_name = row[0]
    except sqlite3.Error:
        pass

    alias_map = load_alias_map(os.path.join(ROOT, 'auth.db'))
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()

    session_date = dict(cur.execute('SELECT session_id, start_time FROM race_sessions'))

    cutoff = _window_cutoff(args.window_months)
    allowed = _filter_sessions_by_layout_and_window(conn, args.layout_id, cutoff)

    pairs = find_sprint_pairs(cur)
    if allowed is not None:
        pairs = {(sid, team) for sid, team in pairs if sid in allowed}

    # Skill-controlled mode preloads per-session (team,kart) bests so we can
    # score each kart with the target driver's own laps excluded.
    session_data = {}
    if args.skill_controlled:
        for sid in {s for s, _ in pairs}:
            cur.execute(
                """SELECT team_name, kart_number, best_lap FROM lap_times
                    WHERE session_id=? AND team_name IS NOT NULL AND team_name != ''
                      AND kart_number IS NOT NULL AND best_lap IS NOT NULL AND best_lap != ''""",
                (sid,),
            )
            tk = {}
            for team, kart, bl in cur.fetchall():
                secs = _safe_parse_time(bl)
                if secs == float('inf') or secs < 20 or secs > 600:
                    continue
                key = (team, kart)
                if key not in tk or secs < tk[key]:
                    tk[key] = secs
            by_kart: dict = defaultdict(list)
            for (team, kart), v in tk.items():
                by_kart[kart].append((v, team))
            all_best = {k: min(v for v, _ in lst) for k, lst in by_kart.items()}
            vals = sorted(all_best.values())
            median_all = vals[len(vals) // 2] if vals else 0.0
            session_data[sid] = {'tk': tk, 'by_kart': by_kart,
                                 'all_best': all_best, 'median_all': median_all}

    samples_by_driver: dict = defaultdict(list)
    display_name: dict = {}
    skipped_placeholder = 0
    dropped_implausible = 0
    for sid, team in pairs:
        if _is_test_placeholder(_strip_driver_class_prefix(team)):
            skipped_placeholder += 1
            continue
        if args.skill_controlled:
            samples = analyze_skill_controlled(session_data.get(sid), team, sid)
        else:
            samples = _analyze_sprint_session(cur, sid, session_date.get(sid), [team], [team])
        if not samples:
            continue
        # A real kart on a given layout is within a few percent of the field
        # median. A "best lap" several times the median is a pit/out lap or a
        # timing glitch, not a kart — drop those draws so one bad row cannot
        # manufacture a false 'disadvantaged' driver.
        good = [s for s in samples
                if args.min_factor <= s['kart_factor'] <= args.max_factor]
        dropped_implausible += len(samples) - len(good)
        if good:
            # Merge name variants that are the same tokens in a different order
            # ("DELVENNE Simon" vs "Simon Delvenne") onto one canonical key.
            canon = canonical_of(team, alias_map)
            key = tuple(sorted(canon.lower().split())) or (canon.lower(),)
            display_name.setdefault(key, canon)
            samples_by_driver[key].extend(good)

    conn.close()

    rows = []
    for key, samples in samples_by_driver.items():
        if len(samples) < args.min_draws:
            continue
        if len({s['session_id'] for s in samples}) < args.min_sessions:
            continue
        summary = summarize(samples)
        summary['driver'] = display_name.get(key, ' '.join(key))
        rows.append(summary)

    if not rows:
        print(f'No sprint kart draws found for {track_name} (track {args.track_id}).')
        return 0

    # FDR control across drivers. Primary test = session-clustered z.
    for key, qkey in (('cluster_p', 'q_cluster'), ('p_mean', 'q_mean'),
                      ('p_top', 'q_top'), ('p_bottom', 'q_bottom')):
        qvals = bh_fdr([r[key] for r in rows])
        for r, q in zip(rows, qvals):
            r[qkey] = q

    rows.sort(key=lambda r: r['mean_percentile'])

    print('=' * 104)
    print(f'KART-DRAW FAIRNESS — {track_name} (track {args.track_id})')
    print(f'window: {args.window_months} months  |  sprint draws: {sum(r["draws"] for r in rows)}  '
          f'|  drivers with >= {args.min_draws} draws over >= {args.min_sessions} sessions: {len(rows)}')
    print(f'{len(pairs)} sprint (session,team) pairs; {skipped_placeholder} test-placeholder pairs skipped; '
          f'{dropped_implausible} implausible draws dropped (factor outside '
          f'[{args.min_factor}, {args.max_factor}])')
    print('=' * 104)
    print('mean%ile = average kart rank percentile (0.5 = random, <0.5 = better karts).')
    print('z_cluster = session-clustered z (primary, cluster-robust); z>0 draws worse, z<0 better.')
    print('q_cluster = BH-FDR adjusted p for z_cluster. topQ = top-quartile hits obs/expected.')
    print()

    header = (f'{"driver":<30} {"sess":>4} {"draws":>5} {"mean%ile":>8} {"factor":>7} '
              f'{"z_cluster":>9} {"q_cluster":>9} {"topQ o/e":>10} {"z_draw":>7} {"q_top":>8}')
    print(header)
    print('-' * len(header))

    def _fmt(r):
        return (f'{r["driver"][:30]:<30} {r["sessions"]:>4} {r["draws"]:>5} '
                f'{r["mean_percentile"]:>8.3f} {r["mean_factor"]:>7.4f} '
                f'{(r["cluster_z"] if r["cluster_z"] is not None else float("nan")):>9.2f} '
                f'{(r["q_cluster"] if r["q_cluster"] is not None else float("nan")):>9.2e} '
                f'{r["top_obs"]:>4}/{r["top_exp"]:<5.1f} '
                f'{(r["z_mean"] if r["z_mean"] is not None else float("nan")):>7.2f} '
                f'{(r["q_top"] if r["q_top"] is not None else float("nan")):>8.2e}')

    if args.names:
        wanted = [n.strip().lower().split() for n in args.names.split(',') if n.strip()]
        selected = [r for r in rows
                    if any(all(tok in r['driver'].lower() for tok in toks) for toks in wanted)]
        print(f'FOCUSED DRIVERS — {track_name} (track {args.track_id})')
        print('-' * len(header))
        print(header)
        print('-' * len(header))
        if selected:
            for r in selected:
                print(_fmt(r))
        else:
            for toks in wanted:
                print(f'  (no qualifying kart-draw data for "{" ".join(toks)}")')
        print()

    print(f'MOST FAVORED (drawing the best karts), top {args.top}')
    print('-' * len(header))
    for r in rows[:args.top]:
        print(_fmt(r))

    print()
    print(f'MOST DISADVANTAGED (drawing the worst karts), top {args.top}')
    print('-' * len(header))
    for r in rows[-args.top:][::-1]:
        print(_fmt(r))

    sig_favored = [r for r in rows if r['cluster_z'] is not None and r['cluster_z'] < 0
                   and r['q_cluster'] is not None and r['q_cluster'] < args.alpha]
    sig_worse = [r for r in rows if r['cluster_z'] is not None and r['cluster_z'] > 0
                 and r['q_cluster'] is not None and r['q_cluster'] < args.alpha]
    print()
    print('=' * 104)
    print(f'SIGNIFICANT AFTER BH-FDR (q_cluster < {args.alpha})')
    print(f'  favored (better-than-random karts):   {len(sig_favored)} drivers')
    print(f'  disadvantaged (worse-than-random):    {len(sig_worse)} drivers')
    if sig_favored:
        print('  favored: ' + ', '.join(f'{r["driver"]} ({r["sessions"]}s/{r["draws"]}d, {r["mean_percentile"]:.2f})'
                                       for r in sig_favored[:40]))
    if sig_worse:
        print('  disadvantaged: ' + ', '.join(f'{r["driver"]} ({r["sessions"]}s/{r["draws"]}d, {r["mean_percentile"]:.2f})'
                                           for r in sig_worse[:40]))
    print()
    print('CAVEATS:')
    print('  * verdicts are only powerful with many sessions; this report requires >= %d.' % args.min_sessions)
    print('  * common first names (THOMAS, HUGO...) may merge distinct people; aliases are only')
    print('    merged through auth.db driver_aliases + HC/JR/G class prefixes.')
    print('  * a kart-rotation EVENT is one shared draw; drivers in it are not independent.')
    print('    Treat this as a screening / QA tool, not proof of deliberate favouritism.')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
