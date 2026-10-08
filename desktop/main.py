"""桌面宠物入口：python desktop/main.py（需后端 8300 运行；依赖 PySide6）"""
import sys
import webbrowser
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication

from api_client import ApiClient
from config_store import load_config, save_config
from pet_widget import PetWindow, ReplyBridge
from tray import TrayIcon
from watch_engine import WatchEngine


def main():
    # ---- 单实例锁：已有宠物运行时直接退出，防止重复启动 ----
    from PySide6.QtNetwork import QLocalServer, QLocalSocket
    lock = QLocalSocket()
    lock.connectToServer("pet_trader_lock")
    if lock.waitForConnected(200):
        lock.disconnectFromServer()
        print("已有桌面宠物实例在运行，本次退出。")
        sys.exit(0)
    QLocalServer.removeServer("pet_trader_lock")
    server = QLocalServer()
    server.listen("pet_trader_lock")

    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)

    api = ApiClient()
    cfg = load_config()
    bridge = ReplyBridge()
    pet = PetWindow(api, bridge)
    pet.show()
    pet._move_to_bottom_right()

    # ---- 设置面板打开器（注入 pet）----
    def open_settings():
        from settings_panel import SettingsDialog
        dlg = SettingsDialog(load_config(), on_apply=apply_config, parent=pet)
        dlg.exec()

    def apply_config():
        """设置保存后重新加载并应用到宠物窗口"""
        pet.cfg = load_config()
        pet._skin_key = None  # 强制重载形象
        pet.update()
        ElMessage_if_possible("宠物设置已应用")

    def ElMessage_if_possible(msg):
        try:
            pet.show_reply(msg)
        except Exception:  # noqa: BLE001
            pass

    pet.open_settings = open_settings

    # ---- 盯盘引擎 ----
    engine = WatchEngine(api, on_alert=lambda code, title, text, imp:
                         pet.alert(code, title, text, imp))
    engine.start()

    # ---- SSE 事件流 ----
    def on_event(event_type: str, payload: dict):
        pet.show_event(event_type, payload, important=bool(payload.get("important")))

    def on_sse_error(_e):
        pet.show_reply("与后端连接中断，10 秒后重连...")
        QTimer.singleShot(10000, lambda: api.subscribe_events(on_event, on_sse_error))

    api.subscribe_events(on_event, on_sse_error)

    # ---- 托盘（含设置入口）----
    tray = TrayIcon(pet, on_quit=app.quit, on_settings=open_settings)

    # 点击映射 "home" 打开首页需要 webbrowser
    pet._fire_mapped_home = lambda: webbrowser.open("http://localhost:5173")

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
