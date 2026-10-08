"""后端 API 客户端（HTTP + SSE）"""
import json
import threading

import httpx

BASE = "http://127.0.0.1:8300/api"


class ApiClient:
    def __init__(self, base: str = BASE):
        self.base = base
        self._client = httpx.Client(timeout=15)

    # ---- 实时行情 ----
    def realtime(self, ts_code: str) -> dict:
        r = self._client.get(f"{self.base}/stocks/{ts_code}/realtime")
        return r.json()

    # ---- 自选股 ----
    def watchlist(self) -> list:
        return self._client.get(f"{self.base}/pet/watchlist").json()

    def watchlist_add(self, ts_code: str) -> dict:
        return self._client.post(f"{self.base}/pet/watchlist",
                                 json={"ts_code": ts_code}).json()

    def watchlist_del(self, row_id: int):
        self._client.delete(f"{self.base}/pet/watchlist/{row_id}")

    # ---- 警报规则 ----
    def rules(self) -> list:
        return self._client.get(f"{self.base}/pet/alert-rules").json()

    def rule_add(self, ts_code: str, rule_type: str, params: dict) -> dict:
        return self._client.post(f"{self.base}/pet/alert-rules",
                                 json={"ts_code": ts_code, "rule_type": rule_type,
                                       "params": params, "enabled": True}).json()

    def rule_del(self, rule_id: int):
        self._client.delete(f"{self.base}/pet/alert-rules/{rule_id}")

    # ---- 对话指令 ----
    def chat(self, text: str) -> dict:
        r = self._client.post(f"{self.base}/pet/chat", json={"text": text}, timeout=300)
        return r.json()

    # ---- agent 状态（待机气泡用） ----
    def agent_status(self) -> list:
        return self._client.get(f"{self.base}/agent/status").json()

    def agent_start(self) -> dict:
        return self._client.post(f"{self.base}/agent/start", json={}).json()

    def agent_stop(self) -> dict:
        return self._client.post(f"{self.base}/agent/stop", json={}).json()

    # ---- SSE 订阅（后台线程） ----
    def subscribe_events(self, on_event, on_error=None):
        """阻塞式 SSE 消费，放在子线程运行。on_event(dict)"""

        def _run():
            try:
                with httpx.stream("GET", f"{self.base}/events/stream", timeout=None) as r:
                    cur_event = None
                    for line in r.iter_lines():
                        if line.startswith("event:"):
                            cur_event = line[6:].strip()
                        elif line.startswith("data:") and cur_event:
                            try:
                                payload = json.loads(line[5:].strip())
                                on_event(cur_event, payload)
                            except json.JSONDecodeError:
                                pass
                            cur_event = None
            except Exception as e:  # noqa: BLE001
                if on_error:
                    on_error(e)

        t = threading.Thread(target=_run, daemon=True, name="sse")
        t.start()
        return t
