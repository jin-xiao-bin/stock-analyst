"""归纳总结相互印证闭环 E2E"""
import json
import urllib.request

req = urllib.request.Request("http://127.0.0.1:8300/api/analysis/000001.SZ/synthesis",
                             method="POST", data=b"{}", headers={"Accept": "text/event-stream"})
cur = None
with urllib.request.urlopen(req, timeout=1200) as resp:
    for raw in resp:
        line = raw.decode("utf-8").rstrip("\n")
        if line.startswith("event:"):
            cur = line[6:].strip()
        elif line.startswith("data:") and cur:
            try:
                d = json.loads(line[5:].strip())
            except Exception:  # noqa: BLE001
                d = line[5:].strip()
            if cur == "status":
                print("STATUS", str(d.get("stage")), "-", str(d.get("msg"))[:60])
            elif cur == "section":
                print("SECTION", d.get("role"), "len:", len(str(d.get("content", ""))))
            elif cur == "done":
                print("DONE synthesis_id:", d.get("report_id"))
                print("  data_issues:", len(d.get("data_issues", [])), d.get("data_issues", [])[:3])
                print("  company_updated:", d.get("company_updated"),
                      "-> new company report:", d.get("updated_company_report_id"))
            elif cur == "error":
                print("ERROR", str(d)[:200])
            cur = None
