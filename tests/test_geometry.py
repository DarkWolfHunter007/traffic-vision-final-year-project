"""Tests for Phase 05 pure geometry validation, hashing, and side-of-line utilities.

Software fixture notice: Test fixtures are synthetic software fixtures for validating
invariants and error handling; they do not represent real-world CCTV footage validation.
"""

from __future__ import annotations

import math
import pytest

from backend.geometry import (
    VALID_ZONE_TYPES,
    compute_config_version,
    compute_geometry_sha256,
    is_polygon_self_intersecting,
    point_line_cross_product,
    point_line_side,
    point_side_of_line,
    polygon_area,
    segments_intersect,
    side_of_line,
    validate_counting_line,
    validate_polygon,
    validate_zone,
)


def test_tp5_01_polygon_vertex_count_acceptance_and_rejection() -> None:
    """TP5-01: Polygon with >= 3 distinct vertices accepted; < 3 vertices rejected."""
    # 3 distinct vertices (triangle)
    triangle = [[10.0, 10.0], [50.0, 10.0], [30.0, 40.0]]
    pts = validate_polygon(triangle)
    assert len(pts) == 3
    assert pts == [(10.0, 10.0), (50.0, 10.0), (30.0, 40.0)]

    # 4 distinct vertices (quadrilateral)
    quad = [[0.0, 0.0], [100.0, 0.0], [100.0, 100.0], [0.0, 100.0]]
    pts_quad = validate_polygon(quad)
    assert len(pts_quad) == 4

    # Explicitly closed polygon (first == last) normalized by stripping closing point
    closed_quad = [[0.0, 0.0], [100.0, 0.0], [100.0, 100.0], [0.0, 100.0], [0.0, 0.0]]
    pts_closed = validate_polygon(closed_quad)
    assert len(pts_closed) == 4

    # Fewer than 3 vertices rejected
    with pytest.raises(ValueError, match="at least 3 distinct vertices"):
        validate_polygon([[10.0, 10.0], [20.0, 20.0]])

    with pytest.raises(ValueError, match="at least 3 distinct vertices"):
        validate_polygon([[10.0, 10.0]])

    with pytest.raises(ValueError, match="at least 3 distinct vertices"):
        validate_polygon([])

    # 3 points where 2 are duplicates (distinct < 3) rejected
    with pytest.raises(ValueError, match="at least 3 distinct vertices"):
        validate_polygon([[10.0, 10.0], [10.0, 10.0], [20.0, 20.0]])

    # 4 points with internal duplicate vertex rejected
    with pytest.raises(ValueError, match="duplicate vertices"):
        validate_polygon([[0.0, 0.0], [50.0, 0.0], [0.0, 0.0], [25.0, 50.0]])

    # Non-finite coordinates rejected
    with pytest.raises(ValueError, match="finite"):
        validate_polygon([[0.0, 0.0], [float("nan"), 10.0], [10.0, 10.0]])

    with pytest.raises(ValueError, match="finite"):
        validate_polygon([[0.0, 0.0], [float("inf"), 10.0], [10.0, 10.0]])


def test_tp5_02_polygon_self_intersection_and_zero_area_rejection() -> None:
    """TP5-02: Self-intersecting polygon rejected; zero-area polygon rejected."""
    # Self-intersecting hourglass/figure-8 polygon rejected
    hourglass = [[0.0, 0.0], [100.0, 100.0], [100.0, 0.0], [0.0, 100.0]]
    assert is_polygon_self_intersecting(hourglass) is True
    with pytest.raises(ValueError, match="self-intersecting"):
        validate_polygon(hourglass)

    # Self-crossing pentagram / star polygon rejected
    star = [
        [50.0, 0.0],
        [20.0, 100.0],
        [100.0, 35.0],
        [0.0, 35.0],
        [80.0, 100.0],
    ]
    assert is_polygon_self_intersecting(star) is True
    with pytest.raises(ValueError, match="self-intersecting"):
        validate_polygon(star)

    # Zero-area collinear vertices rejected
    collinear = [[0.0, 0.0], [50.0, 0.0], [100.0, 0.0]]
    assert polygon_area(collinear) == 0.0
    with pytest.raises(ValueError, match="zero area"):
        validate_polygon(collinear)

    # Coincident vertices with 0 area rejected
    coincident = [[50.0, 50.0], [50.0, 50.0], [50.0, 50.0]]
    with pytest.raises(ValueError, match="distinct vertices"):
        validate_polygon(coincident)

    # Simple valid polygon computes positive non-zero area
    square = [[0.0, 0.0], [10.0, 0.0], [10.0, 10.0], [0.0, 10.0]]
    assert polygon_area(square) == 100.0
    assert is_polygon_self_intersecting(square) is False


def test_tp5_03_counting_line_endpoint_validation() -> None:
    """TP5-03: Counting line with 2 distinct endpoints accepted; coincident or missing endpoints rejected."""
    # Valid line with 2 distinct endpoints
    pts, dir_vec = validate_counting_line(
        endpoints=[[10.0, 20.0], [30.0, 40.0]],
        direction_vector=[1.0, 0.0],
        bidirectional=False,
    )
    assert pts == [(10.0, 20.0), (30.0, 40.0)]
    assert dir_vec == (1.0, 0.0)

    # Coincident endpoints rejected
    with pytest.raises(ValueError, match="endpoints must be distinct"):
        validate_counting_line(
            endpoints=[[10.0, 20.0], [10.0, 20.0]],
            direction_vector=[1.0, 0.0],
            bidirectional=False,
        )

    # Only 1 endpoint rejected
    with pytest.raises(ValueError, match="exactly 2 distinct endpoints"):
        validate_counting_line(
            endpoints=[[10.0, 20.0]],
            direction_vector=[1.0, 0.0],
            bidirectional=False,
        )

    # 3 endpoints rejected
    with pytest.raises(ValueError, match="exactly 2 distinct endpoints"):
        validate_counting_line(
            endpoints=[[10.0, 20.0], [20.0, 30.0], [30.0, 40.0]],
            direction_vector=[1.0, 0.0],
            bidirectional=False,
        )

    # None / empty endpoints rejected
    with pytest.raises(ValueError, match="exactly 2 distinct endpoints"):
        validate_counting_line(endpoints=[], direction_vector=[1.0, 0.0], bidirectional=False)

    # Non-finite coordinates rejected
    with pytest.raises(ValueError, match="finite"):
        validate_counting_line(
            endpoints=[[float("nan"), 20.0], [30.0, 40.0]],
            direction_vector=[1.0, 0.0],
            bidirectional=False,
        )


def test_tp5_04_geometry_sha256_determinism_and_config_version() -> None:
    """TP5-04: geometry_sha256 is deterministic (canonical JSON of geometry + approach + name)
    and config_version is its first 12 hex characters.
    """
    geom_a = {"endpoints": [[10.0, 20.0], [30.0, 40.0]], "direction_vector": [0.0, 1.0]}
    approach_a = "north"
    name_a = "North Entry Line"

    sha1 = compute_geometry_sha256(geom_a, approach_a, name_a)
    sha2 = compute_geometry_sha256(geom_a, approach_a, name_a)
    assert sha1 == sha2
    assert len(sha1) == 64

    ver1 = compute_config_version(sha1)
    ver2 = compute_config_version(sha2)
    assert ver1 == sha1[:12]
    assert len(ver1) == 12
    assert ver1 == ver2

    # Changing geometry yields different hash and version
    geom_mod = {"endpoints": [[10.0, 20.0], [30.0, 50.0]], "direction_vector": [0.0, 1.0]}
    sha_mod_geom = compute_geometry_sha256(geom_mod, approach_a, name_a)
    assert sha_mod_geom != sha1
    assert compute_config_version(sha_mod_geom) != ver1

    # Changing approach yields different hash and version
    sha_mod_app = compute_geometry_sha256(geom_a, "south", name_a)
    assert sha_mod_app != sha1

    # Changing name yields different hash and version
    sha_mod_name = compute_geometry_sha256(geom_a, approach_a, "North Exit Line")
    assert sha_mod_name != sha1

    # Key ordering in input dict does not affect hash (canonical sorted-key JSON)
    geom_reversed_keys = {"direction_vector": [0.0, 1.0], "endpoints": [[10.0, 20.0], [30.0, 40.0]]}
    sha_rev = compute_geometry_sha256(geom_reversed_keys, approach_a, name_a)
    assert sha_rev == sha1


def test_tp5_07_bidirectional_and_unidirectional_line_rules() -> None:
    """TP5-07: Bidirectional line allows crossing without direction vector;
    unidirectional line requires direction vector and rejects missing/zero vector.
    """
    endpoints = [[100.0, 200.0], [300.0, 200.0]]

    # Bidirectional line with direction_vector=None accepted
    pts, d_vec = validate_counting_line(
        endpoints=endpoints,
        direction_vector=None,
        bidirectional=True,
    )
    assert pts == [(100.0, 200.0), (300.0, 200.0)]
    assert d_vec is None

    # Bidirectional line with non-null direction_vector rejected
    with pytest.raises(ValueError, match="must not specify a direction vector"):
        validate_counting_line(
            endpoints=endpoints,
            direction_vector=[0.0, 1.0],
            bidirectional=True,
        )

    # Unidirectional line with valid direction vector accepted
    pts_uni, d_vec_uni = validate_counting_line(
        endpoints=endpoints,
        direction_vector=[0.0, 1.0],
        bidirectional=False,
    )
    assert pts_uni == [(100.0, 200.0), (300.0, 200.0)]
    assert d_vec_uni == (0.0, 1.0)

    # Unidirectional line with missing direction vector rejected
    with pytest.raises(ValueError, match="requires a non-zero direction_vector"):
        validate_counting_line(
            endpoints=endpoints,
            direction_vector=None,
            bidirectional=False,
        )

    # Unidirectional line with zero direction vector [0, 0] rejected
    with pytest.raises(ValueError, match="must be non-zero"):
        validate_counting_line(
            endpoints=endpoints,
            direction_vector=[0.0, 0.0],
            bidirectional=False,
        )


def test_tp5_08_zone_type_application_validation() -> None:
    """TP5-08: Zone type validation in application code accepts only entry, exit, roi, queue;
    invalid strings rejected.
    """
    valid_vertices = [[0.0, 0.0], [50.0, 0.0], [50.0, 50.0], [0.0, 50.0]]
    declared = {"north", "south"}

    for z_type in ("entry", "exit", "roi", "queue"):
        app = "north" if z_type in ("entry", "exit") else None
        v_pts, v_type, v_app = validate_zone(
            vertices=valid_vertices,
            zone_type=z_type,
            approach=app,
            declared_approaches=declared,
        )
        assert v_type == z_type
        assert len(v_pts) == 4

    # Invalid zone types rejected
    for invalid in ("parking", "speed_trap", "staging", "corridor", ""):
        with pytest.raises(ValueError, match="Invalid zone_type"):
            validate_zone(
                vertices=valid_vertices,
                zone_type=invalid,
                approach="north",
                declared_approaches=declared,
            )


def test_side_of_line_helpers() -> None:
    """Test pure line-side helpers and cross products."""
    line_start = (0.0, 0.0)
    line_end = (10.0, 0.0)

    # In Cartesian (x right, y up), (5, 5) is left side (> 0)
    # Formula: (x2 - x1)*(y - y1) - (y2 - y1)*(x - x1) = 10 * 5 - 0 = 50
    assert point_line_cross_product((5.0, 5.0), line_start, line_end) == 50.0
    assert point_side_of_line((5.0, 5.0), line_start, line_end) == 1
    assert side_of_line((5.0, 5.0), line_start, line_end) == 1
    assert point_line_side((5.0, 5.0), line_start, line_end) == 1

    # (5, -5) is right side (< 0)
    assert point_line_cross_product((5.0, -5.0), line_start, line_end) == -50.0
    assert point_side_of_line((5.0, -5.0), line_start, line_end) == -1

    # Collinear point on line returns 0
    assert point_line_cross_product((5.0, 0.0), line_start, line_end) == 0.0
    assert point_side_of_line((5.0, 0.0), line_start, line_end) == 0

    # Vertical line test: line from (0, 0) to (0, 10)
    v_start = (0.0, 0.0)
    v_end = (0.0, 10.0)
    # (-5, 5): (0 - 0)*(5 - 0) - (10 - 0)*(-5 - 0) = +50 -> left side (+1)
    assert point_side_of_line((-5.0, 5.0), v_start, v_end) == 1
    # (5, 5): (0 - 0)*(5 - 0) - (10 - 0)*(5 - 0) = -50 -> right side (-1)
    assert point_side_of_line((5.0, 5.0), v_start, v_end) == -1
    # On vertical line:
    assert point_side_of_line((0.0, 5.0), v_start, v_end) == 0
