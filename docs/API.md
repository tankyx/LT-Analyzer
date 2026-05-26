# API Reference

REST + Socket.IO catalog for the `race_ui.py` backend.

## Conventions

- All paths are prefixed with `/api/` (REST) or are Socket.IO events.
- Authenticated endpoints require the session cookie set by
  `POST /api/auth/login`. `@admin_required` endpoints additionally
  require `users.role = 'admin'`.
- All unsafe-method endpoints (`POST` / `PUT` / `PATCH` / `DELETE`)
  on `/api/*` require a matching `X-CSRF-Token` header. Get the
  current token from `GET /api/auth/csrf`. The exempt list (anonymous
  endpoints protected by Turnstile instead) is: `/api/auth/login`,
  `/api/auth/register`, `/api/auth/forgot-password`,
  `/api/auth/reset-password`, `/api/auth/verify-email`,
  `/api/auth/resend-verification`, `/api/auth/csrf`.
- Rate-limit-protected endpoints return `429 {"error": "rate_limited"}`
  when exceeded.
- Errors are JSON: `{"error": "<machine-readable code>"}`.

---

## Authentication

### `GET /api/auth/csrf`
Returns the current session's CSRF token. Frontend reads on mount and
again after login.

```json
{ "csrfToken": "<32-byte urlsafe>" }
```

### `GET /api/auth/check`
Returns whether the current session is authenticated.

```json
{ "authenticated": true, "user": { "id": 2, "username": "tankyx",
  "email": "...", "role": "user" } }
```

### `POST /api/auth/login`
Body: `{username, password, turnstile_token}`. Turnstile required.
Rate-limited by `(username, ip)`: default 5 failures per 15 min.

- `200 {success, user}` on match.
- `401 {error: 'email_not_verified', email}` when the account exists
  but isn't verified.
- `401 {error: 'Invalid credentials'}` otherwise.
- `429 {error: 'Too many failed attempts...'}` over the rate limit.
- `403 {error: 'captcha_failed'}` if Turnstile rejects.

### `POST /api/auth/logout`
Requires login. Deletes the session row + clears the cookie.

### `POST /api/auth/register`
Body: `{username, email, password, invite_code, accept_terms,
turnstile_token}`. Turnstile required. Rate-limited per IP (default
5/h).

- Username regex `^[a-zA-Z0-9_.-]{3,32}$`, password ≥ 12 chars,
  `accept_terms` must be `true`.
- Reserved usernames blocked: `admin`, `root`, `system`, `support`,
  `security`, `administrator`.
- Invite code required unless `REGISTRATION_OPEN=true`.
- Anti-enumeration: duplicate email or username returns generic
  `{error: 'registration_failed'}`.
- Always returns `200 {success: true, message: 'Check your inbox...'}`
  when registration succeeds (regardless of email-send outcome — the
  email failure is audited, not surfaced).

### `POST /api/auth/verify-email`
Body: `{token}`. Marks `email_verified=1`, clears the token, fires a
welcome email. Rate-limited per IP.

- `200 {success}` on first valid use.
- `400 {error: 'expired_token'}` when expired.
- `400 {error: 'invalid_token'}` otherwise.

### `POST /api/auth/resend-verification`
Body: `{email, turnstile_token}`. Always returns `200 {success: true}`
(no enumeration). Internally: regenerates the token + sends email if
the address exists and is unverified.

### `POST /api/auth/forgot-password`
Body: `{email, turnstile_token}`. Always returns `200 {success: true}`.
Internally: generates a 1-hour reset token, sends email.

### `POST /api/auth/reset-password`
Body: `{token, new_password}`. Password must be ≥ 12 chars.

- `200 {success}` on success. **All existing sessions for the user
  are invalidated.**
- `400 {error: 'expired_token'}` / `400 {error: 'invalid_token'}` /
  `400 {error: 'weak_password'}`.

### Self-service `/api/auth/me`

- `GET /api/auth/me` (login) — current user row (no password hash).
- `POST /api/auth/me/export` (login) — JSON dump of own profile +
  audit-log entries. Fires an audit row `self_export`.
- `DELETE /api/auth/me` (login) — soft-deletes (`deleted_at`,
  `is_active=0`, scramble username + email, drop all sessions, audit
  row `account_deleted`). The bootstrap admin (`id=1`) is protected.

---

## Per-user preferences (Phase 2)

### `GET /api/me/prefs/<int:track_id>` (login)

Returns the user's prefs for that track. If no row exists, returns
defaults (`my_team=null`, `monitored_teams=[]`, `pit_stop_time=158`,
`required_pit_stops=7`, `default_lap_time=90`, `stint_planner_config={}`,
`stint_planner_presets=[]`, `stint_assignments=[]`, `driver_names=[]`,
`current_driver_index=0`).

```json
{ "prefs": { "track_id": 1, "my_team": "GHIDI", "monitored_teams": ["7", "12"],
             "pit_stop_time": 158, "...": "..." } }
```

### `PUT /api/me/prefs/<int:track_id>` (login)

Partial upsert. Body may include any subset of the writable fields:
`my_team`, `monitored_teams`, `pit_stop_time`, `required_pit_stops`,
`default_lap_time`, `stint_planner_config`, `stint_planner_presets`,
`stint_assignments`, `driver_names`, `current_driver_index`.

Validation rejects bad types and out-of-range values
(`pit_stop_time` ∈ (0, 3600], `required_pit_stops` ∈ [0, 100],
`monitored_teams` ≤ 100 entries, `stint_planner_presets` ≤ 50,
`stint_assignments` ≤ 200, `driver_names` ≤ 20).

On success: writes row, audits `prefs_updated`, emits
`prefs_updated` Socket.IO event to `user_prefs_<user_id>` room.

### `DELETE /api/me/prefs/<int:track_id>` (login)
Clears the row (reset to defaults). Audits `prefs_reset`.

### `GET /api/me/selected-track` (login)
Returns the user's currently-viewed track id: `{track_id: int | null}`.

### `PUT /api/me/selected-track` (login)
Body: `{track_id}`. Updates `users.selected_track_id`, emits
`selected_track_updated` to the user's room.

---

## Race data (gated reads)

All require login. Several are also rate-limited per IP (default 120/h)
and cached server-side (60s TTL, invalidated by admin writes).

| Endpoint | Notes |
|---|---|
| `GET /api/race-data` | Current global race_data snapshot (legacy; left in for back-compat) |
| `GET /api/team-data/sessions?track_id=N` | All sessions for a track |
| `GET /api/team-data/top-teams?track_id=N&limit=10\|20\|30` | Cached, rate-limited |
| `GET /api/team-data/search?q=&track_id=N` | Team-name search on one track |
| `GET /api/team-data/search-all?q=` | Cached, rate-limited (full-table scan across all 11 DBs) |
| `GET /api/team-data/stats?team=&track_id=N` | Per-team aggregate stats |
| `POST /api/team-data/compare` | Body `{teams[], track_id}` — pairwise comparison |
| `POST /api/team-data/common-sessions` | Body `{teams[], track_id}` |
| `POST /api/team-data/lap-details` | Body `{teams[], session_id, track_id}` |
| `GET /api/team-data/all-laps?team=&track_id=N` | Paginated raw laps |
| `GET /api/team-data/cross-track-sessions?team=` | Cached, rate-limited (queries every per-track DB) |
| `GET /api/team-data/session-laps?team=&track_id=N&session_id=M` | Lap-by-lap for one session |
| `POST /api/team-data/delete-best-lap` | **Admin only.** Nullifies a best-lap record |
| `POST /api/team-data/mass-delete-laps` | **Admin only.** Threshold-based mass delete |

---

## Track management

| Endpoint | Notes |
|---|---|
| `GET /api/tracks` | List all configured tracks (public) |
| `GET /api/tracks/active` | Tracks with `is_active=1` |
| `GET /api/tracks/status` | Live session status per track |
| `GET /api/tracks/<id>` | Single track detail |
| `GET /api/admin/tracks` | Admin |
| `POST /api/admin/tracks` | Admin |
| `PUT /api/admin/tracks/<id>` | Admin |
| `DELETE /api/admin/tracks/<id>` | Admin |
| `POST /api/admin/tracks/<id>/layouts` | Admin: add a layout (kart-fairness band) |
| `PUT /api/admin/tracks/<id>/layouts/<lid>` | Admin |
| `DELETE /api/admin/tracks/<id>/layouts/<lid>` | Admin |
| `POST /api/admin/tracks/<tid>/sessions/<sid>/exclude` | Admin: toggle `is_excluded` |

---

## Admin

| Endpoint | Notes |
|---|---|
| `GET /api/admin/users` | List users |
| `POST /api/admin/users` | Create user (`email_verified=1` for admin-created) |
| `PUT /api/admin/users/<id>` | Update (email/role/is_active/password); password change drops all sessions |
| `DELETE /api/admin/users/<id>` | Delete (bootstrap admin id=1 protected) |
| `GET /api/admin/aliases` | List driver aliases grouped by canonical |
| `POST /api/admin/aliases` | `{canonical_name, alias_name}` |
| `DELETE /api/admin/aliases/<id>` | |
| `GET /api/admin/invite-codes` | List invites + usage |
| `POST /api/admin/invite-codes` | `{max_uses, expires_at?, note?}` — code returned in plaintext **once** |
| `DELETE /api/admin/invite-codes/<id>` | Revoke |
| `GET /api/admin/audit-log?action=&actor=&limit=200&offset=0` | Paged read |

---

## Test endpoints (production: disabled)

When `ENABLE_TEST_ENDPOINTS=true` (dev only):

- `POST /api/test/simulate-session/<int:track_id>` — admin
- `POST /api/test/stop-session/<int:track_id>` — admin

In production these routes are never registered (404).

---

## Socket.IO events

Server listens for:

| Event | Payload | Effect |
|---|---|---|
| `connect` | (auth, optional) | Joins `race_updates` room; emits a legacy `race_data_update` snapshot |
| `disconnect` | — | Leaves `race_updates` + `standings_stream` |
| `join_track` | `{track_id}` | Joins `track_<id>` room; emits a one-shot `track_update` snapshot for the joining client |
| `leave_track` | `{track_id}` | |
| `join_all_tracks` | — | Joins `all_tracks` room; emits an immediate `all_tracks_status` |
| `leave_all_tracks` | — | |
| `join_team_room` | `{track_id, team_name}` | Joins `team_track_<track_id>_<team>` (used by external mobile clients) |
| `leave_team_room` | `{track_id, team_name}` | |
| `subscribe_user_prefs` | `{user_id}` | Joins `user_prefs_<user_id>` for cross-device sync |
| `unsubscribe_user_prefs` | `{user_id}` | |
| `subscribe_standings` | `{...}` | Joins `standings_stream` for legacy clients |
| `unsubscribe_standings` | — | |
| `request_team_delta` | `{kart_number}` | Replies with current delta info |

Server emits:

| Event | Room | Payload |
|---|---|---|
| `race_data_update` | `race_updates` | Trimmed snapshot (teams, session_info, last_update, is_running, simulation_mode, timing_url) |
| `track_update` | `track_<id>` | `{track_id, track_name, teams, session_id, timestamp}` |
| `teams_update` | `race_updates` | Legacy partial update |
| `session_update` | `race_updates` | session_info change |
| `session_status` | `track_<id>` | `{track_id, track_name, active, message, timestamp}` |
| `all_tracks_status` | `all_tracks` | `{tracks: [{...status per track}], timestamp}` |
| `team_specific_update` | `team_track_<id>_<team>` | per-team live update (mobile API) |
| `team_room_joined` / `team_room_left` / `team_room_error` | (direct) | room-join feedback |
| `prefs_updated` | `user_prefs_<user_id>` | `{user_id, track_id, updated_at}` — refetch hint |
| `selected_track_updated` | `user_prefs_<user_id>` | `{user_id, track_id}` — auto-switch hint |
| `delta_change` | `race_updates` | (legacy) targeted delta delta |

The "rooms" are Socket.IO rooms, not socket connections. A single client
joins multiple rooms (e.g. `race_updates`, `track_3`, `all_tracks`,
`user_prefs_2`) and receives every event broadcast to any of them.
