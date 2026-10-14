import csv
import json
import shutil
import subprocess
from collections import Counter

import numpy as np
import pytest
import yaml

from pattom import detection
from pattom.detection import DetectionConfig

needs_ffmpeg = pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg not installed")


def _cfg(**kw):
    base = dict(weights="models/x.pt", class_map={"car": "car", "motorcycle": "two_wheeler"},
                confidence_threshold=0.1, process_fps=10, ignore_labels=["person"])
    base.update(kw)
    return DetectionConfig(**base)


class FakeDetector:
    name = "fake"
    version = "0"

    def __init__(self, per_call):
        self.per_call = per_call
        self.calls = []

    def predict(self, image, imgsz):
        self.calls.append(image.shape)
        return self.per_call(image)


def test_unmapped_label_stops_the_run():
    with pytest.raises(ValueError, match="neither in class_map"):
        detection.map_labels([{"raw_label": "train"}], _cfg(), Counter())


def test_ignored_labels_are_counted_not_kept():
    ignored = Counter()
    out = detection.map_labels([{"raw_label": "person"}, {"raw_label": "car"}], _cfg(), ignored)
    assert [d["class"] for d in out] == ["car"]
    assert ignored == {"person": 1}


def test_tile_boxes_are_offset_and_merged():
    img = np.zeros((100, 200, 3), np.uint8)

    def predict(image):
        if image.shape[1] == 200:  # full frame: a weaker box for the same car
            return [(np.array([110, 20, 130, 40]), 0.4, "car")]
        return [(np.array([10, 10, 30, 30]), 0.9, "car")]  # tile at x=100, y=10

    dets = detection.detect_frame(img, _cfg(tiles=[[100, 10, 200, 100]]), FakeDetector(predict))
    assert len(dets) == 1
    assert dets[0]["pass"] == "tile0"
    assert list(dets[0]["xyxy"]) == [110, 20, 130, 40]


def test_weights_must_be_inside_models(tmp_path):
    with pytest.raises(ValueError, match="inside"):
        _cfg(weights=str(tmp_path / "x.pt")).weights_path()
    with pytest.raises(FileNotFoundError, match="nothing is downloaded"):
        _cfg(weights="models/does_not_exist.pt").weights_path()


def test_config_rejects_label_both_mapped_and_ignored(tmp_path):
    p = tmp_path / "d.yaml"
    p.write_text(yaml.safe_dump(dict(weights="models/x.pt", class_map={"car": "car"}, ignore_labels=["car"],
                                     confidence_threshold=0.1, process_fps=10)))
    with pytest.raises(ValueError, match="both mapped and ignored"):
        DetectionConfig.load(p)


@needs_ffmpeg
def test_run_detection_writes_csv_and_metadata(tmp_path):
    video = tmp_path / "v.mp4"
    subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "testsrc=size=64x48:rate=30:duration=1",
                    "-c:v", "libx264", "-pix_fmt", "yuv420p", str(video)], check=True)
    fake = FakeDetector(lambda img: [(np.array([1, 2, 11, 12]), 0.8, "car"), (np.array([0, 0, 5, 5]), 0.5, "person")])
    out = detection.run_detection(video, "test", _cfg(), detector=fake, out_dir=tmp_path / "run")
    rows = list(csv.DictReader(open(out)))
    assert len(rows) == 10  # 30 fps processed at 10 fps
    assert rows[1]["frame"] == "3" and float(rows[1]["time_s"]) == pytest.approx(0.1)
    meta = json.loads((tmp_path / "run" / "detections.run.json").read_text())
    assert meta["stage"] == "C.detection"
    assert meta["parameters"]["ignored_label_counts"] == {"person": 10}
