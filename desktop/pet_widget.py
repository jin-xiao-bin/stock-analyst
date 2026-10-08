"""宠物窗口：动画/图片形象、拖拽、右上角×、左右边缘贴边隐藏、单击双击映射、自定义菜单"""
import json
import webbrowser

from PySide6.QtCore import QObject, QPoint, QRect, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QPainter, QPixmap
from PySide6.QtWidgets import (QApplication, QLabel, QLineEdit, QMenu, QWidget)

from api_client import ApiClient
from config_store import load_config, save_config
from pet_draw import draw_pet

STYLE_MAP = {"watch_triggered": "alert", "agent_trade": "alert",
             "agent_halt": "sad", "backtest_done": "happy", "test": "idle"}

EDGE_ZONE = 12      # 拖拽进入边缘判定区(像素)
EDGE_PEEK = 8       # 贴边隐藏后露出的宽度
CLICK_MS = 260      # 单击/双击区分窗口


class ReplySignal(QObject):
    fired = Signal(str)


class PetWindow(QWidget):
    """透明置顶宠物窗口（支持图片形象、边缘隐藏、交互映射、自定义菜单）"""

    def __init__(self, api: ApiClient, bridge: "ReplyBridge"):
        super().__init__()
        self.api = api
        self.bridge = bridge
        self.cfg = load_config()

        self.state = "idle"
        self.tick = 0
        self._squash_at = None  # Q弹触发帧
        self._drag_pos = None
        self._dragging = False
        self._docked = None          # 'left' / 'right' / None
        self._pre_dock_pos = None
        self.confirm_pending: str | None = None
        self.chat_busy = False

        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.resize(230, 210)
        self._move_to_bottom_right()

        # 通知气泡（告警/事件展示，保留）
        self.chat_reply = QLabel(self)
        self.chat_reply.setStyleSheet(
            "QLabel { background: rgba(255,255,255,240); border: 1px solid #409eff;"
            " border-radius: 8px; padding: 6px; font-size: 12px; color: #303133; }")
        self.chat_reply.setWordWrap(True)
        self.chat_reply.hide()

        # 右上角 × （悬停时显示）
        self.close_btn = QLabel("✕", self)
        self.close_btn.setAlignment(Qt.AlignCenter)
        self.close_btn.setFixedSize(18, 18)
        self.close_btn.setStyleSheet(
            "QLabel { background: rgba(0,0,0,120); color:#fff; border-radius: 9px;"
            " font-size: 11px; }"
            "QLabel:hover { background: rgba(245,108,108,220); }")
        self.close_btn.hide()
        self.close_btn.setCursor(Qt.PointingHandCursor)
        self._place_close_btn()
        self.close_btn.mousePressEvent = lambda e: self._hide_to_tray()

        # 动画
        self.timer = QTimer(self)
        self.timer.timeout.connect(self._animate)
        self.timer.start(50)

        # 单击/双击判定
        self._click_timer = QTimer(self)
        self._click_timer.setSingleShot(True)
        self._click_timer.timeout.connect(self._fire_single_click)
        self._press_pending = False

        # 皮肤缓存
        self._skin_pix: QPixmap | None = None
        self._skin_key = None

    # ============ 位置与形象 ============
    def _move_to_bottom_right(self):
        screen = QApplication.primaryScreen().availableGeometry()
        self.move(screen.width() - self.width() - 20,
                  screen.height() - self.height() - 40)

    def _place_close_btn(self):
        self.close_btn.move(self.width() - 22, 2)

    def _skin_pixmap(self) -> QPixmap | None:
        path = self.cfg.get("active_skin")
        if not path:
            return None
        cur_key = (path, self.devicePixelRatioF())
        if self._skin_key == cur_key and self._skin_pix is not None:
            return self._skin_pix
        try:
            pix = QPixmap(path)
            if pix.isNull():
                return None
            # 高 DPI 防模糊：按物理像素缩放并设置 devicePixelRatio
            dpr = self.devicePixelRatioF()
            target = QSize(int(self.width() * dpr), int(self.height() * dpr))
            scaled = pix.scaled(target, Qt.KeepAspectRatio, Qt.SmoothTransformation)
            scaled.setDevicePixelRatio(dpr)
            self._skin_pix = scaled
            self._skin_key = cur_key
            return self._skin_pix
        except Exception:  # noqa: BLE001
            return None

    # ============ 动画参数（图片形象与绘制形象共用变换） ============
    def _anim_params(self):
        """返回 (dx, dy, 旋转角, sx, sy, 透明度)"""
        import math
        t = self.tick
        s = self.state
        # Q弹（事件到来时触发的挤压拉伸）
        squash = 0.0
        if self._squash_at is not None and t - self._squash_at < 12:
            ph = (t - self._squash_at) / 12 * math.pi
            squash = math.sin(ph) * 0.12
        if s == "idle" or s == "talk":
            dy = math.sin(t / 12 if s == "idle" else t / 10) * 3
            return (0, dy, 0, 1 + squash, 1 - squash * 0.6, 1.0)
        if s == "alert":
            dy = -abs(math.sin(t / 4)) * 8
            k = 1 + math.sin(t / 2) * 0.06
            return (0, dy, 0, k + squash, k - squash * 0.6, 1.0)
        if s == "happy":
            rot = math.sin(t / 3) * 8
            k = 1 + abs(math.sin(t / 6)) * 0.05
            return (0, math.sin(t / 8) * 2, rot, k, k, 1.0)
        if s == "sad":
            return (0, 5, 0, 1, 0.97, 0.55)
        return (0, 0, 0, 1 + squash, 1 - squash * 0.6, 1.0)

    # ============ 绘制 ============
    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setRenderHint(QPainter.SmoothPixmapTransform)
        dx, dy, rot, sx, sy, opacity = self._anim_params()
        if dx or dy or rot or sx != 1 or sy != 1 or opacity != 1:
            cx, cy = self.width() / 2, self.height() / 2
            p.translate(cx + dx, cy + dy)
            if rot:
                p.rotate(rot)
            p.scale(sx, sy)
            p.translate(-cx, -cy)
        if opacity != 1:
            p.setOpacity(opacity)
        skin = self._skin_pixmap()
        if skin:
            p.drawPixmap(int((self.width() - skin.width() / skin.devicePixelRatio()) // 2),
                         int((self.height() - skin.height() / skin.devicePixelRatio()) // 2),
                         skin)
        else:
            draw_pet(p, self.state, self.tick, self.width(), self.height())

    def _animate(self):
        self.tick += 1
        self.update()

    def set_state(self, state: str, revert_ms: int = 0):
        self.state = STYLE_MAP.get(state, state)
        self.update()
        if revert_ms:
            QTimer.singleShot(revert_ms, lambda: self.set_state("idle"))

    # ============ 鼠标：拖拽 / 边缘隐藏 / 单双击 ============
    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            self._drag_pos = e.globalPosition().toPoint() - self.frameGeometry().topLeft()
            self._dragging = False
            if self._docked:
                self._undock()

    def mouseMoveEvent(self, e):
        if e.buttons() & Qt.LeftButton and self._drag_pos is not None:
            self._dragging = True
            self.move(e.globalPosition().toPoint() - self._drag_pos)
            self._place_close_btn()
            # 拖到左右边缘 → 贴边隐藏
            if self.cfg.get("edge_hide", True):
                screen = QApplication.primaryScreen().availableGeometry()
                if self.x() <= screen.left() + EDGE_ZONE:
                    self._dock("left")
                elif self.x() + self.width() >= screen.right() - EDGE_ZONE:
                    self._dock("right")

    def mouseReleaseEvent(self, e):
        if e.button() != Qt.LeftButton:
            return
        moved = self._dragging
        self._drag_pos = None
        self._dragging = False
        if moved:
            return
        # 未移动 → 单击/双击判定
        if self._press_pending:
            self._press_pending = False
            self._click_timer.stop()
            self._fire_mapped(self.cfg.get("double_click_action", "chat"))
        else:
            self._press_pending = True
            self._click_timer.start(CLICK_MS)

    def _fire_single_click(self):
        self._press_pending = False
        self._fire_mapped(self.cfg.get("click_action", "menu"))

    def _dock(self, side: str):
        self._docked = side
        self._pre_dock_pos = self.pos()
        screen = QApplication.primaryScreen().availableGeometry()
        y = max(screen.top(), min(self.y(), screen.bottom() - 60))
        if side == "left":
            self.move(screen.left() - self.width() + EDGE_PEEK, y)
        else:
            self.move(screen.right() - EDGE_PEEK + 1, y)
        self._show_edge_strip(side)

    def _undock(self):
        self._hide_edge_strip()
        if self._pre_dock_pos is not None:
            self.move(self._pre_dock_pos)
        self._docked = None

    def _show_edge_strip(self, side: str):
        """贴边隐藏后，在屏幕边缘显示一条可见的橙色小边条，点击唤出宠物"""
        if getattr(self, "_edge_strip", None) is not None:
            return
        screen = QApplication.primaryScreen().availableGeometry()
        strip = QWidget(None, Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
        strip.setFixedSize(14, 160)
        y = max(screen.top(), min(self._pre_dock_pos.y() if self._pre_dock_pos else 200,
                                  screen.bottom() - 170))
        if side == "left":
            strip.move(screen.left(), y)
        else:
            strip.move(screen.right() - strip.width() + 1, y)
        strip.setStyleSheet(
            "background: qlineargradient(x1:0,y1:0,x2:1,y2:0,"
            " stop:0 rgba(230,162,60,230), stop:1 rgba(230,162,60,90));"
            " border-radius: 4px;")
        strip.setToolTip("点击唤出交易助手")
        strip.setCursor(Qt.PointingHandCursor)
        strip.mousePressEvent = lambda e: (self._hide_edge_strip(), self._undock(), self.show())
        strip.show()
        self._edge_strip = strip

    def _hide_edge_strip(self):
        strip = getattr(self, "_edge_strip", None)
        if strip is not None:
            strip.hide()
            strip.deleteLater()
            self._edge_strip = None

    def leaveEvent(self, e):
        self.close_btn.hide()

    # ============ 交互映射与菜单 ============
    def _fire_mapped(self, action: str):
        if action == "chat":
            action = "menu"  # 对话功能暂时下线，回退能力菜单
        if action == "menu":
            self.show_menu()
        elif action == "home":
            webbrowser.open("http://localhost:5173")

    ACTIONS = {
        "home": "打开交易系统首页",
        "chat": "对话",
        "menu": "能力菜单",
    }

    def show_menu(self):
        menu = QMenu()
        order = self.cfg.get("menu_order") or []
        visible = self.cfg.get("menu_items") or {}

        def add_item(item_id: str, label: str, fn):
            if visible.get(item_id, True):
                menu.addAction(label, fn)

        for item_id in order:
            if item_id == "home":
                add_item("home", "🏠 打开交易系统首页",
                         lambda: webbrowser.open("http://localhost:5173"))
            elif item_id == "chat":
                continue  # 对话功能暂时下线
            elif item_id == "rules":
                add_item("rules", "🔔 盯盘设置",
                         lambda: webbrowser.open("http://localhost:5173/agent"))
            elif item_id == "agent_toggle":
                add_item("agent_toggle", "▶ 启动/停止 Agent", self._toggle_agent)
            elif item_id == "hide":
                add_item("hide", "🙈 隐藏宠物", self._hide_to_tray)
            elif item_id == "quit":
                add_item("quit", "❌ 退出", QApplication.quit)
        menu.addSeparator()
        menu.addAction("⚙ 设置...", lambda: self.open_settings())
        menu.exec(self.mapToGlobal(QPoint(self.width() // 2, 0)))

    class SettingsSignal(QObject):
        fired = Signal()

    settings_signal: SettingsSignal = None  # main 注入实例

    def _toggle_agent(self):
        try:
            cfg_list = self.api.agent_status()
            running = cfg_list and cfg_list[0].get("status") == "running"
            (self.api.stop_agent if running else self.api.start_agent)()
        except Exception as e:  # noqa: BLE001
            print("agent toggle failed:", e)

    def _hide_to_tray(self):
        self.hide()
        self.tray.showMessage("交易助手", "宠物已隐藏，点击托盘图标恢复",
                              QSystemTrayIcon.Information, 3000)

    # ---- 托盘引用（main 注入）----

    def open_settings(self):
        """main 注入实现"""
        pass  # main.py 会替换为打开设置面板的函数

    # ============ 对话 ============
    def show_reply(self, text: str):
        self.chat_reply.setText(text)
        self.chat_reply.adjustSize()
        w = max(280, self.width())
        self.chat_reply.setFixedWidth(w - 20)
        self.chat_reply.setGeometry(10, self.height() - 40 - (self.chat_reply.height() + 8),
                                    w - 20, self.chat_reply.height())
        self.chat_reply.show()
        self.set_state("talk")
        QTimer.singleShot(10000, lambda: self.chat_reply.hide())

    def show_event(self, event_type: str, payload: dict, important: bool):
        self._squash_at = self.tick  # Q弹
        self.set_state("alert" if important else "idle", revert_ms=8000)
        self.show_reply(self._friendly_event(event_type, payload))
        QApplication.beep()
        if important:
            QTimer.singleShot(400, QApplication.beep)

    @staticmethod
    def _friendly_event(event_type: str, payload: dict) -> str:
        """事件 → 友好文案"""
        code = payload.get("ts_code", "")
        if event_type == "watch_triggered":
            return (f"🔔 观察任务触发｜{code}\n"
                    f"{payload.get('detail', '')}\n（点击「自主决策」页查看详情）")
        if event_type == "agent_trade":
            action = payload.get("action", "")
            verb = "买入" if action == "buy" else "卖出"
            return (f"🤖 Agent {verb}｜{code}\n"
                    f"{payload.get('qty')} 股 @ {payload.get('price')}\n"
                    f"理由：{payload.get('reason', '')}")
        if event_type == "agent_halt":
            return (f"⛔ 风控熔断｜{code}\n"
                    f"回撤 {payload.get('drawdown', 0):.1%}，"
                    f"暂停开仓至 {payload.get('pause_until')}")
        if event_type == "backtest_done":
            return "回测完成，可到「回测历史」查看结果"
        return f"📢 {event_type}: {json.dumps(payload, ensure_ascii=False)[:100]}"

    def alert(self, ts_code: str, title: str, text: str, important: bool):
        self._squash_at = self.tick  # Q弹
        self.set_state("alert", revert_ms=8000)
        self.show_reply(f"🚨 {title}\n{text}")
        QApplication.beep()
        if important:
            QTimer.singleShot(400, QApplication.beep)


class ReplyBridge(QObject):
    """后台线程 → Qt 主线程 回复桥"""

    fired = Signal(str)

    def bind(self, pet: PetWindow):
        self.fired.connect(pet.show_reply)
        self.fired.connect(lambda _: setattr(pet, "chat_busy", False))


def send_chat_async(pet: PetWindow, payload: dict, bridge: ReplyBridge):
    def work():
        try:
            r = pet.api.chat(payload)
            reply = r.get("text", "(无回复)")
            if r.get("pending_confirm"):
                pet.confirm_pending = r["pending_confirm"]["text"]
                reply += "\n\n⚠️ 涉及下单，回复「确认」执行（或「取消」）"
        except Exception as e:  # noqa: BLE001
            reply = f"调用失败: {e}"
        bridge.fired.emit(reply)
        pet.chat_busy = False

    import threading
    threading.Thread(target=work, daemon=True).start()
