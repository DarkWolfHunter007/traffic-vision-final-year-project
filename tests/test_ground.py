import csv
import json

import cv2
import numpy as np
import pytest
import yaml

from pattom import ground

# A true homography from ground metres to pixels, used to make exact test points.
H_TRUE_INV = np.array([[40.0, 5.0, 100.0], [2.0, 30.0, 50.0], [0.0, 0.01, 1.0]])


def px_of(m):
    return cv2.perspectiveTransform(np.array([[m]], float), H_TRUE_INV)[0, 0].tolist()


def spec(check=True, dist=False, extra_fit=False):
    fit_m = [[0, 0], [10, 0], [10, 8], [0, 8]] + ([[5, 4]] if extra_fit else [])
    pts = [{"id": f"F{i}", "px": px_of(m), "m": m, "role": "fit"} for i, m in enumerate(fit_m)]
    if check:
        pts.append({"id": "C1", "px": px_of([3, 5]), "m": [3, 5], "role": "check"})
    s = {"zone_px": [px_of([-1, -1]), px_of([11, -1]), px_of([11, 9]), px_of([-1, 9])], "points": pts}
    if dist:
        s["check_distances"] = [{"a_px": px_of([0, 2]), "b_px": px_of([4, 2]), "distance_m": 4.0}]
    return s


def test_exact_points_give_near_zero_check_error():
    m = ground.fit_mapping("all", spec(dist=True))
    assert m.max_check_error_m < 1e-6
    assert m.check_distance_errors_m[0] < 1e-6


def test_check_is_required():
    with pytest.raises(ValueError, match="no check point"):
        ground.fit_mapping("all", spec(check=False))


def test_wrong_check_point_shows_error():
    s = spec()
    s["points"][-1]["m"] = [3.5, 5]  # tape measurement off by 0.5 m
    assert ground.fit_mapping("all", s).max_check_error_m == pytest.approx(0.5, abs=1e-6)


def test_points_outside_zone_get_no_ground_position(tmp_path):
    p = tmp_path / "ground.yaml"
    p.write_text(yaml.safe_dump({"mappings": {"all": spec()}}))
    cal = ground.GroundCalibration.from_config(p)
    x, y = cal.locate(*px_of([2, 3]))
    assert (x, y) == pytest.approx((2, 3))
    assert cal.locate(*px_of([30, 30])) is None


def test_map_tracks_fills_bottom_centre(tmp_path):
    p = tmp_path / "ground.yaml"
    p.write_text(yaml.safe_dump({"mappings": {"all": spec()}}))
    cal = ground.GroundCalibration.from_config(p)
    u, v = px_of([4, 4])
    tracks = tmp_path / "tracks.csv"
    with open(tracks, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["frame", "time_s", "track_id", "class", "confidence", "x1", "y1", "x2", "y2",
                    "ground_x_m", "ground_y_m"])
        w.writerow([0, 0, 1, "car", 0.9, u - 10, v - 20, u + 10, v, "", ""])
        w.writerow([0, 0, 2, "car", 0.9, 0, 0, 2, 2, "", ""])
    tracks.with_suffix(".run.json").write_text(json.dumps(
        {"slot": "t", "video_file": "v", "video_sha256": "x", "fps": 30, "width": 1, "height": 1}))
    out = ground.map_tracks(tracks, cal)
    assert out.name == "tracks_ground.csv"
    assert list(csv.DictReader(open(tracks)))[0]["ground_x_m"] == ""   # the tracker's file is untouched
    rows = list(csv.DictReader(open(out)))
    assert float(rows[0]["ground_x_m"]) == pytest.approx(4, abs=1e-3)
    assert rows[1]["ground_x_m"] == ""
    assert json.loads((tmp_path / "tracks_ground.run.json").read_text())["parameters"]["rows_mapped"] == 1


def test_drift_check_finds_shift():
    rng = np.random.default_rng(1)
    ref = (rng.random((200, 200)) * 255).astype(np.uint8)
    moved = np.roll(ref, (3, 4), axis=(0, 1))
    out = ground.drift_check([(0.0, ref), (10.0, moved)], ref, [{"id": "a", "box_px": [80, 80, 120, 120]}])
    assert out[0].max_shift_px == 0
    assert out[1].max_shift_px == pytest.approx(5.0)
