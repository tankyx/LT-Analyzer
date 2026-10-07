#!/usr/bin/env python3
"""Kart-quality table by kart number (driver-independent), plus draw report.

The two-way driver/kart model needs each kart to be shared between several
drivers within a session. On tracks where every driver uses only 2 karts and
overlaps are sparse (e.g. Eupen) the graph fragments and kart effects are not
identified. This script uses a more robust, structure-agnostic measure:

  * For every session, rank each kart by its best lap (by anyone) and turn it
    into a within-session percentile (0 = fastest kart, 1 = slowest).
  * Aggregate that percentile **by kart number** across all sessions. If a kart
    number is consistently at a low percentile over many sessions with
    different drivers, it is a genuinely fast kart (not a driver artefact).
  * For a driver, score each kart they drew by the best lap of the OTHER
    drivers on it (skill-free), convert to a within-session percentile, and
    aggregate. This answers "does this driver draw good karts more than chance?"

Usage::

    python scripts/kart_quality_table.py --track-id 10 --names "Delvenne,Ghidi,Boileau"
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


def bh_fdr(pvalues):
    indexed = sorted(((p, i) for i, p in enumerate(pvalues) if p is not None), key=lambda t: t[0])
    q = [None] * len(pvalues)
    prev = 1.0
    for rank_from_end, (p, i) in enumerate(reversed(indexed), start=1):
        rank = len(indexed) - rank_from_end + 1
        val = min(prev, p * len(indexed) / rank)
        q[i] = val
        prev = val
    return q


def load_sessions(db_path, window_months):
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    dates = dict(cur.execute('SELECT session_id, start_time FROM race_sessions'))
    cutoff = _window_cutoff(window_months)
    allowed = None
    if cutoff is not None:
        allowed = {r[0] for r in cur.execute(
            'SELECT session_id FROM race_sessions WHERE start_time >= ?', (cutoff,))}

    tk = {}  # (sid, team, kart) -> secs
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
        if key not in tk or secs < tk[key]:
            tk[key] = secs
    conn.close()

    by_session = defaultdict(dict)        # sid -> {(team, kart): secs}
    for (sid, team, kart), secs in tk.items():
        if _is_test_placeholder(_strip_driver_class_prefix(team)):
            continue
        by_session[sid][(team, kart)] = secs
    return by_session, dates


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--track-id', type=int, required=True)
    ap.add_argument('--window-months', type=int, default=0)
    ap.add_argument('--names', default=None)
    ap.add_argument('--top', type=int, default=15, help='kart rows to show at each end')
    ap.add_argument('--min-kart-sessions', type=int, default=3,
                    help='min sessions a kart number must appear in for the table')
    args = ap.parse_args()

    db_path = os.path.join(ROOT, f'race_data_track_{args.track_id}.db')
    track_name = f'track {args.track_id}'
    try:
        with sqlite3.connect(os.path.join(ROOT, 'tracks.db')) as tc:
            row = tc.execute('SELECT track_name FROM tracks WHERE id=?', (args.track_id,)).fetchone()
            if row:
                track_name = row[0]
    except sqlite3.Error:
        pass

    by_session, dates = load_sessions(db_path, args.window_months)

    # ---- Kart-quality table by kart number ---------------------------------
    kart_pct = defaultdict(list)          # kart -> [within-session pct, ...]
    kart_sessions = 0
    for sid, pairs in by_session.items():
        kart_best = {}
        for (team, kart), secs in pairs.items():
            if kart not in kart_best or secs < kart_best[kart]:
                kart_best[kart] = secs
        if len(kart_best) < 3:
            continue
        kart_sessions += 1
        ordered = sorted(kart_best.items(), key=lambda kv: kv[1])
        n = len(ordered)
        for i, (kart, _) in enumerate(ordered):
            kart_pct[kart].append((i + 0.5) / n)

    kart_rows = []
    for kart, pcts in kart_pct.items():
        if len(pcts) < args.min_kart_sessions:
            continue
        mean_pct = sum(pcts) / len(pcts)
        sd = _stddev(pcts)
        se = sd / math.sqrt(len(pcts)) if len(pcts) > 1 and sd > 0 else None
        z = (mean_pct - 0.5) / se if se else None
        kart_rows.append({'kart': kart, 'n': len(pcts), 'mean_pct': mean_pct,
                          'z': z, 'fast_q': sum(1 for p in pcts if p < 0.25) / len(pcts),
                          'slow_q': sum(1 for p in pcts if p > 0.75) / len(pcts)})
    kart_rows.sort(key=lambda r: r['mean_pct'])
    kq = {r['kart']: r for r in kart_rows}

    # ---- Driver report (others-best, skill-free) ---------------------------
    driver_draws = defaultdict(list)      # key -> [(sid, kart, pct), ...]
    display = {}
    for sid, pairs in by_session.items():
        # kart -> list of (secs, team); and kart -> all-driver best
        by_kart = defaultdict(list)
        for (team, kart), secs in pairs.items():
            by_kart[kart].append((secs, team))
        if len(by_kart) < 3:
            continue
        # driver -> karts
        driver_karts = defaultdict(set)
        for (team, kart) in pairs:
            driver_karts[team].add(kart)
        for team, karts in driver_karts.items():
            if len(karts) < 2:
                continue  # not a kart-draw event for this driver
            pool = {}
            for kart in by_kart:
                if kart in karts:
                    others = [s for s, t in by_kart[kart] if t != team]
                    pool[kart] = min(others) if others else min(s for s, _ in by_kart[kart])
                else:
                    pool[kart] = min(s for s, _ in by_kart[kart])
            ordered = sorted(pool.items(), key=lambda kv: kv[1])
            n = len(ordered)
            rank = {k: i + 1 for i, (k, _) in enumerate(ordered)}
            canon = _strip_driver_class_prefix(team)
            key = tuple(sorted(canon.lower().split())) or (canon.lower(),)
            display.setdefault(key, canon)
            for kart in karts:
                driver_draws[key].append((sid, kart, (rank[kart] - 0.5) / n))

    driver_rows = []
    for key, draws in driver_draws.items():
        pcts = [p for _, _, p in draws]
        if len(pcts) < 4:
            continue
        per_sess = defaultdict(list)
        for sid, _, p in draws:
            per_sess[sid].append(p)
        if len(per_sess) < 2:
            continue
        sess_means = [sum(v) / len(v) for v in per_sess.values()]
        mean_pct = sum(pcts) / len(pcts)
        m = len(sess_means)
        sd = _stddev(sess_means)
        z = (mean_pct - 0.5) / (sd / math.sqrt(m)) if sd > 0 and m >= 2 else None
        p = 2.0 * (1.0 - _normal_cdf(abs(z))) if z is not None else None
        driver_rows.append({'driver': display.get(key, ' '.join(key)), 'key': key,
                            'draws': len(pcts), 'sessions': m,
                            'mean_pct': mean_pct, 'z': z, 'p': p})
    for r, q in zip(driver_rows, bh_fdr([r['p'] for r in driver_rows])):
        r['q'] = q
    driver_rows.sort(key=lambda r: r['mean_pct'])

    print('=' * 92)
    print(f'KART QUALITY TABLE — {track_name} (track {args.track_id})')
    print(f'sessions used: {kart_sessions} | kart numbers with >= {args.min_kart_sessions} '
          f'sessions: {len(kart_rows)}')
    print('=' * 92)
    print('mean_pct = average within-session rank percentile of the kart\'s best lap')
    print('           (0 = fastest kart in the field, 0.5 = middle, 1 = slowest);')
    print('fast_q/slow_q = share of sessions the kart landed in the fastest/slowest 25%.')
    print()
    print(f'{"kart":>5} {"sess":>5} {"mean_pct":>9} {"z":>7} {"fast_q":>7} {"slow_q":>7}  verdict')
    print('-' * 60)

    def _kfmt(r):
        z = r['z'] if r['z'] is not None else float('nan')
        v = 'FAST' if r['mean_pct'] < 0.4 else ('SLOW' if r['mean_pct'] > 0.6 else '')
        return (f'{r["kart"]:>5} {r["n"]:>5} {r["mean_pct"]:>9.3f} {z:>7.2f} '
                f'{r["fast_q"]:>7.0%} {r["slow_q"]:>7.0%}  {v}')

    for r in kart_rows[:args.top]:
        print(_kfmt(r))
    print('  ...')
    for r in kart_rows[-args.top:]:
        print(_kfmt(r))

    print()
    print('=' * 92)
    print('DRIVER DRAW REPORT — percentile of the karts drawn (others\' best laps, skill-free)')
    print(f'{"driver":<30} {"sess":>4} {"draws":>5} {"mean_pct":>9} {"z":>8} {"q":>9}  meaning')
    print('-' * 78)
    for r in driver_rows[:5]:
        q = r['q'] if r['q'] is not None else float('nan')
        z = r['z'] if r['z'] is not None else float('nan')
        print(f'{r["driver"][:30]:<30} {r["sessions"]:>4} {r["draws"]:>5} {r["mean_pct"]:>9.3f} '
              f'{z:>8.2f} {q:>9.2e}  {"favored" if r["mean_pct"] < 0.5 else "disfavored"}')
    print('  ...')
    for r in driver_rows[-5:]:
        q = r['q'] if r['q'] is not None else float('nan')
        z = r['z'] if r['z'] is not None else float('nan')
        print(f'{r["driver"][:30]:<30} {r["sessions"]:>4} {r["draws"]:>5} {r["mean_pct"]:>9.3f} '
              f'{z:>8.2f} {q:>9.2e}  {"favored" if r["mean_pct"] < 0.5 else "disfavored"}')

    if args.names:
        wanted = [n.strip().lower().split() for n in args.names.split(',') if n.strip()]
        print()
        print('FOCUSED DRIVERS (karts drawn vs that kart number\'s overall quality):')
        print('-' * 78)
        for toks in wanted:
            match = [r for r in driver_rows if all(t in r['driver'].lower() for t in toks)]
            if not match:
                print(f'  (no qualifying draws for "{" ".join(toks)}")')
                continue
            for r in match:
                karts = driver_draws[r['key']]
                kart_ids = sorted({k for _, k, _ in karts})
                detail = ', '.join(
                    f'#{k}=' + (f'{kq[k]["mean_pct"]:.2f}' if k in kq else 'n/a')
                    for k in kart_ids)
                z = r['z'] if r['z'] is not None else float('nan')
                print(f'  {r["driver"]}: {r["sessions"]}s/{r["draws"]}d mean_pct={r["mean_pct"]:.3f} '
                      f'z={z:.2f}')
                print(f'      karts drawn (overall quality, 0=fast): {detail}')

    print()
    print('NOTE: a kart only counts as "fast/slow" if the same number repeats that result across')
    print('      sessions driven by different people; single-driver karts are excluded from the')
    print('      driver score (others\' best required).')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
