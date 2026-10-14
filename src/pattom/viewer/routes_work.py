"""Pages where the user makes inputs: review and relabelling, manual counts, alternatives, settings files."""

from __future__ import annotations

import csv
import io
import json
from pathlib import Path
from typing import Any

import yaml
from fastapi import APIRouter, Body, HTTPException

from pattom.viewer.common import inside, read_json, rel, validated_write

ALTERNATIVES = "configs/alternatives.yaml"
ALT_HEADER = """# Signal-timing alternatives, saved from the Pattom app (FR-17). Written after the problems
# are known (D4). The existing plan is taken from the observed cycles and is not listed here."""


def router(root: Path) -> APIRouter:
    r = APIRouter(prefix="/api")
    runs = root / "runs"

    def run_dir(slot: str, video: str) -> Path:
        d = inside(root, runs / slot / video)
        if not d.is_dir():
            raise HTTPException(404, f"no run {slot}/{video}")
        return d

    def meta(d: Path) -> dict[str, Any]:
        m = read_json(d / "tracks.run.json") or read_json(d / "detections.run.json")
        if not m:
            raise HTTPException(404, "run has no run metadata")
        return m

    def project_classes() -> list[str]:
        p = root / "configs/detection.yaml"
        cm = (yaml.safe_load(p.read_text(encoding="utf-8-sig")) or {}).get("class_map") if p.exists() else None
        return sorted(set((cm or {}).values())) or ["two_wheeler", "auto_rickshaw", "car", "bus", "truck"]

    # --- review -------------------------------------------------------------

    @r.get("/review/{slot}/{video}")
    def review(slot: str, video: str) -> dict[str, Any]:
        d = run_dir(slot, video)
        m = meta(d)
        queue = list(csv.DictReader(open(d / "review_queue.csv", encoding="utf-8"))) if (d / "review_queue.csv").exists() else []
        labels = inside(root, root / "labels" / slot / video)
        done = {}
        if (labels / "review_log.csv").exists():
            for row in csv.DictReader(open(labels / "review_log.csv", encoding="utf-8")):
                done[row["frame"]] = row["reviewer_action"]
        order = (labels / "classes.txt").read_text(encoding="utf-8").split() if (labels / "classes.txt").exists() else []
        classes = order + [c for c in project_classes() if c not in order]
        return {"queue": queue, "reviewed": done, "classes": classes, "fps": m["fps"], "width": m["width"],
                "height": m["height"], "video_file": rel(root, inside(root, m["video_file"])),
                "labels_dir": rel(root, labels)}

    @r.get("/review/{slot}/{video}/boxes/{frame}")
    def frame_boxes(slot: str, video: str, frame: int) -> list[dict[str, Any]]:
        d = run_dir(slot, video)
        src = d / ("tracks.csv" if (d / "tracks.csv").exists() else "detections.csv")
        out = []
        with open(src, newline="", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                if int(row["frame"]) == frame:
                    out.append({"class": row["class"], "confidence": float(row["confidence"]),
                                "track_id": row.get("track_id"),
                                "xyxy": [float(row[k]) for k in ("x1", "y1", "x2", "y2")]})
        return out

    @r.post("/review/{slot}/{video}/label")
    def save(slot: str, video: str, body: dict[str, Any] = Body(...)) -> dict[str, Any]:
        from pattom.review import save_label

        d = run_dir(slot, video)
        m = meta(d)
        boxes = body.get("boxes") or []
        for b in boxes:
            if not b.get("class") or len(b.get("xyxy") or []) != 4:
                raise HTTPException(422, "each box needs a class and xyxy")
        try:
            label = save_label(inside(root, m["video_file"]), int(body["frame"]), float(m["fps"]), boxes,
                               inside(root, root / "labels" / slot / video), slot, body.get("reason", ""),
                               body.get("action", "corrected"))
        except ValueError as e:
            raise HTTPException(422, str(e)) from None
        return {"label": rel(root, label)}

    # --- manual counts --------------------------------------------------------

    @r.get("/manual/{slot}/{video}")
    def manual(slot: str, video: str) -> dict[str, Any]:
        d = run_dir(slot, video)
        m = meta(d)
        lines_file = root / "configs/lines.yaml"
        lines = (yaml.safe_load(lines_file.read_text(encoding="utf-8")) or {}).get("lines", []) if lines_file.exists() else []
        rows = list(csv.DictReader(open(d / "manual_counts.csv", encoding="utf-8"))) if (d / "manual_counts.csv").exists() else []
        return {"lines": [{"name": l["name"], "type": l["type"], "approach": l["approach"]} for l in lines],
                "rows": rows, "classes": project_classes(), "video_file": rel(root, inside(root, m["video_file"])),
                "path": rel(root, d / "manual_counts.csv")}

    @r.put("/manual/{slot}/{video}")
    def put_manual(slot: str, video: str, body: dict[str, Any] = Body(...)) -> dict[str, Any]:
        from pattom.validation import MANUAL_FIELDS

        d = run_dir(slot, video)
        buf = io.StringIO()
        w = csv.DictWriter(buf, fieldnames=MANUAL_FIELDS, lineterminator="\n")
        w.writeheader()
        for win in body.get("windows") or []:
            a, b = float(win["window_start_s"]), float(win["window_end_s"])
            if b <= a:
                raise HTTPException(422, f"window {a}-{b} s: the end must be after the start")
            for cls, n in (win.get("counts") or {}).items():
                w.writerow({"slot": slot, "window_start_s": a, "window_end_s": b, "line_name": win["line_name"],
                            "class": cls, "count": int(n)})
        def check(path: Path) -> None:
            list(csv.DictReader(open(path, encoding="utf-8")))
        validated_write(d / "manual_counts.csv", buf.getvalue(), check)
        return manual(slot, video)

    # --- alternatives ----------------------------------------------------------

    @r.get("/alternatives")
    def get_alternatives() -> dict[str, Any]:
        p = root / ALTERNATIVES
        spec = (yaml.safe_load(p.read_text(encoding="utf-8")) or {}) if p.exists() else {}
        problems = set()
        for f in runs.glob("**/problems.csv") if runs.is_dir() else []:
            problems |= {row["problem"] for row in csv.DictReader(open(f, encoding="utf-8"))}
        caps = sorted(rel(root, f) for f in runs.glob("**/capacity_vc.csv")) if runs.is_dir() else []
        return {"alternatives": spec.get("alternatives") or [], "problems": sorted(problems), "capacity_files": caps,
                "path": ALTERNATIVES}

    @r.put("/alternatives")
    def put_alternatives(body: dict[str, Any] = Body(...)) -> dict[str, Any]:
        from pattom.alternatives import load_alternatives

        text = ALT_HEADER + "\n\n" + yaml.safe_dump({"alternatives": body.get("alternatives") or []}, sort_keys=False,
                                                    allow_unicode=True, width=110)
        validated_write(inside(root, ALTERNATIVES), text, load_alternatives)
        return get_alternatives()

    @r.post("/alternatives/sp41")
    def sp41(body: dict[str, Any] = Body(...)) -> dict[str, Any]:
        from pattom.alternatives import sp41_fixed_plan

        try:
            return sp41_fixed_plan(inside(root, body["capacity_file"]), body["approach_groups"], float(body["all_red_s"]))
        except (KeyError, ValueError) as e:
            raise HTTPException(422, str(e)) from None

    # --- settings files (YAML) -------------------------------------------------

    @r.get("/configs")
    def configs() -> list[dict[str, Any]]:
        out = []
        for folder in ("configs", "calibration"):
            for p in sorted((root / folder).glob("*.yaml")) if (root / folder).is_dir() else []:
                example = p.name.endswith(".example.yaml")
                local = p.with_name(p.name.replace(".example.yaml", ".yaml"))
                if example and local.exists():
                    continue
                out.append({"path": rel(root, local if example else p), "exists": not example,
                            "example": rel(root, p) if example else None})
        return out

    @r.get("/configs/file")
    def get_config(path: str) -> dict[str, Any]:
        p = inside(root, path)
        if p.suffix != ".yaml" or p.parent.name not in ("configs", "calibration"):
            raise HTTPException(403, "only YAML files in configs/ or calibration/")
        ex = p.with_name(p.stem + ".example.yaml")
        src = p if p.exists() else ex
        return {"path": rel(root, p), "from_example": not p.exists(),
                "text": src.read_text(encoding="utf-8-sig") if src.exists() else ""}

    @r.put("/configs/file")
    def put_config(body: dict[str, Any] = Body(...)) -> dict[str, Any]:
        p = inside(root, body.get("path", ""))
        if p.suffix != ".yaml" or p.parent.name not in ("configs", "calibration") or p.name.endswith(".example.yaml"):
            raise HTTPException(403, "only local YAML files in configs/ or calibration/ (examples stay as they are)")

        def check(path: Path) -> None:
            data = yaml.safe_load(path.read_text(encoding="utf-8"))
            if data is not None and not isinstance(data, dict):
                raise ValueError("the file must hold a mapping (key: value)")
        validated_write(p, body.get("text", ""), check)
        return get_config(rel(root, p))

    return r
