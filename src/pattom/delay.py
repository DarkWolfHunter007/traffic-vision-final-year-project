"""Speed, stopped delay and queue length (FR-11, FR-12, ARCHITECTURE 4.6).

Every number here depends on operational definitions that are still open
(O6, task T46): the stopped-speed threshold, the speed smoothing window, the
approach zones and the queue reference point. They come from a definitions
file with a version. AI_RULES section 5 says not to compute queue or delay
until the definitions are approved, so an unapproved file is refused unless
the caller asks for a draft run, and draft outputs say so in every row.

Definitions file (configs/definitions.yaml):

    definition_version: draft-1
    approved: false              # set true only after the user/guide approve
    stopped_speed_kmh: ...       # O6
    speed_window_s: ...          # centred window for speed from ground positions
    max_gap_s: ...               # longest gap between track points still counted as stopped
    approaches:
      north:
        zone_px: [[u, v], ...]   # where delay and queue are counted
        stop_point_m: [x, y]     # stop-line reference on the ground (metres)
        signal_head: N           # head in the signal log for this approach

Speeds use ground positions only (never raw pixels); track points outside the
calibrated zone have no ground position and are skipped.
"""

from __future__ import annotations

import csv
import json
import math
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np
import yaml

from pattom.ground import bottom_centre
from pattom.runmeta import RunMetadata, sha256_file
from pattom.signals import load_log

VEHICLE_FIELDS = ["track_id", "class", "approach", "zone_entry_s", "zone_exit_s", "stopped_delay_s",
                  "definition_version", "definition_status"]
DELAY_FIELDS = ["slot", "approach", "interval_start_s", "interval_end_s", "mean_stopped_delay_s",
                "n_vehicles", "n_stopped", "definition_version", "definition_status", "value_type"]
QUEUE_FIELDS = ["slot", "approach", "cycle_start_s", "queue_length_m", "queued_vehicles",
                "definition_version", "definition_status", "value_type"]


@dataclass
class Approach:
    name: str
    zone_px: list[list[float]]
    stop_point_m: tuple[float, float]
    signal_head: str | None

    def contains(self, u: float, v: float) -> bool:
        return cv2.pointPolygonTest(np.array(self.zone_px, np.float32), (float(u), float(v)), False) >= 0


@dataclass
class Definitions:
    version: str
    approved: bool
    stopped_speed_kmh: float
    speed_window_s: float
    max_gap_s: float
    approaches: dict[str, Approach]
    source_sha256: str

    @classmethod
    def load(cls, path: Path) -> "Definitions":
        d = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
        required = {"definition_version", "approved", "stopped_speed_kmh", "speed_window_s", "max_gap_s",
                    "approaches"}
        missing = required - d.keys()
        if missing:
            raise ValueError(f"{path}: missing {sorted(missing)} (these are the T46 definitions; none has a default)")
        empty = sorted(k for k in required if d[k] is None)
        if empty:
            raise ValueError(f"{path}: {empty} not filled in (T46/O6)")
        apps = {
            name: Approach(name, a["zone_px"], tuple(a["stop_point_m"]), a.get("signal_head"))
            for name, a in d["approaches"].items()
        }
        return cls(str(d["definition_version"]), bool(d["approved"]), float(d["stopped_speed_kmh"]),
                   float(d["speed_window_s"]), float(d["max_gap_s"]), apps, sha256_file(Path(path)))

    @property
    def status(self) -> str:
        return "approved" if self.approved else "draft, not approved"

    def require(self, allow_draft: bool) -> None:
        if not self.approved and not allow_draft:
            raise PermissionError(
                f"definitions {self.version} are not approved (O6). Approve them first, or run as a draft."
            )


@dataclass
class Point:
    t: float
    u: float
    v: float
    xy: tuple[float, float] | None
    speed_kmh: float | None = None


def read_track_points(tracks_csv: Path) -> dict[int, list[Point]]:
    by_track: dict[int, list[Point]] = defaultdict(list)
    with open(tracks_csv, newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            u, v = bottom_centre(*(float(r[k]) for k in ("x1", "y1", "x2", "y2")))
            xy = (float(r["ground_x_m"]), float(r["ground_y_m"])) if r["ground_x_m"] not in ("", None) else None
            by_track[int(r["track_id"])].append(Point(float(r["time_s"]), u, v, xy))
    for pts in by_track.values():
        pts.sort(key=lambda p: p.t)
    return by_track


def add_speeds(points: list[Point], window_s: float) -> None:
    """Centred-window speed (km/h) from ground positions."""
    ground = [p for p in points if p.xy is not None]
    times = [p.t for p in ground]
    for i, p in enumerate(ground):
        lo = np.searchsorted(times, p.t - window_s / 2, side="left")
        hi = np.searchsorted(times, p.t + window_s / 2, side="right") - 1
        if hi > lo and times[hi] > times[lo]:
            a, b = ground[lo].xy, ground[hi].xy
            p.speed_kmh = math.dist(a, b) / (times[hi] - times[lo]) * 3.6


def vehicle_delays(by_track: dict[int, list[Point]], classes: dict[int, str], defs: Definitions) -> list[dict]:
    """Stopped delay per vehicle and approach zone."""
    out = []
    for tid, pts in by_track.items():
        add_speeds(pts, defs.speed_window_s)
        for app in defs.approaches.values():
            inside = [i for i, p in enumerate(pts) if app.contains(p.u, p.v)]
            if not inside:
                continue
            delay = 0.0
            for i in inside:
                if i + 1 >= len(pts):
                    break
                p, q = pts[i], pts[i + 1]
                if p.speed_kmh is not None and p.speed_kmh <= defs.stopped_speed_kmh and q.t - p.t <= defs.max_gap_s:
                    delay += q.t - p.t
            out.append({"track_id": tid, "class": classes.get(tid, ""), "approach": app.name,
                        "zone_entry_s": pts[inside[0]].t, "zone_exit_s": pts[inside[-1]].t,
                        "stopped_delay_s": round(delay, 3), "definition_version": defs.version,
                        "definition_status": defs.status})
    out.sort(key=lambda r: (r["approach"], r["zone_entry_s"]))
    return out


def interval_delays(vehicles: list[dict], slot: str, interval_s: float, offset_s: float,
                    defs: Definitions) -> list[dict]:
    groups: dict[tuple[str, float], list[float]] = defaultdict(list)
    for r in vehicles:
        start = float(int((r["zone_entry_s"] + offset_s) // interval_s) * interval_s)
        groups[(r["approach"], start)].append(r["stopped_delay_s"])
    return [
        {"slot": slot, "approach": a, "interval_start_s": s, "interval_end_s": s + float(interval_s),
         "mean_stopped_delay_s": round(sum(d) / len(d), 3), "n_vehicles": len(d),
         "n_stopped": sum(x > 0 for x in d), "definition_version": defs.version,
         "definition_status": defs.status, "value_type": "derived"}
        for (a, s), d in sorted(groups.items())
    ]


def queues_at_green(by_track: dict[int, list[Point]], defs: Definitions, signal_log: Path, slot: str,
                    tolerance_s: float) -> list[dict]:
    """Queue length at each start of green: distance from the stop point to the
    farthest stopped vehicle in the approach zone (ground metres)."""
    log = load_log(signal_log)
    out = []
    for app in defs.approaches.values():
        if not app.signal_head:
            continue
        if app.signal_head not in log:
            raise ValueError(f"approach {app.name}: signal head {app.signal_head!r} is not in the signal log")
        for t0, state in log[app.signal_head]:
            if state != "green":
                continue
            dists = []
            for pts in by_track.values():
                near = min(pts, key=lambda p: abs(p.t - t0))
                if (abs(near.t - t0) <= tolerance_s and near.xy is not None and near.speed_kmh is not None
                        and near.speed_kmh <= defs.stopped_speed_kmh and app.contains(near.u, near.v)):
                    dists.append(math.dist(near.xy, app.stop_point_m))
            out.append({"slot": slot, "approach": app.name, "cycle_start_s": t0,
                        "queue_length_m": round(max(dists), 2) if dists else 0.0,
                        "queued_vehicles": len(dists), "definition_version": defs.version,
                        "definition_status": defs.status, "value_type": "derived"})
    return out


def _write(path: Path, fields: list[str], rows: list[dict]) -> None:
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)


def run_delay_queue(tracks_csv: Path, definitions: Path, interval_s: float, signal_log: Path | None = None,
                    offset_s: float = 0.0, allow_draft: bool = False) -> Path:
    defs = Definitions.load(definitions)
    defs.require(allow_draft)
    meta = json.loads(tracks_csv.with_suffix(".run.json").read_text(encoding="utf-8"))
    with open(tracks_csv.parent / "track_summary.csv", newline="", encoding="utf-8") as f:
        classes = {int(r["track_id"]): r["majority_class"] for r in csv.DictReader(f)}
    by_track = read_track_points(tracks_csv)
    if not any(p.xy for pts in by_track.values() for p in pts):
        raise ValueError("tracks.csv has no ground positions; run the ground mapping first (pattom ground)")
    out_dir = tracks_csv.parent
    vehicles = vehicle_delays(by_track, classes, defs)
    _write(out_dir / "vehicle_delay.csv", VEHICLE_FIELDS, vehicles)
    _write(out_dir / "stopped_delay.csv", DELAY_FIELDS,
           interval_delays(vehicles, meta["slot"], interval_s, offset_s, defs))
    n_queue = None
    if signal_log is not None:
        queues = queues_at_green(by_track, defs, signal_log, meta["slot"], tolerance_s=defs.speed_window_s / 2)
        _write(out_dir / "queue.csv", QUEUE_FIELDS, queues)
        n_queue = len(queues)
    RunMetadata(
        slot=meta["slot"], stage="F.delay_queue", video_file=meta["video_file"],
        video_sha256=meta["video_sha256"], fps=meta["fps"], width=meta["width"], height=meta["height"],
        tracker=meta.get("tracker"),
        parameters={"definitions": str(definitions), "definitions_sha256": defs.source_sha256,
                    "definition_version": defs.version, "definition_status": defs.status,
                    "signal_log": str(signal_log) if signal_log else None,
                    "signal_log_sha256": sha256_file(signal_log) if signal_log else None,
                    "interval_s": interval_s, "offset_s": offset_s, "vehicles": len(vehicles),
                    "queue_rows": n_queue, "tracks_sha256": sha256_file(tracks_csv)},
    ).write(out_dir / "delay_queue.run.json")
    return out_dir / "stopped_delay.csv"
