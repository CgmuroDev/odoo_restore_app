from __future__ import annotations

import sys
import unittest
from pathlib import Path

SRC_DIR = Path(__file__).resolve().parents[1] / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from update_service import (
    asset_name_for_platform,
    is_newer_version,
    parse_latest_release,
)


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


if __name__ == "__main__":
    unittest.main()
