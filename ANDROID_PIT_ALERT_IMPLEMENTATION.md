# Android Overlay Pit Alert Implementation Guide

This document describes the implementation of flashing pit alert overlay functionality for the Android Datalogger app, triggered from the LT-Analyzer web interface.

## Overview

When a team manager clicks the 🚨 PIT button in the LT-Analyzer dashboard, the Android overlay app receives a Socket.IO event and displays a flashing alert message to the driver.

## Changes Made to Android Datalogger

### 1. RaceSocket.kt
**File**: `/home/ubuntu/Android_DataLogger/app/src/main/kotlin/com/example/android_datalogger/RaceSocket.kt`

**Added Pit Alert Callback**:
```kotlin
var onPitAlert: ((PitAlertData) -> Unit)? = null
```

**Added Socket.IO Event Listener** (after `team_room_error` handler):
```kotlin
// Pit alert - triggered when team needs to pit
socket?.on("pit_alert") { args ->
    Log.d("RaceSocket", "connect: Received pit_alert")
    val data = args[0] as JSONObject
    val alert = PitAlertData(
        alertType = data.optString("alert_type", "pit_required"),
        alertMessage = data.optString("alert_message", "PIT NOW!"),
        flashColor = data.optString("flash_color", "#FF0000"),
        durationMs = data.optInt("duration_ms", 5000),
        priority = data.optString("priority", "high")
    )
    onPitAlert?.invoke(alert)
}
```

**Added Data Class** (at end of file):
```kotlin
data class PitAlertData(
    val alertType: String,
    val alertMessage: String,
    val flashColor: String,
    val durationMs: Int,
    val priority: String
)
```

### 2. SimpleOverlayService.kt
**File**: `/home/ubuntu/Android_DataLogger/app/src/main/kotlin/com/example/android_datalogger/SimpleOverlayService.kt`

**Added UI Element Reference**:
```kotlin
private var tvPitAlert: TextView? = null
```

**Added Handler Registration** (in `setupSocket()` after `onError`):
```kotlin
RaceSocket.onPitAlert = { alert ->
    runOnUiThread {
        showPitAlert(alert)
    }
}
```

**Added Pit Alert Display Method**:
```kotlin
private fun showPitAlert(alert: PitAlertData) {
    android.util.Log.d("SimpleOverlayService", "showPitAlert: ${alert.alertMessage}, color: ${alert.flashColor}, duration: ${alert.durationMs}")
    
    tvPitAlert?.text = alert.alertMessage
    tvPitAlert?.setBackgroundColor(android.graphics.Color.parseColor(alert.flashColor))
    tvPitAlert?.visibility = View.VISIBLE
    
    // Flash effect: alternate between transparent and solid every 250ms
    val flashDuration = alert.durationMs.toLong()
    val flashInterval = 250L
    val handler = android.os.Handler(android.os.Looper.getMainLooper())
    var elapsedTime = 0L
    var isFlashing = false
    
    val flashRunnable = object : java.lang.Runnable {
        override fun run() {
            if (elapsedTime >= flashDuration) {
                tvPitAlert?.visibility = View.GONE
                return
            }
            
            isFlashing = !isFlashing
            tvPitAlert?.alpha = if (isFlashing) 1.0f else 0.3f
            elapsedTime += flashInterval
            handler.postDelayed(this, flashInterval)
        }
    }
    
    handler.post(flashRunnable)
}
```

### 3. simple_overlay.xml
**File**: `/home/ubuntu/Android_DataLogger/app/src/main/res/layout/simple_overlay.xml`

**Added Pit Alert TextView** (after tv_position):
```xml
<!-- PIT ALERT (appears when triggered) -->
<TextView
    android:id="@+id/tv_pit_alert"
    android:layout_width="match_parent"
    android:layout_height="wrap_content"
    android:text="PIT NOW!"
    android:textSize="36sp"
    android:textStyle="bold"
    android:textColor="#FFFFFF"
    android:gravity="center"
    android:paddingVertical="10dp"
    android:visibility="gone"
    android:alpha="1.0" />
```

## Integration Flow

```
LT-Analyzer Dashboard
    ↓
User clicks 🚨 PIT button
    ↓
POST /api/trigger-pit-alert
    ↓
Socket.IO emits "pit_alert" event to team room
    ↓
Android RaceSocket receives event
    ↓
Invokes onPitAlert callback
    ↓
SimpleOverlayService.showPitAlert()
    ↓
Flashing overlay appears for 5 seconds
```

## Socket.IO Event Format

**Event**: `pit_alert`

**Payload Structure**:
```json
{
    "alert_type": "pit_required",
    "alert_message": "PIT NOW! - Team Name",
    "flash_color": "#FF0000",
    "duration_ms": 5000,
    "priority": "high",
    "timestamp": "2025-11-19T15:01:48.025691"
}
```

**Android Event Handler**:
```kotlin
socket?.on("pit_alert") { args ->
    val data = args[0] as JSONObject
    val alert = PitAlertData(
        alertType = data.optString("alert_type", "pit_required"),
        alertMessage = data.optString("alert_message", "PIT NOW!"),
        flashColor = data.optString("flash_color", "#FF0000"),
        durationMs = data.optInt("duration_ms", 5000),
        priority = data.optString("priority", "high")
    )
    onPitAlert?.invoke(alert)
}
```

## Visual Behavior

1. **Default State**: Pit alert TextView is hidden (visibility="gone")
2. **When Triggered**:
   - TextView becomes visible with alert message
   - Background color set to flash_color (default: red #FF0000)
   - Alpha animates between 1.0 (solid) and 0.3 (transparent) every 250ms
   - Duration: 5 seconds (configurable via backend)
   - After duration: visibility set back to "gone"

## Testing

### Backend Test
Trigger a pit alert via API:
```bash
curl -X POST http://localhost:5000/api/trigger-pit-alert \
  -H "Content-Type: application/json" \
  -d '{
    "track_id": 10,
    "team_name": "Test Team",
    "alert_message": "PIT NOW!"
  }'
```

### Android Logcat
Monitor for these log messages:
```
RaceSocket: Received pit_alert
SimpleOverlayService: showPitAlert: PIT NOW!, color: #FF0000, duration: 5000
```

### Manual Testing
1. Build and install Android app
2. Grant "Display over other apps" permission
3. Connect to active track and select your team
4. From LT-Analyzer dashboard, click 🚨 PIT button next to your team
5. Watch for flashing overlay on Android device

## Build and Deploy

### Prerequisites
- Android Studio Arctic Fox or later
- Kotlin 1.8+
- Target SDK: 31+
- Min SDK: 24

### Dependencies
```gradle
dependencies {
    implementation 'io.socket:socket.io-client:2.1.0'
    implementation 'androidx.core:core-ktx:1.9.0'
    implementation 'androidx.appcompat:appcompat:1.6.0'
    implementation 'com.google.android.material:material:1.8.0'
}
```

### Build
Open project in Android Studio and click "Run" button, or use command line:
```bash
cd /home/ubuntu/Android_DataLogger
android-sdk/cmdline-tools/latest/bin/gradle build
```

### Deploy
- Install APK on Android device
- Grant overlay permission in Settings
- Launch app and connect to track

## Notes

- Requires "Display over other apps" system permission
- Uses screen wake lock to keep display on during racing
- Flashing interval is 250ms but can be adjusted
- Alert duration is controlled by backend (default 5 seconds)
- Overlay is draggable by user
- Works in both portrait and landscape orientations

## Troubleshooting

### Overlay Not Appearing
1. Verify overlay permission granted in Settings
2. Check logcat for "SimpleOverlayService: showPitAlert" message
3. Confirm Socket.IO connection to server

### No Pit Alert Received
1. Verify team name matches exactly (case-sensitive)
2. Check backend logs for `/api/trigger-pit-alert` endpoint
3. Confirm team is in a monitored/active status on track

### Build Errors
1. Ensure Kotlin version matches project requirements
2. Check Socket.IO client library version compatibility
3. Verify Android SDK is properly installed
