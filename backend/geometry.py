"""Phase 05 / shared geometry utilities for coordinate calculations and spatial validation."""

from __future__ import annotations

import math


def compute_ground_point(
    x1: float,
    y1: float,
    x2: float,
    y2: float,
    method: str = "bottom_center",
) -> tuple[float, float]:
    """Compute the ground-contact point for a bounding box.

    Parameters:
        x1, y1, x2, y2: Bounding box pixel coordinates.
        method: Ground point computation method. Must be 'bottom_center'.

    Returns:
        (ground_x, ground_y) pixel coordinates.

    Raises:
        ValueError: If coordinates are malformed (e.g. x1 > x2, y1 > y2, NaN, inf)
                    or if an unsupported ground-point method is specified.
    """
    for name, val in (("x1", x1), ("y1", y1), ("x2", x2), ("y2", y2)):
        if math.isnan(val) or math.isinf(val):
            raise ValueError(f"Bounding box coordinate {name} must be finite, got {val}")

    if x1 > x2 or y1 > y2:
        raise ValueError(
            f"Malformed bounding box coordinates: x1={x1} > x2={x2} or y1={y1} > y2={y2}"
        )

    if method != "bottom_center":
        raise ValueError(
            f"Unsupported ground point method '{method}'. "
            "Traffic Vision requires 'bottom_center' as the default physical road point; "
            "bbox centre must not be used."
        )

    return float((x1 + x2) / 2.0), float(y2)
