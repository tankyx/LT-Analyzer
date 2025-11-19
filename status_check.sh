#!/bin/bash
echo "📊 LT-Analyzer Process Status"
echo "=============================="
echo ""
echo "1️⃣  PM2 PROCESS LIST:"
pm2 list
echo ""
echo "2️⃣  ACTIVE PROCESSES (race_ui):"
ps aux | grep -E "race_ui" | grep -v grep || echo "   No race_ui processes found"
echo ""
echo "3️⃣  PM2 BACKEND STATUS:"
if pm2 list | grep -q "lt-analyzer-backend.*online"; then
  echo "   ✅ Backend is ONLINE"
  pm2 show lt-analyzer-backend 2>&1 | grep -E "status|uptime|pid"
else
  echo "   ❌ Backend is NOT ONLINE"
fi
echo ""
echo "4️⃣  PM2 FRONTEND STATUS:"
if pm2 list | grep -q "lt-analyzer-frontend.*online"; then
  echo "   ✅ Frontend is ONLINE"
  pm2 show lt-analyzer-frontend 2>&1 | grep -E "status|uptime|pid"
else
  echo "   ❌ Frontend is NOT ONLINE"
fi
echo ""
echo "5️⃣  PORT CHECK:"
if ss -tuln | grep -q ":5000"; then echo "   ✅ Port 5000 (Backend) LISTENING"; else echo "   ❌ Port 5000 (Backend) NOT LISTENING"; fi
if ss -tuln | grep -q ":3000"; then echo "   ✅ Port 3000 (Frontend) LISTENING"; else echo "   ❌ Port 3000 (Frontend) NOT LISTENING"; fi
echo ""
echo "6️⃣  API ENDPOINT CHECK:"
curl -s http://localhost:5000/api/admin/tracks 2>&1 | grep -q "race_data" && echo "   ✅ Backend API responding" || echo "   ❌ Backend API not responding"
