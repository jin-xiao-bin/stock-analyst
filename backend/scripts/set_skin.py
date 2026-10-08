"""切换当前形象为透明版海绵宝宝"""
import json
from pathlib import Path

CONFIG_DIR = Path.home() / ".pet_trader"
config_file = CONFIG_DIR / "config.json"
cfg = json.loads(config_file.read_text(encoding="utf-8"))
target = str(CONFIG_DIR / "skins" / "spongebob_transparent.png")
if target not in cfg.get("skins", []):
    cfg.setdefault("skins", []).append(target)
cfg["active_skin"] = target
config_file.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")
print("active_skin ->", target)
