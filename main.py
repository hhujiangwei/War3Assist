"""Warcraft III Assistant - program entry.

A remake of the core idea of Warkey 1.8 (inventory-hotkey remapping + toggle),
rebuilt in Python/PySide6, with HP/status-bar support.

Run: python main.py
"""
from __future__ import annotations

import os
import sys

from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication

import config
from ui import MainWindow


def _asset(name: str) -> str:
    """Locate a bundled asset, compatible with PyInstaller single-file mode (frozen dir)."""
    base = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base, "assets", name)


def main() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName("War3Assist")
    icon_path = _asset("app_icon.jpeg")
    if os.path.exists(icon_path):
        app.setWindowIcon(QIcon(icon_path))

    # Load saved config and apply it to the window
    win = MainWindow()
    if os.path.exists(icon_path):
        win.setWindowIcon(QIcon(icon_path))
    win.cfg = config.load_config()
    win._apply_config_to_ui()
    win.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())