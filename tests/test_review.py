"""Unit tests for Phase 10 pure review logic and configuration validation.

Software fixture notice: Test fixtures are synthetic software fixtures for validating
invariants and error handling; they do not represent real-world CCTV footage validation.
"""

from __future__ import annotations

import math
import pytest

from backend.config import ConfigError, load_config
from backend.review import (
    ManualReview,
    ReviewBox,
    UncertaintyCandidate,
    compute_snippet_window,
    identify_uncertain_detections,
    identify_uncertain_tracks,
    validate_bounding_box,
    validate_class_label,
    validate_status_transition,
)


def test_tp10_01_uncertainty_candidate_selection_by_confidence_threshold() -> None:
    """TP10-01: Detections/tracks at or below threshold are flagged; items above are excluded."""
    # Synthetic software fixtures
    detections = [
        {"detection_id": "det_low1", "frame_number": 1, "timestamp_s": 0.1, "confidence": 0.25, "class_name": "car", "x1": 10, "y1": 10, "x2": 50, "y2": 50},
        {"detection_id": "det_high", "frame_number": 2, "timestamp_s": 0.2, "confidence": 0.85, "class_name": "bus", "x1": 20, "y1": 20, "x2": 80, "y2": 80},
        {"detection_id": "det_boundary", "frame_number": 3, "timestamp_s": 0.3, "confidence": 0.50, "class_name": "auto_rickshaw", "x1": 30, "y1": 30, "x2": 70, "y2": 70},
    ]

    candidates = identify_uncertain_detections(detections, confidence_threshold=0.50)
    assert len(candidates) == 2
    candidate_ids = {c.item_id for c in candidates}
    assert candidate_ids == {"det_low1", "det_boundary"}
    assert "det_high" not in candidate_ids


def test_tp10_02_custom_confidence_threshold_candidate_selection() -> None:
    """TP10-02: Providing custom threshold correctly overrides config default."""
    detections = [
        {"detection_id": "det_1", "frame_number": 1, "timestamp_s": 0.1, "confidence": 0.30, "class_name": "car", "x1": 10, "y1": 10, "x2": 50, "y2": 50},
        {"detection_id": "det_2", "frame_number": 2, "timestamp_s": 0.2, "confidence": 0.60, "class_name": "car", "x1": 10, "y1": 10, "x2": 50, "y2": 50},
        {"detection_id": "det_3", "frame_number": 3, "timestamp_s": 0.3, "confidence": 0.75, "class_name": "car", "x1": 10, "y1": 10, "x2": 50, "y2": 50},
    ]

    strict_cands = identify_uncertain_detections(detections, confidence_threshold=0.30)
    assert len(strict_cands) == 1
    assert strict_cands[0].item_id == "det_1"

    lenient_cands = identify_uncertain_detections(detections, confidence_threshold=0.70)
    assert len(lenient_cands) == 2
    assert {c.item_id for c in lenient_cands} == {"det_1", "det_2"}


def test_tp10_03_bounding_box_geometry_validation() -> None:
    """TP10-03: Valid in-frame box coordinates pass validation and are normalized as ReviewBox."""
    valid_box = {"x1": 100.5, "y1": 200.0, "x2": 300.25, "y2": 400.75}
    box = validate_bounding_box(valid_box, frame_width=1280, frame_height=720)
    assert isinstance(box, ReviewBox)
    assert box.x1 == 100.5
    assert box.y1 == 200.0
    assert box.x2 == 300.25
    assert box.y2 == 400.75
    assert box.width == 199.75
    assert box.height == 200.75
    assert box.area == 199.75 * 200.75
    assert box.to_dict() == {"x1": 100.5, "y1": 200.0, "x2": 300.25, "y2": 400.75}


def test_tp10_04_out_of_frame_bounding_box_rejection() -> None:
    """TP10-04: Coordinates extending outside [0, W] x [0, H] are strictly rejected."""
    # x2 beyond frame width
    with pytest.raises(ValueError, match="extends beyond frame width"):
        validate_bounding_box({"x1": 100, "y1": 100, "x2": 1300, "y2": 500}, frame_width=1280, frame_height=720)

    # y2 beyond frame height
    with pytest.raises(ValueError, match="extends beyond frame height"):
        validate_bounding_box({"x1": 100, "y1": 100, "x2": 500, "y2": 750}, frame_width=1280, frame_height=720)

    # Negative coordinates
    with pytest.raises(ValueError, match="cannot be negative"):
        validate_bounding_box({"x1": -10, "y1": 100, "x2": 200, "y2": 300}, frame_width=1280, frame_height=720)

    with pytest.raises(ValueError, match="cannot be negative"):
        validate_bounding_box({"x1": 50, "y1": -5, "x2": 200, "y2": 300}, frame_width=1280, frame_height=720)


def test_tp10_05_inverted_and_zero_area_bounding_box_rejection() -> None:
    """TP10-05: Inverted or zero-area bounding boxes and non-finite numbers are rejected."""
    # Inverted x
    with pytest.raises(ValueError, match="strictly less than x2"):
        validate_bounding_box({"x1": 300, "y1": 100, "x2": 200, "y2": 200})

    # Equal x (zero width)
    with pytest.raises(ValueError, match="strictly less than x2"):
        validate_bounding_box({"x1": 200, "y1": 100, "x2": 200, "y2": 200})

    # Inverted y
    with pytest.raises(ValueError, match="strictly less than y2"):
        validate_bounding_box({"x1": 100, "y1": 400, "x2": 200, "y2": 300})

    # Equal y (zero height)
    with pytest.raises(ValueError, match="strictly less than y2"):
        validate_bounding_box({"x1": 100, "y1": 300, "x2": 200, "y2": 300})

    # Non-finite coordinates
    with pytest.raises(ValueError, match="finite real number"):
        validate_bounding_box({"x1": float("nan"), "y1": 100, "x2": 200, "y2": 300})

    with pytest.raises(ValueError, match="finite real number"):
        validate_bounding_box({"x1": 100, "y1": 100, "x2": float("inf"), "y2": 300})


def test_tp10_06_allowed_vehicle_class_validation() -> None:
    """TP10-06: Valid classes from allowed_classes are accepted; unknown classes rejected."""
    allowed = ["car", "bus", "truck", "motorcycle", "auto_rickshaw"]
    assert validate_class_label("car", allowed_classes=allowed) == "car"
    assert validate_class_label("auto_rickshaw", allowed_classes=allowed) == "auto_rickshaw"
    assert validate_class_label(None, allowed_classes=allowed) is None

    with pytest.raises(ValueError, match="not allowed"):
        validate_class_label("airplane", allowed_classes=allowed)

    with pytest.raises(ValueError, match="non-empty string"):
        validate_class_label("", allowed_classes=allowed)


def test_tp10_07_preservation_of_original_predictions() -> None:
    """TP10-07: Original predictions and candidate formats retain geometry and classes."""
    box = ReviewBox(x1=50.0, y1=60.0, x2=150.0, y2=200.0)
    cand = UncertaintyCandidate(
        candidate_id="cand_1",
        source_type="detection",
        item_id="det_123",
        track_id=None,
        frame_number=42,
        timestamp_s=1.4,
        predicted_class="motorcycle",
        confidence=0.35,
        bbox=box,
        reason="low_confidence",
    )
    d = cand.to_dict()
    assert d["candidate_id"] == "cand_1"
    assert d["source_type"] == "detection"
    assert d["item_id"] == "det_123"
    assert d["confidence"] == 0.35
    assert d["predicted_class"] == "motorcycle"
    assert d["bbox"] == {"x1": 50.0, "y1": 60.0, "x2": 150.0, "y2": 200.0}

    rev = ManualReview(
        review_id="rev_1",
        run_id="run_1",
        video_id="vid_1",
        track_id=10,
        detection_id="det_123",
        frame_number=42,
        timestamp_s=1.4,
        original_class="motorcycle",
        corrected_class="auto_rickshaw",
        original_bbox_json=box.to_json(),
        corrected_bbox_json=ReviewBox(x1=48.0, y1=58.0, x2=152.0, y2=205.0).to_json(),
        reason="class_ambiguity",
        review_status="approved",
        reviewer="traffic_expert",
        reviewed_at="2026-10-14T00:00:00Z",
        snippet_path="/snippets/rev_1.mp4",
    )
    rev_dict = rev.to_dict()
    assert rev_dict["original_class"] == "motorcycle"
    assert rev_dict["corrected_class"] == "auto_rickshaw"
    assert rev_dict["review_status"] == "approved"
    assert rev_dict["reviewer"] == "traffic_expert"


def test_tp10_09_review_status_lifecycle_transitions() -> None:
    """TP10-09: Valid transitions between pending/approved/rejected succeed; invalid fail."""
    allowed = ("pending", "approved", "rejected")
    assert validate_status_transition("pending", "approved", allowed) == "approved"
    assert validate_status_transition("pending", "rejected", allowed) == "rejected"
    assert validate_status_transition("approved", "approved", allowed) == "approved"
    assert validate_status_transition(None, "pending", allowed) == "pending"

    with pytest.raises(ValueError, match="Invalid review status"):
        validate_status_transition("pending", "in_progress", allowed)


def test_tp10_10_snippet_temporal_boundary_clamping() -> None:
    """TP10-10: Temporal window [t - before, t + after] is clamped to [0, duration_s]."""
    # Event near start of video (t = 0.4s, before = 1.0s, after = 1.0s) -> clamped to 0.0s
    start, end = compute_snippet_window(0.4, duration_s=10.0, before_s=1.0, after_s=1.0)
    assert start == 0.0
    assert end == 1.4

    # Event near end of video (t = 9.5s, duration = 10.0s, after = 1.0s) -> clamped to 10.0s
    start, end = compute_snippet_window(9.5, duration_s=10.0, before_s=1.0, after_s=1.0)
    assert start == 8.5
    assert end == 10.0

    # Event in middle of video
    start, end = compute_snippet_window(5.0, duration_s=10.0, before_s=1.5, after_s=2.0)
    assert start == 3.5
    assert end == 7.0

    # Validation errors
    with pytest.raises(ValueError, match="non-negative"):
        compute_snippet_window(5.0, duration_s=10.0, before_s=-1.0)


def test_tp10_16_config_validation_enforces_review_parameters() -> None:
    """TP10-16: backend/config.py validates all review configuration keys and constraints."""
    base_cfg = load_config()
    assert "review" in base_cfg
    assert base_cfg["review"]["confidence_threshold"] == 0.50
    assert base_cfg["review"]["snippet_before_s"] == 1.0
    assert base_cfg["review"]["snippet_after_s"] == 1.0
    assert "car" in base_cfg["review"]["allowed_classes"]

    # Invalid confidence threshold
    with pytest.raises(ConfigError, match="review.confidence_threshold"):
        load_config(overrides={"review": {"confidence_threshold": 1.5}})

    # Invalid snippet duration
    with pytest.raises(ConfigError, match="review.snippet_before_s"):
        load_config(overrides={"review": {"snippet_before_s": -0.5}})

    # Invalid allowed classes
    with pytest.raises(ConfigError, match="review.allowed_classes"):
        load_config(overrides={"review": {"allowed_classes": "not_a_list"}})

    # Missing required review status
    with pytest.raises(ConfigError, match="review.review_statuses must include 'approved'"):
        load_config(overrides={"review": {"review_statuses": ["pending", "rejected"]}})


def test_identify_uncertain_tracks() -> None:
    """Tracks below threshold are flagged."""
    tracks = [
        {"track_observation_id": "trk_1", "track_id": 1, "frame_number": 1, "timestamp_s": 0.1, "confidence": 0.3, "vehicle_class": "car", "x1": 10, "y1": 10, "x2": 50, "y2": 50},
        {"track_observation_id": "trk_2", "track_id": 2, "frame_number": 1, "timestamp_s": 0.1, "confidence": 0.9, "vehicle_class": "car", "x1": 20, "y1": 20, "x2": 60, "y2": 60},
    ]
    candidates = identify_uncertain_tracks(tracks, confidence_threshold=0.5)
    assert len(candidates) == 1
    assert candidates[0].item_id == "trk_1"
    assert candidates[0].track_id == 1
