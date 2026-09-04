"""Centralized configuration for wavSIH26 / Raaya service layer.

OWNED BY: Naidhruv.
Supports environment-variable overrides with safe local defaults.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]


@dataclass(frozen=True)
class AppConfig:
    """Application runtime configuration."""

    repo_root: Path = REPO_ROOT
    upload_dir: Path = Path(os.environ.get("RAAYA_UPLOAD_DIR", str(REPO_ROOT / "uploads")))
    artifact_dir: Path = Path(os.environ.get("RAAYA_ARTIFACT_DIR", str(REPO_ROOT / "reports" / "artifacts")))
    db_path: Path = Path(os.environ.get("RAAYA_DB_PATH", str(REPO_ROOT / "raaya.db")))
    max_upload_size_bytes: int = int(
        os.environ.get("RAAYA_MAX_UPLOAD_SIZE", str(2 * 1024 * 1024 * 1024))
    )  # 2 GB
    max_workers: int = int(os.environ.get("RAAYA_MAX_WORKERS", "4"))
    stage_timeout_seconds: float = float(os.environ.get("RAAYA_STAGE_TIMEOUT", "15.0"))
    total_timeout_seconds: float = float(os.environ.get("RAAYA_TOTAL_TIMEOUT", "90.0"))

    def ensure_directories(self) -> None:
        """Create required runtime directories safely."""
        self.upload_dir.mkdir(parents=True, exist_ok=True)
        self.artifact_dir.mkdir(parents=True, exist_ok=True)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)


config = AppConfig()
