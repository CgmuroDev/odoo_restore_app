from __future__ import annotations

import json
import os
import platform as platform_module
import subprocess
import time
from functools import partial
from datetime import datetime
from pathlib import Path

from PyQt6.QtCore import QThread, pyqtSignal, Qt, QTimer, QUrl
from PyQt6.QtGui import QDesktopServices, QFont, QIcon, QIntValidator, QColor
from PyQt6.QtWidgets import (
    QCheckBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QStatusBar,
    QTabWidget,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from app_meta import APP_ICON_FILE, APP_VERSION
from update_service import (
    fetch_latest_release,
    is_newer_version,
    platform_label,
)


# ---------------------------------------------------------------------------
# HistoryManager
# ---------------------------------------------------------------------------

HISTORY_DIR = Path.home() / ".local" / "share" / "bd_restaurater"
HISTORY_FILE = HISTORY_DIR / "history.json"


class HistoryManager:
    def load(self) -> list[dict]:
        if not HISTORY_FILE.exists():
            return []
        try:
            data = json.loads(HISTORY_FILE.read_text(encoding="utf-8"))
            return data.get("restorations", [])
        except (json.JSONDecodeError, OSError):
            return []

    def add_entry(
        self,
        db_name: str,
        backup_dir: str,
        success: bool,
        duration: float,
        error: str | None = None,
    ) -> None:
        entries = self.load()
        entries.append(
            {
                "date": datetime.now().isoformat(timespec="seconds"),
                "db_name": db_name,
                "backup_dir": backup_dir,
                "success": success,
                "duration_seconds": round(duration, 1),
                "error": error,
            }
        )
        HISTORY_DIR.mkdir(parents=True, exist_ok=True)
        HISTORY_FILE.write_text(
            json.dumps({"restorations": entries}, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

    def clear(self) -> None:
        if HISTORY_FILE.exists():
            HISTORY_FILE.write_text(
                json.dumps({"restorations": []}, indent=2), encoding="utf-8"
            )


# ---------------------------------------------------------------------------
# RestoreWorker
# ---------------------------------------------------------------------------


class RestoreWorker(QThread):
    log_message = pyqtSignal(str)
    finished_signal = pyqtSignal(bool, str)
    step_changed = pyqtSignal(int, str)

    TOTAL_STEPS = 6

    def __init__(
        self,
        db_name: str,
        backup_dir: str,
        db_host: str,
        db_port: str,
        db_user: str,
        db_password: str,
        filestore_root: str,
        copy_filestore: bool,
        drop_if_exists: bool,
        neutralize: bool = True,
        addon_paths: list[str] | None = None,
    ):
        super().__init__()
        self.db_name = db_name
        self.backup_dir = backup_dir
        self.db_host = db_host
        self.db_port = db_port
        self.db_user = db_user
        self.db_password = db_password
        self.filestore_root = filestore_root
        self.copy_filestore = copy_filestore
        self.drop_if_exists = drop_if_exists
        self.neutralize = neutralize
        self.addon_paths = addon_paths or []
        self._cancelled = False
        self._current_process: subprocess.Popen | None = None

    @staticmethod
    def _quote_literal(value: str) -> str:
        return "'" + value.replace("'", "''") + "'"

    @staticmethod
    def _quote_ident(value: str) -> str:
        return '"' + value.replace('"', '""') + '"'

    def cancel(self) -> None:
        self._cancelled = True
        if self._current_process is not None:
            try:
                self._current_process.terminate()
            except OSError:
                pass

    def _ts(self) -> str:
        return datetime.now().strftime("%F %T")

    def _log(self, msg: str) -> None:
        self.log_message.emit(f"[{self._ts()}] {msg}")

    def _pg_env(self) -> dict[str, str]:
        env = os.environ.copy()
        if self.db_password:
            env["PGPASSWORD"] = self.db_password
        return env

    def _run_cmd(self, cmd: list[str], silent: bool = False) -> tuple[bool, str]:
        if self._cancelled:
            return False, "Cancelado"
        if not silent:
            self._log(f"Ejecutando: {' '.join(cmd)}")
        try:
            proc = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                env=self._pg_env(),
            )
            self._current_process = proc
            output_lines: list[str] = []
            for line in proc.stdout:  # type: ignore[union-attr]
                if self._cancelled:
                    proc.terminate()
                    return False, "Cancelado"
                stripped = line.rstrip()
                output_lines.append(stripped)
                if not silent:
                    self.log_message.emit(stripped)
            proc.wait()
            self._current_process = None
            output = "\n".join(output_lines)
            if proc.returncode != 0:
                return False, output
            return True, output
        except FileNotFoundError as exc:
            return False, f"Comando no encontrado: {exc}"

    def _format_cmd_error(self, output: str) -> str:
        normalized = output.lower()
        if "password authentication failed" in normalized:
            return "Autenticacion PostgreSQL fallida. Verifica usuario y password."
        if "could not connect to server" in normalized or "connection refused" in normalized:
            return "No se pudo conectar a PostgreSQL. Verifica host, puerto y servicio."
        if "no such file or directory" in normalized and "psql" in normalized:
            return "No se encontro psql. Instala postgresql-client."
        if "no such file or directory" in normalized and "rsync" in normalized:
            return "No se encontro rsync. Instalalo antes de restaurar."
        if "is being accessed by other users" in normalized:
            return "La base de datos tiene conexiones activas y no se pudo eliminar."
        if output.strip():
            return output
        return "Error desconocido"

    def _terminate_db_connections(self) -> tuple[bool, str]:
        sql = (
            "SELECT pg_terminate_backend(pid) "
            "FROM pg_stat_activity "
            f"WHERE datname = {self._quote_literal(self.db_name)} "
            "AND pid <> pg_backend_pid();"
        )
        return self._run_cmd([
            "psql", "-h", self.db_host, "-p", self.db_port,
            "-U", self.db_user, "-d", "postgres", "-c", sql,
        ], silent=True)

    def _get_installed_modules(self) -> list[str]:
        ok, out = self._run_cmd([
            "psql", "-h", self.db_host, "-p", self.db_port,
            "-U", self.db_user, "-d", self.db_name, "-tAc",
            "SELECT name FROM ir_module_module "
            "WHERE state IN ('installed', 'to upgrade', 'to remove');",
        ], silent=True)
        if not ok:
            self._log(f"No se pudo obtener modulos instalados: {out}")
            return []
        return [line.strip() for line in out.splitlines() if line.strip()]

    def _iter_neutralize_candidates(self, addon_path: str, module: str) -> list[str]:
        base_path = os.path.abspath(addon_path)
        return [
            os.path.join(base_path, module, "data", "neutralize.sql"),
            os.path.join(base_path, "addons", module, "data", "neutralize.sql"),
            os.path.join(base_path, "odoo", "addons", module, "data", "neutralize.sql"),
        ]

    def _find_neutralize_sql_files(self, modules: list[str]) -> list[tuple[str, str]]:
        found = []
        for module in modules:
            for addon_path in self.addon_paths:
                for candidate in self._iter_neutralize_candidates(addon_path, module):
                    if os.path.isfile(candidate):
                        found.append((module, candidate))
                        break
                else:
                    continue
                break
        return found

    def _run_odoo_neutralize(self) -> None:
        modules = self._get_installed_modules()
        if not modules:
            self._log("No se encontraron modulos instalados")
            return
        self._log(f"Modulos instalados encontrados: {len(modules)}")

        sql_files = self._find_neutralize_sql_files(modules)
        self._log(f"Archivos neutralize.sql encontrados: {len(sql_files)}")

        success_count = 0
        fail_count = 0
        for module_name, sql_path in sql_files:
            if self._cancelled:
                return
            self._log(f"  Neutralizando modulo: {module_name}")
            ok, out = self._run_cmd([
                "psql", "-h", self.db_host, "-p", self.db_port,
                "-U", self.db_user, "-d", self.db_name,
                "-f", sql_path,
            ], silent=True)
            if ok:
                success_count += 1
            else:
                fail_count += 1
                self._log(f"  Advertencia en {module_name}: {out[:200]}")

        self._log(
            f"Neutralizacion por modulo: {success_count} OK, {fail_count} con advertencias"
        )

    def run(self) -> None:
        try:
            self._do_restore()
        except Exception as exc:
            self._log(f"Error inesperado: {exc}")
            self.finished_signal.emit(False, str(exc))

    def _do_restore(self) -> None:
        sql_dump = os.path.join(self.backup_dir, "dump.sql")
        source_fs = os.path.join(self.backup_dir, "filestore")

        # -- Step 1: Validar --
        self.step_changed.emit(1, "Validando directorio de respaldo...")
        self._log("Validando directorio de respaldo")
        if not os.path.isdir(self.backup_dir):
            self._log(f"No existe el directorio: {self.backup_dir}")
            self.finished_signal.emit(False, "Directorio de respaldo no existe")
            return
        if not os.path.isfile(sql_dump):
            self._log(f"No se encontro dump.sql en {self.backup_dir}")
            self.finished_signal.emit(False, "dump.sql no encontrado")
            return
        if self.copy_filestore and not os.path.isdir(source_fs):
            self._log(f"No se encontro directorio filestore en {self.backup_dir}")
            self.finished_signal.emit(False, "filestore/ no encontrado")
            return
        self._log("Directorio validado correctamente")

        # -- Step 2: Verificar/eliminar BD --
        self.step_changed.emit(2, "Verificando base de datos...")
        self._log(f"Verificando si existe la base {self.db_name}")
        quoted_db_name = self._quote_literal(self.db_name)
        quoted_db_ident = self._quote_ident(self.db_name)
        ok, out = self._run_cmd(
            [
                "psql", "-h", self.db_host, "-p", self.db_port,
                "-U", self.db_user, "-d", "postgres", "-tAc",
                f"SELECT 1 FROM pg_database WHERE datname={quoted_db_name};",
            ],
            silent=True,
        )
        if not ok:
            message = "Cancelado" if "Cancelado" in out else self._format_cmd_error(out)
            self._log(f"Error verificando base: {message}")
            self.finished_signal.emit(False, message)
            return

        db_exists = out.strip() == "1"

        if db_exists:
            if self.drop_if_exists:
                self._log(f"La base existe. Cerrando conexiones activas de {self.db_name}")
                ok, out = self._terminate_db_connections()
                if not ok:
                    message = self._format_cmd_error(out)
                    self._log(f"Error cerrando conexiones: {message}")
                    self.finished_signal.emit(
                        False,
                        f"No se pudieron cerrar las conexiones activas: {message}",
                    )
                    return
                self._log(f"Conexiones activas cerradas. Eliminando {self.db_name}")
                ok, out = self._run_cmd([
                    "psql", "-h", self.db_host, "-p", self.db_port,
                    "-U", self.db_user, "-d", "postgres", "-c",
                    f"DROP DATABASE {quoted_db_ident};",
                ])
                if not ok:
                    message = self._format_cmd_error(out)
                    self._log(f"Error eliminando base: {message}")
                    self.finished_signal.emit(False, f"Error al eliminar BD: {message}")
                    return
            else:
                self._log(
                    f"La base {self.db_name} ya existe. "
                    "Activa 'Eliminar si existe' para reemplazarla."
                )
                self.finished_signal.emit(False, f"La base {self.db_name} ya existe")
                return

        # -- Step 3: Crear BD --
        self.step_changed.emit(3, f"Creando base de datos {self.db_name}...")
        self._log(f"Creando base {self.db_name}")
        ok, out = self._run_cmd([
            "psql", "-h", self.db_host, "-p", self.db_port,
            "-U", self.db_user, "-d", "postgres", "-c",
            f"CREATE DATABASE {quoted_db_ident};",
        ])
        if not ok:
            message = self._format_cmd_error(out)
            self._log(f"Error creando base: {message}")
            self.finished_signal.emit(False, f"Error al crear BD: {message}")
            return

        # -- Step 4: Restaurar dump + filestore --
        self.step_changed.emit(4, "Restaurando dump.sql...")
        self._log(f"Restaurando dump.sql en {self.db_name}")
        ok, out = self._run_cmd([
            "psql", "-h", self.db_host, "-p", self.db_port,
            "-U", self.db_user, "-d", self.db_name, "-f", sql_dump,
        ])
        if not ok:
            message = self._format_cmd_error(out)
            self._log(f"Error restaurando dump: {message}")
            self.finished_signal.emit(False, f"Error al restaurar dump: {message}")
            return

        if self.copy_filestore:
            target_fs = os.path.join(self.filestore_root, self.db_name)
            self._log(f"Copiando filestore a {target_fs}")
            os.makedirs(target_fs, exist_ok=True)
            ok, out = self._run_cmd(
                ["rsync", "-a", "--delete", f"{source_fs}/", f"{target_fs}/"]
            )
            if not ok:
                message = self._format_cmd_error(out)
                self._log(f"Error copiando filestore: {message}")
                self.finished_signal.emit(False, f"Error copiando filestore: {message}")
                return

        # -- Step 5: Neutralizar --
        if self.neutralize:
            self.step_changed.emit(5, "Neutralizando base de datos...")
            self._log("Neutralizando base de datos con archivos neutralize.sql de Odoo")
            self._run_odoo_neutralize()
            self._log("Neutralizacion completada")
        else:
            self.step_changed.emit(5, "Neutralizacion omitida")

        # -- Step 6: Validar --
        self.step_changed.emit(6, "Validando restauracion...")
        self._log("Validando restauracion")
        ok, out = self._run_cmd(
            [
                "psql", "-h", self.db_host, "-p", self.db_port,
                "-U", self.db_user, "-d", self.db_name, "-tAc",
                "SELECT COUNT(*) FROM information_schema.tables "
                "WHERE table_schema = 'public';",
            ],
            silent=True,
        )
        if ok:
            count = out.strip()
            self._log(f"Tablas publicas encontradas: {count}")

        self._log(f"Restauracion completada para {self.db_name}")
        self.finished_signal.emit(True, "Restauracion completada exitosamente")


class UpdateCheckWorker(QThread):
    completed = pyqtSignal(object, bool, str)

    def __init__(self, manual: bool = False) -> None:
        super().__init__()
        self.manual = manual

    def run(self) -> None:
        try:
            release = fetch_latest_release(system=platform_module.system())
            self.completed.emit(release, self.manual, "")
        except Exception as exc:
            self.completed.emit(None, self.manual, str(exc))


# ---------------------------------------------------------------------------
# MainWindow
# ---------------------------------------------------------------------------


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("Odoo Restore Manager")
        self.setWindowIcon(QIcon(str(APP_ICON_FILE)))
        self.resize(700, 600)

        self._history = HistoryManager()
        self._worker: RestoreWorker | None = None
        self._update_worker: UpdateCheckWorker | None = None
        self._start_time: float = 0
        self._tabs = QTabWidget()

        self._build_ui()
        self._refresh_history()
        QTimer.singleShot(1200, self._check_updates_on_startup)

    def _build_ui(self) -> None:
        self._tabs.addTab(self._build_restore_tab(), "Restaurar")
        self._tabs.addTab(self._build_history_tab(), "Historial")
        self.setCentralWidget(self._tabs)

        self._status_bar = QStatusBar()
        self.setStatusBar(self._status_bar)
        self._status_bar.showMessage("Listo para restaurar")

    def _build_restore_tab(self) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)

        form = QFormLayout()

        self._db_name = QLineEdit()
        self._db_name.setPlaceholderText("Nombre de la base de datos")
        form.addRow("Base de datos:", self._db_name)

        backup_row = QHBoxLayout()
        self._backup_dir = QLineEdit()
        self._backup_dir.setPlaceholderText("/ruta/al/respaldo")
        btn_browse_backup = QPushButton("Explorar...")
        btn_browse_backup.clicked.connect(self._browse_backup_dir)
        backup_row.addWidget(self._backup_dir, 1)
        backup_row.addWidget(btn_browse_backup)
        form.addRow("Directorio backup:", backup_row)

        form.addRow(QLabel(""))
        pg_label = QLabel("PostgreSQL")
        pg_label.setStyleSheet("font-weight: bold;")
        form.addRow(pg_label)

        self._db_host = QLineEdit("localhost")
        form.addRow("Host:", self._db_host)

        self._db_port = QLineEdit("5432")
        self._db_port.setValidator(QIntValidator(1, 65535))
        form.addRow("Puerto:", self._db_port)

        self._db_user = QLineEdit("odoo")
        form.addRow("Usuario:", self._db_user)

        self._db_password = QLineEdit()
        self._db_password.setEchoMode(QLineEdit.EchoMode.Password)
        form.addRow("Password:", self._db_password)

        form.addRow(QLabel(""))
        opt_label = QLabel("Opciones")
        opt_label.setStyleSheet("font-weight: bold;")
        form.addRow(opt_label)

        self._chk_filestore = QCheckBox("Copiar filestore")
        self._chk_filestore.setChecked(True)
        self._chk_filestore.toggled.connect(self._on_filestore_toggled)
        form.addRow(self._chk_filestore)

        self._chk_drop = QCheckBox("Eliminar BD si ya existe")
        form.addRow(self._chk_drop)

        self._chk_neutralize = QCheckBox(
            "Neutralizar base de datos"
        )
        self._chk_neutralize.setChecked(True)
        self._chk_neutralize.toggled.connect(self._on_neutralize_toggled)
        form.addRow(self._chk_neutralize)

        addon_row_1 = QHBoxLayout()
        self._addon_path_1 = QLineEdit()
        self._addon_path_1.setPlaceholderText(
            "Ejemplo: /home/xxxx/Trabajo/repos/odoo-12.0/addons"
        )
        self._addon_path_1.setEnabled(True)
        self._btn_browse_addons_1 = QPushButton("Explorar...")
        self._btn_browse_addons_1.setEnabled(True)
        self._btn_browse_addons_1.clicked.connect(partial(self._browse_addon_path, self._addon_path_1))
        addon_row_1.addWidget(self._addon_path_1, 1)
        addon_row_1.addWidget(self._btn_browse_addons_1)
        form.addRow("Ruta fuente 1:", addon_row_1)

        addon_row_2 = QHBoxLayout()
        self._addon_path_2 = QLineEdit()
        self._addon_path_2.setPlaceholderText(
            "Ejemplo: /home/xxxx/Trabajo/repos/odoo-12.0/odoo/addons"
        )
        self._addon_path_2.setEnabled(True)
        self._btn_browse_addons_2 = QPushButton("Explorar...")
        self._btn_browse_addons_2.setEnabled(True)
        self._btn_browse_addons_2.clicked.connect(partial(self._browse_addon_path, self._addon_path_2))
        addon_row_2.addWidget(self._addon_path_2, 1)
        addon_row_2.addWidget(self._btn_browse_addons_2)
        form.addRow("Ruta fuente 2:", addon_row_2)

        fs_row = QHBoxLayout()
        default_fs = os.path.join(
            str(Path.home()), ".local", "share", "Odoo", "filestore"
        )
        self._filestore_root = QLineEdit(default_fs)
        btn_browse_fs = QPushButton("Explorar...")
        btn_browse_fs.clicked.connect(self._browse_filestore_root)
        fs_row.addWidget(self._filestore_root, 1)
        fs_row.addWidget(btn_browse_fs)
        self._fs_browse_btn = btn_browse_fs
        form.addRow("Filestore root:", fs_row)

        layout.addLayout(form)

        # -- Progress bar --
        self._progress = QProgressBar()
        self._progress.setRange(0, RestoreWorker.TOTAL_STEPS)
        self._progress.setValue(0)
        self._progress.setTextVisible(False)
        self._progress.setFixedHeight(8)
        self._progress.hide()
        layout.addWidget(self._progress)

        # -- Buttons --
        btn_row = QHBoxLayout()
        self._step_label = QLabel("")
        self._step_label.setStyleSheet("color: gray; font-size: 11px;")
        btn_row.addWidget(self._step_label)
        btn_row.addStretch()
        self._btn_restore = QPushButton("Restaurar")
        self._btn_restore.clicked.connect(self._on_restore_clicked)
        self._btn_cancel = QPushButton("Cancelar")
        self._btn_cancel.setEnabled(False)
        self._btn_cancel.clicked.connect(self._on_cancel_clicked)
        btn_row.addWidget(self._btn_restore)
        btn_row.addWidget(self._btn_cancel)
        layout.addLayout(btn_row)

        # -- Log area --
        self._log_area = QTextEdit()
        self._log_area.setReadOnly(True)
        self._log_area.setFont(QFont("monospace", 9))
        layout.addWidget(self._log_area, 1)

        return widget

    def _build_history_tab(self) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)

        self._history_table = QTableWidget(0, 5)
        self._history_table.setHorizontalHeaderLabels(
            ["Fecha", "Base de datos", "Directorio", "Resultado", "Duracion"]
        )
        header = self._history_table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(4, QHeaderView.ResizeMode.ResizeToContents)
        self._history_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._history_table.setSelectionBehavior(
            QTableWidget.SelectionBehavior.SelectRows
        )
        self._history_table.verticalHeader().setVisible(False)
        self._history_table.setAlternatingRowColors(True)
        layout.addWidget(self._history_table, 1)

        btn_row = QHBoxLayout()
        self._history_count = QLabel("")
        self._history_count.setStyleSheet("color: gray; font-size: 11px;")
        btn_row.addWidget(self._history_count)
        btn_row.addStretch()

        btn_repeat = QPushButton("Repetir seleccionada")
        btn_repeat.clicked.connect(self._on_repeat_history)
        btn_row.addWidget(btn_repeat)

        btn_clear = QPushButton("Limpiar historial")
        btn_clear.clicked.connect(self._on_clear_history)
        btn_row.addWidget(btn_clear)
        layout.addLayout(btn_row)

        return widget

    # -- Slots ----------------------------------------------------------

    def _on_filestore_toggled(self, checked: bool) -> None:
        self._filestore_root.setEnabled(checked)
        self._fs_browse_btn.setEnabled(checked)

    def _on_neutralize_toggled(self, checked: bool) -> None:
        self._addon_path_1.setEnabled(checked)
        self._btn_browse_addons_1.setEnabled(checked)
        self._addon_path_2.setEnabled(checked)
        self._btn_browse_addons_2.setEnabled(checked)

    def _expand_source_paths(self, path: str) -> list[str]:
        normalized = os.path.abspath(path)
        candidates = [
            normalized,
            os.path.join(normalized, "addons"),
            os.path.join(normalized, "odoo", "addons"),
        ]
        expanded = []
        for candidate in candidates:
            if os.path.isdir(candidate) and candidate not in expanded:
                expanded.append(candidate)
        return expanded or [normalized]

    def _browse_addon_path(self, target: QLineEdit) -> None:
        path = QFileDialog.getExistingDirectory(
            self, "Seleccionar ruta fuente de Odoo"
        )
        if path:
            target.setText(path)

    def _browse_backup_dir(self) -> None:
        path = QFileDialog.getExistingDirectory(self, "Seleccionar directorio de backup")
        if path:
            self._backup_dir.setText(path)

    def _browse_filestore_root(self) -> None:
        path = QFileDialog.getExistingDirectory(self, "Seleccionar filestore root")
        if path:
            self._filestore_root.setText(path)

    def _check_updates_on_startup(self) -> None:
        self._start_update_check(manual=False)

    def _start_update_check(self, manual: bool) -> None:
        if self._update_worker is not None and self._update_worker.isRunning():
            return

        self._update_worker = UpdateCheckWorker(manual=manual)
        self._update_worker.completed.connect(self._on_update_check_finished)
        self._update_worker.start()

    def _release_notes_excerpt(self, notes: str) -> str:
        if not notes.strip():
            return "Sin notas de release."
        lines = [line.strip() for line in notes.splitlines() if line.strip()]
        excerpt = "\n".join(lines[:8])
        return excerpt[:600]

    def _open_url(self, url: str) -> None:
        QDesktopServices.openUrl(QUrl(url))

    def _on_update_check_finished(self, release: object, manual: bool, error: str) -> None:
        self._update_worker = None

        if error:
            return

        if release is None:
            return

        if not is_newer_version(APP_VERSION, release.version):
            return

        if not release.download_url:
            reply = QMessageBox.question(
                self,
                "Actualizacion disponible",
                (
                    f"Se detecto una nueva version ({release.version}), pero no hay instalador "
                    f"para {platform_label()} en la release.\n\n"
                    "Quieres abrir la pagina de releases?"
                ),
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            )
            if reply == QMessageBox.StandardButton.Yes and release.html_url:
                self._open_url(release.html_url)
            return

        message = (
            f"Se detecto una nueva version.\n\n"
            f"Version actual: {APP_VERSION}\n"
            f"Nueva version: {release.version}\n"
            f"Release: {release.release_name}\n\n"
            "Quieres descargar la actualizacion?\n\n"
            f"{self._release_notes_excerpt(release.release_notes)}"
        )
        dialog = QMessageBox(self)
        dialog.setWindowTitle("Actualizacion disponible")
        dialog.setIcon(QMessageBox.Icon.Information)
        dialog.setText(message)
        download_button = dialog.addButton(
            "Descargar",
            QMessageBox.ButtonRole.AcceptRole,
        )
        dialog.addButton("Cancelar", QMessageBox.ButtonRole.RejectRole)
        dialog.exec()
        if dialog.clickedButton() == download_button:
            self._open_url(release.download_url)

    def _on_restore_clicked(self) -> None:
        db_name = self._db_name.text().strip()
        backup_dir = self._backup_dir.text().strip()

        if not db_name:
            QMessageBox.warning(self, "Campo requerido", "Ingresa el nombre de la base de datos.")
            self._db_name.setFocus()
            return
        if not backup_dir:
            QMessageBox.warning(self, "Campo requerido", "Ingresa el directorio de backup.")
            self._backup_dir.setFocus()
            return

        addon_paths = []
        for source_path in (
            self._addon_path_1.text().strip(),
            self._addon_path_2.text().strip(),
        ):
            if not source_path:
                continue
            for candidate in self._expand_source_paths(source_path):
                if candidate not in addon_paths:
                    addon_paths.append(candidate)

        if self._chk_neutralize.isChecked() and not addon_paths:
            QMessageBox.warning(
                self,
                "Campo requerido",
                "Para neutralizar como Odoo, ingresa al menos una ruta fuente.",
            )
            self._addon_path_1.setFocus()
            return

        self._log_area.clear()
        self._btn_restore.setEnabled(False)
        self._btn_cancel.setEnabled(True)
        self._progress.setValue(0)
        self._progress.show()
        self._step_label.setText("")
        self._start_time = time.time()

        self._worker = RestoreWorker(
            db_name=db_name,
            backup_dir=backup_dir,
            db_host=self._db_host.text().strip() or "localhost",
            db_port=self._db_port.text().strip() or "5432",
            db_user=self._db_user.text().strip() or "odoo",
            db_password=self._db_password.text(),
            filestore_root=self._filestore_root.text().strip(),
            copy_filestore=self._chk_filestore.isChecked(),
            drop_if_exists=self._chk_drop.isChecked(),
            neutralize=self._chk_neutralize.isChecked(),
            addon_paths=addon_paths,
        )
        self._worker.log_message.connect(self._on_log_message)
        self._worker.finished_signal.connect(self._on_restore_finished)
        self._worker.step_changed.connect(self._on_step_changed)
        self._worker.start()

    def _on_cancel_clicked(self) -> None:
        if self._worker is not None:
            self._worker.cancel()

    def _on_log_message(self, msg: str) -> None:
        self._log_area.append(msg)

    def _on_step_changed(self, step: int, desc: str) -> None:
        self._progress.setValue(step)
        self._step_label.setText(f"Paso {step}/{RestoreWorker.TOTAL_STEPS}: {desc}")
        self._status_bar.showMessage(desc)

    def _on_restore_finished(self, success: bool, message: str) -> None:
        duration = time.time() - self._start_time
        self._btn_restore.setEnabled(True)
        self._btn_cancel.setEnabled(False)
        self._step_label.setText("")

        if success:
            self._progress.setValue(RestoreWorker.TOTAL_STEPS)
            self._status_bar.showMessage(f"Completado en {duration:.1f}s")
        else:
            self._progress.hide()
            self._status_bar.showMessage("Error")

        db_name = self._db_name.text().strip()
        backup_dir = self._backup_dir.text().strip()

        self._history.add_entry(
            db_name=db_name,
            backup_dir=backup_dir,
            success=success,
            duration=duration,
            error=None if success else message,
        )
        self._refresh_history()

        if success:
            QMessageBox.information(self, "Exito", message)
        else:
            QMessageBox.critical(self, "Error", message)

    def _on_clear_history(self) -> None:
        reply = QMessageBox.question(
            self,
            "Confirmar",
            "Eliminar todo el historial?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply == QMessageBox.StandardButton.Yes:
            self._history.clear()
            self._refresh_history()

    def _on_repeat_history(self) -> None:
        row = self._history_table.currentRow()
        if row < 0:
            QMessageBox.information(self, "Seleccionar", "Selecciona una fila del historial.")
            return
        db_name = self._history_table.item(row, 1).text()
        backup_dir = self._history_table.item(row, 2).text()
        self._db_name.setText(db_name)
        self._backup_dir.setText(backup_dir)
        self._tabs.setCurrentIndex(0)

    # -- History table --------------------------------------------------

    def _refresh_history(self) -> None:
        entries = self._history.load()
        self._history_table.setRowCount(len(entries))
        for row, entry in enumerate(reversed(entries)):
            self._history_table.setItem(row, 0, QTableWidgetItem(entry.get("date", "")))
            self._history_table.setItem(row, 1, QTableWidgetItem(entry.get("db_name", "")))
            self._history_table.setItem(row, 2, QTableWidgetItem(entry.get("backup_dir", "")))

            success = entry.get("success")
            result = "OK" if success else "Error"
            item = QTableWidgetItem(result)
            if not success:
                item.setForeground(QColor(Qt.GlobalColor.red))
            else:
                item.setForeground(QColor(Qt.GlobalColor.darkGreen))
            item.setFont(QFont("", -1, QFont.Weight.Bold))
            self._history_table.setItem(row, 3, item)

            dur = entry.get("duration_seconds", 0)
            self._history_table.setItem(row, 4, QTableWidgetItem(f"{dur}s"))

        count = len(entries)
        self._history_count.setText(f"{count} restauracion{'es' if count != 1 else ''}")
