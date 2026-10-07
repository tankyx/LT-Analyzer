#!/usr/bin/env python3
"""Two-way (driver + kart) effects model for kart-draw fairness.

The raw kart-draw metric ranks a kart by the best lap *anyone* set on it, so a
fast driver makes his own karts look fast — a skill confound. This script fits,
per session, the additive model ::

    log(lap_seconds) = mu + driver_effect + kart_effect + noise

by alternating least squares. Because a driver's own pace is absorbed by
``driver_effect``, ``kart_effect`` is a skill-free estimate of how good each
physical kart was in that session. We then:

  * aggregate ``kart_effect`` by kart number across sessions -> a **kart-quality
    table** (are specific karts consistently fast/slow?), and
  * average each driver's ``kart_effect`` over the karts they drew -> a
    **favored-driver table** (does someone draw good karts more than chance?),
    tested with a session-clustered z and Benjamini-Hochberg FDR.

Identifiability: within a session we keep only karts driven by >= 2 different
drivers (a kart driven by one person cannot be separated from that person), and
require a connected driver/kart graph. Karts are centred per session, so under
random assignment a driver's mean kart effect is ~0.

Usage::

    python scripts/kart_quality_twoway.py --track-id 10
    python scripts/kart_quality_twoway.py --track-id 6 --names "Delvenne,Ghidi,Boileau"
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
    LAP_MAX_SECONDS,
    LAP_MIN_SECONDS,
    _is_test_placeholder,
    _normal_cdf,
    _safe_parse_time,
    _stddev,
    _strip_driver_class_prefix,
    _window_cutoff,
)


# ---------------------------------------------------------------------------
# Two-way fit
# ---------------------------------------------------------------------------

def _connected_component(edges):
    """Indices of the largest connected component of a bipartite graph.

    `edges` is a list of (driver_index, kart_index). Drivers are 0..D-1 and
    karts are offset by D. Returns the set of edge indices in the largest
    component (by number of edges), so the additive model is identifiable.
    """
    parent: dict = {}

    def find(x):
        parent.setdefault(x, x)
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a, b):
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[ra] = rb

    for d, k in edges:
        union(('d', d), ('k', k))

    groups = defaultdict(list)
    for i, (d, k) in enumerate(edges):
        groups[find(('d', d))].append(i)
    if not groups:
        return set()
    return set(max(groups.values(), key=len))


def fit_two_way(obs, max_iter=200, tol=1e-9):
    """Fit log(secs) = mu + a_driver + b_kart via alternating least squares.

    `obs` is a list of (driver, kart, log_seconds). Returns (a, b) dicts; b is
    centred so that its observation-weighted mean is 0.
    """
    drivers = sorted({d for d, k, y in obs})
    karts = sorted({k for d, k, y in obs})
    if len(drivers) < 2 or len(karts) < 2:
        return None
    di = {d: i for i, d in enumerate(drivers)}
    ki = {k: i for i, k in enumerate(karts)}
    edges = [(di[d], ki[k]) for d, k, y in obs]
    keep = _connected_component(edges)
    if len(keep) < 3:
        return None
    obs = [obs[i] for i in keep]

    mu = sum(y for _, _, y in obs) / len(obs)
    d_set = {d for d, k, y in obs}
    k_set = {k for d, k, y in obs}
    a = {d: 0.0 for d in d_set}
    b = {k: 0.0 for k in k_set}
    for _ in range(max_iter):
        prev_b = dict(b)
        num_d, cnt_d = defaultdict(float), defaultdict(int)
        for d, k, y in obs:
            num_d[d] += y - mu - b[k]
            cnt_d[d] += 1
        a = {d: num_d[d] / cnt_d[d] for d in cnt_d}
        num_k, cnt_k = defaultdict(float), defaultdict(int)
        for d, k, y in obs:
            num_k[k] += y - mu - a[d]
            cnt_k[k] += 1
        b = {k: num_k[k] / cnt_k[k] for k in cnt_k}
        if max((abs(b[k] - prev_b.get(k, 0.0)) for k in b), default=0.0) < tol:
            break

    # Centre b on the observation-weighted mean so random draws average to ~0.
    mean_b = sum(b[k] for d, k, y in obs) / len(obs)
    b = {k: v - mean_b for k, v in b.items()}
    # Do not centre a: it stays relative to b (only b is used for favouritism).
    return a, b


# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------

def load_draws(db_path, window_months=0):
    """Return {session_id: [(driver, kart, log_secs), ...]} plus session dates."""
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    session_date = dict(cur.execute('SELECT session_id, start_time FROM race_sessions'))
    cutoff = _window_cutoff(window_months)
    allowed = None
    if cutoff is not None:
        allowed = {r[0] for r in cur.execute(
            'SELECT session_id FROM race_sessions WHERE start_time >= ?', (cutoff,))}

    best = {}  # (sid, driver, kart) -> seconds
    cur.execute(
        """SELECT session_id, team_name, kart_number, best_lap FROM lap_times
            WHERE best_lap IS NOT NULL AND best_lap != ''
              AND team_name IS NOT NULL AND team_name != ''
              AND kart_number IS NOT NULL"""
    )
    for sid, team, kart, bl in cur:
        if allowed is not None and sid not in allowed:
            continue
        secs = _safe_parse_time(bl)
        if secs == float('inf') or secs < LAP_MIN_SECONDS or secs > LAP_MAX_SECONDS:
            continue
        key = (sid, team, kart)
        if key not in best or secs < best[key]:
            best[key] = secs
    conn.close()

    by_session = defaultdict(list)
    for (sid, team, kart), secs in best.items():
        if _is_test_placeholder(_strip_driver_class_prefix(team)):
            continue
        by_session[sid].append((team, kart, math.log(secs)))
    return by_session, session_date


# ---------------------------------------------------------------------------
# Stats helpers
# ---------------------------------------------------------------------------

def bh_fdr(pvalues):
    m = len(pvalues)
    indexed = sorted(((p, i) for i, p in enumerate(pvalues) if p is not None), key=lambda t: t[0])
    q = [None] * m
    prev = 1.0
    for rank_from_end, (p, i) in enumerate(reversed(indexed), start=1):
        rank = len(indexed) - rank_from_end + 1
        val = min(prev, p * len(indexed) / rank)
        q[i] = val
        prev = val
    return q


def normal_p(z):
    return 2.0 * (1.0 - _normal_cdf(abs(z)))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--track-id', type=int, required=True)
    ap.add_argument('--window-months', type=int, default=0, help='0 = all time')
    ap.add_argument('--names', default=None, help='comma-separated drivers for a focused table')
    ap.add_argument('--top', type=int, default=20)
    ap.add_argument('--min-draws', type=int, default=4)
    ap.add_argument('--min-sessions', type=int, default=2)
    ap.add_argument('--all', action='store_true',
                    help='print the full driver table (no top/bottom truncation)')
    args = ap.parse_args()

    db_path = os.path.join(ROOT, f'race_data_track_{args.track_id}.db')
    if not os.path.exists(db_path):
        print(f'No database at {db_path}', file=sys.stderr)
        return 2
    track_name = f'track {args.track_id}'
    try:
        with sqlite3.connect(os.path.join(ROOT, 'tracks.db')) as tc:
            row = tc.execute('SELECT track_name FROM tracks WHERE id=?', (args.track_id,)).fetchone()
            if row:
                track_name = row[0]
    except sqlite3.Error:
        pass

    by_session, session_date = load_draws(db_path, args.window_months)

    # Fit each session; collect kart effects and per-driver per-session effects.
    kart_effects = defaultdict(list)             # kart_number -> [b, ...] (one per session)
    driver_session_effects = defaultdict(lambda: defaultdict(list))  # key -> sid -> [b,...]
    display_name: dict = {}
    n_sessions_modelled = 0
    n_obs = 0
    for sid, obs in by_session.items():
        # Identifiability: keep karts driven by >= 2 drivers.
        by_kart = defaultdict(set)
        for d, k, y in obs:
            by_kart[k].add(d)
        good_karts = {k for k, ds in by_kart.items() if len(ds) >= 2}
        obs = [(d, k, y) for d, k, y in obs if k in good_karts]
        if len(obs) < 4:
            continue
        fit = fit_two_way(obs)
        if not fit:
            continue
        a, b = fit
        n_sessions_modelled += 1
        n_obs += len(obs)
        for k, v in b.items():
            kart_effects[k].append(v)
        for d, k, y in obs:
            if k not in b:
                continue  # observation sits outside the identified component
            canon = _strip_driver_class_prefix(d)
            key = tuple(sorted(canon.lower().split())) or (canon.lower(),)
            display_name.setdefault(key, canon)
            driver_session_effects[key][sid].append(b[k])

    print('=' * 96)
    print(f'TWO-WAY DRIVER/KART MODEL — {track_name} (track {args.track_id})')
    print(f'sessions modelled: {n_sessions_modelled} | observations: {n_obs} | '
          f'karts: {len(kart_effects)} | drivers: {len(driver_session_effects)}')
    print('=' * 96)
    print('kart_effect is in log-seconds, skill-adjusted & session-centred:')
    print('  negative = consistently FAST kart, positive = SLOW kart.')
    print()

    # ---- Kart-quality table -------------------------------------------------
    kart_rows = []
    for k, vals in kart_effects.items():
        if len(vals) < 2:
            continue
        kart_rows.append({
            'kart': k,
            'sessions': len(vals),
            'mean_b': sum(vals) / len(vals),
            'sd': _stddev(vals),
        })
    kart_rows.sort(key=lambda r: r['mean_b'])
    print(f'--- KART QUALITY (karts seen in >= 2 modelled sessions), {len(kart_rows)} karts ---')
    print(f'{"kart":>5} {"sessions":>8} {"mean_b":>10} {"sd":>9} {"se":>9}  verdict')
    print('-' * 60)
    for r in kart_rows:
        se = r['sd'] / math.sqrt(r['sessions']) if r['sessions'] > 1 else float('nan')
        verdict = ''
        if r['mean_b'] < -0.01:
            verdict = 'fast'
        if r['mean_b'] > 0.01:
            verdict = 'slow'
        print(f'{r["kart"]:>5} {r["sessions"]:>8} {r["mean_b"]:>10.4f} {r["sd"]:>9.4f} {se:>9.4f}  {verdict}')

    # ---- Driver favouritism table ------------------------------------------
    rows = []
    for key, per_sess in driver_session_effects.items():
        draws = [v for vals in per_sess.values() for v in vals]
        n = len(draws)
        if n < args.min_draws or len(per_sess) < args.min_sessions:
            continue
        sess_means = [sum(v) / len(v) for v in per_sess.values()]
        m = len(sess_means)
        mean_b = sum(draws) / n
        cluster_z = cluster_p = None
        if m >= 2:
            sd = _stddev(sess_means)
            if sd > 0:
                cluster_z = mean_b / (sd / math.sqrt(m))
                cluster_p = normal_p(cluster_z)
        rows.append({'driver': display_name.get(key, ' '.join(key)), 'draws': n,
                     'sessions': m, 'mean_b': mean_b,
                     'cluster_z': cluster_z, 'cluster_p': cluster_p})

    for key, qkey in (('cluster_p', 'q'),):
        qvals = bh_fdr([r[key] for r in rows])
        for r, q in zip(rows, qvals):
            r[qkey] = q
    rows.sort(key=lambda r: r['mean_b'])

    print()
    print(f'--- DRIVER FAVOURITISM (>= {args.min_draws} draws over >= {args.min_sessions} '
          f'sessions), {len(rows)} drivers ---')
    print(f'{"driver":<30} {"sess":>4} {"draws":>5} {"mean_b":>9} {"z":>8} {"q":>9}')
    print('-' * 72)

    def _fmt(r):
        z = r['cluster_z'] if r['cluster_z'] is not None else float('nan')
        q = r['q'] if r['q'] is not None else float('nan')
        return f'{r["driver"][:30]:<30} {r["sessions"]:>4} {r["draws"]:>5} {r["mean_b"]:>9.4f} {z:>8.2f} {q:>9.2e}'

    favoured = [r for r in rows if r['mean_b'] < 0 and (r['q'] or 1) < 0.05]
    disfavoured = [r for r in rows if r['mean_b'] > 0 and (r['q'] or 1) < 0.05]
    if args.all:
        print(f'ALL DRIVERS sorted by mean kart effect (most favoured first), {len(rows)} rows')
        for r in rows:
            print(_fmt(r))
    else:
        print(f'MOST FAVOURED (best karts), top {args.top}')
        for r in rows[:args.top]:
            print(_fmt(r))
        print()
        print(f'MOST DISFAVOURED (worst karts), top {args.top}')
        for r in rows[-args.top:][::-1]:
            print(_fmt(r))

    if args.names:
        wanted = [n.strip().lower().split() for n in args.names.split(',') if n.strip()]
        print()
        print('FOCUSED:')
        print('-' * 72)
        for toks in wanted:
            match = [r for r in rows if all(t in r['driver'].lower() for t in toks)]
            if not match:
                print(f'  (no data for "{" ".join(toks)}")')
            for r in match:
                print('  ' + _fmt(r))

    print()
    print(f'significant after FDR q<0.05: favoured {len(favoured)}, disfavoured {len(disfavoured)}')
    if favoured:
        print('  favoured: ' + ', '.join(f'{r["driver"]} ({r["sessions"]}s/{r["draws"]}d, b={r["mean_b"]:+.4f})' for r in favoured[:30]))
    if disfavoured:
        print('  disfavoured: ' + ', '.join(f'{r["driver"]} ({r["sessions"]}s/{r["draws"]}d, b={r["mean_b"]:+.4f})' for r in disfavoured[:30]))
    print()
    print('NOTE: two-way b/kart/kg remove driver skill *within a session*, but karts are only')
    print('      comparable when driven by overlapping sets of drivers; small samples stay noisy.')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
