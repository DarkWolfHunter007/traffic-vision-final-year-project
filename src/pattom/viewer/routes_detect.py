"""Detection preview on one frame, and the tiling part of the detection settings.

The preview runs the same detect_frame as the pipeline, once on the whole
frame only and once with the chosen tiles, so the two can be compared on the
user's own footage before a long run. Nothing is written by the preview.
"""

from __future__ import annotations

import re
import threading
import time
from collections import Counter
from dataclasses import replace
from pathlib import Path
from typing import Any

import yaml
from fastapi import APIRouter, Body, HTTPException

from pattom.viewer.common import inside, validated_write

DETECTION = "configs/detection.yaml"
TILING_KEYS = ("tiles", "tile_grid", "tile_imgsz", "merge_inside")
_lock = threading.Lock()
_detectors: dict[str, Any] = {}


def set_top_level_keys(text: str, updates: dict[str, Any]) -> str:
    """Replace (or append) top-level YAML keys, keeping the rest of the file and its comments."""
    lines = text.splitlines()
    for key, value in updates.items():
        dumped = yaml.safe_dump({key: value}, default_flow_style=True, sort_keys=False, width=4096).strip()[1:-1]
        pat = re.compile(rf"^{re.escape(key)}\s*:")
        idx = next((i for i, ln in enumerate(lines) if pat.match(ln)), None)
        if idx is None:
            lines.append(dumped)
            continue
        end = idx + 1
        while end < len(lines) and (lines[end].startswith((" ", "\t", "-")) and lines[end].strip()):
            end += 1
        comment = lines[idx].split("#", 1)[1] if "#" in lines[idx] and not lines[idx].lstrip().startswith("#") else ""
        lines[idx:end] = [dumped + (f"  #{comment}" if comment else "")]
    return "\n".join(lines) + "\n"


def router(root: Path) -> APIRouter:
    r = APIRouter(prefix="/api")

    def base_config():
        from pattom.detection import DetectionConfig

        p = root / DETECTION
        if not p.exists():
            raise HTTPException(409, "save the detection settings first (Settings page)")
        try:
            return DetectionConfig.load(p)
        except Exception as e:
            raise HTTPException(422, f"detection settings: {e}") from None

    def detector(cfg):
        from pattom.detection import UltralyticsDetector

        key = str(cfg.weights_path())
        if key not in _detectors:
            _detectors.clear()  # one model in GPU memory at a time
            _detectors[key] = UltralyticsDetector(cfg)
        det = _detectors[key]
        det._cfg = cfg  # confidence, half and device are read per call
        return det

    @r.post("/detect/preview")
    def preview(body: dict[str, Any] = Body(...)) -> dict[str, Any]:
        import cv2

        from pattom.detection import detect_frame, map_labels

        cfg = base_config()
        over = {k: body[k] for k in TILING_KEYS + ("imgsz",) if k in body}
        try:
            tiled = replace(cfg, **over)
        except TypeError as e:
            raise HTTPException(422, str(e)) from None
        whole = replace(cfg, tiles=[], tile_grid=None)
        path = inside(root, body.get("path", ""))
        cap = cv2.VideoCapture(str(path))
        try:
            cap.set(cv2.CAP_PROP_POS_MSEC, float(body.get("t", 0)) * 1000.0)
            ok, image = cap.read()
        finally:
            cap.release()
        if not ok:
            raise HTTPException(422, "could not read that frame")
        h, w = image.shape[:2]
        out: dict[str, Any] = {"width": w, "height": h, "tiles": tiled.tiles_for(w, h)}
        with _lock:
            try:
                det = detector(cfg)
            except FileNotFoundError as e:
                raise HTTPException(409, str(e)) from None
            for name, c in (("whole_frame", whole), ("with_tiles", tiled)):
                t0 = time.perf_counter()
                ignored: Counter = Counter()
                try:
                    dets = map_labels(detect_frame(image, c, det), c, ignored)
                except ValueError as e:
                    raise HTTPException(422, str(e)) from None
                out[name] = {
                    "seconds": round(time.perf_counter() - t0, 3),
                    "boxes": [{"xyxy": [round(float(v), 1) for v in d["xyxy"]], "class": d["class"],
                               "confidence": round(float(d["confidence"]), 3), "pass": d["pass"]} for d in dets],
                }
        return out

    @r.put("/settings/detection/tiling")
    def save_tiling(body: dict[str, Any] = Body(...)) -> dict[str, Any]:
        from pattom.detection import DetectionConfig

        p = inside(root, DETECTION)
        if not p.exists():
            raise HTTPException(409, "save the detection settings first")
        updates = {k: body.get(k) for k in TILING_KEYS if k in body}
        text = set_top_level_keys(p.read_text(encoding="utf-8-sig"), updates)
        validated_write(p, text, DetectionConfig.load)
        return {"saved": updates}

    return r
