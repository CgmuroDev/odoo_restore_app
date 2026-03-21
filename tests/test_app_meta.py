from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path
from unittest import mock

SRC_DIR = Path(__file__).resolve().parents[1] / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from app_meta import is_snap_runtime


class AppMetaTests(unittest.TestCase):
    def test_is_snap_runtime_false_without_snap_env(self) -> None:
        with mock.patch.dict(os.environ, {}, clear=True):
            self.assertFalse(is_snap_runtime())

    def test_is_snap_runtime_true_with_snap_env(self) -> None:
        with mock.patch.dict(os.environ, {"SNAP": "/snap/odoo-restore/current"}, clear=True):
            self.assertTrue(is_snap_runtime())


if __name__ == "__main__":
    unittest.main()
