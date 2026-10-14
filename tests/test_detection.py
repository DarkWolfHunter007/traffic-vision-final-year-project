import numpy as np
import pytest

from backend.detection import DetectionError, RawDetection, crop_image, generate_tiles, map_detection, merge_tile_detections, validate_roi_crop


def detection(*, label: str = "car", confidence: float = 0.9, x1: float = 0, y1: float = 0, x2: float = 10, y2: float = 10) -> RawDetection:
    return RawDetection(2, label, confidence, x1, y1, x2, y2)


def test_mapping_requires_explicit_project_class() -> None:
    mapped = map_detection(detection(), {"car": "car"})
    assert mapped.class_name == "car"
    assert mapped.ground_x == 5
    assert mapped.ground_y == 10
    with pytest.raises(DetectionError):
        map_detection(detection(label="auto_rickshaw"), {"car": "car"})


def test_tile_generation_covers_frame_edges_deterministically() -> None:
    tiles = generate_tiles(100, 60, 40, 40, 0.25)
    assert tiles[0].x == 0 and tiles[0].y == 0
    assert any(tile.x + tile.width == 100 for tile in tiles)
    assert any(tile.y + tile.height == 60 for tile in tiles)


def test_tile_merge_is_class_aware_and_deterministic() -> None:
    duplicates = [detection(confidence=0.7), detection(confidence=0.9, x1=1, y1=1, x2=11, y2=11)]
    merged = merge_tile_detections(duplicates, 0.5)
    assert merged == [duplicates[1]]
    different_class = RawDetection(3, "motorcycle", 0.8, 1, 1, 11, 11)
    assert len(merge_tile_detections(duplicates + [different_class], 0.5)) == 2


def test_roi_crop_validates_and_preserves_offsets() -> None:
    image = np.zeros((20, 30, 3), dtype=np.uint8)
    roi = validate_roi_crop([5, 4, 20, 15], image.shape[1], image.shape[0])
    cropped, x_offset, y_offset = crop_image(image, roi)
    assert cropped.shape == (11, 15, 3)
    assert (x_offset, y_offset) == (5, 4)
    with pytest.raises(DetectionError):
        validate_roi_crop([5, 4, 40, 15], image.shape[1], image.shape[0])


def test_ignored_raw_classes_config_validation() -> None:
    from backend.config import ConfigError, load_config

    assert load_config()["detection"]["ignored_raw_classes"] == []
    ok = load_config(overrides={"detection": {"class_mapping": {"car": "car"}, "ignored_raw_classes": ["person"]}})
    assert ok["detection"]["ignored_raw_classes"] == ["person"]
    for bad in ("person", [""], [1], ["  "]):
        with pytest.raises(ConfigError, match="ignored_raw_classes"):
            load_config(overrides={"detection": {"ignored_raw_classes": bad}})
    with pytest.raises(ConfigError, match="overlap"):
        load_config(overrides={"detection": {"class_mapping": {"car": "car"}, "ignored_raw_classes": ["car"]}})


def test_detect_image_ignores_listed_labels_and_counts() -> None:
    import numpy as np

    from backend.config import load_config
    from backend.services.detection import detect_image

    class Det:
        def predict(self, image, *, confidence, iou, image_size):
            return [detection(label="car"), detection(label="person"), detection(label="person", x1=50, x2=60)]

    config = load_config(overrides={"detection": {"class_mapping": {"car": "car"}, "ignored_raw_classes": ["person"]}})
    counts: dict[str, int] = {}
    result = detect_image(np.zeros((24, 32, 3), dtype=np.uint8), config, Det(), counts)
    assert [d.class_name for d in result] == ["car"]
    assert counts == {"person": 2}
    strict = load_config(overrides={"detection": {"class_mapping": {"car": "car"}}})
    with pytest.raises(DetectionError):
        detect_image(np.zeros((24, 32, 3), dtype=np.uint8), strict, Det())
