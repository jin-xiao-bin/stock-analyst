"""把海绵宝宝图片安装为桌面宠物当前形象"""
import json
import shutil
from pathlib import Path

SRC = r"C:\Users\jinxiaobin\.dsh\attachments\v1\objects\5f\5f9b1b8558a835410230fb013e003be8263ed5d8267b989a58aa63f8e1aa01fa"
CONFIG_DIR = Path.home() / ".pet_trader"
SKINS_DIR = CONFIG_DIR / "skins"
DEST = SKINS_DIR / "spongebob.jpg"

SKINS_DIR.mkdir(parents=True, exist_ok=True)
shutil.copy(SRC, DEST)

config_file = CONFIG_DIR / "config.json"
cfg = json.loads(config_file.read_text(encoding="utf-8")) if config_file.exists() else {}
skins = cfg.get("skins", [])
if str(DEST) not in skins:
    skins.append(str(DEST))
cfg["skins"] = skins
cfg["active_skin"] = str(DEST)
config_file.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")
print("installed:", DEST)
print("active_skin set, skins total:", len(skins))
