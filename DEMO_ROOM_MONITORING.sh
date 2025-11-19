#!/bin/bash

echo "╔═══════════════════════════════════════════════════════════════╗"
echo "║  🔔 ROOM MONITORING & AUTO PIT ALERT DEMO                     ║"
echo "╚═══════════════════════════════════════════════════════════════╝"
echo ""

# Check if backend is running
if ! pgrep -f "race_ui.py" > /dev/null; then
    echo "❌ Backend is not running!"
    echo "   Start with: pm2 start lt-analyzer-backend"
    exit 1
fi

echo "✅ Backend is running"
echo ""

# Test room endpoint
echo "📡 Testing admin endpoints..."
RESPONSE=$(curl -s -X POST http://localhost:5000/api/admin/socketio/rooms 2>&1)
if echo "$RESPONSE" | grep -q "error"; then
    echo "⚠️  Admin endpoints not available yet"
    echo ""
    echo "🔧 RESTART REQUIRED:"
    echo "   Run: pm2 restart lt-analyzer-backend"
    echo "   Wait 15 seconds, then run this demo again"
    echo ""
    echo "OR manually start with new code:"
    echo "   cd /home/ubuntu/LT-Analyzer"
    echo "   source racing-venv/bin/activate"
    echo "   python race_ui.py --multi-track --config multi-track-config.yml"
    exit 1
else
    echo "✅ Admin endpoints working"
fi

echo ""
echo "📊 Current Active Rooms:"
curl -s -X POST http://localhost:5000/api/admin/socketio/rooms | jq '.' 2>/dev/null || echo "  (No rooms or not JSON)"

echo ""
echo "🏁 DEMO SCENARIOS:"
echo "=================="
echo ""
echo "1️⃣  MONITOR ENZO.H (One-time)"
echo "   Command: python3 send_pit_alert_on_join.py --track 10 --team 'ENZO.H' --message 'PIT NOW!'"
echo ""
echo "2️⃣  MONITOR MARCO2904 (Continuous)"
echo "   Command: python3 send_pit_alert_on_join.py --track 10 --team 'MARCO2904' --continuous"
echo ""
echo "3️⃣  MONITOR WITH CUSTOM MESSAGE"
echo "   Command: python3 send_pit_alert_on_join.py --track 10 --team 'BEULER J' --message 'BOX BOX!' --continuous"
echo ""
echo "4️⃣  CHECK ROOM STATUS"
echo "   Command: curl -X POST http://localhost:5000/api/admin/socketio/room-info \\"
echo "          -H 'Content-Type: application/json' \\"
echo "          -d '{\"room\": \"team_track_10_ENZO.H\"}'"
echo ""
echo "📝 NOTES:"
echo "   • Run in separate terminal windows for multiple teams"
echo "   • Add '&' at end for background mode"
echo "   • Use Ctrl+C to stop monitoring"
echo "   • Check logs: pm2 logs lt-analyzer-backend --lines 30 | grep ROOM"
echo ""
echo "📚 Full documentation: ROOM_MONITORING_SOLUTION.md"
echo ""

read -p "Press Enter to run demo scenario #1 (monitor ENZO.H)..."
echo ""
echo "🔔 Starting monitor for ENZO.H (will timeout after 30 seconds)..."
echo "    (In another terminal, simulate a join to see the alert)"
echo ""

timeout 30 python3 send_pit_alert_on_join.py --track 10 --team "ENZO.H" --message "PIT NOW DEMO!"

echo ""
echo "✅ Demo complete!"
echo ""
echo "🎯 To test with real device:"
echo "   Have your Android device join room: team_track_10_ENZO.H"
echo "   The script will automatically detect and send pit alert!"
