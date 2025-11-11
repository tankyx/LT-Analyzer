# LT-Analyzer Android Overlay API Documentation

Complete reference for building an Android overlay app that displays real-time race position and gaps.

---

## Overview

The LT-Analyzer backend provides a Socket.IO API for real-time race data. This document covers integration for a simple overlay showing:

**When NOT in P1:**
- Gap to leader (P1) - above position
- Gap to car in front (P-1) - above position
- Current position (center)
- Gap to car behind (P+1) - below position

**When in P1 (leader):**
- Current position (top)
- Gap to P2 - below position
- Gap to P3 - below position

---

## Visual Layout

### Layout When P3 (Not Leader)

```
┌─────────────────────────────┐
│   Gap P1:    +12.345        │  ← Gap to leader
│   Gap P2:    +2.156         │  ← Gap to car in front
│                             │
│          P3                 │  ← Your position (large)
│                             │
│   Gap P4:    -5.234         │  ← Gap to car behind
└─────────────────────────────┘
```

### Layout When P1 (Leader)

```
┌─────────────────────────────┐
│          P1                 │  ← Your position (large)
│                             │
│   Gap P2:    -8.567         │  ← Gap to P2 below you
│   Gap P3:    -15.234        │  ← Gap to P3 below you
└─────────────────────────────┘
```

---

## Socket.IO Connection

### Server URL

```
http://YOUR_SERVER_IP:5000
```

Replace with your LT-Analyzer backend server address.

---

## Socket.IO Events

### Events to Emit (Client → Server)

#### 1. Join Track

Subscribe to a specific track to receive race data.

```javascript
{
  "track_id": 1
}
```

**Event name:** `join_track`

**Example:**
```kotlin
socket.emit("join_track", JSONObject().put("track_id", 1))
```

---

#### 2. Join Team Room

Subscribe to updates for a specific team on a track.

```javascript
{
  "track_id": 1,
  "team_name": "Team Rocket"
}
```

**Event name:** `join_team_room`

**Example:**
```kotlin
socket.emit("join_team_room", JSONObject()
    .put("track_id", 1)
    .put("team_name", "Team Rocket"))
```

**Important:**
- Team name is **case-sensitive**
- Must match exactly as it appears in the timing system
- Team must be currently racing on that track

---

### Events to Listen For (Server → Client)

#### 1. Team Specific Update

Real-time updates for YOUR team only. This is the main event for the overlay.

**Event name:** `team_specific_update`

**Payload:**
```javascript
{
  "track_id": 1,
  "track_name": "Mariembourg",
  "team_name": "Team Rocket",
  "position": 3,                    // Current position (1, 2, 3...)
  "kart": "25",                     // Kart number
  "status": "On Track",             // "On Track", "Pit-in", "Pit-out", "Finished"
  "last_lap": "1:02.345",           // Last lap time
  "best_lap": "1:01.234",           // Best lap time
  "total_laps": 42,                 // Laps completed
  "runtime": "1:23:45",             // Total race time
  "gap_to_leader": "+12.345",       // Gap to P1
  "gap_to_front": "+2.156",         // Gap to car ahead (P-1)
  "gap_to_behind": "-5.234",        // Gap to car behind (P+1)
  "pit_stops": 2,                   // Number of pit stops
  "session_id": "session_123",
  "timestamp": "2025-01-10T12:34:56"
}
```

**Gap Formats:**

- **gap_to_leader:**
  - `"Leader"` - You're in P1
  - `"+12.345"` - Seconds behind leader
  - `"1 lap"`, `"2 laps"` - Lapped

- **gap_to_front:**
  - `"-"` - You're in P1 (no car ahead)
  - `"+2.156"` - Seconds behind car ahead

- **gap_to_behind:**
  - `"-"` - No car behind (last place)
  - `"-5.234"` - Seconds ahead of car behind

---

#### 2. Track Update

Updates for ALL teams on the track. Use this to get P2 and P3 gaps when you're P1.

**Event name:** `track_update`

**Payload:**
```javascript
{
  "track_id": 1,
  "track_name": "Mariembourg",
  "teams": [
    {
      "name": "Team A",
      "position": 1,
      "kart": "10",
      "status": "On Track",
      "last_lap": "1:01.234",
      "best_lap": "1:00.987",
      "total_laps": 45,
      "runtime": "1:25:30",
      "gap_to_leader": "Leader",
      "gap_to_front": "-",
      "gap_to_behind": "-8.567",
      "pit_stops": 3
    },
    {
      "name": "Team B",
      "position": 2,
      "kart": "25",
      "status": "On Track",
      "last_lap": "1:02.100",
      "best_lap": "1:01.500",
      "total_laps": 45,
      "runtime": "1:25:38",
      "gap_to_leader": "+8.567",
      "gap_to_front": "+8.567",
      "gap_to_behind": "-6.667",
      "pit_stops": 2
    },
    // ... more teams
  ],
  "session_id": "session_123",
  "timestamp": "2025-01-10T12:34:56"
}
```

**Use case:** When you're P1, extract P2 and P3 data to show their gaps below your position.

---

#### 3. Session Status

Indicates whether a racing session is active or not.

**Event name:** `session_status`

**Payload:**
```javascript
{
  "track_id": 1,
  "track_name": "Mariembourg",
  "active": true,                   // true = race active, false = no race
  "message": "Session active",
  "timestamp": "2025-01-10T12:34:56"
}
```

**Use case:** Show "Waiting for session" message when `active: false`.

---

#### 4. Team Room Joined

Confirmation that you successfully joined a team room.

**Event name:** `team_room_joined`

**Payload:**
```javascript
{
  "track_id": 1,
  "track_name": "Mariembourg",
  "team_name": "Team Rocket",
  "room": "team_track_1_Team Rocket",
  "timestamp": "2025-01-10T12:34:56"
}
```

---

#### 5. Team Room Error

Error when trying to join a team room.

**Event name:** `team_room_error`

**Payload:**
```javascript
{
  "error": "Team not found on this track",
  "track_id": 1,
  "track_name": "Mariembourg",
  "timestamp": "2025-01-10T12:34:56"
}
```

**Common errors:**
- `"Team not found on this track"` - Team name incorrect or not racing
- `"Track not found"` - Invalid track_id
- `"Missing track_id or team_name"` - Invalid request

---

## Android Implementation

### Dependencies

**`app/build.gradle`:**
```gradle
dependencies {
    implementation 'io.socket:socket.io-client:2.1.0'
}
```

### Permissions

**`AndroidManifest.xml`:**
```xml
<uses-permission android:name="android.permission.INTERNET" />
<uses-permission android:name="android.permission.SYSTEM_ALERT_WINDOW" />
<uses-permission android:name="android.permission.FOREGROUND_SERVICE" />
```

---

## Layout XML

**`res/layout/simple_overlay.xml`:**

```xml
<?xml version="1.0" encoding="utf-8"?>
<LinearLayout xmlns:android="http://schemas.android.com/apk/res/android"
    android:layout_width="wrap_content"
    android:layout_height="wrap_content"
    android:orientation="vertical"
    android:background="#CC000000"
    android:padding="16dp"
    android:minWidth="220dp">

    <!-- Gaps ABOVE position (shown when NOT P1) -->
    <LinearLayout
        android:id="@+id/layout_gaps_above"
        android:layout_width="match_parent"
        android:layout_height="wrap_content"
        android:orientation="vertical"
        android:visibility="gone">

        <!-- Gap to Leader -->
        <TextView
            android:id="@+id/tv_gap_leader"
            android:layout_width="match_parent"
            android:layout_height="wrap_content"
            android:text="Gap P1: -"
            android:textSize="16sp"
            android:textColor="#FFFF9800"
            android:paddingVertical="2dp" />

        <!-- Gap to Car in Front -->
        <TextView
            android:id="@+id/tv_gap_front"
            android:layout_width="match_parent"
            android:layout_height="wrap_content"
            android:text="Gap P-1: -"
            android:textSize="16sp"
            android:textColor="#FFFFFF"
            android:paddingVertical="2dp" />
    </LinearLayout>

    <!-- Current Position (always visible, center) -->
    <TextView
        android:id="@+id/tv_position"
        android:layout_width="match_parent"
        android:layout_height="wrap_content"
        android:text="P-"
        android:textSize="48sp"
        android:textStyle="bold"
        android:textColor="#FFFFFF"
        android:gravity="center"
        android:paddingVertical="12dp" />

    <!-- Gaps BELOW position (shown when P1, or always for car behind) -->
    <LinearLayout
        android:id="@+id/layout_gaps_below"
        android:layout_width="match_parent"
        android:layout_height="wrap_content"
        android:orientation="vertical"
        android:visibility="gone">

        <!-- Gap to P2 (when you're P1) OR Gap to car behind (when not P1) -->
        <TextView
            android:id="@+id/tv_gap_p2"
            android:layout_width="match_parent"
            android:layout_height="wrap_content"
            android:text="Gap P2: -"
            android:textSize="16sp"
            android:textColor="#FFFFFF"
            android:paddingVertical="2dp" />

        <!-- Gap to P3 (only when you're P1) -->
        <TextView
            android:id="@+id/tv_gap_p3"
            android:layout_width="match_parent"
            android:layout_height="wrap_content"
            android:text="Gap P3: -"
            android:textSize="16sp"
            android:textColor="#FFFFFF"
            android:paddingVertical="2dp" />
    </LinearLayout>

</LinearLayout>
```

---

## Kotlin Code

### Socket Manager

**`RaceSocket.kt`:**

```kotlin
import io.socket.client.IO
import io.socket.client.Socket
import org.json.JSONObject

object RaceSocket {

    private const val SERVER_URL = "http://YOUR_SERVER_IP:5000"

    private var socket: Socket? = null

    var onTeamUpdate: ((TeamUpdate) -> Unit)? = null
    var onTrackUpdate: ((List<TeamData>) -> Unit)? = null
    var onSessionStatus: ((Boolean, String) -> Unit)? = null
    var onError: ((String) -> Unit)? = null

    fun connect(trackId: Int, teamName: String) {
        socket = IO.socket(SERVER_URL)

        // Connection events
        socket?.on(Socket.EVENT_CONNECT) {
            socket?.emit("join_track", JSONObject().put("track_id", trackId))
            socket?.emit("join_team_room", JSONObject()
                .put("track_id", trackId)
                .put("team_name", teamName))
        }

        socket?.on(Socket.EVENT_CONNECT_ERROR) {
            onError?.invoke("Connection error")
        }

        // Team-specific updates (YOUR team only)
        socket?.on("team_specific_update") { args ->
            val data = args[0] as JSONObject
            val update = TeamUpdate(
                position = data.optInt("position", 0),
                gapToLeader = data.optString("gap_to_leader", "-"),
                gapToFront = data.optString("gap_to_front", "-"),
                gapToBehind = data.optString("gap_to_behind", "-"),
                lastLap = data.optString("last_lap", "-"),
                bestLap = data.optString("best_lap", "-"),
                pitStops = data.optInt("pit_stops", 0),
                status = data.optString("status", "")
            )
            onTeamUpdate?.invoke(update)
        }

        // Track updates (ALL teams - needed for P2/P3 when you're P1)
        socket?.on("track_update") { args ->
            val data = args[0] as JSONObject
            val teamsArray = data.getJSONArray("teams")
            val teams = mutableListOf<TeamData>()

            for (i in 0 until teamsArray.length()) {
                val team = teamsArray.getJSONObject(i)
                teams.add(TeamData(
                    position = team.optInt("position", 0),
                    gapToLeader = team.optString("gap_to_leader", "-")
                ))
            }

            onTrackUpdate?.invoke(teams)
        }

        // Session status
        socket?.on("session_status") { args ->
            val data = args[0] as JSONObject
            val active = data.getBoolean("active")
            val message = data.getString("message")
            onSessionStatus?.invoke(active, message)
        }

        // Team room errors
        socket?.on("team_room_error") { args ->
            val data = args[0] as JSONObject
            onError?.invoke(data.getString("error"))
        }

        socket?.connect()
    }

    fun disconnect() {
        socket?.disconnect()
        socket = null
    }

    fun isConnected(): Boolean = socket?.connected() ?: false
}

data class TeamUpdate(
    val position: Int,
    val gapToLeader: String,
    val gapToFront: String,
    val gapToBehind: String,
    val lastLap: String,
    val bestLap: String,
    val pitStops: Int,
    val status: String
)

data class TeamData(
    val position: Int,
    val gapToLeader: String
)
```

---

### Overlay Service

**`SimpleOverlayService.kt`:**

```kotlin
import android.app.*
import android.content.Context
import android.content.Intent
import android.graphics.PixelFormat
import android.os.Build
import android.os.IBinder
import android.view.*
import android.widget.LinearLayout
import android.widget.TextView
import androidx.core.app.NotificationCompat

class SimpleOverlayService : Service() {

    private var windowManager: WindowManager? = null
    private var overlayView: View? = null

    // UI Elements
    private var tvPosition: TextView? = null
    private var layoutGapsAbove: LinearLayout? = null
    private var layoutGapsBelow: LinearLayout? = null
    private var tvGapLeader: TextView? = null
    private var tvGapFront: TextView? = null
    private var tvGapP2: TextView? = null
    private var tvGapP3: TextView? = null

    private var allTeams: List<TeamData> = emptyList()

    companion object {
        // Configure these
        private const val TRACK_ID = 1
        private const val TEAM_NAME = "Team Rocket"
    }

    override fun onCreate() {
        super.onCreate()
        createNotificationChannel()
        startForeground(1, createNotification())

        setupSocket()
        createOverlay()
    }

    private fun setupSocket() {
        RaceSocket.onTeamUpdate = { update ->
            runOnUiThread {
                updateDisplay(update)
            }
        }

        RaceSocket.onTrackUpdate = { teams ->
            allTeams = teams
        }

        RaceSocket.onSessionStatus = { active, message ->
            runOnUiThread {
                if (!active) {
                    tvPosition?.text = "---"
                }
            }
        }

        RaceSocket.onError = { error ->
            runOnUiThread {
                tvPosition?.text = "ERR"
            }
        }

        RaceSocket.connect(TRACK_ID, TEAM_NAME)
    }

    private fun createOverlay() {
        windowManager = getSystemService(Context.WINDOW_SERVICE) as WindowManager
        overlayView = LayoutInflater.from(this).inflate(R.layout.simple_overlay, null)

        // Initialize views
        tvPosition = overlayView?.findViewById(R.id.tv_position)
        layoutGapsAbove = overlayView?.findViewById(R.id.layout_gaps_above)
        layoutGapsBelow = overlayView?.findViewById(R.id.layout_gaps_below)
        tvGapLeader = overlayView?.findViewById(R.id.tv_gap_leader)
        tvGapFront = overlayView?.findViewById(R.id.tv_gap_front)
        tvGapP2 = overlayView?.findViewById(R.id.tv_gap_p2)
        tvGapP3 = overlayView?.findViewById(R.id.tv_gap_p3)

        // Window parameters
        val layoutType = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            WindowManager.LayoutParams.TYPE_APPLICATION_OVERLAY
        } else {
            WindowManager.LayoutParams.TYPE_PHONE
        }

        val params = WindowManager.LayoutParams(
            WindowManager.LayoutParams.WRAP_CONTENT,
            WindowManager.LayoutParams.WRAP_CONTENT,
            layoutType,
            WindowManager.LayoutParams.FLAG_NOT_FOCUSABLE,
            PixelFormat.TRANSLUCENT
        ).apply {
            gravity = Gravity.TOP or Gravity.END
            x = 20
            y = 100
        }

        // Make draggable
        makeDraggable(overlayView!!, params)

        windowManager?.addView(overlayView, params)
    }

    private fun updateDisplay(update: TeamUpdate) {
        val position = update.position
        tvPosition?.text = "P$position"

        if (position == 1) {
            // We're P1 (leader) - show P2 and P3 below
            layoutGapsAbove?.visibility = View.GONE
            layoutGapsBelow?.visibility = View.VISIBLE

            // Find P2 and P3 from track updates
            val p2 = allTeams.find { it.position == 2 }
            val p3 = allTeams.find { it.position == 3 }

            tvGapP2?.text = "Gap P2: ${p2?.gapToLeader ?: update.gapToBehind}"
            tvGapP3?.text = "Gap P3: ${p3?.gapToLeader ?: "-"}"

        } else {
            // We're NOT P1 - show leader and front above, behind below
            layoutGapsAbove?.visibility = View.VISIBLE
            layoutGapsBelow?.visibility = View.VISIBLE

            // Above position
            tvGapLeader?.text = "Gap P1: ${update.gapToLeader}"
            tvGapFront?.text = "Gap P${position - 1}: ${update.gapToFront}"

            // Below position
            tvGapP2?.text = "Gap P${position + 1}: ${update.gapToBehind}"
            tvGapP3?.visibility = View.GONE // Hide P3 line when not leader
        }
    }

    private fun makeDraggable(view: View, params: WindowManager.LayoutParams) {
        var initialX = 0
        var initialY = 0
        var initialTouchX = 0f
        var initialTouchY = 0f

        view.setOnTouchListener { _, event ->
            when (event.action) {
                MotionEvent.ACTION_DOWN -> {
                    initialX = params.x
                    initialY = params.y
                    initialTouchX = event.rawX
                    initialTouchY = event.rawY
                    true
                }
                MotionEvent.ACTION_MOVE -> {
                    params.x = initialX + (initialTouchX - event.rawX).toInt()
                    params.y = initialY + (event.rawY - initialTouchY).toInt()
                    windowManager?.updateViewLayout(view, params)
                    true
                }
                else -> false
            }
        }
    }

    private fun runOnUiThread(block: () -> Unit) {
        android.os.Handler(android.os.Looper.getMainLooper()).post(block)
    }

    private fun createNotificationChannel() {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            val channel = NotificationChannel(
                "race_overlay",
                "Race Overlay",
                NotificationManager.IMPORTANCE_LOW
            )
            val manager = getSystemService(NotificationManager::class.java)
            manager.createNotificationChannel(channel)
        }
    }

    private fun createNotification(): Notification {
        return NotificationCompat.Builder(this, "race_overlay")
            .setContentTitle("Race Overlay")
            .setContentText("Position monitoring active")
            .setSmallIcon(android.R.drawable.ic_dialog_info)
            .build()
    }

    override fun onDestroy() {
        super.onDestroy()
        RaceSocket.disconnect()
        overlayView?.let { windowManager?.removeView(it) }
    }

    override fun onBind(intent: Intent?): IBinder? = null
}
```

---

## Configuration

In `SimpleOverlayService.kt`, modify the companion object:

```kotlin
companion object {
    private const val TRACK_ID = 1              // Your track ID
    private const val TEAM_NAME = "Team Rocket" // Your exact team name (case-sensitive!)
}
```

In `RaceSocket.kt`, modify the server URL:

```kotlin
private const val SERVER_URL = "http://192.168.1.100:5000" // Your server IP
```

---

## Getting Track IDs

Query the backend to get available tracks:

```bash
curl http://YOUR_SERVER:5000/api/admin/tracks
```

**Response:**
```json
[
  {
    "id": 1,
    "track_name": "Mariembourg",
    "location": "Belgium"
  },
  {
    "id": 2,
    "track_name": "Spa",
    "location": "Belgium"
  }
]
```

Use the `id` field as `TRACK_ID`.

---

## Getting Team Names

Team names come from the timing system during a race. To find your exact team name:

### Option 1: Listen to track_update

```kotlin
socket.on("track_update") { args ->
    val data = args[0] as JSONObject
    val teams = data.getJSONArray("teams")

    for (i in 0 until teams.length()) {
        val team = teams.getJSONObject(i)
        println("Team: ${team.getString("name")}")
    }
}
```

### Option 2: Check via REST API

```bash
curl http://YOUR_SERVER:5000/api/team-data/search?q=rocket&track_id=1
```

**Important:** Team names are **case-sensitive**. `"Team Rocket"` ≠ `"team rocket"`.

---

## Troubleshooting

### Not Receiving Updates

1. **Check connection:**
   ```kotlin
   RaceSocket.isConnected() // Should return true
   ```

2. **Verify team name is correct** - Must match exactly, case-sensitive

3. **Check if session is active** - No race = no data

4. **Check server is reachable:**
   ```bash
   curl http://YOUR_SERVER:5000/api/tracks/status
   ```

### Overlay Not Showing

1. Overlay permission must be granted
2. Service must be running
3. Check Logcat: `adb logcat | grep SimpleOverlay`

### Wrong Gap Values

- `gap_to_leader` is always relative to P1
- `gap_to_front` is relative to the car directly ahead (P-1)
- `gap_to_behind` is relative to the car directly behind (P+1)
- When you're P1: `gap_to_leader = "Leader"`, `gap_to_front = "-"`

---

## REST API Endpoints (Optional)

### Get Track Status

```bash
GET http://YOUR_SERVER:5000/api/tracks/status
```

**Response:**
```json
{
  "tracks": [
    {
      "track_id": 1,
      "track_name": "Mariembourg",
      "active": true,
      "teams_count": 24
    }
  ]
}
```

### Get Team Statistics

```bash
GET http://YOUR_SERVER:5000/api/team-data/stats?team=Team%20Rocket&track_id=1
```

**Response:**
```json
{
  "team": "Team Rocket",
  "best_lap": "1:01.234",
  "avg_lap": "1:02.567",
  "total_laps": 156,
  "sessions": 3,
  "pit_stops": 4
}
```

---

## Summary

### Required Events

1. **Emit `join_track`** - Subscribe to track updates
2. **Emit `join_team_room`** - Subscribe to your team's updates
3. **Listen to `team_specific_update`** - Get your position and gaps
4. **Listen to `track_update`** - Get all teams (for P2/P3 when you're P1)

### Key Data Points

- `position` - Your current position (1, 2, 3...)
- `gap_to_leader` - Time behind P1 (or "Leader" if you're P1)
- `gap_to_front` - Time behind car ahead
- `gap_to_behind` - Time ahead of car behind

### Layout Logic

```
If position == 1:
  Show: P1 | Gap P2 | Gap P3

Else:
  Show: Gap P1 | Gap P(position-1) | P(position) | Gap P(position+1)
```

---

## Example Values

### When P3:
- `position = 3`
- `gap_to_leader = "+12.345"` → "Gap P1: +12.345"
- `gap_to_front = "+2.156"` → "Gap P2: +2.156"
- `gap_to_behind = "-5.234"` → "Gap P4: -5.234"

### When P1:
- `position = 1`
- `gap_to_leader = "Leader"` → Display "P1"
- `gap_to_front = "-"` → Not shown
- `gap_to_behind = "-8.567"` → "Gap P2: -8.567"
- Find P3 from `track_update` → "Gap P3: -15.234"

---

**End of Documentation**
