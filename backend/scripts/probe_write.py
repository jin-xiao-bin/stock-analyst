import tempfile
from pathlib import Path

base = Path(r"D:\wokerTest\deepseekHarness\stock-analyst\backend\tmp\analysis")
d = Path(tempfile.mkdtemp(prefix="000001_SZ_probe_", dir=base))
print("mkdtemp:", d)
try:
    (d / "data_model.md").write_text("test", encoding="utf-8")
    print("write OK")
except PermissionError as e:
    print("WRITE DENIED:", e)
