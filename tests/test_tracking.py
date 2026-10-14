import pytest

from backend.detection import Detection
from backend.tracking import (
    ByteTrackerAdapter,
    DetectionBatch,
    TrackObservation,
    TrackingError,
    cadence_to_frames,
    evaluate_id_switches,
    resolve_track_class,
)


def make_detection(
    *,
    class_id: int = 2,
    class_name: str = "car",
    confidence: float = 0.9,
    x1: float = 10.0,
    y1: float = 10.0,
    x2: float = 50.0,
    y2: float = 50.0,
) -> Detection:
    return Detection(
        class_id=class_id,
        class_name=class_name,
        confidence=confidence,
        x1=x1,
        y1=y1,
        x2=x2,
        y2=y2,
    )


def test_cadence_to_frames_conversion() -> None:
    assert cadence_to_frames(1.0, 30.0, 1) == 30
    assert cadence_to_frames(1.0, 30.0, 2) == 15
    assert cadence_to_frames(2.0, 25.0, 1) == 50
    assert cadence_to_frames(0.5, 30.0, 3) == 5

    with pytest.raises(TrackingError, match="track_buffer_seconds"):
        cadence_to_frames(0.0, 30.0, 1)
    with pytest.raises(TrackingError, match="Nominal FPS"):
        cadence_to_frames(1.0, 0.0, 1)
    with pytest.raises(TrackingError, match="frame_stride"):
        cadence_to_frames(1.0, 30.0, 0)


def test_detection_batch_properties_and_slicing() -> None:
    batch = DetectionBatch(
        xyxy=[[10.0, 20.0, 30.0, 40.0], [50.0, 60.0, 70.0, 80.0]],
        conf=[0.9, 0.8],
        cls=[2, 3],
        class_names=["car", "bus"],
    )
    assert len(batch) == 2
    assert batch.xywh.shape == (2, 4)
    # Center x: (10+30)/2=20, center y: (20+40)/2=30, width: 20, height: 20
    assert batch.xywh[0].tolist() == [20.0, 30.0, 20.0, 20.0]

    sliced = batch[[True, False]]
    assert len(sliced) == 1
    assert sliced.class_names == ["car"]

    empty_batch = DetectionBatch([], [], [])
    assert len(empty_batch) == 0
    assert empty_batch.xywh.shape == (0, 4)


def test_persistent_id_association_across_frames() -> None:
    tracker = ByteTrackerAdapter(
        track_high_thresh=0.5,
        track_low_thresh=0.1,
        new_track_thresh=0.6,
        track_buffer_frames=10,
    )

    obs1 = tracker.update(1, 0.033, [make_detection(x1=10, y1=10, x2=50, y2=50)])
    assert len(obs1) == 1
    initial_id = obs1[0].track_id
    assert obs1[0].vehicle_class == "car"
    assert obs1[0].ground_x == 30.0
    assert obs1[0].ground_y == 50.0

    obs2 = tracker.update(2, 0.066, [make_detection(x1=12, y1=12, x2=52, y2=52)])
    assert len(obs2) == 1
    assert obs2[0].track_id == initial_id
    assert obs2[0].frame_number == 2

    obs3 = tracker.update(3, 0.099, [make_detection(x1=14, y1=14, x2=54, y2=54)])
    assert len(obs3) == 1
    assert obs3[0].track_id == initial_id

    metrics = tracker.metrics
    assert metrics.total_tracks >= 1
    assert metrics.total_observations == 3
    # id_switches is explicitly unmeasured (None) for unlabelled video
    assert metrics.id_switches is None


def test_empty_frame_handling() -> None:
    tracker = ByteTrackerAdapter()
    obs = tracker.update(1, 0.033, [])
    assert obs == []


def test_missed_detection_reconnection_within_buffer() -> None:
    tracker = ByteTrackerAdapter(
        track_high_thresh=0.5,
        track_low_thresh=0.1,
        new_track_thresh=0.6,
        track_buffer_frames=10,
    )

    obs1 = tracker.update(1, 0.033, [make_detection(x1=10, y1=10, x2=50, y2=50)])
    assert len(obs1) == 1
    initial_id = obs1[0].track_id

    # Temporary missed detection in frame 2
    obs2 = tracker.update(2, 0.066, [])
    assert len(obs2) == 0

    # Detection reappears in frame 3 with slight displacement
    obs3 = tracker.update(3, 0.099, [make_detection(x1=13, y1=13, x2=53, y2=53)])
    assert len(obs3) == 1
    assert obs3[0].track_id == initial_id


def test_evaluate_id_switches_known_switch_and_no_switch() -> None:
    # Known no-switch case: Two ground-truth vehicles maintain their respective tracks
    no_switch_assignments = [
        (1, 101, 1),  # frame 1: GT 101 -> Track 1
        (1, 102, 2),  # frame 1: GT 102 -> Track 2
        (2, 101, 1),  # frame 2: GT 101 -> Track 1
        (2, 102, 2),  # frame 2: GT 102 -> Track 2
        (3, 101, 1),  # frame 3: GT 101 -> Track 1
        (3, 102, 2),  # frame 3: GT 102 -> Track 2
    ]
    assert evaluate_id_switches(no_switch_assignments) == 0

    # Known switch case: Two crossing vehicles swap assigned track IDs at frame 3
    switch_assignments = [
        (1, 101, 1),
        (1, 102, 2),
        (2, 101, 1),
        (2, 102, 2),
        (3, 101, 2),  # GT 101 switched from Track 1 to Track 2!
        (3, 102, 1),  # GT 102 switched from Track 2 to Track 1!
    ]
    assert evaluate_id_switches(switch_assignments) == 2

    # Missed detection case: GT 101 is missed at frame 2, reappears at frame 3 with same track ID
    missed_case = [
        (1, 101, 1),
        (1, 102, 2),
        (2, 102, 2),  # GT 101 missed in this frame
        (3, 101, 1),  # GT 101 reappears with Track 1
        (3, 102, 2),
    ]
    assert evaluate_id_switches(missed_case) == 0


def test_resolve_track_class_majority_voting_and_preservation() -> None:
    # Five 'car' observations (conf 0.9 each) and one 'truck' observation (conf 0.9)
    observations = [
        TrackObservation(1, 1, 0.0, "car", 0.9, 0, 0, 10, 10, 5, 10),
        TrackObservation(1, 2, 0.1, "car", 0.9, 0, 0, 10, 10, 5, 10),
        TrackObservation(1, 3, 0.2, "car", 0.9, 0, 0, 10, 10, 5, 10),
        TrackObservation(1, 4, 0.3, "car", 0.9, 0, 0, 10, 10, 5, 10),
        TrackObservation(1, 5, 0.4, "car", 0.9, 0, 0, 10, 10, 5, 10),
        TrackObservation(1, 6, 0.5, "truck", 0.9, 0, 0, 10, 10, 5, 10),
    ]

    resolved = resolve_track_class(observations)
    assert resolved == "car"
    # Raw per-frame observation classes remain completely intact and unmodified
    assert observations[5].vehicle_class == "truck"


def test_resolve_track_class_deterministic_tie_breaking() -> None:
    # Tied cumulative confidence: 'car' (0.8) vs 'auto_rickshaw' (0.8)
    obs = [
        TrackObservation(1, 1, 0.0, "car", 0.8, 0, 0, 10, 10, 5, 10),
        TrackObservation(1, 2, 0.1, "auto_rickshaw", 0.8, 0, 0, 10, 10, 5, 10),
    ]

    # Alphabetical tie breaker: 'auto_rickshaw' precedes 'car'
    res1 = resolve_track_class(obs)
    res2 = resolve_track_class(obs)
    assert res1 == "auto_rickshaw"
    assert res1 == res2


def test_resolve_track_class_empty_and_low_confidence() -> None:
    assert resolve_track_class([]) == "unknown"
    assert resolve_track_class([], fallback_class="unresolved") == "unresolved"

    low_conf_obs = [
        TrackObservation(1, 1, 0.0, "car", 0.2, 0, 0, 10, 10, 5, 10),
        TrackObservation(1, 2, 0.1, "bus", 0.25, 0, 0, 10, 10, 5, 10),
    ]
    # Filter with min_confidence=0.5 -> evidence is insufficient
    assert resolve_track_class(low_conf_obs, min_confidence=0.5) == "unknown"
