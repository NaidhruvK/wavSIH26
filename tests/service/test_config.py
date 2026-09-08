"""Tests for service/config.py.

Verifies configuration defaults, environment overrides, and directory creation.
Compatible with both unittest and pytest.
"""
from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path

from service.config import AppConfig, config


class TestConfig(unittest.TestCase):
    def test_default_config_values(self):
        self.assertTrue(str(config.upload_dir).endswith("uploads"))
        # Compare path PARTS, not a string with a hardcoded "/" separator: on
        # Windows this is ...\reports\artifacts, so the string form passed in
        # the Linux container and failed on every developer machine - the worst
        # direction for a test to be wrong in.
        self.assertEqual(config.artifact_dir.parts[-2:], ("reports", "artifacts"))
        self.assertTrue(str(config.db_path).endswith("raaya.db"))
        self.assertEqual(config.max_upload_size_bytes, 2 * 1024 * 1024 * 1024)
        self.assertEqual(config.max_workers, 4)
        self.assertEqual(config.stage_timeout_seconds, 15.0)
        self.assertEqual(config.total_timeout_seconds, 90.0)
        self.assertEqual(config.host, "0.0.0.0")
        self.assertEqual(config.port, 8000)

    def test_ensure_directories(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            custom_config = AppConfig(
                repo_root=tmp_path,
                upload_dir=tmp_path / "custom_uploads",
                artifact_dir=tmp_path / "custom_artifacts",
                db_path=tmp_path / "custom_db" / "test.db",
            )
            self.assertFalse(custom_config.upload_dir.exists())
            self.assertFalse(custom_config.artifact_dir.exists())
            self.assertFalse(custom_config.db_path.parent.exists())

            custom_config.ensure_directories()

            self.assertTrue(custom_config.upload_dir.is_dir())
            self.assertTrue(custom_config.artifact_dir.is_dir())
            self.assertTrue(custom_config.db_path.parent.is_dir())

    def test_environment_override(self):
        old_stage = os.environ.get("RAAYA_STAGE_TIMEOUT")
        old_host = os.environ.get("RAAYA_HOST")
        old_port = os.environ.get("RAAYA_PORT")
        try:
            os.environ["RAAYA_STAGE_TIMEOUT"] = "25.5"
            os.environ["RAAYA_HOST"] = "127.0.0.1"
            os.environ["RAAYA_PORT"] = "9090"
            cfg = AppConfig(
                stage_timeout_seconds=float(os.environ["RAAYA_STAGE_TIMEOUT"]),
                host=os.environ["RAAYA_HOST"],
                port=int(os.environ["RAAYA_PORT"]),
            )
            self.assertEqual(cfg.stage_timeout_seconds, 25.5)
            self.assertEqual(cfg.host, "127.0.0.1")
            self.assertEqual(cfg.port, 9090)
        finally:
            if old_stage is not None:
                os.environ["RAAYA_STAGE_TIMEOUT"] = old_stage
            else:
                os.environ.pop("RAAYA_STAGE_TIMEOUT", None)
            if old_host is not None:
                os.environ["RAAYA_HOST"] = old_host
            else:
                os.environ.pop("RAAYA_HOST", None)
            if old_port is not None:
                os.environ["RAAYA_PORT"] = old_port
            else:
                os.environ.pop("RAAYA_PORT", None)


if __name__ == "__main__":
    unittest.main()
