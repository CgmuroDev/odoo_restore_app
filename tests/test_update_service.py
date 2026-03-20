from __future__ import annotations

import sys
import tempfile
import unittest
import zipfile
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

SRC_DIR = Path(__file__).resolve().parents[1] / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

import update_service
from update_service import (
    apply_update,
    asset_name_for_platform,
    download_release_asset,
    extract_macos_app,
    is_newer_version,
    parse_latest_release,
    install_linux_deb,
)


class FakeResponse:
    def __init__(self, payload: bytes) -> None:
        self._payload = payload
        self._offset = 0
        self.headers = {"Content-Length": str(len(payload))}

    def read(self, size: int = -1) -> bytes:
        if size < 0:
            size = len(self._payload) - self._offset
        chunk = self._payload[self._offset:self._offset + size]
        self._offset += len(chunk)
        return chunk

    def __enter__(self) -> FakeResponse:
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        return False


class UpdateServiceTests(unittest.TestCase):
    def test_is_newer_version(self) -> None:
        self.assertTrue(is_newer_version("1.0.0", "1.0.1"))
        self.assertFalse(is_newer_version("1.0.0", "1.0.0"))
        self.assertFalse(is_newer_version("1.2.0", "1.1.9"))

    def test_asset_name_for_linux(self) -> None:
        self.assertEqual(
            asset_name_for_platform("1.2.3", system="Linux"),
            "odoo-restore_1.2.3_all.deb",
        )

    def test_asset_name_for_macos(self) -> None:
        self.assertEqual(
            asset_name_for_platform("1.2.3", system="Darwin"),
            "OdooRestore-macOS-1.2.3.zip",
        )

    def test_parse_latest_release_uses_platform_asset(self) -> None:
        release = parse_latest_release(
            {
                "tag_name": "v1.2.3",
                "name": "v1.2.3",
                "body": "Cambios",
                "html_url": "https://example.invalid/release",
                "assets": [
                    {
                        "name": "odoo-restore_1.2.3_all.deb",
                        "browser_download_url": "https://example.invalid/linux.deb",
                    }
                ],
            },
            system="Linux",
        )
        self.assertEqual(release.version, "1.2.3")
        self.assertEqual(release.download_url, "https://example.invalid/linux.deb")

    def test_parse_latest_release_without_asset_keeps_release(self) -> None:
        release = parse_latest_release(
            {
                "tag_name": "v1.2.3",
                "name": "v1.2.3",
                "body": "",
                "html_url": "https://example.invalid/release",
                "assets": [],
            },
            system="Darwin",
        )
        self.assertEqual(release.version, "1.2.3")
        self.assertIsNone(release.download_url)

    def test_download_release_asset_writes_expected_file(self) -> None:
        release = parse_latest_release(
            {
                "tag_name": "v1.2.3",
                "name": "v1.2.3",
                "body": "",
                "html_url": "https://example.invalid/release",
                "assets": [
                    {
                        "name": "odoo-restore_1.2.3_all.deb",
                        "browser_download_url": "https://example.invalid/linux.deb",
                    }
                ],
            },
            system="Linux",
        )
        progress_calls: list[tuple[str, int, int]] = []
        with tempfile.TemporaryDirectory() as tmpdir:
            cache_dir = Path(tmpdir)
            with mock.patch.object(update_service, "UPDATE_CACHE_DIR", cache_dir):
                with mock.patch.object(
                    update_service,
                    "urlopen",
                    return_value=FakeResponse(b"deb-content"),
                ):
                    downloaded = download_release_asset(
                        release,
                        system="Linux",
                        progress_callback=lambda message, current, total: progress_calls.append(
                            (message, current, total)
                        ),
                    )
                    self.assertTrue(downloaded.name.endswith(".deb"))
                    self.assertEqual(downloaded.read_bytes(), b"deb-content")

        self.assertGreaterEqual(len(progress_calls), 1)

    def test_extract_macos_app_returns_bundle_path(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            zip_path = tmp_path / "OdooRestore-macOS-1.2.3.zip"
            with zipfile.ZipFile(zip_path, "w") as archive:
                archive.writestr("OdooRestore.app/Contents/Info.plist", "plist")

            with mock.patch.object(update_service, "UPDATE_CACHE_DIR", tmp_path / "cache"):
                app_path = extract_macos_app(zip_path, "1.2.3")
                self.assertEqual(app_path.name, "OdooRestore.app")
                self.assertTrue(app_path.is_dir())

    def test_install_linux_deb_invokes_pkexec(self) -> None:
        package_path = Path("/tmp/odoo-restore_1.2.3_all.deb")
        with mock.patch.object(
            update_service.subprocess,
            "run",
            return_value=SimpleNamespace(returncode=0, stdout="", stderr=""),
        ) as mocked_run:
            install_linux_deb(package_path)

        mocked_run.assert_called_once_with(
            ["pkexec", "dpkg", "-i", str(package_path)],
            capture_output=True,
            text=True,
            check=False,
        )

    def test_apply_update_for_linux_returns_installed_result(self) -> None:
        release = parse_latest_release(
            {
                "tag_name": "v1.2.3",
                "name": "v1.2.3",
                "body": "",
                "html_url": "https://example.invalid/release",
                "assets": [
                    {
                        "name": "odoo-restore_1.2.3_all.deb",
                        "browser_download_url": "https://example.invalid/linux.deb",
                    }
                ],
            },
            system="Linux",
        )
        downloaded_path = Path("/tmp/odoo-restore_1.2.3_all.deb")
        progress_calls: list[tuple[str, int, int]] = []
        with mock.patch.object(update_service, "download_release_asset", return_value=downloaded_path):
            with mock.patch.object(update_service, "install_linux_deb") as mocked_install:
                result = apply_update(
                    release,
                    system="Linux",
                    progress_callback=lambda message, current, total: progress_calls.append(
                        (message, current, total)
                    ),
                )

        mocked_install.assert_called_once_with(downloaded_path)
        self.assertEqual(result.action, "installed")
        self.assertEqual(result.downloaded_file, downloaded_path)
        self.assertGreaterEqual(len(progress_calls), 1)


if __name__ == "__main__":
    unittest.main()
