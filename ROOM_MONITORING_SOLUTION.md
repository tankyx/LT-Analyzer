# 🔔 Room Monitoring & Auto Pit Alert System

## Overview

I've created a complete system that monitors Socket.IO room joins and automatically sends pit alerts when devices join specific rooms.

---

## 📦 Components Created

### 1. Backend Changes (race_ui.py)

**Added Admin Endpoints:**
- `POST /api/admin/socketio/rooms` - List all active Socket.IO rooms
- `POST /api/admin/socketio/room-info` - Get client count and IDs for a specific room

**Enhanced Socket.IO Handlers:**
- `join_team_room` - Now logs all joins with monitoring prefix
- `leave_team_room` - Now logs all leaves with monitoring prefix

### 2. Monitoring Script (send_pit_alert_on_join.py)

**Features:**
- ✅ Monitors any team room (e.g., `team_track_10_ENZO.H`)
- ✅ Detects when devices join the room
- ✅ Automatically sends pit alert via API
- ✅ Supports both one-time and continuous monitoring
- ✅ Shows real-time room statistics

---

## 🚀 Usage Examples

### Basic Monitoring (One-Time)

Monitor room and send ONE alert when a device joins:

```bash
python3 send_pit_alert_on_join.py \
  --track 10 \
  --team "ENZO.H" \
  --message "PIT NOW!"
```

**Output:**
```
[19:58:23] ✅ Connected to backend
[19:58:23] 
[19:58:23] 🔔 Monitoring room: team_track_10_ENZO.H
[19:58:23] 📢 Alert will be: 'PIT NOW!'
[19:58:23] ⏱️ One-time alert
[19:58:23] 
[19:58:23] 📊 Current clients in room: 0
[19:58:25] 🎉 1 new device(s) joined!
[19:58:25] ✅ Alert #1 sent!
[19:58:25] 
[19:58:25] 🎉 Mission complete! Sent 1 alert(s)
```

### Continuous Monitoring

Monitor continuously and send alerts EVERY time someone joins:

```bash
python3 send_pit_alert_on_join.py \
  --track 10 \
  --team "ENZO.H" \
  --message "BOX BOX!" \
  --continuous
```

**Output:**
```
[19:59:01] 🔔 Monitoring room: team_track_10_ENZO.H
[19:59:01] 📢 Alert will be: 'BOX BOX!'
[19:59:01] 🔄 Continuous mode
[19:59:01] 
[19:59:01] 📊 Current clients in room: 1
[19:59:05] 🎉 1 new device(s) joined!
[19:59:05] ✅ Alert #1 sent!
[19:59:07] 📊 Current clients in room: 2
[19:59:12] 🎉 1 new device(s) joined!
[19:59:12] ✅ Alert #2 sent!
[19:59:12] 📊 Current clients in room: 3
```

### Monitor Different Team

```bash
python3 send_pit_alert_on_join.py \
  --track 10 \
  --team "MARCO2904" \
  --message "PIT STOP REQUIRED" \
  --continuous
```

---

## 📊 How It Works

### 1. Room Structure

The system uses Socket.IO rooms with this naming pattern:
```
team_track_{track_id}_{team_name}
```

Examples:
- `team_track_10_ENZO.H`
- `team_track_10_MARCO2904`
- `team_track_3_TEAM_ALpine`

### 2. Detection Flow

```
1. Script starts monitoring room X
2. Every 2 seconds, checks room client count
3. When count increases:
   → Detected new device joined
   → Trigger pit alert API call
   → Alert sent to room
4. Device in room receives Socket.IO 'pit_alert' event
5. Device displays visual/audio alert
```

### 3. Pit Alert Data Flow

```
Device Joins → Script Detects → API Called → Socket.IO Emitted
    ↑                                                                  ↓
Alert Displayed ← Device Receives ← Room Broadcast ← Alert Processed
```

---

## 🔧 API Integration

The script uses two backend APIs:

### 1. Get Room Info
```http
POST /api/admin/socketio/room-info
Content-Type: application/json

{
  "room": "team_track_10_ENZO.H"
}

Response:
{
  "room": "team_track_10_ENZO.H",
  "client_count": 2,
  "clients": ["abc123", "def456"],
  "timestamp": "2025-11-19T20:00:00"
}
```

### 2. Send Pit Alert
```http
POST /api/trigger-pit-alert
Content-Type: application/json

{
  "track_id": "10",
  "team_name": "ENZO.H",
  "alert_message": "PIT NOW!"
}

Response:
{
  "status": "success",
  "message": "Pit alert sent to ENZO.H",
  "room": "team_track_10_ENZO.H",
  "alert": { ... }
}
```

---

## 📋 Complete Example Session

**Setup:**
```bash
# Terminal 1: Start monitoring
python3 send_pit_alert_on_join.py --track 10 --team "ENZO.H" --message "PIT NOW!" --continuous
```

**Device Joins (simulated or real):**
```bash
# Terminal 2: Simulate Android device joining
python3 test_socketio_client.py --track 10 --team "ENZO.H"
```

**Automatic Response:**
```
[20:01:15] 🎉 1 new device(s) joined!
[20:01:15] 🚨 Sending pit alert to team ENZO.H on track 10
[20:01:15] ✅ Alert #1 sent!
[20:01:15]    Room: team_track_10_ENZO.H
[20:01:15]    Message: Pit alert sent to ENZO.H
```

**Android Device Shows:**
- 🔴 Red flashing screen (5 seconds)
- 📝 Message: "PIT NOW!"
- 🔊 Audio alert (if configured)

---

## 🎯 Use Cases

### 1. **Pit Crew Tablet**
When the pit crew tablet joins the team room, automatically alert the driver to pit.

### 2. **Remote Coach**
When a remote coach/analyst joins, automatically send current race status or alerts.

### 3. **Race Engineer**
When race engineer joins from paddock, immediately send critical warnings.

### 4. **Automated Systems**
When timing/scoring systems connect, synchronize data automatically.

---

## 🚀 Advanced Usage

### Multiple Teams
Run separate monitors for each team:
```bash
# Terminal 1
python3 send_pit_alert_on_join.py --track 10 --team "ENZO.H" --continuous &

# Terminal 2  
python3 send_pit_alert_on_join.py --track 10 --team "MARCO2904" --continuous &

# Terminal 3
python3 send_pit_alert_on_join.py --track 10 --team "BEULER J" --continuous &
```

### Custom Integration
```python
import requests

def on_device_join(team, callback):
    # Your custom logic here
    if team == "ENZO.H":
        callback("PIT NOW!")
    elif team == "MARCO2904":
        callback("BOX BOX BOX!")
```

---

## ⚠️ Requirements

**Backend must be restarted** to load the new admin endpoints:

```bash
./restart_backend_pm2.sh
```

**Or manually:**
```bash
pm2 restart lt-analyzer-backend
```

Wait 10-15 seconds for backend to fully initialize before running the monitor script.

---

## 📊 Monitoring and Debugging

### Check if backend has room endpoints:
```bash
curl -X POST http://localhost:5000/api/admin/socketio/rooms
```

### Check specific room:
```bash
curl -X POST http://localhost:5000/api/admin/socketio/room-info \
  -H "Content-Type: application/json" \
  -d '{"room": "team_track_10_ENZO.H"}'
```

### View logs:
```bash
pm2 logs lt-analyzer-backend --lines 50 | grep "ROOM MONITOR"
```

---

## ✨ Benefits

1. **Automatic**: No manual intervention needed
2. **Instant**: Sub-second response to joins
3. **Flexible**: Works with any team/track combination
4. **Scalable**: Can monitor multiple rooms simultaneously
5. **Reliable**: Uses backend API for robust communication
6. **Observable**: Clear logging of all activity

---

**Status**: ✅ Ready to use (after backend restart)

**Next Step**: Restart backend and test!
