"""把候选姿势拼成一张带编号的选样大图"""
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

SRC = Path("desktop/skin_candidates")
files = sorted(SRC.glob("sb_*.png"), key=lambda p: int(p.stem.split("_")[1]))

TH = 300          # 缩略图高
COLS = 5
PAD = 20
LABEL_H = 36

rows = (len(files) + COLS - 1) // COLS
cell_w = TH + PAD * 2
cell_h = TH + PAD * 2 + LABEL_H
sheet = Image.new("RGB", (cell_w * COLS, cell_h * rows), (245, 247, 250))
draw = ImageDraw.Draw(sheet)
try:
    font = ImageFont.truetype("msyh.ttc", 26)
except OSError:
    font = ImageFont.load_default()

for i, f in enumerate(files):
    img = Image.open(f).convert("RGBA")
    img.thumbnail((TH, TH))
    bg = Image.new("RGBA", img.size, (255, 255, 255, 255))
    composed = Image.alpha_composite(bg, img).convert("RGB")
    r, c = divmod(i, COLS)
    x = c * cell_w + PAD + (TH - composed.width) // 2
    y = r * cell_h + PAD + (TH - composed.height) // 2
    sheet.paste(composed, (x, y))
    num = f.stem.split("_")[1]
    draw.text((c * cell_w + cell_w // 2 - 30, r * cell_h + PAD + TH + 6),
              f"#{num}", fill=(48, 49, 51), font=font)

out = SRC / "contact_sheet.jpg"
sheet.save(out, quality=88)
print("saved:", out, sheet.size)
