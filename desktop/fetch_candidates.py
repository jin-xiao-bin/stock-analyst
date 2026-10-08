"""下载海绵宝宝姿势候选图（pngimg.com 免抠图）"""
import httpx
from pathlib import Path

OUT = Path("desktop/skin_candidates")
OUT.mkdir(exist_ok=True)

HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/126.0",
           "Referer": "https://pngimg.com/images/cartoons/spongebob"}

# 抽样不同编号（覆盖不同姿势概率大）
CANDIDATES = [68, 66, 65, 60, 58, 53, 47, 44, 41, 39, 34, 28, 24, 21, 19]

ok = []
for n in CANDIDATES:
    url = f"https://pngimg.com/uploads/spongebob/spongebob_PNG{n}.png"
    try:
        r = httpx.get(url, headers=HEADERS, timeout=30, follow_redirects=True)
        if r.status_code == 200 and len(r.content) > 10000:
            f = OUT / f"sb_{n}.png"
            f.write_bytes(r.content)
            ok.append((n, len(r.content) // 1024))
            print(f"PNG{n}: {len(r.content)//1024}KB")
        else:
            print(f"PNG{n}: HTTP {r.status_code}")
    except Exception as e:  # noqa: BLE001
        print(f"PNG{n}: FAIL {e}")

print(f"\ndownloaded {len(ok)}")
