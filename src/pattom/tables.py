"""Small CSV and run-metadata helpers for the calculation stages."""

from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any, Iterable

from pattom.runmeta import RunMetadata, sha256_file


def read_csv(path: Path) -> list[dict[str, str]]:
    with open(path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def write_csv(path: Path, fields: list[str], rows: Iterable[dict[str, Any]]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)
    return path


def write_meta(path: Path, stage: str, slot: str, inputs: dict[str, Path], parameters: dict[str, Any],
               notes: str = "") -> Path:
    """Run metadata for a stage that reads tables, not video: each input's SHA-256."""
    video = {"video_file": "", "video_sha256": ""}
    for p in inputs.values():
        meta = Path(p).with_suffix(".run.json")
        if meta.exists():
            m = json.loads(meta.read_text(encoding="utf-8"))
            video = {"video_file": m.get("video_file", ""), "video_sha256": m.get("video_sha256", "")}
            break
    RunMetadata(slot=slot, stage=stage, **video,
                parameters={**parameters, "inputs": {k: str(v) for k, v in inputs.items()},
                            "inputs_sha256": {k: sha256_file(Path(v)) for k, v in inputs.items() if Path(v).is_file()}},
                notes=notes).write(path)
    return path


def require(params: dict[str, Any], *names: str, why: str = "") -> None:
    """Open decisions are passed in, never defaulted."""
    missing = [n for n in names if params.get(n) in (None, "", [], {})]
    if missing:
        raise ValueError(f"missing {missing}" + (f": {why}" if why else ""))


def num(v: str | None) -> float | None:
    try:
        return float(v) if v not in (None, "") else None
    except ValueError:
        return None
