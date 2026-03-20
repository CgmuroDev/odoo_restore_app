from __future__ import annotations

import json
import platform as platform_module
from dataclasses import dataclass
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from app_meta import APP_DISPLAY_NAME, APP_VERSION, GITHUB_RELEASES_API


@dataclass(frozen=True)
class UpdateCandidate:
    version: str
    release_name: str
    release_notes: str
    html_url: str
    asset_name: str | None
    download_url: str | None


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


def fetch_latest_release(system: str | None = None, timeout: int = 5) -> UpdateCandidate:
    request = Request(
        GITHUB_RELEASES_API,
        headers={
            "Accept": "application/vnd.github+json",
            "User-Agent": f"{APP_DISPLAY_NAME}/{APP_VERSION}",
        },
    )
    try:
        with urlopen(request, timeout=timeout) as response:
            payload = json.load(response)
    except HTTPError as exc:
        raise RuntimeError(f"GitHub devolvio HTTP {exc.code}") from exc
    except URLError as exc:
        raise RuntimeError("No se pudo conectar con GitHub") from exc
    return parse_latest_release(payload, system=system)
