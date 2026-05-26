# scripts/

One-off operational scripts and test helpers. Migrations are
idempotent — safe to re-run.

## Migrations

| Script | Purpose |
|---|---|
| `migrate_phase1_auth.py` | Phase 1: add email-verified, verification + reset tokens, `tos_accepted_at`, `deleted_at` on `users`; create `invite_codes`, `audit_log`, `rate_limit_events`; backfill admin `email_verified=1`; create a bootstrap invite code (printed once) |
| `migrate_phase2_prefs.py` | Phase 2: create `user_track_prefs` table + index; add the `stint_assignments` column added in Phase 2.6 |

Both have idempotent ALTER/CREATE-IF-NOT-EXISTS guards and call
`PRAGMA table_info()` / `sqlite_master` before changing anything. They
abort with `RuntimeError` and a clear message if they find a state
they can't reconcile (e.g. duplicate emails before adding the partial
unique index).

Run via:

```bash
cp auth.db auth.db.bak-before-<thing>     # snapshot first
./racing-venv/bin/python scripts/migrate_<thing>.py
sqlite3 auth.db "<verify>"
pm2 restart lt-analyzer-backend
```

Backend's `_ensure_auth_schema()` also runs the same DDL defensively at
boot, so the migration script + boot-time check are belt-and-braces.

## Data tools

### `recover_merged_sessions.py`

When Apex Timing's parser sees the WebSocket break and reconnect, it
sometimes glues multiple distinct races into a single "session" row.
The recovery script walks `lap_times` chronologically for a flagged
session, detects bursts of new lap data, and splits them back into
separate `race_sessions` rows. See the script's docstring for
tunables.

```bash
python scripts/recover_merged_sessions.py --track 10 --preview   # dry run
python scripts/recover_merged_sessions.py --track 10 --apply
python scripts/recover_merged_sessions.py --track 10 --apply --session 440
```

Operates only on rows where `is_excluded=1` (you flag the session as
bad first), so it's safe to re-run.

## Test wrappers

| Script | Purpose |
|---|---|
| `test-all.sh` | Runs `npm test` + `pytest`, prints a colored summary, supports `--coverage` + `--verbose` + `--ci` |
| `test-backend.sh` | pytest only |
| `test-frontend.sh` | Jest only |
| `check-test-env.sh` | Sanity-checks that pytest, npm, and required packages are installed |
| `install-hooks.sh` | Installs a pre-commit hook that runs the linter + a quick pytest pass |

These are convenience wrappers — `./test.sh` from the project root
forwards to `test-all.sh`. CI doesn't use them (it calls `npm test` and
`pytest` directly).
