#!/bin/bash
# PM2-based backend restart script with virtual environment support

echo "🔄 Restarting lt-analyzer-backend with PM2 and proper venv..."
echo "=============================================================="

echo "⏹️  Step 1: Stopping existing PM2 process..."
pm2 stop lt-analyzer-backend 2>/dev/null || echo "  └─ No process running, continuing..."

# Small delay for clean shutdown
echo "⏳ Step 2: Waiting for clean shutdown..."
sleep 2

echo "🗑️  Step 3: Deleting old PM2 configuration..."
pm2 delete lt-analyzer-backend 2>/dev/null || echo "  └─ No old config to delete"

echo "▶️  Step 4: Starting backend with PM2 (using venv Python)..."
pm2 start /home/ubuntu/LT-Analyzer/start-backend-pm2.sh \
  --name "lt-analyzer-backend" \
  --output /home/ubuntu/LT-Analyzer/backend.log \
  --error /home/ubuntu/LT-Analyzer/backend.log

echo "💾 Step 5: Saving PM2 configuration..."
pm2 save

echo ""
echo "📊 PM2 Status:"
echo "-------------"
pm2 list

echo ""
echo "✅ Backend restarted with PM2!"
echo ""
echo "📄 View logs:"
echo "   pm2 logs lt-analyzer-backend --lines 50"
echo "   tail -f /home/ubuntu/LT-Analyzer/backend.log"
echo ""
echo "🔔 To monitor pit alerts (after restart):"
echo "   ./monitor_pit_alerts.sh"
echo ""
echo "🧪 To test pit alert:"
echo "   python3 /home/ubuntu/LT-Analyzer/test_pit_alert.py"
echo ""
echo "⚠️  Note: Wait 10-15 seconds for backend to fully initialize"