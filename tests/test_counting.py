import csv
import json

import pytest
import yaml

from pattom import counting
from pattom.counting import Line


def test_line_side_and_direction():
    line = Line("L", "stop_line", "north", (0, 0), (10, 0), "left")
    assert line.crossed((5, -2), (5, 2)) == "left->right"  # moving down crosses from left to right
    assert line.crossed((5, 2), (5, -2)) == "right->left"
    assert line.crossed((15, -2), (15, 2)) is None  # beyond the segment end
    assert line.counts("left->right") and not line.counts("right->left")


def _setup(tmp_path):
    lines = {
        "lines": [
            {"name": "N_stop", "type": "stop_line", "approach": "north", "endpoints_px": [[0, 100], [100, 100]],
             "direction": "left"},
            {"name": "S_exit", "type": "exit", "approach": "south", "endpoints_px": [[0, 200], [100, 200]],
             "direction": "left"},
            {"name": "E_exit", "type": "exit", "approach": "east", "endpoints_px": [[150, 0], [150, 300]],
             "direction": "right"},
        ],
        "movements": [
            {"approach": "north", "movement": "through", "entry_line": "N_stop", "exit_line": "S_exit"},
            {"approach": "north", "movement": "left", "entry_line": "N_stop", "exit_line": "E_exit"},
        ],
    }
    ly = tmp_path / "lines.yaml"
    ly.write_text(yaml.safe_dump(lines))
    tracks = tmp_path / "tracks.csv"
    with open(tracks, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["frame", "time_s", "track_id", "class", "confidence", "x1", "y1", "x2", "y2",
                    "ground_x_m", "ground_y_m"])
        # track 1 goes straight down (through); bottom centre = (x, y2)
        for i, y in enumerate([80, 120, 180, 220]):
            w.writerow([i, i * 1.0, 1, "car", 0.9, 40, y - 20, 60, y, "", ""])
        # track 2 crosses the stop line then turns to x>150 (crosses E_exit left->right when moving right?)
        for i, (x, y) in enumerate([(50, 80), (50, 120), (120, 150), (180, 150)]):
            w.writerow([i, 1000 + i * 1.0, 2, "truck", 0.9, x - 10, y - 20, x + 10, y, "", ""])
        # track 3 never crosses anything
        w.writerow([0, 5.0, 3, "car", 0.9, 0, 0, 10, 10, "", ""])
    with open(tmp_path / "track_summary.csv", "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["track_id", "majority_class"])
        w.writerows([[1, "car"], [2, "truck"], [3, "car"]])
    tracks.with_suffix(".run.json").write_text(json.dumps(
        {"slot": "peak", "video_file": "v", "video_sha256": "x", "fps": 30, "width": 1, "height": 1,
         "tracker": "bytetrack"}))
    return tracks, ly


def test_counting_end_to_end(tmp_path):
    tracks, ly = _setup(tmp_path)
    out = counting.run_counting(tracks, ly, interval_s=900)
    rows = list(csv.DictReader(open(out)))
    got = {(r["interval_start_s"], r["approach"], r["movement"], r["class"]): r["count"] for r in rows}
    assert got == {("0.0", "north", "through", "car"): "1", ("900.0", "north", "left", "truck"): "1"}
    assert all(r["value_type"] == "measured" for r in rows)
    crossings = list(csv.DictReader(open(tmp_path / "crossings.csv")))
    assert {c["line_name"] for c in crossings} == {"N_stop", "S_exit", "E_exit"}


def test_bad_line_config_rejected(tmp_path):
    p = tmp_path / "l.yaml"
    p.write_text(yaml.safe_dump({"lines": [{"name": "a", "type": "gate", "approach": "n",
                                            "endpoints_px": [[0, 0], [1, 1]], "direction": "left"}]}))
    with pytest.raises(ValueError, match="type must be"):
        counting.load_lines(p)
