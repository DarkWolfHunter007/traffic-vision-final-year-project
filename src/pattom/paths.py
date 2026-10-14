"""Folder layout (ARCHITECTURE section 10)."""

from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]

DATA_RAW = REPO_ROOT / "data" / "raw"  # originals, never modified
DATA_CFR = REPO_ROOT / "data" / "cfr"  # constant-frame-rate copies
DATA_UNDISTORTED = REPO_ROOT / "data" / "undistorted"
CALIBRATION = REPO_ROOT / "calibration"
LABELS = REPO_ROOT / "labels"
MODELS = REPO_ROOT / "models"
RUNS = REPO_ROOT / "runs"
OUTPUTS = REPO_ROOT / "outputs"
SUMO = REPO_ROOT / "sumo"
