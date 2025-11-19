#!/usr/bin/env python3
"""
Test script to verify pit alert functionality
"""

import requests
import json
import sys

# Test the pit alert API
test_data = {
    "track_id": "10",
    "team_name": "ENZO.H",
    "alert_message": "PIT NOW - Test alert"
}

try:
    response = requests.post(
        'http://localhost:5000/api/trigger-pit-alert',
        json=test_data,
        headers={'Content-Type': 'application/json'}
    )
    
    print(f"Status Code: {response.status_code}")
    print(f"Response: {json.dumps(response.json(), indent=2)}")
    
    if response.status_code == 200:
        print("\n✅ Pit alert API is working!")
        sys.exit(0)
    else:
        print(f"\n❌ Pit alert API returned error: {response.status_code}")
        sys.exit(1)
        
except Exception as e:
    print(f"\n❌ Failed to test pit alert: {e}")
    sys.exit(1)
