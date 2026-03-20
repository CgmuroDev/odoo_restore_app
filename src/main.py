#!/usr/bin/env python3
"""Odoo Backup Restore GUI - Entry point."""

import sys

from PyQt6.QtWidgets import QApplication

from restore_app import MainWindow


def main() -> None:
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
