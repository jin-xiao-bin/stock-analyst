"""宠物设置面板：形象管理 / 交互映射 / 菜单自定义 / 边缘隐藏"""
import shutil

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDialog, QFileDialog,
                               QFormLayout, QHBoxLayout, QLabel, QListWidget,
                               QListWidgetItem, QPushButton, QVBoxLayout)

from config_store import load_config, save_config

ACTION_OPTIONS = [("menu", "能力菜单"), ("home", "打开交易系统首页")]
MENU_ITEMS = [("home", "打开交易系统首页"),
              ("rules", "盯盘设置"), ("agent_toggle", "启动/停止 Agent"),
              ("hide", "隐藏宠物"), ("quit", "退出")]


class SettingsDialog(QDialog):
    """设置完成后写回 pet_config.json 并回调应用"""

    def __init__(self, cfg: dict, on_apply, parent=None):
        super().__init__(parent)
        self.setWindowTitle("宠物设置")
        self.setFixedSize(460, 520)
        self.cfg = cfg
        self.on_apply = on_apply  # 回调：重新加载配置并应用

        layout = QVBoxLayout(self)

        # ---- 形象 ----
        layout.addWidget(QLabel("🖼 显示形象（支持 png/jpg/gif，可上传多张切换）"))
        self.skin_list = QListWidget()
        for p in cfg.get("skins", []):
            self.skin_list.addItem(QListWidgetItem(p))
        if cfg.get("active_skin"):
            self.skin_list.setCurrentRow(cfg["skins"].index(cfg["active_skin"])
                                         if cfg["active_skin"] in cfg["skins"] else 0)
        layout.addWidget(self.skin_list)
        btn_row = QHBoxLayout()
        QPushButton("上传图片", self)
        up = QPushButton("上传图片")
        up.clicked.connect(self._upload)
        use = QPushButton("使用选中形象")
        use.clicked.connect(self._use_selected)
        default = QPushButton("恢复默认(程序绘制)")
        default.clicked.connect(self._use_default)
        for b in (up, use, default):
            btn_row.addWidget(b)
        layout.addLayout(btn_row)

        # ---- 交互映射 ----
        layout.addWidget(QLabel("🖱 交互映射"))
        form = QFormLayout()
        self.click_combo = QComboBox()
        self.dclick_combo = QComboBox()
        for combo, cur in ((self.click_combo, cfg.get("click_action", "menu")),
                           (self.dclick_combo, cfg.get("double_click_action", "menu"))):
            for val, label in ACTION_OPTIONS:
                combo.addItem(label, val)
                if val == cur:
                    combo.setCurrentIndex(combo.count() - 1)
        form.addRow("单击", self.click_combo)
        form.addRow("双击", self.dclick_combo)
        layout.addLayout(form)

        # ---- 菜单自定义 ----
        layout.addWidget(QLabel("📋 能力菜单（勾选显示，上移/下移调整顺序）"))
        self.menu_list = QListWidget()
        for item_id in cfg.get("menu_order", [m[0] for m in MENU_ITEMS]):
            label = dict(MENU_ITEMS).get(item_id, item_id)
            item = QListWidgetItem(label)
            item.setData(Qt.UserRole, item_id)
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
            item.setCheckState(Qt.Checked if
                               (cfg.get("menu_items") or {}).get(item_id, True)
                               else Qt.Unchecked)
            self.menu_list.addItem(item)
        layout.addWidget(self.menu_list)
        order_row = QHBoxLayout()
        up_btn = QPushButton("上移")
        up_btn.clicked.connect(lambda: self._move_item(-1))
        down_btn = QPushButton("下移")
        down_btn.clicked.connect(lambda: self._move_item(1))
        order_row.addWidget(up_btn)
        order_row.addWidget(down_btn)
        order_row.addStretch()
        layout.addLayout(order_row)

        # ---- 边缘隐藏 ----
        self.edge_check = QCheckBox("拖到屏幕左右边缘自动贴边隐藏")
        self.edge_check.setChecked(cfg.get("edge_hide", True))
        layout.addWidget(self.edge_check)

        # ---- 保存 ----
        save = QPushButton("保存并应用")
        save.clicked.connect(self._save)
        layout.addWidget(save)

    def _upload(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "选择宠物形象图片", "", "图片 (*.png *.jpg *.jpeg *.gif *.bmp)")
        if not path:
            return
        # 拷贝到配置目录，避免原文件移动后失效
        skins = self.cfg.get("skins", [])
        dest_dir = __import__("config_store").CONFIG_DIR / "skins"
        dest_dir.mkdir(parents=True, exist_ok=True)
        dest = dest_dir / (str(len(skins) + 1) + "_" + __import__("pathlib").Path(path).name)
        shutil.copy(path, dest)
        skins.append(str(dest))
        self.cfg["skins"] = skins
        self.skin_list.addItem(QListWidgetItem(str(dest)))
        self.skin_list.setCurrentRow(self.skin_list.count() - 1)

    def _use_selected(self):
        row = self.skin_list.currentRow()
        if row >= 0:
            self.cfg["active_skin"] = self.cfg.get("skins", [])[row]
            self._apply_now()

    def _use_default(self):
        self.cfg["active_skin"] = ""
        self._apply_now()

    def _move_item(self, delta):
        row = self.menu_list.currentRow()
        if row < 0:
            return
        new_row = max(0, min(self.menu_list.count() - 1, row + delta))
        item = self.menu_list.takeItem(row)
        self.menu_list.insertItem(new_row, item)
        self.menu_list.setCurrentRow(new_row)

    def _apply_now(self):
        self._collect()
        save_config(self.cfg)
        self.on_apply()

    def _collect(self):
        self.cfg["click_action"] = self.click_combo.currentData()
        self.cfg["double_click_action"] = self.dclick_combo.currentData()
        items, order = {}, []
        for i in range(self.menu_list.count()):
            it = self.menu_list.item(i)
            item_id = it.data(Qt.UserRole)
            order.append(item_id)
            items[item_id] = it.checkState() == Qt.Checked
        self.cfg["menu_items"] = items
        self.cfg["menu_order"] = order
        self.cfg["edge_hide"] = self.edge_check.isChecked()

    def _save(self):
        self._collect()
        save_config(self.cfg)
        self.on_apply()
        self.accept()
