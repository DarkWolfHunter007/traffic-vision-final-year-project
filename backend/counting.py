"""Phase 06 pure vehicle counting, line-crossing detection, movement derivation, and aggregation logic.

Pure computational functions free of database side-effects and external I/O.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping, Sequence
import json
import math
from typing import Any
from uuid import uuid4

from backend.geometry import point_side_of_line, segments_intersect
from backend.trajectories import Trajectory

VALID_MOVEMENTS: frozenset[str] = frozenset(
    {"left", "through", "right", "u_turn", "unknown"}
)


def point_in_polygon(point: Sequence[float], vertices: Sequence[Sequence[float]]) -> bool:
    """Ray-casting algorithm to test whether a 2D point lies inside a planar polygon.

    Parameters:
        point: [x, y] coordinates of the query point.
        vertices: Ordered list of [x, y] polygon vertices.

    Returns:
        True if the point lies inside or on the polygon boundary; False otherwise.
    """
    x, y = float(point[0]), float(point[1])
    n = len(vertices)
    if n < 3:
        return False

    inside = False
    p1x, p1y = float(vertices[0][0]), float(vertices[0][1])
    for i in range(1, n + 1):
        p2x, p2y = float(vertices[i % n][0]), float(vertices[i % n][1])
        if min(p1y, p2y) <= y <= max(p1y, p2y):
            if x <= max(p1x, p2x):
                if p1y != p2y:
                    xinters = (y - p1y) * (p2x - p1x) / (p2y - p1y) + p1x
                    if p1x == p2x or x <= xinters:
                        inside = not inside
                elif y == p1y and min(p1x, p2x) <= x <= max(p1x, p2x):
                    return True
        p1x, p1y = p2x, p2y

    return inside


def _get_val(obj: Any, key: str, default: Any = None) -> Any:
    """Safe key lookup supporting both dict and sqlite3.Row objects."""
    if isinstance(obj, Mapping):
        return obj.get(key, default)
    try:
        val = obj[key]
        return val if val is not None else default
    except (KeyError, IndexError, TypeError):
        return default


def derive_movement(
    trajectory: Trajectory | Sequence[Any],
    zones: Sequence[Mapping[str, Any] | Any],
    movement_mapping: Mapping[str, Any] | None = None,
) -> tuple[str, str | None, str | None]:
    """Derive turning movement from entry zone and exit zone approach evidence.

    Parameters:
        trajectory: Trajectory instance or sequence of points with ground_x, ground_y, timestamp_s.
        zones: Configured zones with zone_type ('entry', 'exit', ...), approach, and vertices.
        movement_mapping: Configurable mapping of approach pairs to movements.
            Supports nested dict `mapping[entry_app][exit_app]` or flat `mapping["entry->exit"]`.

    Returns:
        (movement, entry_approach, exit_approach)
        where movement is one of ('left', 'through', 'right', 'u_turn', 'unknown').
        Unresolved movements always evaluate to 'unknown', never guessed.
    """
    points = trajectory.points if isinstance(trajectory, Trajectory) else trajectory
    if not points:
        return "unknown", None, None

    # Separate entry and exit zones
    entry_zones: list[tuple[str, list[list[float]]]] = []
    exit_zones: list[tuple[str, list[list[float]]]] = []

    for z in zones:
        z_type = str(_get_val(z, "zone_type", ""))
        app = _get_val(z, "approach")
        if not app:
            continue
        geom = _get_val(z, "geometry_json")
        if isinstance(geom, str):
            try:
                geom_data = json.loads(geom)
            except Exception:
                geom_data = {}
            vertices = geom_data.get("vertices", [])
        elif isinstance(geom, Mapping):
            vertices = geom.get("vertices", [])
        else:
            vertices = _get_val(z, "vertices", [])

        if not vertices or len(vertices) < 3:
            continue

        if z_type == "entry":
            entry_zones.append((str(app), vertices))
        elif z_type == "exit":
            exit_zones.append((str(app), vertices))

    entry_approach: str | None = None
    entry_time: float | None = None
    exit_approach: str | None = None
    exit_time: float | None = None

    for pt in points:
        gx = float(getattr(pt, "ground_x", pt[0] if isinstance(pt, Sequence) else 0.0))
        gy = float(getattr(pt, "ground_y", pt[1] if isinstance(pt, Sequence) else 0.0))
        ts = float(getattr(pt, "timestamp_s", pt[2] if isinstance(pt, Sequence) and len(pt) > 2 else 0.0))
        p_coord = (gx, gy)

        # Detect initial entry zone
        if entry_approach is None:
            for app, verts in entry_zones:
                if point_in_polygon(p_coord, verts):
                    entry_approach = app
                    entry_time = ts
                    break

        # Detect exit zone (must occur at or after entry)
        for app, verts in exit_zones:
            if point_in_polygon(p_coord, verts):
                if entry_time is None or ts >= entry_time:
                    exit_approach = app
                    exit_time = ts
                    break

    if entry_approach is None or exit_approach is None or movement_mapping is None:
        return "unknown", entry_approach, exit_approach

    # Lookup approach-pair movement in config
    movement = None
    if entry_approach in movement_mapping and isinstance(movement_mapping[entry_approach], Mapping):
        movement = movement_mapping[entry_approach].get(exit_approach)
    if movement is None:
        flat_key = f"{entry_approach}->{exit_approach}"
        movement = movement_mapping.get(flat_key)
    if movement is None:
        movement = movement_mapping.get((entry_approach, exit_approach))

    if movement is not None and str(movement) in VALID_MOVEMENTS:
        return str(movement), entry_approach, exit_approach

    return "unknown", entry_approach, exit_approach


def detect_crossings_for_trajectory(
    trajectory: Trajectory,
    counting_lines: Sequence[Mapping[str, Any]],
    min_reentry_gap_s: float = 2.0,
    max_gap_seconds: float = 1.0,
    movement: str = "unknown",
    entry_approach: str | None = None,
) -> list[dict[str, Any]]:
    """Detect counting-line crossings for one trajectory history.

    Parameters:
        trajectory: Chronological Trajectory with ground points.
        counting_lines: Configured counting lines.
        min_reentry_gap_s: Time gap threshold for deduplicating re-crossings per line.
        max_gap_seconds: Phase 04 maximum temporal gap allowed between consecutive points.
        movement: Movement string ('left', 'through', 'right', 'u_turn', 'unknown').
        entry_approach: Approach string of entry zone, if resolved.

    Returns:
        List of raw crossing event dictionaries with deduplicated flag recorded.
    """
    points = trajectory.points
    if len(points) < 2:
        return []

    crossings: list[dict[str, Any]] = []

    for line in counting_lines:
        line_id = str(_get_val(line, "line_id"))
        line_approach = _get_val(line, "approach") or entry_approach
        line_version = str(_get_val(line, "config_version", ""))
        bidirectional = bool(_get_val(line, "bidirectional", False))

        geom = _get_val(line, "geometry_json")
        if isinstance(geom, str):
            try:
                geom_data = json.loads(geom)
            except Exception:
                geom_data = {}
        elif isinstance(geom, Mapping):
            geom_data = dict(geom)
        else:
            geom_data = dict(line)

        endpoints = geom_data.get("endpoints")
        if not endpoints or len(endpoints) != 2:
            continue

        l_start = (float(endpoints[0][0]), float(endpoints[0][1]))
        l_end = (float(endpoints[1][0]), float(endpoints[1][1]))
        dir_vec = geom_data.get("direction_vector")
        dir_tuple = (float(dir_vec[0]), float(dir_vec[1])) if dir_vec and len(dir_vec) == 2 else None

        last_counted_ts: float | None = None

        for i in range(len(points) - 1):
            p1 = points[i]
            p2 = points[i + 1]

            # Invariant: Do not interpolate through gaps larger than Phase 04 gap rule
            time_gap = p2.timestamp_s - p1.timestamp_s
            if time_gap > max_gap_seconds:
                continue

            pt1 = (p1.ground_x, p1.ground_y)
            pt2 = (p2.ground_x, p2.ground_y)

            # Check side of line sign change using Phase 05 side helper
            side1 = point_side_of_line(pt1, l_start, l_end)
            side2 = point_side_of_line(pt2, l_start, l_end)

            if not ((side1 > 0 and side2 < 0) or (side1 < 0 and side2 > 0)):
                continue

            # Verify actual segment-segment intersection
            if not segments_intersect(pt1, pt2, l_start, l_end):
                continue

            # A physical line crossing is observed
            t_cross = p2.timestamp_s
            fn_cross = p2.frame_number
            vx = pt2[0] - pt1[0]
            vy = pt2[1] - pt1[1]

            is_wrong_way = False
            if bidirectional:
                direction = "forward" if (side1 < 0 and side2 > 0) else "reverse"
            else:
                if dir_tuple is not None:
                    dot = vx * dir_tuple[0] + vy * dir_tuple[1]
                    if dot > 0:
                        direction = "forward"
                    else:
                        direction = "reverse"
                        is_wrong_way = True
                else:
                    direction = "forward"

            # Deduplication: raw events preserved, deduplicated flag recorded
            if is_wrong_way:
                deduplicated = 1
            elif last_counted_ts is not None and (t_cross - last_counted_ts) < min_reentry_gap_s:
                deduplicated = 1
            else:
                deduplicated = 0
                last_counted_ts = t_cross

            crossings.append(
                {
                    "crossing_event_id": str(uuid4()),
                    "run_id": trajectory.run_id,
                    "video_id": trajectory.video_id,
                    "line_id": line_id,
                    "track_id": trajectory.track_id,
                    "frame_number": fn_cross,
                    "timestamp_s": round(t_cross, 4),
                    "vehicle_class": trajectory.consensus_class,
                    "direction": direction,
                    "approach": line_approach,
                    "movement": movement,
                    "line_config_version": line_version,
                    "deduplicated": deduplicated,
                }
            )

    return crossings


def aggregate_volume_bins(
    crossings: Sequence[Mapping[str, Any]],
    run_id: str,
    video_id: str,
    bin_duration_s: float = 900.0,
    video_duration_s: float | None = None,
) -> list[dict[str, Any]]:
    """Aggregate traffic volume into 15-minute (or configured) time bins.

    Parameters:
        crossings: Sequence of crossing event mappings. Only non-deduplicated events (deduplicated == 0) are counted.
        run_id: Counting processing run ID.
        video_id: Source video identifier.
        bin_duration_s: Duration of each volume bin in seconds (default 900.0).
        video_duration_s: Total observed duration of the source video in seconds, if known.

    Returns:
        List of traffic_volume_bins rows with count and extrapolated vehicles/hour.
    """
    if bin_duration_s <= 0:
        raise ValueError(f"bin_duration_s must be positive, got {bin_duration_s}")

    # Group counts by (line_id, bin_index, vehicle_class, approach, movement)
    counts_map: dict[tuple[str, int, str, str | None, str], int] = defaultdict(int)

    for c in crossings:
        if int(c.get("deduplicated", 0)) != 0:
            continue
        ts = float(c["timestamp_s"])
        bin_idx = int(math.floor(ts / bin_duration_s))
        line_id = str(c["line_id"])
        v_class = str(c.get("vehicle_class") or "unknown")
        app = str(c["approach"]) if c.get("approach") is not None else None
        mov = str(c.get("movement") or "unknown")

        key = (line_id, bin_idx, v_class, app, mov)
        counts_map[key] += 1

    bins: list[dict[str, Any]] = []

    for (line_id, bin_idx, v_class, app, mov), count in sorted(counts_map.items()):
        bin_start = float(bin_idx * bin_duration_s)

        # Calculate actual observed duration within this bin
        if video_duration_s is not None and video_duration_s < (bin_start + bin_duration_s):
            observed_dur = max(0.0, float(video_duration_s - bin_start))
        else:
            observed_dur = float(bin_duration_s)

        if observed_dur > 0.0:
            extrapolated: float | None = round(count * 3600.0 / observed_dur, 2)
        else:
            extrapolated = None

        bins.append(
            {
                "bin_id": str(uuid4()),
                "run_id": run_id,
                "video_id": video_id,
                "line_id": line_id,
                "bin_start_s": bin_start,
                "bin_duration_s": float(bin_duration_s),
                "observed_duration_s": round(observed_dur, 4),
                "vehicle_class": v_class,
                "approach": app,
                "movement": mov,
                "count": count,
                "extrapolated_vehicles_per_hour": extrapolated,
            }
        )

    return bins


def calculate_counting_comparison(
    counted_events: Sequence[Mapping[str, Any]],
    ground_truth_counts: Sequence[Mapping[str, Any]],
    video_segments: Sequence[Mapping[str, Any]] | None = None,
    error_tolerance_pct: float = 10.0,
) -> dict[str, Any]:
    """Compare counted vehicle volume against manual ground-truth counts.

    Invariant: Records error_tolerance_pct but MUST NOT state that the counter passed or was accepted.
    """
    # Build lookup of video_segments by segment_id if provided
    segments_by_id: dict[str, Mapping[str, Any]] = {}
    if video_segments:
        for s in video_segments:
            segments_by_id[str(s["segment_id"])] = s

    # Aggregate counted events (deduplicated == 0 only) by segment, approach, movement, vehicle_class
    # If segments provided, filter crossings by segment time bounds
    counted_totals: dict[tuple[str | None, str, str, str | None], int] = defaultdict(int)

    for event in counted_events:
        if int(event.get("deduplicated", 0)) != 0:
            continue
        ts = float(event["timestamp_s"])
        app = str(event.get("approach") or "all")
        mov = str(event.get("movement") or "all")
        cls_name = str(event.get("vehicle_class")) if event.get("vehicle_class") is not None else None

        if segments_by_id:
            for seg_id, seg in segments_by_id.items():
                s_start = float(seg["start_s"])
                s_end = float(seg["end_s"])
                if s_start <= ts <= s_end:
                    counted_totals[(seg_id, app, mov, cls_name)] += 1
                    counted_totals[(seg_id, app, mov, None)] += 1
        else:
            counted_totals[(None, app, mov, cls_name)] += 1
            counted_totals[(None, app, mov, None)] += 1

    comparisons: list[dict[str, Any]] = []
    total_counted = 0
    total_observed = 0

    for gt in ground_truth_counts:
        seg_id = str(gt["video_segment_id"]) if "video_segment_id" in gt else None
        app = str(gt.get("approach", "all"))
        mov = str(gt.get("movement", "all"))
        gt_cls = str(gt["vehicle_class"]) if gt.get("vehicle_class") is not None else None
        observed = int(gt["observed_count"])

        counted = counted_totals.get((seg_id, app, mov, gt_cls), 0)
        abs_err = abs(counted - observed)
        pct_err = round((abs_err / observed * 100.0), 2) if observed > 0 else (0.0 if abs_err == 0 else 100.0)

        total_counted += counted
        total_observed += observed

        comparisons.append(
            {
                "video_segment_id": seg_id,
                "approach": app,
                "movement": mov,
                "vehicle_class": gt_cls,
                "counted": counted,
                "observed": observed,
                "absolute_error": abs_err,
                "percent_error": pct_err,
            }
        )

    tot_abs_err = abs(total_counted - total_observed)
    tot_pct_err = (
        round((tot_abs_err / total_observed * 100.0), 2)
        if total_observed > 0
        else (0.0 if tot_abs_err == 0 else 100.0)
    )

    return {
        "error_tolerance_pct": float(error_tolerance_pct),
        "total_counted": total_counted,
        "total_observed": total_observed,
        "total_absolute_error": tot_abs_err,
        "total_percent_error": tot_pct_err,
        "items_count": len(comparisons),
        "comparisons": comparisons,
    }
