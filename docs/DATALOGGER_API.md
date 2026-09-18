# LT-Analyzer API for datalogger clients

How an external client (the Android datalogger, a trackside tablet, a script)
authenticates, receives live timing, and reads or writes race state.

- **Base URL**: `https://kart.krranalyser.fr`
- **Content type**: `application/json` for every request with a body
- **Transport for live data**: Socket.IO (Engine.IO v4) on the same origin

Everything below is reachable with the credentials of a normal account. The
`/api/admin/*` routes are not covered here.

---

## 1. Authentication

The API is **cookie-session based**, not token based. A client logs in once,
keeps the session cookie, and sends it on every later request, including the
Socket.IO handshake.

### 1.1 Log in

```http
POST /api/auth/login
Content-Type: application/json

{
  "username": "tankyx",
  "password": "…",
  "turnstile_token": "0.abc…"
}
```

Success returns `200` and sets a `session` cookie:

```json
{
  "success": true,
  "user": { "id": 2, "username": "tankyx", "role": "user", "email": "…" }
}
```

**The captcha token is mandatory in production.** The server runs with
`FLASK_ENV=production` and a Turnstile secret configured, so a login without a
valid `turnstile_token` is rejected with `403 {"error": "captcha_failed"}`.
A native client therefore needs a WebView (or an embedded browser view) that
renders the Cloudflare Turnstile widget with the site key, and passes the
resulting token into this call. This is why the existing Android datalogger is
WebView-based.

Other failures:

| Status | Body | Meaning |
|---|---|---|
| 400 | `{"error": "Username and password required"}` | missing field |
| 401 | `{"error": …}` | wrong credentials, inactive or deleted account |
| 403 | `{"error": "captcha_failed"}` | missing or invalid Turnstile token |
| 401 | `{"error": "email_not_verified", "email": "…"}` | verify the address first |
| 429 | `{"error": "Too many failed attempts…"}` | see rate limits below |

### 1.2 Keep the session

Sessions last **24 hours** by default (`SESSION_LIFETIME_HOURS`). Check one
without spending a login:

```http
GET /api/auth/check
```

Always returns `200`, with either `{"authenticated": true, "user": {…}}` or
`{"authenticated": false}` — branch on the flag, not on the status code. A
datalogger should call this at start-up and log in again only when it is
false.

### 1.3 CSRF token, required for writes

Every unsafe request (`POST`, `PUT`, `DELETE`) to `/api/*` must carry an
`X-CSRF-Token` header, apart from the anonymous auth endpoints. `GET` and
`HEAD` never need it.

```http
GET /api/auth/csrf          ->  {"csrfToken": "…"}
```

The token is issued per session and **rotates on login**, so fetch it after
logging in and reuse it until the next login. A missing or stale token returns
`403 {"error": "csrf_failed"}`.

### 1.4 Rate limits

| Limit | Default | Scope |
|---|---|---|
| Failed logins | 5 per 15 min | username + IP |
| Failed logins | 10 per 15 min | username, any IP |
| Failed logins | 30 per 15 min | IP, any username |
| Heavy reads | 120 per hour | IP |

Heavy reads are the historical analytics endpoints (team comparison, lap
details, driver consistency). Live timing and the pace endpoint are not
rate limited: use the Socket.IO stream rather than polling them.

### 1.5 Log out

```http
POST /api/auth/logout
X-CSRF-Token: …
```

---

## 2. Live timing over Socket.IO

### 2.1 Connecting

Connect to the same origin with the session cookie attached. **Anonymous
connections are refused** — the handshake reads the cookie and drops the
socket if there is no valid session, so log in first.

```
wss://kart.krranalyser.fr/socket.io/?EIO=4&transport=websocket
```

On connect the server puts you in two rooms automatically:

- `race_updates` — general broadcast
- `user_{your_user_id}` — your personal channel, used for pit alerts

You then join the rooms you care about. **A connection may hold at most 20
distinct explicitly-joined rooms** (`SOCKET_MAX_ROOM_JOINS`); rejoining a room
you already hold is free.

### 2.2 Subscribing to a track

```js
socket.emit('join_track', { track_id: 1 });     // -> 'track_joined'
socket.emit('leave_track', { track_id: 1 });
```

While joined you receive `track_update` whenever the parser stores new data
for that track:

```json
{
  "track_id": 1,
  "track_name": "Mariembourg",
  "teams": [
    {
      "Position": "4", "Kart": "14", "Team": "1 - MY TEAM",
      "Last Lap": "1:19.701", "Best Lap": "1:19.233",
      "Gap": "8.115", "RunTime": "0:42:10",
      "Pit Stops": "2", "Status": "On Track"
    }
  ],
  "session_id": 17,
  "timestamp": "2026-09-18T14:03:21.114"
}
```

`teams` is the full standings for the track, one record per kart, ordered as
the timing feed sends it.

You also receive, in the same room:

| Event | When |
|---|---|
| `session_status` | a track's session goes active or inactive |
| `session_update` | session info changes (flags, titles) |
| `race_data_reset` | the parser cleared its data |
| `pit_alert_broadcast` | anyone triggered a pit alert on this track |

### 2.3 Subscribing to one team (the datalogger's usual choice)

Cheaper than a whole track when you only follow your own car. The server only
builds these payloads for rooms that are actually occupied.

```js
socket.emit('join_team_room', { track_id: 1, team_name: "1 - MY TEAM" });
socket.emit('leave_team_room', { track_id: 1, team_name: "1 - MY TEAM" });
```

Confirmations arrive as `team_room_joined` / `team_room_left`; problems as
`team_room_error` (unknown track, or a `team_name` that is not printable or is
longer than 64 characters). The team name must match the timing feed exactly,
class prefix included.

Updates arrive as `team_specific_update`:

```json
{
  "Position": "4",
  "Gap": "8.115",
  "gap_to_front": "-1.245",
  "gap_to_behind": "6.787",
  "Last Lap": "1:19.701",
  "Best Lap": "1:19.233",
  "Pit Stops": "2",
  "Status": "On Track"
}
```

`gap_to_front` and `gap_to_behind` are seconds as strings, or `"-"` when there
is no car there (leader, or last on track).

### 2.4 All tracks at once

```js
socket.emit('join_all_tracks');   // 'all_tracks_status' events
socket.emit('leave_all_tracks');
```

```json
{
  "tracks": [
    { "track_id": 1, "track_name": "Mariembourg", "active": true,
      "last_update": "2026-09-18T14:03:21", "is_connected": true,
      "teams_count": 24, "provider": "apex" }
  ],
  "timestamp": "2026-09-18T14:03:22"
}
```

### 2.5 Pit alerts

Trigger one over REST:

```http
POST /api/trigger-pit-alert
X-CSRF-Token: …

{ "track_id": 1, "team_name": "1 - MY TEAM", "alert_message": "PIT NOW" }
```

It is delivered as a `pit_alert` event **to your own devices only** — the
`user_{id}` room you were placed in at connect time. A rival crew watching the
same team name does not get buzzed.

```json
{
  "track_id": 1,
  "team_name": "1 - MY TEAM",
  "alert_type": "pit_required",
  "alert_message": "PIT NOW",
  "timestamp": "2026-09-18T14:05:00",
  "flash_color": "#FF0000",
  "duration_ms": 80000,
  "priority": "high",
  "triggered_by_user_id": 2
}
```

A `pit_alert_broadcast` also goes to the track room, for dashboards showing a
banner. Treat that one as a UI hint, not a signal to buzz a phone.

### 2.6 Preference changes from other devices

```js
socket.emit('subscribe_user_prefs', { user_id: 2 });   // -> 'prefs_updated'
socket.emit('unsubscribe_user_prefs', { user_id: 2 });
```

The `user_id` must be your own — the server checks it against the account
bound to the connection and silently ignores anything else.

`prefs_updated` carries `{user_id, track_id, updated_at}` and means "re-fetch
if you care". Compare `updated_at` with the value you last wrote to ignore the
echo of your own save. Note the server emits this **before** the originating
`PUT` returns, so your own write can reach you before you have recorded its
`updated_at`: never apply a fetched snapshot over a field the user has edited
since the fetch started.

---

## 3. REST endpoints

### 3.1 Tracks

| Endpoint | Purpose |
|---|---|
| `GET /api/tracks` | every configured track with its id and name |
| `GET /api/tracks/<id>` | one track |
| `GET /api/tracks/active` | tracks currently being monitored |
| `GET /api/tracks/status` | session status for all tracks (same shape as `all_tracks_status`) |
| `GET /api/parser-status` | parser health per track |

### 3.2 Current standings

```http
GET /api/race-data
```

The legacy snapshot of the currently selected track: teams, session info and
last update. Use it to paint a first screen, then follow Socket.IO. It is not
per-track — prefer `join_track` for a specific track.

### 3.3 Team pace (how you are actually going)

```http
GET /api/track/<track_id>/pace/team?team=1%20-%20MY%20TEAM&session_id=17
```

`session_id` is optional and defaults to the track's live session. Each stint
is compared against the median of the field **during that same stint**, so
track conditions cancel out and stints hours apart are comparable. Your own
laps are excluded from that reference.

```json
{
  "team": "1 - MY TEAM",
  "matched_team": "1 - MY TEAM",
  "session_id": 17,
  "current": {
    "stint_index": 2, "lap_count": 12,
    "mean": 79.42, "best": 78.91,
    "field_median": 80.10, "field_laps": 96,
    "field_basis": "stint_window",
    "residual": -0.68, "confidence": "high"
  },
  "recent": { "laps": 5, "mean": 79.60, "residual": -0.45 },
  "trend": "stable",
  "trend_drift": 0.04,
  "own_norm_residual": -0.71,
  "field_ref_seconds": 80.10,
  "kart": { "fleet_kart_id": 4, "label": "K-12" },
  "stints": [ /* one row per stint, same shape as `current` */ ],
  "verdict": {
    "verdict": "keep",
    "reason": "Running at your normal pace.",
    "delta_vs_own_norm": 0.03,
    "band": 0.25
  }
}
```

- `residual` is seconds a lap against the field. **Negative is faster.**
- `verdict` is one of `keep`, `watch`, `consider_switch`, `switch`,
  `insufficient`. It compares the current stint with your own earlier stints,
  which cancels how quick your drivers generally are and leaves the machine.
- `trend` is `improving`, `stable`, `fading` or `unknown`, from the two halves
  of the current stint, each residualised separately.
- `confidence` is `low` under 5 clean laps, `medium` to 9, then `high`.
- It cancels conditions, **not** driver differences. A slow stint may be the
  driver rather than the kart.

Errors: `400 team_required`, `400 invalid_team`, `400 invalid_session_id`,
`404 unknown_track`, `404 no_active_session`.

### 3.4 Per-track preferences (shared across your devices)

This is how a companion app keeps its state in step with the web dashboard.
Everything is scoped to `(your account, track)`.

```http
GET /api/me/prefs/<track_id>
```

```json
{
  "prefs": {
    "track_id": 1,
    "my_team": "14",
    "monitored_teams": ["21", "28"],
    "pit_stop_time": 158,
    "required_pit_stops": 7,
    "default_lap_time": 90,
    "stint_planner_config": { "numStints": 10, "totalRaceTime": 358, "…": 0 },
    "stint_planner_presets": [ { "id": "preset_…", "name": "6H", "config": {}, "driverNames": [], "stintAssignments": [] } ],
    "stint_assignments": [ { "stint": 1, "driver": 1, "duration": 32, "startTime": 0, "endTime": 32, "isJoker": false, "isLong": false } ],
    "driver_names": ["Tanguy", "Marc"],
    "current_driver_index": 0,
    "updated_at": "2026-09-18T14:00:00"
  }
}
```

```http
PUT /api/me/prefs/<track_id>
X-CSRF-Token: …

{ "driver_names": ["Tanguy", "Marc", "Céline"] }
```

A **partial patch**: send only the fields you are changing. Unknown fields are
ignored. The response is the full updated object, and the write is broadcast
to your other devices as `prefs_updated`.

Validation, all of which return `400` with the reason:

| Field | Rule |
|---|---|
| `my_team` | string or null |
| `monitored_teams` | list of at most 100 strings or ints |
| `pit_stop_time` | int, 0 < v ≤ 3600 |
| `required_pit_stops` | int, 0 ≤ v ≤ 100 |
| `default_lap_time` | number, 0 < v ≤ 3600 |
| `stint_planner_config` | object |
| `stint_planner_presets` | list of at most 50 |
| `stint_assignments` | list of at most 200 |
| `driver_names` | list of at most 20 strings |
| `current_driver_index` | int, 0 ≤ v ≤ 100 |

**A patch is all-or-nothing**: one invalid field rejects the whole request, so
do not batch an unvalidated value together with something you need saved.

`DELETE /api/me/prefs/<track_id>` resets that track to defaults.

`GET` / `PUT /api/me/selected-track` (`{"track_id": 1}`) syncs which track the
account is looking at.

### 3.5 Fleet tracker (physical karts)

Per account and per track; see `CLAUDE.md` for the full list. The ones a
datalogger is likely to want:

| Endpoint | Purpose |
|---|---|
| `GET /api/track/<id>/fleet/karts` | your kart registry |
| `GET /api/track/<id>/fleet/state` | live board with each kart's pace and location |
| `POST /api/track/<id>/fleet/assignments` | record which kart a team took |

### 3.6 History

`GET /api/team-data/*` covers past sessions: `top-teams`, `search`, `stats`,
`all-laps`, `session-laps`, `cross-track-sessions`. These are the heavy reads
capped at 120 per hour per IP.

---

## 4. Data formats

- **Lap and best times**: `"M:SS.mmm"` (`"1:19.701"`), occasionally plain
  seconds (`"58.800"`) on some feeds. Parse both.
- **Gap**: seconds as a string (`"8.115"`), `"Leader"` / empty for the leader,
  or `"1 Tour"` / `"2 Tours"` when laps down.
- **RunTime**: `"H:MM:SS"` total running time.
- **Status**: `On Track`, `Pit-in`, `Pit-out`, `Finished`, `Stopped`, `Up`,
  `Down`, `Lapped`. Anything else should be treated as unknown, not an error.
- **Team names** may carry a class prefix, `"1 - TEAM"` or `"2 - TEAM"`. Room
  names and the pace endpoint expect the name exactly as the feed sends it.
- **Ghost rows**: teams whose name starts with `"G - "` are timing-system
  artefacts, not cars. Exclude them from any average or median you compute.
- **Timestamps** are ISO 8601 in the server's local time, without a zone
  suffix.

---

## 5. Recommended client loop

1. `GET /api/auth/check`. If it fails, log in (with a Turnstile token) and
   then `GET /api/auth/csrf`.
2. Open the Socket.IO connection with the session cookie.
3. `join_team_room` for your team, and `subscribe_user_prefs` with your own
   `user_id` if the app shows planner state.
4. Render from `team_specific_update`; it arrives as the feed updates.
5. Poll `GET /api/track/<id>/pace/team` no more than every few seconds, and
   only while a pace screen is open.
6. On a `prefs_updated` whose `updated_at` you did not write, re-fetch the
   preferences, but never overwrite a field the user is editing.
7. Re-authenticate when any call returns `401`.

## 6. Error handling

| Status | Meaning | What a client should do |
|---|---|---|
| 400 | bad request, body names the field | fix the payload, do not retry as is |
| 401 | not authenticated, or session expired | log in again, then retry once |
| 403 | `csrf_failed` or `captcha_failed` | re-fetch the CSRF token, or re-run the captcha |
| 404 | unknown track, or no live session | not an error during a quiet period |
| 429 | rate limited | back off, respect the window in the message |
| 500 | server error | retry with backoff; the body carries no detail |

A refused Socket.IO connection almost always means the session cookie was
missing or expired. Log in again before reconnecting, and back off rather than
reconnecting in a tight loop.
