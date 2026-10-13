"""Focused unit tests for Phase 07 planar homography calibration logic.

Covers test plan criteria:
- TP7-01: Planar homography estimation maps points to ground-plane world coordinates.
- TP7-02: Held-out error calculation evaluates independent test points.
- TP7-03: Point count validation rejects fewer than configured min_points.
- TP7-04: Held-out partitioning enforces at least 4 fit points and held_out points.
- TP7-05: Collinear or degenerate point sets are detected and rejected.
- TP7-06: Calibration exceeding max_reprojection_error_m is rejected (accepted=False).
- TP7-07: Calibration within max_reprojection_error_m is accepted (accepted=True).
- TP7-10: Coordinate projection helpers project_image_to_world and project_world_to_image.
- TP7-12: Config validation for calibration options.

NOTE: All calibration points and coordinates in this file are synthetic
software test fixtures generated for deterministic testing; they are not
traffic measurements from Pattom Intersection or real-world survey data.
"""

from __future__ import annotations

import math
import cv2
import numpy as np
import pytest

from backend.calibration import (
    CalibrationPoint,
    are_points_collinear,
    calibrate_camera,
    compute_homography,
    compute_reprojection_errors,
    is_collinear_or_degenerate,
    project_image_to_world,
    project_points_image_to_world,
    project_world_to_image,
    three_points_collinear,
    validate_calibration_points,
)
from backend.config import ConfigError, load_config


# Software test fixture: synthetic ground-plane mapping
# Simulates a perspective view where image pixel trapezoid maps to world metres rectangle
SOFTWARE_FIXTURE_SRC_PTS = np.array(
    [
        [200.0, 500.0],  # Bottom-left image
        [600.0, 500.0],  # Bottom-right image
        [500.0, 200.0],  # Top-right image
        [300.0, 200.0],  # Top-left image
    ],
    dtype=np.float64,
)
SOFTWARE_FIXTURE_DST_PTS = np.array(
    [
        [0.0, 0.0],      # Bottom-left world (0m, 0m)
        [10.0, 0.0],     # Bottom-right world (10m, 0m)
        [10.0, 30.0],    # Top-right world (10m, 30m)
        [0.0, 30.0],     # Top-left world (0m, 30m)
    ],
    dtype=np.float64,
)
_SOFTWARE_H_TRUE, _ = cv2.findHomography(SOFTWARE_FIXTURE_SRC_PTS, SOFTWARE_FIXTURE_DST_PTS)
_SOFTWARE_H_INV_TRUE = np.linalg.inv(_SOFTWARE_H_TRUE)


def _generate_software_fixture_point(u: float, v: float, role: str = "fit") -> dict[str, float | str]:
    """Generate a consistent synthetic point correspondence using the true software homography."""
    vec = np.array([u, v, 1.0], dtype=np.float64)
    proj = _SOFTWARE_H_TRUE @ vec
    w = proj[2]
    return {
        "image_x": float(u),
        "image_y": float(v),
        "world_x": float(proj[0] / w),
        "world_y": float(proj[1] / w),
        "role": role,
    }


def get_six_software_fixture_points() -> list[dict[str, float | str]]:
    """Return 6 valid synthetic software test points: 4 fit and 2 held-out."""
    pts = [
        _generate_software_fixture_point(200.0, 500.0, role="fit"),
        _generate_software_fixture_point(600.0, 500.0, role="fit"),
        _generate_software_fixture_point(500.0, 200.0, role="fit"),
        _generate_software_fixture_point(300.0, 200.0, role="fit"),
        _generate_software_fixture_point(400.0, 350.0, role="held_out"),
        _generate_software_fixture_point(350.0, 420.0, role="held_out"),
    ]
    return pts


def test_tp7_01_planar_homography_estimation_near_zero_error() -> None:
    """TP7-01: Homography estimation on non-collinear points maps points with near-zero error."""
    points = get_six_software_fixture_points()
    fit_points, held_out_points = validate_calibration_points(points, min_points=6, held_out_count=2)

    H, H_inv = compute_homography(fit_points)
    assert H.shape == (3, 3)
    assert H_inv.shape == (3, 3)

    # Compute fit reprojection error
    fit_errors = compute_reprojection_errors(fit_points, H)
    assert len(fit_errors) == 4
    for err in fit_errors:
        assert err < 1e-4, f"Fit error {err} m exceeds numerical tolerance"


def test_tp7_02_held_out_error_evaluation() -> None:
    """TP7-02: Held-out test points are evaluated independently from fitting."""
    points = get_six_software_fixture_points()
    result = calibrate_camera(points)

    assert result.point_count == 6
    assert result.held_out_point_count == 2
    assert result.fit_reprojection_error_m_max < 1e-4
    assert result.reprojection_error_m_mean < 1e-4
    assert result.reprojection_error_m_max < 1e-4
    assert result.accepted is True


def test_tp7_03_point_count_validation_rejects_insufficient_points() -> None:
    """TP7-03: Point count validation rejects fewer than configured min_points (e.g. 4 or 5)."""
    six_pts = get_six_software_fixture_points()

    # 4 points
    four_pts = six_pts[:4]
    with pytest.raises(ValueError, match="at least 6 points are required"):
        validate_calibration_points(four_pts, min_points=6, held_out_count=2)

    # 5 points
    five_pts = six_pts[:5]
    with pytest.raises(ValueError, match="at least 6 points are required"):
        validate_calibration_points(five_pts, min_points=6, held_out_count=2)


def test_tp7_04_held_out_partitioning_and_role_handling() -> None:
    """TP7-04: Held-out partitioning enforces at least 4 fit points and supports role tags."""
    raw_pts = [
        {"image_x": 100.0, "image_y": 100.0, "world_x": 0.0, "world_y": 0.0},
        {"image_x": 200.0, "image_y": 100.0, "world_x": 10.0, "world_y": 0.0},
        {"image_x": 300.0, "image_y": 200.0, "world_x": 10.0, "world_y": 10.0},
        {"image_x": 100.0, "image_y": 200.0, "world_x": 0.0, "world_y": 10.0},
        {"image_x": 150.0, "image_y": 150.0, "world_x": 5.0, "world_y": 5.0},
        {"image_x": 180.0, "image_y": 170.0, "world_x": 7.0, "world_y": 6.0},
    ]

    # Without explicit roles: last 2 become held_out, first 4 become fit
    fit, held_out = validate_calibration_points(raw_pts, min_points=6, held_out_count=2)
    assert len(fit) == 4
    assert len(held_out) == 2
    assert all(p.role == "fit" for p in fit)
    assert all(p.role == "held_out" for p in held_out)

    # With explicit roles
    tagged_pts = [
        dict(p, role="held_out" if i in {0, 4} else "fit")
        for i, p in enumerate(raw_pts)
    ]
    fit2, held_out2 = validate_calibration_points(tagged_pts, min_points=6, held_out_count=2)
    assert len(fit2) == 4
    assert len(held_out2) == 2


def test_tp7_05_collinear_and_degenerate_points_rejected() -> None:
    """TP7-05: Collinear point sets are detected and rejected as degenerate."""
    # Line test helper
    line_pts = [(float(x), float(2 * x + 1)) for x in range(5)]
    assert are_points_collinear(line_pts) is True

    # 3 points collinear helper
    assert three_points_collinear((0.0, 0.0), (1.0, 1.0), (2.0, 2.0)) is True
    assert three_points_collinear((0.0, 0.0), (1.0, 1.0), (2.0, 5.0)) is False

    # 6 points where all fit points lie on a straight line y = 100
    collinear_pts = [
        {"image_x": float(100 + i * 50), "image_y": 100.0, "world_x": float(i * 5), "world_y": 0.0, "role": "fit"}
        for i in range(4)
    ] + [
        {"image_x": 250.0, "image_y": 300.0, "world_x": 5.0, "world_y": 10.0, "role": "held_out"},
        {"image_x": 350.0, "image_y": 300.0, "world_x": 10.0, "world_y": 10.0, "role": "held_out"},
    ]
    with pytest.raises(ValueError, match="collinear or rank-deficient"):
        validate_calibration_points(collinear_pts, min_points=6, held_out_count=2)


def test_tp7_06_calibration_exceeding_threshold_is_rejected() -> None:
    """TP7-06: Calibration with held-out error exceeding max_reprojection_error_m is accepted=False."""
    points = get_six_software_fixture_points()
    # Perturb the held-out world point by 5.0 metres
    points[4]["world_x"] = float(points[4]["world_x"]) + 5.0

    config = {"calibration": {"max_reprojection_error_m": 1.0}}
    result = calibrate_camera(points, config=config)

    assert result.accepted is False
    assert result.reprojection_error_m_max > 4.0
    assert result.parameters["accepted"] is False


def test_tp7_07_calibration_within_threshold_is_accepted() -> None:
    """TP7-07: Calibration with held-out error within threshold is accepted=True."""
    points = get_six_software_fixture_points()
    config = {"calibration": {"max_reprojection_error_m": 1.0}}
    result = calibrate_camera(points, config=config)

    assert result.accepted is True
    assert result.reprojection_error_m_max < 1.0
    assert result.parameters["accepted"] is True


def test_tp7_10_coordinate_projections_and_inversion() -> None:
    """TP7-10: project_image_to_world and project_world_to_image round-trip and validation."""
    points = get_six_software_fixture_points()
    result = calibrate_camera(points)

    H = result.homography_matrix
    H_inv = result.inverse_homography_matrix

    test_u, test_v = 420.0, 380.0
    wx, wy = project_image_to_world(test_u, test_v, H)
    recovered_u, recovered_v = project_world_to_image(wx, wy, H_inv)

    assert math.isclose(test_u, recovered_u, abs_tol=1e-3)
    assert math.isclose(test_v, recovered_v, abs_tol=1e-3)

    # Batch projection
    batch_img = np.array([[200.0, 500.0], [600.0, 500.0]], dtype=np.float64)
    batch_world = project_points_image_to_world(batch_img, H)
    assert batch_world.shape == (2, 2)
    assert math.isclose(batch_world[0, 0], 0.0, abs_tol=1e-3)
    assert math.isclose(batch_world[0, 1], 0.0, abs_tol=1e-3)

    # Non-finite coordinates raise ValueError
    with pytest.raises(ValueError, match="must be finite"):
        project_image_to_world(float("nan"), 100.0, H)
    with pytest.raises(ValueError, match="must be finite"):
        project_world_to_image(10.0, float("inf"), H_inv)


def test_tp7_12_config_validation_enforces_constraints() -> None:
    """TP7-12: Config validation enforces calibration constraints."""
    # Valid config
    valid = load_config(overrides={"calibration": {"min_points": 7, "held_out_count": 2}})
    assert valid["calibration"]["min_points"] == 7

    # min_points < 6 rejected
    with pytest.raises(ConfigError, match="calibration.min_points must be an integer >= 6"):
        load_config(overrides={"calibration": {"min_points": 5}})

    # held_out_count leaving fewer than 4 fit points rejected
    with pytest.raises(ConfigError, match="calibration fit points .* must be at least 4"):
        load_config(overrides={"calibration": {"min_points": 6, "held_out_count": 3}})

    # invalid method rejected
    with pytest.raises(ConfigError, match="calibration.method to be 'planar_homography'"):
        load_config(overrides={"calibration": {"method": "polynomial"}})

    # non-positive max error rejected
    with pytest.raises(ConfigError, match="calibration.max_reprojection_error_m must be a positive number"):
        load_config(overrides={"calibration": {"max_reprojection_error_m": 0.0}})

    # flat_road_assumption = False rejected
    with pytest.raises(ConfigError, match="calibration.flat_road_assumption to be True"):
        load_config(overrides={"calibration": {"flat_road_assumption": False}})
