"""Phase 08 calibrated world-coordinate speed estimation.

Provides pure mathematical primitives and trajectory transformations for:
- Transforming bottom-centre ground points to road-plane world coordinates in metres.
- Computing distance over authoritative decoder timestamps (pts_s / timestamp_s).
- Deterministic temporal position smoothing without bridging observation gaps.
- Quality flagging for gaps, short tracks, non-monotonic timestamps, stationary jitter, and outliers.
- Unit conversions between m/s and km/h.

Rules (frame-rate independent):
- Smoothing is a symmetric centred moving average; the half-width shrinks to the
  largest symmetric span that stays inside one gap-free segment and inside the
  window, so constant velocity yields the exact true speed. Gaps are never bridged.
- Stationary rule: a step is stationary (valid 0.0 m/s) when the raw-position speed
  measured over a reference span of at least STATIONARY_REFERENCE_S seconds of track
  time (clipped to the gap-free segment) is below min_displacement_m / STATIONARY_REFERENCE_S.
  Using a time-based span (not a single step) keeps jitter at segment edges at 0.0
  regardless of frame rate. Segments shorter than the reference use the whole segment.
- Outliers: the raw unsmoothed step speed is also compared with max_plausible_speed_mps;
  every output whose smoothing window contains a flagged step is marked invalid.
- smoothing_window is NULL when smoothing is not applied (method 'none' or window 0).
- Values are rounded to 4 decimal places.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
import math
from typing import Any
from uuid import uuid4

import numpy as np

from backend.calibration import project_image_to_world
from backend.trajectories import STATUS_INVALID as TRAJ_STATUS_INVALID, Trajectory

STATUS_VALID = "valid"
STATUS_INVALID = "invalid"
STATUS_UNAVAILABLE = "unavailable"

STATIONARY_REFERENCE_S = 0.5

VALID_SPEED_STATUSES: frozenset[str] = frozenset(
    {STATUS_VALID, STATUS_INVALID, STATUS_UNAVAILABLE}
)


@dataclass(frozen=True)
class SpeedObservation:
    """One immutable speed observation row corresponding to the canonical schema."""

    speed_observation_id: str
    run_id: str
    video_id: str
    track_id: int
    timestamp_s: float
    speed_mps: float | None
    speed_kmh: float | None
    calibration_id: str
    status: str
    smoothing_window: float | None
    ground_point_method: str = "bottom_center"
    world_x: float | None = None
    world_y: float | None = None

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary matching database speed_observations columns."""
        return {
            "speed_observation_id": self.speed_observation_id,
            "run_id": self.run_id,
            "video_id": self.video_id,
            "track_id": self.track_id,
            "timestamp_s": float(self.timestamp_s),
            "speed_mps": float(self.speed_mps) if self.speed_mps is not None else None,
            "speed_kmh": float(self.speed_kmh) if self.speed_kmh is not None else None,
            "calibration_id": self.calibration_id,
            "status": self.status,
            "smoothing_window": float(self.smoothing_window) if self.smoothing_window is not None else None,
            "ground_point_method": self.ground_point_method,
        }


def mps_to_kmh(speed_mps: float) -> float:
    """Convert speed from metres per second (m/s) to kilometres per hour (km/h)."""
    return round(float(speed_mps) * 3.6, 4)


def kmh_to_mps(speed_kmh: float) -> float:
    """Convert speed from kilometres per hour (km/h) to metres per second (m/s)."""
    return round(float(speed_kmh) / 3.6, 4)


def _smooth_with_extent(
    points: Sequence[tuple[float, float, float]],
    window_s: float,
    max_gap_s: float,
) -> list[tuple[float, float, int, int]]:
    n = len(points)
    if n == 0:
        return []
    if n == 1 or window_s <= 0.0:
        return [(p[1], p[2], i, i) for i, p in enumerate(points)]

    half_window = window_s / 2.0
    eps = 1e-9

    segments: list[list[int]] = []
    current: list[int] = [0]
    for i in range(1, n):
        dt = points[i][0] - points[i - 1][0]
        if 0 < dt <= max_gap_s:
            current.append(i)
        else:
            segments.append(current)
            current = [i]
    segments.append(current)

    out: list[tuple[float, float, int, int] | None] = [None] * n
    for seg in segments:
        m = len(seg)
        for pos in range(m):
            idx = seg[pos]
            t_i = points[idx][0]
            k = 0
            while (
                pos - k - 1 >= 0
                and pos + k + 1 < m
                and points[seg[pos + k + 1]][0] - t_i <= half_window + eps
                and t_i - points[seg[pos - k - 1]][0] <= half_window + eps
            ):
                k += 1
            members = seg[pos - k : pos + k + 1]
            mean_x = sum(points[j][1] for j in members) / len(members)
            mean_y = sum(points[j][2] for j in members) / len(members)
            out[idx] = (mean_x, mean_y, members[0], members[-1])
    return [o for o in out if o is not None]


def smooth_trajectory_positions(
    points: Sequence[tuple[float, float, float]],
    window_s: float = 0.5,
    max_gap_s: float = 1.0,
) -> list[tuple[float, float]]:
    return [(x, y) for x, y, _, _ in _smooth_with_extent(points, window_s, max_gap_s)]


def estimate_speeds_for_trajectory(
    trajectory: Trajectory,
    homography_matrix: np.ndarray | Sequence[Sequence[float]],
    calibration_id: str,
    run_id: str,
    config: Mapping[str, Any] | None = None,
) -> list[SpeedObservation]:
    """Calculate calibrated speed observations for a single vehicle trajectory.

    Parameters:
        trajectory: Phase 04 Trajectory object with ordered TrajectoryPoint items.
        homography_matrix: 3x3 planar homography matrix mapping image pixels to world metres.
        calibration_id: UUID of accepted calibration run.
        run_id: Child processing run UUID.
        config: Optional project configuration mapping with 'speed' section.

    Returns:
        List of SpeedObservation records, one per trajectory observation point.
    """
    speed_cfg = config.get("speed", {}) if config else {}
    smoothing_method = str(speed_cfg.get("smoothing_method", "moving_average"))
    window_s = float(speed_cfg.get("smoothing_window_s", 0.5))
    min_track_points = int(speed_cfg.get("min_track_points", 3))
    max_gap_s = float(speed_cfg.get("max_gap_seconds", 1.0))
    min_displacement_m = float(speed_cfg.get("min_displacement_m", 0.1))
    max_plausible_speed_mps = float(speed_cfg.get("max_plausible_speed_mps", 45.0))
    ground_point_method = str(speed_cfg.get("ground_point_method", "bottom_center"))
    smoothing_active = smoothing_method == "moving_average" and window_s > 0.0
    window_out: float | None = window_s if smoothing_active else None

    pts = trajectory.points
    n = len(pts)
    if n == 0:
        return []

    # If the entire trajectory is invalid, mark all observations as invalid
    if trajectory.status == TRAJ_STATUS_INVALID:
        return [
            SpeedObservation(
                speed_observation_id=str(uuid4()),
                run_id=run_id,
                video_id=trajectory.video_id,
                track_id=trajectory.track_id,
                timestamp_s=p.timestamp_s,
                speed_mps=None,
                speed_kmh=None,
                calibration_id=calibration_id,
                status=STATUS_INVALID,
                smoothing_window=window_out,
                ground_point_method=ground_point_method,
                world_x=None,
                world_y=None,
            )
            for p in pts
        ]

    # Project bottom-centre ground contact points to road-plane world coordinates
    world_coords: list[tuple[float, float] | None] = []
    for p in pts:
        try:
            wx, wy = project_image_to_world(p.ground_x, p.ground_y, homography_matrix)
            if math.isfinite(wx) and math.isfinite(wy):
                world_coords.append((float(wx), float(wy)))
            else:
                world_coords.append(None)
        except Exception:
            world_coords.append(None)

    # Check for short tracks below the minimum observation requirement
    if n < min_track_points:
        return [
            SpeedObservation(
                speed_observation_id=str(uuid4()),
                run_id=run_id,
                video_id=trajectory.video_id,
                track_id=trajectory.track_id,
                timestamp_s=p.timestamp_s,
                speed_mps=None,
                speed_kmh=None,
                calibration_id=calibration_id,
                status=STATUS_INVALID if world_coords[idx] is None else STATUS_UNAVAILABLE,
                smoothing_window=window_out,
                ground_point_method=ground_point_method,
                world_x=world_coords[idx][0] if world_coords[idx] is not None else None,
                world_y=world_coords[idx][1] if world_coords[idx] is not None else None,
            )
            for idx, p in enumerate(pts)
        ]

    # Apply position smoothing across valid projected points
    extents: list[tuple[int, int]] = [(i, i) for i in range(n)]
    if smoothing_active:
        valid_indices = [i for i, c in enumerate(world_coords) if c is not None]
        valid_tuples = [
            (pts[i].timestamp_s, world_coords[i][0], world_coords[i][1])  # type: ignore[index]
            for i in valid_indices
        ]
        smoothed = _smooth_with_extent(valid_tuples, window_s=window_s, max_gap_s=max_gap_s)

        effective_coords: list[tuple[float, float] | None] = list(world_coords)
        for orig_idx, (sx, sy, lo, hi) in zip(valid_indices, smoothed):
            effective_coords[orig_idx] = (sx, sy)
            extents[orig_idx] = (valid_indices[lo], valid_indices[hi])
    else:
        effective_coords = world_coords

    # Gap-free segments over raw projected points for the stationary reference span
    seg_of: dict[int, list[int]] = {}
    cur_seg: list[int] = []
    last_valid: int | None = None
    for i in range(n):
        if world_coords[i] is None:
            last_valid = None
            cur_seg = []
            continue
        if last_valid is not None:
            d = pts[i].timestamp_s - pts[last_valid].timestamp_s
            if not (0 < d <= max_gap_s):
                cur_seg = []
        cur_seg.append(i)
        seg_of[i] = cur_seg
        last_valid = i

    def _reference_motion(i: int) -> tuple[float, float]:
        """Return (displacement_m, span_s) over the stationary reference span."""
        seg = seg_of[i]
        b = seg.index(i)
        pos0 = b
        a = b - 1
        while pts[seg[b]].timestamp_s - pts[seg[a]].timestamp_s < STATIONARY_REFERENCE_S - 1e-9:
            can_lo = a > 0
            can_hi = b < len(seg) - 1
            if not can_lo and not can_hi:
                break
            if can_lo and (not can_hi or (b - pos0) >= (pos0 - 1 - a)):
                a -= 1
            else:
                b += 1
        c0 = world_coords[seg[a]]
        c1 = world_coords[seg[b]]
        span = pts[seg[b]].timestamp_s - pts[seg[a]].timestamp_s
        return math.hypot(c1[0] - c0[0], c1[1] - c0[1]), span  # type: ignore[index]

    # Raw (unsmoothed) outlier steps: step s joins raw points s-1 and s
    flagged_steps: list[int] = []
    for s_idx in range(1, n):
        c0, c1 = world_coords[s_idx - 1], world_coords[s_idx]
        if c0 is None or c1 is None:
            continue
        raw_dt = pts[s_idx].timestamp_s - pts[s_idx - 1].timestamp_s
        if raw_dt <= 0 or raw_dt > max_gap_s:
            continue
        if math.hypot(c1[0] - c0[0], c1[1] - c0[1]) / raw_dt > max_plausible_speed_mps:
            flagged_steps.append(s_idx)

    observations: list[SpeedObservation] = []

    for i in range(n):
        p_curr = pts[i]
        curr_coord = effective_coords[i]
        t_curr = p_curr.timestamp_s

        curr_wx = curr_coord[0] if curr_coord is not None else None
        curr_wy = curr_coord[1] if curr_coord is not None else None

        # If current point could not be projected, mark invalid
        if curr_coord is None:
            observations.append(
                SpeedObservation(
                    speed_observation_id=str(uuid4()),
                    run_id=run_id,
                    video_id=trajectory.video_id,
                    track_id=trajectory.track_id,
                    timestamp_s=t_curr,
                    speed_mps=None,
                    speed_kmh=None,
                    calibration_id=calibration_id,
                    status=STATUS_INVALID,
                    smoothing_window=window_out,
                    ground_point_method=ground_point_method,
                    world_x=None,
                    world_y=None,
                )
            )
            continue

        # Initial point of track has no preceding observation
        if i == 0:
            observations.append(
                SpeedObservation(
                    speed_observation_id=str(uuid4()),
                    run_id=run_id,
                    video_id=trajectory.video_id,
                    track_id=trajectory.track_id,
                    timestamp_s=t_curr,
                    speed_mps=None,
                    speed_kmh=None,
                    calibration_id=calibration_id,
                    status=STATUS_UNAVAILABLE,
                    smoothing_window=window_out,
                    ground_point_method=ground_point_method,
                    world_x=curr_wx,
                    world_y=curr_wy,
                )
            )
            continue

        prev_coord = effective_coords[i - 1]
        t_prev = pts[i - 1].timestamp_s

        # If previous point was invalid, speed cannot be computed from it
        if prev_coord is None:
            observations.append(
                SpeedObservation(
                    speed_observation_id=str(uuid4()),
                    run_id=run_id,
                    video_id=trajectory.video_id,
                    track_id=trajectory.track_id,
                    timestamp_s=t_curr,
                    speed_mps=None,
                    speed_kmh=None,
                    calibration_id=calibration_id,
                    status=STATUS_UNAVAILABLE,
                    smoothing_window=window_out,
                    ground_point_method=ground_point_method,
                    world_x=curr_wx,
                    world_y=curr_wy,
                )
            )
            continue

        dt = t_curr - t_prev

        # Check non-monotonic or zero timestamp
        if dt <= 0:
            observations.append(
                SpeedObservation(
                    speed_observation_id=str(uuid4()),
                    run_id=run_id,
                    video_id=trajectory.video_id,
                    track_id=trajectory.track_id,
                    timestamp_s=t_curr,
                    speed_mps=None,
                    speed_kmh=None,
                    calibration_id=calibration_id,
                    status=STATUS_INVALID,
                    smoothing_window=window_out,
                    ground_point_method=ground_point_method,
                    world_x=curr_wx,
                    world_y=curr_wy,
                )
            )
            continue

        # Check temporal gap
        if dt > max_gap_s:
            observations.append(
                SpeedObservation(
                    speed_observation_id=str(uuid4()),
                    run_id=run_id,
                    video_id=trajectory.video_id,
                    track_id=trajectory.track_id,
                    timestamp_s=t_curr,
                    speed_mps=None,
                    speed_kmh=None,
                    calibration_id=calibration_id,
                    status=STATUS_UNAVAILABLE,
                    smoothing_window=window_out,
                    ground_point_method=ground_point_method,
                    world_x=curr_wx,
                    world_y=curr_wy,
                )
            )
            continue

        # Compute Euclidean displacement in metres
        dx = curr_coord[0] - prev_coord[0]
        dy = curr_coord[1] - prev_coord[1]
        disp_m = math.hypot(dx, dy)

        # Stationary vehicle jitter threshold
        lo_ext = min(extents[i - 1][0], extents[i][0])
        hi_ext = max(extents[i - 1][1], extents[i][1])
        raw_outlier = any(lo_ext <= st - 1 and st <= hi_ext for st in flagged_steps)
        ref_disp, ref_span = _reference_motion(i)
        if ref_span < STATIONARY_REFERENCE_S - 1e-9:
            # Gap-free segment shorter than the reference span: compare total
            # displacement directly so the effective threshold never drops
            # below min_displacement_m.
            stationary = ref_disp < min_displacement_m
        else:
            stationary = ref_disp / ref_span < (min_displacement_m / STATIONARY_REFERENCE_S)

        if not raw_outlier and stationary:
            observations.append(
                SpeedObservation(
                    speed_observation_id=str(uuid4()),
                    run_id=run_id,
                    video_id=trajectory.video_id,
                    track_id=trajectory.track_id,
                    timestamp_s=t_curr,
                    speed_mps=0.0,
                    speed_kmh=0.0,
                    calibration_id=calibration_id,
                    status=STATUS_VALID,
                    smoothing_window=window_out,
                    ground_point_method=ground_point_method,
                    world_x=curr_wx,
                    world_y=curr_wy,
                )
            )
            continue

        # Instantaneous speed over authoritative elapsed time
        v_mps = disp_m / dt

        # Outlier rejection for implausibly fast jumps
        if raw_outlier or v_mps > max_plausible_speed_mps:
            observations.append(
                SpeedObservation(
                    speed_observation_id=str(uuid4()),
                    run_id=run_id,
                    video_id=trajectory.video_id,
                    track_id=trajectory.track_id,
                    timestamp_s=t_curr,
                    speed_mps=None,
                    speed_kmh=None,
                    calibration_id=calibration_id,
                    status=STATUS_INVALID,
                    smoothing_window=window_out,
                    ground_point_method=ground_point_method,
                    world_x=curr_wx,
                    world_y=curr_wy,
                )
            )
            continue

        # Valid speed observation
        observations.append(
            SpeedObservation(
                speed_observation_id=str(uuid4()),
                run_id=run_id,
                video_id=trajectory.video_id,
                track_id=trajectory.track_id,
                timestamp_s=t_curr,
                speed_mps=round(v_mps, 4),
                speed_kmh=round(v_mps * 3.6, 4),
                calibration_id=calibration_id,
                status=STATUS_VALID,
                smoothing_window=window_out,
                ground_point_method=ground_point_method,
                world_x=curr_wx,
                world_y=curr_wy,
            )
        )

    return observations


def estimate_speeds_for_trajectories(
    trajectories: Mapping[int, Trajectory],
    homography_matrix: np.ndarray | Sequence[Sequence[float]],
    calibration_id: str,
    run_id: str,
    config: Mapping[str, Any] | None = None,
) -> dict[int, list[SpeedObservation]]:
    """Compute speed observations for all trajectories in a dictionary."""
    results: dict[int, list[SpeedObservation]] = {}
    for track_id, traj in sorted(trajectories.items()):
        results[track_id] = estimate_speeds_for_trajectory(
            trajectory=traj,
            homography_matrix=homography_matrix,
            calibration_id=calibration_id,
            run_id=run_id,
            config=config,
        )
    return results
