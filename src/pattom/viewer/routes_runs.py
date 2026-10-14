"""Videos and run results: listing, frames, streaming, boxes, tracks. Read-only."""

from __future__ import annotations

import csv
from functools import lru_cache
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import FileResponse, Response

from pattom.viewer.common import BROWSER_VIDEO, VIDEO_EXT, inside, read_json, rel

VIDEO_DIRS = ("data/raw", "data/cfr", "data/undistorted", "raw-video")


@lru_cache(maxsize=8)
def _boxes(path: str, mtime: float, kind: str) -> dict[int, list[list]]:
    """frame -> [[track_id or None, class, confidence, x1, y1, x2, y2], ...]"""
    by_frame: dict[int, list[list]] = {}
    with open(path, newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            tid = int(r["track_id"]) if kind == "tracks" else None
            by_frame.setdefault(int(r["frame"]), []).append(
                [tid, r["class"], float(r["confidence"])] + [float(r[k]) for k in ("x1", "y1", "x2", "y2")])
    return by_frame


def router(root: Path) -> APIRouter:
    r = APIRouter(prefix="/api")
    runs = root / "runs"

    # --- videos -----------------------------------------------------------

    @r.get("/videos")
    def videos() -> list[dict[str, Any]]:
        out = []
        for d in VIDEO_DIRS:
            for p in sorted((root / d).glob("*")) if (root / d).is_dir() else []:
                if p.suffix.lower() in VIDEO_EXT and p.is_file():
                    meta = read_json(p.with_suffix(".run.json"))
                    out.append({"path": rel(root, p), "folder": d, "name": p.name,
                                "size_mb": round(p.stat().st_size / 1e6, 1),
                                "playable": p.suffix.lower() in BROWSER_VIDEO,
                                "prepared_by": (meta or {}).get("stage"),
                                "original": d in ("data/raw", "raw-video")})
        return out

    @r.get("/videos/probe")
    def probe(path: str) -> dict[str, Any]:
        from dataclasses import asdict

        from pattom.prepare import probe as do_probe

        try:
            return asdict(do_probe(inside(root, path)))
        except FileNotFoundError as e:
            raise HTTPException(404, str(e)) from None
        except Exception as e:
            raise HTTPException(422, f"{type(e).__name__}: {e}") from None

    @r.get("/videos/frame")
    def frame(path: str, t: float = Query(0.0, ge=0), w: int = Query(1600, ge=64, le=4096),
              n: int | None = Query(None, ge=0)) -> Response:
        """One frame as JPEG (at time t, or frame number n), scaled to width w. Headers give the full size."""
        import cv2

        p = inside(root, path)
        if not p.exists():
            raise HTTPException(404, f"{path} not found")
        cap = cv2.VideoCapture(str(p))
        try:
            if n is not None:
                cap.set(cv2.CAP_PROP_POS_FRAMES, n)
            else:
                cap.set(cv2.CAP_PROP_POS_MSEC, t * 1000.0)
            ok, img = cap.read()
        finally:
            cap.release()
        if not ok:
            raise HTTPException(422, f"no frame at {t} s")
        h0, w0 = img.shape[:2]
        if w0 > w:
            img = cv2.resize(img, (w, round(h0 * w / w0)), interpolation=cv2.INTER_AREA)
        ok, jpg = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, 85])
        return Response(jpg.tobytes(), media_type="image/jpeg",
                        headers={"X-Frame-Width": str(w0), "X-Frame-Height": str(h0), "Cache-Control": "no-store"})

    @r.get("/videos/stream")
    def stream(path: str) -> FileResponse:
        p = inside(root, path)
        if not p.exists():
            raise HTTPException(404, f"{path} not found")
        if p.suffix.lower() not in BROWSER_VIDEO:
            raise HTTPException(415, f"{p.suffix} does not play in a browser; use the CFR .mp4 copy")
        return FileResponse(p, media_type="video/mp4")

    # --- runs -------------------------------------------------------------

    def run_dir(slot: str, video: str) -> Path:
        d = inside(root, runs / slot / video)
        if not d.is_dir():
            raise HTTPException(404, f"no run {slot}/{video}")
        return d

    def run_meta(d: Path) -> dict[str, Any]:
        meta = read_json(d / "tracks.run.json") or read_json(d / "detections.run.json")
        if meta is None:
            raise HTTPException(404, "run has no detections.run.json")
        return meta

    @r.get("/runs")
    def list_runs() -> list[dict[str, Any]]:
        out = []
        for f in sorted(runs.glob("*/*/detections.csv")):
            d = f.parent
            out.append({"slot": d.parent.name, "video": d.name, "has_tracks": (d / "tracks.csv").exists(),
                        "has_pipeline": (d.parent / "pipeline.json").exists()})
        return out

    @r.get("/runs/{slot}/{video}")
    def run_info(slot: str, video: str) -> dict[str, Any]:
        d = run_dir(slot, video)
        meta = run_meta(d)
        vf = inside(root, meta["video_file"])
        params = meta.get("parameters", {})
        files = sorted(p.name for p in d.iterdir() if p.is_file())
        return {
            "slot": slot, "video": video, "fps": meta["fps"], "width": meta["width"], "height": meta["height"],
            "frame_stride": params.get("frame_stride") or 1, "model": meta.get("model_name"),
            "tracker": meta.get("tracker"), "video_file": rel(root, vf),
            "video_playable": vf.exists() and vf.suffix.lower() in BROWSER_VIDEO,
            "has_tracks": (d / "tracks.csv").exists(), "date_run": meta.get("date_run"),
            "notes": meta.get("notes", ""), "files": files,
        }

    @r.get("/runs/{slot}/{video}/video")
    def run_video(slot: str, video: str) -> FileResponse:
        return stream(run_meta(run_dir(slot, video))["video_file"])

    @r.get("/runs/{slot}/{video}/boxes")
    def boxes(slot: str, video: str, start: int = Query(0, ge=0), end: int = Query(..., ge=0),
              source: str = Query("tracks", pattern="^(tracks|detections)$")) -> dict[str, list[list]]:
        p = run_dir(slot, video) / f"{source}.csv"
        if not p.exists():
            raise HTTPException(404, f"no {source}.csv")
        frames = _boxes(str(p), p.stat().st_mtime, source)
        return {str(f): frames[f] for f in range(start, min(end, start + 20000) + 1) if f in frames}

    @r.get("/runs/{slot}/{video}/tracks")
    def tracks(slot: str, video: str) -> list[dict[str, str]]:
        p = run_dir(slot, video) / "track_summary.csv"
        if not p.exists():
            return []
        with open(p, newline="", encoding="utf-8") as f:
            return list(csv.DictReader(f))

    @r.get("/runs/{slot}/{video}/table/{name}")
    def table(slot: str, video: str, name: str, limit: int = Query(500, ge=1, le=5000)) -> dict[str, Any]:
        """First rows of a CSV output (crossings, interval counts, ...)."""
        p = inside(root, run_dir(slot, video) / name)
        if p.suffix != ".csv" or not p.exists():
            raise HTTPException(404, f"no {name}")
        with open(p, newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            rows = [row for _, row in zip(range(limit), reader)]
            return {"columns": reader.fieldnames or [], "rows": rows}

    return r
