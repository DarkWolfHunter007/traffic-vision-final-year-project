"""Phase 04 deterministic visualization and trajectory rendering.

Renders bounding boxes, consensus class labels, confidences, track IDs,
bottom-centre ground points, and motion trails onto image canvases.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
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

        # 1. Motion Trail
        if cfg.show_trails and cfg.trail_length > 0:
            past_points = [
                (p.ground_x, p.ground_y)
                for p in trajectory.points
                if p.frame_number <= frame_number
            ]
            if len(past_points) >= 2:
                recent_points = past_points[-cfg.trail_length :]
                pts_arr = np.array(
                    [[int(gx), int(gy)] for gx, gy in recent_points],
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
