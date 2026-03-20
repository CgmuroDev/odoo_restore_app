from __future__ import annotations

import json
import platform as platform_module
import shutil
import subprocess
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Callable
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from app_meta import APP_DISPLAY_NAME, APP_SLUG, APP_VERSION, GITHUB_RELEASES_API


ProgressCallback = Callable[[str, int, int], None]
UPDATE_CACHE_DIR = Path.home() / ".cache" / APP_SLUG / "updates"


@dataclass(frozen=True)
class UpdateCandidate:
    version: str
    release_name: str
    release_notes: str
    html_url: str
    asset_name: str | None
    download_url: str | None


@dataclass(frozen=True)
class AppliedUpdate:
    version: str
    platform: str
    downloaded_file: Path
    action: str
    extracted_app: Path | None = None


def normalize_version(value: str) -> str:
    normalized = value.strip().lstrip("v")
    parts = normalized.split(".")
    if len(parts) != 3 or any(not part.isdigit() for part in parts):
        raise ValueError(f"Version invalida: {value}")
    return normalized


def version_key(value: str) -> tuple[int, int, int]:
    return tuple(int(part) for part in normalize_version(value).split("."))


def is_newer_version(current: str, remote: str) -> bool:
    return version_key(remote) > version_key(current)


def asset_name_for_platform(version: str, system: str | None = None) -> str | None:
    current_system = system or platform_module.system()
    normalized = normalize_version(version)
    if current_system == "Linux":
        return f"odoo-restore_{normalized}_all.deb"
    if current_system == "Darwin":
        return f"OdooRestore-macOS-{normalized}.zip"
    return None


def platform_label(system: str | None = None) -> str:
    current_system = system or platform_module.system()
    if current_system == "Linux":
        return "Linux"
    if current_system == "Darwin":
        return "macOS"
    return current_system


def parse_latest_release(payload: dict, system: str | None = None) -> UpdateCandidate:
    version = normalize_version(payload["tag_name"])
    expected_asset = asset_name_for_platform(version, system)
    download_url = None
    if expected_asset:
        for asset in payload.get("assets", []):
            if asset.get("name") == expected_asset:
                download_url = asset.get("browser_download_url")
                break
    return UpdateCandidate(
        version=version,
        release_name=payload.get("name") or f"v{version}",
        release_notes=payload.get("body") or "",
        html_url=payload.get("html_url") or "",
        asset_name=expected_asset,
        download_url=download_url,
    )


def _github_request(url: str) -> Request:
    return Request(
        url,
        headers={
            "Accept": "application/vnd.github+json",
            "User-Agent": f"{APP_DISPLAY_NAME}/{APP_VERSION}",
        },
    )


def fetch_latest_release(system: str | None = None, timeout: int = 5) -> UpdateCandidate:
    try:
        with urlopen(_github_request(GITHUB_RELEASES_API), timeout=timeout) as response:
            payload = json.load(response)
    except HTTPError as exc:
        raise RuntimeError(f"GitHub devolvio HTTP {exc.code}") from exc
    except URLError as exc:
        raise RuntimeError("No se pudo conectar con GitHub") from exc
    return parse_latest_release(payload, system=system)


def _emit_progress(
    callback: ProgressCallback | None,
    message: str,
    current: int,
    total: int,
) -> None:
    if callback is not None:
        callback(message, current, total)


def download_release_asset(
    candidate: UpdateCandidate,
    system: str | None = None,
    timeout: int = 30,
    chunk_size: int = 64 * 1024,
    progress_callback: ProgressCallback | None = None,
) -> Path:
    current_system = system or platform_module.system()
    expected_asset = asset_name_for_platform(candidate.version, current_system)
    if not expected_asset or not candidate.download_url:
        raise RuntimeError(
            f"No hay un instalador compatible para {platform_label(current_system)}."
        )
    if candidate.asset_name != expected_asset:
        raise RuntimeError("La release no coincide con el asset esperado.")

    UPDATE_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    target_path = UPDATE_CACHE_DIR / expected_asset
    temp_path = target_path.with_suffix(target_path.suffix + ".part")

    _emit_progress(progress_callback, "Descargando actualizacion...", 0, 0)
    try:
        with urlopen(_github_request(candidate.download_url), timeout=timeout) as response:
            total = int(response.headers.get("Content-Length") or 0)
            downloaded = 0
            with temp_path.open("wb") as handle:
                while True:
                    chunk = response.read(chunk_size)
                    if not chunk:
                        break
                    handle.write(chunk)
                    downloaded += len(chunk)
                    _emit_progress(
                        progress_callback,
                        "Descargando actualizacion...",
                        downloaded,
                        total,
                    )
    except HTTPError as exc:
        raise RuntimeError(f"No se pudo descargar la actualizacion: HTTP {exc.code}") from exc
    except URLError as exc:
        raise RuntimeError("No se pudo descargar la actualizacion desde GitHub.") from exc

    if not temp_path.exists() or temp_path.stat().st_size == 0:
        raise RuntimeError("La descarga termino vacia.")

    temp_path.replace(target_path)
    return target_path


def install_linux_deb(package_path: Path) -> None:
    try:
        completed = subprocess.run(
            ["pkexec", "dpkg", "-i", str(package_path)],
            capture_output=True,
            text=True,
            check=False,
        )
    except FileNotFoundError as exc:
        raise RuntimeError(
            "No se encontro pkexec. Instala policykit-1 para habilitar actualizaciones automaticas."
        ) from exc

    if completed.returncode != 0:
        output = (completed.stderr or completed.stdout or "").strip()
        raise RuntimeError(output or "No se pudo instalar el paquete .deb descargado.")


def extract_macos_app(zip_path: Path, version: str) -> Path:
    extract_dir = UPDATE_CACHE_DIR / f"macos-{normalize_version(version)}"
    if extract_dir.exists():
        shutil.rmtree(extract_dir)
    extract_dir.mkdir(parents=True, exist_ok=True)

    try:
        with zipfile.ZipFile(zip_path, "r") as archive:
            archive.extractall(extract_dir)
    except zipfile.BadZipFile as exc:
        raise RuntimeError("El paquete descargado de macOS no es un zip valido.") from exc

    app_bundle = next(extract_dir.rglob("OdooRestore.app"), None)
    if app_bundle is None:
        raise RuntimeError("No se encontro OdooRestore.app dentro del zip descargado.")
    return app_bundle


def apply_update(
    candidate: UpdateCandidate,
    system: str | None = None,
    progress_callback: ProgressCallback | None = None,
) -> AppliedUpdate:
    current_system = system or platform_module.system()
    downloaded_file = download_release_asset(
        candidate,
        system=current_system,
        progress_callback=progress_callback,
    )

    if current_system == "Linux":
        _emit_progress(progress_callback, "Instalando actualizacion...", 1, 1)
        install_linux_deb(downloaded_file)
        return AppliedUpdate(
            version=candidate.version,
            platform=current_system,
            downloaded_file=downloaded_file,
            action="installed",
        )

    if current_system == "Darwin":
        _emit_progress(progress_callback, "Preparando actualizacion...", 1, 1)
        extracted_app = extract_macos_app(downloaded_file, candidate.version)
        return AppliedUpdate(
            version=candidate.version,
            platform=current_system,
            downloaded_file=downloaded_file,
            action="guided",
            extracted_app=extracted_app,
        )

    raise RuntimeError(
        f"Actualizaciones automaticas no soportadas en {platform_label(current_system)}."
    )
