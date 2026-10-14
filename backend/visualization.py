"""Phase 04 deterministic visualization and trajectory rendering.

Renders bounding boxes, consensus class labels, confidences, track IDs,
bottom-centre ground points, and motion trails onto image canvases.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
import json
import math
from typing import Any

import cv2
import numpy as np

from backend.trajectories import Trajectory, TrajectoryPoint

# Deterministic 20-colour palette in RGB
COLOR_PALETTE: list[tuple[int, int, int]] = [
    (235, 64, 52),    # Red
    (235, 131, 52),   # Orange
    (235, 198, 52),   # Yellow
    (140, 235, 52),   # Lime
    (52, 235, 116),   # Green
    (52, 235, 222),   # Cyan
    (52, 137, 235),   # Blue
    (88, 52, 235),    # Indigo
    (192, 52, 235),   # Violet
    (235, 52, 174),   # Magenta
    (245, 120, 120),  # Light red
    (245, 180, 120),  # Light orange
    (245, 230, 120),  # Light yellow
    (170, 245, 120),  # Light lime
    (120, 245, 180),  # Light green
    (120, 245, 245),  # Light cyan
    (120, 180, 245),  # Light blue
    (150, 120, 245),  # Light indigo
    (220, 120, 245),  # Light violet
    (245, 120, 200),  # Light pink
]


def get_track_color(track_id: int) -> tuple[int, int, int]:
    """Return a deterministic RGB color for a given track_id."""
    return COLOR_PALETTE[abs(int(track_id)) % len(COLOR_PALETTE)]


@dataclass(frozen=True)
class VisualizationConfig:
    """Configurable rendering toggles and styling parameters."""

    show_boxes: bool = True
    show_labels: bool = True
    show_confidences: bool = True
    show_ids: bool = True
    show_trails: bool = True
    trail_length: int = 30
    trail_thickness: int = 2
    box_thickness: int = 2
    font_scale: float = 0.5
    draw_ground_point: bool = True
    ground_point_radius: int = 4
    max_trail_gap_seconds: float = 1.0
    max_trail_gap_frames: int | None = None

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> VisualizationConfig:
        if not data:
            return cls()
        return cls(
            show_boxes=bool(data.get("show_boxes", True)),
            show_labels=bool(data.get("show_labels", True)),
            show_confidences=bool(data.get("show_confidences", True)),
            show_ids=bool(data.get("show_ids", True)),
            show_trails=bool(data.get("show_trails", True)),
            trail_length=int(data.get("trail_length", 30)),
            trail_thickness=int(data.get("trail_thickness", 2)),
            box_thickness=int(data.get("box_thickness", 2)),
            font_scale=float(data.get("font_scale", 0.5)),
            draw_ground_point=bool(data.get("draw_ground_point", True)),
            ground_point_radius=int(data.get("ground_point_radius", 4)),
            max_trail_gap_seconds=float(data.get("max_trail_gap_seconds", 1.0)),
            max_trail_gap_frames=int(data["max_trail_gap_frames"]) if data.get("max_trail_gap_frames") is not None else None,
        )


def render_frame_annotations(
    image: np.ndarray,
    frame_number: int,
    tracks: Sequence[tuple[Trajectory, TrajectoryPoint]],
    config: VisualizationConfig | None = None,
) -> np.ndarray:
    """Render overlays for active tracks onto a copy of the input image.

    Parameters:
        image: Source image array (H, W, 3) in RGB or BGR.
        frame_number: Frame index being rendered.
        tracks: Sequence of (Trajectory, TrajectoryPoint) active on this frame.
        config: Rendering configuration toggles.

    Returns:
        Annotated image array of the same shape and type.
    """
    if not isinstance(image, np.ndarray):
        raise TypeError("image must be a numpy.ndarray")
    if image.size == 0 or image.ndim not in (2, 3):
        raise ValueError(f"Invalid image array with shape {image.shape}")

    cfg = config or VisualizationConfig()
    canvas = image.copy()
    img_h, img_w = canvas.shape[:2]

    # Render each track observation
    for trajectory, point in tracks:
        color = get_track_color(trajectory.track_id)

        # 1. Motion Trail (broken into contiguous segments across observation gaps)
        if cfg.show_trails and cfg.trail_length > 0:
            past_obs = [
                p
                for p in trajectory.points
                if p.frame_number <= frame_number
            ]
            if len(past_obs) >= 2:
                recent_obs = past_obs[-cfg.trail_length :]
                segments: list[list[tuple[float, float]]] = []
                current_segment: list[tuple[float, float]] = [
                    (recent_obs[0].ground_x, recent_obs[0].ground_y)
                ]
                for i in range(len(recent_obs) - 1):
                    p_curr = recent_obs[i]
                    p_next = recent_obs[i + 1]
                    time_gap = p_next.timestamp_s - p_curr.timestamp_s
                    frame_gap = p_next.frame_number - p_curr.frame_number

                    is_gap = False
                    if cfg.max_trail_gap_seconds is not None and time_gap > cfg.max_trail_gap_seconds:
                        is_gap = True
                    if cfg.max_trail_gap_frames is not None and frame_gap > cfg.max_trail_gap_frames:
                        is_gap = True

                    if is_gap:
                        if len(current_segment) >= 2:
                            segments.append(current_segment)
                        current_segment = [(p_next.ground_x, p_next.ground_y)]
                    else:
                        current_segment.append((p_next.ground_x, p_next.ground_y))

                if len(current_segment) >= 2:
                    segments.append(current_segment)

                for seg in segments:
                    pts_arr = np.array(
                        [[int(round(gx)), int(round(gy))] for gx, gy in seg],
                        dtype=np.int32,
                    ).reshape((-1, 1, 2))
                    cv2.polylines(
                        canvas,
                        [pts_arr],
                        isClosed=False,
                        color=color,
                        thickness=cfg.trail_thickness,
                        lineType=cv2.LINE_AA,
                    )

        # 2. Bounding Box
        x1, y1 = int(round(point.x1)), int(round(point.y1))
        x2, y2 = int(round(point.x2)), int(round(point.y2))

        # Coordinate sanity check
        if x1 > x2 or y1 > y2 or any(math.isnan(c) for c in (point.x1, point.y1, point.x2, point.y2)):
            continue

        if cfg.show_boxes:
            cv2.rectangle(
                canvas,
                (x1, y1),
                (x2, y2),
                color=color,
                thickness=cfg.box_thickness,
                lineType=cv2.LINE_AA,
            )

        # 3. Ground Point Marker
        if cfg.draw_ground_point:
            gx, gy = int(round(point.ground_x)), int(round(point.ground_y))
            if 0 <= gx < img_w and 0 <= gy < img_h:
                cv2.circle(
                    canvas,
                    (gx, gy),
                    radius=cfg.ground_point_radius,
                    color=color,
                    thickness=-1,
                    lineType=cv2.LINE_AA,
                )

        # 4. Text Label
        label_parts: list[str] = []
        if cfg.show_ids:
            label_parts.append(f"#{trajectory.track_id}")
        if cfg.show_labels:
            cls_name = trajectory.consensus_class
            if cls_name == "unknown" and point.vehicle_class:
                cls_name = point.vehicle_class
            label_parts.append(cls_name)
        if cfg.show_confidences and point.confidence is not None:
            label_parts.append(f"{point.confidence:.2f}")

        if label_parts:
            label_text = " ".join(label_parts)
            (text_w, text_h), baseline = cv2.getTextSize(
                label_text,
                cv2.FONT_HERSHEY_SIMPLEX,
                cfg.font_scale,
                1,
            )
            # Label background position (just above box, or just inside top if at ceiling)
            bg_y1 = max(0, y1 - text_h - 4)
            bg_y2 = bg_y1 + text_h + 4
            bg_x1 = max(0, min(x1, img_w - text_w - 6))
            bg_x2 = bg_x1 + text_w + 6

            # Draw filled dark rectangle behind label for contrast
            cv2.rectangle(
                canvas,
                (bg_x1, bg_y1),
                (bg_x2, bg_y2),
                color=(20, 20, 20),
                thickness=-1,
            )
            # Draw coloured border on label tag
            cv2.rectangle(
                canvas,
                (bg_x1, bg_y1),
                (bg_x2, bg_y2),
                color=color,
                thickness=1,
            )
            # Put text in white
            cv2.putText(
                canvas,
                label_text,
                (bg_x1 + 3, bg_y2 - 3),
                cv2.FONT_HERSHEY_SIMPLEX,
                cfg.font_scale,
                (255, 255, 255),
                1,
                lineType=cv2.LINE_AA,
            )

    return canvas


ZONE_TYPE_COLORS: dict[str, tuple[int, int, int]] = {
    "entry": (52, 235, 116),    # Green
    "exit": (235, 64, 52),     # Red
    "roi": (52, 235, 222),     # Cyan
    "queue": (192, 52, 235),   # Violet
}


def render_geometry_overlay(
    image: np.ndarray,
    lines: Sequence[Any],
    zones: Sequence[Any],
) -> np.ndarray:
    """Render counting lines and polygonal zones onto an image canvas.

    Parameters:
        image: Source image array (H, W, 3) in RGB or BGR.
        lines: Sequence of counting-line dicts or sqlite3.Row mappings.
        zones: Sequence of zone dicts or sqlite3.Row mappings.

    Returns:
        New image array with rendered geometry overlays.
    """
    canvas = image.copy()
    overlay = canvas.copy()

    # 1. Render zones with semi-transparent fill and solid boundary
    for zone in zones:
        z_dict = dict(zone) if not isinstance(zone, dict) else zone
        geom = z_dict["geometry_json"]
        if isinstance(geom, str):
            geom = json.loads(geom)
        vertices = geom.get("vertices", [])
        if len(vertices) < 3:
            continue
        pts = np.array(vertices, dtype=np.int32).reshape((-1, 1, 2))
        zone_type = str(z_dict.get("zone_type", "roi"))
        color = ZONE_TYPE_COLORS.get(zone_type, (200, 200, 200))

        # Fill on overlay
        cv2.fillPoly(overlay, [pts], color=color)
        # Outline on canvas
        cv2.polylines(canvas, [pts], isClosed=True, color=color, thickness=2, lineType=cv2.LINE_AA)

        # Zone label
        name = z_dict.get("name") or z_dict.get("zone_id", "zone")
        label = f"{name} ({zone_type})"
        if z_dict.get("approach"):
            label += f" [{z_dict['approach']}]"
        first_pt = (int(vertices[0][0]), max(15, int(vertices[0][1]) - 5))
        cv2.putText(
            canvas,
            label,
            first_pt,
            cv2.FONT_HERSHEY_SIMPLEX,
            0.45,
            (255, 255, 255),
            1,
            lineType=cv2.LINE_AA,
        )

    # Blend semi-transparent filled zones
    cv2.addWeighted(overlay, 0.25, canvas, 0.75, 0, canvas)

    # 2. Render counting lines with arrows for unidirectional lines
    for line in lines:
        l_dict = dict(line) if not isinstance(line, dict) else line
        geom = l_dict["geometry_json"]
        if isinstance(geom, str):
            geom = json.loads(geom)
        endpoints = geom.get("endpoints", [])
        if len(endpoints) != 2:
            continue
        p1 = (int(round(endpoints[0][0])), int(round(endpoints[0][1])))
        p2 = (int(round(endpoints[1][0])), int(round(endpoints[1][1])))
        color = (235, 198, 52)  # Gold/Yellow

        # Line stroke and endpoint dots
        cv2.line(canvas, p1, p2, color=color, thickness=3, lineType=cv2.LINE_AA)
        cv2.circle(canvas, p1, 4, (255, 255, 255), -1, lineType=cv2.LINE_AA)
        cv2.circle(canvas, p2, 4, (255, 255, 255), -1, lineType=cv2.LINE_AA)

        # Direction vector arrow if unidirectional
        dir_vec = geom.get("direction_vector")
        if dir_vec and len(dir_vec) == 2:
            dx, dy = float(dir_vec[0]), float(dir_vec[1])
            mag = math.hypot(dx, dy)
            if mag > 1e-6:
                mid_x = (p1[0] + p2[0]) / 2.0
                mid_y = (p1[1] + p2[1]) / 2.0
                arrow_len = 25.0
                ax = int(round(mid_x + (dx / mag) * arrow_len))
                ay = int(round(mid_y + (dy / mag) * arrow_len))
                cv2.arrowedLine(
                    canvas,
                    (int(round(mid_x)), int(round(mid_y))),
                    (ax, ay),
                    color=(235, 131, 52),  # Orange arrow
                    thickness=2,
                    tipLength=0.35,
                    line_type=cv2.LINE_AA,
                )

        # Line label
        name = l_dict.get("name") or l_dict.get("line_id", "line")
        label = f"{name}"
        if l_dict.get("approach"):
            label += f" [{l_dict['approach']}]"
        mid_pt = (int((p1[0] + p2[0]) / 2) + 5, max(15, int((p1[1] + p2[1]) / 2) - 5))
        cv2.putText(
            canvas,
            label,
            mid_pt,
            cv2.FONT_HERSHEY_SIMPLEX,
            0.45,
            (255, 255, 255),
            1,
            lineType=cv2.LINE_AA,
        )

    return canvas

