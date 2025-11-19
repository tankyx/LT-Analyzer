# Pit Alert System Implementation

## Overview
This document describes the implementation of a Pit Alert feature that allows the web client to trigger flashing alerts on Android overlay clients.

## Architecture

```
Web Client (React) → API Call → Flask Backend → Socket.IO → Android Client
     ↓              ↓              ↓              ↓              ↓
PIT Button   POST /api/trigger    Process      Emit Event     Receive &
  Click       -pit-alert        Request     pit_alert      Flash UI
```

## Implementation Details

### 1. Backend API Endpoint (`race_ui.py`)

**New Endpoint:** `POST /api/trigger-pit-alert`

**Request Body:**
```json
{
  "track_id": 1,
  "team_name": "Team Rocket",
  "alert_message": "PIT NOW!"  // optional
}
```

**Response:**
```json
{
  "status": "success",
  "message": "Pit alert sent to Team Rocket",
  "room": "team_track_1_Team Rocket",
  "alert": { ... }
}
```

**Socket.IO Events Emitted:**
- `pit_alert` → Team-specific room (Android devices)
- `pit_alert_broadcast` → Track room (web clients)

### 2. Frontend React Component

**New File:** Updated `app/services/ApiService.ts`

**New Method:**
```typescript
triggerPitAlert: async (data: { 
  track_id: number; 
  team_name: string; 
  alert_message?: string 
}) => {
  // Returns: { status: 'success'|'error', message: string }
}
```

**New Component:** `PitAlertButton`
- Shows 🚨 PIT button for monitored teams
- Located in Monitor column next to StarIcon
- Only visible when team is NOT already in pits
- Loading state with spinner while sending

**Integration:**
- Added to each team row in Standings table
- Button appears for monitored teams with green left border
- Click triggers API call and shows alert confirmation

**Alert Feedback:**
- Success: "🚨 PIT ALERT sent to {TeamName}"
- Error: "❌ Failed to send pit alert..."

### 3. Socket.IO Event Payload

**Event Name:** `pit_alert`

**Payload sent to Android:**
```json
{
  "track_id": 1,
  "team_name": "Team Rocket",
  "alert_type": "pit_required",
  "alert_message": "PIT NOW!",
  "timestamp": "2025-11-19T14:30:00",
  "flash_color": "#FF0000",
  "duration_ms": 5000,
  "priority": "high"
}
```

### 4. Usage Flow

1. **Setup:**
   - Open web client: `http://localhost:3000`
   - Select track from dropdown
   - Monitor a team (click star icon)
   - Team row gets colored left border

2. **Trigger Alert:**
   - Click "🚨 PIT" button in Monitor column
   - Button shows spinner while sending
   - Alert confirmation appears at top
   - Backend emits event to team room

3. **Android Client:** (Needs implementation)
   - Listen for `pit_alert` event
   - Flash overlay with red/black
   - Show "PIT NOW!" message
   - Auto-clear after 5 seconds

## Required Android Client Implementation

### File: `RaceSocket.kt` (Android)

Add to socket event listeners:

```kotlin
socket?.on("pit_alert") { args ->
    val data = args[0] as JSONObject
    val alert = PitAlert(
        teamName = data.getString("team_name"),
        message = data.getString("alert_message"),
        durationMs = data.getLong("duration_ms"),
        color = data.getString("flash_color")
    )
    onPitAlert?.invoke(alert)
}
```

### File: `SimpleOverlayService.kt` (Android)

Add pit alert display:

```kotlin
private fun handlePitAlert(alert: PitAlert) {
    // Flash the overlay
    overlayView?.setBackgroundColor(Color.parseColor(alert.color))
    
    // Show "PIT NOW!" message
    tvPosition?.text = "PIT!"
    tvPosition?.setTextColor(Color.BLACK)
    
    // Flash effect (alternating colors)
    val flashRunnable = object : Runnable {
        var flashCount = 0
        override fun run() {
            if (flashCount < 10) { // 5 seconds at 500ms intervals
                val isRed = flashCount % 2 == 0
                overlayView?.setBackgroundColor(if (isRed) Color.RED else Color.BLACK)
                tvPosition?.setTextColor(if (isRed) Color.BLACK else Color.RED)
                
                android.os.Handler().postDelayed(this, 500)
                flashCount++
            } else {
                // Reset to normal
                overlayView?.setBackgroundColor(Color.parseColor("#CC000000"))
                tvPosition?.setTextColor(Color.WHITE)
                updateDisplay(lastTeamUpdate) // Restore normal data
            }
        }
    }
    
    // Start flashing
    android.os.Handler().post(flashRunnable)
}
```

## Files Modified

### Frontend
- `app/services/ApiService.ts` - Added `triggerPitAlert` method
- `app/components/RaceDashboard/index.tsx` - Added PitAlertButton component and integration

### Backend
- `race_ui.py` - Added `/api/trigger-pit-alert` endpoint and Socket.IO event emitters

## Testing

### Manual Test
1. Monitor a team in web client
2. Click "🚨 PIT" button
3. Check PM2 logs: `pm2 logs lt-analyzer-backend --lines 20`
4. Verify event emission in logs

### API Test
```bash
curl -X POST http://localhost:5000/api/trigger-pit-alert \
  -H "Content-Type: application/json" \
  -d '{
    "track_id": 1,
    "team_name": "Test Team",
    "alert_message": "PIT NOW!"
  }'
```

Expected response:
```json
{"status":"success","message":"Pit alert sent to Test Team",...}
```

## Known Limitations

1. **Android Client Required**: The Android overlay app needs to implement the `pit_alert` event listener
2. **No Acknowledgment**: Currently no confirmation from Android that alert was received
3. **Single Team**: Alert goes to one team only (not broadcast to all)
4. **No Queue**: Multiple rapid clicks will queue multiple alerts

## Future Enhancements

1. Add Android acknowledgment channel
2. Queue management for multiple alerts
3. Sound/vibration on Android device
4. Alert history logging
5. Web client shows Android receipt status
6. Team-specific alert tones/vibration patterns

## Security Considerations

- No authentication required for alerts (relies on network access control)
- Consider adding API key or user authentication for production
- Rate limiting to prevent spam
- Alert flooding protection

---

**Implementation Date:** 2025-11-19  
**Backend Version:** Flask + Socket.IO  
**Frontend Version:** Next.js 15 + React 19  
**Android Protocol:** Socket.IO Client
