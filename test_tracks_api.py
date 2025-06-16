#!/usr/bin/env python3
import requests

# Test the tracks API endpoint
try:
    response = requests.get('http://localhost:5000/api/tracks')
    print(f"Status Code: {response.status_code}")
    print(f"Response: {response.json()}")
except Exception as e:
    print(f"Error: {e}")