"""API 全量冒烟测试"""
import sys
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.path.insert(0, ".")

import json
import urllib.request

BASE = "http://127.0.0.1:8300/api"


def get(path):
    try:
        with urllib.request.urlopen(f"{BASE}{path}", timeout=10) as r:
            data = json.loads(r.read())
            return r.status, (len(data) if isinstance(data, list) else "OK")
    except Exception as e:
        return 0, str(e)[:40]


endpoints = [
    ("health", "/health"),
    ("stocks", "/stocks?q=000001"),
    ("daily", "/stocks/000001.SZ/daily?adjust=qfq"),
    ("finance", "/stocks/000001.SZ/finance"),
    ("realtime", "/stocks/601689.SH/realtime"),
    ("replay", "/replay"),
    ("accounts", "/accounts"),
    ("trades", "/trades?page_size=5"),
    ("analysis", "/analysis/all-reports"),
    ("watch-tasks", "/watch-tasks?page_size=5"),
    ("strategies", "/strategies"),
    ("backtests", "/backtests"),
    ("agent-status", "/agent/status"),
    ("agent-decisions", "/agent/decisions?page_size=5"),
    ("agent-equity", "/agent/equity"),
    ("users", "/users"),
    ("users-logs", "/users/logs"),
]

ok = fail = 0
for name, path in endpoints:
    status, detail = get(path)
    s = "PASS" if status == 200 else "FAIL"
    if status == 200:
        ok += 1
    else:
        fail += 1
    print(f"  {s} {name}: {status} ({detail})")

print(f"\n{ok}/{ok + fail} endpoints OK, {fail} failed")
