"""宠物本地配置：JSON 存储（形象/交互映射/菜单自定义/边缘隐藏）"""
import json
import logging
from pathlib import Path

log = logging.getLogger(__name__)

CONFIG_DIR = Path.home() / ".pet_trader"
CONFIG_FILE = CONFIG_DIR / "config.json"

DEFAULT_CONFIG = {
    "skins": [],                 # 用户上传的图片路径列表
    "active_skin": "",           # 当前使用的形象（路径 或 ""=默认程序绘制）
    "click_action": "menu",      # menu / chat / home
    "double_click_action": "chat",
    "menu_items": {              # 可见性
        "home": True, "chat": True, "rules": True, "agent_toggle": True,
        "hide": True, "quit": True,
    },
    "menu_order": ["home", "chat", "rules", "agent_toggle", "hide", "quit"],
    "edge_hide": True,           # 拖到左右边缘自动贴边隐藏
}


def load_config() -> dict:
    try:
        if CONFIG_FILE.exists():
            cfg = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
            merged = {**DEFAULT_CONFIG, **cfg}
            return merged
    except Exception as e:  # noqa: BLE001
        log.warning("配置读取失败，使用默认: %s", e)
    return json.loads(json.dumps(DEFAULT_CONFIG))


def save_config(cfg: dict):
    try:
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        CONFIG_FILE.write_text(json.dumps(cfg, ensure_ascii=False, indent=2),
                               encoding="utf-8")
    except Exception as e:  # noqa: BLE001
        log.warning("配置保存失败: %s", e)
