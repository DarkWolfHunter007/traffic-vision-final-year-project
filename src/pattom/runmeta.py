"""Run metadata, one record per processing run (ARCHITECTURE 4.1, FR-05)."""

from __future__ import annotations

import hashlib
import json
import subprocess
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from pattom.paths import REPO_ROOT


def sha256_file(path: Path, chunk: int = 1 << 20) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while block := f.read(chunk):
            h.update(block)
    return h.hexdigest()


def code_revision() -> str:
    try:
        out = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=REPO_ROOT, capture_output=True, text=True, check=True
        ).stdout.strip()
        dirty = subprocess.run(
            ["git", "status", "--porcelain"], cwd=REPO_ROOT, capture_output=True, text=True, check=True
        ).stdout.strip()
        return out + ("-dirty" if dirty else "")
    except (OSError, subprocess.CalledProcessError):
        return "unknown"


@dataclass
class RunMetadata:
    slot: str
    stage: str
    video_file: str
    video_sha256: str
    fps: float | None = None
    width: int | None = None
    height: int | None = None
    model_name: str | None = None
    model_version: str | None = None
    tracker: str | None = None
    confidence_threshold: float | None = None
    tiling_settings: dict[str, Any] | None = None
    parameters: dict[str, Any] = field(default_factory=dict)
    code_revision: str = field(default_factory=code_revision)
    date_run: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat(timespec="seconds"))
    notes: str = ""

    def write(self, path: Path) -> Path:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(asdict(self), indent=2, sort_keys=True) + "\n", encoding="utf-8")
        return path
