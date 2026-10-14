"""Phase 04 trajectory aggregation, ground-point geometry, and continuity classification.

Strictly adheres to data contract in docs/data_dictionary.md and backend/database/schema.sql.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
import math
from typing import Any

from backend.geometry import compute_ground_point
from backend.tracking import resolve_track_class

STATUS_ACTIVE = "active"
STATUS_COMPLETE = "complete"
STATUS_FRAGMENTED = "fragmented"
STATUS_INVALID = "invalid"

VALID_TRAJECTORY_STATUSES: frozenset[str] = frozenset(
    {STATUS_ACTIVE, STATUS_COMPLETE, STATUS_FRAGMENTED, STATUS_INVALID}
)

LIFECYCLE_ACTIVE = "active"
LIFECYCLE_ENDED = "ended"
LIFECYCLE_UNKNOWN = "unknown"

CONTINUITY_CONTINUOUS = "continuous"
CONTINUITY_DISCONTINUOUS = "discontinuous"
CONTINUITY_INVALID = "invalid"

TERMINATION_BOUNDARY_EXIT = "boundary_exit"
TERMINATION_INTERIOR = "interior_termination"
TERMINATION_VIDEO_END = "video_end"
TERMINATION_INVALID = "invalid"



def is_near_boundary(
    x1: float,
    y1: float,
    x2: float,
    y2: float,
    width: int,
    height: int,
    margin_px: float = 20.0,
) -> bool:
    """Determine whether a bounding box intersects the outer margin of the video frame."""
    return (
        x1 <= margin_px
        or y1 <= margin_px
        or x2 >= (width - margin_px)
        or y2 >= (height - margin_px)
    )


@dataclass(frozen=True)
class TrajectoryPoint:
    """One immutable trajectory observation point on the camera road plane."""

    frame_number: int
    timestamp_s: float
    ground_x: float
    ground_y: float
    x1: float
    y1: float
    x2: float
    y2: float
    confidence: float | None = None
    vehicle_class: str | None = None


@dataclass
class Trajectory:
    """Ordered chronological trajectory history for one tracked vehicle."""

    run_id: str
    video_id: str
    track_id: int
    points: list[TrajectoryPoint]
    consensus_class: str
    status: str
    status_reason: str
    total_observations: int
    missing_frames_count: int
    duration_s: float
    is_incomplete: bool
    diagnostics: dict[str, Any] = field(default_factory=dict)
    lifecycle: str = LIFECYCLE_ENDED
    continuity: str = CONTINUITY_CONTINUOUS
    termination_reason: str | None = None

    @property
    def start_frame(self) -> int | None:
        return self.points[0].frame_number if self.points else None

    @property
    def end_frame(self) -> int | None:
        return self.points[-1].frame_number if self.points else None

    @property
    def start_timestamp_s(self) -> float | None:
        return self.points[0].timestamp_s if self.points else None

    @property
    def end_timestamp_s(self) -> float | None:
        return self.points[-1].timestamp_s if self.points else None

    def trail_points(self, max_length: int | None = None) -> list[tuple[float, float]]:
        """Return sequence of (ground_x, ground_y) points, optionally capped to max_length."""
        pts = [(p.ground_x, p.ground_y) for p in self.points]
        if max_length is not None and max_length > 0:
            return pts[-max_length:]
        return pts

    def point_at_frame(self, frame_number: int) -> TrajectoryPoint | None:
        """Find the observation at the specified frame number, if present."""
        for p in self.points:
            if p.frame_number == frame_number:
                return p
        return None


def _row_val(row: Any, key: str, default: Any = None) -> Any:
    try:
        val = row[key]
        return val if val is not None else default
    except (KeyError, IndexError, TypeError):
        return default


def build_trajectories(
    observations: Sequence[Mapping[str, Any]],
    video_width: int | None = None,
    video_height: int | None = None,
    last_video_frame: int | None = None,
    config: Mapping[str, Any] | None = None,
    frame_stride: int | None = None,
) -> dict[int, Trajectory]:
    """Group, chronologically order, and classify trajectory histories by track_id.

    Parameters:
        observations: Raw track observation mappings (e.g. from the 'tracks' table).
        video_width: Source video width in pixels, if known.
        video_height: Source video height in pixels, if known.
        last_video_frame: Highest frame index in the source video, if known.
        config: Optional configuration dictionary with 'trajectories' settings.
        frame_stride: Optional sampling cadence (stride); if None, inferred from config.

    Returns:
        Mapping of track_id to Trajectory instances.

    Raises:
        ValueError: If observations span multiple processing runs.
    """
    if not observations:
        return {}

    run_ids = {
        str(row["run_id"])
        for row in observations
        if "run_id" in row and row["run_id"] is not None
    }
    if len(run_ids) > 1:
        raise ValueError(
            f"build_trajectories received observations from multiple runs: {sorted(run_ids)}. "
            "Observations must be scoped to a single run_id."
        )

    traj_cfg = (config or {}).get("trajectories", {})
    ground_method = traj_cfg.get("ground_point_method", "bottom_center")
    max_gap_seconds = float(traj_cfg.get("max_gap_seconds", 1.0))
    min_track_length = int(traj_cfg.get("min_track_length_frames", 3))
    boundary_margin = float(traj_cfg.get("boundary_margin_px", 20.0))

    if frame_stride is None:
        frame_stride = int(
            traj_cfg.get("frame_stride")
            or (config or {}).get("detection", {}).get("frame_stride", 1)
        )
    if frame_stride < 1:
        frame_stride = 1

    # Group observations by track_id
    grouped_rows: dict[int, list[Any]] = defaultdict(list)
    for row in observations:
        track_id = int(row["track_id"])
        grouped_rows[track_id].append(row)

    trajectories: dict[int, Trajectory] = {}

    for track_id, rows in sorted(grouped_rows.items(), key=lambda item: item[0]):
        # Deterministic chronological sort by frame_number ASC, then timestamp_s ASC
        sorted_rows = sorted(
            rows,
            key=lambda r: (int(r["frame_number"]), float(r["timestamp_s"])),
        )

        first_row = sorted_rows[0]
        run_id = str(_row_val(first_row, "run_id", ""))
        video_id = str(_row_val(first_row, "video_id", ""))

        points: list[TrajectoryPoint] = []
        is_invalid = False
        invalid_reason = ""
        seen_frames: set[int] = set()
        prev_timestamp: float | None = None

        for row in sorted_rows:
            # Identity consistency check
            if str(_row_val(row, "run_id", "")) != run_id or str(_row_val(row, "video_id", "")) != video_id:
                is_invalid = True
                invalid_reason = "Inconsistent run_id or video_id within track group"
                break

            fn = int(row["frame_number"])
            if fn < 0:
                is_invalid = True
                invalid_reason = f"Negative frame_number {fn}"
                break
            if fn in seen_frames:
                is_invalid = True
                invalid_reason = f"Duplicate observation detected at frame_number {fn}"
                break
            seen_frames.add(fn)

            ts = _row_val(row, "timestamp_s")
            if ts is None or math.isnan(float(ts)) or math.isinf(float(ts)):
                is_invalid = True
                invalid_reason = f"Missing, NaN, or infinite timestamp_s at frame_number {fn}"
                break
            ts_float = float(ts)
            if ts_float < 0.0:
                is_invalid = True
                invalid_reason = f"Negative timestamp_s {ts_float}s at frame_number {fn}"
                break

            if prev_timestamp is not None and ts_float < prev_timestamp:
                is_invalid = True
                invalid_reason = (
                    f"Non-monotonic timestamp detected: {ts_float}s < {prev_timestamp}s at frame {fn}"
                )
                break
            prev_timestamp = ts_float

            try:
                x1 = float(row["x1"])
                y1 = float(row["y1"])
                x2 = float(row["x2"])
                y2 = float(row["y2"])
            except (ValueError, TypeError) as err:
                is_invalid = True
                invalid_reason = f"Non-numeric bounding box coordinates at frame {fn}: {err}"
                break

            for c_name, c_val in (("x1", x1), ("y1", y1), ("x2", x2), ("y2", y2)):
                if math.isnan(c_val) or math.isinf(c_val):
                    is_invalid = True
                    invalid_reason = f"Non-finite bounding box coordinate {c_name}={c_val} at frame {fn}"
                    break
            if is_invalid:
                break

            try:
                gx, gy = compute_ground_point(x1, y1, x2, y2, method=ground_method)
            except ValueError as err:
                is_invalid = True
                invalid_reason = f"Invalid bounding box at frame {fn}: {err}"
                break

            # Validate stored ground coordinates against computed ground point
            stored_gx = _row_val(row, "ground_x")
            stored_gy = _row_val(row, "ground_y")
            point_gx = gx
            point_gy = gy
            if stored_gx is not None and stored_gy is not None:
                try:
                    sgx_float = float(stored_gx)
                    sgy_float = float(stored_gy)
                    if math.isnan(sgx_float) or math.isinf(sgx_float) or math.isnan(sgy_float) or math.isinf(sgy_float):
                        is_invalid = True
                        invalid_reason = f"Non-finite stored ground coordinates at frame {fn}"
                        break
                    if abs(sgx_float - gx) > 1e-3 or abs(sgy_float - gy) > 1e-3:
                        is_invalid = True
                        invalid_reason = (
                            f"Corrupt stored ground coordinates at frame {fn}: "
                            f"stored=({sgx_float}, {sgy_float}) != computed=({gx}, {gy})"
                        )
                        break
                    point_gx = sgx_float
                    point_gy = sgy_float
                except (ValueError, TypeError):
                    is_invalid = True
                    invalid_reason = f"Malformed non-numeric stored ground coordinates at frame {fn}"
                    break

            conf = _row_val(row, "confidence")
            conf_float = float(conf) if conf is not None else None
            cls_name = str(_row_val(row, "vehicle_class")) if _row_val(row, "vehicle_class") is not None else None

            points.append(
                TrajectoryPoint(
                    frame_number=fn,
                    timestamp_s=ts_float,
                    ground_x=point_gx,
                    ground_y=point_gy,
                    x1=x1,
                    y1=y1,
                    x2=x2,
                    y2=y2,
                    confidence=conf_float,
                    vehicle_class=cls_name,
                )
            )

        # Compute consensus vehicle class using Phase 03 voting
        consensus_class = resolve_track_class(points) if points else "unknown"

        # Calculate stride-aware gaps and missing frame counts
        total_missing_frames = 0
        raw_missing_frames = 0
        internal_gaps: list[dict[str, Any]] = []
        for i in range(len(points) - 1):
            fn_gap = points[i + 1].frame_number - points[i].frame_number
            if fn_gap > 1:
                raw_missing_frames += (fn_gap - 1)
                expected_steps = round(fn_gap / frame_stride)
                missing_samples = max(0, expected_steps - 1)
                total_missing_frames += missing_samples

            time_gap = points[i + 1].timestamp_s - points[i].timestamp_s
            if time_gap > max_gap_seconds:
                internal_gaps.append(
                    {
                        "from_frame": points[i].frame_number,
                        "to_frame": points[i + 1].frame_number,
                        "gap_seconds": round(time_gap, 4),
                    }
                )

        duration_s = (points[-1].timestamp_s - points[0].timestamp_s) if len(points) > 1 else 0.0

        # Classify continuity status, lifecycle, and termination reason
        exited_boundary: bool | None = None
        if video_width is not None and video_height is not None and points:
            last_pt = points[-1]
            exited_boundary = is_near_boundary(
                last_pt.x1,
                last_pt.y1,
                last_pt.x2,
                last_pt.y2,
                video_width,
                video_height,
                boundary_margin,
            )

        if is_invalid or not points:
            status = STATUS_INVALID
            status_reason = invalid_reason or "Empty or malformed trajectory points"
            lifecycle = LIFECYCLE_ENDED
            continuity = CONTINUITY_INVALID
            termination_reason = TERMINATION_INVALID
        elif internal_gaps:
            status = STATUS_FRAGMENTED
            continuity = CONTINUITY_DISCONTINUOUS
            status_reason = (
                f"Observation gap exceeded threshold ({len(internal_gaps)} gap(s) > {max_gap_seconds}s)"
            )
            if last_video_frame is not None and points[-1].frame_number >= last_video_frame:
                lifecycle = LIFECYCLE_ACTIVE
                termination_reason = TERMINATION_VIDEO_END
            else:
                lifecycle = LIFECYCLE_ENDED
                if exited_boundary is True:
                    termination_reason = TERMINATION_BOUNDARY_EXIT
                elif exited_boundary is False:
                    termination_reason = TERMINATION_INTERIOR
                else:
                    termination_reason = None
        elif last_video_frame is not None and points[-1].frame_number >= last_video_frame:
            status = STATUS_ACTIVE
            continuity = CONTINUITY_CONTINUOUS
            lifecycle = LIFECYCLE_ACTIVE
            termination_reason = TERMINATION_VIDEO_END
            status_reason = f"Track remains active on final video frame ({points[-1].frame_number})"
        else:
            lifecycle = LIFECYCLE_ENDED
            continuity = CONTINUITY_CONTINUOUS
            if exited_boundary is False:
                # Ended in the interior of the scene without reaching the frame boundary
                status = STATUS_FRAGMENTED
                termination_reason = TERMINATION_INTERIOR
                status_reason = "Track terminated in scene interior without reaching frame boundary"
            else:
                status = STATUS_COMPLETE
                termination_reason = TERMINATION_BOUNDARY_EXIT if exited_boundary is True else None
                status_reason = "Track completed normally"

        is_incomplete = (
            status in (STATUS_ACTIVE, STATUS_FRAGMENTED, STATUS_INVALID)
            or len(points) < min_track_length
        )

        diagnostics: dict[str, Any] = {
            "internal_gaps": internal_gaps,
            "total_missing_frames": total_missing_frames,
            "raw_missing_frames": raw_missing_frames,
            "frame_stride": frame_stride,
            "exited_boundary": exited_boundary,
            "points_count": len(points),
            "is_short_track": len(points) < min_track_length,
            "suspected_fragmentation": status == STATUS_FRAGMENTED,
            "lifecycle": lifecycle,
            "continuity": continuity,
            "termination_reason": termination_reason,
            "uncertainty_note": (
                "Temporal gaps and interior disappearance indicate possible occlusion or detector loss; "
                "physical vehicle fragmentation cannot be proved without manual ground truth."
            ),
        }

        trajectories[track_id] = Trajectory(
            run_id=run_id,
            video_id=video_id,
            track_id=track_id,
            points=points,
            consensus_class=consensus_class,
            status=status,
            status_reason=status_reason,
            total_observations=len(points),
            missing_frames_count=total_missing_frames,
            duration_s=round(duration_s, 6),
            is_incomplete=is_incomplete,
            diagnostics=diagnostics,
            lifecycle=lifecycle,
            continuity=continuity,
            termination_reason=termination_reason,
        )

    return trajectories
