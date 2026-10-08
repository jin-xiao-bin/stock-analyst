"""自动去除图片白底：从四边泛洪填充（保留主体内部的白色，如眼睛/衬衫）"""
import sys
from pathlib import Path

import numpy as np
from PIL import Image

SRC = Path.home() / ".pet_trader" / "skins" / "spongebob.jpg"
DST = Path.home() / ".pet_trader" / "skins" / "spongebob_transparent.png"

TOLERANCE = 235   # RGB 均值高于此视为"白"
TOL_COLOR = 30    # 与种子色接近判定（抗 JPEG 噪声）


def remove_white_bg(src: Path, dst: Path):
    img = Image.open(src).convert("RGB")
    arr = np.array(img).astype(int)
    h, w = arr.shape[:2]

    is_bg = np.zeros((h, w), dtype=bool)
    # 种子：四条边上的白色像素
    seeds = []
    for x in range(w):
        for y in (0, h - 1):
            if arr[y, x].mean() >= TOLERANCE:
                seeds.append((y, x))
    for y in range(h):
        for x in (0, w - 1):
            if arr[y, x].mean() >= TOLERANCE:
                seeds.append((y, x))

    # BFS 泛洪：与边缘连通的浅色区域 = 背景
    from collections import deque
    q = deque(seeds)
    for y, x in seeds:
        is_bg[y, x] = True
    while q:
        y, x = q.popleft()
        for dy, dx in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            ny, nx = y + dy, x + dx
            if 0 <= ny < h and 0 <= nx < w and not is_bg[ny, nx]:
                px = arr[ny, nx]
                if px.mean() >= TOLERANCE and abs(int(px[0]) - int(px[1])) < TOL_COLOR \
                        and abs(int(px[1]) - int(px[2])) < TOL_COLOR:
                    is_bg[ny, nx] = True
                    q.append((ny, nx))

    # 生成 RGBA
    rgba = np.dstack([np.array(img), np.where(is_bg, 0, 255).astype("uint8")])
    out = Image.fromarray(rgba, "RGBA")
    out.save(dst)
    removed = is_bg.sum() / (h * w)
    print(f"完成: 去除背景 {removed:.0%}，输出 {dst}")


if __name__ == "__main__":
    remove_white_bg(SRC, DST)
