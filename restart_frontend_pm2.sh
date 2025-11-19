#!/bin/bash
# PM2-based frontend restart script

echo "🔄 Restarting lt-analyzer-frontend with PM2..."
echo "=============================================="

# Step 1: Stop existing PM2 process
echo "⏹️  Step 1: Stopping existing PM2 process..."
pm2 stop lt-analyzer-frontend 2>/dev/null || echo "  └─ Process not running"

# Step 2: Wait for clean shutdown
echo "⏳ Step 2: Waiting for shutdown..."
sleep 2

# Step 3: Delete old PM2 configuration
echo "🗑️  Step 3: Deleting old PM2 configuration..."
pm2 delete lt-analyzer-frontend 2>/dev/null || echo "  └─ No old config"

# Step 4: Start frontend with PM2 in correct directory
echo "▶️  Step 4: Starting frontend with PM2..."
cd /home/ubuntu/LT-Analyzer/racing-analyzer
pm2 start npm --name "lt-analyzer-frontend" -- start

# Step 5: Save PM2 configuration
echo "💾 Step 5: Saving PM2 configuration..."
pm2 save

# Step 6: Show status
echo ""
echo "📊 PM2 Status:"
pm2 list

echo ""
echo "✅ Frontend restarted with PM2!"
echo ""
echo "📄 View logs:"
echo "   pm2 logs lt-analyzer-frontend --lines 30"
echo ""
echo "🔗 Frontend URL:"
echo "   http://localhost:3000 (internal)"
echo "   https://tpresearch.fr (public via Nginx)"
