"""Phase 05 / shared geometry utilities for coordinate calculations and spatial validation."""

from __future__ import annotations

from collections.abc import Sequence
import hashlib
import json
import math
from typing import Any

VALID_ZONE_TYPES: frozenset[str] = frozenset({"entry", "exit", "roi", "queue"})


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


def polygon_area(vertices: Sequence[Sequence[float]]) -> float:
    """Calculate the absolute planar area of a 2D polygon using the Shoelace formula."""
    n = len(vertices)
    if n < 3:
        return 0.0
    area = 0.0
    for i in range(n):
        j = (i + 1) % n
        area += float(vertices[i][0]) * float(vertices[j][1]) - float(vertices[j][0]) * float(vertices[i][1])
    return abs(area) * 0.5


def _ccw(a: Sequence[float], b: Sequence[float], c: Sequence[float]) -> float:
    """Signed cross product of (b - a) and (c - a)."""
    return (float(b[0]) - float(a[0])) * (float(c[1]) - float(a[1])) - (float(b[1]) - float(a[1])) * (float(c[0]) - float(a[0]))


def _on_segment(p: Sequence[float], a: Sequence[float], b: Sequence[float], eps: float = 1e-9) -> bool:
    """Check if point p lies within the bounding box of segment [a, b]."""
    return (
        min(float(a[0]), float(b[0])) - eps <= float(p[0]) <= max(float(a[0]), float(b[0])) + eps
        and min(float(a[1]), float(b[1])) - eps <= float(p[1]) <= max(float(a[1]), float(b[1])) + eps
    )


def segments_intersect(
    a: Sequence[float],
    b: Sequence[float],
    c: Sequence[float],
    d: Sequence[float],
    eps: float = 1e-9,
) -> bool:
    """Determine whether 2D line segment [a, b] intersects segment [c, d]."""
    d1 = _ccw(a, b, c)
    d2 = _ccw(a, b, d)
    d3 = _ccw(c, d, a)
    d4 = _ccw(c, d, b)

    if ((d1 > eps and d2 < -eps) or (d1 < -eps and d2 > eps)) and (
        (d3 > eps and d4 < -eps) or (d3 < -eps and d4 > eps)
    ):
        return True

    if abs(d1) <= eps and _on_segment(c, a, b, eps):
        return True
    if abs(d2) <= eps and _on_segment(d, a, b, eps):
        return True
    if abs(d3) <= eps and _on_segment(a, c, d, eps):
        return True
    if abs(d4) <= eps and _on_segment(b, c, d, eps):
        return True

    return False


def is_polygon_self_intersecting(vertices: Sequence[Sequence[float]], eps: float = 1e-9) -> bool:
    """Check if any non-adjacent edges of a closed polygon intersect."""
    n = len(vertices)
    if n < 4:
        return False
    for i in range(n):
        for j in range(i + 1, n):
            # Exclude adjacent edges (sharing an endpoint)
            if j == i + 1 or (i == 0 and j == n - 1):
                continue
            if segments_intersect(
                vertices[i],
                vertices[(i + 1) % n],
                vertices[j],
                vertices[(j + 1) % n],
                eps=eps,
            ):
                return True
    return False


def validate_polygon(
    vertices: Sequence[Sequence[float]],
    frame_width: float | None = None,
    frame_height: float | None = None,
) -> list[tuple[float, float]]:
    """Validate a polygonal region of interest or zone.

    Rules:
        - At least 3 distinct vertices.
        - All coordinates finite and within frame bounds [0, width] x [0, height].
        - Non-zero area (rejects collinear vertices).
        - No self-intersecting or self-touching edges.

    Returns:
        Normalized list of (x, y) float tuples (without redundant closing point).
    """
    if not isinstance(vertices, Sequence) or len(vertices) < 3:
        raise ValueError("Polygon must have at least 3 distinct vertices")

    pts: list[tuple[float, float]] = []
    for idx, pt in enumerate(vertices):
        if not isinstance(pt, Sequence) or len(pt) != 2:
            raise ValueError(f"Polygon vertex {idx} must have exactly 2 coordinates [x, y]")
        x, y = float(pt[0]), float(pt[1])
        if math.isnan(x) or math.isinf(x) or math.isnan(y) or math.isinf(y):
            raise ValueError(f"Polygon vertex {idx} coordinates must be finite, got ({x}, {y})")
        if frame_width is not None and frame_height is not None:
            if not (0.0 <= x <= frame_width and 0.0 <= y <= frame_height):
                raise ValueError(
                    f"Polygon coordinate ({x}, {y}) is outside video frame bounds "
                    f"[0, {frame_width}] x [0, {frame_height}]"
                )
        pts.append((x, y))

    # Strip redundant closing vertex if explicitly closed
    if len(pts) >= 4 and abs(pts[0][0] - pts[-1][0]) <= 1e-9 and abs(pts[0][1] - pts[-1][1]) <= 1e-9:
        pts = pts[:-1]

    distinct_pts = {(p[0], p[1]) for p in pts}
    if len(distinct_pts) < 3:
        raise ValueError("Polygon must have at least 3 distinct vertices")
    if len(distinct_pts) < len(pts):
        raise ValueError("Polygon contains duplicate vertices")

    if is_polygon_self_intersecting(pts):
        raise ValueError("Polygon is self-intersecting")

    area = polygon_area(pts)
    if area <= 1e-6:
        raise ValueError("Polygon has zero area")

    return pts


def validate_counting_line(
    endpoints: Sequence[Sequence[float]],
    direction_vector: Sequence[float] | None = None,
    bidirectional: bool = False,
    frame_width: float | None = None,
    frame_height: float | None = None,
) -> tuple[list[tuple[float, float]], tuple[float, float] | None]:
    """Validate counting-line geometry and direction constraints.

    Rules:
        - Exactly 2 distinct endpoints (coincident endpoints rejected).
        - All coordinates finite and within frame bounds [0, width] x [0, height].
        - Bidirectional line: direction_vector must be null.
        - Unidirectional line: direction_vector must be non-zero [dx, dy].

    Returns:
        (endpoints, direction_vector) where direction_vector is None for bidirectional lines.
    """
    if endpoints is None or not isinstance(endpoints, Sequence) or len(endpoints) != 2:
        raise ValueError("Counting line must have exactly 2 distinct endpoints")

    p1, p2 = endpoints[0], endpoints[1]
    if not isinstance(p1, Sequence) or len(p1) != 2 or not isinstance(p2, Sequence) or len(p2) != 2:
        raise ValueError("Counting line endpoints must each have exactly 2 coordinates (x, y)")

    x1, y1 = float(p1[0]), float(p1[1])
    x2, y2 = float(p2[0]), float(p2[1])

    for name, val in (("x1", x1), ("y1", y1), ("x2", x2), ("y2", y2)):
        if math.isnan(val) or math.isinf(val):
            raise ValueError(f"Counting line coordinate {name} must be finite, got {val}")

    if frame_width is not None and frame_height is not None:
        for name, x, y in (("p1", x1, y1), ("p2", x2, y2)):
            if not (0.0 <= x <= frame_width and 0.0 <= y <= frame_height):
                raise ValueError(
                    f"Counting line {name} coordinate ({x}, {y}) is outside video frame bounds "
                    f"[0, {frame_width}] x [0, {frame_height}]"
                )

    if (x1 - x2) ** 2 + (y1 - y2) ** 2 <= 1e-12:
        raise ValueError("Counting line endpoints must be distinct (coincident endpoints rejected)")

    norm_endpoints = [(x1, y1), (x2, y2)]

    if bidirectional:
        if direction_vector is not None:
            raise ValueError(
                "Bidirectional counting line must not specify a direction vector (direction_vector must be null)"
            )
        norm_dir: tuple[float, float] | None = None
    else:
        if direction_vector is None or not isinstance(direction_vector, Sequence) or len(direction_vector) != 2:
            raise ValueError("Unidirectional counting line requires a non-zero direction_vector")
        dx, dy = float(direction_vector[0]), float(direction_vector[1])
        if math.isnan(dx) or math.isinf(dx) or math.isnan(dy) or math.isinf(dy):
            raise ValueError(f"Direction vector coordinates must be finite, got ({dx}, {dy})")
        if dx ** 2 + dy ** 2 <= 1e-12:
            raise ValueError("Direction vector must be non-zero")
        norm_dir = (dx, dy)

    return norm_endpoints, norm_dir


def validate_zone(
    vertices: Sequence[Sequence[float]],
    zone_type: str,
    approach: str | None = None,
    declared_approaches: Sequence[str] | set[str] | None = None,
    frame_width: float | None = None,
    frame_height: float | None = None,
) -> tuple[list[tuple[float, float]], str, str | None]:
    """Validate zone parameters and approach declarations."""
    if zone_type not in VALID_ZONE_TYPES:
        raise ValueError(
            f"Invalid zone_type '{zone_type}'. Must be one of: {sorted(VALID_ZONE_TYPES)}"
        )

    decl_set = set(declared_approaches) if declared_approaches is not None else None

    if zone_type in ("entry", "exit"):
        if not approach:
            raise ValueError(
                f"{zone_type} zone must be assigned to a declared approach, got approach='{approach}'"
            )
        if decl_set is not None and approach not in decl_set:
            raise ValueError(
                f"{zone_type} zone approach '{approach}' is not declared in approaches: {sorted(decl_set)}"
            )
    else:
        if approach is not None and decl_set is not None and approach not in decl_set:
            raise ValueError(
                f"{zone_type} zone approach '{approach}' is not declared in approaches: {sorted(decl_set)}"
            )

    norm_vertices = validate_polygon(vertices, frame_width=frame_width, frame_height=frame_height)
    return norm_vertices, zone_type, approach


def compute_geometry_sha256(
    geometry: dict[str, Any] | str,
    approach: str | None,
    name: str,
) -> str:
    """Compute deterministic SHA-256 over canonical sorted-key JSON of geometry + approach + name."""
    if isinstance(geometry, str):
        geometry_obj = json.loads(geometry)
    else:
        geometry_obj = geometry

    payload = {
        "approach": approach,
        "geometry": geometry_obj,
        "name": name,
    }
    canonical_str = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonical_str.encode("utf-8")).hexdigest()


def compute_config_version(geometry_sha256: str) -> str:
    """Derive 12-character immutable config_version from geometry_sha256."""
    return geometry_sha256[:12]


def point_line_cross_product(
    point: Sequence[float],
    line_start: Sequence[float],
    line_end: Sequence[float],
) -> float:
    """Compute the 2D cross product of (line_end - line_start) and (point - line_start).

    Formula:
        (x2 - x1) * (y - y1) - (y2 - y1) * (x - x1)

    Returns:
        float: > 0 for left side, < 0 for right side, == 0 on the line.
    """
    x1, y1 = float(line_start[0]), float(line_start[1])
    x2, y2 = float(line_end[0]), float(line_end[1])
    px, py = float(point[0]), float(point[1])
    return (x2 - x1) * (py - y1) - (y2 - y1) * (px - x1)


def point_side_of_line(
    point: Sequence[float],
    line_start: Sequence[float],
    line_end: Sequence[float],
    eps: float = 1e-9,
) -> int:
    """Determine which side of a directed line a 2D point lies on.

    Returns:
        1: Point lies on the positive / left side of the directed line.
       -1: Point lies on the negative / right side of the directed line.
        0: Point lies collinear with the line (within eps tolerance).
    """
    cp = point_line_cross_product(point, line_start, line_end)
    if cp > eps:
        return 1
    elif cp < -eps:
        return -1
    return 0


# Ergonomic aliases
side_of_line = point_side_of_line
point_line_side = point_side_of_line

