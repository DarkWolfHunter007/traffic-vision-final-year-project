import csv
import json

import numpy as np
import pytest

from pattom.tracking import ByteTracker, TrackerConfig, run_tracking

CFG = TrackerConfig(high_thresh=0.5, low_thresh=0.1, new_track_thresh=0.6, match_iou=0.2,
                    low_match_iou=0.5, track_buffer_s=1.0)


def _box(x):
    return [x, 50, x + 40, 80]


def test_two_vehicles_keep_their_ids():
    t = ByteTracker(CFG, fps=10)
    ids = []
    for f in range(20):
        out = t.update(f, np.array([_box(10 + 5 * f), _box(300 - 5 * f)]), np.array([0.9, 0.9]), ["car", "bus"])
        ids.append(dict((j, tid) for tid, j in out))
    assert all(d == ids[0] for d in ids[:12])  # same ids until the boxes meet
    assert len(set(ids[0].values())) == 2


def test_low_confidence_box_keeps_track_alive():
    t = ByteTracker(CFG, fps=10)
    seen = set()
    for f in range(15):
        score = 0.3 if 5 <= f < 9 else 0.9  # partly hidden for four frames
        for tid, _ in t.update(f, np.array([_box(10 + 4 * f)]), np.array([score]), ["car"]):
            seen.add(tid)
    assert seen == {1}


def test_track_survives_short_gap_and_drops_after_buffer():
    t = ByteTracker(CFG, fps=10)
    for f in range(5):
        t.update(f, np.array([_box(10 + 4 * f)]), np.array([0.9]), ["car"])
    for f in range(5, 8):  # 3 missed frames < 10-frame buffer
        t.update(f, np.zeros((0, 4)), np.array([]), [])
    out = t.update(8, np.array([_box(10 + 4 * 8)]), np.array([0.9]), ["car"])
    assert out == [(1, 0)]
    for f in range(9, 21):
        t.update(f, np.zeros((0, 4)), np.array([]), [])
    assert t.tracks == []


def test_run_tracking_files(tmp_path):
    det = tmp_path / "detections.csv"
    with open(det, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["frame", "time_s", "class", "raw_label", "confidence", "x1", "y1", "x2", "y2", "pass"])
        for step in range(10):
            frame = step * 2
            cls = "car" if step != 4 else "truck"
            w.writerow([frame, frame / 20, cls, cls, 0.9, *_box(10 + 5 * step), "full"])
    det.with_suffix(".run.json").write_text(json.dumps({
        "fps": 20, "parameters": {"frame_stride": 2}, "slot": "test", "video_file": "v.mp4",
        "video_sha256": "x", "width": 640, "height": 480, "model_name": "fake", "model_version": "0",
        "confidence_threshold": 0.1, "tiling_settings": None}))
    run_tracking(det, CFG)
    rows = list(csv.DictReader(open(tmp_path / "tracks.csv")))
    assert {r["track_id"] for r in rows} == {"1"} and len(rows) == 10
    summary = list(csv.DictReader(open(tmp_path / "track_summary.csv")))
    assert summary[0]["majority_class"] == "car"
    assert summary[0]["class_changes"] == "2"
    assert json.loads((tmp_path / "tracks.run.json").read_text())["tracker"] == "bytetrack"


def test_config_rejects_bad_thresholds(tmp_path):
    p = tmp_path / "t.yaml"
    p.write_text("high_thresh: 0.1\nlow_thresh: 0.5\nnew_track_thresh: 0.6\nmatch_iou: 0.2\n"
                 "low_match_iou: 0.5\ntrack_buffer_s: 1\n")
    with pytest.raises(ValueError):
        TrackerConfig.load(p)
