from __future__ import annotations

import os
from pathlib import Path


APP_SLUG = "odoo-restore"
APP_DISPLAY_NAME = "Odoo Restore Manager"
GITHUB_REPO = "CgmuroDev/odoo_restore_app"
GITHUB_RELEASES_API = f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest"
GITHUB_RELEASES_PAGE = f"https://github.com/{GITHUB_REPO}/releases/latest"
ROOT_DIR = Path(__file__).resolve().parent.parent
MODULE_DIR = Path(__file__).resolve().parent


def _resolve_version_file() -> Path:
    candidates = [
        MODULE_DIR / "VERSION",
        ROOT_DIR / "VERSION",
    ]
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return candidates[0]


VERSION_FILE = _resolve_version_file()


def resolve_icon_file() -> Path:
    candidates = [
        MODULE_DIR / "icon.svg",
        ROOT_DIR / "src" / "icon.svg",
    ]
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return candidates[0]


def load_version() -> str:
    return VERSION_FILE.read_text(encoding="utf-8").strip()


def is_snap_runtime() -> bool:
    return bool(os.environ.get("SNAP"))


APP_VERSION = load_version()
APP_ICON_FILE = resolve_icon_file()
