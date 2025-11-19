#!/bin/bash
# Restart both backend and frontend with PM2

echo "🔄 Restarting LT-Analyzer (Backend + Frontend)"
echo "==============================================="
echo ""

# Backend restart
echo "1️⃣  BACKEND RESTART"
echo "--------------------"
cd /home/ubuntu/LT-Analyzer
echo "⏹️  Stopping backend..."
pm2 stop lt-analyzer-backend 2>/dev/null || echo "  └─ Not running"
sleep 2

echo "🗑️  Cleaning old config..."
pm2 delete lt-analyzer-backend 2>/dev/null || echo "  └─ No config to delete"

echo "▶️  Starting backend with PM2..."
pm2 start /home/ubuntu/LT-Analyzer/start-backend-pm2.sh \
  --name "lt-analyzer-backend" \
  --output /home/ubuntu/LT-Analyzer/backend.log \
  --error /home/ubuntu/LT-Analyzer/backend.log

echo "✅ Backend restarted"
echo ""

# Frontend restart
echo "2️⃣  FRONTEND RESTART"
echo "---------------------
cd /home/ubuntu/LT-Analyzer/racing-analyzer
echo "⏹️  Stopping frontend..."
pm2 stop lt-analyzer-frontend 2>/dev/null || echo "  └─ Not running"
sleep 2

echo "🗑️  Cleaning old config..."
pm2 delete lt-analyzer-frontend 2>/dev/null || echo "  └─ No config to delete"

echo "▶️  Starting frontend with PM2..."
pm2 start npm --name "lt-analyzer-frontend" -- start

echo "✅ Frontend restarted"
echo ""

# Save configuration
echo "💾 Saving PM2 configuration..."
pm2 save

# Show final status
echo ""
echo "📊 FINAL PM2 STATUS"
echo "==================="
pm2 list

echo ""
echo "✅ LT-Analyzer restarted successfully!"
echo ""
echo "🔗 Access Points:"
echo "   Frontend: https://tpresearch.fr"
echo "   Frontend Direct: http://localhost:3000"
echo "   Backend API: http://localhost:5000"
echo ""
echo "📄 Logs:"
echo "   Backend: pm2 logs lt-analyzer-backend"
echo "   Frontend: pm2 logs lt-analyzer-frontend"
echo "   Combined: tail -f /home/ubuntu/LT-Analyzer/backend.log"
echo ""
echo "🚨 Pit Alert Monitoring:"
echo "   ./monitor_pit_alerts.sh"
echo ""
echo "⏱️  Note: Wait 15-20 seconds for full initialization"
