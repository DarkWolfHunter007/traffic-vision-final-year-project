"""Local visual node editor server.

Features:
- Standard library HTTP server bound strictly to 127.0.0.1.
- Path-traversal restricted: file operations and media serving locked inside REPO_ROOT.
- HTTP 206 Partial Content video streaming (range requests for smooth scrub in browser).
- Real-time execution control (Run, Run Selected, Stop) via subprocess isolation.
- Server-Sent Events (SSE) and polling endpoints for live node progress, elapsed times, and logs.
- Dynamic Result Previews: videos, detections/tracks synced by time_s, counting lines, charts.
- Approval Gate status inspections (O3, O4, O6) directly from config files.
- Run History inspector for .run.json files.
"""

from __future__ import annotations

import csv
import json
import mimetypes
import os
import queue
import sys
import threading
import time
import urllib.parse
import urllib.request
import webbrowser
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

import yaml

from pattom.graph.engine import (
    CACHE_DIR,
    GraphError,
    check_cache,
    compute_cache_key,
    load_graph,
    run_graph,
    validate_graph,
)
from pattom.graph import calibration as calib
from pattom.graph.nodes import NODE_TYPES
from pattom.paths import CALIBRATION, REPO_ROOT

EDITOR_HTML = Path(__file__).with_name("editor.html")
CALIBRATE_HTML = Path(__file__).with_name("calibrate.html")


def safe_repo_path(raw_path: str) -> Path | None:
    """Resolve and verify that a path is strictly inside REPO_ROOT to prevent path traversal."""
    try:
        decoded = urllib.parse.unquote(raw_path).strip().replace("\\", "/")
        # Remove leading slashes
        clean = decoded.lstrip("/")
        target = (REPO_ROOT / clean).resolve()
        if target == REPO_ROOT or REPO_ROOT in target.parents:
            return target
        return None
    except Exception:
        return None


def _cfg(name: str) -> str:
    return str(REPO_ROOT / "configs" / name)



class ExecutionManager:
    """Manages active graph runs, cancellation, and live event broadcasting."""

    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.state: str = "idle"  # idle, running, stopped, completed, failed
        self.run_id: str | None = None
        self.active_spec: dict[str, Any] = {}
        self.target_node: str | None = None
        self.order: list[str] = []
        self.node_status: dict[str, str] = {}
        self.node_elapsed: dict[str, float] = {}
        self.node_errors: dict[str, str] = {}
        self.outputs: dict[str, dict[str, str]] = {}
        self.logs: list[dict[str, Any]] = []
        self.stop_event: threading.Event = threading.Event()
        self.subscribers: list[queue.Queue] = []
        self.worker_thread: threading.Thread | None = None

    def subscribe(self) -> queue.Queue:
        q: queue.Queue = queue.Queue(maxsize=500)
        with self.lock:
            self.subscribers.append(q)
        return q

    def unsubscribe(self, q: queue.Queue) -> None:
        with self.lock:
            if q in self.subscribers:
                self.subscribers.remove(q)

    def broadcast(self, event_type: str, data: Any) -> None:
        msg = {"type": event_type, "data": data, "timestamp": time.time()}
        with self.lock:
            dead = []
            for q in self.subscribers:
                try:
                    q.put_nowait(msg)
                except queue.Full:
                    dead.append(q)
            for q in dead:
                if q in self.subscribers:
                    self.subscribers.remove(q)

    def start_run(self, spec: dict[str, Any], target_node_id: str | None = None, force: bool = False) -> str:
        with self.lock:
            if self.state == "running":
                raise RuntimeError("A pipeline execution is already in progress. Stop it first.")
            self.state = "running"
            self.run_id = f"run_{int(time.time())}"
            self.active_spec = spec
            self.target_node = target_node_id
            self.order = validate_graph(spec)
            self.node_status = {n: "queued" for n in self.order}
            self.node_elapsed = {}
            self.node_errors = {}
            self.outputs = {}
            self.logs = []
            self.stop_event.clear()

        def _log_cb(node_id: str, line: str) -> None:
            entry = {"node": node_id, "line": line, "time": time.time()}
            with self.lock:
                self.logs.append(entry)
            self.broadcast("log", entry)

        def _status_cb(node_id: str, st: str, elapsed: float | None = None, err: str | None = None) -> None:
            with self.lock:
                self.node_status[node_id] = st
                if elapsed is not None:
                    self.node_elapsed[node_id] = elapsed
                if err:
                    self.node_errors[node_id] = err
            self.broadcast("status", {"node": node_id, "status": st, "elapsed": elapsed, "error": err})

        def _worker():
            try:
                res = run_graph(
                    spec=spec,
                    target_node_id=target_node_id,
                    force=force,
                    use_subprocess=True,
                    log_callback=_log_cb,
                    status_callback=_status_cb,
                    stop_event=self.stop_event,
                )
                with self.lock:
                    self.outputs = res.outputs
                    if self.stop_event.is_set():
                        self.state = "stopped"
                    elif any(v == "failed" for v in res.status.values()):
                        self.state = "failed"
                    elif any(v == "locked" for v in res.status.values()):
                        self.state = "locked"
                    else:
                        self.state = "completed"
                self.broadcast("done", {"state": self.state, "order": res.order, "status": res.status, "errors": res.errors})
            except Exception as e:
                with self.lock:
                    self.state = "failed"
                self.broadcast("error", {"error": str(e)})

        self.worker_thread = threading.Thread(target=_worker, daemon=True)
        self.worker_thread.start()
        return self.run_id

    def stop_run(self) -> None:
        self.stop_event.set()
        with self.lock:
            if self.state == "running":
                self.state = "stopped"
        self.broadcast("status_change", {"state": "stopped"})

    def get_state(self) -> dict[str, Any]:
        with self.lock:
            return {
                "state": self.state,
                "run_id": self.run_id,
                "target_node": self.target_node,
                "order": self.order,
                "status": dict(self.node_status),
                "elapsed": dict(self.node_elapsed),
                "errors": dict(self.node_errors),
                "outputs": dict(self.outputs),
                "log_count": len(self.logs),
            }


EXEC_MGR = ExecutionManager()


def _get_node_outputs(node_id: str, spec: dict[str, Any] | None = None) -> dict[str, str] | None:
    # 1. From active execution
    with EXEC_MGR.lock:
        if node_id in EXEC_MGR.outputs:
            return EXEC_MGR.outputs[node_id]

    # 2. From disk cache
    cache_file = CACHE_DIR / f"{node_id}.cache.json"
    if cache_file.is_file():
        try:
            data = json.loads(cache_file.read_text(encoding="utf-8"))
            outputs = data.get("outputs", {})
            if outputs and all(Path(p).is_file() for p in outputs.values()):
                return outputs
        except Exception:
            pass

    # 3. Infer from spec and existing files
    if spec and node_id in spec.get("nodes", {}):
        n = spec["nodes"][node_id]
        t = n.get("type")
        p = n.get("params", {})
        if t == "cfr" and p.get("out") and Path(p["out"]).is_file():
            return {"video": str(Path(p["out"]))}
        if t == "undistort" and p.get("out") and Path(p["out"]).is_file():
            return {"video": str(Path(p["out"]))}
        slot = p.get("slot") or "test"
        base_run = REPO_ROOT / "runs" / slot
        if base_run.is_dir():
            # Find subfolder matching video
            for sub in base_run.iterdir():
                if sub.is_dir():
                    if t == "detect" and (sub / "detections.csv").is_file():
                        return {"detections": str(sub / "detections.csv")}
                    if t in ("track", "ground") and (sub / "tracks.csv").is_file():
                        return {"tracks": str(sub / "tracks.csv")}
                    if t == "count" and (sub / "interval_counts.csv").is_file():
                        return {"counts": str(sub / "interval_counts.csv")}
                    if t == "delay_queue" and (sub / "stopped_delay.csv").is_file():
                        return {"delays": str(sub / "stopped_delay.csv")}
                    if t == "indicators" and (sub / "approach_indicators.csv").is_file():
                        return {"indicators": str(sub / "approach_indicators.csv")}
                    if t == "congestion" and (sub / "congestion_index.csv").is_file():
                        return {"index": str(sub / "congestion_index.csv")}
    return None


def generate_node_preview(node_id: str, spec: dict[str, Any] | None = None) -> dict[str, Any]:
    """Generate structured preview payload for a given node."""
    spec = spec or EXEC_MGR.active_spec or {}
    node_conf = spec.get("nodes", {}).get(node_id, {})
    node_type = node_conf.get("type")
    params = node_conf.get("params", {})
    outputs = _get_node_outputs(node_id, spec)

    if not outputs and not (node_type in ("cfr", "undistort") and params.get("video")):
        return {"ready": False, "node_id": node_id, "message": "Node has not produced outputs yet"}

    res: dict[str, Any] = {"ready": True, "node_id": node_id, "type": node_type}

    def _media_rel(p_str: str) -> str:
        p = Path(p_str)
        try:
            rel = p.relative_to(REPO_ROOT) if p.is_relative_to(REPO_ROOT) else p
            return f"/media/{rel.as_posix()}"
        except Exception:
            return f"/media/{p.as_posix()}"

    # Helper to find upstream video
    def _find_upstream_video() -> str | None:
        if "video" in outputs:
            return _media_rel(outputs["video"])
        # Check inputs or trace edges
        if spec:
            for e in spec.get("edges", []):
                if e.get("to", "").startswith(f"{node_id}."):
                    src_node, _ = e["from"].split(".")
                    src_out = _get_node_outputs(src_node, spec)
                    if src_out and "video" in src_out:
                        return _media_rel(src_out["video"])
                    # Check cfr/undistort out params directly
                    src_params = spec.get("nodes", {}).get(src_node, {}).get("params", {})
                    if src_params.get("out") and Path(src_params["out"]).is_file():
                        return _media_rel(src_params["out"])
                    if src_params.get("video") and Path(src_params["video"]).is_file():
                        return _media_rel(src_params["video"])
        # Fallback (e.g. after an editor restart, when no run spec is held):
        # runs/<slot>/<stem>/ pairs with data/cfr/<stem>.mp4
        for out_path in outputs.values():
            cfr_mp4 = REPO_ROOT / "data" / "cfr" / f"{Path(out_path).parent.name}.mp4"
            if cfr_mp4.is_file():
                return _media_rel(str(cfr_mp4))
        return None

    if node_type in ("cfr", "undistort"):
        vid_path = outputs.get("video") or params.get("out") or params.get("video")
        if vid_path and Path(vid_path).is_file():
            p = Path(vid_path)
            res["video_url"] = _media_rel(str(p))
            res["file_name"] = p.name
            res["size_mb"] = round(p.stat().st_size / (1024 * 1024), 2)
        return res

    if node_type == "detect":
        det_path = outputs.get("detections")
        if det_path and Path(det_path).is_file():
            p = Path(det_path)
            res["detections_csv"] = _media_rel(str(p))
            res["video_url"] = _find_upstream_video()
            class_counts: dict[str, int] = {}
            total = 0
            with open(p, newline="", encoding="utf-8") as f:
                r = csv.DictReader(f)
                for row in r:
                    total += 1
                    c = row.get("class", "unknown")
                    class_counts[c] = class_counts.get(c, 0) + 1
            res["total_detections"] = total
            res["class_counts"] = class_counts
        return res

    if node_type in ("track", "ground"):
        trk_path = outputs.get("tracks")
        if trk_path and Path(trk_path).is_file():
            p = Path(trk_path)
            res["tracks_csv"] = _media_rel(str(p))
            res["video_url"] = _find_upstream_video()
            class_counts: dict[str, int] = {}
            track_ids = set()
            points_by_time: list[dict[str, Any]] = []

            # Read tracks
            with open(p, newline="", encoding="utf-8") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    tid = int(row["track_id"])
                    track_ids.add(tid)
                    cls = row.get("class", "unknown")
                    class_counts[cls] = class_counts.get(cls, 0) + 1
                    # Collect box points with time_s for browser overlay
                    points_by_time.append({
                        "t": float(row["time_s"]),
                        "id": tid,
                        "c": cls,
                        "conf": round(float(row.get("confidence", 1.0)), 2),
                        "box": [
                            round(float(row["x1"]), 1),
                            round(float(row["y1"]), 1),
                            round(float(row["x2"]), 1),
                            round(float(row["y2"]), 1),
                        ],
                    })

            res["total_tracks"] = len(track_ids)
            res["class_counts"] = class_counts
            res["points"] = points_by_time  # Streamed for synchronous canvas overlay synced by time_s
        return res

    if node_type == "count":
        cnt_path = outputs.get("counts")
        if cnt_path and Path(cnt_path).is_file():
            p = Path(cnt_path)
            res["video_url"] = _find_upstream_video()
            # Read lines config
            lines_cfg_path = params.get("lines") or _cfg("lines.yaml")
            lines_data = []
            if Path(lines_cfg_path).is_file():
                try:
                    c = yaml.safe_load(Path(lines_cfg_path).read_text(encoding="utf-8")) or {}
                    lines_data = c.get("lines", [])
                except Exception:
                    pass
            res["lines"] = lines_data
            # Boxes under the lines, from the tracks file of the same run
            trk_file = p.parent / "tracks.csv"
            if trk_file.is_file():
                pts = []
                with open(trk_file, newline="", encoding="utf-8") as f:
                    for row in csv.DictReader(f):
                        pts.append({
                            "t": float(row["time_s"]), "id": int(row["track_id"]),
                            "c": row.get("class", "unknown"),
                            "box": [round(float(row[k]), 1) for k in ("x1", "y1", "x2", "y2")],
                        })
                res["points"] = pts

            # Read interval counts table
            table = []
            with open(p, newline="", encoding="utf-8") as f:
                for row in csv.DictReader(f):
                    table.append(row)
            res["interval_counts"] = table

            # Read crossings if exists
            cross_file = p.parent / "crossings.csv"
            by_line: dict[str, int] = {}
            if cross_file.is_file():
                with open(cross_file, newline="", encoding="utf-8") as f:
                    for row in csv.DictReader(f):
                        ln = row.get("line_name", "unknown")
                        by_line[ln] = by_line.get(ln, 0) + 1
            res["line_totals"] = by_line
        return res

    if node_type == "delay_queue":
        delay_path = outputs.get("delays")
        if delay_path and Path(delay_path).is_file():
            p = Path(delay_path)
            stopped_delays = []
            with open(p, newline="", encoding="utf-8") as f:
                for row in csv.DictReader(f):
                    stopped_delays.append(row)
            res["stopped_delays"] = stopped_delays

            # Queue lengths per cycle
            q_file = p.parent / "queue.csv"
            queues = []
            if q_file.is_file():
                with open(q_file, newline="", encoding="utf-8") as f:
                    for row in csv.DictReader(f):
                        queues.append(row)
            res["queues"] = queues
        return res

    if node_type == "indicators":
        ind_path = outputs.get("indicators")
        if ind_path and Path(ind_path).is_file():
            rows = []
            with open(ind_path, newline="", encoding="utf-8") as f:
                for row in csv.DictReader(f):
                    rows.append(row)
            res["indicators"] = rows
        return res

    if node_type == "congestion":
        ci_path = outputs.get("index")
        if ci_path and Path(ci_path).is_file():
            rows = []
            with open(ci_path, newline="", encoding="utf-8") as f:
                for row in csv.DictReader(f):
                    rows.append(row)
            res["congestion"] = rows
            res["notes"] = _run_notes(Path(ci_path).parent / "congestion.run.json")
        return res

    if node_type == "emissions":
        em_path = outputs.get("emissions")
        if em_path and Path(em_path).is_file():
            with open(em_path, newline="", encoding="utf-8") as f:
                res["emissions"] = list(csv.DictReader(f))
            res["notes"] = _run_notes(Path(em_path).parent / "emissions.run.json")
        return res

    table_outputs = {"problems": ("problems", "problems.run.json"), "pre_sumo": ("scores", "pre_sumo_scores.run.json"),
                     "sumo_run": ("results", "sumo_results.run.json"), "comparison": ("comparison", "comparison.run.json")}
    if node_type in table_outputs:
        port, meta = table_outputs[node_type]
        path = outputs.get(port)
        if path and Path(path).is_file():
            with open(path, newline="", encoding="utf-8") as f:
                res["table"] = list(csv.DictReader(f))
            res["notes"] = _run_notes(Path(path).parent / meta)
            if not res["table"]:
                res["notes"].append("No rows.")
        return res

    if node_type in ("alternatives", "mce", "sumo_inputs"):
        port = {"alternatives": "alternatives", "mce": "selected", "sumo_inputs": "sumo_inputs"}[node_type]
        path = outputs.get(port)
        if path and Path(path).is_file():
            res["json"] = json.loads(Path(path).read_text(encoding="utf-8"))
        return res

    return res


def _run_notes(path: Path) -> list[str]:
    """Notes a stage wrote into its .run.json (why a value is missing, and so on)."""
    try:
        meta = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return []
    notes = (meta.get("parameters") or {}).get("notes") or meta.get("notes") or []
    return [notes] if isinstance(notes, str) else [str(n) for n in notes]


def scan_run_history() -> list[dict[str, Any]]:
    """Scan runs/ directory for all run records (.run.json)."""
    runs_dir = REPO_ROOT / "runs"
    if not runs_dir.is_dir():
        return []
    records = []
    for p in runs_dir.rglob("*.run.json"):
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
            data["_file"] = str(p.relative_to(REPO_ROOT).as_posix())
            data["_mtime"] = p.stat().st_mtime
            records.append(data)
        except Exception:
            pass
    records.sort(key=lambda r: r.get("_mtime", 0), reverse=True)
    return records


class Handler(BaseHTTPRequestHandler):
    def _send(self, code: int, body: bytes, ctype: str = "application/json") -> None:
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def _json(self, code: int, payload: Any) -> None:
        self._send(code, json.dumps(payload, indent=2).encode(), "application/json; charset=utf-8")

    def _serve_media(self, path: Path) -> None:
        if not path.is_file():
            self._json(404, {"error": f"File not found: {path.name}"})
            return

        file_size = path.stat().st_size
        mime, _ = mimetypes.guess_type(str(path))
        mime = mime or "application/octet-stream"

        range_hdr = self.headers.get("Range")
        if range_hdr and range_hdr.startswith("bytes="):
            # Parse Range header (e.g. bytes=0-1000 or bytes=1000-)
            try:
                parts = range_hdr[6:].split("-")
                start = int(parts[0]) if parts[0] else 0
                end = int(parts[1]) if parts[1] else file_size - 1
                if start >= file_size:
                    self.send_response(HTTPStatus.REQUESTED_RANGE_NOT_SATISFIABLE)
                    self.send_header("Content-Range", f"bytes */{file_size}")
                    self.end_headers()
                    return
                end = min(end, file_size - 1)
                length = end - start + 1

                self.send_response(HTTPStatus.PARTIAL_CONTENT)
                self.send_header("Content-Type", mime)
                self.send_header("Content-Range", f"bytes {start}-{end}/{file_size}")
                self.send_header("Content-Length", str(length))
                self.send_header("Accept-Ranges", "bytes")
                self.send_header("Access-Control-Allow-Origin", "*")
                self.end_headers()

                with open(path, "rb") as f:
                    f.seek(start)
                    rem = length
                    while rem > 0:
                        chunk_size = min(rem, 64 * 1024)
                        buf = f.read(chunk_size)
                        if not buf:
                            break
                        self.wfile.write(buf)
                        rem -= len(buf)
                return
            except (ConnectionResetError, ConnectionAbortedError, BrokenPipeError):
                return
            except Exception:
                pass

        # Full content response
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", mime)
        self.send_header("Content-Length", str(file_size))
        self.send_header("Accept-Ranges", "bytes")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()

        try:
            with open(path, "rb") as f:
                while True:
                    buf = f.read(64 * 1024)
                    if not buf:
                        break
                    self.wfile.write(buf)
        except (ConnectionResetError, ConnectionAbortedError, BrokenPipeError):
            pass

    def do_HEAD(self) -> None:
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path.startswith("/media/"):
            rel = parsed.path[7:]
            p = safe_repo_path(rel)
            if p and p.is_file():
                mime, _ = mimetypes.guess_type(str(p))
                self.send_response(HTTPStatus.OK)
                self.send_header("Content-Type", mime or "application/octet-stream")
                self.send_header("Content-Length", str(p.stat().st_size))
                self.send_header("Accept-Ranges", "bytes")
                self.end_headers()
                return
        self.send_response(HTTPStatus.NOT_FOUND)
        self.end_headers()

    def do_GET(self) -> None:
        parsed = urllib.parse.urlparse(self.path)
        route = parsed.path
        qs = urllib.parse.parse_qs(parsed.query)

        if route in ("/", "/index.html"):
            if not EDITOR_HTML.is_file():
                self._send(500, b"editor.html missing")
                return
            self._send(200, EDITOR_HTML.read_bytes(), "text/html; charset=utf-8")

        elif route == "/calibrate":
            if not CALIBRATE_HTML.is_file():
                self._send(500, b"calibrate.html missing")
                return
            self._send(200, CALIBRATE_HTML.read_bytes(), "text/html; charset=utf-8")

        elif route == "/calib/state":
            self._json(200, calib.state())

        elif route == "/frame":
            vid = safe_repo_path(qs.get("video", [""])[0])
            try:
                if not vid:
                    raise calib.CalibrationError("Video path is outside the project")
                jpg, w, h = calib.read_frame_jpeg(vid, float(qs.get("t", ["0"])[0]))
            except (calib.CalibrationError, ValueError) as e:
                self._json(404, {"error": str(e)})
                return
            self.send_response(200)
            self.send_header("Content-Type", "image/jpeg")
            self.send_header("Content-Length", str(len(jpg)))
            self.send_header("X-Frame-Width", str(w))
            self.send_header("X-Frame-Height", str(h))
            self.send_header("Access-Control-Expose-Headers", "X-Frame-Width, X-Frame-Height")
            self.end_headers()
            self.wfile.write(jpg)

        elif route == "/live":
            # Newest live_preview.jpg written by a running detection (display only)
            files = sorted((REPO_ROOT / "runs").glob("*/*/live_preview.jpg"), key=lambda p: p.stat().st_mtime)
            if not files:
                self._json(404, {"error": "no live view yet"})
                return
            newest = files[-1]
            self.send_response(200)
            body = newest.read_bytes()
            self.send_header("Content-Type", "image/jpeg")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Age-S", f"{time.time() - newest.stat().st_mtime:.1f}")
            self.send_header("Access-Control-Expose-Headers", "X-Age-S")
            self.end_headers()
            self.wfile.write(body)

        elif route == "/nodes":
            self._json(200, [t.describe() for t in NODE_TYPES.values()])

        elif route == "/status":
            self._json(200, EXEC_MGR.get_state())

        elif route == "/events":
            # Server-Sent Events (SSE)
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Cache-Control", "no-cache")
            self.send_header("Connection", "keep-alive")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()

            q = EXEC_MGR.subscribe()
            # Send initial state
            init_msg = json.dumps({"type": "init", "state": EXEC_MGR.get_state()})
            self.wfile.write(f"data: {init_msg}\n\n".encode("utf-8"))
            self.wfile.flush()

            try:
                while True:
                    try:
                        ev = q.get(timeout=1.0)
                        self.wfile.write(f"data: {json.dumps(ev)}\n\n".encode("utf-8"))
                        self.wfile.flush()
                    except queue.Empty:
                        # Keep-alive heartbeat comment
                        self.wfile.write(b": keepalive\n\n")
                        self.wfile.flush()
            except (ConnectionResetError, ConnectionAbortedError, BrokenPipeError):
                pass
            finally:
                EXEC_MGR.unsubscribe(q)

        elif route.startswith("/preview/"):
            node_id = route[9:]
            self._json(200, generate_node_preview(node_id))

        elif route == "/history":
            self._json(200, scan_run_history())

        elif route == "/files":
            # Safe file browser limited strictly to REPO_ROOT
            sub = qs.get("dir", [""])[0]
            exts = [e.lower() for e in qs.get("ext", [""])[0].split(",") if e]
            target_dir = safe_repo_path(sub) or REPO_ROOT
            if not target_dir.is_dir():
                self._json(404, {"error": "Directory not found"})
                return

            results = []
            for root, _, files in os.walk(target_dir):
                r_path = Path(root)
                # Ignore hidden directories like .venv, .git
                if any(part.startswith(".") and part not in (".cache",) for part in r_path.parts):
                    continue
                for f in files:
                    fp = r_path / f
                    if not exts or fp.suffix.lower() in exts:
                        try:
                            rel = fp.relative_to(REPO_ROOT).as_posix()
                            results.append({
                                "path": rel,
                                "name": fp.name,
                                "size_mb": round(fp.stat().st_size / (1024 * 1024), 2),
                                "ext": fp.suffix.lower(),
                            })
                        except Exception:
                            pass
            results.sort(key=lambda x: x["path"])
            self._json(200, results)

        elif route == "/config":
            req_path = qs.get("path", [""])[0]
            p = safe_repo_path(req_path)
            if not p or not p.is_file():
                self._json(404, {"error": f"Config not found: {req_path}"})
                return
            try:
                content = p.read_text(encoding="utf-8")
                parsed_yaml = yaml.safe_load(content)
                self._json(200, {
                    "path": req_path,
                    "content": content,
                    "parsed": parsed_yaml,
                })
            except Exception as e:
                self._json(500, {"error": f"Read error: {e}"})

        elif route.startswith("/media/"):
            rel_path = route[7:]
            p = safe_repo_path(rel_path)
            if not p:
                self._json(403, {"error": "Access forbidden: path outside repository"})
                return
            self._serve_media(p)

        else:
            self._json(404, {"error": f"Not found: {route}"})

    def do_POST(self) -> None:
        route = self.path
        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length) if length > 0 else b"{}"

        try:
            payload = json.loads(body) if body else {}
        except Exception as e:
            self._json(400, {"error": f"Invalid JSON payload: {e}"})
            return

        try:
            if route == "/validate":
                order = validate_graph(payload)
                self._json(200, {"valid": True, "order": order})

            elif route == "/run":
                spec = payload.get("graph", payload)
                target = payload.get("target_node_id")
                force = bool(payload.get("force", False))
                run_id = EXEC_MGR.start_run(spec, target_node_id=target, force=force)
                self._json(200, {"started": True, "run_id": run_id, "state": "running"})

            elif route == "/preview":
                # The editor sends its current graph so previews work after a restart.
                self._json(200, generate_node_preview(str(payload.get("node_id", "")), payload.get("graph")))

            elif route == "/calib/ground_check":
                self._json(200, calib.check_ground(payload.get("mapping") or {}))

            elif route == "/calib/measure":
                self._json(200, calib.measure(payload.get("a_px"), payload.get("b_px")))

            elif route == "/calib/ground_save":
                self._json(200, calib.save_ground(payload))

            elif route == "/calib/lines_save":
                self._json(200, calib.save_lines(payload))

            elif route == "/calib/zones_save":
                self._json(200, calib.save_zones(payload))

            elif route == "/calib/width":
                if payload.get("remove"):
                    self._json(200, calib.remove_width(str(payload.get("approach", ""))))
                elif payload.get("toggle"):
                    self._json(200, calib.toggle_width(str(payload.get("approach", ""))))
                else:
                    self._json(200, calib.save_width(str(payload.get("approach", "")), float(payload.get("width_m")), str(payload.get("value_type", "")), payload.get("check_error_m"), payload.get("signal_head"), payload.get("enabled", True)))

            elif route == "/stop":
                EXEC_MGR.stop_run()
                self._json(200, {"stopped": True, "state": "stopped"})

            elif route == "/config":
                req_path = payload.get("path")
                content = payload.get("content")
                if not req_path or content is None:
                    self._json(400, {"error": "path and content are required"})
                    return
                p = safe_repo_path(req_path)
                if not p:
                    self._json(403, {"error": "Path traversal prohibited"})
                    return
                try:
                    # Validate YAML syntax
                    yaml.safe_load(content)
                    p.parent.mkdir(parents=True, exist_ok=True)
                    p.write_text(content, encoding="utf-8")
                    self._json(200, {"saved": True, "path": req_path})
                except Exception as e:
                    self._json(422, {"error": f"Invalid YAML: {e}"})

            elif route == "/gate_check":
                node_type_name = payload.get("type")
                params = payload.get("params", {})
                if not node_type_name or node_type_name not in NODE_TYPES:
                    self._json(404, {"error": f"Unknown node type: {node_type_name}"})
                    return
                node_type = NODE_TYPES[node_type_name]
                gate_info = node_type.gate_checker(params) if node_type.gate_checker else None
                self._json(200, {"gate": gate_info})

            else:
                self._json(404, {"error": "Not found"})
        except calib.CalibrationError as error:
            self._json(422, {"error": str(error)})
        except GraphError as error:
            self._json(422, {"valid": False, "error": str(error)})
        except Exception as error:
            self._json(500, {"error": str(error)})

    def log_message(self, *args) -> None:
        pass


class QuietServer(ThreadingHTTPServer):
    """Browsers drop connections on refresh or tab close; that is not an error."""

    def handle_error(self, request, client_address) -> None:
        if isinstance(sys.exc_info()[1], (ConnectionError, BrokenPipeError)):
            return
        super().handle_error(request, client_address)


def serve(port: int = 8765, open_browser: bool = True) -> None:
    QuietServer.allow_reuse_address = False

    selected_port = port
    url = f"http://127.0.0.1:{selected_port}/"
    try:
        server = QuietServer(("127.0.0.1", selected_port), Handler)
    except OSError:
        # Single instance: if our editor already serves this port, reuse it.
        try:
            with urllib.request.urlopen(f"{url}nodes", timeout=2) as r:
                running = r.status == 200
        except Exception:
            running = False
        if not running:
            raise OSError(f"Port {selected_port} is in use by another program; use --port.")
        print(f"The editor is already running at {url}; opening it instead of starting another.")
        if open_browser:
            webbrowser.open(url)
        return

    print(f"\n==================================================================")
    print(f" Traffic Vision Visual Editor started at {url}")
    print(f" Bound strictly to 127.0.0.1 (Windows/Local PC). Press Ctrl+C to stop.")
    print(f"==================================================================\n")
    if open_browser:
        threading.Timer(0.6, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down server...")
        server.shutdown()

