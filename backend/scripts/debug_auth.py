"""调试 create_user"""
import json
import sys
import urllib.request
import urllib.error

sys.stdout.reconfigure(encoding='utf-8', errors='replace')
BASE = "http://127.0.0.1:8300/api"

req = urllib.request.Request(
    f"{BASE}/users", method="POST",
    data=json.dumps({"open_id": "ou_admin_test", "name": "Admin", "role": "admin"}).encode(),
    headers={"Content-Type": "application/json"})
try:
    with urllib.request.urlopen(req, timeout=30) as r:
        print(json.loads(r.read()))
except urllib.error.HTTPError as e:
    print(f"HTTP {e.code}: {e.read().decode('utf-8', errors='replace')}")
