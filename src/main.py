#!/usr/bin/env python3
"""Odoo Backup Restore GUI - Entry point."""

import sys

from PyQt6.QtGui import QIcon
from PyQt6.QtWidgets import QApplication

from app_meta import APP_DISPLAY_NAME, APP_ICON_FILE, APP_SLUG, APP_VERSION
from restore_app import MainWindow


def main() -> None:
    app = QApplication(sys.argv)
    app.setApplicationName(APP_DISPLAY_NAME)
    app.setApplicationVersion(APP_VERSION)
    app.setDesktopFileName(APP_SLUG)
    app.setWindowIcon(QIcon(str(APP_ICON_FILE)))
    window = MainWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
