"""Click-to-calibrate helpers (src/pattom/graph/calibration.py). Files go to tmp_path."""

import pytest
import yaml

from pattom.counting import load_lines
from pattom.graph import calibration as calib
from pattom.ground import GroundCalibration

# A 3 m x 4 m rectangle seen as 100 px per metre, so distances are easy to check.
RECT = [([100, 100], [0, 0]), ([400, 100], [3, 0]), ([400, 500], [3, 4]), ([100, 500], [0, 4])]


def mapping(check_m=2.0):
    return {
        "name": "all",
        "zone_px": [[0, 0], [600, 0], [600, 700], [0, 700]],
        "points": [{"id": f"Z{i + 1}", "px": px, "m": m, "role": "fit"} for i, (px, m) in enumerate(RECT)],
        "check_distances": [{"a_px": [100, 200], "b_px": [300, 200], "distance_m": check_m}],
    }


@pytest.fixture
def files(tmp_path, monkeypatch):
    for name, rel in [("GROUND_FILE", "calibration/ground.yaml"), ("LINES_FILE", "configs/lines.yaml"),
                      ("DEFINITIONS_FILE", "configs/definitions.yaml"), ("INDICATORS_FILE", "configs/indicators.yaml")]:
        p = tmp_path / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        monkeypatch.setattr(calib, name, p)
    return tmp_path


def test_check_reports_error_in_metres():
    r = calib.check_ground(mapping(check_m=2.5))
    assert r["fit_points"] == 4
    assert r["max_check_error_m"] == pytest.approx(0.5, abs=1e-3)


def test_check_needs_a_tape_check():
    m = mapping()
    m["check_distances"] = []
    with pytest.raises(calib.CalibrationError, match="check"):
        calib.check_ground(m)


def test_missing_metres_is_refused():
    m = mapping()
    m["points"][0]["m"] = [None, 0]
    with pytest.raises(calib.CalibrationError, match="metres"):
        calib.check_ground(m)


def test_measure_reads_through_saved_mapping(files):
    with pytest.raises(calib.CalibrationError, match="ground points first"):
        calib.measure([100, 100], [400, 100])
    calib.save_ground({"mapping": mapping()})
    r = calib.measure([100, 100], [400, 100])
    assert r["distance_m"] == pytest.approx(3.0)
    assert r["value_type"] == "derived"


def test_measure_refuses_points_outside_valid_area(files):
    calib.save_ground({"mapping": mapping()})
    with pytest.raises(calib.CalibrationError, match="outside the valid area"):
        calib.measure([100, 100], [650, 100])


def test_saved_ground_loads_with_project_code(files):
    calib.save_ground({"mapping": mapping()})
    cal = GroundCalibration.from_config(files / "calibration/ground.yaml")
    assert cal.locate(400, 500) == pytest.approx((3.0, 4.0))


def test_lines_save_keeps_valid_movements_only(files):
    (files / "configs/lines.yaml").write_text(yaml.safe_dump({"lines": [], "movements": [
        {"approach": "north", "movement": "through", "entry_line": "N_stop", "exit_line": "S_exit"},
        {"approach": "north", "movement": "left", "entry_line": "N_stop", "exit_line": "gone"}]}), encoding="utf-8")
    line = {"type": "stop_line", "approach": "north", "endpoints_px": [[0, 0], [10, 0]], "direction": "left"}
    r = calib.save_lines({"lines": [dict(line, name="N_stop"), dict(line, name="S_exit")]})
    assert (r["movements_kept"], r["movements_dropped"]) == (1, 1)
    lines, moves = load_lines(files / "configs/lines.yaml")
    assert set(lines) == {"N_stop", "S_exit"} and len(moves) == 1


def test_duplicate_line_name_refused(files):
    line = {"name": "A", "type": "arrival", "approach": "north", "endpoints_px": [[0, 0], [1, 1]], "direction": "left"}
    with pytest.raises(calib.CalibrationError):
        calib.save_lines({"lines": [line, line]})


def test_zones_need_ground_first(files):
    with pytest.raises(calib.CalibrationError, match="ground"):
        calib.save_zones({"approaches": {"north": {"zone_px": [[0, 0], [1, 0], [1, 1]], "stop_point_px": [0, 0]}}})


def test_zone_stop_point_in_metres(files):
    calib.save_ground({"mapping": mapping()})
    (files / "configs/definitions.yaml").write_text("# header kept\napproved: false\n", encoding="utf-8")
    calib.save_zones({"approaches": {"north": {"zone_px": [[100, 100], [400, 100], [400, 500]],
                                               "stop_point_px": [400, 500], "signal_head": "N"}}})
    text = (files / "configs/definitions.yaml").read_text(encoding="utf-8")
    data = yaml.safe_load(text)
    assert text.startswith("# header kept")
    assert data["approved"] is False
    assert data["approaches"]["north"]["stop_point_m"] == [3.0, 4.0]
    assert data["approaches"]["north"]["stop_point_px"] == [400.0, 500.0]


def test_zone_needs_signal_head_and_inside_stop_point(files):
    calib.save_ground({"mapping": mapping()})
    zone = [[100, 100], [400, 100], [400, 500]]
    with pytest.raises(calib.CalibrationError, match="signal head"):
        calib.save_zones({"approaches": {"north": {"zone_px": zone, "stop_point_px": [400, 500]}}})
    with pytest.raises(calib.CalibrationError, match="outside"):
        calib.save_zones({"approaches": {"north": {"zone_px": zone, "stop_point_px": [650, 500], "signal_head": "N"}}})


def test_regrounding_recomputes_or_clears_stop_points(files):
    calib.save_ground({"mapping": mapping()})
    zone = [[100, 100], [400, 100], [400, 500]]
    calib.save_zones({"approaches": {"north": {"zone_px": zone, "stop_point_px": [400, 500], "signal_head": "N"},
                                     "south": {"zone_px": zone, "stop_point_px": [550, 650], "signal_head": "S"}}})
    # Same rectangle clicked from the opposite corner: the origin moves, and the valid area shrinks.
    m = mapping()
    for p, new in zip(m["points"], [[3, 4], [0, 4], [0, 0], [3, 0]]):
        p["m"] = new
    m["zone_px"] = [[0, 0], [500, 0], [500, 600], [0, 600]]
    r = calib.save_ground({"mapping": m})
    assert r["stop_points"]["north"] == "updated"
    assert r["stop_points"]["south"].startswith("cleared")
    apps = yaml.safe_load((files / "configs/definitions.yaml").read_text(encoding="utf-8"))["approaches"]
    assert apps["north"]["stop_point_m"] == [0.0, 0.0]
    assert apps["south"]["stop_point_m"] is None


def test_template_ground_is_not_used(files, monkeypatch):
    example = files / "calibration/ground.example.yaml"
    example.write_text(yaml.safe_dump({"mappings": {"all": calib.clean_ground_spec(mapping())}}), encoding="utf-8")
    (files / "calibration/ground.yaml").write_text(example.read_text(encoding="utf-8"), encoding="utf-8")
    with pytest.raises(calib.CalibrationError, match="ground points first"):
        calib.measure([100, 100], [400, 100])


def test_width_saved_without_touching_other_keys(files):
    (files / "configs/indicators.yaml").write_text(
        "# keep me\npcu_table: table_3_1\napproaches:\n  north: {width_m: null, gradient_pct: 0.0, signal_head: N}\n",
        encoding="utf-8")
    calib.save_width("north", 7.25, "measured")
    data = yaml.safe_load((files / "configs/indicators.yaml").read_text(encoding="utf-8"))
    assert data["pcu_table"] == "table_3_1"
    assert data["approaches"]["north"] == {"width_m": 7.25, "gradient_pct": 0.0, "signal_head": "N",
                                           "width_value_type": "measured"}
    assert (files / "configs/indicators.yaml.bak").read_text(encoding="utf-8").startswith("# keep me")


def test_derived_width_keeps_its_label(files):
    calib.save_ground({"mapping": mapping()})
    r = calib.save_width("east", 3.0, "derived", 0.1)
    assert r["warning"]
    entry = yaml.safe_load((files / "configs/indicators.yaml").read_text(encoding="utf-8"))["approaches"]["east"]
    assert entry["width_value_type"] == "derived" and entry["width_check_error_m"] == 0.1
