"""Speed, stopped delay (FR-12) and queue length (FR-11) from ground-mapped tracks.

The definitions are the user's (open decision O6) and are passed in; nothing
here has a default:

- ``stopped_speed_kmh``: a vehicle slower than this is stopped.
- ``speed_window_s``: speed at a point is the ground distance travelled over a
  window of this length centred on it, divided by the time (smooths box jitter).
- ``definition_version``: the name of the approved written definition, stored
  in every row (ARCHITECTURE 4.6).

Stopped delay of a vehicle = the time it spends stopped before it crosses its
approach's stop line. Vehicles without ground positions (outside the
calibrated zone) are counted and reported, never filled in.

Queue length at a moment = ground distance from the approach's stop line to the
farthest stopped vehicle that has not yet crossed it; measured at the start of
green or as the largest value during red (``measure_at``). Ground positions are
the bottom centre of each box (ARCHITECTURE section 6); vehicle length is not
added.
"""

from __future__ import annotations

from collections import defaultdict
from pathlib import Path
from statistics import mean
from typing import Any

import numpy as np

from pattom.tables import num, read_csv, require, write_csv, write_meta
from pattom.values import ValueType

DELAY_FIELDS = ["slot", "approach", "interval_start_s", "interval_end_s", "mean_stopped_delay_s", "n_vehicles",
                "n_without_speed", "stopped_speed_kmh", "definition_version", "value_type"]
VEHICLE_FIELDS = ["track_id", "class", "approach", "stop_line", "cross_time_s", "stopped_s", "speed_samples",
                  "value_type"]
QUEUE_FIELDS = ["slot", "approach", "signal_head", "cycle_start", "measured_at_s", "queue_length_m", "n_queued",
                "measure_at", "definition_version", "value_type"]


def ground_tracks(tracks_csv: Path) -> tuple[dict[int, dict[str, Any]], set[int]]:
    """track_id -> {t, xy, class} for rows with ground positions; and the ids with none."""
    rows = defaultdict(list)
    classes: dict[int, str] = {}
    seen: set[int] = set()
    for r in read_csv(tracks_csv):
        tid = int(r["track_id"])
        seen.add(tid)
        classes.setdefault(tid, r["class"])
        x, y = num(r.get("ground_x_m")), num(r.get("ground_y_m"))
        if x is not None and y is not None:
            rows[tid].append((float(r["time_s"]), x, y))
    out = {}
    for tid, obs in rows.items():
        obs.sort()
        a = np.array(obs, float)
        out[tid] = {"t": a[:, 0], "xy": a[:, 1:3], "class": classes[tid]}
    return out, seen - set(out)


def speeds(t: np.ndarray, xy: np.ndarray, window_s: float) -> np.ndarray:
    """Speed in m/s at each sample (NaN where the window holds a single sample)."""
    half = window_s / 2.0
    lo = np.searchsorted(t, t - half, side="left")
    hi = np.searchsorted(t, t + half, side="right") - 1
    v = np.full(len(t), np.nan)
    ok = hi > lo
    dt = t[hi[ok]] - t[lo[ok]]
    v[ok] = np.linalg.norm(xy[hi[ok]] - xy[lo[ok]], axis=1) / dt
    return v


def first_stop_crossings(crossings_csv: Path) -> dict[int, tuple[float, str, str]]:
    """track_id -> (time_s, stop line, approach) of its first stop-line crossing."""
    out: dict[int, tuple[float, str, str]] = {}
    for c in read_csv(crossings_csv):
        if c["line_type"] != "stop_line":
            continue
        tid, t = int(c["track_id"]), float(c["time_s"])
        if tid not in out or t < out[tid][0]:
            out[tid] = (t, c["line_name"], c["approach"])
    return out


def stopped_delay(tracks_csv: Path, crossings_csv: Path, slot: str, params: dict[str, Any], out_dir: Path) -> Path:
    require(params, "stopped_speed_kmh", "speed_window_s", "definition_version",
            why="the stopped-speed threshold and speed window are part of the queue/delay definition (O6)")
    thr = float(params["stopped_speed_kmh"]) / 3.6
    window = float(params["speed_window_s"])
    interval = float(params.get("interval_s", 900.0))
    offset = float(params.get("offset_s", 0.0))
    tracks, no_ground = ground_tracks(tracks_csv)
    crossing = first_stop_crossings(crossings_csv)
    vehicles = []
    for tid, (tc, line, approach) in sorted(crossing.items()):
        tr = tracks.get(tid)
        if tr is None:
            vehicles.append({"track_id": tid, "class": "", "approach": approach, "stop_line": line,
                             "cross_time_s": tc, "stopped_s": "", "speed_samples": 0, "value_type": ""})
            continue
        t, v = tr["t"], speeds(tr["t"], tr["xy"], window)
        before = t < tc
        stopped = 0.0
        for i in np.nonzero(before[:-1])[0]:
            if not np.isnan(v[i]) and v[i] < thr:
                stopped += min(t[i + 1], tc) - t[i]
        vehicles.append({"track_id": tid, "class": tr["class"], "approach": approach, "stop_line": line,
                         "cross_time_s": tc, "stopped_s": round(stopped, 2),
                         "speed_samples": int(np.count_nonzero(~np.isnan(v[before]))),
                         "value_type": ValueType.DERIVED.value})
    groups: dict[tuple[str, float], list[dict]] = defaultdict(list)
    for veh in vehicles:
        start = float(int((veh["cross_time_s"] + offset) // interval) * interval)
        groups[(veh["approach"], start)].append(veh)
    rows = []
    for (approach, start), vs in sorted(groups.items()):
        known = [v["stopped_s"] for v in vs if v["stopped_s"] != ""]
        rows.append({"slot": slot, "approach": approach, "interval_start_s": start, "interval_end_s": start + interval,
                     "mean_stopped_delay_s": round(mean(known), 2) if known else "", "n_vehicles": len(known),
                     "n_without_speed": len(vs) - len(known), "stopped_speed_kmh": params["stopped_speed_kmh"],
                     "definition_version": params["definition_version"], "value_type": ValueType.DERIVED.value})
    write_csv(out_dir / "stopped_delay_vehicles.csv", VEHICLE_FIELDS, vehicles)
    out = write_csv(out_dir / "stopped_delay.csv", DELAY_FIELDS, rows)
    write_meta(out_dir / "stopped_delay.run.json", "F.stopped_delay", slot,
               {"tracks": tracks_csv, "crossings": crossings_csv},
               {**params, "vehicles": len(vehicles), "tracks_without_ground": len(no_ground)})
    return out


def _segment_distance(p: np.ndarray, a: np.ndarray, b: np.ndarray) -> float:
    d = b - a
    s = np.clip(np.dot(p - a, d) / max(np.dot(d, d), 1e-12), 0.0, 1.0)
    return float(np.linalg.norm(p - (a + s * d)))


def stop_lines_on_ground(lines_yaml: Path, ground_yaml: Path) -> dict[str, tuple[str, np.ndarray, np.ndarray]]:
    """Stop line name -> (approach, a_m, b_m), mapped through the ground calibration."""
    from pattom.counting import load_lines
    from pattom.ground import GroundCalibration

    cal = GroundCalibration.from_config(ground_yaml)
    lines, _ = load_lines(lines_yaml)
    out = {}
    for line in lines.values():
        if line.type != "stop_line":
            continue
        a, b = cal.locate(*line.a), cal.locate(*line.b)
        if a is None or b is None:
            raise ValueError(f"stop line {line.name} is outside the calibrated ground zone; queue length needs it inside")
        out[line.name] = (line.approach, np.array(a), np.array(b))
    return out


def queue_lengths(tracks_csv: Path, crossings_csv: Path, cycles_csv: Path, lines_yaml: Path, ground_yaml: Path,
                  slot: str, params: dict[str, Any], out_dir: Path) -> Path:
    require(params, "stopped_speed_kmh", "speed_window_s", "definition_version", "measure_at", "approach_heads",
            why="the queue definition (O6) and which signal head controls each approach")
    if params["measure_at"] not in ("green_start", "max_during_red"):
        raise ValueError("measure_at must be green_start or max_during_red")
    thr, window = float(params["stopped_speed_kmh"]) / 3.6, float(params["speed_window_s"])
    heads: dict[str, str] = params["approach_heads"]
    tracks, _ = ground_tracks(tracks_csv)
    speed = {tid: speeds(tr["t"], tr["xy"], window) for tid, tr in tracks.items()}
    crossing = first_stop_crossings(crossings_csv)
    stop = stop_lines_on_ground(lines_yaml, ground_yaml)
    by_approach = {ap: (name, a, b) for name, (ap, a, b) in stop.items()}
    cycles = read_csv(cycles_csv)

    def queue_at(approach: str, t0: float) -> tuple[float, int]:
        _, a, b = by_approach[approach]
        far, n = 0.0, 0
        for tid, (tc, _, ap) in crossing.items():
            tr = tracks.get(tid)
            if ap != approach or tc <= t0 or tr is None:
                continue
            i = int(np.argmin(np.abs(tr["t"] - t0)))
            if abs(tr["t"][i] - t0) > window / 2 or np.isnan(speed[tid][i]) or speed[tid][i] >= thr:
                continue
            n += 1
            far = max(far, _segment_distance(tr["xy"][i], a, b))
        return far, n

    sample_times = np.unique(np.concatenate([tr["t"] for tr in tracks.values()])) if tracks else np.array([])
    rows = []
    for approach, head in sorted(heads.items()):
        if approach not in by_approach:
            raise ValueError(f"no stop line for approach {approach!r} in {lines_yaml}")
        for c in (c for c in cycles if c["signal_head"] == head):
            start, green, amber = float(c["cycle_start_s"]), float(c["green_s"]), float(c["amber_s"])
            green_onset = float(c["cycle_end_s"])  # red ends at the next green
            if params["measure_at"] == "green_start":
                t_best, (length, n) = green_onset, queue_at(approach, green_onset)
            else:
                red = sample_times[(sample_times >= start + green + amber) & (sample_times <= green_onset)]
                best = max(((queue_at(approach, t), t) for t in red), default=((0.0, 0), green_onset))
                (length, n), t_best = best
            rows.append({"slot": slot, "approach": approach, "signal_head": head, "cycle_start": green_onset,
                         "measured_at_s": round(float(t_best), 3), "queue_length_m": round(length, 2), "n_queued": n,
                         "measure_at": params["measure_at"], "definition_version": params["definition_version"],
                         "value_type": ValueType.DERIVED.value})
    out = write_csv(out_dir / "queue.csv", QUEUE_FIELDS, rows)
    write_meta(out_dir / "queue.run.json", "F.queue", slot,
               {"tracks": tracks_csv, "crossings": crossings_csv, "signal_cycles": cycles_csv,
                "lines": lines_yaml, "ground": ground_yaml}, params)
    return out
