"""Home page status, from the app's own files only, and the source register."""

from __future__ import annotations

import csv
from pathlib import Path
from typing import Any

import yaml
from fastapi import APIRouter

from pattom.viewer.common import VIDEO_EXT, read_json


def _exists(root: Path, path: str) -> bool:
    return (root / path).exists()


def router(root: Path) -> APIRouter:
    r = APIRouter(prefix="/api")

    @r.get("/status")
    def status() -> dict[str, Any]:
        from pattom.harness import Pipeline

        originals = [p for d in ("data/raw", "raw-video") if (root / d).is_dir()
                     for p in (root / d).iterdir() if p.suffix.lower() in VIDEO_EXT]
        prepared = [p for d in ("data/cfr", "data/undistorted") if (root / d).is_dir()
                    for p in (root / d).iterdir() if p.suffix.lower() in VIDEO_EXT]
        weights = sorted(p.name for p in (root / "models").glob("*.pt")) if (root / "models").is_dir() else []
        pipe: dict[str, Any] = {"saved": _exists(root, "configs/pipeline.yaml")}
        if pipe["saved"]:
            try:
                p = Pipeline.load(root / "configs/pipeline.yaml")
                p.repo_root, p.runs_dir = root, root / "runs"
                pipe.update(slot=p.slot, problems=p.check(),
                            enabled=[s.id for s in p.steps if s.enabled])
                last = read_json(p.manifest_path()) or {}
                pipe["last_run"] = {"date": last.get("date_run"),
                                    "steps": [(s["id"], s.get("status")) for s in last.get("steps", [])]}
            except Exception as e:
                pipe["error"] = str(e)
        lines = 0
        if _exists(root, "configs/lines.yaml"):
            lines = len((yaml.safe_load((root / "configs/lines.yaml").read_text(encoding="utf-8")) or {}).get("lines") or [])
        ground = None
        if _exists(root, "calibration/ground.yaml"):
            from pattom.viewer.routes_tools import _ground_report

            ground = _ground_report(yaml.safe_load((root / "calibration/ground.yaml").read_text(encoding="utf-8")) or {})
        phase_logs = {}
        for f in sorted((root / "runs").glob("*/phase_log.csv")) if (root / "runs").is_dir() else []:
            with open(f, newline="", encoding="utf-8") as fh:
                phase_logs[f.parent.name] = sum(1 for _ in csv.DictReader(fh))
        runs = [f.parent for f in sorted((root / "runs").glob("*/*/detections.csv"))] if (root / "runs").is_dir() else []
        return {
            "videos": {"originals": len(originals), "prepared": len(prepared)},
            "lens": _exists(root, "calibration/lens.json"),
            "settings": {"detection": _exists(root, "configs/detection.yaml"),
                         "tracker": _exists(root, "configs/tracker.yaml")},
            "weights": weights,
            "pipeline": pipe,
            "lines": lines,
            "ground": ground,
            "phase_logs": phase_logs,
            "runs": [{"slot": d.parent.name, "video": d.name, "tracks": (d / "tracks.csv").exists(),
                      "counts": (d / "interval_counts.csv").exists()} for d in runs],
        }

    @r.get("/status/gpu")
    def gpu() -> dict[str, Any]:
        """Whether YOLO can use the GPU from this interpreter (imports PyTorch, a few seconds)."""
        try:
            import torch
        except ImportError:
            return {"torch": None, "cuda": False, "note": "PyTorch not installed (detect extra)"}
        cuda = torch.cuda.is_available()
        return {"torch": torch.__version__, "cuda": cuda, "device": torch.cuda.get_device_name(0) if cuda else None}

    @r.get("/register")
    def register() -> dict[str, Any]:
        data = yaml.safe_load((root / "sources/register.yaml").read_text(encoding="utf-8")) or {}
        values = []
        for key, e in (data.get("values") or {}).items():
            values.append({"key": key, "value": e.get("value"), "unit": e.get("unit"), "source": e.get("source"),
                           "ref": e.get("ref"), "status": e.get("status"), "note": e.get("note")})
        return {"sources": data.get("sources") or {}, "values": values}

    return r
