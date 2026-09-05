"""Main window: light-theme PySide6 UI (2 columns x 3 rows grid + hotkey overview). (English build)"""
from __future__ import annotations

import os

from PySide6.QtCore import QProcess, Qt
from PySide6.QtWidgets import (
    QCheckBox, QFileDialog, QFrame, QGridLayout, QGroupBox, QHBoxLayout, QLabel,
    QLineEdit, QMainWindow, QPushButton, QTabWidget, QTextEdit, QVBoxLayout,
    QWidget,
)

import config
from config import AppConfig, SlotConfig
from engine import AssistantEngine

# Global light theme style sheet
QSS = """
MainWindow { background:#f5f7fa; }
QTabWidget::pane { border:1px solid #e3e8f0; border-radius:10px; background:#ffffff; top:-1px; }
QTabBar::tab { background:transparent; padding:7px 14px; color:#6b7686; font-weight:600; }
QTabBar::tab:selected { color:#1f2733; border-bottom:2px solid #7c5295; }
QPushButton { background:#eef2f7; border:1px solid #dbe2ec; border-radius:8px; padding:7px 12px;
              font-weight:600; color:#1f2733; }
QPushButton:hover { background:#e4eaf2; }
QPushButton#primary { background:#7c5295; border-color:#7c5295; color:#ffffff; padding:8px 16px; }
QPushButton#primary:hover { background:#684087; }
QTextEdit, QLineEdit { border:1px solid #dbe2ec; border-radius:10px; padding:5px 8px; background:#ffffff; }
QCheckBox { spacing:5px; color:#3a4556; }
QCheckBox::indicator { width:16px; height:16px; border:1px solid #c6ceda; border-radius:4px;
                       background:#ffffff; }
QCheckBox::indicator:checked { background:#7c5295; border-color:#7c5295; }
QCheckBox::indicator:hover { border-color:#7c5295; }
QWidget#slot { background:#ffffff; border:1px solid #e3e8f0; border-radius:12px; }
QLabel#panelTitle { font-size:14px; font-weight:700; color:#1f2733; }
QLabel#panelHint { color:#7b8798; font-size:11px; }
QLabel#idx { color:#9aa4b4; font-weight:700; font-size:10px; }
QLabel#hkName { font-size:13px; font-weight:600; }
QLabel#hkEffect { color:#7b8798; font-size:11px; }
QLabel#dotOn { background:#2eaf6b; border-radius:5px; min-width:10px; max-width:10px;
              min-height:10px; max-height:10px; }
QLabel#dotOff { background:#c6ceda; border-radius:5px; min-width:10px; max-width:10px;
               min-height:10px; max-height:10px; }
QGroupBox { border:1px solid #e3e8f0; border-radius:12px; margin-top:12px; font-weight:600; color:#1f2733; }
QGroupBox::title { subcontrol-origin: margin; left:12px; padding:0 4px; background:transparent; }
"""

# Keycap styling: unified grape-purple; switches to light "active" style while rebinding
_PURPLE_CSS = (
    "QLineEdit{background:#7e53a0;border:2px solid #684087;border-radius:9px;"
    "color:#ffffff;font-weight:800;font-family:Consolas,'Microsoft YaHei';}"
    "QLineEdit:hover{background:#9270b3;border-color:#7a5299;}")

# Generic active state (awaiting key): white fill + grape-purple border
_ACTIVE_CSS = (
    "QLineEdit{background:#ffffff;border:2px solid #7c5295;border-radius:9px;"
    "color:#7c5295;font-weight:800;font-family:Consolas,'Microsoft YaHei';}")

_CAPTURE_CSS = _PURPLE_CSS

# Qt key value -> Win32 virtual key code (special/function keys).
# Letters A-Z and digits 0-9 share the same Qt and VK value (ASCII).
_QT_TO_VK: dict[int, int] = {
    Qt.Key_Escape: 27, Qt.Key_Tab: 9, Qt.Key_Backspace: 8,
    Qt.Key_Return: 13, Qt.Key_Enter: 13, Qt.Key_Insert: 45,
    Qt.Key_Delete: 46, Qt.Key_Home: 36, Qt.Key_End: 35,
    Qt.Key_Left: 37, Qt.Key_Up: 38, Qt.Key_Right: 39, Qt.Key_Down: 40,
    Qt.Key_PageUp: 33, Qt.Key_PageDown: 34,
    Qt.Key_CapsLock: 20, Qt.Key_NumLock: 144, Qt.Key_ScrollLock: 145,
    Qt.Key_Pause: 19, Qt.Key_Print: 42, Qt.Key_Space: 32,
    # Punctuation: Qt value = ASCII, but the Win32 VK is OEM_* (differs from
    # ASCII), so a one-to-one mapping is required.
    Qt.Key_BracketLeft: 219,    # '['
    Qt.Key_BracketRight: 221,   # ']'
    Qt.Key_Backslash: 220,      # '\'
    Qt.Key_Semicolon: 186,      # ';'
    Qt.Key_Apostrophe: 222,     # "'"
    Qt.Key_Comma: 188,          # ','
    Qt.Key_Period: 190,         # '.'
    Qt.Key_Slash: 191,          # '/'
    Qt.Key_Minus: 189,          # '-'
    Qt.Key_Equal: 187,          # '='
    Qt.Key_QuoteLeft: 192,      # '`'
}
_QT_TO_VK.update({getattr(Qt, f"Key_F{i}"): 111 + i for i in range(1, 13)})


def _qt_key_to_vk(qt: int) -> int | None:
    """Map a Qt key value to a Win32 virtual key code; None for modifiers/unsupported."""
    if qt in _QT_TO_VK:
        return _QT_TO_VK[qt]
    # Letters A-Z (0x41..0x5a) and digits 0-9 (0x30..0x39) match VK directly
    if 0x30 <= qt <= 0x39 or 0x41 <= qt <= 0x5a:
        return qt
    return None


class KeyCaptureLineEdit(QLineEdit):
    """Keycap rebind box: click it, then press a key to capture its VK code."""

    def __init__(self, code: int = 0, placeholder: str = "Press a key",
                 size=(76, 30), font_size: int = 15, style: str = _CAPTURE_CSS):
        super().__init__()
        self._code = code
        self._capturing = False
        self.setReadOnly(True)
        self.setCursor(Qt.PointingHandCursor)
        self.setFixedSize(*size)
        self.setAlignment(Qt.AlignCenter)
        font = self.font()
        font.setPointSize(font_size)
        font.setBold(True)
        self.setFont(font)
        self.setToolTip("Click then press the key you want to bind")
        self._style = style
        self._normal = style
        self._active = _ACTIVE_CSS
        self.setStyleSheet(self._style)
        self.setText(config.code_name(code) if code else placeholder)

    @property
    def code(self) -> int:
        return self._code

    def set_code(self, code: int) -> None:
        self._code = code
        self.setText(config.code_name(code))
        self.setStyleSheet(self._normal)

    def mousePressEvent(self, e) -> None:
        self._capturing = True
        self.setText("Press key…")
        self.setStyleSheet(self._active)
        super().mousePressEvent(e)

    def keyPressEvent(self, e) -> None:
        if self._capturing:
            vk = _qt_key_to_vk(int(e.key()))
            if vk is None:
                return  # pure modifier or unsupported key
            self._capturing = False
            self.set_code(vk)
            return
        super().keyPressEvent(e)


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Warcraft III Assistant")
        self.resize(800, 700)
        self.setFixedSize(800, 700)
        self.setMinimumSize(800, 700)
        self.cfg = AppConfig(slots=AppConfig.default_slots())
        self.engine: AssistantEngine | None = None
        self._build_ui()
        self._apply_config_to_ui()

    # ────────────────────────── UI layout ──────────────────────────
    def _build_ui(self):
        self.setStyleSheet(QSS)
        central = QWidget()
        self.setCentralWidget(central)
        outer = QVBoxLayout(central)
        outer.setContentsMargins(12, 10, 12, 10)
        outer.setSpacing(8)

        # Top engine status bar
        self.hk_act_dot = self._dot(False)
        self.hp_dot_all = self._dot(False)
        self.hp_dot_ally = self._dot(False)
        self.hp_dot_enemy = self._dot(False)

        eng = QWidget()
        eng.setStyleSheet("QWidget{background:#ffffff;border:1px solid #e3e8f0;border-radius:12px;}")
        st = QHBoxLayout(eng)
        st.setContentsMargins(12, 8, 12, 8)
        self.state_label = QLabel("Engine stopped")
        self.state_label.setStyleSheet("font-weight:700;color:#6b7686;")
        st.addWidget(self.state_label)
        st.addSpacing(6)
        st.addWidget(self.hp_dot_all)
        st.addSpacing(6)
        self.hp_label = QLabel("HP: off")
        self.hp_label.setStyleSheet("color:#7b8798;font-weight:600;")
        st.addWidget(self.hp_label)
        st.addStretch(1)
        self.start_btn = QPushButton("▶ Start Engine")
        self.start_btn.setStyleSheet(self._btn_css_start())
        self.start_btn.clicked.connect(self._toggle_engine)
        st.addWidget(self.start_btn)
        outer.addWidget(eng)

        tabs = QTabWidget()
        tabs.addTab(self._build_hotkey_tab(), "Hotkeys & HP")
        outer.addWidget(tabs)

        # Log
        self.log_view = QTextEdit()
        self.log_view.setReadOnly(True)
        self.log_view.setFixedHeight(88)
        outer.addWidget(QLabel("Log:", objectName="panelHint"))
        outer.addWidget(self.log_view)

    @staticmethod
    def _btn_css_start() -> str:
        """Engine start/stop button - running state: solid grape-purple."""
        return ("QPushButton{background:#7c5295;border:1px solid #7c5295;color:#ffffff;"
                "border-radius:8px;padding:7px 16px;font-weight:600;}"
                "QPushButton:hover{background:#684087;}"
                "QPushButton:pressed{background:#5f4580;}")

    @staticmethod
    def _btn_css_stop() -> str:
        """Engine start/stop button - stop state: light grey."""
        return ("QPushButton{background:#e2e6ec;border:1px solid #cfd7e1;color:#5a6472;"
                "border-radius:8px;padding:7px 16px;font-weight:600;}"
                "QPushButton:hover{background:#d5dbe4;}"
                "QPushButton:pressed{background:#c8d0da;}")

    @staticmethod
    def _btn_css_launch() -> str:
        """Launch Game button - a slightly deeper grape-purple than the primary buttons."""
        return ("QPushButton{background:#5f4580;border:1px solid #5f4580;color:#ffffff;"
                "border-radius:8px;padding:7px 16px;font-weight:600;}"
                "QPushButton:hover{background:#4f3970;}"
                "QPushButton:pressed{background:#432f5e;}")

    @staticmethod
    def _dot_style(on: bool) -> str:
        """Inline background color for a status dot (reliable in both IDE and EXE)."""
        return "QLabel{background:%s;border-radius:5px;}" % ("#2eaf6b" if on else "#c6ceda")

    def _dot(self, on: bool) -> QLabel:
        lab = QLabel()
        lab.setFixedSize(10, 10)
        lab.setStyleSheet(self._dot_style(on))
        return lab

    @staticmethod
    def _set_dot(dot: QLabel, on: bool) -> None:
        """Repaint a status dot green/off via inline style (reliable in EXE builds)."""
        dot.setStyleSheet(MainWindow._dot_style(on))

    def _build_hotkey_tab(self) -> QWidget:
        w = QWidget()
        root = QHBoxLayout(w)
        root.setContentsMargins(10, 10, 10, 10)
        root.setSpacing(10)

        # ── Left: inventory hotkey table ──
        left = QWidget()
        lv = QVBoxLayout(left)
        lv.setSpacing(8)
        title = QLabel("Inventory Hotkeys")
        title.setObjectName("panelTitle")
        lv.addWidget(title)
        hint = QLabel("When enabled, pressing a Custom key triggers that cell's Target key. "
                      "Click a keycap to rebind.")
        hint.setObjectName("panelHint")
        hint.setWordWrap(True)
        lv.addWidget(hint)

        board = QWidget()
        board.setObjectName("slot")
        bg = QVBoxLayout(board)
        bg.setContentsMargins(10, 10, 10, 10)
        bg.setSpacing(6)

        # Header + 6 rows laid out as a grid so columns align and never overlap
        grid = QGridLayout()
        grid.setHorizontalSpacing(14)
        grid.setVerticalSpacing(8)
        grid.setColumnMinimumWidth(0, 80)     # Slot label
        grid.setColumnMinimumWidth(1, 104)    # Custom keycap
        grid.setColumnMinimumWidth(2, 104)    # Target keycap
        grid.setColumnMinimumWidth(3, 48)     # On checkbox
        for c, text in enumerate(("Slot", "Custom", "Target", "On")):
            h = QLabel(text)
            h.setObjectName("panelHint")
            grid.addWidget(h, 0, c, Qt.AlignLeft)

        # 6 data rows
        self.slot_rows: list[dict] = []
        for r, slot in enumerate(self.cfg.slots):
            lbl = QLabel(slot.label)
            lbl.setObjectName("idx")
            cap = KeyCaptureLineEdit(slot.custom_code, size=(104, 34), font_size=11,
                                     style=_PURPLE_CSS)
            cap.setToolTip("Click then press a key to set the custom shortcut")
            tgt = KeyCaptureLineEdit(slot.default_code, size=(104, 34), font_size=11,
                                     style=_PURPLE_CSS)
            tgt.setToolTip("Click then press a key to set the target key sent to the game")
            chk = QCheckBox("On")
            chk.setChecked(slot.enabled)
            grid.addWidget(lbl, r + 1, 0, Qt.AlignLeft | Qt.AlignVCenter)
            grid.addWidget(cap, r + 1, 1, Qt.AlignLeft)
            grid.addWidget(tgt, r + 1, 2, Qt.AlignLeft)
            grid.addWidget(chk, r + 1, 3, Qt.AlignLeft)
            self.slot_rows.append({"label": lbl, "capture": cap,
                                   "target": tgt, "chk": chk})
        bg.addLayout(grid)
        lv.addWidget(board)

        save_row = QHBoxLayout()
        save_btn = QPushButton("Apply & Save")
        save_btn.setObjectName("primary")
        save_btn.clicked.connect(self._save_and_apply)
        save_row.addWidget(save_btn)
        reset_btn = QPushButton("Restore Defaults")
        reset_btn.setObjectName("primary")
        reset_btn.clicked.connect(self._reset_defaults)
        save_row.addWidget(reset_btn)
        save_row.addStretch(1)
        lv.addLayout(save_row)
        lv.addStretch(1)
        root.addWidget(left, 1)

        # ── Right: hotkey overview (with rebinding) ──
        right = QWidget()
        right.setObjectName("slot")
        rv = QVBoxLayout(right)
        rv.setContentsMargins(14, 12, 14, 12)
        rv.setSpacing(6)
        rt = QLabel("Hotkey Overview")
        rt.setObjectName("panelTitle")
        rv.addWidget(rt)
        rh = QLabel("Click a keycap on the right to rebind")
        rh.setObjectName("panelHint")
        rv.addWidget(rh)
        rv.addSpacing(2)

        self.toggle_key = KeyCaptureLineEdit(self.cfg.toggle_code, size=(84, 32), font_size=12)
        self.show_ally_toggle_key = KeyCaptureLineEdit(self.cfg.show_ally_toggle_code, size=(84, 32), font_size=12)
        self.show_enemy_toggle_key = KeyCaptureLineEdit(self.cfg.show_enemy_toggle_code, size=(84, 32), font_size=12)

        rows = [
            ("⌨", "Inventory Hotkeys", "toggle → triggers slot default key", self.toggle_key, "act"),
            ("✚", "HP: ally", "→ hold [", self.show_ally_toggle_key, "ally"),
            ("✕", "HP: enemy", "→ hold ]", self.show_enemy_toggle_key, "enemy"),
        ]
        for icon, name, eff, key, kind in rows:
            sep = QFrame()
            sep.setFrameShape(QFrame.HLine)
            sep.setStyleSheet("color:#e8edf4;background:#e8edf4;height:1px;border:none;")
            rv.addSpacing(2)
            rv.addWidget(sep)
            rv.addSpacing(6)
            row = QHBoxLayout()
            row.setSpacing(12)
            row.setAlignment(Qt.AlignBottom)
            dot = self._dot(False)
            if kind == "act":
                self.hk_act_dot = dot
            elif kind == "ally":
                self.hp_dot_ally = dot
            elif kind == "enemy":
                self.hp_dot_enemy = dot
            row.addWidget(dot)
            meta = QVBoxLayout()
            meta.setSpacing(2)
            n = QLabel(name); n.setObjectName("hkName")
            e = QLabel(eff); e.setObjectName("hkEffect")
            meta.addWidget(n); meta.addWidget(e)
            row.addLayout(meta, 1)
            row.addWidget(key)
            rv.addLayout(row)
            rv.addSpacing(9)

        # Launch Game - its own dedicated area at the bottom of the overview
        lg = QGroupBox("Launch")
        lv2 = QVBoxLayout(lg)
        lv2.setSpacing(6)
        li = QLabel("Launch Warcraft III")
        li.setObjectName("panelHint")
        lv2.addWidget(li)
        self.launch_btn = QPushButton("⚐ Launch Game")
        self.launch_btn.setStyleSheet(self._btn_css_launch())
        self.launch_btn.setToolTip("Launch Warcraft III. First click (or if the path is "
                                   "missing) opens a file picker to locate the game.")
        self.launch_btn.clicked.connect(self._launch_game)
        lv2.addWidget(self.launch_btn)
        rv.addWidget(lg)
        rv.addSpacing(10)
        rv.addStretch(1)
        root.addWidget(right, 0)

        return w

    # ────────────────────────── Config sync ──────────────────────────
    def _apply_config_to_ui(self):
        self.toggle_key.set_code(self.cfg.toggle_code)
        self.show_ally_toggle_key.set_code(self.cfg.show_ally_toggle_code)
        self.show_enemy_toggle_key.set_code(self.cfg.show_enemy_toggle_code)
        for i, s in enumerate(self.cfg.slots):
            if i < len(self.slot_rows):
                row = self.slot_rows[i]
                row["chk"].setChecked(s.enabled)
                row["capture"].set_code(s.custom_code)
                row["target"].set_code(s.default_code)

    def _collect_cfg(self) -> AppConfig:
        cfg = AppConfig(slots=[])
        cfg.toggle_code = self.toggle_key.code
        cfg.show_ally_toggle_code = self.show_ally_toggle_key.code
        cfg.show_enemy_toggle_code = self.show_enemy_toggle_key.code
        for i, row in enumerate(self.slot_rows):
            cfg.slots.append(SlotConfig(
                i, f"Slot {i + 1}", row["target"].code, row["capture"].code,
                row["chk"].isChecked()))
        return cfg

    def _save_and_apply(self):
        self.cfg = self._collect_cfg()
        config.save_config(self.cfg)
        if self.engine and self.engine.isRunning():
            self.engine.update_cfg(self.cfg)
        self._log("Settings saved and applied.")

    def _reset_defaults(self):
        """Restore inventory hotkeys to defaults (incl. enabled flags); does not save/apply."""
        defaults = AppConfig.default_slots()
        for i, row in enumerate(self.slot_rows):
            if i >= len(defaults):
                break
            d = defaults[i]
            row["chk"].setChecked(d.enabled)
            row["capture"].set_code(d.custom_code)
            row["target"].set_code(d.default_code)
            self._log(f"{d.label} restored to default")

    # ────────────────────────── Game launch ──────────────────────────
    def _launch_game(self):
        """Launch Warcraft III. First click (or a stale/missing saved path) opens a file
        picker; once a valid path is stored, later clicks start the game directly."""
        path = (self.cfg.game_path or "").strip()
        if not path or not os.path.isfile(path):
            start_dir = os.path.dirname(path) if path else os.path.expanduser("~")
            chosen, _ = QFileDialog.getOpenFileName(
                self, "Select Warcraft III Executable", start_dir,
                "Warcraft III (*.exe);;All files (*.*)")
            if not chosen:
                self._log("No game executable selected.")
                return
            self.cfg.game_path = chosen
            config.save_config(self.cfg)
            path = chosen
        if QProcess.startDetached(path):
            self._log(f"Launching Warcraft III: {path}")
        else:
            self._log(f"Failed to launch Warcraft III: {path}")

    # ────────────────────────── Engine control ──────────────────────────
    def _toggle_engine(self):
        try:
            self._toggle_engine_impl()
        except Exception:
            import traceback
            self._log("Engine toggle error: "
                      + traceback.format_exc().replace("\n", " | "))

    def _toggle_engine_impl(self):
        if self.engine and self.engine.isRunning():
            self.engine.stop()
            self.engine = None
            self.state_label.setText("Engine: stopped")
            self.state_label.setStyleSheet("font-weight:bold;color:#c0392b;")
            self.start_btn.setText("▶ Start Engine")
            self.start_btn.setStyleSheet(self._btn_css_start())
            self._set_dot(self.hk_act_dot, False)
            self._set_dot(self.hp_dot_all, False)
            self._set_dot(self.hp_dot_ally, False)
            self._set_dot(self.hp_dot_enemy, False)
            self.hp_label.setText("　HP: off")
            self.hp_label.setStyleSheet("font-weight:bold;color:#888;")
            self._log("Engine stopped.")
            return
        self.cfg = self._collect_cfg()
        config.save_config(self.cfg)
        self.engine = AssistantEngine(self.cfg, self)
        self.engine.active_changed.connect(self._on_active)
        self.engine.hp_status.connect(self._on_hp_status)
        self.engine.log.connect(self._log)
        self.engine.start()
        self.state_label.setText("Engine: running")
        self.state_label.setStyleSheet("font-weight:bold;color:#7c5295;")
        self.start_btn.setText("■ Stop Engine")
        self.start_btn.setStyleSheet(self._btn_css_stop())

    def _on_active(self, active: bool):
        self.state_label.setText("Running - hotkeys " + ("enabled" if active else "disabled"))
        self.state_label.setStyleSheet("font-weight:bold;color:#27ae60;")
        self._set_dot(self.hk_act_dot, active)

    def _on_hp_status(self, text: str):
        self._set_dot(self.hp_dot_all, "All" in text)
        self._set_dot(self.hp_dot_ally, "Ally" in text)
        self._set_dot(self.hp_dot_enemy, "Enemy" in text)
        if not text:
            self.hp_label.setText("　HP: off")
            self.hp_label.setStyleSheet("font-weight:bold;color:#888;")
            return
        self.hp_label.setText("　HP: " + text)
        self.hp_label.setStyleSheet("font-weight:bold;color:#27ae60;")

    def closeEvent(self, e):
        if self.engine and self.engine.isRunning():
            self.engine.stop()
        super().closeEvent(e)

    # ────────────────────────── Logging ──────────────────────────
    def _log(self, msg: str):
        self.log_view.append(msg)