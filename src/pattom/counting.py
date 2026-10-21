"""Counting lines, crossings, movements and interval counts (FR-09, ARCHITECTURE 4.3-4.4).

- A crossing is recorded when a track's ground-contact point (bottom centre,
  in pixels) passes from one side of a line segment to the other.
- Each line has a type: ``stop_line`` (measures discharge, capped by capacity
  when the junction is oversaturated) or ``arrival`` (upstream of the longest
  queue, for demand).
- A line counts one direction only, given by ``direction``: the side a vehicle
  must come from, "left" or "right" of the line as drawn from its first to its
  second endpoint (in image coordinates, y down), or "both".
- A movement (through, left, right, free_left) is assigned when a track
  crosses its entry line and later its exit line. Otherwise the movement is
  "unknown"; the line count itself still stands.
- Interval counts are measured values, per approach, movement and class. The
  class of a track is its majority class over the whole track.

Config file (configs/lines.yaml):

    lines:
      - {name: N_stop, type: stop_line, approach: north, endpoints_px: [[u,v],[u,v]], direction: left}
      - {name: N_arrival, type: arrival, approach: north, endpoints_px: [...], direction: left}
      - {name: E_exit, type: exit, approach: east, endpoints_px: [...], direction: right}
    movements:
      - {approach: north, movement: through, entry_line: N_stop, exit_line: S_exit}
      - {approach: north, movement: free_left, entry_line: N_freeleft, exit_line: E_exit}
"""

from __future__ import annotations

import csv
import json
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path

import yaml

from pattom.ground import bottom_centre
from pattom.runmeta import RunMetadata, sha256_file

LINE_TYPES = {"stop_line", "arrival", "exit"}
MOVEMENTS = {"through", "left", "right", "free_left"}
CROSSING_FIELDS = ["time_s", "frame", "line_name", "line_type", "approach", "track_id", "class", "direction"]
INTERVAL_FIELDS = ["slot", "interval_start_s", "interval_end_s", "line_name", "line_type", "approach",
                   "movement", "class", "count", "value_type"]


@dataclass(frozen=True)
class Line:
    name: str
    type: str
    approach: str
    a: tuple[float, float]
    b: tuple[float, float]
    direction: str

    def side(self, p: tuple[float, float]) -> float:
        """Positive on the right of a->b, negative on the left (image coords, y down)."""
        (ax, ay), (bx, by) = self.a, self.b
        return (bx - ax) * (p[1] - ay) - (by - ay) * (p[0] - ax)

    def crossed(self, p: tuple[float, float], q: tuple[float, float]) -> str | None:
        """'left->right', 'right->left' or None for the step p -> q."""
        # A point exactly on the line counts as the right side, so a step is never counted twice.
        r1, r2 = self.side(p) >= 0, self.side(q) >= 0
        if r1 == r2:
            return None
        # The step must also cross within the segment, not its extension.
        d1 = (q[0] - p[0]) * (self.a[1] - p[1]) - (q[1] - p[1]) * (self.a[0] - p[0])
        d2 = (q[0] - p[0]) * (self.b[1] - p[1]) - (q[1] - p[1]) * (self.b[0] - p[0])
        if d1 * d2 > 0:
            return None
        return "left->right" if r2 else "right->left"

    def counts(self, crossing: str) -> bool:
        return self.direction == "both" or crossing.startswith(self.direction)


@dataclass(frozen=True)
class Movement:
    approach: str
    movement: str
    entry_line: str
    exit_line: str


def load_lines(path: Path) -> tuple[dict[str, Line], list[Movement]]:
    spec = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    lines: dict[str, Line] = {}
    for d in spec.get("lines") or []:
        if d["type"] not in LINE_TYPES:
            raise ValueError(f"line {d['name']}: type must be one of {sorted(LINE_TYPES)}")
        if d["direction"] not in ("left", "right", "both"):
            raise ValueError(f"line {d['name']}: direction must be left, right or both")
        if d["name"] in lines:
            raise ValueError(f"duplicate line name {d['name']}")
        (a, b) = d["endpoints_px"]
        lines[d["name"]] = Line(d["name"], d["type"], d["approach"], tuple(a), tuple(b), d["direction"])
    moves = []
    for d in spec.get("movements") or []:
        if d["movement"] not in MOVEMENTS:
            raise ValueError(f"movement must be one of {sorted(MOVEMENTS)}: {d}")
        for k in ("entry_line", "exit_line"):
            if d[k] not in lines:
                raise ValueError(f"movement {d}: unknown {k} {d[k]!r}")
        moves.append(Movement(d["approach"], d["movement"], d["entry_line"], d["exit_line"]))
    if not lines:
        raise ValueError(f"{path}: no lines")
    return lines, moves


def _read_tracks(tracks_csv: Path):
    by_track: dict[int, list[tuple[float, int, tuple[float, float]]]] = defaultdict(list)
    with open(tracks_csv, newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            p = bottom_centre(*(float(r[k]) for k in ("x1", "y1", "x2", "y2")))
            by_track[int(r["track_id"])].append((float(r["time_s"]), int(r["frame"]), p))
    for obs in by_track.values():
        obs.sort()
    return by_track


def _majority_classes(summary_csv: Path) -> dict[int, str]:
    with open(summary_csv, newline="", encoding="utf-8") as f:
        return {int(r["track_id"]): r["majority_class"] for r in csv.DictReader(f)}


def find_crossings(by_track, lines: dict[str, Line], classes: dict[int, str]) -> list[dict]:
    out = []
    for tid, obs in by_track.items():
        for (_, _, p), (t, frame, q) in zip(obs, obs[1:]):
            for line in lines.values():
                c = line.crossed(p, q)
                if c and line.counts(c):
                    out.append({"time_s": t, "frame": frame, "line_name": line.name, "line_type": line.type,
                                "approach": line.approach, "track_id": tid, "class": classes[tid],
                                "direction": c})
    out.sort(key=lambda r: (r["time_s"], r["track_id"], r["line_name"]))
    return out


def assign_movements(crossings: list[dict], movements: list[Movement]) -> dict[int, tuple[str, str]]:
    """track_id -> (approach, movement) from entry-then-exit crossings."""
    first_time: dict[tuple[int, str], float] = {}
    for c in crossings:
        first_time.setdefault((c["track_id"], c["line_name"]), c["time_s"])
    result: dict[int, tuple[str, str]] = {}
    tracks = {c["track_id"] for c in crossings}
    for tid in tracks:
        hits = [m for m in movements
                if (tid, m.entry_line) in first_time and (tid, m.exit_line) in first_time
                and first_time[(tid, m.entry_line)] < first_time[(tid, m.exit_line)]]
        if len(hits) == 1:
            result[tid] = (hits[0].approach, hits[0].movement)
        elif len(hits) > 1:
            result[tid] = (hits[0].approach, "ambiguous")
    return result


def interval_counts(crossings: list[dict], track_moves: dict[int, tuple[str, str]], slot: str,
                    interval_s: float, offset_s: float = 0.0, video_end_s: float | None = None) -> list[dict]:
    """Counts per line and interval. offset_s places this file within its slot.
    An interval that runs past the end of the video ends at the video's end, so a
    flow per hour is never computed over time that was not recorded."""
    c = Counter()
    for x in crossings:
        if x["line_type"] == "exit":
            continue
        t = x["time_s"] + offset_s
        start = float(int(t // interval_s) * interval_s)
        move = track_moves.get(x["track_id"], (x["approach"], "unknown"))[1]
        c[(start, x["line_name"], x["line_type"], x["approach"], move, x["class"])] += 1
    return [
        {"slot": slot, "interval_start_s": s,
         "interval_end_s": round(min(s + float(interval_s), offset_s + video_end_s), 3) if video_end_s else s + float(interval_s),
         "line_name": ln,
         "line_type": lt, "approach": ap, "movement": mv, "class": cl, "count": n, "value_type": "measured"}
        for (s, ln, lt, ap, mv, cl), n in sorted(c.items())
    ]


def run_counting(tracks_csv: Path, lines_yaml: Path, interval_s: float, offset_s: float = 0.0) -> Path:
    meta = json.loads(tracks_csv.with_suffix(".run.json").read_text(encoding="utf-8"))
    lines, movements = load_lines(lines_yaml)
    classes = _majority_classes(tracks_csv.parent / "track_summary.csv")
    crossings = find_crossings(_read_tracks(tracks_csv), lines, classes)
    moves = assign_movements(crossings, movements)
    out_dir = tracks_csv.parent
    with open(out_dir / "crossings.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=CROSSING_FIELDS + ["movement"])
        w.writeheader()
        for x in crossings:
            w.writerow({**x, "movement": moves.get(x["track_id"], (None, "unknown"))[1]})
    det_meta = tracks_csv.parent / "detections.run.json"
    video_end_s = None
    if det_meta.is_file():
        dm = json.loads(det_meta.read_text(encoding="utf-8"))
        frames, fps = (dm.get("parameters") or {}).get("frames_read"), dm.get("fps")
        if frames and fps:
            video_end_s = float(frames) / float(fps)
    counts = interval_counts(crossings, moves, meta["slot"], interval_s, offset_s, video_end_s)
    out = out_dir / "interval_counts.csv"
    with open(out, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=INTERVAL_FIELDS)
        w.writeheader()
        w.writerows(counts)
    RunMetadata(
        slot=meta["slot"],
        stage="F.counting",
        video_file=meta["video_file"],
        video_sha256=meta["video_sha256"],
        fps=meta["fps"],
        width=meta["width"],
        height=meta["height"],
        tracker=meta.get("tracker"),
        parameters={"lines_config": str(lines_yaml), "lines_config_sha256": sha256_file(lines_yaml),
                    "interval_s": interval_s, "offset_s": offset_s, "crossings": len(crossings),
                    "tracks_with_movement": sum(m[1] not in ("unknown", "ambiguous") for m in moves.values()),
                    "tracks_sha256": sha256_file(tracks_csv)},
    ).write(out_dir / "counting.run.json")
    return out
