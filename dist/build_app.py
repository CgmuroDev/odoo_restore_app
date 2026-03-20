#!/usr/bin/env python3
"""
Script multiplataforma para generar ejecutable con PyInstaller.

Uso:
  python dist/build_app.py

Requisitos:
  pip install PyQt6 pyinstaller

Genera:
  - Windows: dist/OdooRestore.exe
  - Mac:     dist/OdooRestore.app
  - Linux:   dist/OdooRestore
"""

import os
import platform
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent / "src"
ICON = ROOT / "icon.svg"
MAIN = ROOT / "main.py"
APP_NAME = "OdooRestore"


def check_pyinstaller() -> None:
    try:
        import PyInstaller  # noqa: F401
    except ImportError:
        print("PyInstaller no encontrado. Instalando...")
        subprocess.check_call([sys.executable, "-m", "pip", "install", "pyinstaller"])


def build() -> None:
    check_pyinstaller()

    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--onefile",
        "--windowed",
        "--name", APP_NAME,
        "--add-data", f"{ROOT / 'restore_app.py'}{os.pathsep}.",
    ]

    system = platform.system()

    # Icono: en Windows necesita .ico, en Mac .icns, en Linux no importa
    if system == "Windows" and (ROOT / "icon.ico").exists():
        cmd += ["--icon", str(ROOT / "icon.ico")]
    elif system == "Darwin" and (ROOT / "icon.icns").exists():
        cmd += ["--icon", str(ROOT / "icon.icns")]

    cmd.append(str(MAIN))

    print(f"Plataforma: {system}")
    print(f"Ejecutando: {' '.join(cmd)}")
    print()

    subprocess.check_call(cmd)

    print()
    print(f"Ejecutable generado en: dist/{APP_NAME}")
    if system == "Windows":
        print(f"  -> dist/{APP_NAME}.exe")
    elif system == "Darwin":
        print(f"  -> dist/{APP_NAME}.app")


if __name__ == "__main__":
    build()
