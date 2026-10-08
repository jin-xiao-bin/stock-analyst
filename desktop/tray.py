"""系统托盘图标"""
from PySide6.QtGui import QAction, QIcon, QPainter, QPixmap
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QMenu, QSystemTrayIcon


def _icon() -> QIcon:
    pix = QPixmap(64, 64)
    pix.fill(Qt.transparent)
    p = QPainter(pix)
    p.setRenderHint(QPainter.Antialiasing)
    from pet_draw import draw_pet
    draw_pet(p, "idle", 0, 64, 64)
    p.end()
    return QIcon(pix)


class TrayIcon(QSystemTrayIcon):
    def __init__(self, pet, on_quit, on_settings=None):
        super().__init__()
        self.setIcon(_icon())
        self.setToolTip("交易助手 - 盯盘中（双击宠物对话）")
        menu = QMenu()
        show_act = QAction("显示/隐藏 宠物", None)
        show_act.triggered.connect(lambda: pet.setVisible(not pet.isVisible()))
        menu.addAction(show_act)
        if on_settings:
            settings_act = QAction("⚙ 宠物设置...", None)
            settings_act.triggered.connect(on_settings)
            menu.addAction(settings_act)
        quit_act = QAction("退出", None)
        quit_act.triggered.connect(on_quit)
        menu.addAction(quit_act)
        self.setContextMenu(menu)
        self.show()
