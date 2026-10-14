"""Phase 07 planar homography camera calibration and held-out error diagnostics.

Provides pure mathematical primitives for:
- Reference point validation, duplicate detection, and collinearity checking.
- Planar homography estimation H (image -> world) and H_inv (world -> image).
- Projection between image pixels and ground world coordinates (metres).
- Independent held-out test evaluation and reprojection error diagnostics.
- Acceptance decision against configurable error thresholds.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
import json
import math
from typing import Any
from uuid import uuid4

import cv2
import numpy as np


@dataclass(frozen=True)
class CalibrationPoint:
    """Single reference point correspondence between image and road ground plane."""

    image_x: float
    image_y: float
    world_x: float
    world_y: float
    role: str = "fit"  # 'fit' or 'held_out'
    calibration_point_id: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "image_x": float(self.image_x),
            "image_y": float(self.image_y),
            "world_x": float(self.world_x),
            "world_y": float(self.world_y),
            "role": str(self.role),
            "calibration_point_id": self.calibration_point_id,
        }


@dataclass
class CalibrationResult:
    """Full diagnostic result of a camera calibration run."""

    calibration_id: str
    method: str
    homography_matrix: list[list[float]]
    inverse_homography_matrix: list[list[float]]
    point_count: int
    held_out_point_count: int
    reprojection_error_m_mean: float
    reprojection_error_m_max: float
    fit_reprojection_error_m_mean: float
    fit_reprojection_error_m_max: float
    accepted: bool
    distortion_checked: bool
    flat_road_assumption: bool
    points: list[dict[str, Any]]
    parameters: dict[str, Any]
    parameters_json: str


def are_points_collinear(points_2d: Sequence[tuple[float, float]], eps: float = 1e-4) -> bool:
    """Check if all given 2D points lie on a single 1D line within tolerance.

    Uses Singular Value Decomposition (SVD) of mean-centered 2D coordinates.
    If the second singular value is near zero compared to the first, all points
    are collinear.
    """
    if len(points_2d) < 3:
        return True
    arr = np.array(points_2d, dtype=np.float64)
    centered = arr - np.mean(arr, axis=0)
    _, s, _ = np.linalg.svd(centered)
    if len(s) < 2:
        return True
    # If the smaller singular value is negligible relative to the span, it's a line
    return bool(s[1] < eps * (s[0] + 1e-9) or s[1] < 1e-7)


def three_points_collinear(
    p1: tuple[float, float],
    p2: tuple[float, float],
    p3: tuple[float, float],
    eps: float = 1e-4,
) -> bool:
    """Check if three 2D points are collinear using normalized cross product."""
    dx1 = p2[0] - p1[0]
    dy1 = p2[1] - p1[1]
    dx2 = p3[0] - p1[0]
    dy2 = p3[1] - p1[1]
    cross = abs(dx1 * dy2 - dy1 * dx2)
    d1 = math.hypot(dx1, dy1)
    d2 = math.hypot(dx2, dy2)
    if d1 < 1e-9 or d2 < 1e-9:
        return True
    return bool((cross / (d1 * d2)) < eps)


def is_collinear_or_degenerate(
    points: Sequence[CalibrationPoint | dict[str, Any]],
    eps: float = 1e-4,
) -> bool:
    """Detect if reference points form a collinear or rank-deficient configuration.

    Checks both image-space coordinates (u, v) and world-space coordinates (X, Y).
    """
    if len(points) < 4:
        return True

    img_pts = [
        (float(p.image_x if isinstance(p, CalibrationPoint) else p["image_x"]),
         float(p.image_y if isinstance(p, CalibrationPoint) else p["image_y"]))
        for p in points
    ]
    world_pts = [
        (float(p.world_x if isinstance(p, CalibrationPoint) else p["world_x"]),
         float(p.world_y if isinstance(p, CalibrationPoint) else p["world_y"]))
        for p in points
    ]

    # Check overall collinearity
    if are_points_collinear(img_pts, eps=eps) or are_points_collinear(world_pts, eps=eps):
        return True

    # If exactly 4 points, check if any 3 of the 4 are collinear
    if len(points) == 4:
        indices = [(0, 1, 2), (0, 1, 3), (0, 2, 3), (1, 2, 3)]
        for i, j, k in indices:
            if three_points_collinear(img_pts[i], img_pts[j], img_pts[k], eps=eps):
                return True
            if three_points_collinear(world_pts[i], world_pts[j], world_pts[k], eps=eps):
                return True

    return False


def validate_calibration_points(
    points: Sequence[dict[str, Any] | CalibrationPoint],
    min_points: int = 6,
    held_out_count: int = 2,
) -> tuple[list[CalibrationPoint], list[CalibrationPoint]]:
    """Validate reference point correspondences and partition into fit and held-out sets.

    Parameters:
        points: Sequence of point correspondences (dict or CalibrationPoint).
        min_points: Minimum number of total reference points required (must be >= 6).
        held_out_count: Number of validation points held out from homography fitting.

    Returns:
        tuple of (fit_points, held_out_points).

    Raises:
        ValueError: If point count is insufficient, points contain NaN/inf, duplicates exist,
                    or point configuration is collinear/degenerate.
    """
    if len(points) < min_points:
        raise ValueError(
            f"Insufficient calibration points: at least {min_points} points are required, "
            f"got {len(points)}. Four points with no independent error check are strictly insufficient."
        )

    parsed: list[CalibrationPoint] = []
    seen_img: set[tuple[float, float]] = set()
    seen_world: set[tuple[float, float]] = set()

    for idx, p in enumerate(points):
        if isinstance(p, CalibrationPoint):
            img_x, img_y = float(p.image_x), float(p.image_y)
            w_x, w_y = float(p.world_x), float(p.world_y)
            role = p.role
            pt_id = p.calibration_point_id
        elif isinstance(p, Mapping):
            if "image_x" not in p or "image_y" not in p or "world_x" not in p or "world_y" not in p:
                raise ValueError(
                    f"Point at index {idx} is missing required coordinates "
                    f"('image_x', 'image_y', 'world_x', 'world_y')"
                )
            img_x = float(p["image_x"])
            img_y = float(p["image_y"])
            w_x = float(p["world_x"])
            w_y = float(p["world_y"])
            role = str(p.get("role", "")).strip().lower()
            pt_id = p.get("calibration_point_id")
        else:
            raise ValueError(f"Invalid point format at index {idx}: expected mapping or CalibrationPoint")

        for name, val in [("image_x", img_x), ("image_y", img_y), ("world_x", w_x), ("world_y", w_y)]:
            if not math.isfinite(val):
                raise ValueError(f"Point {idx} coordinate {name} must be finite, got {val}")

        # Duplicate check within tolerance
        img_key = (round(img_x, 3), round(img_y, 3))
        world_key = (round(w_x, 3), round(w_y, 3))
        if img_key in seen_img:
            raise ValueError(f"Duplicate image coordinate detected at index {idx}: ({img_x}, {img_y})")
        if world_key in seen_world:
            raise ValueError(f"Duplicate world coordinate detected at index {idx}: ({w_x}, {w_y})")
        seen_img.add(img_key)
        seen_world.add(world_key)

        parsed.append(
            CalibrationPoint(
                image_x=img_x,
                image_y=img_y,
                world_x=w_x,
                world_y=w_y,
                role=role if role in {"fit", "held_out"} else "unassigned",
                calibration_point_id=pt_id,
            )
        )

    # Partition based on roles or hold out the last held_out_count points
    has_explicit_roles = all(p.role in {"fit", "held_out"} for p in parsed)
    if has_explicit_roles:
        fit_points = [p for p in parsed if p.role == "fit"]
        held_out_points = [p for p in parsed if p.role == "held_out"]
    else:
        # Assign last held_out_count points to held_out, rest to fit
        if len(parsed) - held_out_count < 4:
            raise ValueError(
                f"Held-out count ({held_out_count}) leaves fewer than 4 fit points from {len(parsed)} points"
            )
        fit_points = [
            CalibrationPoint(p.image_x, p.image_y, p.world_x, p.world_y, role="fit", calibration_point_id=p.calibration_point_id)
            for p in parsed[:-held_out_count]
        ]
        held_out_points = [
            CalibrationPoint(p.image_x, p.image_y, p.world_x, p.world_y, role="held_out", calibration_point_id=p.calibration_point_id)
            for p in parsed[-held_out_count:]
        ]

    if len(fit_points) < 4:
        raise ValueError(f"Planar homography requires at least 4 fit points, got {len(fit_points)}")
    if len(held_out_points) < 1:
        raise ValueError(
            f"Validation requires at least 1 held-out point, got {len(held_out_points)}. "
            "Four points with no independent error check are strictly insufficient."
        )

    # Check for collinearity on fit points
    if is_collinear_or_degenerate(fit_points):
        raise ValueError("Degenerate point configuration: fit points are collinear or rank-deficient")

    return fit_points, held_out_points


def compute_homography(
    fit_points: Sequence[CalibrationPoint | dict[str, Any]],
) -> tuple[np.ndarray, np.ndarray]:
    """Compute 3x3 planar perspective homography matrix H (image -> world) and its inverse H_inv.

    Parameters:
        fit_points: Sequence of point correspondences with role 'fit' (at least 4 non-collinear).

    Returns:
        tuple (H, H_inv) where H maps image (u, v) -> world (X, Y) in metres,
        and H_inv maps world (X, Y) -> image (u, v) in pixels.

    Raises:
        ValueError: If homography computation fails or matrix is singular.
    """
    if len(fit_points) < 4:
        raise ValueError(f"At least 4 points required to compute homography, got {len(fit_points)}")

    src = np.array(
        [[float(p.image_x if isinstance(p, CalibrationPoint) else p["image_x"]),
          float(p.image_y if isinstance(p, CalibrationPoint) else p["image_y"])]
         for p in fit_points],
        dtype=np.float64,
    )
    dst = np.array(
        [[float(p.world_x if isinstance(p, CalibrationPoint) else p["world_x"]),
          float(p.world_y if isinstance(p, CalibrationPoint) else p["world_y"])]
         for p in fit_points],
        dtype=np.float64,
    )

    H, _ = cv2.findHomography(src, dst, method=0)
    if H is None or H.shape != (3, 3):
        raise ValueError("Homography estimation failed: degenerate point configuration")

    det = float(np.linalg.det(H))
    if not math.isfinite(det) or abs(det) < 1e-12:
        raise ValueError(f"Computed homography matrix is singular or near-singular (det={det})")

    # Invert H to map world -> image
    H_inv = np.linalg.inv(H)

    # Projective normalization: set H[2, 2] = 1.0 if non-zero
    if abs(H[2, 2]) > 1e-12:
        H = H / H[2, 2]
        H_inv = np.linalg.inv(H)
    if abs(H_inv[2, 2]) > 1e-12:
        H_inv = H_inv / H_inv[2, 2]

    return H, H_inv


def project_image_to_world(
    image_x: float,
    image_y: float,
    homography_matrix: np.ndarray | Sequence[Sequence[float]],
) -> tuple[float, float]:
    """Project 2D image coordinates (pixels) to ground world coordinates (metres).

    Parameters:
        image_x, image_y: Pixel coordinates on image canvas.
        homography_matrix: 3x3 homography matrix H.

    Returns:
        (world_x, world_y) in metres.

    Raises:
        ValueError: If coordinates are non-finite or point projects to infinity.
    """
    if not (math.isfinite(image_x) and math.isfinite(image_y)):
        raise ValueError(f"Image coordinates must be finite, got ({image_x}, {image_y})")

    H = np.asarray(homography_matrix, dtype=np.float64)
    if H.shape != (3, 3):
        raise ValueError(f"Homography matrix must be 3x3, got {H.shape}")

    vec = np.array([image_x, image_y, 1.0], dtype=np.float64)
    proj = H @ vec
    w = float(proj[2])
    if abs(w) < 1e-12:
        raise ValueError(f"Point ({image_x}, {image_y}) projects to infinity on ground plane (w={w})")

    return float(proj[0] / w), float(proj[1] / w)


def project_world_to_image(
    world_x: float,
    world_y: float,
    inverse_homography_matrix: np.ndarray | Sequence[Sequence[float]],
) -> tuple[float, float]:
    """Project 2D ground world coordinates (metres) to image coordinates (pixels).

    Parameters:
        world_x, world_y: Ground plane coordinates in metres.
        inverse_homography_matrix: 3x3 inverse homography matrix H_inv.

    Returns:
        (image_x, image_y) in pixels.

    Raises:
        ValueError: If coordinates are non-finite or point projects to infinity.
    """
    if not (math.isfinite(world_x) and math.isfinite(world_y)):
        raise ValueError(f"World coordinates must be finite, got ({world_x}, {world_y})")

    H_inv = np.asarray(inverse_homography_matrix, dtype=np.float64)
    if H_inv.shape != (3, 3):
        raise ValueError(f"Inverse homography matrix must be 3x3, got {H_inv.shape}")

    vec = np.array([world_x, world_y, 1.0], dtype=np.float64)
    proj = H_inv @ vec
    w = float(proj[2])
    if abs(w) < 1e-12:
        raise ValueError(f"World point ({world_x}, {world_y}) projects to infinity in image space (w={w})")

    return float(proj[0] / w), float(proj[1] / w)


def project_points_image_to_world(
    points: np.ndarray,
    homography_matrix: np.ndarray | Sequence[Sequence[float]],
) -> np.ndarray:
    """Batch project Nx2 image points to Nx2 world coordinates in metres."""
    if len(points) == 0:
        return np.empty((0, 2), dtype=np.float64)
    arr = np.asarray(points, dtype=np.float64)
    if arr.ndim != 2 or arr.shape[1] != 2:
        raise ValueError(f"Expected Nx2 array of points, got shape {arr.shape}")
    H = np.asarray(homography_matrix, dtype=np.float64)
    ones = np.ones((len(arr), 1), dtype=np.float64)
    homogeneous = np.hstack([arr, ones])  # Nx3
    projected = (H @ homogeneous.T).T      # Nx3
    w = projected[:, 2:3]
    if np.any(np.abs(w) < 1e-12):
        raise ValueError("One or more points project to infinity on the ground plane")
    return projected[:, :2] / w


def compute_reprojection_errors(
    points: Sequence[CalibrationPoint | dict[str, Any]],
    homography_matrix: np.ndarray | Sequence[Sequence[float]],
) -> list[float]:
    """Compute Euclidean reprojection error in metres for each point correspondence.

    For each point (image_x, image_y, world_x, world_y):
        (hat_X, hat_Y) = project_image_to_world(image_x, image_y, H)
        error = sqrt((hat_X - world_x)^2 + (hat_Y - world_y)^2)
    """
    errors: list[float] = []
    for p in points:
        img_x = float(p.image_x if isinstance(p, CalibrationPoint) else p["image_x"])
        img_y = float(p.image_y if isinstance(p, CalibrationPoint) else p["image_y"])
        w_x = float(p.world_x if isinstance(p, CalibrationPoint) else p["world_x"])
        w_y = float(p.world_y if isinstance(p, CalibrationPoint) else p["world_y"])

        hat_x, hat_y = project_image_to_world(img_x, img_y, homography_matrix)
        err = math.hypot(hat_x - w_x, hat_y - w_y)
        errors.append(float(err))
    return errors


def calibrate_camera(
    points: Sequence[dict[str, Any] | CalibrationPoint],
    config: Mapping[str, Any] | None = None,
) -> CalibrationResult:
    """Execute complete planar homography calibration with held-out error diagnostics.

    Parameters:
        points: Sequence of point correspondences (dict or CalibrationPoint).
        config: Optional configuration dictionary containing 'calibration' section.

    Returns:
        CalibrationResult containing matrices, error metrics, acceptance status,
        and JSON parameters.

    Raises:
        ValueError: If points are insufficient, non-finite, collinear, or degenerate.
    """
    calib_cfg = config.get("calibration", {}) if config else {}
    min_points = int(calib_cfg.get("min_points", 6))
    held_out_count = int(calib_cfg.get("held_out_count", 2))
    max_reprojection_error_m = float(calib_cfg.get("max_reprojection_error_m", 1.0))
    distortion_checked = bool(calib_cfg.get("distortion_check_enabled", False))
    flat_road_assumption = bool(calib_cfg.get("flat_road_assumption", True))
    coordinate_unit = str(calib_cfg.get("coordinate_unit", "meter"))

    # Validate and partition points
    fit_points, held_out_points = validate_calibration_points(
        points, min_points=min_points, held_out_count=held_out_count
    )

    # Estimate homography on fit points only
    H, H_inv = compute_homography(fit_points)

    # Compute errors on fit points (diagnostics)
    fit_errors = compute_reprojection_errors(fit_points, H)
    fit_mean = float(np.mean(fit_errors)) if fit_errors else 0.0
    fit_max = float(np.max(fit_errors)) if fit_errors else 0.0

    # Compute errors on held-out test points (validation)
    held_out_errors = compute_reprojection_errors(held_out_points, H)
    held_out_mean = float(np.mean(held_out_errors)) if held_out_errors else 0.0
    held_out_max = float(np.max(held_out_errors)) if held_out_errors else 0.0

    # Acceptance criterion: maximum held-out error must not exceed configured threshold
    accepted = bool(held_out_max <= max_reprojection_error_m)

    # Build annotated points list
    point_records: list[dict[str, Any]] = []
    for pt, err in zip(fit_points, fit_errors):
        point_records.append({
            "image_x": pt.image_x,
            "image_y": pt.image_y,
            "world_x": pt.world_x,
            "world_y": pt.world_y,
            "role": "fit",
            "reprojection_error_m": err,
            "calibration_point_id": pt.calibration_point_id or str(uuid4()),
        })
    for pt, err in zip(held_out_points, held_out_errors):
        point_records.append({
            "image_x": pt.image_x,
            "image_y": pt.image_y,
            "world_x": pt.world_x,
            "world_y": pt.world_y,
            "role": "held_out",
            "reprojection_error_m": err,
            "calibration_point_id": pt.calibration_point_id or str(uuid4()),
        })

    parameters: dict[str, Any] = {
        "homography_matrix": H.tolist(),
        "inverse_homography_matrix": H_inv.tolist(),
        "coordinate_unit": coordinate_unit,
        "fit_point_count": len(fit_points),
        "held_out_point_count": len(held_out_points),
        "fit_reprojection_error_m_mean": fit_mean,
        "fit_reprojection_error_m_max": fit_max,
        "held_out_reprojection_error_m_mean": held_out_mean,
        "held_out_reprojection_error_m_max": held_out_max,
        "max_reprojection_error_threshold_m": max_reprojection_error_m,
        "accepted": accepted,
        "distortion_checked": distortion_checked,
        "flat_road_assumption": flat_road_assumption,
    }
    parameters_json = json.dumps(parameters, sort_keys=True, separators=(",", ":"), ensure_ascii=False)

    return CalibrationResult(
        calibration_id=str(uuid4()),
        method="planar_homography",
        homography_matrix=H.tolist(),
        inverse_homography_matrix=H_inv.tolist(),
        point_count=len(point_records),
        held_out_point_count=len(held_out_points),
        reprojection_error_m_mean=held_out_mean,
        reprojection_error_m_max=held_out_max,
        fit_reprojection_error_m_mean=fit_mean,
        fit_reprojection_error_m_max=fit_max,
        accepted=accepted,
        distortion_checked=distortion_checked,
        flat_road_assumption=flat_road_assumption,
        points=point_records,
        parameters=parameters,
        parameters_json=parameters_json,
    )
