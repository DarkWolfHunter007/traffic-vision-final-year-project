"""Phase 09 stopped vehicle and calibrated queue detection pure logic.

Provides pure mathematical primitives and trajectory evaluations for:
- Detecting stopped/slow states and continuous stop episodes for vehicle tracks.
- Ray-casting polygon containment (point_in_polygon) using bottom-centre ground points.
- Queue formation decisions and calibrated physical queue length calculations in metres.
- Association of queue zones with approach stop lines.
- Complete independence from signal phase timing.
- Explicit avoidance of final congestion index computation.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
import json
import math
from typing import Any
from uuid import uuid4

import numpy as np

from backend.calibration import project_image_to_world

STATUS_VALID = "valid"
STATUS_INVALID = "invalid"
STATUS_UNAVAILABLE = "unavailable"

VALID_STATUSES: frozenset[str] = frozenset(
    {STATUS_VALID, STATUS_INVALID, STATUS_UNAVAILABLE}
)


@dataclass(frozen=True)
class StopEvent:
    """One immutable stop event matching the canonical stop_events table."""

    stop_event_id: str
    run_id: str
    video_id: str
    track_id: int
    start_timestamp_s: float
    end_timestamp_s: float | None
    duration_s: float | None
    threshold_kmh: float
    status: str

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary matching database stop_events columns."""
        return {
            "stop_event_id": self.stop_event_id,
            "run_id": self.run_id,
            "video_id": self.video_id,
            "track_id": int(self.track_id),
            "start_timestamp_s": float(self.start_timestamp_s),
            "end_timestamp_s": float(self.end_timestamp_s) if self.end_timestamp_s is not None else None,
            "duration_s": float(self.duration_s) if self.duration_s is not None else None,
            "threshold_kmh": float(self.threshold_kmh),
            "status": self.status,
        }


@dataclass(frozen=True)
class QueueEvent:
    """One immutable queue event matching the canonical queue_events table."""

    queue_event_id: str
    run_id: str
    video_id: str
    zone_id: str | None
    approach: str | None
    timestamp_s: float
    queue_length_m: float | None
    queued_vehicle_count: int | None
    status: str

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary matching database queue_events columns."""
        return {
            "queue_event_id": self.queue_event_id,
            "run_id": self.run_id,
            "video_id": self.video_id,
            "zone_id": self.zone_id,
            "approach": self.approach,
            "timestamp_s": float(self.timestamp_s),
            "queue_length_m": float(self.queue_length_m) if self.queue_length_m is not None else None,
            "queued_vehicle_count": int(self.queued_vehicle_count) if self.queued_vehicle_count is not None else None,
            "status": self.status,
        }


def _get_val(obj: Any, key: str, default: Any = None) -> Any:
    """Extract a key from either a dict/mapping, sqlite3.Row, or object attributes."""
    if isinstance(obj, Mapping):
        return obj.get(key, default)
    if hasattr(obj, "keys") and callable(getattr(obj, "keys")):
        try:
            return obj[key]
        except (KeyError, IndexError):
            return default
    return getattr(obj, key, default)


def point_in_polygon(x: float, y: float, polygon: Sequence[Sequence[float]]) -> bool:
    """Ray-casting point-in-polygon containment test.

    Tests whether 2D point (x, y) lies inside the given polygon vertices.
    Strictly checks the vehicle road contact point against the polygonal boundary.
    """
    n = len(polygon)
    if n < 3:
        return False
    inside = False
    p1x, p1y = float(polygon[0][0]), float(polygon[0][1])
    for i in range(1, n + 1):
        p2x, p2y = float(polygon[i % n][0]), float(polygon[i % n][1])
        if min(p1y, p2y) < y <= max(p1y, p2y):
            if x <= max(p1x, p2x):
                if p1y != p2y:
                    xinters = (y - p1y) * (p2x - p1x) / (p2y - p1y) + p1x
                if p1x == p2x or x <= xinters:
                    inside = not inside
        p1x, p1y = p2x, p2y
    return inside


def _point_to_segment_distance(
    px: float, py: float, s1: Sequence[float], s2: Sequence[float]
) -> float:
    """Calculate Euclidean distance from 2D point (px, py) to line segment [s1, s2]."""
    x1, y1 = float(s1[0]), float(s1[1])
    x2, y2 = float(s2[0]), float(s2[1])
    dx = x2 - x1
    dy = y2 - y1
    l2 = dx * dx + dy * dy
    if l2 <= 1e-12:
        return math.hypot(px - x1, py - y1)
    t = max(0.0, min(1.0, ((px - x1) * dx + (py - y1) * dy) / l2))
    proj_x = x1 + t * dx
    proj_y = y1 + t * dy
    return math.hypot(px - proj_x, py - proj_y)


def detect_stop_events_for_track(
    track_id: int,
    observations: Sequence[Any],
    stop_speed_threshold_kmh: float = 5.0,
    min_stop_duration_s: float = 3.0,
    max_gap_s: float = 1.0,
    run_id: str = "",
    video_id: str = "",
) -> list[StopEvent]:
    """Detect confirmed stopped vehicle episodes for an individual vehicle track.

    Rules:
    - Speed <= stop_speed_threshold_kmh constitutes a stopped state.
    - Continuous stopped duration >= min_stop_duration_s confirms a StopEvent.
    - Gaps > max_gap_s break continuity and split or terminate episodes.
    - Non-monotonic timestamps (dt <= 0) or invalid status are flagged with status='invalid'.
    """
    events: list[StopEvent] = []
    active_stop: dict[str, float] | None = None
    prev_t: float | None = None

    for obs in observations:
        t_curr = float(_get_val(obs, "timestamp_s", 0.0))
        speed_kmh = _get_val(obs, "speed_kmh")
        status = str(_get_val(obs, "status", STATUS_VALID))

        # Check for invalid observation status
        if status == STATUS_INVALID:
            if active_stop is not None:
                dur = active_stop["end_t"] - active_stop["start_t"]
                if dur >= min_stop_duration_s:
                    events.append(
                        StopEvent(
                            stop_event_id=str(uuid4()),
                            run_id=run_id,
                            video_id=video_id,
                            track_id=track_id,
                            start_timestamp_s=active_stop["start_t"],
                            end_timestamp_s=active_stop["end_t"],
                            duration_s=round(dur, 4),
                            threshold_kmh=float(stop_speed_threshold_kmh),
                            status=STATUS_VALID,
                        )
                    )
                active_stop = None
            events.append(
                StopEvent(
                    stop_event_id=str(uuid4()),
                    run_id=run_id,
                    video_id=video_id,
                    track_id=track_id,
                    start_timestamp_s=t_curr,
                    end_timestamp_s=t_curr,
                    duration_s=0.0,
                    threshold_kmh=float(stop_speed_threshold_kmh),
                    status=STATUS_INVALID,
                )
            )
            prev_t = t_curr
            continue

        # Check non-monotonic or negative intervals
        if prev_t is not None:
            dt = t_curr - prev_t
            if dt <= 0:
                if active_stop is not None:
                    dur = active_stop["end_t"] - active_stop["start_t"]
                    if dur >= min_stop_duration_s:
                        events.append(
                            StopEvent(
                                stop_event_id=str(uuid4()),
                                run_id=run_id,
                                video_id=video_id,
                                track_id=track_id,
                                start_timestamp_s=active_stop["start_t"],
                                end_timestamp_s=active_stop["end_t"],
                                duration_s=round(dur, 4),
                                threshold_kmh=float(stop_speed_threshold_kmh),
                                status=STATUS_VALID,
                            )
                        )
                    active_stop = None
                events.append(
                    StopEvent(
                        stop_event_id=str(uuid4()),
                        run_id=run_id,
                        video_id=video_id,
                        track_id=track_id,
                        start_timestamp_s=t_curr,
                        end_timestamp_s=t_curr,
                        duration_s=0.0,
                        threshold_kmh=float(stop_speed_threshold_kmh),
                        status=STATUS_INVALID,
                    )
                )
                prev_t = t_curr
                continue

        # Check if current observation qualifies as stopped
        is_stopped = (
            status == STATUS_VALID
            and speed_kmh is not None
            and float(speed_kmh) <= stop_speed_threshold_kmh
        )

        if is_stopped:
            if active_stop is None:
                active_stop = {"start_t": t_curr, "end_t": t_curr}
            else:
                gap = t_curr - active_stop["end_t"]
                if gap > max_gap_s:
                    # Break continuity due to excessive time gap
                    dur = active_stop["end_t"] - active_stop["start_t"]
                    if dur >= min_stop_duration_s:
                        events.append(
                            StopEvent(
                                stop_event_id=str(uuid4()),
                                run_id=run_id,
                                video_id=video_id,
                                track_id=track_id,
                                start_timestamp_s=active_stop["start_t"],
                                end_timestamp_s=active_stop["end_t"],
                                duration_s=round(dur, 4),
                                threshold_kmh=float(stop_speed_threshold_kmh),
                                status=STATUS_VALID,
                            )
                        )
                    active_stop = {"start_t": t_curr, "end_t": t_curr}
                else:
                    active_stop["end_t"] = t_curr
        else:
            # Moving or unavailable observation terminates active episode
            if active_stop is not None:
                dur = active_stop["end_t"] - active_stop["start_t"]
                if dur >= min_stop_duration_s:
                    events.append(
                        StopEvent(
                            stop_event_id=str(uuid4()),
                            run_id=run_id,
                            video_id=video_id,
                            track_id=track_id,
                            start_timestamp_s=active_stop["start_t"],
                            end_timestamp_s=active_stop["end_t"],
                            duration_s=round(dur, 4),
                            threshold_kmh=float(stop_speed_threshold_kmh),
                            status=STATUS_VALID,
                        )
                    )
                active_stop = None

        prev_t = t_curr

    # Finalize active episode at track end
    if active_stop is not None:
        dur = active_stop["end_t"] - active_stop["start_t"]
        if dur >= min_stop_duration_s:
            events.append(
                StopEvent(
                    stop_event_id=str(uuid4()),
                    run_id=run_id,
                    video_id=video_id,
                    track_id=track_id,
                    start_timestamp_s=active_stop["start_t"],
                    end_timestamp_s=active_stop["end_t"],
                    duration_s=round(dur, 4),
                    threshold_kmh=float(stop_speed_threshold_kmh),
                    status=STATUS_VALID,
                )
            )

    return events


def detect_stop_events_for_tracks(
    track_observations: Mapping[int, Sequence[Any]] | Sequence[Any],
    stop_speed_threshold_kmh: float = 5.0,
    min_stop_duration_s: float = 3.0,
    max_gap_s: float = 1.0,
    run_id: str = "",
    video_id: str = "",
) -> dict[int, list[StopEvent]]:
    """Detect stop events across multiple tracks."""
    if isinstance(track_observations, Mapping):
        grouped = track_observations
    else:
        grouped = defaultdict(list)
        for obs in track_observations:
            tr_id = int(_get_val(obs, "track_id"))
            grouped[tr_id].append(obs)

    results: dict[int, list[StopEvent]] = {}
    for track_id, obs_seq in sorted(grouped.items()):
        results[track_id] = detect_stop_events_for_track(
            track_id=track_id,
            observations=obs_seq,
            stop_speed_threshold_kmh=stop_speed_threshold_kmh,
            min_stop_duration_s=min_stop_duration_s,
            max_gap_s=max_gap_s,
            run_id=run_id,
            video_id=video_id,
        )
    return results


def compute_queue_length_m(
    queued_points_world: Sequence[Sequence[float]],
    stop_line_world: Sequence[Sequence[float]] | Sequence[float] | None = None,
) -> float | None:
    """Calculate physical queue length in metres from ground-plane world coordinates.

    Parameters:
        queued_points_world: Sequence of (X, Y) world coordinates in metres.
        stop_line_world: Optional stop line reference in world coordinates.
                         Can be a line segment [[x1, y1], [x2, y2]] or single point [x, y].

    Returns:
        Queue length in metres, or None if coordinates are non-finite or invalid.
    """
    if not queued_points_world:
        return 0.0

    # Validate coordinate finiteness
    for pt in queued_points_world:
        if len(pt) < 2 or not (math.isfinite(pt[0]) and math.isfinite(pt[1])):
            return None

    if stop_line_world is not None:
        # Check if stop_line_world is a segment [[x1, y1], [x2, y2]]
        if (
            isinstance(stop_line_world, Sequence)
            and len(stop_line_world) == 2
            and isinstance(stop_line_world[0], Sequence)
            and len(stop_line_world[0]) >= 2
        ):
            s1, s2 = stop_line_world[0], stop_line_world[1]
            if not (
                math.isfinite(s1[0])
                and math.isfinite(s1[1])
                and math.isfinite(s2[0])
                and math.isfinite(s2[1])
            ):
                return None
            distances = [
                _point_to_segment_distance(pt[0], pt[1], s1, s2)
                for pt in queued_points_world
            ]
            return max(distances)

        # Single reference point [x, y]
        if isinstance(stop_line_world, Sequence) and len(stop_line_world) >= 2:
            sx, sy = float(stop_line_world[0]), float(stop_line_world[1])
            if not (math.isfinite(sx) and math.isfinite(sy)):
                return None
            distances = [
                math.hypot(pt[0] - sx, pt[1] - sy)
                for pt in queued_points_world
            ]
            return max(distances)

        return None

    # No stop line: queue span (max pairwise Euclidean distance between queued vehicles)
    n = len(queued_points_world)
    if n < 2:
        return 0.0

    max_dist = 0.0
    for i in range(n):
        for j in range(i + 1, n):
            d = math.hypot(
                queued_points_world[i][0] - queued_points_world[j][0],
                queued_points_world[i][1] - queued_points_world[j][1],
            )
            if d > max_dist:
                max_dist = d
    return max_dist


def detect_queue_events_at_timestamp(
    timestamp_s: float,
    stopped_tracks_at_t: Sequence[Any],
    zones: Sequence[Any],
    counting_lines: Sequence[Any],
    homography_matrix: np.ndarray | Sequence[Sequence[float]] | None,
    min_queue_vehicles: int = 2,
    stop_line_mapping: Mapping[str, str] | None = None,
    run_id: str = "",
    video_id: str = "",
) -> list[QueueEvent]:
    """Detect and evaluate queue states across all queue zones at a single sample instant."""
    line_mapping = dict(stop_line_mapping or {})
    events: list[QueueEvent] = []

    # Filter to queue zones only
    queue_zones = []
    for z in zones:
        z_type = _get_val(z, "zone_type")
        if z_type == "queue":
            queue_zones.append(z)

    for zone in queue_zones:
        z_id = str(_get_val(zone, "zone_id", ""))
        approach = _get_val(zone, "approach")
        approach_str = str(approach) if approach is not None else None

        # Parse polygon vertices
        raw_geom = _get_val(zone, "geometry_json")
        if raw_geom is not None:
            if isinstance(raw_geom, str):
                geom_obj = json.loads(raw_geom)
            else:
                geom_obj = raw_geom
            vertices = geom_obj.get("vertices", [])
        else:
            vertices = _get_val(zone, "vertices", [])

        # Find stopped vehicles inside this queue zone
        queued_vehicles = []
        for tr in stopped_tracks_at_t:
            if isinstance(tr, (list, tuple)):
                gx, gy = float(tr[0]), float(tr[1])
            else:
                gx = float(_get_val(tr, "ground_x", 0.0))
                gy = float(_get_val(tr, "ground_y", 0.0))

            if point_in_polygon(gx, gy, vertices):
                queued_vehicles.append((gx, gy))

        v_count = len(queued_vehicles)

        # Handle uncalibrated input: must never fall back to pixel distance
        if homography_matrix is None:
            events.append(
                QueueEvent(
                    queue_event_id=str(uuid4()),
                    run_id=run_id,
                    video_id=video_id,
                    zone_id=z_id,
                    approach=approach_str,
                    timestamp_s=float(timestamp_s),
                    queue_length_m=None,
                    queued_vehicle_count=v_count,
                    status=STATUS_UNAVAILABLE,
                )
            )
            continue

        # If vehicle count is below threshold, no queue formed
        if v_count < min_queue_vehicles:
            events.append(
                QueueEvent(
                    queue_event_id=str(uuid4()),
                    run_id=run_id,
                    video_id=video_id,
                    zone_id=z_id,
                    approach=approach_str,
                    timestamp_s=float(timestamp_s),
                    queue_length_m=0.0,
                    queued_vehicle_count=v_count,
                    status=STATUS_VALID,
                )
            )
            continue

        # Project queued ground points to world coordinates
        world_points: list[tuple[float, float]] = []
        proj_error = False
        for gx, gy in queued_vehicles:
            try:
                wx, wy = project_image_to_world(gx, gy, homography_matrix)
                if math.isfinite(wx) and math.isfinite(wy):
                    world_points.append((float(wx), float(wy)))
                else:
                    proj_error = True
                    break
            except Exception:
                proj_error = True
                break

        if proj_error:
            events.append(
                QueueEvent(
                    queue_event_id=str(uuid4()),
                    run_id=run_id,
                    video_id=video_id,
                    zone_id=z_id,
                    approach=approach_str,
                    timestamp_s=float(timestamp_s),
                    queue_length_m=None,
                    queued_vehicle_count=v_count,
                    status=STATUS_INVALID,
                )
            )
            continue

        # Locate associated stop line
        matched_line = None
        target_line_id = line_mapping.get(z_id)
        if target_line_id is not None:
            for cl in counting_lines:
                if str(_get_val(cl, "line_id")) == target_line_id:
                    matched_line = cl
                    break
        elif approach_str is not None:
            for cl in counting_lines:
                cl_app = _get_val(cl, "approach")
                if cl_app is not None and str(cl_app) == approach_str:
                    matched_line = cl
                    break

        stop_line_world = None
        if matched_line is not None:
            raw_cl_geom = _get_val(matched_line, "geometry_json")
            if raw_cl_geom is not None:
                if isinstance(raw_cl_geom, str):
                    cl_geom = json.loads(raw_cl_geom)
                else:
                    cl_geom = raw_cl_geom
                endpoints = cl_geom.get("endpoints", [])
            else:
                endpoints = _get_val(matched_line, "endpoints", [])

            if len(endpoints) == 2:
                try:
                    w1 = project_image_to_world(endpoints[0][0], endpoints[0][1], homography_matrix)
                    w2 = project_image_to_world(endpoints[1][0], endpoints[1][1], homography_matrix)
                    if math.isfinite(w1[0]) and math.isfinite(w1[1]) and math.isfinite(w2[0]) and math.isfinite(w2[1]):
                        stop_line_world = [w1, w2]
                    else:
                        proj_error = True
                except Exception:
                    proj_error = True

        if proj_error:
            events.append(
                QueueEvent(
                    queue_event_id=str(uuid4()),
                    run_id=run_id,
                    video_id=video_id,
                    zone_id=z_id,
                    approach=approach_str,
                    timestamp_s=float(timestamp_s),
                    queue_length_m=None,
                    queued_vehicle_count=v_count,
                    status=STATUS_INVALID,
                )
            )
            continue

        q_len = compute_queue_length_m(world_points, stop_line_world=stop_line_world)
        if q_len is None:
            events.append(
                QueueEvent(
                    queue_event_id=str(uuid4()),
                    run_id=run_id,
                    video_id=video_id,
                    zone_id=z_id,
                    approach=approach_str,
                    timestamp_s=float(timestamp_s),
                    queue_length_m=None,
                    queued_vehicle_count=v_count,
                    status=STATUS_INVALID,
                )
            )
        else:
            events.append(
                QueueEvent(
                    queue_event_id=str(uuid4()),
                    run_id=run_id,
                    video_id=video_id,
                    zone_id=z_id,
                    approach=approach_str,
                    timestamp_s=float(timestamp_s),
                    queue_length_m=round(float(q_len), 4),
                    queued_vehicle_count=v_count,
                    status=STATUS_VALID,
                )
            )

    return events


def evaluate_queue_events_for_run(
    speed_observations: Sequence[Any] | Mapping[int, Sequence[Any]],
    trajectories: Sequence[Any] | Mapping[int, Any],
    zones: Sequence[Any],
    counting_lines: Sequence[Any],
    homography_matrix: np.ndarray | Sequence[Sequence[float]] | None,
    config: Mapping[str, Any] | None = None,
    run_id: str = "",
    video_id: str = "",
) -> tuple[list[StopEvent], list[QueueEvent]]:
    """Complete evaluation of stop events and time-sliced queue observations across a processing run."""
    queue_cfg = config.get("queue", {}) if config else {}
    stop_speed_threshold_kmh = float(queue_cfg.get("stop_speed_threshold_kmh", 5.0))
    min_stop_duration_s = float(queue_cfg.get("min_stop_duration_s", 3.0))
    min_queue_vehicles = int(queue_cfg.get("min_queue_vehicles", 2))
    aggregation_interval_s = float(queue_cfg.get("aggregation_interval_s", 1.0))
    max_gap_s = float(queue_cfg.get("max_gap_seconds", 1.0))
    stop_line_mapping = dict(queue_cfg.get("stop_line_mapping", {}))

    # Detect confirmed stop events for all vehicle tracks
    stop_events_by_track = detect_stop_events_for_tracks(
        track_observations=speed_observations,
        stop_speed_threshold_kmh=stop_speed_threshold_kmh,
        min_stop_duration_s=min_stop_duration_s,
        max_gap_s=max_gap_s,
        run_id=run_id,
        video_id=video_id,
    )

    all_stop_events: list[StopEvent] = []
    for tr_id, ev_list in sorted(stop_events_by_track.items()):
        all_stop_events.extend(ev_list)

    # Index trajectories by track_id
    traj_map: dict[int, Any] = {}
    if isinstance(trajectories, Mapping):
        traj_map = dict(trajectories)
    else:
        for traj in trajectories:
            tr_id = int(_get_val(traj, "track_id"))
            traj_map[tr_id] = traj

    # Find timeline bounds from observations
    all_timestamps: list[float] = []
    if isinstance(speed_observations, Mapping):
        for obs_list in speed_observations.values():
            for obs in obs_list:
                all_timestamps.append(float(_get_val(obs, "timestamp_s", 0.0)))
    else:
        for obs in speed_observations:
            all_timestamps.append(float(_get_val(obs, "timestamp_s", 0.0)))

    if not all_timestamps:
        for traj in traj_map.values():
            pts = _get_val(traj, "points", [])
            for p in pts:
                all_timestamps.append(float(_get_val(p, "timestamp_s", 0.0)))

    if not all_timestamps:
        return all_stop_events, []

    t_min = min(all_timestamps)
    t_max = max(all_timestamps)

    # Generate regular sample instants
    sample_instants: list[float] = []
    curr_t = t_min
    while curr_t <= t_max + 1e-6:
        sample_instants.append(round(curr_t, 6))
        curr_t += aggregation_interval_s

    all_queue_events: list[QueueEvent] = []

    for t_sample in sample_instants:
        # Determine which tracks are stopped at t_sample
        stopped_tracks_at_t: list[dict[str, Any]] = []
        for tr_id, stop_list in stop_events_by_track.items():
            is_stopped_now = any(
                se.status == STATUS_VALID
                and se.start_timestamp_s <= t_sample + 1e-6
                and (se.end_timestamp_s is not None and t_sample <= se.end_timestamp_s + 1e-6)
                for se in stop_list
            )
            if not is_stopped_now:
                continue

            traj = traj_map.get(tr_id)
            if traj is None:
                continue

            pts = _get_val(traj, "points", [])
            if not pts:
                continue

            # Find closest observation point within max_gap_s
            best_pt = None
            best_dt = float("inf")
            for p in pts:
                pt_t = float(_get_val(p, "timestamp_s", 0.0))
                dt = abs(pt_t - t_sample)
                if dt < best_dt:
                    best_dt = dt
                    best_pt = p

            if best_pt is not None and best_dt <= max_gap_s:
                stopped_tracks_at_t.append(
                    {
                        "track_id": tr_id,
                        "ground_x": float(_get_val(best_pt, "ground_x", 0.0)),
                        "ground_y": float(_get_val(best_pt, "ground_y", 0.0)),
                        "timestamp_s": t_sample,
                    }
                )

        q_events = detect_queue_events_at_timestamp(
            timestamp_s=t_sample,
            stopped_tracks_at_t=stopped_tracks_at_t,
            zones=zones,
            counting_lines=counting_lines,
            homography_matrix=homography_matrix,
            min_queue_vehicles=min_queue_vehicles,
            stop_line_mapping=stop_line_mapping,
            run_id=run_id,
            video_id=video_id,
        )
        all_queue_events.extend(q_events)

    return all_stop_events, all_queue_events
